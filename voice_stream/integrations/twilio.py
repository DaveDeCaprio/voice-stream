"""
`Twilio <https://www.twilio.com>`_ provides an API for making and receiving telephone calls.  You can use Twilio along
with VoiceStream to automate calls with an LLM.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import logging
from typing import AsyncIterator, Tuple, Optional, Dict, Any, Callable, Union, Coroutine

import asyncstdlib

from voice_stream.core import (
    AwaitableOrObj,
    partition_step,
    map_step,
    map_str_to_json_step,
    filter_step,
    fork_step,
    extract_value_step,
    merge_step,
    queue_source,
)
from voice_stream.events import BaseEvent, CallStarted, CallEnded
from voice_stream.types import map_future, resolve_awaitable_or_obj

logger = logging.getLogger(__name__)


def twilio_split_media_step(
    async_iter: AsyncIterator[dict],
) -> Tuple[AsyncIterator[dict], AsyncIterator[dict]]:
    """
    Data flow step that splits a Twilio stream into two separate streams, one for media
    stream and another for control messages.

    Parameters
    ----------
    async_iter : AsyncIterator[dict]
        An asynchronous iterator over Twilio stream events. Each event is represented
        as a dictionary.

    Returns
    -------
    Tuple[AsyncIterator[dict], AsyncIterator[dict]]
        A tuple of two asynchronous iterators. The first iterator yields dictionaries
        of media stream events, and the second yields dictionaries of control messages.

    Notes
    -----
    - The function relies on the presence of an "event" key in each dictionary to
      determine the type of the message.
    - This function is useful for handling different types of events in a Twilio stream
      separately, especially in applications that need to process media and control
      messages differently.

    Examples
    --------
    >>> media_stream, control_messages = twilio_split_media_step(async_iter)
    """
    return partition_step(async_iter, lambda x: x["event"] == "media")


class TwilioSequenceError(ValueError):
    """Indicates a problem in the sequence numbers for messages received from Twilio."""

    pass


async def twilio_check_sequence_step(
    async_iter: AsyncIterator[dict],
) -> AsyncIterator[dict]:
    """
    Data flow step that verifies that no Twilio websocket messages were lost.

    This step checks each message in the provided asynchronous iterator for a
    sequence number and validates that the messages are in the correct sequence.
    If a message is found to be out of sequence or missing a sequence number, a
    TwilioSequenceError is raised.

    Parameters
    ----------
    async_iter : AsyncIterator[dict]
        An asynchronous iterator over Twilio websocket messages, where each message
        is expected to be a dictionary containing a 'sequenceNumber' key.

    Yields
    ------
    AsyncIterator[dict]
        An asynchronous iterator yielding the same Twilio websocket messages after
        verifying their sequence.

    Raises
    ------
    TwilioSequenceError
        If a message is missing a sequence number or if the sequence of messages is
        found to be out of order.

    Notes
    -----
    - The function starts by expecting a sequence number of 1 and increments this
      expectation with each message.
    """
    expected = 1
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if "sequenceNumber" not in item:
                raise TwilioSequenceError(f"Message {item} has no sequence number")
            if int(item["sequenceNumber"]) != expected:
                raise TwilioSequenceError(
                    f"Expected sequence number {expected}, got {item['sequenceNumber']}"
                )
            expected += 1
            yield item


async def twilio_close_on_stop_step(
    async_iter: AsyncIterator[dict],
    close_func: Callable[[], Union[None, Coroutine[Any, Any, None]]],
) -> AsyncIterator[dict]:
    """
    Data flow step that calls a close function when a stop message is received.

    Receives Twilio websocket messages and checks for a 'stop' event.  Upon receiving a 'stop' message, it triggers
    a closure function (typically to close the websocket) and continues to yield the remaining messages.

    Parameters
    ----------
    async_iter : AsyncIterator[dict]
        An asynchronous iterator over Twilio websocket messages.
    close_func : Callable[[], None]
        A asynchronous callable function that is executed when a 'stop' event is received. This function is awaited
        when the 'stop' event occurs and is intended to close the websocket or perform other cleanup actions.

    Return
    ------
    AsyncIterator[dict]
        An asynchronous iterator yielding Twilio websocket messages.

    Notes
    -----
    - The function does not stop yielding messages after the 'stop' event; it continues
      to yield any remaining messages in the iterator after performing the closure action.

    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if item["event"] == "stop":
                logger.info("Stop message received, closing websocket")
                await close_func()
            yield item


