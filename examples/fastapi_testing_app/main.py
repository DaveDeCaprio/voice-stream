from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from typing import Coroutine, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import Request
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain.memory import ConversationBufferMemory
from starlette.templating import Jinja2Templates
from starlette.websockets import WebSocket

from examples.fastapi_testing_app.chain import create_chain
from voice_stream import (
    queue_source,
    map_step,
    queue_sink,
    log_step,
    fork_step,
    binary_file_sink,
    empty_sink,
    collect_dict_step,
    filter_step,
    recover_exception_step,
    partition_step,
    buffer_tts_text_step,
    tts_rate_limit_step,
    concat_step,
    cancelable_substream_step,
)
from voice_stream.audio import AudioFormat
from voice_stream.core import single_source, array_source, merge_step
from voice_stream.integrations.fastapi import (
    fastapi_websocket_text_sink,
    fastapi_websocket_bytes_source,
    fastapi_websocket_bytes_sink,
    fastapi_websocket_text_source,
)
from voice_stream.integrations.google import (
    google_speech_step,
    google_text_to_speech_step,
)
from voice_stream.integrations.langchain import (
    langchain_step,
    langchain_save_memory_step,
    langchain_load_memory_step,
)
from voice_stream.speech_to_text import first_partial_speech_result_step

logger = logging.getLogger(__name__)

# Set up logging and turn off noisy logs
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)
logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("openai").setLevel(logging.INFO)

# Set up clients
load_dotenv()


@dataclasses.dataclass
class CallQueues:
    inbound = asyncio.Queue()
    outbound = asyncio.Queue()


speech_async_client = SpeechAsyncClient(
    client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
)
text_to_speech_async_client = TextToSpeechAsyncClient()

current_calls = {}

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


current_streams = {}


async def wait_on_sinks(*sinks: list[Coroutine]):
    """Called after the streams have been set up.  Takes a list of sinks to wait on"""
    result = asyncio.gather(*sinks)
    logger.info("Call stream is set up, processing messages...")
    await result
    logger.info("All tasks finished.")


@app.websocket("/chat/{id}")
async def chat(websocket: WebSocket, id: str):
    """Streams back call status updates."""
    queues = current_streams.get(id, None)
    if queues:
        # If queues exist, it's an audio call and the main processing happens on the audio websocket.
        # Just forward messages from queues here.
        logger.info(f"Hooking up call status for audio call {id}")
        inputs = fastapi_websocket_text_source(websocket)
        inputs = queue_sink(inputs, queues.inbound)
        outputs = queue_source(queues.outbound)
        outputs = fastapi_websocket_text_sink(outputs, websocket)
        await wait_on_sinks(inputs, outputs)
    else:
        # If no queues, this is a text only chat, run langchain to set up the full chain.
        logger.info(f"New text chat. {id}")
        stream = fastapi_websocket_text_source(websocket)
        stream = log_step(stream, "Human Input")

        memory = ConversationBufferMemory(return_messages=True)
        chain = create_chain()

        stream = map_step(stream, lambda x: {"query": x})
        stream = langchain_load_memory_step(stream, memory)
        stream = langchain_step(stream, chain, on_completion="")
        stream, memory_stream = fork_step(stream)
        # Remove empty token that marks end of stream.
        stream = filter_step(stream, lambda x: x)
        # Remove full conversation history.  We don't need it.
        stream = map_step(
            stream, lambda x: {k: v for k, v in x.items() if k != "history"}
        )
        stream = log_step(stream, "Send to client")
        stream_done = fastapi_websocket_text_sink(stream, websocket)

        memory_stream = collect_dict_step(memory_stream)
        memory_stream = map_step(
            memory_stream,
            lambda x: {
                "input": {"query": x["query"]},
                "output": {"output": x["output"]},
            },
        )
        memory_stream = log_step(memory_stream, "Conversation Memory:")
        memory_stream = langchain_save_memory_step(memory_stream, memory)
        memory_done = empty_sink(memory_stream)

        await wait_on_sinks(stream_done, memory_done)


