from __future__ import annotations

import asyncio
import base64
import dataclasses
import datetime
import logging
import os
import time
import urllib
import uuid
from asyncio import CancelledError
from typing import Coroutine, AsyncIterator

from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.speech_v1 import SpeechAsyncClient as SpeechAsyncClientV1
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from pydantic import BaseModel
from quart import (
    Quart,
    websocket,
    request,
    render_template,
    current_app,
)
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client
from werkzeug.exceptions import BadRequest

from examples.example_events import TextInput, TextOutput
from examples.llm_testing_app.chain import create_chain
from quart_ngrok import run_quart_ngrok
from voice_stream import (
    queue_source,
    map_step,
    text_file_sink,
    queue_sink,
    merge_step,
    log_step,
    fork_step,
    binary_file_sink,
    binary_file_source,
    audio_rate_limit_step,
    filter_spurious_speech_start_events_step,
    tts_with_buffer_and_rate_limit_step,
    cancelable_substream_step,
)
from voice_stream.audio import wav_mulaw_file_sink, AudioFormat
from voice_stream.events import AnsweringMachineDetection, CallStarted
from voice_stream.integrations.google import (
    google_speech_step,
    google_text_to_speech_step,
    google_speech_v1_step,
)
from voice_stream.integrations.langchain import langchain_step
from voice_stream.integrations.quart import quart_websocket_sink, quart_websocket_source
from voice_stream.integrations.twilio import (
    TwilioInputFlow,
    audio_bytes_to_twilio_media_step,
)
from voice_stream.types import map_future, AwaitableOrObj, resolve_awaitable_or_obj

logger = logging.getLogger(__name__)

# Pull configuration from the .env file
load_dotenv()
app = Quart(__name__)
app.config["HTTP_SERVER_PORT"] = 8080
app.config["GCP_PROJECT_ID"] = os.environ["GCP_PROJECT_ID"]
app.config["GCP_SPEECH_LOCATION"] = os.environ["GCP_SPEECH_LOCATION"]
app.config["GCP_TELEPHONE_SPEECH_RECOGNIZER"] = os.environ[
    "GCP_TELEPHONE_SPEECH_RECOGNIZER"
]
app.config["GCP_BROWSER_SPEECH_RECOGNIZER"] = os.environ[
    "GCP_BROWSER_SPEECH_RECOGNIZER"
]
app.config["TWILIO_ACCOUNT_SID"] = os.environ["TWILIO_ACCOUNT_SID"]
app.config["TWILIO_PHONE_NUMBER"] = os.environ["TWILIO_PHONE_NUMBER"]
app.config["TWILIO_API_KEY"] = os.environ["TWILIO_API_KEY"]
app.config["TWILIO_API_SECRET"] = os.environ["TWILIO_API_SECRET"]


@dataclasses.dataclass
class CallQueues:
    inbound = asyncio.Queue()
    outbound = asyncio.Queue()


@app.before_serving
async def before_serving():
    http_client = AsyncTwilioHttpClient()
    current_app.domain = app.config["DOMAIN"]
    current_app.twilio_client = Client(
        app.config["TWILIO_API_KEY"],
        app.config["TWILIO_API_SECRET"],
        app.config["TWILIO_ACCOUNT_SID"],
        http_client=http_client,
    )
    current_app.speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    current_app.text_to_speech_async_client = TextToSpeechAsyncClient()

    assert current_app.twilio_client
    current_app.current_calls = {}


@app.route("/")
async def index():
    return await render_template("index.html")


@app.route("/call/<path:endpoint>", methods=["GET"])
async def outbound_call(endpoint):
    phone_number = request.args.get("phone")
    call_instance = await current_app.twilio_client.calls.create_async(
        from_=app.config["TWILIO_PHONE_NUMBER"],
        to=phone_number,
        url=f"https://{current_app.domain}/twiml/{endpoint}",
        async_amd=True,
        machine_detection="DetectMessageEnd",
        async_amd_status_callback=f"https://{current_app.domain}/machine_detect",
    )
    logger.info(f"Initiating outbound call. SID: {call_instance.sid}")
    current_app.current_calls[call_instance.sid] = CallQueues()
    return {"callSid": call_instance.sid}


