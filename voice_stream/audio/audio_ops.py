import asyncio
import inspect
import logging
import time
from typing import AsyncIterator

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
    """
    Data flow source that reads audio bytes from a wav file.

    Parameters
    ----------
    filename : str
        Name of the audio file
    chunk_size : int
        Number of bytes to read at one time from the file.  Passing 0 indicates the whole file should be read at once.

    Returns
    -------
    AsyncIterator[bytes]
        A stream of audio bytes.


    Notes
    -------
    - The WAV header will be removed, so the data being passed will only include audio samples.
    """
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
    async_iter: AsyncIterator[bytes], filename: AwaitableOrObj[str]
) -> None:
    """
    Data flow sink that writes telephone audio (8Khz mu-law encoded audio) to a WAV file.

    Parameters
    ----------
    async_iter : str
        A stream containing the audio data to write.
    filename : str
        Name of the audio file.  Can be an `Awaitable[str]` if the filename isn't known at creation time (for example if it is generated based on data in the stream).

    Notes
    -------
    - Assumes only audio data is passed.  A WAV header will be placed before the audio to properly format the file.
    """
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
    """
    Data flow step that splits incoming MP3 data on MP3 frame boundaries.

    Takes incoming audio data and splits it into smaller chunks based on MP3 frame boundaries.  Attempts to keep
    outgoing bytes smaller than `chunk_size` but may be larger if an individual frame can't fit into a chunk.

    Parameters
    ----------
    async_iter :
        The MP3 data to be split into chunks

    chunk_size : int
        The maximum allowable chunk size.

    Returns
    -------
    AsyncIterator[bytes]
        The incoming data split into smaller chunks which are all complete MP3 frames.

    Notes
    -----
    - If an individual frame is larger than the chunk_size, it will not be split and the chunk can exceed chunk_size.
    """
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
    """
    Data flow step that splits incoming OGG data into distinct pages.

    Takes in a stream of bytes from an OGG media file and outputs bytes ensuring that each output is a complete page.
    Checks if the last page in each chunk sent is a full page, if so, it sends it.

    Parameters
    ----------
    async_iter
        Bytes from an OGG media file.

    Returns
    -------
    AsyncIterator[bytes]
        Bytes objects, each representing a full OGG page.

    Notes
    -----
    - If the data passed in contains a partial page at the end, that page data will be buffered until the next input.
    """
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
    """
    Data flow step that concatenates multiple OGG streams into one.

    With files in OGG format, you can't concatenate two different streams simply by concatenating the bytes.
    This step performs the necessary operations to concatenate streams.  It assumes data is coming in chunked into
    full OGG pages (the way :func:`~voice_stream.audio.ogg_page_separator_step` outputs it).

    Parameters
    ----------
    async_iter
        OGG pages as bytes objects

    Returns
    -------
    AsyncIterator[bytes]
        OGG pages, updated so that they form a single consistent stream.

    Notes
    -----
    - This could be done more efficiently by using numpy to modify the buffer in place.
    """
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


def audio_rate_limit_step(
    async_iter: AsyncIterator[bytes],
    audio_format: AwaitableOrObj[AudioFormat],
    buffer_seconds: float,
):
    """
    Data flow step that rate-limits the audio data coming in.

    This step takes in audio data and produces the same audio data with delays introduced so that the downstream
    iterator only gets `buffer_seconds` worth of audio at once.  Rate-limiting provides the ability to stop the audio
    stream due to an interruption or other event.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator returning bytes of audio data.

    audio_format : AwaitableOrObj[voice_stream.audio.AudioFormat]
       The format of the audio data.  Can be an Awaitable if the format isn't known when the step is created.

    buffer_seconds : float
        The amount of audio to pass to the downstream iterator.

    Returns
    -------
    audio
        The same audio bytes that came in, but rate-limited so that the downstream consumer only gets `buffer_seconds` worth of audio.

    Raises
    ------
    AudioFormatError
        If the audio format is not supported.

    Notes
    ------
    - This function will break up long chunks of data in a format-specific way to perform the rate-limiting.
    """

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
    """
    Data flow step that performs rate-liming on chunks of audio data coming in.

    This step rate limits input objects based on a given sample rate.  Generally, using :func:`~voice_stream.audio.audio_rate_limit_step`
     is preferred to using this step, as that step handles the details of different audio formats.  This step does not
     break up long chunks or handle differing formats.  It takes in bytes objects, determines the length of the audio based
     on `bytes_per_second` and outputs the identical chunks it got with a delay.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        The input audio data
    bytes_per_second: AwaitableOrObj[int],
        The playback rate of the audio in bytes.  This is used to compute the duration of the audio based on the length of the byte array.
    buffer_seconds : float
        The number of seconds of audio left before we send the next chunk.

    Note
    ----
    Usually, you will want to put a max size chunk step in before this.
    """
    last_send = time.perf_counter()
    queued_audio_seconds = 0

    def compute_remaining(now):
        """Compute the amount of audio remaining to be played in seconds."""
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
