import asyncio
from typing import AsyncIterator


class QueueWithException:
    """A queue that propagates exceptions.
    If a None is enqueued and the exception is set, then the exception is thrown on put.
    """

    def __init__(self):
        self.queue = asyncio.Queue()
        self.exception = None

    async def enqueue_iterator(self, async_iter: AsyncIterator):
        if not hasattr(async_iter, "__aiter__"):
            raise ValueError(f"Object {async_iter} is not an async iterator")
        try:
            async for item in async_iter:
                await self.queue.put(item)
        except Exception as e:
            self.exception = e
        # Signal end of iteration
        await self.queue.put(None)

    def qsize(self):
        return self.queue.qsize()

    async def put(self, item):
        await self.queue.put(item)

    async def get(self):
        ret = await self.queue.get()
        if ret is None and self.exception:
            exception = self.exception
            self.exception = None
            raise exception
        return ret

    def get_nowait(self):
        ret = self.queue.get_nowait()
        if ret is None and self.exception:
            exception = self.exception
            self.exception = None
            raise exception
        return ret

    def set_exception(self, exception: Exception):
        self.exception = exception
