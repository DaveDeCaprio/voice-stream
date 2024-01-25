"""
Integration with Google Cloud APIs.
"""

import logging
from typing import AsyncIterator, Union, Tuple

import asyncstdlib
from google.api_core.exceptions import Cancelled
from google.cloud.speech_v1 import (
    SpeechAsyncClient as SpeechAsyncClientV1,
    StreamingRecognizeRequest as StreamingRecognizeRequestV1,
    StreamingRecognizeResponse as StreamingRecognizeResponseV1,
    StreamingRecognitionConfig as StreamingRecognitionConfigV1,
    RecognitionConfig as RecognitionConfigV1,
)
from google.cloud.speech_v2 import (
    StreamingRecognizeRequest,
    StreamingRecognitionConfig,
    StreamingRecognitionFeatures,
    SpeechAsyncClient,
    StreamingRecognizeResponse,
    RecognitionConfig,
    RecognitionFeatures,
)
from google.cloud.texttospeech_v1 import (
    TextToSpeechAsyncClient,
    SynthesizeSpeechRequest,
    SynthesisInput,
    VoiceSelectionParams,
    AudioConfig,
    AudioEncoding,
)
from pydantic import BaseModel

from voice_stream.audio import AudioFormat, remove_wav_header
from voice_stream.core import (
    map_step,
    partition_step,
    async_init_step,
)
from voice_stream.events import (
    SpeechStart,
    SpeechEnd,
    BaseEvent,
    SpeechPartialResult,
    SpeechToTextResult,
)
from voice_stream.integrations._google_endless import EndlessStream
from voice_stream.integrations.google_utils import (
    _resolve_audio_decoding,
    GoogleDecodingConfig,
)
from voice_stream.text_to_speech import AudioWithText

# Can be one of the standard audio formats or a Google AudioConfig object
GoogleAudioConfig = Union[AudioFormat, AudioConfig]

logger = logging.getLogger(__name__)


class TTSRequest(BaseModel):
    text: str
    voice: str


async def google_text_to_speech_step(
    async_iter: AsyncIterator[Union[str, TTSRequest]],
    text_to_speech_async_client: TextToSpeechAsyncClient,
    voice_name: str = "en-US-Standard-H",
    audio_format: GoogleAudioConfig = AudioFormat.OGG_OPUS,
    speaking_rate: float = 1.0,
) -> AsyncIterator[AudioWithText]:
    """
    Data flow step that converts text to speech using Google's Text-to-Speech service.

    This function takes in strings or TTSRequest objects and converts each into audio using the specified voice and
    audio format. The function supports customization of the voice for each item if provided within a TTSRequest object.

    Parameters
    ----------
    async_iter : AsyncIterator[Union[str, TTSRequest]]
        An asynchronous iterator over text blocks or TTSRequest objects.  Using TTSRequest objects allows the voice to be
        customized for each block of text.
    text_to_speech_async_client : TextToSpeechAsyncClient
        An instance of TextToSpeechAsyncClient for interacting with the Google Text-to-Speech API.
    voice_name : str, optional
        Default voice name to be used for text-to-speech conversion. Default is "en-US-Standard-H".
    audio_format : GoogleAudioConfig, optional
        The audio format for the output speech. Default is AudioFormat.OGG_OPUS.
    speaking_rate
         Speaking rate/speed, in the range [0.25, 4.0]. 1.0 is the normal native speed supported by the specific voice.
         2.0 is twice as fast, and 0.5 is half as fast. If unset(0.0), defaults to the native 1.0 speed.
         Ignored if a GoogleAudioConfig is passed to `audio_format`.

    Yields
    ------
    AsyncIterator[AudioWithText]
        An asynchronous iterator yielding AudioWithText objects, each containing
        the audio output and the original text.

    Notes
    -----
    - The function allows for dynamic voice selection if a TTSRequest object is provided,
      which specifies the voice for a particular text block.
    - Supports different audio encoding formats based on the GoogleAudioConfig.
    """
    audio_config = _resolve_google_audio_config(audio_format, speaking_rate)

    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
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
    audio_format: Union[GoogleDecodingConfig, AudioFormat] = None,
    include_events: bool = False,
    max_minutes: int = 9,
    stream_reset_timeout_secs=240,
) -> Union[AsyncIterator[str], Tuple[AsyncIterator[str], AsyncIterator[BaseEvent]]]:
    """
    Data flow step for converting audio into text using Google Cloud Speech-to-Text V2 API.

    This function processes an asynchronous stream of audio bytes, using Google Cloud
    Speech-to-Text service to convert the audio into text. It supports additional
    configuration such as specifying the model, language codes, and audio format.
    If 'include_events' is set to True, it also returns a stream of speech recognition
    events alongside the text (:class:`~voice_stream.events.SpeechStart` and :class:`~voice_stream.events.SpeechEnd`).

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator over audio data in bytes.
    speech_async_client : SpeechAsyncClient
        An instance of SpeechAsyncClient for interacting with the Google Cloud Speech-to-Text API.
    project :
        The Google Cloud project identifier.
    location :
        The location or region of the Google Cloud project.
    recognizer :
        The recognizer identifier within the Google Cloud project.  This must be a previously created recognizer.  See
        :func:`~voice_stream.integrations.google_utils.create_recognizer` for details.
    model : str, optional
        The model to be used by the recognizer. Default is "latest_long".
    language_codes : Union[str, list[str]], optional
        The language code(s) for the recognizer. Can be a single string or a list of strings.
        Default is ["en-US", "es-US"].
    audio_format : GoogleDecodingConfig | AudioFormat, optional
        Optional configuration for audio decoding. Not required if the recognizer auto-detects the format.
    include_events : bool, optional
        If True, the function also returns a stream of speech recognition events. Default is False.
    max_minutes : int, optional
        The maximum number of minutes to process.  Default is 9.
    stream_reset_timeout_secs : int, optional
        The time internal on which to refresh the call to the recognizer.  Google only supports streams up to 5 minutes,
        so the default is 4 minutes.

    Returns
    -------
    Union[AsyncIterator[str], Tuple[AsyncIterator[str], AsyncIterator[voice_stream.events.BaseEvent]]]
        If `include_events` is False, returns an asynchronous iterator yielding recognized text from the audio stream.
        If `include-events` is True, returns a tuple with 2 iterators.  The first yields the recognized text, and the
        second contain speech events.

    Notes
    -----
    - The function breaks the audio stream into chunks, sends them to the Speech-to-Text
      API, and processes the responses to extract the transcript.
    - Speech recognition events include information like word timings and confidences.
    - If you intend to run a recognition stream that is longer than `stream_reset_timeout_secs`, you need to set the
      audio format.
    """
    initial_config = _initial_recognition_config(
        include_events,
        project,
        location,
        recognizer,
        model,
        language_codes,
        audio_format,
    )

    def map_audio(x):
        return StreamingRecognizeRequest(recognizer=recognizer, audio=x)

    stream = EndlessStream(
        speech_async_client,
        initial_config,
        audio_format=audio_format,
        map_audio=map_audio,
        map_event=_map_speech_event,
        stream_reset_timeout_secs=stream_reset_timeout_secs,
        max_resets=(60 * max_minutes) // stream_reset_timeout_secs,
    ).step(async_iter)
    return _google_speech_postprocessing(stream, include_events)


