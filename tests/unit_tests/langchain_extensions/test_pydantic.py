# from datetime import date
#
# import pytest
# from pydantic import BaseModel, ValidationError, Field
#
# from voice_stream.langchain_extensions.pydantic import reduce_schema, pydantic_chain
#
#
# class ActionItem(BaseModel):
#     """A task that to be captured in the to-do list."""
#
#     name: str = Field(
#         description="A short name for the task that will be displayed in lists."
#     )
#     description: str = Field(description="A detailed description of the task.")
#     assignee: str = Field(
#         description="Email address of the person to whom this task is assigned."
#     )
#     due_date: date = Field(description="Date on which the task is due.")
#     done: bool = Field(description="Whether the task is done or not.", default=False)
#
#
# def example_chain():
#     return pydantic_chain(ActionItem)
#
#
# def test_model_validation():
#     data = {"name": "Dave"}
#     with pytest.raises(ValidationError) as ve:
#         ActionItem.model_validate(data)
#     assert len(ve.value.errors()) == 3
#
#
# def test_model_schema():
#     schema = ActionItem.model_json_schema()
#     reduced = reduce_schema(schema)
#     assert reduced == {
#         "description": "A task that to be captured in the to-do list.",
#         "properties": {
#             "name": {
#                 "description": "A short name for the task that will be displayed in lists.",
#                 "type": "string",
#             },
#             "description": {
#                 "description": "A detailed description of the task.",
#                 "type": "string",
#             },
#             "assignee": {
#                 "description": "Email address of the person to whom this task is assigned.",
#                 "type": "string",
#             },
#             "due_date": {
#                 "description": "Date on which the task is due.",
#                 "format": "date",
#                 "type": "string",
#             },
#             "done": {
#                 "description": "Whether the task is done or not.",
#                 "type": "boolean",
#                 "default": False,
#             },
#         },
#         "required": ["name", "description", "assignee", "due_date"],
#     }
#
#
# # # def test_model_input_chain():
# #     chain = pydantic_chain(ActionItem)
# #     result = chain.invoke({"message":"Have Jeff pick up my clothes on Tuesday", "current_parse":{}})
