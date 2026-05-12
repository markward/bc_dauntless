"""Walk live ships / set objects.

Extracted from engine/host_loop.py so the headless gameloop can drive
per-tick subsystem updates without pulling in the renderer-host module.

Iteration intentionally uses `pSet._objects.values()` rather than BC's
`GetFirstObject + GetNextObject` API: the latter is unreliable in the
presence of stub objects.  Any object whose `GetObjID()` returns an
`App._NamedStub` causes `SetClass.GetNextObject(stub).int(stub) -> 0`
to find no match and return None, terminating iteration prematurely.
The `_objects` private attribute is already inspected elsewhere
(set-membership checks, verbose logging), so the implementation
coupling is consistent.
"""
from typing import Iterable

import App


def iter_set_objects(pSet) -> Iterable:
    """Walk every object in a set exactly once via _objects.values()."""
    for obj in getattr(pSet, "_objects", {}).values():
        yield obj


def iter_ships(*, verbose: bool = False) -> Iterable:
    """Walk every ShipClass-like object in every active set."""
    from engine.appc.ships import ShipClass
    for set_name, pSet in App.g_kSetManager._sets.items():
        if verbose:
            count = len(getattr(pSet, "_objects", {}))
            obj_keys = list(getattr(pSet, "_objects", {}).keys())
            print(f"[ship_iter] set {set_name!r}: {count} object(s), keys={obj_keys}", flush=True)
        for obj in iter_set_objects(pSet):
            # Reject _NamedStub and any other non-ship members — set objects
            # include grids, waypoints, characters, and SDK stubs for engine
            # classes we don't model yet (GridClass etc.). hasattr() can't
            # discriminate against _NamedStub because its __getattr__ returns
            # a stub for any name.
            if isinstance(obj, ShipClass):
                yield obj
