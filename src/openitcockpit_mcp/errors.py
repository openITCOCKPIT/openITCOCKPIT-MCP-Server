"""Translation of openITCOCKPIT HTTP responses into errors an agent can act on.

``require_success``
    For reads and for ``add.json`` writes. Reports a failure as one message
    naming the action that failed.

``require_write_success``
    For writes that can fail CakePHP field validation. Reports each field's
    validation error individually, so a caller can correct every rejected field
    in one retry.
"""

from __future__ import annotations

from typing import Any


class OITCUnreachableError(RuntimeError):
    """openITCOCKPIT could not be reached at all (timeout, DNS, refused connection)."""


def require_success(resp: dict[str, Any], code: int, action: str) -> None:
    """Raise unless openITCOCKPIT answered 200 while *action*."""
    if code == 200:
        return
    _raise_common(code, action)
    message = (resp.get("message") or resp.get("error")) if isinstance(resp, dict) else None
    raise RuntimeError(f"openITCOCKPIT returned an error (HTTP {code}) while {action}" + (f": {message}" if message else "."))


def require_write_success(resp: dict[str, Any], code: int, action: str) -> None:
    """Like :func:`require_success`, but surfaces CakePHP field-level validation errors.

    The response shape on a failed ``add()``/``edit()`` is
    ``{"error": {"field_name": {"rule_name": "message", ...}, ...}}``.
    """
    if code == 200:
        return
    _raise_common(code, action)
    errors = resp.get("error") if isinstance(resp, dict) else None
    if isinstance(errors, dict) and errors:
        details = []
        for field, rules in errors.items():
            messages = "; ".join(str(m) for m in rules.values()) if isinstance(rules, dict) else str(rules)
            details.append(f"{field}: {messages}")
        raise ValueError(f"openITCOCKPIT rejected the write while {action} (HTTP {code}): " + " | ".join(details))
    message = resp.get("message") if isinstance(resp, dict) else None
    raise RuntimeError(f"openITCOCKPIT returned an error (HTTP {code}) while {action}" + (f": {message}" if message else "."))


def _raise_common(code: int, action: str) -> None:
    """The status codes both checkers report identically."""
    if code in (401, 403):
        raise RuntimeError(
            f"Authentication with openITCOCKPIT failed while {action}. "
            "Check that OITC_APIKEY is valid and has sufficient permissions."
        )
    if code == 404:
        raise RuntimeError(f"openITCOCKPIT reported 'not found' while {action}.")
