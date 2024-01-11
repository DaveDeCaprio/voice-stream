import inspect

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

os.makedirs("_gen", exist_ok=True)
with open("_gen/sources.rst", "w") as sources:
    sources.write("Sources\n=======\n\n")
    with open("_gen/sinks.rst", "w") as sinks:
        sinks.write("Sinks\n=======\n\n")
        with open("_gen/steps.rst", "w") as steps:
            steps.write("Steps\n=======\n\n")
            with open("_gen/helpers.rst", "w") as helpers:
                helpers.write("Helpers\n=======\n\n")
                import voice_stream

                for name, obj in inspect.getmembers(voice_stream):
                    if inspect.isfunction(obj):
                        if name.endswith("_source"):
                            sources.write(f".. autofunction:: voice_stream.{name}\n")
                        elif name.endswith("_sink"):
                            sinks.write(f".. autofunction:: voice_stream.{name}\n")
                        elif name.endswith("_step"):
                            steps.write(f".. autofunction:: voice_stream.{name}\n")
                        else:
                            helpers.write(f".. autofunction:: voice_stream.{name}\n")
                    elif inspect.isclass(obj):
                        helpers.write(f".. autoclass:: voice_stream.{name}\n")
                        helpers.write(f"   :members:\n")
                        helpers.write(f"   :undoc-members:\n")
                        helpers.write(f"   :show-inheritance:\n")
