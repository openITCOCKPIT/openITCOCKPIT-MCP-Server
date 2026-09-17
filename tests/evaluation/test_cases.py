"""Reading case files, including the ones that ship."""

from __future__ import annotations

import pytest

from openitcockpit_mcp.evaluation import cases


def write(tmp_path, text: str):
    path = tmp_path / "cases.toml"
    path.write_text(text)
    return path


def test_the_shipped_cases_load_and_only_read():
    loaded, instance = cases.load(cases.shipped())

    assert loaded, "the shipped file holds no case"
    assert instance["time_zone"]
    for case in loaded:
        assert not case.get("setup") and not case.get("reset"), f"{case['id']} would change the instance"


def test_a_typo_in_a_key_is_refused(tmp_path):
    path = write(tmp_path, '[[case]]\nid = "a"\nquestion = "q"\nmust_quotes = 1\n')
    with pytest.raises(cases.CaseFileError, match="must_quotes"):
        cases.load(path)


def test_two_cases_cannot_share_an_id(tmp_path):
    path = write(tmp_path, '[[case]]\nid = "a"\nquestion = "q"\n\n[[case]]\nid = "a"\nquestion = "r"\n')
    with pytest.raises(cases.CaseFileError, match="share the id"):
        cases.load(path)


def test_arguments_written_as_json_reach_the_case(tmp_path):
    """TOML has no null, and null is how a field goes back to its template."""
    path = write(
        tmp_path,
        '[[case]]\nid = "a"\nquestion = "q"\n'
        "must_call = [{ tool = \"update_service\", arguments_json = '''{\"fields\": {\"check_interval_seconds\": null}}''' }]\n",
    )
    loaded, _ = cases.load(path)
    assert loaded[0]["must_call"][0]["arguments"] == {"fields": {"check_interval_seconds": None}}


def test_a_file_without_cases_says_so(tmp_path):
    with pytest.raises(cases.CaseFileError, match="holds no"):
        cases.load(write(tmp_path, "[instance]\ntime_zone = 'UTC'\n"))
