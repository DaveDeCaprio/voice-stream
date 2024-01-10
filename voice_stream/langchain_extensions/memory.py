from typing import Any, List

from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import BaseMessage
from langchain_core.prompts import MessagesPlaceholder
from langchain_core.runnables.history import GetSessionHistoryCallable


class InMemoryChatMessageHistories(GetSessionHistoryCallable):
    def __init__(self):
        self.histories = {}

    def __call__(self, session_id):
        return self.histories.setdefault(session_id, ChatMessageHistory())


class LastKMessagesPlaceholder(MessagesPlaceholder):
    """Variant of Langchain MessagesPlaceholder that only includes the last X messages."""

    variable_name: str
    """Name of variable to use as messages."""

    optional: bool = False

    max_messages: int
    """Max messages to include.  Use 0 for no limit."""

    def __init__(
        self,
        variable_name: str,
        max_messages: int,
        *,
        optional: bool = False,
        **kwargs: Any,
    ):
        super().__init__(
            variable_name=variable_name,
            optional=optional,
            max_messages=max_messages,
            **kwargs,
        )

    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        """Format messages from kwargs.

        Args:
            **kwargs: Keyword arguments to use for formatting.

        Returns:
            List of BaseMessage.
        """
        value = (
            kwargs.get(self.variable_name, [])
            if self.optional
            else kwargs[self.variable_name]
        )
        if not isinstance(value, list):
            raise ValueError(
                f"variable {self.variable_name} should be a list of base messages, "
                f"got {value}"
            )
        for v in value:
            if not isinstance(v, BaseMessage):
                raise ValueError(
                    f"variable {self.variable_name} should be a list of base messages,"
                    f" got {value}"
                )
        if self.max_messages > 0:
            value = value[-self.max_messages :]
        return value
