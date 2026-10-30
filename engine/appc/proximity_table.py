"""The per-tick ProximityCheck pass, run from a cached pair table.

The pass itself is unchanged in meaning: every set, every check its
ProximityManager registered, every watched entry, each tested by
ProximityCheck._evaluate_one. What changed is who looks at the quiet pairs.

A 64-ship fight carries 272 live (check, watched ship) pairs -- one per
ConditionInRange -- and evaluating each in Python cost ~1 ms a tick, while 94%
of ticks fire nothing. The check lists only change when a condition is set up
or retargeted (in that fight: one tick, at mission start). So the pairs are
packed once into the buffers TransformStore.proximity_report reads, and each
tick one store call returns the few pairs that could fire. Only those go back
through _evaluate_one, so the gates (same set, pending delete) and the event
are the same code as before.

A firing runs its handlers synchronously (AddEvent dispatches), and a handler
can change what later pairs in the same pass see:
  - it re-arms its own pair (ConditionInRange.ProximityEvent always does):
    ProximityCheck.SetTriggerType patches that pair's want byte in place;
  - it moves something, or re-arms a later pair: the pairs after it are
    re-tested from the store before the pass goes on;
  - it changes a check list, a radius, an anchor or a registration
    (`touch`): the rest of the pass runs the old way, from exactly where it
    stopped, and the table is rebuilt next tick.

Pairs the store cannot test -- an object or anchor that answers
GetWorldLocation itself, a check registered with an explicit anchor -- are
always reported, and Python runs them in their place in the order.
"""
from array import array

from engine.appc.transform_store import get_store

# want bytes, as TransformStore.proximity_report reads them.
_WANT_INSIDE = 0
_WANT_OUTSIDE = 1
_ALWAYS = 2
_NEVER = 3

# Stands in for the watched object on a row that runs a whole
# ProximityCheck.Evaluate(anchor) -- a check registered with its anchor.
_WHOLE_CHECK = object()

_epoch = 0
_table = None


def location_is_stored(obj) -> bool:
    """Is `obj`'s GetWorldLocation exactly its transform-store slot?

    False for anything that answers GetWorldLocation itself (DebrisChunk,
    subsystems, bridge objects, test doubles): those must be asked.
    """
    from engine.appc.objects import ObjectClass
    d = getattr(obj, "__dict__", None)
    return (d is not None and "_xform" in d and "GetWorldLocation" not in d
            and getattr(type(obj), "GetWorldLocation", None)
            is ObjectClass.GetWorldLocation)


def touch() -> None:
    """A check list, radius, anchor or registration changed: drop the table.

    Mid-pass, this also tells the running pass to finish the old way."""
    global _epoch, _table
    _epoch += 1
    _table = None


def reset() -> None:
    """Drop the table (and the objects it holds). For test isolation."""
    touch()


def _want(trigger_type) -> int:
    if trigger_type == 0:
        return _WANT_INSIDE
    if trigger_type == 1:
        return _WANT_OUTSIDE
    return _NEVER       # _evaluate_one fires on neither


def retrigger(check, obj, trigger_type) -> None:
    """ProximityCheck.SetTriggerType(obj, tt) re-armed `obj` on `check`.

    Patches the table in place rather than dropping it: ConditionInRange
    re-arms on every firing, and a rebuild per firing would cost more than the
    pass it saves."""
    t = _table
    if t is None:
        return
    want = _want(trigger_type)
    for k in t.by_check.get(id(check), ()):
        if t.objs[k] is obj and t.want[k] != _ALWAYS:
            t.want[k] = want


