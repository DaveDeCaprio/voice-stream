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

    Attributes
    ----------
    WAV_MULAW_8KHZ : str
        WAV Telephone audio - mu-law encoded 8kHz.
    OGG_OPUS : str
        Ogg container with Opus audio.
    WEBM_OPUS : str
        WebM container with Opus audio.
    MP3 : str
        MP3 audio format.
    """

    WAV_MULAW_8KHZ = "wav_mulaw_8khz"
    OGG_OPUS = "ogg_opus"
    WEBM_OPUS = "webm_opus"
    MP3 = "mp3"


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
