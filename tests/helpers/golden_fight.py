"""Recorded golden fights: the reference fire control is checked against
once its Python copy is gone (fire control native only, Task 1; spec
docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md §4.2,
decision M7, rulings R9 and R10; the proposal and its rows are
docs/reference/engine/native-combat/k1-retirement-map.md §5.5).

A scene is one of the former native-vs-Python differentials' fights, run
as ONE arm: "native" (``DAUNTLESS_NATIVE_COMBAT=1``), the only one since
fire control's Python copy was deleted (fire control native only, Task 6,
M3; scenes 1-5 were recorded from that Python arm, then checked native).
Every scene also asserts that nothing failed to fire for want of the
mirror and no row was dropped (k1_no_fire all zero: ruling R3). The scenes
are those fights themselves, imported, not copied:

* ``k1_ops_tpf1`` / ``k1_ops_tpf6``: the K1 differential's combat_stress op
  stream (tests/helpers/k1_fight.py ``_Scene``,
  ``OPS``), 1 and 6 ticks per frame; ``tpf6`` in the host's whole-tick
  order (``whole_ticks=True``, native motion phase 4, ruling 2);
* ``k1_gameloop_ai``: the same fight under GameLoop's real AI (its
  ``_loop_arm``, after a discarded warm-up arm, as the differential runs);
* ``k1_midwalk_handler``: its mid-walk handler scene (``handler_arm``);
* ``posed_fight``: tests/helpers/posed_fight.py's fight, headless;
* ``tractor_modes``: a tractor scene (``_tractor_modes`` below);
* ``sdk_dumb_fire``: the GameLoop fight with every AI's BasicAttack at
  Difficulty 0.0, so its FireScript dumb-fires torpedoes
  (``_sdk_dumb_fire``);
* ``host_frames`` / ``host_frames_tpf1``: the same GameLoop fight through
  real host frames (``host_loop._run_frame_sim``, headless;
  tests/helpers/host_frame_fight.py), a tick-count cycle with ops, and one
  tick per frame.

``run_scene(name, arm)`` returns one canonical tuple per tick, tick 0 first
(what happened before the first tick):

    (tick, state, events, queued, calls, presented, notes)

* ``state``: the scene's own per-tick record (weapon systems and leaves,
  ships' hull and shields, torpedoes; the posed fight's whole Recorder row),
  then every ship's pose (position, rotation, velocity), every tractor
  system's ``_mode``, ``_engage_state``, ``_was_firing``,
  ``_next_emitter_index`` and IsEngaged, every torpedo tube's
  ``_reload_timers`` and ``_last_fire_time``, and last every ship's
  subsystem-stage state (``stage``: batteries, available power, every
  subsystem's condition, the repair queue, the cloak, the shield charge
  accumulator; schema 4, phase 6 A1). Each row is ``[kind, label, ...]``;
  ``FIELDS[kind]`` names its fields. Floats by ``.hex()``; objects by ship
  name, ``ship/subsystem`` name, or numbered by first sight (never ``id()``
  or a mirror handle);
* ``events``: that tick's AddEvent rows, in order (all but the queued kinds);
* ``queued``: that tick's effect-queue kinds and bank sounds, in delivery
  order (tests/helpers/effect_split.py);
* ``calls``: that tick's ordered game-state calls (apply_hit, hits);
* ``presented``: that tick's presentation calls as a sorted multiset (no
  order inside a tick: ruling Q1, compare_calls);
* ``notes``: what a scene's own listeners saw (the tractor scene's).

Every value is JSON-normalised (tuples become lists), as the file holds it.

``check(name, rows)`` compares with
``tests/fixtures/golden_fights/<name>.<sys.platform>.json.gz`` (per-tick
SHA-256 digests plus the rows; R9: no file for this platform skips, naming
it) and names the first differing tick, row and field. ``record(name, rows,
reason)`` writes that file, only under ``UPDATE_COMBAT_GOLDEN=1``, and then
skips; its header names scene, arm, seed, ships, ticks, tpf, schema,
platform and the reason.

Determinism (R10): every RNG seeded (the scenes' own seeding), in-flight
objects cleared and fight audio isolated (the scenes do both),
``gc.collect()`` before every scene load, and event types from the dynamic
counter named by first sight (``_DYNAMIC_EVENT_TYPES``), so a scene gives
the same rows whatever ran before it in the process.
"""
import gc
import gzip
import hashlib
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Callable, NamedTuple, Optional

import pytest

import App

from engine import host_loop
from engine.appc import native_combat as nc
from engine.appc import sensor_contacts
from engine.appc import ship_motion
from engine.appc import weapon_subsystems as ws
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import k3_fight, posed_fight
from tests.helpers import k1_fight as k1d

SCHEMA = 4     # the file format; bump it on any change to it or to the rows
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "golden_fights"
UPDATE_ENV = "UPDATE_COMBAT_GOLDEN"
#: The arms a scene can run as: native fire control always (it has no
#: Python copy, M3; a re-record is labelled with the arm it ran).
#: "python_motion" is the native arm with the motion stage in Python
#: (DAUNTLESS_NATIVE_MOTION=0, native motion phase 2): the reference kernel
#: M is checked against, on the one Python recording.
ARMS = {"native": k1d.ON,
        "python_motion": {**k1d.ON, "DAUNTLESS_NATIVE_MOTION": "0"}}