class _Table:
    __slots__ = ("key", "levels", "checks", "objs", "anchor_args", "where",
                 "by_check", "anchors", "objects", "r2", "want")

    def __init__(self, key, levels):
        self.key = key
        # (set, checks list) per set, in pass order; checks is None when the
        # set has no ProximityManager.
        self.levels = levels
        self.checks, self.objs, self.anchor_args, self.where = [], [], [], []
        self.by_check = {}
        self.anchors, self.objects = array("I"), array("I")
        self.r2, self.want = array("d"), bytearray()

    def add(self, check, obj, anchor_arg, where, centre, r2, want):
        k = len(self.checks)
        self.checks.append(check)
        self.objs.append(obj)
        self.anchor_args.append(anchor_arg)
        self.where.append(where)
        if want == _ALWAYS:
            self.anchors.extend((0, 0))
            self.objects.extend((0, 0))
        else:
            self.anchors.extend(centre._xform)
            self.objects.extend(obj._xform)
            self.by_check.setdefault(id(check), []).append(k)
        self.r2.append(r2)
        self.want.append(want)

    def report(self, start):
        return get_store().proximity_report(
            self.anchors, self.objects, self.r2, self.want, start)


def _levels(sets):
    """(set, its manager's check list) per set, as the old pass read them --
    GetProximityManager() included, which creates a set's manager."""
    out = []
    for pSet in sets:
        pm = pSet.GetProximityManager() if hasattr(pSet, "GetProximityManager") else None
        out.append((pSet, None if pm is None
                    else getattr(pm, "_proximity_checks", ())))
    return out


def _key(levels):
    # The table holds every set and list in it, so these ids cannot be
    # reused while it lives. The length catches an append that skipped touch.
    return tuple((id(s), id(c), -1 if c is None else len(c)) for s, c in levels)


def _build(levels, key) -> _Table:
    t = _Table(key, levels)
    for si, (_pSet, checks) in enumerate(levels):
        if checks is None:
            continue
        for ci, (check, anchor) in enumerate(checks):
            where = (si, ci)
            if anchor is not None:
                t.add(check, _WHOLE_CHECK, anchor, where, None, 0.0, _ALWAYS)
                continue
            centre = check._anchor if check._anchor is not None else check
            centre_ok = location_is_stored(centre)
            radius = check._proximity_radius
            r2 = radius * radius
            # _evaluate_one reads the FIRST entry's trigger type for an
            # object listed twice.
            first = {}
            for obj, tt in check._check_objects:
                first.setdefault(id(obj), tt)
            for obj, _tt in check._check_objects:
                if centre_ok and location_is_stored(obj):
                    t.add(check, obj, None, where, centre, r2,
                          _want(first[id(obj)]))
                else:
                    t.add(check, obj, None, where, None, r2, _ALWAYS)
    return t


def _run(t, k) -> bool:
    """Row k through the unchanged Python path. True when it may have run a
    handler."""
    obj = t.objs[k]
    if obj is _WHOLE_CHECK:
        t.checks[k].Evaluate(t.anchor_args[k])
        return True
    return bool(t.checks[k]._evaluate_one(obj))


def _finish_old_way(t, k) -> None:
    """Row k's handler changed a check list: finish the pass as the old loop
    would have, from row k on."""
    si, ci = t.where[k]
    check = t.checks[k]
    if t.objs[k] is not _WHOLE_CHECK:
        # The rest of this check's Evaluate snapshot, taken before row k ran.
        j = k + 1
        while j < len(t.where) and t.where[j] == (si, ci):
            check._evaluate_one(t.objs[j])
            j += 1
    # The rest of this manager's list, live (as a for loop over it reads it).
    checks = t.levels[si][1]
    idx = ci + 1
    while idx < len(checks):
        c, a = checks[idx]
        c.Evaluate(a)
        idx += 1
    for pSet, _checks in t.levels[si + 1:]:
        pm = pSet.GetProximityManager() if hasattr(pSet, "GetProximityManager") else None
        if pm is None:
            continue
        for c, a in getattr(pm, "_proximity_checks", ()):
            c.Evaluate(a)


def evaluate() -> None:
    """One pass over every ProximityCheck. See the module docstring."""
    global _table
    import App
    levels = _levels(list(App.g_kSetManager._sets.values()))
    key = _key(levels)
    t = _table
    if t is None or t.key != key:
        t = _table = _build(levels, key)
    epoch = _epoch
    todo = t.report(0)
    i = 0
    while i < len(todo):
        k = todo[i]
        i += 1
        if not _run(t, k):
            continue
        if _epoch != epoch:
            _finish_old_way(t, k)
            return
        # A handler ran: whatever it moved or re-armed, test the rest again.
        todo = t.report(k + 1)
        i = 0
