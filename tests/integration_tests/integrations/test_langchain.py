import logging

import pytest
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from langchain_community.chat_models import ChatVertexAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from tests.unit_tests.integrations.example_chains import math_physics_routing
from voice_stream import (
    array_source,
    str_buffer_step,
    log_step,
    byte_buffer_step,
    map_step,
)
from voice_stream.audio import wav_mulaw_file_sink, AudioFormat
from voice_stream.core import single_source, array_sink
from voice_stream.integrations.google import google_text_to_speech_step
from voice_stream.integrations.langchain import langchain_step

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_llm_and_tts(tmp_path):
    chain = math_physics_routing()
    stream = array_source(
        [
            "In one sentence, explain the second law of thermodynamics.",
            "What is 4*8",
        ]
    )
    stream = langchain_step(stream, chain, on_completion="")
    stream = str_buffer_step(stream)
    stream = log_step(stream, "LLM output")
    text_to_speech_async_client = TextToSpeechAsyncClient()
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.WAV_MULAW_8KHZ
    )
    stream = map_step(stream, lambda x: x.audio)
    stream = byte_buffer_step(stream)
    out = await wav_mulaw_file_sink(stream, tmp_path.joinpath("chain_tts.wav"))


@pytest.mark.asyncio
async def test_gemini():
    chain = (
        ChatPromptTemplate.from_messages([("human", "{query}")])
        | ChatVertexAI(model_name="gemini-pro")
        | StrOutputParser()
    )
    stream = single_source({"query": "What's 2+2?"})
    stream = langchain_step(stream, chain, on_completion="")
    out = await array_sink(stream)
    logger.info(f"Gemini response {out}")
    assert len(out) == 2
    assert out[1] == ""
