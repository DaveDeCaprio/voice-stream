import asyncio
import inspect
import json
import logging
import time
from asyncio import QueueEmpty, CancelledError
from typing import (
    AsyncIterator,
    Any,
    Tuple,
    Callable,
    Union,
    Optional,
    Type,
    Iterable,
    Coroutine,
    List,
)

import aiofiles
import asyncstdlib

from voice_stream.queue_with_exception import QueueWithException
from voice_stream.types import (
    to_tuple,
    resolve_awaitable_or_obj,
    T,
    Output,
    AwaitableOrObj,
    EndOfStreamMarker,
    is_async_iterator,
    to_source,
    format_current_task,
    format_stack_trace,
    background_task,
    cancel_with_confirmation,
)

logger = logging.getLogger(__name__)

# Streams are an abstraction on top of ASyncIterators.
# Sources are iterators.
# Sinks take an iterator.
# Steps take iterators and return iterators


def empty_source() -> AsyncIterator[T]:
    """
    Data flow source that returns an empty asynchronous iterator.

    This function provides a utility to create an empty asynchronous iterator. The returned iterator will immediately
    signal the end of iteration when iterated over, as it contains no elements.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator that yields no items and immediately ends iteration.

    Examples
    --------
    >>> stream = empty_source()
    >>> done = await array_sink(stream)
    >>> assert done == []

    Notes
    -----
    - The generic type `T` in `AsyncIterator[T]` indicates that the function can theoretically return
      an iterator of any type, but since it's initialized with an empty list, no items of any type are yielded.
    """
    return array_source([])


def none_source() -> AsyncIterator[None]:
    """
    Data flow source that yields a single None value.

    This function is a simple utility for generating an asynchronous iterator that yields exactly one item,
    which is `None` before signaling the end of iteration.  This is useful when you want to send 'None' as a
    cancel signal to a substream function.

    Returns
    -------
    AsyncIterator[None]
        An asynchronous iterator that yields a single item, `None`.

    Examples
    --------
    >>> stream = empty_source()
    >>> done = await array_sink(stream)
    >>> assert done == [None]

    Notes
    -----
    - The type `T` in `AsyncIterator[T]` is a placeholder indicating the iterator can be of any type.
      In this specific case, the iterator yields items of type `NoneType`.

    See Also
    --------
    :func:`~voice_stream.interruptable_substream_step`
    :func:`~voice_stream.cancelable_substream_step`
    """
    return array_source([None])


