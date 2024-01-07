import asyncio
import datetime
import os

import pytest

from tests.helpers import example_file
from voice_stream.audio import AudioFormat, wav_mulaw_file_source, wav_mulaw_file_sink
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
    audio_rate_limit_step,
)
from voice_stream.events import TimedText


@pytest.mark.asyncio
async def test_min_tokens_step():
    pipe = array_source(["", "Hello", " my", " name", " is", " Bob", ""])
    pipe = min_tokens_step(pipe, 3)
    ret = await array_sink(pipe)
    assert ret == ["Hello my name", " is Bob"]


@pytest.mark.asyncio
async def test_timed_text_rate_limit_step():
    pipe = array_source([TimedText("Hello, my name is", 1.0), TimedText(" Dave", 0.5)])
    pipe = timed_text_rate_limit_step(pipe, 0.25)
    now = datetime.datetime.now()
    ret = await array_sink(pipe)
    elapsed = datetime.datetime.now() - now
    assert ret == ["Hello,", " my", " name", " is", "", " Dave"]
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_min_tokens_step():
    pipe = array_source(["", "Hello", " my", " name", " is", " Bob", ""])
    pipe = min_tokens_step(pipe, 3)
    ret = await array_sink(pipe)
    assert ret == ["Hello my name", " is Bob"]


@pytest.mark.asyncio
async def test_rate_limit_wav():
    pipe = wav_mulaw_file_source(example_file("tts.wav"))
    pipe = map_step(
        pipe,
        lambda x: AudioWithText(
            audio=x,
            text="Hello, my name is Dave",
            audio_format=AudioFormat.WAV_MULAW_8KHZ,
        ),
    )
    pipe = tts_rate_limit_step(
        pipe,
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        buffer_seconds=0.25,
        include_text_output=False,
    )
    pipe = array_sink(pipe)

    now = datetime.datetime.now()
    ret = await pipe
    elapsed = datetime.datetime.now() - now
    assert len(ret) > 10
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_rate_limit_wav_with_text(tmp_path):
    pipe = wav_mulaw_file_source(example_file("tts.wav"), chunk_size=-1)
    pipe = map_step(
        pipe,
        lambda x: AudioWithText(
            audio=x,
            text="Hello, my name is Dave",
            audio_format=AudioFormat.WAV_MULAW_8KHZ,
        ),
    )
    pipe, text = tts_rate_limit_step(
        pipe,
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        buffer_seconds=0.25,
        include_text_output=True,
    )
    pipe = wav_mulaw_file_sink(pipe, tmp_path.joinpath("rate_limit_test.wav"))
    text = array_sink(text)

    now = datetime.datetime.now()
    audio, text_output = await asyncio.gather(pipe, text)
    elapsed = datetime.datetime.now() - now
    assert text_output == ["Hello,", " my", " name", " is", " Dave"]
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_rate_limit_ogg_audio_only():
    pipe = binary_file_source(example_file("tts.ogg"), chunk_size=-1)
    pipe = log_step(pipe, "Audio in", lambda x: len(x))
    pipe = audio_rate_limit_step(
        pipe, audio_format=AudioFormat.OGG_OPUS, buffer_seconds=0.25
    )
    pipe = log_step(pipe, "Audio out", lambda x: len(x))
    ret = await array_sink(pipe)
    assert len(ret) == 6


@pytest.mark.asyncio
async def test_rate_limit_ogg_with_text(tmp_path):
    pipe = binary_file_source(example_file("tts.ogg"), chunk_size=-1)
    pipe = map_step(
        pipe,
        lambda x: AudioWithText(
            audio=x, text="Hello, my name is Dave", audio_format=AudioFormat.OGG_OPUS
        ),
    )
    pipe, text = tts_rate_limit_step(
        pipe,
        audio_format=AudioFormat.OGG_OPUS,
        buffer_seconds=0.5,
        include_text_output=True,
    )
    pipe = log_step(pipe, "Audio out", lambda x: len(x))
    out_file = tmp_path.joinpath("rate_limit_test.ogg")
    pipe = binary_file_sink(pipe, out_file)
    text = array_sink(text)

    now = datetime.datetime.now()
    audio, text_output = await asyncio.gather(pipe, text)
    elapsed = datetime.datetime.now() - now
    assert text_output == ["Hello,", " my", " name", " is", " Dave"]
    # Check length of output file
    assert os.path.getsize(out_file) > 18000
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_rate_limit_mp3_with_text(tmp_path):
    pipe = binary_file_source(example_file("tts.mp3"), chunk_size=-1)
    pipe = map_step(
        pipe,
        lambda x: AudioWithText(
            audio=x, text="Hello, my name is Dave", audio_format=AudioFormat.MP3
        ),
    )
    pipe, text = tts_rate_limit_step(
        pipe, audio_format=AudioFormat.MP3, buffer_seconds=0.5, include_text_output=True
    )
    pipe = log_step(pipe, "Audio out", lambda x: len(x))
    out_file = tmp_path.joinpath("rate_limit_test.mp3")
    pipe = binary_file_sink(pipe, out_file)
    text = array_sink(text)

    now = datetime.datetime.now()
    audio, text_output = await asyncio.gather(pipe, text)
    elapsed = datetime.datetime.now() - now
    assert text_output == ["Hello,", " my", " name", " is", " Dave"]
    # Check length of output file
    assert os.path.getsize(out_file) > 17500
    assert elapsed.total_seconds() > 1.0
