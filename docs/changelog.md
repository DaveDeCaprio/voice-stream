# Change Log

## 0.10.0 (Jan 29, 2024)

* Added `PydanticV2OutputParser` parser and chain which runs a conversation where the goal is to fill in a pydantic object.
* Fixed bug where `ignore_none` in `map_step` was ignoring any falsy value (like '' and 0). Fixed so it only ignores 'None'.
* Added new example: FastAPI llm test app without telephony 

## 0.9.0 (Jan 25, 2024)

* Rewrote `google_speech_step` to allow streaming for longer than 5 minutes.
* Added `background_task` which logs exceptions in all background tasks for better observability.
* Added `abort_step`
* Added optional `cancel_event` to `queue_source`
* Add `every_nth_message` parameter to log step
* Fixed some bugs in `async_init_step` where exceptions would cause hangs.
* google_speech_step now requires an audioFormat.  Required to split audio when exceeding 5 minutes of streaming.
* Added `recover_exception_substream`

## 0.8.0 (Jan 17, 2024)

* Added LangChain memory steps
* Added speaking rate to Google TTS step.
* Added worked examples for llm_test_app and gemini_gpt4_showdown
* Added Cookbooks for Interruptions and Phone Use Cases

## 0.7.0 (Jan 15, 2024)

* Updated all docs and docstrings

## 0.6.0 (Jan 10, 2024)

* Reorganized package structure
* Updated naming conventions for examples

## 0.5.0 (Jan 9, 2024)

* Added langchain extensions

## 0.4.0 (Jan 9, 2024)

* Finished Quickstart

