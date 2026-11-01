"""Native K1 fire control is bit-identical to the Python in real fights
(native combat phase 1b, Task 6; plan
docs/superpowers/plans/2026-10-31-native-combat-phase1b-fire-control.md).

Two fresh loads of combat_stress -- the Python reference
(``DAUNTLESS_NATIVE_COMBAT=0``) and native (``=1``, where every held-weapon
pump and every StartFiring's immediate update is walked by the K1 kernel and
Python runs only the effects) -- get the same seeded stream of operations,
all through public calls: StartFiring / StopFiring / re-target without a
stop, SetSingleFire, SetFiringChainMode, weapon systems TurnOff / TurnOn,
SetCondition on banks and tubes, SetPowerSetting on emitters, a torpedo
magazine emptied and refilled, ships nudged and turned, and the player's
Manual Aim switched on and off with a locked subsystem.

After every tick each weapon system's and each bank's state (the Task 5
tuple: type-tagged, floats by .hex(), the `_target_offset` values and which
bank's offset is the same OBJECT as which), every ship's hull condition and
six shield faces, and the whole event log (every AddEvent: type, source,
destination, tick, order, and a weapon hit's payload -- damage, hit point and
normal by .hex(); torpedoes and bolts numbered by first sight) are compared
with ``==``. Each
arm starts with nothing in flight: the other arm's torpedoes would otherwise
fly on in it (headless_mission.clear_in_flight). The native arm must show that K1 really walked and
fired phaser, pulse and torpedo systems (not merely that the scene has
them), and end with a clean mirror audit.

Driven the host's way, without GameLoop.tick (AI draws on the unseeded
module ``random``), exactly as the phase 1a step differential does.
"""
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
from engine.appc import native_combat as nc
from engine.appc import part_pose
from engine.appc import sensor_contacts
from engine.appc import weapon_subsystems as ws
from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core import step_memo
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, headless_mission
from tests.helpers.fight_audio import isolate_fight_audio

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")

TICKS = 600
SEED = 20261031

OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}

# Weapon kinds (native_combat._weapon_kind): systems, then their leaves.
PHASERS, PULSES, TORPEDOES = 1, 2, 4
BANK, CANNON, TUBE = 5, 6, 8


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    nc.reset()


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
    SDK's App.g_kSystemWrapper.GetRandomNumber (unseeded by default) and the
    engine's two process-lifetime streams (avoidance, random unit vectors)."""
    from engine.appc import collision_avoidance
    from engine.appc.math import reset_random_unit_vector_rng
    random.seed(seed)
    App.g_kSystemWrapper.SetRandomSeed(seed)
    collision_avoidance._rng.seed(collision_avoidance._AVOID_RNG_SEED)
    reset_random_unit_vector_rng()


