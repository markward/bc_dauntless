"""QuickBattle consults the ship->bridge matrix by a once-installed wrap of
RecreatePlayer, so every caller -- Initialize, StartSimulation2,
EndSimulation, ShipDestroyed -- resolves the matrix at the moment of use.
"""
import types

import pytest

from engine import bridge_selection as bs


class _Pins:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def resolve(self, ship):
        self.calls.append(ship)
        return self.mapping.get(ship, "GalaxyBridge")


def _fake_qb():
    """A stand-in QuickBattle module: the globals + RecreatePlayer shape the
    hook touches, plus callers that reach RecreatePlayer through the module
    global exactly as the SDK does."""
    qb = types.ModuleType("QB")
    qb.g_sPlayerType = "Galaxy"
    qb.g_sBridgeType = "GalaxyBridge"
    qb.loaded = []

    def RecreatePlayer():
        qb.loaded.append(qb.g_sBridgeType)
        return "player"
    qb.RecreatePlayer = RecreatePlayer

    def StartSimulation2():
        return qb.RecreatePlayer()          # module-global lookup, like the SDK
    qb.StartSimulation2 = StartSimulation2
    return qb


def test_hook_sets_bridge_type_from_the_matrix_before_the_original_runs():
    qb = _fake_qb()
    pins = _Pins({"Akira": "SovereignBridge"})
    assert bs.install_quickbattle_hook(qb, pins) is True
    qb.g_sPlayerType = "Akira"
    assert qb.RecreatePlayer() == "player"
    assert qb.loaded == ["SovereignBridge"]
    assert qb.g_sBridgeType == "SovereignBridge"


def test_sdk_internal_callers_go_through_the_wrap():
    qb = _fake_qb()
    bs.install_quickbattle_hook(qb, _Pins({"Galaxy": "SovereignBridge"}))
    qb.StartSimulation2()
    assert qb.loaded == ["SovereignBridge"]


def test_a_pin_changed_between_recreations_is_honoured_by_the_second():
    qb = _fake_qb()
    pins = _Pins({"Galaxy": "GalaxyBridge"})
    bs.install_quickbattle_hook(qb, pins)
    qb.RecreatePlayer()
    pins.mapping["Galaxy"] = "SovereignBridge"
    qb.RecreatePlayer()
    assert qb.loaded == ["GalaxyBridge", "SovereignBridge"]


def test_install_is_idempotent():
    qb = _fake_qb()
    pins = _Pins({})
    assert bs.install_quickbattle_hook(qb, pins) is True
    assert bs.install_quickbattle_hook(qb, pins) is False
    qb.RecreatePlayer()
    assert pins.calls == ["Galaxy"]            # resolved once, not twice


def test_install_without_pins_is_a_noop():
    qb = _fake_qb()
    orig = qb.RecreatePlayer
    assert bs.install_quickbattle_hook(qb, None) is False
    assert qb.RecreatePlayer is orig


def test_reinstall_with_different_pins_rewraps_instead_of_stacking():
    """Regression: sys.modules['QuickBattle.QuickBattle'] is never actually
    re-imported by a mission swap in this engine (reset_sdk_globals /
    _init_mission both leave it cached), so a second HostController with its
    own fresh BridgePins reaching an already-hooked module is a REAL shape,
    not a hypothetical -- two headless test runs sharing one process hit it
    directly. "Already installed" must not mean "bound to the first pins
    forever": install_quickbattle_hook must rebind to the new pins, and must
    rewrap the TRUE original (not stack on the stale wrapper, whose
    g_sBridgeType write would otherwise clobber the new one before
    RecreatePlayer's own body runs)."""
    qb = _fake_qb()
    first = _Pins({"Galaxy": "GalaxyBridge"})
    second = _Pins({"Galaxy": "SovereignBridge"})
    assert bs.install_quickbattle_hook(qb, first) is True
    assert bs.install_quickbattle_hook(qb, second) is True
    qb.RecreatePlayer()
    assert qb.loaded == ["SovereignBridge"]
    assert second.calls == ["Galaxy"]
    assert first.calls == []


def test_reinstall_with_no_pins_unwraps_a_stale_hook():
    """Regression: pins=None must not inherit a stale hook from an earlier
    controller in the same process. A controller with no matrix
    (bridge_pins left at its HostController.__init__ default of None) means
    'the SDK's own g_sBridgeType default stands' -- but if RecreatePlayer is
    already wrapped for a DIFFERENT (real) pins object, the old gate
    (`if pins is None: return False` before any unwrap check) left that
    stale wrapper installed, so the pins-less controller silently kept
    resolving through the FIRST controller's matrix instead of getting no
    resolution at all."""
    qb = _fake_qb()
    pins = _Pins({"Galaxy": "SovereignBridge"})
    assert bs.install_quickbattle_hook(qb, pins) is True
    assert bs.install_quickbattle_hook(qb, None) is False
    assert not hasattr(qb.RecreatePlayer, "_dauntless_bridge_hook")
    before = qb.g_sBridgeType
    qb.RecreatePlayer()
    assert qb.g_sBridgeType == before
    assert pins.calls == []                    # the stale pins are never consulted


# ---- live cascade ------------------------------------------------------------

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
