import asyncio
import inspect
import json
import logging
from asyncio import QueueEmpty
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
    >>> pipe = empty_source()
    >>> done = await array_sink(pipe)
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
    >>> pipe = empty_source()
    >>> done = await array_sink(pipe)
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
    >>> pipe = array_source([1,2,3])
    >>> pipe = log_step(pipe, "Value")
    >>> await empty_sink(pipe)
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
    >>> pipe = single_source("Hello, world")
    >>> ret = await array_sink(pipe)
    >>> assert ret == ["Hello, world"]

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
    >>> pipe = array_source([1,2,3])
    >>> pipe = log_step(pipe, "Value")
    >>> await empty_sink(pipe)

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
    >>> pipe = array_source([1,2,3])
    >>> pipe = log_step(pipe, "Value")
    >>> ret = await array_sink(pipe)
    >>> assert ret == [1,2,3]

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
    >>> pipe = queue
    >>> done = array_sink()
    >>> await queue_iter.put(1)
    >>> await queue_iter.put(2)
    >>> await queue_iter.put(EndOfStreaMarker)
    >>> ret = await done
    >>> assert ret == [1, 2]
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
    >>> pipe = queue_source()
    >>> done = await array_sink(pipe)
    >>> assert done == [1,2]

    Notes
    -----
    - The function expects that the queue will be closed by putting `EndOfStreamMarker` into it.
    - If an Awaitable[Queue] is passed, this function will return immediately and the queue will be awaited when the iterator is started.
    """
    if queue:

        async def gen():
            resolved_queue = await resolve_awaitable_or_obj(queue)
            while True:
                try:
                    item = await resolved_queue.get()
                    if item == EndOfStreamMarker:
                        break
                except asyncio.CancelledError:
                    # logger.debug("Queue iterator cancelled.")
                    break
                yield item

        return gen()
    else:
        return QueueAsyncIterator()


async def queue_sink(
    async_iter: AsyncIterator[T],
    queue: Optional[AwaitableOrObj[asyncio.Queue]] = None,
    end_of_stream=EndOfStreamMarker,
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

    Returns
    -------
    asyncio.Queue
        The queue to which the elements from async_iter are written.

    Examples
    --------
    >>> pipe = array_source([1,2])
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
                        resolved_queue = asyncio.Queue()
                await resolved_queue.put(message)
    except Exception as e:
        if resolved_queue and hasattr(resolved_queue, "set_exception"):
            await resolved_queue.set_exception(e)
        else:
            raise e
    if resolved_queue:
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
    >>> pipe = text_file_source("example.txt")
    >>> done = await text_file_sink(pipe, "copy.txt")
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
    >>> pipe = text_file_source("example.txt")
    >>> done = await text_file_sink(pipe, "copy.txt")
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
    >>> pipe = binary_file_source("example.bin")
    >>> pipe = log_step(pipe, "Bytes read", lambda x: len(x))
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
    >>> pipe = binary_file_source("example.bin")
    >>> pipe = log_step(pipe, "Bytes read", lambda x: len(x))
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
    >>> pipe = array_source([
    ...     '{"name": "Alice", "age": 30}',
    ...     '{"name": "Bob", "age": 25}',
    ... ])
    >>> pipe = map_str_to_json_step(pipe)
    >>> pipe = map_step(pipe, lambda x: x['age'])
    >>> await array_sink(pipe)
    [30, 25]
    return map_step(async_iter, lambda x: json.loads(x))
    """
    return map_step(async_iter, lambda x: json.loads(x))


