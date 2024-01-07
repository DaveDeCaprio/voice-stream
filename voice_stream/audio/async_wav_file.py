import asyncio
import logging
import struct
from concurrent.futures import ThreadPoolExecutor

import aiofiles

logger = logging.getLogger(__name__)


class AsyncMuLawStreamReader:
    def __init__(self, filename, chunk_size=4096):
        self.filename = filename
        self.chunk_size = chunk_size
        self._file = None

    async def open(self):
        self._file = await aiofiles.open(self.filename, "rb")
        # RIFF header
        riff_chunk_id = await self._file.read(4)
        if riff_chunk_id != b"RIFF":
            raise Exception("No RIFF header found")
        riff_chunk_size = struct.unpack("<I", await self._file.read(4))[0]

        wave_format = await self._file.read(4)
        if wave_format != b"WAVE":
            raise Exception("Not a WAVE file")

        # read fmt chunk
        fmt_chunk_id = await self._file.read(4)
        if fmt_chunk_id != b"fmt ":
            raise Exception("fmt chunk missing")

        fmt_chunk_size = struct.unpack("<I", await self._file.read(4))[0]
        self._audioformat = struct.unpack("<H", await self._file.read(2))[0]
        self._numchannels = struct.unpack("<H", await self._file.read(2))[0]
        self._samplerate = struct.unpack("<I", await self._file.read(4))[0]
        self._byterate = struct.unpack("<I", await self._file.read(4))[0]
        self._bytespersample = struct.unpack("<H", await self._file.read(2))[0]
        self._bitspersample = struct.unpack("<H", await self._file.read(2))[0]
        if fmt_chunk_size == 18:
            self._extraparams = struct.unpack("<H", await self._file.read(2))[0]
            fact_chunk_id = await self._file.read(4)
            if fact_chunk_id != b"fact":
                raise Exception("fact chunk missing")

            fact_chunk_size = struct.unpack("<I", await self._file.read(4))[0]
            self._samplelength = struct.unpack("<I", await self._file.read(4))[0]
        data_chunk_id = await self._file.read(4)
        if data_chunk_id != b"data":
            raise Exception("data chunk missing")
        data_chunk_size = struct.unpack("<I", await self._file.read(4))[0]
        if self._samplelength == 0:  # no fact chunk
            self._samplelength = data_chunk_size
        logger.info(f"Opened {self.filename} with {self._samplelength} samples")

    async def read(self):
        if not self._file:
            raise Exception("Wave file not opened. Call open() method first.")
        data = await self._file.read(self.chunk_size)
        return data

    async def close(self):
        if self._file:
            await self._file.close()


class AsyncMuLawStreamWriter:
    def __init__(
        self, filename, channels=1, sample_rate=8000, bits_per_sample=8, audio_format=7
    ):
        self.filename = filename
        self._numofchannels = channels
        self._samplerate = sample_rate
        self._bitspersample = bits_per_sample
        if audio_format != 1 and audio_format != 6 and audio_format != 7:
            raise Exception("Unsupported audio format")
        self._audioformat = audio_format
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.loop = asyncio.get_event_loop()
        self._file = None
        self._datawritten = 0

    async def open(self):
        self._file = await aiofiles.open(self.filename, "wb")
        await self._file.write(b"RIFF")
        self._form_length_pos = await self._file.tell()
        if self._audioformat == 1:
            await self._file.write(
                struct.pack(
                    "<L4s4sLHHLLHH4s",
                    36 + self._datawritten,
                    b"WAVE",
                    b"fmt ",
                    16,
                    self._audioformat,
                    self._numofchannels,
                    self._samplerate,
                    int(
                        self._numofchannels
                        * self._samplerate
                        * (self._bitspersample / 8)
                    ),
                    int(self._numofchannels * (self._bitspersample / 8)),
                    self._bitspersample,
                    b"data",
                )
            )
        elif self._audioformat == 6 or self._audioformat == 7:
            await self._file.write(
                struct.pack(
                    "<L4s4sLHHLLHHH4sLL4s",
                    50 + self._datawritten,
                    b"WAVE",
                    b"fmt ",
                    18,
                    self._audioformat,
                    self._numofchannels,
                    self._samplerate,
                    int(
                        self._numofchannels
                        * self._samplerate
                        * (self._bitspersample / 8)
                    ),
                    int(self._numofchannels * (self._bitspersample / 8)),
                    self._bitspersample,
                    0,
                    b"fact",
                    4,
                    self._datawritten,
                    b"data",
                )
            )
        self._data_length_pos = await self._file.tell()
        await self._file.write(struct.pack("<L", self._datawritten))

    async def write(self, audio_data):
        if not self._file:
            raise Exception("Wave file not opened. Call open() method first.")

        await self._file.write(audio_data)
        self._datawritten += len(audio_data)

    async def close(self):
        if self._file:
            await self._patchheader()
            await self._file.close()

    async def _patchheader(self):
        curpos = await self._file.tell()
        await self._file.seek(self._form_length_pos, 0)
        await self._file.write(struct.pack("<L", 36 + self._datawritten))
        await self._file.seek(self._data_length_pos, 0)
        await self._file.write(struct.pack("<L", self._datawritten))
        await self._file.seek(curpos, 0)
