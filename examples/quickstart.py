import os

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

from voice_stream.integrations.fastapi_streams import (
    fastapi_websocket_source,
    fastapi_websocket_sink,
)

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

os.environ["OPENAI_API_KEY"] = "sk-INSERT YOUR OPENAI KEY HERE"


@app.get("/")
def get():
    return HTMLResponse(html)


@app.websocket("/ws/audio")
async def audio_websocket_endpoint(websocket: WebSocket):
    pipe = fastapi_websocket_source(websocket)
    pipe = speech_recognize_step()
    pipe = text_to_speech_step(pipe)
    await fastapi_websocket_sink(pipe, websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
