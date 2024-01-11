# Approach

This section contains guidelines used throughout the code base.

* Use asyncio everywhere.  Isolate any code that needs to be blocking in a separate worker thread.
* Standardize naming.  Sources, sinks, and steps are all functions with a suffix on the name indicating what type they are.
* Build off existing abstractions.  Python already has async iterators which work well, and LangChain has Runnables.  Avoid new core abstractions to improve interoperability.
