"""For the player's sensors: which contacts are in which band, and which are
on their way to being identified (sensor-tiers spec §1).

BC keeps this on a player-only singleton (RE'd: the global contact manager
@0x0098C000, every entry point gated on GetParentShip() == GetPlayerShip()), so
this module is player-only too. AI ships never identify.

- A sweep every `sweep_period_s` (BC: 1.0 s) walks the player's set and diffs
  near (`near_fraction` x range, BC: half) and far (full range) membership.
  Bands are PURE DISTANCE, as BC's are: E8M1 relies on FAR firing for a ship
  inside a nebula before it can be seen.
- Crossings post ET_SENSORS_SHIP_FAR/NEAR_PROXIMITY as a TGBoolEvent
  (1 entered / 0 left), source = the contact (the SDK handlers read
  GetSource()), destination = the player's sensors.
- A contact in the near band that can_detect passes and is not known gets a
  pending identification at now + identification_time_s (BC: 4.0 s). A passive
  entry re-checks near band + can_detect when it falls due; a scan entry
  (schedule_scan) commits unconditionally. Commit = _identify_one.
- Identity survives leaving range. A contact leaving the set is purged and
  forgotten; the player leaving its set wipes the lot (BC HandleExitSet).

Ticked every sim frame from host_loop (sim-gated). Never call from
render_payload.
"""
import weakref

import App
from engine.appc import sensor_dials
from engine.core.ids import implements

_near: "weakref.WeakSet" = weakref.WeakSet()
_far: "weakref.WeakSet" = weakref.WeakSet()
_pending: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_next_sweep_gt = None
_player_ref = None


def reset() -> None:
    global _next_sweep_gt, _player_ref
    _near.clear()
    _far.clear()
    _pending.clear()
    _next_sweep_gt = None
    _player_ref = None


def is_pending(obj) -> bool:
    return obj in _pending


def _now() -> float:
    try:
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception:
        return 0.0


def current_player():
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetPlayer() if game is not None else None
    except Exception:
        return None


def _sensors_of(ship):
    if ship is None or not implements(ship, "GetSensorSubsystem"):
        return None
    return ship.GetSensorSubsystem()


def player_knows(obj) -> bool:
    """True iff the current player's sensors have identified *obj*."""
    sensors = _sensors_of(current_player())
    if sensors is None or obj is None:
        return False
    try:
        return bool(sensors.IsObjectKnown(obj))
    except Exception:
        return False


def _contacts(player):
    """Ships and planets in the player's set, minus the player — exactly the
    filter the old passive sweep used (contact_index buckets ships only, and
    planets must still be identifiable). RockClass asteroids are ShipClass and
    are included, as they were before; rock-field scenery rocks are not set
    objects and never appear here."""
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet
    pset = player.GetContainingSet() if implements(player, "GetContainingSet") else None
    if pset is None or not hasattr(pset, "GetObjectList"):
        return ()
    return tuple(o for o in pset.GetObjectList()
                 if o is not None and o is not player
                 and isinstance(o, (ShipClass, Planet)))


