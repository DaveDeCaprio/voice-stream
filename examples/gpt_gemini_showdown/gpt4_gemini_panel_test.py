import logging
from operator import itemgetter

import pytest
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI

from examples.gpt_gemini_showdown.gpt4_gemini_panel import (
    PanelModels,
    RoutingPromptTemplate,
    PanelDiscussionPromptTemplate,
    routing_chain,
    gpt4_chain,
    gemini_chain,
    full_discussion_chain,
)

logger = logging.getLogger(__name__)

example_panel_router_data = [
    (
        "Ok Gemini, let's start with you.  What are your advantages over GPT-4",
        PanelModels.Gemini,
    ),
    ("Do your creators at Google know about that?", PanelModels.Gemini),
    ("ChatGPT, would you like to add anything?", PanelModels.GPT),
]

example_simple_history = {
    "query": "Gemini, what do you think about that?",
    "history": [
        HumanMessage(content="Ready to start"),
        AIMessage(content="GPT: I'm ready"),
    ],
}


def test_routing_prompt():
    p = RoutingPromptTemplate()
    r = p.format_messages(**example_simple_history)
    assert r == [
        SystemMessage(content=RoutingPromptTemplate().ROUTING_SYSTEM_PROMPT),
        HumanMessage(
            content="""Moderator: Ready to start
GPT: I'm ready
Moderator: Gemini, what do you think about that?
Output: """
        ),
    ]


def test_gpt_prompt():
    p = PanelDiscussionPromptTemplate(
        system_prompt="system", panel_model=PanelModels.GPT
    )
    r = p.format_messages(**example_simple_history)
    assert r == [
        SystemMessage(content="system"),
        HumanMessage(content="Moderator: Ready to start\nGPT: "),
        AIMessage(content="""I'm ready"""),
        HumanMessage(content="Moderator: Gemini, what do you think about that?\nGPT: "),
    ]


def test_gemini_prompt():
    p = PanelDiscussionPromptTemplate(
        system_prompt="system", panel_model=PanelModels.Gemini, use_system_prompt=False
    )
    r = p.format_messages(**example_simple_history)
    assert r == [
        HumanMessage(
            content="Instructions:\nsystem\n\nModerator: Ready to start\nGPT: I'm ready\nModerator: Gemini, what do you think about that?\nGemini: "
        ),
    ]


@pytest.mark.parametrize("input, expected_output", example_panel_router_data)
def test_panel_router_chain(input, expected_output):
    chain = routing_chain()
    output = chain.invoke({"query": input, "history": []})
    assert output == expected_output


def test_gpt4_chain():
    chain = gpt4_chain()
    inputs = [
        "Ok Gemini, let's start with you.  What are your advantages over GPT-4",
        "Can you repeat that?",
    ]
    results = run_chain(chain, inputs)
    assert len(results) == 2


def test_gemini_simple():
    chain = gemini_chain()
    inputs = [
        "Ok Gemini, let's start with you.  What are your advantages over GPT-4",
        "Can you repeat that?",
    ]
    results = run_chain(chain, inputs)
    assert len(results) == 2
    logger.info(results)


def test_full_chain():
    chain = full_discussion_chain()
    inputs = [
        "Ok Gemini, let's start with you.  What are your advantages over GPT-4",
        "Can you repeat that?",
    ]
    # config = {"callbacks": [ConsoleCallbackHandler()]}
    config = {}
    results = [
        chain.invoke({"query": query, "history": []}, config=config) for query in inputs
    ]
    assert len(results) == 2
    logger.info("\n".join([str(_) for _ in results]))


def test_panel_chain_streaming():
    chain = full_discussion_chain()
    config = {}
    gpt4_input = {
        "query": "Ok GPT, let's start with you.  What are your advantages?",
        "history": [],
    }
    results = chain.stream(gpt4_input, config=config)
    for s in results:
        logger.info(s)


def run_chain(chain, input, verbose: bool = True):
    memory = ConversationBufferMemory(return_messages=True)
    memory_chain = (
        RunnablePassthrough.assign(
            history=RunnableLambda(memory.load_memory_variables) | itemgetter("history")
        )
        | chain
    )

    # Manage manually instead of using RunnableWithMessageHistory
    def invoke(query):
        assert len(query) > 1
        inputs = {"query": query}
        ret = memory_chain.invoke(inputs)
        memory.save_context(inputs, {"outputs": ret})
        return ret

    results = [invoke(query) for query in input]
    return results
