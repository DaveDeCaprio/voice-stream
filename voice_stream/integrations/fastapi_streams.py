import json
import logging
from typing import AsyncIterator, Union

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)


async def fastapi_websocket_text_source(websocket: WebSocket) -> AsyncIterator[str]:
    """Creates an AsyncIterator for text messages coming from the FastAPI websocket."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            yield message
    except WebSocketDisconnect:
        logger.debug("websocket.receive is cancelled.")


async def fastapi_websocket_bytes_source(websocket: WebSocket) -> AsyncIterator[str]:
    """Creates an AsyncIterator for binary data coming from the FastAPI websocket."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_bytes()
            yield message
    except WebSocketDisconnect:
        logger.debug("websocket.receive is cancelled.")


async def fastapi_websocket_text_sink(
    async_iter: AsyncIterator[Union[str, dict]], websocket: WebSocket
) -> None:
    """Takes an async iterator and sends everything to a FastAPI websocket.  Handles strings or dicts."""
    async for message in async_iter:
        if isinstance(message, dict):
            message = json.dumps(message)
        await websocket.send_text(message)


async def fastapi_websocket_bytes_sink(
    async_iter: AsyncIterator[bytes], websocket: WebSocket
) -> None:
    """Takes an async iterator and sends everything to a FastAPI websocket.  Expects bytes."""
    async for message in async_iter:
        await websocket.send_bytes(message)
