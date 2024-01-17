"""
The `LangChain <https://www.langchain.com/>`_ is a framework for building LLM based applications.  VoiceStream allows
any LangChain runnable to be used to power a voice application.
"""
from __future__ import annotations

from typing import AsyncIterator, Callable, Any, Optional, Dict

import asyncstdlib
from langchain_core.memory import BaseMemory
from langchain_core.runnables import Runnable

from voice_stream.core import (
    fork_step,
    Output,
    map_step,
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


async def langchain_step(
    async_iter: AsyncIterator[Input],
    chain: Runnable[Input, Output],
    input_key: Optional[str] = None,
    config_key: Optional[str] = None,
    on_completion: SourceConvertable = None,
) -> AsyncIterator[Output]:
    """
    Data flow step that passes each input item to a LangChain runnable and streams the output.

    This step is used to call LLMs or run any other LangChain runnable.  It receives text
    items, processes them through a specified 'chain', and yields the resulting output
    tokens asynchronously.  If `input_key` is not specified, the input will be directly passed to the runnable.
    If `input_key` is specified, then the items coming from the source iterator must be dictionaries, and the `input_key`
    specifies which item should be passed as input to the runnable.  The `config_key` can also be used to pass configuration
    to the Runnable.

    Parameters
    ----------
    async_iter : AsyncIterator[str]
        An asynchronous iterator that provides input text items.
    chain : Runnable[Input, Output]
        A Langchain Runnable that processes each input item.
    input_key : Optional[str], optional
        If specified, the item from the incoming dictionary that should be used as the input to the Runnable.
        If empty, then the incoming item will be passed directly.
    config_key : Optional[str], optional
        If specified, the item from the incoming dictionary that should be used as the config argument to the Runnable.
        Can only be specified if input_key is specified.
    on_completion : SourceConvertable, optional
        An optional source to be converted and iterated upon completion of processing each text item.  Can be used to
        signal the end of output if that isn't clear form the output of the chain itself.

    Returns
    ------=
    AsyncIterator[Output]
        An asynchronous iterator yielding the output from the LangChain Runnable.

    """
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


def langchain_load_memory_step(
    async_iter: AsyncIterator[Dict],
    memory: BaseMemory,
) -> AsyncIterator[Dict]:
    """
    Data flow step that adds variables from LangChain memory into a dictionary.

    This step is used to insert variables from the memory into the current flow.  It expects a dictionary as input and
    returns a dictionary as output.  Used to prepare input for a langchain_step.

    Parameters
    ----------
    async_iter : AsyncIterator[str]
        An asynchronous iterator that provides dictionaries.
    memory : BaseMemory
        A Langchain BaseMemory that contains the variables to insert

    Returns
    ------
    AsyncIterator[Dic]
        An asynchronous iterator yielding dictionaries with memory variables added.

    Notes
    -----
    - If the incoming dictionary contains any of the variables that are included in the history, they will override the
      values in the memory.
    """

    def load(x):
        m = memory.load_memory_variables(x)
        return {**m, **x}

    return map_step(async_iter, load)


def langchain_save_memory_step(
    async_iter: AsyncIterator[Dict],
    memory: BaseMemory,
    input_key="input",
    output_key="output",
) -> AsyncIterator[Dict]:
    """
    Data flow step that adds saves variables into LangChain memory.

    This step is used to save variables to memory into the current flow.  It expects a dictionary as input and
    returns the same dictionary as output.  It has a side effect of updating the memory.  Updating memory requires
    two dictionaries, one for input and one for output.  These are found by looking at the input_key and output_key
    values within the dictionary.

    Parameters
    ----------
    async_iter : AsyncIterator[str]
        An asynchronous iterator that provides dictionaries.
    memory : BaseMemory
        A Langchain BaseMemory to update
    input_key : str
        Key within the input dictionary whose value will be used as the `input` parameter to save_context.
    output_key : str
        Key within the input dictionary whose value will be used as the `output` parameter to save_context.

    Returns
    ------
    AsyncIterator[Dic]
        An asynchronous iterator that is a copy of the input iterator.
    """

    def save(x):
        memory.save_context(inputs=x[input_key], outputs=x[output_key])
        return x

    return map_step(async_iter, lambda x: save(x))
