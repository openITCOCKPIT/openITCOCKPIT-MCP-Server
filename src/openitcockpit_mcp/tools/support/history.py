"""Check-execution and state-change history for hosts and services."""

from __future__ import annotations

#: Default row count for the check-execution tools, whose rows carry output and
#: perfdata and are returned newest-first.
CHECK_HISTORY_DEFAULT = 25


NARROW_HINT = "a shorter hours= window"
