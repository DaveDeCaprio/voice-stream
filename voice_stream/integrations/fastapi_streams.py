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
            yield await websocket.receive_text()
    except WebSocketDisconnect:
        pass


async def fastapi_websocket_bytes_source(websocket: WebSocket) -> AsyncIterator[bytes]:
    """Creates an AsyncIterator for binary data coming from the FastAPI websocket."""
    await websocket.accept()
    try:
        while True:
            yield await websocket.receive_bytes()
    except WebSocketDisconnect:
        pass


async def fastapi_websocket_json_source(websocket: WebSocket) -> AsyncIterator[dict]:
    """Creates an AsyncIterator for json data coming from the FastAPI websocket."""
    await websocket.accept()
    try:
        while True:
            yield await websocket.receive_json()
    except WebSocketDisconnect:
        pass


async def fastapi_websocket_text_sink(
    async_iter: AsyncIterator[Union[str, dict]], websocket: WebSocket
) -> None:
    """Takes an async iterator and sends everything to a FastAPI websocket.  Handles strings or dicts."""
    async for message in async_iter:
        if isinstance(message, dict):
            await websocket.send_json(message)
        else:
            await websocket.send_text(message)


async def fastapi_websocket_bytes_sink(
    async_iter: AsyncIterator[bytes], websocket: WebSocket
) -> None:
    """Takes an async iterator and sends everything to a FastAPI websocket.  Expects bytes."""
    try:
        async for message in async_iter:
            await websocket.send_bytes(message)
    finally:
        logger.debug("fastapi_websocket_bytes_sink done.")
