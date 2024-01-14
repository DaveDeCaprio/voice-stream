import io
from enum import Enum

from mutagen.mp3 import MP3

from voice_stream.audio.audio_ogg import OggPage, OpusIdPacket


class AudioFormatError(Exception):
    pass


class AudioFormat(str, Enum):
    WAV_MULAW_8KHZ = "wav_mulaw_8khz"
    OGG_OPUS = "ogg_opus"
    WEBM_OPUS = "webm_opus"
    MP3 = "mp3"


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
