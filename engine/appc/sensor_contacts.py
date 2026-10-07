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

Continuity (sensor continuity/occlusion spec):

- A contact is CONCEALED (`is_concealed`) when it is in the player's set,
  inside player sensor range, and HIDDEN (`not can_detect`: a major rock, the
  dense nebula core) -- and not fully cloaked. Mark's rulings (2026-10-05):
  1A, cloak never starts the clock -- identity survives cloak, as in BC
  (perception still asks can_detect, so the row behaves as before); 2A, a
  medium alone (`sensor_media.medium_unknown`: an asteroid field, moderate
  nebula) never loses the track -- it only changes the DISPLAY to Unknown
  (`shows_identity`). Leaving range is never concealment either.
- Each sweep, a KNOWN contact that is concealed starts (or keeps) its clock in
  `_concealed_since`; one that is not has its clock cleared. Concealed for
  `continuity_window_s` (dial, 5.0 s) => LOST TRACK: RemoveKnownObject, then
  `Bridge.HelmMenuHandlers.ExitedSet(obj)` called directly (via the
  `_helm_exited_set` seam) to drop its Hail button. Never a synthetic
  ET_EXITED_SET. The clock is read on the sweep, so the window is accurate to
  one `sweep_period_s`.
- Passive arming and passive commit both require can_detect and the contact
  not to read Unknown by medium (`_unknown_by_medium`): no passive
  identification inside a field or nebula. A scan entry is dropped if a major
  rock blocks the line when it falls due (only while
  `ENHANCED_SENSOR_CONTEST` is on, as for can_detect); a successful scan
  records `_scanned_at` (a one-window name glimpse in a medium, after which
  the display reverts to Unknown and the ship stays known), and if the
  contact is concealed (hidden) its clock restarts from the scan -- one
  window, then the track is lost.
- `shows_identity(obj)` is the ONE display answer for the target-list
  caption, the reticle name and the Science Scan button label: known AND
  (not unknown-by-medium OR scanned within the window). Never re-derive it at
  a call site.
- Each sweep the Science Scan Object button of every contact is renamed
  between its "Unknown N" placeholder and its real name whenever its
  shows_identity answer changes (`_shown_real` remembers the last one).
  Because it syncs on the 1 s sweep, the Science label can lag the target
  list and reticle (which ask shows_identity every frame) by up to one
  sweep -- it never shows a name the player had not legitimately seen.
  Caveat: Scan buttons are keyed by label, so two KNOWN ships sharing a
  display name share one Scan button.
- Only ships have a signature: a planet (any non-ShipClass contact) is never
  concealed and never reads Unknown by medium (`_has_signature`).
- A scan of a KNOWN contact that reads Unknown in a medium is re-armed; its
  commit restarts the glimpse and the clock without a second
  ET_SENSORS_SHIP_IDENTIFIED. A scan in clear space whose contact then
  enters a medium keeps its glimpse until that window (from the scan) ends.

