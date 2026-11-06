"""K3 dispatch: `cb.projectiles` (projectiles.update_all) runs through the
native torpedo kernel when native combat is on (native combat phase 3, Task
5; spec docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md
§4.3-§4.5; map docs/reference/engine/native-combat/k3-k4-map.md §A5, §A6).

Each scenario runs twice on fresh real ships and torpedoes -- native off
(today's Python update_all) and native on (K3 decides; native_combat.run_k3
answers its ASKs and applies its DONE) -- through the whole combat step
(host_loop._advance_combat), and compares after every tick:

- every torpedo's position, velocity, age, guidance fields, mount key and
  bubble entry (floats by .hex()), and whether it is still in flight;
- the step's hits (points by .hex(), and whether the hit point IS the
  torpedo's `_bubble_entry` object: update_all's returned ones, or those the
  native step applies itself, native damage Task 4), and every hit as its
  HIT_PRESENT delivers it (all inputs by .hex(), and whether `shield_point
  is point`);
- the full ordered event log (every AddEvent: type, source, destination,
  tick; a weapon hit's damage, point and normal by .hex());
- the incoming-torpedo table's velocity writes (torpedo_scan set_velocity,
  per tick as a sorted multiset: an ASK-guided torpedo pushes during the walk,
  the rest at DONE, so only the per-tick set is the contract) and its answer
  to incoming_ids.

The native arm must also show that K3 really ran (its run count, no
whole-step hand-back) or, for the fallback scenarios, that it did not and
why -- and its mirror (torpedo rows included) must still equal the Python at
the end (audit_mirror).
"""
import gc
import importlib
import math
import sys

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k3_begin"),
    reason="native K3 bindings not built")

from engine import host_io  # noqa: E402
from engine import host_loop  # noqa: E402
from engine.appc import articulation  # noqa: E402
from engine.appc import collisions  # noqa: E402
from engine.appc import combat  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_pose  # noqa: E402
from engine.appc import part_severance  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import physical_parents  # noqa: E402
from engine.appc import projectiles  # noqa: E402
from engine.appc import sensor_detection  # noqa: E402
from engine.appc import subsystems  # noqa: E402
from engine.appc import torpedo_scan  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.events import WeaponHitEvent  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.projectiles import Torpedo  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
from engine.core import ids  # noqa: E402
from engine.systems import frames  # noqa: E402
from tests.helpers.fight_audio import isolate_fight_audio  # noqa: E402
from tests.helpers.k3_fight import spy_hits, spy_k3_hits  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _load_hardpoint(ship, name):
    mod_name = "ships.Hardpoints." + name
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


def _hx(v):
    """A float or a point by .hex(); None as it is; anything else with its
    type, so True and 1 (or 0 and False) never compare equal."""
    if v is None:
        return None
    if isinstance(v, float):
        return v.hex()
    if isinstance(v, TGPoint3):
        return tuple(float(c).hex() for c in (v.x, v.y, v.z))
    if isinstance(v, tuple) and len(v) == 3 and all(
            isinstance(c, float) for c in v):
        return tuple(c.hex() for c in v)
    return ("%s" % type(v).__name__, v)


class World:
    """Real ships in one set, a pinned weapon clock, the logs.

    `ships` is ((name, hardpoint, (x, y, z), yaw[, script]), ...), built the
    same way in both arms so labels line up. Torpedoes are labelled T1, T2,
    ... in firing order. `after_hit` hooks run after each hit's HIT_PRESENT
    is delivered (a stand-in for an ET_WEAPON_HIT handler, at the tick
    boundary as handlers are since native damage M2)."""

    def __init__(self, mp, native, ships, tag):
        nc.reset()
        if native:
            nc.configure(ON)
            assert nc.enabled()
        self.native = native
        isolate_fight_audio(mp)
        self.clock = [100.0]
        mp.setattr(ws, "_game_time", lambda: self.clock[0])
        self.set = App.SetClass_Create()
        self.tag = tag
        App.g_kSetManager.AddSet(self.set, tag)
        self.ships = {}
        for name, hardpoint, at, yaw, *script in ships:
            ship = App.ShipClass_Create(name)
            if script:      # lets articulation resolve the hardpoint leaf
                ship.SetScript(script[0])
            _load_hardpoint(ship, hardpoint)
            ship.SetTranslateXYZ(*at)
            m = TGMatrix3()
            m.MakeZRotation(yaw)
            ship.SetMatrixRotation(m)
            ship.SetRadius(3.0)
            self.set.AddObjectToSet(ship, name)
            self.ships[name] = ship
        mp.setattr(App, "Game_GetCurrentPlayer",
                   lambda p=self.ships["Galaxy"]: p)
        self.order = list(self.ships.values())
        self.listed = list(self.order)      # the step's ships_list
        self.instances = None
        self.labels = {id(s): s.GetName() for s in self.order}
        self.torps = []
        self.by_objid = {}
        self.n = 0
        self.log = []
        self.calls = []
        self.events = []
        self.after_hit = []
        self.scan_writes = {}
        projectiles._active.clear()
        # The incoming-torpedo table live (as the AI's incoming_ids keeps it
        # in a fight), so velocity writes reach it.
        projectiles._scan_rebuild(projectiles._scan_table())
        self._spy(mp)

    def _spy(self, mp):
        update_all = projectiles.update_all
        # Every hit as its HIT_PRESENT delivers it (native damage Task 4: K3
        # applies its hits with no combat.apply_hit call, and a spy ON it
        # would be obeyed -- the hits handed back), the after_hit hooks after
        # each; K3's decided hits in both arms.
        spy_hits(mp, self.calls, lambda: self.n, self.label, _hx,
                 after=[lambda: [hook(self) for hook in list(self.after_hit)]])

        def hit_row(t, ship, point, normal):
            self.calls.append((
                "hit", self.n, self.label(t), self.label(ship),
                _hx(point), _hx(normal), _hx(t._bubble_entry),
                point is t._bubble_entry))

        def update_spy(dt, ships, *, ship_instances=None):
            hits = update_all(dt, ships, ship_instances=ship_instances)
            for t, ship, point, normal in hits:
                hit_row(t, ship, point, normal)
            return hits

        mp.setattr(projectiles, "update_all", update_spy)
        spy_k3_hits(mp, hit_row)

        scan_cls = type(torpedo_scan.get_scan())
        set_velocity = scan_cls.set_velocity

        def set_velocity_spy(scan, tid, vx, vy, vz, _orig=set_velocity):
            label = self.by_objid.get(tid, tid)
            self.scan_writes.setdefault(self.n, []).append(
                (label, _hx((float(vx), float(vy), float(vz)))))
            return _orig(scan, tid, vx, vy, vz)

        mp.setattr(scan_cls, "set_velocity", set_velocity_spy)

        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            row = (evt.GetEventType(), self.label(evt.GetSource()),
                   self.label(evt.GetDestination()), self.n)
            if isinstance(evt, WeaponHitEvent):
                row += (_hx(evt.GetDamage()), _hx(evt.GetHitPoint()),
                        _hx(evt.GetNormal()))
            self.events.append(row)
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    def label(self, obj):
        if obj is None:
            return None
        hit = self.labels.get(id(obj))
        if hit is not None:
            return hit
        name = getattr(obj, "GetName", None)
        return (type(obj).__name__, name() if callable(name) else None)

    def fire(self, src, at, vel, target=None, offset=None, ttl=None,
             damage=50.0):
        t = Torpedo()
        t._source_ship = src
        t.SetTranslateXYZ(*at)
        t._velocity = TGPoint3(*vel)
        t._damage = damage
        if ttl is not None:
            t.SetLifetime(ttl)
        if target is not None:
            t._target_ship = target
            if offset is not None:
                t.SetTargetOffset(offset)
        label = "T%d" % (len(self.torps) + 1)
        self.labels[id(t)] = label
        self.torps.append(t)
        projectiles.register(t)
        self.by_objid[t.GetObjID()] = label
        return t

    def close(self):
        for t in list(projectiles._active):
            projectiles.expire(t)
        App.g_kSetManager.DeleteSet(self.tag)

    def _torp_row(self, t):
        d = t.__dict__
        p = t.GetTranslate()
        key = d.get("_mount_key")
        if key is not None:
            key = (self.label(key[0]), _hx(key[1]), _hx(key[2]),
                   _hx(key[3]), self.label(key[4]))
        return (self.label(t), t in projectiles._active, _hx(p),
                _hx(t._vel), _hx(d.get("_age")),
                _hx(d.get("_last_seen_target_pos")),
                _hx(d.get("_last_target_vel")), key,
                _hx(t._bubble_entry))

    def record(self):
        row = [self._torp_row(t) for t in self.torps]
        for s in self.order:
            row.append((self.label(s),
                        _hx(float(s.GetHull().GetCondition()))))
        row.append(("scan_writes", sorted(self.scan_writes.get(self.n, []))))
        observer = self.ships.get("Vorcha")
        if observer is not None and type(projectiles._active) is \
                projectiles._ActiveList:
            row.append(("incoming", [
                self.by_objid.get(i, i) for i in
                projectiles.incoming_ids(observer, 3600.0, None, 0)]))
        self.log.append(row)

    def tick(self, before=None):
        self.n += 1
        self.clock[0] += DT
        if before is not None:
            before(self)
        host_loop._advance_combat(list(self.listed), DT,
                                  ship_instances=self.instances,
                                  push_render_data=False)
        host_loop._combat_tick_boundary()   # as the host does (native damage)
        self.record()