async def empty_sink(async_iter: AsyncIterator[T]) -> None:
    """
    Data flow sink that performs no action on the received items.

    This function asynchronously iterates over all items from the provided iterator, effectively 'emptying' it.
    Each item is retrieved but not used. This is useful in cases where the useful work in a data flow is done as
    a side effect of a previous iterator.  Since data flows are "pull-based", each branch must end in some kind of sink.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An asynchronous iterator whose items will be consumed. The type `T` is generic and can represent
        any type of item that the iterator yields.

    Returns
    -------
    None
        This function does not return any value.

    Examples
    --------
    >>> # If your only goal is to log values and not do anything with them
    >>> # The data flow still needs to have a sink to run correctly.
    >>>
    >>> stream = array_source([1,2,3])
    >>> stream = log_step(stream, "Value")
    >>> await empty_sink(stream)
    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for _ in owned_aiter:
            pass
    # logger.info("Empty sink finished")


async def single_source(item: T) -> AsyncIterator[T]:
    """
    Data flow source that yields a single specified item.

    This function generates an asynchronous iterator that yields exactly one item, the one passed as
    an argument.

    Parameters
    ----------
    item : T
        The item to be yielded by the asynchronous iterator. The generic type `T` allows for any type
        of item to be provided.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator that yields the provided item once.

    Examples
    --------
    >>> stream = single_source("Hello, world")
    >>> out = await array_sink(stream)
    >>> assert out == ["Hello, world"]

    Notes
    -----
    -  Often used with a :func:`~voice_stream.concat_step` to add an object ot the beginning or end of
    a stream.
    """
    await asyncio.sleep(0)
    yield item


async def array_source(array: list[T]) -> AsyncIterator[T]:
    """
    Data flow source the yields items from a list.

    This function takes a list and converts it into an asynchronous iterator. Each element of the list
    is yielded one by one in an asynchronous fashion.

    Parameters
    ----------
    array : list[T]
        A list of items of type `T`. The elements of this list will be yielded by the asynchronous iterator.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator that yields each element of the input list.

    Examples
    --------
    >>> stream = array_source([1,2,3])
    >>> stream = log_step(stream, "Value")
    >>> await empty_sink(stream)

    Notes
    -----
    - This source is useful when an existing list needs to be processed asynchronously.
    """
    for item in array:
        await asyncio.sleep(0)
        yield item


async def array_sink(async_iter: AsyncIterator[T]) -> list[T]:
    """
    Data flow sink that collects items into a list.

    This function asynchronously iterates over all items from the provided iterator and collects
    them into a list. This is useful for when you want to convert an asynchronous stream of data into a
    synchronous data structure like a list.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An asynchronous iterator from which items will be consumed. The generic type `T` can represent
        any type of item that the iterator yields.

    Returns
    -------
    list[T]
        A list containing all the items yielded by the asynchronous iterator.

    Examples
    --------
    >>> stream = array_source([1,2,3])
    >>> stream = log_step(stream, "Value")
    >>> out = await array_sink(stream)
    >>> assert out == [1,2,3]

    Notes
    -----
    - This sink is ideal for scenarios where the entirety of an asynchronous data stream needs to be
      collected and processed at once.
    - The sink does end up holding all the collected items in memory, which can cause memory issues with very large streams.
    """
    array = []
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            array.append(item)
        return array


class QueueAsyncIterator:
    """
    An asynchronous iterator that operates on its own queue.

    This class implements an async iterator which allows asynchronous iteration over
    queued items. It uses an asyncio.Queue for storing items and provides a `put` method
    to add items to this queue. The iterator retrieves items from the queue in the order
    they were added.

    Examples
    --------
    >>> queue = queue_source() # With no input arguments, this returns a QueueAsyncIterator.
    >>> stream = queue
    >>> done = array_sink()
    >>> await queue_iter.put(1)
    >>> await queue_iter.put(2)
    >>> await queue_iter.put(EndOfStreaMarker)
    >>> out = await done
    >>> assert out == [1, 2]
    """

    def __init__(self):
        self.queue = asyncio.Queue()
        self.iter = queue_source(self.queue)

    async def put(self, item):
        """Adds an item to the queue managed by this iterator.

        Parameters
        ----------
        item : any type
            The item to be added to the queue.
        """
        return await self.queue.put(item)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.iter.__anext__()


def queue_source(
    queue: AwaitableOrObj[asyncio.Queue[T]] = None,
    cancel_event: asyncio.Event = None,
) -> Union[AsyncIterator[T], QueueAsyncIterator]:
    """
    Data flow source that yields items from an asyncio.Queue.

    This function returns an asynchronous iterator that consumes items from an asyncio.Queue.  The iteration continues
    until an `EndOfStreamMarker` is encountered in the queue, signaling the end of iteration.

    Parameters
    ----------
    queue : AwaitableOrObj[asyncio.Queue[T]], optional
        An instance of asyncio.Queue from which the items will be consumed. This can be an instance of the queue
        or an Awaitable that returns the queue, which can be useful if the queue isn't yet created.  This parameter is
        optional.  If not provided, the AsyncIterator will be a :func:`~voice_stream.QueueAsyncIterator` which allows
        items to be added to the queue via the `put` method.
    cancel_event : asyncio.Event
        An optional cancellation event that externally indicates that this sink should stop listening on the queue.
        This is useful if the queue will be reused for another operation.  Otherwise this event will sit around waiting
        for a new message.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator over the items in the queue.

    Examples
    --------
    >>> queue = asyncio.Queue()
    >>> queue.put(1)
    >>> queue.put(2)
    >>> queue.put(EndOfStreamMarker)
    >>> stream = queue_source()
    >>> done = await array_sink(stream)
    >>> assert done == [1,2]

    Notes
    -----
    - The function expects that the queue will be closed by putting `EndOfStreamMarker` into it.
    - If an Awaitable[Queue] is passed, this function will return immediately and the queue will be awaited when the iterator is started.
    - cancel_event is only allowed if a queue is passed in.  (It doesn't make sense otherwise.  If the queue is internally managed, it can't be reused).
    """
    if queue:
        if cancel_event:

            class WaitingIter:
                def __init__(self, queue, event):
                    self.queue = queue
                    self.event = event

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self.event.is_set():
                        raise StopAsyncIteration
                    resolved_queue = await resolve_awaitable_or_obj(self.queue)
                    item_task = asyncio.create_task(resolved_queue.get())
                    stop_task = asyncio.create_task(self.event.wait())
                    done, pending = await asyncio.wait(
                        {item_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        await cancel_with_confirmation(task)
                    if item_task in done:
                        item = await item_task
                        if item == EndOfStreamMarker:
                            raise StopAsyncIteration
                        return item
                    else:
                        assert stop_task in done
                        raise StopAsyncIteration

            return WaitingIter(queue, cancel_event)

        else:

            async def gen():
                resolved_queue = await resolve_awaitable_or_obj(queue)
                while True:
                    try:
                        item = await resolved_queue.get()
                        if item == EndOfStreamMarker:
                            break
                    except asyncio.CancelledError:
                        # logger.debug("Queue iterator cancelled.")
                        raise
                    # logger.debug(f"Got {str(item)[:50]} from queue")
                    yield item
                # logger.debug("Queue exhausted.")

            return gen()
    else:
        return QueueAsyncIterator()


async def queue_sink(
    async_iter: AsyncIterator[T],
    queue: Optional[AwaitableOrObj[asyncio.Queue]] = None,
    end_of_stream: Any = EndOfStreamMarker,
    send_end_of_stream: bool = True,
    propagate_exceptions: bool = True,
) -> asyncio.Queue:
    """
    Data flow sink that writes items to a queue.

    This function takes an asynchronous iterator and writes each element it yields into a queue.
    If a queue is provided, it is used; otherwise, a new asyncio.Queue is created. Upon completion
    or exception it signals the end of the stream.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An asynchronous iterator from which elements are read.
    queue : Optional[AwaitableOrObj[asyncio.Queue]], optional
        An optional asyncio.Queue or an awaitable resulting in an asyncio.Queue.
        If not provided, a new :class:`~voice_stream:QueueWithException` is created.
    end_of_stream : The item to enqueue to indicate the stream has ended.  Defaults to EndOfStreamMarker
    send_end_of_stream : bool, optional
        If False, don't send any end of stream signal at all.
    propagate_exceptions : bool, optional
        If True, send exceptions to the queue.  Otherwise, raise them.  Defaults to True.

    Returns
    -------
    asyncio.Queue
        The queue to which the elements from async_iter are written.

    Examples
    --------
    >>> stream = array_source([1,2])
    >>> queue = await queue_sink()
    >>> assert len(queue) == 2
    >>> assert queue.get() == 1
    >>> assert queue.get() == 2
    >>> assert queue.empty()

    Notes
    --------
    - If the Queue has a `set_exception` method, that will be called when an exception is thrown by the iterator.  The
      :class:`~voice_stream:QueueWithException` has this method, and uses it to throw the exception on the next call to `queue.get`.
    """
    resolved_queue = None
    try:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for message in owned_aiter:
                if resolved_queue is None:
                    if queue:
                        resolved_queue = await resolve_awaitable_or_obj(queue)
                    else:
                        resolved_queue = QueueWithException()
                # logger.debug(f"Put {str(message)[:50]} on queue")
                await resolved_queue.put(message)
    except Exception as e:
        if (
            propagate_exceptions
            and resolved_queue
            and hasattr(resolved_queue, "set_exception")
        ):
            await resolved_queue.set_exception(e)
        else:
            raise e
    if resolved_queue and send_end_of_stream:
        # logger.debug(f"Adding end of stream marker to queue {format_stack_trace(asyncio.current_task())}")
        await resolved_queue.put(end_of_stream)  # signal completion
    return resolved_queue


async def text_file_source(filename: str) -> AsyncIterator[str]:
    """
    Data flow source that yields the lines in a text file.

    This function asynchronously reads a text file line by line, yielding each line without the trailing newline
    character.

    Parameters
    ----------
    filename : str
        The path to the text file to be read.

    Returns
    -------
    AsyncIterator[str]
        An asynchronous iterator yielding lines from the file as strings.

    Raises
    ------
    FileNotFoundError
        If the file specified by filename does not exist.
    IOError
        If an I/O error occurs while opening or reading the file.

    Examples
    --------
    >>> stream = text_file_source("example.txt")
    >>> done = await text_file_sink(stream, "copy.txt")
    """
    async with aiofiles.open(filename, "rt") as f:
        async for line in f:
            line = line[:-1] if line[-1] == "\n" else line
            yield line


async def text_file_sink(
    async_iter: AsyncIterator[Any], filename: AwaitableOrObj[str]
) -> None:
    """
    Data flow sink that writes each element to a file, each as a new line.

    This function takes each element from the provided async iterator and writes it to the specified
    text file. Each element is converted to a string and written as a separate line. The filename
    can be either a string or an awaitable object that resolves to a string.

    Parameters
    ----------
    async_iter : AsyncIterator[Any]
        An asynchronous iterator whose elements are to be written to the file.
    filename : AwaitableOrObj[str]
        The path to the file where the data will be written. This can be a string or an
        awaitable object that yields a string.  The object will be awaited only after the first element is received
        from the iterator.

    Returns
    -------
    None
        This function does not return a value but completes when all elements have been
        written to the file.

    Examples
    --------
    >>> stream = text_file_source("example.txt")
    >>> done = await text_file_sink(stream, "copy.txt")
    """
    return await _file_sink(async_iter, filename, "wt", lambda x: f"{x}\n")


async def binary_file_source(
    filename: str, chunk_size: int = 4096
) -> AsyncIterator[bytes]:
    """
    Data flow source that yields chunks of bytes from a binary file.

    This function opens a binary file and asynchronously reads it in chunks of a specified size.
    It yields each chunk of bytes until the end of the file is reached. This is particularly useful
    for processing large binary files in an asynchronous manner.

    Parameters
    ----------
    filename : str
        The path to the binary file to be read.
    chunk_size : int, optional
        The number of bytes to read in each chunk. Defaults to 4096 bytes.  Pass 0 to read in the whole file at once.

    Returns
    -------
    AsyncIterator[bytes]
        An asynchronous iterator yielding chunks of bytes from the file.

    Raises
    ------
    FileNotFoundError
        If the file specified by filename does not exist.
    IOError
        If an I/O error occurs while opening or reading the file.

    Examples
    --------
    >>> stream = binary_file_source("example.bin")
    >>> stream = log_step(stream, "Bytes read", lambda x: len(x))
    >>> done = await binary_file_sink("copy.bin")
    Bytes read 4096
    Bytes read 4096
    Bytes read 1024  # Example output for a 9216-byte file
    """
    async with aiofiles.open(filename, "rb") as f:
        while True:
            chunk = await f.read(chunk_size)
            if not chunk:
                break
            yield chunk


async def binary_file_sink(
    async_iter: AsyncIterator[bytes], filename: AwaitableOrObj[str]
) -> None:
    """
    Data flow sink that writes chunks of bytes to a binary file.

    This function takes each block of bytes yielded by the provided async iterator and appends it to
    the specified binary file. The filename can be either a string or an awaitable object that resolves
    to a string.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator yielding blocks of bytes to be written to the file.
    filename : AwaitableOrObj[str]
        The path to the binary file where the data will be appended. This can be a string or an
        awaitable object that yields a string.

    Returns
    -------
    None
        This function does not return a value but completes when all blocks of bytes have been
        appended to the file.

    Raises
    ------
    IOError
        If an I/O error occurs while opening or writing to the file.

    Examples
    --------
    >>> stream = binary_file_source("example.bin")
    >>> stream = log_step(stream, "Bytes read", lambda x: len(x))
    >>> done = await binary_file_sink("copy.bin")
    Bytes read 4096
    Bytes read 4096
    Bytes read 1024  # Example output for a 9216-byte file

    Notes
    -----
    - If an awaitable is passed, it is not waited on until the first item has been retrieved from the iterator.
    """
    return await _file_sink(async_iter, filename, "wb", lambda x: x)


async def _file_sink(
    async_iter: AsyncIterator[T],
    filename: AwaitableOrObj[str],
    mode: str,
    prep_func: Callable[[T], Any],
) -> None:
    f = None
    try:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for block in owned_aiter:
                # We wait to resolve the filename until we have a message to write
                if f is None:
                    filename = await resolve_awaitable_or_obj(filename)
                    f = await aiofiles.open(filename, mode)
                await f.write(prep_func(block))
    finally:
        if f is not None:
            await f.close()
            logger.debug(f"Closed {filename}")


def map_str_to_json_step(async_iter: AsyncIterator[str]) -> AsyncIterator[dict]:
    """
    Data flow step that parses JSON strings into dictionaries.

    Each string element from the async iterator is parsed as JSON and transformed into a dictionary.

    Parameters
    ----------
    async_iter : AsyncIterator[str]
        An asynchronous iterator yielding strings, each expected to be a valid JSON text.

    Returns
    -------
    AsyncIterator[dict]
        An asynchronous iterator yielding dictionaries resulting from JSON parsing of each string element.

    Examples
    --------
    >>> stream = array_source([
    ...     '{"name": "Alice", "age": 30}',
    ...     '{"name": "Bob", "age": 25}',
    ... ])
    >>> stream = map_str_to_json_step(stream)
    >>> stream = map_step(stream, lambda x: x['age'])
    >>> await array_sink(stream)
    [30, 25]
    return map_step(async_iter, lambda x: json.loads(x))
    """
    return map_step(async_iter, lambda x: json.loads(x))


async def collect_dict_step(async_iter: AsyncIterator[dict]) -> AsyncIterator[dict]:
    """
    Data flow step that appends values to a dictionary until an empty value is passed.

    This step combines dictionary values coming out of an iterator.  It adds new keys to the output dictionary and
    appends values if possible (if not it replaces values).  It emits the current dictionary when an empty input
    is pulled form the incoming iterator.  Useful for combining incremental results coming from a streamed LangChain.

    Parameters
    ----------
    async_iter : AsyncIterator[Iterable[T]]
        An asynchronous iterator where each item is an iterable of elements.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator yielding combined dictionaries.

    Examples
    --------
    >>> stream = array_source([{'text':'Hello'}, {'text':' World!', 'confidence':0.75}, None])
    >>> stream = collect_dict_step(stream)
    >>> done = await array_sink(stream)
    >>> assert done == [{'text':"Hello World!", 'confidence': 0.75}]
    """

    def combine(x, y):
        try:
            return x + y
        except:
            return y

    buffer = {}
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if item:
                appended_vals = {
                    k: (v if k not in buffer else combine(buffer[k], v))
                    for k, v in item.items()
                }
                buffer = {**buffer, **appended_vals}
            else:
                yield buffer
                buffer = {}


async def delay_step(
    async_iter: AsyncIterator[T], delay_secs: float
) -> AsyncIterator[T]:
    """
    Data flow step that imposes a deplay on items coming in.

    This step simply adds a fixed delay to the items from the incoming iterator.  Mainly useful for testing.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An asynchronous iterator
    delay : float
        The number of seconds to sleep between each item

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator yielding the items coming from the input iterator with a delay.
    """

    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            try:
                await asyncio.sleep(delay_secs)
            except CancelledError as e:
                pass
            yield item


async def flatten_step(
    async_iter: AsyncIterator[Union[Iterable[T], AsyncIterator[T]]],
) -> AsyncIterator[T]:
    """
    Data flow step that flattens an iterator of iterators into a single iterator.

    This function takes an asynchronous iterator where each item is itself an async iterator or a regular iterable
    (like a list or tuple) and flattens it. This means it iterates over each element of these iterables in order, yielding them
    individually. It's useful for converting a stream of iterables into a flat stream of elements.

    Parameters
    ----------
    async_iter : AsyncIterator[Iterable[T]]
        An asynchronous iterator where each item is an iterable of elements.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator yielding individual elements from each iterable in the input async iterator.

    Examples
    --------
    >>> stream = array_source([[1,2], [3,4]])
    >>> stream = flatten_step(stream)
    >>> done = await array_sink(stream)
    >>> assert done == [1, 2, 3, 4]
    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if is_async_iterator(item):
                async with asyncstdlib.scoped_iter(item) as owned_subiter:
                    async for subitem in owned_subiter:
                        yield subitem
            else:
                for subitem in item:
                    yield subitem


