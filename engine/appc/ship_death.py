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

import engine.dev_mode as dev_mode
from engine.core.ids import implements

THROES_DURATION       = 5.0   # seconds the ship coasts, dying, before removal
WRECK_LINGER_DURATION = 5.0   # seconds a dead hull lingers, selectable in the
                              # target list, after the throes before removal
# Explosion VFX tunables (consumed by _spawn_explosion), kept beside
# THROES_DURATION. Tuned by feel.
EXPLOSION_SIZE_FACTOR   = 0.75  # per-puff size as a fraction of ship radius
MIN_EXPLOSION_SIZE      = 2.0   # GU floor for tiny craft
EXPLOSION_PUFF_LIFE     = 3.0   # seconds per puff = 8-frame animation duration
                                # (2x the SDK 1.5s default → frames play 2x slower)
EXPLOSION_SPREAD_FACTOR = 0.8   # emit-sphere radius as a fraction of ship radius,
                                # so puffs spawn all over the hull, not just centre
EXPLOSION_COUNT         = 4     # total big blasts over the throes window —
                                # evenly spaced, each at a different hull spot

# Registry of in-progress death sequences: each entry is
# {"ship": ship, "time_left": float}.
_active: list[dict] = []


def _out_of_action(ship) -> bool:
    """True when `ship` is dying or dead. The single definition of 'inert',
    which the AI and weapon gate sites call.

    MRO-guarded, NOT hasattr-guarded: IsDying/IsDead are DamageableObject
    surface (sdk/Build/scripts/App.py:5363), and a Waypoint / Planet /
    LightPlacement has neither. hasattr() cannot express that -- it is
    vacuously True on any TGObject -- so the old guards made every inert
    placement object read back as DYING."""
    if ship is None:
        return False
    dying = bool(ship.IsDying()) if implements(ship, "IsDying") else False
    dead = bool(ship.IsDead()) if implements(ship, "IsDead") else False
    return dying or dead


def begin(ship, killer=None) -> None:
    """Start the death sequence for `ship`. Idempotent: a ship already
    dying or dead is ignored (covers a second critical subsystem dropping
    mid-throes).

    `killer` is the firing ship that dealt the fatal blow (None for scripted /
    unattributed kills); it flows onto the ET_OBJECT_EXPLODING event as the
    firing-player-id so mission friendly-fire logic can attribute the kill."""
    if ship is None or _out_of_action(ship):
        return
    if hasattr(ship, "SetDying"):
        ship.SetDying(True)
    _active.append({"ship": ship, "phase": "throes", "time_left": THROES_DURATION})
    # Run the mission's authored death script (SDK SetDeathScript) before the
    # generic fireball, so authored debris VFX/sound lead. Raise-safe.
    if hasattr(ship, "RunDeathScript"):
        try:
            ship.RunDeathScript()
        except Exception as _e:
            dev_mode.log_swallowed("run death script from begin", _e)
    _broadcast_exploding(ship, killer)
    _spawn_explosion(ship)


def _clear_target_locks(dying) -> None:
    """Release every lock held ON the dying ship: the target itself and the
    targeted-subsystem lock (which BC stores on the FIRING ship — see
    player.SetTargetSubsystem). The player's HUD reticle and tracking camera
    follow GetTarget, so they drop automatically. Raise-safe."""
    try:
        from engine.appc.ship_iter import iter_ships
        for other in iter_ships():
            if other is dying:
                continue
            if not hasattr(other, "GetTarget") or other.GetTarget() is not dying:
                continue
            other.SetTarget(None)
            if hasattr(other, "SetTargetSubsystem"):
                other.SetTargetSubsystem(None)
    except Exception as _e:
        dev_mode.log_swallowed("clear target locks on dying ship", _e)