def _both(monkeypatch, script, ticks, ships=None, setup=None):
    """Run `script(world, tick)` before each of `ticks` ticks, native off
    then on; compare. Returns (reference world, native world, native
    counts)."""
    worlds = []
    counts = None
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = World(mp, native, ships or GALAXY_VORCHA, "k3_%d" % native)
            try:
                if setup is not None:
                    setup(w, mp)
                for t in range(ticks):
                    w.tick(before=lambda w, t=t: script(w, t))
                if native:
                    counts = nc.counts()
                    nc.audit_mirror()
                    assert nc.audit_failures() == [], nc.audit_failures()
                    assert not _h.combat_k3_open()
            finally:
                w.close()
            worlds.append(w)
    ref, nat = worlds
    assert len(ref.log) == len(nat.log) == ticks
    for i, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                i, x, y)
    for i, (a, b) in enumerate(zip(ref.calls, nat.calls)):
        assert a == b, "call %d differs:\n python %r\n native %r" % (i, a, b)
    assert len(ref.calls) == len(nat.calls)
    assert nat.events == ref.events
    return ref, nat, counts


def _calls(world, kind):
    return [c for c in world.calls if c[0] == kind]


def _k3_ran(counts):
    assert counts.get("k3_runs", 0) > 0, counts
    assert counts.get("k3_python_steps", 0) == 0, counts
    # Native damage Task 4: no hit the kernel decided is handed to Python.
    assert counts["k3_hit_python"] == 0, counts["k3_hit_python_reasons"]


def _k3_stood_down(counts, why, at_least=1):
    assert counts.get("k3_runs", 0) == 0, counts
    assert counts["k3_python_reasons"][why] >= at_least, counts


GALAXY_VORCHA = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
                 ("Vorcha", "vorcha", (10.0, 120.0, 8.0), math.pi))
