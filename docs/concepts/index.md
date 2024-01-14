# Concepts

## Streaming 

As its name implies, VoiceStream is designed to be a streaming framework.  The streaming abstraction eliminates much
of the complexity of Python coding required to build voice applications.  Streaming is a natural fit for voice.

Using streaming, you set up a data flow that describes how you want your data to be processed, and then the framework
handles the actual execution of the data flow.  In a typical voicebot, the steps in the data flow might look like:
* Receive incoming audio, through some channel
* Have that audio transcribed into text
* Have that text run through an LLM or a chain of LLMs to produce text output.
* Have that text output converted to audio
* Send that audio back to the user

The code to implement this in VoiceStream maps very closely to the process described above: 

```
    stream = fastapi_websocket_bytes_source(websocket)
    stream = google_speech_v1_step(
        stream,
        speech_async_client,
        audio_format=AudioFormat.WEBM_OPUS,
    )
    stream = langchain_step(stream, chain)
    stream = google_text_to_speech_step(
        stream, text_to_speech_async_client, audio_format=AudioFormat.MP3
    )
    stream = map_step(stream, lambda x: x.audio)
    await fastapi_websocket_bytes_sink(stream, websocket)
```

Don't let the simplicity of this code fool you.  Under the hood, this creates a very performant pipeline for voicebot processing.
* Asyncio is used throughout so there is no blocking code.  That lets one thread efficiently process multiple streams.  
* Langchains's [async streaming Runnables](https://python.langchain.com/docs/expression_language/interface#async-stream) are used to minimize the time to first token.
* Asyncio resources are handling efficiently and everything is correctly cleaned up when the connection is closed.

Note - streaming as it is used here refers to the general concept of sending data continuously through a dataflow.  It is
not the same as [Python streams](https://docs.python.org/3/library/asyncio-stream.html).

### AsyncIterators

VoiceStream makes heavy use of [Python's AsyncIterator](https://peps.python.org/pep-0525/).  AsyncIterators connect the different steps in the data flow.

AsyncIterator are what are created when you use an async for loop.  For example, the following code creates an AsyncIterator that returns the numbers 1 through 10:

```
async def count_to_ten():
    async for i in range(1, 11):
        yield i
```        

Many of the steps implemented in VoiceStream use `async for` loops, although as a user, you generally don't need to worry about those details.
You can just assemble the components.

### Source, Sinks, & Steps

A data flow is made from 3 core components:
* Sources - These are the start of a data flow.  Sources all return one or more AsyncIterators.  A given data flow can have multiple sources.
* Steps - These process the data somehow.  Steps take one or more AsyncIterators as inputs and return one or more AsyncIterators as outputs.
* Sinks - These are the end of a data flow.  Sinks take one or more AsyncIterators as inputs.  They return an [Awaitable](https://docs.python.org/3/library/asyncio-task.html#awaitables) that completes when the iterator is exhausted.

In VoiceStream, you can tell which component is which by the function name.  Sources all end with '_source', steps with '_step', and sinks with '_sink'.

Here is a very simple flow that shows you how it works.  To help focus on the flow, this one doesn't deal with audio or voice or LLMs.  Those are really just different components.
This flow copies a text file, converting it to lowercase as it goes (don't worry, we'll get to voice in a minute):

```
    stream = text_file_source('test.txt')
    stream = map_step(stream, lambda x: x.lower())
    done = text_file_sink(stream, 'copy.txt')
    await done
```

### Dissecting a simple flow

Let's review the flow above in detail.

```
    stream = text_file_source('test.txt')
```

`text_file_source` is a source that reads lines form a text file.  It returns an AsyncIterator[str], where each item in 
the iterator is a line in the file.  We assign that to the variable `stream`.  By convention the default VoiceStream
variable name for a single stream in a data flow is `stream`.

`stream = map_step(stream, lambda x: x.lower())`

The `map_step` takes the AsyncIterator created by the text file source and applies a function to each item (each line in the text file).
In this case we use a lambda to convert the line to lower case.  The result is a new AsyncIterator the produces lowercase lines.
We reassign `stream` to this new iterator.  Again, this is the standard convention in VoiceStream.  The stream is updated as it is built.

`out = text_file_sink(stream, 'copy.txt')`

Finally, we use the `text_file_sink` to write the output to a file.  Since this is a sink, and doesn't return an AsyncIterator, we use a different variable.
You can't append a new step after the end of the sink.

`await out`

It's important to understand that up until this last line, nothing has actually happened.  We've been setting up the data flow, but not running it.
Data flows are only run once you await on their sinks.  Awaiting on this sink causes text_file_sink to start pulling from the AsyncIterator returned by the 
map_step.  This in turn causes the map_step to pull from the AsyncIterator returned by the text_file_source.  Only then does the file get opened, read, and copied.

*Data flows are pull-based*.  This means that data flows through when the sink pulls it, rather than when the source pulls it.  This property ends up being
very useful for rate-limiting and to avoid.  You can use buffers to simulate a push-based system.  We will show examples of that.

### Why all the fuss?

The code above may seem complicated for such a simple task.  Why not just write a simple for loop to read the file and write the output?

The streaming abstraction is very powerful.  It allows you to build complex data flows that can handle multiple inputs and outputs, and can be run in parallel.
It also allows you to build reusable components that can be used in multiple data flows.  For example, we send the output to a websocket just be changing the sink.
Finally, in cases where you are dealing with audio, the streaming abstraction allows you to process audio in real time, without having to wait for the entire file to be read. 

### Flow Control

The data flow above is very simple.  It is a linear flow, with one source, one step, and one sink.  In more complex flows, you may have multiple sources, steps, and sinks.

There are a variety of steps within VoiceStream to handle flow control:
* `fork_step` - Takes a single AsyncIterator and returns two.  All items are sent to both outputs.
* `partition_step` - Takes a single AsyncIterator and a condition and returns two AsyncIterators.  Items are sent to either the first or the second based on the condition.
* `merge_step` - Takes multiple AsyncIterators and returns one.  Items are sent to the output in the order they are received from the inputs. 
* `concat_step` - Takes multiple AsyncIterators and returns one.  The first iterator is consumed first, followed by the second, etc.

Here is an example flow that reads a text file and writes it to two different files, one with the even lines and one with the odd lines:

```
    stream = text_file_source('test.txt')
    even_stream, odd_stream = partition_step(stream, lambda x: x % 2 == 0)
    even_done = text_file_sink(even_stream, 'even.txt')
    odd_done = text_file_sink(odd_stream, 'odd.txt')
    await asyncio.gather(even_done, odd_done)
``` 
When running a data flow, you generally wait on all the sinks in the flow at once.  Running one sink without the other can cause the streamline to hang. 

