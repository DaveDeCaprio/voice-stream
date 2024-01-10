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
    TypeVar,
    Optional,
    Type,
    Iterable,
    Coroutine,
    List,
)

import aiofiles

from voice_stream._queue_with_exception import QueueWithException
from voice_stream.types import to_tuple, resolve_obj_or_future

T = TypeVar("T")
Output = TypeVar("Output")
FutureOrObj = Union[T, asyncio.Future[T]]

logger = logging.getLogger(__name__)

# Streams are an abstraction on top of ASyncIterators.
# Sources are iterators.
# Sinks take an iterator.
# Steps take iterators and return iterators


def empty_source() -> AsyncIterator[T]:
    """Returns an empty async iterator that immediately sends an end of iteration."""
    return array_source([])


def none_source() -> AsyncIterator[T]:
    """Returns an async iterator that returns one item, which is None."""
    return array_source([None])


async def empty_sink(async_iter: AsyncIterator[T]) -> None:
    """An async iterator created from an array.  Returns the array."""
    async for _ in async_iter:
        pass
    # logger.info("Empty sink finished")


async def single_source(item: T) -> AsyncIterator[T]:
    """An async iterator created from an array."""
    await asyncio.sleep(0)
    yield item


async def array_source(array: list[T]) -> AsyncIterator[T]:
    """An async iterator created from an array."""
    for item in array:
        await asyncio.sleep(0)
        yield item


async def array_sink(async_iter: AsyncIterator[T]) -> list[T]:
    """An async iterator created from an array.  Returns the array."""
    array = []
    async for item in async_iter:
        array.append(item)
    return array


class QueueAsyncIterator:
    """An AsyncIterator that works over its own queue and adds a 'put' method."""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.iter = _make_queue_iterator(self.queue)

    async def put(self, item):
        return await self.queue.put(item)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.iter.__anext__()


def queue_source(queue: FutureOrObj[asyncio.Queue[T]] = None) -> AsyncIterator[T]:
    """Returns an async iterator over objects in a queue.  The queue must be closed by putting None into it."""
    if queue:

        async def gen():
            resolved_queue = await resolve_obj_or_future(queue)
            while True:
                try:
                    item = await resolved_queue.get()
                    if item is None:
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
    queue: Optional[FutureOrObj[Union[QueueWithException, asyncio.Queue]]] = None,
) -> asyncio.Queue:
    """Writes each element of the async_iter to a queue"""
    resolved_queue = None
    try:
        async for message in async_iter:
            if resolved_queue is None:
                if queue:
                    resolved_queue = await resolve_obj_or_future(queue)
                else:
                    resolved_queue = asyncio.Queue()
            await resolved_queue.put(message)
    except Exception as e:
        if resolved_queue and hasattr(resolved_queue, "set_exception"):
            await resolved_queue.set_exception(e)
        else:
            raise e
    if resolved_queue:
        await resolved_queue.put(None)  # signal completion
    return resolved_queue


async def text_file_source(filename: str) -> AsyncIterator[str]:
    """Returns an async iterator over the lines in the file"""
    async with aiofiles.open(filename, "rt") as f:
        async for line in f:
            line = line[:-1] if line[-1] == "\n" else line
            yield line


async def text_file_sink(
    async_iter: AsyncIterator[Any], filename: FutureOrObj[str]
) -> None:
    """Write each element of the async_iter to a file as a line"""
    return await _file_sink(async_iter, filename, "wt", lambda x: f"{x}\n")


async def binary_file_source(
    filename: str, chunk_size: int = 4096
) -> AsyncIterator[bytes]:
    """Returns an async iterator over the bytes in the file"""
    async with aiofiles.open(filename, "rb") as f:
        while True:
            chunk = await f.read(chunk_size)
            if not chunk:
                break
            yield chunk


async def binary_file_sink(
    async_iter: AsyncIterator[bytes], filename: FutureOrObj[str]
) -> None:
    """Append each block of bytes from async_iter to the file"""
    return await _file_sink(async_iter, filename, "wb", lambda x: x)


async def _file_sink(
    async_iter: AsyncIterator[T],
    filename: FutureOrObj[str],
    mode: str,
    prep_func: Callable[[T], Any],
) -> None:
    f = None
    try:
        async for block in async_iter:
            # We wait to resolve the filename until we have a message to write
            if f is None:
                filename = await resolve_obj_or_future(filename)
                f = await aiofiles.open(filename, mode)
            await f.write(prep_func(block))
    finally:
        if f is not None:
            await f.close()
            logger.debug(f"Closed {filename}")


def map_str_to_json_step(async_iter: AsyncIterator[str]) -> AsyncIterator[dict]:
    return map_step(async_iter, lambda x: json.loads(x))


async def flatten_step(async_iter: AsyncIterator[Iterable[T]]) -> AsyncIterator[T]:
    """Takes an async iterator where each item is iterable and iterates over it."""
    async for item in async_iter:
        for subitem in item:
            yield subitem


