import pytest

from tests.helpers import example_file
from voice_stream import (
    text_file_source,
    map_str_to_json_step,
    filter_step,
    array_sink,
)
from voice_stream.integrations.twilio import (
    twilio_check_sequence_step,
    twilio_split_media_step,
)


@pytest.mark.asyncio
async def test_twilio_sequence_correct():
    pipe = text_file_source(example_file("echo.ndjson"))
    pipe = map_str_to_json_step(pipe)
    pipe = twilio_check_sequence_step(pipe)
    result = await array_sink(pipe)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_twilio_sequence_incorrect():
    pipe = text_file_source(example_file("echo.ndjson"))
    pipe = map_str_to_json_step(pipe)
    pipe = filter_step(pipe, lambda x: x["sequenceNumber"] != 2)
    pipe = twilio_check_sequence_step(pipe)
    with pytest.raises(ValueError):
        await array_sink(pipe)


@pytest.mark.asyncio
async def test_twilio_media():
    pipe = text_file_source(example_file("echo.ndjson"))
    pipe = map_str_to_json_step(pipe)
    media, control = twilio_split_media_step(pipe)
    media = await array_sink(media)
    control = await array_sink(control)
    assert media == [
        {"event": "media", "sequenceNumber": 2},
        {"event": "media", "sequenceNumber": 3},
    ]
    assert control == [
        {"event": "start", "sequenceNumber": 1, "data": {"id": 1, "name": "test"}}
    ]
