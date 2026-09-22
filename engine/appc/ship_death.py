# engine/appc/ship_death.py
"""Ship death sequence — BC's explosion cascade, then removal.

Single owner of the dying -> dead transition. `begin(ship)` starts the throes
(and the death cascade); `advance(dt)` ticks every dying ship and, when its
timer expires, marks it dead (which fires ship_lifecycle.publish_destroyed),
broadcasts ET_OBJECT_DESTROYED, and removes it from its set. Plugs into the
per-frame _advance_combat hub the same way hit_vfx / particles do.

The throes window is no longer a fixed 5 s: `engine.appc.death_cascade` rolls
BC's 5-15 s per ship (honouring a mission-set lifetime), and drives the storm of
explosions that carves the hull open while it dies. That module owns everything
visual about a death; this one owns the lifecycle.

See docs/superpowers/specs/2026-06-11-ship-death-sequence-design.md and
engine/appc/death_cascade.py.
"""

import engine.dev_mode as dev_mode
from engine.appc import death_cascade, explosion_lights
from engine.core.ids import implements

# There is no selectable window after the throes. On the original exe the
# player's target clears and the reticule vanishes on the SAME SAMPLE the
# dying phase ends (stbc-oracle bible §12.2a V7, `camera_kill/*`); a five-
# second "linger" in which the dead hull stayed in the target list, locks and
# reticule kept, used to sit here and read live as the reticule hanging on
# the wreck. The hull itself still stays, as a hulk (below).
WRECK_LINGER_DURATION = 0.0   # kept as a name for callers that drive a death
                              # to completion; the phase is gone

# How many dead hulls stay in the world at once. Oldest evicted.
#
# BC removed the hull the moment the death lifetime expired. Five quiet
# seconds after a 5-15 s death reads as vanishing on the spot, so a dead hull
# STAYS as a hulk — scenery, not a target.
#
# Persisting costs nothing to wire — both the renderer's instance reaper and
# collisions.iter_collidables walk set membership with no dead filter, so a
# hull left in its set keeps drawing and colliding by construction. It does
# cost per frame, though: every hulk is a full hull draw plus collision pairs.
# Hence a cap rather than true permanence; a long fight cannot grow the scene
# without limit. This is a deliberate DEVIATION from BC, not recovered
# behaviour.
MAX_HULKS = 8

# The longest throes BC can roll. Callers that need to drive a death to
# completion (tests, teardown) advance by this rather than by a per-ship value
# they cannot know — the throes are randomised per ship now.
MAX_THROES_DURATION = death_cascade.THROES_MAX

# Registry of in-progress death sequences: each entry is
# {"ship": ship, "phase": str, "time_left": float, "cascade": dict | None}.
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
    # BC rolls the death window per ship (Effects.ObjectExploding), honouring a
    # lifetime a mission already set. The cascade is planned against that same
    # duration, so the finish always lands inside the throes.
    duration = death_cascade.roll_duration(ship)
    _active.append({
        "ship": ship,
        "phase": "throes",
        "time_left": duration,
        "cascade": death_cascade.begin(ship, duration),
    })
    # Run the mission's authored death script (SDK SetDeathScript) before the
    # generic fireball, so authored debris VFX/sound lead. Raise-safe.
    if hasattr(ship, "RunDeathScript"):
        try:
            ship.RunDeathScript()
        except Exception as _e:
            dev_mode.log_swallowed("run death script from begin", _e)
    _broadcast_exploding(ship, killer)
    # Faithful death-explosion collateral: BC's m_splashDamage to everything in
    # m_splashDamageRadius (loadspacehelper sets it on every ship). Raise-safe;
    # a no-op for objects with no authored splash. Fired here so EVERY death
    # (combat, warp-core, scripted) splashes exactly once, at the blast moment.
    try:
        from engine.appc import splash_damage
        splash_damage.apply(ship)
    except Exception as _e:
        dev_mode.log_swallowed("apply death splash damage", _e)


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
    becomes a hulk on the spot: the death-marker fires, every lock on it is
    released (V7: the target and reticule clear on the same sample as BC's
    removal), and the hull stays in its set as scenery until evicted."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        if entry["phase"] == "hulk":
            survivors.append(entry)          # no timer — a hulk waits for the cap
            continue
        # Drive the explosion cascade before the timer, so a blast scheduled at
        # the very end of the window still fires on the frame the throes expire.
        if entry["phase"] == "throes" and entry["cascade"] is not None:
            death_cascade.advance(entry["cascade"], dt)
        entry["time_left"] -= dt
        if entry["time_left"] > 0.0:
            survivors.append(entry)
            continue
        if entry["phase"] == "throes":
            _mark_dead(entry["ship"])
            entry["cascade"] = None          # stop carving; the ship is dead
            # Release every lock HERE, on the sample the throes end: the hulk
            # leaves the target list at this moment (V7), so a player still
            # tracking it would otherwise stay locked onto a corpse.
            _clear_target_locks(entry["ship"])
            entry["phase"] = "hulk"
            survivors.append(entry)
    _active[:] = survivors
    _evict_excess_hulks()


