import asyncio
import inspect
import logging
from asyncio import InvalidStateError
from typing import AsyncIterator, Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


class SimpleFlow(AsyncIterator):
    """Serves as a stub for creating flows.  Acts like an async iterator, but when apply is called with an async iterator, it wraps that iterator."""

    def __init__(self):
        loop = asyncio.get_running_loop()
        self.iter_f = loop.create_future()
        self.iter = None

    def finish(self, *outputs: AsyncIterator[Any]):
        self.outputs = outputs

    def __call__(self, async_iter: AsyncIterator[T]):
        if not self.outputs:
            raise InvalidStateError("Flow was not finished with finish()")
        self.iter_f.set_result(async_iter)
        return self.outputs

    def flow_for_output(self, ix: int):
        def output_wrapper(async_iter: AsyncIterator[T]):
            ret = self.__call__(async_iter)
            return ret[ix]

        return output_wrapper

    def __aiter__(self):
        if self.iter:
            self.iter = self.iter_f.result().__aiter__()
        return self

    async def __anext__(self):
        if not self.iter:
            logger.info(
                "Stub iterator not resolved before use.  If the stream stalls, this could be the problem."
            )
            self.iter = (await self.iter_f).__aiter__()
        return await self.iter.__anext__()


class ResettableIterator(AsyncIterator):
    """Wraps an AsyncIterator and allows it to be used in multiple downstream generators.  It works like a normal
    iterator, but if 'reset' is called, it throws a StopAsyncIteration.  This ends iteration for all downstream tasks.
     However, the underlying iterator isn't finished and so this iterator can be used in another generator.
    """

    def __init__(self, async_iter: AsyncIterator):
        self.async_iter = async_iter
        self.reset_flag = asyncio.Event()
        self.next_item_task = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        # logger.trace(f"Entering __anext__")
        if self.reset_flag.is_set():
            # logger.trace(f"Reset flag set on entry")
            raise StopAsyncIteration
        if self.next_item_task is None:
            self.next_item_task = asyncio.create_task(self.async_iter.__anext__())
        reset_task = asyncio.create_task(self.reset_flag.wait())
        done, pending = await asyncio.wait(
            {self.next_item_task, reset_task}, return_when=asyncio.FIRST_COMPLETED
        )
        # logger.trace(f"Tasks completed: Done is {done}.  Pending is {pending}")
        if reset_task in done:
            # logger.debug(f"Reset flag set on wait")
            raise StopAsyncIteration
        assert reset_task in pending and self.next_item_task in done
        reset_task.cancel()
        ret = await self.next_item_task
        self.next_item_task = None
        return ret

    def reset(self):
        self.reset_flag.set()
        # It's important that we create a new event because we don't know if __anext__ will be called again before the original event is cleared.
        self.reset_flag = asyncio.Event()


class SwitchableIterator:
    """
    An iterator that can change its source.

    It is created with an iterator.  When disconnect is called, it cancels looking at the original iterator and waits for a call to switch.
    When switch is called, moves over to the pull from the new iterator.

    If None is passed for the initial async_iter, then nothing will happen until switch is called.

    The callback allows you to specify whether to propagate a StopAsyncIteration exception.  If you don't propagate, then you must eventually call end_iteration.

    The state model for the initial iterator

    Connected - The iterator is actively forwarding from a source iterator.  Any call to __anext__ will be forwarded to that iterator.
    Disconnected - The is not connected.  Any call to __anext__ will block until the iterator is connected.
    Completed - The iterator is done, it has sent an end of iteration message.
    """

    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"
    COMPLETED = "Completed"

    def __init__(
        self,
        async_iter: AsyncIterator,
        callback=None,
        propagate_end_of_iter: bool = True,
    ):
        self.state = (
            SwitchableIterator.CONNECTED
            if async_iter
            else SwitchableIterator.DISCONNECTED
        )
        self.state_change_event = asyncio.Event()
        self.async_iter = async_iter
        self.callback = callback
        self.propagate_end_of_iter = propagate_end_of_iter
        # logger.debug(f"New SwitchableIterator {self}")

    def __aiter__(self):
        return self

    async def __anext__(self):
        # logger.debug(f"Entering SwitchableIterator.__anext__ {self}")
        while True:
            self.state_change_event.clear()
            try:
                if self.state == SwitchableIterator.DISCONNECTED:
                    await self.state_change_event.wait()
                elif self.state == SwitchableIterator.COMPLETED:
                    raise StopAsyncIteration
                else:
                    assert self.state == SwitchableIterator.CONNECTED
                    next_item_task = asyncio.create_task(self.async_iter.__anext__())
                    state_change_task = asyncio.create_task(
                        self.state_change_event.wait()
                    )
                    done, pending = await asyncio.wait(
                        {next_item_task, state_change_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        except StopAsyncIteration:
                            pass
                    if next_item_task in done:
                        try:
                            return await next_item_task
                        except StopAsyncIteration as e:
                            if self.callback:
                                self.callback()
                            if self.propagate_end_of_iter:
                                raise e
                            # If we aren't propagating the end, disconnect the iterator.
                            self.disconnect()
            finally:
                self.state_change_event.clear()

    def end_iteration(self):
        self.state = SwitchableIterator.COMPLETED
        self.async_iter = None
        self.state_change_event.set()

    def switch(self, async_iter: AsyncIterator):
        if not inspect.isasyncgen(async_iter):  # and not is_async_iterator(async_iter):
            raise ValueError(
                f"SwitchableIterator.switch must be called with an AsyncIterator.  Got {async_iter}"
            )
        # logger.debug("Switching iterators")
        if self.state == SwitchableIterator.COMPLETED:
            raise InvalidStateError("Cannot switch a completed iterator")
        self.state = SwitchableIterator.CONNECTED
        self.async_iter = async_iter
        self.state_change_event.set()

    def disconnect(self):
        # logger.debug("Disconnecting iterators")
        if self.state == SwitchableIterator.COMPLETED:
            raise InvalidStateError("Cannot disconnect a completed iterator")
        self.state = SwitchableIterator.DISCONNECTED
        self.async_iter = None
        self.state_change_event.set()
