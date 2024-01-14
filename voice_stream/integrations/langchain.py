from __future__ import annotations

from typing import AsyncIterator, Callable, Any, Optional

import asyncstdlib
from langchain_core.runnables import Runnable

from voice_stream.core import (
    fork_step,
    Output,
)
from voice_stream.speech_to_text import (
    filter_spurious_speech_start_events_step,
    SpeechStep,
)
from voice_stream.substreams import cancelable_substream_step
from voice_stream.text_to_speech import (
    TextToSpeechStep,
    tts_with_buffer_and_rate_limit_step,
)
from voice_stream.types import Input, SourceConvertable, to_source

GenericStepFunc = Callable[[AsyncIterator[Any]], AsyncIterator[Any]]


class LangchainVoiceFlow:
    def __init__(
        self,
        text_input: AsyncIterator[str],
        text_output: AsyncIterator[str],
        audio_output: AsyncIterator[bytes],
    ):
        self.text_input = text_input
        self.text_output = text_output
        self.audio_output = audio_output

    @classmethod
    def create(
        cls,
        audio_input: AsyncIterator[bytes],
        speech_step: SpeechStep,
        chain: Runnable,
        tts_step: TextToSpeechStep,
        langchain_postprocess: Optional[GenericStepFunc] = None,
    ) -> LangchainVoiceFlow:
        stream, speech_start = speech_step(audio_input)
        speech_start = filter_spurious_speech_start_events_step(speech_start)
        stream, text_input = fork_step(stream)

        def create_output_chain(
            stream: AsyncIterator[str],
        ) -> (AsyncIterator[bytes], AsyncIterator[str]):
            stream = langchain_step(stream, chain, on_completion="")
            if langchain_postprocess:
                stream = langchain_postprocess(stream)
            # stream = log_step(stream, "Token")
            return tts_with_buffer_and_rate_limit_step(stream, tts_step)

        stream, text_output = cancelable_substream_step(
            stream, speech_start, create_output_chain
        )
        return cls(
            text_input=text_input,
            text_output=text_output,
            audio_output=stream,
        )


async def langchain_step(
    async_iter: AsyncIterator[str],
    chain: Runnable[Input, Output],
    input_key: Optional[str] = None,
    config_key: Optional[str] = None,
    on_completion: SourceConvertable = None,
) -> AsyncIterator[Output]:
    """Runs a chain for each text item sent in, streams back response tokens."""
    # Note on cancelling - https://github.com/langchain-ai/langchain/issues/11959
    async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
        async for text in owned_aiter:
            input = text[input_key] if input_key else text
            config = text[config_key] if config_key else None
            async for token in chain.astream(input, config=config):
                yield token
            source = to_source(on_completion)
            async with asyncstdlib.scoped_iter(source) as owned_source:
                async for item in owned_source:
                    yield item
