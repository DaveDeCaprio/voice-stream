import asyncio
import datetime
import logging
from typing import AsyncIterator, Callable, Tuple

from voice_stream.basic_streams import log_step
from voice_stream.events import SpeechStart, BaseEvent, SpeechEnd

logger = logging.getLogger(__name__)

SpeechStep = Callable[
    [AsyncIterator[bytes]], Tuple[AsyncIterator[str], AsyncIterator[BaseEvent]]
]


def speech_with_start_detection_step(
    async_iter: AsyncIterator[bytes], speech_step: SpeechStep
):
    pipe, speech_events = speech_step(async_iter)
    # speech_events = log_step(speech_events, "Speech event")
    speech_start = filter_spurious_speech_start_events_step(speech_events)
    return pipe, speech_start


def filter_spurious_speech_start_events_step(
    async_iter: AsyncIterator[BaseEvent], threshold: float = 1.0
):
    """Detects the start of speech and returns the audio that was detected."""

    class WaitingIterator:
        def __init__(self):
            self.aiter = async_iter.__aiter__()
            self.task_for_next_item = None

        def __aiter__(self):
            return self

        async def __anext__(self):
            end_time = None
            start_event = None
            while True:
                now = datetime.datetime.now()
                timeout_to_use = (
                    (end_time - now).microseconds / 1e6 if end_time else None
                )
                if timeout_to_use and timeout_to_use <= 0:
                    timeout_to_use = None
                if not self.task_for_next_item:
                    self.task_for_next_item = asyncio.create_task(
                        self.aiter.__anext__()
                    )
                # logger.debug(f"Starting to wait with timeout {timeout_to_use}.")
                done, pending = await asyncio.wait(
                    {self.task_for_next_item}, timeout=timeout_to_use
                )
                if pending:
                    # We didn't get an end event, so this was a real speech start.
                    # logger.debug("No response received in time.  Sending start event.")
                    assert not done
                    assert start_event
                    return start_event
                else:
                    assert done
                    self.task_for_next_item = None
                    item = await done.pop()
                    if isinstance(item, SpeechStart):
                        # logger.debug("Received Speech Start.  Resetting timer")
                        end_time = datetime.datetime.now() + datetime.timedelta(
                            seconds=threshold
                        )
                        start_event = item
                    elif isinstance(item, SpeechEnd):
                        # logger.debug("Received Speech End, ignoring the start.")
                        end_time = None
                        start_event = None
                    else:
                        logger.info(f"Received unknown speech event, ignoring. {item}")

    pipe = WaitingIterator()
    pipe = log_step(pipe, "New Speech Detected", lambda x: x.time_since_start)
    return pipe
