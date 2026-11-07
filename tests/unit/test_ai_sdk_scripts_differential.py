"""Every SDK AI script that has a smoke test, walked by both walkers
(phase 6 AI part 4, Task 6).

Each case builds the script's tree on a ship in a small scene (the ship
carries the subsystems the smoke tests give it: hull, impulse engine, sensors,
shields, phasers, torpedoes, warp engine; a second ship and a waypoint are the
targets) and runs ``tests.helpers.ai_walk_diff.run_walk_diff`` for 120 ticks:
the call log into Python and the state of every node must agree tick for tick
between the Python walker and the native one. The step also advances the
ships' motion, as the smokes that run several ticks do, so the scripts see a
changing scene.

PlainAI scripts are the root node of the ship (a PlainAI is walkable on its
own); compound scripts are built through their own ``CreateAI``. Covered
scripts are the ones with a smoke file under ``tests/integration``. Not
covered, on purpose: ``test_m3gameflow_combat_smoke`` (a whole tutorial
mission; the golden fights run real trees), ``test_bindings_smoke`` /
``test_embedded_sdk_smoke`` / the hull-hit smokes (no AI tree), and
``ai_intercept`` / ``ai_stay`` / ``ai_goforward`` / ``ai_turn_to_orientation``
(run through ``GameLoop`` rather than a walker scene; their scripts Intercept,
Stay, GoForward and TurnToOrientation are cases here).
"""
import gc
import itertools
import sys

import pytest

import App

from tests.helpers import ai_walk_diff as awd

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "aitree_roster_count"),
    reason="native AI tree engine not built")

TICKS = 120
#: Awake scenes run longer: scripts poll every 0.5-5 s, and the change under
#: test lands midway.
AWAKE_TICKS = 360


@pytest.fixture(autouse=True)
def _game_and_sets():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    mission.SetScript("tests.unit.test_ai_sdk_scripts_differential")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    App.g_kSetManager._sets.clear()
    yield
    # The last side's world is finalised here, while the conditions' shared
    # instances are still registered (and before the per-test reset).
    _retire_previous_side()
    _set_current_game(None)
    App.g_kSetManager._sets.clear()


def _retire_previous_side():
    """Drop everything the previous side's world left behind, in the order
    that lets it finalise cleanly.

    * its sets, event handlers and condition groups (the per-test reset clears
      the same tables): handlers and groups would hear this side's events,
      and posting them allocates ids;
    * its garbage, collected on a THROWAWAY id counter: a condition's teardown
      allocates ids and would otherwise run inside this side at a
      collector-timing-dependent point and shift every id after it;
    * only then the SDK condition scripts' shared "internal instances" (one
      per ship name in a module global, which a new condition would reuse with
      the old verdict). Clearing them BEFORE the collection would make the old
      conditions' finalisers raise KeyError on removing their own entry."""
    from engine.appc import projectiles
    from engine.appc.objects import ObjectGroup
    from engine.core import ids
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    ObjectGroup._live.clear()
    ObjectGroup._by_name.clear()
    projectiles._active.clear()
    projectiles._groups.clear()
    projectiles._scan_mark_dirty()
    from engine.appc import ai_driver
    # The walker's module-level scratch lists hold the last walk's nodes, and
    # the out-of-action slot the last ship.
    ai_driver._ooa_cache[:] = [None, False]
    for attr in ("_reached_this_tick_all", "_reached_this_tick", "_all",
                 "_all_ids", "_pending_got_focus"):
        scratch = getattr(ai_driver, attr, None)
        if isinstance(scratch, (list, set, dict)):
            scratch.clear()
    # The id registry holds every TGObject strongly (the condition scripts'
    # event wrappers among them, and through them the conditions); the
    # per-test reset clears it too.
    ids._registry.clear()
    ids._weak_registry.clear()
    side_counter = ids._counter
    ids._counter = itertools.count(10 ** 9)
    try:
        for _ in range(3):
            gc.collect()
    finally:
        ids._counter = side_counter
    # Conditions that outlive the collection (the harness's instance-level
    # wrappers keep a few reachable) give their reference back NOW, while the
    # shared entry exists, and are told their finaliser has nothing to do.
    mod = sys.modules.get("Conditions.ConditionIncomingTorps")
    if mod is not None:
        class _Retired:
            def RemoveReference(self, *args):
                pass
        for obj in gc.get_objects():
            if type(obj) is mod.ConditionIncomingTorps and not isinstance(
                    obj.pInternal, _Retired):
                obj.pInternal.RemoveReference(obj, obj.pCodeCondition)
                obj.pInternal = _Retired()
    for name, mod in list(sys.modules.items()):
        if name.startswith("Conditions.") and isinstance(
                getattr(mod, "g_dInternalInstances", None), dict):
            mod.g_dInternalInstances.clear()


