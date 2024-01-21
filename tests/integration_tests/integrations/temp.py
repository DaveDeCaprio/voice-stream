import asyncio
import json
import logging
import logging.config
import os
from pathlib import Path
import atexit
from dotenv import load_dotenv

from tests.integration_tests.integrations.test_google import (
    test_google_speech_exception,
)

load_dotenv()
if "GOOGLE_APPLICATION_CREDENTIALS_JSON" in os.environ:
    import tempfile

    env = os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"]
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        # If the value isn't JSON, assume it is base64 encoded.
        # Github actions recommend against using JSON direct in secrets.
        # https://docs.github.com/en/actions/reference/encrypted-secrets#limits-for-secrets
        if not env.startswith("{"):
            import base64

            creds = base64.b64decode(env).decode()
        else:
            creds = env
        f.write(creds)
        f.flush()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name
        atexit.register(os.remove, f.name)

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s - %(message)s"
)

asyncio.run(test_google_speech_exception())