Ticked every sim frame from host_loop (sim-gated). Never call from
render_payload.
"""
import weakref

import App
import engine.dev_mode as dev_mode
from engine.appc import sensor_dials
from engine.core.ids import implements

_near: "weakref.WeakSet" = weakref.WeakSet()
_far: "weakref.WeakSet" = weakref.WeakSet()
_pending: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_concealed_since: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_scanned_at: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_shown_real: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_next_sweep_gt = None
_player_ref = None


def _clear_continuity() -> None:
    _concealed_since.clear()
    _scanned_at.clear()
    _shown_real.clear()


def reset() -> None:
    global _next_sweep_gt, _player_ref
    _near.clear()
    _far.clear()
    _pending.clear()
    _clear_continuity()
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


def shows_identity(obj, now_gt=None, sensors=None, *, concealment=None) -> bool:
    """THE display answer: should *obj* show its real name (target-list
    caption, reticle name, Science Scan button)?

    Known AND (not unknown-by-medium OR scanned within `continuity_window_s`
    of *now_gt*). "Known" is read from *sensors* when given (perception
    passes the observer's), else from the current game player's sensors.
    *now_gt* defaults to the current game time. *concealment* is forwarded
    to `sensor_media.medium_unknown` unchanged -- pass it only under that
    function's hand-off contract (this frame's exact sample for *obj*)."""
    if obj is None:
        return False
    if sensors is None:
        sensors = _sensors_of(current_player())
    if sensors is None:
        return False
    try:
        if not sensors.IsObjectKnown(obj):
            return False
    except Exception:
        return False
    if not _has_signature(obj):
        return True
    from engine.appc import sensor_media
    if not sensor_media.medium_unknown(obj, concealment=concealment):
        return True
    scanned = _scanned_at.get(obj)
    if scanned is None:
        return False
    now = _now() if now_gt is None else float(now_gt)
    return now - scanned < sensor_dials.get("continuity_window_s")


def _has_signature(obj) -> bool:
    """Only ships can be concealed or read Unknown by medium. A planet (any
    non-ShipClass contact) has no signature to hide -- the same exemption
    sensor_detection.clear_undetectable_player_lock makes -- so it never
    loses track and never reads Unknown (controller ruling, Task 4 fix 1)."""
    from engine.appc.ships import ShipClass
    return isinstance(obj, ShipClass)


def is_concealed(player, obj) -> bool:
    """Does *obj* run the lost-track clock? In the player's set, IN REACH
    (sensor_detection.in_reach: unshrunk range, or BC's memory / over-boost
    unless jammed -- sub-project 3), HIDDEN (`not can_detect`) and not fully
    cloaked. Cloak (ruling 1A) and a medium alone (ruling 2A) never conceal;
    leaving REACH is never concealment. Never true for a non-ShipClass
    contact (`_has_signature`)."""
    if player is None or obj is None or not _has_signature(obj):
        return False
    try:
        pset = player.GetContainingSet() if implements(player, "GetContainingSet") else None
        oset = obj.GetContainingSet() if implements(obj, "GetContainingSet") else None
        if pset is None or oset is not pset:
            return False
        from engine.appc.sensor_detection import (can_detect, in_reach,
                                                  is_hidden_by_cloak)
        if not in_reach(player, obj):
            return False
        if is_hidden_by_cloak(obj):
            return False
        return not can_detect(player, obj)
    except Exception as e:
        dev_mode.log_swallowed("sensor_contacts.is_concealed", e)
        return False


def _unknown_by_medium(obj) -> bool:
    """Does *obj* read Unknown by medium? Ships only (`_has_signature`).
    Gates passive identification; never starts the lost-track clock."""
    if not _has_signature(obj):
        return False
    from engine.appc import sensor_media
    try:
        return bool(sensor_media.medium_unknown(obj))
    except Exception as e:
        dev_mode.log_swallowed("sensor_contacts._unknown_by_medium", e)
        return False


def concealed_since(obj):
    """Game time the continuity clock started for *obj*, or None."""
    return _concealed_since.get(obj)


def _helm_exited_set(obj) -> None:
    """Drop *obj*'s Hail button (or fleet submenu) the way BC does when a
    contact leaves: the SDK's own `Bridge.HelmMenuHandlers.ExitedSet`, called
    directly with no event. A seam so unit tests (no bridge menus) can record
    the call; the real call is exercised by
    tests/integration/test_sensor_continuity_science.py."""
    try:
        import Bridge.HelmMenuHandlers as helm
    except ImportError:
        return
    helm.ExitedSet(obj)


def _lose_track(player, sensors, obj) -> None:
    """Concealed for the whole window: forget identity and drop the Hail
    button. Never posts ET_EXITED_SET -- the contact is still in the set."""
    try:
        sensors.RemoveKnownObject(obj)
    except Exception as e:
        dev_mode.log_swallowed("sensor_contacts lost-track RemoveKnownObject", e)
    try:
        _helm_exited_set(obj)
    except Exception as e:
        dev_mode.log_swallowed("sensor_contacts lost-track Helm ExitedSet", e)
    _concealed_since.pop(obj, None)
    _scanned_at.pop(obj, None)


def _scan_menu():
    try:
        import MissionLib
        return MissionLib.GetCharacterSubmenu("Science", "Scan Object")
    except Exception:
        return None


def _sync_science_label(obj, now_gt) -> None:
    """Rename *obj*'s Scan Object button between its placeholder and its real
    name when its shows_identity answer changes. No-op without a button."""
    want_real = shows_identity(obj, now_gt)
    prior = _shown_real.get(obj)
    if prior is want_real:
        return
    _shown_real[obj] = want_real
    if prior is None and not want_real and not player_knows(obj):
        # First sight of a never-identified contact: its button (if any) was
        # built with the placeholder already (science_scan_labels wraps
        # CreateScanButton). Buttons are keyed by LABEL, so looking one up by
        # this contact's real name could find a known NAMESAKE's button.
        return
    try:
        from engine.appc import unknown_labels
        menu = _scan_menu()
        real = obj.GetDisplayName()
        has_real_button = menu is not None and menu.GetButtonW(real) is not None
        label = unknown_labels.current(obj)
        if want_real:
            if label is not None and menu is not None:
                menu.RenameButton(label, real)
            return
        if label is None and (has_real_button or _listed(obj)):
            label = unknown_labels.placeholder(obj)
        if label is not None and has_real_button:
            menu.RenameButton(real, label)
    except Exception as e:
        dev_mode.log_swallowed("sensor_contacts science label sync", e)


def _listed(obj) -> bool:
    """Is *obj* a targetable row in the player's target list?"""
    try:
        from engine.appc.target_menu import STTargetMenu_GetTargetMenu
        tm = STTargetMenu_GetTargetMenu()
        c = tm.contact_for(obj) if tm is not None else None
        return bool(c is not None and c.targetable)
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
    _clear_continuity()
    _next_sweep_gt = None
    _player_ref = weakref.ref(player) if player is not None else None


