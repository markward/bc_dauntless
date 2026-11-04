"""The K1 fights: combat_stress scenes with a seeded op stream, driven the
host's way, recorded tick by tick (fire control native only, Task 6: the
former K1 differential, tests/integration/test_native_k1_differential.py,
whose Python reference arm is deleted with fire control's Python copy, M3).

They are the golden fights' scenes 1-3 (tests/helpers/golden_fight.py:
k1_ops_tpf1/tpf6, k1_gameloop_ai, k1_midwalk_handler) and the other kernels'
differentials' (K0, the off-lock stress, the presentation RNG), which keep
both arms of THEIR switch with fire control native in both (M9).

A fresh load of combat_stress gets a seeded stream of operations, all
through public calls: StartFiring / StopFiring / re-target without a stop,
SetSingleFire, SetFiringChainMode, weapon systems TurnOff / TurnOn,
SetCondition on banks and tubes, SetPowerSetting on emitters, a torpedo
magazine emptied and refilled, ships nudged and turned, and the player's
Manual Aim switched on and off with a locked subsystem. After every tick
each weapon system's and each bank's state (type-tagged, floats by .hex(),
the `_target_offset` values and which bank's offset is the same OBJECT as
which), every ship's hull condition and six shield faces, every torpedo in
flight, and the whole event log (every AddEvent: type, source, destination,
tick, order, and a weapon hit's payload -- damage, hit point and normal by
.hex(); torpedoes and bolts numbered by first sight) are recorded, and so
is the ordered log of every apply_hit, and every hit VFX spawn and shield
hit per tick (compare_calls). Each scene starts with nothing in flight
(headless_mission.clear_in_flight).

Driven the host's way, without GameLoop.tick (AI draws on the unseeded
module ``random``), except _loop_arm, which runs GameLoop.tick on purpose.
"""
import contextlib
import math
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import articulation
from engine.appc import combat
from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import part_pose
from engine.appc import passive_state
from engine.appc import projectiles
from engine.appc import sensor_contacts
from engine.appc import weapon_subsystems as ws
from engine.appc.actions import TGObjPtrEvent
from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core import step_memo
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, effect_split, headless_mission
from tests.helpers.fight_audio import isolate_fight_audio
from tests.helpers.k3_fight import (compare_calls, presented,
                                   spy_presentation)

TICKS = 600
SEED = 20261031

#: The other kernels' switch (fire control is native in both: M9): OFF
#: runs K0, K2, K3, K4 and damage in Python, ON natively.
OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}

# Weapon kinds (native_combat._weapon_kind): systems, then their leaves.
PHASERS, PULSES, TORPEDOES = 1, 2, 4
BANK, CANNON, TUBE = 5, 6, 8


def _groups(ship):
    return [g for g in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                        ship.GetTractorBeamSystem(), ship.GetTorpedoSystem())
            if g is not None]


def _t(v):
    """A value with its type; floats by .hex()."""
    if isinstance(v, float):
        return ("float", v.hex())
    return (type(v).__name__, v)


