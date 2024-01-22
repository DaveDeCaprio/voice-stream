import asyncio
import logging
from typing import (
    AsyncIterator,
    Callable,
    Tuple,
    Optional,
    List,
    Union,
    Any,
)

from voice_stream._substream_iters import SwitchableIterator, ResettableIterator
from voice_stream.core import (
    single_source,
    queue_source,
    concat_step,
    empty_sink,
    recover_exception_step,
    log_step,
    empty_source,
)
from voice_stream.types import (
    T,
    Output,
    to_source,
    to_tuple,
    from_tuple,
    SourceConvertable,
    EndOfStreamMarker,
    OptionalMultipleOutputs,
)

logger = logging.getLogger(__name__)


async def substream_on_dict_key_step(
    async_iter: AsyncIterator[dict],
    key: str,
    substream_func: Callable[[AsyncIterator[Any]], AsyncIterator[Any]],
) -> AsyncIterator[dict]:
    """
    Data flow step that updates a value in a dictionary with the result of a substream.

    This step takes in a dictionary and produces a new dictionary that has one key modified.  The modified value comes
    from running a substream on the existing value.

    Parameters
    ----------
    async_iter : AsyncIterator[dict]
        An asynchronous iterator that yields dictionaries.
    key : str
        The key in the dictionary on which to perform the substreaming.
    substream_func : callable
        A function that takes an AsyncIterator and returns a stream based off that iterator.

    Returns
    -------
    AsyncIterator[dict]
        An asynchronous iterator that yields the modified dictionaries.

    Example
    -------
    >>> def substream(async_iter):
    ...     return map_step(async_iter, lambda x: x+2)
    >>> stream = array_source([{'a', 1, 'b':2}])
    >>> stream = substream_on_dict_key_step(stream, "b", substream)
    >>> out = await array_sink(stream)
    >>> assert out == [{'a', 1, 'b':4}]
    """
    current_dict = None

    async def input_gen():
        async for item in async_iter:
            nonlocal current_dict
            current_dict = item
            yield item[key]

    stream = input_gen()
    stream = substream_func(stream)
    async for item in stream:
        out = {**current_dict, key: item}
        yield out


async def substream_step(
    async_iter: AsyncIterator[T],
    substream_func: Callable[[AsyncIterator[T]], AsyncIterator[Output]],
) -> AsyncIterator[Output]:
    """
    Data flow step that runs a new stream on each item.

    A substream is useful when you want to group steps together for error handling or flow control.  This step calls the
    substream_func to create a new substream for each item from the source iterator.  The output of this step is the
    output of the substreams.  Each instance of the substream only gets one input value.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An asynchronous iterator.
    substream_func : str
        A function that takes an AsyncIterator and creates a stream off of it.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator over the values produced by the substreams.

    Returns
    ----------
    >>> instance_count = 0
    >>> def substream(async_iter):
    ...     nonlocal instance_count
    ...     instance_count += 1
    ...     return map_step(async_iter, lambda x: x+instance_count)
    >>> stream = array_source([1,1,1])
    >>> stream = substream(stream, substream)
    >>> out = await array_sink(stream)
    >>> assert out == [2, 3, 4]
    """
    async for item in async_iter:
        stream = single_source(item)
        stream = substream_func(stream)
        async for sub_item in stream:
            yield sub_item


def cancelable_substream_step(
    async_iter: AsyncIterator[T],
    cancel_iter: AsyncIterator[T],
    substream_func: Callable[[AsyncIterator[T]], Union[AsyncIterator[Output], Tuple]],
    cancel_messages: Optional[List[SourceConvertable]] = None,
) -> OptionalMultipleOutputs:
    """
    Data flow step that runs a substream for each input, but takes a second iterator which causes the current substream to cancel.

    Calls the `substream_func` to create a new substream for each item from the source iterator.  If any item is produced
    from the `cancel_iter` during the processing of this substream, the substream is immediately stopped.  When a stop occurs,
    `cancel_messages` are optionally sent down each output stream.

    Parameters
    ----------
    async_iter
        The input AsyncIterator which we want to create substreams for.

    cancel_iter
        The cancel stream.  If an item appears on this iterator, the processing of the current substream is immediately stopped.

    substream_func
        The function used to generate AsyncIterators for each substream.

    cancel_messages
        An optional list of items to produce in the stream when a substream is cancelled.  If present, this must be a list
        which has the same length as the number of outputs returns by `substream_func`.  Each element will determine how cancels
        our signaled down that particular data stream.  If an AsyncIterator is passed, that iterator will be put into the stream.
        If any other object is passed, that signal object will be sent.  If None is passed, then nothing will be sent down the stream.

    Returns
    -------
     OptionalMultipleOutputs
        Either a single AsyncIterator or a tuple of multiple AsyncIterators.  The length is determined by the number of
        iterators returns from the substream_func.

    Notes
    -----
    - If you want to explicitly send `None` when a cancel occurs, use a :func:`~voice_stream:none_source`.

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
                    logger.debug("Substream canceled - sending cancel messages.")
                    _switch_outputs(output_iters, cancel_iters)
                else:
                    logger.debug(
                        "Ignoring cancel because there is no active substream."
                    )
            except Exception as e:
                logger.error(f"Error in cancelable_substream: {e}", exc_info=True)

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
            await next_source.put(EndOfStreamMarker)
            await substream_completed.wait()
            next_source = queue_source()
            next_substream = to_tuple(substream_func(next_source))
        monitor_cancel_task.cancel()
        await next_source.put(EndOfStreamMarker)
        await asyncio.wait([asyncio.create_task(empty_sink(i)) for i in next_substream])
        for i in output_iters:
            i.end_iteration()

    asyncio.create_task(gen())
    return from_tuple(output_iters)


def interruptable_substream_step(
    async_iter: AsyncIterator[T],
    substream_func: Callable[
        [AsyncIterator[T]],
        Callable[[AsyncIterator[T]], Union[AsyncIterator[Output], Tuple]],
    ],
    cancel_messages: Optional[List[SourceConvertable]] = None,
) -> OptionalMultipleOutputs:
    """
    Data flow step that creates a substream which will get interrupted if a new value comes in.

    For each input, creates a new substream and runs it.  If a new input is available before the substream completes,
    this cancels the existing substream and starts a new one.  This is similar to :func:`~voice_stream.cancelable_substream_step`
    except that it uses the same iterator for input values and to trigger cancellation.

    Parameters
    ----------
    async_iter
        The input AsyncIterator which we want to create substreams for.

    substream_func
        The function used to generate AsyncIterators for each substream.

    cancel_messages
        An optional list of items to produce in the stream when a substream is cancelled.  If present, this must be a list
        which has the same length as the number of outputs returns by `substream_func`.  Each element will determine how cancels
        our signaled down that particular data stream.  If an AsyncIterator is passed, that iterator will be put into the stream.
        If any other object is passed, that signal object will be sent.  If None is passed, then nothing will be sent down the stream.

    Returns
    -------
     OptionalMultipleOutputs
        Either a single AsyncIterator or a tuple of multiple AsyncIterators.  The length is determined by the number of
        iterators returns from the substream_func.
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
        async for item in async_iter:
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
            await active_source.put(EndOfStreamMarker)
            next_source = queue_source()
            next_substream = to_tuple(substream_func(next_source))
        logger.debug("Completed interruptable substream iter")
        for i in output_iters:
            i.end_iteration()

    logger.debug("Creating task")
    asyncio.create_task(gen())
    return from_tuple(output_iters)


