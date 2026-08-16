"""TGCreditAction.Play() delegates to its host SubtitleWindow."""
import pytest

from engine.appc.actions import TGCreditAction, TGCreditAction_Create
from engine.appc.windows import _SubtitleWindow


def test_play_calls_host_add_text():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("Disable the patrol", host, 0.5, 0.5, 5.0, 0.25, 0.5, 16)
    ca.Play()
    assert len(host._active_texts) == 1
    text, _start, _expires, _fade_in, _fade_out, _placement = host._active_texts[0]
    assert text == "Disable the patrol"


def test_play_uses_duration_from_args():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("hi", host, 0.0, 0.0, 7.5)
    ca.Play()
    text, start, expires, fade_in, fade_out, placement = host._active_texts[0]
    # Expiry is monotonic-now + 7.5; just check that 7.5 went through.
    # Approximate by reading the action's stored duration.
    assert ca._duration_s == 7.5


def test_play_is_idempotent():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("once", host, 0.0, 0.0, 3.0)
    ca.Play()
    ca.Play()
    assert len(host._active_texts) == 1


def test_play_with_short_args_uses_default_duration():
    # Short form: TGCreditAction_Create(text, subtitle_window).
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("brief", host)
    ca.Play()
    assert host._active_texts[0][0] == "brief"
    assert ca._duration_s == 3.0  # default matches SDK MissionLib.TextBanner


def test_play_no_op_when_host_lacks_add_text():
    # If TGCreditAction is constructed against a non-subtitle host
    # (some SDK paths chain credit actions on TGPane), don't crash.
    class _Bare: pass
    ca = TGCreditAction_Create("x", _Bare(), 0.0, 0.0, 1.0)
    ca.Play()  # must not raise


def test_play_after_restart_delivers_text_again():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("again", host, 0.0, 0.0, 2.0)
    ca.Play()
    assert len(host._active_texts) == 1
    ca.Restart()
    ca.Play()
    assert len(host._active_texts) == 2


# ── fade args ───────────────────────────────────────────────────────────────

def test_fade_args_are_read_from_the_sdk_call():
    # MissionLib.EpisodeTitleAction: (text, window, x, y, dur, fade_in, fade_out, size)
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("hi", host, 0.5, 0.025, 5.0, 0.25, 0.5, 12)
    assert ca._fade_in == 0.25
    assert ca._fade_out == 0.5


def test_fade_args_default_to_zero_on_short_form():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("brief", host)
    assert ca._fade_in == 0.0
    assert ca._fade_out == 0.0


def test_fades_reach_the_banner_slot():
    host = _SubtitleWindow()
    TGCreditAction_Create("Friendly Fire", host, 0.0, 0.25, 5.0, 0.25, 0.5, 12).Play()
    _text, _start, _expiry, fade_in, fade_out, _placement = host._active_texts[0]
    assert (fade_in, fade_out) == (0.25, 0.5)


# ── slot routing ────────────────────────────────────────────────────────────

def test_episode_title_routes_to_the_title_slot():
    # This is exactly what MissionLib.EpisodeTitleAction emits.
    host = _SubtitleWindow()
    TGCreditAction_Create(
        'Episode 1 - "Picking up the Pieces"', host,
        0.5, 0.025, 5.0, 0.25, 0.5, 12,
    ).Play()
    assert host._active_texts == []          # NOT a banner
    eyebrow, title, _start, _expiry, fade_in, fade_out = host._episode_title
    assert eyebrow == "Episode 1"
    assert title == "Picking up the Pieces"
    assert (fade_in, fade_out) == (0.25, 0.5)


def test_banner_text_does_not_route_to_the_title_slot():
    host = _SubtitleWindow()
    TGCreditAction_Create("Friendly Fire", host, 0.0, 0.25, 5.0, 0.25, 0.5, 12).Play()
    assert host._episode_title is None
    assert host._active_texts[0][0] == "Friendly Fire"


def test_episode_title_on_a_host_without_the_title_slot_falls_back_to_text():
    # Some SDK paths chain credit actions onto a TGPane (E8M2's MoviePane).
    # Such a host has neither slot -- must not raise.
    class _Bare: pass
    TGCreditAction_Create('Episode 1 - "Picking up the Pieces"', _Bare(),
                          0.5, 0.025, 5.0, 0.25, 0.5, 12).Play()  # must not raise


# ── banner placement (fX/fY/justify) ────────────────────────────────────────
# sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py:1966-1967 -- the SDK's own
# banner placement call, positional (text, window, fX, fY, dur, fadeIn,
# fadeOut, size, iJustifyX, iJustifyY). Root cause + rule:
# docs/superpowers/sdd/... /banner-placement-brief.md.

def test_e1m1_exact_call_captures_placement():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create(
        "Press 's' to skip introduction", host,
        0, 0.05, 10, 0.25, 0.5, 16,
        TGCreditAction.JUSTIFY_CENTER, TGCreditAction.JUSTIFY_TOP,
    )
    assert ca._placement["center_x"] is True
    assert ca._placement["y"] == pytest.approx(0.05)
    assert ca._placement["center_y"] is False


def test_placement_reaches_the_active_texts_entry():
    host = _SubtitleWindow()
    TGCreditAction_Create(
        "Press 's' to skip introduction", host,
        0, 0.05, 10, 0.25, 0.5, 16,
        TGCreditAction.JUSTIFY_CENTER, TGCreditAction.JUSTIFY_TOP,
    ).Play()
    placement = host._active_texts[0][5]
    assert placement["center_x"] is True
    assert placement["y"] == pytest.approx(0.05)


def test_bonus_case_fy_does_not_collapse_to_top():
    # E4M6's Bonus1 banner: fY=0.75, still JUSTIFY_TOP -- must not collapse
    # to a fixed top slot; the raw fY fraction must survive distinctly from
    # E1M1's fY=0.05.
    host = _SubtitleWindow()
    TGCreditAction_Create(
        "Bonus1", host, 0.05, 0.75, 4.0, 0.0, 0.0, 12,
        TGCreditAction.JUSTIFY_CENTER, TGCreditAction.JUSTIFY_TOP,
    ).Play()
    placement = host._active_texts[0][5]
    assert placement["y"] == pytest.approx(0.75)
    assert placement["center_y"] is False


def test_left_justified_x_uses_fx_fraction_not_centred():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create(
        "text", host, 0.2, 0.35, 3.0, 0.0, 0.0, 12,
        TGCreditAction.JUSTIFY_LEFT, TGCreditAction.JUSTIFY_TOP,
    )
    assert ca._placement["center_x"] is False
    assert ca._placement["x"] == pytest.approx(0.2)


def test_short_args_fall_back_to_centred_x_and_default_top_y():
    # TGCreditAction_Create(text, window) -- no x/y/justify at all.
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("brief", host)
    assert ca._placement["center_x"] is True
    assert ca._placement["center_y"] is False
    assert ca._placement["y"] == pytest.approx(0.05)


def test_unparseable_placement_args_do_not_raise():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create(
        "text", host, "not-a-number", None, 3.0, 0.0, 0.0, 12,
        TGCreditAction.JUSTIFY_CENTER, TGCreditAction.JUSTIFY_TOP,
    )  # must not raise
    assert ca._placement["center_x"] is True
    assert ca._placement["y"] == pytest.approx(0.05)
