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
    """
    Representing audio data along with its corresponding text.  Used as the output of a text-to-speech step.
    """

    audio: bytes
    """The audio data."""

    text: str
    """The corresponding text for the audio."""

    audio_format: AudioFormat
    """The format of the audio."""


TextToSpeechStep = Callable[[AsyncIterator[str]], AsyncIterator[AudioWithText]]


def buffer_tts_text_step(async_iter: AsyncIterator[str]) -> AsyncIterator[str]:
    """
    Data flow step that buffers text for input to Text-to-Speech (TTS).

    When performing realtime TTS off of a token stream, there is a tradeoff.  You want to produce audio as soon as
    possible after receiving the first token, but passing longer utterances to a TTS engine produces more natural sounding
    speech.  This step buffers tokens to achieve a good balance by:

    1. Waiting for punctuation: Waits for some form of punctuation in the token stream to indicate the end of a phrase
       and then passes the full phrase.
    2. Buffers tokens received between pulls.  This step eagerly pulls tokens from the incoming iterator and buffers them.
       This way, any new tokens that come in while the TTS system is generating the current utterance are grouped together.

    Parameters
    ----------
    async_iter : AsyncIterator[str]
        An asynchronous iterator that provides a stream of text.

    Returns
    -------
    AsyncIterator[str]
        The buffered TTS text.

    Example
    -------
    >>> stream = array_source(["Hello", " world!", " How", " are", " you", " today", ""])
    >>> stream = buffer_tts_text_step(stream)
    >>> out = await array_sink(stream)
    >>> assert out == ["Hello world!", " How are you today"]

    Note
    -------
    - An incoming empty string indicates an end of response and will cause the buffer to be flushed.

    """
    stream = wait_for_punctuation_step(async_iter)
    stream = str_buffer_step(stream)
    stream = filter_step(stream, lambda x: len(x) > 0)
    return stream


def tts_with_buffer_and_rate_limit_step(
    async_iter: AsyncIterator[str],
    tts_step: TextToSpeechStep,
    buffer_seconds: float = 0.5,
) -> (AsyncIterator[bytes], AsyncIterator[str]):
    """
    Data flow step that wraps a text to speech (TTS) step with buffering before the TTS and rate limiting on the output.

    Creates a data stream to handle a typical TTS flow.  It buffers input tokens to produce output as soon as possible but
    still keeping phrases together to produce natural sounding TTS.  It applies rate limiting to both the audio and text
    output.

    Parameters
    ----------
    async_iter : AsyncIterator[str]
        An asynchronous iterator yielding text strings to be converted to speech.
    tts_step : TextToSpeechStep
        A function that takes an async iterator of text strings and returns an async iterator of audio bytes.
    buffer_seconds : float, default 0.5
        The duration (in seconds) of audio to buffer for rate limiting.

    Returns
    -------
    Tuple[AsyncIterator[bytes], AsyncIterator[str]]
        A tuple containing rate-limited iterators over the audio and text streams.

    Examples
    --------
    >>> tts_step = google_text_to_speech_step(
    ...     stream, text_to_speech_async_client, audio_format=AudioFormat.MP3
    ... )
    >>> stream = array_source(["Hello", "World"])
    >>> audio_stream, text_stream = tts_with_buffer_and_rate_limit_step(stream, tts_step)
    >>> audio_done = empty_sink(audio_stream)
    >>> text_done = array_sink(text_stream)
    >>> audio_out, text_out = asyncio.gather(audio_done, text_done)
    >>> assert text_out == [TimedText("Hello", 0.2), TimedText("World", 0.2)]
    """
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
    """
    Data flow step that buffers incoming text tokens into phrases based on punctuation.

    Parameters
    ----------
    async_iter : AsyncIterator[str]
        An asynchronous iterator yielding text strings to be converted to speech.

    Returns
    -------
    AsyncIterator[str]
        The input token concatenated into phrases based on punctuation.
    """
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
    """
    Applies rate limiting to an audio stream from a TTS output, optionally including synchronized text output.

    This function processes an asynchronous iterator of TTS audio output, each paired with text. It applies
    rate limiting to ensure that audio is emitted at a realistic rate based on its duration. Additionally,
    it can output timed text that is synchronized with the audio output. The text timing is adjusted based
    on the audio format and the buffer duration.  Rate-limiting allows the audio to be cancelled if an interruption
    occurs.

    Parameters
    ----------
    async_iter : AsyncIterator[voice_stream.AudioWithText]
        An asynchronous iterator yielding audio data paired with text.
    audio_format : AwaitableOrObj[voice_stream.audio.AudioFormat]
        The format of the audio stream, which can be an awaitable or a direct object.
    buffer_seconds : float, default 0.5
        The duration in seconds to buffer for rate limiting.
    include_text_output : bool, default True
        If True, includes a text output iterator that yields text synchronized with the audio rate.

    Returns
    -------
    Union[AsyncIterator[bytes], Tuple[AsyncIterator[bytes], AsyncIterator[str]]]
        Depending on `include_text_output`, either an async iterator of audio bytes or a tuple of
        async iterators for audio bytes and synchronized text.
    """

    async def tts_output_to_timed_text(tts: AudioWithText) -> TimedText:
        resolved_audio_format = await resolve_awaitable_or_obj(audio_format)
        duration = get_audio_length(resolved_audio_format, tts.audio)
        return TimedText(text=tts.text, duration_in_seconds=duration)

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
    """
    Data flow step that takes :class:`~voice_stream.TimedText` objects and yield their text tokens based on the indicated timing.

    This step is usually used in combination with a rate limiting step.  The rate at which the text should be outputted
    is produced in a previous step and passed in `TimedText` objects.  This step then produces the raw text with the
    appropriate delays.

    Parameters
    ----------
    async_iter : AsyncIterator[TimedText]
        An asynchronous iterator over `TimedText` objects. Each `TimedText` object
        contains text and a duration in seconds.
    buffer_seconds : float, optional
        A buffer time in seconds to control the rate of text token output.  The buffer is designed so that the downstream
        iterator will always have at least buffer_seconds of text to display.

    Returns
    ------
    AsyncIterator[str]
        An asynchronous iterator yielding text tokens.

    Notes
    -----
    - The step will impose delays to slow down the rate at which objects pass through the stream, but because streams
      are pull-based, the downstream iterator must be ready to consume the objects that fast.  This step will never go
      faster than the downstream iterator allows.
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
                yield TimedText(text=token, duration_in_seconds=token_duration)
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
    async_iter: AsyncIterator[str], min_tokens: int
) -> AsyncIterator[str]:
    """
    Data flow step that aggregates string inputs to ensure a minimum number of tokens.

    The step assumes each input item is a single token, and concatenates the tokens until either an empty string is
    received or the number of concatenated tokens is at least `min_tokens`.

    Parameters
    ----------
    async_iter : AsyncIterator[TimedText]
        An asynchronous iterator over `TimedText` objects. Each `TimedText` object
        contains text and a duration in seconds.
    min_tokens : int
        The minimum number of tokens to buffer before outputting the concatenated value.

    Notes
    -----
    - If an empty token is detected, the function will automatically flush (i.e., clear and reset) the token list.
    """
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
