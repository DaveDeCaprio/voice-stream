# QuickStart

In this quickstart we'll build a fully functional voice bot with a browser interface that allows you to have a two-way 
conversation with Google's Gemini model.

The server uses FastAPI to serve a web page with start and stop audio buttons.   

## Installation

```{include} ../README.md
:start-after: <!-- start install -->
:end-before: <!-- end install -->
```

To use integrations, you can install the packages directly, or use the 'extras' syntax to install them as part of voice-stream.
Run the command below to install the 'quickstart' extra dependencies.  This will install fastAPI and the Google Cloud python clients.

   ```text
   pip install voice-stream[quickstart]
   ```

Most other integrations can be installed in the same way, by replacing 'quickstart' with the name of the integration.

   ```text
   pip install voice-stream[twilio,openai]
   ```

## Quickstart Code

Here is the code for our server.  You can also find it in the [examples directory of the VoiceStream repo](https://github.com/DaveDeCaprio/voice-stream/blob/main/examples/quickstart.py).

```{include} ../examples/quickstart.py
```

Save this code as quickstart.py.  We'll walk through it, but for now you can run it using uvicorn.  Because the audio is
sent over websockets, you'll run it using uvicorn rather than a regular python interpreter.  Uvicorn will already be 
installed if you installed with `pip install voice-stream[quickstart]` above.

```text
uvicorn quickstart:app
````

You should see the following exception:
```google.auth.exceptions.DefaultCredentialsError: File google_creds.json was not found.```

We'll fix this in the next section.  To use the Google APIs, we'll need a credentials file. 

## Google Cloud Setup

In this QuickStart, we will use Google Cloud for the Gemini LLM, Speech Recognition, and Text-To-Speech.  

### Prerequisites
You'll need to set up a Google Cloud account and create a project.  You can do this for free and get free credits that will cover many hours of conversation.
[Getting Started with Google Cloud](https://console.cloud.google.com/getting-started)    

### Service Account Setup (GCP)

We'll create a service account with credentials to access the APIs.

1. Navigate to https://console.cloud.google.com/apis/credentials
2. Click on "+ CREATE CREDENTIALS" and select "Servie Account".
3. Fill in any value under "Service account name" and press "CREATE AND CONTINUE".
4. Under "Select a role", select "Basic > Owner" and press "CONTINUE"
5. Press "DONE".
4. You should see your new service account listed.  Click on it to go to the details.
5. Go to the "KEYS" tab, then click on "+ ADD KEY" and select "Create new key". 
6. Ensure the key type is JSON and click "CREATE".  This will download a JSON file with your credentials.
7. Save the JSON file as google_creds.json in the same directory as this quickstart.

Now if you try to run the quickstart again.
```text
`python quickstart.py
````
You should get another big exception.  If you scroll up, it should contain a message like this: 

```
    status = StatusCode.PERMISSION_DENIED
    details = "Vertex AI API has not been used in project XXXXXXXXX before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/aiplatform.googleapis.com/overview then retry. If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry."
```

This is because even though you have valid credentials, the individual APIs all need to be turned on for the project.  Let's fix that.


### Enable APIs 

To run the project, you'll need to enable 3 APIs for this project.  Go to the 3 links below, and click "Enable".  Check the dropdown at the top of the window to make sure you are in the correct project.

* **[Vertex AI](https://console.cloud.google.com/apis/library/aiplatform.googleapis.com)** - Enables the Gemini LLM
* **[Cloud Speech-to-Text API](https://console.cloud.google.com/apis/library/speech.googleapis.com)** - Enables speech recognition
* **[Cloud Text-to-Speech API](https://console.developers.google.com/apis/api/texttospeech.googleapis.com/overview)** - Enables text-to-speech




