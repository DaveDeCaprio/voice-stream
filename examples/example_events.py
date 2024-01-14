from voice_stream.events import BaseEvent


class TextInput(BaseEvent):
    text: str
    event_name: str = "text_input"


class TextOutput(BaseEvent):
    text: str
    event_name: str = "text_output"