def async_init_step(
    async_iter: AsyncIterator[T],
    f: Callable[[AsyncIterator[T]], Coroutine],
    num_outputs: int = 1,
) -> AsyncIterator[Output]:
    """
    Data flow step that asyncronously initializes a step.

    This step takes an AsyncIterator and a lambda that takes the iterator and returns an Awaitable.  It eagerly pulls
    the first item from the iterator and separately calls the lambda and awaits the result in a separate task.  This
    is useful when you ahve a step that requires an async call to initialize (which we generally avoid).  It's also
    useful when the initialization depends on a value produced from earlier in the data flow.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An input asynchronous iterator.
    f : Callable[[AsyncIterator[T]], Coroutine]
        A coroutine function that takes the input async iterator and returns another async iterator
    num_outputs : int, optional
        The number of output async iterators to expect from `f`. Defaults to 1.  Use this if the step you are
        asynchronously initializing returns more than one iterator, such as a :class:`~voice_stream:fork_step`.
        num_outputs can be 0 in the case where the asynchronous initialization is for a sink.

    Returns
    -------
    AsyncIterator[Output] or Tuple[AsyncIterator[Output], ...]
        if `num_outputs` is 1, then returns an AsyncIterator
        otherwise, returns a tuple of AsyncIterators the same length as `num_outputs`

    Examples
    --------
    # Copy a file, generating a name based on the first line of the file.
    >>> stream = text_file_source("example.txt")
    >>> stream, name = extract_value_step(stream, lambda x: x)
    >>> done = await async_init_step(stream, lambda x: text_file_sink(x, resolve_awaitable_or_obj(name)), num_outputs=0)
    """

    class AsyncInitInputIterator:
        """Wraps the input iterator and eagerly gets the first item.  This pulls data through the stream in case our
        async_init function is waiting on it."""

        def __init__(self):
            self.iter = async_iter.__aiter__()
            # Using create_task here because any exception in the result will get through in __anext__
            self.first_item_task = asyncio.create_task(self.iter.__anext__())

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.first_item_task:
                out = self.first_item_task
                self.first_item_task = None
                # logger.debug(f"Waiting for first item to async init step {format_current_task()}")
                return await out
            else:
                return await self.iter.__anext__()

    class AsyncInitOutputIterator:
        """Wraps the output and doesn't create the real iterator until the first item is requested."""

        def __init__(self, init_event):
            self.iter = None
            self.init_event = init_event
            self.init_exception: Optional[Exception] = None

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.iter:
                await self.init_event.wait()
                if self.init_exception:
                    raise self.init_exception
                # logger.debug(f"Async init completed.  Waiting for next step in {format_current_task()}.")
            return await self.iter.__anext__()

    init_event = asyncio.Event()
    outputs = [AsyncInitOutputIterator(init_event) for _ in range(num_outputs)]

    async def do_init():
        try:
            input = AsyncInitInputIterator()
            # logger.debug(f"Beginning async init in {format_current_task()}.")
            step = await f(input)
            # logger.debug(f"Completed async init in {format_current_task()}.")
            for output, iterable in zip(outputs, to_tuple(step)):
                output.iter = iterable.__aiter__()
        except Exception as e:
            # logger.exception("Exception in async init.")
            for output in outputs:
                output.init_exception = e
        finally:
            init_event.set()

    background_task(do_init())

    if len(outputs) == 1:
        return outputs[0]
    else:
        return outputs


