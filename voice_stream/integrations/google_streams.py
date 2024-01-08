import dataclasses
import logging
from typing import AsyncIterator, Union

from google.api_core.exceptions import Aborted
from google.cloud.speech_v2 import (
    StreamingRecognizeRequest,
    StreamingRecognitionConfig,
    StreamingRecognitionFeatures,
    SpeechAsyncClient,
    StreamingRecognizeResponse,
    RecognitionConfig,
)

from google.cloud.speech_v1 import (
    SpeechAsyncClient as SpeechAsyncClientV1,
    StreamingRecognizeRequest as StreamingRecognizeRequestV1,
    StreamingRecognizeResponse as StreamingRecognizeResponseV1,
    StreamingRecognitionConfig as StreamingRecognitionConfigV1,
    RecognitionConfig as RecognitionConfigV1,
)


from google.cloud.texttospeech_v1 import (
    TextToSpeechAsyncClient,
    SynthesizeSpeechRequest,
    SynthesisInput,
    VoiceSelectionParams,
    AudioConfig,
    AudioEncoding,
)

from voice_stream.audio.audio_streams import remove_wav_header, AudioFormat
from voice_stream.basic_streams import (
    map_step,
    filter_step,
    array_source,
    concat_step,
    byte_buffer_step,
    chunk_bytes_step,
    exception_handler_step,
    partition_step,
    async_init_step,
)
from voice_stream.events import SpeechStart, SpeechEnd
from voice_stream.integrations.google_setup import (
    resolve_audio_decoding,
    GoogleDecodingConfig,
)
from voice_stream.text_to_speech_streams import AudioWithText

# Can be one of the standard audio formats or a Google AudioConfig object
GoogleAudioConfig = Union[AudioFormat, AudioConfig]

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TTSRequest:
    text: str
    voice: str


async def google_text_to_speech_step(
    async_iter: AsyncIterator[Union[str, TTSRequest]],
    text_to_speech_async_client: TextToSpeechAsyncClient,
    voice_name: str = "en-US-Standard-H",
    audio_format: GoogleAudioConfig = AudioFormat.OGG_OPUS,
) -> AsyncIterator[AudioWithText]:
    """Each text block that comes in is converted to audio using the desired voice and format.
    Can take either strings in, or a TTSRequest, which allows you to specify the voice.
    """
    audio_config = _resolve_google_audio_config(audio_format)

    async for item in async_iter:
        if isinstance(item, TTSRequest):
            voice = item.voice
            text = item.text
        else:
            voice = voice_name
            text = item
        # noinspection PyTypeChecker
        request = SynthesizeSpeechRequest(
            input=SynthesisInput(text=text),
            voice=VoiceSelectionParams(
                language_code="en-us",
                name=voice,
            ),
            audio_config=audio_config,
        )
        result = await text_to_speech_async_client.synthesize_speech(request)
        audio = result.audio_content
        if audio_config.audio_encoding == AudioEncoding.MULAW:
            audio = remove_wav_header(audio)
        yield AudioWithText(audio=audio, text=text, audio_format=audio_format)


