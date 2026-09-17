"""Time as openITCOCKPIT reads it: in the time zone of the user a request acts as.

``filter[from]``/``filter[to]`` and downtime dates are interpreted in that zone,
not in UTC and not in the server's. Built from this process's own clock, a
window is off by the difference - measured with a user in Europe/Berlin and the
server in a UTC container: "the last 24 hours" returned nothing, because the
window ended two hours before the newest entries.

``angular/user_timezone.json`` answers for every signed-in user without a role
permission. The zone is cached per identity, like the scope cache.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from threading import Lock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success

#: The format filter[from]/filter[to] parse, not ISO 8601.
FILTER_DATE_FORMAT = "%d.%m.%Y %H:%M"


def _end_of_minute(moment: datetime) -> datetime:
    """The next full minute, so the minute a window ends in is inside it.

    openITCOCKPIT reads the window bounds to the minute and compares them as
    ``created <= to``. A window ending at the current minute therefore cut off
    everything that happened in it - measured: a host edited at 10:42:39 was
    missing from a window ending at 10:42.
    """
    return (moment + timedelta(minutes=1)).replace(second=0, microsecond=0)


#: openITCOCKPIT's own fallback for a user without a time zone.
DEFAULT_ZONE = "Europe/Berlin"


class UserClock:
    def __init__(self, api: OITCClient, ttl_seconds: int = 300) -> None:
        self._api = api
        self._ttl = ttl_seconds
        self._zones: dict[str, tuple[ZoneInfo, float]] = {}
        self._lock = Lock()

    def zone(self) -> ZoneInfo:
        partition = self._api.cache_partition()
        with self._lock:
            cached = self._zones.get(partition)
            if cached and cached[1] > time.monotonic():
                return cached[0]
        resp, code = self._api.get("/angular/user_timezone.json")
        require_success(resp, code, "reading the user's time zone")
        name = ((resp.get("timezone") or {}).get("user_timezone") or "").strip() or DEFAULT_ZONE
        try:
            zone = ZoneInfo(name)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo(DEFAULT_ZONE)
        with self._lock:
            self._zones[partition] = (zone, time.monotonic() + self._ttl)
        return zone

    def now(self) -> datetime:
        """Wall-clock time in the user's zone, without tzinfo, as openITCOCKPIT expects it."""
        return datetime.now(self.zone()).replace(tzinfo=None)

    def window(self, hours: int) -> dict[str, str]:
        """``filter[from]``/``filter[to]`` covering the last ``hours`` hours."""
        now = self.now()
        return {
            "filter[from]": (now - timedelta(hours=hours)).strftime(FILTER_DATE_FORMAT),
            "filter[to]": _end_of_minute(now).strftime(FILTER_DATE_FORMAT),
        }


def between(start: datetime, end: datetime) -> dict[str, str]:
    """``filter[from]``/``filter[to]`` for two times; aware times are first put in ``start``'s zone."""
    if start.tzinfo and end.tzinfo:
        end = end.astimezone(start.tzinfo)
    return {"filter[from]": start.strftime(FILTER_DATE_FORMAT), "filter[to]": _end_of_minute(end).strftime(FILTER_DATE_FORMAT)}
