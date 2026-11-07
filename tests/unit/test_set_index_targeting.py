"""The native set index's (set, target) counts, popularity and "who targets X"
(engine/appc/set_index.py), kept in step by the one targeting door,
ShipClass.SetTarget.

Spec: docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md
§4.1; plan docs/superpowers/plans/2026-11-07-phase6-ai-p1-set-index.md, Task 3.
"""
import ast
import random
from pathlib import Path

import App
import pytest

from engine.appc import set_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass, ShipClass_Create

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_sets():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()
    App._reset_target_menu_singleton()


def _set(name="S"):
    s = SetClass()
    s.SetName(name)
    App.g_kSetManager._sets[name] = s
    return s


def _ship(name):
    return ShipClass_Create(name)


def _count(pSet, target):
    return set_index.targeted_by_count(pSet, target)


# ── the stock loop, transcribed ──────────────────────────────────────────────

def _stock_popularity(pSet, pOurShip, pTarget):
    """AI/Preprocessors.py GetTargetRating, the fPopularity block, verbatim
    (with pSet standing in for pOurShip.GetContainingSet())."""
    fPopularity = 0.0
    if pSet:
        idOurID = pOurShip.GetObjID()
        idTargetID = pTarget.GetObjID()
        lpShips = pSet.GetClassObjectList(App.CT_SHIP)
        for pShip in lpShips:
            if pShip.GetObjID() == idOurID:
                continue
            pShipTarget = pShip.GetTarget()
            if pShipTarget and (pShipTarget.GetObjID() == idTargetID):
                fPopularity = fPopularity + 1.0
    return fPopularity


def test_popularity_matches_the_stock_loop_under_random_play():
    from engine.appc.planet import Planet_Create
    rng = random.Random(20261107)
    sets = [_set("S0"), _set("S1")]
    planet = Planet_Create(170.0, "")
    sets[0].AddObjectToSet(planet, "Planet")
    ships = [_ship("Ship%d" % i) for i in range(12)]
    for i, s in enumerate(ships):
        sets[i % 2].AddObjectToSet(s, "Ship%d" % i)
    spare = [_ship("Spare%d" % i) for i in range(4)]

    def members(pSet):
        return list(pSet._objects.items())

    for step in range(400):
        op = rng.choice(["target_name", "target_obj", "target_none",
                         "move", "delete", "second_ident", "overwrite"])
        pSet = rng.choice(sets)
        items = members(pSet)
        if op.startswith("target"):
            ship = rng.choice(ships)
            if op == "target_name":
                other = rng.choice(sets)
                names = [n for n, _ in members(other)]
                ship.SetTarget(rng.choice(names) if names else None)
            elif op == "target_obj":
                ship.SetTarget(rng.choice(ships + [planet] + spare))
            else:
                ship.SetTarget(None)
        elif op == "move" and items:
            name, obj = rng.choice(items)
            other = sets[1] if pSet is sets[0] else sets[0]
            pSet.RemoveObjectFromSet(name)
            other.AddObjectToSet(obj, name)
        elif op == "delete" and items:
            name, _ = rng.choice(items)
            pSet.DeleteObjectFromSet(name)
        elif op == "second_ident" and items:
            _, obj = rng.choice(items)
            pSet.AddObjectToSet(obj, "Alias%d" % step)
        elif op == "overwrite" and items:
            name, _ = rng.choice(items)
            pSet.AddObjectToSet(rng.choice(spare + ships), name)

        for S in sets:
            for R in S.GetClassObjectList(App.CT_SHIP):
                for C in list(S._objects.values()):
                    got = set_index.popularity(S, R, C)
                    assert isinstance(got, float)
                    assert got == _stock_popularity(S, R, C), (step, op)


def test_join_picks_up_a_target_set_outside_any_set():
    """Review focus 3: the target is chosen while the ship is in no set."""
    S = _set()
    prey = _ship("Prey")
    S.AddObjectToSet(prey, "Prey")
    hunter = _ship("Hunter")
    hunter.SetTarget(prey)
    assert _count(S, prey) == 0
    S.AddObjectToSet(hunter, "Hunter")
    assert _count(S, prey) == 1
    S.RemoveObjectFromSet("Hunter")
    assert _count(S, prey) == 0


