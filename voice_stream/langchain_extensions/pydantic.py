# import json
# import re
# from typing import Type
#
# from langchain_community.chat_models import ChatVertexAI
# from langchain_core.exceptions import OutputParserException
# from langchain_core.output_parsers import BaseOutputParser, StrOutputParser
# from langchain_core.prompts import ChatPromptTemplate
# from pydantic import ValidationError
#
# from voice_stream.types import T
#
#
# def reduce_schema(schema: dict) -> dict:
#     if "title" in schema:
#         del schema["title"]
#     if "type" in schema:
#         del schema["type"]
#     for prop in schema["properties"]:
#         if "title" in schema["properties"][prop]:
#             del schema["properties"][prop]["title"]
#     return schema
#
#
# def pydantic_chain(cls):
#     return (
#         ChatPromptTemplate.from_messages([("human", "{query}")])
#         | ChatVertexAI()
#         | StrOutputParser()
#     )
#
#
# # main_chain = (
# #         RunnableParallel(
# #             message=itemgetter("message"),
# #             history=itemgetter("history"),
# #             assistant=lambda x: x['assistant'] if 'assistant' in x else "default",
# #         )
# #         | RunnablePassthrough.assign(assistant=routing_chain)
# #         | RunnablePassthrough.assign(
# #     # RunnableLambda doesn't work here because it breaks streaming.
# #     output=RunnableSwitch(
# #         "assistant",
# #         branches = {_.name: _.chain for _ in assistants},
# #         default_branch = [_.chain for _ in assistants if _.name == 'default'][0]
# #     )
# # )
# # )
#
#
# PYDANTIC_FORMAT_INSTRUCTIONS = """The output should be formatted as a JSON instance that conforms to the JSON schema below.
#
# As an example, for the schema {{"properties": {{"foo": {{"title": "Foo", "description": "a list of strings", "type": "array", "items": {{"type": "string"}}}}}}, "required": ["foo"]}}
# the object {{"foo": ["bar", "baz"]}} is a well-formatted instance of the schema. The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not well-formatted.
#
# Here is the output schema:
# ```
# {schema}
# ```"""
#
#
# class PydanticV2OutputParser(BaseOutputParser):
#     """Parse an output using a pydantic model."""
#
#     pydantic_object: Type[T]
#     """The pydantic model to parse."""
#
#     def parse(self, text: str) -> T:
#         try:
#             # Greedy search for 1st json candidate.
#             match = re.search(
#                 r"\{.*\}", text.strip(), re.MULTILINE | re.IGNORECASE | re.DOTALL
#             )
#             json_str = match.group() if match else ""
#             json_object = json.loads(json_str, strict=False)
#             return self.pydantic_object.parse_obj(json_object)
#
#         except (json.JSONDecodeError, ValidationError) as e:
#             name = self.pydantic_object.__name__
#             msg = f"Failed to parse {name} from completion {text}. Got: {e}"
#             raise OutputParserException(msg, llm_output=text)
#
#     def get_format_instructions(self) -> str:
#         schema = self.pydantic_object.schema()
#
#         # Remove extraneous fields.
#         reduced_schema = schema
#         if "title" in reduced_schema:
#             del reduced_schema["title"]
#         if "type" in reduced_schema:
#             del reduced_schema["type"]
#         # Ensure json in context is well-formed with double quotes.
#         schema_str = json.dumps(reduced_schema)
#
#         return PYDANTIC_FORMAT_INSTRUCTIONS.format(schema=schema_str)
#
#     @property
#     def _type(self) -> str:
#         return "pydantic"
#
#
# NEXT_QUESTION_PROMPT = """
# You are trying to create an "ActionItem", which is "A task that to be captured in the to-do list.".
#
# Here is the schema of the structure you need to fill in:
# {
#         "properties": {
#             "name": {"description": "A short name for the task that will be displayed in lists.", "type": "string"},
#             "description": {"description": "A detailed description of the task.", "type": "string"},
#             "assignee": {"description": "Email address of the person to whom this task is assigned.", "type": "string"},
#             "due_date": {"description": "Date on which the task is due.", "format":"date", "type": "string"},
#             "done": {"description": "Whether the task is done or not.", "type":"boolean", "default": False},
#         },
#         "required": ["name", "description", "assignee", "due_date"],
#     }
# }
#
# At the start of each message, I'll tell you what the information you already have is.
#
# Ask the user questions, one at a time, until you have all the information.
# """
#
# PARSING_PROMPT = """
# You are trying to create an "ActionItem", which is "A task that to be captured in the to-do list.".
#
# The output should be formatted as a JSON instance that conforms to the JSON schema below.
#
# As an example, for the schema {"properties": {"foo": {"title": "Foo", "description": "a list of strings", "type": "array", "items": {"type": "string"}}}, "required": ["foo"]}
# the object {"foo": ["bar", "baz"]} is a well-formatted instance of the schema. The object {"properties": {"foo": ["bar", "baz"]}} is not well-formatted.
#
# Here is the output schema:
# {
#         "properties": {
#             "name": {"description": "A short name for the task that will be displayed in lists.", "type": "string"},
#             "description": {"description": "A detailed description of the task.", "type": "string"},
#             "assignee": {"description": "Email address of the person to whom this task is assigned.", "type": "string"", "format":"email"},
#             "due_date": {"description": "Date on which the task is due.", "format":"date", "type": "string"},
#             "done": {"description": "Whether the task is done or not.", "type":"boolean"},
#         },
#     }
# }
#
# Today is Wednesday, 1/10/2024
#
# Extract whatever structured information you can from the user's message.  Be conservative, if you aren't sure, just ignore the field.  Don't make up anything.  Don't include any fields in the output that you can explicitly populate based on the input.
# """
