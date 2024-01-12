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

    Examples
    --------
    >>> queue = queue_source()
    >>> queue.put(1)
    >>> queue.put(2)
    >>> queue.set_exception(RuntimeError("Test Error"))
    >>> await array_sink(queue)
    Caught exception: Test Error

    Notes
    -----
    - If an exception is set, it maintains its place in the queue.  If there are existing items in the queue, those will
      be returned in calls to `get()` until all items in the queue when `set_exception` was called have been exhausted.
    """

    def __init__(self):
        super().__init__()
        self.exception = None

    async def enqueue_iterator(self, async_iter: AsyncIterator):
        """Enqueues items from an asynchronous iterator to the queue.

        Parameters:
        -----------
            async_iter : AsyncIterator
                An asynchronous iterator whose items will be enqueued.

        """
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
        """Sets an exception to be propagated to consumers.

        When an exception is set, the EndOfStreamMarker is enqueued and when that marker is removed from the queue,
        the exception will be raised.
        """
        self.exception = exception
