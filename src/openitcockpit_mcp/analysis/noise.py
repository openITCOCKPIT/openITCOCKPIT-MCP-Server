"""What to do about a noisy check, by rules an operator can read.

The suggestions name settings openITCOCKPIT has; which value fits is left to the
operator, who knows the service.
"""

from __future__ import annotations


def flapping() -> str:
    return (
        "Its state goes back and forth. Raise max_check_attempts or retry_interval so short blips do not count, "
        "or look at the thresholds the check uses."
    )


def notified() -> str:
    return (
        "If the problem behind the notifications is known, acknowledge it or schedule a downtime; "
        "if it keeps coming back, fix the cause or raise notification_interval."
    )


def long_standing(state: str, hours: int) -> str:
    if state == "unknown":
        return (
            f"Unknown for more than {hours} hours: the check itself cannot run or read its target. "
            "Look at the plugin, its arguments or the agent."
        )
    return (
        f"{state.capitalize()} for more than {hours} hours and neither acknowledged nor in a downtime. "
        "Acknowledge it with a note, schedule a downtime, fix it, or disable the check if nobody needs it."
    )