@app.websocket("/audio/{id}")
async def audio(websocket: WebSocket, id: str):
    current_streams[id] = CallQueues()

    stream = fastapi_websocket_bytes_source(websocket)
    stream, audio_input = fork_step(stream)

    audio_output, text_output, memory_done = run_chat_flow(
        stream=stream,
        speech_async_client=speech_async_client,
        project=app.config["GCP_PROJECT_ID"],
        location=app.config["GCP_SPEECH_LOCATION"],
        recognizer=app.config["GCP_BROWSER_SPEECH_RECOGNIZER"],
        text_to_speech_async_client=text_to_speech_async_client,
    )

    audio_output_done = fastapi_websocket_bytes_sink(audio_output, websocket)
    text_output_done = queue_sink(text_output, current_streams[id].outbound)

    os.makedirs("logs/browser", exist_ok=True)
    audio_input_done = binary_file_sink(audio_input, f"logs/browser/{id}.webm")

    await wait_on_sinks(
        audio_output_done, audio_input_done, text_output_done, memory_done
    )


def run_chat_flow(
    stream: AsyncIterator[bytes],
    speech_async_client: SpeechAsyncClient,
    project: str,
    location: str,
    recognizer: str,
    text_to_speech_async_client: TextToSpeechAsyncClient,
):
    stream, speech_event_stream = google_speech_step(
        stream,
        speech_async_client,
        project=project,
        location=location,
        recognizer=recognizer,
        model="latest_long",
        language_codes=["en-US", "es-US"],
        audio_format=AudioFormat.WEBM_OPUS,
        include_events=True,
        max_minutes=30,
    )
    stream, text_input = fork_step(stream)
    text_input = map_step(text_input, lambda x: {"query": x})

    memory = ConversationBufferMemory(return_messages=True)
    chain = create_chain()

    def create_response_substream(stream):
        stream = map_step(stream, lambda x: {"query": x})
        stream = langchain_load_memory_step(stream, memory)
        stream = log_step(stream, "LLM Input")
        stream = langchain_step(stream, chain, on_completion="")

        def handle_exception(e):
            logger.error(f"Langchain exception {e}", exc_info=True)
            return {"output": "I'm not allowed to answer that."}

        stream = recover_exception_step(stream, Exception, handle_exception)
        stream = filter_step(stream, lambda x: x != "" and ("history" not in x))
        stream = map_step(
            stream, lambda x: {"model": x["model"].value} if "model" in x else x
        )
        stream, text_output = fork_step(stream)
        # stream = log_step(stream, "pre-dict substream")
        stream = map_step(stream, lambda x: x.get("output", None), ignore_none=True)
        stream = buffer_tts_text_step(stream)
        stream = log_step(stream, "TTS input")
        stream = google_text_to_speech_step(
            stream,
            text_to_speech_async_client,
            audio_format=AudioFormat.MP3,
            speaking_rate=1.25,
        )
        stream, text_output = tts_rate_limit_step(stream, audio_format=AudioFormat.MP3)
        text_output = map_step(text_output, lambda x: {"output": x})
        text_output = concat_step(text_output, single_source(None))
        return stream, text_output

    speech_event_stream = first_partial_speech_result_step(speech_event_stream)
    speech_event_stream = log_step(speech_event_stream, "Interruption detected")
    stream, text_output = cancelable_substream_step(
        stream,
        speech_event_stream,
        create_response_substream,
        cancel_messages=[
            None,
            lambda: array_source([{"output": "..."}, None]),
        ],
    )

    text_output = merge_step(text_input, text_output)

    text_output, memory_stream = fork_step(text_output)
    text_output = filter_step(text_output, lambda x: x)
    # text_output = log_step(text_output, "Events")

    memory_stream = collect_dict_step(memory_stream)
    # Ignore the case where there was an interruption before a full response
    memory_stream = filter_step(memory_stream, lambda x: "model" in x and "output" in x)
    memory_stream = map_step(
        memory_stream,
        lambda x: {
            "input": {"query": x["query"]},
            "output": {"output": x["output"]},
        },
    )
    memory_stream = log_step(memory_stream, "Conversation Memory:")
    memory_stream = langchain_save_memory_step(memory_stream, memory)
    memory_done = empty_sink(memory_stream)
    return stream, text_output, memory_done
