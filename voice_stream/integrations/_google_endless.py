# Google Speech by itself limits streams to 5 minutes, so you have to play games to have endless recognition.
# See https://github.com/GoogleCloudPlatform/python-docs-samples/blob/main/speech/microphone/transcribe_streaming_infinite.py
import logging
import sys
import time
from asyncio import Event
from typing import AsyncIterator, Callable, Union, Optional

import asyncstdlib
from google.api_core.exceptions import Cancelled
from google.cloud.speech_v1 import (
    StreamingRecognizeRequest as StreamingRecognizeRequestV1,
)
from google.cloud.speech_v1 import (
    StreamingRecognizeResponse as StreamingRecognizeResponseV1,
)
from google.cloud.speech_v2 import StreamingRecognizeResponse, StreamingRecognizeRequest

from voice_stream import (
    byte_buffer_step,
    chunk_bytes_step,
    queue_sink,
    queue_source,
    log_step,
    concat_step,
    async_init_step,
    QueueWithException,
    EndOfStreamMarker,
)
from voice_stream.audio import AudioFormat
from voice_stream.audio.audio_webm import split_webm_buffer
from voice_stream.core import (
    single_source,
    _chunk_bytes,
    fork_step,
    text_file_sink,
    map_step,
    binary_file_sink,
)
from voice_stream.events import BaseEvent, SpeechToTextResult
from voice_stream.types import background_task, format_current_task

logger = logging.getLogger(__name__)


def _wrap_streaming_recognize(stream, speech_async_client):
    """streaming_recognize doesn't exit cleanly or have good error handling.

    This fixes it so that when the input stream stops cleanly, the output stream stops cleanly, and when the
    input stream has an exception, it is propagated to the output stream.
    """
    exc_info = None

    async def input_wrap(async_iter):
        try:
            async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                async for item in owned_aiter:
                    yield item
        except Exception as e:
            nonlocal exc_info
            exc_info = sys.exc_info()

    async def output_wrap(async_iter):
        try:
            async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
                async for item in owned_aiter:
                    yield item
        except Cancelled as e:
            # We always get a cancelled out of the grpc, even for a clean stop in the audio.
            # If there was an input error, propagate that.  Otherwise, exit cleanly.
            pass
        if exc_info:
            exc_type, exc_value, exc_traceback = exc_info
            raise exc_value

    stream = input_wrap(stream)
    stream = async_init_step(stream, speech_async_client.streaming_recognize)
    stream = output_wrap(stream)
    return stream


