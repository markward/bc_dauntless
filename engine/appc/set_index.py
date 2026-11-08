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
keeps sets across tests. A set deleted by a carry-over mission change is not
forgotten either: while anything still holds it, its lists must keep matching
its `_objects`. `forget_set` and `reset` remain as explicit calls.

Members are borrowed, so a write that bypasses the doors can leave a dangling
key: the writer guard is what makes that safe, and the audit checks the
entry count against `len(_objects)` before it reads the index.
"""
from __future__ import annotations

import _dauntless_host as _h

from engine.core.ids import implements


def target_id(target) -> int:
    """The count key of a ship's target: its GetObjID(), -1 for none."""
    if target is None or not implements(target, "GetObjID"):
        return -1
    return int(target.GetObjID())


def _is_contact(obj) -> bool:
    return isinstance(obj, (_ShipClass, _Nebula))


def _push(pSet) -> None:
    """The set's contact view changed: refresh the native combat mirror."""
    from engine.appc import native_combat
    native_combat.push_set_members(pSet)


def on_added(pSet, identifier: str, obj, previous=None) -> None:
    """`pSet._objects[identifier] = obj` just ran (AddObjectToSet).
    `previous` is what the identifier held before, if anything (the caller
    keeps it alive until this returns)."""
    contact_new = _is_contact(obj)
    contact_prev = (previous is not None and previous is not obj
                    and _is_contact(previous))
    seen_new = contact_new and _h.set_index_visible(pSet, obj)
    seen_prev = contact_prev and _h.set_index_visible(pSet, previous)
    own_id = target_id(obj)  # the id other ships' targets count it under
    if isinstance(obj, _ShipClass):
        _h.set_index_add(pSet, identifier, obj, True, target_id(obj.GetTarget()),
                         own_id)
    else:
        _h.set_index_add(pSet, identifier, obj, False, -1, own_id)
    if ((contact_new and not seen_new)
            or (seen_prev and not _h.set_index_visible(pSet, previous))):
        _push(pSet)


def on_leaving(pSet, identifier: str, obj) -> None:
    """A removal door is about to run its handlers for `identifier`, which
    holds `obj`."""
    seen = _is_contact(obj) and _h.set_index_visible(pSet, obj)
    _h.set_index_leaving(pSet, identifier)
    if seen and not _h.set_index_visible(pSet, obj):
        _push(pSet)


def on_removed(pSet, identifier: str, removed) -> None:
    """A removal door popped `identifier` (which held `removed`) from
    `pSet._objects`. Only an entry that is still visible changes the
    contact view (a handler re-added it)."""
    seen = _is_contact(removed) and _h.set_index_visible(pSet, removed)
    _h.set_index_remove(pSet, identifier)
    if seen and not _h.set_index_visible(pSet, removed):
        _push(pSet)


def on_reclassified(obj) -> None:
    """`obj.__class__` changed (native_combat.reclassify)."""
    _h.set_index_reclassified(obj, isinstance(obj, _ShipClass))


def on_target_changed(ship) -> None:
    """`ship._target` just changed (ShipClass.SetTarget, the only writer)."""
    _h.set_index_set_target(ship, target_id(ship._target))


def targeted_by_count(pSet, target) -> int:
    """Entries of `pSet` whose ship currently targets `target`. Target
    membership in `pSet` is irrelevant: the key is the target's GetObjID()."""
    return _h.set_index_targeted_by(pSet, target_id(target))


def targeting(pSet, target) -> list:
    """The ships of `pSet` targeting `target`, in set order, one per entry
    (an object under two identifiers is listed twice, as it is counted)."""
    return _h.set_index_targeting(pSet, target_id(target))


def popularity(pSet, rater, target) -> float:
    """The stock GetTargetRating fPopularity: other entries of `pSet`
    targeting `target`, the rater's own entries skipped. A float, as the SDK
    loop sums 1.0s."""
    return float(_h.set_index_popularity(pSet, rater, target_id(target)))


def class_objects(pSet, cls: type) -> list:
    """Members of `pSet` that are instances of `cls`, in `_objects` order, as
    a NEW list. The bucket is created on first use."""
    return _h.set_index_class_objects(pSet, cls)


def ships_in(pSet) -> tuple:
    """Distinct ShipClass members of `pSet` not leaving, first-entry order."""
    return _h.set_index_ships(pSet)


def ship_positions_in(pSet) -> tuple:
    """((ship, (x, y, z)), ...) for ships_in(pSet), in one native call. A
    stale transform handle raises StaleHandleError, as get_positions does."""
    try:
        return _h.set_index_ship_positions(pSet)
    except (RuntimeError, TypeError) as exc:
        from engine.appc.transform_store import StaleHandleError
        raise StaleHandleError(str(exc)) from exc


def nebulae_in(pSet) -> tuple:
    """Distinct Nebula members of `pSet` not leaving, first-entry order."""
    return _h.set_index_nebulae(pSet)


def sets_holding(obj) -> list:
    """Every set holding `obj` under an entry that is not leaving."""
    return _h.set_index_sets_holding(obj)


def entry_count(pSet) -> int:
    """Entries the index holds for `pSet`: len(pSet._objects) when in step."""
    return _h.set_index_entry_count(pSet)


def hide_contacts(pSet) -> None:
    """Empty `pSet`'s contact view (ships_in, nebulae_in, sets_holding) while
    its class lists and counts stay equal to its `_objects`. A later add shows
    its member. This is what a mission swap and a carry-over mission change
    do to a set that may still be alive."""
    if _h.set_index_hide(pSet):
        _push(pSet)


def hide_all_contacts() -> None:
    """hide_contacts for every set the index tracks."""
    for pSet in _h.set_index_hide_all():
        _push(pSet)


def forget_set(pSet) -> None:
    """Forget `pSet` now. Explicit only: a set's death forgets it anyway, and
    forgetting a set that is still alive makes its lists diverge from its
    `_objects`."""
    changed = _h.set_index_hide(pSet)
    _h.set_index_forget_set(pSet)
    if changed:
        _push(pSet)


def reset() -> None:
    """Forget every set. Explicit only: a set's death forgets it anyway."""
    changed = _h.set_index_hide_all()
    _h.set_index_reset()
    for pSet in changed:
        _push(pSet)


def _configure():
    from App import Nebula
    from engine.appc.ships import ShipClass
    _h.set_index_configure(ShipClass, Nebula)
    return ShipClass, Nebula


_ShipClass, _Nebula = _configure()