class _Scene:
    """combat_stress, loaded fresh, with the native switch set after the
    load; the op stream, the per-tick record and the full event log."""

    def __init__(self, mp, env, ships="8"):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
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
        self.tick = 0
        self.log = []
        self.events = []
        self.manual = []        # the manual offsets set, as hexes
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            self.events.append((evt.GetEventType(),
                                self.label(evt.GetSource()),
                                self.label(evt.GetDestination()), self.tick,
                                self.payload(evt)))
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

        # Evidence that K1 itself walked and decided, per kind: the walked
        # systems (WALK_START) and the banks K1 decided to fire (FIRE).
        self.walked = {}
        self.walked_names = set()
        self.fired = {}
        if self.native:
            walk_start = nc._K1Walk.walk_start
            decision = nc._k1_decision

            def counting_walk_start(walk, system, _orig=walk_start):
                patched = _orig(walk, system)
                if not patched:     # handed to Python: not a native walk
                    k = nc._weapon_kind(system)
                    self.walked[k] = self.walked.get(k, 0) + 1
                    self.walked_names.add(self.label(system))
                return patched

            def counting_decision(bank, d, walk, _orig=decision):
                k = nc._weapon_kind(bank)
                self.fired[k] = self.fired.get(k, 0) + 1
                return _orig(bank, d, walk)

            mp.setattr(nc._K1Walk, "walk_start", counting_walk_start)
            mp.setattr(nc, "_k1_decision", counting_decision)

    def label(self, obj):
        """A ship's or weapon's name; any other object (a torpedo, a pulse
        bolt, an event's sink) is numbered by first sight, so two arms that
        create them in the same order label them alike. The object is held,
        so its id is never reused."""
        if obj is None:
            return None
        name = self.labels.get(id(obj))
        if name is None:
            name = self.labels[id(obj)] = "%s#%d" % (type(obj).__name__,
                                                     len(self.held))
            self.held.append(obj)
        return name

    def payload(self, evt):
        """A weapon hit's payload: damage, hit point and normal by .hex(),
        hull hit, weapon type, the struck subsystem and the target."""
        if not isinstance(evt, WeaponHitEvent):
            return None
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
            row.append((self.label(g), _t(g.IsFiring()),
                        _t(d.get("_fire_held")), _t(d.get("_force_update")),
                        _t(d.get("_last_weapon_idx")),
                        _t(d.get("_last_group_fired")),
                        _t(d.get("_group_fire_mode")),
                        self.label(d.get("_held_target")),
                        [self.label(t) for t in d.get("_target_list", ())]))
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
        self.log.append(row)

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self, ticks_per_frame, ops, ticks=TICKS, before_frame=None):
        rng = random.Random(SEED)
        while self.tick < ticks:
            if before_frame is not None:
                before_frame(self)
            for _ in range(rng.randint(0, 2)):
                self.op(rng, ops)
            for _ in range(ticks_per_frame):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
            for _ in range(rng.randint(0, 2)):
                self.op(rng, ops)
            for _ in range(ticks_per_frame):
                self.tick += 1
                ships = list(iter_ships())
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=self.player,
                                          push_render_data=False)
                self.record()
                if rng.random() < 0.3:
                    self.op(rng, ops)
            sensor_contacts.tick(self.player,
                                 App.g_kUtopiaModule.GetGameTime())
        if self.native:
            nc.audit_mirror()
            self.audit = list(nc.audit_failures())
            assert _h.combat_k1_depth() == 0
        self.counts = nc.counts()
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
    assert len(ref.log) == len(nat.log)
    for tick, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                tick, x, y)
    for i, (x, y) in enumerate(zip(ref.events, nat.events)):
        assert x == y, "event %d differs:\n python %r\n native %r" % (i, x, y)
    assert len(ref.events) == len(nat.events)
    assert nat.audit == [], nat.audit
    assert nat.counts["k1_records"] > 0, nat.counts
    assert ref.counts["k1_records"] == 0, ref.counts


def _both(monkeypatch, ticks_per_frame, ops=OPS, ships="8", ticks=TICKS,
          before_frame=None, setup=None):
    runs = []
    for env in (OFF, ON):
        with monkeypatch.context() as mp:
            scene = _Scene(mp, env, ships=ships)
            if setup is not None:
                setup(scene, mp)
            runs.append(scene.run(ticks_per_frame, ops, ticks=ticks,
                                  before_frame=before_frame))
    ref, nat = runs
    _compare(ref, nat)
    return ref, nat


def _kinds(scene):
    return {e[0] for e in scene.events}


def _reasons(counts, session="pump"):
    return {k: v for k, v in counts["k1_python_reasons"][session].items()
            if v}


