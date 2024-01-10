import asyncio
import inspect
from asyncio import Future
from typing import TypeVar, Tuple, List, Optional, Union, Callable, AsyncIterator

from voice_stream.basic_streams import (
    single_source,
    empty_source,
    T,
    Output,
    FutureOrObj,
)

T = TypeVar("T")
Input = TypeVar("Input", contravariant=True)
Output = TypeVar("Output", covariant=True)

SourceConvertable = Optional[Union[Callable[[], T], T]]


def to_source(x: SourceConvertable) -> AsyncIterator[T]:
    """Creates a source from a callable or value."""
    if callable(x):
        return x()
    elif x:
        return single_source(x)
    else:
        return empty_source()


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
    ret = loop.create_future()

    def callback(fut: Future[T]) -> None:
        try:
            ret.set_result(func(fut.result()))
        except Exception as e:
            ret.set_exception(e)

    f.add_done_callback(callback)
    return ret


async def resolve_obj_or_future(obj: FutureOrObj[T]) -> T:
    """Returns the result of an object or a future"""
    if isinstance(obj, asyncio.Future):
        return await obj
    return obj