class EndlessStream:
    MAX_STREAM_SIZE = 25600

    class StreamTimeoutException(Exception):
        pass

    def __init__(
        self,
        speech_async_client,
        initial_config: Union[StreamingRecognizeRequest, StreamingRecognizeRequestV1],
        map_audio: Callable[
            [bytes], Union[StreamingRecognizeRequest, StreamingRecognizeRequestV1]
        ],
        map_event: Callable[
            [Union[StreamingRecognizeResponse, StreamingRecognizeResponseV1], float],
            Optional[BaseEvent],
        ],
        audio_format: AudioFormat,
        stream_reset_timeout_secs: int = 240,
        max_resets: int = 4,
    ):
        self.speech_async_client = speech_async_client
        self.initial_config = initial_config
        self.map_audio = map_audio
        self.map_event = map_event
        self.audio_format = audio_format
        self.stream_reset_timeout_secs = stream_reset_timeout_secs
        self.max_resets = max_resets

        # Modifiable state
        self.new_stream = True
        self.stream_start_time = None
        self.duration_of_previous_streams = 0
        self.last_final_result_end_time = 0
        self.restart_counter = 0
        self.output_queue = QueueWithException()

    def step(self, async_iter):
        background_task(self._run_streams(async_iter))
        return queue_source(self.output_queue)

    async def _run_streams(self, async_iter: AsyncIterator[bytes]):
        queue_audio_task = None
        try:
            # Enqueue the input audio
            stream = async_iter
            stream = byte_buffer_step(stream)
            stream = chunk_bytes_step(stream, EndlessStream.MAX_STREAM_SIZE)
            stream = self.input_iterator(stream)
            input_queue = QueueWithException()
            queue_audio_task = background_task(queue_sink(stream, input_queue))

            while self.restart_counter < self.max_resets:
                cancel_event = Event()
                try:
                    stream = queue_source(input_queue, cancel_event)
                    # stream = log_step(stream, "Audio", lambda x: f"{format_current_task()}")
                    # stream, audio_out = fork_step(stream)
                    # audio_out = map_step(audio_out, lambda x:x.audio_content if hasattr(x, "audio_content") else x.audio)
                    # background_task(binary_file_sink(audio_out, f"{self.restart_counter}.webm"))
                    # background_task(text_file_sink(audio_out, f"{self.restart_counter}.ndjson"))
                    config = single_source(self.initial_config)
                    config = log_step(
                        config,
                        f"Recognize started #{self.restart_counter+1}",
                        lambda x: "",
                    )
                    stream = concat_step(config, stream)
                    # stream = log_step(
                    #     stream, f"Audio to SR #{self.restart_counter+1}", lambda x: f"", every_nth_message=25
                    # )
                    stream = _wrap_streaming_recognize(stream, self.speech_async_client)
                    stream = self.output_iterator(stream)
                    logger.debug("Initiating stream")
                    await queue_sink(
                        stream,
                        self.output_queue,
                        send_end_of_stream=False,
                        propagate_exceptions=False,
                    )
                    logger.debug("Endless stream completed successfully")
                    return
                except EndlessStream.StreamTimeoutException:
                    logger.debug("Endless stream timeout exception, restarting stream")
                    self.restart_counter += 1
                    cancel_event.set()
                    # Drain any queued audio from the input queue (it will be replayed with the new stream).
                    logger.debug(
                        f"Clearing {input_queue.qsize()} remaining items from the queue"
                    )
                    while not input_queue.empty():
                        input_queue.get_nowait()
                    if queue_audio_task.done():
                        return
                    self.new_stream = True
            logger.debug(
                f"Exceeded maximum reset count of {self.max_resets}.  Stopping stream."
            )
        except Exception as e:
            logger.exception(f"Exception during Google Recognize.")
            await self.output_queue.set_exception(e)
        finally:
            if queue_audio_task:
                queue_audio_task.cancel()
            if not self.output_queue.exception:
                await self.output_queue.put(EndOfStreamMarker)

    async def input_iterator(self, async_iter):
        duration_of_replay_buffer = 0
        replay_buffer = []
        self.stream_start_time = time.perf_counter()
        count = 0
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                if self.new_stream and replay_buffer:
                    # If we are starting a new stream, replay from our last final result in the old stream.
                    seconds_per_chunk = (
                        duration_of_replay_buffer + self.stream_reset_timeout_secs
                    ) / len(replay_buffer)
                    logger.debug(
                        f"Restarting last_end: {self.last_final_result_end_time} duration_of_previous_streams {self.duration_of_previous_streams} duration_of_replay_buffer {duration_of_replay_buffer} seconds_per_chunk: {seconds_per_chunk}"
                    )

                    n_chunks_fully_processed = round(
                        (
                            self.last_final_result_end_time
                            - self.duration_of_previous_streams
                            - duration_of_replay_buffer
                        )
                        / seconds_per_chunk
                    )

                    self.duration_of_previous_streams += (
                        n_chunks_fully_processed * seconds_per_chunk
                    )

                    duration_of_replay_buffer = (
                        len(replay_buffer) - n_chunks_fully_processed
                    ) * seconds_per_chunk
                    logger.debug(
                        f"Restarting stream with {duration_of_replay_buffer} seconds of replay.  Previous streams were {self.duration_of_previous_streams} seconds."
                    )

                    replay_audio = self.split_stream(
                        replay_buffer, n_chunks_fully_processed
                    )
                    replay_buffer = []
                    count += 1
                    for c in _chunk_bytes(replay_audio, EndlessStream.MAX_STREAM_SIZE):
                        replay_buffer.append(c)
                        ret = self.map_audio(c)
                        yield ret

                if self.new_stream:
                    logger.debug(
                        f"New stream initiating with {len(item)} bytes of audio"
                    )
                self.new_stream = False
                replay_buffer.append(item)
                yield self.map_audio(item)
        logger.debug("Reached the end of the input audio.")

    async def output_iterator(self, async_iter: AsyncIterator):
        async with asyncstdlib.scoped_iter(async_iter) as owned_aiter:
            async for item in owned_aiter:
                event = self.map_event(item, self.duration_of_previous_streams)
                if isinstance(event, SpeechToTextResult):
                    self.last_final_result_end_time = event.time_since_start

                yield event

                now = time.perf_counter()
                if now - self.stream_start_time > self.stream_reset_timeout_secs:
                    self.stream_start_time = now
                    raise EndlessStream.StreamTimeoutException()

    def split_stream(self, frame_list: list[bytes], split_point: int):
        if (
            self.audio_format == AudioFormat.WAV_MULAW_8KHZ
            or self.audio_format == AudioFormat.MP3
        ):
            return b"".join(frame_list[split_point:])
        elif self.audio_format == AudioFormat.WEBM_OPUS:
            byte_cutoff = 0
            for i in range(split_point):
                byte_cutoff += len(frame_list[i])
            replay_audio = b"".join(frame_list)
            return split_webm_buffer(replay_audio, byte_cutoff)
        elif self.audio_format == AudioFormat.OGG_OPUS:
            raise ValueError(
                f"Splitting OGG requires updating all future packets.  Not really feasible."
            )
        else:
            raise ValueError(
                f"Audio format not supported for split {self.audio_format}"
            )
