import asyncio
import inspect
import logging
import string
import time
from typing import AsyncIterator, Tuple, Callable, Union

from pydantic import BaseModel

from voice_stream.audio import AudioFormat, AudioFormatError
from voice_stream.audio.audio_streams import (
    get_audio_length,
    ogg_page_separator_step,
    mp3_chunk_step,
)
from voice_stream.basic_streams import (
    chunk_bytes_step,
    fork_step,
    map_step,
    extract_value_step,
    FutureOrObj,
    async_init_step,
    str_buffer_step,
    filter_step,
)
from voice_stream.types import map_future, resolve_obj_or_future
from voice_stream.events import TimedText
from voice_stream.substreams import substream_step

logger = logging.getLogger(__name__)


class AudioWithText(BaseModel):
    audio: bytes
    text: str
    audio_format: AudioFormat


TextToSpeechStep = Callable[[AsyncIterator[str]], AsyncIterator[AudioWithText]]


def buffer_tts_text_step(async_iter: AsyncIterator[str]):
    pipe = wait_for_punctuation_step(async_iter)
    pipe = str_buffer_step(pipe)
    pipe = filter_step(pipe, lambda x: len(x) > 0)
    return pipe


def tts_with_buffer_and_rate_limit_step(
    async_iter: AsyncIterator[str], tts_step, buffer_seconds: float = 0.5
) -> (AsyncIterator[bytes], AsyncIterator[str]):
    pipe = buffer_tts_text_step(async_iter)
    pipe = tts_step(pipe)
    pipe, audio_format_f = extract_value_step(pipe, lambda x: x.audio_format)
    pipe, text_output = tts_rate_limit_step(
        pipe, audio_format_f, buffer_seconds=buffer_seconds
    )
    return pipe, text_output


async def wait_for_punctuation_step(
    async_iter: AsyncIterator[str],
) -> AsyncIterator[str]:
    """For TTS, we want to generate as soon as possible, but we don't want to do partial phrases.  Go until we get
    a punctuation mark or an empty token (which signals the end of a phrase)."""
    buffer = ""
    async for item in async_iter:
        buffer += item
        has_punc = any(char in string.punctuation for char in item.strip())
        if len(item) == 0 or has_punc:
            yield buffer
            buffer = ""


def tts_rate_limit_step(
    async_iter: AsyncIterator[AudioWithText],
    audio_format: FutureOrObj[AudioFormat],
    buffer_seconds: float = 0.5,
    include_text_output: bool = True,
) -> Union[AsyncIterator[bytes], Tuple[AsyncIterator[bytes], AsyncIterator[str]]]:
    """Breaks a single TextToSpeechOutput into smaller chunks."""

    async def tts_output_to_timed_text(tts: AudioWithText) -> TimedText:
        resolved_audio_format = await resolve_obj_or_future(audio_format)
        duration = get_audio_length(resolved_audio_format, tts.audio)
        return TimedText(tts.text, duration_in_seconds=duration)

    if include_text_output:
        audio, text = fork_step(async_iter, backpressure=True)
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


def audio_rate_limit_step(
    async_iter: AsyncIterator[bytes],
    audio_format: FutureOrObj[AudioFormat],
    buffer_seconds: float,
):
    def init(async_iter, af):
        if af == AudioFormat.WAV_MULAW_8KHZ:
            SAMPLE_RATE = 8000
            audio = chunk_bytes_step(async_iter, int(buffer_seconds * SAMPLE_RATE))
            audio = raw_audio_rate_limit_step(
                audio, SAMPLE_RATE, buffer_seconds=buffer_seconds
            )
        elif af == AudioFormat.OGG_OPUS:
            audio = _opus_rate_limit_step(async_iter, buffer_seconds=buffer_seconds)
        elif af == AudioFormat.MP3:
            audio = _mp3_rate_limit_step(async_iter, buffer_seconds=buffer_seconds)
        else:
            raise AudioFormatError(f"Unsupported audio format: {audio_format}")
        return audio

    async def async_init(async_iter):
        af = await resolve_obj_or_future(audio_format)
        return init(async_iter, af)

    if inspect.isawaitable(audio_format):
        return async_init_step(async_iter, async_init)
    else:
        return init(async_iter, audio_format)


