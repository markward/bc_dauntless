"""Spawn a Quick Battle from the BattlePlan: only GenerateShips is replaced.

BC's chain is untouched: StartSimulation -> preload -> StartSimulation2 ->
RecreatePlayer -> GenerateShips (OURS) -> AI from g_kShips -> red alert;
ShipDestroyed's win/lose and EndSimulation's cleanup read the same g_kShips /
g_iNumEnemies BC's own GenerateShips writes. Neutrals get no g_kShips entry, so
they run no AI and never count (spec D6). With no provider -- or a provider that
returns None -- BC's original runs, which keeps headless tests that fill
g_kEnemyList working. Spec §4.
"""
from __future__ import annotations

import logging
import os

from engine.quickbattle import placement

_log = logging.getLogger(__name__)
_provider = None
_SIDE = {"friendly": "Friendly", "enemy": "Enemy"}
_FALLBACK = {"Friendly": ("QuickBattleFriendlyAI", "QBFriendlyGenericShipDestroyed"),
             "Enemy": ("QuickBattleAI", "QBEnemyGenericShipDestroyed")}
_MAX_NUDGES = 8


def set_provider(fn) -> None:
    global _provider
    _provider = fn


def current_plan():
    if _provider is None:
        return None
    try:
        return _provider()
    except Exception as e:
        _log.warning("quickbattle plan provider failed: %s", e)
        return None


def registry_path(class_id, stem) -> str:
    from engine.appc.registry_texture import DEFAULT_REGISTRY_BY_CLASS
    rel = DEFAULT_REGISTRY_BY_CLASS.get(class_id)
    if rel and os.path.splitext(os.path.basename(rel))[0] == stem:
        return rel
    return "Data/Models/Ships/%s/%s.tga" % (class_id, stem)


def _details(qb, class_id, side):
    table = qb.g_dFriendlyShipTypeToDetails if side == "Friendly" else \
        qb.g_dEnemyShipTypeToDetails
    for row in table.values():
        if str(row[0]).lower() == class_id.lower():
            return row[3], row[2]
    return _FALLBACK[side]


def _manifest(qb, order):
    side = _SIDE.get(order.allegiance, "Friendly")
    ai, msg = _details(qb, order.class_id, side)
    return (order.ship_file, order.title, msg, ai, side, order.ai_level)


def _set_xo_start(qb, enabled) -> None:
    try:
        menu = qb.g_pXOMenu
        for key in ("Start Simulation", "Restart Simulation"):
            btn = menu.GetButtonW(qb.g_pMissionDatabase.GetString(key))
            if btn is not None:
                btn.SetEnabled() if enabled else btn.SetDisabled()
                return
    except Exception as e:
        _log.info("quickbattle XO start sync skipped: %s", e)


def sync_sdk(qb, plan) -> None:
    if plan is None:
        return
    qb.g_sPlayerType = plan.player.ship_file
    enemies = [_manifest(qb, o) for o in plan.orders if o.allegiance == "enemy"]
    others = [_manifest(qb, o) for o in plan.orders if o.allegiance != "enemy"]
    qb.g_kEnemyList, qb.g_kFriendList = enemies, others
    if not getattr(qb, "bInSimulation", 0):
        _set_xo_start(qb, bool(plan.orders))


def _vec(p):
    return (p.x, p.y, p.z)


def _cols(rot):
    return tuple(_vec(rot.GetCol(i)) for i in range(3))


def _place(qb, ship, pos, lateral):
    import App
    pt = App.TGPoint3()
    r = ship.GetRadius()
    for k in range(_MAX_NUDGES + 1):
        off = r * k
        pt.SetXYZ(pos[0] + lateral[0] * off, pos[1] + lateral[1] * off,
                  pos[2] + lateral[2] * off)
        if qb.g_pSet.IsLocationEmptyTG(pt, 2.0 * r, 1):
            break
    ship.SetTranslate(pt)


