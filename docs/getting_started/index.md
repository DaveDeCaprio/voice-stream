# QuickStart

In this quickstart we'll build a fully functional voice bot that runs in a browser and allows you to have a two-way conversation with Google's Gemini model.

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

## Google Cloud Setup

In this QuickStart, we will use Google Cloud for the Gemini LLM, Speech Recognition, and Text-To-Speech.  

### Prerequisites
You'll need to set up a Google Cloud account and create a project.  You can do this for free and get free credits that will cover many hours of conversation.
[Getting Started with Google Cloud](https://console.cloud.google.com/getting-started)    

### Service Account Setup (GCP)

We'll create a service account with credentials to access the APIs.

1. Navigate to https://console.cloud.google.com/apis/credentials
2. Click on "+ CREATE CREDENTIALS" and select "Servie Account".
3. Fill in any value under "Service account name" and press "DONE".
4. You should see your new service account listed.  Click on it to go to the details.
5. Go to the "KEYS" tab, then click on "+ ADD KEY" and select "Create new key". 
6. Ensure the key type is JSON and click "CREATE".  This will download a JSON file with your credentials.
7. Save the JSON file in the same directory as this quickstart.

For the integration to function properly, it is necessary to create a Service Account in your agent’s GCP Project. See [this page](https://cloud.google.com/dialogflow/docs/quick/setup#sa-create) of the documentation for more details.

Follow the steps below to create a Service Account and set up the integration.

1. Go into the Dialogflow agent’s settings and click on the Project ID link to open its associated GCP Project.
2. Click on the navigation menu in the GCP console, hover over "IAM & admin", and click "Service accounts".
3. 

If deploying this integration outside of GCP, you may authenticate using a key file. Deploying on Cloud Run or Cloud Functions obviates this process.
1. Click on "+ Create Key" and download the resulting JSON key file.
2. Save the JSON key file in the desired platform subdirectory.
3. Set the GOOGLE_APPLICATION_CREDENTIALS environmental variable on the deployment environment to the absolute path of Service Account JSON key file. See [this guide](https://cloud.google.com/dialogflow/docs/quick/setup#auth) for details.

### Enable 


enable the Text-To-Speech API.  You can follow the instructions [here](https://cloud.google.com/text-to-speech/docs/quickstart-client-libraries) to setup your account and get a service account key.   
To use Google's Gemini model, you'll need to setup a Google Cloud account and enable the Text-To-Speech API.  You can follow the instructions [here](https://cloud.google.com/text-to-speech/docs/quickstart-client-libraries) to setup your account and get a service account key.