def advance(dt: float) -> None:
    """Tick every in-progress death sequence. A 'throes' entry that expires
    becomes a dead, still-selectable wreck (the death-marker fires, but the
    hull stays in its set and keeps its locks); a 'linger' entry that expires
    is finally removed. Only fully-removed entries are pruned."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        entry["time_left"] -= dt
        if entry["time_left"] > 0.0:
            survivors.append(entry)
            continue
        if entry["phase"] == "throes":
            _mark_dead(entry["ship"])
            entry["phase"] = "linger"
            entry["time_left"] = WRECK_LINGER_DURATION
            survivors.append(entry)          # wreck lingers, still selectable
        else:  # "linger"
            _remove(entry["ship"])           # pruned (not re-appended)
    _active[:] = survivors


def _mark_dead(ship) -> None:
    """End of throes: mark the ship dead and broadcast ET_OBJECT_DESTROYED so
    mission logic and ship_lifecycle.publish_destroyed (fired by SetDead) run
    on schedule. The hull stays in its set and keeps its target locks — it
    lingers as a selectable wreck for WRECK_LINGER_DURATION."""
    if hasattr(ship, "SetDead"):
        ship.SetDead()
    _broadcast_destroyed(ship)


def _remove(ship) -> None:
    """End of linger: release every lock held on the wreck, then remove it from
    its set. Order matters — locks clear while the handle is still in the set
    so firing ships drop their target pointers against a valid object."""
    _clear_target_locks(ship)
    try:
        pSet = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        if pSet is not None and hasattr(ship, "GetName"):
            pSet.RemoveObjectFromSet(ship.GetName())
    except Exception as _e:
        dev_mode.log_swallowed("remove dead ship from set", _e)


def is_targetable_wreck(ship) -> bool:
    """True while `ship` is in an in-progress death/linger sequence (dying or a
    dead wreck not yet removed). The HUD target list uses this to keep a
    destroyed ship selectable through the throes + linger window. Identity
    match against the active registry; no engine calls, so it is safe to call
    on any object."""
    return any(entry["ship"] is ship for entry in _active)


def _broadcast_exploding(ship, killer=None) -> None:
    """Fire ET_OBJECT_EXPLODING the instant the death throes begin — BC's
    "object started exploding" event, the one mission kill-detection listens
    on (24 SDK missions, e.g. E1M2's ObjectDestroyed handler that clears the
    debris/asteroid goals). ET_OBJECT_DESTROYED comes later, at removal; the
    two are NOT interchangeable, so a mission subscribed only to EXPLODING
    hangs forever without this. source == destination == ship, so both
    func-broadcast handlers (read GetSource) and per-instance handlers
    (dispatched via GetDestination) receive it.

    The event carries the firing-player-id (the killer ship's GetObjID, or
    NULL_ID when unattributed) so MissionLib.ObjectStartedExploding can detect
    the player destroying a friendly and raise ET_FRIENDLY_FIRE_GAME_OVER.
    Raise-safe."""
    try:
        import App
        evt = App.ObjectExplodingEvent_Create()
        evt.SetEventType(App.ET_OBJECT_EXPLODING)
        evt.SetSource(ship)
        evt.SetDestination(ship)
        killer_id = killer.GetObjID() if killer is not None else App.NULL_ID
        evt.SetFiringPlayerID(killer_id)
        App.g_kEventManager.AddEvent(evt)
    except Exception as _e:
        dev_mode.log_swallowed("broadcast ET_OBJECT_EXPLODING", _e)


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
    except Exception as _e:
        dev_mode.log_swallowed("broadcast ET_OBJECT_DESTROYED", _e)


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
            # Force the colour sheet (helper randomly picks A or greyscale B);
            # CreateTarget auto-declares the 8x8 sprite-sheet grid.
            ctrl.CreateTarget("data/Textures/Effects/ExplosionA.tga")
            # Frames step over each puff's life, so a longer life = slower
            # animation. Spread births across a hull-sized sphere so puffs
            # appear all over the ship, not just at its centre.
            ctrl.SetEmitLife(EXPLOSION_PUFF_LIFE)
            ctrl.SetEmitRadius(radius * EXPLOSION_SPREAD_FACTOR)
            # Exactly EXPLOSION_COUNT births, evenly spaced across the throes
            # window: births land at i*spacing; capping the emission window at
            # (COUNT - 0.5)*spacing allows births 0..COUNT-1 and no more. The
            # last blast finishes its animation after the hulk is removed,
            # anchored at the wreck site.
            spacing = THROES_DURATION / EXPLOSION_COUNT
            ctrl.SetEmitFrequency(spacing)
            ctrl.SetEffectLifeTime(spacing * (EXPLOSION_COUNT - 0.5))
        if action is not None and hasattr(action, "Play"):
            action.Play()
    except Exception as _e:
        dev_mode.log_swallowed("spawn death explosion", _e)


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
