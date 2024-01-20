import logging
import time

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from examples.gpt_gemini_showdown.gpt4_gemini_panel import (
    gemini_chain,
    PanelDiscussionPromptTemplate,
    PanelModels,
)

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logger.debug("Start")


load_dotenv()

system_prompt = """We are making an entertaining podcast which simulates a panel discussion between you and
    OpenAI's GPT-4 model.   

     The queries you receive will be the output of speech recognition, and your responses will
     be turned into speech using text-to-speech.  Keep your responses short to avoid boring the listener, and
     don't use any special formatting that won't translate well as text to speech.
     Your tone should be witty and fun in a casual conversational tone,
     but with an underlying current of competitiveness.

    """
chat = PanelDiscussionPromptTemplate(
    system_prompt=system_prompt,
    panel_model=PanelModels.Gemini,
    use_system_prompt=False,
)
chat = gemini_chain()

input = {
    "history": [],
    "query": "Write me a song about goldfish on the moon",
}
# start = time.perf_counter()
# stop = None
# for chunk in chat.stream(input):
#     if not stop:
#         stop = time.perf_counter()
#     print(chunk, end="", flush=True)
#     break
# print(f"\nTime: {stop-start}")


# chat = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0.9, top_p=1.0, n=1)
# start = time.perf_counter()
# stop = None
# for chunk in chat.stream(input["query"]):
#     if not stop:
#         stop = time.perf_counter()
#     print(chunk.content, end="", flush=True)
#     break
#
# print(f"\nTime: {stop-start}")
