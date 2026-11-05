"""The ``motion_branches`` golden scene: every ship-motion branch, recorded
from the Python motion before it is ported to a native kernel (native motion
phase 2, Task 1; docs/reference/engine/native-motion/golden-fights-for-motion.md
section 5.1).

combat_stress is loaded for its set and player (two AI ships, cleared of
their AI and parked far away), then a cast of scripted ships is added with
``loadspacehelper.CreateShip`` (real impulse pods) and driven the loop's own
way: the beats, ``GameLoop.tick()``, ``host_loop._combat_tick_boundary()``,
the record. No weapons, no combat, no tractor.

The branches of ``engine/appc/ship_motion._step_ship_motion`` and who takes
each (the cast is in set order, which decides the kernel's segments):

* immobile anchor                  -> ``Anchor``
* in-system warp flight            -> ``Warper`` (flies), ``WarperBoP``
                                      (holds for its parts: step() False,
                                      then its setpoints, then the flight)
* warp-in arrival (dewarp drive)   -> ``Arriver``
* setpoint-less drift              -> ``Drifter`` (model-space spin),
                                      ``DrifterW`` (world-space spin),
                                      the two parked AI ships, ``Target``,
                                      and the player before tick 500
* total loss -> inertial drift     -> ``Cripple`` (tick 200; repaired 400)
* the ramp and its caps            -> ``Ramp`` (beats below), ``Cripple``,
                                      the player after tick 500
* no impulse engine at all         -> ``Bare`` (fallback snap)
* an engine with authored limits 0 -> ``ZeroLimits`` (fallback snap)

``run`` returns ``(state, events, queued)``: per tick ``pose`` rows
(golden_fight._pose_rows) then ``motion`` rows (``motion_rows``), then every
AddEvent row (all but the queued kinds), as golden_fight's scenes do.
"""
import math

import App

from engine import host_loop
from engine.appc import subsystems, warp_state
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.placement import PlacementObject
from engine.appc.ship_iter import iter_ships
from engine.appc.ship_motion import _effective_motion
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import ImpulseEngineSubsystem
from engine.core import loop as game_loop
from engine.core import step_memo
from tests.helpers import effect_split, headless_mission
from tests.helpers.fight_audio import isolate_fight_audio
from tests.helpers.k1_fight import _seed_every_rng

MODEL = PhysicsObjectClass.DIRECTION_MODEL_SPACE
WORLD = PhysicsObjectClass.DIRECTION_WORLD_SPACE

MOTION_FIELDS = (
    "name", "_current_speed", "_current_angular_velocity", "_drift_velocity",
    "_speed_setpoint", "_target_angular_velocity_setpoint",
    "_angular_velocity", "_angular_space", "warp_flight", "_warp_consumed",
    "arriving", "impulse_fractions", "effective_motion")

TICK_REPAIR = 400           # Cripple: one pod back to maximum
TICK_CRIPPLE = 200          # Cripple: every pod to condition 0
TICK_PLAYER = 500           # the player's first speed setpoint
TICK_WARP = 30              # both warpers
TICK_ARRIVE = 20            # Arriver's dewarp drive starts
TICK_BARE = 100             # Bare's setpoint is written

#: Ramp's beats: (tick, name).
RAMP_BEATS = (
    (10, "over_max"), (400, "pods_half"), (430, "pods_full"),
    (450, "reverse"), (950, "ang_over_max"), (1000, "power_half"),
    (1050, "off"), (1080, "on"), (1110, "world_dir"), (1180, "no_speed"),
)
TICK_ARRIVER_FLY = 200      # Arriver: setpoints, after the 2 s slide
RAD_IES = (600, 650)        # ZeroLimits: its IES _radiation_out is set


# ── the record ───────────────────────────────────────────────────────────────

def _f(v):
    return float(v).hex()


def _vec(p):
    return None if p is None else [_f(p.x), _f(p.y), _f(p.z)]


def _setpoint(sp):
    if sp is None:
        return None
    speed, direction, frame = sp
    return [_f(speed), _vec(direction), int(frame)]


def _flight(ship):
    flight = ship.__dict__.get("_insystem_warp_transit")
    if flight is None:
        return None
    target = flight.target
    label = target.GetName() if hasattr(target, "GetName") else repr(target)
    return [label, flight.speed_policy, _f(flight._parts_hold),
            _f(flight._held)]


