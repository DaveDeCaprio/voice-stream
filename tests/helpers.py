import logging
import traceback
from os.path import join, dirname

import asyncio

logger = logging.getLogger(__name__)


def example_file(filename: str) -> str:
    return join(dirname(__file__), "examples", filename)


def assert_files_equal(expected_path: str, actual_path: str, mode: str = "t") -> None:
    with open(expected_path, f"r{mode}") as file1, open(
        actual_path, f"r{mode}"
    ) as file2:
        assert file2.read() == file1.read()


async def debug_event_loop(max_iters: int = 10):
    async def gen():
        count = 0
        while count < max_iters:
            count += 1
            await asyncio.sleep(1)
            all_tasks = asyncio.all_tasks()
            tasks_info = []

            for task in all_tasks:
                # Get the stack for the task
                stack = task.get_stack()

                # Format the stack trace
                try:
                    formatted_stack = "".join(traceback.format_stack(stack[-1]))
                except Exception as e:
                    formatted_stack = f"Error formatting stack {stack} {e}"

                # Combine task info and its stack trace
                tasks_info.append(f"Task: {task}\nStack Trace:\n{formatted_stack}\n")
            response = "\n\n".join(tasks_info)
            # output = '\n'.join([str(task) for task in asyncio.all_tasks()])
            logger.info(f"Event loop:\n{response}\n\n")

    asyncio.create_task(gen())
