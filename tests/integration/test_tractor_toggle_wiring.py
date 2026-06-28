"""Tractor toggle → StartFiring wiring.

In stock BC the C++ TacWeaponsCtrl widget engages the tractor when the beam
toggle is clicked; our engine had no such widget, so toggling did nothing.
App._TacWeaponsCtrl now reproduces that behaviour: ET_OTHER_BEAM_TOGGLE_CLICKED
→ BridgeHandlers.ToggleTractorBeam (flips the toggle + re-fires the event) →
TacWeaponsCtrl → StartFiring/StopFiring on the player's WG_TRACTOR system.

Pins both the engine-side handler in isolation and the full SDK chain.
"""
from unittest.mock import patch

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TractorBeam, TractorBeamSystem
from engine.appc.properties import TractorBeamProperty, WeaponSystemProperty


def _make_emitter(name):
    emitter = TractorBeam(name)
    prop = TractorBeamProperty(name)
    prop.SetMaxCharge(5.0)
    prop.SetMinFiringCharge(3.0)
    emitter.SetProperty(prop)
    emitter._max_charge = 5.0
    emitter._min_firing_charge = 3.0
    emitter._normal_discharge_rate = 1.0
    emitter._recharge_rate = 0.5
    emitter._charge_level = 5.0
    emitter._armed = True
    return emitter


def _player_with_tractor(with_tractor=True):
    ship = ShipClass_Create("Player")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    if with_tractor:
        parent = TractorBeamSystem("Tractors")
        parent.TurnOn()
        parent.SetProperty(WeaponSystemProperty("Tractors"))
        parent.SetSingleFire(1)
        parent._parent_ship = ship
        ship._tractor_beam_system = parent
        parent.AddChildSubsystem(_make_emitter("Aft Tractor"))
    return ship


def _target():
    t = ShipClass_Create("Target")
    t.SetWorldLocation(TGPoint3(0, 50, 0))
    return t


def _fresh_ctrl():
    """Reset the TacWeaponsCtrl singleton's toggle to a known-off state."""
    ctrl = App.TacWeaponsCtrl_GetTacWeaponsCtrl()
    ctrl.GetBeamToggle().SetState(0)
    return ctrl


# ── Engine handler in isolation ──────────────────────────────────────────────

def test_handler_engages_then_disengages():
    player = _player_with_tractor()
    target = _target()
    player.SetTarget(target)
    tractor = player.GetWeaponSystemGroup(App.ShipClass.WG_TRACTOR)
    ctrl = _fresh_ctrl()

    with patch("MissionLib.GetPlayer", return_value=player), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        ctrl.GetBeamToggle().SetState(1)
        App._tac_weapons_beam_toggled(ctrl, None)
        assert tractor.IsFiring() == 1, "toggle-on must StartFiring the tractor"

        ctrl.GetBeamToggle().SetState(0)
        App._tac_weapons_beam_toggled(ctrl, None)
        assert tractor.IsFiring() == 0, "toggle-off must StopFiring the tractor"


def test_handler_no_target_snaps_toggle_off():
    player = _player_with_tractor()   # no target set
    tractor = player.GetWeaponSystemGroup(App.ShipClass.WG_TRACTOR)
    ctrl = _fresh_ctrl()
    with patch("MissionLib.GetPlayer", return_value=player), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        ctrl.GetBeamToggle().SetState(1)
        App._tac_weapons_beam_toggled(ctrl, None)
    assert tractor.IsFiring() == 0
    assert ctrl.GetBeamToggle().GetState() == 0


def test_handler_noops_without_tractor_system():
    player = _player_with_tractor(with_tractor=False)
    ctrl = _fresh_ctrl()
    with patch("MissionLib.GetPlayer", return_value=player):
        ctrl.GetBeamToggle().SetState(1)
        App._tac_weapons_beam_toggled(ctrl, None)   # must not raise


# ── Re-fired event delivery: ctrl responds via the event manager ─────────────
#
# BridgeHandlers.ToggleTractorBeam flips the toggle then re-fires
# ET_OTHER_BEAM_TOGGLE_CLICKED with the TacWeaponsCtrl as destination
# (App.g_kEventManager.AddEvent).  This pins the second half of that chain — the
# ctrl, registered as it is, engages/disengages when the event is delivered.
# (Driving BridgeHandlers itself in-test is meaningless: conftest replaces its
# `App` with a stub, so it operates on stubs; in the live engine it gets the
# real App and the full chain works.)

def _fire_toggle_event(ctrl):
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_OTHER_BEAM_TOGGLE_CLICKED)
    ev.SetDestination(ctrl)
    App.g_kEventManager.AddEvent(ev)


def test_refired_event_engages_then_disengages():
    player = _player_with_tractor()
    target = _target()
    player.SetTarget(target)
    tractor = player.GetWeaponSystemGroup(App.ShipClass.WG_TRACTOR)
    ctrl = _fresh_ctrl()

    with patch("MissionLib.GetPlayer", return_value=player), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        ctrl.GetBeamToggle().SetState(1)   # BridgeHandlers flipped it on
        _fire_toggle_event(ctrl)
        assert tractor.IsFiring() == 1

        ctrl.GetBeamToggle().SetState(0)   # BridgeHandlers flipped it off
        _fire_toggle_event(ctrl)
        assert tractor.IsFiring() == 0


# ── Alt+T input poller: chord posts ET_OTHER_BEAM_TOGGLE_CLICKED to the TCW ──

class _Keys:
    KEY_T = 1
    KEY_LEFT_ALT = 2
    KEY_RIGHT_ALT = 3


class _Host:
    """Fake host exposing key_state + a keys submodule for the poller."""
    keys = _Keys()
    def __init__(self, down):  self._down = set(down)
    def key_state(self, code): return 1 if code in self._down else 0


def test_alt_t_chord_toggles_rising_edge_only():
    import engine.host_loop as hl
    hl._tractor_toggle_prev = False

    calls = []
    real = App.ToggleTractorFromInput
    try:
        App.ToggleTractorFromInput = lambda: calls.append(1)
        # T alone (no Alt) → nothing.
        hl._poll_tractor_toggle(_Host({_Keys.KEY_T}))
        assert calls == []
        # Alt held + T pressed → one toggle on the rising edge.
        hl._poll_tractor_toggle(_Host({_Keys.KEY_T, _Keys.KEY_LEFT_ALT}))
        assert len(calls) == 1
        # Chord still held → no repeat.
        hl._poll_tractor_toggle(_Host({_Keys.KEY_T, _Keys.KEY_LEFT_ALT}))
        assert len(calls) == 1
        # Release, press again → a second toggle.
        hl._poll_tractor_toggle(_Host(set()))
        hl._poll_tractor_toggle(_Host({_Keys.KEY_T, _Keys.KEY_RIGHT_ALT}))
        assert len(calls) == 2
    finally:
        App.ToggleTractorFromInput = real
        hl._tractor_toggle_prev = False


def test_toggle_from_input_engages_then_disengages():
    player = _player_with_tractor()
    target = _target()
    player.SetTarget(target)
    tractor = player.GetWeaponSystemGroup(App.ShipClass.WG_TRACTOR)
    App.TacWeaponsCtrl_GetTacWeaponsCtrl().GetBeamToggle().SetState(0)
    with patch("MissionLib.GetPlayer", return_value=player), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.ToggleTractorFromInput()
        assert tractor.IsFiring() == 1
        App.ToggleTractorFromInput()
        assert tractor.IsFiring() == 0
