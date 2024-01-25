import logging
from typing import AsyncIterator

from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain.memory import ConversationBufferMemory

from examples.gpt_gemini_showdown.gpt4_gemini_panel import full_discussion_chain
from voice_stream import (
    fork_step,
    map_step,
    log_step,
    partition_step,
    recover_exception_step,
    filter_step,
    buffer_tts_text_step,
    merge_as_dict_step,
    tts_rate_limit_step,
    merge_step,
    concat_step,
    cancelable_substream_step,
)
from voice_stream.audio import AudioFormat
from voice_stream.core import single_source, array_source, collect_dict_step, empty_sink
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
from voice_stream.speech_to_text import first_partial_speech_result_step

logger = logging.getLogger(__name__)


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
    chain = full_discussion_chain()

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
            text_to_speech_async_client,
            audio_format=AudioFormat.MP3,
            speaking_rate=1.25,
        )
        stream, text_output = tts_rate_limit_step(stream, audio_format=AudioFormat.MP3)
        text_output = map_step(text_output, lambda x: {"output": x})
        model_stream_for_output = map_step(
            model_stream_for_output, lambda x: {"model": x}
        )
        text_output = merge_step(text_output, model_stream_for_output)
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
            "output": {"output": f'{x["model"]}: {x["output"]}'},
        },
    )
    memory_stream = log_step(memory_stream, "Conversation Memory:")
    memory_stream = langchain_save_memory_step(memory_stream, memory)
    memory_done = empty_sink(memory_stream)
    return stream, text_output, memory_done
