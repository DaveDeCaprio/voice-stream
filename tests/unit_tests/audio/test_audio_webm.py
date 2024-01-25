import logging

from tests.helpers import example_file, assert_files_equal
from voice_stream.audio.audio_webm import (
    split_webm_buffer,
    read_ebml_size,
    find_last_webm_simple_block,
    is_webm_simple_block_header,
)

logger = logging.getLogger(__name__)


def test_webm_split(tmp_path):
    with open(example_file("testing.webm"), "rb") as f:
        data = f.read()
    out = split_webm_buffer(data, 5000)
    # with open(example_file('testing_cut_out.webm'), 'wb') as f:
    #     f.write(out)
    assert out[-20:] == data[-20:]


def test_webm_split_a(tmp_path):
    with open(example_file("split_a.webm"), "rb") as f:
        data = f.read()
    section = data[:179871]
    out = split_webm_buffer(section, 82940)
    # with open(example_file('split_a_out.webm'), 'wb') as f:
    #     f.write(out)
    actual = out[-3000:]
    expected = section[-3000:]
    for ix, (a, e) in enumerate(zip(actual, expected)):
        if a != e:
            ap = len(out) - 3000 + ix
            ep = len(section) - 3000 + ix
            logger.debug(f"Difference {a} vs {e} at {ap:x} {ep:x}")
    assert out[-2000:] == section[-2000:]


def test_is_web_simple_block_header():
    with open(example_file("testing.webm"), "rb") as f:
        data = f.read()
    assert is_webm_simple_block_header(data, 0x9FF7) == 1087


def test_find_last_simple_block():
    with open(example_file("testing.webm"), "rb") as f:
        data = f.read()
    pos, size = find_last_webm_simple_block(data)
    logger.debug(f"Last block is at {pos} and is {size} bytes long")
    assert pos == 0x9FF7
    assert size == 1087
    pos, size = find_last_webm_simple_block(data, pos)
    logger.debug(f"Second to last block is at {pos} and is {size} bytes long")
    assert pos == 0x9C2E
    assert size == 969
    assert 0x9C2E + 969 == 0x9FF7


def test_read_ebml_size():
    b = bytes([0x43, 0xC6, 0x81, 0x44, 0x3C, 0x00])
    assert read_ebml_size(b, 0) == (966, 2)
    assert read_ebml_size(b, 2) == (1, 1)
    assert read_ebml_size(b, 3) == (1084, 2)
    assert read_ebml_size(b, 5) == (None, 9)
