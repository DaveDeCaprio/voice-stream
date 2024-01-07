from __future__ import annotations

import dataclasses
import logging
import struct

from voice_stream.audio import AudioFormatError

logger = logging.getLogger(__name__)


def __generate_ogg_crc_lookup():
    polynomial = 0x04C11DB7
    crc_lookup = []

    for i in range(256):
        crc = i << 24
        for _ in range(8, 0, -1):
            if crc & 0x80000000:
                crc = (crc << 1) ^ polynomial
            else:
                crc = crc << 1
            crc = crc & 0xFFFFFFFF  # Ensure CRC remains a 32-bit value
        crc_lookup.append(crc)

    return crc_lookup


OGG_CRC_LOOKUP = __generate_ogg_crc_lookup()


@dataclasses.dataclass
class OggPage:
    data: bytes
    offset: int
    header_type: bytes
    granule: int
    serial_number: int
    page_sequence_number: int
    num_segments: bytes
    segment_lengths: list[int]
    header_length: int
    page_length: int

    @classmethod
    def from_data(cls, data: bytes, offset: int):
        # OGG page header structure:
        # 0-3 bytes: capture pattern (OggS)
        # 4 byte: stream structure version
        # 5 byte: header type flag
        # 6-13 bytes: granule position
        # 14-17 bytes: bitstream serial number
        # 18-21 bytes: page sequence number
        # 22-25 bytes: checksum (to be recalculated)
        # 26 byte: page segments
        if data[offset : offset + 4] != b"OggS":
            raise AudioFormatError(
                f"Invalid OGG page.  Expected 'OggS' header but got {data[offset:offset+4]}"
            )
        version = data[offset + 4]
        if version != 0:
            raise AudioFormatError(f"Last known OGG versions is 0.  {version} found.")
        header_type = data[offset + 5]
        granule = struct.unpack("<Q", data[offset + 6 : offset + 14])[0]
        serial_number = struct.unpack("<I", data[offset + 14 : offset + 18])[0]
        page_sequence_number = struct.unpack("<I", data[offset + 18 : offset + 22])[0]
        num_segments = data[offset + 26]
        segment_lengths = [data[offset + 27 + i] for i in range(num_segments)]
        header_length = 27 + num_segments
        page_length = header_length + sum(segment_lengths)
        return cls(
            data,
            offset,
            header_type,
            granule,
            serial_number,
            page_sequence_number,
            num_segments,
            segment_lengths,
            header_length,
            page_length,
        )

    def get_bytes(self) -> bytes:
        if self.offset == 0 and len(self.data) == self.page_length:
            return self.data
        else:
            return self.data[self.offset : self.offset + self.page_length]

    def update(
        self, new_header_type: bytes, granule_offset: int, sequence_offset: int
    ) -> OggPage:
        new_granule = granule_offset + self.granule
        granule_bytes = struct.pack("<Q", new_granule)
        new_sequence_number = sequence_offset + self.page_sequence_number
        sequence_bytes = struct.pack("<I", new_sequence_number)
        new_data = (
            self.data[self.offset : self.offset + 5]
            + struct.pack("<B", new_header_type)
            + granule_bytes
            + self.data[self.offset + 14 : self.offset + 18]
            + sequence_bytes
            + b"\x00\x00\x00\x00"
            + self.data[self.offset + 26 : self.offset + self.page_length]
        )
        checksum = self._compute_ogg_crc_checksum(new_data)
        checksum_bytes = struct.pack("<I", checksum)
        new_data = new_data[:22] + checksum_bytes + new_data[26:]
        return OggPage(
            new_data,
            0,
            new_header_type,
            new_granule,
            self.serial_number,
            new_sequence_number,
            self.num_segments,
            self.segment_lengths,
            self.header_length,
            self.page_length,
        )

    def log(self):
        checksum_matched = self.is_checksum_valid()
        logger.info(
            f"OGG page: offset={self.offset}, len={self.page_length}, header_type={self.header_type}, granule={self.granule}, serial_number={self.serial_number}, page_sequence_number={self.page_sequence_number}, checksum={checksum_matched}, num_segments={self.num_segments}, segment_lengths={self.segment_lengths}"
        )

    def is_checksum_valid(self):
        checksum = struct.unpack("<I", self.data[self.offset + 22 : self.offset + 26])[
            0
        ]
        return self.compute_checksum() == checksum

    def compute_checksum(self):
        checksum_buffer = (
            self.data[self.offset : self.offset + 22]
            + b"\x00\x00\x00\x00"
            + self.data[self.offset + 26 : self.offset + self.page_length]
        )
        return self._compute_ogg_crc_checksum(checksum_buffer)

    @classmethod
    def find_last_page(cls, data: bytes):
        return data.rfind(b"OggS")

    @classmethod
    def last_page_from_data(cls, data: bytes):
        position = data.rfind(b"OggS")
        return cls.from_data(data, position)

    @classmethod
    def is_full_page(cls, data: bytes, offset: int):
        """Determine if the data buffer contains the full OGG page.  It can contain extra bytes."""
        data_len = len(data)
        if data_len < offset + 27:
            return False
        num_segments = data[offset + 26]
        if data_len < offset + 27 + num_segments:
            return False
        segment_lengths = [data[offset + 27 + i] for i in range(num_segments)]
        header_length = 27 + num_segments
        page_length = header_length + sum(segment_lengths)
        return data_len >= offset + page_length

    @classmethod
    def _compute_ogg_crc_checksum(cls, data):
        checksum = 0
        for byte in data:
            tbl_idx = ((checksum >> 24) ^ byte) & 0xFF
            checksum = (OGG_CRC_LOOKUP[tbl_idx] ^ (checksum << 8)) & 0xFFFFFFFF

        return checksum


