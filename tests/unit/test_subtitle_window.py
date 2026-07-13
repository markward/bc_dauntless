"""Unit tests for the _SubtitleWindow SDK shim (engine/appc/windows.py)."""
import pytest

from engine.appc.windows import _SubtitleWindow, SubtitleWindow_Cast, SubtitleWindow


def test_initial_state_hidden_and_empty():
    sw = _SubtitleWindow()
    assert sw._visible is False
    assert sw._active_texts == []
    assert sw._id == "subtitle-0"


def test_set_on_off_toggle():
    sw = _SubtitleWindow()
    sw.SetOn()
    assert sw.IsOn() is True
    sw.SetOff()
    assert sw.IsOn() is False


def test_set_visible_alias_matches_set_on():
    sw = _SubtitleWindow()
    sw.SetVisible()
    assert sw.IsOn() is True


def test_set_position_for_mode_stores_int():
    sw = _SubtitleWindow()
    sw.SetPositionForMode(SubtitleWindow.SM_TACTICAL)
    assert sw._mode == SubtitleWindow.SM_TACTICAL


def test_add_text_records_start_expiry_and_fades(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw._add_text("hello", 5.0, 0.25, 0.5)
    assert sw._active_texts == [("hello", 100.0, 105.0, 0.25, 0.5)]


def test_add_text_defaults_to_no_fade(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("hello", 5.0)
    assert sw._active_texts == [("hello", 0.0, 5.0, 0.0, 0.0)]


def test_snapshot_returns_none_when_hidden_and_empty():
    sw = _SubtitleWindow()
    assert sw._snapshot(now=0.0) is None


def test_snapshot_returns_dict_when_visible():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert snap == {
        "type": "subtitle", "id": "subtitle-0",
        "visible": True, "mode": SubtitleWindow.SM_TACTICAL, "lines": [],
    }


def test_snapshot_prunes_expired_text(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("expired", 1.0)
    sw._add_text("alive", 10.0)
    snap = sw._snapshot(now=5.0)
    assert snap["lines"] == [{"text": "alive", "opacity": 1.0}]
    assert sw._active_texts == [("alive", 0.0, 10.0, 0.0, 0.0)]


def test_snapshot_visible_true_when_text_active_even_if_set_off(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("hello", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["lines"] == [{"text": "hello", "opacity": 1.0}]


def test_subtitle_window_class_exports_sm_constants():
    assert SubtitleWindow.SM_BRIDGE == 0
    assert SubtitleWindow.SM_TACTICAL == 1
    assert SubtitleWindow.SM_FELIX == 2
    assert SubtitleWindow.SM_NONFELIX == 3
    assert SubtitleWindow.SM_MAP == 4
    assert SubtitleWindow.SM_CINEMATIC == 5
    assert SubtitleWindow.SM_END_CINEMATIC == 6
    assert SubtitleWindow.SM_SPECIAL_FELIX == 7


def test_cast_returns_argument_if_subtitle_window():
    sw = _SubtitleWindow()
    assert SubtitleWindow_Cast(sw) is sw


def test_cast_returns_none_for_none():
    assert SubtitleWindow_Cast(None) is None


def test_cast_returns_none_for_non_subtitle_window():
    assert SubtitleWindow_Cast("not-a-window") is None
    assert SubtitleWindow_Cast(object()) is None
    assert SubtitleWindow_Cast(42) is None


def test_set_crew_line_records_slot(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw.set_crew_line("Tactical", "Shields holding", 4.0)
    assert sw._crew_line == ("Tactical", "Shields holding", 104.0)


def test_snapshot_includes_speaker_and_speech_when_crew_line_live(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw.set_crew_line("Helm", "Course laid in", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["speaker"] == "Helm"
    assert snap["speech"] == "Course laid in"
    assert snap["lines"] == []


def test_snapshot_prunes_expired_crew_line(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw.set_crew_line("XO", "Aye", 1.0)
    snap = sw._snapshot(now=5.0)   # crew line expired, nothing else visible
    assert snap is None


def test_snapshot_crew_line_expires_exactly_at_expiry(monkeypatch):
    # Boundary case: a crew line whose expiry == now is treated as expired
    # (the prune uses `<= now`, complementing _active_texts' `e > now`).
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw.set_crew_line("Science", "Scan complete", 3.0)  # expiry == 3.0
    assert sw._snapshot(now=2.999)["speech"] == "Scan complete"  # just live
    assert sw._snapshot(now=3.0) is None                          # exact boundary → gone


def test_snapshot_omits_speaker_keys_when_no_crew_line():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert "speaker" not in snap
    assert "speech" not in snap


# ── fade math ───────────────────────────────────────────────────────────────

def test_banner_fades_in_then_holds_then_fades_out(monkeypatch):
    # 10s banner starting at t=0, 0.25s fade-in, 0.5s fade-out.
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("banner", 10.0, 0.25, 0.5)

    def opacity(now):
        return sw._snapshot(now=now)["lines"][0]["opacity"]

    assert opacity(0.0) == pytest.approx(0.0)     # start of fade-in
    assert opacity(0.125) == pytest.approx(0.5)   # mid fade-in
    assert opacity(0.25) == pytest.approx(1.0)    # fade-in complete
    assert opacity(5.0) == pytest.approx(1.0)     # hold
    # NOTE: the fade-out window is [expiry - fade_out, expiry] = [9.5, 10.0];
    # 9.75 is that window's midpoint, so opacity is 0.5 there (matching the
    # _fade_opacity formula in windows.py verbatim), not 1.0 -- the brief's
    # draft test asserted 1.0 here, which is inconsistent with its own next
    # assertion (0.25 at 9.875) and with the given reference implementation.
    assert opacity(9.75) == pytest.approx(0.5)    # mid fade-out window
    assert opacity(9.875) == pytest.approx(0.25)  # 3/4 through fade-out
    assert opacity(9.999) == pytest.approx(0.002, abs=1e-3)


def test_zero_fade_args_give_hard_on(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("banner", 5.0, 0.0, 0.0)
    assert sw._snapshot(now=0.0)["lines"][0]["opacity"] == pytest.approx(1.0)
    assert sw._snapshot(now=4.999)["lines"][0]["opacity"] == pytest.approx(1.0)


def test_crew_line_has_no_fade(monkeypatch):
    # Crew captions carry no SDK fade args -- they pop on and pop off.
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw.set_crew_line("Helm", "Course laid in", 5.0)
    snap = sw._snapshot(now=0.0)
    assert snap["speech"] == "Course laid in"
    assert "speech_opacity" not in snap   # no fade channel for captions


# ── episode title slot ──────────────────────────────────────────────────────

def test_add_episode_title_records_slot(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    assert sw._episode_title == (
        "Episode 1", "Picking up the Pieces", 100.0, 105.0, 0.25, 0.5,
    )


def test_snapshot_includes_episode_title_when_live(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["title_eyebrow"] == "Episode 1"
    assert snap["title_text"] == "Picking up the Pieces"
    assert snap["title_opacity"] == pytest.approx(1.0)


def test_episode_title_fades(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    assert sw._snapshot(now=0.125)["title_opacity"] == pytest.approx(0.5)
    # See the analogous note in test_banner_fades_in_then_holds_then_fades_out:
    # 4.75 is the midpoint of the [4.5, 5.0] fade-out window -> 0.5, not 1.0.
    assert sw._snapshot(now=4.75)["title_opacity"] == pytest.approx(0.5)
    assert sw._snapshot(now=4.875)["title_opacity"] == pytest.approx(0.25)


def test_snapshot_prunes_expired_episode_title(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    assert sw._snapshot(now=10.0) is None       # expired, nothing else live
    assert sw._episode_title is None


def test_second_episode_title_replaces_the_first(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.0, 0.0)
    sw._add_episode_title("Episode 2", "Know Thine Enemy", 5.0, 0.0, 0.0)
    assert sw._snapshot(now=1.0)["title_eyebrow"] == "Episode 2"


def test_snapshot_omits_title_keys_when_no_episode_title():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert "title_eyebrow" not in snap
    assert "title_text" not in snap
    assert "title_opacity" not in snap


def test_all_three_slots_can_be_live_at_once(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("Friendly Fire", 5.0)
    sw.set_crew_line("Liu", "Captain.", 5.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["lines"] == [{"text": "Friendly Fire", "opacity": 1.0}]
    assert snap["speaker"] == "Liu"
    assert snap["title_text"] == "Picking up the Pieces"
    assert snap["visible"] is True
