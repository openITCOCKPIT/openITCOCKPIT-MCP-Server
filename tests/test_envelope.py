from __future__ import annotations

from openitcockpit_mcp.tools.envelope import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    build_result,
    clamp_limit,
    fetch_limit,
)


def test_no_limit_means_the_default():
    assert clamp_limit(None) == DEFAULT_LIMIT


def test_limit_is_clamped_into_range():
    assert clamp_limit(0) == 1
    assert clamp_limit(-5) == 1
    assert clamp_limit(10_000) == MAX_LIMIT


def test_one_extra_row_is_requested_to_detect_truncation():
    assert fetch_limit(50) == 51


def test_complete_result_is_not_marked_truncated():
    result = build_result([1, 2, 3], 50, "name_filter")
    assert (result.count, result.truncated, result.hint) == (3, False, None)


def test_exactly_full_result_is_not_truncated():
    """limit rows means limit rows - the probe row is what proves there is more."""
    result = build_result(list(range(50)), 50, "name_filter")
    assert result.truncated is False
    assert result.count == 50


def test_probe_row_marks_truncation_and_is_dropped():
    result = build_result(list(range(51)), 50, "name_filter")
    assert result.truncated is True
    assert result.count == 50
    assert len(result.items) == 50


def test_hint_names_the_way_to_narrow_this_tool():
    result = build_result(list(range(51)), 50, "a shorter hours= window")
    assert "a shorter hours= window" in (result.hint or "")
    assert str(MAX_LIMIT) in (result.hint or "")


def test_hint_warns_against_treating_it_as_complete():
    result = build_result(list(range(51)), 50, "name_filter")
    assert "complete set" in (result.hint or "")
