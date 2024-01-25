"""
`Quart <https://github.com/pallets/quart/>`_ is an async Python web framework based on Flask.  VoiceStream provides
integrations to send and receive audio using websockets using Quart.

.. note::
    Flask generally uses SocketIO through the Flask_SocketIO library, which is different from regular WebSockets.
    If you just want regular websockets, it's easier to switch to Quart, which is a drop in replacement.

"""

import json
import logging
from asyncio import CancelledError
from typing import AsyncIterator, Union, Dict

try:
    from quart import websocket
except ImportError:
    raise ImportError(
        "Could not import quart python package. "
        "Please install it with `pip install quart`."
    )
from hypercorn.utils import UnexpectedMessageError


logger = logging.getLogger(__name__)


async def quart_websocket_source() -> AsyncIterator[Union[bytes, str]]:
    """
    Data flow source for receiving messages from a Quart WebSocket connection.

    This function facilitates the handling of incoming text or binary messages from a client connected through
    a Quart WebSocket. It continuously listens for messages and yields them as they arrive. The
    function handles the WebSocket connection lifecycle by accepting the connection and managing
    disconnection events.

    Returns
    -------
    AsyncIterator[Union[bytes, str]]
        An asynchronous iterator that yields incoming messages as bytes or strings.

    Notes
    -----
    - The function uses an infinite loop to listen for messages. It exits the loop and stops iterating
      when a CancelledError exception occurs.

    Examples
    --------
    >>> from quart import Quart
    >>> import asyncio
    >>>
    >>> app = Quart()
    >>>
    >>> @app.websocket("/ws")
    >>> async def websocket_endpoint():
    >>>     stream = quart_websocket_source(websocket)
    >>>     stream = map_step(stream, lambda x: "Echo: "+x)
    >>>     await quart_websocket_sink(stream)
    """
    await websocket.accept()
    while True:
        try:
            message = await websocket.receive()
        except CancelledError:
            logger.debug("websocket.receive is cancelled.")
            raise
        yield message


async def quart_websocket_sink(
    async_iter: AsyncIterator[Union[str, Dict, bytes]]
) -> None:
    """Takes an async iterator and sends everything to a Quart websocket.  Handles ."""
    """
    Data flow sink to strings, dicts, Pydantic objects, or bytes bytes to a Quart websocket.

    For each item in the incoming iterator, send it to the currently in scope Quart websocket connection.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator that yields string, dictionaries, or bytes. Each incoming object is sent as a 
        websocket message.

    Returns
    -------
    None
        This function does not return any value.

    Examples
    --------
    >>> from quart import Quart
    >>> import asyncio
    >>>
    >>> app = Quart()
    >>>
    >>> @app.websocket("/ws")
    >>> async def websocket_endpoint():
    >>>     stream = quart_websocket_source(websocket)
    >>>     stream = map_step(stream, lambda x: "Echo: "+x)
    >>>     await quart_websocket_sink(stream)

    Notes
    -----
    - The function will continue sending data until the iterator is exhausted.
    - In case of any interruption or when the iterator is exhausted, it ensures proper cleanup.
    """
    try:
        async for message in async_iter:
            if isinstance(message, dict):
                message = json.dumps(message)
            elif hasattr(message, "model_dump"):
                message = message.model_dump()
            await websocket.send(message)
    except UnexpectedMessageError as e:
        if "ASGIWebsocketState.CLOSED" in str(e):
            logger.info("Websocket closed before all queued messages were sent.")
        else:
            raise e
