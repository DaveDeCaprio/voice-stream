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
    exception_handler_step,
    binary_file_source,
    binary_file_sink,
    async_init_step,
    map_step,
    filter_step,
    merge_as_dict_step,
)

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
async def test_log_source():
    pipe = array_source(range(4))
    pipe = log_step(pipe, "test")
    ret = await array_sink(pipe)
    assert ret == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_map_step():
    pipe = array_source(range(4))
    pipe = map_step(pipe, lambda x: x + 2)
    ret = await array_sink(pipe)
    assert ret == [2, 3, 4, 5]


@pytest.mark.asyncio
async def test_map_step_none():
    pipe = array_source(range(4))
    pipe = map_step(pipe, lambda x: (x + 2) if x % 2 == 0 else None, ignore_none=False)
    ret = await array_sink(pipe)
    assert ret == [2, None, 4, None]


@pytest.mark.asyncio
async def test_map_step_ignore():
    pipe = array_source(range(4))
    pipe = map_step(pipe, lambda x: (x + 2) if x % 2 == 0 else None, ignore_none=True)
    ret = await array_sink(pipe)
    assert ret == [2, 4]


@pytest.mark.asyncio
async def test_map_async_step():
    pipe = array_source(range(4))

    async def add_two(x):
        await asyncio.sleep(0)
        return x + 2

    pipe = map_step(pipe, add_two)
    ret = await array_sink(pipe)
    assert ret == [2, 3, 4, 5]


@pytest.mark.asyncio
async def test_materialize_value():
    pipe = array_source(range(4))
    pipe, f_value = extract_value_step(pipe, lambda x: x, condition=lambda x: x == 2)
    ret = await array_sink(pipe)
    value = await f_value
    assert ret == [0, 1, 2, 3]
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
async def test_async_init_step_with_future():
    async def increment_by_future(async_iter: AsyncIterator, inc_f: Future[int]):
        inc = await inc_f
        return map_step(async_iter, lambda x: x + inc)

    pipe = array_source([2, 3, 4])
    pipe, inc_f = extract_value_step(pipe, lambda x: x)
    # Increment each element by the value of the first element.
    pipe = async_init_step(pipe, lambda x: increment_by_future(x, inc_f))
    ret = await array_sink(pipe)
    assert ret == [4, 5, 6]


@pytest.mark.asyncio
async def test_fork_step():
    source = array_source(range(2))
    a, b = fork_step(source, backpressure=False)
    a = await array_sink(a)
    b = await array_sink(b)
    assert a == [0, 1]
    assert b == [0, 1]


@pytest.mark.asyncio
async def test_fork_step_backpressure():
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
    pipe1 = array_source([1, 2])
    pipe2 = array_source([3, 4])
    pipe = concat_step(pipe1, pipe2)
    ret = await array_sink(pipe)
    assert ret == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_queues():
    source = asyncio.Queue()
    await source.put(1)
    await source.put(2)
    await source.put(3)
    await source.put(None)
    pipe = queue_source(source)
    dest = await queue_sink(pipe)
    assert await dest.get() == 1
    assert await dest.get() == 2
    assert await dest.get() == 3
    assert await dest.get() is None
    assert dest.empty()


@pytest.mark.asyncio
async def test_queue_source_put():
    source = queue_source()
    pipe = array_sink(source)
    await source.put(1)
    await source.put(2)
    await source.put(None)
    ret = await pipe
    assert ret == [1, 2]


@pytest.mark.asyncio
async def test_merge_step():
    pipe1 = array_source([1, 2])
    pipe2 = array_source([3, 4])
    pipe = merge_step(pipe1, pipe2)
    ret = await array_sink(pipe)
    # This ordering technically isn't guaranteed, but seems to work.  If it fails, just leave the second assert.
    assert ret == [1, 3, 2, 4]
    assert sorted(ret) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_merge_as_dict_step():
    pipe = array_source([1, 2, 3, 4, 5, 6])
    pipe, evens = fork_step(pipe)
    by_three, odds = fork_step(pipe)
    evens = filter_step(evens, lambda x: x % 2 == 0)
    odds = filter_step(odds, lambda x: x % 2 == 1)
    by_three = filter_step(by_three, lambda x: x % 3 == 0)
    pipe = merge_as_dict_step(
        {"last_even": evens, "last_odd": odds, "last_by_three": by_three}
    )
    ret = await array_sink(pipe)
    assert ret == [
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
async def test_handle_exception_step_no_failure():
    raised = None

    def set_raised(x):
        nonlocal raised
        raised = x

    pipe = array_source([1, 2, 3])
    pipe = exception_handler_step(pipe, KeyError, set_raised)
    ret = await array_sink(pipe)
    assert ret == [1, 2, 3]


@pytest.mark.asyncio
async def test_handle_exception_step():
    raised = None

    def set_raised(x):
        nonlocal raised
        raised = x

    pipe = _source_with_exception()
    pipe = exception_handler_step(pipe, KeyError, set_raised)
    ret = await array_sink(pipe)
    assert raised.args[0] == "Test"


@pytest.mark.asyncio
async def test_handle_exception_step_different_type():
    raised = None

    def set_raised(x):
        nonlocal raised
        raised = x

    pipe = _source_with_exception()
    pipe = exception_handler_step(pipe, ValueError, set_raised)
    with pytest.raises(KeyError):
        await array_sink(pipe)
