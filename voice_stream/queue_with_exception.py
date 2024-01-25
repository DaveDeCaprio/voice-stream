import asyncio
import logging
from typing import AsyncIterator, AsyncGenerator

import asyncstdlib

from voice_stream.types import (
    EndOfStreamMarker,
    QueueExceptionMarker,
    T,
    format_current_task,
)

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
    >>> await queue.put(1)
    >>> await queue.put(2)
    >>> await queue.set_exception(RuntimeError("Test Error"))
    >>> await array_sink(queue)
    Caught exception: Test Error

    Notes
    -----
    - If an exception is set, it maintains its place in the queue.  If there are existing items in the queue, those will
      be returned in calls to `get()` until all items in the queue when `set_exception` was called have been exhausted.
    """

    def __init__(self, *kargs, **kwargs):
        super().__init__(*kargs, **kwargs)
        self.exception = None

    async def enqueue_iterator(
        self,
        async_iter: AsyncIterator[T],
        include_end_of_stream: bool = True,
        propagate_exception: bool = True,
    ) -> AsyncGenerator[T, None]:
        """Enqueues items from an asynchronous iterator to the queue.

        If the asynchronous iterator is cancelled, no end of stream is appended.

        Parameters:
        -----------
            async_iter : AsyncIterator
                An asynchronous iterator whose items will be enqueued.
            include_end_of_stream : bool, optional
                Whether to include an end of stream marker after iteration is completed.
        """
        if not hasattr(async_iter, "__aiter__"):
            raise ValueError(f"Object {async_iter} is not an async iterator")
        try:
            async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                async for item in owned_aiter:
                    await self.put(item)
            if include_end_of_stream:
                # logger.debug(f"End of stream in task {format_current_task()}")
                await self.put(EndOfStreamMarker)
        except Exception as e:
            if propagate_exception:
                # logger.debug(f"Queuing exception in task {format_current_task()} - {e}")
                await self.set_exception(e)
            else:
                raise e

    def _get(self):
        out = super()._get()
        if out == QueueExceptionMarker and self.exception:
            # logger.debug("Raising exception in queue")
            exception = self.exception
            self.exception = None
            raise exception
        return out

    async def set_exception(self, exception: Exception):
        """Sets an exception to be propagated to consumers.

        When an exception is set, the EndOfStreamMarker is enqueued and when that marker is removed from the queue,
        the exception will be raised.
        """
        if self.exception:
            raise ValueError(
                "set_exception called when the queue already had an exception."
            )
        self.exception = exception
        await self.put(QueueExceptionMarker)
