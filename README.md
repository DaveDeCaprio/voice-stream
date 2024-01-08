# voice-stream: Creating voice bots from LLMs.

![PyPI](https://img.shields.io/pypi/v/voice-stream)
[![Tests](https://github.com/DaveDeCaprio/voice-stream/actions/workflows/tests.yaml/badge.svg)](https://github.com/DaveDeCaprio/voice-stream/actions/workflows/tests.yaml)
[![Documentation Status](https://readthedocs.org/projects/voice-stream/badge/?version=latest)](https://voice-stream.readthedocs.io/en/latest/?badge=latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python Versions](https://img.shields.io/pypi/pyversions/voice-stream)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org/)

<!-- start elevator-pitch -->

VoiceStream is a framework for building voice bots using language models.  

   * Integrates with LangChain so you can take any LLM application.
   * Makes it easy to use different TTS and Speech Recognition models
   * Uses asyncio and streaming throughout to provide a great user experience.
   * Handles voice specific conversation flows, like interrupting the current speaker.

<!-- end elevator-pitch -->

<!-- start install -->

## Quick Install

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

VoiceStream is distributed on [PyPI].  To install, run:

## Contributing

VoiceStream is a volunteer maintained open source project, and we welcome contributions of all forms. Please take a look at our [Contributing Guide](https://voice-stream.readthedocs.io/en/latest/contributing/index.html) for more information.

<!-- start license -->
## License

This project is licensed under the [**MIT License**](https://choosealicense.com/licenses/mit/).
<!-- end license -->