@app.route("/twiml/<path:endpoint>", methods=["POST"])
async def twiml_webhook(endpoint):
    logger.info(f"Returning TwiML for {endpoint}")
    return await render_template(
        "twiml.xml", domain=current_app.domain, endpoint=endpoint
    )


def form_data_to_dict(form):
    regular_dict = {}
    for key in form.keys():
        values = form.getlist(key)
        regular_dict[key] = values[0] if len(values) == 1 else values
    return regular_dict


@app.route("/machine_detect", methods=["POST"])
async def machine_detect_webhook():
    form = await request.form
    event = form_data_to_dict(form)
    call_id = event["CallSid"]
    event = AnsweringMachineDetection(
        call_id=call_id,
        answered_by=event["AnsweredBy"],
        time_since_start=float(event["MachineDetectionDuration"]) / 1000,
    )
    logger.info(
        f"Answering machine detection on call SID {call_id}: {event.answered_by} {event.time_since_start} seconds"
    )
    call = current_app.current_calls.get(call_id, None)
    if call is None:
        logger.warning(
            f"No active call {call_id}.  Not sending answering machine detection to queue."
        )
    else:
        await call.inbound.put(event)
    return "Ok"


@app.websocket("/callStatus/<call_sid>")
async def callStatus(call_sid):
    """Streams back call status updates."""
    queue = current_app.current_calls[call_sid].outbound
    logger.info(f"Status log client connected for call {call_sid}")
    stream = queue_source(queue)
    # stream = log_step(stream, "CalLStatus output")
    stream = map_step(stream, format_call_status)
    await quart_websocket_sink(stream)
    await websocket.close(1000)
    logger.info(f"Finished logging call status for call {call_sid}")


def format_call_status(event):
    timestamp = datetime.datetime.now().isoformat()
    if not isinstance(event, dict):
        event = (
            event.model_dump()
            if isinstance(event, BaseModel)
            else dataclasses.asdict(event)
        )
    event = {"timestamp": timestamp, **event}
    return event


@app.websocket("/ws/record")
async def record():
    logger.info("Recording call")
    logger.info(f"Current calls {current_app.current_calls}")
    os.makedirs("target/calls", exist_ok=True)
    stream = quart_websocket_source()
    input_flow = TwilioInputFlow.create(
        stream,
        expose_all_messages=True,
        close_func=lambda: websocket.close(1000),
        current_calls=current_app.current_calls,
    )

    message_filename = map_future(
        input_flow.call_sid_f, lambda x: f"target/calls/{x}.ndjson"
    )
    twilio_log = text_file_sink(input_flow.all_twilio_messages, message_filename)

    audio_filename = map_future(
        input_flow.call_sid_f, lambda x: f"target/calls/{x}.wav"
    )
    audio = wav_mulaw_file_sink(input_flow.audio, audio_filename)

    events = queue_sink(input_flow.events, input_flow.outbound_queue_f)

    await run_call(input_flow.call_sid_f, audio, twilio_log, events)


@app.websocket("/ws/transcribe")
async def transcribe():
    logger.info("Transcribing call")
    stream = quart_websocket_source()
    input_flow = TwilioInputFlow.create(
        stream,
        close_func=lambda: websocket.close(1000),
        current_calls=current_app.current_calls,
    )
    stream = input_flow.audio
    stream = google_speech_step(
        stream,
        current_app.speech_async_client,
        project=app.config["GCP_PROJECT_ID"],
        location=app.config["GCP_SPEECH_LOCATION"],
        recognizer=app.config["GCP_TELEPHONE_SPEECH_RECOGNIZER"],
        model="telephony",
        language_codes=["en-US", "es-US"],
        audio_format=AudioFormat.WAV_MULAW_8KHZ,
    )
    stream = log_step(stream, "Recognized")
    stream = map_step(stream, lambda x: TextInput(text=x))
    stream = merge_step(stream, input_flow.events)
    stream = log_step(stream, "Merged events")
    stream = queue_sink(stream, input_flow.outbound_queue_f)

    await run_call(input_flow.call_sid_f, stream)


