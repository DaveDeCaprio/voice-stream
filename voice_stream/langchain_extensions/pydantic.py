import json
import re
from operator import itemgetter
from typing import Type

from langchain_community.chat_models import ChatVertexAI
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import BaseOutputParser, StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    HumanMessagePromptTemplate,
)
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableBranch
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from voice_stream.langchain_extensions.memory import LastKMessagesPlaceholder
from voice_stream.types import T


def reduce_schema(schema: dict) -> dict:
    if "title" in schema:
        del schema["title"]
    if "type" in schema:
        del schema["type"]
    for prop in schema["properties"]:
        if "title" in schema["properties"][prop]:
            del schema["properties"][prop]["title"]
    return schema


def pydantic_chain(cls):
    return (
        ChatPromptTemplate.from_messages([("human", "{query}")])
        | ChatOpenAI(model="gpt-4")
        | StrOutputParser()
    )


class PydanticV2OutputParser(BaseOutputParser):
    """Parse an output using a pydantic model."""

    pydantic_model: Type[T]
    """The pydantic model to parse."""

    def parse(self, text: str) -> T:
        # Greedy search for 1st json candidate.
        match = re.search(
            r"\{.*\}", text.strip(), re.MULTILINE | re.IGNORECASE | re.DOTALL
        )
        json_str = match.group() if match else ""
        json_object = json.loads(json_str, strict=False)
        try:
            return self.pydantic_model.parse_obj(json_object)
        except ValidationError as e:
            errors = e.errors(
                include_url=False, include_context=True, include_input=True
            )

            def format_error(e):
                input = f"'{e['input']}' - " if e["msg"] != "Field required" else ""
                return f"{', '.join(e['loc'])}: {input}{e['msg']}"

            reformatted = "\n".join([format_error(e) for e in errors])
            raise OutputParserException(
                error=reformatted, observation=json_object, llm_output=text
            )

    def get_format_instructions(self) -> str:
        return PYDANTIC_FORMAT_INSTRUCTIONS.format(output_schema=self._output_schema())

    def _output_schema(self) -> str:
        schema = self.pydantic_model.schema()

        # Remove extraneous fields.
        reduced_schema = schema
        if "title" in reduced_schema:
            del reduced_schema["title"]
        if "type" in reduced_schema:
            del reduced_schema["type"]
        # Ensure json in context is well-formed with double quotes.
        return json.dumps(reduced_schema)

    @property
    def _type(self) -> str:
        return "pydantic"

    def get_parsing_prompt(self):
        return ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content=PARSING_PROMPT.format(
                        model_name=self.pydantic_model.__name__,
                        output_schema=self._output_schema(),
                    )
                ),
                LastKMessagesPlaceholder(variable_name="history", max_messages=1),
                HumanMessagePromptTemplate.from_template(
                    "Existing Parse:\n{parse}\n\nErrors:\n{errors}\n\nUser message:\n{message}"
                ),
            ]
        )

    def get_next_question_prompt(self):
        return ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content=NEXT_QUESTION_PROMPT.format(
                        model_name=self.pydantic_model.__name__,
                        output_schema=self._output_schema(),
                    )
                ),
                LastKMessagesPlaceholder(variable_name="history", max_messages=6),
                HumanMessagePromptTemplate.from_template(
                    "{message}\n\nADDITIONAL INFO:\nParse:\n{parse}\n\nErrors:\n{errors}"
                ),
            ]
        )

    def get_confirmation_prompt(self):
        return ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content=CONFIRMATION_PROMPT.format(
                        model_name=self.pydantic_model.__name__,
                        output_schema=self._output_schema(),
                    )
                ),
                HumanMessagePromptTemplate.from_template("{parsed_result}"),
            ]
        )

    def get_chain(self):
        next_question_chain = (
            {
                "message": itemgetter("message"),
                "history": itemgetter("history"),
                "parse": lambda x: x["exception"].observation,
                "errors": lambda x: x["exception"].args[0],
            }
            | self.get_next_question_prompt()
            | ChatOpenAI(model="gpt-4")
            | StrOutputParser()
        )
        confirmation_chain = (
            self.get_confirmation_prompt()
            | ChatOpenAI(model="gpt-4")
            | StrOutputParser()
        )
        return (
            {
                "message": itemgetter("message"),
                "history": lambda x: x.get("history", []),
                "parse": lambda x: x.get("parse", "{}"),
                "errors": lambda x: x.get("errors", ""),
            }
            # Take the initial user message and try to parse it.  We either get a full object back, or an exception with the missing info
            | (
                self.get_parsing_prompt()
                | ChatOpenAI(model="gpt-4")
                | self
                | RunnableLambda(lambda x: {"parsed_result": x})
            ).with_fallbacks(
                [RunnableLambda(lambda x: x)],
                exceptions_to_handle=(OutputParserException,),
                exception_key="exception",
            )
            # If we didn't have a clean parse, then generate the next question.
            | RunnableBranch(
                [
                    lambda x: "exception" in x,
                    RunnablePassthrough.assign(response=next_question_chain),
                ],
                RunnablePassthrough.assign(response=confirmation_chain),
            )
        )


