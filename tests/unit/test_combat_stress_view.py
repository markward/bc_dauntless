"""combat_stress can be watched from outside the ship.

The mission loads a bridge and stays on it, so a capture of it measures the
bridge view only: the crew are drawn and posed, and costs that only the
exterior view pays (the hull from the chase camera, anything the bridge
covers) never show. DAUNTLESS_DEV_VIEW=exterior switches to the exterior
view a moment after Initialize, as felix_destroy and vesuvi_dust_cloud do."""
import App
import tools.mission_harness as mh
from engine.dev_missions import combat_stress as cs

MODULE = "engine.dev_missions.combat_stress"


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def _initialize(monkeypatch, view):
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    if view is None:
        monkeypatch.delenv("DAUNTLESS_DEV_VIEW", raising=False)
    else:
        monkeypatch.setenv("DAUNTLESS_DEV_VIEW", view)
    mh.setup_sdk()
    status, exc = mh.run_mission(MODULE)
    assert status == "pass", exc


def test_the_view_action_shows_the_exterior_when_asked(monkeypatch):
    _initialize(monkeypatch, "exterior")
    top = App.TopWindow_GetTopWindow()
    top.ForceBridgeVisible()
    cs.ViewAction(None)
    assert top.IsTacticalVisible()
    assert not top.IsBridgeVisible()


def test_the_view_action_leaves_the_bridge_by_default(monkeypatch):
    _initialize(monkeypatch, None)
    top = App.TopWindow_GetTopWindow()
    top.ForceBridgeVisible()
    cs.ViewAction(None)
    assert top.IsBridgeVisible()


def test_the_switch_is_scheduled_after_initialize(monkeypatch):
    """Initialize queues the switch rather than flipping the view while the
    bridge is still being set up; the delay is short so the measured window
    is all exterior."""
    _initialize(monkeypatch, "exterior")
    assert 0.0 < cs.VIEW_AFTER_S <= 2.0
