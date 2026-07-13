"""TGCreditAction.Play() delegates to its host SubtitleWindow."""
import pytest

from engine.appc.actions import TGCreditAction, TGCreditAction_Create
from engine.appc.windows import _SubtitleWindow


def test_play_calls_host_add_text():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("Disable the patrol", host, 0.5, 0.5, 5.0, 0.25, 0.5, 16)
    ca.Play()
    assert len(host._active_texts) == 1
    text, _start, _expires, _fade_in, _fade_out = host._active_texts[0]
    assert text == "Disable the patrol"


def test_play_uses_duration_from_args():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("hi", host, 0.0, 0.0, 7.5)
    ca.Play()
    text, start, expires, fade_in, fade_out = host._active_texts[0]
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
