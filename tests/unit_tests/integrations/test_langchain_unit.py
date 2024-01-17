import pytest
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage

from voice_stream.core import single_source, map_step, fork_step, array_sink, empty_sink
from voice_stream.integrations.langchain import (
    langchain_load_memory_step,
    langchain_save_memory_step,
)


@pytest.mark.asyncio
async def test_langchain_load_memory_step():
    memory = ConversationBufferMemory(return_messages=True)
    stream = single_source({"query": "My name is Dave"})
    stream = langchain_load_memory_step(stream, memory)
    ret = await array_sink(stream)
    assert ret == [{"history": [], "query": "My name is Dave"}]

    stream = single_source({"query": "My name is Dave"})
    stream = map_step(
        stream, lambda x: {"input": x, "output": {"response": "Hi Dave!"}}
    )
    stream = langchain_save_memory_step(stream, memory)
    await empty_sink(stream)

    stream = single_source({"query": "What is my name?"})
    stream = langchain_load_memory_step(stream, memory)
    ret = await array_sink(stream)
    assert ret == [
        {
            "history": [
                HumanMessage(content="My name is Dave"),
                AIMessage(content="Hi Dave!"),
            ],
            "query": "What is my name?",
        }
    ]