def test_targeting_lists_the_raters_in_set_order():
    S = _set()
    prey = _ship("Prey")
    S.AddObjectToSet(prey, "Prey")
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    for n, s in (("C", c), ("A", a), ("B", b)):
        S.AddObjectToSet(s, n)
    for s in (a, b, c):
        s.SetTarget(prey)
    assert [o.GetName() for o in set_index.targeting(S, prey)] == ["C", "A", "B"]
    b.SetTarget(None)
    assert [o.GetName() for o in set_index.targeting(S, prey)] == ["C", "A"]
    assert _count(S, prey) == 2
    assert set_index.targeting(S, c) == []


def test_the_index_holds_each_members_own_id_for_part_2():
    """Final-review fix: a native reader holding only the candidate's key
    (Part 2's kernels) asks popularity by key, which needs the object's own
    GetObjID() in the core. The facade passes it at every add."""
    import _dauntless_host as _h
    from engine.appc.projectiles import Torpedo
    S = _set()
    prey, a, b = _ship("Prey"), _ship("A"), _ship("B")
    torp = Torpedo()
    for n, s in (("Prey", prey), ("A", a), ("B", b), ("Torp", torp)):
        S.AddObjectToSet(s, n)
    for s in (a, b):
        s.SetTarget(prey)
    for o in (prey, a, b, torp):
        assert _h.set_index_obj_id(o) == o.GetObjID()
    assert _h.set_index_obj_id(_ship("Elsewhere")) == -1  # held by no set
    for rater in (prey, a, b):
        for cand in (prey, a, b, torp):
            assert (_h.set_index_popularity_by_key(S, rater, cand)
                    == set_index.popularity(S, rater, cand)), (rater, cand)
    assert _h.set_index_popularity_by_key(S, a, prey) == 1


def test_a_retarget_to_the_same_object_does_not_double_count():
    S = _set()
    prey = _ship("Prey")
    hunter = _ship("Hunter")
    S.AddObjectToSet(prey, "Prey")
    S.AddObjectToSet(hunter, "Hunter")
    hunter.SetTarget(prey)
    hunter.SetTarget("Prey")
    hunter.SetTarget(prey)
    assert _count(S, prey) == 1


def test_the_count_is_visible_to_a_target_changed_handler():
    S = _set()
    prey = _ship("Prey")
    hunter = _ship("Hunter")
    S.AddObjectToSet(prey, "Prey")
    S.AddObjectToSet(hunter, "Hunter")
    seen = []
    orig = App.g_kEventManager.AddEvent

    def spy(evt):
        if evt.GetEventType() == App.ET_TARGET_WAS_CHANGED:
            seen.append(_count(S, prey))
        return orig(evt)

    App.g_kEventManager.AddEvent = spy
    try:
        hunter.SetTarget(prey)
    finally:
        del App.g_kEventManager.AddEvent
    assert seen == [1]


# ── one test per door ───────────────────────────────────────────────────────

def _hunter_and_prey():
    S = _set()
    hunter = _ship("Hunter")
    prey = _ship("Prey")
    S.AddObjectToSet(hunter, "Hunter")
    S.AddObjectToSet(prey, "Prey")
    return S, hunter, prey


def test_door_sdk_string_set_target():
    S, hunter, prey = _hunter_and_prey()
    hunter.SetTarget("Prey")
    assert _count(S, prey) == 1
    hunter.SetTarget("Nobody")
    assert _count(S, prey) == 0


def test_door_sdk_object_set_target():
    S, hunter, prey = _hunter_and_prey()
    hunter.SetTarget(prey)
    assert _count(S, prey) == 1
    hunter.SetTarget(None)
    assert _count(S, prey) == 0


def test_door_ai_driver_select_target():
    """ai_driver._ensure_select_target_initialized pushes SelectTarget's
    sCurrentTarget through SetTarget (the SDK's own call)."""
    from AI.Preprocessors import SelectTarget
    from engine.appc.ai import PreprocessingAI_Create
    from engine.appc.ai_driver import tick_ai
    from engine.appc.objects import ObjectGroup
    S, hunter, prey = _hunter_and_prey()
    pp = PreprocessingAI_Create(hunter, "SelectPP")
    pp._has_focus = True
    grp = ObjectGroup()
    grp.AddName("Prey")
    inst = SelectTarget(grp)
    inst.ForceCurrentTargetString("Prey")
    inst.bSetShipTarget = 1
    pp.SetPreprocessingMethod(inst, "Update")
    assert _count(S, prey) == 0
    tick_ai(pp, game_time=0.0)
    assert hunter.GetTarget() is prey
    assert _count(S, prey) == 1


