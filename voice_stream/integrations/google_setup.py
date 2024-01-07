import logging
from typing import Union, Optional

from google.cloud.speech_v2 import (
    Recognizer,
    CreateRecognizerRequest,
    SpeechAsyncClient,
    RecognitionConfig,
    ExplicitDecodingConfig,
    AutoDetectDecodingConfig,
)

from voice_stream.audio.audio_streams import AudioFormat

GoogleDecodingConfig = Optional[Union[AudioFormat, ExplicitDecodingConfig]]

logger = logging.getLogger(__name__)


async def create_recognizer(
    client: SpeechAsyncClient,
    project_id: str,
    location: str,
    recognizer_id: str,
    model: str,
    language_codes: Union[str, list[str]],
    audio_format: GoogleDecodingConfig = None,
):
    # Create a recognizer configuration
    parent = f"projects/{project_id}/locations/{location}"
    auto_decoding, explicit_decoding = resolve_audio_decoding(audio_format)

    # Create the recognizer
    # noinspection PyTypeChecker
    operation = client.create_recognizer(
        request=CreateRecognizerRequest(
            parent=parent,
            recognizer=Recognizer(
                name=f"{parent}/recognizers/{recognizer_id}",
                default_recognition_config=RecognitionConfig(
                    auto_decoding_config=auto_decoding,
                    explicit_decoding_config=explicit_decoding,
                    model=model,
                    language_codes=language_codes,
                ),
            ),
            recognizer_id=recognizer_id,
        )
    )

    # Wait for the operation to complete
    response = (await operation).result(timeout=90)
    response = await response
    logger.info(f"Recognizer created: {response.name}")


def resolve_audio_decoding(audio_format):
    if isinstance(audio_format, ExplicitDecodingConfig):
        return None, audio_format
    elif audio_format is None or audio_format != AudioFormat.WAV_MULAW_8KHZ:
        return AutoDetectDecodingConfig(), None
    else:
        # noinspection PyTypeChecker
        explicit = ExplicitDecodingConfig(
            encoding=ExplicitDecodingConfig.AudioEncoding.MULAW,
            sample_rate_hertz=8000,
            audio_channel_count=1,
        )
        return None, explicit
