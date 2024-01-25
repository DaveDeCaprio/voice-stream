import collections
import io
import logging

import av

logger = logging.getLogger(__name__)


def split_webm_buffer(
    audio: bytes, split_before: int, adjust_timestamps: bool = False
) -> bytes:
    """Returns a valid webm stream that strips off roughly `split_before` bytes from the stream.

    Locates the final key frame before `split_before` and creates a new WEBM stream starting at that point.
    Does not do any decoding, so it runs fast.

    Parameters
    ----------
    audio: bytes
        A byte string with the data
    split_before: int
        The split point.  The new webm stream will contain all bytes after the split point, and some from before.
    """

    # Figure out where the header ends
    orig_data_start, _ = find_first_webm_simple_block(audio)

    # Find last key frame before the split.
    new_data_start, _ = find_last_webm_simple_block(
        audio, split_before, keys_frames_only=True, full_frames_only=True
    )

    logger.debug(
        f"Spliting {len(audio)} audio bytes at {new_data_start} (cutoff was {split_before}).  Header is {orig_data_start} bytes"
    )
    return audio[:orig_data_start] + audio[new_data_start:]

    # Original implementation with pyav
    # last_start, size = find_last_webm_simple_block(audio)
    # if len(audio) == last_start + size:
    #     # If the last block was a full block, use the whole thing
    #     logger.debug("Last block was full")
    #     last_start += size
    # usable_audio = audio[:last_start]
    # extra_bytes = audio[last_start:]
    #
    # # Open the input file
    # input_container = av.open(io.BytesIO(usable_audio))
    #
    # # Find the audio stream
    # audio_stream = next((s for s in input_container.streams if s.type == "audio"), None)
    # if audio_stream is None:
    #     raise ValueError("No audio stream found in the WEBM container")
    #
    # # Process and buffer the audio frames
    # packets_since_last_keyframe = []
    # byte_ptr = 0
    # key_frame_start = -1
    # for packet in input_container.demux(audio_stream):
    #     if packet.is_keyframe and byte_ptr < split_before:
    #         packets_since_last_keyframe = []
    #         key_frame_start = byte_ptr
    #     byte_ptr += packet.size
    #     packets_since_last_keyframe.append(packet)
    # logger.debug(
    #     f"Split {len(audio)} audio bytes at {key_frame_start} (cutoff was {split_before}).  {len(packets_since_last_keyframe)} packets included. {len(extra_bytes)} extra bytes"
    # )
    #
    # # Open the output file
    # output_buffer = io.BytesIO()
    # output_container = av.open(output_buffer, mode="w", format="webm")
    # output_container.add_stream(template=audio_stream)
    #
    # # Write the frames from the buffer
    # dts_start = packets_since_last_keyframe[0].dts
    # pts_start = packets_since_last_keyframe[0].pts
    # for packet in packets_since_last_keyframe:
    #     if adjust_timestamps and packet.dts is not None:
    #         packet.dts = packet.dts - dts_start
    #         packet.pts = packet.pts - pts_start
    #     output_container.mux(packet)
    #
    # output_container.close()
    # # PyAV adds a "Cues" section at the end that we don't want.  Cut that off
    # raw = output_buffer.getvalue()
    # pos, size = find_last_webm_simple_block(raw)
    # assert (
    #     len(raw) >= pos + size
    # ), f"Last block should always be a full block.  Internal error."
    # ret = raw[: pos + size] + extra_bytes
    # return ret


def find_first_webm_simple_block(data):
    """
    Searches in a bytes object to find the first occurrence of a "Simple block" webm element.



    `mkvinfo` was really helpful in figuring this out.

    :param data: The bytes object to search.
    :param end: Position to start search backwards from.  If None, starts at the end of the data.
    :return: The position of the '0xA3' byte if found, otherwise -1.
    """
    pos = 0

    while True:
        pos = data.find(b"\xA3", pos)
        if pos == -1:
            # No more occurrences of '0xA3'
            return -1, None

        size = is_webm_simple_block_header(data, pos)
        if size != -1:
            return pos, size

        # Update the search range to exclude the current '0xA3' position
        pos += 1


