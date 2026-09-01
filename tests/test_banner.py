"""The start-up banner. Decoration must never take the server down."""

from __future__ import annotations

import io

from openitcockpit_mcp.banner import MARK, WORDMARK, render, show


def _box_widths(banner: str) -> set[int]:
    return {len(line) for line in banner.splitlines()}


def test_every_line_has_the_same_width(settings):
    """A ragged box means a value overflowed its column."""
    assert len(_box_widths(render(settings, 24, 15))) == 1


def test_a_long_instance_url_is_truncated_rather_than_breaking_the_box(settings):
    long_url = "https://" + "a" * 300 + ".example.org"
    banner = render(settings.model_copy(update={"baseurl": long_url}), 24, 15)
    assert len(_box_widths(banner)) == 1
    assert "…" in banner


def test_the_mark_and_wordmark_are_present(settings):
    banner = render(settings, 24, 15)
    assert MARK[0].strip() in banner
    assert len(WORDMARK) == 13


def test_mutating_tools_are_counted_when_present(settings):
    assert "39 registered, 14 of them mutating" in render(settings, 39, 14)


def test_a_read_only_server_says_so(settings):
    assert "all read-only (write tools disabled)" in render(settings, 24, 0)


def test_unverified_tls_is_called_out(settings):
    banner = render(settings.model_copy(update={"verify_tls": False}), 24, 0)
    assert "NOT VERIFIED" in banner


def test_a_ca_bundle_is_named(settings):
    banner = render(settings.model_copy(update={"ca_bundle": "/etc/ssl/ca.pem"}), 24, 0)
    assert "/etc/ssl/ca.pem" in banner


def test_stdio_reports_the_transport_not_a_url(settings):
    banner = render(settings.model_copy(update={"transport": "stdio"}), 24, 0)
    assert "stdio" in banner
    assert "http://" not in banner


def test_the_banner_can_be_switched_off(settings):
    out = io.StringIO()
    show(settings.model_copy(update={"show_banner": False}), 24, 15, stream=out)
    assert out.getvalue() == ""


def test_a_stream_that_cannot_encode_blocks_gets_ascii(settings):
    """A non-UTF-8 stream must not raise and kill the start-up."""
    raw = io.BytesIO()
    ascii_only = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
    show(settings, 24, 15, stream=ascii_only)
    ascii_only.flush()
    rendered = raw.getvalue().decode("ascii")
    assert "#" in rendered
    assert "Version" in rendered


def test_a_suppressed_banner_still_reports_the_facts_once(settings, caplog):
    """Nothing else logs the version and instance, so switching the banner off
    must not make them disappear."""
    out = io.StringIO()
    with caplog.at_level("INFO"):
        show(settings.model_copy(update={"show_banner": False}), 39, 14, stream=out)
    assert out.getvalue() == ""
    assert "2.0.0" in caplog.text
    assert settings.baseurl in caplog.text


def test_the_shown_banner_does_not_also_log_it(settings, caplog):
    out = io.StringIO()
    with caplog.at_level("INFO"):
        show(settings, 39, 14, stream=out)
    assert out.getvalue() != ""
    assert caplog.text == ""