def google_speech_v1_step(
    async_iter: AsyncIterator[bytes],
    speech_async_client: SpeechAsyncClientV1,
    audio_format: AudioFormat,
    model: str = "latest_long",
    language_code: str = "en-US",
    include_events: bool = False,
    max_minutes: int = 9,
    stream_reset_timeout_secs=240,
) -> AsyncIterator[str]:
    """
    Data flow step for converting audio into text using Google Cloud Speech-to-Text V1 API.

    This function processes an asynchronous stream of audio bytes, using Google Cloud
    Speech-to-Text V1 service to convert the audio into text. It supports additional
    configuration such as specifying the model, language codes, and audio format.
    If 'include_events' is set to True, it also returns a stream of speech recognition
    events alongside the text (:class:`~voice_stream.events.SpeechStart` and :class:`~voice_stream.events.SpeechEnd`).

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator over audio data in bytes.
    speech_async_client : SpeechAsyncClient
        An instance of SpeechAsyncClientV1 for interacting with the Google Cloud Speech-to-Text API V1.
    audio_format : voice_stream.audio.AudioFormat
        The audio format of the input data.  This is required in V1.  Use the V2 API for auto-detection of formats.
    model : str, optional
        The model to be used by the recognizer. Default is "latest_long".
    language_code : str, optional
        The language code(s) for the recognizer. Default is "en-US".
    include_events : bool, optional
        If True, the function also returns a stream of speech recognition events. Default is False.
    max_minutes : int, optional
        The maximum number of minutes to process.  Default is 9.

    Returns
    -------
    Union[AsyncIterator[str], Tuple[AsyncIterator[str], AsyncIterator[voice_stream.events.BaseEvent]]]
        If `include_events` is False, returns an asynchronous iterator yielding recognized text from the audio stream.
        If `include-events` is True, returns a tuple with 2 iterators.  The first yields the recognized text, and the
        second contain speech events.

    Notes
    -----
    - The function breaks the audio stream into chunks, sends them to the Speech-to-Text
      API, and processes the responses to extract the transcript.
    - Speech recognition events include information like word timings and confidences.
    """
    initial_config = _initial_recognition_config_v1(
        include_events=include_events,
        model=model,
        language_code=language_code,
        audio_format=audio_format,
    )

    def map_audio(x):
        return StreamingRecognizeRequestV1(audio_content=x)

    stream = EndlessStream(
        speech_async_client,
        initial_config,
        audio_format=audio_format,
        map_audio=map_audio,
        map_event=_map_speech_event_v1,
        stream_reset_timeout_secs=stream_reset_timeout_secs,
        max_resets=(60 * max_minutes) // stream_reset_timeout_secs,
    ).step(async_iter)
    return _google_speech_postprocessing(
        stream,
        include_events,
    )