def google_speech_step(
    async_iter: AsyncIterator[bytes],
    speech_async_client: SpeechAsyncClient,
    project,
    location,
    recognizer,
    model: str = "latest_long",
    language_codes: Union[str, list[str]] = ["en-US", "es-US"],
    audio_format: GoogleDecodingConfig = None,
    include_events: bool = False,
) -> AsyncIterator[str]:
    """Converts a stream of audio bytes into a stream of text.
    If include_events is True, a second stream will be returned containing speech events.
    """
    MAX_STREAM_SIZE = 25600
    pipe = async_iter
    # pipe = count_step(pipe, "pre")
    pipe = byte_buffer_step(pipe)
    pipe = chunk_bytes_step(pipe, MAX_STREAM_SIZE)
    # pipe = count_step(pipe, "post")
    pipe = map_step(
        pipe, lambda x: StreamingRecognizeRequest(recognizer=recognizer, audio=x)
    )
    config = array_source(
        [
            _initial_recognition_config(
                include_events,
                project,
                location,
                recognizer,
                model,
                language_codes,
                audio_format,
            )
        ]
    )
    pipe = concat_step(config, pipe)
    pipe = async_init_step(pipe, speech_async_client.streaming_recognize)
    pipe = exception_handler_step(
        pipe, Aborted, lambda x: logger.info("Google Recognize aborted.")
    )
    # pipe = filter_step(pipe, lambda x: x.results[0].is_final)
    # pipe = log_step(pipe, "google_speech")

    def get_transcript(result):
        if not result.results:
            logger.info("No results in google response")
            return ""
        if not result.results[0].alternatives:
            logger.info("No alternatives in google response")
            return ""
        return result.results[0].alternatives[0].transcript

    if include_events:
        pipe, events = partition_step(pipe, lambda x: x.results)
        # pipe = log_step(pipe, "google_partition")
    pipe = map_step(pipe, get_transcript)
    # pipe = log_step(pipe, "get_transcript")
    pipe = filter_step(pipe, lambda x: len(x) > 0)
    if include_events:
        events = map_step(events, _map_speech_events)
        events = filter_step(events, lambda x: x is not None)
        # pipe = log_step(pipe, "Google out")
        return pipe, events
    else:
        return pipe


def google_speech_v1_step(
    async_iter: AsyncIterator[bytes],
    speech_async_client: SpeechAsyncClientV1,
    audio_format: AudioFormat,
    model: str = "latest_long",
    language_code: str = "en-US",
    include_events: bool = False,
) -> AsyncIterator[str]:
    """Converts a stream of audio bytes into a stream of text.
    If include_events is True, a second stream will be returned containing speech events.
    """
    MAX_STREAM_SIZE = 25600
    pipe = async_iter
    pipe = byte_buffer_step(pipe)
    pipe = chunk_bytes_step(pipe, MAX_STREAM_SIZE)
    pipe = map_step(pipe, lambda x: StreamingRecognizeRequestV1(audio_content=x))
    config = array_source(
        [
            _initial_recognition_config_v1(
                include_events=include_events,
                model=model,
                language_code=language_code,
                audio_format=audio_format,
            )
        ]
    )
    pipe = concat_step(config, pipe)
    pipe = async_init_step(pipe, speech_async_client.streaming_recognize)
    pipe = exception_handler_step(
        pipe, Aborted, lambda x: logger.info("Google Recognize aborted.")
    )
    # pipe = filter_step(pipe, lambda x: x.results[0].is_final)
    # pipe = log_step(pipe, "google_speech")

    def get_transcript(result):
        if not result.results:
            logger.info("No results in google response")
            return ""
        if not result.results[0].alternatives:
            logger.info("No alternatives in google response")
            return ""
        return result.results[0].alternatives[0].transcript

    if include_events:
        pipe, events = partition_step(pipe, lambda x: x.results)
        # pipe = log_step(pipe, "google_partition")
    pipe = map_step(pipe, get_transcript)
    # pipe = log_step(pipe, "get_transcript")
    pipe = filter_step(pipe, lambda x: len(x) > 0)
    if include_events:
        events = map_step(events, _map_speech_events_v1)
        events = filter_step(events, lambda x: x is not None)
        # pipe = log_step(pipe, "Google out")
        return pipe, events
    else:
        return pipe


def _map_speech_events(input):
    if (
        input.speech_event_type
        == StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN
    ):
        return SpeechStart(time_since_start=input.speech_event_offset.total_seconds())
    if (
        input.speech_event_type
        == StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_END
    ):
        return SpeechEnd(time_since_start=input.speech_event_offset.total_seconds())
    return None