def _face(ship, player, allegiance):
    if placement.faces_player(allegiance):
        ship.AlignToVectors(player.GetWorldBackwardTG(), player.GetWorldUpTG())
    else:
        ship.SetMatrixRotation(player.GetWorldRotation())


def generate_ships(qb, plan) -> None:
    import App
    import loadspacehelper
    from engine.appc.registry_texture import REGISTRY_OLD_NAME
    from engine.quickbattle import naming

    qb.g_iNumFriends = qb.g_iNumEnemies = 0
    qb.g_kShips = {}
    mission = App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission()
    neutrals = mission.GetNeutralGroup()
    for grp in (qb.pEnemies, qb.pFriendlies, neutrals):
        grp.RemoveAllNames()
    player = App.Game_GetCurrentGame().GetPlayer()
    qb.pFriendlies.AddName(player.GetName())

    created = []                               # (order, ship)
    for n, order in enumerate(plan.orders, start=1):
        name = naming.object_name(order.title, n)
        try:
            ship = loadspacehelper.CreateShip(order.ship_file, qb.g_pSet, name, "")
            if ship is None or App.IsNull(ship):
                raise RuntimeError("CreateShip returned null")
            if order.display_name:
                ship.SetDisplayName(App.TGString(order.display_name))
            else:
                ship.SetDisplayName(App.TGString(name))
            if order.registry:
                ship.ReplaceTexture(registry_path(order.class_id, order.registry),
                                    REGISTRY_OLD_NAME)
            created.append((order, ship))
        except Exception as e:
            _log.error("quickbattle: could not spawn %s (%s): %s", name, order.ship_file, e)

    ppos = _vec(player.GetWorldLocation())
    cols = _cols(player.GetWorldRotation())
    by_group: dict = {}
    for order, ship in created:
        by_group.setdefault(order.group_id, []).append((order, ship))
    for members in by_group.values():
        o0 = members[0][0]
        radii = [s.GetRadius() for _o, s in members]
        try:
            if o0.direction is None:
                positions = placement.escort_positions(ppos, cols, player.GetRadius(), radii)
                lateral = cols[0]
            else:
                positions = placement.group_positions(ppos, cols, o0.direction,
                                                      o0.distance_gu, radii)
                lateral = placement.lateral_for(o0.direction, cols)
        except Exception as e:
            _log.error("quickbattle: placement failed: %s", e)
            continue
        for (order, ship), pos in zip(members, positions):
            try:
                _place(qb, ship, pos, lateral)
                _face(ship, player, order.allegiance)
                ship.UpdateNodeOnly()
                pm = qb.g_pSet.GetProximityManager()
                if pm:
                    pm.UpdateObject(ship)
                side = _SIDE.get(order.allegiance)
                if side is None:
                    neutrals.AddName(ship.GetName())
                    continue
                (qb.pEnemies if side == "Enemy" else qb.pFriendlies).AddName(ship.GetName())
                ai, msg = _details(qb, order.class_id, side)
                qb.g_kShips[ship.GetObjID()] = (ai, msg, side, order.ai_level)
                if side == "Enemy":
                    qb.g_iNumEnemies = qb.g_iNumEnemies + 1
                else:
                    qb.g_iNumFriends = qb.g_iNumFriends + 1
            except Exception as e:
                _log.error("quickbattle: could not place %s: %s", ship.GetName(), e)


def install_generate_ships_hook(qb) -> bool:
    current = getattr(qb, "GenerateShips", None)
    if current is None or getattr(current, "_dauntless_qb_spawn_orig", None) is not None:
        return False
    orig = current

    def GenerateShips():
        plan = current_plan()
        if plan is None:
            return orig()
        try:
            return generate_ships(qb, plan)
        except Exception as e:
            _log.error("quickbattle: GenerateShips hook failed, falling back to BC: %s", e)
            return orig()

    GenerateShips._dauntless_qb_spawn_orig = orig
    qb.GenerateShips = GenerateShips
    return True