PYDANTIC_FORMAT_INSTRUCTIONS = """The output should be formatted as a JSON object that conforms to the JSON schema below.

As an example, for the schema {{"properties": {{"foo": {{"title": "Foo", "description": "a list of strings", "type": "array", "items": {{"type": "string"}}}}}}, "required": ["foo"]}}
the object {{"foo": ["bar", "baz"]}} is a well-formatted instance of the schema. The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not well-formatted.

Here is the output schema:
```
{output_schema}
```"""


PARSING_PROMPT = """
You are an expert at extracting information from free text user responses into a structured JSON objects that conform to a specific 
schema.

As an example, for the schema {{"properties": {{"foo": {{"title": "Foo", "description": "a list of strings", "type": "array", "items": {{"type": "string"}}}}}}, "required": ["foo"]}}
the object {{"foo": ["bar", "baz"]}} is a well-formatted instance of the schema. The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not well-formatted.

The schema you are using for this task is:   
```
{output_schema}
```

The object is a "{model_name}"

You may not have enough information from the user to fill in all fields.  That is totally fine.  You can produce a partial
object, which will later be filled in with other values.  Omit any fields where you aren't sure you have the right information.  Be conservative.

You will be given several inputs.  
- A "Previous Parse" which contains a partial version of the JSON object created from earlier in the conversation.
- A list of zero or more "Errors", which are problems with the "previous parse" object that prevented it from being correctly parsed. 
- A previous AI chat message, which is the question which was asked to the user based on the previous output.  It might be empty if this is the first parse.
- A "User message", which is what the user responded with.

Your job is to output a new JSON object that updates the "Previous Parse" based on the user message.
"""


NEXT_QUESTION_PROMPT = """
You are working in a system extracting information from free text user responses into a structured JSON objects that conform to a specific 
schema.  

As an example, for the schema {{"properties": {{"foo": {{"title": "Foo", "description": "a list of strings", "type": "array", "items": {{"type": "string"}}}}}}, "required": ["foo"]}}
the object {{"foo": ["bar", "baz"]}} is a well-formatted instance of the schema. The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not well-formatted.

The schema you are using for this task is:   
```
{output_schema}
```

The object is a "{model_name}"

Your job is to understand what information you need to successfully complete the structured JSON object, and then figure 
out the right next question to ask the user to elicit that information.  Only ask one question at a time.

You will be given the recent chat history for context.

The last user message in the context will have some extra information appended to it.
- A "Parse" which contains the current parsed version of the object based on the user's responses.
- A list of zero or more "Errors", which are problems with the "Parse" object.  This includes incorrect or missing fields. 

Your output should be the next question to ask the user.  Remember, only ask for 1 piece of information.
"""

CONFIRMATION_PROMPT = """The previous conversation has taken information from the user and used it to construct a JSON object.

The object is a "{model_name}", and it's schema is:
```
{output_schema}
```

Your job is to take the object present in the message, and provide a confirmation response summarizing the information.  
The summary should be conversational and using normal prose.  Don't just list out all the fields and values.
"""