#: The tick tuple's components, in order.
COMPONENTS = ("tick", "state", "events", "queued", "calls", "presented",
              "notes")

#: Field names of each state row kind, after its kind (index 0 = label).
FIELDS = {
    # tests/helpers/k1_fight._Scene.record
    "system": ("label", "IsFiring", "_fire_held", "_force_update",
               "_last_weapon_idx", "_last_group_fired", "_group_fire_mode",
               "_held_target", "_target_list", "_target_list_is_new"),
    "weapon": ("label", "IsFiring", "_target", "_fire_timer", "_depleted",
               "_charge_level", "_cooldown_remaining", "_num_ready",
               "_target_offset", "offset_first_holder",
               "offset_is_held_offset", "_beam_on_countdown",
               "asleep_not_at_rest"),
    "ship": ("name", "IsDead", "hull_condition", "shields"),
    "torpedo": ("label", "translate", "_velocity", "_target_ship",
                "_target_offset", "_damage",
                "_damage_radius_factor", "_ttl", "_age",
                "_guidance_lifetime", "_max_angular_accel", "_source_ship",
                "in_set", "_is_disruptor"),
    # tests/helpers/k3_fight.py weapon_rows (the posed fight)
    "psystem": ("label", "IsFiring", "_fire_held", "_force_update",
                "_last_weapon_idx", "_last_group_fired", "_held_target",
                "_target_list"),
    "pweapon": ("label", "IsFiring", "_target", "_fire_timer", "_depleted",
                "_dwell", "_beam_on_countdown", "_charge_level",
                "_cooldown_remaining", "_num_ready", "_target_offset",
                "offset_first_holder", "asleep_not_at_rest"),
    # added here, every scene
    "pose": ("name", "position", "rotation", "velocity"),
    "tractor": ("label", "_mode", "_engage_state", "_was_firing",
                "_next_emitter_index", "IsEngaged"),
    "tube": ("label", "_reload_timers", "_last_fire_time"),
    # the subsystem stage's own state (_stage_rows), every scene, last
    "stage": ("name", "_main_battery_power", "_backup_battery_power",
              "_available_power", "conditions", "repair_queue",
              "_cloak_state", "_transition_elapsed", "_charge_accum"),
    # tests/helpers/motion_fight.py (the motion_branches scene only)
    "motion": ("name", "_current_speed", "_current_angular_velocity",
               "_drift_velocity", "_speed_setpoint",
               "_target_angular_velocity_setpoint", "_angular_velocity",
               "_angular_space", "warp_flight", "_warp_consumed", "arriving",
               "impulse_fractions", "effective_motion"),
}

EVENT_FIELDS = ("type", "source", "destination", "tick", "payload")


class Scene(NamedTuple):
    name: str
    arm: str                # the arm its test runs
    seed: int
    ships: str              # DAUNTLESS_COMBAT_SHIPS (+ any scripted)
    ticks: int
    tpf: int
    run: Optional[Callable]  # run(mp, env, scene) -> _Take


class _Take(NamedTuple):
    """What a scene's run leaves: per-tick state rows (already kinded),
    and the whole-run logs."""
    state: list
    events: list
    queued: list
    calls: list
    notes: list


# ── Rows every scene adds: poses and tractors ────────────────────────────────

def _hexes(p):
    return [float(c).hex() for c in (p.x, p.y, p.z)]


def _pose_rows(ships):
    rows = []
    for s in ships:
        rows.append(["pose", s.GetName(), _hexes(s.GetWorldLocation()),
                     [float(c).hex() for c in s.GetWorldRotation().as_tuple()],
                     _hexes(s.GetVelocityTG())])
    return rows


def _engage_state(state):
    if state is None:
        return None
    if isinstance(state, dict):
        return sorted([k, None if v is None else _hexes(v)]
                      for k, v in state.items())
    return repr(state)


def _tractor_rows(ships, label):
    rows = []
    for s in ships:
        t = s.GetTractorBeamSystem()
        if t is None:
            continue
        d = t.__dict__
        rows.append(["tractor", label(t), d.get("_mode"),
                     _engage_state(d.get("_engage_state")),
                     d.get("_was_firing"), d.get("_next_emitter_index"),
                     t.IsEngaged()])
    return rows


def _hex_or(v):
    return v.hex() if isinstance(v, float) else v


def _tube_rows(ships, label):
    """Every torpedo tube's reload slots and last launch time (KRM §5.5:
    neither is in the scenes' own records; _num_ready alone would pass a
    reload-timer change that moves no launch)."""
    rows = []
    for s in ships:
        torps = s.GetTorpedoSystem()
        if torps is None:
            continue
        for i in range(torps.GetNumWeapons()):
            w = torps.GetWeapon(i)
            if not isinstance(w, ws.TorpedoTube):
                continue
            timers = getattr(w, "_reload_timers", None)
            rows.append(["tube", label(w),
                         None if timers is None else [_hex_or(float(t))
                                                      for t in timers],
                         _hex_or(getattr(w, "_last_fire_time", None))])
    return rows


def _stage_value(v):
    """A stage field as the file holds it: a float by .hex(), else as is
    (None for a field the object does not hold)."""
    return v.hex() if isinstance(v, float) else v


