import asyncio
import importlib
import inspect
import logging
import traceback
from asyncio import Future, CancelledError
from typing import (
    TypeVar,
    Tuple,
    List,
    Optional,
    Union,
    Callable,
    AsyncIterator,
    Awaitable,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
Input = TypeVar("Input", contravariant=True)
Output = TypeVar("Output", covariant=True)
AwaitableOrObj = Union[T, Awaitable[T]]

SourceConvertable = Optional[Union[Callable[[], T], T]]

OptionalMultipleOutputs = Union[AsyncIterator[T], Tuple]


class _MarkerObjectType:
    """This is a marker object used to indicate a special case during stream iteration."""

    pass


EndOfStreamMarker = _MarkerObjectType()
"""Special marker object that indicates the end of a stream.
"""


QueueExceptionMarker = _MarkerObjectType()
"""Special marker object that indicates an exception.
"""


def to_source(x: SourceConvertable) -> AsyncIterator[T]:
    """Creates a source from a callable or value.

    Tries to turn the input value into a VoiceStream source.
    - If it is a callable, assumes that is a callable that returns an AsyncIterator
    - If it is an object, return a single_source containing the object.
    - If it is None, return an empty_source.

    To create a source that explicitly yields `None`, pass lambda x: none_source()
    """
    if callable(x):
        # logger.debug("Callable source")
        return x()
    elif x is None:
        # logger.debug("Empty source")
        from voice_stream.core import empty_source

        return empty_source()
    else:
        # logger.debug(f"Single source {x}")
        from voice_stream.core import single_source

        return single_source(x)


def to_tuple(obj) -> Tuple:
    if isinstance(obj, Tuple):
        return obj
    if isinstance(obj, List):
        return tuple(obj)
    else:
        return (obj,)


def from_tuple(obj):
    return obj[0] if len(obj) == 1 else obj


def is_async_iterator(obj):
    return inspect.iscoroutinefunction(getattr(obj, "__anext__", None)) and hasattr(
        obj, "__aiter__"
    )


def map_future(f: Future[T], func: Callable[[T], Output]) -> Future[Output]:
    """Returns a future that will be resolved with the result of applying func to the result of f.

    Words are made lowercase and punctuation is removed
    before counting.

    Parameters
    ----------
    input_file : str
        Path to text file.

    Returns
    -------
    collections.Counter
        dict-like object where keys are words and values are counts.

    Examples
    --------
    >>> count_words("text.txt")
    """
    loop = asyncio.get_running_loop()
    out = loop.create_future()

    def callback(fut: Future[T]) -> None:
        try:
            out.set_result(func(fut.result()))
        except Exception as e:
            out.set_exception(e)

    f.add_done_callback(callback)
    return out


async def resolve_awaitable_or_obj(obj: AwaitableOrObj[T]) -> T:
    """Returns the result of an object or a future"""
    if inspect.isawaitable(obj):
        return await obj
    return obj


def load_attribute(full_path):
    # Split the path into module and attribute
    parts = full_path.split(".")
    module_path = ".".join(parts[:-1])
    attribute_name = parts[-1]

    try:
        # Import the module
        module = importlib.import_module(module_path)
        # Return the attribute
        return getattr(module, attribute_name)
    except ImportError:
        print(f"Module {module_path} not found.")
    except AttributeError:
        print(f"Attribute {attribute_name} not found in module {module_path}.")


async def cancel_with_confirmation(task: asyncio.Task) -> None:
    """Cancels a task and waits for confirmation that it has stopped."""
    task.cancel()
    try:
        a = await task
        # logger.debug(f"Return {a}")
    except asyncio.CancelledError:
        # logger.debug("C")
        pass
    except StopAsyncIteration:
        # logger.debug("S")
        pass
    # logger.debug(f"Cancelled task {format_task(task)}")


def format_task(task: asyncio.Task):
    if task.cancelled():
        if task.done():
            state = "canceled"
        else:
            state = "cancelling"
    elif task.done():
        result = "exception" if task.exception() else "normal"
        state = f"finished ({result})"
    else:
        state = "pending"  # The task is still pending or running
    return task.get_name() + " " + state


def format_current_task():
    return format_task(asyncio.current_task())


def format_stack_trace(task: asyncio.Task):
    try:
        stack = task.get_stack()

        # Format the stack trace into a string
        if stack:
            last_frame = stack[-1]
            formatted_stack_trace = "".join(traceback.format_stack(last_frame))
        else:
            formatted_stack_trace = "No stack trace available"
        return formatted_stack_trace
    except Exception as e:
        logger.exception("Error printing stack")


def background_task(a: Awaitable):
    """Creates a background task that will log any exceptions that occur."""
    task = asyncio.create_task(a)
    task.add_done_callback(background_callback)
    return task


def background_callback(task: asyncio.Task):
    # logger.debug(f"Finished background task {task}")
    try:
        ex = task.exception()
        if ex:
            logger.error(
                f"Exception thrown from background {format_task(task)} task: {ex}"
            )
    except CancelledError:
        pass
