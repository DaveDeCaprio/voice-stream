"""
`FastAPI <https://fastapi.tiangolo.com/>`_ is a high performance web framework.  VoiceStream provides integrations to
send and receive audio using websockets using FastAPI.
"""

import logging
from typing import AsyncIterator, Union

import asyncstdlib

try:
    from fastapi import WebSocket
except ImportError:
    raise ImportError(
        "Could not import fastapi python package. "
        "Please install it with `pip install fastapi`."
    )

from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


async def fastapi_websocket_text_source(websocket: WebSocket) -> AsyncIterator[str]:
    """
    Data flow source for receiving text messages from a FastAPI WebSocket connection.

    This function facilitates the handling of incoming text messages from a client connected through
    a FastAPI WebSocket. It continuously listens for messages and yields them as they arrive. The
    function handles the WebSocket connection lifecycle by accepting the connection and managing
    disconnection events.

    Parameters
    ----------
    websocket : WebSocket
        An instance of WebSocket from FastAPI. This is the WebSocket connection through which the
        function will receive text messages.

    Returns
    -------
    AsyncIterator[str]
        An asynchronous iterator that yields incoming text messages as strings.

    Notes
    -----
    - The function uses an infinite loop to listen for messages. It exits the loop and stops iterating
      when a WebSocketDisconnect exception occurs.
    - This source will call `accept` on the websocket if it has not already been called.


    Examples
    --------
        >>> from fastapi import FastAPI, WebSocket
        >>> import asyncio
        >>>
        >>> app = FastAPI()
        >>>
        >>> @app.websocket("/ws")
        >>> async def websocket_endpoint(websocket: WebSocket):
        >>>     stream = fastapi_websocket_text_source(websocket)
        >>>     stream = map_step(stream, lambda x: "Echo: "+x)
        >>>     await fastapi_websocket_text_sink(stream, websocket)
    """
    if websocket.client_state == WebSocketState.CONNECTING:
        await websocket.accept()
    try:
        while True:
            yield await websocket.receive_text()
    except WebSocketDisconnect:
        pass


async def fastapi_websocket_bytes_source(websocket: WebSocket) -> AsyncIterator[bytes]:
    """
    Data flow source for binary data received from a FastAPI WebSocket.

    This function continuously listens to a WebSocket connection, yielding binary data as
    it's received. The iterator will handle the connection establishment and will
    terminate gracefully if the WebSocket disconnects.

    Parameters
    ----------
    websocket : WebSocket
        The FastAPI WebSocket connection from which to receive binary data.

    Returns
    -------
    bytes
        Binary data received from the WebSocket.

    Examples
    --------
    >>> from fastapi import FastAPI, WebSocket
    >>> import asyncio
    >>>
    >>> app = FastAPI()
    >>>
    >>> @app.websocket("/ws")
    >>> async def websocket_endpoint(websocket: WebSocket):
    >>>     stream = fastapi_websocket_text_source(websocket)
    >>>     stream = map_step(stream, lambda x: "Echo: "+x)
    >>>     await fastapi_websocket_text_sink(stream, websocket)

    Notes
    -----
    This function is designed to be used with FastAPI's WebSocket support.
    It requires an established WebSocket connection passed as the parameter.

    This source will call `accept` on the websocket if it has not already been called.

    See Also
    --------
    WebSocket.receive_bytes : Method of FastAPI's WebSocket to receive binary data.

    """
    if websocket.client_state == WebSocketState.CONNECTING:
        await websocket.accept()
    try:
        while True:
            yield await websocket.receive_bytes()
    except WebSocketDisconnect:
        pass


async def fastapi_websocket_json_source(websocket: WebSocket) -> AsyncIterator[dict]:
    """
    Data flow source for JSON data received from a FastAPI WebSocket.

    This function continuously listens to a WebSocket connection, yielding JSON data (in the
    form of Python dictionaries) as it's received. The iterator manages the connection
    establishment and will terminate gracefully if the WebSocket disconnects.

    Parameters
    ----------
    websocket : WebSocket
        The WebSocket connection from which to receive JSON data.

    Returns
    -------
    AsyncIterator[dict]
        JSON data received from the WebSocket, parsed into a Python dictionary.

    Examples
    --------
    >>> from fastapi import FastAPI, WebSocket
    >>> import asyncio
    >>>
    >>> app = FastAPI()
    >>>
    >>> @app.websocket("/ws")
    >>> async def websocket_endpoint(websocket: WebSocket):
    >>>     stream = fastapi_websocket_json_source(websocket)
    >>>     stream = log_step(stream, "JSON received")
    >>>     await empty_step(stream, websocket)

    Notes
    -----
    This function is specifically tailored for use with FastAPI's WebSocket support.
    It requires an active WebSocket connection as the parameter.

    This source will call `accept` on the websocket if it has not already been called.

    See Also
    --------
    WebSocket.receive_json : Method of FastAPI's WebSocket to receive JSON data.

    """
    if websocket.client_state == WebSocketState.CONNECTING:
        await websocket.accept()
    try:
        while True:
            yield await websocket.receive_json()
    except WebSocketDisconnect:
        pass


