import asyncio

import pytest

from voice_stream.core import array_sink
from voice_stream.events import SpeechStart, SpeechEnd, SpeechPartialResult
from voice_stream.speech_to_text import (
    filter_spurious_speech_start_events_step,
    first_partial_speech_result_step,
)


@pytest.mark.asyncio
async def test_filter_spurious_speech_start_events_step():
    async def gen():
        yield SpeechStart(time_since_start=1)
        await asyncio.sleep(0.1)
        yield SpeechStart(time_since_start=2)
        await asyncio.sleep(0.5)

    stream = gen()
    stream = filter_spurious_speech_start_events_step(stream, 0.2)
    out = await array_sink(stream)
    assert out == [SpeechStart(time_since_start=2)]


@pytest.mark.asyncio
async def test_filter_spurious_speech_start_events_step_with_cancel():
    async def gen():
        yield SpeechStart(time_since_start=1)
        await asyncio.sleep(0.1)
        yield SpeechEnd(time_since_start=2)
        await asyncio.sleep(0.3)

    stream = gen()
    stream = filter_spurious_speech_start_events_step(stream, 0.2)
    out = await array_sink(stream)
    assert out == []


@pytest.mark.asyncio
async def test_first_partial_result_step():
    async def gen():
        yield SpeechStart(time_since_start=1)
        yield SpeechEnd(time_since_start=2)
        yield SpeechPartialResult(text="hello", time_since_start=1.5)
        yield SpeechPartialResult(text="hello world", time_since_start=2)
        yield SpeechStart(time_since_start=1)
        yield SpeechPartialResult(text="next", time_since_start=2.5)

    stream = gen()
    stream = first_partial_speech_result_step(stream)
    out = await array_sink(stream)
    assert out == [
        SpeechPartialResult(text="hello", time_since_start=1.5),
        SpeechPartialResult(text="next", time_since_start=2.5),
    ]
