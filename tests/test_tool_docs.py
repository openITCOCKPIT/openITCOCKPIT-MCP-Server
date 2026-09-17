"""docs/tools.md is generated from the registered tools and must not drift from them."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import tool_docs  # noqa: E402


def test_tool_docs_are_current():
    assert (ROOT / "docs" / "tools.md").read_text(encoding="utf-8") == tool_docs.render(), (
        "docs/tools.md is out of date - run python scripts/tool_docs.py"
    )
