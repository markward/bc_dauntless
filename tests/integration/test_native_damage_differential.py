"""The native hit and condition chain is bit-identical to the Python
reference for every NON-kernel caller (native damage, Task 3; spec
docs/superpowers/specs/2026-11-02-native-damage-design.md §3 goals 1, 4, 5,
§4.1-4.2).

Two fresh worlds -- the Python reference (``DAUNTLESS_NATIVE_COMBAT=0``) and
native (``=1``) -- run the same script of steps, each step one tick: its
calls, then the tick boundary (``effect_queue.boundary``). The callers are
the real ones: ``combat.apply_hit`` called directly (weapon, collision and
splash keyword shapes), ``AddDamage``, the collision pass
(``collisions.resolve_collisions``), the death splash at its SPLASH delivery
(a chain: one death's splash kills a neighbour, whose splash lands too),
the death cascade's AddDamage and the hull's subsystem cascade
(DestroySystem) in the deaths' later ticks,
the radiation drain's ``DamageSystem``, and scripted ``DamageSystem`` /
``DestroySystem`` / ``SetCondition`` / ``SetConditionPercentage`` and a
repair bay's tick.

The script covers shielded, unshielded (generator off) and bypassing hits;
every ramp band (no ramp yet, >= 0.6, the linear band, <= 0.1, an empty
face, an overdraw, a zero-max face); god mode, double damage and NPC shields
off; hurtable(0), invincible ships and invincible subsystems; hits with no
overlap, several overlaps and a tie for the primary subsystem; watcher
crossings (COND_WATCH), the threshold events, the repair queue (R10: two
same-tick writes, two REPAIR_ADD entries); deaths and a splash chain; and
Review Focus 4 -- each of the SEVEN shield-face writers (construction,
SetMaxShields, SetCurrentShields, the charge tick's ramp refresh, the
offline drain, the regen, a direct ApplyDamage) run between hits, so a
writer whose mirror push is missing feeds the native hit a stale face.

After every step it compares, by ``.hex()``: every subsystem's condition,
threshold state and watcher values, every face charge and ramp fraction,
each ship's ``_dying`` and ``_dead`` and every repair queue; and every
damage-kind entry delivered in that step, kind by kind, in order, each
operand by its frozen-contract type (R/H by identity -- a label --, D by
``.hex()``, I and B by ``==``, the Python type included). The native arm
must show the native chain ran (hits, condition writes and DamageSystem
calls, no fallback) and end with a clean mirror audit.
"""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import collisions
from engine.appc import combat
from engine.appc import effect_queue as eq
from engine.appc import native_combat as nc
from engine.appc import ship_death, subsystem_cascade
from engine.appc import weapon_subsystems as ws
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.radiation import RadiationDriver
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (HullSubsystem, ImpulseEngineSubsystem,
                                    PowerSubsystem, RepairSubsystem,
                                    SensorSubsystem, ShieldSubsystem)
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.subsystem_stage import tick_subsystem, tick_subsystems

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_effect_post_typed"),
    reason="native combat bindings not built")

OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261102
SET_NAME = "NativeDamageDifferential"


@pytest.fixture(autouse=True)
def _clean():
    nc.reset()
    eq.reset()
    subsystem_cascade.reset()
    ship_death.reset()
    yield
    nc.reset()
    eq.reset()
    subsystem_cascade.reset()
    ship_death.reset()


def _seed_every_rng(seed):
    from engine.appc import collision_avoidance
    from engine.appc import presentation_rng
    from engine.appc.math import reset_random_unit_vector_rng
    random.seed(seed)
    App.g_kSystemWrapper.SetRandomSeed(seed)
    collision_avoidance._rng.seed(collision_avoidance._AVOID_RNG_SEED)
    reset_random_unit_vector_rng()
    presentation_rng.reset()


def _yaw(deg):
    import math
    m = TGMatrix3()
    m.MakeZRotation(math.radians(deg))
    return m


def _place(sub, x, y, z, r):
    sub._position = TGPoint3(x, y, z)
    sub.SetRadius(r)