def _google_speech_postprocessing(
    async_iter: AsyncIterator[BaseEvent],
    include_events: bool,
):
    stream = async_iter
    # stream = log_step(stream, "SR EH out", lambda x: f"{format_current_task()}\n{x}")

    def extract_text(x):
        return x.text if isinstance(x, SpeechToTextResult) and len(x.text) > 0 else None

    if include_events:
        stream, events = partition_step(
            stream, lambda x: isinstance(x, SpeechToTextResult)
        )
        stream = map_step(stream, extract_text, ignore_none=True)
        return stream, events
    else:
        stream = map_step(stream, extract_text, ignore_none=True)
        return stream


def _get_transcript(result):
    if not result.results:
        logger.info("No results in google response")
        return ""
    if not result.results[0].alternatives:
        logger.info("No alternatives in google response")
        return ""
    return result.results[0].alternatives[0].transcript


def _resolve_google_audio_config(audio_format: GoogleAudioConfig, speaking_rate: float):
    if isinstance(audio_format, AudioConfig):
        return audio_format
    elif audio_format == AudioFormat.WAV_MULAW_8KHZ:
        # noinspection PyTypeChecker
        return AudioConfig(
            audio_encoding=AudioEncoding.MULAW,
            sample_rate_hertz=8000,
            speaking_rate=speaking_rate,
        )
    elif audio_format == AudioFormat.OGG_OPUS:
        # noinspection PyTypeChecker
        return AudioConfig(
            audio_encoding=AudioEncoding.OGG_OPUS, speaking_rate=speaking_rate
        )
    elif audio_format == AudioFormat.MP3:
        # noinspection PyTypeChecker
        return AudioConfig(
            audio_encoding=AudioEncoding.MP3, speaking_rate=speaking_rate
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
    auto_decoding, explicit_decoding = _resolve_audio_decoding(audio_format)

    # noinspection PyTypeChecker
    out = StreamingRecognizeRequest(
        recognizer=recognizer_path,
        streaming_config=StreamingRecognitionConfig(
            config=RecognitionConfig(
                auto_decoding_config=auto_decoding,
                explicit_decoding_config=explicit_decoding,
                features=RecognitionFeatures(enable_automatic_punctuation=True),
                model=model,
                language_codes=language_codes,
            ),
            streaming_features=StreamingRecognitionFeatures(
                interim_results=include_events,
                enable_voice_activity_events=True,
                # voice_activity_timeout=StreamingRecognitionFeatures.VoiceActivityTimeout(
                #     # speech_end_timeout
                # ),
            ),
        ),
    )
    # logger.debug(f"Initial recognition config: {out}")
    return out


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
    out = StreamingRecognizeRequestV1(
        streaming_config=StreamingRecognitionConfigV1(
            config=RecognitionConfigV1(
                encoding=encoding,
                sample_rate_hertz=sample_rate_hertz,
                model=model,
                language_code=language_code,
                enable_automatic_punctuation=True,
                use_enhanced=use_enhanced,
            ),
            interim_results=include_events,
            enable_voice_activity_events=True,
        ),
    )
    # logger.debug(f"Initial recognition config: {out}")
    return out


def _map_speech_event(input, time_offset: float = 0):
    if (
        input.speech_event_type
        == StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN
    ):
        return SpeechStart(
            time_since_start=time_offset + input.speech_event_offset.total_seconds()
        )
    if (
        input.speech_event_type
        == StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_END
    ):
        return SpeechEnd(
            time_since_start=time_offset + input.speech_event_offset.total_seconds()
        )
    if input.results:
        transcript = _get_transcript(input)
        time_since = time_offset + input.results[-1].result_end_offset.total_seconds()
        if input.results[0].is_final:
            return SpeechToTextResult(text=transcript, time_since_start=time_since)
        else:
            return SpeechPartialResult(text=transcript, time_since_start=time_since)
    logger.warning(f"Unmapped speech event {input}")
    return None


def _map_speech_event_v1(input, time_offset: float = 0):
    if (
        input.speech_event_type
        == StreamingRecognizeResponseV1.SpeechEventType.SPEECH_ACTIVITY_BEGIN
    ):
        return SpeechStart(
            time_since_start=time_offset + input.speech_event_time.total_seconds()
        )
    if (
        input.speech_event_type
        == StreamingRecognizeResponseV1.SpeechEventType.SPEECH_ACTIVITY_END
    ):
        return SpeechEnd(
            time_since_start=time_offset + input.speech_event_time.total_seconds()
        )
    if input.results:
        transcript = _get_transcript(input)
        time_since = time_offset + input.results[-1].result_end_time.total_seconds()
        if input.results[0].is_final:
            return SpeechToTextResult(text=transcript, time_since_start=time_since)
        else:
            return SpeechPartialResult(text=transcript, time_since_start=time_since)
    if input.error:
        raise ValueError(
            f"Google Speech Recognition Error - Code: {input.error.code} Message: {input.error.message}"
        )
    logger.warning(f"Unmapped speech event {input}")
    return None
