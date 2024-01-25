import collections
import io
import logging

import av

from tests.helpers import example_file

logger = logging.getLogger(__name__)


def print_packets(filename):
    with open(filename, "rb") as f:
        audio = f.read()

    input_container = av.open(io.BytesIO(audio))

    # Find the audio stream
    audio_stream = next((s for s in input_container.streams if s.type == "audio"), None)
    if audio_stream is None:
        raise ValueError("No audio stream found in the WEBM container")

    packets = [_ for _ in input_container.demux(audio_stream)]
    first_5 = packets

    print(f"First 5\n")
    i = 1
    for p in first_5:
        if p.is_corrupt:
            print("Packet is corrupt.")
        print(f"{i}: {p}")
        i += 1


def copy_webm(filename, outfile, skip: bool):
    with open(filename, "rb") as f:
        audio = f.read()

    input_container = av.open(io.BytesIO(audio))

    # Find the audio stream
    audio_stream = next((s for s in input_container.streams if s.type == "audio"), None)
    if audio_stream is None:
        raise ValueError("No audio stream found in the WEBM container")

    packets = [_ for _ in input_container.demux(audio_stream)]

    output_buffer = io.BytesIO()
    output_container = av.open(output_buffer, mode="w", format="webm")
    output_container.add_stream(template=audio_stream)
    if skip:
        assert packets[-1].size == 0
        print(f"Skipping packet of length {packets[-2].size}")
    for packet in packets:
        if packet.is_corrupt:
            print("Packet is corrupt.")
        if packet.dts is None:
            output_container.mux(packet)
    output_container.close()
    with open(outfile, "wb") as f:
        f.write(output_buffer.getvalue())


print_packets(example_file("testing.webm"))
# print("\n")
# print_packets(example_file("testing_out.webm"))

# copy_webm(example_file("testing.webm"), example_file("testing_copy.webm"), skip=False)
# copy_webm(example_file("testing.webm"), example_file("testing_copy2.webm"), skip=True)


# with open(example_file('testing.webm'), 'rb') as f:

# print_packets(example_file("longer.webm"))
# print("\n")
# print_packets("../../0.webm")
# print("\n")
# print_packets("../../1.webm")

#
# o = io.BytesIO()
# output_container = av.open(o, mode='w', format='webm')
# output_container.add_stream(template=audio_stream)
#
# for packet in first_5:
#     output_container.mux(packet)
#
# output_container.close()
#
# with open(example_file('testing_out2.webm'), 'wb') as f:
#     audio = f.write(o.getvalue())
#
# print("Reload")
#
# reload = av.open(example_file('testing_out2.webm'), 'rb')
# audio_stream = next((s for s in input_container.streams if s.type == 'audio'), None)
#
# for packet in reload.demux(audio_stream):
#     print(packet)
# reload.close()
#
