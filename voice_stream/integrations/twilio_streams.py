from __future__ import annotations

import asyncio
import base64
import dataclasses
import logging
from typing import AsyncIterator, Tuple, Optional

from quart import websocket, current_app

from voice_stream.basic_streams import (
    FutureOrObj,
    partition_step,
    map_step,
    map_str_to_json_step,
    filter_step,
    fork_step,
    extract_value_step,
    merge_step,
    queue_source,
)
from voice_stream.types import map_future, resolve_obj_or_future
from voice_stream.events import BaseEvent, CallStarted, CallEnded
from voice_stream.integrations.quart_streams import quart_websocket_source

logger = logging.getLogger(__name__)


def twilio_split_media_step(
    async_iter: AsyncIterator[dict],
) -> Tuple[AsyncIterator[dict], AsyncIterator[dict]]:
    """Returns 2 iterators for a twilio stream, the media stream, and control messages."""
    return partition_step(async_iter, lambda x: x["event"] == "media")


async def twilio_check_sequence_step(
    async_iter: AsyncIterator[dict],
) -> AsyncIterator[dict]:
    """Verifies that no websocket messages were lost in the sequence"""
    expected = 1
    async for item in async_iter:
        assert "sequenceNumber" in item, f"Message {item} has no sequence number"
        if int(item["sequenceNumber"]) != expected:
            raise ValueError(
                f"Expected sequence number {expected}, got {item['sequenceNumber']}"
            )
        expected += 1
        yield item


async def twilio_close_on_stop_step(
    async_iter: AsyncIterator[dict],
) -> AsyncIterator[dict]:
    """Performs a websocket.close() when a stop message is received."""
    async for item in async_iter:
        if item["event"] == "stop":
            logger.info("Stop message received, closing websocket")
            await websocket.close(1000)
        yield item


async def twilio_media_to_audio_bytes_step(
    async_iter: AsyncIterator[dict],
) -> AsyncIterator[bytes]:
    """Converts a twilio media stream into a stream of audio bytes"""
    async for item in async_iter:
        assert "media" in item, f"Message {item} has no media"
        yield base64.b64decode(item["media"]["payload"])


async def audio_bytes_to_twilio_media_step(
    async_iter: AsyncIterator[bytes], stream_sid: FutureOrObj[str]
) -> AsyncIterator[dict]:
    resolved_stream_sid = None
    async for packet in async_iter:
        encoded_data = base64.b64encode(packet).decode("utf-8")
        if not resolved_stream_sid:
            resolved_stream_sid = await resolve_obj_or_future(stream_sid)
        yield {
            "event": "media",
            "streamSid": resolved_stream_sid,
            "media": {"payload": encoded_data},
        }


async def twilio_format_events_step(
    async_iter: AsyncIterator[bytes],
) -> AsyncIterator[BaseEvent]:
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
    # Stream of audio bytes.
    audio: AsyncIterator[bytes]
    # All the events coming from the main stream in twilio, excluding raw audio.
    events: AsyncIterator[BaseEvent]
    all_twilio_messages: Optional[AsyncIterator[dict]]
    call_sid_f: asyncio.Future[str]
    stream_sid_f: asyncio.Future[str]
    inbound_queue_f: asyncio.Future[asyncio.Queue[BaseEvent]]
    outbound_queue_f: asyncio.Future[asyncio.Queue[BaseEvent]]

    @classmethod
    async def create(cls, expose_all_messages: bool = False) -> TwilioInputFlow:
        """
        Creates a basic flow to receive audio and call event data from Twilio.
        expose_all_messages - If true, all incoming twilio messages, including raw audio, will be set through the 'all_twilio_messages' iterator.  Otherwise this iterator will be empty.
        """
        pipe = quart_websocket_source()
        pipe = map_str_to_json_step(pipe)
        pipe = filter_step(pipe, lambda x: x["event"] != "connected")
        if expose_all_messages:
            pipe, all_twilio_messages = fork_step(pipe)
        else:
            all_twilio_messages = None
        pipe = twilio_check_sequence_step(pipe)
        # Retrieve values once the call is connected.
        pipe, call_sid_f = extract_value_step(
            pipe, value=lambda x: x["start"]["callSid"]
        )
        pipe, stream_sid_f = extract_value_step(pipe, value=lambda x: x["streamSid"])
        outbound_queue_f = map_future(
            call_sid_f, lambda x: current_app.current_calls[x].outbound
        )
        inbound_queue_f = map_future(
            call_sid_f, lambda x: current_app.current_calls[x].inbound
        )
        audio, events = partition_step(pipe, lambda x: x["event"] == "media")
        audio = twilio_media_to_audio_bytes_step(audio)
        events = twilio_close_on_stop_step(events)
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
        )
