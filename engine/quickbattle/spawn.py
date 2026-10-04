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
import math
import os

from engine.quickbattle import placement

_log = logging.getLogger(__name__)
_provider = None
_radius_fn = None
_SIDE = {"friendly": "Friendly", "enemy": "Enemy"}
_FALLBACK = {"Friendly": ("QuickBattleFriendlyAI", "QBFriendlyGenericShipDestroyed"),
             "Enemy": ("QuickBattleAI", "QBEnemyGenericShipDestroyed")}
# Lateral steps tried on EACH side of a slot before giving up. Alternating
# sides (0, +1, -1, +2, -2 ...) lets a second group at the same anchor spread
# around the first instead of piling up on one side.
_MAX_NUDGES = 16
_PARALLEL_EPS = 0.999  # |dot(forward, up)| above this -> treat as (anti)parallel


def set_provider(fn) -> None:
    global _provider
    _provider = fn


def set_radius_fn(fn) -> None:
    """Register `fn(ship) -> None`, which seeds `ship`'s GetRadius() when it
    is still 0. Nothing is realised at GenerateShips time -- the radius is
    normally seeded at realisation (host_loop._seed_ship_radius) -- so without
    this every ship, and the just-recreated player, reports 0 and placement
    spacing collapses to MARGIN_GU. The host registers one at QuickBattle boot;
    None (the default) leaves radii untouched."""
    global _radius_fn
    _radius_fn = fn


def _seed_radius(ship) -> None:
    if _radius_fn is None or ship is None:
        return
    try:
        _radius_fn(ship)
    except Exception as e:
        _log.warning("quickbattle: radius seed failed for %s: %s", ship.GetName(), e)


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


def _write_manifests(qb, plan) -> None:
    """Write `g_kEnemyList` / `g_kFriendList` as BC's 6-tuple preload
    manifests. Shared by `sync_sdk` (every scenario change, plus once at
    Start) and `generate_ships` itself, so a hook-driven Start always leaves
    these populated even when nothing upstream called `sync_sdk` first --
    `StartSimulation2` runs `if len(g_kEnemyList) > 0: bWonOrLost = 0`
    immediately after `GenerateShips()` returns (QuickBattle.py ~3148), and
    without this the win/lose message never arms.

    Neutrals land in `g_kFriendList` purely as PRELOAD MANIFESTS (so
    `StartSimulationAction` preloads their models too) -- nothing of ours
    reads these lists back once `generate_ships` has actually run; group
    membership and `g_kShips` come from the plan directly (spec §4.1/§4.5).
    The one place this is NOT inert is BC's own fallback `GenerateShips`
    (no provider installed): it has no neutral concept at all, so a neutral
    manifest there spawns as an ordinary AI-driven friendly. That degraded
    behaviour is accepted -- it only applies with no provider, where BC's
    unmodified code runs end to end anyway.
    """
    enemies = [_manifest(qb, o) for o in plan.orders if o.allegiance == "enemy"]
    others = [_manifest(qb, o) for o in plan.orders if o.allegiance != "enemy"]
    qb.g_kEnemyList, qb.g_kFriendList = enemies, others


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
    """Manifests + XO Start enablement only. `g_sPlayerType` is NOT written
    here any more (Mark's home-ship ruling, 2026-10-02): `sync_sdk` only
    ever runs OUTSIDE a battle (the panel's `_after_change`, guarded on
    `not bInSimulation`), and outside a battle the player is always the
    home ship regardless of what the setup screen names -- the battle ship
    is picked at the moment it matters, by `player_type_for_recreate`
    inside the RecreatePlayer wrap (`bridge_selection.set_player_type_
    resolver`), which reads `bInSimulation` live rather than trusting a
    value written ahead of time."""
    if plan is None:
        return
    _write_manifests(qb, plan)
    if not getattr(qb, "bInSimulation", 0):
        _set_xo_start(qb, bool(plan.orders))


def _vec(p):
    return (p.x, p.y, p.z)


def _cols(rot):
    return tuple(_vec(rot.GetCol(i)) for i in range(3))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit_towards(from_pos, to_pos, fallback):
    d = _sub(to_pos, from_pos)
    n = math.sqrt(_dot(d, d))
    if n < 1e-9:
        return fallback
    return (d[0] / n, d[1] / n, d[2] / n)


def _enemy_facing(ship_pos, player_pos, player_fore, player_up):
    """(forward, up) for an enemy ship: forward is the unit vector FROM the
    ship TOWARD the player (not merely the player's backward column -- that
    only happens to point at the player for a "fore" group; an aft group's
    backward points away, a port group's points abeam). `up` is the player's
    up, unless it is (anti)parallel to that forward (a dorsal/ventral group),
    in which case AlignToVectors' own orthogonalization of up against forward
    would zero out, so fall back to the player's fore instead."""
    fwd = _unit_towards(ship_pos, player_pos, player_fore)
    up = player_fore if abs(_dot(fwd, player_up)) > _PARALLEL_EPS else player_up
    return fwd, up


