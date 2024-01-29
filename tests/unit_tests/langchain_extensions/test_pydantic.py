import datetime
import logging
from datetime import date

import pytest
from langchain.globals import set_llm_cache
from langchain_community.cache import SQLiteCache
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError, Field

from voice_stream.langchain_extensions.pydantic import (
    reduce_schema,
    PydanticV2OutputParser,
)

logger = logging.getLogger(__name__)

set_llm_cache(SQLiteCache(database_path=".langchain.db"))


class ActionItem(BaseModel):
    """A task that to be captured in the to-do list."""

    name: str = Field(
        description="A short name for the task that will be displayed in lists."
    )
    description: str = Field(description="A detailed description of the task.")
    assignee: str = Field(
        description="Email address of the person to whom this task is assigned."
    )
    due_date: date = Field(description="Date on which the task is due.")
    done: bool = Field(description="Whether the task is done or not.", default=False)


def test_model_validation():
    data = {"name": "Dave"}
    with pytest.raises(ValidationError) as ve:
        ActionItem.model_validate(data)
    assert len(ve.value.errors()) == 3


def test_model_schema():
    schema = ActionItem.model_json_schema()
    reduced = reduce_schema(schema)
    assert reduced == {
        "description": "A task that to be captured in the to-do list.",
        "properties": {
            "name": {
                "description": "A short name for the task that will be displayed in lists.",
                "type": "string",
            },
            "description": {
                "description": "A detailed description of the task.",
                "type": "string",
            },
            "assignee": {
                "description": "Email address of the person to whom this task is assigned.",
                "type": "string",
            },
            "due_date": {
                "description": "Date on which the task is due.",
                "format": "date",
                "type": "string",
            },
            "done": {
                "description": "Whether the task is done or not.",
                "type": "boolean",
                "default": False,
            },
        },
        "required": ["name", "description", "assignee", "due_date"],
    }


def test_pydantic_parser_format_instructions():
    parser = PydanticV2OutputParser(pydantic_model=ActionItem)
    prompt = parser.get_format_instructions()
    assert """Here is the output schema:\n""" in prompt
    assert (
        """"properties": {"name": {"description": "A short name for the task that will """
        in prompt
    )


def test_pydantic_parser_correct():
    parser = PydanticV2OutputParser(pydantic_model=ActionItem)
    result = parser.parse(
        """Result: {"name":"Laundry", "description":"Do laundry", "assignee":"joe@example.com", "due_date":"2024-01-23"}"""
    )
    assert result == ActionItem(
        name="Laundry",
        description="Do laundry",
        assignee="joe@example.com",
        due_date=datetime.datetime(2024, 1, 23, 0, 0),
    )


def test_pydantic_parser_date_error():
    parser = PydanticV2OutputParser(pydantic_model=ActionItem)
    with pytest.raises(OutputParserException) as e:
        parser.parse(
            """Result: {"name":"Laundry", "description":"Do laundry", "assignee":"joe@example.com", "due_date":"today"}"""
        )
    assert (
        e.value.args[0]
        == "due_date: 'today' - Input should be a valid date or datetime, input is too short"
    )


def test_pydantic_parser_date_multiple_errors():
    parser = PydanticV2OutputParser(pydantic_model=ActionItem)
    with pytest.raises(OutputParserException) as e:
        parser.parse(
            """Result: {"description":"Do laundry", "assignee":"joe@example.com", "due_date":"today"}"""
        )
    assert (
        e.value.args[0]
        == "name: Field required\ndue_date: 'today' - Input should be a valid date or datetime, input is too short"
    )


def test_pydantic_parsing_prompt():
    parser = PydanticV2OutputParser(pydantic_model=ActionItem)
    chain = parser.get_parsing_prompt() | ChatOpenAI(model="gpt-4") | parser
    with pytest.raises(OutputParserException) as e:
        chain.invoke(
            {
                "query": "Have Jeff pick up my clothes",
                "parse": "{}",
                "errors": "",
                "history": [],
            }
        )
    assert "due_date: Field required" in e.value.args[0]


def test_pydantic_next_question_prompt():
    parser = PydanticV2OutputParser(pydantic_model=ActionItem)
    chain = (
        parser.get_next_question_prompt()
        | ChatOpenAI(model="gpt-4")
        | StrOutputParser()
    )
    next_question = chain.invoke(
        {
            "query": "Have Jeff pick up my clothes",
            "parse": "{}",
            "errors": "",
            "history": [],
        }
    )
    logger.debug(f"Next question: {next_question}")


def test_pydantic_full_next_question():
    action_item_parser = PydanticV2OutputParser(pydantic_model=ActionItem)
    ret = action_item_parser.get_chain().invoke(
        {
            "query": "Have Jeff pick up my clothes from the dry cleaner on the corner by 2024-01-12"
        }
    )
    logger.debug(f"Response:\n{ret}")
    assert isinstance(ret["parsed_result"], ActionItem)
    assert ret["parsed_result"].due_date == datetime.date(2024, 1, 12)
    assert "clothes" in ret["output"].lower()
