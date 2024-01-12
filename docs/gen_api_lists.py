import importlib
import inspect

import os
import pkgutil
import sys

sys.path.insert(0, os.path.abspath(".."))

os.makedirs("_gen/integrations", exist_ok=True)


def write_class(f, module: str, name: str):
    f.write(f".. autoclass:: {module}.{name}\n")
    f.write(f"   :members:\n")
    f.write(f"   :undoc-members:\n")
    f.write(f"   :show-inheritance:\n")


def write_integration(module_name: str):
    full_name = f"voice_stream.integrations.{module_name}"
    with open(f"_gen/integrations/{module_name}.rst", "w") as f:
        underline = "=" * len(module_name)
        f.write(f"{module_name}\n{underline}\n\n")
        m = importlib.import_module(full_name)
        for name, obj in inspect.getmembers(m):
            if inspect.isfunction(obj) and obj.__module__ == full_name:
                f.write(
                    f".. autofunction:: voice_stream.integrations.{module_name}.{name}\n"
                )
            elif inspect.isclass(obj) and obj.__module__ == full_name:
                write_class(f, f"voice_stream.integrations.{module_name}", name)
            # else:
            #     print(f"Unknown type: {name}")


import voice_stream

# Doc for the basic packages
with open("_gen/sources.rst", "w") as sources:
    sources.write("Sources\n=======\n\n")
    with open("_gen/sinks.rst", "w") as sinks:
        sinks.write("Sinks\n=======\n\n")
        with open("_gen/steps.rst", "w") as steps:
            steps.write("Steps\n=======\n\n")
            with open("_gen/helpers.rst", "w") as helpers:
                helpers.write("Helpers\n=======\n\n")

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
                        write_class(helpers, "voice_stream", name)

# Now do integrations
from voice_stream import integrations

submodules = list(pkgutil.iter_modules(integrations.__path__))

for submodule in submodules:
    write_integration(submodule.name)

with open("_gen/integrations/index.md", "w") as f:
    f.write(
        """
# Integrations

```{toctree}
:hidden:
"""
    )
    for submodule in submodules:
        f.write(f"{submodule.name}\n")
    f.write("""```""")
