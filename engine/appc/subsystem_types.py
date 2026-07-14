"""Single source of truth for the CT_* <-> subsystem-class mapping.

The `CT_*` constants exposed by App.py for subsystem types (App.py:345-364)
are Property classes, NOT subsystem classes — `CT_HULL_SUBSYSTEM =
HullProperty`, `CT_WEAPON_SYSTEM = WeaponSystemProperty`, etc. (property sets
hold design-time templates; subsystems hold per-ship runtime state — see
App.py's comment block above the CT_* block).

Three SDK call shapes consume this mapping, and before this module existed
they disagreed:

  - `ShipClass.StartGetSubsystemMatch(CT_X)` — filter a ship's subsystems by
    class (matches every subsystem `isinstance` of the mapped class).
  - `pSubsystem.GetObjType()` — the subsystem's own most-specific CT_*
    constant (Conditions/ConditionCriticalSystemBelow.py:76,
    AI/Preprocessors.py:153).
  - `pSubsystem.IsTypeOf(CT_X)` — runtime class-id check on a subsystem
    instance (AI/Preprocessors.py:153).

This module is the ONE table both directions read, so they can never drift
apart again.
"""

from engine.appc.subsystems import (
    ShipSubsystem,
    SensorSubsystem,
    ImpulseEngineSubsystem,
    WarpEngineSubsystem,
    ShieldSubsystem,
    HullSubsystem,
    PowerSubsystem,
    RepairSubsystem,
    CloakingSubsystem,
)
from engine.appc.weapon_subsystems import (
    WeaponSystem,
    PhaserSystem,
    PulseWeaponSystem,
    TractorBeamSystem,
    TorpedoSystem,
)


def _ct_table():
    """Build the (CT_* constant, subsystem class) table, most-derived class
    first.

    Deferred (not module scope): it reads live `App.CT_*` attributes, and
    `App` imports `engine.appc.ships` (which imports `engine.appc.subsystems`)
    at module load time — importing `App` eagerly here would loop. Callers
    only ever reach this after both `engine.appc.subsystems` and
    `engine.appc.weapon_subsystems` have finished loading (see those modules'
    own import-order notes), so the class imports above are safe at module
    scope.

    Order matters for `ct_for_subsystem`: it walks this list top-to-bottom
    and returns the first `isinstance` match, so every subclass must appear
    before its base class (PhaserSystem before WeaponSystem, WeaponSystem
    before ShipSubsystem, ...).
    """
    import App
    return (
        (App.CT_PHASER_SYSTEM,             PhaserSystem),
        (App.CT_PULSE_WEAPON_SYSTEM,       PulseWeaponSystem),
        (App.CT_TRACTOR_BEAM_SYSTEM,       TractorBeamSystem),
        (App.CT_TORPEDO_SYSTEM,            TorpedoSystem),
        (App.CT_WEAPON_SYSTEM,             WeaponSystem),
        (App.CT_SENSOR_SUBSYSTEM,          SensorSubsystem),
        (App.CT_IMPULSE_ENGINE_SUBSYSTEM,  ImpulseEngineSubsystem),
        (App.CT_WARP_ENGINE_SUBSYSTEM,     WarpEngineSubsystem),
        (App.CT_SHIELD_SUBSYSTEM,          ShieldSubsystem),
        (App.CT_HULL_SUBSYSTEM,            HullSubsystem),
        (App.CT_POWER_SUBSYSTEM,           PowerSubsystem),
        (App.CT_REPAIR_SUBSYSTEM,          RepairSubsystem),
        (App.CT_CLOAKING_SUBSYSTEM,        CloakingSubsystem),
        # Base class LAST — CT_SHIP_SUBSYSTEM matches every subsystem, so it
        # must never shadow a more specific entry above it.
        (App.CT_SHIP_SUBSYSTEM,            ShipSubsystem),
    )


def subsystem_class_for_ct(ct):
    """The subsystem class a `CT_*` Property constant selects.

    Returns `None` for `ct is None` and for any unknown/unmapped `ct`
    (including a `_NamedStub`/`_Stub` fall-through for an undefined CT_*
    attribute) — callers use this to terminate SDK while-loops cleanly.
    """
    if ct is None:
        return None
    for ct_const, cls in _ct_table():
        if ct is ct_const:
            return cls
    return None


def ct_for_subsystem(subsystem):
    """The most-specific `CT_*` constant for `subsystem`, or `None` if it
    isn't a recognised subsystem class at all."""
    for ct_const, cls in _ct_table():
        if isinstance(subsystem, cls):
            return ct_const
    return None