def _motion_row(ship):
    d = ship.__dict__
    ies = ship.GetImpulseEngineSubsystem()
    online, output = subsystems.impulse_fractions(ies)
    em = _effective_motion(ship)
    consumed = d.get("_warp_consumed")
    space = d.get("_angular_space")
    speed = d.get("_current_speed")
    return ["motion", ship.GetName(),
            None if speed is None else _f(speed),
            _vec(d.get("_current_angular_velocity")),
            _vec(d.get("_drift_velocity")),
            _setpoint(d.get("_speed_setpoint")),
            _vec(d.get("_target_angular_velocity_setpoint")),
            _vec(d.get("_angular_velocity")),
            None if space is None else int(space),
            _flight(ship),
            None if consumed is None else bool(consumed),
            bool(warp_state.is_arriving(ship)),
            [_f(online), _f(output)],
            [bool(em.has_linear), _f(em.max_speed), _f(em.max_accel),
             bool(em.has_angular), _f(em.max_ang_vel), _f(em.max_ang_accel)]]


def motion_rows(ships):
    """One ``["motion", name, ...]`` row per ship (golden_fight.FIELDS)."""
    return [_motion_row(s) for s in ships]


# ── the world ────────────────────────────────────────────────────────────────

def _create(kind, name, pSet, x, y, z=0.0, radius=4.0):
    import loadspacehelper
    ship = loadspacehelper.CreateShip(kind, pSet, name, "")
    assert not App.IsNull(ship), kind
    ship.SetTranslateXYZ(x, y, z)
    ship.UpdateNodeOnly()
    if ship.GetRadius() <= 0.0:
        ship.SetRadius(radius)
    return ship


def _fwd():
    return TGPoint3(0.0, 1.0, 0.0)


def _turned(radians):
    m = TGMatrix3()
    m.MakeZRotation(radians)
    return m


def _bare(name, pSet, x, y, impulse=False):
    ship = ShipClass_Create(name)
    ship.SetTranslateXYZ(x, y, 0.0)
    if impulse:
        ies = ImpulseEngineSubsystem("Impulse Engines")
        ies._max_condition = 100.0
        ies._condition = 100.0
        ship.SetImpulseEngineSubsystem(ies)
    pSet.AddObjectToSet(ship, name)
    return ship


def _pods(ship):
    ies = ship.GetImpulseEngineSubsystem()
    return [ies.GetChildSubsystem(i) for i in range(ies.GetNumChildSubsystems())]


def _build(mp, env, ships):
    """combat_stress for its set and player, then the cast (module doc)."""
    mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
    mp.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
    mp.setenv("DAUNTLESS_COMBAT_SHIPS", ships)
    for k, v in env.items():
        mp.setenv(k, v)
    from engine.appc import native_combat as nc
    nc.reset()
    App.g_kTimerManager._time = 0.0
    _seed_every_rng(0)
    headless_mission.clear_in_flight()
    isolate_fight_audio(mp)
    headless_mission.load("engine.dev_missions.combat_stress")
    host_loop._reset_sensor_state()
    step_memo.forget()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")
    player = App.Game_GetCurrentPlayer()
    # The two stock AI ships: no AI, parked far from everything.
    parked = [s for s in iter_ships() if s is not player]
    assert len(parked) == int(ships), [s.GetName() for s in parked]
    for i, s in enumerate(parked):
        s.ClearAI()
        s.SetTranslateXYZ(9000.0, 3000.0 * (i + 1), 0.0)
        s.UpdateNodeOnly()

    cast = {}
    cast["Anchor"] = _create("Galaxy", "Anchor", pSet, 0.0, 300.0)
    cast["Ramp"] = _create("Galaxy", "Ramp", pSet, 0.0, 600.0)
    # Warpers: 600 GU from Target, nose on it; WarperBoP on the far side.
    cast["Warper"] = _create("Galaxy", "Warper", pSet, 3000.0, 2400.0)
    cast["WarperBoP"] = _create("BirdOfPrey", "WarperBoP", pSet,
                                3000.0, 3600.0)
    cast["WarperBoP"].SetMatrixRotation(_turned(math.pi))
    cast["Arriver"] = _create("Galaxy", "Arriver", pSet, -1000.0, -1000.0)
    cast["Drifter"] = _create("Galaxy", "Drifter", pSet, -2000.0, 0.0)
    cast["DrifterW"] = _create("Galaxy", "DrifterW", pSet, -2000.0, 300.0)
    cast["Cripple"] = _create("Galaxy", "Cripple", pSet, -2000.0, 600.0)
    cast["Bare"] = _bare("Bare", pSet, -3000.0, 0.0)
    cast["ZeroLimits"] = _bare("ZeroLimits", pSet, -3000.0, 300.0,
                               impulse=True)
    cast["Target"] = _create("Galaxy", "Target", pSet, 3000.0, 3000.0)
    return pSet, player, cast, parked


