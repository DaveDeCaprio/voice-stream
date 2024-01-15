# Recording Audio

If you want to record the incoming audio for a conversation, you can just fork the audio stream and send it to a file. 
Recording the audio allows you to do quality control and also generate new test cases for unusual situations 

The block below updates the websocket endpoint from the [quickstart](../getting_started/index) to save the audio from each chat to a separate file.

```{code-block} python
:linenos:
:emphasize-lines: 4, 24, 26

    @app.websocket("/ws/audio")
    async def audio_websocket_endpoint(websocket: WebSocket, id: str):
        stream = fastapi_websocket_bytes_source(websocket)
        stream, audio_stream  = fork_step(stream)
        stream = google_speech_v1_step(
        stream,
        speech_async_client,
        audio_format=AudioFormat.WEBM_OPUS,
        )
        stream = log_step(stream, "Recognized speech")
        stream = map_step(stream, lambda x: {"query": x})
        stream = langchain_step(stream, chain, on_completion="")
        stream = recover_exception_step(
        stream,
        Exception,
        lambda x: "Google blocked the response.  Ending conversation.",
        )
        stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.MP3
        )
        stream = map_step(stream, lambda x: x.audio)
        done = fastapi_websocket_bytes_sink(stream, websocket)
        
        audio_done = binary_file_sink(audio_stream, f"call_logs/{id}.webm")
        
        await asyncio.gather(done, audio_done)
```

* In line 4, we fork the audio stream before it goes into the recognizer.  This will send copies of the data to both the recognizer and our file.
* In line 24, we send the forked audio to a file, with a name based on the id passed from the client.
* In line 26, we wait on both sinks.  It's always best to `await` all sinks in a data flow at once.  