def find_last_webm_simple_block(
    data,
    end: int = None,
    keys_frames_only: bool = False,
    full_frames_only: bool = False,
):
    """
    Searches backwards in a bytes object to find the last occurrence of
    a "Simple block" webm element.

    Looks for "a3", followed by a 1 or 2 byte length, A variable length in less than 5, then skip two bytes and look for 80 or 0.

    `mkvinfo` was really helpful in figuring this out.

    :param data: The bytes object to search.
    :param end: Position to start search backwards from.  If None, starts at the end of the data.
    :return: A tuple of the position of the '0xA3' byte if found, otherwise -1 and then the size (None is pos is -1)
    """
    l = end or len(data)
    pos = l

    while True:
        pos = data.rfind(b"\xA3", 0, pos)
        if pos == -1:
            # No more occurrences of '0xA3'
            return -1, None
        # logger.debug(f"Checking {pos:x}")
        size = is_webm_simple_block_header(data, pos, l, is_key_frame=keys_frames_only)
        if size != -1:
            # logger.debug(f"Found block at {pos}")
            if not full_frames_only or pos + size <= l:
                return pos, size

        # Update the search range to exclude the current '0xA3' position
        pos -= 1


def is_webm_simple_block_header(
    data, pos, end: int = None, is_key_frame: bool = False
) -> int:
    """Returns the length of the header or -1 if it isn't a header.

    Looks for "a3", followed by a 1 or 2 byte length, A variable length in less than 5, then skip two bytes and look for 80 or 0.
    """
    l = end or len(data)
    if data[pos] != 0xA3:
        logger.debug("Initial byte didn't match")
        return -1
    if pos + 5 < l:
        size, size_bytes = read_ebml_size(data, pos + 1)
        if size is not None:
            track, track_bytes = read_ebml_size(data, pos + 1 + size_bytes)
            if (
                track is not None and track < 10
            ):  # Something is fishy if there are more than 10 tracks
                flag_pos = pos + 1 + size_bytes + track_bytes + 2
                if flag_pos < l:
                    flag = data[pos + 1 + size_bytes + track_bytes + 2]
                    key_frame = flag | 0x80
                    if (
                        flag - key_frame == 0x00
                    ):  # We expect the only flag set is key_frame.
                        if key_frame or not is_key_frame:
                            return size + 1 + size_bytes
    return -1


def read_ebml_size(data, position, max_bytes=2):
    """
    Reads a variable-length integer from an EBML stream.

    Returns None as the value if you hit the end of stream or the value is larger than max_bytes bytes in length.

    :param data: The bytes object containing the EBML data.
    :param position: The position in the data where the size field starts.
    :param max_bytes: The maximum number of expected bytes.  Throws ValueError if this is off.
    :return: The interpreted size value and the number of bytes.
    """
    # Extract the first byte
    first_byte = data[position]

    # Count leading zeros to determine the number of bytes in the size field
    num_bytes = 1
    for bit in range(7, -1, -1):
        if (first_byte >> bit) & 1:
            break
        num_bytes += 1

    if num_bytes > max_bytes:
        return None, num_bytes

    # If num_bytes is 0, it means the size is in this single byte
    if num_bytes == 1:
        return first_byte & 0x7F, 1  # Mask out the marker bit

    # Read the size field bytes
    if len(data) < position + num_bytes:
        return None, num_bytes
    size_bytes = data[position : position + num_bytes]

    # Calculate the size value
    size_value = 0
    for i, byte in enumerate(size_bytes):
        if i == 0:
            # For the first byte, mask out the marker bits
            size_value = byte & (0xFF >> (num_bytes + 1))
        else:
            size_value = (size_value << 8) | byte

    return size_value, num_bytes
