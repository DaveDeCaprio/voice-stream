from enum import Enum


class AudioFormatError(Exception):
    pass


class AudioFormat(str, Enum):
    WAV_MULAW_8KHZ = "wav_mulaw_8khz"
    OGG_OPUS = "ogg_opus"
    MP3 = "mp3"
