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
    _set_current_game(None)
    App.g_kSetManager._sets.clear()


def _world(target_y=400.0, torpedo=False):
    """The shared scene: set "S" with ``Ours`` (fully equipped), ``Target``
    `target_y` GU ahead (+Y), a waypoint ``WP1`` and, if asked, one hostile
    torpedo inbound on ``Ours``."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import (
        HullSubsystem, ShieldSubsystem, PhaserSystem, TorpedoSystem,
        TorpedoAmmoType, ImpulseEngineSubsystem, SensorSubsystem,
        WarpEngineSubsystem)
    App.g_kSetManager._sets.clear()
    # The previous side's broadcast / method handlers (a condition's torpedo
    # or set listener) would still hear this side's events; the per-test
    # reset clears the same two tables.
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    # Condition scripts share an "internal instance" per (ship name, ...) in a
    # module global; the previous side's would be reused with its old verdict.
    for name, mod in list(sys.modules.items()):
        if name.startswith("Conditions.") and isinstance(
                getattr(mod, "g_dInternalInstances", None), dict):
            mod.g_dInternalInstances.clear()
    # Groups the previous side's conditions still hold would hear this set's
    # membership events, and posting them allocates ids (the per-test reset
    # does the same clearing).
    from engine.appc.objects import ObjectGroup
    ObjectGroup._live.clear()
    ObjectGroup._by_name.clear()
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
        from engine.appc.math import TGPoint3
        projectiles._active.clear()
        projectiles._groups.clear()
        projectiles._scan_mark_dirty()
        torp = projectiles.Torpedo()
        torp.SetTranslateXYZ(0, 100, 0)
        torp._velocity = TGPoint3(0, -50, 0)
        projectiles.register(torp)
        pSet.AddObjectToSet(torp, "Torp")
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
        # Garbage of the previous side whose finaliser allocates an id (a
        # condition's teardown) would otherwise run inside this side, on its
        # fresh counter, at a collector-timing-dependent point and shift
        # every id after it. Collect it on a throwaway counter.
        from engine.core import ids
        side_counter = ids._counter
        ids._counter = itertools.count(10 ** 9)
        try:
            for _ in range(3):
                gc.collect()
        finally:
            ids._counter = side_counter
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


def _cripple(ours):
    ours._hull.SetCondition(50.0)


#: name -> (builder, scene kwargs, minimum number of script Updates)
def _awake_cases():
    return {
        "FedAttack": (CASES["compound/FedAttack"], dict(target_y=30.0,
                                                         torpedo=True,
                                                         timed=True), 30),
        "NonFedAttack": (CASES["compound/NonFedAttack"],
                         dict(target_y=30.0, torpedo=True, timed=True), 30),
        "SweepPhasers": (CASES["parts/SweepPhasers"],
                         dict(target_y=30.0, timed=True), 12),
        "EvadeTorps": (_compound("AI.Compound.Parts.EvadeTorps", None,
                                 {"AvoidTorps": 1}),
                       dict(target_y=30.0, torpedo=True, timed=True), 20),
        "WarpBeforeDeath": (_compound("AI.Compound.Parts.WarpBeforeDeath",
                                      {"WarpOutBeforeDying": 1}),
                            dict(actions={150: _cripple}, timed=True), 2),
        "NoSensorsEvasive": (CASES["parts/NoSensorsEvasive"],
                             dict(actions={150: _blind}, timed=True), 4),
    }


@pytest.mark.parametrize("name", sorted(_awake_cases()))
def test_awake_scene_walks_identically(name):
    build, kw, min_updates = _awake_cases()[name]
    rec = awd.run_walk_diff(_scene(build, **kw), AWAKE_TICKS,
                            warm_ticks=AWAKE_TICKS)
    calls = rec.calls()
    assert calls["script.Update"] >= min_updates, (name, dict(calls))
    # The tree switched state: a node was activated and one deactivated or
    # lost focus, beyond the first-tick activation.
    assert calls["node.SetActive"] >= 1, dict(calls)
    if name.startswith("Fed") or name.startswith("NonFed"):
        assert calls["eval"] >= 6, dict(calls)      # conditionals flipped
    if name in ("WarpBeforeDeath", "NoSensorsEvasive"):
        # The midway change flipped a conditional: the eval ran again with a
        # different verdict.
        evals = [e for e in rec.log() if e[0] == "ret" and e[1] == "eval"]
        assert len({e[3] for e in evals}) >= 2, evals[:6]


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
