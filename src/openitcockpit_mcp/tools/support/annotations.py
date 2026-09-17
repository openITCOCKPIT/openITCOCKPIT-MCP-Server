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
