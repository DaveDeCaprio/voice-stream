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
    stream = text_file_source(example_file("echo.ndjson"))
    stream = map_str_to_json_step(stream)
    stream = twilio_check_sequence_step(stream)
    result = await array_sink(stream)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_twilio_sequence_incorrect():
    stream = text_file_source(example_file("echo.ndjson"))
    stream = map_str_to_json_step(stream)
    stream = filter_step(stream, lambda x: x["sequenceNumber"] != 2)
    stream = twilio_check_sequence_step(stream)
    with pytest.raises(ValueError):
        await array_sink(stream)


@pytest.mark.asyncio
async def test_twilio_media():
    stream = text_file_source(example_file("echo.ndjson"))
    stream = map_str_to_json_step(stream)
    media, control = twilio_split_media_step(stream)
    media = await array_sink(media)
    control = await array_sink(control)
    assert media == [
        {"event": "media", "sequenceNumber": 2},
        {"event": "media", "sequenceNumber": 3},
    ]
    assert control == [
        {"event": "start", "sequenceNumber": 1, "data": {"id": 1, "name": "test"}}
    ]