async def async_flatten_step(
    async_iter: AsyncIterator[AsyncIterator[T]],
) -> AsyncIterator[T]:
    """Takes an async iterator where each item is an AsyncIterator and iterates over it."""
    async for item in async_iter:
        async for subitem in item:
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
        async for item in async_iter:
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
        async for item in async_iter:
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
        async for item in async_iter:
            yield item
    except exception_type as e:
        exception_handler(e)


async def log_step(
    async_iter: AsyncIterator[T], name: str, formatter: Callable[[T], Any] = lambda x: x
) -> AsyncIterator[T]:
    """Logs out the messages coming through a source."""
    async for item in async_iter:
        formatted = formatter(item)
        logger.info(f"{name}: {formatted}")
        yield item


async def count_step(async_iter: AsyncIterator[T], name: str) -> AsyncIterator[T]:
    """Counts the number of messages streamed through a pipe."""
    counter = 0
    async for item in async_iter:
        counter += 1
        yield item
    logger.info(f"{name} count: {counter}")


async def filter_step(
    async_iter: AsyncIterator[T], condition: Callable[[T], bool]
) -> AsyncIterator[T]:
    async for item in async_iter:
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
    async for item in async_iter:
        v = func(item)
        if is_async:
            v = await v
        if (not ignore_none) or v:
            yield v


async def concat_step(*async_iters: List[AsyncIterator[T]]) -> AsyncIterator[T]:
    """Concatenates multiple iterators into a single iterator."""
    for async_iter in async_iters:
        async for item in async_iter:
            yield item


async def chunk_bytes_step(
    async_iter: AsyncIterator[bytes], chunk_size: FutureOrObj[int]
) -> AsyncIterator[bytes]:
    """Breaks byte buffers into chunks with a maximum size."""
    async for item in async_iter:
        resolved_chunk_size = await resolve_obj_or_future(chunk_size)
        for i in range(0, len(item), resolved_chunk_size):
            data = item[i : i + resolved_chunk_size]
            # logger.debug(f"Chunked {len(data)} bytes")
            yield data


async def min_size_bytes_step(
    async_iter: AsyncIterator[bytes], min_size: FutureOrObj[int]
) -> AsyncIterator[bytes]:
    """Ensures byte streams have a least a minimum size."""
    buffer = b""
    async for item in async_iter:
        combined = buffer + item
        if len(combined) >= await resolve_obj_or_future(min_size):
            yield combined
            buffer = b""
        else:
            buffer = combined
    if len(buffer) > 0:
        yield buffer


async def merge_step(*async_iters: list[AsyncIterator[T]]) -> AsyncIterator[T]:
    """Merges multiple iterators into one.  Differs from concat in that it takes from both iterators at the same time.
    An exception in any iterators cancels all."""
    queue = QueueWithException()
    tasks = [asyncio.create_task(queue.enqueue_iterator(it)) for it in async_iters]

    try:
        completed = 0
        while completed < len(async_iters):
            item = await queue.get()
            if item is None:
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

    async def consume_iter(key, iter):
        # logger.debug(f"Starting consumer for {key}")
        async for item in iter:
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
            async for item in async_iter:
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
        await true_queue.put(None)  # Signal end of iteration
        await false_queue.put(None)

    distribution_task = asyncio.create_task(distribute())
    true_iterator = _make_queue_iterator(true_queue)
    false_iterator = _make_queue_iterator(false_queue)

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
        right_iterator = _make_queue_iterator(right_queue)

        async def consume_and_queue() -> AsyncIterator[T]:
            async for item in async_iter:
                await right_queue.put(item)
                yield item
            await right_queue.put(None)

        left_iterator = consume_and_queue()
        return left_iterator, right_iterator

    def no_backpressure():
        left_queue = QueueWithException()
        right_queue = QueueWithException()

        async def distribute():
            try:
                async for item in async_iter:
                    await left_queue.put(item)
                    await right_queue.put(item)
            except Exception as e:
                left_queue.set_exception(e)
                right_queue.set_exception(e)
            await left_queue.put(None)  # Signal end of iteration
            await right_queue.put(None)

        asyncio.create_task(distribute())
        left_iterator = _make_queue_iterator(left_queue)
        right_iterator = _make_queue_iterator(right_queue)

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
                if item is None:
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
                    if chunk is None:
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


async def _make_queue_iterator(
    queue: Union[asyncio.Queue, QueueWithException]
) -> AsyncIterator[T]:
    """Returns an async iterator over objects in a queue.  The queue must be closed by putting None into it."""
    while True:
        try:
            # logger.debug(f"Dequeuing {queue}")
            item = await queue.get()
            # logger.debug(f"Dequeued {item}")
            if item is None:
                break
        except asyncio.CancelledError:
            # logger.debug("Queue iterator cancelled.")
            break
        yield item
