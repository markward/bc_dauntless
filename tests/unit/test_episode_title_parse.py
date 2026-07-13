"""parse_episode_title() splits BC's single TGL episode string into two tiers.

The 8 EpNTitle strings below are the real values read from the shipped
game/data/TGL/Maelstrom/Maelstrom.tgl — note Ep6's trailing space and the
embedded punctuation in Ep8. Anything that does not match is not an episode
title and must fall through to the banner path (see TGCreditAction).
"""
import pytest

from engine.appc.actions import parse_episode_title


@pytest.mark.parametrize("raw,expected", [
    ('Episode 1 - "Picking up the Pieces"', ("Episode 1", "Picking up the Pieces")),
    ('Episode 2 - "Know Thine Enemy"',      ("Episode 2", "Know Thine Enemy")),
    ('Episode 3 - "Obscured by Clouds"',    ("Episode 3", "Obscured by Clouds")),
    ('Episode 4 - "Indefinite Presence"',   ("Episode 4", "Indefinite Presence")),
    ('Episode 5 - "Found and Lost"',        ("Episode 5", "Found and Lost")),
    ('Episode 6 - "Too Firm A Grasp" ',     ("Episode 6", "Too Firm A Grasp")),
    ('Episode 7 - "The Drawn Line"',        ("Episode 7", "The Drawn Line")),
    ('Episode 8 - "Arise, Fair Sun..."',    ("Episode 8", "Arise, Fair Sun...")),
])
def test_real_tgl_strings_parse_into_two_tiers(raw, expected):
    assert parse_episode_title(raw) == expected


@pytest.mark.parametrize("raw", [
    "Friendly Fire",
    "Saving",
    "Enroute To Starbase 12",
    "Chapter Three",
    "Episode",          # no number
    "Episode 9",        # number but no title
    "",
])
def test_non_episode_text_does_not_parse(raw):
    assert parse_episode_title(raw) is None


def test_unquoted_title_still_parses():
    # Mod text may omit the quotes; the hyphen + number prefix is the anchor.
    assert parse_episode_title("Episode 12 - Return to Sector 001") == (
        "Episode 12", "Return to Sector 001",
    )


def test_colon_separator_parses():
    assert parse_episode_title('Episode 3: "Obscured by Clouds"') == (
        "Episode 3", "Obscured by Clouds",
    )


def test_non_string_input_returns_none():
    assert parse_episode_title(None) is None
