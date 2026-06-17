"""Dev-mode comm-set render flag: announce once per activation."""
import logging
import types

from engine.appc.comm_render_flag import CommRenderFlag


class _VS:
    def __init__(self, on, cam):
        self._on, self._cam = on, cam
    def IsOn(self):
        return self._on
    def GetRemoteCam(self):
        return self._cam


def _patch_dev(monkeypatch, enabled):
    import engine.appc.comm_render_flag as mod
    monkeypatch.setattr(mod.dev_mode, "is_enabled", lambda: enabled)


def test_announces_once_per_activation(monkeypatch, caplog):
    _patch_dev(monkeypatch, True)
    flag = CommRenderFlag()
    vs = _VS(1, object())
    with caplog.at_level(logging.WARNING):
        assert flag.notice(vs) is True       # first frame on -> announce
        assert flag.notice(vs) is False      # same activation -> silent
    assert sum("NOT IMPLEMENTED" in r.message for r in caplog.records) == 1


def test_reactivation_announces_again(monkeypatch):
    _patch_dev(monkeypatch, True)
    flag = CommRenderFlag()
    cam = object()
    assert flag.notice(_VS(1, cam)) is True
    assert flag.notice(_VS(0, cam)) is False   # off -> reset
    assert flag.notice(_VS(1, cam)) is True     # on again -> announce


def test_silent_when_no_remote_cam(monkeypatch):
    _patch_dev(monkeypatch, True)
    assert CommRenderFlag().notice(_VS(1, None)) is False


def test_silent_when_dev_mode_off(monkeypatch):
    _patch_dev(monkeypatch, False)
    assert CommRenderFlag().notice(_VS(1, object())) is False


def test_silent_when_viewscreen_none(monkeypatch):
    _patch_dev(monkeypatch, True)
    assert CommRenderFlag().notice(None) is False
