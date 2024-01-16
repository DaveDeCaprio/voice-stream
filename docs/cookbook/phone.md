# Phone

Follow the instructions below from the [GitHub example](https://github.com/DaveDeCaprio/voice-stream/tree/main/examples/twilio) directory.

```{include} ../../examples/twilio/README.md
:start-after: "# Twilio Demo"
:end-before: "## Walkthrough"
```

## Walkthrough

### Initiating the call

The HTML is fairly straightforward.  It simply displays a web page that lets 
you input a phone number and has a button to make a call to the server to initiate the call.

The handler on the server side just calls the Twilio API to initiate the call.  Twilio takes
a webhook URL to the TWiML script that describes what to do on the call.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Initiate Call"
:end-before: "# TWiML Webhook"
```

### TWiML

When Twilio receives the API call and makes the call, it posts to the `/twiml` endpoint to decide how 
to handle it.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# TWiML Webhook"
:end-before: "# Handle Audio"
```

The TWiML for this call is very simple, we just use a `<Connect\>` element to send the audio stream to
our websocket URL. 

### Audio URL

When Twilio receives the API call and makes the call, it posts to the `/twiml` endpoint to decide how 

We will break down the VoiceStream data flow.

First, we set up the websocket to receive JSON messages from Twilio.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Handle Audio"
:lines: 1-4
```

### Initial message handling

Next we filter out the 'connected' message since that doesn't tell us anything.  Then we check
the sequence numbers as a verification that the stream is valid.  Then we use an
:func:`~voice_stream.extract_value_step` to extract the Twilio `streamSid` from the first message.  
We will need this later to format the output audio messages.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Handle Audio"
:lines: 4-9
```

### Separating Audio from Call Events

We then separate the call events, like "call started" and "call ended" from the audio messages
using a partition step.  We deal with the event stream later.  For now, we continue to process
the audio stream by converting from twilio media JSON messages to bytes.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Handle Audio"
:lines: 10-11
```

### Running LangChain

Once we have a stream of audio bytes, we use the same flow from the quickstart to 
generate the LLM response and convert it to audio.  In this case we use a `telephony`
recognizer and use an :class:`~voice_stream.audio.AudioFormat` of `WAV_MULAW_8KHZ`.  This
is what Twilio expects.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Handle Audio"
:lines: 12-30
```

### Audio Output

Finally, we take the output audio, convert it into Twilio media messages and send
out of the websocket.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Handle Audio"
:lines: 31-32
```

### Handling the `stop` event

We then handle the event stream.  With that, all we do is watch for a stop message
and use that to close the stream.  We then wait on the two streams.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Handle Audio"
:lines: 33-41
```

### Full Call Handler

Here is the full code for the call handler, all together.

```{literalinclude} ../../examples/twilio/main.py
:language: python
:start-after: "# Handle Audio"
```



