import logging
from typing import Sequence, List, Any

from langchain.output_parsers import EnumOutputParser
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import BaseOutputParser

logger = logging.getLogger(__name__)


class RobustEnumOutputParser(EnumOutputParser):
    """The regular LangChain EnumOutputParser is too strict.  It doesn't strip punctuation, so we use this one instead."""

    def parse(self, response: str) -> Any:
        no_punc_response = response.replace(".", "").replace(",", "")
        return super().parse(no_punc_response)


class FixedValuesOutputParser(BaseOutputParser):
    """Parses output into one of the fixed string values."""

    values: Sequence[str]
    """The allowed values."""

    @property
    def _valid_values(self) -> List[str]:
        return list(self.values)

    def parse(self, response: str) -> Any:
        no_punc_response = response.replace(".", "").replace(",", "").strip().lower()
        for key in self.values:
            if no_punc_response == key.lower():
                return key
        raise OutputParserException(
            f"Response '{response}' is not one of the "
            f"expected values: {self._valid_values}"
        )

    def get_format_instructions(self) -> str:
        return f"Select one of the following options: {', '.join(self._valid_values)}"
