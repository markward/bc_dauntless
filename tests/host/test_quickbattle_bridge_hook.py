"""QuickBattle consults the ship->bridge matrix by a once-installed wrap of
RecreatePlayer, so every caller -- Initialize, StartSimulation2,
EndSimulation, ShipDestroyed -- resolves the matrix at the moment of use.

Pure-Python hook-mechanics tests only, so this file stays importable (and
runnable) without the built _dauntless_host extension. The live-cascade tests
that actually drive load_quickbattle() through the extension live in
tests/host/test_quickbattle_bridge_hook_live.py, which carries its own
importorskip.
"""
import types

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