def test_door_target_list_row_click():
    from engine.core.game import (Game, Episode, Mission, _set_current_game)
    from engine.ui.target_list_view import TargetListView
    S, _, prey = _hunter_and_prey()
    episode = Episode()
    episode.SetCurrentMission(Mission())
    game = Game()
    game.SetCurrentEpisode(episode)
    player = _ship("Player")
    S.AddObjectToSet(player, "Player")
    game.SetPlayer(player)
    _set_current_game(game)
    try:
        assert _count(S, prey) == 0
        assert TargetListView().dispatch_event("Prey") is True
        assert player.GetTarget() is prey
        assert _count(S, prey) == 1
    finally:
        _set_current_game(None)


def test_door_persistent_target_restore():
    from engine.appc import target_menu
    from engine.appc.perception import Contact
    S, player, quarry = _hunter_and_prey()
    menu = App.STTargetMenu_CreateW("Targets")
    player.SetTarget(quarry)
    target_menu.remember_player_target(player)
    player.SetTarget(None)
    assert _count(S, quarry) == 0
    menu.set_contacts([Contact(ship=quarry, surface_gu=1.0, perceivable=True,
                               targetable=True, subsystems_targetable=True)])
    assert target_menu.attempt_persistent_restore(player) is True
    assert _count(S, quarry) == 1


def test_door_target_death_clears_others_targets():
    from engine.appc import ship_death
    S, hunter, prey = _hunter_and_prey()
    hunter.SetTarget(prey)
    assert _count(S, prey) == 1
    ship_death._clear_target_locks(prey)
    assert hunter.GetTarget() is None
    assert _count(S, prey) == 0


def test_door_warp_clears_target():
    from engine.appc.warp import _clear_all_targets
    S, hunter, prey = _hunter_and_prey()
    hunter.SetTarget(prey)
    assert _count(S, prey) == 1
    _clear_all_targets(hunter)
    assert _count(S, prey) == 0


def test_door_sensor_loss_drops_the_player_lock(monkeypatch):
    import engine.appc.sensor_detection as sd
    S, player, prey = _hunter_and_prey()
    player.SetTarget(prey)
    assert _count(S, prey) == 1
    monkeypatch.setattr(sd, "can_detect", lambda *a, **k: False)
    sd.clear_undetectable_player_lock(player)
    assert player.GetTarget() is None
    assert _count(S, prey) == 0


# ── one writer ──────────────────────────────────────────────────────────────

_TARGET_OWNERS = {
    "engine/appc/ships.py",
    "engine/appc/weapon_subsystems.py",
    "engine/appc/events.py",
    "engine/appc/native_combat.py",
    "engine/ui/letterbox.py",
    "engine/ui/quick_battle_setup_panel.py",
}


def _py_files():
    for root in ("engine",):
        yield from (PROJECT_ROOT / root).rglob("*.py")
    for f in ("App.py", "tools/mission_harness.py"):
        yield PROJECT_ROOT / f


def _target_writes(tree):
    """(lineno, kind) of every write to an attribute `_target`, or to
    `__dict__["_target"]`."""
    out = []

    def targets_of(node):
        if isinstance(node, ast.Assign):
            return node.targets
        if isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            return [node.target]
        return []

    for node in ast.walk(tree):
        for t in targets_of(node):
            for sub in ast.walk(t):
                if isinstance(sub, ast.Attribute) and sub.attr == "_target":
                    out.append((node.lineno, "attr"))
                if (isinstance(sub, ast.Subscript)
                        and isinstance(sub.slice, ast.Constant)
                        and sub.slice.value == "_target"):
                    out.append((node.lineno, "dict"))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "setattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "_target"):
            out.append((node.lineno, "setattr"))
    return out


def test_target_has_one_writer():
    bad = []
    for path in _py_files():
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, kind in _target_writes(tree):
            if kind != "attr" or rel not in _TARGET_OWNERS:
                bad.append("%s:%d (%s)" % (rel, lineno, kind))
    assert not bad, bad

    ships = ast.parse((PROJECT_ROOT / "engine/appc/ships.py").read_text(encoding="utf-8"))
    owners = set()
    for cls in [n for n in ast.walk(ships) if isinstance(n, ast.ClassDef)
                and n.name == "ShipClass"]:
        for fn in [n for n in ast.walk(cls) if isinstance(n, ast.FunctionDef)]:
            if _target_writes(fn):
                owners.add(fn.name)
    assert owners == {"__init__", "SetTarget"}, owners
