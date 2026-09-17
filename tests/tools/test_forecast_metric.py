"""forecast_metric against constructed series, where the right answer is arithmetic.

A recording would fix the forecast to whatever the instance happened to be doing
that day. These build the series instead, so each case states the rate and the
threshold it expects to be reached.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import pytest
import responses
from cassette import BASE_URL
from fastmcp import Client

from openitcockpit_mcp.server import create_server

HOST_UUID = "11111111-1111-1111-1111-111111111111"
SERVICE_UUID = "22222222-2222-2222-2222-222222222222"


def series(start: float, per_day: float, days: int, step_hours: int = 1) -> dict[str, float]:
    """Measurements ending now, as the endpoint returns them: ISO stamp to value."""
    end = datetime.now().astimezone().replace(microsecond=0)
    steps = int(days * 24 / step_hours)
    points = {}
    for index in range(steps + 1):
        moment = end - timedelta(hours=(steps - index) * step_hours)
        points[moment.isoformat()] = start + per_day * (index * step_hours / 24)
    return points


def perfdata(data: dict[str, float], warn: float | None = 80.0, crit: float | None = 90.0, unit: str = "GiB") -> dict:
    return {
        "performance_data": [
            {
                "datasource": {"metric": "/", "name": "/", "unit": unit, "warn": warn, "crit": crit, "min": 0, "max": 100},
                "data": data,
            }
        ]
    }


@pytest.fixture
def instance(settings):
    """A server whose service lookup and perfdata answers are set per test."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add(
            responses.GET,
            re.compile(rf"{re.escape(BASE_URL)}/angular/user_timezone\.json.*"),
            json={"timezone": {"user_timezone": "Europe/Berlin"}},
        )
        mock.add(
            responses.GET,
            re.compile(rf"{re.escape(BASE_URL)}/services/index\.json.*"),
            json={"all_services": [{"Host": {"uuid": HOST_UUID}, "Service": {"uuid": SERVICE_UUID}}]},
        )
        mcp, deps = create_server(settings)
        try:
            yield mcp, mock
        finally:
            deps.api.close()


def answer(mcp) -> dict:
    async def call():
        async with Client(mcp) as client:
            result = await client.call_tool("forecast_metric", {"hostname": "web01", "servicename": "Disk /", "hours": 168})
            return result.structured_content

    import asyncio

    return asyncio.run(call())


def graph(mock, payload: dict) -> None:
    mock.add(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/graphgenerators/.*"), json=payload)


def test_a_steady_rise_gives_the_day_the_threshold_is_reached(instance):
    mcp, mock = instance
    # 50 at the start, 2 a day for seven days: 64 now, 16 to go at 2 a day.
    graph(mock, perfdata(series(start=50.0, per_day=2.0, days=7)))
    result = answer(mcp)
    metric = result["metrics"][0]
    assert metric["change_per_day"] == 2.0
    assert metric["current"] == 64.0
    assert metric["days_to_warning"] == 8.0
    assert metric["days_to_critical"] == 13.0
    assert "reaches warning in 8.0 days" in result["summary"]


def test_a_value_that_does_not_move_is_not_given_a_date(instance):
    mcp, mock = instance
    graph(mock, perfdata(series(start=42.0, per_day=0.0, days=7)))
    result = answer(mcp)
    metric = result["metrics"][0]
    assert metric["direction"] == "flat"
    assert "days_to_warning" not in metric
    assert "is moving" in result["summary"]


def test_a_series_that_is_not_a_trend_is_refused_rather_than_dated(instance):
    mcp, mock = instance
    # A sawtooth: a straight line explains almost none of it.
    points = series(start=10.0, per_day=1.0, days=7)
    sawtooth = {stamp: value + (20.0 if index % 2 else 0.0) for index, (stamp, value) in enumerate(points.items())}
    graph(mock, perfdata(sawtooth))
    result = answer(mcp)
    metric = result["metrics"][0]
    assert "days_to_warning" not in metric
    assert metric["forecast"].startswith("not forecast:")
    assert "No date" in result["summary"]


def test_a_threshold_already_passed_is_reported_as_such(instance):
    mcp, mock = instance
    # 85 rising a day for a week: 92 now, over both 80 and 90.
    graph(mock, perfdata(series(start=85.0, per_day=1.0, days=7)))
    result = answer(mcp)
    metric = result["metrics"][0]
    assert metric["current"] == 92.0
    assert metric["reaches_warning_at"] == "already past it"
    assert metric["reaches_critical_at"] == "already past it"
    assert "current state rather than a forecast" in result["summary"]


def test_a_falling_value_reaches_no_upper_threshold(instance):
    mcp, mock = instance
    graph(mock, perfdata(series(start=70.0, per_day=-2.0, days=7)))
    result = answer(mcp)
    metric = result["metrics"][0]
    assert metric["direction"] == "falling"
    assert "days_to_warning" not in metric
    assert "does not reach a threshold" in result["summary"]


def test_a_metric_without_thresholds_still_reports_its_rate(instance):
    mcp, mock = instance
    graph(mock, perfdata(series(start=10.0, per_day=5.0, days=7), warn=None, crit=None))
    result = answer(mcp)
    metric = result["metrics"][0]
    assert metric["change_per_day"] == 5.0
    assert metric["warning_at"] is None
    assert "days_to_warning" not in metric


def test_a_service_without_performance_data_says_so(instance):
    mcp, mock = instance
    graph(mock, {"performance_data": [{"datasource": [], "data": []}]})
    result = answer(mcp)
    assert result["metrics"] == []
    assert "no performance data" in result["summary"]


def test_the_measurements_are_read_from_the_service_the_names_resolve_to(instance):
    mcp, mock = instance
    graph(mock, perfdata(series(start=50.0, per_day=2.0, days=7)))
    answer(mcp)
    asked = next(call.request.url for call in mock.calls if "graphgenerators" in call.request.url)
    assert f"host_uuid={HOST_UUID}" in asked
    assert f"service_uuid={SERVICE_UUID}" in asked
    assert "isoTimestamp=1" in asked


def test_several_metrics_are_ordered_by_what_is_reached_first(instance):
    mcp, mock = instance
    slow = series(start=50.0, per_day=1.0, days=7)
    fast = series(start=50.0, per_day=5.0, days=7)
    graph(
        mock,
        {
            "performance_data": [
                {"datasource": {"metric": "slow", "unit": "GiB", "warn": 80, "crit": 90, "min": 0, "max": 100}, "data": slow},
                {"datasource": {"metric": "fast", "unit": "GiB", "warn": 80, "crit": 90, "min": 0, "max": 100}, "data": fast},
            ]
        },
    )
    result = answer(mcp)
    assert [metric["metric"] for metric in result["metrics"]] == ["fast", "slow"]
    assert json.dumps(result["summary"]).count("fast") == 1
