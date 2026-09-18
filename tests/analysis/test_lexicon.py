"""Finding a page or setting by the words someone uses, and keeping secrets out of the answer."""

from __future__ import annotations

import pytest

from openitcockpit_mcp.analysis import lexicon


def test_words_ignore_case_umlauts_and_punctuation():
    assert lexicon.words("Absender-Adresse für E-Mail") == ["absender", "adresse", "fuer", "e", "mail"]


def test_a_word_matches_as_part_of_a_longer_one():
    assert lexicon.score("mail", [(1, "Mailserver")]) == 1


def test_a_short_word_only_matches_a_whole_word():
    assert lexicon.score("ip", [(1, "Zip archive")]) == 0
    assert lexicon.score("ip", [(1, "IP address")]) == 1


def test_a_word_counts_with_the_weight_of_its_best_field():
    assert lexicon.score("proxy", [(1, "Proxy"), (3, "Proxy Einstellungen")]) == 3


def test_every_query_word_adds_to_the_score():
    assert lexicon.score("mail absender", [(2, "Absender der Mail")]) == 4


def test_rank_puts_the_best_match_first_and_keeps_the_order_of_ties():
    items = ["mail relay", "notification mail", "mail sender address"]
    ranked = lexicon.rank(items, "mail sender", lambda text: [(1, text)], 5)
    assert ranked == ["mail sender address", "mail relay", "notification mail"]


def test_rank_drops_what_does_not_match_and_stops_at_the_limit():
    items = ["proxy", "proxy settings", "ldap"]
    assert lexicon.rank(items, "proxy", lambda text: [(1, text)], 1) == ["proxy"]


@pytest.mark.parametrize("key", ["SUDO_SERVER.API_KEY", "FRONTEND.LDAP.PASSWORD", "FRONTEND.SSO.CLIENT_SECRET", "X.ACCESS_KEY"])
def test_a_setting_that_may_hold_a_secret_keeps_its_value(key):
    assert lexicon.shown_value(key, "the-secret") == lexicon.HIDDEN


def test_an_ordinary_setting_shows_its_value():
    assert lexicon.shown_value("MONITORING.FROM_ADDRESS", "oitc@example.org") == "oitc@example.org"
