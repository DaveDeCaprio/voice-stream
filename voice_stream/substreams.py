import asyncio
import logging
from typing import (
    AsyncIterator,
    Callable,
    Tuple,
    Any,
    Optional,
    List,
    Union,
)

from voice_stream._substream_iters import SwitchableIterator
from voice_stream.basic_streams import (
    single_source,
    queue_source,
    concat_step,
    empty_sink,
)
from voice_stream.types import (
    T,
    Output,
    to_source,
    to_tuple,
    from_tuple,
    SourceConvertable,
)

logger = logging.getLogger(__name__)


async def substream_on_dict_key_step(
    async_iter: AsyncIterator[dict], key: str, substream_func
) -> AsyncIterator[dict]:
    current_dict = None

    async def input_gen():
        async for item in async_iter:
            nonlocal current_dict
            current_dict = item
            yield item[key]

    pipe = input_gen()
    pipe = substream_func(pipe)
    async for item in pipe:
        ret = {**current_dict, key: item}
        yield ret


async def substream_step(async_iter: AsyncIterator[T], substream_func):
    """For each item in the input iterator, creates a substream and feeds the item into it."""
    async for item in async_iter:
        pipe = single_source(item)
        pipe = substream_func(pipe)
        async for sub_item in pipe:
            yield sub_item


def cancelable_substream_step(
    async_iter: AsyncIterator[T],
    cancel_iter: AsyncIterator[T],
    substream_func: Callable[[AsyncIterator[T]], Union[AsyncIterator[Output], Tuple]],
    cancel_messages: Optional[List[SourceConvertable]] = None,
):
    """Creates a new substream for each input to async_iter.  If any item comes in on cancel_iter, it immediately stops
    the processing of the current substream, and optionally sends cancel_messages.
    Returns as many AsyncIterators as are returned by the substream func.
    """

    substream_completed = asyncio.Event()

    async def monitor_cancel():
        nonlocal next_substream, completed_outputs
        async for _ in cancel_iter:
            try:
                if completed_outputs < len(output_iters):
                    for i in output_iters:
                        i.disconnect()
                    cancel_iters = _create_cancel_messages(
                        output_iters, cancel_messages
                    )
                    completed_outputs = 0
                    for o, c in zip(output_iters, cancel_iters):
                        o.switch(c)
                else:
                    logger.debug(
                        "Ignoring cancel because there is no active substream."
                    )
            except Exception as e:
                logger.error(f"Error in cancelable_substream: {e}")

    def on_output_complete():
        # logger.debug("on_output_complete")
        nonlocal completed_outputs
        completed_outputs += 1
        if completed_outputs == len(output_iters):
            substream_completed.set()

    next_source = queue_source()
    next_substream = to_tuple(substream_func(next_source))
    output_iters = [
        SwitchableIterator(
            None, callback=on_output_complete, propagate_end_of_iter=False
        )
        for _ in next_substream
    ]
    completed_outputs = len(output_iters)
    cancel_messages = (
        cancel_messages if cancel_messages else [None for _ in output_iters]
    )

    monitor_cancel_task = asyncio.create_task(monitor_cancel())

    async def gen():
        nonlocal next_source, next_substream, completed_outputs
        async for item in async_iter:
            completed_outputs = 0
            substream_completed.clear()
            _switch_outputs(output_iters, next_substream)
            await next_source.put(item)
            await next_source.put(None)
            await substream_completed.wait()
            next_source = queue_source()
            next_substream = to_tuple(substream_func(next_source))
        monitor_cancel_task.cancel()
        await next_source.put(None)
        await asyncio.wait([empty_sink(i) for i in next_substream])
        for i in output_iters:
            i.end_iteration()

    asyncio.create_task(gen())
    return from_tuple(output_iters)


def interruptable_substream_step(
    async_iterator: AsyncIterator[T],
    substream_func: Callable[
        [AsyncIterator[T]],
        Callable[[AsyncIterator[T]], Union[AsyncIterator[Output], Tuple]],
    ],
    cancel_messages: Optional[List[SourceConvertable]] = None,
):
    """For each input, creates a new substream and runs it.
    If a new item comes in, the old item is immediately cancelled and a new one is created.
    """

    completed_outputs = 0

    def on_output_complete():
        nonlocal completed_outputs
        completed_outputs += 1

    active_source = None
    next_source = queue_source()
    next_substream = to_tuple(substream_func(next_source))
    # logger.debug(f"Created substream {next_substream}")
    output_iters = [
        SwitchableIterator(_, callback=on_output_complete, propagate_end_of_iter=False)
        for _ in next_substream
    ]

    async def gen():
        nonlocal active_source, next_source, next_substream, completed_outputs
        async for item in async_iterator:
            if active_source:
                if cancel_messages and completed_outputs < len(output_iters):
                    cancel_iters = _create_cancel_messages(
                        output_iters, cancel_messages
                    )
                    next_substream = [
                        concat_step(cancel_iter, output)
                        for output, cancel_iter in zip(next_substream, cancel_iters)
                    ]
                completed_outputs = 0
                _switch_outputs(output_iters, next_substream)
            # logger.debug("Running substream")
            active_source = next_source
            await active_source.put(item)
            await active_source.put(None)
            next_source = queue_source()
            next_substream = to_tuple(substream_func(next_source))
        logger.debug("Completed interruptable substream iter")
        for i in output_iters:
            i.end_iteration()

    logger.debug("Creating task")
    asyncio.create_task(gen())
    return from_tuple(output_iters)


def _create_cancel_messages(
    outputs: List[AsyncIterator], cancel_messages: Optional[List[SourceConvertable]]
):
    if cancel_messages and len(cancel_messages) != len(outputs):
        raise ValueError(
            f"cancel_messages must be the same length as the number of outputs for the substream.  Got {len(cancel_messages)} cancel messages and {len(outputs)} substream outputs."
        )

    return [to_source(_) for _ in cancel_messages]


def _switch_outputs(
    switchable_iters: List[SwitchableIterator], new_outputs: List[AsyncIterator]
):
    assert len(new_outputs) == len(switchable_iters)
    for switchable_iter, new_output in zip(switchable_iters, new_outputs):
        switchable_iter.switch(new_output)
