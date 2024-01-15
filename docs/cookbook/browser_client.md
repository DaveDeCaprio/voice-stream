# Browser Audio JavaScript

Hooking up two-way audio to a web-browser is fairly straightforward.  This page provides `startAudio` and `stopAudio` 
functions that open a 2-way websocket connection to a server and stream audio in both directions.  All of the browser 
based examples make use of these functions.

## Importing

You can directly include and use these functions from within your JavaScript using:

    <script 
    src="https://cdn.jsdelivr.net/gh/DaveDeCaprio/voice-stream@main/examples/static/audio_ws.js">
    </script>

## Usage

To play audio, these functions make use of the HTML audio element.  You should have an element on your page, and pass the 
id of that element to the `startAudio` function.  `startAudio` also takes the WS endpoint to connect to.

Outgoing audio is handled through a MediaRecorder, which doesn't require any additional elements on your HTML page.

Here is a simple example from the [quickstart](../quickstart/walkthrough) demonstrating how these functions can be used in an HTML page.

    <button onclick="startAudio('audio-player', '/ws/audio')">Start Voice Chat</button>
    <button onclick="stopAudio()">Stop Voice Chat</button>
    <audio id="audio-player"></audio> 

## Source

```{literalinclude} ../../examples/static/audio_ws.js
:language: javascript
```

