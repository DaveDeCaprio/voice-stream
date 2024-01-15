"""
Expands on the basic quickstart by adding in logging of the input and output text.
"""

import asyncio
import logging
import os

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v1 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain_community.chat_models import ChatVertexAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from examples.example_events import TextInput, TextOutput

# 0 - VoiceStream imports
from voice_stream import (
    map_step,
    recover_exception_step,
    fork_step,
    merge_step,
    queue_sink,
    queue_source,
)
from voice_stream.audio import AudioFormat
from voice_stream.integrations.fastapi import (
    fastapi_websocket_bytes_source,
    fastapi_websocket_bytes_sink,
    fastapi_websocket_text_sink,
)
from voice_stream.integrations.google import (
    google_speech_v1_step,
    google_text_to_speech_step,
)
from voice_stream.integrations.langchain import langchain_step

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# HTML shown by the browser
html = """
<!DOCTYPE html>
<html>
    <head><title>VoiceStream Quickstart</title></head>
    <body>
        <script 
        src="https://cdn.jsdelivr.net/gh/DaveDeCaprio/voice-stream@main/examples/static/audio_ws.js">
        </script>
        <button onclick="startChat()">Start Voice Chat</button>
        <button onclick="stopChat()">Stop Voice Chat</button>
        <audio id="audio-player"></audio>
        <div id="result"></div>
<script>
let textWebsocket;

/* Set up the websockets */
async function startChat() {
    const uuid = generateUUID();
    await startAudio("audio-player",`/ws/audio?id=${uuid}`);

    var resultDiv = document.getElementById('result');
    resultDiv.innerHTML = "";

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host; // Includes hostname and port if present
    const wsUrl = `${protocol}//${host}/ws/text?id=${uuid}`;
    callStatusWebsocket = new WebSocket(wsUrl);
    var lastEventName = "";
    
    callStatusWebsocket.onmessage = function (event) {
        const data = JSON.parse(event.data)
        if (lastEventName === data.event_name)
            resultDiv.innerHTML += data.text;
        else
            resultDiv.innerHTML += `<br>${data.event_name}: ${data.text}`;
        lastEventName = data.event_name;
    }    
}

/* Close the websockets */
async function stopChat() {
    await stopAudio();
    if(textWebsocket) {
        textWebsocket.close()
    }
}

function generateUUID() {
    return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
            (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
}
</script>
        
    </body>
</html>
"""
# End HTML

app = FastAPI()


@app.get("/")
def get():
    return HTMLResponse(html)


os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_creds.json"
speech_async_client = SpeechAsyncClient(
    client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
)
text_to_speech_async_client = TextToSpeechAsyncClient()
chain = (
    ChatPromptTemplate.from_messages([("human", "{query}")])
    | ChatVertexAI()
    | StrOutputParser()
)

# Text Endpoint
call_queues = {}


@app.websocket("/ws/text")
async def text_websocket_endpoint(websocket: WebSocket, id: str):
    queue = call_queues[id]
    stream = queue_source(queue)
    await fastapi_websocket_text_sink(stream, websocket)


# Audio Endpoint
@app.websocket("/ws/audio")
async def audio_websocket_endpoint(websocket: WebSocket, id: str):
    call_queues[id] = asyncio.Queue()
    stream = fastapi_websocket_bytes_source(websocket)
    stream = google_speech_v1_step(
        stream,
        speech_async_client,
        audio_format=AudioFormat.WEBM_OPUS,
    )
    stream, text_input_stream = fork_step(stream)
    stream = map_step(stream, lambda x: {"query": x})
    stream = langchain_step(stream, chain, on_completion="")
    stream = recover_exception_step(
        stream,
        Exception,
        lambda x: "Google blocked the response.  Ending conversation.",
    )
    stream, text_output_stream = fork_step(stream)
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.MP3
    )
    stream = map_step(stream, lambda x: x.audio)
    done = fastapi_websocket_bytes_sink(stream, websocket)

    text_input_stream = map_step(text_input_stream, lambda x: TextInput(text=x))
    text_output_stream = map_step(text_output_stream, lambda x: TextOutput(text=x))
    output_stream = merge_step(text_input_stream, text_output_stream)
    queue_done = queue_sink(output_stream, call_queues[id])
    await asyncio.gather(done, queue_done)


logger.info("INIT")