def _queued_label(ship_name, sub):
    """A repair-queue member by name. Anything else raises: no repr (and so
    no memory address) may ever reach a fixture."""
    from engine.appc.subsystems import ShipSubsystem
    if not isinstance(sub, ShipSubsystem):
        raise TypeError("golden stage row: %s's repair queue holds a %s, "
                        "not a subsystem" % (ship_name, type(sub).__name__))
    return "%s/%s" % (ship_name, sub.GetName())


def _stage_rows(ships):
    """The subsystem stage's own state, one row per ship (phase 6 A1, Task 2:
    the plan's ruling R2 makes the goldens the stage's oracle once the Python
    stage is gone): the power plant's main and backup battery and available
    power, every subsystem's condition (subsystems.iter_subsystems' order:
    the hull, then each top-level subsystem followed by its children), the
    repair queue by name in order, the cloak's state and transition elapsed,
    and the shield generator's charge accumulator. Read straight from each
    object's ``__dict__`` (no getter, no stub), so recording changes nothing
    it records. Appended after every other row of a tick, so the rows before
    it keep their indices."""
    from engine.appc import subsystems as subs
    rows = []
    for s in ships:
        name = s.GetName()

        def field(sub, attr):
            return None if sub is None else _stage_value(
                sub.__dict__.get(attr))

        power = s.GetPowerSubsystem()
        repair = s.GetRepairSubsystem()
        cloak = s.GetCloakingSubsystem()
        shields = s.GetShieldSubsystem()
        conditions = [["%s/%s" % (name, sub.GetName()),
                       _stage_value(sub.__dict__.get("_condition"))]
                      for sub in subs.iter_subsystems(s)]
        queue = None if repair is None else [
            _queued_label(name, q) for q in repair.__dict__.get("_queue", ())]
        rows.append(["stage", name,
                     field(power, "_main_battery_power"),
                     field(power, "_backup_battery_power"),
                     field(power, "_available_power"),
                     conditions, queue,
                     field(cloak, "_cloak_state"),
                     field(cloak, "_transition_elapsed"),
                     field(shields, "_charge_accum")])
    return rows


def _extras(scene_like, ships, label):
    scene_like.__dict__.setdefault("golden_extra", []).append(
        _pose_rows(ships) + _tractor_rows(ships, label)
        + _tube_rows(ships, label) + _stage_rows(ships))


def _patch_records(mp):
    """Both recorders append this tick's pose and tractor rows to
    `golden_extra` after their own record."""
    k1_record = k1d._Scene.record
    k3_record = k3_fight.Recorder.record

    def k1(scene, _orig=k1_record):
        _orig(scene)
        _extras(scene, scene.ships, scene.label)

    def k3(rec, _orig=k3_record):
        _orig(rec)
        _extras(rec, rec.ships, rec.label)

    mp.setattr(k1d._Scene, "record", k1)
    mp.setattr(k3_fight.Recorder, "record", k3)


def _k1_state(scene):
    """_Scene.log, each row given its kind (the record's layout: systems,
    weapons, ships, then torpedoes), plus the extras."""
    kinds = (["system"] * len(scene.systems)
             + ["weapon"] * len(scene.weapons)
             + ["ship"] * len(scene.ships))
    out = []
    for row, extra in zip(scene.log, scene.golden_extra):
        out.append([[kinds[i] if i < len(kinds) else "torpedo"] + list(r)
                    for i, r in enumerate(row)] + extra)
    return out


def _k1_take(scene, notes=()):
    assert len(scene.log) == len(scene.golden_extra)
    return _Take(_k1_state(scene), scene.events, scene.queued.rows,
                 scene.calls, list(notes))


# ── Scenes 1-3: the K1 differential's fights ─────────────────────────────────

def _check_native(scene):
    if scene.native:
        assert scene.audit == [], scene.audit
        assert scene.counts["k1_records"] > 0, scene.counts


def _k1_ops(mp, env, spec):
    scene = k1d._Scene(mp, env, ships=spec.ships)
    scene.run(spec.tpf, k1d.OPS, ticks=spec.ticks)
    _check_native(scene)
    return _k1_take(scene)


def _k1_ops_whole_ticks(mp, env, spec):
    """_k1_ops in the host's whole-tick order (native motion phase 4,
    ruling 2): each tick's subsystem update, weapons, combat and boundary
    together, the frame's ops at frame start."""
    scene = k1d._Scene(mp, env, ships=spec.ships)
    scene.run(spec.tpf, k1d.OPS, ticks=spec.ticks, whole_ticks=True)
    _check_native(scene)
    return _k1_take(scene)


# The GameLoop fight's warm-up arm (discarded): the first combat_stress
# fight in a process diverged from every later one in that harness
# (test_k1_matches_python_under_the_game_loop_ai's docstring), and a golden
# must not depend on what ran before it in the process.
WARM_UP_TICKS = k1d.LOOP_TICKS


def _k1_gameloop_ai(mp, env, spec):
    k1d._loop_arm(mp, k1d.OFF, ticks=WARM_UP_TICKS)
    gc.collect()
    scene = k1d._loop_arm(mp, env, ticks=spec.ticks)
    _check_native(scene)
    assert scene.starts > 0
    return _k1_take(scene)


def _k1_midwalk_handler(mp, env, spec):
    stats = {}
    scene = k1d.handler_arm(mp, env, spec.tpf, stats)
    _check_native(scene)
    assert stats[scene.native]["calls"] > 0, stats
    return _k1_take(scene)


# ── Scene 4: the posed fight ─────────────────────────────────────────────────

