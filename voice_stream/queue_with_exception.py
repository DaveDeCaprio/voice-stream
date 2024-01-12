import asyncio
import logging
from typing import AsyncIterator

import asyncstdlib

from voice_stream.types import EndOfStreamMarker

logger = logging.getLogger(__name__)


class QueueWithException(asyncio.Queue):
    """
    A specialized asyncio.Queue that propagates exceptions to the consumers.

    This queue enhances the standard asyncio.Queue by handling exceptions. When an exception
    is set in the queue via `set_exception()`, it is propagated to the consumers either when they call `get()` or
    `get_nowait()`.

    Methods
    -------
    enqueue_iterator(self, async_iter: AsyncIterator):
        Enqueues items from an asynchronous iterator to the queue.
        Parameters:
            async_iter : AsyncIterator
                An asynchronous iterator whose items will be enqueued.

    get(self):
        Asynchronously gets an item from the queue, propagating any exception if present.

    get_nowait(self):
        Gets an item from the queue without blocking, propagating any exception if present.

    set_exception(self, exception: Exception):
        Sets an exception to be propagated to consumers.
        Parameters:
            exception : Exception
                The exception to be propagated.

    Raises
    ------
    ValueError
        If the provided async_iter is not an AsyncIterator.
    Exception
        The stored exception, if any, when `get` or `get_nowait` is called.

    Examples
    --------
    >>> queue = queue_source()
    >>> queue.put(1)
    >>> queue.put(2)
    >>> queue.set_exception(RuntimeError("Test Error"))
    >>> await array_sink(queue)
    Caught exception: Test Error
    """

    def __init__(self):
        super().__init__()
        self.exception = None

    async def enqueue_iterator(self, async_iter: AsyncIterator):
        if not hasattr(async_iter, "__aiter__"):
            raise ValueError(f"Object {async_iter} is not an async iterator")
        try:
            async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                async for item in owned_aiter:
                    await self.put(item)
        except Exception as e:
            self.exception = e
        # Signal end of iteration
        await self.put(EndOfStreamMarker)

    async def get(self):
        ret = await super().get()
        return self._handle_get(ret)

    def get_nowait(self):
        ret = super().get_nowait()
        return self._handle_get(ret)

    def _handle_get(self, ret):
        if ret == EndOfStreamMarker and self.exception:
            exception = self.exception
            self.exception = None
            raise exception
        return ret

    def set_exception(self, exception: Exception):
        self.exception = exception
