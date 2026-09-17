"""Times in every date format a user can choose come out as ISO 8601 with the offset."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.times import localize, to_iso

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    "rendered",
    [
        "September 16, 2026 18:04:40",
        "09-16-2026 18:04:40",
        "09-16-2026 06:04:40 PM",
        "18:04:40 09-16-2026",
        "16 September 2026, 18:04:40",
        "16.09.2026 - 18:04:40",
        "16.09.2026 - 06:04:40 PM",
        "18:04:40 - 16.09.2026",
        "2026-09-16 18:04:40",
    ],
)
def test_every_user_format_with_seconds_reads_the_same(rendered):
    assert to_iso(rendered, BERLIN) == "2026-09-16T18:04:40+02:00"


@pytest.mark.parametrize("rendered", ["09-16-2026 18:04", "18:04 - 16.09.2026", "2026-09-16 18:04"])
def test_formats_without_seconds(rendered):
    assert to_iso(rendered, BERLIN) == "2026-09-16T18:04:00+02:00"


def test_the_offset_follows_the_date():
    assert to_iso("12:00:00 - 16.01.2026", BERLIN) == "2026-01-16T12:00:00+01:00"


@pytest.mark.parametrize("text", ["45m 27s", "4 minutes ago", "scale-srv-002", "CRITICAL: scale: host down", ""])
def test_anything_else_stays_as_it_is(text):
    assert to_iso(text, BERLIN) == text


def test_times_nested_anywhere_are_converted():
    data = {"items": [{"since": "18:04:40 - 16.09.2026", "name": "web01"}], "total": 1}
    assert localize(data, BERLIN) == {"items": [{"since": "2026-09-16T18:04:40+02:00", "name": "web01"}], "total": 1}


def test_a_result_leaves_out_empty_fields_and_converts_times_once_it_has_a_zone():
    class Sample(Result):
        since: str
        hint: str | None = None

    assert Sample(since="18:04:40 - 16.09.2026").model_dump() == {"since": "18:04:40 - 16.09.2026"}
    assert Sample(since="18:04:40 - 16.09.2026").in_zone(BERLIN).model_dump() == {"since": "2026-09-16T18:04:40+02:00"}
