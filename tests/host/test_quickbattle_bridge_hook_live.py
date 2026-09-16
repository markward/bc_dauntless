"""Live-cascade half of the QuickBattle ship->bridge matrix hook tests: these
drive an actual load_quickbattle() through the built _dauntless_host
extension, so they need it importable. The pure-Python hook-mechanics tests
live in tests/host/test_quickbattle_bridge_hook.py, which must stay importable
(and runnable) in a checkout without the extension built -- importorskip here,
not there.
"""
import pytest

from engine import bridge_selection as bs

pytest.importorskip("_dauntless_host")


def test_load_quickbattle_installs_the_hook_every_time(monkeypatch, tmp_path):
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.bridge_pins = bs.load_bridge_pins(tmp_path / "bridges.json")

    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB
    assert getattr(QB.RecreatePlayer, "_dauntless_bridge_hook", False)
    # Boot player is a Galaxy => the default pin => GalaxyBridge.
    assert QB.g_sBridgeType == "GalaxyBridge"

    # A mission swap re-imports the SDK; the hook must be back.
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB2
    assert getattr(QB2.RecreatePlayer, "_dauntless_bridge_hook", False)


def test_boot_with_a_galaxy_to_sovereign_pin_loads_the_sovereign_bridge(
        monkeypatch, tmp_path):
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    (tmp_path / "bridges.json").write_text(
        '{"version": 1, "pins": {"Galaxy": "SovereignBridge"}}')
    controller.bridge_pins = bs.load_bridge_pins(tmp_path / "bridges.json")

    controller.loader.load_quickbattle()
    import App
    bridge = App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
    assert bridge.GetConfig() == "SovereignBridge"


def test_a_controller_with_no_matrix_does_not_inherit_an_earlier_controllers_pin(
        monkeypatch, tmp_path):
    """Regression (live): a SECOND HostController in the same process, built
    with bridge_pins left at its __init__ default of None, must get the
    SDK's own GalaxyBridge default -- not silently inherit an earlier
    controller's real Galaxy->SovereignBridge pin via a stale hook left on
    the process-wide cached QuickBattle.QuickBattle module.

    Asserts on the realized bridge SET's GetConfig(), not on
    QB.g_sBridgeType: _inject_quickbattle_player_defaults stomps that
    variable back after the cascade, which would mask exactly this bug from
    a test that only checked the module global.
    """
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    import App

    hl1, controller1 = _fresh_quickbattle_loader(monkeypatch)
    (tmp_path / "bridges.json").write_text(
        '{"version": 1, "pins": {"Galaxy": "SovereignBridge"}}')
    controller1.bridge_pins = bs.load_bridge_pins(tmp_path / "bridges.json")
    controller1.loader.load_quickbattle()

    hl2, controller2 = _fresh_quickbattle_loader(monkeypatch)
    assert controller2.bridge_pins is None
    controller2.loader.load_quickbattle()

    bridge = App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
    assert bridge.GetConfig() == "GalaxyBridge"
