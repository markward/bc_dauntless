"""Ships and nebulae by the set that contains them — the contact view of the
native set index.

There is ONE set index (engine/appc/set_index.py, native/src/combat/): it
mirrors every SetClass's `_objects` slot for slot and answers both
`GetClassObjectList` and this contact view. This module is a thin reader over
it; it stores nothing. (It used to keep its own per-set buckets, kept in step
by a second pair of calls beside the index's, which is how the two could
drift.)

The view holds what EXISTS. It is observer-independent by construction: AI
ships and the player ask the same question, and the target, hail and scan lists
all read it. Anything observer-relative (range, cloak, nebula concealment) is
computed at read time by engine.appc.perception, never stored.

Only membership is held. Authored flags (IsTargetable / IsHailable /
IsScannable), alive-or-dead, and positions are read through to the object at
query time. Copying them would mean a write per change — and for positions, a
write per ship per frame — with a stale contact on any missed write, which is
the exact failure this index exists to remove.

What the view is: the DISTINCT `ShipClass` (or `Nebula`) members of the set,
in first-entry order, whose entry is not LEAVING. A removal door marks the
entry LEAVING before it runs its handlers, so the view stops listing the
object before any handler runs, while `GetClassObjectList` keeps listing it
until the pop (SDK ConditionIncomingTorps reads it during an exit broadcast).
The view is observer-independent and keyed by the SetClass OBJECT, not its
name: QuickBattle renames a set in place when reloading a region
(QuickBattle.py:2678 appends "Dupe").

Whenever a set's view changes, set_index calls
native_combat.push_set_members(pSet): the native combat mirror holds each
set's ship and nebula lists in exactly this order (occlusion iterates it).

This view's correctness rests on one fact: SetClass.AddObjectToSet /
RemoveObjectFromSet / DeleteObjectFromSet (engine/appc/sets.py) are the ONLY
writers of a set's `_objects`, and each calls the set index right beside the
write (tests/unit/test_set_index.py guards it). Three call sites still bypass
the view and scan `GetClassObjectList(App.CT_NEBULA)` directly instead of
`nebulae_in` — host_loop.py (nebula rendering, twice) and
engine.appc.nebula_runtime._nebulae_in_set — so they agree with it only
because that invariant holds. A second write path into `_objects` would desync
**sensors**, which read this view via `concealment_at`, from the
**renderer**, which still scans the set, with no exception on either side.

`reset()` and `forget_set(pSet)` HIDE rather than forget: the sets may still
be alive (a mission swap clears the view before the swap tears the sets down),
so their class lists and counts must keep matching `_objects`. A hidden set
shows a member again as soon as it is added.

Two deliberate differences from the old private buckets, both of which were
drift bugs there: an identifier overwritten with another ship drops the old
ship from the view (it stayed listed forever), and an object still present
under a second identifier stays listed when one of its entries is removed (one
removal dropped it).
"""
from __future__ import annotations

from engine.appc import set_index


def ships_in(pSet) -> tuple:
    """Ships currently in *pSet*, in first-entry order. Empty for an unknown
    set."""
    return set_index.ships_in(pSet)


def ship_positions_in(pSet) -> tuple:
    """(ship, (x, y, z)) for every ship in *pSet*, same order as ships_in.

    Every listed ship is a ShipClass, so every one carries a transform-store
    handle. This still reads positions through to the object at query time,
    per the module docstring above — the only change is one bulk
    transform-store call for the whole set instead of one per ship, for
    callers (engine.appc.perception.perceived_by) that walk every ship in a
    set once per call."""
    ships = ships_in(pSet)
    if not ships:
        return ()
    from engine.appc.transform_store import get_store
    positions = get_store().get_positions([s._xform for s in ships])
    return tuple(zip(ships, positions))


def nebulae_in(pSet) -> tuple:
    """Nebulae currently in *pSet*, in first-entry order. Empty for an
    unknown set or a set with none."""
    return set_index.nebulae_in(pSet)


def sets_holding(obj) -> list:
    """Every set whose ship or nebula view lists *obj*. For native_combat,
    when *obj*'s mirror row is dropped."""
    if not set_index._is_contact(obj):
        return []
    return set_index.sets_holding(obj)


def reset() -> None:
    """Empty every set's view. Called on mission swap and between tests."""
    set_index.hide_all_contacts()


def forget_set(pSet) -> None:
    """Empty *pSet*'s view -- a set deleted by a carry-over mission change
    (engine.core.mission_change), whose kept sets keep theirs."""
    set_index.hide_contacts(pSet)