def _evict_excess_hulks() -> None:
    """Keep at most MAX_HULKS dead hulls in the world, oldest first out.

    `_active` is append-ordered by time of death, so the oldest hulks are
    simply the earliest matching entries."""
    hulks = [e for e in _active if e["phase"] == "hulk"]
    excess = len(hulks) - MAX_HULKS
    if excess <= 0:
        return
    for entry in hulks[:excess]:
        _remove(entry["ship"])
        _active.remove(entry)


def _mark_dead(ship) -> None:
    """End of throes: mark the ship dead and broadcast ET_OBJECT_DESTROYED so
    mission logic and ship_lifecycle.publish_destroyed (fired by SetDead) run
    on schedule. The hull stays in its set and keeps its target locks — it
    lingers as a selectable wreck for WRECK_LINGER_DURATION.

    Also tears down the ship's AI tree (spec #15): nothing outside ships.py
    ever touches the AI slot, so a destroyed ship's tree otherwise stays
    installed on the hulk forever, and its Warp leaf never runs LostFocus
    (which re-enables the collisions it disabled) — a killed ship mid-warp
    would end up permanently non-collidable.

    Tear the AI down the way ClearAI does — LostFocus down the tree (Warp's
    re-enables collisions, FireScript's stops firing) and detach — but
    WITHOUT ET_AI_DONE: that event means "the tree finished", and missions
    gate beats on it. A ship that died did not finish its orders."""
    if hasattr(ship, "SetDead"):
        ship.SetDead()
    # ship.__dict__.get, not getattr: a TGObject.__getattr__ stub would
    # otherwise masquerade as a real (but empty) _ai attribute.
    ai = ship.__dict__.get("_ai")
    if ai is not None:
        try:
            ship._deactivate_ai_tree(ai)
        except Exception as _e:
            dev_mode.log_swallowed("deactivate AI tree on death", _e)
        ship._ai = None
        ship._insystem_warp_transit = None
    _broadcast_destroyed(ship)


def _remove(ship) -> None:
    """End of linger: release every lock held on the wreck, remove it from its
    set, then broadcast the delete. Order matters twice over: locks clear
    while the handle is still in the set so firing ships drop their target
    pointers against a valid object; and the set removal (which posts
    EXITED_SET) happens BEFORE ET_DELETE_OBJECT_PUBLIC so an object "leaves
    the set" before it "leaves the world" — the same order DeleteObjectFromSet
    already used, now matched here (see M5 in the 2026-09-19 NPC AI contract
    review fix wave). ConditionExists.Deleted, the SDK's own subscriber, only
    needs the event and never reads set membership, so nothing depends on the
    old order.

    The set removal keeps its own try: it guards the removal itself, not the
    broadcast that follows. broadcast_object_deleted guards its own dispatch
    internally, so it is one plain call here."""
    _clear_target_locks(ship)
    try:
        pSet = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        if pSet is not None and hasattr(ship, "GetName"):
            pSet.RemoveObjectFromSet(ship.GetName())
    except Exception as _e:
        dev_mode.log_swallowed("remove dead ship from set", _e)
    from engine.appc.objects import broadcast_object_deleted
    broadcast_object_deleted(ship)


def retire(ship) -> None:
    """Immediate, single-step removal of `ship` from the world — no throes /
    linger phases. Marks it dead (fires ET_OBJECT_DESTROYED + publish_destroyed),
    clears target locks, and removes it from its set. Used by the lifetime
    countdown (engine.appc.object_lifetime), where the object's death was
    already scripted and only removal remains. Safe to call once per object."""
    if ship is None:
        return
    _mark_dead(ship)   # SetDead + ET_OBJECT_DESTROYED
    _remove(ship)      # clear locks + remove from set


def is_targetable_wreck(ship) -> bool:
    """True while `ship` is dying or is a dead wreck still worth selecting.

    The HUD target list uses this to keep a dying ship selectable through
    its throes. Hulks are excluded deliberately: they persist for the rest of
    the battle, and a target list that fills with corpses is worse than one
    with no wrecks in it at all.

    Identity match against the active registry; no engine calls, so it is safe
    to call on any object."""
    return any(entry["ship"] is ship and entry["phase"] != "hulk"
               for entry in _active)


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


def reset() -> None:
    """Clear the registry (mission swap / test teardown).

    Also clears the explosion-light registry: a ship that died in the
    previous mission would otherwise keep lighting the next one from its
    old world position.
    """
    _active.clear()
    explosion_lights.reset()
