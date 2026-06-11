# engine/appc/ship_death.py
"""Ship death sequence — fixed-window throes, then removal.

Single owner of the dying -> dead transition. `begin(ship)` starts the
throes timer (and spawns the death explosion); `advance(dt)` ticks every
dying ship and, when its timer expires, marks it dead (which fires
ship_lifecycle.publish_destroyed), broadcasts ET_OBJECT_DESTROYED, and
removes it from its set. Plugs into the per-frame _advance_combat hub the
same way hit_vfx / particles do.

See docs/superpowers/specs/2026-06-11-ship-death-sequence-design.md.
"""

THROES_DURATION       = 2.5   # seconds the ship coasts, dying, before removal
# Consumed by _spawn_explosion (filled in a later task); defined here so the
# VFX tunables live alongside THROES_DURATION.
EXPLOSION_SIZE_FACTOR = 1.0   # ship-radius multiplier (starting value, tune by feel)
MIN_EXPLOSION_SIZE    = 2.0   # GU floor for tiny craft (starting value, tune by feel)

# Registry of in-progress death sequences: each entry is
# {"ship": ship, "time_left": float}.
_active: list[dict] = []


def _out_of_action(ship) -> bool:
    """True when `ship` is dying or dead. The single definition of 'inert',
    which the AI and weapon gate sites will call in later tasks. hasattr-
    guarded so non-ship objects never read as out of action."""
    if ship is None:
        return False
    dying = bool(ship.IsDying()) if hasattr(ship, "IsDying") else False
    dead = bool(ship.IsDead()) if hasattr(ship, "IsDead") else False
    return dying or dead


def begin(ship) -> None:
    """Start the death sequence for `ship`. Idempotent: a ship already
    dying or dead is ignored (covers a second critical subsystem dropping
    mid-throes)."""
    if ship is None or _out_of_action(ship):
        return
    if hasattr(ship, "SetDying"):
        ship.SetDying(True)
    _active.append({"ship": ship, "time_left": THROES_DURATION})
    _spawn_explosion(ship)


def advance(dt: float) -> None:
    """Tick every in-progress death sequence. When a timer expires, mark
    the ship dead and remove it from its set. Prunes completed entries."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        entry["time_left"] -= dt
        if entry["time_left"] > 0.0:
            survivors.append(entry)
            continue
        _finish(entry["ship"])
    _active[:] = survivors


def _finish(ship) -> None:
    """Death instant: mark dead, then remove from set. Order matters —
    SetDead fires publish_destroyed while the handle is still valid."""
    if hasattr(ship, "SetDead"):
        ship.SetDead()
    try:
        pSet = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        if pSet is not None and hasattr(ship, "GetName"):
            pSet.RemoveObjectFromSet(ship.GetName())
    except Exception:
        pass


def _spawn_explosion(ship) -> None:
    """Death explosion: an ExplosionA/B fireball sized to the ship radius,
    emitted from the (still-present, coasting) hull. Reuses the SDK Effects
    helper via our AnimTSParticleController shim + particle backend.

    Raise-safe: death logic must never depend on VFX succeeding (missing
    asset / headless test without a backend just yields no explosion)."""
    try:
        import Effects
        from engine.appc.math import TGPoint3
        radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 1.0
        size = max(radius * EXPLOSION_SIZE_FACTOR, MIN_EXPLOSION_SIZE)
        action = Effects.CreateExplosionPuffHigh(
            THROES_DURATION,            # fLife
            size,                       # fSize
            ship,                       # pEmitFrom — tracks the tumbling hull
            TGPoint3(0.0, 0.0, 0.0),    # kEmitPos (body origin)
            TGPoint3(0.0, 0.0, 1.0),    # kEmitDir
            None,                       # pAttachTo — unattached at emit pos
        )
        if action is not None and hasattr(action, "Play"):
            action.Play()
    except Exception:
        pass


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