async def abort_step(
    async_iter: AsyncIterator[T], event: asyncio.Event
) -> AsyncIterator[T]:
    """
    Data flow step that ends when an event is set.

    This step passes along items from the input iterator until an event is set, and then it ends.  Useful for cleanup tasks.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An input asynchronous iterator.
    event : asyncio.Event
        The event that signals that iteration should end.

    Returns
    -------
    AsyncIterator[T]
        An iterator returning the input values.

    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if event.is_set():
                return
            yield item


def extract_value_step(
    async_iter: AsyncIterator[T],
    value: Callable[[T], Any],
    condition: Optional[Callable[[T], bool]] = None,
) -> Tuple[AsyncIterator[T], asyncio.Future[Any]]:
    """
    Extracts a value from an async iterator based on a condition, returning the iterator and a future.

    This function processes an asynchronous iterator, applying a given condition to each item. The first time
    an item meets the condition, a specified value extraction function is applied to it, and the result
    is set in an asyncio.Future. The function returns an async iterator and the future containing the extracted value.
    The output iterator produces all the same elements that go into it.  If the condition is not provided, the value
    function is applied to the first item.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An input asynchronous iterator.
    value : Callable[[T], Any]
        A function that extracts a value from an item in the iterator.
    condition : Optional[Callable[[T], bool]], optional
        A function that returns True if the value should be extracted from the item.
        If None, the value is extracted from the first item.

    Returns
    -------
    Tuple[AsyncIterator[T], asyncio.Future[Any]]
        The modified async iterator and a future containing the extracted value.

    Examples
    --------
    # Copy a file, generating a name based on the first line of the file.
    >>> stream = text_file_source("example.txt")
    >>> stream, name = extract_value_step(stream, lambda x: x)
    >>> done = await async_init_step(stream, lambda x: text_file_sink(x, resolve_awaitable_or_obj(name)), num_outputs=0)
    """
    loop = asyncio.get_running_loop()
    fut = loop.create_future()

    async def chain():
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                if not fut.done() and (condition is None or condition(item)):
                    fut.set_result(value(item))
                yield item

    return chain(), fut


async def recover_exception_step(
    async_iter: AsyncIterator[T],
    exception_type: Type[BaseException],
    exception_handler: Callable[[BaseException], Any],
) -> AsyncIterator[T]:
    """
    Data flow step that recovers from an exception in a previous step.

    This function takes an async iterator and a specified exception type. If an exception with the
    specified type occurs during iteration, it is caught and passed to the provided exception
    handler function. The result depends on what is returned by the exception handler:
    * If it returns an AsyncIterator, that will be yielded and this step will end when the iterator ends.
    * If it returns None, this step will immediately end.
    * If it returns anything else, that object will be yielded and this step will end.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        The asynchronous iterator to be wrapped.
    exception_type : Type[BaseException]
        The type of exception to be caught and handled.
    exception_handler : Callable[[BaseException], Any]
        A function to handle the caught exception.  Returns an optional value that will be converted to an AsyncIterator.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator that handles exceptions with the specified type.

    Examples
    --------
    >>> def gen():
    ...    yield 1
    ...    yield 2
    ...    raise ValueError("No more")
    >>> stream = gen()
    >>> stream = recover_exeption_step(stream, ValueError, lambda x: x.args[0])
    >>> done = await array_sink(stream)
    >>> assert done == [1,2,"No more"]

    Notes
    -----
    - Once the source iterator throws the exception, it will not be accessed again.
    """
    try:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                yield item
    except exception_type as e:
        eh = await resolve_awaitable_or_obj(exception_handler(e))
        handler_iter = to_source(eh)
        async with asyncstdlib.scoped_iter(handler_iter) as owned_aiter:
            async for item in owned_aiter:
                yield item


async def log_step(
    async_iter: AsyncIterator[T],
    name: str,
    formatter: Callable[[T], Any] = lambda x: x,
    every_nth_message: Optional[int] = None,
) -> AsyncIterator[T]:
    """
    Data flow step that prints using the Python logger.

    This function takes an async iterator and logs each item that passes through it. The logging
    includes a specified name and uses an optional formatter function to convert items to a log-friendly format.
    This is useful for debugging or monitoring the contents of an data flow.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        The asynchronous iterator whose items are to be logged.
    name : str
        A name to prepend to each logged message for identification.
    formatter : Callable[[T], Any], optional
        A function to format each item before logging. Defaults to a function that returns the item unchanged.
    every_nth_message : Optional[int]
        Indicates that the log should only happen every nth message.  The first message will always cause a log message,
        and then every nth message after the first.  For example, if the value is 10, then the 1st, 11th, 22nd, etc.
        messages will be logged.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator that logs each item and then yields it.

    Examples
    --------
    >>> stream = array_source([1,2,3])
    >>> stream = log_step(stream, "Value squared", lambda x: x*x)
    >>> await empty_sink()
    Value squared: 1
    Value squared: 4
    Value squared: 9
    """
    count = 0
    log = True
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if every_nth_message and every_nth_message > 1:
                count += 1
                log = count % every_nth_message == 1
            if log:
                formatted = formatter(item)
                logger.info(f"{name}: {formatted}")
            yield item


async def count_step(async_iter: AsyncIterator[T], name: str) -> AsyncIterator[T]:
    """
    Data flow step that counts the number of items.

    This function takes an async iterator and counts the number of items that pass through it.
    After the iteration completes, it logs the total count of items. This is useful for monitoring or debugging the
    flow of data through async streamlines.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        The asynchronous iterator whose items are to be counted.
    name : str
        A name to use in the log message for identifying the count source.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator that counts each item and then yields it.

    Examples
    --------
    >>> stream = array_source([1,2,3])
    >>> stream = count_step(stream, "Value")
    >>> await empty_sink()
    Value count: 3
    """
    counter = 0
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            counter += 1
            yield item
    logger.info(f"{name} count: {counter}")


async def filter_step(
    async_iter: AsyncIterator[T], condition: Callable[[T], bool]
) -> AsyncIterator[T]:
    """
    Data flow step that filters items based on a specified condition.

    This function wraps an async iterator and yields only those items that satisfy a given condition.
    It is analogous to the built-in `filter` function but for asynchronous iterators. Each item from
    the input async iterator is passed to the `condition` function, and only items for which this
    function returns `True` are yielded.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        The asynchronous iterator whose items are to be filtered.
    condition : Callable[[T], bool]
        A function that evaluates each item in the iterator. If this function returns `True`,
        the item is yielded; otherwise, it is skipped.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator yielding only the items that satisfy the condition.

    Examples
    --------
    >>> stream = array_source(range(4))
    >>> stream = filter_step(stream, lambda x: x % 2 == 0)
    >>> done = await array_sink(stream)
    >>>
    # Output: 0, 2
    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if condition(item):
                yield item