def _hexes(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def _vec(p):
    """A point-like value by .hex(): a TGPoint3, a 3-sequence, or None."""
    if p is None:
        return None
    if isinstance(p, TGPoint3):
        return _hexes(p)
    if isinstance(p, (tuple, list)):
        return tuple(float(c).hex() for c in p)
    return repr(p)


def _seed_every_rng(seed):
    """Every RNG a fight draws on, to one state: the module `random`, the
    SDK's App.g_kSystemWrapper.GetRandomNumber (unseeded by default), the
    engine's two process-lifetime streams (avoidance, random unit vectors)
    and the presentation generator."""
    from engine.appc import collision_avoidance
    from engine.appc import presentation_rng
    from engine.appc.math import reset_random_unit_vector_rng
    random.seed(seed)
    App.g_kSystemWrapper.SetRandomSeed(seed)
    collision_avoidance._rng.seed(collision_avoidance._AVOID_RNG_SEED)
    reset_random_unit_vector_rng()
    presentation_rng.reset()


class _Scene:
    """combat_stress, loaded fresh, with the native switch set after the
    load; the op stream, the per-tick record and the full event log."""

    # Record the RAW passive asleep flag of each weapon (only meaningful
    # with K0 stood down: K0 puts no weapon to sleep, so with it running the
    # flag differs by design and the record keeps "asleep while NOT at
    # rest" instead).
    raw_asleep = False

    def __init__(self, mp, env, ships="8"):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
        # Radii come from the models, as live: a leaked headless flag from
        # another test gives every ship a nominal radius and changes the fight.
        mp.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", ships)
        nc.reset()
        App.g_kTimerManager._time = 0.0
        _seed_every_rng(0)      # the load's AI draws (initial staggers) too
        headless_mission.clear_in_flight()      # the other arm's torpedoes
        # Hit sounds draw on the SDK RNG: decided by the fight, never by
        # wall-clock speed or the fight before (tests/helpers/fight_audio).
        isolate_fight_audio(mp)
        headless_mission.load("engine.dev_missions.combat_stress")
        host_loop._reset_sensor_state()
        self.player = App.Game_GetCurrentPlayer()
        self.ships = list(iter_ships())
        assert len(self.ships) == int(ships) + 1
        # Everyone starts facing a foe, so forward tubes and arcs bear (on
        # the ring nobody does: the player's tubes never would).
        face = random.Random(SEED + 2)
        for ship in self.ships:
            self.face(ship, self._enemy_of(face, ship))
        step_memo.forget()
        nc.configure(env)
        assert nc.enabled() is (env is ON)
        assert nc.fire_control_native()
        self.native = env is ON
        self.firing = [g for s in self.ships for g in _groups(s)
                       if g is not s.GetTractorBeamSystem()]
        self.systems = [g for s in self.ships for g in _groups(s)]
        self.weapons = [g.GetWeapon(i) for g in self.systems
                        for i in range(g.GetNumWeapons())]
        self.emitters = [w for w in self.weapons
                         if isinstance(w, (ws.PhaserBank, ws.PulseWeapon))]
        self.torpedo_systems = [g for g in self.firing
                                if isinstance(g, ws.TorpedoSystem)]
        self.pulse_systems = [g for g in self.firing
                              if isinstance(g, ws.PulseWeaponSystem)]
        self.labels = {id(s): s.GetName() for s in self.ships}
        for g in self.systems:
            self.labels[id(g)] = "%s/%s" % (g.GetParentShip().GetName(),
                                            g.GetName())
        for w in self.weapons:
            self.labels[id(w)] = "%s/%s" % (
                w.GetParentSubsystem().GetParentShip().GetName(), w.GetName())
        self.held = []
        self.torps = []         # torpedoes and bolts, in creation order
        self.tick = 0
        self.log = []
        self.events = []
        self.calls = []
        self.lists = {}         # id(system) -> its last recorded _target_list
        self.manual = []        # the manual offsets set, as hexes
        # The queued kinds (weapon events, bank sounds) leave the ordered
        # event log for a per-tick ordered list of their own: with native
        # on, the tick's scope delivers them at the boundary
        # (tests/helpers/effect_split.py).
        self.queued = effect_split.Queued(mp, self.label, lambda: self.tick)
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            row = (evt.GetEventType(), self.label(evt.GetSource()),
                   self.label(evt.GetDestination()), self.tick,
                   self.payload(evt))
            if self.queued.takes(evt):
                self.queued.rows.append(row)
            else:
                self.events.append(row)
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

        # The presentation (round trips Task 5): every apply_hit (its
        # target and damage: the event log holds the rest), then every hit
        # VFX spawn and shield hit, in one log (compare_calls: the hits in
        # order, the presentation per tick as a multiset).
        apply_hit = combat.apply_hit

        def hit_spy(target, damage, point, *args, _orig=apply_hit, **kw):
            self.calls.append(("apply_hit", self.tick, self.label(target),
                               _t(damage), _vec(point)))
            return _orig(target, damage, point, *args, **kw)

        mp.setattr(combat, "apply_hit", hit_spy)
        spy_presentation(mp, self.calls, lambda: self.tick, self.label)

        # Evidence that K1 itself walked, per kind: the walked systems whose
        # offset object Python made (a logged write naming the walk's
        # offset: _K1Walk.materialise). A walk that stamped no offset is not
        # seen here (counted in k1_logged.walk_start).
        self.walked = {}
        self.walked_names = set()
        materialise = nc._K1Walk.materialise

        def counting_materialise(walk, n, h, _orig=materialise):
            first = walk.walk != n
            offset = _orig(walk, n, h)
            if first:
                system = walk.walked
                k = nc._weapon_kind(system)
                self.walked[k] = self.walked.get(k, 0) + 1
                self.walked_names.add(self.label(system))
            return offset

        mp.setattr(nc._K1Walk, "materialise", counting_materialise)

    def label(self, obj):
        """A ship's or weapon's name; any other object (a torpedo, a pulse
        bolt, an event's sink) is numbered by first sight, so two arms that
        create them in the same order label them alike. The object is held,
        so its id is never reused."""
        if obj is None:
            return None
        name = self.labels.get(id(obj))
        if name is None and isinstance(obj, projectiles.Torpedo):
            # Torpedoes (and bolts) in their own sequence: with native on a
            # launch's torpedo is made at the tick boundary (launch
            # deferral, ruling L3), after objects the rest of the step
            # numbers, but in the same order as the reference makes them.
            name = self.labels[id(obj)] = "Torpedo@%d" % len(self.torps)
            self.torps.append(obj)
            return name
        if name is None:
            name = self.labels[id(obj)] = "%s#%d" % (type(obj).__name__,
                                                     len(self.held))
            self.held.append(obj)
        return name

    def torp_row(self, t):
        g = lambda name: getattr(t, name, None)  # noqa: E731
        return (self.label(t), _vec(t.GetTranslate()), _vec(t._velocity),
                self.label(g("_target_ship")), _vec(g("_target_offset")),
                _t(g("_damage")), _t(g("_damage_radius_factor")),
                _t(g("_ttl")), _t(g("_age")), _t(g("_guidance_lifetime")),
                _t(g("_max_angular_accel")), self.label(t._source_ship),
                t.GetContainingSet() is not None, _t(g("_is_disruptor")))

    def payload(self, evt):
        """A weapon hit's payload: damage, hit point and normal by .hex(),
        hull hit, weapon type, the struck subsystem and the target.  Any
        other event's payload is its object pointer (ET_WEAPON_FIRED's
        target)."""
        if not isinstance(evt, WeaponHitEvent):
            return (self.label(evt.GetObjPtr())
                    if isinstance(evt, TGObjPtrEvent) else None)
        return (_t(evt.GetDamage()), _vec(evt.GetHitPoint()),
                _vec(evt.GetNormal()), _t(evt.GetRadius()),
                _t(evt.IsHullHit()), _t(evt.GetWeaponType()),
                self.label(evt.GetSubsystem()), self.label(evt.GetTarget()))

    # ── Ops ──────────────────────────────────────────────────────────────────

    def _foes(self, ship):
        side = ship.GetName().startswith("Enemy")
        return [s for s in self.ships
                if s.GetName().startswith("Enemy") != side and not s.IsDead()]

    def _enemy_of(self, rng, ship):
        foes = self._foes(ship)
        return rng.choice(foes) if foes else None

    @staticmethod
    def face(ship, target):
        """Turn `ship` about Z so its nose (body +Y) points at `target`."""
        a, b = ship.GetTranslate(), target.GetTranslate()
        m = TGMatrix3()
        m.MakeZRotation(math.atan2(-(b.x - a.x), b.y - a.y))
        ship.SetMatrixRotation(m)

    def _offset(self, rng):
        if rng.random() < 0.5:
            return None
        return TGPoint3(rng.uniform(-2.0, 2.0), rng.uniform(-3.0, 3.0),
                        rng.uniform(-1.0, 1.0))

    def _lock(self, rng, target):
        subs = [s for s in (target.GetPowerSubsystem(),
                            target.GetSensorSubsystem(),
                            target.GetImpulseEngineSubsystem(),
                            target.GetShields())
                if s is not None]
        return rng.choice(subs) if subs else None

    def manual_on(self, rng):
        """The player picks a target, locks a subsystem, Manual Aim picks a
        point on its hull, and the player fires everything at it."""
        target = self._enemy_of(rng, self.player)
        if target is None:
            return
        self.player.SetTarget(target)
        self.player.SetTargetSubsystem(self._lock(rng, target))
        self.manual_move(rng)
        for g in self.firing:
            if g.GetParentShip() is self.player:
                g.StartFiring(self.player.GetTarget(),
                              self.player.GetTargetOffsetTG())

    def manual_move(self, rng):
        p = TGPoint3(rng.uniform(-1.5, 1.5), rng.uniform(-4.0, 4.0),
                     rng.uniform(-0.8, 0.8))
        self.player.set_manual_target_offset(p)
        self.manual.append(_hexes(p))

    def op(self, rng, ops):
        kind = rng.choice(ops)
        if kind == "fire":
            group = rng.choice(self.firing)
            group.StartFiring(self._enemy_of(rng, group.GetParentShip()),
                              self._offset(rng))
        elif kind == "fire_pulse" or kind == "player_torps":
            # Cannons and tubes bear only in narrow arcs: half the time the
            # ship turns to its target first.
            if kind == "fire_pulse":
                group = rng.choice(self.pulse_systems)
            else:
                group = self.player.GetTorpedoSystem()
            target = self._enemy_of(rng, group.GetParentShip())
            if target is not None and rng.random() < 0.5:
                self.face(group.GetParentShip(), target)
            group.StartFiring(target, self._offset(rng))
        elif kind == "reload":
            # Tubes reload in 40 s; load a system's tubes by hand so they
            # fire (and fail) more than once in a short fight.
            torps = rng.choice(self.torpedo_systems)
            for i in range(torps.GetNumWeapons()):
                torps.GetWeapon(i).SetNumReady(1)
        elif kind == "retarget":
            held = [g for g in self.firing if g._fire_held]
            if held:
                group = rng.choice(held)
                group.StartFiring(self._enemy_of(rng, group.GetParentShip()),
                                  self._offset(rng))
        elif kind == "stop":
            rng.choice(self.firing).StopFiring()
        elif kind == "single":
            rng.choice(self.firing).SetSingleFire(rng.choice((0, 1)))
        elif kind == "chain":
            g = rng.choice(self.firing)
            g.SetFiringChainMode(rng.randint(0, 2))
        elif kind == "off":
            rng.choice(self.firing).TurnOff()
        elif kind == "on":
            rng.choice(self.firing).TurnOn()
        elif kind == "condition":
            w = rng.choice(self.weapons)
            w.SetCondition(w.GetMaxCondition()
                           * rng.choice((0.0, 0.2, 0.5, 0.8, 1.0, 1.0)))
        elif kind == "power":
            rng.choice(self.emitters).SetPowerSetting(rng.randint(0, 2))
        elif kind == "drain":
            # A bank near empty: a held beam runs dry (the depleted latch)
            # and must climb back before it relights (Review Focus 3).
            w = rng.choice(self.emitters)
            w.SetChargeLevel(w.GetMaxCharge()
                             * rng.choice((0.0, 0.02, 0.05, 0.1, 0.3)))
        elif kind == "ammo_out":
            ammo = rng.choice(self.torpedo_systems).GetCurrentAmmoType()
            if ammo is not None:
                ammo.SetAvailable(0)
        elif kind == "ammo_fill":
            ammo = rng.choice(self.torpedo_systems).GetCurrentAmmoType()
            if ammo is not None:
                ammo.SetAvailable(ammo.GetMaxTorpedoes())
        elif kind == "move":
            ship = rng.choice(self.ships)
            p = ship.GetTranslate()
            ship.SetTranslateXYZ(p.x + rng.uniform(-3.0, 3.0),
                                 p.y + rng.uniform(-3.0, 3.0),
                                 p.z + rng.uniform(-1.0, 1.0))
            ship.SetVelocity(TGPoint3(rng.uniform(-5.0, 5.0),
                                      rng.uniform(-5.0, 5.0), 0.0))
        elif kind == "face":
            ship = rng.choice(self.ships)
            target = self._enemy_of(rng, ship)
            if target is not None:
                self.face(ship, target)
        elif kind == "turn":
            ship = rng.choice(self.ships)
            m = TGMatrix3()
            m.MakeZRotation(rng.uniform(-3.14159, 3.14159))
            ship.SetMatrixRotation(m)
        elif kind == "manual_on":
            self.manual_on(rng)
        elif kind == "manual_move":
            if self.player.is_using_target_offset():
                self.manual_move(rng)
        elif kind == "manual_off":
            self.player.UseTargetOffsetTG(0)
        else:
            raise AssertionError(kind)

    # ── Record ───────────────────────────────────────────────────────────────

    def record(self):
        row = []
        for g in self.systems:
            d = g.__dict__
            # Whether `_target_list` is a NEW object since the last record:
            # every walk's prune writes a new list, unchanged or not (K1
            # logs that write on every walk since round trips Task 1). The
            # previous object is held, so its id is never reused.
            lst = d.get("_target_list")
            new = lst is not self.lists.get(id(g))
            self.lists[id(g)] = lst
            row.append((self.label(g), _t(g.IsFiring()),
                        _t(d.get("_fire_held")), _t(d.get("_force_update")),
                        _t(d.get("_last_weapon_idx")),
                        _t(d.get("_last_group_fired")),
                        _t(d.get("_group_fire_mode")),
                        self.label(d.get("_held_target")),
                        [self.label(t) for t in d.get("_target_list", ())],
                        new))
        first = {}      # id(offset object) -> the first bank holding it
        for i, w in enumerate(self.weapons):
            d = w.__dict__
            energy = isinstance(w, ws._EnergyWeaponFireMixin)
            tube = isinstance(w, ws.TorpedoTube)
            off = d.get("_target_offset")
            if off is not None:
                first.setdefault(id(off), i)
            row.append((
                self.label(w), _t(w.IsFiring()),
                self.label(d.get("_target")),
                _t(d.get("_fire_timer", 0.0)), _t(d.get("_depleted")),
                w.GetChargeLevel().hex() if energy else None,
                _t(d.get("_cooldown_remaining")),
                _t(w.GetNumReady()) if tube else None,
                None if off is None else (
                    _hexes(off) if isinstance(off, TGPoint3) else repr(off)),
                # Which bank's offset is the same OBJECT (ruling P5).
                None if off is None else first[id(off)],
                off is not None and any(
                    off is g.__dict__.get("_held_offset")
                    for g in self.systems),
                # What an energy bank's idle StopFiring writes with
                # `_firing`; K1 logs those writes since round trips Task 2.
                _t(d.get("_beam_on_countdown")) if energy else None,
                # A missed wake (passive weapons): asleep while NOT at rest.
                # Every `_firing` write, a logged one included, wakes a
                # sleeping weapon (WakeField). The raw asleep flag differs
                # by design with native on: K0 steps every weapon and puts
                # none to sleep (spec 2026-11-02-native-weapon-state-design
                # .md §4.3).
                _t(passive_state.is_asleep(w)) if self.raw_asleep else
                _t(passive_state.is_asleep(w)
                   and not w._passive_at_rest()),
            ))
        for s in self.ships:
            hull = s.GetHull()
            shields = s.GetShields()
            row.append((s.GetName(), _t(s.IsDead()),
                        None if hull is None else
                        _t(float(hull.GetCondition())),
                        None if shields is None else tuple(
                            _t(float(shields.GetCurShields(f)))
                            for f in range(6))))
        # Last (after the ships: the slices below index those): every
        # torpedo and bolt in flight, in `_active` order (K3's flight and
        # hit order), field by field -- the spawn's values (launch
        # deferral) and its flight since.
        for t in projectiles._active:
            row.append(self.torp_row(t))
        self.log.append(row)

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self, ticks_per_frame, ops, ticks=TICKS, before_frame=None,
            scope="tick", whole_ticks: bool = False):
        """`scope` "tick" runs each tick's weapons and combat inside the
        host's effect scope (open with native on only, as in play). "both"
        opens effect_queue.scope() itself, in BOTH arms, around each tick
        and each op: every weapon event a tick or an op produces is then
        delivered when it ends, in the Python reference too.

        `whole_ticks` drives the host's order since native motion phase 4
        (ruling 2): per frame, both op draws first (the frame-start input),
        then each tick whole -- its subsystem update, then its weapons,
        combat and boundary. Off: the batched order (every tick's subsystem
        update, then the between-batch ops, then every combat tick)."""
        rng = random.Random(SEED)

        def tick_scope():
            if scope == "both":
                return effect_queue.scope()
            return host_loop._combat_effect_scope()

        def op_scope():
            if scope == "both":
                return effect_queue.scope()
            return contextlib.nullcontext()

        def op():
            with op_scope():
                self.op(rng, ops)

        def combat_tick():
            self.tick += 1
            ships = list(iter_ships())
            with tick_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=self.player,
                                          push_render_data=False)
            host_loop._combat_tick_boundary()   # as the host does (native damage)
            self.record()
            if rng.random() < 0.3:
                op()

        def gameloop_tick():
            App.g_kTimerManager._time += TICK_DELTA
            game_loop._update_ship_subsystems()

        while self.tick < ticks:
            if before_frame is not None:
                before_frame(self)
            for _ in range(rng.randint(0, 2)):
                op()
            if whole_ticks:
                for _ in range(rng.randint(0, 2)):
                    op()
                for _ in range(ticks_per_frame):
                    gameloop_tick()
                    combat_tick()
            else:
                for _ in range(ticks_per_frame):
                    gameloop_tick()
                for _ in range(rng.randint(0, 2)):
                    op()
                for _ in range(ticks_per_frame):
                    combat_tick()
            sensor_contacts.tick(self.player,
                                 App.g_kUtopiaModule.GetGameTime())
        if self.native:
            nc.audit_mirror()
            self.audit = list(nc.audit_failures())
            assert _h.combat_k1_depth() == 0
        self.counts = nc.counts()
        self.effects = effect_queue.counts()
        return self