async def fastapi_websocket_text_sink(
    async_iter: AsyncIterator[Union[str, dict]], websocket: WebSocket
) -> None:
    """
    Data flow sink to send data to a FastAPI WebSocket connection.

    This function takes an asynchronous iterator, which can yield either strings, Pydantic objects, or
    dictionaries, and sends each item to a specified WebSocket. If the item is a dictionary,
    it is sent as a JSON message. Otherwise, it is sent as a text message.

    Parameters
    ----------
    async_iter : AsyncIterator[Union[str, dict]]
        An asynchronous iterator that yields either strings or dictionaries.
    websocket : WebSocket
        The FastAPI WebSocket connection to which the data will be sent.

    Examples
    --------
    >>> from fastapi import FastAPI, WebSocket
    >>> import asyncio
    >>>
    >>> app = FastAPI()
    >>>
    >>> @app.websocket("/ws")
    >>> async def websocket_endpoint(websocket: WebSocket):
    >>>     stream = fastapi_websocket_json_source(websocket)
    >>>     stream = log_step(stream, "JSON received")
    >>>     await fastapi_websocket_text_sink(stream, websocket)

    Notes
    -----
    - This function is useful for streaming data from an asynchronous source to a WebSocket
      client. It supports both text and JSON formats, making it versatile for various types
      of data communication in a FastAPI application.
    - This sink will call `accept` on the websocket if it has not already been called.

    See Also
    --------
    WebSocket.send_json : Method of FastAPI's WebSocket to send JSON data.
    WebSocket.send_text : Method of FastAPI's WebSocket to send text data.

    """
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        if websocket.client_state == WebSocketState.CONNECTING:
            await websocket.accept()
        async for message in owned_aiter:
            if isinstance(message, dict):
                await websocket.send_json(message)
            elif hasattr(message, "model_dump"):
                json = message.model_dump()
                logger.info(f"Sending {json}")
                await websocket.send_json(json)
            else:
                await websocket.send_text(message)


async def fastapi_websocket_bytes_sink(
    async_iter: AsyncIterator[bytes], websocket: WebSocket
) -> None:
    """
    Data flow sink to send bytes to a FastAPI websocket.

    This function takes an asynchronous iterator that yields bytes, and for each item in this iterator,
    it sends the item to the specified FastAPI WebSocket connection.

    Parameters
    ----------
    async_iter : AsyncIterator[bytes]
        An asynchronous iterator that yields bytes. Each byte sequence received from this iterator
        will be sent to the websocket.
    websocket : WebSocket
        The FastAPI WebSocket instance to which the byte sequences will be sent.

    Returns
    -------
    None
        This function does not return any value.

    Examples
    --------
    >>> from fastapi import FastAPI, WebSocket
    >>> import asyncio
    >>>
    >>> app = FastAPI()
    >>>
    >>> @app.websocket("/ws")
    >>> async def websocket_endpoint(websocket: WebSocket):
    >>>     stream = fastapi_websocket_bytes_source(websocket)
    >>>     stream = log_step(stream, "# Bytes received", lambda x: len(x))
    >>>     await fastapi_websocket_bytes_sink(stream, websocket)

    Notes
    -----
    - It's essential that the `async_iter` provided is an asynchronous iterator yielding byte sequences.
    - The function will continue sending data until the iterator is exhausted.
    - In case of any interruption or when the iterator is exhausted, it ensures proper cleanup.
    - This sink will call `accept` on the websocket if it has not already been called.
    """
    try:
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            if websocket.client_state == WebSocketState.CONNECTING:
                await websocket.accept()
            async for message in owned_aiter:
                await websocket.send_bytes(message)
    finally:
        logger.debug("fastapi_websocket_bytes_sink done.")
