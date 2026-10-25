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


def _put_back(records) -> None:
    for obj, home, loc, rot in records:
        now = obj.GetContainingSet()
        if now is home:
            continue
        name = obj.GetName()
        if now is not None and now.GetObject(name) is obj:
            now.RemoveObjectFromSet(name)
        home.AddObjectToSet(obj, name)
        obj.SetTranslate(loc)
        obj.SetMatrixRotation(rot)
        obj.UpdateNodeOnly()


def _wrap_change_region(qb) -> bool:
    current = qb.__dict__.get("ChangeRegion")
    if current is None or _MARK in getattr(current, "__dict__", {}):
        return False
    orig = current

    def ChangeRegion(*args):
        try:
            records = _owned_in_player_set()
        except Exception as e:  # noqa: BLE001 - never stop BC's region change
            _log.error("quickbattle: recording owned objects failed: %s", e)
            records = []
        result = orig(*args)
        try:
            _put_back(records)
        except Exception as e:  # noqa: BLE001
            _log.error("quickbattle: returning owned objects failed: %s", e)
        return result

    setattr(ChangeRegion, _MARK, orig)
    qb.ChangeRegion = ChangeRegion
    return True


def install(qb) -> bool:
    """Wrap the Quick Battle module's functions; True when any wrapper was
    installed by this call."""
    installed = False
    installed |= _wrap_change_region(qb)
    return installed