async def map_step(
    async_iter: AsyncIterator[T],
    func: Callable[[T], Output],
    ignore_none: Optional[bool] = False,
) -> AsyncIterator[Output]:
    """
    Data flow step that transforms items using a mapping function.

    This function applies either a synchronous or asynchronous mapping function to each item in the
    input async iterator. If `ignore_none` is set to True, any items that are transformed to `None`
    are not yielded. This feature allows the function to perform both transformation and filtering in a single step.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        The asynchronous iterator whose items are to be transformed.
    func : Callable[[T], Output]
        A mapping function to apply to each item. This can be either a synchronous or asynchronous function.
    ignore_none : Optional[bool], default False
        If True, items that are transformed to None by `func` are not yielded.

    Returns
    -------
    AsyncIterator[Output]
        An asynchronous iterator yielding transformed items, optionally skipping None values.

    Examples
    --------
    >>> stream = array_source(range(4))
    >>> stream = map_step(stream, lambda x: x + 2)
    >>> done = await array_sink(stream)
    >>> assert done == [2,3,4,5]
    """
    is_async = inspect.iscoroutinefunction(func)
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            v = func(item)
            if is_async:
                v = await v
            if (not ignore_none) or v:
                yield v


async def timeout_step(
    async_iter: AsyncIterator[bytes], timeout: float
) -> AsyncIterator[bytes]:
    start = time.perf_counter()
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            now = time.perf_counter()
            if (now - start) > timeout:
                logger.debug("Raising TimeoutError from timeout_step")
                raise TimeoutError()
            yield item