# With ship scripts: articulation resolves the hardpoint leaves, so a posed
# target's part slots can be resolved (and its steer point is native).
SCRIPTED_GALAXY_VORCHA = (
    ("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0, "ships.Galaxy"),
    ("Vorcha", "vorcha", (10.0, 120.0, 8.0), math.pi, "ships.Vorcha"))
#: A Bird of Prey between them, across the shots' path.
BOP_IN_THE_PATH = SCRIPTED_GALAXY_VORCHA + (
    ("BoP", "birdofprey", (10.0, 40.0, 8.0), 0.0, "ships.BirdOfPrey"),)
#: The steer-point ASK reasons a posed target with a current slot must
#: never give.
_POSED_STEER_REASONS = ("posed_target", "part_stale", "mount_stale")


def _steer_reasons(counts, names):
    why = counts["k3_steer_reasons"]
    return sum(why.get(n, 0) for n in names)


def _move_vorcha(w, t):
    """The Vor'cha drifts: its velocity feeds the guided torpedoes' lead."""
    v = w.ships["Vorcha"]
    vel = TGPoint3(1.5, -0.75 + 0.01 * t, 0.5)
    p = v.GetWorldLocation()
    v.SetTranslateXYZ(p.x + vel.x * DT, p.y + vel.y * DT, p.z + vel.z * DT)
    v.SetVelocity(vel)


def _volley(w, t):
    g, v = w.ships["Galaxy"], w.ships["Vorcha"]
    _move_vorcha(w, t)
    if t == 0:
        w.fire(g, (0.5, 4.0, 0.0), (2.0, 59.0, 3.0), target=v)
        w.fire(g, (-0.5, 4.0, 0.0), (-3.0, 59.5, 1.0), target=v,
               offset=v.GetShields().GetPosition())
        w.fire(g, (0.0, 4.0, 0.5), (0.0, 60.0, 0.0))          # dumbfire
        w.fire(g, (0.0, 4.0, -0.5), (25.0, 50.0, -5.0), target=v)
    elif t == 30:
        w.fire(v, (10.0, 115.0, 8.0), (0.0, -60.0, 0.0), target=g,
               offset=g.GetShields().GetPosition())
        w.fire(v, (11.0, 115.0, 8.0), (1.0, -60.0, 2.0), target=g)


# ── Scenarios ────────────────────────────────────────────────────────────────

def test_volley_matches(monkeypatch):
    """Guided shots (one at a subsystem offset), a dumbfire and a wide shot
    that turns, from both ships at a drifting target: steer, advance, hit."""
    ref, _nat, counts = _both(monkeypatch, _volley, 200)
    assert _calls(ref, "hit") and _calls(ref, "hit_present")
    assert any(e[0] == App.ET_WEAPON_HIT for e in ref.events)
    assert any(e[0] == App.ET_TORPEDO_EXITED_SET for e in ref.events)
    assert any(ref.scan_writes.values())
    _k3_ran(counts)
    # The offset shots' mounts attributed natively (round trips, Task 4).
    assert counts["k3_asks"]["steer_point"] == 0, counts
    assert counts["k3_native_attributions"] >= 2, counts


def test_ttl_and_hit_expire_order(monkeypatch):
    """One tick ends a TTL shot and a hit shot fired BEFORE it: both
    EXITED_SET events come TTL first, then the hit, then its WEAPON_HIT."""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            p = v.GetWorldLocation()
            w.fire(g, (p.x, p.y - 6.5, p.z), (0.0, 60.0, 0.0))     # hits
            w.fire(g, (-50.0, 0.0, 0.0), (0.0, 60.0, 0.0), ttl=DT * 3.5)

    ref, _nat, counts = _both(monkeypatch, script, 6)
    exits = [e for e in ref.events if e[0] == App.ET_TORPEDO_EXITED_SET]
    assert [(e[1], e[3]) for e in exits] == [("T2", 4), ("T1", 4)], exits
    order = [e[0] for e in ref.events if e[3] == 4]
    assert order.index(App.ET_WEAPON_HIT) > order.index(
        App.ET_TORPEDO_EXITED_SET), order
    _k3_ran(counts)


def _shield_box(w, mp):
    w.ships["Vorcha"]._shield_hull_box = ((0.0, 0.5, 0.0), (1.2, 2.5, 0.6))


def test_bubble_hit_point_is_shield_point(monkeypatch):
    """A shot into a raised bubble detonates ON it: update_all's hit point,
    the torpedo's `_bubble_entry` and the hit's shield_point are ONE
    object (the fallback tier, headless), in both arms."""

    def script(w, t):
        if t == 0:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            p = v.GetWorldLocation()
            w.fire(g, (p.x + 0.2, p.y - 12.0, p.z), (0.0, 60.0, 0.0))

    ref, nat, counts = _both(monkeypatch, script, 20, setup=_shield_box)
    (hit,) = _calls(ref, "hit")
    assert hit[6] is not None and hit[7] is True, hit
    (applied,) = _calls(ref, "hit_present")
    assert applied[9] is not None and applied[10] is True, applied
    _k3_ran(counts)


def test_handler_launch_moves_next_tick(monkeypatch):
    """A torpedo launched by a hit's handler (at the hit's delivery, after
    the step) is not moved until the next tick, in both arms."""

    def setup(w, mp):
        def launch(world):
            if not world.__dict__.get("launched"):
                world.launched = world.n
                v, g = world.ships["Vorcha"], world.ships["Galaxy"]
                world.fire(v, (10.0, 110.0, 8.0), (0.0, -60.0, 0.0),
                           target=g)
        w.after_hit.append(launch)

    def script(w, t):
        if t == 0:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            p = v.GetWorldLocation()
            w.fire(g, (p.x, p.y - 6.0, p.z), (0.0, 60.0, 0.0))

    ref, _nat, counts = _both(monkeypatch, script, 30, setup=setup)
    n = ref.launched
    t2 = [r for r in ref.log[n - 1] if r[0] == "T2"][0]
    assert t2[2] == _hx((10.0, 110.0, 8.0)) and t2[4] == _hx(0.0), t2
    t2_next = [r for r in ref.log[n] if r[0] == "T2"][0]
    assert t2_next[2] != t2[2]
    _k3_ran(counts)


def test_plain_list_active_runs_python(monkeypatch):
    """`_active` replaced by a plain list (tests do it): the whole step is
    Python's."""

    def setup(w, mp):
        mp.setattr(projectiles, "_active", [])

    ref, _nat, counts = _both(monkeypatch, _volley, 60, setup=setup)
    assert any(r[1] for r in ref.log[-1] if str(r[0]).startswith("T"))
    _k3_stood_down(counts, "plain_active", 60)


def _patched_fn(module, name):
    real = getattr(module, name)

    def setup(w, mp):
        mp.setattr(module, name, lambda *a, **k: real(*a, **k))
    return setup


def test_a_patched_target_visible_is_not_honoured(monkeypatch):
    """projectiles._target_visible patched (a spy): the step stays native
    (spec Part A, phase 6 A3), so only the Python arm calls it."""
    seen = []
    real = projectiles._target_visible

    def setup(w, mp):
        def spy(torpedo, target):
            seen.append(w.native)
            return real(torpedo, target)
        mp.setattr(projectiles, "_target_visible", spy)

    _ref, _nat, counts = _both(monkeypatch, _volley, 40, setup=setup)
    assert False in seen and True not in seen
    _k3_ran(counts)


# Every other function (and constant) K3 stands in for (map §A8.3.9): a
# patch of one leaves the step native (Part A, phase 6 A3).
_SNAPSHOT_FUNCTIONS = (
    (projectiles, "_guide"), (projectiles, "_steer_point"),
    (projectiles, "_broadphase"), (projectiles, "_shifted"),
    (combat, "sphere_hit"), (combat, "_resolve_hit_point"),
    (combat, "shield_bubble_entry"), (combat, "shields_block"),
    (combat, "bubble_bound_radius"), (combat, "ray_sphere_entry"),
    (combat, "cloak_shields_suspended"), (combat, "_hull_box_for"),
    (combat, "_body_frame_delta"), (collisions, "world_radius"),
    (frames, "offset_between"), (frames, "containing_set"),
    (frames, "shifted"), (subsystems, "target_offset_world"),
    (subsystems, "_is_offline"),
    (part_severance, "authored_mount_subsystem"),
    (part_severance, "_mounted_subsystems"),
    (sensor_detection, "can_detect"), (host_io, "ray_trace_mesh"),
    (ids, "implements"),
)


@pytest.mark.parametrize("module, name", _SNAPSHOT_FUNCTIONS,
                         ids=["%s.%s" % (m.__name__, n)
                              for m, n in _SNAPSHOT_FUNCTIONS])
def test_a_patched_stood_in_function_is_not_honoured(
        monkeypatch, module, name):
    _ref, _nat, counts = _both(monkeypatch, _volley, 12,
                               setup=_patched_fn(module, name))
    _k3_ran(counts)


@pytest.mark.parametrize("module, name, value", (
    (projectiles, "_LEAD_ACCEL_K", 0.25),
    (sensor_detection, "ENHANCED_SENSOR_CONTEST",
     not sensor_detection.ENHANCED_SENSOR_CONTEST),
), ids=["_LEAD_ACCEL_K", "ENHANCED_SENSOR_CONTEST"])
def test_a_changed_constant_reaches_the_kernel_when_pushed(
        monkeypatch, module, name, value):
    """A constant the kernel was pushed at resync, changed since and
    re-pushed (push_globals): the step stays native and matches Python's
    with the new value. (Changed and NOT pushed, the kernel keeps the old
    one: Part A, phase 6 A3, there is no snapshot compare.)"""

    def setup(w, mp):
        mp.setattr(module, name, value)
        nc.push_globals()

    _ref, _nat, counts = _both(monkeypatch, _volley, 12, setup=setup)
    _k3_ran(counts)


def test_a_foreign_ship_velocity_getter_is_not_honoured(monkeypatch):
    """GetVelocityTG (the target's lead) is read from the mirror: a ship
    class resolving it to non-engine code leaves the step native (Part A,
    phase 6 A3; the static override guard still covers ENGINE classes)."""

    def setup(w, mp):
        real = ShipClass.GetVelocityTG
        mp.setattr(ShipClass, "GetVelocityTG",
                   lambda self: real(self))

    _ref, _nat, counts = _both(monkeypatch, _volley, 12, setup=setup)
    _k3_ran(counts)


def test_a_torpedo_subclass_overriding_translate_is_not_honoured(
        monkeypatch):
    """A torpedo whose class overrides GetTranslate (a mod's subclass): the
    kernel reads the store's position regardless (Part A, phase 6 A3), so
    the step stays native (the override here returns the store's)."""

    class OddTorpedo(Torpedo):
        def GetTranslate(self):
            return Torpedo.GetTranslate(self)

    def script(w, t):
        if t == 0:
            g = w.ships["Galaxy"]
            odd = OddTorpedo()
            odd._source_ship = g
            odd.SetTranslateXYZ(0.0, 4.0, 0.0)
            odd._velocity = TGPoint3(0.0, 60.0, 0.0)
            w.labels[id(odd)] = "T1"
            w.torps.append(odd)
            projectiles.register(odd)
            w.by_objid[odd.GetObjID()] = "T1"

    _ref, _nat, counts = _both(monkeypatch, script, 10)
    _k3_ran(counts)


def test_forced_part_pose_target_steers_natively(monkeypatch):
    """Shots at a subsystem of a ship with a part forced off its NIF pose
    (no mount on it: the slot reads "no part", the offset itself): the
    first guided tick attributes the mount natively (round trips, Task 4;
    was an ASK steer_point), and the steer point is the kernel's. (Was
    test_posed_target_asks_and_matches -- an ASK steer_point every guided
    tick -- before posed parts went native.)"""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            articulation.force_part_pose(
                g, "probe part",
                part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0))
            w.fire(v, (10.0, 115.0, 8.0), (0.0, -60.0, 0.0), target=g,
                   offset=g.GetShields().GetPosition())
            w.fire(v, (11.0, 115.0, 8.0), (2.0, -60.0, 1.0), target=g)

    ref, _nat, counts = _both(monkeypatch, script, 130,
                              ships=SCRIPTED_GALAXY_VORCHA)
    assert _calls(ref, "hit")
    _k3_ran(counts)
    # The one offset shot attributed natively; no steer ASK at all.
    assert counts["k3_asks"]["steer_point"] == 0, counts
    assert counts["k3_native_attributions"] == 1, counts
    assert counts["k3_posed_steers"] > 30, counts
    assert _steer_reasons(counts, _POSED_STEER_REASONS) == 0, counts