# Weighted toward firing, so banks run dry and tubes empty while the rest of
# the stream changes what each walk sees.
OPS = (("fire",) * 10 + ("fire_pulse",) * 3 + ("reload",) * 2
       + ("player_torps",) * 2
       + ("retarget",) * 3 + ("stop",) * 2
       + ("single", "single", "chain", "chain", "off", "on", "on",
          "condition", "condition", "power", "power", "drain", "drain", "ammo_out", "ammo_fill",
          "move", "turn", "face", "manual_on", "manual_move", "manual_off"))


def _compare(ref, nat):
    """Two runs of a scene, tick by tick: every recorded row, the event log,
    the queued rows, the presentation calls (compare_calls). Fire control
    is native in both (M9): both ran K1."""
    assert len(ref.log) == len(nat.log)
    for tick, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n ref %r\n native %r" % (
                tick, x, y)
    for i, (x, y) in enumerate(zip(ref.events, nat.events)):
        assert x == y, "event %d differs:\n ref %r\n native %r" % (i, x, y)
    assert len(ref.events) == len(nat.events)
    effect_split.compare(ref.queued, nat.queued)
    compare_calls(ref.calls, nat.calls)
    assert nat.audit == [], nat.audit
    for arm in (ref, nat):
        assert arm.counts["k1_records"] > 0, arm.counts
        assert arm.counts["k1_logged"]["walk_start"] > 0, arm.counts


