# Cookbook

The cookbook provides worked examples to show how to accomplish various tasks with VoiceStream.  

* *[Browser Text and Audio](./browser)* - Enhances the quickstart to display a transcript of the conversation in the browser. 
* *[Browser Audio Javascript](./browser_client)* - Explains the `startAudio` and `stopAudio` functions for handling 2-way audio in the browser.
* *[Phone](./phone)* - Demonstrates using Twilio to automate voice calls powered by LLMs.
* *[Desktop](./desktop)* - Uses PyAudio to use your computer's local audio.
* *[Interruptions](./interruptions)* - Handling interruptions - when the speaker talks before the LLM is finished responding.
* *[Recording](./recording)* - Record incoming audio while also running a LangChain LLM.
* *[Tips](./tips)* - General guidelines for creating good voice applications.

The [examples directory](https://github.com/DaveDeCaprio/voice-stream/blob/main/examples) of the VoiceStream repo contains
even more detailed examples of larger applications. 

```{toctree}
:hidden:

browser
browser_client
phone
desktop
recording
interruptions
tips
```
