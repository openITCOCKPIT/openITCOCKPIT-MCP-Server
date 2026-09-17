"""Talking to the model under test: any OpenAI-compatible chat completions endpoint.

Nothing here is specific to a provider. An installation points this at whatever
it runs - a hosted API, a local server - and measures that model against its own
openITCOCKPIT.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

#: Answers that mean "try again": the endpoint is busy or briefly unavailable.
RETRY_ON = (429, 502, 503, 504)
ATTEMPTS = 5


@dataclass(frozen=True)
class Endpoint:
    """Where the model answers, and how to authenticate."""

    base_url: str
    api_key: str
    timeout_seconds: int = 300

    def complete(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
        """One chat completion. Retries a busy endpoint, raises anything else."""
        body = {"model": model, "messages": messages, "tools": tools, "max_tokens": max_tokens}
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
        )
        for attempt in range(ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code not in RETRY_ON or attempt == ATTEMPTS - 1:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError("unreachable")
