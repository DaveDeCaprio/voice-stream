# LLM Testing App

This app can be used for testing apps in development.

Allows a single LangChain to be tested using text chat, browser based audio, or telephony.

Records incoming audio to a logs directory.

## Setup

### Python Setup

The recommended way to run this example is to set up a virtual environment and install your dependencies there.

1. Create your virtualenv `python -v venv .venv`
2. Run `source .venv/bin/activate`
3. Run `pip install -r requirements.txt`

### Set up Google APIs and Credentials 

You will need to set up Google credentials and APIs to use the server.  See the [quickstart](https://voice-stream.readthedocs.io/en/latest/getting_started/index.html).
If you have already done the quickstart, copy your `google_cred.json` file to this example directory.

Because this example uses Vertex, it also needs a GOOGLE_API_KEY, which you can get from <https://console.cloud.google.com/apis/credentials>

### Create an .env file with your account details.

1. Rename the `.env.example` file to `.env`
2. Add your `OPENAI_API_KEY` to the file
3. Add your Google project information to the file.

All of these variables will be read in as environment variables on startup using `load_dotenv`

### Set up Google recognizer

This example uses the Google Speech V2 API.  To get this to work you will need
to set up a V2 recognizer in your account.  After you set up your `.env` file with a project id, 
you can create the recognizer using the provided script.

```python setup_recognizer.py```

## Run the server

Run the app with:

```uvicorn main:app --reload```

Point your browser to: http: and you should see:

![browser.png](./browser.png)

