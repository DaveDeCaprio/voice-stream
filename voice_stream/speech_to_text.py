import asyncio
import datetime
import logging
from typing import AsyncIterator, Callable, Tuple

import asyncstdlib

from voice_stream.core import log_step
from voice_stream.events import SpeechStart, BaseEvent, SpeechEnd, SpeechPartialResult

logger = logging.getLogger(__name__)

SpeechStep = Callable[
    [AsyncIterator[bytes]], Tuple[AsyncIterator[str], AsyncIterator[BaseEvent]]
]


def speech_with_start_detection_step(
    async_iter: AsyncIterator[bytes], speech_step: SpeechStep
):
    """
    Data flow step to perform speech recognition on a stream of audio and produce a robust start detection event.

    Takes a normal speech recognition step and filters the speech events to remove false :class:`~voice_stream.events.SpeechStart` events.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator that yields bytes of audio data.

    speech_step : SpeechStep
        A function that takes an async iterator as input and returns a tuple of a stream and speech events.

    Returns
    -------
    tuple
        A tuple of the audio stream and filtered speech start events.

    Example
    -------
    >>> speech_step = google_speech_v1_step(
    ...    stream,
    ...    speech_async_client,
    ...    audio_format=AudioFormat.WEBM_OPUS,
    ...    include_events=True,
    ... )
    >>> stream = fastapi_websocket_bytes_source(websocket)
    >>> stream, speech_events = speech_with_start_detection_step(stream, speech_step)
    >>> stream = merge_step(stream, speech_events)
    >>> await array_sink(stream)
    [SpeechStart(time_since_start=1.2), SpeechEnd(time_since_start=2.5), "Hello, how are you?"]
    """
    stream, speech_events = speech_step(async_iter)
    # speech_events = log_step(speech_events, "Speech event")
    speech_start = filter_spurious_speech_start_events_step(speech_events)
    return stream, speech_start


def filter_spurious_speech_start_events_step(
    async_iter: AsyncIterator[BaseEvent], threshold_secs: float = 1.0
):
    """
    Data flow step the filters a stream of speech events to remove false positives.

    This step filters speech events so that if a :class:`~voice_stream.events.SpeechStart` is quickly followed by a
    :class:`~voice_stream.events.SpeechEnd`, it is considered spurious and ignored.  This is useful for avoiding false
    detections which could create unnecessary interruptions.

    Parameters
    ----------
    async_iter : AsyncIterator[voice_stream.events.BaseEvent]
        An asynchronous iterator that yields bytes of audio data.

    threshold_secs : float
        The number of seconds to wait for a SpeechEnd after a SpeechStart is received.

    Returns
    -------
    AsyncIterator[voice_stream.events.BaseEvent]
        A modified event stream that removes the spurious :class:`~voice_stream.events.SpeechStart` events.

    Example
    -------
    >>> stream, speech_events = speech_step(async_iter)
    >>> speech_events = filter_spurious_speech_start_events_step(speech_events)

    Notes
    -------
    - Using this step does cause a delay in the movement of SpeechStart events down the stream.
    """

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
                            seconds=threshold_secs
                        )
                        start_event = item
                    elif isinstance(item, SpeechEnd):
                        # logger.debug("Received Speech End, ignoring the start.")
                        end_time = None
                        start_event = None
                    else:
                        logger.info(f"Received unknown speech event, ignoring. {item}")

    stream = WaitingIterator()
    stream = log_step(stream, "New Speech Detected", lambda x: x.time_since_start)
    return stream


async def first_partial_speech_result_step(
    async_iter: AsyncIterator[BaseEvent],
) -> AsyncIterator[SpeechPartialResult]:
    """
    Data flow step that returns the first partial result after speech starts.

    This step uses partial results from the speech recognizer to signal the start of speech.  It waits for a
    :class:`~voice_stream.events.SpeechStart` event and then returns the first
    :class:`~voice_stream.events.SpeechPartialResult` that occurs after that.

    Parameters
    ----------
    async_iter : AsyncIterator[voice_stream.events.BaseEvent]
        An asynchronous iterator of Speech events

    Returns
    -------
    async_iter : AsyncIterator[voice_stream.events.SpeechPartialResult]
        The input stream filtered for just the first partial result after each speech start event.

    Example
    -------
    >>> async def gen():
    ...     yield SpeechStart(time_since_start=1)
    ...     yield SpeechEnd(time_since_start=2)
    ...     yield SpeechPartialResult(text="hello", time_since_start=1.5)
    ...     yield SpeechPartialResult(text="hello world", time_since_start=2)
    ...     yield SpeechStart(time_since_start=1)
    ...     yield SpeechPartialResult(text="next", time_since_start=2.5)
    >>> stream = gen()
    >>> stream = first_partial_speech_result_step(stream)
    >>> out = await array_sink(stream)
    >>> assert out == [
    ...     SpeechPartialResult(text="hello", time_since_start=1.5),
    ...     SpeechPartialResult(text="next", time_since_start=2.5)
    ... ]
    """
    started = False
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if started:
                if isinstance(item, SpeechPartialResult):
                    started = False
                    yield item
            elif isinstance(item, SpeechStart):
                started = True
