# engine/appc/subsystem_emitters.py
"""Subsystem damage emitters — sustained, state-driven plume state machine (Spec B).

This module owns POLICY: which subsystem state triggers which plume, where it
anchors, when it starts/stops/fades, the severity ladder, the per-ship budget,
and the mod registration table. It drives a particle-controller *backend*
through a narrow interface (see PlumeBackend); the real backend (Spec A) lives
behind the SDK Effects.py factory names and is built separately. Until then the
default backend is NullBackend (a safe no-op), so the host-loop pump does
nothing in production.

Spec: docs/superpowers/specs/2026-06-11-subsystem-damage-emitters-design.md
"""
from dataclasses import dataclass


class DirectionMode:
    FIXED_BODY_VECTOR    = 0   # emit along a fixed body-frame vector (nacelle -> aft)
    SPHERICAL            = 1   # radiate omnidirectionally (warp-core arcing)
    ALONG_SUBSYSTEM_AXIS = 2   # use the subsystem's own forward axis


# Severity tiers. DAMAGED/DISABLED are sustained registry rows; DESTROYED is a
# one-shot death-puff (not a registry row); NONE means "no plume desired".
TIER_NONE      = 0
TIER_DAMAGED   = 1
TIER_DISABLED  = 2
TIER_DESTROYED = 3


@dataclass(frozen=True)
class PlumeDescriptor:
    factory: str                    # Spec A / Effects.py factory name
    params: dict                    # factory kwargs sans the resolved emit frame
    direction_mode: int             # DirectionMode.*
    direction_vec: tuple = (0.0, -1.0, 0.0)   # body-frame unit vec for FIXED_BODY_VECTOR
    death_puff: "str | None" = None # one-shot factory on -> DESTROYED transition
    priority_bias: float = 0.0      # nudge in the budget sort


# ---- registry --------------------------------------------------------------

_registry = {}
_kind_aliases = {}

_DEFAULT_KINDS = {
    "WarpEngineSubsystem":   "warp_engine",
    "ImpulseEngineSubsystem": "impulse_engine",
    "PowerSubsystem":        "warp_core",
    "ShieldSubsystem":       "shield_generator",
}


def _builtin_table():
    """The default (kind, tier) -> descriptor table. Art values are tune-by-eye
    (spec §7); this fixes which factory + direction semantics."""
    aft = (0.0, -1.0, 0.0)
    return {
        ("warp_engine", TIER_DAMAGED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 2.0, "fLife": 1.2, "fSize": 0.6},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("warp_engine", TIER_DISABLED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 1.0, "fLife": 2.5, "fSize": 1.4},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("impulse_engine", TIER_DAMAGED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 1.5, "fLife": 1.2, "fSize": 0.5},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("impulse_engine", TIER_DISABLED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 0.8, "fLife": 2.5, "fSize": 1.2},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("warp_core", TIER_DAMAGED): PlumeDescriptor(
            "CreateExplosionPlumeHigh", {"fConeAngle": 120.0, "fLife": 1.0, "fSize": 0.4},
            DirectionMode.SPHERICAL, death_puff="CreateExplosionPlumeHigh"),
        ("warp_core", TIER_DISABLED): PlumeDescriptor(
            "CreateExplosionPlumeHigh", {"fConeAngle": 160.0, "fLife": 1.5, "fSize": 0.8},
            DirectionMode.SPHERICAL, death_puff="CreateExplosionPlumeHigh"),
    }


def reset_registry():
    """Restore the built-in table and drop all mod additions/aliases.
    Tests call this for isolation; production calls it once at import."""
    _registry.clear()
    _registry.update(_builtin_table())
    _kind_aliases.clear()


def register(kind, tier, descriptor):
    _registry[(kind, int(tier))] = descriptor


def unregister(kind, tier):
    _registry.pop((kind, int(tier)), None)


def resolve(kind, tier):
    return _registry.get((kind, int(tier)))


def register_kind_alias(class_token, kind):
    _kind_aliases[class_token] = kind


def subsystem_kind(sub):
    """Stable string token for a subsystem, or None if it has no plume mapping."""
    token = type(sub).__name__
    if token in _kind_aliases:
        return _kind_aliases[token]
    return _DEFAULT_KINDS.get(token)


def desired_tier(sub):
    """Resolve a subsystem's current state to a severity tier (most severe wins)."""
    if sub.IsDestroyed():
        return TIER_DESTROYED
    if sub.IsDisabled():
        return TIER_DISABLED
    if sub.IsDamaged():
        return TIER_DAMAGED
    return TIER_NONE


# ---- backend interface ------------------------------------------------------

class _NullHandle:
    def stop_emitting(self):       pass
    def has_live_particles(self):  return False


class NullBackend:
    """Default production backend until Spec A's real controllers land.
    Every call is a safe no-op; the manager runs its full state machine but
    nothing renders."""
    def create(self, factory, params, emit_pos_body, emit_dir, direction_mode):
        return _NullHandle()

    def fire_one_shot(self, factory, emit_pos_body, emit_dir):
        pass


reset_registry()
