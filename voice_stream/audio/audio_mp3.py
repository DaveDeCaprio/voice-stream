import logging
from io import BytesIO

from mutagen.mp3 import MP3

logger = logging.getLogger(__name__)

# Bitrates and sampling rates values for different versions and layers
MP3_BITRATES = {
    "V1L1": [None, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    "V1L2": [None, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    "V1L3": [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    "V2L1": [None, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    "V2L2": [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    "V2L3": [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}

MP3_SAMPLING_RATES = {
    "V1": [44100, 48000, 32000],
    "V2": [22050, 24000, 16000],
    "V2.5": [11025, 12000, 8000],
}


def find_frame_boundaries(mp3_data):
    # Function to find frame boundaries
    # This is a simplified version and might need more robust handling
    info = MP3(BytesIO(mp3_data)).info
    boundaries = []
    index = 0
    while index < len(mp3_data):
        if mp3_data[index] == 0xFF and (mp3_data[index + 1] & 0xE0) == 0xE0:
            boundaries.append(index)
            # Simplified frame size calculation (actual calculation is more complex)
            frame_size = calculate_frame_size(
                mp3_data[index : index + 4], version=info.version, layer=info.layer
            )
            index += frame_size
        else:
            logger.warning(f"Invalid frame header at index {index}")
            index += 1
    return boundaries


def calculate_frame_size(header, version, layer):
    # Extracting information from the header
    bitrate_index = (header[2] >> 4) & 0x0F
    sampling_rate_index = (header[2] >> 2) & 0x03
    padding = (header[2] >> 1) & 0x01

    # Look up the bitrate and sampling rate
    key = f"V{version}L{layer}"
    bitrate = MP3_BITRATES[key][bitrate_index] * 1000
    sampling_rate = MP3_SAMPLING_RATES[f"V{version}"][sampling_rate_index]

    # Calculate frame size
    frame_size = 144 * bitrate // sampling_rate + padding
    return frame_size


def calculate_split_points(frame_boundaries, buffer_size, max_size):
    """
    Calculate the split points for chunking an MP3 buffer.

    Each chunk will be no larger than max_size. If a single frame is larger than max_size,
    it will be a chunk on its own.

    :param frame_boundaries: A list of integers representing the start of each MP3 frame.
    :param buffer_size: The total size of the MP3 buffer.
    :param max_size: The maximum size of each chunk.
    :return: A list of integers representing the split points in the buffer.
    """
    split_points = []
    current_chunk_start = 0

    for i, boundary in enumerate(frame_boundaries):
        next_boundary = (
            frame_boundaries[i + 1] if i + 1 < len(frame_boundaries) else buffer_size
        )
        frame_size = next_boundary - boundary

        if frame_size > max_size:
            # If a single frame is larger than max_size, it becomes its own chunk
            if current_chunk_start < boundary:
                split_points.append(boundary)
            split_points.append(next_boundary)
            current_chunk_start = next_boundary
        elif boundary - current_chunk_start + frame_size > max_size:
            # Start a new chunk
            split_points.append(boundary)
            current_chunk_start = boundary

    # Add the last boundary if there's remaining data
    if current_chunk_start < buffer_size:
        split_points.append(buffer_size)

    return split_points
