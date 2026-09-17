"""Measuring whether a model can actually work with these tools.

The unit tests show that a tool returns what it promises. This shows something
else: that a model, given the tool definitions and a question an operator would
ask, calls the right tool and reports what came back instead of inventing it.

It runs against a live openITCOCKPIT and an OpenAI-compatible model endpoint,
and it is meant to be re-run: after a change to a tool, its description or a
system prompt, and against every model an installation considers.
"""
