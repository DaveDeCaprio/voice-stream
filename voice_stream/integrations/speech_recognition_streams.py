# # Works with the python speech_recognition package
# import asyncio
# from concurrent.futures import ThreadPoolExecutor
# from typing import AsyncIterator
#
# import speech_recognition as sr
#
# from voice_stream import chunk_bytes_step
#
#
# def python_speech_recognition_step(
#     async_iter: AsyncIterator[bytes],
#     recognition_function: str,
#     sample_rate: int,
#     sample_width: int,
#     chunk_size: int = 4096,
#     **recognition_kwargs: dict,
# ) -> AsyncIterator[str]:
#     # This class does triple duty.  It is:
#     # The async iterator that is returned (__aiter__ and __anext__)
#     # The AudioSource for the recognizer.  (__enter__ and __exit__)
#     # The audio stream for the recognizer.  (read)
#     class _AsyncPythonSpeechRecIter(sr.AudioSource):
#         def __init__(self, input):
#             self.stream = self
#             self.loop = asyncio.get_event_loop()
#             self.iter = input.__aiter__()
#             self.buffer = b''
#             self.CHUNK = chunk_size
#             self.SAMPLE_RATE = sample_rate
#             self.SAMPLE_WIDTH = sample_width
#
#         def __aiter__(self):
#                 return self
#
#         async def __anext__(self):
#             loop = asyncio.get_running_loop()
#             with ThreadPoolExecutor() as pool:
#                 result = await loop.run_in_executor(pool, self.blocking_recognize)
#                 return result
#
#         def read(self, size):
#             while True:
#                 if len(self.buffer) >= size:
#                     ret = self.buffer[:size]
#                     self.buffer = self.buffer[size:]
#                     return ret
#                 else:
#                     try:
#                         # Schedule the async function on the event loop and wait for the result
#                         future = asyncio.run_coroutine_threadsafe(self.iter.__anext__(), self.loop)
#                         self.buffer += future.result()  # This blocks the thread until the coroutine is done
#                     except StopAsyncIteration:
#                         ret = self.buffer
#                         self.buffer = b''
#                         return ret
#
#         def blocking_recognize(self):
#             r = sr.Recognizer()
#             audio = r.listen(self)
#             f = getattr(r, recognition_function)
#             return f(audio, **recognition_kwargs)
#
#     pipe = chunk_bytes_step(async_iter, chunk_size)
#     return _AsyncPythonSpeechRecIter(pipe)
#
