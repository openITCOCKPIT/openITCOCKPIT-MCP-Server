"""Tool annotation presets.

MCP ``annotations`` are hints a client uses to decide whether a tool call may run
unattended or needs confirmation. They are declarative claims, not enforcement.

``openWorldHint`` is true throughout: every tool reaches a live openITCOCKPIT
instance rather than a closed local domain.
"""

from __future__ import annotations

# Reads. Safe to call unattended and repeatedly.
READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# Creates a new object. Nothing existing is overwritten, so not destructive;
# calling it twice creates two objects or fails on a duplicate name, so not
# idempotent.
CREATE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}

# Read-modify-write on an existing object: every field named in the call has its
# previous value overwritten. Repeating the call with the same fields converges
# on the same state.
UPDATE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}

# A command to the monitoring engine that adds to an object's state, such as an
# acknowledgement or a check run now. Nothing is lost, and sending it again
# leaves the same state.
COMMAND = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# A command that takes something away someone else put there, such as their
# acknowledgement. Sending it again changes nothing more.
REMOVE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}

# Writing the configuration to the monitoring engine and reloading it. It
# replaces what the engine runs, and sending it again leads to the same state.
APPLY = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}

# Removes an object for good, with everything that belongs to it. Calling it
# again finds nothing left to delete.
DELETE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}
