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
        return
    if isinstance(obj, Nebula):
        bucket = _nebula_buckets.setdefault(pSet, [])
        if obj not in bucket:
            bucket.append(obj)


def on_removed(pSet, obj) -> None:
    """Drop *obj* from *pSet*'s bucket(s). Silent if absent —
    RemoveObjectFromSet is called for objects that were never ships or
    nebulae."""
    bucket = _buckets.get(pSet)
    if bucket:
        try:
            bucket.remove(obj)
        except ValueError:
            pass
    nebula_bucket = _nebula_buckets.get(pSet)
    if nebula_bucket:
        try:
            nebula_bucket.remove(obj)
        except ValueError:
            pass


def ships_in(pSet) -> tuple:
    """Ships currently in *pSet*, in insertion order. Empty for an unknown set."""
    return tuple(_buckets.get(pSet, ()))


def nebulae_in(pSet) -> tuple:
    """Nebulae currently in *pSet*, in insertion order. Empty for an unknown
    set or a set with none."""
    return tuple(_nebula_buckets.get(pSet, ()))


def reset() -> None:
    """Drop every bucket. Called on mission swap and between tests."""
    _buckets.clear()
    _nebula_buckets.clear()