async def chunk_bytes_step(
    async_iter: AsyncIterator[bytes], chunk_size: AwaitableOrObj[int]
) -> AsyncIterator[bytes]:
    """
    Data flow step that breaks long byte sequences from an asynchronous iterator into fixed-size chunks.

    This function takes an asynchronous iterator yielding byte sequences and a chunk size,
    then yields these byte sequences in chunks of the specified size. The chunk size can
    be provided either as a direct integer value or as an awaitable object that resolves
    to an integer. This is useful for processing large byte sequences in manageable sizes.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator that yields byte sequences.
    chunk_size : AwaitableOrObj[int]
        The size of each chunk as an integer, or an awaitable object that yields an integer.

    Returns
    -------
    AsyncIterator[bytes]
        An asynchronous iterator yielding byte chunks of the specified size.

    Examples
    --------
    >>> stream = array_source([b'HelloWorld!', b'PythonAsyncIO']):
    >>> stream = chunk_bytes_step(stream, chunk_size=5)
    >>> done = await array_sink(stream)
    >>> assert done == [b'Hello', b'World', b'!', b'Pytho', b'nAsyn', b'cIO']
    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            resolved_chunk_size = await resolve_awaitable_or_obj(chunk_size)
            for c in _chunk_bytes(item, resolved_chunk_size):
                yield c


def _chunk_bytes(item, chunk_size):
    for i in range(0, len(item), chunk_size):
        data = item[i : i + chunk_size]
        # logger.debug(f"Chunked {len(data)} bytes")
        yield data


async def min_size_bytes_step(
    async_iter: AsyncIterator[bytes], min_size: AwaitableOrObj[int]
) -> AsyncIterator[bytes]:
    """
    Data flow steps that aggregates byte sequences to ensure a minimum size for each emitted chunk.

    This function takes an asynchronous iterator yielding byte sequences and a minimum size. It aggregates
    the byte sequences and yields them only when they reach or exceed the specified minimum size. The minimum
    size can be provided either as a direct integer value or as an awaitable object that resolves to an
    integer. This is useful for ensuring that chunks of data meet a size requirement before processing.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator that yields byte sequences.
    min_size : AwaitableOrObj[int]
        The minimum size of each chunk as an integer, or an awaitable object that yields an integer.

    Returns
    -------
    AsyncIterator[bytes]
        An asynchronous iterator yielding byte chunks that are at least the specified minimum size.

    Examples
    --------
    >>> stream = array_source([b'Hello', b'World', b'PythonAsyncIO', b'End')
    >>> stream = min_size_bytes_step(stream, min_size=10)
    >>> done = await array_sink(stream)
    >>> assert done == [
    ...     b'HelloWorld',
    ...     b'PythonAsyncIO',
    ...     b'End',
    ... ]
    """
    buffer = b""
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            combined = buffer + item
            if len(combined) >= await resolve_awaitable_or_obj(min_size):
                yield combined
                buffer = b""
            else:
                buffer = combined
        if len(buffer) > 0:
            yield buffer


async def concat_step(*async_iters: List[AsyncIterator[T]]) -> AsyncIterator[T]:
    """
    Data flow step that combines multiple streams by concatenating them.

    This function takes a list of asynchronous iterators and concatenates their elements
    into a single async iterator. It iterates over each input iterator in the order they
    are provided, yielding all items from each before moving on to the next.

    Parameters
    ----------
    async_iters : List[AsyncIterator[T]]
        A list of asynchronous iterators to be concatenated.

    Returns
    -------
    AsyncIterator[T]
        A single asynchronous iterator yielding items from all provided iterators in sequence.

    Examples
    --------
    >>> stream1 = array_source([1,2])
    >>> stream2 = array_source([3,4])
    >>> stream = concat_step(stream1, stream2)
    >>> done = await array_sink(stream)
    >>> assert done == [1,2,3,4]
    """
    for async_iter in async_iters:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                yield item


async def merge_step(*async_iters: list[AsyncIterator[T]]) -> AsyncIterator[T]:
    """
    Data flow step that merges multiple streams into one, consuming from all iterators concurrently.

    Unlike concatenation which consumes one iterator at a time, `merge_step` interleaves items from all
    provided iterators as they become available. The merged iterator continues until all input iterators
    are exhausted. If an exception occurs in any of the iterators, all others are canceled.

    Parameters
    ----------
    async_iters : list[AsyncIterator[T]]
        A list of asynchronous iterators to be merged.

    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator yielding items from all input iterators in the order they become available.

    Examples
    --------
    >>> async def async_iter1():
    ...     for i in [1,2,3]:
    ...         await asyncio.sleep(0.3)
    ...         yield i
    >>> async def async_iter2():
    ...     for i in [4,5,6]:
    ...         await asyncio.sleep(0.5)
    ...         yield i
    >>> stream1 = async_iter1()
    >>> stream2 = async_iter2()
    >>> stream = merge_step(stream1, stream2)
    >>> done = await array_sink(stream)
    >>> assert done == [1,4,2,3,5,6]
    # Output order is not guaranteed.
    """
    # TODO Implement with backpressure.
    queue = QueueWithException()
    tasks = [background_task(queue.enqueue_iterator(it)) for it in async_iters]

    try:
        completed = 0
        while completed < len(async_iters):
            item = await queue.get()
            if item == EndOfStreamMarker:
                completed += 1
            else:
                yield item
    finally:
        for task in tasks:
            task.cancel()  # Cancel all tasks


async def merge_as_dict_step(
    dict_iters: dict[str, AsyncIterator[Any]]
) -> AsyncIterator[dict]:
    """
    Data flow step that merges multiple streams into a single one that yields dictionaries.

    Each iterator in the input dictionary is associated with a key. The function concurrently consumes
    items from all iterators and yields dictionaries. Each dictionary contains the most recent item
    from each iterator, keyed by the respective iterator's key. The output frequency is driven by the
    first iterator specified in the input dictionary.

    Parameters
    ----------
    dict_iters : dict[str, AsyncIterator[Any]]
        A dictionary mapping keys to asynchronous iterators. The first iterator in the dictionary
        drives the output frequency.

    Returns
    -------
    AsyncIterator[dict]
        An asynchronous iterator yielding dictionaries. Each dictionary combines the most recent items
        from each input iterator under their corresponding keys.

    Raises
    ------
    ValueError
        If `dict_iters` is empty.

    Examples
    --------
    >>> async def async_iter1():
    ...     for i in [1,2,3]:
    ...         await asyncio.sleep(0.3)
    ...         yield i
    >>> async def async_iter2():
    ...     for i in [4,5,6]:
    ...         await asyncio.sleep(0.5)
    ...         yield i
    >>> stream1 = async_iter1()
    >>> stream2 = async_iter2()
    >>> stream = merge_as_dict_step({'a':stream1, 'b':stream2})
    >>> done = await array_sink(stream)
    >>> assert done == [
    ...     {'a':1},
    ...     {'a':2, 'b':4},
    ...     {'a':3, 'b':4},
    ... ]
    """
    # logger.debug(f"merge_as_dict_step")
    if not dict_iters:
        raise ValueError("merge_as_dict_step requires at least on iterator")
    key_iter = iter(dict_iters)
    first_key = next(key_iter)
    first_iter = dict_iters[first_key]
    secondary_iters = {k: dict_iters[k] for k in key_iter}
    values = {}

    async def consume_iter(key, it):
        # logger.debug(f"Starting consumer for {key}")
        async with asyncstdlib.scoped_iter(it) as owned_it:
            async for item in owned_it:
                # logger.debug(f"Consumed {item} for {key}")
                values[key] = item

    tasks = [
        background_task(consume_iter(k, iter)) for k, iter in secondary_iters.items()
    ]
    async for item in first_iter:
        # logger.debug(f"Merging dict for {item}")
        yield {first_key: item, **values}
    for task in tasks:
        task.cancel()


def partition_step(
    async_iter: AsyncIterator[T], condition: Callable[[T], bool]
) -> Tuple[AsyncIterator[T], AsyncIterator[T]]:
    """
    Data flow step that partitions items into two output streams based on a specified condition.

    This function divides the items from the input async iterator into two separate iterators: one
    for items where the condition evaluates to True, and another for items where the condition is False.
    If an exception occurs during iteration, it is propagated to both output iterators.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        An asynchronous iterator whose items are to be partitioned.
    condition : Callable[[T], bool]
        A function that evaluates each item in the iterator. Returns True if the item should go to the
        first iterator, and False for the second.

    Returns
    -------
    Tuple[AsyncIterator[T], AsyncIterator[T]]
        A tuple of two asynchronous iterators: the first yields items where the condition is True,
        and the second yields items where the condition is False.

    Examples
    --------
    >>> stream = array_source(range(4))
    >>> true_stream, false_stream = partition_step(stream, lambda x: x % 2 == 0)
    >>> true_done = array_sink(true_stream)
    >>> false_done = array_sink(false_stream)
    >>> true_ret, false_ret = await asyncio.gather(true_done, false_done)
    >>> assert true_ret == [0,2]
    >>> assert false_ret == [1,3]
    """
    true_queue = QueueWithException()
    false_queue = QueueWithException()

    async def distribute():
        try:
            async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                async for item in owned_aiter:
                    # logger.debug(f"Distributing {item}")
                    if condition(item):
                        await true_queue.put(item)
                    else:
                        await false_queue.put(item)
                    # logger.debug(f"Queue sizes: {true_queue.qsize()} {false_queue.qsize()}")
        except Exception as e:
            # logger.debug(f"Exception while queueing")
            await true_queue.set_exception(e)
            await false_queue.set_exception(e)
        await true_queue.put(EndOfStreamMarker)  # Signal end of iteration
        await false_queue.put(EndOfStreamMarker)

    distribution_task = background_task(distribute())
    true_iterator = queue_source(true_queue)
    false_iterator = queue_source(false_queue)

    return true_iterator, false_iterator


def fork_step(
    async_iter: AsyncIterator[T],
    pull_from_all: bool = False,
) -> Tuple[AsyncIterator[T], AsyncIterator[T]]:
    """
    Data flow step that splips a stream into two, creating a 'fork' in the stream.

    This function takes an async iterator and divides its output into two separate async iterators.
    If `pull_from_all` is set to False (default), the consumption rate of items is determined by the
    rate of consumption of the first returned iterator; the second iterator's output rate will match
    the first. If `pull_from_all` is True, both iterators will consume items independently as quickly
    as possible.

    If pull_from_all is False, exceptions will only propagate to the first iterator. If True, exceptions
    will propagate to both iterators.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        The asynchronous iterator to be forked.
    pull_from_all : bool, default False
        If true, both forks will pull form the incoming iterator.  If False, the second iterator will only
        receive data as fast as the first pulls.

    Returns
    -------
    Tuple[AsyncIterator[T], AsyncIterator[T]]
        A tuple of two asynchronous iterators representing the forked output.

    Examples
    --------
    >>> source = array_source(range(2))
    >>> a, b = fork_step(source)
    >>> a = await array_sink(a)
    >>> b = await array_sink(b)
    >>> assert a == [0, 1]
    >>> assert b == [0, 1]

    Notes
    -----
    - With pull_from_all set to False, the rate of iteration in the first iterator controls the overall
      pace of item consumption from the original iterator.
    - With pull_from_all set to True, items are consumed from the original iterator as quickly as possible,
      and both iterators receive items independently.
    """

    def no_pull_from_all():
        right_queue = asyncio.Queue()
        right_iterator = queue_source(right_queue)

        async def consume_and_queue() -> AsyncIterator[T]:
            async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                async for item in owned_aiter:
                    await right_queue.put(item)
                    yield item
            await right_queue.put(EndOfStreamMarker)

        left_iterator = consume_and_queue()
        return left_iterator, right_iterator

    def with_pull_from_all():
        left_queue = QueueWithException()
        right_queue = QueueWithException()

        async def distribute():
            try:
                async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                    async for item in owned_aiter:
                        await left_queue.put(item)
                        await right_queue.put(item)
            except Exception as e:
                await left_queue.set_exception(e)
                await right_queue.set_exception(e)
            await left_queue.put(EndOfStreamMarker)  # Signal end of iteration
            await right_queue.put(EndOfStreamMarker)

        background_task(distribute())
        left_iterator = queue_source(left_queue)
        right_iterator = queue_source(right_queue)

        return left_iterator, right_iterator

    iterators = with_pull_from_all() if pull_from_all else no_pull_from_all()
    return iterators


def buffer_step(
    async_iter: AsyncIterator[T], join_func: Optional[Callable[[List[T]], T]] = None
) -> AsyncIterator[T]:
    """
    Data flow step that buffers and aggregates items them before yielding.

    This function acts as a buffer.  It pulls items from the incoming iterator as fast as they can come in, and
    then outputs aggreged items only as fast as the output iterator can pull them.  The aggregation is performed using a
    specified join function.

    Parameters
    ----------
    async_iter : AsyncIterator[T]
        The asynchronous iterator to buffer from.
    join_func : Callable[[List[T]], T], optional
        A function that takes a list of items and returns an aggregated result.  This is useful for buffering strings or
        byte arrays.  If not specified, then the items are returned exactly as they are put on the buffer.


    Returns
    -------
    AsyncIterator[T]
        An asynchronous iterator that yields aggregated items.

    Examples
    --------
    >>> async def rate_limit_sink(ai):
    ...     out = []
    ...     async for item in ai:
    ...         await asyncio.sleep(0.1)
    ...         out.append(item)
    >>> stream = array_source(['a','b','c','d'])
    >>> stream = buffer_step(stream, lambda x:  ''.join(x))
    >>> done = await rate_limit_sink(stream)
    >>> assert done == ['abcd']
    """
    queue = QueueWithException()
    task = background_task(queue.enqueue_iterator(async_iter))

    async def make_iterator() -> AsyncIterator[T]:
        try:
            ongoing = True
            while ongoing:
                # Use a blocking get() to ensure there's at least one chunk of
                # data, and stop iteration if the chunk is None, indicating the
                # end of the audio stream.
                item = await queue.get()
                if item == EndOfStreamMarker:
                    # logger.debug(f"End of queue")
                    return
                if join_func:
                    data = [item]
                    # Now consume whatever other data's still buffered.
                    while True:
                        try:
                            chunk = queue.get_nowait()
                            if chunk == EndOfStreamMarker:
                                # logger.debug(f"Got None in nowait")
                                ongoing = False
                                break
                            data.append(chunk)
                        except QueueEmpty:
                            # logger.debug(f"Got QueueEmpty in nowait")
                            break
                    out = join_func(data)
                    # logger.debug(f"Joining {data} {out}")
                    yield out
                else:
                    yield item
        finally:
            task.cancel()

    return make_iterator()


def byte_buffer_step(async_iter: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """
    Data flow step that buffers and aggregates byte sequences to match producer and consumer rates.

    This function acts as a buffer specifically for byte streams.  It pulls bytes from the incoming iterator as fast
     as they can come in, and then outputs aggreged byte buffers only as fast as the output iterator can pull them.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator yielding byte sequences.

    Returns
    -------
    AsyncIterator[bytes]
        An asynchronous iterator yielding concatenated byte sequences.

    Examples
    --------
    >>> async def rate_limit_sink(ai):
    ...     out = []
    ...     async for item in ai:
    ...         await asyncio.sleep(0.5)
    ...         out.append(item)
    >>> stream = array_source([b'a',b'b',b'c',b'd'])
    >>> stream = byte_buffer_step(stream)
    >>> done = await rate_limit_sink(stream)
    >>> assert done == [b'abcd']
    """
    return buffer_step(async_iter, lambda x: b"".join(x))


def str_buffer_step(async_iter: AsyncIterator[str]) -> AsyncIterator[str]:
    """
    Data flow step that buffers and aggregates text strings to match producer and consumer rates.

    This function acts as a buffer specifically for text string.  It pulls text from the incoming iterator as fast
     as it can come in, and then outputs concatenated text only as fast as the output iterator can pull.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator yielding text.

    Returns
    -------
    AsyncIterator[str]
        An asynchronous iterator yielding concatenated text.

    Examples
    --------
    >>> async def rate_limit_sink(ai):
    ...     out = []
    ...     async for item in ai:
    ...         await asyncio.sleep(0.5)
    ...         out.append(item)
    >>> stream = array_source(['a','b','c','d'])
    >>> stream = str_buffer_step(stream)
    >>> done = await rate_limit_sink(stream)
    >>> assert done == ['abcd']
    """
    return buffer_step(async_iter, lambda x: "".join(x))
