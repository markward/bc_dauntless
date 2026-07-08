"""Phase C — cloak combat consequences (full faithful enforcement).

BC enforces the cloak's combat rules in the C++ engine (the SDK Python never
checks them), so Dauntless authors them here:

  * a cloaked / cloaking ship cannot fire (weapons forced offline);
  * engaging the cloak PRESERVES shield charge and lets shields recharge while
    hidden (2026-07-08 live-play fix — shields no longer come back empty);
  * a fully cloaked ship is undetectable to sensors / targeting;
  * the hull stays physically present — a collision still fires
    ET_CLOAKED_COLLISION.
"""
import App

from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (
    PhaserSystem, PhaserBank, ShieldSubsystem, CloakingSubsystem,
)


# ── shared setup (mirrors test_weapons_disabled_blocks_fire) ──────────────────

def _bank(name):
    b = PhaserBank(name)
    b._max_charge = 5.0
    b._charge_level = 5.0
    b._min_firing_charge = 3.0
    b._max_damage = 1.0
    b._max_damage_distance = 1000.0
    b._max_condition = 100.0
    b._condition = 100.0
    b._disabled_percentage = 0.25
    return b


def _cloak_ship():
    """Firing-ready PhaserSystem ship that also carries a cloaking device."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    for i in range(4):
        sys_.AddChildSubsystem(_bank(f"Bank{i}"))
    ship.SetPhaserSystem(sys_)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return ship, sys_


def _target():
    class _T:
        def GetWorldLocation(self):
            from engine.appc.math import TGPoint3
            return TGPoint3(0.0, 100.0, 0.0)
        def IsDead(self): return False
    return _T()


# ── Weapons lockout ───────────────────────────────────────────────────────────

def test_cloaking_ship_cannot_fire():
    ship, sys_ = _cloak_ship()
    target = _target()
    ship.GetCloakingSubsystem().StartCloaking()   # CLOAKING — trying to cloak
    sys_.StartFiring(target=target)
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0
    assert sys_._currently_firing == []


def test_engaging_cloak_stops_active_fire():
    """A ship already firing when it cloaks must go silent immediately — the
    StartFiring gate only blocks *new* fire, so StartCloaking actively stops the
    weapons (else a ship that cloaks mid-volley keeps shooting)."""
    ship, sys_ = _cloak_ship()
    target = _target()
    sys_.StartFiring(target=target)
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))
    ship.GetCloakingSubsystem().StartCloaking()
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0
    assert sys_._currently_firing == []


def test_fully_cloaked_ship_cannot_fire():
    ship, sys_ = _cloak_ship()
    target = _target()
    ship.GetCloakingSubsystem().InstantCloak()    # CLOAKED
    sys_.StartFiring(target=target)
    assert sys_._currently_firing == []


def test_decloaked_ship_fires_normally():
    """Positive control: with the cloak down, firing works as before."""
    ship, sys_ = _cloak_ship()
    target = _target()
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 0
    sys_.StartFiring(target=target)
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))


def test_decloaking_ship_may_fire():
    """A DECLOAKING ship is committed to reappearing and may fire again."""
    ship, sys_ = _cloak_ship()
    target = _target()
    cloak = ship.GetCloakingSubsystem()
    cloak.InstantCloak()
    cloak.StopCloaking()                          # DECLOAKING
    assert cloak.IsTryingToCloak() == 0
    sys_.StartFiring(target=target)
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))


# ── Shields forced down ───────────────────────────────────────────────────────

def _shielded_cloak_ship():
    ship = ShipClass()
    shields = ShieldSubsystem("Shields")
    shields.TurnOn()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(f, 1000.0)          # seeds current to max
        shields.SetShieldChargePerSecond(f, 100.0)
    ship.SetShieldSubsystem(shields)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return ship, shields


def test_engaging_cloak_preserves_shield_charge():
    # Cloaking no longer zeroes the shields: their charge is PRESERVED so a
    # decloaking ship isn't defenceless (2026-07-08 live-play fix).
    ship, shields = _shielded_cloak_ship()
    assert shields.GetCurrentShields(0) == 1000.0
    ship.GetCloakingSubsystem().StartCloaking()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert shields.GetCurrentShields(f) == 1000.0   # unchanged by cloak


def test_shields_recharge_while_cloaked():
    # Shields recharge during cloak (the ship rebuilds shields while hiding).
    ship, shields = _shielded_cloak_ship()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetCurrentShields(f, 500.0)             # partially drained
    ship.GetCloakingSubsystem().InstantCloak()          # fully cloaked
    shields.Update(1.0)                                  # 100/s * 1s
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert shields.GetCurrentShields(f) == 600.0     # recharged, not suppressed


def test_shields_recharge_while_cloaked_even_if_not_up():
    # "even if they aren't up": regen proceeds during cloak regardless of the
    # normal IsOn (raised) gate — a cloaked ship with lowered shields still
    # rebuilds their charge.
    ship, shields = _shielded_cloak_ship()
    shields.TurnOff()                                    # shields down (IsOn False), drained to 0
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetCurrentShields(f, 200.0)             # residual charge
    ship.GetCloakingSubsystem().InstantCloak()
    shields.Update(1.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert shields.GetCurrentShields(f) == 300.0     # recharged despite IsOn False


def test_shields_do_not_recharge_when_generator_offline():
    # A disabled/destroyed shield generator still can't recharge, even cloaked.
    ship, shields = _shielded_cloak_ship()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetCurrentShields(f, 200.0)
    shields.SetCondition(0.0)                             # destroyed generator -> offline
    ship.GetCloakingSubsystem().InstantCloak()
    shields.Update(1.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert shields.GetCurrentShields(f) == 200.0     # no regen while offline


# ── Sensor / targeting invisibility ───────────────────────────────────────────

def _sensor_ship():
    from engine.appc.subsystems import SensorSubsystem
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors._disabled_percentage = 0.5
    sensors.SetBaseSensorRange(5000.0)
    ship.SetSensorSubsystem(sensors)
    return ship


def test_can_detect_false_for_fully_cloaked_target():
    from engine.appc.sensor_detection import can_detect
    observer = _sensor_ship()
    target = ShipClass_Create("Galaxy")
    target.SetTranslateXYZ(0.0, 200.0, 0.0)       # well within range
    target.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))

    assert can_detect(observer, target) is True   # decloaked: visible
    target.GetCloakingSubsystem().InstantCloak()
    assert can_detect(observer, target) is False  # cloaked: gone


def test_cloaking_target_still_visible_until_complete():
    """Mid-cloak (CLOAKING) stays visible until the transition finishes —
    the SDK drops it on ET_CLOAK_COMPLETED, not at cloak start."""
    from engine.appc.sensor_detection import can_detect
    observer = _sensor_ship()
    target = ShipClass_Create("Galaxy")
    target.SetTranslateXYZ(0.0, 200.0, 0.0)
    target.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    target.GetCloakingSubsystem().StartCloaking()  # CLOAKING, not yet CLOAKED
    assert can_detect(observer, target) is True


# ── Collision keeps physics + fires ET_CLOAKED_COLLISION ──────────────────────

def test_collision_with_cloaked_ship_fires_event():
    import engine.appc.collisions as collisions

    fired = []
    class _Cap:
        pass
    cap = _Cap()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_CLOAKED_COLLISION, cap, __name__ + "._on_cloaked_collision")
    _COLLISION_SINK.clear()

    a = ShipClass_Create("Galaxy")
    a.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    a.GetCloakingSubsystem().InstantCloak()
    b = ShipClass_Create("Galaxy")

    collisions._emit_cloaked_collision(a, b)
    assert len(_COLLISION_SINK) == 1
    assert _COLLISION_SINK[0] is a                # source is the cloaked ship


def test_no_event_when_neither_party_cloaked():
    import engine.appc.collisions as collisions
    _COLLISION_SINK.clear()
    a = ShipClass_Create("Galaxy")
    b = ShipClass_Create("Galaxy")
    collisions._emit_cloaked_collision(a, b)
    assert _COLLISION_SINK == []


# Module-level event sink for the broadcast handler.
_COLLISION_SINK: list = []


def _on_cloaked_collision(handler, event):
    _COLLISION_SINK.append(event.GetSource())
