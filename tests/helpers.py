from os.path import join, dirname


def example_file(filename: str) -> str:
    return join(dirname(__file__), "examples", filename)


def assert_files_equal(expected_path: str, actual_path: str, mode: str = "t") -> None:
    with open(expected_path, f"r{mode}") as file1, open(
        actual_path, f"r{mode}"
    ) as file2:
        assert file2.read() == file1.read()
