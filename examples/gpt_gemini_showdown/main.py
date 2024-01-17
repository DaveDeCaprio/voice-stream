from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from typing import Coroutine, AsyncIterator, Optional, Any

from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain.globals import set_llm_cache
from langchain.memory import ConversationBufferMemory
from langchain_community.cache import SQLiteCache
from quart import (
    Quart,
    render_template,
    current_app,
)

from gpt4_gemini_panel import full_discussion_chain
from voice_stream import (
    fork_step,
    map_step,
    buffer_tts_text_step,
    tts_rate_limit_step,
    filter_spurious_speech_start_events_step,
    cancelable_substream_step,
    queue_sink,
    queue_source,
    collect_dict_step,
    log_step,
    empty_sink,
    merge_as_dict_step,
    array_source,
    binary_file_sink,
    merge_step,
    filter_step,
    partition_step,
)
from voice_stream.audio import AudioFormat
from voice_stream.integrations.google import (
    google_speech_step,
    TTSRequest,
    google_text_to_speech_step,
)
from voice_stream.integrations.langchain import (
    langchain_load_memory_step,
    langchain_step,
    langchain_save_memory_step,
)
from voice_stream.integrations.quart import quart_websocket_source, quart_websocket_sink

# Set up logging and turn off noisy logs
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)
logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("openai").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Set up clients
load_dotenv()
app = Quart(__name__)
app.config["HTTP_SERVER_PORT"] = 8080
app.config["GCP_PROJECT_ID"] = os.environ["GCP_PROJECT_ID"]
app.config["GCP_SPEECH_LOCATION"] = os.environ["GCP_SPEECH_LOCATION"]
app.config["GCP_BROWSER_SPEECH_RECOGNIZER"] = os.environ[
    "GCP_BROWSER_SPEECH_RECOGNIZER"
]

set_llm_cache(SQLiteCache(database_path=".langchain.db"))


@app.before_serving
async def before_serving():
    current_app.speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    current_app.text_to_speech_async_client = TextToSpeechAsyncClient()


@app.route("/")
async def index():
    return await render_template("index.html")


# Incoming and outgoing message queues for each session
@dataclasses.dataclass
class CallQueues:
    inbound = asyncio.Queue()
    outbound = asyncio.Queue()


current_streams = {}


async def wait_on_sinks(*sinks: list[Coroutine]):
    """Called after the streams have been set up.  Takes a list of sinks to wait on"""
    result = asyncio.gather(*sinks)
    logger.info("Call stream is set up, processing messages...")
    await result
    logger.info("All tasks finished.")


@app.websocket("/chat/<id>")
async def chat(id):
    """Streams back call status updates."""
    queues = current_streams.get(id, None)
    if queues:
        # If queues exist, it's an audio call and the main processing happens on the audio websocket.
        # Just forward messages from queues here.
        logger.info(f"Hooking up call status for audio call {id}")
        inputs = quart_websocket_source()
        inputs = queue_sink(inputs, queues.inbound)
        outputs = queue_source(queues.outbound)
        outputs = quart_websocket_sink(outputs)
        await wait_on_sinks(inputs, outputs)
    else:
        # If no queues, this is a text only chat, run langchain to set up the full chain.
        logger.info(f"New text chat. {id}")
        stream = quart_websocket_source()
        stream = log_step(stream, "Human Input")

        memory = ConversationBufferMemory(return_messages=True)
        chain = full_discussion_chain()

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
        # Convert the model name to a string
        stream = map_step(
            stream, lambda x: {**x, "model": x["model"].value} if "model" in x else x
        )
        stream_done = quart_websocket_sink(stream)

        memory_stream = collect_dict_step(memory_stream)
        memory_stream = map_step(
            memory_stream,
            lambda x: {
                "input": {"query": x["query"]},
                "output": {"output": f'{x["model"]}: {x["output"]}'},
            },
        )
        memory_stream = log_step(memory_stream, "Conversation Memory:")
        memory_stream = langchain_save_memory_step(memory_stream, memory)
        memory_done = empty_sink(memory_stream)

        await wait_on_sinks(stream_done, memory_done)