def _posed(mp, env, spec):
    # posed_fight tells its arms apart by ITS constants (`env is ON`).
    env = posed_fight.ON if env is k1d.ON else posed_fight.OFF
    scene = posed_fight.PosedFight(mp, env, spec.seed)
    try:
        scene.run(spec.tpf, ticks=spec.ticks)
    finally:
        scene.close()
    if scene.native:
        assert scene.audit == [], scene.audit
    rec = scene.rec
    n_sys, n_w = len(scene.systems), len(scene.weapons)
    n_extra = n_sys + n_w + 3 * len(scene.posed)
    state = []
    for row, extra in zip(rec.log, rec.golden_extra):
        base = len(row) - n_extra
        kinds = (["record"] * base + ["psystem"] * n_sys
                 + ["pweapon"] * n_w)
        state.append([[kinds[i] if i < len(kinds) else "posed"] + list(r)
                      for i, r in enumerate(row)] + extra)
    assert len(rec.log) == len(rec.golden_extra)
    return _Take(state, rec.events, rec.queued.rows, rec.calls, [])


# ── Scene 5: tractors ────────────────────────────────────────────────────────
#
# combat_stress with two AI ships and no AI run (host-style ticks, no
# GameLoop.tick, no op stream): only the player's tractor acts. The player
# (a Sovereign: four projectors, single fire) grabs Enemy-1 (a Warbird)
# ahead of it and steps through every mode, then loses and re-acquires the
# grip by range, by arc (hidden, then astern: an aft projector takes it), by
# its system being switched off and by power starvation (the beam's
# UpdateCharge drops it every starved tick, and the pump re-grips it in the
# same tick, so no STOPPED event: the drop is seen between the two). A
# broadcast handler on ET_TRACTOR_BEAM_STARTED_FIRING stops the beam once
# (E8M2's OD1 TractorHandler, E8M2.py:1010-1034), and the SDK's own
# ConditionFiringTractorBeam watches the ship (E1M2/E2M1's intercept AI).
# The force runs where GameLoop's motion stage sits (ship_motion.tick_tractors,
# after the timer bump and before the subsystem updates: Mark 2026-11-04),
# never the whole tick_all_ship_motion, which would start integrating the
# scene's ships too. Native only
# since tractors went native (fire control native only, Task 3): its
# STARTED / STOPPED are effect-queue entries (ruling R8), so the handler's
# StopFiring no longer nests a STOPPED inside the STARTED it handles.

TBS = ws.TractorBeamSystem
TRACTOR_RADIUS = 4.0            # both hulls: a standoff off the hull
TRACTOR_AHEAD = 25.0            # GU ahead of the player, inside 120
TRACTOR_FAR = 135.0             # past TRACTOR_MAX_RANGE_GU (120)
# The range pinned from both sides: held at 110 GU, lost at 125 (so a
# changed TRACTOR_MAX_RANGE_GU, 120 -> 100 or 130, moves the scene).
TRACTOR_RANGE_IN, TRACTOR_RANGE_OUT = 110.0, 125.0
# (tick, beat), run at the start of the tick.
TRACTOR_BEATS = (
    (10, "hold"), (40, "nudge"), (70, "tow"), (140, "pull"),
    (220, "push"), (300, "dock1"), (350, "dock2"), (400, "pull"),
    (410, "far"), (440, "near"), (450, "range_in"), (460, "range_out"),
    (470, "near"), (480, "out_of_arc"), (500, "astern"),
    (520, "face"), (560, "off"), (590, "on"), (720, "arm_handler"),
    (750, "start"), (800, "hold"), (840, "stop"),
)
TOW_TURN = (90, 130)            # the player yaws 0.5 deg a tick (tows)
STARVE = (620, 680)             # the main battery zeroed every tick
TRACTOR_PLACES = {"far": TRACTOR_FAR, "near": TRACTOR_AHEAD,
                  "range_in": TRACTOR_RANGE_IN,
                  "range_out": TRACTOR_RANGE_OUT}
MODE_OF = {"hold": TBS.TBS_HOLD, "tow": TBS.TBS_TOW, "pull": TBS.TBS_PULL,
           "push": TBS.TBS_PUSH, "dock1": TBS.TBS_DOCK_STAGE_1,
           "dock2": TBS.TBS_DOCK_STAGE_2}

_TRACTOR = {}


class _Status:
    """The CodeCondition a ConditionScript reports to: every SetStatus
    noted with its tick."""

    def __init__(self, notes, tick):
        self.notes = notes
        self.tick = tick

    def SetStatus(self, status):
        self.notes.append(["condition", self.tick(), int(status)])


def TractorStartedHandler(_dest, evt):
    """ET_TRACTOR_BEAM_STARTED_FIRING broadcast handler on the player: once
    armed, the first STARTED stops the player's tractor system (as E8M2's
    OD1 TractorHandler does)."""
    scene = _TRACTOR.get("scene")
    if scene is None:
        return
    ship = evt.GetDestination()
    _TRACTOR["notes"].append(["started", scene.tick,
                              scene.label(evt.GetSource()),
                              scene.label(ship)])
    if _TRACTOR["armed"] and not _TRACTOR["stopped"]:
        _TRACTOR["stopped"] = scene.tick
        ship.GetTractorBeamSystem().StopFiring()
        _TRACTOR["notes"].append(["handler_stop", scene.tick])