def create_langchain_flow(stream: AsyncIterator[bytes], telephony: bool):
    audio_output_format = AudioFormat.WAV_MULAW_8KHZ if telephony else AudioFormat.MP3
    tts_step = lambda stream: google_text_to_speech_step(
        stream,
        current_app.text_to_speech_async_client,
        audio_format=audio_output_format,
    )

    if telephony:
        stream, speech_start = google_speech_step(
            stream,
            current_app.speech_async_client,
            project=app.config["GCP_PROJECT_ID"],
            location=app.config["GCP_SPEECH_LOCATION"],
            recognizer=app.config["GCP_TELEPHONE_SPEECH_RECOGNIZER"],
            model="telephony",
            language_codes=["en-US", "es-US"],
            audio_format=AudioFormat.WAV_MULAW_8KHZ,
            include_events=True,
        )
    else:
        stream, speech_start = google_speech_step(
            stream,
            current_app.speech_async_client,
            project=app.config["GCP_PROJECT_ID"],
            location=app.config["GCP_SPEECH_LOCATION"],
            recognizer=app.config["GCP_BROWSER_SPEECH_RECOGNIZER"],
            model="latest_long",
            language_codes=["en-US", "es-US"],
            audio_format=None,
            include_events=True,
        )
    speech_start = filter_spurious_speech_start_events_step(speech_start)
    stream, text_input = fork_step(stream)

    def create_output_chain(
        stream: AsyncIterator[str],
    ) -> (AsyncIterator[bytes], AsyncIterator[str]):
        stream = langchain_step(stream, create_chain(), on_completion="")
        return tts_with_buffer_and_rate_limit_step(stream, tts_step)

    stream, text_output = cancelable_substream_step(
        stream, speech_start, create_output_chain
    )
    return stream, text_input, text_output


@app.websocket("/ws/langchain/<chain_name>")
async def langchain_call(chain_name):
    logger.info(f"Receiving voicebot call with {chain_name}")
    os.makedirs("target/calls", exist_ok=True)
    stream = quart_websocket_source()
    input_flow = TwilioInputFlow.create(
        stream,
        close_func=lambda: websocket.close(1000),
        current_calls=current_app.current_calls,
    )
    stream = input_flow.audio
    stream, audio_input = fork_step(stream)

    audio_output, text_input, text_output = create_langchain_flow(
        stream, telephony=True
    )

    stream = audio_bytes_to_twilio_media_step(audio_output, input_flow.stream_sid_f)
    stream = quart_websocket_sink(stream)

    audio_filename = map_future(
        input_flow.call_sid_f, lambda x: f"target/calls/{x}.wav"
    )
    audio_input = wav_mulaw_file_sink(audio_input, audio_filename)

    text_input = map_step(text_input, lambda x: TextInput(text=x))
    text_output = map_step(text_output, lambda x: TextOutput(text=x))

    events = merge_step(text_input, text_output, input_flow.events)
    events = log_step(events, "Merged events")
    events = queue_sink(events, input_flow.outbound_queue_f)

    await run_call(input_flow.call_sid_f, stream, events, audio_input)


async def run_call(call_sid: AwaitableOrObj[str], *sinks: list[Coroutine]):
    """Called after the streams have been set up.  Takes a list of sinks to wait on"""
    result = asyncio.gather(*sinks)
    try:
        logger.info("Call stream is set up, processing messages...")
        await result
    finally:
        logger.info("All tasks finished.")
        resolved_call_sid = await resolve_awaitable_or_obj(call_sid)
        del current_app.current_calls[resolved_call_sid]


