"""Replaying a cassette: every request a tool made against a live instance, with its answer.

Requests are matched by path and query, so a tool that asks for something the
recording does not hold fails with a KeyError instead of being answered with
something else. Left out of the match: the ``angular`` flag, and the time window
``filter[from]``/``filter[to]``, which depends on when the test runs - the clock
tests cover how it is computed. A test that freezes the clock at the recording
time can match the start of the window with ``match_window=True``; the end stays
out, since it is rounded up to the minute the request is made in.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_URL = "https://oitc.example.test"

#: Query parameters a recording is not matched on.
UNMATCHED = {"angular", "filter[from]", "filter[to]"}


def key(path: str, params: dict, unmatched: set[str] = UNMATCHED) -> str:
    flat = {
        name: sorted(str(v) for v in (value if isinstance(value, list) else [value]))
        for name, value in params.items()
        if name not in unmatched
    }
    return path + json.dumps(flat, sort_keys=True)


class Cassette:
    def __init__(self, recording: Path, match_window: bool = False) -> None:
        self.unmatched = {"angular", "filter[to]"} if match_window else UNMATCHED
        self.tape = {key(entry["path"], entry["params"], self.unmatched): entry for entry in json.loads(recording.read_text())}
        self.requests: list[str] = []
        self.status_map_allowed = True

    def __call__(self, request):
        url = urlparse(request.url)
        path = url.path
        self.requests.append(path)
        if path.endswith("/statusmaps/index.json") and not self.status_map_allowed:
            return 403, {"Content-Type": "application/json"}, "{}"
        params = {k: v if len(v) > 1 or k.endswith("[]") else v[0] for k, v in parse_qs(url.query).items()}
        entry = self.tape[key(path, params, self.unmatched)]
        return entry["code"], {"Content-Type": "application/json"}, json.dumps(entry["response"])
