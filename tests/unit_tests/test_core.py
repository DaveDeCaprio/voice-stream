import asyncio
import logging
from asyncio import Future
from typing import AsyncIterator

import pytest

from tests.helpers import example_file, assert_files_equal
from voice_stream import (
    array_source,
    partition_step,
    array_sink,
    text_file_source,
    text_file_sink,
    fork_step,
    log_step,
    extract_value_step,
    concat_step,
    queue_source,
    queue_sink,
    merge_step,
    recover_exception_step,
    binary_file_source,
    binary_file_sink,
    async_init_step,
    map_step,
    filter_step,
    merge_as_dict_step,
)
from voice_stream.core import buffer_step
from voice_stream.types import EndOfStreamMarker

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_partition():
    source = array_source(range(4))
    even, odd = partition_step(source, lambda x: x % 2 == 0)
    even = await array_sink(even)
    odd = await array_sink(odd)
    assert even == [0, 2]
    assert odd == [1, 3]


@pytest.mark.asyncio
async def test_log_step():
    stream = array_source(range(4))
    stream = log_step(stream, "test")
    out = await array_sink(stream)
    assert out == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_log_step_every_n(caplog):
    stream = array_source(range(4))
    stream = log_step(stream, "test", every_nth_message=2)
    out = await array_sink(stream)
    assert out == [0, 1, 2, 3]
    assert caplog.record_tuples == [
        ("voice_stream.core", 20, "test: 0"),
        ("voice_stream.core", 20, "test: 2"),
    ]


@pytest.mark.asyncio
async def test_map_step():
    stream = array_source(range(4))
    stream = map_step(stream, lambda x: x + 2)
    out = await array_sink(stream)
    assert out == [2, 3, 4, 5]


@pytest.mark.asyncio
async def test_map_step_none():
    stream = array_source(range(4))
    stream = map_step(
        stream, lambda x: (x + 2) if x % 2 == 0 else None, ignore_none=False
    )
    out = await array_sink(stream)
    assert out == [2, None, 4, None]


@pytest.mark.asyncio
async def test_map_step_ignore():
    stream = array_source(range(4))
    stream = map_step(
        stream, lambda x: (x + 2) if x % 2 == 0 else None, ignore_none=True
    )
    out = await array_sink(stream)
    assert out == [2, 4]


@pytest.mark.asyncio
async def test_map_async_step():
    stream = array_source(range(4))

    async def add_two(x):
        await asyncio.sleep(0)
        return x + 2

    stream = map_step(stream, add_two)
    out = await array_sink(stream)
    assert out == [2, 3, 4, 5]


@pytest.mark.asyncio
async def test_materialize_value():
    stream = array_source(range(4))
    stream, f_value = extract_value_step(
        stream, lambda x: x, condition=lambda x: x == 2
    )
    out = await array_sink(stream)
    value = await f_value
    assert out == [0, 1, 2, 3]
    assert value == 2


@pytest.mark.asyncio
async def test_async_init_step():
    async def delayed_init(async_iter: AsyncIterator):
        await asyncio.sleep(0.1)
        return async_iter

    source = array_source(range(2))
    a = async_init_step(source, delayed_init)
    a = await array_sink(a)
    assert a == [0, 1]


@pytest.mark.asyncio
async def test_async_init_step_with_failure_in_init():
    async def delayed_init(async_iter: AsyncIterator):
        await asyncio.sleep(0.1)
        raise ValueError("Test")

    source = array_source(range(2))
    a = async_init_step(source, delayed_init)
    with pytest.raises(ValueError) as e:
        a = await array_sink(a)
    assert e.value.args[0] == "Test"


@pytest.mark.asyncio
async def test_async_init_step_with_future():
    async def increment_by_future(async_iter: AsyncIterator, inc_f: Future[int]):
        inc = await inc_f
        return map_step(async_iter, lambda x: x + inc)

    stream = array_source([2, 3, 4])
    stream, inc_f = extract_value_step(stream, lambda x: x)
    # Increment each element by the value of the first element.
    stream = async_init_step(stream, lambda x: increment_by_future(x, inc_f))
    out = await array_sink(stream)
    assert out == [4, 5, 6]


@pytest.mark.asyncio
async def test_fork_step_pull_from_all():
    source = array_source(range(2))
    a, b = fork_step(source, pull_from_all=True)
    a = await array_sink(a)
    b = await array_sink(b)
    assert a == [0, 1]
    assert b == [0, 1]


@pytest.mark.asyncio
async def test_fork_step():
    source = array_source(range(2))
    a, b = fork_step(source)
    a = await array_sink(a)
    b = await array_sink(b)
    assert a == [0, 1]
    assert b == [0, 1]


@pytest.mark.asyncio
async def test_echo_file(tmp_path):
    source = text_file_source(example_file("echo.ndjson"))
    sink = text_file_sink(source, tmp_path.joinpath("echo.ndjson"))
    await sink
    assert_files_equal(example_file("echo.ndjson"), tmp_path.joinpath("echo.ndjson"))


