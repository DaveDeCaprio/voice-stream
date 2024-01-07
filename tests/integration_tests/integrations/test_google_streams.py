import logging
import os

import pytest
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient

from tests.helpers import assert_files_equal, example_file
from voice_stream.audio import (
    wav_mulaw_file_source,
    wav_mulaw_file_sink,
    AudioFormat,
    ogg_page_separator_step,
    ogg_concatenator_step,
)
from voice_stream import (
    array_sink,
    array_source,
    binary_file_source,
    binary_file_sink,
    log_step,
    map_step,
)
from voice_stream.events import SpeechStart, SpeechEnd
from voice_stream.integrations.google_streams import (
    google_speech_step,
    google_text_to_speech_step,
)

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_google_speech():
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    project = os.environ["GCP_PROJECT_ID"]
    location = os.environ["GCP_SPEECH_LOCATION"]
    recognizer = os.environ["GCP_TELEPHONE_SPEECH_RECOGNIZER"]
    pipe = wav_mulaw_file_source(example_file("testing.wav"))
    logger.info(f"Recognizer is {recognizer}")
    pipe = google_speech_step(
        pipe,
        speech_async_client,
        project=project,
        location=location,
        recognizer=recognizer,
        model="telephony",
        language_codes=["en-US", "es-US"],
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
    )
    ret = await array_sink(pipe)
    assert ret == ["testing 1 2 3 testing 1 2 3"]


@pytest.mark.asyncio
async def test_google_speech_browser():
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    project = os.environ["GCP_PROJECT_ID"]
    location = os.environ["GCP_SPEECH_LOCATION"]
    recognizer = os.environ["GCP_BROWSER_SPEECH_RECOGNIZER"]
    pipe = binary_file_source(example_file("testing.webm"), chunk_size=65536)
    logger.info(f"Recognizer is {recognizer}")
    pipe = google_speech_step(
        pipe,
        speech_async_client,
        project=project,
        location=location,
        recognizer=recognizer,
    )
    ret = await array_sink(pipe)
    assert ret == ["start browser bass call"]


@pytest.mark.asyncio
async def test_google_speech_with_events():
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    project = os.environ["GCP_PROJECT_ID"]
    location = os.environ["GCP_SPEECH_LOCATION"]
    recognizer = os.environ["GCP_TELEPHONE_SPEECH_RECOGNIZER"]
    pipe = wav_mulaw_file_source(example_file("testing.wav"))
    pipe, events = google_speech_step(
        pipe,
        speech_async_client,
        project,
        location,
        recognizer,
        model="telephony",
        language_codes=["en-US", "es-US"],
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        include_events=True,
    )
    ret = await array_sink(pipe)
    events = await array_sink(events)
    logger.info(events)
    assert ret == ["testing 1 2 3 testing 1 2 3"]
    assert events == [
        SpeechStart(1.29),
        SpeechEnd(4.5),
    ]


@pytest.mark.asyncio
async def test_google_text_to_speech(tmp_path):
    pipe = array_source(
        ["Hello world", "Longer second utterance that drags on a bit and keeps going"]
    )
    text_to_speech_async_client = TextToSpeechAsyncClient()
    pipe = google_text_to_speech_step(
        pipe, text_to_speech_async_client, audio_format=AudioFormat.WAV_MULAW_8KHZ
    )
    pipe = map_step(pipe, lambda x: x.audio)
    target = tmp_path.joinpath("tts.wav")
    ret = await wav_mulaw_file_sink(pipe, target)
    assert_files_equal(example_file("tts.wav"), target, mode="b")


@pytest.mark.asyncio
async def test_google_text_to_speech_ogg(tmp_path):
    pipe = array_source(
        ["Hello world", "Longer second utterance that drags on a bit and keeps going"]
    )
    text_to_speech_async_client = TextToSpeechAsyncClient()
    pipe = google_text_to_speech_step(
        pipe, text_to_speech_async_client, audio_format=AudioFormat.OGG_OPUS
    )
    pipe = map_step(pipe, lambda x: x.audio)
    pipe = log_step(pipe, "ogg", formatter=lambda x: f"{len(x)} bytes")
    pipe = ogg_page_separator_step(pipe)
    pipe = ogg_concatenator_step(pipe)
    target = tmp_path.joinpath("tts.ogg")
    await binary_file_sink(pipe, target)
    assert_files_equal(example_file("tts.ogg"), target, mode="b")


@pytest.mark.asyncio
async def test_google_text_to_speech_mp3(tmp_path):
    pipe = array_source(
        ["Hello world", "Longer second utterance that drags on a bit and keeps going"]
    )
    text_to_speech_async_client = TextToSpeechAsyncClient()
    pipe = google_text_to_speech_step(
        pipe, text_to_speech_async_client, audio_format=AudioFormat.MP3
    )
    pipe = map_step(pipe, lambda x: x.audio)
    target = tmp_path.joinpath("tts.mp3")
    await binary_file_sink(pipe, target)
    assert_files_equal(example_file("tts.mp3"), target, mode="b")