@pytest.mark.parametrize("ticks_per_frame", (1, 6))
def test_k1_matches_python_in_a_fight(monkeypatch, ticks_per_frame):
    ref, nat = _both(monkeypatch, ticks_per_frame)
    # The scene carries every kind K1 decides for.
    kinds = {nc._weapon_kind(g) for g in ref.firing}
    assert {PHASERS, PULSES, TORPEDOES} <= kinds, kinds
    # ... and K1 really walked and fired each kind natively.
    for k in (PHASERS, PULSES, TORPEDOES):
        assert nat.walked.get(k, 0) > 0, nat.walked
    for k in (BANK, CANNON, TUBE):
        assert nat.fired.get(k, 0) > 0, nat.fired
    # The fight happened: fires, torpedo launches, hits, fire failures and
    # the player's ammo use.
    for et in (App.ET_WEAPON_FIRED, App.ET_TORPEDO_FIRED, App.ET_WEAPON_HIT,
               App.ET_WEAPON_FIRE_FAILED, App.ET_TORPEDO_AMMO_CONSUMED):
        assert et in _kinds(ref), et
    # Hits carried their payload into the comparison (damage, hit point),
    # and the shields it compared moved.
    hits = [e[4] for e in ref.events if e[0] == App.ET_WEAPON_HIT]
    assert hits and all(h is not None and h[1] is not None for h in hits)
    ships = slice(len(ref.systems) + len(ref.weapons), None)
    assert any(a[3] != b[3] for a, b in zip(ref.log[0][ships],
                                            ref.log[-1][ships]))
    # A bank ran dry and Manual Aim's offset reached a bank.
    banks = slice(len(ref.systems), len(ref.systems) + len(ref.weapons))
    assert any(r[4] == ("bool", True) for rows in ref.log
               for r in rows[banks]), "no bank ran dry"
    assert ref.manual
    print("k1 differential (tpf=%d): counts %r walked %r fired %r "
          "events %d" % (ticks_per_frame, nat.counts, nat.walked, nat.fired,
                         len(ref.events)))


# ── Review Focus 1: a handler changes state mid-walk ─────────────────────────

_HANDLER = {}


def WeaponEventHandler(_dest, evt):
    """An SDK-style broadcast handler on ET_WEAPON_FIRED and
    ET_WEAPON_FIRE_FAILED: stop the firing system, then start another
    ship's system (re-entrant K1), sometimes switch a ship's sensors off or
    destroy a tube. Seeded, and bounded in depth."""
    state = _HANDLER.get("scene")
    if state is None or _HANDLER["depth"] >= 2:
        return
    scene, rng = state
    weapon = evt.GetSource()
    system = getattr(weapon, "GetParentSubsystem", lambda: None)()
    if system is None or rng.random() < 0.3:
        return
    # The K1 sessions open around this post: 0 in Python, 1 mid-walk, 2
    # when a handler's own StartFiring session posted it.
    session = _h.combat_k1_depth()
    if session:
        _HANDLER["in_session"] += 1
    _HANDLER["max_session"] = max(_HANDLER["max_session"], session)
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


@pytest.mark.parametrize("ticks_per_frame", (1, 6))
def test_handler_stops_and_restarts_mid_walk(monkeypatch, ticks_per_frame):
    """Review Focus 1: a handler on the events K1's effects post changes
    the world in the middle of a walk -- stops the firing system, starts
    another ship's (a K1 session inside a K1 session), turns sensors off,
    destroys a tube -- and the rest of the walk goes as Python's does."""
    events = (App.ET_WEAPON_FIRED, App.ET_WEAPON_FIRE_FAILED)
    name = __name__ + ".WeaponEventHandler"
    ops = ("fire",) * 6 + ("fire_pulse", "reload", "player_torps",
                           "retarget", "single", "chain", "on", "on")
    stats = {}
    runs = []
    try:
        for env in (OFF, ON):
            with monkeypatch.context() as mp:
                scene = _Scene(mp, env)
                _HANDLER.clear()
                _HANDLER.update(scene=(scene, random.Random(SEED + 1)),
                                depth=0, calls=0, in_session=0,
                                max_session=0)
                for et in events:
                    App.g_kEventManager.AddBroadcastPythonFuncHandler(
                        et, scene.player, name)
                try:
                    runs.append(scene.run(ticks_per_frame, ops, ticks=300))
                finally:
                    for et in events:
                        App.g_kEventManager.RemoveBroadcastHandler(
                            et, scene.player, name)
                    stats[scene.native] = dict(_HANDLER, scene=None)
    finally:
        _HANDLER.clear()
    ref, nat = runs
    _compare(ref, nat)
    py, native = stats[False], stats[True]
    assert py["calls"] > 0 and native["calls"] == py["calls"], stats
    # In the native arm the handler ran inside K1 sessions (mid-walk), and
    # its StartFiring opened a session inside one.
    assert native["in_session"] > 0 and py["in_session"] == 0, stats
    assert native["max_session"] >= 2, stats
    for k in (PHASERS, PULSES, TORPEDOES):
        assert nat.walked.get(k, 0) > 0, nat.walked
    print("k1 handler differential (tpf=%d): handler %r, counts %r"
          % (ticks_per_frame, native, nat.counts))