def _ahead(ship, dist):
    p, fwd = ship.GetWorldLocation(), ship.GetWorldRotation().GetCol(1)
    return (p.x + fwd.x * dist, p.y + fwd.y * dist, p.z + fwd.z * dist)


def _bears(tractors, ship, target):
    """Whether any projector's arc holds `target` (the walk's own test)."""
    for i in range(tractors.GetNumWeapons()):
        em = tractors.GetWeapon(i)
        if ws._emitter_in_arc(em, ship, ws._resolve_bank_aim_world(em,
                                                                    target)):
            return True
    return False


def _turn_out_of_arc(tractors, ship, target):
    """Turn `ship` (about Z, then about X) to the first orientation, in 5
    degree steps, where no projector bears on `target`."""
    base = ship.GetWorldRotation()
    for axis in ("z", "x"):
        for step in range(1, 72):
            m = TGMatrix3()
            a = math.radians(5.0 * step)
            (m.MakeZRotation if axis == "z" else m.MakeXRotation)(a)
            ship.SetMatrixRotation(base.MultMatrix(m))
            if not _bears(tractors, ship, target):
                return
    raise AssertionError("no orientation hides the target from every "
                         "projector")


def _tractor_beat(scene, beat, tractors, target):
    ship = scene.player
    if beat in MODE_OF:
        tractors.SetMode(MODE_OF[beat])
        if beat == "hold" and scene.tick < 100:
            tractors.StartFiring(target, None)
    elif beat == "nudge":
        p = target.GetWorldLocation()
        target.SetTranslateXYZ(p.x + 2.0, p.y, p.z + 1.0)
    elif beat in TRACTOR_PLACES:
        target.SetTranslateXYZ(*_ahead(ship, TRACTOR_PLACES[beat]))
    elif beat == "out_of_arc":
        _turn_out_of_arc(tractors, ship, target)
    elif beat == "face":
        k1d._Scene.face(ship, target)
    elif beat == "astern":
        # The target dead astern: the forward projector drops, an aft one
        # grips (the round robin moves on).
        k1d._Scene.face(ship, target)
        m = TGMatrix3()
        m.MakeZRotation(math.pi)
        ship.SetMatrixRotation(ship.GetWorldRotation().MultMatrix(m))
    elif beat == "off":
        tractors.TurnOff()
    elif beat == "on":
        tractors.TurnOn()
    elif beat == "arm_handler":
        _TRACTOR["armed"] = True
        tractors.StopFiring()
        tractors.StartFiring(target, None)
    elif beat == "start":
        tractors.StartFiring(target, None)
    elif beat == "stop":
        tractors.StopFiring()
    else:
        raise AssertionError(beat)


def _tractor_modes(mp, env, spec):
    from Conditions.ConditionFiringTractorBeam import (
        ConditionFiringTractorBeam)
    scene = k1d._Scene(mp, env, ships=spec.ships)
    ship = scene.player
    target = [s for s in scene.ships if s.GetName() == "Enemy-1"][0]
    for s in (ship, target):
        s.SetRadius(TRACTOR_RADIUS)
    target.SetTranslateXYZ(*_ahead(ship, TRACTOR_AHEAD))
    target.SetVelocity(TGPoint3(0.5, 0.0, 0.0))   # HOLD damps it
    tractors = ship.GetTractorBeamSystem()
    tractors.TurnOn()
    assert tractors.GetNumWeapons() == 4 and tractors._single_fire
    notes = []
    tick = lambda: scene.tick                     # noqa: E731
    _TRACTOR.clear()
    _TRACTOR.update(scene=scene, armed=False, stopped=0, notes=notes)
    handler = __name__ + ".TractorStartedHandler"
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_TRACTOR_BEAM_STARTED_FIRING, ship, handler, ship)
    cond = ConditionFiringTractorBeam(_Status(notes, tick), ship)
    beats = dict(TRACTOR_BEATS)
    seen = {"modes": set(), "drops": 0, "grips": 0, "starved": 0,
            "emitters": set(), "range": {}}
    power = ship.GetPowerSubsystem()
    try:
        while scene.tick < spec.ticks:
            scene.tick += 1
            t = scene.tick
            was = tractors.IsFiring()
            if t in beats:
                _tractor_beat(scene, beats[t], tractors, target)
            if TOW_TURN[0] <= t < TOW_TURN[1]:
                m = TGMatrix3()
                m.MakeZRotation(math.radians(0.5))
                ship.SetMatrixRotation(ship.GetWorldRotation().MultMatrix(m))
            if STARVE[0] <= t < STARVE[1]:
                power.SetMainBatteryPower(0.0)
            App.g_kTimerManager._time += TICK_DELTA
            ship_motion.tick_tractors(TICK_DELTA)
            game_loop._update_ship_subsystems()
            ships = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                if STARVE[0] <= t < STARVE[1]:
                    seen["starved"] += bool(was and not tractors.IsFiring())
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=scene.player,
                                          push_render_data=False)
            host_loop._combat_tick_boundary()
            scene.record()
            sensor_contacts.tick(scene.player,
                                 App.g_kUtopiaModule.GetGameTime())
            now = tractors.IsFiring()
            if now:
                seen["modes"].add(tractors.GetMode())
                seen["emitters"].update(
                    tractors.GetWeapon(i).GetName()
                    for i in range(tractors.GetNumWeapons())
                    if tractors.GetWeapon(i).IsFiring())
            if beats.get(t) in ("range_in", "range_out"):
                seen["range"][beats[t]] = now
            seen["drops"] += bool(was and not now)
            seen["grips"] += bool(now and not was)
    finally:
        App.g_kEventManager.RemoveBroadcastHandler(
            App.ET_TRACTOR_BEAM_STARTED_FIRING, ship, handler)
        for et, method in ((App.ET_TRACTOR_BEAM_STARTED_FIRING,
                            "StartedFiring"),
                           (App.ET_TRACTOR_BEAM_STOPPED_FIRING,
                            "StoppedFiring")):
            App.g_kEventManager.RemoveBroadcastHandler(
                et, cond.pEventHandler, method, ship)
        stopped = _TRACTOR.get("stopped")
        _TRACTOR.clear()
    # The scene is what it claims: every mode gripped, by a forward and an
    # aft projector; the grip dropped and came back (range, arc, off, the
    # handler, the stop) and starvation dropped it; held at RANGE_IN, lost at
    # RANGE_OUT; the handler stopped the beam once; the condition went true
    # and false.
    assert seen["modes"] == set(MODE_OF.values()), seen
    assert stopped == _beat_tick("arm_handler"), stopped
    assert seen["drops"] >= 6 and seen["grips"] >= 6, seen
    assert seen["range"] == {"range_in": 1, "range_out": 0}, seen
    assert seen["starved"] > 0, seen
    assert {n.split()[0] for n in seen["emitters"]} == {"Aft", "Forward"}, seen
    statuses = {n[2] for n in notes if n[0] == "condition"}
    assert statuses == {0, 1}, notes
    if scene.native:
        nc.audit_mirror()
        assert list(nc.audit_failures()) == []
    return _k1_take(scene, notes)


