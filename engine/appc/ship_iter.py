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
    """Walk every object in a set exactly once via _objects.values().

    Snapshot the values into a list first: an object's AI tick can add to /
    remove from the set mid-walk (the E6M2 dock AI adds waypoints / the Graff
    control-room set / PlaceObjectByName targets during tick_all_ai), which
    otherwise raises 'dictionary changed size during iteration'. Objects added
    mid-tick are simply picked up on the next tick."""
    for obj in list(getattr(pSet, "_objects", {}).values()):
        yield obj


def active_set():
    """The single space set that is currently 'live' for the WORLD SCENE — the
    one the player ship occupies. BC renders exactly one space set at a time;
    every other space set (and every comm/bridge set) is off-screen until the
    player warps in. Returns that SetClass, or None when it can't be determined
    (no player yet).

    Keyed to the player's containing set rather than GetRenderedSet(): the
    rendered set is a camera concept a cutscene may point at the bridge, whereas
    the player ship stays in its real space set the whole time, which is what the
    world scene must track.

    Used to scope RENDERING (realize/reconcile/planets/suns) to the player's
    system so other systems' ships/planets don't bleed into the scene. It does
    NOT gate simulation: AI/motion/combat still iterate every set via iter_ships,
    so scripted off-screen activity (e.g. M3Gameflow's Biranu1 duel while the
    player is in Biranu2) keeps running as before.
    """
    try:
        player = App.Game_GetCurrentPlayer()
    except Exception:
        player = None
    if player is not None:
        pSet = player.GetContainingSet()
        # Real SetClass exposes _objects; a _Stub / None does not.
        if pSet is not None and hasattr(pSet, "_objects"):
            return pSet
    return None


def iter_ships(*, verbose: bool = False) -> Iterable:
    """Walk every ShipClass-like object in every set — the SIMULATION roster
    (AI, motion, combat, subsystem updates). Rendering uses iter_active_ships to
    scope to the player's set; simulation stays global so off-screen scripted
    activity is unaffected."""
    from engine.appc.ships import ShipClass
    # Snapshot _sets too: a tick can create a whole set (E6M2 dock ->
    # SetupGraffSet builds "FedOutpostSet_Graff"), which would mutate _sets
    # mid-walk. New sets are picked up next tick.
    for set_name, pSet in list(App.g_kSetManager._sets.items()):
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


def iter_active_ships(*, verbose: bool = False) -> Iterable:
    """Walk ShipClass objects in the ACTIVE set only (see active_set) — the
    RENDER roster. Falls back to every set when no active set is determinable
    (no player yet), preserving load-time behaviour for single-set boots and
    headless tests without a game."""
    from engine.appc.ships import ShipClass
    act = active_set()
    sets = [(act.GetName(), act)] if act is not None else list(
        App.g_kSetManager._sets.items())
    for set_name, pSet in sets:
        if verbose:
            count = len(getattr(pSet, "_objects", {}))
            obj_keys = list(getattr(pSet, "_objects", {}).keys())
            print(f"[ship_iter] active set {set_name!r}: {count} object(s), "
                  f"keys={obj_keys}", flush=True)
        for obj in iter_set_objects(pSet):
            if isinstance(obj, ShipClass):
                yield obj