# ── Review Focus 5: Manual Aim, and a ship on a rig ──────────────────────────

def test_manual_aim_offset_matches(monkeypatch):
    """The player fights on Manual Aim with a locked subsystem: the cursor
    pick moves, Manual Aim drops back to the lock and is picked again. Each
    of the player's banks stamps the walk's offset as Python does."""
    ops = (("manual_on",) * 3 + ("manual_move",) * 4
           + ("manual_off", "fire", "fire"))
    ref, nat = _both(monkeypatch, 1, ops=ops, ticks=360)
    assert ref.manual
    # A Manual Aim pick reached one of the player's banks...
    banks = slice(len(ref.systems), len(ref.systems) + len(ref.weapons))
    player_banks = [i for i, w in enumerate(ref.weapons)
                    if w.GetParentSubsystem().GetParentShip() is ref.player]
    picks = set(ref.manual)
    stamped = {rows[banks][i][8] for rows in ref.log for i in player_banks}
    assert picks & stamped, "no manual pick reached a bank"
    # ... through K1 itself: the player's systems were walked natively.
    assert any(n.startswith("Player/") for n in nat.walked_names), \
        nat.walked_names
    assert any(e[0] == App.ET_WEAPON_FIRED and e[1].startswith("Player/")
               for e in ref.events)


def test_forced_pose_ship_runs_native(monkeypatch):
    """Six ships (no Bird of Prey, so nothing is rigged): K1 walks every
    armed system, and goes on walking the Galaxy's natively once a pose is
    forced on it at tick 120 -- its mounts through the pushed part slots
    (posed parts, Task 4). The results stay the Python's. (Was
    test_rigged_ship_runs_python -- RUN_PYTHON posed_ship from the pose
    on -- before posed parts went native.)"""
    pose_at = 120
    seen = {}

    def before_frame(scene):
        if scene.tick >= pose_at and "posed" not in scene.__dict__:
            scene.posed = True
            galaxy = [s for s in scene.ships
                      if s.GetScript() == "ships.Galaxy"][0]
            seen[scene.native] = (nc.counts(), set(scene.walked_names))
            articulation.force_part_pose(
                galaxy, "probe part",
                part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0))
            assert articulation.posed_part_names(galaxy)
            scene.walked_names.clear()

    ref, nat = _both(monkeypatch, 1, ships="6", ticks=360,
                     before_frame=before_frame)
    before, walked_before = seen[True]
    assert before["k1_python_systems"] == 0, before
    assert before["k1_posed"]["walks"] == 0, before
    assert any(n.startswith("Friend-3/") for n in walked_before), \
        walked_before
    assert nat.counts["k1_python_systems"] == 0, nat.counts
    assert nat.counts["k1_posed"]["walks"] > 0, nat.counts
    assert any(n.startswith("Friend-3/") for n in nat.walked_names), \
        nat.walked_names
    assert any(e[0] == App.ET_WEAPON_FIRED and e[1].startswith("Friend-3/")
               and e[3] > pose_at for e in ref.events)


# ── Task 6b: a rigged Bird of Prey at its natural pose runs native ──────────

