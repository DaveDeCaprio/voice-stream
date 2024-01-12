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
)
from voice_stream._substream_iters import ResettableIterator, SwitchableIterator

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
    ret = await sink
    assert ret == [1, 2, "a", "b"]


@pytest.mark.asyncio
async def test_substream():
    substream_ix = 0

    def mini_stream(async_iter):
        nonlocal substream_ix
        substream_ix += 1
        pipe = flatten_step(async_iter)
        pipe = map_step(pipe, lambda x: f"Sub {substream_ix}: {x}")
        return pipe

    pipe = array_source(["ab", "bc", "c"])
    pipe = substream_step(pipe, mini_stream)
    ret = await array_sink(pipe)
    assert ret == ["Sub 1: a", "Sub 1: b", "Sub 2: b", "Sub 2: c", "Sub 3: c"]


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

    pipe_instance = 1

    async def create_pipe(iter):
        nonlocal pipe_instance
        instance_count = pipe_instance
        pipe_instance += 1
        async for item in iter:
            await asyncio.sleep(0.2)
            yield f"Instance {instance_count}: {item}"

    pipe = cancelable_substream_step(generator(), cancel_generator(), create_pipe)
    pipe = log_step(pipe, "Output")
    ret = await array_sink(pipe)
    assert ret == ["Instance 1: 1", "Instance 3: 3", "Instance 4: 4"]


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

    pipe_instance = 1

    async def delay(async_iter):
        async for item in async_iter:
            await asyncio.sleep(0.1)
            yield item

    def create_pipe(iter):
        nonlocal pipe_instance
        instance_count = pipe_instance
        pipe_instance += 1
        pipe1, pipe2 = fork_step(iter)
        pipe1 = map_step(pipe1, lambda x: f"Instance {instance_count}: {x}")
        pipe1 = delay(pipe1)
        pipe2 = map_step(pipe2, lambda x: f"Alternate Instance {instance_count}: {x}")
        return pipe1, pipe2

    pipe1, pipe2 = cancelable_substream_step(
        generator(), cancel_generator(), create_pipe
    )
    pipe1 = array_sink(pipe1)
    pipe2 = array_sink(pipe2)
    result = await asyncio.gather(pipe1, pipe2)
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

    pipe_instance = 1

    async def create_pipe(iter):
        # logger.info("Creating substream")
        nonlocal pipe_instance
        instance_count = pipe_instance
        pipe_instance += 1
        async for item in iter:
            # logger.info("In substream")
            yield f"Substream {instance_count} Output 1: {item}"
            await asyncio.sleep(0.1)
            yield f"Substream {instance_count} Output 2: {item}"

    pipe = generator()
    pipe = log_step(pipe, "In")
    pipe = interruptable_substream_step(pipe, create_pipe, cancel_messages=["Cancel"])
    pipe = log_step(pipe, "Out")
    result = await array_sink(pipe)
    logger.info(f"Result: {result}")
    assert result == [
        "Substream 1 Output 1: 1",
        "Substream 1 Output 2: 1",
        "Cancel",
        "Substream 2 Output 1: 3",
        "Substream 2 Output 2: 3",
    ]
