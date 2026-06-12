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

THROES_DURATION       = 5.0   # seconds the ship coasts, dying, before removal
# Explosion VFX tunables (consumed by _spawn_explosion), kept beside
# THROES_DURATION. Tuned by feel.
EXPLOSION_SIZE_FACTOR   = 0.75  # per-puff size as a fraction of ship radius
MIN_EXPLOSION_SIZE      = 2.0   # GU floor for tiny craft
EXPLOSION_PUFF_LIFE     = 3.0   # seconds per puff = 8-frame animation duration
                                # (2x the SDK 1.5s default → frames play 2x slower)
EXPLOSION_SPREAD_FACTOR = 0.8   # emit-sphere radius as a fraction of ship radius,
                                # so puffs spawn all over the hull, not just centre

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
    """Death instant: mark dead, broadcast ET_OBJECT_DESTROYED, then remove
    from set. Order matters — the event fires while the handle is still in
    the set so handlers can read the ship's name/position."""
    if hasattr(ship, "SetDead"):
        ship.SetDead()
    _broadcast_destroyed(ship)
    try:
        pSet = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        if pSet is not None and hasattr(ship, "GetName"):
            pSet.RemoveObjectFromSet(ship.GetName())
    except Exception:
        pass


def _broadcast_destroyed(ship) -> None:
    """Fire ET_OBJECT_DESTROYED with source == destination == ship, so both
    func-broadcast handlers (read GetSource) and per-source method handlers
    (filter on GetDestination) receive it. Raise-safe."""
    try:
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_OBJECT_DESTROYED)
        evt.SetSource(ship)
        evt.SetDestination(ship)
        App.g_kEventManager.AddEvent(evt)
    except Exception:
        pass


def _spawn_explosion(ship) -> None:
    """Death explosion: an animated ExplosionA fireball sized to the ship
    radius, emitted from the (still-present, coasting) hull. Reuses the SDK
    Effects helper via our AnimTSParticleController shim + particle backend.

    ExplosionA.tga is a 256x256, 8x8 sprite sheet: 8 animation frames across,
    8 explosion variants down. We force ExplosionA (it carries its own alpha,
    unlike the greyscale ExplosionB) and declare the 8x8 grid so the renderer
    steps a per-particle cell (frame from age, row for variety) instead of
    drawing the whole sheet as one static billboard.

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
        ctrl = action.GetController() if hasattr(action, "GetController") else None
        if ctrl is not None:
            ctrl.CreateTarget("data/Textures/Effects/ExplosionA.tga")
            if hasattr(ctrl, "SetTextureCells"):
                ctrl.SetTextureCells(8, 8)
            # Frames step over each puff's life, so a longer life = slower
            # animation. Spread births across a hull-sized sphere so puffs
            # appear all over the ship, not just at its centre.
            ctrl.SetEmitLife(EXPLOSION_PUFF_LIFE)
            ctrl.SetEmitRadius(radius * EXPLOSION_SPREAD_FACTOR)
        if action is not None and hasattr(action, "Play"):
            action.Play()
    except Exception:
        pass


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