@app.websocket("/audio/<id>")
async def audio(id):
    current_streams[id] = CallQueues()

    stream = quart_websocket_source()
    stream, audio_input = fork_step(stream)

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
    stream, text_input = fork_step(stream)
    text_input = map_step(text_input, lambda x: {"query": x})

    memory = ConversationBufferMemory(return_messages=True)
    chain = full_discussion_chain()

    def response_stream(stream):
        stream = map_step(stream, lambda x: {"query": x})
        stream = langchain_load_memory_step(stream, memory)
        stream = log_step(stream, "LLM Input")
        stream = langchain_step(stream, chain, on_completion="")
        stream = filter_step(stream, lambda x: x != "" and ("history" not in x))
        stream = map_step(
            stream, lambda x: {"model": x["model"].value} if "model" in x else x
        )
        stream, text_output = fork_step(stream)
        # stream = log_step(stream, "pre-dict substream")
        model_stream, stream = partition_step(stream, lambda x: "model" in x)
        stream = map_step(stream, lambda x: x.get("output", None), ignore_none=True)
        stream = buffer_tts_text_step(stream)
        model_stream = map_step(model_stream, lambda x: x["model"])
        model_stream, model_stream_for_output = fork_step(model_stream)
        stream = merge_as_dict_step({"output": stream, "model": model_stream})
        # stream = log_step(stream, "post-dict substream")
        stream = map_step(
            stream,
            lambda d: TTSRequest(
                text=d["output"],
                voice="en-US-Standard-H" if d["model"] == "GPT" else "en-GB-News-K",
            ),
        )
        stream = log_step(stream, "TTS input")
        stream = google_text_to_speech_step(
            stream,
            current_app.text_to_speech_async_client,
            audio_format=AudioFormat.MP3,
        )
        stream, text_output = tts_rate_limit_step(stream, audio_format=AudioFormat.MP3)
        text_output = map_step(text_output, lambda x: {"output": x})
        model_stream_for_output = map_step(
            model_stream_for_output, lambda x: {"model": x}
        )
        text_output = merge_step(text_output, model_stream_for_output)
        return stream, text_output

    speech_start = filter_spurious_speech_start_events_step(
        speech_start, threshold_secs=0.5
    )
    stream, text_output = cancelable_substream_step(
        stream,
        speech_start,
        response_stream,
        cancel_messages=[
            None,
            lambda: array_source([{"output": "..."}, ""]),
        ],
    )

    audio_output_done = quart_websocket_sink(stream)

    os.makedirs("logs/browser", exist_ok=True)
    audio_input_done = binary_file_sink(audio_input, f"logs/browser/{id}.webm")

    text_output = merge_step(text_input, text_output)

    text_output, memory_stream = fork_step(text_output)
    text_output = filter_step(text_output, lambda x: x != "")
    text_output = log_step(text_output, "Events")
    text_output_done = queue_sink(text_output, current_streams[id].outbound)

    memory_stream = collect_dict_step(memory_stream)
    # Ignore the case where there was an interruption before a full response
    memory_stream = filter_step(memory_stream, lambda x: "model" in x and "output" in x)
    memory_stream = map_step(
        memory_stream,
        lambda x: {
            "input": {"query": x["query"]},
            "output": {"output": f'{x["model"]}: {x["output"]}'},
        },
    )
    memory_stream = log_step(memory_stream, "Conversation Memory:")
    memory_stream = langchain_save_memory_step(memory_stream, memory)
    memory_done = empty_sink(memory_stream)

    await wait_on_sinks(
        audio_output_done, audio_input_done, text_output_done, memory_done
    )


if __name__ == "__main__":
    app.run(port=app.config["HTTP_SERVER_PORT"])
