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


def write_submodule(module_path: str, module_name: str):
    full_name = f"{module_path}.{module_name}"
    file = module_path.replace("voice_stream", "_gen").replace(".", "/")
    with open(f"{file}/{module_name}.rst", "w") as f:
        underline = "=" * len(module_name)
        f.write(f"{module_name}\n{underline}\n\n")
        m = importlib.import_module(full_name)
        f.write(f"\n{m.__doc__}\n\n")
        for name, obj in inspect.getmembers(m):
            if inspect.isfunction(obj) and obj.__module__.startswith("voice_stream"):
                f.write(f".. autofunction:: {module_path}.{module_name}.{name}\n")
            elif inspect.isclass(obj) and obj.__module__.startswith(
                f"{module_path}.{module_name}"
            ):
                # print(f"{name} {obj} {obj.__module__} {module_path}.{module_name}\n")
                write_class(f, f"{module_path}.{module_name}", name)
            # else:
            #     print(f"Unknown type: {module_path} {module_name} {name}")


import voice_stream

# Doc for the basic packages
with open("_gen/sources.rst", "w") as sources:
    sources.write("core sources\n============\n\n")
    with open("_gen/sinks.rst", "w") as sinks:
        sinks.write("core sinks\n============\n\n")
        with open("_gen/steps.rst", "w") as steps:
            steps.write("core steps\n============\n\n")
            with open("_gen/helpers.rst", "w") as helpers:
                helpers.write("helpers\n=======\n\n")

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


write_submodule("voice_stream", "audio")
write_submodule("voice_stream", "events")

# Now do integrations
from voice_stream import integrations

submodules = list(pkgutil.iter_modules(integrations.__path__))

for submodule in submodules:
    write_submodule("voice_stream.integrations", submodule.name)

with open("_gen/integrations/index.md", "w") as f:
    f.write(
        """
# integrations

Integrations provide VoiceStream sources, steps, and sinks for working with various third-party tools.

These include:

* __Web Frameworks__ like [FastAPI](./fastapi) and [Quart](./quart) let you put a web API on your voice application.   
* __AI Components__ for speech recognition, text to speech, and LLMs are provided by tools such as [LangChain](./langchain) and [Google Cloud APIs](./google) 
* __Other audio sources__ allow integration into different kinds of applications, like [Twilio](./twilio) for voice calls and PyAudio for desktop audio.  

```{toctree}
:hidden:
"""
    )
    for submodule in submodules:
        f.write(f"{submodule.name}\n")
    f.write("""```""")