def _overlaps(pos, radius, placed, margin) -> bool:
    for other_pos, other_radius in placed:
        d = _sub(pos, other_pos)
        min_sep = radius + other_radius + margin
        if _dot(d, d) < min_sep * min_sep:
            return True
    return False


def _nudge_offsets(max_nudges):
    """0, +1, -1, +2, -2, ... +max, -max (in steps)."""
    yield 0
    for k in range(1, max_nudges + 1):
        yield k
        yield -k


def _place(qb, ship, pos, lateral, placed) -> tuple:
    """Place `ship` at `pos`, nudging either way along `lateral` until clear of both
    every ship placed so far THIS call (exact distance check) and the
    (stubbed) `IsLocationEmptyTG`. Returns the final world position so the
    caller can face the ship from where it actually ended up.

    Two groups that share a direction and distance get the SAME anchor
    (placement.py computes each group independently), and
    `Set.IsLocationEmptyTG` is a Phase-1 stub that always reports empty
    (engine/appc/sets.py ~312) -- so the exact overlap check against `placed`
    is the only thing that actually separates them here.

    The nudge step is `2 * radius + MARGIN_GU`, not one radius: a freshly
    created, not-yet-realised ship reports `GetRadius() == 0.0` until the
    post-sim scene reconcile runs (see test_chase_camera_radius_catches_up_
    after_recreate_player) -- a one-radius step is then exactly zero and the
    loop never moves. Adding the margin keeps every step non-zero regardless
    of radius.
    """
    import App
    pt = App.TGPoint3()
    r = ship.GetRadius()
    step = 2.0 * r + placement.MARGIN_GU
    candidate = pos
    for k in _nudge_offsets(_MAX_NUDGES):
        off = step * k
        candidate = (pos[0] + lateral[0] * off, pos[1] + lateral[1] * off,
                     pos[2] + lateral[2] * off)
        pt.SetXYZ(*candidate)
        if (not _overlaps(candidate, r, placed, placement.MARGIN_GU)
                and qb.g_pSet.IsLocationEmptyTG(pt, 2.0 * r, 1)):
            break
    else:
        # Every candidate collided: the ship goes on the last one, overlapping.
        # Say so, rather than silently stacking hulls.
        _log.warning("quickbattle: no clear spot for %s within %d lateral steps "
                     "either side; it overlaps another ship", ship.GetName(), _MAX_NUDGES)
    ship.SetTranslate(pt)
    placed.append((candidate, r))
    return candidate


def _face(ship, ship_pos, player, player_pos, cols, allegiance) -> None:
    import App
    if placement.faces_player(allegiance):
        fwd, up = _enemy_facing(ship_pos, player_pos, cols[1], cols[2])
        ship.AlignToVectors(App.TGPoint3(*fwd), App.TGPoint3(*up))
    else:
        ship.SetMatrixRotation(player.GetWorldRotation())


def generate_ships(qb, plan) -> None:
    import App
    import loadspacehelper
    from engine.appc.registry_texture import REGISTRY_OLD_NAME
    from engine.quickbattle import naming

    qb.g_iNumFriends = qb.g_iNumEnemies = 0
    qb.g_kShips = {}
    _write_manifests(qb, plan)
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

    if not created:
        return

    # From here on, every ship below already exists in the set. A failure
    # must NOT propagate out of generate_ships: install_generate_ships_hook's
    # wrapper falls back to BC's original GenerateShips on any exception, and
    # that would spawn a second full roster on top of what we already have
    # (spec §4.5 step 3 says fall back only when the hook raises BEFORE
    # spawning anything -- the operative word is BEFORE).
    try:
        # Seed radii before placement reads GetRadius(): after ReplaceTexture,
        # so a registry-keyed model load matches the one realisation makes.
        # The player's identity goes on first for the same reason; it
        # overrides the "default NCC" CreatePlayerShip queued (last write wins
        # per slot) and is idempotent with the reconcile block's repeat.
        apply_player_identity(player, plan=plan)
        _seed_radius(player)
        for _order, ship in created:
            _seed_radius(ship)
        ppos = _vec(player.GetWorldLocation())
        cols = _cols(player.GetWorldRotation())
        # Seed with the player so a group's anchor -- fixed depth from the
        # player, independent of radius -- never nudges a ship toward or
        # into it (Minor 3): "close" + large enough radii puts the anchor
        # itself inside the player otherwise.
        placed: list = [(ppos, player.GetRadius())]
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
                    final_pos = _place(qb, ship, pos, lateral, placed)
                    _face(ship, final_pos, player, ppos, cols, order.allegiance)
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
    except Exception as e:
        _log.error(
            "quickbattle: GenerateShips placement pass failed after %d ship(s) "
            "were already created; NOT falling back to BC's original (that "
            "would spawn a second roster on top): %s", len(created), e)
        return


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