def round_trips_ran(nat):
    """Every round trip the plan removed ran in the native arm: walks
    started natively (Task 1), lit beams sustained and idle banks stopped as
    logged writes (Task 2), resting contacts batched and offline systems
    stopped as logged writes (Task 3), and torpedo mounts attributed
    natively (Task 4). And the records combat fire events (Task 3) turned
    into logged writes plus queue entries: beam edges (FIRE_SOUND,
    WEAPON_FIRED) and failed aims (WEAPON_FIRE_FAILED), counted as the
    entries K1 appended, not as records."""
    c = nat.counts
    for key in ("walk_start", "beam_sustain", "idle_bank_stop", "beam_edge",
                "fire_failed"):
        assert c["k1_logged"][key] > 0, (key, c["k1_logged"])
    e = c["k1_entries"]
    logged = c["k1_logged"]
    # A beam's edge and a tube's launch (launch deferral) each queue one
    # ET_WEAPON_FIRED; a launch also its SPAWN and AMMO_CONSUMED. A
    # cannon's launch (Task 3) queues its SPAWN only: the delivery posts
    # its ET_WEAPON_FIRED once the bolt exists.
    launches = logged["tube_launch"] + logged["dumb_launch"]
    assert e["FIRE_SOUND"] == logged["beam_edge"], c
    assert e["WEAPON_FIRED"] == logged["beam_edge"] + launches, c
    assert e["AMMO_CONSUMED"] == launches, c
    assert e["SPAWN"] == launches + logged["pulse_launch"], c
    assert e["WEAPON_FIRE_FAILED"] == c["k1_logged"]["fire_failed"], c
    for key in ("k2_batched_contacts", "k2_logged_system_stop",
                "k3_native_attributions"):
        assert c[key] > 0, (key, c)
    assert presented(nat.calls) > 0
    # The tick's scope delivered the weapon events and sounds at the
    # boundary (the reference never opened it), none lost or raising.
    e = nat.effects
    assert e["delivered"] > 0 and e["skipped_gone"] == e["failed"] == 0, e


