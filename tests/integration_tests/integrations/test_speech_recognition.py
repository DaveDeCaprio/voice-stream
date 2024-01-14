# Deprecated because it only works with already decoded PCM data.

# import logging
# import os
#
# import pytest
#
# from tests.helpers import example_file
# from voice_stream import wav_mulaw_file_source, array_sink, map_step
# from voice_stream.audio.audio_streams import remove_wav_header
# from voice_stream.integrations.speech_recognition_streams import python_speech_recognition_step
#
# logger = logging.getLogger(__name__)
#
#
# @pytest.mark.asyncio
# async def test_recognize_whisper():
#     stream = wav_mulaw_file_source(example_file("testing.wav"), chunk_size=0)
#     stream = map_step(stream, remove_wav_header)
#     stream = python_speech_recognition_step(
#         stream,
#         "recognize_whisper_api",
#         sample_rate=8000,
#         sample_width=1,
#         api_key=os.environ['OPENAI_API_KEY'],
#     )
#     out = await array_sink(stream)
#     assert out == ["testing 1 2 3 testing 1 2 3"]
