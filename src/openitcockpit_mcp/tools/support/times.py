"""Times as a model can read them without guessing: ISO 8601 with the offset.

openITCOCKPIT renders a time in the user's zone and in the date format the user
chose (``UsersTable::getDateformats``), with no zone in the string. Asked about a
result that carried the zone in a separate field, a model asked which times it
applied to; a time that carries its own offset leaves nothing to ask.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

#: The formats a user can choose, as PHP date() patterns (UsersTable.php:791).
PHP_FORMATS = (
    "F j, Y H:i:s",
    "m-d-Y H:i:s",
    "m-d-Y H:i",
    "m-d-Y h:i:s A",
    "H:i:s m-d-Y",
    "j F Y, H:i:s",
    "d.m.Y - H:i:s",
    "d.m.Y - h:i:s A",
    "H:i:s - d.m.Y",
    "H:i - d.m.Y",
    "Y-m-d H:i",
    "Y-m-d H:i:s",
)

_PHP_TO_STRPTIME = {"F": "%B", "j": "%d", "d": "%d", "m": "%m", "Y": "%Y", "H": "%H", "h": "%I", "i": "%M", "s": "%S", "A": "%p"}

FORMATS = tuple("".join(_PHP_TO_STRPTIME.get(char, char) for char in php) for php in PHP_FORMATS)


def to_iso(value: str, zone: ZoneInfo) -> str:
    """``value`` as ISO 8601 with offset when it is a time in one of the user formats, else unchanged."""
    text = value.strip()
    for pattern in FORMATS:
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=zone).isoformat()
    return value


def parse(value: str, zone: ZoneInfo) -> datetime | None:
    """``value`` as an aware time when it is ISO 8601 or a time in one of the user formats."""
    try:
        parsed = datetime.fromisoformat(to_iso(value, zone))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)


def localize(data: Any, zone: ZoneInfo) -> Any:
    """Every time anywhere in ``data`` as ISO 8601 with offset."""
    if isinstance(data, str):
        return to_iso(data, zone)
    if isinstance(data, dict):
        return {key: localize(value, zone) for key, value in data.items()}
    if isinstance(data, list):
        return [localize(value, zone) for value in data]
    return data