async def flatten_step(async_iter: AsyncIterator[Iterable[T]]) -> AsyncIterator[T]:
    """
    Data flow step that flattens an iterator of iterators into a sinle iterator.

    This function takes an asynchronous iterator where each item is itself an iterable (like a list or tuple)
    and flattens it. This means it iterates over each element of these iterables in order, yielding them
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
    >>> pipe = array_source([[1,2], [3,4]])
    >>> pipe = flatten_step(pipe)
    >>> done = await array_sink(pipe)
    >>> assert done == [1, 2, 3, 4]
    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            for subitem in item:
                yield subitem


async def async_flatten_step(
    async_iter: AsyncIterator[AsyncIterator[T]],
) -> AsyncIterator[T]:
    """Takes an async iterator where each item is an AsyncIterator and iterates over it."""
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            async with asyncstdlib.scoped_iter(item) as owned_subiter:
                async for subitem in owned_subiter:
                    yield subitem


def async_init_step(
    async_iter: AsyncIterator[T],
    f: Callable[[AsyncIterator[T]], Coroutine],
    num_outputs: int = 1,
) -> AsyncIterator[Output]:
    class AsyncInitInputIterator:
        """Wraps the input iterator and eagerly gets the first item.  This pulls data through the stream in case our
        async_init function is waiting on it."""

        def __init__(self):
            self.iter = async_iter.__aiter__()
            self.first_item_task = asyncio.create_task(self.iter.__anext__())

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.first_item_task:
                ret = self.first_item_task
                self.first_item_task = None
                return await ret
            else:
                return await self.iter.__anext__()

    class AsyncInitOutputIterator:
        """Wraps the output and doesn't create the real iterator until the first item is requested."""

        def __init__(self, init_event):
            self.iter = None
            self.init_event = init_event

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.iter:
                await self.init_event.wait()
            return await self.iter.__anext__()

    init_event = asyncio.Event()
    outputs = [AsyncInitOutputIterator(init_event) for _ in range(num_outputs)]

    async def do_init():
        input = AsyncInitInputIterator()
        step = await f(input)

        for output, iterable in zip(outputs, to_tuple(step)):
            output.iter = iterable.__aiter__()
        init_event.set()

    asyncio.create_task(do_init())

    if len(outputs) == 1:
        return outputs[0]
    else:
        return outputs


def extract_value_step(
    async_iter: AsyncIterator[T],
    value: Callable[[T], Any],
    condition: Optional[Callable[[T], bool]] = None,
) -> Tuple[AsyncIterator[T], asyncio.Future[Any]]:
    """Extracts a value from the iterator.  Returns the iterator and a future containing the value"""
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
    exception_handler: Callable[[BaseException], None],
) -> AsyncIterator[T]:
    """Wraps an async iterator and logs any exceptions that occur."""
    try:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                yield item
    except exception_type as e:
        yield exception_handler(e)


async def exception_handler_step(
    async_iter: AsyncIterator[T],
    exception_type: Type[BaseException],
    exception_handler: Callable[[BaseException], None],
) -> AsyncIterator[T]:
    """Wraps an async iterator and logs any exceptions that occur."""
    try:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                yield item
    except exception_type as e:
        exception_handler(e)


async def log_step(
    async_iter: AsyncIterator[T], name: str, formatter: Callable[[T], Any] = lambda x: x
) -> AsyncIterator[T]:
    """Logs out the messages coming through a source."""
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            formatted = formatter(item)
            logger.info(f"{name}: {formatted}")
            yield item


async def count_step(async_iter: AsyncIterator[T], name: str) -> AsyncIterator[T]:
    """Counts the number of messages streamed through a pipe."""
    counter = 0
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            counter += 1
            yield item
    logger.info(f"{name} count: {counter}")


async def filter_step(
    async_iter: AsyncIterator[T], condition: Callable[[T], bool]
) -> AsyncIterator[T]:
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if condition(item):
                yield item


async def map_step(
    async_iter: AsyncIterator[T],
    func: Callable[[T], Output],
    ignore_none: Optional[bool] = False,
) -> AsyncIterator[Output]:
    """Handles both sync and async functions
    Optional 'ignore_none' clause indicates that a value of None should be dropped.  Allows filtering and mapping in one step.
    """
    is_async = inspect.iscoroutinefunction(func)
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            v = func(item)
            if is_async:
                v = await v
            if (not ignore_none) or v:
                yield v


async def concat_step(*async_iters: List[AsyncIterator[T]]) -> AsyncIterator[T]:
    """Concatenates multiple iterators into a single iterator."""
    for async_iter in async_iters:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                yield item


async def chunk_bytes_step(
    async_iter: AsyncIterator[bytes], chunk_size: AwaitableOrObj[int]
) -> AsyncIterator[bytes]:
    """Breaks byte buffers into chunks with a maximum size."""
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            resolved_chunk_size = await resolve_awaitable_or_obj(chunk_size)
            for i in range(0, len(item), resolved_chunk_size):
                data = item[i : i + resolved_chunk_size]
                # logger.debug(f"Chunked {len(data)} bytes")
                yield data