@app.websocket("/ws/audio/record")
async def browser_record():
    browser_call_id = await _setup_browser_call()
    logger.info(f"Recording audio from browser uuid: {browser_call_id}")
    os.makedirs("target/browser", exist_ok=True)
    stream = quart_websocket_source()
    # stream = log_step(stream, "Received audio from browser")
    await binary_file_sink(stream, f"target/browser/{browser_call_id}.webm")


@app.websocket("/ws/audio/transcribe")
async def browser_transcribe():
    browser_call_id = await _setup_browser_call()
    logger.info(f"Playback and record browser audio.  uuid: {browser_call_id}")
    stream = quart_websocket_source()
    stream, audio_save = fork_step(stream)
    audio_out = binary_file_sink(audio_save, f"all.webm")
    # os.makedirs("target/browser", exist_ok=True)
    # now = time.perf_counter()
    # def audio_json(packet):
    #     encoded_data = base64.b64encode(packet).decode("utf-8")
    #     return {"time":time.perf_counter()-now, "audio":encoded_data}
    # audio_save = map_step(audio_save, audio_json)
    # audio_done = text_file_sink(audio_save, f"target/browser/{browser_call_id}.ndjson")
    # stream = log_step(stream, "Audio", lambda x: len(x))
    stream = google_speech_step(
        stream,
        current_app.speech_async_client,
        project=app.config["GCP_PROJECT_ID"],
        location=app.config["GCP_SPEECH_LOCATION"],
        recognizer=app.config["GCP_BROWSER_SPEECH_RECOGNIZER"],
        model="latest_long",
        language_codes=["en-US", "es-US"],
        audio_format=AudioFormat.WEBM_OPUS,
        stream_reset_timeout_secs=10,
    )
    stream = log_step(stream, "Speech")
    stream = map_step(stream, lambda x: TextInput(text=x))
    done = queue_sink(stream, current_app.current_calls[browser_call_id].outbound)
    await run_call(browser_call_id, done, audio_out)
    logger.info("Transcription started")


@app.websocket("/ws/audio/langchain/<chain_name>")
async def browser_langchain(chain_name):
    browser_call_id = await _setup_browser_call()
    logger.info(f"Running langchain from browser uuid: {browser_call_id}")
    os.makedirs("target/browser", exist_ok=True)
    stream = quart_websocket_source()
    stream, audio_input = fork_step(stream)
    stream, text_input, text_output = create_langchain_flow(stream, telephony=False)
    audio_output = log_step(stream, "Audio out", lambda x: len(x))
    stream = quart_websocket_sink(audio_output)

    audio_input = binary_file_sink(
        audio_input, f"target/browser/{browser_call_id}.webm"
    )

    text_input = map_step(text_input, lambda x: TextInput(text=x))
    text_output = map_step(text_output, lambda x: TextOutput(text=x))

    events = merge_step(text_input, text_output)
    events = log_step(events, "Merged events")
    events = queue_sink(events, current_app.current_calls[browser_call_id].outbound)
    await run_call(browser_call_id, stream, events, audio_input)


async def _setup_browser_call():
    query_string = websocket.scope["query_string"].decode()
    query_params = urllib.parse.parse_qs(query_string)
    id = query_params.get("id", [str(uuid.uuid4())])[0]
    if id in current_app.current_calls:
        raise BadRequest(f"Call {id} already in progress.")
    queues = CallQueues()
    current_app.current_calls[id] = queues
    await queues.outbound.put(CallStarted(call_id=id, stream_id=None))
    return id


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
    )
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("openai").setLevel(logging.INFO)
    logging.getLogger("quart_ngrok").setLevel(logging.INFO)

    run_quart_ngrok(app)
