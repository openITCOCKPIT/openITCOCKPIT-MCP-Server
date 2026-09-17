"""Runs kept in SQLite, so two models and two days stay comparable."""

from __future__ import annotations

import json

from openitcockpit_mcp.evaluation import report, store

META = {
    "instance": "https://oitc.example.test",
    "cases": "/cases/monitoring.toml",
    "toolsets": "health",
    "write": False,
    "samples": 2,
    "system_prompt": ["en/general", "en/health"],
}


def result(model: str, case: str, sample: int, passed: bool, failed: list[str] | None = None) -> dict:
    return {
        "model": model,
        "case": case,
        "sample": sample,
        "passed": passed,
        "failed": failed or [],
        "calls": [{"tool": "find_hosts"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "seconds": 1.5,
        "answer": "3 hosts are down.",
        "invented_names": [],
    }


def test_a_run_is_kept_per_model_with_its_samples(tmp_path):
    db = store.connect(tmp_path / "runs.sqlite")
    results = [result("big", "a", 0, True), result("big", "a", 1, False, ["must quote"]), result("small", "a", 0, True)]

    run_id = store.save(db, "big", META, results)

    (run,) = store.recent(db)
    assert (run["model"], run["passed"], run["total"]) == ("big", 1, 2)
    rows = list(db.execute("SELECT * FROM samples WHERE run_id = ?", (run_id,)))
    assert len(rows) == 2, "only this model's samples belong to its run"
    assert json.loads(rows[1]["failed"]) == ["must quote"]
    assert json.loads(rows[0]["tools_called"]) == ["find_hosts"]


def test_the_newest_run_of_every_model_is_what_a_comparison_shows(tmp_path):
    db = store.connect(tmp_path / "runs.sqlite")
    store.save(db, "big", META, [result("big", "a", 0, False)])
    store.save(db, "big", META, [result("big", "a", 0, True)])
    store.save(db, "small", META, [result("small", "a", 0, False)])

    runs = store.latest_per_model(db)

    assert [r["model"] for r in runs] == ["big", "small"]
    assert [r["passed"] for r in runs] == [1, 0], "the older run of big is not the one shown"


def test_the_comparison_reads_as_a_table(tmp_path):
    db = store.connect(tmp_path / "runs.sqlite")
    store.save(db, "big", META, [result("big", "hosts-down", 0, True)])
    store.save(db, "small", META, [result("small", "hosts-down", 0, False)])

    runs = store.latest_per_model(db)
    text = report.comparison(runs, store.per_case(db, [int(r["id"]) for r in runs]))

    assert "big" in text and "small" in text
    assert "hosts-down" in text
    assert "1/1" in text and "0/1" in text


def test_history_says_nothing_happened_yet(tmp_path):
    db = store.connect(tmp_path / "runs.sqlite")
    assert report.history(store.recent(db)) == "No run recorded yet."


def test_what_a_run_took_is_kept_next_to_whether_it_passed(tmp_path):
    """Two models that both pass can be far apart in turns and tokens."""
    db = store.connect(tmp_path / "runs.sqlite")
    results = [
        {**result("big", "a", 0, True), "steps": 2, "calls": [{"tool": "find_hosts"}]},
        {**result("big", "a", 1, True), "steps": 4, "calls": [{"tool": "find_hosts"}, {"tool": "get_host_health"}]},
    ]

    store.save(db, "big", META, results)

    (run,) = store.recent(db)
    assert (run["steps"], run["tool_calls"]) == (6, 3)
    assert (run["prompt_tokens"], run["completion_tokens"]) == (200, 40)
    rows = list(db.execute("SELECT steps, tool_calls FROM samples ORDER BY sample"))
    assert [(r["steps"], r["tool_calls"]) for r in rows] == [(2, 1), (4, 2)]


def test_a_database_from_an_older_version_gains_the_new_columns(tmp_path):
    path = tmp_path / "runs.sqlite"
    db = store.connect(path)
    db.execute("ALTER TABLE runs DROP COLUMN steps")
    db.commit()
    db.close()

    db = store.connect(path)

    assert "steps" in {row["name"] for row in db.execute("PRAGMA table_info(runs)")}


def test_every_tool_call_is_kept_so_a_run_reads_by_tool_too(tmp_path):
    db = store.connect(tmp_path / "runs.sqlite")
    results = [
        {
            **result("big", "a", 0, True),
            "calls": [{"tool": "find_hosts", "error": False}, {"tool": "get_host_health", "error": True}],
        },
        {**result("big", "b", 0, False), "calls": [{"tool": "find_hosts", "error": False}]},
    ]

    store.save(db, "big", META, results)
    rows = {r["tool"]: r for r in store.by_tool(db)}

    assert (rows["find_hosts"]["calls"], rows["find_hosts"]["cases"]) == (2, 2)
    assert rows["find_hosts"]["in_passing"] == 1, "one of the two answers using it failed"
    assert rows["get_host_health"]["errors"] == 1


def test_a_model_and_toolset_are_compared_by_their_newest_run(tmp_path):
    db = store.connect(tmp_path / "runs.sqlite")
    store.save(db, "big", META, [result("big", "a", 0, False)])
    store.save(db, "big", META, [result("big", "a", 0, True)])
    store.save(db, "big", {**META, "toolsets": "operations"}, [result("big", "a", 0, True)])

    rows = store.by_toolset(db)

    assert [(r["toolsets"], r["passed"]) for r in rows] == [("health", 1), ("operations", 1)]
