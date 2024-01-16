import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v1 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain_community.chat_models import ChatVertexAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client

from voice_stream import (
    map_step,
    log_step,
    recover_exception_step,
    filter_step,
    extract_value_step,
    partition_step,
)
from voice_stream.audio import AudioFormat
from voice_stream.core import empty_sink
from voice_stream.integrations.fastapi import (
    fastapi_websocket_json_source,
    fastapi_websocket_text_sink,
)
from voice_stream.integrations.google import (
    google_speech_v1_step,
    google_text_to_speech_step,
)
from voice_stream.integrations.langchain import langchain_step
from voice_stream.integrations.twilio import (
    twilio_check_sequence_step,
    twilio_media_to_audio_bytes_step,
    twilio_close_on_stop_step,
    audio_bytes_to_twilio_media_step,
)

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Set up clients
load_dotenv()

speech_async_client = SpeechAsyncClient(
    client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
)
text_to_speech_async_client = TextToSpeechAsyncClient()
chain = (
    ChatPromptTemplate.from_messages([("human", "{query}")])
    | ChatVertexAI()
    | StrOutputParser()
)

# Set up Twilio client
twilio_client = Client(
    os.environ["TWILIO_API_KEY"],
    os.environ["TWILIO_API_SECRET"],
    os.environ["TWILIO_ACCOUNT_SID"],
    http_client=AsyncTwilioHttpClient(),
)

# HTML shown by the browser
html = """
<!DOCTYPE html>
<html>
    <head><title>VoiceStream Quickstart</title></head>
    <body>
        <label for="phone-number">Phone Number (in format +12125551234):</label>
        <input type="tel" id="phone-number" placeholder="+12125551234">
        <button onclick="initiateCall()">Place Call</button>
        <div id="result"></div>
<script>
    async function initiateCall(endpoint) {
        var phoneNumber = document.getElementById('phone-number').value;
        var resultDiv = document.getElementById('result');
        const response = await fetch(`/call?phone=${encodeURIComponent(phoneNumber)}`);
        const data = await response.json();

        const callSid = data.callSid;
        resultDiv.textContent = "Placing call to " + phoneNumber + " with call_sid " + callSid;
    }
</script>
    </body>
</html>
"""

# FastAPI app and route to serve the UI
app = FastAPI()


@app.get("/")
def get():
    return HTMLResponse(html)


# Initiate Call
@app.get("/call")
async def outbound_call(phone):
    call_instance = await twilio_client.calls.create_async(
        from_=os.environ["TWILIO_PHONE_NUMBER"],
        to=phone,
        url=f"https://{os.environ['DOMAIN']}/twiml",
    )
    return {"callSid": call_instance.sid}


# TWiML Webhook
@app.post("/twiml")
async def twiml_webhook():
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{os.environ["DOMAIN"]}/ws"></Stream>
  </Connect>
  <Pause length="10"/>
</Response>
    """
    return HTMLResponse(twiml)


# Handle Audio
@app.websocket("/ws")
async def audio_websocket_endpoint(websocket: WebSocket):
    logger.info("Receiving audio for new call")
    stream = fastapi_websocket_json_source(websocket)
    stream = filter_step(stream, lambda x: x["event"] != "connected")
    stream = twilio_check_sequence_step(stream)
    stream, twilio_sid_f = extract_value_step(stream, value=lambda x: x["streamSid"])
    stream, event_stream = partition_step(stream, lambda x: x["event"] == "media")
    stream = twilio_media_to_audio_bytes_step(stream)
    stream = google_speech_v1_step(
        stream,
        speech_async_client,
        model="telephony",
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
    )
    stream = log_step(stream, "Recognized speech")
    stream = map_step(stream, lambda x: {"query": x})
    stream = langchain_step(stream, chain, on_completion="")
    stream = recover_exception_step(
        stream,
        Exception,
        lambda x: "Google blocked the response.  Ending conversation.",
    )
    stream = log_step(stream, "LLM Output")
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.WAV_MULAW_8KHZ
    )
    stream = map_step(stream, lambda x: x.audio)
    stream = audio_bytes_to_twilio_media_step(stream, twilio_sid_f)
    done = fastapi_websocket_text_sink(stream, websocket)

    async def close_websocket():
        await websocket.close()

    event_stream = twilio_close_on_stop_step(event_stream, close_func=close_websocket)
    event_done = empty_sink(event_stream)

    logger.info("Streams set up")
    await asyncio.gather(done, event_done)
    logger.info("Call completed")
