import os
import atexit

from dotenv import load_dotenv

load_dotenv()

os.environ["PYTHONASYNCIODEBUG"] = "1"

# Handle google credentials.  If GOOGLE_APPLICATION_CREDENTIALS_JSON is set, write the contents to a temp file
# and set GOOGLE_APPLICATION_CREDENTIALS to that path.  If GOOGLE_APPLICATION_CREDENTIALS is already set,
# do nothing.
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