def test_rigged_bop_at_red_runs_native(monkeypatch):
    """The scene's Bird of Prey (Enemy-4, rigged: both wings) has a target,
    so it is in "red", which its rig authors as the NIF pose: every part at
    identity, its mounts the unrigged mounts. K1 walks its systems, and
    those aiming at it, natively. At tick 200 both arms force its wings to
    cruise (a forced transition window); tick_ship eases them home over the
    rig's 2 s. In that window K1 walks it natively too -- its posed mounts
    through the pushed pose table and part slots (posed parts, Task 4; it
    fell back to Python before) -- and once home, native as ever. No posed
    fallback (posed_ship, posed_target, part_stale) at all; native and
    Python identical throughout."""
    force_at, home_by = 200, 360
    seen = {}

    def bop_of(scene):
        return [s for s in scene.ships
                if s.GetScript() == "ships.BirdOfPrey"][0]

    def setup(scene, mp):
        bop = bop_of(scene)
        assert [p.GetName() for p in articulation.parts_for_ship(bop)] == [
            "left wing", "left wing01"]
        bop.SetTarget(scene._enemy_of(random.Random(SEED + 3), bop))
        assert articulation.state_for(bop) == "red"

    def posed(counts):
        # Every posed fallback but the Fire ASKs at a random op-stream
        # offset on the posed BoP that no mount claims (no_mount: Python's
        # box rule, by design -- ruling C4).
        return tuple(counts["k1_python_reasons"][session][why]
                     for session in ("pump", "system")
                     for why in ("posed_ship", "posed_target", "part_stale",
                                 "mount_unknown", "no_mount")) + tuple(
            counts["k1_fire_ask_reasons"][why]
            for why in ("part_stale", "mount_unknown"))

    def before_frame(scene):
        bop = bop_of(scene)
        if scene.tick >= force_at and "forced" not in scene.__dict__:
            scene.forced = True
            seen[scene.native, "before"] = (nc.counts(),
                                            set(scene.walked_names))
            scene.walked_names.clear()  # from here: walks in the window
            assert all(part_pose.is_identity(p)
                       for p in bop._articulation_poses.values())
            articulation.force_pose(bop, "cruise")
            assert scene.native is False or _h.combat_dump(
                bop.__dict__["_nslot"])["has_posed_parts"] == 1
            # Its own systems ask K1 inside the window (StartFiring's
            # immediate walk, then the pump), whatever the op stream did:
            # cannons on, a full magazine, loaded tubes.
            torps = bop.GetTorpedoSystem()
            ammo = torps.GetCurrentAmmoType()
            ammo.SetAvailable(ammo.GetMaxTorpedoes())
            for i in range(torps.GetNumWeapons()):
                torps.GetWeapon(i).SetNumReady(1)
            for g in (bop.GetPulseWeaponSystem(), torps):
                g.TurnOn()
                g.StartFiring(bop.GetTarget(), None)
                assert g._fire_held
        if scene.tick >= home_by and "home" not in scene.__dict__:
            scene.home = True
            assert not bop._articulation_transitions
            assert all(part_pose.is_identity(p)
                       for p in bop._articulation_poses.values())
            seen[scene.native, "home"] = (nc.counts(),
                                          set(scene.walked_names))
            # From here on, walks AFTER the wings came home only.
            scene.walked_names.clear()

    ref, nat = _both(monkeypatch, 1, setup=setup, before_frame=before_frame)
    before, walked_before = seen[True, "before"]
    home, walked_window = seen[True, "home"]
    nothing = (0,) * len(posed(before))
    # At identity before the window: native, no articulation fallback.
    assert posed(before) == nothing, before
    assert any(n.startswith("Enemy-4/") for n in walked_before), \
        walked_before
    # In the window: native too (it fell back to Python before posed parts
    # went native) -- its own systems walked with posed mounts.
    assert posed(home) == nothing, home
    assert home["k1_posed"]["walks"] > before["k1_posed"]["walks"], home
    assert any(n.startswith("Enemy-4/") for n in walked_window), \
        walked_window
    # Home again: no articulation fallback to the end, and the BoP walks
    # natively (walked_names was cleared at home).
    assert posed(nat.counts) == nothing, nat.counts
    assert any(n.startswith("Enemy-4/") for n in nat.walked_names), \
        nat.walked_names
    print("k1 rigged BoP differential: posed walks before %d home %d end "
          "%d; no_mount fire ASKs %d"
          % (before["k1_posed"]["walks"], home["k1_posed"]["walks"],
             nat.counts["k1_posed"]["walks"],
             nat.counts["k1_fire_ask_reasons"]["no_mount"]))


