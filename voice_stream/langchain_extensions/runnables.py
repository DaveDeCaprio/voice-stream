import logging
from pprint import pformat
from typing import Dict, Iterator

from langchain_core.runnables import RunnableBranch
from langchain_core.runnables.base import RunnableLike, RunnableGenerator

from voice_stream.types import T

logger = logging.getLogger(__name__)


class RunnableSwitch(RunnableBranch):
    """Like RunnableBranch, but just takes a dict"""

    def __init__(
        self,
        input_key: str,
        branches: Dict[
            str,
            RunnableLike,
        ],
        default_branch: RunnableLike,
    ) -> None:
        def check(y):
            def f(x):
                logger.info(f"Checking {x} == {y}")
                return x[input_key] == y

            return f

        b = [*[(check(k), v) for k, v in branches.items()], default_branch]
        super().__init__(*b)


def RunnableLogger(header: str):
    """
    Logs out whatever is coming through the pipeline.

    Parameters
    ----------
    header
        Message to prepend to the log.

    Yields
    ------
    Yields the same items that come in.
    """

    async def async_gen(input: Iterator[T]) -> Iterator[T]:
        # hold partial input until we get a comma
        async for entry in input:
            logger.info(f"{header} {type(entry)}\n{pformat(entry)}")
            yield entry

    def gen(input: Iterator[T]) -> Iterator[T]:
        # hold partial input until we get a comma
        for entry in input:
            logger.info(f"{header} {type(entry)}\n{pformat(entry)}")
            yield entry

    return RunnableGenerator(gen, atransform=async_gen)
