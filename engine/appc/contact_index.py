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
"""
from __future__ import annotations

# SetClass -> list of ShipClass, in insertion order.
_buckets: dict = {}


def on_added(pSet, obj) -> None:
    """Record *obj* as present in *pSet*. Non-ships are ignored, so no
    read-time type test is needed. Idempotent."""
    from engine.appc.ships import ShipClass
    if not isinstance(obj, ShipClass):
        return
    bucket = _buckets.setdefault(pSet, [])
    if obj not in bucket:
        bucket.append(obj)


def on_removed(pSet, obj) -> None:
    """Drop *obj* from *pSet*'s bucket. Silent if absent — RemoveObjectFromSet
    is called for objects that were never ships."""
    bucket = _buckets.get(pSet)
    if not bucket:
        return
    try:
        bucket.remove(obj)
    except ValueError:
        pass


def ships_in(pSet) -> tuple:
    """Ships currently in *pSet*, in insertion order. Empty for an unknown set."""
    return tuple(_buckets.get(pSet, ()))


def reset() -> None:
    """Drop every bucket. Called on mission swap and between tests."""
    _buckets.clear()
