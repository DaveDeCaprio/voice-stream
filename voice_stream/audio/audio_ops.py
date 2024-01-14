import asyncio
import inspect
import logging
import time
from typing import AsyncIterator, Union

import asyncstdlib

from voice_stream import (
    chunk_bytes_step,
    async_init_step,
    extract_value_step,
    substream_step,
)
from voice_stream.audio.async_wav_file import (
    AsyncMuLawStreamWriter,
    AsyncMuLawStreamReader,
)
from voice_stream.audio.audio_mp3 import find_frame_boundaries, calculate_split_points
from voice_stream.audio.audio_ogg import OggPage, OpusIdPacket
from voice_stream.audio.audio_utils import (
    AudioFormatError,
    AudioFormat,
    get_audio_length,
)
from voice_stream.types import resolve_awaitable_or_obj, AwaitableOrObj, map_future

logger = logging.getLogger(__name__)


async def wav_mulaw_file_source(
    filename: str, chunk_size: int = 4096
) -> AsyncIterator[bytes]:
    """Reads a wav file and returns a stream of audio bytes"""
    f = AsyncMuLawStreamReader(filename, chunk_size=chunk_size)
    try:
        await f.open()
        while True:
            data = await f.read()
            if not data:
                break
            # logger.debug(f"Read {len(data)} bytes from {filename}")
            yield data
    finally:
        await f.close()


async def wav_mulaw_file_sink(
    async_iter: AsyncIterator[bytes], filename: Union[str, asyncio.Future[str]]
) -> None:
    """Writes a stream of audio bytes to a wav file"""
    f = None
    try:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for message in owned_aiter:
                # We wait to resolve the filename until we have a message to write
                if f is None:
                    filename = await resolve_awaitable_or_obj(filename)
                    f = AsyncMuLawStreamWriter(filename)
                    await f.open()
                if message is None:
                    break
                # logger.debug(f"Wrote {len(message)} bytes to {filename}")
                await f.write(message)
    finally:
        if f is not None:
            await f.close()
        logger.info(f"Closed {filename}")


async def mp3_chunk_step(
    async_iter: AsyncIterator[bytes], chunk_size: AwaitableOrObj[int]
) -> AsyncIterator[bytes]:
    """Takes in MP3 data and splits it on MP3 frame boundaries, making chunks as large as possible, but not larger than max_size, unless an individual frame is larger than max_size."""
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for data in owned_aiter:
            resolved_chunk_size = await resolve_awaitable_or_obj(chunk_size)
            boundaries = find_frame_boundaries(data)
            splits = calculate_split_points(boundaries, len(data), resolved_chunk_size)
            split_start = 0
            for split_end in splits:
                yield data[split_start:split_end]
                split_start = split_end
            assert split_end == len(data)


async def ogg_page_separator_step(
    async_iter: AsyncIterator[bytes],
) -> AsyncIterator[bytes]:
    """Takes in a stream of bytes from an OGG media file and outputs bytes ensuring that each output is a complete page.
    Checks if the last page in each chunk sent is a full page, if so, it sends it."""
    buffer = b""
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for data in owned_aiter:
            concatenated = buffer + data
            if concatenated[:4] != b"OggS":
                raise AudioFormatError(
                    f"Bytes didn't start with a proper OggS head.  Expected 'OggS, got {concatenated[:4]}"
                )
            position = concatenated.rfind(b"OggS")
            if OggPage.is_full_page(concatenated, position):
                position = len(concatenated)
            buffer = concatenated[position:]
            if position > 0:
                yield concatenated[:position]
    if len(buffer) > 0:
        yield buffer


async def ogg_concatenator_step(
    async_iter: AsyncIterator[bytes],
) -> AsyncIterator[bytes]:
    """With files in OGG format, you can't concatenate the bytes.  This performs the necessary operations to concatenate streams.
    This step assumes data is coming in chunked into full OGG pages.  If it is not, put an ogg_page_separator_step before.

    This could be done more efficiently by using numpy to modify the buffer in place."""
    sequence_offset = 0
    granule_offset = 0
    header = None

    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for data in owned_aiter:
            # Iterate through each ogg page and update.
            position = 0
            pages = []
            while position < len(data):
                page = OggPage.from_data(data, position)
                page_header_type = page.header_type
                position += page.page_length
                if page.page_sequence_number == 0:
                    if not OpusIdPacket.is_opus_encoded(
                        data, page.offset + page.header_length
                    ):
                        raise AudioFormatError(
                            "OGG file is not OPUS encoded.  Only Opus is currently supported."
                        )
                    new_header = OpusIdPacket.from_data(
                        data, page.offset + page.header_length
                    )
                    if header is not None:
                        if (
                            header.output_channel_count
                            != new_header.output_channel_count
                            or header.input_sample_rate != new_header.input_sample_rate
                            or header.output_gain != new_header.output_gain
                            or header.channel_mapping_family
                            != new_header.channel_mapping_family
                        ):
                            raise AudioFormatError(
                                "Cant concatenate OGG streams with different headers."
                            )
                if sequence_offset and page.page_sequence_number < 2:
                    logger.debug("skipping opus header for later sequence")
                    continue
                if sequence_offset:
                    page = page.update(
                        new_header_type=0,
                        granule_offset=granule_offset,
                        sequence_offset=sequence_offset,
                    )
                    # page.log()
                if page_header_type == 4:
                    sequence_offset = sequence_offset + page.page_sequence_number
                    granule_offset = granule_offset + page.granule
                pages.append(page)
            logger.debug(f"Adjusted {len(pages)} OGG pages")
            adjusted = b"".join(_.get_bytes() for _ in pages)
            yield adjusted


