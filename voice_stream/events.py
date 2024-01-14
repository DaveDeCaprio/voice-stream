import dataclasses

from pydantic import BaseModel


class BaseEvent(BaseModel):
    """
    Base class for structured objects used in streams.

    Attributes
    ----------
    event_name : str
        The name of the event.
    """

    event_name: str


class SpeechStart(BaseEvent):
    """
    Indicates that speech has been detected in the incoming audio.

    Attributes
    ----------
    time_since_start : float
        The time when the speech starts (in seconds) relative to the start of the audio.
    event_name : str
        Always 'speech_start'.
    """

    time_since_start: float
    event_name: str = "speech_start"


class SpeechEnd(BaseEvent):
    """
    Indicates that the end of speech has been detected in the incoming audio.

    Attributes
    ----------
    time_since_start : float
        The time when the speech ends (in seconds) relative to the start of the audio.
    event_name : str
        Always 'speech_end'
    """

    time_since_start: float
    event_name: str = "speech_end"


class TimedText(BaseEvent):
    """
    Represents text synchronized to an audio stream. Used for rate-limited output of TextToSpeech.

    Attributes
    ----------
    text : str
        The text
    duration_in_seconds : float
        The duration of the audio associated with this text.
    event_name : str
        Always 'timed_text'.
    """

    text: str
    duration_in_seconds: float
    event_name: str = "timed_text"


class AnsweringMachineDetection(BaseEvent):
    """
    Indicates that an answering machine has been detected on a telephone call.

    Attributes
    ----------
    call_id : str
        The unique identifier for the call.
    answered_by : str
        Who took the call - 'machine' or 'human'.
    time_since_start : float
        Time since the start of the call.
    event_name : str, optional
        Always 'amd'.

    Methods
    -------
    is_human()
        Check if the call was taken by a human.
    """

    call_id: str
    answered_by: str
    time_since_start: float
    event_name: str = "amd"

    def is_human(self):
        """
        Check if the response was answered by a human.

        Returns
        -------
        bool
            True if the response was answered by a human, False otherwise.
        """
        return self.answered_by == "human"


class CallStarted(BaseEvent):
    """
    Indicates that a new telephone call has been started.

    Attributes
    ----------
    call_id : str
        The unique identifier for the call.
    stream_id : str
        The unique identifier for the audio stream associated with this call.
    event_name : str, optional
        Always 'call_started'.
    """

    call_id: str
    stream_id: str
    event_name: str = "call_started"


class CallEnded(BaseEvent):
    """
    Indicates that a telephone call has ended.

    Attributes
    ----------
    event_name : str
        Always 'call_ended'.
    """

    event_name: str = "call_ended"