def _build(name, pos, yaw=0.0, scale=1.0, hull_max=1000.0):
    """A ship with a critical hull, sensors, a targetable power plant,
    impulse, a phaser system of two banks (a WeaponSystem: aggregate
    predicates), a torpedo system with a tube, six shield faces and a
    repair bay, at `pos` turned `yaw` degrees."""
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    hull.SetCritical(1)
    hull.SetDisabledPercentage(0.5)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensors")
    sensor.SetMaxCondition(200.0)
    _place(sensor, 0.0, 1.0, 0.0, 0.5)
    ship.SetSensorSubsystem(sensor)
    plant = PowerSubsystem("Warp Core")
    plant.SetMaxCondition(300.0)
    plant.SetCritical(1)
    _place(plant, 0.0, -0.5, 0.0, 0.4)
    ship.SetPowerSubsystem(plant)
    impulse = ImpulseEngineSubsystem("Impulse")
    impulse.SetMaxCondition(150.0)
    _place(impulse, 0.0, -1.0, 0.2, 0.4)
    ship.SetImpulseEngineSubsystem(impulse)
    phasers = ws.PhaserSystem("Phasers")
    phasers.SetMaxCondition(100.0)
    _place(phasers, 0.0, 0.0, 0.3, 0.3)
    for label, x in (("Phaser 1", 0.5), ("Phaser 2", -0.5)):
        bank = ws.PhaserBank(label)
        bank.SetMaxCondition(80.0)
        _place(bank, x, 0.5, 0.3, 0.3)
        phasers.AddChildSubsystem(bank)
    ship.SetPhaserSystem(phasers)
    torps = ws.TorpedoSystem("Torpedoes")
    torps.SetMaxCondition(100.0)
    _place(torps, 0.0, 1.5, -0.2, 0.3)
    tube = ws.TorpedoTube("Forward Torpedo")
    tube.SetMaxCondition(60.0)
    _place(tube, 0.0, 1.7, -0.2, 0.25)
    torps.AddChildSubsystem(tube)
    ship.SetTorpedoSystem(torps)
    shields = ShieldSubsystem("Shield Generator")
    shields.SetMaxCondition(100.0)
    shields.SetDisabledPercentage(0.25)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(f, 1000.0)
        shields.SetShieldChargePerSecond(f, 40.0)
    _place(shields, 0.0, 0.2, 0.0, 0.3)
    ship.SetShieldSubsystem(shields)
    ship.SetRepairSubsystem(RepairSubsystem("Engineering"))
    ship._radius = 3.0
    ship._shield_hull_box = ((0.0, 0.1, 0.0), (1.0, 2.0, 0.5))
    ship.SetScale(scale)
    ship.SetTranslateXYZ(*pos)
    ship.SetMatrixRotation(_yaw(yaw))
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def _body(ship, x, y, z):
    """Body point (x, y, z) of `ship` in world space (no scale)."""
    p = TGPoint3(x, y, z)
    p.MultMatrixLeft(ship.GetWorldRotation())
    loc = ship.GetWorldLocation()
    return TGPoint3(p.x + loc.x, p.y + loc.y, p.z + loc.z)


def _check(watcher, threshold):
    evt = App.TGFloatEvent_Create()
    evt.SetEventType(App.ET_AI_SYSTEM_STATUS_WATCHER)
    watcher.AddRangeCheck(threshold, FloatRangeWatcher.FRW_BOTH, evt)


