from voice_stream.audio.audio_mp3 import calculate_split_points


def test_split_points():
    frame_boundaries = [
        0,
        100,
        200,
        350,
        800,
        900,
    ]  # Replace with your actual frame boundaries
    buffer_size = 1000  # Total size of the MP3 buffer
    max_size = 250  # Maximum size of each chunk

    split_points = calculate_split_points(frame_boundaries, buffer_size, max_size)
    assert split_points == [200, 350, 800, 1000]
