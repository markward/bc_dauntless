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


@pytest.mark.parametrize("raw", [
    # Hyphen/colon-shaped banners that are NOT episode titles -- these pin the
    # `Episode <n>` prefix anchor. Without it, a regex anchored purely on the
    # separator would treat any "X - Y" / "X: Y" banner as an episode title
    # card, which is exactly the false-positive this function exists to avoid.
    "Arriving at Starbase 12 - Docking Sequence",
    "Warning: hull breach",
    "Saving Game...",          # real shipped TextBanner string, no separator match needed but no false positive either
    "Sector 001 - Earth",      # numeric-but-not-an-episode
])
def test_hyphen_or_colon_banners_without_episode_prefix_do_not_parse(raw):
    assert parse_episode_title(raw) is None


def test_interior_whitespace_in_title_is_stripped():
    # Padding INSIDE the quotes (not just trailing whitespace outside them,
    # which the regex's `\s*$` already handles) must be stripped from the
    # captured title.
    assert parse_episode_title('Episode 6 - "Too Firm A Grasp "') == (
        "Episode 6", "Too Firm A Grasp",
    )


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
