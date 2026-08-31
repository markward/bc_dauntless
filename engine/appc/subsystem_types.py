"""Single source of truth for the CT_* <-> subsystem-class mapping.

The `CT_*` constants exposed by App.py are BC's integer type tags. The class
each tag selects is registered in `engine.appc.object_types`, and for the
subsystem-type tags that class is a *Property* class, NOT a subsystem class —
`CT_HULL_SUBSYSTEM` -> `HullProperty`, `CT_WEAPON_SYSTEM` ->
`WeaponSystemProperty`, etc. (property sets hold design-time templates;
subsystems hold per-ship runtime state — see App.py's comment block above the
CT_* block). This module is what bridges a tag to the SUBSYSTEM class.

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
`CT_ENERGY_WEAPON` — `WeaponProperty`/`EnergyWeaponProperty` templates for
individual emitters (PhaserBank, PulseWeapon, TractorBeam, TorpedoTube), not
the top-level `WeaponSystem` that owns them. Real SDK consumers:
sdk/Build/scripts/loadspacehelper.py:229,242 (energy-weapon difficulty
scaling) and AI/Preprocessors.py:993 (RateSubsystemForTargeting).
"""

from engine.appc.constants_generated import MODULE_CONSTANTS
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
    """Build the (CT_* int tag, subsystem class) table, most-derived class
    first.

    Tags are read from `MODULE_CONSTANTS` — the generated q13 dump — rather
    than from live `App.CT_*` attributes. That is deliberate and it is what
    makes the memoisation below safe: the cache CANNOT be built before the
    constant table has been applied, because the table it reads IS the
    constant table. Reading `App` would have made the cache order-dependent,
    and a cache filled with pre-correction values would then be wrong forever
    with nothing to notice. It also removes the `import App` cycle this
    function used to have to defer around.

    Order matters for `ct_for_subsystem`: it walks this list top-to-bottom
    and returns the first `isinstance` match, so every subclass must appear
    before its base class (PhaserSystem before WeaponSystem, CT_ENERGY_WEAPON
    before CT_WEAPON, WeaponSystem before ShipSubsystem, ...). A `cls` entry
    may be a single class or a tuple of classes (isinstance accepts both).

    Memoised after first build (module-level `_CT_TABLE_CACHE`) — this table
    sits under `IsTypeOf`, which `RateSubsystemForTargeting` calls ~6x per
    subsystem per AI update, so rebuilding the 16-tuple on every call is
    wasted work.
    """
    global _CT_TABLE_CACHE
    if _CT_TABLE_CACHE is not None:
        return _CT_TABLE_CACHE
    _t = MODULE_CONSTANTS
    _CT_TABLE_CACHE = (
        (_t["CT_PHASER_SYSTEM"],             PhaserSystem),
        (_t["CT_PULSE_WEAPON_SYSTEM"],       PulseWeaponSystem),
        (_t["CT_TRACTOR_BEAM_SYSTEM"],       TractorBeamSystem),
        (_t["CT_TORPEDO_SYSTEM"],            TorpedoSystem),
        (_t["CT_WEAPON_SYSTEM"],             _WEAPON_SYSTEM_CLASSES),
        # Leaf weapon emitters — see _ENERGY_WEAPON_CLASSES/_WEAPON_CLASSES
        # above. CT_ENERGY_WEAPON before CT_WEAPON: every energy weapon is
        # also a CT_WEAPON, so the narrower constant must win first.
        (_t["CT_ENERGY_WEAPON"],             _ENERGY_WEAPON_CLASSES),
        (_t["CT_WEAPON"],                    _WEAPON_CLASSES),
        (_t["CT_SENSOR_SUBSYSTEM"],          SensorSubsystem),
        (_t["CT_IMPULSE_ENGINE_SUBSYSTEM"],  ImpulseEngineSubsystem),
        (_t["CT_WARP_ENGINE_SUBSYSTEM"],     WarpEngineSubsystem),
        (_t["CT_SHIELD_SUBSYSTEM"],          ShieldSubsystem),
        (_t["CT_HULL_SUBSYSTEM"],            HullSubsystem),
        (_t["CT_POWER_SUBSYSTEM"],           PowerSubsystem),
        (_t["CT_REPAIR_SUBSYSTEM"],          RepairSubsystem),
        (_t["CT_CLOAKING_SUBSYSTEM"],        CloakingSubsystem),
        # Base class LAST — CT_SHIP_SUBSYSTEM matches every subsystem, so it
        # must never shadow a more specific entry above it.
        (_t["CT_SHIP_SUBSYSTEM"],            ShipSubsystem),
    )
    return _CT_TABLE_CACHE


# Populated on first call to `_ct_table()`; see its docstring for why this is
# memoised, and for why reading the generated table (not `App`) is what makes
# memoising it safe.
_CT_TABLE_CACHE = None


def subsystem_class_for_ct(ct):
    """The subsystem class (or tuple of classes) a `CT_*` tag selects.

    `ct` is BC's integer type tag. A *Property* class is still accepted (that
    is what the tag resolves to in `engine.appc.object_types`, and engine
    callers and tests pass one directly) and is normalised to its tag first.

    Returns `None` for `ct is None` and for any unknown/unmapped `ct`
    (including a `_NamedStub`/`_Stub` fall-through for an undefined CT_*
    attribute) — callers use this to terminate SDK while-loops cleanly.
    """
    if ct is None:
        return None
    if isinstance(ct, type):
        # Back-compat: a Property class in the tag slot. object_types knows
        # which tag it was registered under.
        from engine.appc import object_types
        ct = object_types.tag_for(ct)
        if ct is None:
            return None
    # bool is an int subclass; never let True/False select tag 0/1.
    if not isinstance(ct, int) or isinstance(ct, bool):
        return None
    for ct_tag, cls in _ct_table():
        if ct == ct_tag:
            return cls
    return None


def ct_for_subsystem(subsystem):
    """The most-specific `CT_*` int tag for `subsystem`, or `None` if it
    isn't a recognised subsystem class at all."""
    for ct_tag, cls in _ct_table():
        if isinstance(subsystem, cls):
            return ct_tag
    return None