def _resolve_google_audio_config(audio_format: GoogleAudioConfig):
    if isinstance(audio_format, AudioConfig):
        return audio_format
    elif audio_format == AudioFormat.WAV_MULAW_8KHZ:
        # noinspection PyTypeChecker
        return AudioConfig(
            audio_encoding=AudioEncoding.MULAW,
            sample_rate_hertz=8000,
        )
    elif audio_format == AudioFormat.OGG_OPUS:
        # noinspection PyTypeChecker
        return AudioConfig(
            audio_encoding=AudioEncoding.OGG_OPUS,
        )
    elif audio_format == AudioFormat.MP3:
        # noinspection PyTypeChecker
        return AudioConfig(
            audio_encoding=AudioEncoding.MP3,
        )
    else:
        assert False, f"Unsupported audio format {audio_format}"


def _initial_recognition_config(
    include_events: bool,
    project: str,
    location: str,
    recognizer: str,
    model: str = "latest_long",
    language_codes: Union[str, list[str]] = ["en-US", "es-US"],
    audio_format: GoogleDecodingConfig = None,
):
    recognizer_path = (
        f"projects/{project}/locations/{location}/recognizers/{recognizer}"
    )
    auto_decoding, explicit_decoding = resolve_audio_decoding(audio_format)

    # noinspection PyTypeChecker
    ret = StreamingRecognizeRequest(
        recognizer=recognizer_path,
        streaming_config=StreamingRecognitionConfig(
            config=RecognitionConfig(
                auto_decoding_config=auto_decoding,
                explicit_decoding_config=explicit_decoding,
                model=model,
                language_codes=language_codes,
            ),
            streaming_features=StreamingRecognitionFeatures(
                interim_results=False,
                enable_voice_activity_events=include_events,
                # voice_activity_timeout=StreamingRecognitionFeatures.VoiceActivityTimeout(
                #     # speech_end_timeout
                # ),
            ),
        ),
    )
    # logger.debug(f"Initial recognition config: {ret}")
    return ret


def _initial_recognition_config_v1(
    include_events: bool,
    audio_format: AudioFormat,
    model: str = "latest_long",
    language_code: str = "en-US",
    use_enhanced: bool = True,
):
    if audio_format == AudioFormat.MP3:
        encoding = RecognitionConfigV1.AudioEncoding.MP3
        sample_rate_hertz = 44100
    elif audio_format == AudioFormat.WAV_MULAW_8KHZ:
        encoding = RecognitionConfigV1.AudioEncoding.MULAW
        sample_rate_hertz = 8000
    elif audio_format == AudioFormat.OGG_OPUS:
        encoding = RecognitionConfigV1.AudioEncoding.OGG_OPUS
        sample_rate_hertz = 48000
    elif audio_format == AudioFormat.WEBM_OPUS:
        encoding = RecognitionConfigV1.AudioEncoding.WEBM_OPUS
        sample_rate_hertz = 48000
    else:
        assert False, f"Unsupported audio format {audio_format}"

    # noinspection PyTypeChecker
    ret = StreamingRecognizeRequestV1(
        streaming_config=StreamingRecognitionConfigV1(
            config=RecognitionConfigV1(
                encoding=encoding,
                sample_rate_hertz=sample_rate_hertz,
                model=model,
                language_code=language_code,
                enable_automatic_punctuation=True,
                use_enhanced=use_enhanced,
            ),
            interim_results=False,
            enable_voice_activity_events=include_events,
        ),
    )
    # logger.debug(f"Initial recognition config: {ret}")
    return ret


def _map_speech_events_v1(input):
    if (
        input.speech_event_type
        == StreamingRecognizeResponseV1.SpeechEventType.SPEECH_ACTIVITY_BEGIN
    ):
        return SpeechStart(time_since_start=input.speech_event_time.total_seconds())
    if (
        input.speech_event_type
        == StreamingRecognizeResponseV1.SpeechEventType.SPEECH_ACTIVITY_END
    ):
        return SpeechEnd(time_since_start=input.speech_event_time.total_seconds())
    return None