def _beat_tick(beat):
    return next(t for t, b in TRACTOR_BEATS if b == beat)


# ── Scene 6: SDK dumb fire ───────────────────────────────────────────────────

DUMB_DIFFICULTY = 0.0           # BasicAttack's floor: DumbFireTorps on


def _sdk_dumb_fire(mp, env, spec):
    """The GameLoop fight (k1d._loop_arm) with every AI's BasicAttack at
    Difficulty 0.0 (AI/Compound/BasicAttack.py: the 0.0 row turns on
    InaccurateTorps and DumbFireTorps), so AI/Preprocessors.py's
    FireSystemAtTarget calls pTube.FireDumb(0, 1) for every tube within
    90 degrees of the target."""
    from engine.dev_missions import combat_stress
    mp.setattr(combat_stress, "_AI_DIFFICULTY", DUMB_DIFFICULTY)
    k1d._loop_arm(mp, k1d.OFF, ticks=WARM_UP_TICKS)
    gc.collect()
    # The scene is what it claims: the SDK's FireDumb ran (past its warp-in
    # hold) and launched, counted by the kernel's dumb-fire sessions (fire
    # control native only, M8.1: the SDK's FireDumb is one).
    nc._h.combat_k1_reset_counts()
    scene = k1d._loop_arm(mp, env, ticks=spec.ticks)
    assert scene.native
    assert scene.audit == [], scene.audit
    logged = scene.counts["k1_logged"]
    assert logged["sdk_dumb_fire"] > 0, "the SDK never dumb-fired a tube"
    assert logged["dumb_launch"] > 0, logged
    assert not any(scene.counts["k1_launch_reasons"].values()), \
        scene.counts["k1_launch_reasons"]
    launched = [e for e in scene.queued.rows
                if e[0] == App.ET_TORPEDO_FIRED]
    assert launched, "no torpedo launched"
    return _k1_take(scene)


# ── Scene 7: every motion branch ─────────────────────────────────────────────

def _motion_branches(mp, env, spec):
    """tests/helpers/motion_fight.py: the scripted cast, recorded from the
    Python motion (native motion phase 2, Task 1). Its rows are `pose` then
    `motion`; no weapon rows."""
    from tests.helpers import motion_fight
    state, events, queued = motion_fight.run(mp, env, spec.ticks)
    return _Take(state, events, queued, [], [])


# ── Scenes 8-9: real host frames ────────────────────────────────────────────

def _host_frames(mp, env, spec):
    """tests/helpers/host_frame_fight.py: the GameLoop fight through
    host_loop._run_frame_sim, FRAME_TICKS ticks per frame, with ops (native
    motion phase 4: recorded in the batched order in Task 2, re-recorded in
    whole ticks for ruling 2 in Task 3)."""
    from tests.helpers import host_frame_fight as hff
    return hff.run(mp, env, spec, hff.FRAME_TICKS, 300, hff.HOST_FRAME_OPS)


def _host_frames_tpf1(mp, env, spec):
    """The same, one tick per frame and no ops."""
    from tests.helpers import host_frame_fight as hff
    return hff.run(mp, env, spec, (1,), 300, ())


# ── The scene table ──────────────────────────────────────────────────────────

