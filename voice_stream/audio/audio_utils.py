import io
from enum import Enum

from mutagen.mp3 import MP3

from voice_stream.audio.audio_ogg import OggPage, OpusIdPacket


class AudioFormatError(Exception):
    """
    Indicates a problem related to audio formats.
    """

    pass


class AudioFormat(str, Enum):
    """
    A class representing an audio format as an Enum.
    """

    WAV_MULAW_8KHZ = "wav_mulaw_8khz"
    """WAV Telephone audio - mu-law encoded 8kHz."""

    OGG_OPUS = "ogg_opus"
    """Ogg container with Opus audio."""

    WEBM_OPUS = "webm_opus"
    """WebM container with Opus audio."""

    MP3 = "mp3"
    """MP3 audio format."""


def get_audio_length(audio_format: AudioFormat, audio: bytes):
    """
    Get the length of audio in seconds given the audio format and audio data.

    Parameters
    ----------
    audio_format : AudioFormat
        The format of audio data.
    audio : bytes
        The audio data.

    Returns
    -------
    float
        The length of the audio in seconds.

    Raises
    ------
    AudioFormatError
        If the audio format is not supported.
    """
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


def remove_wav_header(wav_bytes: bytes) -> bytes:
    """
    Removes the wav header from a wav file, regardless of the format.

    Parameters
    ----------
    wav_bytes
        The beginning of a WAV file, including the header.

    Returns
    -------
    bytes
        The audio bytes from the file, without the header.
    """
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
