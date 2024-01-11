# Design

* Unit tests should not hit external APIs.
* Integration tests should hit real APIs.

## Backpressure

As much as possible try to keep backpressure in place (keeping the data flow pull based).  Avoid add queues and buffering
internally within steps since that breaks backpressure.  The user can insert buffers if they want as separate steps, but avoid having them
in implementations.