@pytest.mark.asyncio
async def test_echo_binary_file(tmp_path):
    source = binary_file_source(example_file("testing.wav"))
    sink = binary_file_sink(source, tmp_path.joinpath("echo.wav"))
    await sink
    assert_files_equal(
        example_file("testing.wav"), tmp_path.joinpath("echo.wav"), mode="b"
    )


@pytest.mark.asyncio
async def test_concat_step():
    stream1 = array_source([1, 2])
    stream2 = array_source([3, 4])
    stream = concat_step(stream1, stream2)
    out = await array_sink(stream)
    assert out == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_queues():
    source = asyncio.Queue()
    await source.put(1)
    await source.put(2)
    await source.put(3)
    await source.put(EndOfStreamMarker)
    stream = queue_source(source)
    dest = await queue_sink(stream)
    assert await dest.get() == 1
    assert await dest.get() == 2
    assert await dest.get() == 3
    assert await dest.get() == EndOfStreamMarker
    assert dest.empty()


@pytest.mark.asyncio
async def test_queue_source_put():
    source = queue_source()
    stream = array_sink(source)
    await source.put(1)
    await source.put(2)
    await source.put(EndOfStreamMarker)
    out = await stream
    assert out == [1, 2]


@pytest.mark.asyncio
async def test_queue_source_cancel():
    q = asyncio.Queue()
    e = asyncio.Event()
    source = queue_source(q, e)
    stream = array_sink(source)
    await q.put(1)
    await q.put(2)
    e.set()
    out = await stream
    assert out == [1, 2]


@pytest.mark.asyncio
async def test_queue_sink_no_end():
    stream = array_source([1, 2, 3])
    queue = await queue_sink(stream, send_end_of_stream=False)
    assert await queue.get() == 1
    assert await queue.get() == 2
    assert await queue.get() == 3
    assert queue.empty() == True


@pytest.mark.asyncio
async def test_merge_step():
    stream1 = array_source([1, 2])
    stream2 = array_source([3, 4])
    stream1 = log_step(stream1, "Pre-merge1")
    stream2 = log_step(stream2, "Pre-merge2")
    stream = merge_step(stream1, stream2)
    stream = log_step(stream, "Merged")
    out = await array_sink(stream)
    # This ordering technically isn't guaranteed, but seems to work.  If it fails, just leave the second assert.
    assert out == [1, 3, 2, 4]
    assert sorted(out) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_merge_as_dict_step():
    stream = array_source([1, 2, 3, 4, 5, 6])
    stream, evens = fork_step(stream)
    by_three, odds = fork_step(stream)
    evens = filter_step(evens, lambda x: x % 2 == 0)
    odds = filter_step(odds, lambda x: x % 2 == 1)
    by_three = filter_step(by_three, lambda x: x % 3 == 0)
    stream = merge_as_dict_step(
        {"last_even": evens, "last_odd": odds, "last_by_three": by_three}
    )
    out = await array_sink(stream)
    assert out == [
        {"last_even": 2, "last_odd": 1},
        {"last_even": 4, "last_odd": 3, "last_by_three": 3},
        {"last_even": 6, "last_odd": 5, "last_by_three": 6},
    ]


def _source_with_exception() -> AsyncIterator[int]:
    async def throw_exception():
        yield 1
        yield 2
        yield 3
        raise KeyError("Test")

    return throw_exception()


@pytest.mark.asyncio
async def test_recover_exception_step_no_failure():
    raised = None

    def set_raised(x):
        nonlocal raised
        raised = x

    stream = array_source([1, 2, 3])
    stream = recover_exception_step(stream, KeyError, set_raised)
    out = await array_sink(stream)
    assert out == [1, 2, 3]


@pytest.mark.asyncio
async def test_recover_exception_step():
    raised = None

    def set_raised(x):
        nonlocal raised
        raised = x
        return 4

    stream = _source_with_exception()
    stream = recover_exception_step(stream, KeyError, set_raised)
    out = await array_sink(stream)
    assert raised.args[0] == "Test"
    assert out == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_recover_exception_step_different_type():
    raised = None

    def set_raised(x):
        nonlocal raised
        raised = x

    stream = _source_with_exception()
    stream = recover_exception_step(stream, ValueError, set_raised)
    with pytest.raises(KeyError):
        await array_sink(stream)


@pytest.mark.asyncio
async def test_buffer_step():
    async def rate_limit_sink(ai):
        out = []
        async for item in ai:
            await asyncio.sleep(0.1)
            out.append(item)
        return out

    stream = array_source(["a", "b", "c", "d"])
    stream = buffer_step(stream, lambda x: "".join(x))
    stream = log_step(stream, "Test")
    out = await rate_limit_sink(stream)
    assert out == ["a", "bcd"]


@pytest.mark.asyncio
async def test_buffer_step_no_join():
    async def rate_limit_sink(ai):
        out = []
        async for item in ai:
            await asyncio.sleep(0.1)
            out.append(item)
        return out

    stream = array_source(["a", "b", "c", "d"])
    stream = buffer_step(stream)
    stream = log_step(stream, "Test")
    out = await rate_limit_sink(stream)
    assert out == ["a", "b", "c", "d"]
