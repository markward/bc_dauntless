"""Player-AI motion handoff (_PlayerControl vs _step_ship_motion arbitration).

When a helm AI is installed on the player (MissionLib.SetPlayerAI — Orbit
Planet, All Stop, ...), the AI setpoints + engine/appc/ship_motion own the
transform: _PlayerControl.apply() must not zero the AI-set velocity
(host_loop's unconditional SetVelocity) nor integrate its own rotation on top
of the AI's. Handoff back must be seamless: AI removal resumes manual control
from the ship's ACTUAL motion (no snap), and manual flight input while an AI
is installed cancels the AI (BC: a manual helm order overrides the current
order).
"""
import App
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem
from engine.appc.ship_motion import _step_ship_motion
from engine.host_loop import _PlayerControl

_DT = 1.0 / 60.0
_MODEL_FWD = TGPoint3(0.0, 1.0, 0.0)


class _Keys:
    """Auto-vivifying key-code namespace with distinct codes per name."""
    _counter = iter(range(1000, 9000))

    def __getattr__(self, name):
        code = next(_Keys._counter)
        setattr(self, name, code)
        return code


class _Host:
    def __init__(self):
        self.keys = _Keys()
        self._pressed = set()
        self._held = set()

    def key_pressed(self, code):
        return code in self._pressed

    def key_state(self, code):
        return code in self._held


def _player_with_ies():
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(10.0)
    ies.SetMaxAccel(2.0)
    ies.SetMaxAngularVelocity(2.0)
    ies.SetMaxAngularAccel(1.0)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def _drive_integrator_to(ship, speed):
    """Park the ship-motion integrator at `speed` GU/s along model-forward
    (identity rotation → world +Y) and run one step so the ship publishes
    that velocity, exactly as a helm AI's setpoints would."""
    ship.SetSpeed(speed, _MODEL_FWD, PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship._current_speed = speed
    _step_ship_motion(ship, _DT)


def _rot_elements(ship):
    R = ship.GetWorldRotation()
    return [(c.x, c.y, c.z) for c in (R.GetCol(0), R.GetCol(1), R.GetCol(2))]


def test_ai_owned_apply_preserves_integrator_velocity_and_position():
    """The core Layer-4b bug: with an AI installed, apply() used to zero the
    velocity the motion integrator set that same tick and never translate."""
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())            # latch AI ownership

    _drive_integrator_to(player, 5.0)
    v = player.GetVelocity()
    assert abs(v.y - 5.0) < 1e-9
    pos_after_step = player.GetTranslate()
    p0 = (pos_after_step.x, pos_after_step.y, pos_after_step.z)

    pc.apply(player, _DT, _Host())            # must be a ship-motion no-op

    v = player.GetVelocity()
    assert abs(v.y - 5.0) < 1e-9, "apply() clobbered the AI-set velocity"
    p = player.GetTranslate()
    assert (p.x, p.y, p.z) == p0, "apply() moved the ship while AI owns it"
    assert p0[1] > 0.0, "integrator never translated the ship"


def test_ai_owned_apply_does_not_double_apply_rotation():
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())            # latch AI ownership
    # Stale manual rates must not be integrated while the AI owns the ship.
    pc._current_pitch_rate = 0.5
    pc._current_yaw_rate = 0.5
    pc._current_roll_rate = 0.5

    before = _rot_elements(player)
    pc.apply(player, _DT, _Host())
    assert _rot_elements(player) == before


def test_ai_removal_resumes_manual_control_without_speed_snap():
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())
    _drive_integrator_to(player, 5.0)

    player.ClearAI()                          # order finished / cleared
    pc.apply(player, _DT, _Host())

    # Resynced to the ship's real speed, then one normal braking ramp step
    # toward the throttle notch (impulse_level 0) at MaxAccel=2 — NOT a snap
    # to zero.
    assert 4.9 < pc._current_speed < 5.0
    v = player.GetVelocity()
    assert 4.9 < v.y < 5.0
    # The AI's setpoints are cleared so _step_ship_motion disengages.
    assert player._speed_setpoint is None
    assert player._target_angular_velocity_setpoint is None
    assert pc._ai_owned is False


def test_ai_removal_resyncs_angular_rates_with_sign_mapping():
    """ship._current_angular_velocity applies (x, z, y) about (X, Z, Y) with
    no negation; _apply_body_rotation negates yaw and roll. The handoff must
    map pitch ≡ cav.x, yaw ≡ −cav.z, roll ≡ −cav.y (then one ramp-toward-zero
    step runs in the same apply — allow that step, forbid a snap)."""
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())
    cav = player._current_angular_velocity
    cav.x, cav.y, cav.z = 0.6, -0.9, 0.9

    player.ClearAI()
    pc.apply(player, _DT, _Host())

    step = 1.0 * _DT + 1e-9    # MaxAngularAccel=1 → one ramp step toward 0
    assert abs(pc._current_pitch_rate - 0.6) <= step
    assert abs(pc._current_yaw_rate - (-0.9)) <= step
    assert abs(pc._current_roll_rate - 0.9) <= step