SCENES = {s.name: s for s in (
    Scene("k1_ops_tpf1", "native", k1d.SEED, "8", k1d.TICKS, 1, _k1_ops),
    Scene("k1_ops_tpf6", "native", k1d.SEED, "8", k1d.TICKS, 6,
          _k1_ops_whole_ticks),
    Scene("k1_gameloop_ai", "native", k1d.SEED, "8", k1d.LOOP_TICKS, 1,
          _k1_gameloop_ai),
    Scene("k1_midwalk_handler", "native", k1d.SEED, "8", k1d.HANDLER_TICKS,
          1, _k1_midwalk_handler),
    Scene("posed_fight", "native", 20261105, "8+Enemy-B", posed_fight.TICKS,
          1, _posed),
    Scene("tractor_modes", "native", 0, "2", 870, 1, _tractor_modes),
    Scene("sdk_dumb_fire", "native", k1d.SEED, "8", 900, 1, _sdk_dumb_fire),
    Scene("motion_branches", "native", 20261110, "2", 1250, 1,
          _motion_branches),
    Scene("host_frames", "native", k1d.SEED, "8", 720, 0, _host_frames),
    Scene("host_frames_tpf1", "native", k1d.SEED, "8", 300, 1,
          _host_frames_tpf1),
)}

_LAST_ARM = {}

# Event types the SDK takes from App's dynamic counter (App.py
# Game_GetNextEventType, from 1200 up; every static ET_* constant is below
# 1200 or at 0x800000 and up). The engine restarts the counter on every
# mission load, while SDK modules keep what they took for the process: at
# import (AI/PlainAI/Warp.py:22-23, Conditions/ConditionPulseReady.py:17,
# ...) or on first use (LoadBridge.py:221-223,
# Conditions/ConditionPowerBelow.py:18-20). So the NUMBER a scene sees
# depends on what ran before it in the process (measured: the GameLoop
# fight's power-fraction event was 1214 after another scene, 1215 as the
# process's first). The rows name them by first sight in the scene instead
# ("dyn#0", ...), as objects are: which events share a type is kept.
_DYNAMIC_EVENT_TYPES = range(1200, 0x10000)


# ── Canonical rows ───────────────────────────────────────────────────────────

def _norm(v):
    return json.loads(json.dumps(v))


def _by_tick(rows, at, n):
    out = [[] for _ in range(n + 1)]
    for r in rows:
        t = r[at]
        assert 0 <= t <= n, ("row outside the scene's ticks", r)
        out[t].append(r)
    return out


def _canonical(take):
    n = len(take.state)
    ordered, shown = k3_fight.split_calls(take.calls)
    events = _by_tick(take.events, 3, n)
    queued = _by_tick(take.queued, 3, n)
    calls = _by_tick(ordered, 1, n)
    notes = _by_tick(take.notes, 1, n)
    dynamic = {}

    def typed(rows):
        out = []
        for r in rows:
            et = r[0]
            if isinstance(et, int) and et in _DYNAMIC_EVENT_TYPES:
                name = dynamic.setdefault(et, "dyn#%d" % len(dynamic))
                r = (name,) + tuple(r[1:])
            out.append(r)
        return out

    rows = []
    for t in range(n + 1):
        rows.append((t, [] if t == 0 else take.state[t - 1],
                     typed(events[t]), typed(queued[t]), calls[t],
                     shown.get(t, []), notes[t]))
    return [tuple(r) for r in _norm(rows)]


def run_scene(name: str, arm: str) -> list:
    """Run scene `name` as `arm` ("native": ARMS); its canonical per-tick
    rows (module docstring). Asserts the scene's run had no no-fire and
    dropped no row (k1_no_fire all zero, "dropped" included: R3)."""
    spec = SCENES[name]
    if arm not in ARMS:
        raise ValueError("golden arm %r: fire control is native only (M3), "
                         "the arms are %r" % (arm, sorted(ARMS)))
    env = ARMS[arm]
    gc.collect()
    with pytest.MonkeyPatch.context() as mp:
        # The motion switch is the arm's, never the caller's shell's.
        mp.delenv("DAUNTLESS_NATIVE_MOTION", raising=False)
        _patch_records(mp)
        random.seed(spec.seed)
        take = spec.run(mp, env, spec)
        no_fire = nc.counts()["k1_no_fire"]
    assert not any(no_fire.values()), (name, no_fire)
    _LAST_ARM[name] = arm
    return _canonical(take)


# ── The file ─────────────────────────────────────────────────────────────────

def path(name):
    return FIXTURES / ("%s.%s.json.gz" % (name, sys.platform))


def _digest(row):
    return hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(name):
    with gzip.open(path(name), "rt", encoding="utf-8") as f:
        return json.load(f)


# The file holds each tick's state as its changes since the tick before:
# the full rows were ~17 MB gzipped for the seven scenes (gzip's window is
# smaller than a tick). A row equal to the row at its index is left out; a
# row whose (kind, label) was in the tick before is stored as the fields
# that differ from that row ("from": its index there; torpedoes shift
# index as others die); anything else whole.


def _key(row):
    return json.dumps(row[:2])


def _encode(rows):
    out, prev = [], []
    for r in rows:
        state = r[1]
        where = {_key(row): j for j, row in enumerate(prev)}
        changed = []
        for i, row in enumerate(state):
            if i < len(prev) and prev[i] == row:
                continue
            j = where.get(_key(row))
            if j is not None and len(prev[j]) == len(row):
                changed.append([i, {"from": j, "f": [
                    [k, v] for k, (u, v) in enumerate(zip(prev[j], row))
                    if u != v]}])
            else:
                changed.append([i, row])
        out.append([r[0], {"n": len(state), "changed": changed}] + r[2:])
        prev = state
    return out