def _kinds(scene):
    return {e[0] for e in scene.events + scene.queued.rows}


# ── Review Focus 1: a handler changes state mid-walk ─────────────────────────
# Ruling F2, revised by ruling F3 (combat fire events, Task 3): the queued
# weapon events never reach a handler mid-walk any more -- inside the tick's
# scope they are delivered at the boundary, outside it a K1 session defers
# them to its own end -- so a Python reference that runs them mid-walk is
# no longer comparable. Both arms open the effect scope themselves around
# each tick and each op: the handlers run at the scope's end in both, and
# their StartFiring is a K1 session started inside a delivery (native).

_HANDLER = {}


def WeaponEventHandler(_dest, evt):
    """An SDK-style broadcast handler on ET_WEAPON_FIRED and
    ET_WEAPON_FIRE_FAILED: stop the firing system, then start another
    ship's system (inside the delivery: a K1 session there), sometimes
    switch a ship's sensors off or destroy a tube. Seeded. It acts only at
    depth 0: the events its own StartFiring produces reach it mid-walk in
    the Python and at that session's end natively (ruling F3), so acting
    on them would compare two different orders."""
    state = _HANDLER.get("scene")
    if state is None or _HANDLER["depth"] >= 1:
        return
    scene, rng = state
    weapon = evt.GetSource()
    system = getattr(weapon, "GetParentSubsystem", lambda: None)()
    if system is None or rng.random() < 0.3:
        return
    if effect_queue._draining:
        _HANDLER["in_delivery"] += 1
    _HANDLER["depth"] += 1
    _HANDLER["calls"] += 1
    try:
        system.StopFiring()
        ship = system.GetParentShip()
        other = rng.choice([g for g in scene.firing
                            if g.GetParentShip() is not ship])
        other.StartFiring(scene._enemy_of(rng, other.GetParentShip()),
                          scene._offset(rng))
        roll = rng.random()
        if roll < 0.1:
            sensors = rng.choice(scene.ships).GetSensorSubsystem()
            if sensors is not None:
                sensors.TurnOff()
        elif roll < 0.2:
            tube = rng.choice([w for w in scene.weapons
                               if isinstance(w, ws.TorpedoTube)])
            tube.SetCondition(0.0)
    finally:
        _HANDLER["depth"] -= 1


