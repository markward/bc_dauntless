"""Quick Battle wrappers that keep owned objects (engine/systems/owners.py)
where their owner put them.

BC's `ChangeRegion` (QuickBattle.py) moves EVERY ship in the player's set into
the new battle region. An object an engine module placed in its own region --
a home station -- must not follow the player there, so the wrapper puts each
owned object back into the set it was in, at the pose it had.

`install(qb)` replaces module attributes, so every SDK caller that reaches the
function through its module global (StartSimulation2 calls ChangeRegion) gets
the wrapper without an SDK edit. Each wrapper carries
`_dauntless_sim_restore_orig`, which makes installing idempotent.
"""
from __future__ import annotations

import logging

from engine.appc.math import TGMatrix3, TGPoint3
from engine.systems import owners

_log = logging.getLogger(__name__)

_MARK = "_dauntless_sim_restore_orig"


def _owned_in_player_set() -> list:
    """(object, its set, location copy, rotation copy) for every owned object
    in the player's set; [] with no player or set."""
    import App
    game = App.Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    pSet = player.GetContainingSet() if player is not None else None
    if pSet is None:
        return []
    out = []
    for obj in pSet.GetObjectList():
        if owners.owner_of(obj) is None:
            continue
        loc = obj.GetWorldLocation()
        rot = TGMatrix3()
        rot.set_from_tuple(obj.GetWorldRotation().as_tuple())
        out.append((obj, pSet, TGPoint3(loc.x, loc.y, loc.z), rot))
    return out


def _proximity(pSet):
    get = getattr(type(pSet), "GetProximityManager", None)
    return get(pSet) if get is not None else None


def _leave(obj, now, name) -> None:
    """Take `obj` out of `now` and out of its proximity index: BC's loop
    UpdateObject'ed it into the battle set's manager, and leaving the set
    does not drop that entry."""
    if now.GetObject(name) is obj:
        now.RemoveObjectFromSet(name)
    pm = _proximity(now)
    if pm is not None:
        pm.RemoveObject(obj)


def _return_home(obj, home, name, loc, rot) -> None:
    home.AddObjectToSet(obj, name)
    obj.SetTranslate(loc)
    obj.SetMatrixRotation(rot)
    obj.UpdateNodeOnly()
    pm = _proximity(home)
    if pm is not None:
        pm.UpdateObject(obj)


def _put_back(records) -> None:
    """Every record gets its own try, and leaving the wrong set is tried
    apart from going home: one bad record, or a failure while leaving, can
    never strand an object in no set."""
    for obj, home, loc, rot in records:
        try:
            now = obj.GetContainingSet()
            if now is home:
                continue
            name = obj.GetName()
        except Exception:  # noqa: BLE001 - the other records still go home
            _log.exception("quickbattle: reading an owned object failed")
            continue
        if now is not None:
            try:
                _leave(obj, now, name)
            except Exception:  # noqa: BLE001 - still send it home
                _log.exception("quickbattle: %s did not leave %s", name,
                               now.GetName())
        try:
            _return_home(obj, home, name, loc, rot)
        except Exception:  # noqa: BLE001 - the other records still go home
            _log.exception("quickbattle: %s did not go back to %s", name,
                           home.GetName())


def _wrap_change_region(qb) -> bool:
    current = qb.__dict__.get("ChangeRegion")
    if current is None or _MARK in getattr(current, "__dict__", {}):
        return False
    orig = current

    def ChangeRegion(*args):
        try:
            records = _owned_in_player_set()
        except Exception:  # noqa: BLE001 - never stop BC's region change
            _log.exception("quickbattle: recording owned objects failed")
            records = []
        try:
            return orig(*args)
        finally:
            # Also when BC's ChangeRegion raises partway: whatever it already
            # moved still goes home, and the exception still propagates.
            _put_back(records)

    setattr(ChangeRegion, _MARK, orig)
    qb.ChangeRegion = ChangeRegion
    return True


def install(qb) -> bool:
    """Wrap the Quick Battle module's functions; True when any wrapper was
    installed by this call."""
    installed = False
    installed |= _wrap_change_region(qb)
    return installed
