import asyncio
import datetime
import os

import pytest

from tests.helpers import example_file
from voice_stream import (
    array_source,
    array_sink,
    map_step,
    binary_file_source,
    binary_file_sink,
    log_step,
    min_tokens_step,
    timed_text_rate_limit_step,
    AudioWithText,
    tts_rate_limit_step,
    buffer_tts_text_step,
)
from voice_stream.audio import AudioFormat, wav_mulaw_file_source, wav_mulaw_file_sink
from voice_stream.events import TimedText


@pytest.mark.asyncio
async def test_min_tokens_step():
    stream = array_source(["", "Hello", " my", " name", " is", " Bob", ""])
    stream = min_tokens_step(stream, 3)
    out = await array_sink(stream)
    assert out == ["Hello my name", " is Bob"]


@pytest.mark.asyncio
async def test_timed_text_rate_limit_step():
    stream = array_source(
        [
            TimedText(text="Hello, my name is", duration_in_seconds=1.0),
            TimedText(text=" Dave", duration_in_seconds=0.5),
        ]
    )
    stream = timed_text_rate_limit_step(stream, 0.25)
    now = datetime.datetime.now()
    out = await array_sink(stream)
    elapsed = datetime.datetime.now() - now
    assert out == ["Hello,", " my", " name", " is", "", " Dave"]
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_min_tokens_step():
    stream = array_source(["", "Hello", " my", " name", " is", " Bob", ""])
    stream = min_tokens_step(stream, 3)
    out = await array_sink(stream)
    assert out == ["Hello my name", " is Bob"]


@pytest.mark.asyncio
async def test_rate_limit_wav_with_text(tmp_path):
    stream = wav_mulaw_file_source(example_file("tts.wav"), chunk_size=-1)
    stream = map_step(
        stream,
        lambda x: AudioWithText(
            audio=x,
            text="Hello, my name is Dave",
            audio_format=AudioFormat.WAV_MULAW_8KHZ,
        ),
    )
    stream, text = tts_rate_limit_step(
        stream,
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        buffer_seconds=0.25,
        include_text_output=True,
    )
    stream = wav_mulaw_file_sink(stream, tmp_path.joinpath("rate_limit_test.wav"))
    text = array_sink(text)

    now = datetime.datetime.now()
    audio, text_output = await asyncio.gather(stream, text)
    elapsed = datetime.datetime.now() - now
    assert text_output == ["Hello,", " my", " name", " is", " Dave"]
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_rate_limit_ogg_with_text(tmp_path):
    stream = binary_file_source(example_file("tts.ogg"), chunk_size=-1)
    stream = map_step(
        stream,
        lambda x: AudioWithText(
            audio=x, text="Hello, my name is Dave", audio_format=AudioFormat.OGG_OPUS
        ),
    )
    stream, text = tts_rate_limit_step(
        stream,
        audio_format=AudioFormat.OGG_OPUS,
        buffer_seconds=0.5,
        include_text_output=True,
    )
    stream = log_step(stream, "Audio out", lambda x: len(x))
    out_file = tmp_path.joinpath("rate_limit_test.ogg")
    stream = binary_file_sink(stream, out_file)
    text = array_sink(text)

    now = datetime.datetime.now()
    audio, text_output = await asyncio.gather(stream, text)
    elapsed = datetime.datetime.now() - now
    assert text_output == ["Hello,", " my", " name", " is", " Dave"]
    # Check length of output file
    assert os.path.getsize(out_file) > 18000
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_rate_limit_mp3_with_text(tmp_path):
    stream = binary_file_source(example_file("tts.mp3"), chunk_size=-1)
    stream = map_step(
        stream,
        lambda x: AudioWithText(
            audio=x, text="Hello, my name is Dave", audio_format=AudioFormat.MP3
        ),
    )
    stream, text = tts_rate_limit_step(
        stream,
        audio_format=AudioFormat.MP3,
        buffer_seconds=0.5,
        include_text_output=True,
    )
    stream = log_step(stream, "Audio out", lambda x: len(x))
    out_file = tmp_path.joinpath("rate_limit_test.mp3")
    stream = binary_file_sink(stream, out_file)
    text = array_sink(text)

    now = datetime.datetime.now()
    audio, text_output = await asyncio.gather(stream, text)
    elapsed = datetime.datetime.now() - now
    assert text_output == ["Hello,", " my", " name", " is", " Dave"]
    # Check length of output file
    assert os.path.getsize(out_file) > 17500
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_buffer_tts_text_step():
    stream = array_source(["Hello", " world!", " How", " are", " you", " today", ""])
    stream = buffer_tts_text_step(stream)
    out = await array_sink(stream)
    assert out == ["Hello world!", " How are you today"]
