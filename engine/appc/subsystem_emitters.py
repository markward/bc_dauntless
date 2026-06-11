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


def _camera_distance(ship, camera_pos):
    """Euclidean distance from ship world location to camera, or None if the
    camera position is unknown (proximity term then drops out)."""
    if camera_pos is None or not hasattr(ship, "GetWorldLocation"):
        return None
    loc = ship.GetWorldLocation()
    dx = loc.x - camera_pos[0]
    dy = loc.y - camera_pos[1]
    dz = loc.z - camera_pos[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5


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
        self._seen = set()            # keys observed at least once this manager's lifetime

    def active_count(self):
        return len(self._active)

    # -- main entry ----------------------------------------------------------

    def update(self, ships, camera_pos, dt):
        # dt: reserved for future timed-fade behaviour; unused today.
        self._advance_faders()
        admitted = self._select_candidates(ships, camera_pos)  # Task 6 adds budget
        for key, ship, sub, kind, tier, descriptor in admitted:
            self._reconcile(key, ship, sub, tier, descriptor)
        self._suppress_unseen(admitted)

    # -- candidate selection (Task 6 replaces the body with the budget) ------

    def _select_candidates(self, ships, camera_pos):
        """Per-ship: gather registered damaged subsystems, distance-cull whole
        ships, sort sustained candidates by (severity desc, priority_bias desc),
        and admit the top n_per_ship (spec §4.3). Proximity is uniform within a
        ship, so it is not a per-ship tiebreaker; it only orders ships against
        each other for reconcile sequencing (see the cross-ship sort below)."""
        out = []
        for ship in ships:
            dist = _camera_distance(ship, camera_pos)
            if self.r_cull is not None and dist is not None and dist > self.r_cull:
                continue
            cands = []
            for sub in ship.GetSubsystems():
                kind = subsystem_kind(sub)
                if kind is None:
                    continue
                tier = desired_tier(sub)
                if tier == TIER_NONE:
                    continue
                key = (ship.GetObjID(), id(sub))
                if tier == TIER_DESTROYED:
                    cands.append((key, ship, sub, kind, tier, None, 0.0))
                    continue
                descriptor = resolve(kind, tier)
                if descriptor is None:
                    continue
                cands.append((key, ship, sub, kind, tier, descriptor,
                              descriptor.priority_bias))
            # DESTROYED is a one-shot and must never consume a sustained slot:
            destroyed = [c for c in cands if c[4] == TIER_DESTROYED]
            sustained = [c for c in cands if c[4] != TIER_DESTROYED]
            # sort sustained by severity, then bias (proximity is per-ship-uniform)
            sustained.sort(key=lambda c: (c[4], c[6]), reverse=True)
            admitted = destroyed + sustained[:self.n_per_ship]
            # out rows are 7-tuples: (key, ship, sub, kind, tier, descriptor, dist).
            # Note index 6 is `dist` here, whereas in `cands` index 6 was priority_bias.
            for c in admitted:
                out.append((c[0], c[1], c[2], c[3], c[4], c[5], dist))
        # cross-ship proximity ordering (nearest first). This does NOT change
        # which plumes are admitted (already capped per-ship above); it only
        # makes reconcile call order deterministic. Ships with unknown distance
        # (None) sort as 0.0 / nearest.
        out.sort(key=lambda r: (r[6] if r[6] is not None else 0.0))
        # return the 6-tuple the rest of the manager expects
        return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in out]

    # -- per-subsystem reconcile (spec §4.2 transition matrix) ---------------

    def _reconcile(self, key, ship, sub, tier, descriptor):
        first_sight = key not in self._seen
        self._seen.add(key)
        if tier == TIER_DESTROYED:
            self._go_destroyed(key, ship, sub, first_sight)
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

    def _go_destroyed(self, key, ship, sub, first_sight):
        if key in self._terminal:
            return
        existing = self._active.pop(key, None)
        if first_sight and existing is None:
            # Never observed alive in this session: either loaded already-
            # destroyed (spec §4.6), or never admitted to the budget before
            # dying. No live transition to punctuate -> no puff.
            self._terminal.add(key)
            return
        # death_puff: use the most-severe registered puff for this kind
        # (DISABLED before DAMAGED). Both share one puff in the builtin table.
        kind = subsystem_kind(sub)
        puff = None
        for t in (TIER_DISABLED, TIER_DAMAGED):
            d = resolve(kind, t)
            if d is not None and d.death_puff:
                puff = d.death_puff
                break
        if existing is not None:
            existing.handle.stop_emitting()
            existing.fading = True
            self._active[key] = existing
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
        admitted_keys = {row[0] for row in admitted}
        for key, em in self._active.items():
            if key in admitted_keys or em.fading:
                continue
            em.handle.stop_emitting()
            em.fading = True


# ---- module singleton + host-loop entry point ------------------------------

_backend = None        # set via set_backend(); defaults to NullBackend
_manager = None


def set_backend(backend):
    """Install the particle-controller backend (Spec A in production; a fake in
    tests). Resets the manager so the next pump rebuilds against it."""
    global _backend, _manager
    _backend = backend
    _manager = None


def reset_manager():
    """Drop the singleton manager (and any tracked emitters). Used by tests and
    on mission swap / load so plumes re-derive from predicates."""
    global _manager
    _manager = None


def get_manager():
    global _manager, _backend
    if _manager is None:
        if _backend is None:
            _backend = NullBackend()
        _manager = PlumeManager(_backend)
    return _manager


def pump(ships, camera_pos, dt):
    """Host-loop entry point: advance the plume state machine one tick."""
    get_manager().update(ships, camera_pos, dt)


reset_registry()
