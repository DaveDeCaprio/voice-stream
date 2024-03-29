"""
Simple example showing serving a text chat app using a source, sink, and LLM step.
"""

import logging
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from langchain_community.cache import SQLiteCache
from langchain_community.chat_models import ChatVertexAI
from langchain_core.globals import set_llm_cache
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from voice_stream import map_step
from voice_stream.integrations.fastapi import (
    fastapi_websocket_text_source,
    fastapi_websocket_text_sink,
)
from voice_stream.integrations.langchain import (
    langchain_load_memory_step,
    langchain_step,
)
from voice_stream.types import load_attribute

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)

set_llm_cache(SQLiteCache(database_path=".langchain.db"))

app = FastAPI()

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Chat</title>
        <style>
        .message-input {
            margin-bottom: 20px;
            width: 300px; /* Width of the text area */
            height: 100px; /* Height of the text area */
        }        
        </style>
    </head>
    <body>
        <h1>WebSocket Chat</h1>
        <form action="" onsubmit="sendMessage(event)">
            <textarea class="message-input" id="messageText" autocomplete="off"></textarea>
            <button>Send</button>
        </form>
        <ul id='messages'>
        </ul>
        <script>
            var newAI = false;
            function appendMessage(role, text) {
                var messages = document.getElementById('messages')
                var message = document.createElement('li')
                var aiPrefix = document.createElement('strong');
                aiPrefix.textContent = role;
                var content = document.createTextNode(text)
                message.appendChild(aiPrefix)
                message.appendChild(content)
                messages.appendChild(message)            
            };
            var ws = new WebSocket("ws://localhost:8000/ws");
            ws.onmessage = function(event) {
                if (newAI) {
                    newAI = false;
                    appendMessage('AI: ', event.data);
                }
                else {
                    var messages = document.getElementById('messages')
                    messages.lastChild.innerHTML += escapeHTML(event.data)
                }
            };
            function escapeHTML(str) {
                return str.replace(/[&<>"']/g, function(match) {
                    const escape = {
                        '&': '&amp;',
                        '<': '&lt;',
                        '>': '&gt;',
                        '"': '&quot;',
                        "'": '&#39;'
                    };
                    return escape[match];
                });
            }
            function sendMessage(event) {
                var input = document.getElementById("messageText")
                ws.send(input.value)
                appendMessage('Human: ', input.value);
                newAI = true;
                input.value = ''
                event.preventDefault()
            }
        </script>
    </body>
</html>
"""


@app.get("/")
async def get():
    return HTMLResponse(html)


# set_debug(True)


load_dotenv()
chain = (
    ChatPromptTemplate.from_messages([("human", "{query}")])
    | ChatVertexAI()
    | StrOutputParser()
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_id = uuid.uuid4()
    stream = fastapi_websocket_text_source(websocket)
    stream = map_step(
        stream,
        lambda x: {
            "input": {"message": x},
            "config": {"configurable": {"session_id": session_id}},
        },
    )
    stream = langchain_step(stream, chain, input_key="input", config_key="config")
    stream = map_step(stream, lambda x: x, ignore_none=True)
    await fastapi_websocket_text_sink(stream, websocket)