HANDLER_OPS = ("fire",) * 6 + ("fire_pulse", "reload", "player_torps",
                               "retarget", "single", "chain", "on", "on")
HANDLER_TICKS = 300


def handler_arm(monkeypatch, env, ticks_per_frame, stats):
    """One arm of the mid-walk handler scene: a fresh _Scene with
    WeaponEventHandler on ET_WEAPON_FIRED and ET_WEAPON_FIRE_FAILED, run
    with the effect scope opened in both arms. `stats[native]` gets the
    handler's tallies. (Also tests/helpers/golden_fight.py's
    k1_midwalk_handler scene.)"""
    events = (App.ET_WEAPON_FIRED, App.ET_WEAPON_FIRE_FAILED)
    name = __name__ + ".WeaponEventHandler"
    try:
        with monkeypatch.context() as mp:
            scene = _Scene(mp, env)
            _HANDLER.clear()
            _HANDLER.update(scene=(scene, random.Random(SEED + 1)),
                            depth=0, calls=0, in_delivery=0,
                            k1_in_delivery=0)
            k1_system = nc.k1_system

            def counting_k1_system(system, dt, _orig=k1_system):
                if effect_queue._draining:
                    _HANDLER["k1_in_delivery"] += 1
                return _orig(system, dt)
            mp.setattr(nc, "k1_system", counting_k1_system)
            for et in events:
                App.g_kEventManager.AddBroadcastPythonFuncHandler(
                    et, scene.player, name)
            try:
                return scene.run(ticks_per_frame, HANDLER_OPS,
                                 ticks=HANDLER_TICKS, scope="both")
            finally:
                for et in events:
                    App.g_kEventManager.RemoveBroadcastHandler(
                        et, scene.player, name)
                stats[scene.native] = dict(_HANDLER, scene=None)
    finally:
        _HANDLER.clear()


