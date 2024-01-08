import pytest
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient

from tests.unit_tests.integrations.example_chains import math_physics_routing
from voice_stream.audio import wav_mulaw_file_sink, AudioFormat
from voice_stream import (
    array_source,
    str_buffer_step,
    log_step,
    byte_buffer_step,
    map_step,
)
from voice_stream.integrations.google_streams import google_text_to_speech_step
from voice_stream.integrations.langchain_streams import langchain_step


@pytest.mark.asyncio
async def test_llm_and_tts(tmp_path):
    chain = math_physics_routing()
    pipe = array_source(
        [
            "In one sentence, explain the second law of thermodynamics.",
            "What is 4*8",
        ]
    )
    pipe = langchain_step(pipe, chain)
    pipe = str_buffer_step(pipe)
    pipe = log_step(pipe, "LLM output")
    text_to_speech_async_client = TextToSpeechAsyncClient()
    pipe = google_text_to_speech_step(
        pipe, text_to_speech_async_client, audio_format=AudioFormat.WAV_MULAW_8KHZ
    )
    pipe = map_step(pipe, lambda x: x.audio)
    pipe = byte_buffer_step(pipe)
    ret = await wav_mulaw_file_sink(pipe, tmp_path.joinpath("chain_tts.wav"))