@dataclasses.dataclass
class OpusIdPacket:
    data: bytes
    offset: int
    output_channel_count: bytes
    pre_skip: int
    input_sample_rate: int
    output_gain: int
    channel_mapping_family: bytes

    @classmethod
    def is_opus_encoded(cls, data: bytes, offset: int) -> bool:
        return data[offset : offset + 8] == b"OpusHead"

    @classmethod
    def from_ogg_page(cls, page: OggPage) -> OpusIdPacket:
        return cls.from_data(page.data, page.offset + page.header_length)

    @classmethod
    def from_data(cls, data: bytes, offset: int) -> OpusIdPacket:
        header = data[offset : offset + 8]
        if header != b"OpusHead":
            raise AudioFormatError(
                f"Invalid Opus ID packet header '{header}'.  Should be 'OpusHead'."
            )
        version = data[offset + 8]
        if version != 1:
            raise AudioFormatError(f"Last known OPUS versions is 1.  {version} found.")
        output_channel_count = data[offset + 9]
        pre_skip = struct.unpack("<H", data[offset + 10 : offset + 12])[0]
        input_sample_rate = struct.unpack("<I", data[offset + 12 : offset + 16])[0]
        output_gain = struct.unpack("<H", data[offset + 16 : offset + 18])[0]
        channel_mapping_family = data[offset + 18]
        assert (
            channel_mapping_family == 0
        ), f"Channel mapping is not yet supported.  Channel mapping is {channel_mapping_family}"
        # if channel_mapping_family != 0:
        #     stream_count = data[offset+20]
        #     coupled_count = data[offset+21]
        #     channel_mapping = [data[offset+22+i] for i in range(output_channel_count)]
        return cls(
            data,
            offset,
            output_channel_count,
            pre_skip,
            input_sample_rate,
            output_gain,
            channel_mapping_family,
        )

    def log(self):
        logger.info(
            f"Opus ID packet: offset={self.offset}, output_channel_count={self.output_channel_count}, pre_skip={self.pre_skip}, input_sample_rate={self.input_sample_rate}, output_gain={self.output_gain}, channel_mapping_family={self.channel_mapping_family}"
        )


@dataclasses.dataclass
class OpusCommentPacket:
    data: bytes
    offset: int
    vendor_string: bytes
    user_comment_list: list[bytes]

    @classmethod
    def from_data(cls, data: bytes, offset: int) -> OpusCommentPacket:
        header = data[offset : offset + 8]
        assert (
            header == b"OpusTags"
        ), f"Invalid Opus comment header '{header}'.  Should be 'OpusTags'."
        vendor_length = struct.unpack("<I", data[offset + 8 : offset + 12])[0]
        vendor_string = data[offset + 12 : offset + 12 + vendor_length]
        user_comment_list_length = struct.unpack(
            "<I", data[offset + 12 + vendor_length : offset + 16 + vendor_length]
        )[0]
        user_comment_list = []
        for i in range(user_comment_list_length):
            comment_length = struct.unpack(
                "<I",
                data[
                    offset
                    + 16
                    + vendor_length
                    + i * 4 : offset
                    + 20
                    + vendor_length
                    + i * 4
                ],
            )[0]
            comment_string = data[
                offset
                + 20
                + vendor_length
                + i * 4 : offset
                + 20
                + vendor_length
                + i * 4
                + comment_length
            ]
            user_comment_list.append(comment_string)
        return cls(data, offset, vendor_string, user_comment_list)

    def log(self):
        logger.info(
            f"Opus comment header: offset={self.offset}, vendor_string={self.vendor_string}, user_comment_list={self.user_comment_list}"
        )