def _setup(cast, player):
    """The beats that run before tick 1."""
    anchor = cast["Anchor"]
    anchor.SetStatic(1)
    anchor.SetSpeed(5.0, _fwd(), MODEL)
    anchor.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.2))

    cast["Ramp"].SetSpeed(0.0, _fwd(), MODEL)

    for name in ("Warper", "WarperBoP"):
        cast[name].SetSpeed(2.0, _fwd(), MODEL)

    dr = cast["Drifter"]
    dr.SetVelocity(TGPoint3(1.0, 0.0, 0.5))
    dr.SetAngularVelocity(TGPoint3(0.1, 0.05, 0.2), MODEL)
    dw = cast["DrifterW"]
    dw.SetVelocity(TGPoint3(-1.0, 0.5, 0.0))
    dw.SetAngularVelocity(TGPoint3(0.1, 0.05, 0.2), WORLD)

    cr = cast["Cripple"]
    cr.SetSpeed(4.0, _fwd(), MODEL)
    cr.SetTargetAngularVelocityDirect(TGPoint3(0.3, 0.0, 0.2))
    pods = _pods(cr)
    assert len(pods) >= 2, len(pods)
    pods[0]._radiation_out = True       # out of action throughout

    cast["ZeroLimits"].SetSpeed(3.0, _fwd(), MODEL)
    cast["ZeroLimits"].SetTargetAngularVelocityDirect(
        TGPoint3(0.0, 0.0, 0.1))


def _placement():
    p = PlacementObject()
    p.SetTranslateXYZ(-1000.0, -700.0, 0.0)
    return p


def _ramp_beat(ship, beat):
    ies = ship.GetImpulseEngineSubsystem()
    if beat == "over_max":
        ship.SetSpeed(20.0, _fwd(), MODEL)
    elif beat == "pods_half":
        for pod in _pods(ship):
            pod.SetCondition(pod.GetMaxCondition() * 0.5)
    elif beat == "pods_full":
        for pod in _pods(ship):
            pod.SetCondition(pod.GetMaxCondition())
    elif beat == "reverse":
        ship.SetSpeed(-20.0, _fwd(), MODEL)     # past the reverse cap
    elif beat == "ang_over_max":
        ship.SetTargetAngularVelocityDirect(TGPoint3(5.0, 5.0, 5.0))
    elif beat == "power_half":
        ies.SetPowerPercentageWanted(0.5)
    elif beat == "off":
        ies.TurnOff()
    elif beat == "on":
        ies.TurnOn()
    elif beat == "world_dir":
        ship.SetSpeed(4.0, TGPoint3(1.0, 1.0, 0.0), WORLD)
    elif beat == "no_speed":
        ship.SetTargetAngularVelocityDirect(TGPoint3(0.3, 0.0, 0.2))
        ship._speed_setpoint = None
    else:
        raise AssertionError(beat)


def _beats(t, cast, player, placement):
    ramp_beats = dict((tick, b) for tick, b in RAMP_BEATS)
    if t in ramp_beats:
        _ramp_beat(cast["Ramp"], ramp_beats[t])
    if t == TICK_WARP:
        for name in ("Warper", "WarperBoP"):
            got = cast[name].InSystemWarp(cast["Target"], 50)
            assert got == 1, (name, got)
    if t == TICK_ARRIVE:
        sub = cast["Arriver"].GetWarpEngineSubsystem()
        sub.SetPlacement(placement)
        sub.SetWarpState(sub.WES_WARPING)
        sub.TransitionToState(sub.WES_DEWARP_INITIATED)
    if t == TICK_ARRIVER_FLY:
        arr = cast["Arriver"]
        arr.SetSpeed(3.0, _fwd(), MODEL)
        arr.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.3))
    if t == TICK_BARE:
        cast["Bare"].SetSpeed(2.0, _fwd(), MODEL)
        cast["Bare"].SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.1))
    if t == TICK_CRIPPLE:
        for pod in _pods(cast["Cripple"]):
            pod.SetCondition(0.0)
    if t == TICK_REPAIR:
        pod = _pods(cast["Cripple"])[1]
        pod.SetCondition(pod.GetMaxCondition())
    if t in RAD_IES:
        cast["ZeroLimits"].GetImpulseEngineSubsystem()._radiation_out = (
            t == RAD_IES[0])
    if t == TICK_PLAYER:
        player.SetSpeed(3.0, _fwd(), MODEL)