def _opus_rate_limit_step(async_iter: AsyncIterator[bytes], buffer_seconds: float):
    def get_bytes_per_second(data):
        duration = get_audio_length(AudioFormat.OGG_OPUS, data)
        length_in_bytes = len(data)
        return int(length_in_bytes / duration)

    def opus_substream(async_iter: AsyncIterator[bytes]):
        pipe, bytes_per_second_f = extract_value_step(async_iter, get_bytes_per_second)
        chunk_size_f = map_future(
            bytes_per_second_f,
            lambda bytes_per_second: int(buffer_seconds * bytes_per_second / 2),
        )
        pipe = chunk_bytes_step(pipe, chunk_size_f)
        # pipe = log_step(pipe, "Audio Chunk", lambda x: len(x))
        pipe = raw_audio_rate_limit_step(
            pipe, bytes_per_second_f, buffer_seconds=buffer_seconds
        )
        pipe = ogg_page_separator_step(pipe)
        # pipe = log_step(pipe, "Full OGG Page", lambda x: len(x))
        return pipe

    ret = substream_step(async_iter, opus_substream)
    return ret


def _mp3_rate_limit_step(async_iter: AsyncIterator[bytes], buffer_seconds: float):
    def get_bytes_per_second(data):
        seconds = get_audio_length(AudioFormat.MP3, data)
        length_in_bytes = len(data)
        return int(length_in_bytes / seconds)

    def mp3_substream(async_iter: AsyncIterator[bytes]):
        pipe, bytes_per_second_f = extract_value_step(async_iter, get_bytes_per_second)
        chunk_size_f = map_future(
            bytes_per_second_f,
            lambda bytes_per_second: int(buffer_seconds * bytes_per_second / 2),
        )
        pipe = mp3_chunk_step(pipe, chunk_size_f)
        pipe = raw_audio_rate_limit_step(
            pipe, bytes_per_second_f, buffer_seconds=buffer_seconds
        )
        return pipe

    ret = substream_step(async_iter, mp3_substream)
    return ret


async def raw_audio_rate_limit_step(
    async_iter: AsyncIterator[bytes],
    bytes_per_second: FutureOrObj[int],
    buffer_seconds: FutureOrObj[float],
) -> AsyncIterator[bytes]:
    """Limits the rate of sending audio bytes down the pipe.  Note that this step always sends a full chunk.
    buffer_seconds is the number of seconds of audio left before we send the next chunk.  Usually, you will want to put
    a max size chunk step in before this.  buffer_seconds should be large enough to make sure the send executes.
    """
    last_send = time.perf_counter()
    queued_audio_seconds = 0

    def compute_remaining(now):
        # Compute the amount of audio remaining to be played in seconds.
        return max(0, queued_audio_seconds - (now - last_send))

    async for item in async_iter:
        resolved_buffer_seconds = await resolve_obj_or_future(buffer_seconds)
        now = time.perf_counter()
        # Compute the amount of audio remaining to be played in seconds.
        remaining_audio_seconds = compute_remaining(now)
        # If we have more than the buffer, sleep until we hit the buffer limit
        if remaining_audio_seconds > resolved_buffer_seconds:
            await asyncio.sleep(remaining_audio_seconds - resolved_buffer_seconds)
            # We don't know how long we actually slept.
            now = time.perf_counter()
            remaining_audio_seconds = compute_remaining(now)
        resolved_bytes_per_second = await resolve_obj_or_future(bytes_per_second)
        queued_audio_seconds = (
            remaining_audio_seconds + len(item) / resolved_bytes_per_second
        )
        last_send = now
        yield item


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

    async for timed_text in async_iter:
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
    async for item in async_iter:
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
