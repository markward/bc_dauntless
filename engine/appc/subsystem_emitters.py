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


class _ActiveEmitter:
    __slots__ = ("tier", "handle", "fading")
    def __init__(self, tier, handle):
        self.tier = tier
        self.handle = handle
        self.fading = False


def _emit_frame(ship, sub, descriptor):
    """Return (emit_pos_body, emit_dir) for the backend.

    Position is the subsystem's body-frame hardpoint (world-SCALE offset, no
    model scale - CLAUDE.md hardpoint-position-frame). Direction depends on the
    descriptor's mode. The backend resolves these through the ship's live world
    matrix each frame (SetEmitFromObject), so the manager stays body-frame.
    """
    p = sub.GetPosition()
    emit_pos_body = (p.x, p.y, p.z)
    mode = descriptor.direction_mode
    if mode == DirectionMode.SPHERICAL:
        emit_dir = None
    elif mode == DirectionMode.ALONG_SUBSYSTEM_AXIS and hasattr(sub, "GetDirection"):
        d = sub.GetDirection()
        emit_dir = (d.x, d.y, d.z)
    else:  # FIXED_BODY_VECTOR (and the axis fallback)
        emit_dir = tuple(descriptor.direction_vec)
    return emit_pos_body, emit_dir


class PlumeManager:
    """Per-tick subsystem-plume state machine (spec §3, §4)."""

    def __init__(self, backend, *, n_per_ship=3, r_cull=4000.0):
        self.backend = backend
        self.n_per_ship = n_per_ship
        self.r_cull = r_cull          # None disables distance culling
        self._active = {}             # key -> _ActiveEmitter
        self._terminal = set()        # keys that reached DESTROYED (never re-emit)

    def active_count(self):
        return len(self._active)

    # -- main entry ----------------------------------------------------------

    def update(self, ships, camera_pos, dt):
        self._advance_faders()
        admitted = self._select_candidates(ships, camera_pos)  # Task 6 adds budget
        for key, ship, sub, kind, tier, descriptor in admitted:
            self._reconcile(key, ship, sub, tier, descriptor)
        self._suppress_unseen(admitted)

    # -- candidate selection (Task 6 replaces the body with the budget) ------

    def _select_candidates(self, ships, camera_pos):
        """Yield (key, ship, sub, kind, tier, descriptor) for every registered,
        damaged subsystem. No budget yet - Task 6 caps/culls/sorts this list."""
        out = []
        for ship in ships:
            for sub in ship.GetSubsystems():
                kind = subsystem_kind(sub)
                if kind is None:
                    continue
                tier = desired_tier(sub)
                if tier == TIER_NONE:
                    continue
                key = (ship.GetObjID(), id(sub))
                if tier == TIER_DESTROYED:
                    descriptor = None  # death-puff handled in _reconcile
                else:
                    descriptor = resolve(kind, tier)
                    if descriptor is None:
                        continue
                out.append((key, ship, sub, kind, tier, descriptor))
        return out

    # -- per-subsystem reconcile (spec §4.2 transition matrix) ---------------

    def _reconcile(self, key, ship, sub, tier, descriptor):
        if tier == TIER_DESTROYED:
            self._go_destroyed(key, ship, sub)
            return
        if key in self._terminal:
            return  # destroyed earlier; never re-emit
        existing = self._active.get(key)
        if existing is None:
            self._spawn(key, ship, sub, tier, descriptor)
        elif existing.fading:
            # was repaired/suppressed and re-damaged before fade finished
            self._spawn(key, ship, sub, tier, descriptor)
        elif existing.tier != tier:
            existing.handle.stop_emitting()  # swap tiers: fade old, spawn new
            self._spawn(key, ship, sub, tier, descriptor)

    def _spawn(self, key, ship, sub, tier, descriptor):
        emit_pos_body, emit_dir = _emit_frame(ship, sub, descriptor)
        handle = self.backend.create(descriptor.factory, descriptor.params,
                                     emit_pos_body, emit_dir, descriptor.direction_mode)
        self._active[key] = _ActiveEmitter(tier, handle)

    def _go_destroyed(self, key, ship, sub):
        if key in self._terminal:
            return  # puff already fired
        existing = self._active.pop(key, None)
        # find a death_puff factory: prefer the active tier's, else the kind's
        kind = subsystem_kind(sub)
        puff = None
        for t in (TIER_DISABLED, TIER_DAMAGED):
            d = resolve(kind, t)
            if d is not None and d.death_puff:
                puff = d.death_puff
                break
        if existing is not None:
            existing.handle.stop_emitting()  # fade the sustained plume
            existing.fading = True
            self._active[key] = existing     # keep lingering until particles die
        if puff is not None:
            p = sub.GetPosition()
            self.backend.fire_one_shot(puff, (p.x, p.y, p.z), None)
        self._terminal.add(key)

    # -- fade + suppression bookkeeping --------------------------------------

    def _advance_faders(self):
        for key in list(self._active.keys()):
            em = self._active[key]
            if em.fading and not em.handle.has_live_particles():
                del self._active[key]

    def _suppress_unseen(self, admitted):
        """Any active emitter whose subsystem is no longer a live candidate
        (repaired, or budget-suppressed) stops emitting and fades."""
        seen = {row[0] for row in admitted}
        for key, em in self._active.items():
            if key in seen or em.fading:
                continue
            em.handle.stop_emitting()
            em.fading = True


reset_registry()
