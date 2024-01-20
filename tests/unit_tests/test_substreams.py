import asyncio
import logging

import pytest

from voice_stream import (
    array_sink,
    map_step,
    fork_step,
    array_source,
    flatten_step,
    log_step,
    substream_step,
    cancelable_substream_step,
    interruptable_substream_step,
    concat_step,
)
from voice_stream._substream_iters import ResettableIterator, SwitchableIterator
from voice_stream.substreams import exception_handling_substream

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_resettable_iterator():
    async def generator():
        yield 1
        await asyncio.sleep(0.2)
        yield 2
        await asyncio.sleep(0.2)
        yield 3
        await asyncio.sleep(0.2)
        yield 4

    iterator = ResettableIterator(generator())
    sink1 = asyncio.create_task(array_sink(iterator))
    await asyncio.sleep(0.3)
    iterator.reset()
    logger.info(f"Iterator is reset")
    sink2 = asyncio.create_task(array_sink(iterator))
    ret1 = await sink1
    assert ret1 == [1, 2]
    ret2 = await sink2
    assert ret2 == [3, 4]


@pytest.mark.asyncio
async def test_switchable_iterator():
    async def generator():
        yield 1
        await asyncio.sleep(0.2)
        yield 2
        await asyncio.sleep(0.2)
        yield 3
        await asyncio.sleep(0.2)
        yield 4

    async def generator2():
        yield "a"
        await asyncio.sleep(0.2)
        yield "b"

    iterator = SwitchableIterator(generator())
    sink = asyncio.create_task(array_sink(iterator))
    await asyncio.sleep(0.3)
    iterator.disconnect()
    iterator.switch(generator2())
    out = await sink
    assert out == [1, 2, "a", "b"]


@pytest.mark.asyncio
async def test_substream():
    substream_ix = 0

    def mini_stream(async_iter):
        nonlocal substream_ix
        substream_ix += 1
        stream = flatten_step(async_iter)
        stream = map_step(stream, lambda x: f"Sub {substream_ix}: {x}")
        return stream

    stream = array_source(["ab", "bc", "c"])
    stream = substream_step(stream, mini_stream)
    out = await array_sink(stream)
    assert out == ["Sub 1: a", "Sub 1: b", "Sub 2: b", "Sub 2: c", "Sub 3: c"]


@pytest.mark.asyncio
async def test_cancellable_substream():
    async def generator():
        yield 1
        yield 2
        yield 3
        yield 4

    async def cancel_generator():
        await asyncio.sleep(0.3)
        logger.debug("Sending cancel")
        yield 1

    stream_instance = 1

    async def create_stream(iter):
        nonlocal stream_instance
        instance_count = stream_instance
        stream_instance += 1
        async for item in iter:
            logger.debug(f"Got item {item}")
            await asyncio.sleep(0.2)
            ret = f"Instance {instance_count}: {item}"
            yield ret

    stream = cancelable_substream_step(generator(), cancel_generator(), create_stream)
    stream = log_step(stream, "Output")
    out = await array_sink(stream)
    assert out == ["Instance 1: 1", "Instance 3: 3", "Instance 4: 4"]


@pytest.mark.asyncio
async def test_cancellable_substream_multi_output():
    async def generator():
        yield 1
        yield 2
        yield 3
        yield 4

    async def cancel_generator():
        await asyncio.sleep(0.15)
        yield 1

    stream_instance = 1

    async def delay(async_iter):
        async for item in async_iter:
            await asyncio.sleep(0.1)
            yield item

    def create_stream(iter):
        nonlocal stream_instance
        instance_count = stream_instance
        stream_instance += 1
        stream1, stream2 = fork_step(iter)
        stream1 = map_step(stream1, lambda x: f"Instance {instance_count}: {x}")
        stream1 = delay(stream1)
        stream2 = map_step(
            stream2, lambda x: f"Alternate Instance {instance_count}: {x}"
        )
        return stream1, stream2

    stream1, stream2 = cancelable_substream_step(
        generator(), cancel_generator(), create_stream
    )
    stream1 = array_sink(stream1)
    stream2 = array_sink(stream2)
    result = await asyncio.gather(stream1, stream2)
    logger.info(f"Result: {result}")
    assert result[0] == [
        "Instance 1: 1",
        "Instance 3: 3",
        "Instance 4: 4",
    ]
    assert result[1] == [
        "Alternate Instance 1: 1",
        "Alternate Instance 2: 2",
        "Alternate Instance 3: 3",
        "Alternate Instance 4: 4",
    ]


@pytest.mark.asyncio
async def test_interruptable_substream_step():
    async def generator():
        yield 1
        await asyncio.sleep(0.2)
        yield 2
        yield 3
        await asyncio.sleep(0.2)
        yield 4

    stream_instance = 1

    async def create_stream(iter):
        # logger.info("Creating substream")
        nonlocal stream_instance
        instance_count = stream_instance
        stream_instance += 1
        async for item in iter:
            # logger.info("In substream")
            yield f"Substream {instance_count} Output 1: {item}"
            await asyncio.sleep(0.1)
            yield f"Substream {instance_count} Output 2: {item}"

    stream = generator()
    stream = log_step(stream, "In")
    stream = interruptable_substream_step(
        stream, create_stream, cancel_messages=["Cancel"]
    )
    stream = log_step(stream, "Out")
    result = await array_sink(stream)
    logger.info(f"Result: {result}")
    assert result == [
        "Substream 1 Output 1: 1",
        "Substream 1 Output 2: 1",
        "Cancel",
        "Substream 2 Output 1: 3",
        "Substream 2 Output 2: 3",
    ]


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)


@pytest.mark.asyncio
async def test_exception_handling_substream_no_error():
    stream = array_source([1, 2, 3])

    def new_sub(stream):
        stream = log_step(stream, "In sub")
        return map_step(stream, lambda x: x + 1)

    stream = exception_handling_substream(stream, new_sub, [lambda x: x])
    out = await array_sink(stream)
    assert out == [2, 3, 4]


@pytest.mark.asyncio
async def test_exception_handling_substream():
    async def gen():
        yield 1
        yield 2
        yield 3
        yield 4

    async def sub_with_ex(stream):
        async for item in stream:
            if item == 3:
                raise ValueError("3 is not allowed")
            yield item

    stream = gen()
    stream = exception_handling_substream(
        stream, sub_with_ex, [lambda x: [f"Error {x.args[0]}"]]
    )
    out = await array_sink(stream)
    assert out == [1, 2, "Error 3 is not allowed", 4]
