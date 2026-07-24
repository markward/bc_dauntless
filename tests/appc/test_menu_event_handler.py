"""CharacterClass.MenuEventHandler drives the bridge maincamera zoom."""
import pytest
import App
from engine.appc.bridge_set import ZoomCameraObjectClass


class _FakeBridge:
    def __init__(self, cam):
        self._cam = cam
    def GetCamera(self, name):
        return self._cam if name == "maincamera" else None


@pytest.fixture
def wired(monkeypatch):
    cam = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    cam.SetMinZoom(0.64); cam.SetMaxZoom(1.0); cam.SetZoomTime(0.375)
    bridge = _FakeBridge(cam)

    class _SM:
        def GetSet(self, name):
            return bridge if name == "bridge" else None
    monkeypatch.setattr(App, "g_kSetManager", _SM(), raising=False)
    return cam


def _char():
    from engine.appc.characters import CharacterClass_Create
    return CharacterClass_Create("", "")


def test_engage_zooms_camera_in(wired):
    _char().MenuEventHandler(True, (1.0, 2.0, 3.0), 0.5)
    assert wired.IsZoomed() == 1
    assert wired.active_factor == pytest.approx(0.5)
    assert wired.look_at == (1.0, 2.0, 3.0)


def test_disengage_zooms_camera_out(wired):
    c = _char()
    c.MenuEventHandler(True, None, 0.5)
    c.MenuEventHandler(False, None, 0.5)
    assert wired.IsZoomed() == 0


def test_forward_engage_keeps_none_lookat(wired):
    _char().MenuEventHandler(True, None, 0.5)
    assert wired.IsZoomed() == 1
    assert wired.look_at is None


def test_missing_maincamera_is_safe(monkeypatch):
    class _SM:
        def GetSet(self, name):
            return None
    monkeypatch.setattr(App, "g_kSetManager", _SM(), raising=False)
    _char().MenuEventHandler(True, None, 0.5)   # must not raise
