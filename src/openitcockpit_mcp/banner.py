"""The start-up banner.

Prints to stderr, never stdout: the stdio transport carries MCP messages on
stdout and any stray byte there corrupts the stream.

Set ``OITC_SHOW_BANNER=false`` to suppress it, for example when the log is
shipped to a collector that would rather not parse a picture.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.version import OITC_COMPAT_VERSION, __version__

log = logging.getLogger(__name__)

# The openITCOCKPIT mark, generated from the product favicon at 20 columns by
# mapping each pair of pixel rows onto one half-block character. Embedded as a
# literal so rendering the banner needs no image library at runtime.
MARK = (
    "     ▄▄███████▄",
    "  ▄██████████████▄",
    " ▄████████████████▄",
    "▄███▀▀    ▀▀██▀",
    "███  ▄████▄ ▄▄ ▄████",
    "███  ██████ █▀██████",
    "███▄  ████▀ ▀  ▀████",
    "█████▄▄  ▄▄▄██▄▄",
    "█████████████████▀",
    "█████████████▀▀",
)

# Two-row half-block glyphs, one per character of "openITCOCKPIT".
_GLYPHS: dict[str, tuple[str, str]] = {
    "o": ("█▀█", "█▄█"),
    "p": ("█▀█", "█▀▀"),
    # The crossbar is what separates e from C, which is otherwise the same shape.
    "e": ("███", "█▄▄"),
    "n": ("█▄█", "█ █"),
    # Serifs, not a bare stem: a single column disappears between the wide
    # letters. The bottom row keeps it distinct from T.
    "I": ("▀█▀", "▄█▄"),
    "T": ("▀█▀", " █ "),
    "C": ("█▀▀", "█▄▄"),
    "O": ("█▀█", "█▄█"),
    "K": ("█▄▀", "█ █"),
    "P": ("█▀█", "█▀▀"),
}

WORDMARK = "openITCOCKPIT"

#: Inner width of the box. The wordmark is 51 columns; this leaves a margin and
#: keeps the whole thing inside a standard 80-column terminal.
_WIDTH = 76


def _wordmark_rows() -> list[str]:
    top = " ".join(_GLYPHS[c][0] for c in WORDMARK)
    bottom = " ".join(_GLYPHS[c][1] for c in WORDMARK)
    return [top, bottom]


def _as_block(rows: tuple[str, ...]) -> list[str]:
    """Pad rows to a common width so the picture is centred as one block.

    Centring each row on its own length would shift them against each other and
    break the shape.
    """
    width = max(len(row) for row in rows)
    return [row.ljust(width) for row in rows]


def _centre(text: str) -> str:
    return f"│{text.center(_WIDTH)}│"


def _field(label: str, value: str) -> str:
    """A label/value row, truncating an over-long value rather than breaking the box."""
    room = _WIDTH - 4 - 16
    if len(value) > room:
        value = value[: room - 1] + "…"
    return f"│  {label:<16}{value:<{_WIDTH - 18}}│"


def render(settings: Settings, total: int, mutating: int) -> str:
    top = "╭" + "─" * _WIDTH + "╮"
    bottom = "╰" + "─" * _WIDTH + "╯"
    blank = _centre("")

    if settings.transport == "stdio":
        listening = "stdio"
    else:
        listening = f"http://{settings.host}:{settings.port}/mcp"

    if mutating:
        tools = f"{total} registered, {mutating} of them mutating"
    else:
        tools = f"{total} registered, all read-only (write tools disabled)"

    if settings.ca_bundle:
        tls = f"verified against {settings.ca_bundle}"
    elif settings.verify_tls:
        tls = "verified"
    else:
        tls = "NOT VERIFIED (OITC_VERIFY_TLS=false)"

    lines = [top, blank]
    lines += [_centre(row) for row in _as_block(MARK)]
    lines += [blank]
    lines += [_centre(row) for row in _wordmark_rows()]
    lines += [blank, _centre("MCP Server"), blank]
    lines += [
        _field("Version", f"{__version__}  (built against openITCOCKPIT {OITC_COMPAT_VERSION})"),
        _field("Instance", settings.baseurl),
        _field("TLS", tls),
        _field("Listening on", listening),
        _field("Tools", tools),
    ]
    lines += [blank, bottom]
    return "\n".join(lines)


def _to_ascii(banner: str) -> str:
    """Fallback for a stream that cannot encode the block characters."""
    table = str.maketrans({"█": "#", "▀": "#", "▄": "#", "─": "-", "│": "|",
                           "╭": "+", "╮": "+", "╰": "+", "╯": "+", "…": "..."})
    return banner.translate(table)


def show(settings: Settings, total: int, mutating: int, stream: TextIO | None = None) -> None:
    """Write the banner to stderr unless OITC_SHOW_BANNER is off.

    Decoration must never take the server down: a stream that cannot encode the
    block characters gets an ASCII rendering, and anything else is swallowed.
    """
    if not settings.show_banner:
        # The banner is the only place these facts are reported, so a suppressed
        # banner becomes one log line rather than nothing.
        log.info(
            "openITCOCKPIT MCP Server %s (built against %s), instance %s, %d tools (%d mutating)",
            __version__, OITC_COMPAT_VERSION, settings.baseurl, total, mutating,
        )
        return
    out = stream or sys.stderr
    banner = render(settings, total, mutating)
    try:
        print(banner, file=out, flush=True)
    except UnicodeEncodeError:
        try:
            print(_to_ascii(banner), file=out, flush=True)
        except Exception:
            pass