def test_manual_throttle_edge_cancels_ai_and_registers_same_tick():
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())
    _drive_integrator_to(player, 5.0)

    h = _Host()
    h._pressed.add(h.keys.KEY_5)              # manual throttle: impulse 5
    pc.apply(player, _DT, h)

    assert player.GetAI() is None, "manual input must cancel the helm AI"
    assert pc.impulse_level == 5
    assert pc._ai_owned is False
    # Resumed from the ship's real 5.0 GU/s, then one same-tick ramp step
    # toward the new impulse-5 target ((5/9)·MaxSpeed ≈ 5.56) — no snap.
    assert 4.9 < pc._current_speed < 5.1


def test_held_rotation_key_cancels_ai():
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())

    h = _Host()
    h._held.add(pc._input_map.code("yaw_left"))
    pc.apply(player, _DT, h)

    assert player.GetAI() is None


def test_alt_digit_press_does_not_wake_manual_control():
    """ALT+3 is the power-preset chord — it must not also register as a
    manual throttle edge that yanks control away from the helm AI.
    Finding 3."""
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())

    h = _Host()
    h._held.add(h.keys.KEY_LEFT_ALT)
    h._pressed.add(h.keys.KEY_3)
    pc.apply(player, _DT, h)

    assert player.GetAI() is not None, "ALT+digit must not wake manual control"


def test_ctrl_digit_press_does_not_wake_manual_control():
    """CTRL+2 is the maneuver-order chord — same suppression as ALT."""
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())

    h = _Host()
    h._held.add(h.keys.KEY_LEFT_CONTROL)
    h._pressed.add(h.keys.KEY_2)
    pc.apply(player, _DT, h)

    assert player.GetAI() is not None, "CTRL+digit must not wake manual control"


def test_scroll_throttle_nudge_cancels_ai():
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    pc.apply(player, _DT, _Host())

    pc.nudge_throttle(1)                      # wheel detent outside apply()
    pc.apply(player, _DT, _Host())

    assert player.GetAI() is None


def test_manual_takeover_aborts_in_system_warp_transit():
    """Cancelling the AI mid-warp must also abort the warp transit —
    otherwise the integrator keeps flying the ship across the system
    after the player took the conn."""
    pc = _PlayerControl()
    player = _player_with_ies()
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 5000.0, 0.0)
    player.SetAI(object())
    pc.apply(player, _DT, _Host())
    assert player.InSystemWarp(target, 295.0) == 1   # facing +Y, engages

    h = _Host()
    h._pressed.add(h.keys.KEY_5)                     # manual takeover
    pc.apply(player, _DT, h)

    assert player.GetAI() is None
    assert player._insystem_warp_transit is None
    assert player.IsDoingInSystemWarp() == 0


def test_manual_to_ai_handoff_seeds_ship_integrator():
    """Symmetric edge: when the AI takes over mid-flight, the ship-side ramp
    must start from the player's actual speed, not a stale value."""
    pc = _PlayerControl()
    player = _player_with_ies()
    pc._current_speed = 7.0
    pc._current_yaw_rate = 0.4

    player.SetAI(object())
    pc.apply(player, _DT, _Host())

    assert player._current_speed == 7.0
    cav = player._current_angular_velocity
    assert cav.z == -0.4


def test_speed_readout_reads_ship_velocity_under_ai():
    """The SPEED panel used to read _PlayerControl._current_speed, which is
    parked while an AI owns the ship — it must show the ship's real motion."""
    from engine.ui.weapons_display_panel import _speed_label_for
    from engine.units import GUPS_TO_KPH

    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetAI(object())
    player.SetVelocity(TGPoint3(3.0, 4.0, 0.0))   # |v| = 5 GU/s
    pc._current_speed = 0.0

    label = _speed_label_for(player, pc)
    assert str(int(5.0 * GUPS_TO_KPH)) in label


def test_speed_readout_keeps_control_speed_without_ai():
    from engine.ui.weapons_display_panel import _speed_label_for
    from engine.units import GUPS_TO_KPH

    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetVelocity(TGPoint3(3.0, 4.0, 0.0))   # must be ignored (no AI)
    pc._current_speed = 2.0
    pc.impulse_level = 3

    label = _speed_label_for(player, pc)
    assert str(int(2.0 * GUPS_TO_KPH)) in label
    assert "Speed 3" in label


def test_no_ai_manual_flight_path_unchanged():
    """Regression guard: without an AI the ship-motion path runs exactly as
    before — velocity published from _current_speed along facing, stationary
    ship publishes zero."""
    pc = _PlayerControl()
    player = _player_with_ies()
    player.SetVelocity(TGPoint3(9.0, 9.0, 9.0))   # stale, must be overwritten

    pc.apply(player, _DT, _Host())

    v = player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert pc._ai_owned is False
    assert player._speed_setpoint is None
