# Handling Interruptions

When moving from text chat to voice chat, one of the biggest differences is interruptions.  In a text chat an LLM can
be streaming out a response and the user can just go ahead and start typing their next response.  That doesn't work for
voice.  If the user starts talking, you need to detect that and stop the audio output so the LLM can hear what the user
has to say.  

You always want to track interruptions accurately in the conversation history.  If the LLM had planned to say two giant
paragraphs but the user interrupted after the first sentence, it's important to track what was actually said.  Otherwise,
the LLM will continue on thinking that it had said the full two paragraphs to the user.

VoiceStream has all the tools you need to handle interruptions cleanly.  We will walk through what that looks like here.

The code shown here is from the [gpt4_gemini_showdown example](https://github.com/DaveDeCaprio/voice-stream/blob/main/examples/gpt4_gemini_showdown/main.py) in the GitHub repo.