def _in_battle() -> bool:
    """`QuickBattle.QuickBattle.bInSimulation`, read live (never cached):
    StartSimulation2 sets it to 1 before ITS OWN RecreatePlayer and
    EndSimulation sets it to 0 before ITS OWN RecreatePlayer, so this one
    read covers Start, XO Restart (EndSimulation then Start), End Combat
    and a death outside a battle alike. False (never raises) when the SDK
    module isn't importable -- headless unit tests that build a player by
    hand, never through the real QuickBattle cascade."""
    try:
        import QuickBattle.QuickBattle as QB
    except Exception:
        return False
    return bool(getattr(QB, "bInSimulation", 0))


def _home_display_name():
    """BC's class-default variant name for the home ship (the Galaxy's is
    "USS Dauntless"), read from the ship catalog so a mod's own class
    default is honoured too. None if the catalog has nothing for it."""
    from engine import ship_catalog
    from engine.quickbattle import scenario
    try:
        e = ship_catalog.entry(scenario.DEFAULT_PLAYER_SHIP)
    except Exception:
        return None
    if e is not None and e.variants:
        return e.variants[0].name
    return None


def player_type_for_recreate(qb):
    """g_sPlayerType for `qb.RecreatePlayer`, by Mark's home-ship ruling
    (2026-10-02): the plan's player ship while a battle is actually running
    (`qb.bInSimulation`), else the home ship -- Galaxy, "USS Dauntless"
    (`scenario.DEFAULT_PLAYER_SHIP`). `bInSimulation` is the one decision
    that covers every RecreatePlayer caller: StartSimulation2 sets it to 1
    BEFORE its own RecreatePlayer, EndSimulation (and RestartSimulation,
    which is EndSimulation then a re-post of ET_START_SIMULATION) sets it
    to 0 BEFORE its own RecreatePlayer, and ShipDestroyed's player-death
    branch calls RecreatePlayer directly only when bInSimulation is already
    0 (the in-battle death instead arms the end-of-battle timer).

    Returns None -- leave g_sPlayerType untouched -- when no plan provider
    is registered at all, so BC's own flow is unchanged without the setup
    screen. Consulted by `bridge_selection.install_quickbattle_hook` via
    `bridge_selection.set_player_type_resolver`."""
    if _provider is None:
        return None
    plan = current_plan()
    if plan is not None and getattr(qb, "bInSimulation", 0):
        return plan.player.ship_file
    from engine.quickbattle import scenario
    return scenario.DEFAULT_PLAYER_SHIP


def apply_player_identity(ship, plan=None) -> bool:
    """Registry + display name for a freshly created player (called from
    host_loop's QuickBattle reconcile block, and by generate_ships before it
    seeds radii). Idempotent; overrides the "default NCC" BC's
    MissionLib.CreatePlayerShip queues on every Federation player.

    Mark's home-ship ruling (2026-10-02): while a battle is actually
    running (`_in_battle()`) AND the live ship's class (its `ships.<Leaf>`
    script) matches the plan's player ship, the plan's registry and display
    name apply -- same as before. In every other case -- not currently in a
    battle (boot, End Combat, XO Restart's EndSimulation half, a death
    outside a battle), or a live player whose class doesn't match the plan
    -- the ship's REGISTRY goes back to the home ship (BC's class default),
    never another ship's registry.

    The home DISPLAY NAME ("USS Dauntless" for the Galaxy) is a separate,
    narrower step: it only applies when `plan` is not None (a provider is
    registered) AND the live ship's class is the home class itself
    (`scenario.DEFAULT_PLAYER_SHIP`). With NO plan at all -- no provider
    registered -- the name is left alone entirely, matching
    `player_type_for_recreate`'s "no provider -> BC's own flow is
    unchanged": a non-Galaxy player with no setup screen in play must never
    be renamed to "USS Dauntless" just because its own class has no
    registry default of its own. `plan` None -> `current_plan()`."""
    from engine.appc import registry_texture
    from engine.quickbattle import scenario
    if plan is None:
        plan = current_plan()
    if plan is not None and _in_battle():
        cls = registry_texture._class_of(ship)
        if cls is not None and cls.lower() == str(plan.player.ship_file).lower():
            try:
                import App
                p = plan.player
                if p.registry:
                    ship.ReplaceTexture(registry_path(p.class_id, p.registry),
                                        registry_texture.REGISTRY_OLD_NAME)
                if p.display_name:
                    ship.SetDisplayName(App.TGString(p.display_name))
                return True
            except Exception as e:
                _log.warning("quickbattle: player identity failed: %s", e)
                return False
    applied = registry_texture.apply_class_default(ship)
    if plan is not None:
        cls = registry_texture._class_of(ship)
        if cls is not None and cls.lower() == scenario.DEFAULT_PLAYER_SHIP.lower():
            name = _home_display_name()
            if name:
                try:
                    import App
                    ship.SetDisplayName(App.TGString(name))
                except Exception as e:
                    _log.warning("quickbattle: home player name failed: %s", e)
    return applied