class _World:
    """One arm: the world, the script, the per-step record."""

    def __init__(self, mp, env):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
        nc.reset()
        eq.reset()
        subsystem_cascade.reset()
        ship_death.reset()
        _seed_every_rng(SEED)
        App.g_kTimerManager._time = 0.0
        game = _fresh_world()
        mp.setattr(_h, "developer_mode", True, raising=False)
        import engine.dev_combat_cheats as cheats
        cheats.reset()
        self.cheats = cheats
        self.pset = App.SetClass_Create()
        App.g_kSetManager.AddSet(self.pset, SET_NAME)
        self.ships = {}
        for name, pos, yaw, scale, hull in (
                ("Player", (0.0, -30.0, 0.0), 0.0, 1.0, 2000.0),
                ("Alpha", (0.0, 0.0, 0.0), 30.0, 1.0, 8000.0),
                ("Bravo", (3.0, 1.0, 0.0), -15.0, 1.5, 3000.0),
                ("Charlie", (40.0, 0.0, 0.0), 90.0, 1.0, 4000.0)):
            self.add(name, pos, yaw, scale, hull)
        game.SetPlayer(self.ships["Player"])
        self.player = self.ships["Player"]
        nc.configure(env)
        assert nc.enabled() is (env is ON)
        self.native = env is ON
        self.labels = {}
        self.held = []
        self.rows = []
        self.entries = []
        self.step = None
        wrapped = []
        for kind, fn in enumerate(eq._DELIVER):
            if kind in eq.DAMAGE_KINDS:
                fn = self._spy(kind, fn)
            wrapped.append(fn)
        mp.setattr(eq, "_DELIVER", tuple(wrapped))

    def add(self, name, pos, yaw=0.0, scale=1.0, hull=1000.0):
        ship = _build(name, pos, yaw, scale, hull)
        self.pset.AddObjectToSet(ship, name)
        self.ships[name] = ship
        return ship

    # ── labels and operands ─────────────────────────────────────────────────

    def label(self, obj):
        if obj is None:
            return None
        if isinstance(obj, ShipClass):
            return obj.GetName()
        ship = getattr(obj, "_owning_ship", None)
        ship = ship() if callable(ship) else None
        if ship is not None and hasattr(obj, "GetName"):
            return "%s/%s" % (ship.GetName(), obj.GetName())
        for i, o in enumerate(self.held):
            if o is obj:
                return "%s#%d" % (type(obj).__name__, i)
        self.held.append(obj)
        return "%s#%d" % (type(obj).__name__, len(self.held) - 1)

    def operand(self, v):
        t = type(v)
        if v is None:
            return None
        if t is float:
            return ("D", v.hex())
        if t is bool:
            return ("B", v)
        if t is int:
            return ("I", v)
        return ("R", self.label(v))

    def _spy(self, kind, fn):
        def deliver(*ops):
            self.entries.append((self.step, eq.KIND_NAMES[kind],
                                 tuple(self.operand(v) for v in ops)))
            return fn(*ops)
        return deliver

    # ── the record ──────────────────────────────────────────────────────────

    @staticmethod
    def subsystems(ship):
        out = []
        for s in ship.GetSubsystems():
            out.append(s)
            out.extend(getattr(s, "_children", ()))
        return out

    def record(self):
        row = []
        for name in sorted(self.ships):
            ship = self.ships[name]
            row.append((name, bool(ship._dying), bool(ship._dead)))
            for s in self.subsystems(ship):
                watchers = tuple(
                    None if w is None else float(w._value).hex()
                    for w in (s.__dict__.get("_combined_watcher"),
                              s.__dict__.get("_condition_watcher")))
                row.append((self.label(s), float(s._condition).hex(),
                            s._threshold_state, bool(s._in_repair_queue),
                            watchers, bool(s.IsDestroyed())))
            sh = ship.GetShields()
            row.append(("faces", tuple(float(c).hex()
                                       for c in sh._current_shields),
                        tuple(None if r is None else float(r).hex()
                              for r in sh._ramp_fraction),
                        tuple(float(m).hex() for m in sh._max_shields)))
            bay = ship.GetRepairSubsystem()
            row.append(("repair", tuple(self.label(s) for s in bay._queue)))
        row.append(("counts", tuple(sorted(eq.counts().items()))))
        return row

    def run(self, steps):
        for name, fn in steps:
            self.step = name
            fn(self)
            eq.boundary()
            self.rows.append((name, self.record()))


# ── The script ───────────────────────────────────────────────────────────────

def _hit(ship_name, damage, body, *, source="Player", shield=True, **kw):
    """apply_hit on `ship_name` at body point `body`, shooting in from the
    front along the body's -Y, the shield point the bubble entry."""
    def step(w):
        ship = w.ships[ship_name]
        point = _body(ship, *body)
        if shield and "shield_point" not in kw:
            origin = _body(ship, body[0], body[1] + 20.0, body[2])
            d = TGPoint3(point.x - origin.x, point.y - origin.y,
                         point.z - origin.z)
            n = d.Length()
            d = TGPoint3(d.x / n, d.y / n, d.z / n)
            kw["shield_point"] = combat.shield_bubble_entry(ship, origin, d,
                                                            40.0)
        combat.apply_hit(ship, damage, point,
                         source=None if source is None else w.ships[source],
                         **kw)
    return step


def _faces(ship_name, values):
    def step(w):
        sh = w.ships[ship_name].GetShields()
        for f, v in values.items():
            sh.SetCurrentShields(f, v)              # writer W3
    return step


def _charge(ship_name, dt=0.5):
    def step(w):
        tick_subsystem(w.ships[ship_name].GetShields(), dt)  # writers W4 + W5/W6
    return step


def _call(fn):
    def step(w):
        fn(w)
    return step