def _launch_torpedo(pSet, announce=False):
    """One hostile torpedo 100 GU ahead of Ours, closing at 50 GU/s."""
    from engine.appc import projectiles
    from engine.appc.math import TGPoint3
    torp = projectiles.Torpedo()
    torp.SetTranslateXYZ(0, 100, 0)
    torp._velocity = TGPoint3(0, -50, 0)
    projectiles.register(torp)
    pSet.AddObjectToSet(torp, "Torp")
    if announce:
        projectiles._post_set_transition(torp, entered=True)


def _world(target_y=400.0, torpedo=False):
    """The shared scene: set "S" with ``Ours`` (fully equipped), ``Target``
    `target_y` GU ahead (+Y), a waypoint ``WP1`` and, if asked, one hostile
    torpedo inbound on ``Ours``."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import (
        HullSubsystem, ShieldSubsystem, PhaserSystem, TorpedoSystem,
        TorpedoAmmoType, ImpulseEngineSubsystem, SensorSubsystem,
        WarpEngineSubsystem)
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass()
    ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._hull.SetCritical(1)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(120.0)
    ies.SetMaxAccel(50.0)
    ies.SetMaxAngularVelocity(0.5)
    ies.SetMaxAngularAccel(0.3)
    ours._impulse_engine_subsystem = ies
    sensors = SensorSubsystem("Sensors")
    sensors.SetMaxCondition(100.0)
    sensors.SetCondition(100.0)
    ours.SetSensorSubsystem(sensors)
    shields = ShieldSubsystem("Sh")
    for face in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(face, 100.0)
        shields._current_shields[face] = 80.0
    ours.SetShieldSubsystem(shields)
    ours._phaser = PhaserSystem("P")
    ours._phaser._parent_ship = ours
    ours._torpedo_system = TorpedoSystem("T")
    ours._torpedo_system._parent_ship = ours
    ours._torpedo_system._ammo_by_slot = {
        0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    ours._warp_engine_subsystem = WarpEngineSubsystem("WES")
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass()
    target.SetTranslateXYZ(0, target_y, 0)
    target._hull = HullSubsystem("H")
    target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    wp = App.Waypoint_Create("WP1", "S", None)
    wp.SetTranslateXYZ(1500.0, 300.0, 0.0)
    if torpedo:
        from engine.appc import projectiles
        projectiles._active.clear()
        projectiles._groups.clear()
        projectiles._scan_mark_dirty()
        _launch_torpedo(pSet)
    return ours, target


def _plain(module, setup=None):
    from engine.appc.ai import PlainAI_Create

    def build(ours, target):
        plain = PlainAI_Create(ours, "Test" + module)
        plain.SetScriptModule(module)
        if setup is not None:
            setup(plain.GetScriptInstance())
        return plain
    return build


def _compound(module, *args):
    def build(ours, target):
        import importlib
        mod = importlib.import_module(module)
        return mod.CreateAI(ours, *args)
    return build


def _group(name):
    from engine.appc.objects import ObjectGroup
    g = ObjectGroup()
    g.AddName(name)
    return g


def _vec(x, y, z):
    v = App.TGPoint3()
    v.SetXYZ(x, y, z)
    return v


def _trigger_event(inst):
    from engine.appc.events import TGEvent
    evt = TGEvent()
    evt.SetEventType(App.ET_MISSION_START)
    inst.SetEvent(evt)


def _run_script(inst):
    inst.SetScriptModule("MissionLib")
    inst.SetFunction("GetPlayer")


def _maneuver(inst):
    inst.SetLoopFraction(0.25)
    inst.SetTurnAxis(App.TGPoint3_GetModelLeft())
    inst.SetSpeeds(0.0, 0.0)


def _intercept(inst):
    inst.SetTargetObjectName("Target")
    inst.SetMaximumSpeed(120.0)


#: name -> tree builder; one per AI module with a smoke file (the guard
#: below parses the smoke files and requires each module here or in
#: EXCLUDED_MODULES).
CASES = {
    "plain/GoForward": _plain("GoForward", lambda i: i.SetImpulse(50.0)),
    "plain/Stay": _plain("Stay"),
    "plain/Intercept": _plain("Intercept", _intercept),
    "plain/TurnToOrientation": _plain(
        "TurnToOrientation", lambda i: i.SetObjectName("Target")),
    "plain/CircleObject": _plain(
        "CircleObject", lambda i: (i.SetFollowObjectName("Target"),
                                   i.SetNearFacingVector(_vec(1, 0, 0)))),
    "plain/Defensive": _plain("Defensive", lambda i: i.SetEnemyName("Target")),
    "plain/EvadeTorps": _plain("EvadeTorps"),
    "plain/EvilShuttleDocking": _plain(
        "EvilShuttleDocking", lambda i: i.SetObjectToDockWith("Target")),
    "plain/Flee": _plain(
        "Flee", lambda i: i.SetFleeFromGroup(_group("Target"))),
    "plain/FollowObject": _plain(
        "FollowObject", lambda i: i.SetFollowObjectName("Target")),
    "plain/FollowThroughWarp": _plain(
        "FollowThroughWarp", lambda i: i.SetFollowObjectName("Target")),
    "plain/FollowWaypoints": _plain(
        "FollowWaypoints", lambda i: i.SetTargetWaypointName("WP1")),
    "plain/IntelligentCircleObject": _plain(
        "IntelligentCircleObject",
        lambda i: i.SetFollowObjectName("Target")),
    "plain/ManeuverLoop": _plain("ManeuverLoop", _maneuver),
    "plain/MoveToObjectSide": _plain(
        "MoveToObjectSide", lambda i: (i.SetObjectSide(_vec(1, 0, 0)),
                                       i.SetObjectName("Target"))),
    "plain/Ram": _plain("Ram", lambda i: i.SetTargetObjectName("Target")),
    "plain/RunAction": _plain(
        "RunAction", lambda i: i.SetAction(App.TGAction_CreateNull())),
    "plain/RunScript": _plain("RunScript", _run_script),
    "plain/SelfDestruct": _plain("SelfDestruct"),
    "plain/StarbaseAttack": _plain(
        "StarbaseAttack", lambda i: i.SetTargets(_group("Target"))),
    "plain/StationaryAttack": _plain(
        "StationaryAttack", lambda i: i.SetTargetObjectName("Target")),
    "plain/TorpedoRun": _plain(
        "TorpedoRun", lambda i: i.SetTargetObjectName("Target")),
    "plain/TriggerEvent": _plain("TriggerEvent", _trigger_event),
    "plain/Warp": _plain("Warp"),
    "compound/FedAttack": _compound("AI.Compound.FedAttack", "Target"),
    "compound/NonFedAttack": _compound("AI.Compound.NonFedAttack", "Target"),
    "compound/CallDamageAI": _compound("AI.Compound.CallDamageAI"),
    "compound/FollowThroughWarp": _compound(
        "AI.Compound.FollowThroughWarp", "Target"),
    "parts/EvadeTorps": _compound("AI.Compound.Parts.EvadeTorps"),
    "parts/ICOMove": _compound("AI.Compound.Parts.ICOMove", "Target", {}),
    "parts/NoSensorsEvasive": _compound("AI.Compound.Parts.NoSensorsEvasive"),
    "parts/SweepPhasers": _compound(
        "AI.Compound.Parts.SweepPhasers", "Target", 0.75, {}),
    "parts/WarpBeforeDeath": _compound(
        "AI.Compound.Parts.WarpBeforeDeath", {}),
}

def _scene(build_tree, target_y=400.0, torpedo=False, actions=None,
           timed=False):
    """`actions[i](ours)` runs before tick i's walk. `timed`: the AI time-slice
    scheduler also runs each tick (conditions that poll on a
    PythonMethodProcess, e.g. incoming torpedoes) and the combat tick
    boundary delivers held effects (subsystem watcher events)."""
    actions = actions or {}

    def scene(mp):
        from engine.appc.ship_motion import _step_ship_motion
        _retire_previous_side()
        from engine.appc.time_slice import g_kAIManager
        g_kAIManager._procs = []
        ours, target = _world(target_y, torpedo)
        ours.SetAI(build_tree(ours, target))
        ships = [ours, target]

        def step(i):
            from engine.appc import ai_driver
            if i in actions:
                actions[i](ours)
            if timed:
                from engine.appc.planet import evaluate_proximity_checks
                evaluate_proximity_checks()
                g_kAIManager.tick((i + 1) / 60.0, (i + 1) / 60.0)
            ai_driver.tick_all_ai((i + 1) / 60.0)
            for s in ships:
                _step_ship_motion(s, 1.0 / 60.0)
            if timed:
                # Held effects (subsystem watcher events) land at the tick
                # boundary.
                from engine import host_loop
                host_loop._combat_tick_boundary()
        return awd.synthetic_scene(mp, [ours], step)
    return scene


@pytest.mark.parametrize("name", sorted(CASES))
def test_sdk_script_walks_identically(name):
    rec = awd.run_walk_diff(_scene(CASES[name]), TICKS, warm_ticks=TICKS)
    # The scene must have walked something: the root was visited natively.
    assert rec.calls(), "%s: no Python call was ever logged" % name


# -- awake scenes: the trees actually working ---------------------------------

def _blind(ours):
    ours._sensor_subsystem.SetCondition(10.0)


def _repair_sensors(ours):
    ours._sensor_subsystem.SetCondition(100.0)


def _cripple(ours):
    ours._hull.SetCondition(50.0)


def _repair_hull(ours):
    ours._hull.SetCondition(1000.0)


def _move_target(y):
    def act(ours):
        App.ObjectClass_GetObject(None, "Target").SetTranslateXYZ(0, y, 0)
    return act


def _torp_out(ours):
    """The inbound torpedo is gone."""
    from engine.appc import projectiles
    projectiles.expire(projectiles._active[0])      # posts the exit event


def _torp_in(ours):
    """... and another one comes in."""
    _launch_torpedo(ours.GetContainingSet(), announce=True)


def _set_flag(node_name, value):
    """Set the status of the first condition of the ConditionalAI `node_name`
    in Ours' tree (the SDK's flag conditions are plain statuses)."""
    def act(ours):
        from engine.appc.ai import ArtificialIntelligence
        todo = [ours.GetAI()]
        while todo:
            n = todo.pop()
            if n.GetName() == node_name:
                n._conditions[0].SetStatus(value)
                return
            todo.extend(getattr(n, "_ais", []) and [
                c[1] if isinstance(c, tuple) else c for c in n._ais])
            if getattr(n, "_contained_ai", None) is not None:
                todo.append(n._contained_ai)
        raise AssertionError("no node " + node_name)
    return act


def _both(*acts):
    def act(ours):
        for a in acts:
            a(ours)
    return act


#: name -> (builder, scene kwargs). Each scene changes something at tick 120,
#: 200 and 280 so the tree switches on and then off again.
def _awake_cases():
    return {
        "FedAttack": (CASES["compound/FedAttack"], dict(
            target_y=30.0, torpedo=True, timed=True,
            actions={120: _both(_move_target(900.0), _torp_out),
                     200: _both(_move_target(30.0), _torp_in),
                     280: _move_target(900.0)})),
        "NonFedAttack": (CASES["compound/NonFedAttack"], dict(
            target_y=30.0, torpedo=True, timed=True,
            actions={120: _both(_move_target(900.0), _torp_out),
                     200: _both(_move_target(30.0), _torp_in),
                     280: _move_target(900.0)})),
        "SweepPhasers": (CASES["parts/SweepPhasers"], dict(
            target_y=30.0, timed=True,
            actions={120: _set_flag("UseSideArcs", 1),
                     200: _set_flag("UseSideArcs", 0),
                     280: _set_flag("UseSideArcs", 1)})),
        "EvadeTorps": (_compound("AI.Compound.Parts.EvadeTorps", None,
                                 {"AvoidTorps": 1}), dict(
            target_y=30.0, torpedo=True, timed=True,
            actions={120: _torp_out, 200: _torp_in, 280: _torp_out})),
        "WarpBeforeDeath": (_compound("AI.Compound.Parts.WarpBeforeDeath",
                                      {"WarpOutBeforeDying": 1}), dict(
            timed=True, actions={120: _cripple, 200: _repair_hull,
                                 280: _cripple})),
        "NoSensorsEvasive": (CASES["parts/NoSensorsEvasive"], dict(
            timed=True, actions={120: _blind, 200: _repair_sensors,
                                 280: _blind})),
    }


def _tree_movement(rec):
    """What the recorded run shows the tree doing, from the call log and the
    per-tick node state:

    * ``updates``: script Updates;
    * ``edges`` / ``deactivations``: real changes of a node's
      ``_is_active_in_tree`` after tick 0 (the first walk's activation), False
      to True and True to False respectively (SetActive / SetInactive are also
      called on every walk, so call counts say nothing);
    * ``verdicts``: distinct EvalFunc results;
    * ``switched``: nodes whose picked child changed: ``_current_child`` (a
      RandomAI's pick; priority lists have none) or ``_current_index`` (a
      SequenceAI's step) took two or more values over the run, None and a
      node counted as different values (the snapshot does record the field:
      a measure that skipped None saw a RandomAI's pick-and-finish as one
      value and so read as dead);
    * ``focus_moves``: ticks where the set of focused nodes changed."""
    updates = sum(1 for log, _s in rec.ticks for e in log
                  if e[0] == "call" and e[1] == "script.Update")
    verdicts = {e[3] for e in rec.log() if e[0] == "ret" and e[1] == "eval"}
    edges = deactivations = focus_moves = 0
    children = {}
    prev_active = {}
    prev_focus = None
    for t, (_log, snap) in enumerate(rec.ticks):
        focus = set()
        for sname, ship in snap["ships"].items():
            for nid, st in ship["nodes"].items():
                key = (sname, nid)
                act = st["_is_active_in_tree"]
                if t >= 1 and key in prev_active and prev_active[key] != act:
                    edges += 1
                    deactivations += not act
                prev_active[key] = act
                for field in ("_current_child", "_current_index"):
                    if st[field] != awd._ABSENT:
                        children.setdefault((key, field), set()).add(
                            st[field])
                if st["_has_focus"] is True or st["_has_focus"] == 1:
                    focus.add(key)
        if t >= 1 and prev_focus is not None and focus != prev_focus:
            focus_moves += 1
        prev_focus = focus
    return {"updates": updates, "edges": edges,
            "deactivations": deactivations, "verdicts": len(verdicts),
            "switched": sorted(n for n, c in children.items() if len(c) >= 2),
            "focus_moves": focus_moves}


@pytest.mark.parametrize("name", sorted(_awake_cases()))
def test_awake_scene_walks_identically(name):
    build, kw = _awake_cases()[name]
    rec = awd.run_walk_diff(_scene(build, **kw), AWAKE_TICKS,
                            warm_ticks=AWAKE_TICKS)
    awake = _tree_movement(rec)
    # The same tree in the static scene (400 GU target, nothing happening),
    # for the same number of ticks, on the Python side.
    static = _tree_movement(awd.run_side(_scene(build), AWAKE_TICKS,
                                         native=False))
    detail = (name, awake, static)
    if name == "SweepPhasers":
        # PhaserSweep polls every 0.3 s whenever it has focus, in the static
        # scene too, so its Update count cannot rise; the switch between the
        # side-arc and plain sweep is what this scene adds.
        assert awake["updates"] >= static["updates"], detail
    else:
        assert awake["updates"] >= max(2 * static["updates"],
                                       static["updates"] + 3), detail
    assert awake["edges"] >= 1, detail
    assert awake["deactivations"] >= 1, detail
    assert awake["verdicts"] >= 2 or awake["switched"], detail
    assert awake["focus_moves"] >= 2, detail      # focus moved between nodes


# -- guard: every AI module a smoke test touches has a case ------------------

#: Smoke-file modules with no case, and why.
EXCLUDED_MODULES = {
    "AI.Compound.BasicAttack": "dispatcher; routes to FedAttack/NonFedAttack",
}


def test_every_smoked_ai_module_has_a_case():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    smoked = set()
    for d in ("integration", "host", "unit"):
        for f in (root / d).glob("*smoke*.py"):
            txt = f.read_text()
            smoked.update(re.findall(
                r"import (AI\.(?:PlainAI|Compound)[\w.]*)", txt))
            smoked.update("AI.PlainAI." + m for m in re.findall(
                r'(?:plain|pai)\.SetScriptModule\("(\w+)"\)', txt))
    assert len(smoked) >= 25, sorted(smoked)      # the scan found the smokes
    covered = set()
    for key, build in CASES.items():
        kind, mod = key.split("/")
        covered.add({"plain": "AI.PlainAI.", "compound": "AI.Compound.",
                     "parts": "AI.Compound.Parts."}[kind] + mod)
    missing = {m for m in smoked if m not in covered
               and m not in EXCLUDED_MODULES}
    assert not missing, "smoked AI modules without a CASES entry: %s" % sorted(
        missing)