def _in_near_band(player, obj) -> bool:
    from engine.appc.sensor_detection import effective_sensor_range
    r = effective_sensor_range(player)
    return r > 0.0 and _dist(player, obj) <= r * sensor_dials.get("near_fraction")


def _scan_blocked(player, obj) -> bool:
    """A scan never sees through a major rock -- under the same toggle that
    gates occlusion inside can_detect."""
    from engine.appc import sensor_detection, sensor_occlusion
    return bool(sensor_detection.ENHANCED_SENSOR_CONTEST
                and sensor_occlusion.blocked(player, obj))


def _commit_due(player, sensors, now_gt) -> None:
    from engine.appc.sensor_detection import can_detect
    from engine.appc.sensor_identification import _identify_one
    for obj, (due, by_scan) in list(_pending.items()):
        if now_gt < due:
            continue
        _pending.pop(obj, None)
        known = bool(sensors.IsObjectKnown(obj))
        if by_scan:
            if _scan_blocked(player, obj):
                continue
            # A KNOWN contact here is a rescan of one reading Unknown in a
            # medium: restart its glimpse without re-identifying it (no
            # second ET_SENSORS_SHIP_IDENTIFIED -- _identify_one would
            # refuse a known contact anyway).
            if known or _identify_one(sensors, obj):
                _scanned_at[obj] = now_gt
                if is_concealed(player, obj):
                    _concealed_since[obj] = now_gt    # one window from the scan
        elif (not known and _in_near_band(player, obj)
              and can_detect(player, obj) and not _unknown_by_medium(obj)):
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
        known = bool(sensors.IsObjectKnown(obj))
        if known:
            _continuity(player, sensors, obj, now_gt)
        else:
            _concealed_since.pop(obj, None)
            if (near and obj not in _pending and can_detect(player, obj)
                    and not _unknown_by_medium(obj)):
                _pending[obj] = (now_gt + dwell, False)
        _sync_science_label(obj, now_gt)


def _continuity(player, sensors, obj, now_gt) -> None:
    """Run the continuity clock for one KNOWN contact (see module doc)."""
    if not is_concealed(player, obj):
        _concealed_since.pop(obj, None)
        return
    since = _concealed_since.setdefault(obj, now_gt)
    if now_gt - since >= sensor_dials.get("continuity_window_s"):
        _lose_track(player, sensors, obj)


def tick(player, now_gt: float) -> None:
    global _next_sweep_gt
    from engine.appc import sensor_occlusion
    sensor_occlusion.begin_tick(now_gt)
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
    Commits when due unless a major rock blocks the line then. Keeps the
    earlier due time if one is already pending. No-op if *obj* already shows
    its identity; a KNOWN contact reading Unknown in a medium is re-armed,
    and its commit restarts the glimpse (see `_commit_due`)."""
    if obj is None or shows_identity(obj):
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
    _concealed_since.pop(obj, None)
    _scanned_at.pop(obj, None)
    _shown_real.pop(obj, None)
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