def _sub(w, ship_name, name):
    for s in w.subsystems(w.ships[ship_name]):
        if s.GetName() == name:
            return s
    raise KeyError(name)


def _watch(w):
    alpha = w.ships["Alpha"]
    _check(alpha.GetHull().GetCombinedPercentageWatcher(), 0.9)
    _check(alpha.GetHull().GetConditionWatcher(), 0.8)
    _check(_sub(w, "Alpha", "Sensors").GetConditionWatcher(), 0.5)
    _sub(w, "Alpha", "Phaser 1").GetConditionWatcher()      # no checks


def _cheat(name, on):
    def step(w):
        getattr(w.cheats, name)(on)
    return step


def _twice_below_max(w):
    imp = _sub(w, "Delta", "Impulse")
    imp.SetCondition(140.0)
    imp.SetCondition(120.0)         # R10: still not queued -> two entries


def _scripted(w):
    alpha = w.ships["Alpha"]
    _sub(w, "Alpha", "Impulse").SetConditionPercentage(0.2)    # disabled
    alpha.DestroySystem(_sub(w, "Alpha", "Forward Torpedo"))   # destroyed
    alpha.DamageSystem(_sub(w, "Alpha", "Phaser 2"), 30.0, w.player)
    _sub(w, "Alpha", "Torpedoes").SetCondition(55.5)


def _repair_back(w):
    _sub(w, "Alpha", "Impulse").SetCondition(150.0)           # operational
    tick_subsystems([w.ships["Alpha"]], 1.0)


def _radiation(w):
    _check(w.ships["Charlie"].GetHull().GetCombinedPercentageWatcher(),
           0.95)
    drv = RadiationDriver(lambda ship: None, rng=random.Random(7))
    sh = w.ships["Charlie"].GetShields()
    sh.TurnOff()
    drv.apply_chunk(w.ships["Charlie"], 0.8, 1.0)
    drv.apply_chunk(w.ships["Charlie"], 0.8, 1.0)
    sh.TurnOn()


def _collide(w):
    a, b = w.ships["Charlie"], w.ships["Delta"]
    for s in (a, b):
        s.SetMass(10.0)
    a.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    b.SetVelocity(TGPoint3(-1.5, 0.0, 0.0))
    collisions.resolve_collisions([a, b], None, 1.0 / 60.0)


def _new_ship(w):
    # Writer W1: a ship built mid-run binds fresh face lists.
    w.add("Delta", (42.5, 0.0, 0.0), 0.0, 1.0, 2500.0)


def _set_max(w):
    sh = w.ships["Alpha"].GetShields()
    sh.SetCurrentShields(2, 0.0)
    sh.SetMaxShields(2, 600.0)          # writer W2: seeds the empty face
    sh.SetMaxShields(3, 0.0)            # a zero-max face


def _offline(w):
    gen = w.ships["Alpha"].GetShields()
    gen.SetCondition(10.0)              # disabled generator
    tick_subsystem(gen, 0.5)                     # writer W5: every face to zero


def _repair_generator(w):
    w.ships["Alpha"].GetShields().SetCondition(100.0)   # faces still empty


def _direct_apply(face, amount):
    def step(w):
        w.ships["Bravo"].GetShields().ApplyDamage(face, amount)   # W7
    return step


def _sqrt_edge(w):
    """DM H1: a hit whose squared distance to Delta's sensors is one where
    libm's pow(s, 0.5) (CPython's ``** 0.5``) and sqrt(s) differ by an ulp,
    with the catchment's edge r_sub + r_hit exactly at the larger: under one
    the sensors overlap, under the other they do not."""
    import math
    from engine.appc.subsystems import subsystem_world_position
    ship = w.ships["Delta"]
    sensor = _sub(w, "Delta", "Sensors")
    hw = subsystem_world_position(sensor, ship)
    r_sub = sensor.GetRadius()
    rng = random.Random(5)
    while True:
        p = TGPoint3(hw.x + rng.uniform(0.2, 0.6), hw.y + rng.uniform(0.2, 0.6),
                     hw.z + rng.uniform(-0.3, 0.3))
        dx, dy, dz = p.x - hw.x, p.y - hw.y, p.z - hw.z
        sq = dx * dx + dy * dy + dz * dz
        d_pow, d_sqrt = sq ** 0.5, math.sqrt(sq)
        if d_pow == d_sqrt:
            continue
        edge = max(d_pow, d_sqrt)
        r_hit = edge - r_sub
        if r_hit > 0.0 and r_sub + r_hit == edge:
            break
    combat.apply_hit(ship, 45.0, p, source=None, splash_radius=r_hit,
                     bypass_shields=True)


