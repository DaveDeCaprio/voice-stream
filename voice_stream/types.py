import asyncio
import importlib
import inspect
from asyncio import Future
from typing import TypeVar, Tuple, List, Optional, Union, Callable, AsyncIterator

T = TypeVar("T")
Input = TypeVar("Input", contravariant=True)
Output = TypeVar("Output", covariant=True)
FutureOrObj = Union[T, asyncio.Future[T]]

SourceConvertable = Optional[Union[Callable[[], T], T]]


def to_source(x: SourceConvertable) -> AsyncIterator[T]:
    """Creates a source from a callable or value."""
    if callable(x):
        return x()
    elif x:
        from voice_stream.basic_streams import single_source

        return single_source(x)
    else:
        from voice_stream.basic_streams import empty_source

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
