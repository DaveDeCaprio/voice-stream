import logging
import os

import pytest
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v1 import SpeechAsyncClient as SpeechAsyncClientV1
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient

from tests.helpers import assert_files_equal, example_file
from voice_stream import (
    array_sink,
    array_source,
    binary_file_source,
    binary_file_sink,
    log_step,
    map_step,
)
from voice_stream.audio import (
    wav_mulaw_file_source,
    wav_mulaw_file_sink,
    AudioFormat,
    ogg_page_separator_step,
    ogg_concatenator_step,
)
from voice_stream.events import SpeechStart, SpeechEnd
from voice_stream.integrations.google import (
    google_speech_step,
    google_text_to_speech_step,
    google_speech_v1_step,
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
    stream = wav_mulaw_file_source(example_file("testing.wav"))
    logger.info(f"Recognizer is {recognizer}")
    stream = google_speech_step(
        stream,
        speech_async_client,
        project=project,
        location=location,
        recognizer=recognizer,
        model="telephony",
        language_codes=["en-US", "es-US"],
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
    )
    out = await array_sink(stream)
    assert out == ["testing 1 2 3 testing 1 2 3"]


@pytest.mark.asyncio
async def test_google_speech_browser():
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    project = os.environ["GCP_PROJECT_ID"]
    location = os.environ["GCP_SPEECH_LOCATION"]
    recognizer = os.environ["GCP_BROWSER_SPEECH_RECOGNIZER"]
    stream = binary_file_source(example_file("testing.webm"), chunk_size=65536)
    logger.info(f"Recognizer is {recognizer}")
    stream = google_speech_step(
        stream,
        speech_async_client,
        project=project,
        location=location,
        recognizer=recognizer,
    )
    out = await array_sink(stream)
    assert out == ["start browser bass call"]


@pytest.mark.asyncio
async def test_google_speech_with_events():
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    project = os.environ["GCP_PROJECT_ID"]
    location = os.environ["GCP_SPEECH_LOCATION"]
    recognizer = os.environ["GCP_TELEPHONE_SPEECH_RECOGNIZER"]
    stream = wav_mulaw_file_source(example_file("testing.wav"))
    stream, events = google_speech_step(
        stream,
        speech_async_client,
        project,
        location,
        recognizer,
        model="telephony",
        language_codes=["en-US", "es-US"],
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        include_events=True,
    )
    out = await array_sink(stream)
    events = await array_sink(events)
    logger.info(events)
    assert out == ["testing 1 2 3 testing 1 2 3"]
    assert events == [
        SpeechStart(time_since_start=1.29),
        SpeechEnd(time_since_start=4.5),
    ]


@pytest.mark.asyncio
async def test_google_speech_browser_v1():
    speech_async_client = SpeechAsyncClientV1(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    stream = binary_file_source(example_file("testing.webm"), chunk_size=65536)
    stream = google_speech_v1_step(
        stream,
        speech_async_client,
        audio_format=AudioFormat.WEBM_OPUS,
    )
    out = await array_sink(stream)
    assert out == ["Start browser-based call."]


@pytest.mark.asyncio
async def test_google_speech_v1_with_events():
    speech_async_client = SpeechAsyncClientV1(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    stream = wav_mulaw_file_source(example_file("testing.wav"))
    stream, events = google_speech_v1_step(
        stream,
        speech_async_client,
        model="telephony",
        language_code="en-US",
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        include_events=True,
    )
    out = await array_sink(stream)
    events = await array_sink(events)
    logger.info(events)
    assert out == ["Testing 1 2 3 testing 1 2 3."]
    assert events == [
        SpeechStart(time_since_start=1.38),
        SpeechEnd(time_since_start=4.46),
    ]


@pytest.mark.asyncio
async def test_google_text_to_speech(tmp_path):
    stream = array_source(
        ["Hello world", "Longer second utterance that drags on a bit and keeps going"]
    )
    text_to_speech_async_client = TextToSpeechAsyncClient()
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.WAV_MULAW_8KHZ
    )
    stream = map_step(stream, lambda x: x.audio)
    target = tmp_path.joinpath("tts.wav")
    out = await wav_mulaw_file_sink(stream, target)
    assert_files_equal(example_file("tts.wav"), target, mode="b")


@pytest.mark.asyncio
async def test_google_text_to_speech_fast(tmp_path):
    stream = array_source(
        ["Hello world", "Longer second utterance that drags on a bit and keeps going"]
    )
    text_to_speech_async_client = TextToSpeechAsyncClient()
    stream = google_text_to_speech_step(
        stream,
        text_to_speech_async_client,
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        speaking_rate=4,
    )
    stream = map_step(stream, lambda x: x.audio)
    target = tmp_path.joinpath("tts_fast.wav")
    out = await wav_mulaw_file_sink(stream, target)
    assert_files_equal(example_file("tts_fast.wav"), target, mode="b")


@pytest.mark.asyncio
async def test_google_text_to_speech_ogg(tmp_path):
    stream = array_source(
        ["Hello world", "Longer second utterance that drags on a bit and keeps going"]
    )
    text_to_speech_async_client = TextToSpeechAsyncClient()
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.OGG_OPUS
    )
    stream = map_step(stream, lambda x: x.audio)
    stream = log_step(stream, "ogg", formatter=lambda x: f"{len(x)} bytes")
    stream = ogg_page_separator_step(stream)
    stream = ogg_concatenator_step(stream)
    target = tmp_path.joinpath("tts.ogg")
    await binary_file_sink(stream, target)
    assert_files_equal(example_file("tts.ogg"), target, mode="b")


@pytest.mark.asyncio
async def test_google_text_to_speech_mp3(tmp_path):
    stream = array_source(
        ["Hello world", "Longer second utterance that drags on a bit and keeps going"]
    )
    text_to_speech_async_client = TextToSpeechAsyncClient()
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.MP3
    )
    stream = map_step(stream, lambda x: x.audio)
    target = tmp_path.joinpath("tts.mp3")
    await binary_file_sink(stream, target)
    assert_files_equal(example_file("tts.mp3"), target, mode="b")
