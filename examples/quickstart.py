import os

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v1 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain_community.chat_models import ChatVertexAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

# 0 - VoiceStream imports
from voice_stream import map_step, log_step, recover_exception_step
from voice_stream.audio import AudioFormat
from voice_stream.integrations.fastapi import (
    fastapi_websocket_bytes_source,
    fastapi_websocket_bytes_sink,
)
from voice_stream.integrations.google import (
    google_speech_v1_step,
    google_text_to_speech_step,
)
from voice_stream.integrations.langchain import langchain_step

# 1 - HTML shown by the browser
html = """
<!DOCTYPE html>
<html>
    <head><title>VoiceStream Quickstart</title></head>
    <body>
        <script 
        src="https://cdn.jsdelivr.net/gh/DaveDeCaprio/voice-stream@main/examples/static/audio_ws.js">
        </script>
        <button onclick="startAudio('audio-player', '/ws/audio')">Start Voice Chat</button>
        <button onclick="stopAudio()">Stop Voice Chat</button>
        <audio id="audio-player"></audio>
    </body>
</html>
"""

# 2 - FastAPI app and route to serve the UI
app = FastAPI()


@app.get("/")
def get():
    return HTMLResponse(html)


# 3 - Set up Google client and credentials
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


# 4 - The VoiceStream data flow to run the voice chat
@app.websocket("/ws/audio")
async def audio_websocket_endpoint(websocket: WebSocket):
    stream = fastapi_websocket_bytes_source(websocket)
    stream = google_speech_v1_step(
        stream,
        speech_async_client,
        audio_format=AudioFormat.WEBM_OPUS,
    )
    stream = log_step(stream, "Recognized speech")
    stream = map_step(stream, lambda x: {"query": x})
    stream = langchain_step(stream, chain, on_completion="")
    stream = recover_exception_step(
        stream,
        Exception,
        lambda x: "Google blocked the response.  Ending conversation.",
    )
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.MP3
    )
    stream = map_step(stream, lambda x: x.audio)
    await fastapi_websocket_bytes_sink(stream, websocket)
