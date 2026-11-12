"""Tear a destroyed ship's AI down at the moment it is deleted.

BC deletes a ship's AI tree with the ship: the C++ nodes and ConditionScripts
go, each releasing its Python script instance, so from that instant none of
them handles an event, fires a timer or watches a proximity sphere.

Ours used to keep all of it forever (the strong id registry held the ship),
which leaked but was at least deterministic. Freed only by the cyclic GC,
the tree would keep reacting until a collection that allocation noise can
move -- tests/integration/test_presentation_rng_falsifier.py saw an AI timer
reach a dead condition in one arm and not the other. So the release is
explicit, here, at deletion: the script instances are dropped, the wrappers
they own stop dispatching to them, their broadcast handlers are removed and
their time-slice processes stopped. What the GC later collects can no longer
do anything.
"""
from __future__ import annotations


def tear_down(ship) -> None:
    """Release `ship`'s AI tree (see the module docstring). A no-op for a
    ship with no AI."""
    root = ship.__dict__.get("_ai")
    if root is None:
        return
    try:
        nodes = list(root.GetAllAIsInTree())
    except Exception:
        nodes = [root]
    in_tree = {id(n) for n in nodes}
    owners = []
    for node in nodes:
        d = getattr(node, "__dict__", None)
        if d is None:
            continue
        for key in ("_script_instance", "_preprocessing_instance"):
            inst = d.get(key)
            if inst is not None:
                owners.append(inst)
                d[key] = None
        for cond in list(d.get("_conditions", ())):
            cd = getattr(cond, "__dict__", None)
            inst = cd.get("_instance") if cd is not None else None
            if inst is None:
                continue
            # A condition something outside this tree also watches (a
            # mission's ConditionEventCreator, a TGConditionAction) is not
            # this ship's to delete.
            live = getattr(cond, "_live_handlers", None)
            if live is not None and any(id(h) not in in_tree for h in live()):
                continue
            owners.append(inst)
            cd["_instance"] = None
    ship.__dict__["_ai"] = None
    silence(owners)


def silence(owners) -> None:
    """Stop every wrapper, broadcast handler and time-slice process that
    belongs to one of `owners`. An owner is matched by identity or by its
    __dict__ (the native SelectTarget binding is an alias object sharing the
    SDK instance's __dict__)."""
    if not owners:
        return
    import App
    from engine.appc.events import TGPythonInstanceWrapper
    from engine.appc.time_slice import g_kAIManager

    owner_ids = {id(o) for o in owners}
    owner_dicts = {id(o.__dict__) for o in owners
                   if getattr(o, "__dict__", None) is not None}

    def owned(py) -> bool:
        if py is None:
            return False
        if id(py) in owner_ids:
            return True
        d = getattr(py, "__dict__", None)
        return d is not None and id(d) in owner_dicts

    wrappers = {}
    for o in owners:
        for v in list(getattr(o, "__dict__", {}).values()):
            if isinstance(v, TGPythonInstanceWrapper):
                wrappers[id(v)] = v
    em = App.g_kEventManager
    for handlers in list(em._method_handlers.values()):
        hit = False
        for w, _m, _f in handlers:
            if id(w) in wrappers:
                hit = True
                continue
            get = getattr(type(w), "GetPyWrapper", None)
            if get is not None and owned(get(w)):
                wrappers[id(w)] = w
                hit = True
        if hit:
            # In place: a dispatch in progress iterates a snapshot.
            handlers[:] = [h for h in handlers if id(h[0]) not in wrappers]
    for w in wrappers.values():
        # Events addressed to the wrapper (an AI timer's) now reach nobody.
        w.SetPyWrapper(None)
    for proc in g_kAIManager._live():
        resolve = getattr(proc, "_resolve_instance", None)
        if resolve is not None and owned(resolve()):
            g_kAIManager.Remove(proc)
