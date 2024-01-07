import dataclasses


class BaseEvent:
    event_name: str


@dataclasses.dataclass
class SpeechStart(BaseEvent):
    time_since_start: float
    event_name: str = "speech_start"


@dataclasses.dataclass
class SpeechEnd(BaseEvent):
    time_since_start: float
    event_name: str = "speech_end"


@dataclasses.dataclass
class TextInput(BaseEvent):
    text: str
    event_name: str = "text_input"


@dataclasses.dataclass
class TextOutput(BaseEvent):
    text: str
    event_name: str = "text_output"


@dataclasses.dataclass
class TimedText(BaseEvent):
    text: str
    duration_in_seconds: float
    event_name: str = "timed_text"


@dataclasses.dataclass
class AnsweringMachineDetection(BaseEvent):
    call_id: str
    answered_by: str
    time_since_start: float
    event_name: str = "amd"

    def is_human(self):
        return self.answered_by == "human"


@dataclasses.dataclass
class CallStarted(BaseEvent):
    call_id: str
    stream_id: str
    event_name: str = "call_started"


@dataclasses.dataclass
class CallEnded(BaseEvent):
    event_name: str = "call_ended"
