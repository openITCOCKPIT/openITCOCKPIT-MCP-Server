"""The start-up banner.

Prints to stderr, never stdout: the stdio transport carries MCP messages on
stdout and any stray byte there corrupts the stream.

Set ``OITC_SHOW_BANNER=false`` to suppress it, for example when the log is
shipped to a collector that would rather not parse a picture.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import TextIO

from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.version import OITC_MIN_VERSION, __version__

log = logging.getLogger(__name__)

# The openITCOCKPIT mark, generated from the product favicon and embedded as a
# literal so rendering the banner needs no image library at runtime.
#
# One pixel is one full block, two columns wide - a terminal cell is about
# twice as tall as it is wide, so doubling the width keeps the mark from
# looking squashed. An earlier version packed two pixel rows into one row of
# ▀▄█ half-blocks, which halved the height but relied on the terminal font
# aligning three different glyphs seamlessly; plenty of them do not, and the
# mark came out streaked. One character, drawn solid, survives any font.
MARK = (
    "              ██████████████",
    "          ████████████████████",
    "      ████████████████████████████",
    "    ████████████████████████████████",
    "    ████████████████████████████████",
    "  ████████████████████████████████████",
    "  ██████████        ██████████",
    "████████                ████",
    "██████      ████████            ████████",
    "██████    ████████████  ████  ██████████",
    "██████    ████████████  ████████████████",
    "██████    ████████████  ██  ████████████",
    "██████      ██████████  ██    ██████████",
    "████████    ████████            ████████",
    "██████████              ████",
    "██████████████    ██████████████",
    "████████████████████████████████████",
    "██████████████████████████████████",
    "██████████████████████████████",
    "██████████████████████████",
)

# A 3x5 block glyph per character of "openITCOCKPIT", one row per pixel row, in
# the same solid blocks as the mark above. The five rows are, top to bottom:
# cap line, x-height line, middle, baseline, descender.
#
# "open" is set on x-height and "ITCOCKPIT" on cap height, the way the product
# wordmark does it, so the lowercase letters leave the cap row empty. Drawing
# them at cap height made o and O the very same glyph, and the whole thing read
# as OPENITCOCKPIT.
#
# The descender row exists for one stroke, the tail of the p. Without it a
# lowercase p has three rows for a bowl that needs a top, a counter and a
# bottom, so the counter has to go - and a p whose bowl is a solid block reads
# as an unrecognisable blob next to the hollow uppercase P.
_GLYPHS: dict[str, tuple[str, str, str, str, str]] = {
    "o": ("   ", "███", "█ █", "███", "   "),
    "p": ("   ", "███", "█ █", "███", "█  "),
    # The crossbar, open to the right, is what separates e from o.
    "e": ("   ", "███", "██ ", "███", "   "),
    "n": ("   ", "███", "█ █", "█ █", "   "),
    # Serifs, not a bare stem: a single column disappears between the wide
    # letters. The bottom row keeps it distinct from T.
    "I": ("███", " █ ", " █ ", "███", "   "),
    "T": ("███", " █ ", " █ ", " █ ", "   "),
    "C": ("███", "█  ", "█  ", "███", "   "),
    "O": ("███", "█ █", "█ █", "███", "   "),
    "K": ("█ █", "██ ", "█ █", "█ █", "   "),
    "P": ("███", "█ █", "███", "█  ", "   "),
}

#: Pixel rows per glyph. Every entry in _GLYPHS carries exactly this many.
_GLYPH_ROWS = 5

WORDMARK = "openITCOCKPIT"

#: Inner width of the box. The mark is 40 columns and the wordmark 51; this
#: leaves a margin and keeps the whole thing inside an 80-column terminal.
_WIDTH = 76


def _wordmark_rows() -> list[str]:
    return [" ".join(_GLYPHS[c][row] for c in WORDMARK) for row in range(_GLYPH_ROWS)]


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

    listening = "stdio" if settings.transport == "stdio" else f"http://{settings.host}:{settings.port}/mcp"

    tools = f"{total} registered, {mutating} of them mutating" if mutating else f"{total} registered, all read-only (write tools disabled)"

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
        _field("Version", f"{__version__}  (requires openITCOCKPIT {OITC_MIN_VERSION} or newer)"),
        _field("Instance", settings.baseurl),
        _field("TLS", tls),
        _field("Listening on", listening),
        _field("Tools", tools),
    ]
    lines += [blank, bottom]
    return "\n".join(lines)


def _to_ascii(banner: str) -> str:
    """Fallback for a stream that cannot encode the block characters."""
    table = str.maketrans({"█": "#", "─": "-", "│": "|",
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
            "openITCOCKPIT MCP Server %s (requires openITCOCKPIT %s or newer), instance %s, %d tools (%d mutating)",
            __version__, OITC_MIN_VERSION, settings.baseurl, total, mutating,
        )
        return
    out = stream or sys.stderr
    banner = render(settings, total, mutating)
    try:
        print(banner, file=out, flush=True)
    except UnicodeEncodeError:
        with contextlib.suppress(Exception):
            print(_to_ascii(banner), file=out, flush=True)