def test_write_log_keeps_scan_velocity(monkeypatch):
    """A guided shot's velocity reaches the incoming-torpedo table at DONE
    exactly as the `_velocity` setter would (the per-tick writes and the
    table's incoming_ids answers compare), with no extra or missing write;
    and a target outside the step's ships_list is an ASK guide, whose own
    setter pushes."""

    def setup(w, mp):
        # The Bird of Prey is in the set but NOT in ships_list: a torpedo
        # aimed at it is guided by Python (ASK guide).
        w.listed = [w.ships["Galaxy"], w.ships["Vorcha"]]

    def script(w, t):
        _move_vorcha(w, t)
        if t == 0:
            g, v, b = (w.ships["Galaxy"], w.ships["Vorcha"],
                       w.ships["Bop"])
            w.fire(g, (0.0, 4.0, 0.0), (6.0, 59.0, 2.0), target=v)
            w.fire(g, (0.0, -4.0, 0.0), (5.0, -59.0, 1.0), target=b)

    ships = GALAXY_VORCHA + (("Bop", "birdofprey", (-20.0, -150.0, 5.0),
                              0.0),)
    ref, _nat, counts = _both(monkeypatch, script, 90, ships=ships,
                              setup=setup)
    writes = [lbl for n in ref.scan_writes for lbl, _v in ref.scan_writes[n]]
    assert "T1" in writes and "T2" in writes
    _k3_ran(counts)
    assert counts["k3_asks"]["guide"] > 0, counts


def test_switch_off_unchanged_calls(monkeypatch):
    """Switch off: update_all never reaches the driver or a K3 / step / torp
    binding (byte-identical to before)."""
    called = []
    for name in dir(_h):
        if name.startswith(("combat_k3", "combat_step", "combat_torp")):
            real = getattr(_h, name)
            monkeypatch.setattr(
                _h, name,
                lambda *a, _n=name, _r=real, **k: called.append(_n)
                or _r(*a, **k))
    monkeypatch.setattr(nc, "run_k3",
                        lambda *a, **k: called.append("run_k3"),
                        raising=False)
    with monkeypatch.context() as mp:
        w = World(mp, False, GALAXY_VORCHA, "k3_off")
        # The free queue's drain asks combat_k3_open() whether a session is
        # open -- a status read, not K3 dispatch. Garbage an EARLIER test
        # left is collected at whatever moment the cyclic GC picks, and its
        # finalizers queue frees: drain them now and hold the collector off
        # for the window, so only this test's own switch-off path is seen.
        nc.drain()
        gc.disable()
        del called[:]
        try:
            for t in range(40):
                w.tick(before=lambda w, t=t: _volley(w, t))
        finally:
            gc.enable()
            w.close()
    assert called == []


def test_audit_mode_runs_the_python_step(monkeypatch):
    """DAUNTLESS_NATIVE_AUDIT=1: every can_detect is audited, which the
    kernel's own can_detect would bypass, so K3 stands down ("audit")."""

    def setup(w, mp):
        if w.native:
            nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1",
                          "DAUNTLESS_NATIVE_AUDIT": "1"})
            assert nc.audit_enabled()

    _ref, _nat, counts = _both(monkeypatch, _volley, 30, setup=setup)
    _k3_stood_down(counts, "audit", 30)