# ── Review Focus 5: Manual Aim, and a ship on a rig ──────────────────────────

# ── Task 6b: a rigged Bird of Prey at its natural pose runs native ──────────

# ── Ruling P3: the real AI's own StartFiring cadence, through GameLoop.tick ─

LOOP_TICKS = 1500
# Hull left on every ship (and shields down), so the fight kills inside the
# window: hull 0 at ~550 ticks, the death sequence done (IsDead) by ~1300.
LOOP_HULL_FRACTION = 0.05
# Turned to face directly away from the foe it was faced at (its forward and
# aft tubes loaded): the AI's first torpedo walks then try forward tubes
# with the target astern, so failed aims (WEAPON_FIRE_FAILED) happen in
# every fight. Without it a failed aim needed the fight to put a target
# behind a loaded tube when a launch came due, which the presentation RNG
# phase's changed roll stream no longer did.
LOOP_TURNED_AWAY = "Friend-3"


def _deterministic_loop(mp):
    """The process-lifetime input a GameLoop-driven fight reads that a second
    load would otherwise see differently (the hit-audio clocks and memories
    are the _Scene's: tests/helpers/fight_audio). Both arms get the same
    stand-in, so the comparison stays a native-vs-Python one:

    * ai_optimized._phase_key keys the avoidance preprocessor's first-reschedule
      phase on ship.GetObjID(), a process-wide counter (a second load's ships
      get other ids, so other phases): keyed on the ship's name instead."""
    import zlib
    from engine.appc import ai_optimized

    def phase_key(node):
        ai = node.__dict__.get("pCodeAI")
        ship = ai.GetShip() if ai is not None else None
        return zlib.crc32(ship.GetName().encode()) if ship is not None else 0

    mp.setattr(ai_optimized, "_phase_key", phase_key)


