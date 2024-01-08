import os

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v1 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from voice_stream import map_step
from voice_stream.audio import AudioFormat
from voice_stream.integrations.fastapi_streams import (
    fastapi_websocket_bytes_source,
    fastapi_websocket_bytes_sink,
)
from voice_stream.integrations.google_streams import (
    google_speech_v1_step,
    google_text_to_speech_step,
)
from voice_stream.integrations.langchain_streams import langchain_step

app = FastAPI()

html = """
<!DOCTYPE html>
<html>
    <head><title>VoiceStream Quickstart</title></head>
    <body>
        <button onclick="startRecording()">Start Recording</button>
        <button onclick="stopRecording()">Stop Recording</button>
        <script src="audio_ws.js"></script>
    </body>
</html>
"""

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_creds.json"
speech_async_client = SpeechAsyncClient(
    client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
)
text_to_speech_async_client = TextToSpeechAsyncClient()
chain = (
    ChatPromptTemplate.from_messages([HumanMessage(content="{query}")])
    | ChatGoogleGenerativeAI(model="gemini-pro")
    | StrOutputParser()
)


@app.get("/")
def get():
    return HTMLResponse(html)


@app.websocket("/ws/audio")
async def audio_websocket_endpoint(websocket: WebSocket):
    pipe = fastapi_websocket_bytes_source(websocket)
    pipe = google_speech_v1_step(
        pipe,
        speech_async_client,
        audio_format=AudioFormat.WEBM_OPUS,
    )
    pipe = langchain_step(pipe, chain)
    pipe = google_text_to_speech_step(
        pipe, text_to_speech_async_client, audio_format=AudioFormat.MP3
    )
    pipe = map_step(pipe, lambda x: x.audio)
    await fastapi_websocket_bytes_sink(pipe, websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