def test_plain_dict_instances_runs_python(monkeypatch):
    """`ship_instances` that is not a TrackedInstances: Python
    ("instances"), as K2."""

    def setup(w, mp):
        w.instances = {}

    _ref, _nat, counts = _both(monkeypatch, _volley, 20, setup=setup)
    _k3_stood_down(counts, "instances", 20)


def test_duplicate_torpedo_runs_python(monkeypatch):
    """A torpedo in `_active` twice (Python advances it twice a tick): no
    table can hold it, so the step is Python's ("row") until it is gone."""

    def script(w, t):
        g = w.ships["Galaxy"]
        if t == 0:
            w.dup = w.fire(g, (40.0, 0.0, 0.0), (0.0, 0.0, 30.0))
            projectiles._active.append(w.dup)
            w.fire(g, (0.0, 4.0, 0.0), (1.0, 60.0, 0.0),
                   target=w.ships["Vorcha"])
        elif t == 10:
            projectiles._active.remove(w.dup)     # one copy left

    _ref, _nat, counts = _both(monkeypatch, script, 20)
    assert counts["k3_python_reasons"]["row"] == 10, counts
    assert counts["k3_runs"] == 10, counts


def test_no_step_scan_runs_python(monkeypatch):
    """update_all called outside a combat step (no current step scan for
    this ships_list): Python ("scan")."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_noscan")
        try:
            _volley(w, 0)
            projectiles.update_all(DT, list(w.order))
        finally:
            w.close()
    c = nc.counts()
    assert c.get("k3_runs", 0) == 0 and \
        c["k3_python_reasons"]["scan"] == 1, c


def test_stale_native_scan_runs_python(monkeypatch):
    """`_step` is this ships_list's, but the native step state was re-scanned
    since (another list): the serial the driver sends no longer matches, so
    the kernel hands the step back ("scan") instead of walking the other
    list's ships."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_stale")
        try:
            _volley(w, 0)
            st = nc.step_scan(w.listed)
            assert st.ok
            ok, _why, _sets = _h.combat_step_scan(
                [w.ships["Galaxy"]], nc._kind("Object"), nc._KIND_SHIFT,
                nc._k2_seen_set, nc._STEP_SHIP_PATCHES)
            assert ok and _h.combat_step_serial() != st.serial
            projectiles.update_all(DT, w.listed)
            c = nc.counts()
            assert c.get("k3_runs", 0) == 0, c
            assert c["k3_python_reasons"]["scan"] == 1, c
        finally:
            nc.clear_step()
            w.close()


def test_step_scan_rebuilds_a_dirty_torpedo_table(monkeypatch):
    """A dirty torpedo table is rebuilt at the top of step_scan, BEFORE the
    native scan checks the rows, so every torpedo's set is in the step's
    sets and framed at scan time (not asked for one by one later)."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_dirty_scan")
        try:
            _volley(w, 0)
            nc.torpedo_table_mark_dirty()
            assert nc._k3_dirty
            st = nc.step_scan(w.listed)
            assert st.ok
            assert not nc._k3_dirty
            assert list(_h.combat_torp_handles()) == [
                t.__dict__["_k3_row"] for t in projectiles._active]
        finally:
            nc.clear_step()
            w.close()


def test_step_scan_cleared_after_the_step(monkeypatch):
    """The step's scan (holding ships_list) does not outlive the step."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_clear")
        try:
            w.tick(before=lambda w: _volley(w, 0))
            assert nc._step is None
            assert nc.counts()["k3_runs"] == 1
        finally:
            w.close()


def test_step_scan_cleared_when_update_all_raises(monkeypatch):
    """host_loop's try/finally: an exception from projectiles.update_all
    inside the combat step still drops the step's scan (it holds
    ships_list) and empties the native step state."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_raise_step")
        try:
            _volley(w, 0)
            seen = []

            def boom(dt, ships, *, ship_instances=None):
                seen.append(nc._step)
                raise ZeroDivisionError("boom")
            mp.setattr(projectiles, "update_all", boom)
            with pytest.raises(ZeroDivisionError):
                host_loop._advance_combat(list(w.listed), DT,
                                          push_render_data=False)
            assert seen and seen[0] is not None and seen[0].ok
            assert nc._step is None
            assert not _h.combat_step_dump()["representable"]
        finally:
            w.close()


def test_mission_swap_clears_the_step_scan(monkeypatch):
    """HostController._drain_pending_swap drops a step scan left over from
    the old mission (it holds the old ships_list)."""
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_swap")
        try:
            assert nc.step_scan(w.listed).ok
            assert _h.combat_step_dump()["representable"]
            h = HostController()
            h.renderer = _FakeRenderer()
            h.loader = _StubLoader()
            h.session = MissionSession(mission_name="prev")
            h.swap_mission("Next.Mission")
            h._drain_pending_swap()
            assert nc._step is None
            assert not _h.combat_step_dump()["representable"]
        finally:
            w.close()


def test_ask_exception_abandons_and_reraises(monkeypatch):
    """A Python ASK answer that raises (a target outside ships_list with a
    raising GetVelocityTG: ASK guide): the session is abandoned and the
    exception propagates; no age or position was applied (the Python body
    would have advanced the torpedoes before it in the list)."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_raise")
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            stray = ShipClass()
            stray.SetName("Stray")
            stray.SetTranslateXYZ(0.0, 50.0, 0.0)
            w.set.AddObjectToSet(stray, "Stray")

            def boom():
                raise ZeroDivisionError("boom")
            stray.GetVelocityTG = boom
            first = w.fire(g, (0.0, 4.0, 0.0), (0.0, 60.0, 0.0), target=v)
            w.fire(g, (1.0, 4.0, 0.0), (0.0, 60.0, 0.0), target=stray)
            before = _hx(first.GetTranslate())
            nc.step_scan(w.listed)
            with pytest.raises(ZeroDivisionError):
                projectiles.update_all(DT, w.listed)
            assert not _h.combat_k3_open()
            assert _hx(first.GetTranslate()) == before
            assert first._age == 0.0
            w.set.RemoveObjectFromSet("Stray")
        finally:
            w.close()


