# Walkthrough

In this section, we walk through the code in the [QuickStart example](./index) to see what's going on.

The first section of the code is all application infrastructure required to set up the UI and serve the page to the browser.  This is followed by the VoiceStream data flow.  

## Application Structure

### Imports

The quickstart begins with some standard import, which we will skip.  It then imports several names from the VoiceStream package: 

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 0 - "
:end-before: "# 1 - "
```

In this case, we import the core {py:func}`~voice_stream.map_step`, {py:func}`~voice_stream.log_step`, and {py:func}`~voice_stream.recover_exception_step` steps directly from voice_stream.  Most of the
core steps are there.  We also import the {py:class}`~voice_stream.AudioFormat` enum. Most of the core source and sink functions are imported directly from voice_stream.

Integrations with 3rd party components, such as Google Cloud, are in the integrations package.  Those are imported as 
`voice_stream.integrations.<provider>`.  We use this to import the {py:func}`~voice_stream.integrations.fastapi.fastapi_websocket_bytes_source`, 
and {py:func}`~voice_stream.integrations.fastapi.fastapi_websocket_bytes_sink` to send and receive data to and from the browser.

### Browser UI

The next sections contains the HTML code for the browser UI.  Because this is not hte focus of the quickstart, it's just 
a minimal page with 2 buttons that start and stop the audio stream.

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 1 - "
:end-before: "# 2 - "
```

`startAudio` takes the id of an HTML 'audio' element for playing the audio, and the path to WebSocket endpoint for the audio.
In this case, we route to `/ws/audio`, which will be used in our route down below.

You may notice that the HTML references a JavaScript file called `audio_ws.js`.  This is a small JavaScript library that
contains generic functions for sending and receiving audio data to and from WebSockets.  It's included as a separate file
to keep the overall code length short, but if you want to understand how that works, it's covered in the  [Cookbook - JS for Browser Audio](../cookbook/browser_client).

### Serve the UI

The next lines create the FastAPI server, and provide a route to serve the HTML page we just created.

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 2 - "
:end-before: "# 3 - "
```

## VoiceStream Data Flow

All the code above was really just there to set up the server and UI.  The actual VoiceBot is implemented at the bottom.

### Client setup

The next section initializes the Google speech and text-to-speech clients that we will use to convert the audio to and from text.
It also creates a basic LangChain runnable to run the Google LLM.  These will be used in the flow below.  

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 3 - "
:end-before: "# 4 - "
```

### Websocket Handler

The meat of the work is all done in the websocket handler.  This code is invoked when the browser makes a WebSocket connection
to `/ws/audio`.  It takes audio from the web socket, converts it to text using Google Speech Recognition, runs that text
through the LangChain LLM, and then converts the output text to speech, which is sent back via the WebSocket.

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
```

We'll walk through this code in more detail.  Let's go line by line.

#### Quickstart Code

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-3
:emphasize-lines: 3
```
First we set up the source using {py:func}`~voice_stream.integrations.fastapi.fastapi_websocket_bytes_source`.  This creates the stream and returns an AsyncIterator[bytes] which will contain the audio data.

#### Speech Recognition

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-8
:emphasize-lines: 4-8
```

Next, we send that audio data for speech recognition.  We use the {py:func}`~voice_stream.integrations.google.google_speech_v1_step` here because it requires less 
configuration than the standard {py:func}`~voice_stream.integrations.google.google_speech_step`.  *V1 and V2 here refer to the versions of the Google Speech API.*  With the V1 step, we need to explicitly set the audio format.  Here 
we set it to WEBM_OPUS, which is used by Chrome.  The V2 step can detect the audio format automatically, and is what you
should use in production applications.

The output of this step is an AsyncIterator[str] which contains the recognized speech.

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-9
:emphasize-lines: 9
```

The next step is a {py:func}`~voice_stream.log_step` which writes out the recognized speech to the console.  This makes it 
easy to watch and verify that the speech is understood correctly.

#### LangChain LLM

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-10
:emphasize-lines: 10
```

The LangChain we have created expects input in the form of a dictionary, but what's being passed down the stream right now is a string.  
We use a {py:func}`~voice_stream.map_step` to format the string into the dictionary format that the LangChain expects.

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-11
:emphasize-lines: 11
```

The {py:func}`~voice_stream.integrations.langchain.langchain_step` runs the chain we created above.  This step uses 
streaming mode by default, so it is capable of outputting a token at a time down the stream.  `ChatVertexAI` doesn't 
currently support this mode though, so that output will come out all at once.  This creates a longer delay between the 
end of you speaking and the start of the response.  In production applications, you wil probably want to use an LLM that
supports streaming tokens.

The output of this step is an AsyncIterator[str] with the response from the LLM. 

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-14
:emphasize-lines: 12-14
```

The {py:func}`~voice_stream.recover_exception_step` handles the case where for some reason the LLM blocks your response
and doesn't return a value.  In that case, an exception is thrown, which propagates down the stream the say way normal data does.
In this case, we recover from that exception by passing new text, which will tell the user about the error.

#### Text-to-Speech

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-17
:emphasize-lines: 15-17
```

We take the text from the LLM and pass it to a {py:func}`~voice_stream.integrations.google.google_text_to_speech_step`.
The output of this step is an AsyncIterator of {py:class}`~voice_stream.AudioWithText` objects.  In this application,
we only care about the audio, so we use a {py:func}`~voice_stream.map_step` to extract just the audio, as shown in 
the next block.

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:lines: 1-18
:emphasize-lines: 18
```

#### Sink

```{literalinclude} ../../examples/quickstart.py
:language: python
:start-after: "# 4 - "
:emphasize-lines: 19
```

Finally, the audio data is sent back to the browser for playback using an {py:func}`~voice_stream.integrations.fastapi.fastapi_websocket_bytes_sink`.

Note that on the last line we `await` the sink.  The sink will not actually complete until the websocket is closed.  Data
will keep flowing through the stream as long as it is open.  This allows us to have many rounds of recognizing speech and
returning responses all within the same flow.

## Where To Go Now

From here, you can go to the [Concepts](../concepts/index) section to learn more about the core streaming abstractions on which VoiceStream
is built, or jump right into the [Cookbook](../cookbook/index) or [GitHub Examples](https://github.com/DaveDeCaprio/voice-stream/blob/main/examples/quickstart.py) to see how to accomplish 
specific tasks with VoiceStream.








