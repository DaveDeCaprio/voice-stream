# Voicemail Detection

When making automated phone calls, it's useful to know if you got an answering machine or an actual person.  Twilio's 
API has pretty good detection built in, and in this example we'll show how to use that.

Examples here are take from the [llm_testing_app example](https://github.com/DaveDeCaprio/voice-stream/blob/main/examples/llm_testing_app/main.py) in the GitHub repo.

## Initiating Voicemail Detection

Twilio call this "Answering machine detection".  I don't think anyone has an answering machine anymore, but whatever.

Lines 8 through 10 show the detection parameters.

```{code-block} python
:linenos:
:emphasize-lines: 8-10

@app.route("/call/<path:endpoint>", methods=["GET"])
async def outbound_call(endpoint):
    phone_number = request.args.get("phone")
    call_instance = await current_app.twilio_client.calls.create_async(
        from_=app.config["TWILIO_PHONE_NUMBER"],
        to=phone_number,
        url=f"https://{current_app.domain}/twiml/{endpoint}",
        async_amd=True,
        machine_detection="DetectMessageEnd",
        async_amd_status_callback=f"https://{current_app.domain}/machine_detect",
    )
    logger.info(f"Initiating outbound call. SID: {call_instance.sid}")
    current_app.current_calls[call_instance.sid] = CallQueues()
    return {"callSid": call_instance.sid}
```

In a voice app, we generally want asynchronous detection, so when the call connects we will immediately get the audio
and start processing.  The detection happens in the background and we will get notified if an answering machine is
detected.

Setting `machine_detection` to `DetectMessageEnd` tells Twilio to call the webhook when the voicemail greeting has completed, so if you want to 
play a canned message, you can start with that immediately.

The final parameter `async_amd_status_callback` sets the webhook that Twilio will call when the detection is done.  It will always hit this endpoint, giving you
a response of 'human', 'amd', or 'unknown'.  

## Implementing the Detection WebHook

In this case, we just convert the detection into a message and put it on the inbound queue for that call.  

```{code-block} python
:linenos:
:emphasize-lines: 8-11

@app.route("/machine_detect", methods=["POST"])
async def machine_detect_webhook():
    form = await request.form
    event = form_data_to_dict(form)
    call_id = event["CallSid"]
    event = AnsweringMachineDetection(
        call_id=call_id,
        answered_by=event["AnsweredBy"],
        time_since_start=float(event["MachineDetectionDuration"]) / 1000,
    )
    call = current_app.current_calls.get(call_id, None)
    if call:
        await call.inbound.put(event)
    return "Ok"
```

This queue can be merged with other Twilio events in the call handler so you can process the call however you want.

```{code-block} python
:linenos:
:emphasize-lines: 14-15

@app.websocket("/ws")
async def handle_call_audio():
    stream = quart_websocket_source()
    stream = map_str_to_json_step(stream)
    stream = filter_step(stream, lambda x: x["event"] != "connected")
    stream = twilio_check_sequence_step(stream)
    
    # Extract the callSid and use that to find the right queue.
    stream, call_sid_f = extract_value_step(
        stream, value=lambda x: x["start"]["callSid"]
    )
    inbound_queue_f = map_future(call_sid_f, lambda x: current_app.current_calls[x].inbound)    
    
    vm_detection_source = queue_source(inbound_queue_f)
    stream = merge_step(stream, vm_detection_source)

    # From here the AnsweringMachineDetection event will be in the stream just like CallStarted and CallEnded events.
    # ...
```