def test_exception_right_after_begin_leaves_no_open_session(monkeypatch):
    """An exception between combat_k3_begin and the walk's own try (the
    driver's set-up: the ASK kind lookup, the handle walker) must not leak
    an open session -- every later begin would throw. The next step runs
    through K3 as normal."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_begin_raise")
        try:
            _volley(w, 0)

            def boom():
                raise ZeroDivisionError("boom")
            with monkeypatch.context() as inner:
                inner.setattr(nc, "_K1Walk", boom)
                nc.step_scan(w.listed)
                try:
                    with pytest.raises(ZeroDivisionError):
                        projectiles.update_all(DT, w.listed)
                finally:
                    nc.clear_step()
            assert not _h.combat_k3_open()
            runs = nc.counts().get("k3_runs", 0)
            w.tick()
            assert not _h.combat_k3_open()
            assert nc.counts()["k3_runs"] == runs + 1, nc.counts()
        finally:
            w.close()


def test_ask_guide_round_trip_advances_on_pushed_velocity(monkeypatch):
    """By hand: a target outside the step scan is an ASK guide; the real
    projectiles._guide answers it, its `_velocity` setter pushes the new
    velocity into the K3 row, and the kernel advances the torpedo on THAT
    velocity (the store position by .hex())."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_rt")
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            t = w.fire(g, (0.0, 4.0, 0.0), (20.0, 50.0, 3.0), target=v)
            start = t.GetTranslate()
            nc.torpedo_table_rebuild(projectiles._active)
            st = nc.step_scan([g])        # the target is not in the scan
            assert st.ok
            t_now, use_memo, drift = nc._k1_clocks()
            assert _h.combat_k3_begin(
                DT, (t_now, drift), use_memo,
                {"n_active": 1, "scan_serial": st.serial}) is None
            rec = _h.combat_k3_next()
            assert rec[:3] == (1, "guide", t.__dict__["_k3_row"])
            v0 = _hx(t._vel)
            projectiles._guide(t, DT)
            assert _hx(t._vel) != v0           # it really turned
            _h.combat_k3_answer(None)
            rec = _h.combat_k3_next()
            assert rec[0] == 0
            (wr,) = rec[1]
            assert wr[2:] == (None,) * 4   # Python already wrote
            _h.combat_k3_end()
            want = start + t._vel * DT
            assert _hx(t.GetTranslate()) == _hx(want)
        finally:
            nc._step = None
            w.close()


def test_reset_clears_step_and_k3_state(monkeypatch):
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k3_reset")
        try:
            _volley(w, 0)
            nc.step_scan(w.listed)
            before = _h.combat_step_serial()
            nc.reset()
            assert nc._step is None
            assert _h.combat_step_serial() != before
            assert not _h.combat_step_dump()["representable"]
            c = nc.counts()
            assert c["k3_runs"] == 0
            assert all(n == 0 for n in c["k3_python_reasons"].values())
        finally:
            w.close()


def test_available_needs_the_k3_and_step_bindings(monkeypatch):
    for name in ("combat_step_scan", "combat_k4_eligible", "combat_k3_begin",
                 "combat_step_serial"):
        with monkeypatch.context() as mp:
            mp.delattr(_h, name)
            assert not nc.available(), name
    assert nc.available()


# ── Posed parts (native-combat posed parts, Task 4) ─────────────────────────


def test_posed_target_steer_point_native(monkeypatch):
    """Shots locked on a Bird of Prey's wing cannons with the wings swung
    for cruise: each shot's mount attributed natively (round trips, Task 4;
    was one ASK each), the steer point is the posed mount, computed
    natively -- per tick equal to Python."""
    moved = []

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            cannons = bop.GetPulseWeaponSystem()
            for i, vel in ((0, (0.0, -60.0, 0.0)), (1, (1.0, -60.0, 0.5))):
                cannon = cannons.GetWeapon(i)
                p = cannon.GetPosition()
                q = articulation.part_transform_point(
                    bop, (p.x, p.y, p.z),
                    prop=physical_parents.property_of(cannon))
                moved.append(tuple(q) != (p.x, p.y, p.z))
                w.fire(v, (10.0 + i, 115.0, 8.0), vel, target=bop,
                       offset=cannon.GetPosition())

    ref, _nat, counts = _both(monkeypatch, script, 130,
                              ships=BOP_IN_THE_PATH)
    assert moved and all(moved), moved
    assert any(c[3] == "BoP" for c in _calls(ref, "hit")), ref.calls
    _k3_ran(counts)
    assert counts["k3_asks"]["steer_point"] == 0, counts
    assert counts["k3_native_attributions"] == 2, counts
    assert counts["k3_posed_steers"] > 30, counts
    assert _steer_reasons(counts, _POSED_STEER_REASONS) == 0, counts


def test_stale_slot_falls_back_part_stale(monkeypatch):
    """With no step boundary resolving the slots, the posed target's mount
    slot stays unresolved: the steer point is Python's (ASK steer_point,
    counted part_stale), never a stale part read. Equal to Python."""
    monkeypatch.setattr(nc, "resolve_stale_part_slots", lambda ships: None)

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            cannon = bop.GetPulseWeaponSystem().GetWeapon(0)
            w.fire(v, (10.0, 115.0, 8.0), (0.0, -60.0, 0.0), target=bop,
                   offset=cannon.GetPosition())

    ref, _nat, counts = _both(monkeypatch, script, 130,
                              ships=BOP_IN_THE_PATH)
    assert any(c[3] == "BoP" for c in _calls(ref, "hit")), ref.calls
    _k3_ran(counts)
    assert counts["k3_steer_reasons"].get("part_stale", 0) > 30, counts
    assert counts["k3_steer_reasons"].get("posed_target", 0) == 0, counts
    assert counts["k3_posed_steers"] == 0, counts


# ── Manual Aim on a posed target (posed parts, Task 4b) ──────────────────────


def _wing_pick(bop, part="left wing", frac=(0.5, 0.5, 0.5)):
    """A Manual Aim pick on a Bird of Prey wing: a point inside that part's
    box the box rule gives to it, and no subsystem's mount (so _RESOLVE
    finds none and the pick is authored=False)."""
    from engine.appc import part_severance
    lo, hi = articulation.part_boxes_for("birdofprey")[part]
    p = tuple(a + f * (b - a) for a, b, f in zip(lo, hi, frac))
    assert articulation._live_part(bop, None, p, False, None) == part, p
    assert part_severance.authored_mount_subsystem(bop, p) is None, p
    return p


def _manual_moved(bop, p):
    return tuple(articulation.part_transform_point(bop, p,
                                                   authored=False)) != p


def test_manual_aim_on_posed_target_steers_natively(monkeypatch):
    """Torpedoes the Vor'cha fired at its Manual Aim pick on a Bird of
    Prey's wing (no mount there: `_mount_key` attributes None): once
    attributed, the steer point is the pick as a plain body point (fire
    control native only, M5), natively."""
    moved = []

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            v.SetTarget(bop)
            p = _wing_pick(bop)
            moved.append(_manual_moved(bop, p))
            v.set_manual_target_offset(TGPoint3(*p))
            for i, vel in ((0, (0.0, -60.0, 0.0)), (1, (1.0, -60.0, 0.5))):
                w.fire(v, (10.0 + i, 115.0, 8.0), vel, target=bop,
                       offset=TGPoint3(*p))

    ref, _nat, counts = _both(monkeypatch, script, 130,
                              ships=BOP_IN_THE_PATH)
    assert moved == [True, True], moved
    assert any(c[3] == "BoP" for c in _calls(ref, "hit")), ref.calls
    _k3_ran(counts)
    assert counts["k3_asks"]["steer_point"] == 0, counts
    assert counts["k3_native_attributions"] == 2, counts
    assert counts["k3_posed_steers"] > 30, counts
    assert _steer_reasons(counts, _POSED_STEER_REASONS) == 0, counts


