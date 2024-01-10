import asyncio
import io
import logging
from typing import AsyncIterator, Union

from mutagen.mp3 import MP3

from voice_stream.audio.async_wav_file import (
    AsyncMuLawStreamWriter,
    AsyncMuLawStreamReader,
)
from voice_stream.audio import AudioFormatError, AudioFormat
from voice_stream.audio.audio_mp3 import find_frame_boundaries, calculate_split_points
from voice_stream.audio.audio_ogg import OggPage, OpusIdPacket
from voice_stream.basic_streams import FutureOrObj
from voice_stream.types import resolve_obj_or_future

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
        async for message in async_iter:
            # We wait to resolve the filename until we have a message to write
            if f is None:
                filename = await resolve_obj_or_future(filename)
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
    async_iter: AsyncIterator[bytes], chunk_size: FutureOrObj[int]
) -> AsyncIterator[bytes]:
    """Takes in MP3 data and splits it on MP3 frame boundaries, making chunks as large as possible, but not larger than max_size, unless an individual frame is larger than max_size."""
    async for data in async_iter:
        resolved_chunk_size = await resolve_obj_or_future(chunk_size)
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
    async for data in async_iter:
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

    async for data in async_iter:
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
                        header.output_channel_count != new_header.output_channel_count
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


def get_audio_length(audio_format: AudioFormat, audio: bytes):
    if audio_format == AudioFormat.WAV_MULAW_8KHZ:
        return len(audio) / 8000.0
    elif audio_format == AudioFormat.OGG_OPUS:
        first_page = OggPage.from_data(audio, 0)
        header = OpusIdPacket.from_ogg_page(first_page)
        page = OggPage.last_page_from_data(audio)
        return page.granule / float(header.input_sample_rate)
    elif audio_format == AudioFormat.MP3:
        return MP3(io.BytesIO(audio)).info.length
    else:
        raise AudioFormatError(
            f"Unsupported audio type '{audio_format}' for getting total audio length"
        )