def _decode(ticks):
    out, prev = [], []
    for r in ticks:
        enc = r[1]
        state = prev[:enc["n"]] + [None] * max(0, enc["n"] - len(prev))
        for i, row in enc["changed"]:
            if isinstance(row, dict):
                delta, row = row, list(prev[row["from"]])
                for k, v in delta["f"]:
                    row[k] = v
            state[i] = row
        out.append([r[0], state] + r[2:])
        prev = state
    return out


def header(name):
    return _load(name)["header"]


def record(name, rows, reason):
    """Write scene `name`'s golden for this platform, only under
    UPDATE_COMBAT_GOLDEN=1 (then skip). A re-record must say why."""
    if os.environ.get(UPDATE_ENV) != "1":
        return
    if not reason:
        pytest.fail("a golden re-record needs a reason "
                    "(COMBAT_GOLDEN_REASON)")
    spec = SCENES[name]
    rows = [list(r) for r in rows]
    data = {"header": {"scene": name, "arm": _LAST_ARM.get(name, spec.arm),
                       "seed": spec.seed, "ships": spec.ships,
                       "ticks": len(rows) - 1, "tpf": spec.tpf,
                       "schema": SCHEMA, "platform": sys.platform,
                       "reason": reason},
            "digests": [_digest(r) for r in rows],
            "ticks": _encode(rows)}
    out = path(name)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":")).encode()
    with open(out, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
            gz.write(raw)
    pytest.skip("golden re-recorded: %s (%d ticks, %d bytes)"
                % (out, len(rows) - 1, out.stat().st_size))


def _first_difference(want, got, at=()):
    if isinstance(want, list) and isinstance(got, list):
        for i, (a, b) in enumerate(zip(want, got)):
            d = _first_difference(a, b, at + (i,))
            if d is not None:
                return d
        if len(want) != len(got):
            return at + ("length",), len(want), len(got)
        return None
    if type(want) is not type(got) or want != got:
        return at, want, got
    return None


def _describe(t, at, want_row):
    """`at`, a path into tick `t`'s tuple `want_row`, in words: the
    component, a state row's kind and label and its field's name."""
    words = ["tick %d" % t]
    if not at:
        return words[0]
    comp = COMPONENTS[at[0]]
    words.append(comp)
    rest = list(at[1:])
    if comp == "state" and rest and isinstance(rest[0], int):
        row = want_row[1][rest[0]]
        words.append("row %d (%s %r)" % (rest[0], row[0], row[1]))
        rest = rest[1:]
        if rest and isinstance(rest[0], int):
            i = rest[0] - 1
            names = FIELDS.get(row[0], ())
            words.append("field %d %s" % (
                i, names[i] if 0 <= i < len(names) else "?"))
            rest = rest[1:]
    elif rest and isinstance(rest[0], int):
        words.append("[%d]" % rest[0])
        rest = rest[1:]
        if comp in ("events", "queued") and rest and isinstance(rest[0], int):
            words.append("field %s" % EVENT_FIELDS[rest[0]])
            rest = rest[1:]
    if rest:
        words.append("at %r" % (rest,))
    return ", ".join(words)


def _drop_baked_offset(ticks):
    """Schema 2 -> 3: torpedo rows lost their `_baked_offset` field (fire
    control native only, M5: a picked spot is a plain body point, there is
    no launch-time bake). It sat after `_target_offset`, row index 6; every
    other field of the recorded row is compared as it was recorded."""
    out = []
    for r in ticks:
        state = [row[:6] + row[7:] if row and row[0] == "torpedo" else row
                 for row in r[1]]
        out.append([r[0], state] + r[2:])
    return out


#: Readers of older schemas: each maps a file's decoded ticks to this one's.
#: The stored digests stay those of the rows as recorded.
_UPGRADES = {2: _drop_baked_offset}


def check(name, rows):
    """Compare `rows` (run_scene's) with this platform's golden of `name`;
    fail naming the first differing tick and field. No golden for this
    platform skips (R9)."""
    p = path(name)
    if not p.exists():
        pytest.skip("no golden for %s on %s: %s is missing (goldens are "
                    "per platform, ruling R9; record one with %s=1)"
                    % (name, sys.platform, p, UPDATE_ENV))
    data = _load(name)
    h = data["header"]
    assert h["schema"] == SCHEMA or h["schema"] in _UPGRADES, (
        "golden schema", h, SCHEMA)
    stored = _decode(data["ticks"])
    want = (stored if h["schema"] == SCHEMA
            else _UPGRADES[h["schema"]](stored))
    got = [list(r) for r in _norm([list(r) for r in rows])]
    for t, (a, b) in enumerate(zip(want, got)):
        # The rows themselves are compared (a digest alone would pass a
        # perturbed row), and the stored digest must still be its row's.
        d = _first_difference(a, b)
        if d is None:
            if data["digests"][t] != _digest(stored[t]):
                raise AssertionError("%s tick %d: the golden's digest does "
                                     "not match its own row" % (name, t))
            continue
        at, w, g = d
        raise AssertionError(
            "%s: golden differs at %s\n recorded %r\n got      %r\n"
            "(golden %s, recorded from the %s arm: %s)"
            % (name, _describe(t, at, a), w, g, p.name, h["arm"],
               h["reason"]))
    assert len(want) == len(got), (
        "%s: golden has %d ticks, the run %d" % (name, len(want) - 1,
                                                 len(got) - 1))
