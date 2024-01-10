from typing import Dict

from langchain_core.runnables import RunnableBranch
from langchain_core.runnables.base import RunnableLike

from voice_stream.langchain_extensions.parsers import logger


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
