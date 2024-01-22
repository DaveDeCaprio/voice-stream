import logging
import os

import asyncio
import pytest
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v1 import SpeechAsyncClient as SpeechAsyncClientV1
from google.cloud.speech_v2 import SpeechAsyncClient, StreamingRecognizeRequest
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient

from tests.helpers import assert_files_equal, example_file
from voice_stream import (
    array_sink,
    array_source,
    binary_file_source,
    binary_file_sink,
    log_step,
    map_step,
    concat_step,
    async_init_step,
    audio_rate_limit_step,
)
from voice_stream.audio import (
    wav_mulaw_file_source,
    wav_mulaw_file_sink,
    AudioFormat,
    ogg_page_separator_step,
    ogg_concatenator_step,
)
from voice_stream.core import delay_step, filter_step
from voice_stream.events import SpeechStart, SpeechEnd, SpeechPartialResult
from voice_stream.integrations.google import (
    google_speech_step,
    google_text_to_speech_step,
    google_speech_v1_step,
    _initial_recognition_config,
)
from voice_stream.substreams import exception_handling_substream

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
    assert out == ["Testing 1 2 3 testing 1 2 3."]


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
    assert out == ["Testing 1 2 3 testing 1 2 3."]
    assert events[:3] == [
        SpeechStart(time_since_start=1.29),
        SpeechEnd(time_since_start=4.5),
        SpeechPartialResult(
            event_name="speech_end", text="test", time_since_start=1.83
        ),
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
    assert events[:3] == [
        SpeechStart(time_since_start=1.38),
        SpeechEnd(time_since_start=4.46),
        SpeechPartialResult(text="test", time_since_start=1.86),
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


@pytest.mark.asyncio
async def test_google_speech_exception():
    """This annoyingly long and complicated test checks that we can really recover from errors in google speech steps.
    Attempts to replicate all failure modes with a simpler test failed."""
    logger.debug("Start")
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    project = os.environ["GCP_PROJECT_ID"]
    location = os.environ["GCP_SPEECH_LOCATION"]
    recognizer = os.environ["GCP_TELEPHONE_SPEECH_RECOGNIZER"]
    stream = binary_file_source(example_file("testing.webm"), chunk_size=1000)
    stream = delay_step(stream, 0.05)

    def map_audio(x):
        return StreamingRecognizeRequest(recognizer=recognizer, audio=x)

    stream = log_step(stream, "Audio", lambda x: len(x))
    stream = map_step(stream, map_audio)
    initial_config = _initial_recognition_config(
        False,
        project,
        location,
        recognizer,
    )

    async def recognize_step(stream):
        return await speech_async_client.streaming_recognize(stream, timeout=0.8)

    def recognize_substream(stream):
        logger.info("Initializing new recognize step")
        config = array_source([initial_config])
        config = log_step(config, "Config", lambda x: "")
        stream = concat_step(config, stream)
        return async_init_step(stream, recognize_step)

    def handle_exception(e):
        logger.error(f"Google Recognize aborted. {e}", exc_info=e)
        return [None]

    stream = exception_handling_substream(
        stream, recognize_substream, [handle_exception], max_exceptions=10
    )
    out = await array_sink(stream)
    assert out == []


@pytest.mark.asyncio
async def test_google_speech_long():
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    project = os.environ["GCP_PROJECT_ID"]
    location = os.environ["GCP_SPEECH_LOCATION"]
    recognizer = os.environ["GCP_BROWSER_SPEECH_RECOGNIZER"]
    logger.info(f"Recognizer is {recognizer}")
    stream = binary_file_source(example_file("12min.mp3"), chunk_size=1024)
    # stream = audio_rate_limit_step(stream, audio_format=AudioFormat.MP3, buffer_seconds=0.5)
    # 1 Mb for 60 seconds of audio
    stream = delay_step(stream, 60 / 1000)
    stream, events = google_speech_step(
        stream,
        speech_async_client,
        project=project,
        location=location,
        recognizer=recognizer,
        include_events=True,
        max_minutes=20,
    )
    stream = log_step(stream, "output")
    out = array_sink(stream)
    events = filter_step(events, lambda x: x.event_name == "speech_start")
    events = log_step(events, "Speech event")
    events = array_sink(events)
    out, events = await asyncio.gather(out, events)
    assert out == ["start browser bass call"]
