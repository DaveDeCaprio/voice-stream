from __future__ import annotations

import logging
from enum import Enum
from operator import itemgetter
from typing import Any, Optional, List, Dict

from langchain.memory import ConversationBufferMemory
from langchain.output_parsers import EnumOutputParser
from langchain_openai import ChatOpenAI
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    BaseChatPromptTemplate,
)
from langchain_core.runnables import (
    RunnablePassthrough,
    RunnableLambda,
    RunnableParallel,
    RunnableBranch,
)
from langchain_google_genai import ChatGoogleGenerativeAI

from voice_stream.langchain_extensions.runnables import RunnableLogger

logger = logging.getLogger(__name__)


class PanelModels(Enum):
    GPT = "GPT"
    Gemini = "Gemini"


class RoutingOutputParser(EnumOutputParser):
    last_response: Optional[str]
    """The enum to parse. Its values must be strings."""

    def parse(self, response: str) -> Any:
        try:
            no_punc_response = response.replace(".", "").replace(",", "")
            ret = super().parse(no_punc_response)
            self.last_response = ret
            return ret
        except OutputParserException as e:
            if self.last_response:
                ret = self.last_response
            else:
                ret = PanelModels.GPT
            logger.warning(f"Failed to parse routing response, defaulting to {ret}", e)
            return ret


