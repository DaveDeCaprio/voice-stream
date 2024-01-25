"""
Additional utilities for working with the Google Cloud steps.
"""

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

from voice_stream.audio.audio_ops import AudioFormat

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
    """
    Helper function to create a Google Speech V2 recognizer in a Google Cloud project.

    With Google Speech V2, you need to create a recognizer first before you can run speech recognition.  The V1 API
    uses a fixed set of recognizers and doesn't require this step.  This function sets up and initializes a speech
    recognizer with the specified configuration options.

    Parameters
    ----------
    client : SpeechAsyncClient
        An instance of SpeechAsyncClient for interacting with the Google Cloud Speech API.
    project_id : str
        The ID of the Google Cloud project where the recognizer is to be created.
    location : str
        The location or region where the recognizer is to be deployed.
    recognizer_id : str
        The unique identifier for the recognizer within the project.
    model : str
        The model to be used by the recognizer for speech recognition.
    language_codes : Union[str, list[str]]
        The language code(s) for the recognizer. Can be a single string or a list of strings.
    audio_format : GoogleDecodingConfig, optional
        Optional configuration for audio decoding. If not specified, the recognizer will auto-detect the audio configuration.

    Notes
    -----
    - The function handles the creation and configuration of a recognizer in an
      asynchronous manner, utilizing the `SpeechAsyncClient`.
    - It constructs the necessary request with the provided parameters and sends it
      to the Google Cloud Speech API.
    - After the recognizer is successfully created, the function logs its name for
      confirmation.

    Examples
    --------
    >>> await create_recognizer(client, "my-project", "us-west1", "my-recognizer", "phone_call", "en-US")

    This example demonstrates how to create a recognizer for English language
    phone calls in the 'us-west1' region of the 'my-project' Google Cloud project.
    """
    # Create a recognizer configuration
    parent = f"projects/{project_id}/locations/{location}"
    auto_decoding, explicit_decoding = _resolve_audio_decoding(audio_format)

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


def _resolve_audio_decoding(audio_format):
    if isinstance(audio_format, ExplicitDecodingConfig):
        return None, audio_format
    elif audio_format == AudioFormat.WAV_MULAW_8KHZ:
        # noinspection PyTypeChecker
        explicit = ExplicitDecodingConfig(
            encoding=ExplicitDecodingConfig.AudioEncoding.MULAW,
            sample_rate_hertz=8000,
            audio_channel_count=1,
        )
        return None, explicit
    else:
        return AutoDetectDecodingConfig(), None