def _pos(ship):
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def run(mp, env, ticks):
    """Build and run the scene; returns ``(state, events, queued)``."""
    from tests.helpers import golden_fight
    pSet, player, cast, parked = _build(mp, env, "2")
    placement = _placement()
    _setup(cast, player)
    ships = list(iter_ships())
    names = [s.GetName() for s in ships]
    assert len(set(names)) == len(names), names
    for need in ("Anchor", "Ramp", "Warper", "WarperBoP", "Arriver",
                 "Drifter", "DrifterW", "Cripple", "Bare", "ZeroLimits",
                 "Target"):
        assert need in names, need

    state, events = [], []
    tick = [0]

    def label(obj):
        name = obj.GetName() if hasattr(obj, "GetName") else None
        return name if isinstance(name, str) else type(obj).__name__

    queued = effect_split.Queued(mp, label, lambda: tick[0])
    orig = App.g_kEventManager.AddEvent
    posts = []

    def add_event(evt, _orig=orig):
        payload = None
        if evt.GetEventType() == App.ET_IN_SYSTEM_WARP:
            payload = int(evt.GetBool())
            posts.append(payload)
        row = (evt.GetEventType(), label(evt.GetSource()),
               label(evt.GetDestination()), tick[0], payload)
        if queued.takes(evt):
            queued.rows.append(row)
        else:
            events.append(row)
        return _orig(evt)

    mp.setattr(App.g_kEventManager, "AddEvent", add_event)
    _seed_every_rng(20261110)
    loop = game_loop.GameLoop(owns_boundary=False)

    seen = {"anchor": set(), "warper_flight": [], "bop_hold": 0,
            "bop_moved": 0, "arriving": 0, "drift_set": [],
            "bare": None}
    last = {}
    pre = {n: _pos(cast[n]) for n in ("Anchor", "WarperBoP")}
    player_start = _pos(player)
    player_before, player_after = set(), set()
    while tick[0] < ticks:
        tick[0] += 1
        t = tick[0]
        _beats(t, cast, player, placement)
        loop.tick()
        host_loop._combat_tick_boundary()
        ships = list(iter_ships())
        state.append(golden_fight._pose_rows(ships)
                     + motion_rows(ships) + golden_fight._stage_rows(ships))
        # ── the scene's own evidence
        seen["anchor"].add(_pos(cast["Anchor"]))
        w = cast["Warper"].__dict__.get("_insystem_warp_transit")
        seen["warper_flight"].append(w is not None)
        b = cast["WarperBoP"]
        bf = b.__dict__.get("_insystem_warp_transit")
        if bf is not None and bf._parts_hold > 0.0:
            seen["bop_hold"] += 1
            if _pos(b) != last.get("bop"):
                seen["bop_moved"] += 1
        last["bop"] = _pos(b)
        if warp_state.is_arriving(cast["Arriver"]):
            seen["arriving"] += 1
        seen["drift_set"].append(
            cast["Cripple"].__dict__.get("_drift_velocity") is not None)
        (player_before if t < TICK_PLAYER else player_after).add(
            _pos(player))
        ramp = cast["Ramp"]
        cap = _effective_motion(ramp).max_speed
        if abs(ramp._current_speed - cap) < 0.1 and "cap" not in seen:
            seen["cap"] = t
        if ramp._current_speed < 0.0 and "neg" not in seen:
            seen["neg"] = t
        if t == RAD_IES[0] + 1 or t == RAD_IES[1] - 1:
            seen.setdefault("rad", []).append(subsystems.impulse_fractions(
                cast["ZeroLimits"].GetImpulseEngineSubsystem()))
        if t == TICK_BARE:      # written at the start of this very tick
            bare = cast["Bare"]
            seen["bare"] = (bare._current_speed,
                            bare._speed_setpoint[0])

    # ── the scene is what it claims
    assert seen["anchor"] == {pre["Anchor"]}, "Anchor moved"
    wf = seen["warper_flight"]
    assert any(wf), "Warper never flew an in-system warp"
    first = wf.index(True)
    assert False in wf[first:] and not wf[-1], "Warper's flight did not end"
    assert seen["bop_hold"] > 0, "WarperBoP never held for its parts"
    assert seen["bop_moved"] > 0, "WarperBoP did not move during its hold"
    assert 110 <= seen["arriving"] <= 130, seen["arriving"]
    ds = seen["drift_set"]
    assert any(ds) and not ds[-1], \
        "Cripple's drift snapshot was not set then cleared"
    assert seen["bare"] is not None and seen["bare"][0] == seen["bare"][1], \
        seen["bare"]
    assert player_before == {player_start}, "the player moved before 500"
    assert len(player_after) > 1 and player_after != {player_start}, \
        "the player never moved after 500"
    assert seen.get("cap"), "Ramp never reached its effective max speed"
    assert seen.get("neg"), "Ramp never reversed"
    assert seen["neg"] > seen["cap"]
    assert seen["rad"] == [(0.0, 0.0)] * 2, seen["rad"]
    print("[motion_branches] Ramp at cap from tick %d, negative from %d"
          % (seen["cap"], seen["neg"]))
    assert 1 in posts and 0 in posts, posts     # ET_IN_SYSTEM_WARP both ways
    return state, events, queued.rows
