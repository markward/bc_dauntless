"""BC's damage-geometry switches — real flags, not stubs.

`App.DamageableObject_{Set,Is}{DamageGeometry,VolumeDamageGeometry,
BreakableComponents}Enabled` are genuine Appc surface. Ours were `_NamedStub`s,
so every getter returned a truthy stub object instead of a flag.
`Maelstrom/Episode3/E3M1/E3M1.py:3001-3003` reads all three into
`g_pVisibleDamageState` to save and restore damage state around a cutscene, so
the stubs were being stored and written back.

Policy: in Dauntless damage is always on, so all three default enabled. The
setters are still honoured, because a mission legitimately wants to suppress
damage for a cutscene.

`BreakableComponents` is BC's name for pieces breaking off a ship. Hulls are
authored as named body sections (Galaxy: `Ent-D Saucer Section`, `Ent-D-Hull`,
`Ent-D-Neck`; Galor: `galor wing left`/`right`), so the pieces exist -- but the
names are ad-hoc per ship and nothing in the SDK designates breakability, so we
detect breaks from the hull volume rather than from authored data.

See docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md §8-§9.
"""

__all__ = [
    "BREAKABLE_MIN_RADIUS_GU",
    "reset",
    "set_damage_geometry_enabled", "is_damage_geometry_enabled",
    "set_volume_damage_geometry_enabled", "is_volume_damage_geometry_enabled",
    "set_breakable_components_enabled", "is_breakable_components_enabled",
    "breakables_allowed_for",
]

# A Cardassian Galor's bounding radius, MEASURED from its stock hull NIF
# (238.1 model units x BC_MODEL_SCALE 0.01). Mark's rule: a ship breaks into
# components only if it is larger than a Galor.
#
# The Nebula clears this by 1.5% (2.416), and how GetRadius should be derived is
# itself an open question against the clean-room reference -- so
# tests/unit/test_damage_geometry_flags.py pins the whole stock fleet either
# side of this line. Change the constant and that test tells you exactly which
# ships changed sides.
BREAKABLE_MIN_RADIUS_GU = 2.381

# In Dauntless damage is always on.
_DEFAULTS = {"damage": 1, "volume": 1, "breakable": 1}
_state = dict(_DEFAULTS)


def reset() -> None:
    """Restore launch defaults. For test isolation and mission swaps."""
    _state.update(_DEFAULTS)


def _set(key, value) -> None:
    try:
        _state[key] = 1 if int(value) else 0
    except (TypeError, ValueError):
        pass


def set_damage_geometry_enabled(value) -> None:
    _set("damage", value)


def is_damage_geometry_enabled() -> int:
    return _state["damage"]


def set_volume_damage_geometry_enabled(value) -> None:
    _set("volume", value)


def is_volume_damage_geometry_enabled() -> int:
    return _state["volume"]


def set_breakable_components_enabled(value) -> None:
    _set("breakable", value)


def is_breakable_components_enabled() -> int:
    return _state["breakable"]


def breakables_allowed_for(ship) -> bool:
    """True when `ship` may break into components: the global flag is on AND
    the hull is larger than a Galor. Strictly larger — a Galor is the floor,
    not the smallest qualifier."""
    if not _state["breakable"]:
        return False
    getter = getattr(ship, "GetRadius", None)
    if getter is None:
        return False
    try:
        radius = float(getter())
    except (TypeError, ValueError):
        return False
    return radius > BREAKABLE_MIN_RADIUS_GU
