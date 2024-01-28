"""
Use this script to create the Google Speech V2 recognizer in your account.

Your .env file should be set up with appropriate values.
"""

import asyncio
import logging
import os

from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechAsyncClient
from dotenv import load_dotenv

from voice_stream.integrations.google_utils import create_recognizer


async def main():
    print(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    speech_async_client = SpeechAsyncClient(
        client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
    )
    return await create_recognizer(
        speech_async_client,
        os.environ["GCP_PROJECT_ID"],
        os.environ["GCP_SPEECH_LOCATION"],
        os.environ["GCP_BROWSER_SPEECH_RECOGNIZER"],
        model="latest_long",
        language_codes=["en-US", "es-US"],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    load_dotenv()
    asyncio.run(main())
