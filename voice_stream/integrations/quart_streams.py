import json
import logging
from asyncio import CancelledError
from typing import AsyncIterator

from hypercorn.utils import UnexpectedMessageError
from quart import websocket

logger = logging.getLogger(__name__)


async def quart_websocket_source() -> AsyncIterator[str]:
    """Creates an ASyncIterator for messages coming from the Quart websocket object."""
    while True:
        try:
            message = await websocket.receive()
        except CancelledError:
            logger.debug("websocket.receive is cancelled.")
            return
        yield message


async def quart_websocket_sink(async_iter: AsyncIterator[str]) -> None:
    """Takes an async iterator and sends everything to a Quart websocket.  Handles strings, dicts, or bytes."""
    try:
        async for message in async_iter:
            if isinstance(message, dict):
                message = json.dumps(message)
            await websocket.send(message)
    except UnexpectedMessageError as e:
        if "ASGIWebsocketState.CLOSED" in str(e):
            logger.info("Websocket closed before all queued messages were sent.")
        else:
            raise e