async def min_size_bytes_step(
    async_iter: AsyncIterator[bytes], min_size: AwaitableOrObj[int]
) -> AsyncIterator[bytes]:
    """Ensures byte streams have a least a minimum size."""
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


async def merge_step(*async_iters: list[AsyncIterator[T]]) -> AsyncIterator[T]:
    """Merges multiple iterators into one.  Differs from concat in that it takes from both iterators at the same time.
    An exception in any iterators cancels all."""
    # TODO Implement with backpressure.
    queue = QueueWithException()
    tasks = [asyncio.create_task(queue.enqueue_iterator(it)) for it in async_iters]

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
    """Takes several iterators and collects each into different keys in a dictionary.  The first in the list driver the output."""
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
        asyncio.create_task(consume_iter(k, iter))
        for k, iter in secondary_iters.items()
    ]
    async for item in first_iter:
        # logger.debug(f"Merging dict for {item}")
        yield {first_key: item, **values}
    for task in tasks:
        task.cancel()


def partition_step(
    async_iter: AsyncIterator[T], condition: Callable[[T], bool]
) -> Tuple[AsyncIterator[T], AsyncIterator[T]]:
    """Partitions a source into two iterators, one where the condition is true and one where it is false.
    Exceptions are propagated to both iterators."""
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
            true_queue.set_exception(e)
            false_queue.set_exception(e)
        await true_queue.put(EndOfStreamMarker)  # Signal end of iteration
        await false_queue.put(EndOfStreamMarker)

    distribution_task = asyncio.create_task(distribute())
    true_iterator = queue_source(true_queue)
    false_iterator = queue_source(false_queue)

    return true_iterator, false_iterator


def fork_step(
    async_iter: AsyncIterator[T],
    backpressure: bool = True,
) -> Tuple[AsyncIterator[T], AsyncIterator[T]]:
    """Forks a stream, splitting a single source into two separate sources.
    If backpressure is True (the default), then items will only be consumed as fast as the first returned source is consumed,
    the second source will be rate limited to the first.  If false, items will always be consumed as fast as possible.

    If backpressure is True, then exceptions will only be propagated to the first iterator.  If False, it will go to both.
    """

    def with_backpressure():
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

    def no_backpressure():
        left_queue = QueueWithException()
        right_queue = QueueWithException()

        async def distribute():
            try:
                async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                    async for item in owned_aiter:
                        await left_queue.put(item)
                        await right_queue.put(item)
            except Exception as e:
                left_queue.set_exception(e)
                right_queue.set_exception(e)
            await left_queue.put(EndOfStreamMarker)  # Signal end of iteration
            await right_queue.put(EndOfStreamMarker)

        asyncio.create_task(distribute())
        left_iterator = queue_source(left_queue)
        right_iterator = queue_source(right_queue)

        return left_iterator, right_iterator

    iterators = with_backpressure() if backpressure else no_backpressure()
    return iterators


def buffer_step(
    async_iter: AsyncIterator[T], join_func: Callable[[T], T]
) -> AsyncIterator[T]:
    """Acts as a buffer that can receive multiple byte messages and aggregates them on the way out."""
    queue = QueueWithException()

    async def make_iterator() -> AsyncIterator[T]:
        ongoing = True
        while ongoing:
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            try:
                item = await queue.get()
                if item == EndOfStreamMarker:
                    # logger.info(f"None was on top of queue")
                    return
                data = [item]
            except asyncio.CancelledError:
                # logger.info(f"ByteBuffer cancelled")
                return
            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = queue.get_nowait()
                    if chunk == EndOfStreamMarker:
                        # logger.info(f"Got None in nowait")
                        ongoing = False
                        break
                    data.append(chunk)
                except QueueEmpty:
                    # logger.info(f"Got QueueEmpty in nowait")
                    break
            yield join_func(data)

    asyncio.create_task(queue.enqueue_iterator(async_iter))
    return make_iterator()


def byte_buffer_step(async_iter: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    return buffer_step(async_iter, lambda x: b"".join(x))


def str_buffer_step(async_iter: AsyncIterator[str]) -> AsyncIterator[str]:
    return buffer_step(async_iter, lambda x: "".join(x))