def remove_wav_header(wav_bytes: bytes) -> bytes:
    """Removes the wav header from a wav file, regardless of the format."""
    # Check if it's a valid RIFF file
    if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise ValueError("Invalid WAV file")

    # Find the "data" chunk
    index = 12
    while index < len(wav_bytes):
        chunk_id = wav_bytes[index : index + 4]
        chunk_size = int.from_bytes(wav_bytes[index + 4 : index + 8], "little")
        if chunk_id == b"data":
            # Found the "data" chunk, return its content
            start = index + 8  # Skip "data" chunk header
            return wav_bytes[start : start + chunk_size]
        # logger.info(f"Skipping chunk {chunk_id}")
        index += 8 + chunk_size  # Move to the next chunk

    raise ValueError("WAV file does not contain a 'data' chunk")


def audio_rate_limit_step(
    async_iter: AsyncIterator[bytes],
    audio_format: AwaitableOrObj[AudioFormat],
    buffer_seconds: float,
):
    def init(async_iter, af):
        if af == AudioFormat.WAV_MULAW_8KHZ:
            SAMPLE_RATE = 8000
            audio = chunk_bytes_step(async_iter, int(buffer_seconds * SAMPLE_RATE))
            audio = raw_audio_rate_limit_step(
                audio, SAMPLE_RATE, buffer_seconds=buffer_seconds
            )
        elif af == AudioFormat.OGG_OPUS:
            audio = _opus_rate_limit_step(async_iter, buffer_seconds=buffer_seconds)
        elif af == AudioFormat.MP3:
            audio = _mp3_rate_limit_step(async_iter, buffer_seconds=buffer_seconds)
        else:
            raise AudioFormatError(f"Unsupported audio format: {audio_format}")
        return audio

    async def async_init(async_iter):
        af = await resolve_awaitable_or_obj(audio_format)
        return init(async_iter, af)

    if inspect.isawaitable(audio_format):
        return async_init_step(async_iter, async_init)
    else:
        return init(async_iter, audio_format)


def _opus_rate_limit_step(async_iter: AsyncIterator[bytes], buffer_seconds: float):
    def get_bytes_per_second(data):
        duration = get_audio_length(AudioFormat.OGG_OPUS, data)
        length_in_bytes = len(data)
        return int(length_in_bytes / duration)

    def opus_substream(async_iter: AsyncIterator[bytes]):
        stream, bytes_per_second_f = extract_value_step(
            async_iter, get_bytes_per_second
        )
        chunk_size_f = map_future(
            bytes_per_second_f,
            lambda bytes_per_second: int(buffer_seconds * bytes_per_second / 2),
        )
        stream = chunk_bytes_step(stream, chunk_size_f)
        # stream = log_step(stream, "Audio Chunk", lambda x: len(x))
        stream = raw_audio_rate_limit_step(
            stream, bytes_per_second_f, buffer_seconds=buffer_seconds
        )
        stream = ogg_page_separator_step(stream)
        # stream = log_step(stream, "Full OGG Page", lambda x: len(x))
        return stream

    out = substream_step(async_iter, opus_substream)
    return out


def _mp3_rate_limit_step(async_iter: AsyncIterator[bytes], buffer_seconds: float):
    def get_bytes_per_second(data):
        seconds = get_audio_length(AudioFormat.MP3, data)
        length_in_bytes = len(data)
        return int(length_in_bytes / seconds)

    def mp3_substream(async_iter: AsyncIterator[bytes]):
        stream, bytes_per_second_f = extract_value_step(
            async_iter, get_bytes_per_second
        )
        chunk_size_f = map_future(
            bytes_per_second_f,
            lambda bytes_per_second: int(buffer_seconds * bytes_per_second / 2),
        )
        stream = mp3_chunk_step(stream, chunk_size_f)
        stream = raw_audio_rate_limit_step(
            stream, bytes_per_second_f, buffer_seconds=buffer_seconds
        )
        return stream

    out = substream_step(async_iter, mp3_substream)
    return out


async def raw_audio_rate_limit_step(
    async_iter: AsyncIterator[bytes],
    bytes_per_second: AwaitableOrObj[int],
    buffer_seconds: AwaitableOrObj[float],
) -> AsyncIterator[bytes]:
    """Limits the rate of sending audio bytes down the stream.  Note that this step always sends a full chunk.
    buffer_seconds is the number of seconds of audio left before we send the next chunk.  Usually, you will want to put
    a max size chunk step in before this.  buffer_seconds should be large enough to make sure the send executes.
    """
    last_send = time.perf_counter()
    queued_audio_seconds = 0

    def compute_remaining(now):
        # Compute the amount of audio remaining to be played in seconds.
        return max(0, queued_audio_seconds - (now - last_send))

    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            resolved_buffer_seconds = await resolve_awaitable_or_obj(buffer_seconds)
            now = time.perf_counter()
            # Compute the amount of audio remaining to be played in seconds.
            remaining_audio_seconds = compute_remaining(now)
            # If we have more than the buffer, sleep until we hit the buffer limit
            if remaining_audio_seconds > resolved_buffer_seconds:
                await asyncio.sleep(remaining_audio_seconds - resolved_buffer_seconds)
                # We don't know how long we actually slept.
                now = time.perf_counter()
                remaining_audio_seconds = compute_remaining(now)
            resolved_bytes_per_second = await resolve_awaitable_or_obj(bytes_per_second)
            queued_audio_seconds = (
                remaining_audio_seconds + len(item) / resolved_bytes_per_second
            )
            last_send = now
            yield item
