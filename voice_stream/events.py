import dataclasses
from typing import Optional

from pydantic import BaseModel


class BaseEvent(BaseModel):
    """
    Base class for structured objects used in streams.
    """

    event_name: str
    """The name of the event."""


class SpeechStart(BaseEvent):
    """
    Indicates that speech has been detected in the incoming audio.
    """

    time_since_start: float
    """The time when the speech starts (in seconds) relative to the start of the audio."""

    event_name: str = "speech_start"
    """Always 'speech_start'."""


class SpeechEnd(BaseEvent):
    """
    Indicates that the end of speech has been detected in the incoming audio.
    """

    time_since_start: float
    """The time when the speech ends (in seconds) relative to the start of the audio."""
    event_name: str = "speech_end"
    """Always 'speech_end'"""


class SpeechPartialResult(BaseEvent):
    """
    Provides partial results from a speech recognizer.
    """

    text: str
    """Partial text returned."""
    time_since_start: float
    """The time when the speech ends (in seconds) relative to the start of the audio."""
    event_name: str = "speech_partial_result"
    """Always 'speech_partial_result'"""


class SpeechToTextResult(BaseEvent):
    """
    Provides partial results from a speech recognizer.
    """

    text: str
    """Recognized text"""
    time_since_start: float
    """The time when the speech ends (in seconds) relative to the start of the audio."""
    event_name: str = "speech_to_text_result"
    """Always 'speech_to_text_result'"""


class TimedText(BaseEvent):
    """
    Represents text synchronized to an audio stream. Used for rate-limited output of TextToSpeech.
    """

    text: str
    """The text"""
    duration_in_seconds: float
    """The duration of the audio associated with this text."""
    event_name: str = "timed_text"
    """Always 'timed_text'."""


class AnsweringMachineDetection(BaseEvent):
    """
    Indicates that an answering machine has been detected on a telephone call.
    """

    call_id: str
    """The unique identifier for the call."""
    answered_by: str
    """Who took the call - 'machine' or 'human'."""
    time_since_start: float
    """Time since the start of the call."""
    event_name: str = "amd"
    """Always 'amd'."""

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
    """

    call_id: str
    """The unique identifier for the call."""
    stream_id: Optional[str] = None
    """The unique identifier for the audio stream associated with this call."""
    event_name: str = "call_started"
    """Always 'call_started'."""


class CallEnded(BaseEvent):
    """
    Indicates that a telephone call has ended.
    """

    event_name: str = "call_ended"
    """Always 'call_ended'."""