def test_picked_spot_steers_at_body_point_natively(monkeypatch):
    """Fire control native only, M5 ("we dont need torpedoes to track
    articulated parts moving mid flight"): torpedoes fired at a picked spot
    on a Bird of Prey's wing (no mount) while the wings are at cruise; the
    wings then go back to the NIF pose and later to warp. Each shot steers
    at the pick as a plain body point for its whole flight -- natively, with
    no steer ASK -- and per tick equal to Python. A shot locked on a wing
    cannon (a mount) in the same scene still follows the wing."""
    seen = {}

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            p = _wing_pick(bop)
            seen["p"] = p
            # The box rule would move it at cruise: the test is not vacuous.
            seen["moved"] = _manual_moved(bop, p)
            for i, vel in ((0, (0.0, -60.0, 0.0)), (1, (1.0, -60.0, 0.5))):
                w.fire(v, (10.0 + i, 115.0, 8.0), vel, target=bop,
                       offset=TGPoint3(*p))
            cannon = bop.GetPulseWeaponSystem().GetWeapon(0)
            w.fire(v, (9.0, 115.0, 8.0), (-1.0, -60.0, 0.0), target=bop,
                   offset=cannon.GetPosition())
        elif t in (10, 20, 50):
            if t == 20:
                articulation.force_pose(bop, None)
            elif t == 50:
                articulation.force_pose(bop, "warp")
            # Python's own steer point: the pick itself, whatever the pose.
            p = seen["p"]
            got = projectiles._steer_point(w.torps[0], bop)
            seen.setdefault("plain", []).append(
                _hx(got) == _hx(subsystems.body_point_world(bop, p)))

    ref, _nat, counts = _both(monkeypatch, script, 130,
                              ships=BOP_IN_THE_PATH)
    assert seen.get("moved") is True, seen
    assert seen.get("plain") == [True] * 6, seen     # both arms, 3 ticks
    assert any(c[3] == "BoP" for c in _calls(ref, "hit")), ref.calls
    _k3_ran(counts)
    # Every shot's mount attributed natively; no steer ASK at all.
    assert counts["k3_asks"]["steer_point"] == 0, counts
    assert counts["k3_native_attributions"] == 3, counts
    assert _steer_reasons(counts, _POSED_STEER_REASONS) == 0, counts
    assert counts["k3_posed_steers"] > 30, counts


# ── Native mount attribution (round trips, Task 4) ──────────────────────────
#
# A shot's first guided tick at a new (target, offset) attributes the mount
# (`_steer_point`: `_mount_key = (target, x, y, z,
# authored_mount_subsystem(...))`). The kernel does it natively for a
# ShipClass target whose mount order it can read, and logs the `_mount_key`
# write for `_k3_apply` (quiet: no push echo). A mount it cannot tell
# (kMountUnknown) or a non-ShipClass target still ASKs.


def _quiet_mount_pushes(w, mp):
    """Count the `_mount_key` pushes made INSIDE update_all (a Python
    `_steer_point` writing the key through the TorpedoField setter)."""
    w.mount_pushes = []
    inside = [False]
    push = nc._torp_push
    update_all = projectiles.update_all

    def push_spy(t, h, name, value):
        if inside[0] and name == "_mount_key":
            w.mount_pushes.append((w.n, w.label(t)))
        return push(t, h, name, value)

    def update_spy(dt, ships, *, ship_instances=None):
        inside[0] = True
        try:
            return update_all(dt, ships, ship_instances=ship_instances)
        finally:
            inside[0] = False

    mp.setattr(nc, "_torp_push", push_spy)
    mp.setattr(projectiles, "update_all", update_spy)


def _expire_reads_mount_key(w, mp):
    """An expire() that reads the torpedo's `_mount_key` first (a stand-in
    for an ET_TORPEDO_EXITED_SET handler): into the compared call log."""
    expire = projectiles.expire

    def expire_spy(t):
        key = t.__dict__.get("_mount_key")
        w.calls.append(("expire", w.n, w.label(t), None if key is None else (
            w.label(key[0]), _hx(key[1]), _hx(key[2]), _hx(key[3]),
            w.label(key[4]))))
        return expire(t)

    mp.setattr(projectiles, "expire", expire_spy)


def test_unattributed_steer_is_native(monkeypatch):
    """Shots at a subsystem's mount and at a spot no mount claims, from both
    ships: no steer_point ASK at all -- the kernel attributes each mount
    itself and `_k3_apply` writes Python's tuple quietly: the target and
    mount OBJECTS (identity), the offset's own floats, the row's mount
    fields in step (no re-attribution next tick). One shot reaches its TTL
    on its first guided tick: expire() already sees its `_mount_key`.
    Per tick equal to Python."""
    seen = {}

    def setup(w, mp):
        _quiet_mount_pushes(w, mp)
        _expire_reads_mount_key(w, mp)

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        _move_vorcha(w, t)
        if t == 0:
            w.fire(g, (-0.5, 4.0, 0.0), (-3.0, 59.5, 1.0), target=v,
                   offset=v.GetShields().GetPosition())
            w.fire(g, (0.5, 4.0, 0.0), (2.0, 59.0, 3.0), target=v,
                   offset=TGPoint3(0.25, -1.5, 0.75))       # no mount
            w.fire(g, (0.0, 4.0, 0.5), (0.0, 60.0, 0.0), target=v,
                   offset=v.GetShields().GetPosition(), ttl=DT * 0.5)
            w.fire(v, (10.0, 115.0, 8.0), (0.0, -60.0, 0.0), target=g,
                   offset=g.GetShields().GetPosition())
            # Two mounts at one point: a child of an earlier system moved
            # onto a later top-level system's mount. The first in mount
            # order (the child) is the attribution.
            tops = [s for s in v.GetSubsystems()
                    if s is not None and s is not v.GetHull()]
            parent = next(s for s in tops if getattr(s, "_children", None))
            child = parent._children[-1]
            later = tops[tops.index(parent) + 1]
            at = later.GetPosition()
            child._position = TGPoint3(at.x, at.y, at.z)
            seen["shared"] = (child, later)
            w.fire(g, (0.25, 4.0, -0.25), (1.0, 59.5, 2.0), target=v,
                   offset=later.GetPosition())
        elif t == 1:
            t1, t2, _t3, t4, t5 = w.torps
            k1, k2, k4 = t1._mount_key, t2._mount_key, t4._mount_key
            child, later = seen["shared"]
            assert child.GetName() != later.GetName()
            seen[w.native] = (
                k1[0] is v and k1[4] is v.GetShields(),
                k2[0] is v and k2[4] is None,
                k4[0] is g and k4[4] is g.GetShields(),
                t5._mount_key[4] is child,
                tuple(type(c) for c in k1[1:4]))
            if w.native:
                row = _h.combat_torp_dump(t1._k3_row)
                o = t1._target_offset
                seen["row"] = (
                    row["mount_attributed"],
                    row["mount_sub"] == v.GetShields().__dict__["_nslot"],
                    _hx(tuple(row["mount_offset"])) == _hx(o))
                seen["key"] = _hx(tuple(k1[1:4])) == _hx(o)

    ref, nat, counts = _both(monkeypatch, script, 40, setup=setup)
    _k3_ran(counts)
    assert seen[False] == seen[True] == (True,) * 4 + ((float,) * 3,), seen
    assert seen["row"] == (1, True, True) and seen["key"], seen
    assert counts["k3_asks"]["steer_point"] == 0, counts
    assert counts["k3_native_attributions"] == 5, counts
    # The Python arm's _steer_point pushed nothing (switch off); the native
    # arm's write is quiet: no push from inside update_all.
    assert nat.mount_pushes == [], nat.mount_pushes
    expires = [c for c in ref.calls if c[0] == "expire"]
    assert expires and expires[0][3] is not None, expires


