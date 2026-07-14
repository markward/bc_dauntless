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

The table also covers the two LEAF `CT_*` constants, `CT_WEAPON` and
`CT_ENERGY_WEAPON` (App.py:361-362) — `WeaponProperty`/`EnergyWeaponProperty`
templates for individual emitters (PhaserBank, PulseWeapon, TractorBeam,
TorpedoTube), not the top-level `WeaponSystem` that owns them. Real SDK
consumers: sdk/Build/scripts/loadspacehelper.py:229,242 (energy-weapon
difficulty scaling) and AI/Preprocessors.py:993 (RateSubsystemForTargeting).
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
    Weapon,
    WeaponSystem,
    PhaserSystem,
    PulseWeaponSystem,
    TractorBeamSystem,
    TorpedoSystem,
    PhaserBank,
    PulseWeapon,
    TractorBeam,
)

# Leaf energy-weapon emitters. In the real SDK these are
# `EnergyWeapon(Weapon)` and `PhaserBank`/`PulseWeapon`/`TractorBeam`
# (`TractorBeamProjector`) all inherit `EnergyWeapon` — a leaf emitter, never
# a `WeaponSystem`. Our engine's `PhaserBank`/`PulseWeapon`/`TractorBeam`
# instead inherit `WeaponSystem` directly (see weapon_subsystems.py — they
# mix in `_EnergyWeaponFireMixin` for charge/fire behaviour rather than a
# `Weapon` base), so they must be listed here by name rather than falling
# out of a `Weapon`/`WeaponSystem` isinstance check.
_ENERGY_WEAPON_CLASSES = (PhaserBank, PulseWeapon, TractorBeam)
# CT_WEAPON's real-SDK leaf hierarchy is `Weapon` + its `EnergyWeapon`
# descendants, so every energy-weapon leaf is also a CT_WEAPON.
_WEAPON_CLASSES = (Weapon,) + _ENERGY_WEAPON_CLASSES
# The four concrete top-level weapon-SYSTEM container classes. Deliberately
# NOT bare `WeaponSystem` — `_ENERGY_WEAPON_CLASSES` above also inherit
# `WeaponSystem` in this engine, so matching on bare `WeaponSystem` would
# make every leaf emitter also IsTypeOf(CT_WEAPON_SYSTEM), which is wrong
# (a phaser bank is not a weapon system; it lives inside one).
_WEAPON_SYSTEM_CLASSES = (
    PhaserSystem, PulseWeaponSystem, TractorBeamSystem, TorpedoSystem,
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
    before its base class (PhaserSystem before WeaponSystem, CT_ENERGY_WEAPON
    before CT_WEAPON, WeaponSystem before ShipSubsystem, ...). A `cls` entry
    may be a single class or a tuple of classes (isinstance accepts both).

    Memoised after first build (module-level `_CT_TABLE_CACHE`) — this table
    sits under `IsTypeOf`, which `RateSubsystemForTargeting` calls ~6x per
    subsystem per AI update, so rebuilding the 16-tuple (and re-importing
    `App`) on every call is wasted work.
    """
    global _CT_TABLE_CACHE
    if _CT_TABLE_CACHE is not None:
        return _CT_TABLE_CACHE
    import App
    _CT_TABLE_CACHE = (
        (App.CT_PHASER_SYSTEM,             PhaserSystem),
        (App.CT_PULSE_WEAPON_SYSTEM,       PulseWeaponSystem),
        (App.CT_TRACTOR_BEAM_SYSTEM,       TractorBeamSystem),
        (App.CT_TORPEDO_SYSTEM,            TorpedoSystem),
        (App.CT_WEAPON_SYSTEM,             _WEAPON_SYSTEM_CLASSES),
        # Leaf weapon emitters — see _ENERGY_WEAPON_CLASSES/_WEAPON_CLASSES
        # above. CT_ENERGY_WEAPON before CT_WEAPON: every energy weapon is
        # also a CT_WEAPON, so the narrower constant must win first.
        (App.CT_ENERGY_WEAPON,             _ENERGY_WEAPON_CLASSES),
        (App.CT_WEAPON,                    _WEAPON_CLASSES),
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
    return _CT_TABLE_CACHE


# Populated on first call to `_ct_table()`; see its docstring for why this is
# memoised rather than rebuilt (and `App` re-imported) on every lookup.
_CT_TABLE_CACHE = None


def subsystem_class_for_ct(ct):
    """The subsystem class (or tuple of classes) a `CT_*` Property constant
    selects.

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
