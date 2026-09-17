"""The checks a case is built from, without a model or an instance."""

from __future__ import annotations

import json

from openitcockpit_mcp.evaluation.checks import called, grade, invented_names, invented_numbers, quoted, returned_values


def call(tool: str, arguments: dict | None = None, result: dict | None = None, error: bool = False) -> dict:
    return {"tool": tool, "arguments": arguments or {}, "result": json.dumps(result or {}), "error": error}


def test_a_number_has_to_stand_on_its_own():
    assert quoted(600, "set to 600 seconds")
    assert not quoted(600, "the id is 6001")
    assert not quoted(600, "600.5 is something else")


def test_zero_may_be_written_as_a_word():
    """ "No host is down" reports a count of zero as a person writes it."""
    assert quoted(0, "No host is down.")
    assert quoted(0, "Kein Host ist down.")
    assert not quoted(0, "3 hosts are down.")


def test_text_is_matched_by_word_and_regardless_of_case():
    assert quoted("ok", "The service is now ok.")
    assert quoted("ok", "output was DISK OK - used 40%")
    assert not quoted("ok", "The service is critical.")


def test_a_value_is_read_out_of_the_result_it_was_returned_in():
    calls = [call("find_hosts", result={"by_state": {"down": 3}}), call("find_hosts", result={"by_state": {}})]
    assert returned_values(calls, "find_hosts", "by_state.down") == [3]


def test_a_failed_call_does_not_count_as_having_returned_anything():
    calls = [call("find_hosts", result={"by_state": {"down": 3}}, error=True)]
    assert returned_values(calls, "find_hosts", "by_state.down") == []


def test_a_call_matches_when_the_named_arguments_are_contained():
    made = call("update_service", {"hostname": "web01", "fields": {"check_interval_seconds": 600, "notes": "x"}})
    assert called({"tool": "update_service", "arguments": {"fields": {"check_interval_seconds": 600}}}, made)
    assert not called({"tool": "update_service", "arguments": {"fields": {"check_interval_seconds": 300}}}, made)


def test_a_string_argument_is_a_pattern():
    made = call("acknowledge_problem", {"hostname": "web01", "comment": "ticket OPS-4712"})
    assert called({"tool": "acknowledge_problem", "arguments": {"comment": "OPS-4712"}}, made)
    assert not called({"tool": "acknowledge_problem", "arguments": {"hostname": "^db01$"}}, made)


def test_an_expected_outcome_is_read_out_of_the_result():
    made = call("schedule_downtime", {"hostname": "web01"}, {"outcome": "done"})
    assert called({"tool": "schedule_downtime", "outcome": "done"}, made)
    assert not called({"tool": "schedule_downtime", "outcome": "not_sent"}, made)


def test_a_name_no_tool_returned_is_an_invention():
    calls = [call("find_hosts", result={"items": [{"host": "web01"}]})]
    assert invented_names("web01 and db-07 are down", "which hosts are down?", calls) == ["db-07"]
    assert invented_names("web01 is down", "which hosts are down?", calls) == []


def test_a_number_no_tool_returned_is_worked_out():
    calls = [call("find_services", result={"total": 12})]
    assert invented_numbers("12 services, 47 of them new", "how many?", calls) == ["47"]


def test_grade_reports_every_check_that_failed():
    case = {
        "id": "x",
        "question": "how many hosts are down?",
        "must": [["down"]],
        "must_not": ["guess"],
        "must_call": [{"tool": "find_hosts"}],
        "must_quote": {"tool": "find_hosts", "field": "by_state.down"},
        "must_not_invent": True,
    }
    calls = [call("find_hosts", result={"by_state": {"down": 3}})]

    assert grade(case, "3 hosts are down.", calls)["passed"]

    failed = grade(case, "I guess that db-07 is down.", calls)["failed"]
    assert any("must quote" in f for f in failed)
    assert any("must not: guess" in f for f in failed)
    assert any("db-07" in f for f in failed)


def test_no_answer_within_the_step_limit_is_a_failure():
    assert grade({"id": "x", "question": "?"}, None, [])["failed"] == ["no answer within the step limit"]


def test_one_of_several_values_may_be_quoted():
    """Two tools can answer the same question; the answer has to carry one of them."""
    case = {
        "id": "x",
        "question": "how many services have a problem?",
        "must_quote": [
            {"tool": "find_services", "field": "total"},
            {"tool": "get_problem_overview", "field": "services.by_state.critical"},
        ],
    }
    calls = [call("get_problem_overview", result={"services": {"by_state": {"critical": 7}}})]

    assert grade(case, "7 services are critical.", calls)["passed"]
    failed = grade(case, "Some services are critical.", calls)["failed"]
    assert "find_services.total (never returned)" in failed[0]