def _dist(a, b) -> float:
    from engine.appc.subsystems import _get_xyz
    ax, ay, az = _get_xyz(a)
    bx, by, bz = _get_xyz(b)
    return ((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2) ** 0.5


def _post(event_type, obj, entered: bool, sensors) -> None:
    evt = App.TGBoolEvent_Create()
    evt.SetEventType(event_type)
    evt.SetBool(1 if entered else 0)
    evt.SetSource(obj)
    evt.SetDestination(sensors)
    App.g_kEventManager.AddEvent(evt)


def _sync_player(player) -> None:
    """A different player ship starts a clean manager (BC HandleSetPlayer).

    Only wipes state when a PREVIOUS player existed and differs from the new
    one. When _player_ref is None (first sight, or right after reset()), just
    record the new player and leave _pending alone: a scan scheduled before
    this module's first tick (Task 5's IdentifyObject calling schedule_scan)
    must still commit when due, not be silently cancelled by the very first
    tick that happens to observe it.

    A RECORDED ref that no longer resolves to *player* is a swap too, even
    when it is now dead (the old player was GC'd): "no ref was ever recorded"
    (first sight) is the ONLY state that skips the wipe. Checking
    `current is not None` after dereferencing used to conflate "first sight"
    with "the old player died" -- both read back `current is None` -- so a
    dead ref silently kept the dead player's `_near`/`_far` membership alive
    across the swap and the new player's sweep saw no crossing to post.
    """
    global _player_ref, _next_sweep_gt
    if _player_ref is None:
        _player_ref = weakref.ref(player) if player is not None else None
        return
    if _player_ref() is player:
        return
    _near.clear()
    _far.clear()
    _pending.clear()
    _next_sweep_gt = None
    _player_ref = weakref.ref(player) if player is not None else None


def _in_near_band(player, obj) -> bool:
    from engine.appc.sensor_detection import effective_sensor_range
    r = effective_sensor_range(player)
    return r > 0.0 and _dist(player, obj) <= r * sensor_dials.get("near_fraction")


def _commit_due(player, sensors, now_gt) -> None:
    from engine.appc.sensor_detection import can_detect
    from engine.appc.sensor_identification import _identify_one
    for obj, (due, by_scan) in list(_pending.items()):
        if now_gt < due:
            continue
        _pending.pop(obj, None)
        if sensors.IsObjectKnown(obj):
            continue
        if by_scan or (_in_near_band(player, obj) and can_detect(player, obj)):
            _identify_one(sensors, obj)


def _sweep(player, sensors, now_gt) -> None:
    from engine.appc.sensor_detection import can_detect, effective_sensor_range
    r = effective_sensor_range(player)
    nf = sensor_dials.get("near_fraction")
    dwell = sensor_dials.get("identification_time_s")
    for obj in _contacts(player):
        d = _dist(player, obj)
        far = r > 0.0 and d <= r
        near = r > 0.0 and d <= r * nf
        was_far, was_near = obj in _far, obj in _near
        if far and not was_far:
            _far.add(obj)
            _post(App.ET_SENSORS_SHIP_FAR_PROXIMITY, obj, True, sensors)
        if near and not was_near:
            _near.add(obj)
            _post(App.ET_SENSORS_SHIP_NEAR_PROXIMITY, obj, True, sensors)
        if was_near and not near:
            _near.discard(obj)
            _post(App.ET_SENSORS_SHIP_NEAR_PROXIMITY, obj, False, sensors)
        if was_far and not far:
            _far.discard(obj)
            _post(App.ET_SENSORS_SHIP_FAR_PROXIMITY, obj, False, sensors)
        if (near and obj not in _pending and not sensors.IsObjectKnown(obj)
                and can_detect(player, obj)):
            _pending[obj] = (now_gt + dwell, False)


def tick(player, now_gt: float) -> None:
    global _next_sweep_gt
    _sync_player(player)
    sensors = _sensors_of(player)
    if sensors is None:
        return
    _commit_due(player, sensors, now_gt)
    if _next_sweep_gt is None or now_gt >= _next_sweep_gt:
        _next_sweep_gt = now_gt + sensor_dials.get("sweep_period_s")
        _sweep(player, sensors, now_gt)


def schedule_scan(obj, delay_s: float, now_gt=None) -> None:
    """Arm a scan identification of *obj* (IdentifyObject / ScanAllObjects).
    Commits unconditionally when due. Keeps the earlier due time if one is
    already pending. No-op if the player already knows *obj*."""
    if obj is None or player_knows(obj):
        return
    t = (_now() if now_gt is None else float(now_gt)) + float(delay_s)
    prior = _pending.get(obj)
    if prior is not None:
        t = min(t, prior[0])
    _pending[obj] = (t, True)


def on_exited_set(pSet, obj) -> None:
    """Called by SetClass after the ET_EXITED_SET broadcast (so Science's
    ExitedSet has already found the placeholder button)."""
    from engine.appc import unknown_labels
    _near.discard(obj)
    _far.discard(obj)
    _pending.pop(obj, None)
    unknown_labels.release(obj)
    player = current_player()
    sensors = _sensors_of(player)
    if obj is player:
        reset()
        unknown_labels.reset()
        if sensors is not None:
            sensors._known_objects.clear()
        return
    if sensors is not None:
        sensors.RemoveKnownObject(obj)