def _loop_setup(mp, env, owns_boundary=True):
    """_loop_arm's scene, up to its first tick: a fresh combat_stress, near
    death, shields down, LOOP_TURNED_AWAY facing away, the counters
    installed, every RNG seeded. Returns (scene, GameLoop). A host-driven
    caller passes owns_boundary=False and runs the boundary itself."""
    scene = _Scene(mp, env)
    mp.setenv("DAUNTLESS_NATIVE_COMBAT",
               env["DAUNTLESS_NATIVE_COMBAT"])
    loop = game_loop.GameLoop(          # configure() reads the env
        owns_boundary=owns_boundary)
    assert nc.enabled() is scene.native
    _deterministic_loop(mp)
    for ship in scene.ships:
        hull = ship.GetHull()
        hull.SetCondition(hull.GetMaxCondition() * LOOP_HULL_FRACTION)
        shields = ship.GetShields()
        if shields is not None:
            for face in range(6):
                shields.SetCurShields(face, 0.0)
    turned = [s for s in scene.ships if s.GetName() == LOOP_TURNED_AWAY]
    assert len(turned) == 1, [s.GetName() for s in scene.ships]
    half_turn = TGMatrix3()
    half_turn.MakeZRotation(math.pi)
    turned[0].SetMatrixRotation(
        turned[0].GetWorldRotation().MultMatrix(half_turn))
    scene.starts = 0
    start_firing = ws.WeaponSystem.StartFiring

    def counting_start(system, *args, _orig=start_firing, **kw):
        scene.starts += 1
        return _orig(system, *args, **kw)
    mp.setattr(ws.WeaponSystem, "StartFiring", counting_start)
    scene.k1_systems = 0
    k1_system = nc.k1_system

    def counting_k1_system(system, dt, _orig=k1_system):
        scene.k1_systems += 1
        return _orig(system, dt)
    mp.setattr(nc, "k1_system", counting_k1_system)
    _seed_every_rng(SEED)       # the AI draws on all of them
    return scene, loop


def _loop_arm(monkeypatch, env, ticks=LOOP_TICKS):
    """One fresh combat_stress driven the host's way WITH GameLoop.tick: per
    tick the timers, the real AI (QuickBattle's BasicAttack: its FireScript
    StartFiring -> K1 system sessions with native on), motion and
    subsystems, then host_loop._advance_weapons and _advance_combat (the
    held-weapon pump -> K1), then the per-tick record. Every ship starts
    near death with its shields down, and LOOP_TURNED_AWAY with its foe
    astern."""
    with monkeypatch.context() as mp:
        scene, loop = _loop_setup(mp, env)
        while scene.tick < ticks:
            scene.tick += 1
            loop.tick()
            ships = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=scene.player,
                                          push_render_data=False)
            host_loop._combat_tick_boundary()   # as the host does (native damage)
            scene.record()
            sensor_contacts.tick(scene.player,
                                 App.g_kUtopiaModule.GetGameTime())
        if scene.native:
            nc.audit_mirror()
            scene.audit = list(nc.audit_failures())
            assert _h.combat_k1_depth() == 0
        else:
            scene.audit = []
        scene.counts = nc.counts()
        scene.effects = effect_queue.counts()
        return scene