class RoutingPromptTemplate(BaseChatPromptTemplate):
    """Formats the recent history for use by the routing model."""

    ROUTING_SYSTEM_PROMPT = """You are being used as part of a simulated panel discussion with a moderator and two LLMs.  Your job
    is not to participate in the discussion, but just to decide which of the two LLMs should answer each question.
    
    The LLMs are GPT-4 (or ChatGPT) from OpenAI and Gemini from Google.
    If it's not obvious from context, just pick one of the two options randomly.
    
    The query will contain the recent conversation history of the conversation so far, your answer should be the logical model to speak next.  
    Your answer should be a single word, either "GPT" or "Gemini".
    
    Examples:
    Moderator: What's Gemini's opinion on that?
    Output: Gemini
    
    Moderator: What's Gemini's opinion on that?
    Gemini: I agree
    Moderator: What's OpenAI's view?
    Output: GPT
    
    Moderator: What do your creators at Google say?
    Output: Gemini
    """

    input_variables: List[str] = ["history", "query"]
    input_types: Dict[str, Any] = {"history": List[BaseMessage], "query": str}

    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        # Get the source code of the function
        history = kwargs["history"]
        query = kwargs["query"]

        recent_history = history[-4:] + [HumanMessage(content=query)]

        def format_message(message):
            if isinstance(message, HumanMessage):
                ret = f"Moderator: {message.content}"
            elif isinstance(message, AIMessage):
                ret = message.content
            else:
                raise ValueError(f"Unknown message type: {type(message)}")
            return ret

        prompt = "\n".join([format_message(_) for _ in recent_history])
        prompt += "\nOutput: "
        return [
            SystemMessage(content=self.ROUTING_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

    def _prompt_type(self):
        return "panel_history"


class PanelDiscussionPromptTemplate(BaseChatPromptTemplate):
    system_prompt: str
    panel_model: PanelModels
    use_system_prompt: bool = True

    input_variables: List[str] = ["history", "query"]
    input_types: Dict[str, Any] = {"history": List[BaseMessage], "query": str}

    def format_messages(self, **kwargs: Any) -> List[BaseMessage]:
        # Get the source code of the function
        conversation = kwargs["history"] + [HumanMessage(content=kwargs["query"])]

        if self.use_system_prompt:
            messages = [SystemMessage(content=self.system_prompt)]
            current_human_content = ""
        else:
            messages = []
            current_human_content = f"Instructions:\n{self.system_prompt}\n\n"

        # See - https://python.langchain.com/docs/integrations/chat/google_generative_ai
        # Gemini requires alternating human and AI messages and doesn't support system messages.
        for message in conversation:
            if isinstance(message, HumanMessage):
                current_human_content += f"Moderator: {message.content}\n"
            elif (
                isinstance(message, AIMessage)
                and message.content[: len(self.panel_model.value)]
                == self.panel_model.value
            ):
                # AI message from this model
                current_human_content += f"{self.panel_model.value}: "
                messages.append(HumanMessage(content=current_human_content))
                current_human_content = ""
                messages.append(
                    AIMessage(
                        content=message.content[len(self.panel_model.value) + 2 :]
                    )
                )
            elif isinstance(message, AIMessage):
                # AI message from another model
                current_human_content += f"{message.content}\n"
        current_human_content += f"{self.panel_model.value}: "
        messages.append(HumanMessage(content=current_human_content))
        return messages


def routing_chain():
    parser = RoutingOutputParser(enum=PanelModels)
    return RoutingPromptTemplate() | ChatOpenAI(model="gpt-3.5-turbo") | parser


def gpt4_chain():
    system_prompt = """We are making an entertaining podcast which simulates a panel discussion between you and
    Google's Gemini model.  I've included some background on Gemini, which is an LLM model design to compete directly
    with GPT_4.

    Background on Gemini:
    Google's Project Gemini, announced at the Google I/O developer conference in May 2023, represents a significant advancement in the field of artificial intelligence (AI). This project is a collaboration between Google's Brain Team and DeepMind, known for creating AlphaGo. Gemini is an ambitious effort by Google to develop a next-generation AI system, aiming to compete with OpenAI's ChatGPT.

Gemini is designed to be a multimodal system, which means it is capable of processing and understanding various types of data, including text, images, audio, and video. It's built to be highly efficient in tool and API integrations and is geared towards supporting future innovations, such as memory and planning. The foundation of Gemini lies in PaLM 2, a new language model with enhanced multilingual, reasoning, and coding capabilities.

A key aspect of Gemini is its performance on various benchmarks, where it surpasses state-of-the-art models like GPT-4 in areas such as text, coding, and multimodal tasks. For instance, Gemini has demonstrated its proficiency in MMLU (Massive Multitask Language Understanding), Big-Bench Hard, and HumanEval, among others. Additionally, it shows superior performance in multimodal benchmarks like image understanding, document understanding, and automatic speech translation.

Gemini comes in three sizes: Ultra, Pro, and Nano, each tailored for different levels of complexity and efficiency. Ultra is the largest model designed for highly complex tasks, Pro is best for a wide range of tasks, and Nano is the most efficient for on-device tasks.

Google's commitment to Project Gemini can be seen in its significant investment and the involvement of its co-founders, Larry Page and Sergey Brin, who were reportedly coaxed out of retirement to contribute to this project. This effort is partly driven by the competitive landscape in AI, particularly in response to the rapid growth and popularity of ChatGPT.

In summary, Google's Project Gemini is a groundbreaking development in AI, representing a fusion of cutting-edge language and multimodal capabilities. Its potential impact on Google’s products and services is substantial, and it positions Google as a key player in the rapidly evolving AI landscape
    End of background on Gemini
    
    The queries you receive will be the output of speech recognition, and your responses will
     be turned into speech using text-to-speech.  Keep your responses to a paragraph or so to avoid boring the listener, and
     don't use any special formatting that won't translate well as text to speech.
     Your tone should be witty and fun in a casual conversational tone,
     but with an underlying current of competitiveness.
"""
    prompt = PanelDiscussionPromptTemplate(
        system_prompt=system_prompt, panel_model=PanelModels.GPT
    )
    return prompt | ChatOpenAI(model="gpt-4") | StrOutputParser()


def gemini_chain():
    system_prompt = """We are making an entertaining podcast which simulates a panel discussion between you and
    OpenAI's GPT-4 model.   

     The queries you receive will be the output of speech recognition, and your responses will
     be turned into speech using text-to-speech.  Keep your responses to a paragraph or so to avoid boring the listener, and
     don't use any special formatting that won't translate well as text to speech.
     Your tone should be witty and fun in a casual conversational tone,
     but with an underlying current of competitiveness.
     
     If you understand these instructions, reply with 'ok'
    """
    prompt = PanelDiscussionPromptTemplate(
        system_prompt=system_prompt,
        panel_model=PanelModels.Gemini,
        use_system_prompt=False,
    )
    return prompt | ChatGoogleGenerativeAI(model="gemini-pro") | StrOutputParser()


def full_discussion_chain():
    def default_branch():
        raise ValueError("No branch matched")
        yield "default"

    return (
        RunnablePassthrough.assign(model=routing_chain())
        # | RunnableLogger("LLM Input")
        | RunnablePassthrough.assign(
            # RunnableLambda doesn't work here because it breaks streaming.
            output=RunnableBranch(
                (lambda x: x["model"] == PanelModels.GPT, gpt4_chain()),
                (lambda x: x["model"] == PanelModels.Gemini, gemini_chain()),
                default_branch,
            )
        )
    )