class _Unnamed:
    """A mounted subsystem the mirror cannot name (no row): -2 in the
    mount order, so the kernel cannot tell the mount (kMountUnknown)."""

    def __init__(self, p):
        self._p = p

    def GetPosition(self):
        return TGPoint3(*self._p)


def test_mount_unknown_still_asks(monkeypatch):
    """A Vor'cha whose first mount-order entry is a subsystem the mirror
    cannot name: the kernel cannot attribute the shot's offset (the
    unnamed one might match), so the steer point is Python's (ASK,
    unattributed), which writes `_mount_key` itself. Equal to Python."""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            first = next(s for s in v.GetSubsystems()
                         if s is not None and s is not v.GetHull())
            first._children = [_Unnamed((31.5, 32.5, 33.5))] + list(
                first._children)
            nc.push_mount_order(v)
            w.fire(g, (-0.5, 4.0, 0.0), (-3.0, 59.5, 1.0), target=v,
                   offset=v.GetShields().GetPosition())

    _ref, _nat, counts = _both(monkeypatch, script, 20)
    _k3_ran(counts)
    assert counts["k3_steer_reasons"]["unattributed"] == 1, counts
    assert counts["k3_native_attributions"] == 0, counts


def test_non_ship_target_still_asks(monkeypatch):
    """A guided shot with an offset at a target that is not a ShipClass (a
    hulk): its mount order is never pushed, so the kernel cannot attribute
    the mount. Such a target is never in the step scan (the scan holds
    ShipClass rows only), so its torpedo's whole _guide is Python's (ASK
    guide, target_not_in_scan) -- the attribution with it -- and none is
    made natively. (The kernel-level refusal itself is the
    ProjectileGeometry.GuideAttributesTheMountNatively gtest.) Equal to
    Python."""
    from engine.appc.objects import DamageableObject

    def setup(w, mp):
        hulk = DamageableObject()
        hulk.SetTranslateXYZ(-10.0, 120.0, 0.0)
        hulk.SetRadius(3.0)
        w.set.AddObjectToSet(hulk, "Hulk")
        w.labels[id(hulk)] = "Hulk"
        w.ships["Hulk"] = hulk

    def script(w, t):
        if t == 0:
            w.fire(w.ships["Galaxy"], (-0.5, 4.0, 0.0), (-3.0, 59.5, 1.0),
                   target=w.ships["Hulk"], offset=TGPoint3(0.5, 0.25, 0.0))

    _ref, nat, counts = _both(monkeypatch, script, 20, setup=setup)
    _k3_ran(counts)
    assert counts["k3_guide_reasons"].get("target_not_in_scan", 0) > 0, \
        counts
    assert counts["k3_native_attributions"] == 0, counts
    key = nat.torps[0].__dict__.get("_mount_key")
    assert key is not None and key[0] is nat.ships["Hulk"] \
        and key[4] is None, key


# ── THE HITS (native damage, Task 4) ────────────────────────────────────────
#
# K3 applies its hits itself (every scenario above asserts none is handed
# back, _k3_ran); what it cannot apply runs in Python in its place.


def test_a_spy_on_apply_hit_hands_every_hit_back(monkeypatch):
    """A patched combat.apply_hit is obeyed: every hit is Python's, in
    order, with the patch called once per hit in both arms."""
    seen = []

    def setup(w, mp):
        stock = combat.apply_hit

        def spy(*args, _w=w, **kw):
            seen.append(_w.native)
            return stock(*args, **kw)
        mp.setattr(combat, "apply_hit", spy)

    _ref, _nat, counts = _both(monkeypatch, _volley, 200,
                               setup=setup)
    assert counts["k3_native_hits"] == 0, counts
    assert counts["k3_hit_python_reasons"]["not_ok"] > 0, counts
    assert seen.count(True) == seen.count(False) > 0, seen


def test_an_instance_patch_on_a_hit_ships_subsystem_hands_its_hits_back(
        monkeypatch):
    """Override-guard gap 1: the Galaxy's shield generator shadows
    ApplyDamage on the instance: its hits are Python's (the patch obeyed in
    both arms); the Vor'cha's stay native."""
    seen = []

    def setup(w, mp):
        shields = w.ships["Galaxy"].GetShields()
        stock = type(shields).ApplyDamage

        def patched(face, amount, _s=shields, _w=w):
            seen.append(_w.native)
            return stock(_s, face, amount)
        mp.setattr(shields, "ApplyDamage", patched, raising=False)

    _ref, _nat, counts = _both(monkeypatch, _volley, 200,
                               setup=setup)
    assert counts["k3_hit_python_reasons"]["unscanned"] > 0, counts
    assert counts["k3_native_hits"] > 0, counts
    assert True in seen and False in seen, seen


def test_a_torpedo_shadowing_its_drf_is_handed_back(monkeypatch):
    """weapon_splash_radius reads GetDamageRadiusFactor on the torpedo: an
    instance attribute there is obeyed (the driver's own reason)."""
    seen = []

    def script(w, t):
        if t == 0:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            p = v.GetWorldLocation()
            torp = w.fire(g, (p.x, p.y - 6.0, p.z), (0.0, 60.0, 0.0))
            torp.GetDamageRadiusFactor = (
                lambda _w=w: seen.append(_w.native) or 0.75)

    ref, _nat, counts = _both(monkeypatch, script, 20)
    assert counts["k3_hit_python_reasons"]["python"] == 1, counts
    assert seen == [False, True], seen
    (hit,) = _calls(ref, "hit_present")
    assert hit[8] == _hx(0.75), hit      # its R_hit
