# voice-stream: Creating voice bots from LLMs.

![PyPI](https://img.shields.io/pypi/v/voice-stream)
[![Tests](https://github.com/DaveDeCaprio/voice-stream/actions/workflows/tests.yml/badge.svg)](https://github.com/DaveDeCaprio/voice-stream/actions/workflows/tests.yml)
[![Documentation Status](https://readthedocs.org/projects/voice-stream/badge/?version=latest)](https://voice-stream.readthedocs.io/en/latest/?badge=latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python Versions](https://img.shields.io/pypi/pyversions/voice-stream)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org/)

## Quick Install

<!-- start install -->
VoiceStream is distributed on [PyPI].  To install, run:

   ```text
   pip install voice-stream
   ```

This will install the bare minimum requirements of VoiceStream.
A lot of the value of VoiceStream comes when integrating it with different audio sources, speech recognition and
text to speech systems.  By default, the dependencies needed to do that are NOT installed. You will need to install 
the dependencies for specific integrations separately.

[pypi]: https://pypi.org/project/voice-stream/
<!-- end install -->

## 🤔 What is VoiceStream

<!-- start elevator-pitch -->

VoiceStream is a framework for building voicebots using language models.

* Integrates with LangChain so you can take any LLM application.
* Makes it easy to use different Text-To-Speech and Speech Recognition models
* Uses asyncio and streaming throughout to provide a great user experience.
* Handles voice specific conversation flows, like interrupting the current speaker.

VoiceStream is built to make it easy to build voice applications on top of LangChain, but 
can work with any LLM framework.

## 🧱 What can you build with VoiceStream?

* :robot: **VoiceBots** - Chatbots that you can talk and listen to instead of typing.
* :telephone_receiver: **Automated Telephone Calls** - Make automated phone calls powered by LLMs and rich-content
* :teacher: **Voice Assistants** - Build your own voice assistant that can do anything you want.

## 🚀 How does VoiceStream help?

The main value props of VoiceStream are:
1. **Components** - Modular and easy-to-use components for audio input/output, speech recognition, and text to speech.
1. **Streaming** - Audio programming can be tricky in Python.  VoiceStream provides simple streaming commands that make it easy to string together audio applications. 

<!-- end elevator-pitch -->

## 📖 Documentation

Please see [here](https://voice-stream.readthedocs.io/en/latest/) for full documentation, which includes:

<!-- start doc-highlights -->
From here, explore the rest of the documentation to learn more about VoiceStream.
* [Quickstart](https://voice-stream.readthedocs.io/en/latest/getting_started/index.html) - Build a fully functional voicebot in 15 minutes.
* [Concepts](https://voice-stream.readthedocs.io/en/latest/concepts/index.html) - A methodical intro to the concepts underlying VoiceStream.
* [Cookbook](https://voice-stream.readthedocs.io/en/latest/cookbook/index.html) - How to take advantage of the various capability of VoiceStream.
* [GitHub Examples](https://github.com/DaveDeCaprio/voice-stream/blob/main/examples) - To view and run the code for fully worked examples.
* [API Reference](https://voice-stream.readthedocs.io/en/latest/reference/index.html) - If you are into reading API docs directly.

<!-- end doc-highlights -->

## 💁 Contributing

VoiceStream is a volunteer maintained open source project, and we welcome contributions of all forms. Please take a look at our [Contributing Guide](https://voice-stream.readthedocs.io/en/latest/contributing/index.html) for more information.

<!-- start license -->
## :classical_building: License

This project is licensed under the [**MIT License**](https://choosealicense.com/licenses/mit/).
<!-- end license -->