async def twilio_media_to_audio_bytes_step(
    async_iter: AsyncIterator[dict],
) -> AsyncIterator[bytes]:
    """
    Data flow step that extracts the audio bytes from Twilio media stream messages.

    Twilio media stream messages come in as JSON, which are usually converted to Python dictionaries.
    Each dictionary contains a 'media' key with a 'payload' sub-key. The function decodes the base64-encoded payload into bytes
    representing audio data and yields these bytes.

    Parameters
    ----------
    async_iter : AsyncIterator[dict]
        An asynchronous iterator over Twilio media stream messages.

    Yields
    ------
    AsyncIterator[bytes]
        An asynchronous iterator yielding audio data in bytes.

    Raises
    ------
    ValueError
        If a message in the stream does not contain a 'media' key or if the 'media' key
        does not have a 'payload' sub-key.

    Notes
    -----
    - The function is specifically designed to handle media streams from Twilio,
      converting the audio into bytes objects for further processing.
    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if "media" not in item:
                raise ValueError(f"Message {item} has no media")
            yield base64.b64decode(item["media"]["payload"])


async def audio_bytes_to_twilio_media_step(
    async_iter: AsyncIterator[bytes], stream_sid: AwaitableOrObj[str]
) -> AsyncIterator[dict]:
    """
    Data flow step that formats audio bytes into outgoing Twilio media stream messages.

    To play audio over a Twilio media stream, messages must be formatted as JSON with the audio bytes base64-encoded.
    This step converts raw audio data into the correct format for Twilio.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator over audio bytes
    stream_sid: AwaitableOrObj[str]
        The Twilio stream id for the outgoing audio.  This is passed with the :class:`~voice_stream.CallStart` message when the call is initiated.

    Returns
    -------
    AsyncIterator[bytes]
        An asynchronous iterator yielding outgoing Twilio media stream messages.

    """
    resolved_stream_sid = None
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for packet in owned_aiter:
            encoded_data = base64.b64encode(packet).decode("utf-8")
            if not resolved_stream_sid:
                resolved_stream_sid = await resolve_awaitable_or_obj(stream_sid)
            yield {
                "event": "media",
                "streamSid": resolved_stream_sid,
                "media": {"payload": encoded_data},
            }


async def twilio_format_events_step(
    async_iter: AsyncIterator[Dict],
) -> AsyncIterator[BaseEvent]:
    """
    Data flow step to formats Twilio event messages into VoiceStream call status objects.

    This function converts Twilio event messages into the VoiceStream generic call event classes.  These include
    :class:`~voice_stream.events.CallStarted`, :class:`~voice_stream.events.CallEnded`, and :class:`~voice_stream.events.AnsweringMachineDetection`

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator over Twilio event messages.

    Yields
    ------
    AsyncIterator[BaseEvent]
        An asynchronous iterator yielding `BaseEvent` objects that represent formatted
        Twilio events.

    Notes
    -----
    - Twilio messages that don't correspond to events are ignored.
    - For 'start' events, it creates a `CallStarted` event object with the call and
      stream IDs.
    - For 'stop' events, it creates a `CallEnded` event object.
    """

    def format_events(input):
        if input["event"] == "start":
            return CallStarted(
                call_id=input["start"]["callSid"], stream_id=input["start"]["streamSid"]
            )
        if input["event"] == "stop":
            return CallEnded()

    return map_step(async_iter, format_events)


@dataclasses.dataclass
class TwilioInputFlow:
    """Experimental"""

    # Stream of audio bytes.
    audio: AsyncIterator[bytes]
    # All the events coming from the main stream in twilio, excluding raw audio.
    events: AsyncIterator[BaseEvent]
    all_twilio_messages: Optional[AsyncIterator[dict]]
    call_sid_f: asyncio.Future[str]
    stream_sid_f: asyncio.Future[str]
    inbound_queue_f: asyncio.Future[asyncio.Queue[BaseEvent]]
    outbound_queue_f: asyncio.Future[asyncio.Queue[BaseEvent]]
    current_calls: Dict[str, Any]

    @classmethod
    def create(
        cls,
        source: AsyncIterator[dict],
        close_func: Callable[[], None],
        current_calls: Dict[str, Any],
        expose_all_messages: bool = False,
    ) -> TwilioInputFlow:
        """
        Creates a basic flow to receive audio and call event data from Twilio.
        expose_all_messages - If true, all incoming twilio messages, including raw audio, will be set through the 'all_twilio_messages' iterator.  Otherwise this iterator will be empty.
        """
        stream = map_str_to_json_step(source)
        stream = filter_step(stream, lambda x: x["event"] != "connected")
        if expose_all_messages:
            stream, all_twilio_messages = fork_step(stream)
        else:
            all_twilio_messages = None
        stream = twilio_check_sequence_step(stream)
        # Retrieve values once the call is connected.
        stream, call_sid_f = extract_value_step(
            stream, value=lambda x: x["start"]["callSid"]
        )
        stream, stream_sid_f = extract_value_step(
            stream, value=lambda x: x["streamSid"]
        )
        outbound_queue_f = map_future(call_sid_f, lambda x: current_calls[x].outbound)
        inbound_queue_f = map_future(call_sid_f, lambda x: current_calls[x].inbound)
        audio, events = partition_step(stream, lambda x: x["event"] == "media")
        audio = twilio_media_to_audio_bytes_step(audio)
        events = twilio_close_on_stop_step(events, close_func=close_func)
        events = twilio_format_events_step(events)
        events = merge_step(events, queue_source(inbound_queue_f))
        return cls(
            audio,
            events,
            all_twilio_messages,
            call_sid_f,
            stream_sid_f,
            inbound_queue_f,
            outbound_queue_f,
            current_calls,
        )