def exception_handling_substream(
    async_iterator: AsyncIterator[T],
    substream_func: Callable[
        [AsyncIterator[T]],
        Callable[[AsyncIterator[T]], Union[AsyncIterator[Output], Tuple]],
    ],
    exception_handlers: List[Callable[[BaseException], List[Any]]],
    max_exceptions: Optional[int] = None,
):
    exception_count = 0
    end_of_iter = False

    lock = asyncio.Lock()

    async def mark_end_of_iter(aiter):
        try:
            logger.debug(f"Waiting for lock")
            async with lock:
                logger.debug(f"Got lock")
                async for item in aiter:
                    yield item
            logger.debug(f"Released lock cleanly")
        except BaseException as e:
            logger.debug(f"Released lock through exception")
            raise e
        finally:
            logger.debug(f"Released lock/Iteration ended")
            nonlocal end_of_iter
            end_of_iter = True

    async_iterator = ResettableIterator(mark_end_of_iter(async_iterator))

    def new_substreams():
        if end_of_iter:
            logger.debug("End of iteration was reached.  New substreams are empty")
            return [empty_source() for _ in range(len(output_iters))]
        else:
            substreams = to_tuple(substream_func(async_iterator))
            return [
                recover_exception_step(
                    stream, Exception, lambda x: exception_received(x, ix)
                )
                for ix, stream in enumerate(substreams)
            ]

    async def exception_received(e, ix):
        logger.exception(f"Exception in stream #{ix} received {e}")
        nonlocal exception_count
        exception_count += 1
        if max_exceptions and exception_count > max_exceptions:
            logger.info(
                f"Exceeded the maximum of {max_exceptions} exception retries.  Throwing exception"
            )
            raise e
        # When an exception is received, recreate the stream and reset the outputs.
        async_iterator.reset()
        logger.debug("Reset made")
        await async_iterator.confirm_reset()
        logger.debug("Reset confirmed")
        nonlocal substreams
        exeception_result = exception_handlers[ix](e)
        assert len(exeception_result) == len(
            substreams
        ), "The exception handler must return a list of outputs, one for each output stream."
        substreams = [
            concat_step(to_source(result), stream)
            for result, stream in zip(exeception_result, new_substreams())
        ]
        logger.debug("Switching outputs after cancel")
        _switch_outputs(output_iters, substreams)
        logger.debug(f"{len(output_iters)} Outputs switched")
        for i in output_iters:
            try:
                await i.wait_for_state_change()
            except BaseException as e:
                logger.exception(f"Error waiting for state change {e}")
                raise e
            finally:
                logger.debug("Done waiting for state change, but maybe an exception?")
        logger.debug("Switch completed")
        return None

    substreams = new_substreams()
    output_iters = [
        SwitchableIterator(s, propagate_end_of_iter=True) for s in substreams
    ]

    ret = from_tuple(output_iters)
    return ret


def _create_cancel_messages(
    outputs: List[AsyncIterator], cancel_messages: Optional[List[SourceConvertable]]
):
    """
    The cancel_messages list must have the same length as the outputs list, indicating which output to cancel. If cancel_messages is not provided, it defaults to None.

    The output cancel messages are converted to the appropriate type using the to_source() function.
    """
    if cancel_messages and len(cancel_messages) != len(outputs):
        raise ValueError(
            f"cancel_messages must be the same length as the number of outputs for the substream.  Got {len(cancel_messages)} cancel messages and {len(outputs)} substream outputs."
        )

    return [to_source(_) for _ in cancel_messages]


def _switch_outputs(
    switchable_iters: List[SwitchableIterator], new_outputs: List[AsyncIterator]
):
    """
    Switch the outputs of `switchable_iters` with the provided `new_outputs`.
    """
    assert len(new_outputs) == len(switchable_iters)
    for switchable_iter, new_output in zip(switchable_iters, new_outputs):
        switchable_iter.switch(new_output)
