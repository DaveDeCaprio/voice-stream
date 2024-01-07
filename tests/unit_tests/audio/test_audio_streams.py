import logging

import pytest

from voice_stream.audio import AudioFormatError
from voice_stream.audio.audio_streams import (
    remove_wav_header,
)
from voice_stream import (
    count_step,
    byte_buffer_step,
    chunk_bytes_step,
    wav_mulaw_file_source,
    wav_mulaw_file_sink,
    ogg_page_separator_step,
    ogg_concatenator_step,
    array_sink,
    binary_file_source,
    concat_step,
    binary_file_sink,
)
from tests.helpers import assert_files_equal, example_file

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_wav_read_write(tmp_path):
    pipe = wav_mulaw_file_source(example_file("testing.wav"))
    pipe = count_step(pipe, "Before buffer")
    pipe = byte_buffer_step(pipe)
    pipe = chunk_bytes_step(pipe, 5000)
    pipe = count_step(pipe, "After buffer")
    await wav_mulaw_file_sink(pipe, tmp_path.joinpath("testing.wav"))
    assert_files_equal(
        example_file("testing.wav"), tmp_path.joinpath("testing.wav"), mode="b"
    )


@pytest.mark.asyncio
async def test_fail_smoothly_on_bad_filename():
    with pytest.raises(FileNotFoundError):
        pipe = wav_mulaw_file_source("BAD_FILE_NAME.wav")
        pipe = byte_buffer_step(pipe)
        await array_sink(pipe)


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
    pipe = binary_file_source(example_file("tts.ogg"), chunk_size=100)
    pipe = ogg_page_separator_step(pipe)
    ret = await array_sink(pipe)
    msg = "\n".join([f"{len(_)} {_}" for _ in ret])
    logger.info(f"ret={msg}")
    assert all(_[:4] == b"OggS" for _ in ret)


@pytest.mark.asyncio
async def test_ogg_page_separator_step_failure():
    pipe = wav_mulaw_file_source(example_file("testing.wav"))
    with pytest.raises(AudioFormatError):
        pipe = ogg_page_separator_step(pipe)
        await array_sink(pipe)


@pytest.mark.asyncio
async def test_ogg_concatenator_step(tmp_path):
    pipe1 = binary_file_source(example_file("tts1.ogg"))
    pipe2 = binary_file_source(example_file("tts2.ogg"))
    pipe = concat_step(pipe1, pipe2)
    pipe = ogg_page_separator_step(pipe)
    # pipe = log_step(pipe, "Buffer len", lambda x: len(x))
    pipe = ogg_concatenator_step(pipe)
    target = tmp_path.joinpath("tts_concat.ogg")
    await binary_file_sink(pipe, target)
    assert_files_equal(example_file("tts_concat.ogg"), target, mode="b")