def _aftermath(w):
    """The deaths' later ticks: each dying ship's explosion cascade
    (death_cascade: AddDamage at points on the model) and each zeroed
    hull's subsystem cascade (DestroySystem on every subsystem)."""
    for _ in range(6):
        ship_death.advance(0.5)
        subsystem_cascade.advance(0.5)
        eq.boundary()


def _invincible_sub(w, on):
    _sub(w, "Alpha", "Sensors").SetInvincible(on)


def _splash_setup(w):
    w.ships["Alpha"].SetSplashDamage(900.0, 8.0)
    w.ships["Bravo"].SetSplashDamage(700.0, 8.0)
    w.ships["Bravo"].GetHull().SetCondition(150.0)
    w.ships["Alpha"].GetHull().SetCondition(400.0)


STEPS = [
    ("watchers", _call(_watch)),
    ("no ramp yet", _hit("Alpha", 120.0, (0.0, 2.2, 0.0),
                         weapon_type="phaser", ship_instances={})),
    ("W3 faces", _faces("Alpha", {0: 450.0, 1: 50.0, 4: 30.0})),
    ("set faces, read live", _hit("Alpha", 60.0, (0.0, 2.2, 0.0))),
    ("W4 ramp", _charge("Alpha")),
    ("band >= 0.6", _hit("Alpha", 90.0, (0.0, 0.0, 0.55),
                         shield_point=None)),
    ("linear band", _hit("Alpha", 200.0, (0.0, 2.2, 0.0))),
    ("overdraw", _hit("Alpha", 900.0, (0.0, 2.2, 0.0),
                      weapon_type="torpedo")),
    ("bypass band", _hit("Alpha", 80.0, (0.0, -2.2, 0.0),
                         shield_point=None)),
    ("empty face", _hit("Alpha", 75.0, (-1.05, 0.0, 0.0),
                        shield_point=None)),
    ("several overlaps, a tie", _hit("Alpha", 60.0, (0.0, 0.5, 0.3),
                                     splash_radius=0.6, shield=False,
                                     bypass_shields=True)),
    ("no overlap", _hit("Alpha", 40.0, (0.9, -1.9, -0.4), shield=False,
                        bypass_shields=True)),
    ("W2 set max", _call(_set_max)),
    ("top face", _hit("Alpha", 100.0, (0.0, 0.0, 0.55),
                      shield_point=None)),
    ("zero-max face", _hit("Alpha", 100.0, (0.0, 0.0, -0.55),
                           shield_point=None)),
    ("W5 offline", _call(_offline)),
    ("generator repaired", _call(_repair_generator)),
    ("drained hit", _hit("Alpha", 50.0, (0.0, 0.0, 0.55),
                         shield_point=None)),
    ("W6 regen", _charge("Alpha")),
    ("regen hit", _hit("Alpha", 50.0, (0.0, 2.2, 0.0))),
    ("W7 direct ApplyDamage", _call(_direct_apply(0, 350.0))),
    ("after direct", _hit("Bravo", 120.0, (0.0, 2.2, 0.0), source="Alpha")),
    ("W7 direct overdraw", _call(_direct_apply(1, 5000.0))),
    ("after direct overdraw", _hit("Bravo", 90.0, (0.0, -2.2, 0.0),
                                   source="Alpha", shield_point=None)),
    ("generator off", _call(lambda w: w.ships["Bravo"].GetShields()
                            .TurnOff())),
    ("unshielded", _hit("Bravo", 130.0, (0.0, 1.0, 0.0), source="Alpha")),
    ("generator on", _call(lambda w: w.ships["Bravo"].GetShields()
                           .TurnOn())),
    ("AddDamage", _call(lambda w: w.ships["Bravo"].AddDamage(
        _body(w.ships["Bravo"], 0.0, -0.5, 0.0), 0.7, 140.0))),
    ("god on", _cheat("set_god_mode", True)),
    ("god-mode hit", _hit("Player", 400.0, (0.0, 2.2, 0.0),
                          source="Alpha")),
    ("god off", _cheat("set_god_mode", False)),
    ("double on", _cheat("set_double_player_weapons", True)),
    ("double damage", _hit("Charlie", 70.0, (0.0, 2.2, 0.0))),
    ("double off", _cheat("set_double_player_weapons", False)),
    ("npc shields off", _cheat("set_disable_npc_shields", True)),
    ("npc unshielded", _hit("Charlie", 65.0, (0.0, 1.0, 0.0))),
    ("player shielded", _hit("Player", 65.0, (0.0, 2.2, 0.0),
                             source="Charlie")),
    ("npc shields back", _cheat("set_disable_npc_shields", False)),
    ("not hurtable", _call(lambda w: w.ships["Charlie"].SetHurtable(0))),
    ("immune hit", _hit("Charlie", 300.0, (0.0, 2.2, 0.0))),
    ("hurtable", _call(lambda w: w.ships["Charlie"].SetHurtable(1))),
    ("invincible sub", _call(lambda w: _invincible_sub(w, 1))),
    ("sub immune hit", _hit("Alpha", 30.0, (0.0, 1.0, 0.0), shield=False,
                            bypass_shields=True)),
    ("sub vulnerable", _call(lambda w: _invincible_sub(w, 0))),
    ("scripted writes", _call(_scripted)),
    ("repairs", _call(_repair_back)),
    ("radiation", _call(_radiation)),
    ("W1 new ship", _call(_new_ship)),
    ("new ship hit", _hit("Delta", 110.0, (0.0, 2.2, 0.0),
                          source="Charlie")),
    ("same-tick repair writes", _call(_twice_below_max)),
    ("pow, not sqrt", _call(_sqrt_edge)),
    ("collision", _call(_collide)),
    ("light phaser", _hit("Charlie", 90.0, (0.0, 1.0, 0.0), shield=False,
                          bypass_shields=True, damage_hull=False,
                          weapon_type="phaser")),
    ("invincible ship", _call(lambda w: w.ships["Charlie"]
                              .SetInvincible(1))),
    ("invincible to zero", _hit("Charlie", 5000.0, (0.0, 0.0, 0.0),
                                shield=False, bypass_shields=True)),
    ("splash setup", _call(_splash_setup)),
    ("kill and splash chain", _hit("Alpha", 5000.0, (0.0, -0.5, 0.0),
                                   shield=False, bypass_shields=True,
                                   weapon_type="torpedo",
                                   hit_tangent=TGPoint3(1.0, 0.0, 0.0),
                                   decal_radius=0.4, decal_dent=1.0,
                                   single_impact=True, shield_radius=0.9)),
    ("after the deaths", _hit("Bravo", 25.0, (0.0, 0.0, 0.0), shield=False,
                              bypass_shields=True)),
    ("death and subsystem cascades", _call(_aftermath)),
]


