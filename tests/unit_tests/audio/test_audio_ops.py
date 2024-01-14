import datetime
import logging

import pytest

from tests.helpers import assert_files_equal, example_file
from voice_stream import (
    count_step,
    byte_buffer_step,
    chunk_bytes_step,
    array_sink,
    binary_file_source,
    concat_step,
    binary_file_sink,
    map_step,
    AudioWithText,
    tts_rate_limit_step,
    log_step,
    audio_rate_limit_step,
)
from voice_stream.audio import AudioFormatError, wav_mulaw_file_source, AudioFormat
from voice_stream.audio.audio_ops import (
    remove_wav_header,
    wav_mulaw_file_sink,
    ogg_page_separator_step,
    ogg_concatenator_step,
)

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_wav_read_write(tmp_path):
    stream = wav_mulaw_file_source(example_file("testing.wav"))
    stream = count_step(stream, "Before buffer")
    stream = byte_buffer_step(stream)
    stream = chunk_bytes_step(stream, 5000)
    stream = count_step(stream, "After buffer")
    await wav_mulaw_file_sink(stream, tmp_path.joinpath("testing.wav"))
    assert_files_equal(
        example_file("testing.wav"), tmp_path.joinpath("testing.wav"), mode="b"
    )


@pytest.mark.asyncio
async def test_fail_smoothly_on_bad_filename():
    with pytest.raises(FileNotFoundError):
        stream = wav_mulaw_file_source("BAD_FILE_NAME.wav")
        stream = byte_buffer_step(stream)
        await array_sink(stream)


def test_remove_wav_header():
    with open(example_file("tts.wav"), "rb") as f:
        data = f.read()
        cleaned = remove_wav_header(data)
        header_len = 58
        assert len(cleaned) == len(data[header_len:])
        assert cleaned[:10] == data[header_len : header_len + 10]
        assert cleaned[-10:] == data[-10:]


@pytest.mark.asyncio
async def test_ogg_page_separator_step():
    stream = binary_file_source(example_file("tts.ogg"), chunk_size=100)
    stream = ogg_page_separator_step(stream)
    out = await array_sink(stream)
    msg = "\n".join([f"{len(_)} {_}" for _ in out])
    # logger.info(f"out={msg}")
    assert all(_[:4] == b"OggS" for _ in out)


def throw_e(x):
    raise AudioFormatError("")


@pytest.mark.asyncio
async def test_ogg_page_separator_step_failure():
    # with pytest.raises(AudioFormatError):
    try:
        stream = wav_mulaw_file_source(example_file("testing.wav"))
        stream = ogg_page_separator_step(stream)
        await array_sink(stream)
    except AudioFormatError as e:
        pass
    # loop = asyncio.get_event_loop()
    # pending = asyncio.all_tasks(loop)
    # if pending:
    #     logger.warning(f"PENDING {pending}")


@pytest.mark.asyncio
async def test_ogg_concatenator_step(tmp_path):
    stream1 = binary_file_source(example_file("tts1.ogg"))
    stream2 = binary_file_source(example_file("tts2.ogg"))
    stream = concat_step(stream1, stream2)
    stream = ogg_page_separator_step(stream)
    # stream = log_step(stream, "Buffer len", lambda x: len(x))
    stream = ogg_concatenator_step(stream)
    target = tmp_path.joinpath("tts_concat.ogg")
    await binary_file_sink(stream, target)
    assert_files_equal(example_file("tts_concat.ogg"), target, mode="b")


@pytest.mark.asyncio
async def test_rate_limit_wav():
    stream = wav_mulaw_file_source(example_file("tts.wav"))
    stream = map_step(
        stream,
        lambda x: AudioWithText(
            audio=x,
            text="Hello, my name is Dave",
            audio_format=AudioFormat.WAV_MULAW_8KHZ,
        ),
    )
    stream = tts_rate_limit_step(
        stream,
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
        buffer_seconds=0.25,
        include_text_output=False,
    )
    stream = array_sink(stream)

    now = datetime.datetime.now()
    out = await stream
    elapsed = datetime.datetime.now() - now
    assert len(out) > 10
    assert elapsed.total_seconds() > 1.0


@pytest.mark.asyncio
async def test_rate_limit_ogg_audio_only():
    stream = binary_file_source(example_file("tts.ogg"), chunk_size=-1)
    stream = log_step(stream, "Audio in", lambda x: len(x))
    stream = audio_rate_limit_step(
        stream, audio_format=AudioFormat.OGG_OPUS, buffer_seconds=0.25
    )
    stream = log_step(stream, "Audio out", lambda x: len(x))
    out = await array_sink(stream)
    assert len(out) == 6
