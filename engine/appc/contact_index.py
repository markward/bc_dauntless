"""Ships bucketed by the set that contains them — the persistent half of the
contact model.

The store holds what EXISTS. It is observer-independent by construction: AI
ships and the player ask the same question, and the target, hail and scan lists
all read the same buckets. Anything observer-relative (range, cloak, nebula
concealment) is computed at read time by engine.appc.perception, never stored
here.

Only membership is stored. Authored flags (IsTargetable / IsHailable /
IsScannable), alive-or-dead, and positions are read through to the object at
query time. Copying them here would mean a write per change — and for positions,
a write per ship per frame — with a stale contact on any missed write, which is
the exact failure this index exists to remove.

Maintained by SetClass.AddObjectToSet / RemoveObjectFromSet /
DeleteObjectFromSet, which call in directly (the same shape as the existing
ship_lifecycle.publish_added call beside them).

Keyed by the SetClass OBJECT, not its name: QuickBattle renames a set in place
when reloading a region (QuickBattle.py:2678 appends "Dupe"), so a name key
would silently split one bucket in two.

This index's correctness rests on one fact: engine/appc/sets.py:186
(`self._objects[identifier] = obj`, in `SetClass.AddObjectToSet`) is the ONLY
place that inserts an object into a set's object dict, with the call to
`contact_index.on_added` sitting right beside it. Every reader here — the
target/hail/scan lists, sensor_detection.concealment_at — trusts that a set's
buckets and its `_objects` dict never drift apart because there is exactly one
door in. Three call sites still bypass the index and scan
`GetClassObjectList(App.CT_NEBULA)` directly instead of `nebulae_in` —
host_loop.py:3770 and :7505 (nebula rendering) and
engine.appc.nebula_runtime._nebulae_in_set — so they agree with the index today
only because that single-insertion invariant holds. A future second write path
into `_objects` (a mission script poking a set's dict directly, a save/load
restore that reconstructs membership by hand, and so on) would desync
**sensors**, which read this index via `concealment_at`, from the **renderer**,
which still scans the set — producing a nebula that is drawn but no longer
conceals, or vice versa, with no exception raised on either side.
"""
from __future__ import annotations

from engine.appc import native_combat

# Every mutation of a bucket below is followed by
# native_combat.push_set_members(pSet): the native combat mirror holds each
# set's ship and nebula lists in exactly this order (occlusion iterates it).

# SetClass -> list of ShipClass, in insertion order.
_buckets: dict = {}

# SetClass -> list of Nebula (App.CT_NEBULA), in insertion order. Nebulae
# essentially never spawn or despawn mid-mission, so — like the ship
# buckets above — this is genuinely event-maintained state rather than
# something worth rediscovering by scanning the set on every query.
# sensor_detection.concealment_at reads this instead of calling
# pSet.GetClassObjectList(App.CT_NEBULA) once per ship, per call.
_nebula_buckets: dict = {}


def on_added(pSet, obj) -> None:
    """Record *obj* as present in *pSet*. Ships and nebulae are bucketed;
    everything else is ignored, so no read-time type test is needed.
    Idempotent."""
    from engine.appc.ships import ShipClass
    from App import Nebula
    if isinstance(obj, ShipClass):
        bucket = _buckets.setdefault(pSet, [])
        if obj not in bucket:
            bucket.append(obj)
            native_combat.push_set_members(pSet)
        return
    if isinstance(obj, Nebula):
        bucket = _nebula_buckets.setdefault(pSet, [])
        if obj not in bucket:
            bucket.append(obj)
            native_combat.push_set_members(pSet)


def on_removed(pSet, obj) -> None:
    """Drop *obj* from *pSet*'s bucket(s). Silent if absent —
    RemoveObjectFromSet is called for objects that were never ships or
    nebulae."""
    changed = False
    bucket = _buckets.get(pSet)
    if bucket:
        try:
            bucket.remove(obj)
            changed = True
        except ValueError:
            pass
    nebula_bucket = _nebula_buckets.get(pSet)
    if nebula_bucket:
        try:
            nebula_bucket.remove(obj)
            changed = True
        except ValueError:
            pass
    if changed:
        native_combat.push_set_members(pSet)


def ships_in(pSet) -> tuple:
    """Ships currently in *pSet*, in insertion order. Empty for an unknown set."""
    return tuple(_buckets.get(pSet, ()))


def ship_positions_in(pSet) -> tuple:
    """(ship, (x, y, z)) for every ship in *pSet*, same order as ships_in.

    Every bucketed ship is a ShipClass (see on_added's isinstance gate), so
    every one carries a transform-store handle. This still reads positions
    through to the object at query time, per the module docstring above — the
    only change is one bulk transform-store call for the whole set instead of
    one per ship, for callers (engine.appc.perception.perceived_by) that walk
    every ship in a set once per call."""
    ships = ships_in(pSet)
    if not ships:
        return ()
    from engine.appc.transform_store import get_store
    positions = get_store().get_positions([s._xform for s in ships])
    return tuple(zip(ships, positions))


def nebulae_in(pSet) -> tuple:
    """Nebulae currently in *pSet*, in insertion order. Empty for an unknown
    set or a set with none."""
    return tuple(_nebula_buckets.get(pSet, ()))


def sets_holding(obj) -> list:
    """Every set whose ship or nebula bucket holds *obj* (identity), in
    bucket order. For native_combat, when *obj*'s mirror row is dropped."""
    out = []
    for buckets in (_buckets, _nebula_buckets):
        for pSet, bucket in buckets.items():
            if (all(p is not pSet for p in out)
                    and any(o is obj for o in bucket)):
                out.append(pSet)
    return out


def reset() -> None:
    """Drop every bucket. Called on mission swap and between tests."""
    emptied = list(_buckets) + [s for s in _nebula_buckets
                                if s not in _buckets]
    _buckets.clear()
    _nebula_buckets.clear()
    for pSet in emptied:
        native_combat.push_set_members(pSet)


def forget_set(pSet) -> None:
    """Drop *pSet*'s buckets -- a set deleted by a carry-over mission change
    (engine.core.mission_change), whose kept sets keep theirs."""
    had = _buckets.pop(pSet, None) is not None
    had = (_nebula_buckets.pop(pSet, None) is not None) or had
    if had:
        native_combat.push_set_members(pSet)