def _arm(monkeypatch, env):
    with monkeypatch.context() as mp:
        w = _World(mp, env)
        w.run(STEPS)
        if w.native:
            nc.audit_mirror()
            w.audit = list(nc.audit_failures())
            w.damage_counts = dict(getattr(nc, "damage_counts",
                                           lambda: {})())
        App.g_kSetManager.DeleteSet(SET_NAME)
        return w


def test_native_damage_matches_python_for_every_non_kernel_caller(
        monkeypatch):
    ref = _arm(monkeypatch, OFF)
    nat = _arm(monkeypatch, ON)
    assert [n for n, _ in ref.rows] == [n for n, _ in nat.rows]
    for (name, a), (_n, b) in zip(ref.rows, nat.rows):
        assert a == b, "state differs after step %r" % name
    for name, _ in ref.rows:
        a = [e for e in ref.entries if e[0] == name]
        b = [e for e in nat.entries if e[0] == name]
        assert a == b, "delivered entries differ in step %r" % name
    # The script reached what it claims to.
    kinds = {k for _s, k, _o in ref.entries}
    assert kinds == set(eq.KIND_NAMES[k] for k in eq.DAMAGE_KINDS), kinds
    deaths = [o for s, k, o in ref.entries if k == "SPLASH"]
    assert len(deaths) >= 2, "the splash chain killed a second ship"
    collided = [o for s, k, o in ref.entries
                if s == "collision" and k == "WEAPON_HIT"]
    assert collided, "the collision pass applied a hit"
    # The native chain ran, for every caller, and never handed back.
    counts = nat.damage_counts
    assert counts.get("hits", 0) > 0, counts
    assert counts.get("conditions", 0) > 0, counts
    assert counts.get("damage_systems", 0) > 0, counts
    assert counts.get("fallbacks", 0) == 0, counts
    assert nat.audit == []
