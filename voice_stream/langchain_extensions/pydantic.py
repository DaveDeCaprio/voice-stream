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
