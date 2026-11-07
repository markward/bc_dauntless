"""The native set index: every SetClass's members by class, in C++.

`SetClass._objects` stays the source of truth; this mirrors it slot for slot
(native/src/combat/include/dauntless/combat/set_index.h) so that
`SetClass.GetClassObjectList` is a bucket read, not a scan of the whole set,
and so the native AI stages can ask the same questions without Python.

What it reproduces, exactly (spec 2026-11-05-phase6-engine-stages-native,
§4.1):

- **Order.** Dict slot order: an overwritten identifier keeps its slot, a
  popped one that is added again goes to the end.
- **Multiplicity.** One entry per identifier; an object under two identifiers
  is listed twice, as the scan lists it.
- **Removal timing.** The removal doors run their handlers BEFORE
  `_objects.pop`. `on_leaving` (before the handlers) hides the entry from the
  contact view (`ships_in`, `nebulae_in`, `sets_holding`) only; `on_removed`
  (at the pop) takes it out of the class lists. So a handler reading
  `GetClassObjectList` during an ET_EXITED_SET broadcast still sees the
  leaving object (SDK ConditionIncomingTorps reads CT_TORPEDO there).
- **Class test.** `isinstance`, when a bucket is created, when a member is
  added, and again for every bucket holding an object whose `__class__`
  changed (`on_reclassified`, from `native_combat.reclassify`: the rock
  conversion in engine/rocks/rock.py is the only `__class__` swap).

Kept in step by exactly three doors in engine/appc/sets.py
(AddObjectToSet, RemoveObjectFromSet, DeleteObjectFromSet), the only writers
of `_objects` (guarded by tests/unit/test_set_index.py). A write that bypasses
them desyncs the index silently; `DAUNTLESS_SET_INDEX_AUDIT=1` makes
GetClassObjectList compare against the old scan and raise on any difference.
There is no Python copy to fall back to.

Lifetime: exactly each set's own, never a reset call. Members are BORROWED
(the set's `_objects` dict keeps them alive, and the index mirrors it), and
each set is held by a weakref whose callback forgets it, so a set and its
members die as if the index did not exist. A reset tied to the mission swap
would be wrong: HostController runs host_loop.reset_mission_state BEFORE
reset_sdk_globals tears down against still-live sets, and tests/conftest.py
keeps sets across tests. `forget_set` (a set deleted by a carry-over mission
change) and `reset` remain as explicit calls. Members are borrowed, so a
write that bypasses the doors can leave a dangling key: the writer guard is
what makes that safe.
"""
from __future__ import annotations

import _dauntless_host as _h

from engine.core.ids import implements


def target_id(target) -> int:
    """The count key of a ship's target: its GetObjID(), -1 for none."""
    if target is None or not implements(target, "GetObjID"):
        return -1
    return int(target.GetObjID())


def on_added(pSet, identifier: str, obj) -> None:
    """`pSet._objects[identifier] = obj` just ran (AddObjectToSet)."""
    if isinstance(obj, _ShipClass):
        _h.set_index_add(pSet, identifier, obj, True, target_id(obj.GetTarget()))
    else:
        _h.set_index_add(pSet, identifier, obj, False, -1)


def on_leaving(pSet, identifier: str) -> None:
    """A removal door is about to run its handlers for `identifier`."""
    _h.set_index_leaving(pSet, identifier)


def on_removed(pSet, identifier: str) -> None:
    """A removal door popped `identifier` from `pSet._objects`."""
    _h.set_index_remove(pSet, identifier)


def on_reclassified(obj) -> None:
    """`obj.__class__` changed (native_combat.reclassify)."""
    _h.set_index_reclassified(obj, isinstance(obj, _ShipClass))


def class_objects(pSet, cls: type) -> list:
    """Members of `pSet` that are instances of `cls`, in `_objects` order, as
    a NEW list. The bucket is created on first use."""
    return _h.set_index_class_objects(pSet, cls)


def ships_in(pSet) -> tuple:
    """Distinct ShipClass members of `pSet` not leaving, first-entry order."""
    return _h.set_index_ships(pSet)


def nebulae_in(pSet) -> tuple:
    """Distinct Nebula members of `pSet` not leaving, first-entry order."""
    return _h.set_index_nebulae(pSet)


def sets_holding(obj) -> list:
    """Every set holding `obj` under an entry that is not leaving."""
    return _h.set_index_sets_holding(obj)


def forget_set(pSet) -> None:
    """Forget `pSet` (deleted by a carry-over mission change)."""
    _h.set_index_forget_set(pSet)


def reset() -> None:
    """Forget every set. Explicit only: a set's death forgets it anyway."""
    _h.set_index_reset()


def _configure():
    from App import Nebula
    from engine.appc.ships import ShipClass
    _h.set_index_configure(ShipClass, Nebula)
    return ShipClass


_ShipClass = _configure()