# ── Ruling P3: the real AI's own StartFiring cadence, through GameLoop.tick ─

LOOP_TICKS = 1500
# Hull left on every ship (and shields down), so the fight kills inside the
# window: hull 0 at ~550 ticks, the death sequence done (IsDead) by ~1300.
LOOP_HULL_FRACTION = 0.05


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


def _loop_arm(monkeypatch, env, ticks=LOOP_TICKS):
    """One fresh combat_stress driven the host's way WITH GameLoop.tick: per
    tick the timers, the real AI (QuickBattle's BasicAttack: its FireScript
    StartFiring -> K1 system sessions with native on), motion and
    subsystems, then host_loop._advance_weapons and _advance_combat (the
    held-weapon pump -> K1), then the per-tick record."""
    with monkeypatch.context() as mp:
        scene = _Scene(mp, env)
        mp.setenv("DAUNTLESS_NATIVE_COMBAT",
                   env["DAUNTLESS_NATIVE_COMBAT"])
        loop = game_loop.GameLoop()         # configure() reads the env
        assert nc.enabled() is scene.native
        _deterministic_loop(mp)
        for ship in scene.ships:
            hull = ship.GetHull()
            hull.SetCondition(hull.GetMaxCondition() * LOOP_HULL_FRACTION)
            shields = ship.GetShields()
            if shields is not None:
                for face in range(6):
                    shields.SetCurShields(face, 0.0)
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
        while scene.tick < ticks:
            scene.tick += 1
            loop.tick()
            ships = list(iter_ships())
            host_loop._advance_weapons(ships, TICK_DELTA)
            host_loop._advance_combat(ships, TICK_DELTA, player=scene.player,
                                      push_render_data=False)
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
        return scene


def test_k1_matches_python_under_the_game_loop_ai(monkeypatch):
    """Ruling P3's gap: the AI's OWN StartFiring cadence (no op stream), with
    GameLoop.tick driving it, native vs Python, until ships die. A first,
    discarded arm runs before the two compared ones: the first combat_stress
    fight in a process diverged from every later one in this harness
    (observed in the AI's tick-1 avoidance scheduling; the cause was not
    chased), while any two later arms matched exactly."""
    import time
    t0 = time.perf_counter()
    _loop_arm(monkeypatch, OFF, ticks=LOOP_TICKS)       # warm-up, discarded
    ref = _loop_arm(monkeypatch, OFF)
    nat = _loop_arm(monkeypatch, ON)
    _compare(ref, nat)
    # The AI fired on its own, and with native on its StartFiring walks
    # went through K1 (system sessions), as did the pump.
    assert ref.starts > 0 and nat.starts == ref.starts, (ref.starts,
                                                         nat.starts)
    assert nat.k1_systems > 0 and ref.k1_systems == 0, (nat.k1_systems,
                                                        ref.k1_systems)
    for k in (PHASERS, TORPEDOES):
        assert nat.walked.get(k, 0) > 0, nat.walked
    assert nat.fired, nat.fired
    for et in (App.ET_WEAPON_FIRED, App.ET_WEAPON_HIT, App.ET_OBJECT_EXPLODING,
               App.ET_OBJECT_DESTROYED):
        assert et in _kinds(ref), et
    # At least one ship destroyed inside the window.
    ships = slice(len(ref.systems) + len(ref.weapons), None)
    dead = {r[0] for r in ref.log[-1][ships] if r[1] == ("int", 1)}
    assert dead, ref.log[-1][ships]
    print("k1 game-loop differential: %.1f s, starts %d, k1 system "
          "sessions %d, dead %r, counts %r walked %r fired %r"
          % (time.perf_counter() - t0, ref.starts, nat.k1_systems,
             sorted(dead), nat.counts, nat.walked, nat.fired))
