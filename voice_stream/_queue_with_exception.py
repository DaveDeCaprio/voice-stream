import asyncio
import logging
from typing import AsyncIterator

import asyncstdlib

from voice_stream.types import EndOfStreamMarker

logger = logging.getLogger(__name__)


class QueueWithException(asyncio.Queue):
    """A queue that propagates exceptions.
    If a None is enqueued and the exception is set, then the exception is thrown on put.
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
