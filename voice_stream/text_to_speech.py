import asyncio
import logging
import string
import time
from typing import AsyncIterator, Tuple, Callable, Union

import asyncstdlib
from pydantic import BaseModel

from voice_stream.audio import AudioFormat, get_audio_length, audio_rate_limit_step
from voice_stream.core import (
    fork_step,
    map_step,
    extract_value_step,
    AwaitableOrObj,
    str_buffer_step,
    filter_step,
)
from voice_stream.events import TimedText
from voice_stream.types import resolve_awaitable_or_obj

logger = logging.getLogger(__name__)


class AudioWithText(BaseModel):
    audio: bytes
    text: str
    audio_format: AudioFormat


TextToSpeechStep = Callable[[AsyncIterator[str]], AsyncIterator[AudioWithText]]


def buffer_tts_text_step(async_iter: AsyncIterator[str]):
    stream = wait_for_punctuation_step(async_iter)
    stream = str_buffer_step(stream)
    stream = filter_step(stream, lambda x: len(x) > 0)
    return stream


def tts_with_buffer_and_rate_limit_step(
    async_iter: AsyncIterator[str], tts_step, buffer_seconds: float = 0.5
) -> (AsyncIterator[bytes], AsyncIterator[str]):
    stream = buffer_tts_text_step(async_iter)
    stream = tts_step(stream)
    stream, audio_format_f = extract_value_step(stream, lambda x: x.audio_format)
    stream, text_output = tts_rate_limit_step(
        stream, audio_format_f, buffer_seconds=buffer_seconds
    )
    return stream, text_output


async def wait_for_punctuation_step(
    async_iter: AsyncIterator[str],
) -> AsyncIterator[str]:
    """For TTS, we want to generate as soon as possible, but we don't want to do partial phrases.  Go until we get
    a punctuation mark or an empty token (which signals the end of a phrase)."""
    buffer = ""
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            buffer += item
            has_punc = any(char in string.punctuation for char in item.strip())
            if len(item) == 0 or has_punc:
                yield buffer
                buffer = ""


def tts_rate_limit_step(
    async_iter: AsyncIterator[AudioWithText],
    audio_format: AwaitableOrObj[AudioFormat],
    buffer_seconds: float = 0.5,
    include_text_output: bool = True,
) -> Union[AsyncIterator[bytes], Tuple[AsyncIterator[bytes], AsyncIterator[str]]]:
    """Breaks a single TextToSpeechOutput into smaller chunks."""

    async def tts_output_to_timed_text(tts: AudioWithText) -> TimedText:
        resolved_audio_format = await resolve_awaitable_or_obj(audio_format)
        duration = get_audio_length(resolved_audio_format, tts.audio)
        return TimedText(tts.text, duration_in_seconds=duration)

    if include_text_output:
        audio, text = fork_step(async_iter, pull_from_all=False)
        text = map_step(text, tts_output_to_timed_text)
        # text = log_step(text, "Timed text in")
        text = timed_text_rate_limit_step(text, buffer_seconds=buffer_seconds)
        # text = log_step(text, "Timed text out")
    else:
        audio = async_iter

    audio = map_step(audio, lambda x: x.audio)
    # audio = log_step(audio, "Audio out", lambda x: len(x))
    audio = audio_rate_limit_step(audio, audio_format, buffer_seconds=buffer_seconds)

    if include_text_output:
        return audio, text
    else:
        return audio


async def timed_text_rate_limit_step(
    async_iter: AsyncIterator[TimedText], buffer_seconds: float = 0.5
) -> AsyncIterator[str]:
    """Used in conjunction with text to speech.  Takes in timed text and outputs it token by token given the time.
    Assumes all tokens take equal time.
    """
    last_send = time.perf_counter()
    queued_text_seconds = 0

    def compute_remaining(now):
        # Compute the amount of text remaining to be played in seconds.
        return max(0, queued_text_seconds - (now - last_send))

    async def break_into_tokens(timed_text: TimedText):
        tokens = timed_text.text.split(" ")
        if len(tokens) > 0:
            token_duration = timed_text.duration_in_seconds / len(tokens)
            tokens = [tokens[0]] + [" " + _ for _ in tokens[1:]]
            for token in tokens:
                yield TimedText(token, token_duration)
        else:
            yield timed_text

    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for timed_text in owned_aiter:
            async for token in break_into_tokens(timed_text):
                now = time.perf_counter()
                remaining_text_seconds = compute_remaining(now)
                # If we have more than the buffer, sleep until we hit the buffer limit
                if remaining_text_seconds > buffer_seconds:
                    await asyncio.sleep(remaining_text_seconds - buffer_seconds)
                    # We don't know how long we actually slept.
                    now = time.perf_counter()
                    remaining_text_seconds = compute_remaining(now)
                queued_text_seconds = remaining_text_seconds + token.duration_in_seconds
                last_send = now
                yield token.text


async def min_tokens_step(
    async_iter: AsyncIterator[str], min_tokens: int = 3
) -> AsyncIterator[str]:
    """Makes sure we have at least minimum number of tokens, but always flushes on an empty token."""
    buffer = ""
    num_tokens = 0
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for item in owned_aiter:
            if len(item) == 0:
                if len(buffer) > 0:
                    yield buffer
                    buffer = ""
            else:
                buffer += item
                num_tokens += 1
                if num_tokens >= min_tokens:
                    yield buffer
                    buffer = ""
                    num_tokens = 0
    if len(buffer) > 0:
        yield buffer
