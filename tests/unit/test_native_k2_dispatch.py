"""K2 dispatch: the `cb.phasers` step runs through the native beam kernel when
native combat is on (native combat phase 2, Task 5; plan
docs/superpowers/plans/2026-10-31-native-combat-k2-beams.md).

Each scenario runs twice on fresh real ships -- native off (today's Python
loop body, host_loop._phaser_step_ship) and native on (K2 decides, Python runs
only the effects through native_combat.run_k2) -- through the whole combat
step (host_loop._advance_combat), and compares after every tick:

- every phaser bank's (`_dwell.hex()`, `_firing`, `_target is None`);
- the call log of every StopFiring (bank and system), every
  hit_feedback.beam_contact (arguments by .hex(), and the shields_block it
  acted on: the kwarg when given, else its own evaluation) and every
  combat.apply_hit (arguments by .hex());
- the event log (every AddEvent: type, source, destination, tick, order; a
  weapon hit's damage, point and normal by .hex()).

The native arm must also show that K2 really walked (its record count) or,
for the fallback scenarios, that it did not, and its mirror must still equal
the Python at the end (audit_mirror).
"""
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
    _h is None or not hasattr(_h, "combat_k2_next"),
    reason="native K2 bindings not built")

from engine import host_io  # noqa: E402
from engine import host_loop  # noqa: E402
from engine.appc import articulation  # noqa: E402
from engine.appc import combat  # noqa: E402
from engine.appc import hit_feedback  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_pose  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import passive_weapons  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.events import WeaponHitEvent  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.core.tracked_instances import TrackedInstances  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
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
    """A float or a point by .hex(); None and others as they are."""
    if v is None:
        return None
    if isinstance(v, float):
        return v.hex()
    if isinstance(v, TGPoint3):
        return tuple(float(c).hex() for c in (v.x, v.y, v.z))
    return ("%s" % type(v).__name__, v)


class World:
    """Real ships in one set, a pinned weapon clock, the logs.

    `ships` is ((name, hardpoint, (x, y, z), yaw), ...). Built the same way
    in both arms, so labels (ship name / subsystem name) line up. The spies
    call the real function; `after_contact` hooks run after each
    beam_contact (a stand-in for an effect's handler)."""

    def __init__(self, mp, native, ships, tag, instances=None):
        nc.reset()
        if native:
            nc.configure(ON)
            assert nc.enabled()
        self.native = native
        self.clock = [100.0]
        mp.setattr(ws, "_game_time", lambda: self.clock[0])
        self.set = App.SetClass_Create()
        self.tag = tag
        App.g_kSetManager.AddSet(self.set, tag)
        self.ships = {}
        for name, hardpoint, at, yaw in ships:
            ship = App.ShipClass_Create(name)
            _load_hardpoint(ship, hardpoint)
            ship.SetTranslateXYZ(*at)
            m = TGMatrix3()
            m.MakeZRotation(yaw)
            ship.SetMatrixRotation(m)
            self.set.AddObjectToSet(ship, name)
            self.ships[name] = ship
            phasers = ship.GetPhaserSystem()
            if phasers is not None:
                phasers.TurnOn()
        # The Galaxy is the player: the viewing set is this set, so the
        # view-offset table K2 is handed names it (frames.viewing_set).
        mp.setattr(App, "Game_GetCurrentPlayer",
                   lambda p=self.ships["Galaxy"]: p)
        self.order = list(self.ships.values())
        self.instances = (instances(self) if instances is not None
                          else None)
        self.labels = {}
        self.banks = []
        for s in self.order:
            self.labels[id(s)] = s.GetName()
            g = s.GetPhaserSystem()
            if g is None:
                continue
            self.labels[id(g)] = "%s/%s" % (s.GetName(), g.GetName())
            for i in range(g.GetNumWeapons()):
                b = g.GetWeapon(i)
                self.labels[id(b)] = "%s/%s" % (s.GetName(), b.GetName())
                self.banks.append(b)
        self.n = 0
        self.log = []
        self.calls = []
        self.events = []
        self.after_contact = []
        self._spy(mp)

    def _spy(self, mp):
        bank_stop = ws.PhaserBank.StopFiring
        sys_stop = ws.PhaserSystem.StopFiring
        beam_contact = hit_feedback.beam_contact
        apply_hit = combat.apply_hit

        def bank_spy(bank, _orig=bank_stop):
            self.calls.append(("bank_stop", self.n, self.label(bank)))
            return _orig(bank)

        def sys_spy(sys_, *args, _orig=sys_stop):
            self.calls.append(("system_stop", self.n, self.label(sys_)))
            return _orig(sys_, *args)

        def contact_spy(**kw):
            # What it acts on: the kwarg (K2 passes the loop's answer) or its
            # own evaluation (the Python path; K2 when the loop had none).
            if "shields_block" in kw:
                acted = kw["shields_block"]
            else:
                acted = bool(combat.shields_block(kw["ship"]))
            self.calls.append((
                "beam_contact", self.n, self.label(kw["ship"]),
                self.label(kw["source"]), _hx(kw["point"]),
                _hx(kw["normal"]), _hx(kw["shield_point"]),
                _hx(kw["tick_damage"]), kw["ship_instances"] is
                self.instances, kw.get("weapon_type"), _hx(kw.get("radius")),
                acted))
            result = beam_contact(**kw)
            for hook in list(self.after_contact):
                hook(self)
            return result

        def hit_spy(target, damage, point, **kw):
            self.calls.append((
                "apply_hit", self.n, self.label(target), _hx(damage),
                _hx(point), self.label(kw.get("source")),
                _hx(kw.get("normal")), kw.get("ship_instances") is
                self.instances, kw.get("weapon_type"),
                self.label(kw.get("hardpoint_weapon")),
                kw.get("damage_hull"), _hx(kw.get("shield_point")),
                sorted(kw)))
            return apply_hit(target, damage, point, **kw)

        mp.setattr(ws.PhaserBank, "StopFiring", bank_spy)
        mp.setattr(ws.PhaserSystem, "StopFiring", sys_spy)
        mp.setattr(hit_feedback, "beam_contact", contact_spy)
        mp.setattr(combat, "apply_hit", hit_spy)

        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            row = (evt.GetEventType(), self.label(evt.GetSource()),
                   self.label(evt.GetDestination()), self.n)
            if isinstance(evt, WeaponHitEvent):
                row += (_hx(float(evt.GetDamage())),
                        _hx(evt.GetObjectHitPoint()),
                        _hx(evt.GetObjectHitNormal()))
            self.events.append(row)
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    def label(self, obj):
        if obj is None:
            return None
        return self.labels.get(id(obj), type(obj).__name__)

    def close(self):
        App.g_kSetManager.DeleteSet(self.tag)
        if getattr(self, "cleanup", None) is not None:
            self.cleanup()

    def record(self):
        row = []
        for b in self.banks:
            d = b.__dict__
            row.append((self.label(b), d.get("_dwell").hex(),
                        d.get("_firing"), d.get("_target") is None,
                        self.label(d.get("_target"))))
        for s in self.order:
            row.append((self.label(s),
                        _hx(float(s.GetHull().GetCondition()))))
        self.log.append(row)

    def tick(self, before=None):
        """One host tick: the weapons' own update, then the whole combat
        step (K1's pump, then `cb.phasers`)."""
        self.n += 1
        self.clock[0] += DT
        if before is not None:
            before(self)
        for s in self.order:
            passive_weapons.step_every_weapon(s, DT)
        host_loop._advance_combat(list(self.order), DT,
                                  ship_instances=self.instances,
                                  push_render_data=False)
        self.record()


def _both(monkeypatch, ships, script, ticks, instances=None, setup=None):
    """Run `script(world, tick)` before each of `ticks` ticks, native off
    then on; compare. Returns (reference world, native world, native
    counts)."""
    worlds = []
    counts = None
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = World(mp, native, ships, "k2_%d" % native,
                      instances=instances)
            try:
                if setup is not None:
                    setup(w, mp)
                for t in range(ticks):
                    w.tick(before=lambda w, t=t: script(w, t))
                if native:
                    counts = nc.counts()
                    nc.audit_mirror()
                    assert nc.audit_failures() == [], nc.audit_failures()
                    assert not _h.combat_k2_open()
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


def _native_ran(counts):
    assert counts.get("k2_records", 0) > 0, counts
    assert counts.get("k2_python_steps", 0) == 0, counts


GALAXY_VORCHA = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
                 ("Vorcha", "vorcha", (20.0, 260.0, 15.0), math.pi))


# ── Scenarios ────────────────────────────────────────────────────────────────

def test_beam_volley_matches(monkeypatch):
    """A Galaxy holds its phasers on a Vor'cha, which fires back: banks
    light, wind up, contact, flush pulses and run dry."""

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])
        elif t == 20:
            w.ships["Vorcha"].GetPhaserSystem().StartFiring(w.ships["Galaxy"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 240)
    assert _calls(ref, "beam_contact") and _calls(ref, "apply_hit")
    assert any(e[0] == App.ET_WEAPON_HIT for e in ref.events)
    _native_ran(counts)
    assert counts["k2_python_ships"] == 0, counts


def _banks_in_arc(ship, target):
    """The phaser banks of `ship` whose arc holds `target`."""
    sys_ = ship.GetPhaserSystem()
    banks = [sys_.GetWeapon(i) for i in range(sys_.GetNumWeapons())]
    return [b for b in banks if ws._emitter_in_arc(
        b, ship, ws._resolve_bank_aim_world(b, target))]


def test_windup_and_flush_matches(monkeypatch):
    """Lit banks stopped with dwell banked flush a final partial pulse (the
    flush path: no can_detect, no arc test). Then a bank is lit by hand (no
    held trigger, so the pump leaves it to `cb.phasers`) and the target is
    swept astern: the arc fails, the bank stops and its partial pulse lands
    with this tick's aim."""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
        elif t == 75:
            g.GetPhaserSystem().StopFiring()
        elif t == 100:
            bank = _banks_in_arc(g, v)[0]
            bank._target = v
            bank._firing = True
            bank._beam_on_countdown = ws.BEAM_ON_DELAY_S
        elif t == 160:
            v.SetTranslateXYZ(-15.0, -240.0, 10.0)

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 200)
    hits = [c[1] for c in _calls(ref, "apply_hit")]
    assert 76 in hits, hits                     # the flush path
    assert 161 in hits, hits                    # the arc fail's pulse
    assert ("bank_stop", 161) in {c[:2] for c in ref.calls}
    _native_ran(counts)


def test_lock_and_manual_aim_match(monkeypatch):
    """A subsystem lock aims at the lock's mount (and the arc at it); then
    Manual Aim's offset wins; then the lock is dropped."""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            g.SetTarget(v)
            g.SetTargetSubsystem(v.GetShields())
            g.GetPhaserSystem().StartFiring(v)
        elif t == 90:
            g.set_manual_target_offset(TGPoint3(1.5, -2.0, 0.25))
        elif t == 150:
            g.UseTargetOffsetTG(0)
            g.SetTargetSubsystem(None)

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 200)
    points = {c[4] for c in _calls(ref, "beam_contact")}
    assert len(points) >= 3, points
    _native_ran(counts)


def test_shields_drop_mid_volley(monkeypatch):
    """The Vor'cha has a hull box (so the beam meets its bubble) and shields
    up. In the middle of tick 120 a handler turns the disable-NPC-shields
    cheat on (K2 learns it through the re-sent context): the banks after it
    no longer stop at the bubble. At tick 130 it is off again; at 160 the
    shields go off for good."""
    import engine.dev_combat_cheats as cheats
    import engine.dev_mode as dev_mode

    def setup(w, mp):
        w.ships["Vorcha"]._shield_hull_box = ((0.0, 0.5, 0.0),
                                              (1.2, 2.5, 0.6))
        mp.setattr(dev_mode, "is_enabled", lambda: True)
        mp.setattr(cheats, "_disable_npc_shields", False)
        nc.push_globals()       # the mirror's dev_mode global follows it

        def cheat_on(world):
            if world.n == 120:
                cheats._disable_npc_shields = True
        w.after_contact.append(cheat_on)

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if w.n == 1:
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
        elif w.n == 130:
            cheats._disable_npc_shields = False
        elif w.n == 160:
            v.GetShields().TurnOff()

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 220,
                              setup=setup)
    contacts = _calls(ref, "beam_contact")
    assert {c[11] for c in contacts} == {True, False}
    assert any(c[6] is not None for c in contacts)      # a bubble entry
    in_120 = [c[11] for c in contacts if c[1] == 120]
    assert in_120[0] is True and False in in_120, in_120
    assert all(c[11] is False for c in contacts if c[1] > 160)
    _native_ran(counts)
    assert counts["k2_ask_queries"]["shields_block"] == 0, counts


def test_off_system_stops_every_tick(monkeypatch):
    """A powered-off phaser system is stopped EVERY tick (no "already
    stopped" short cut), and a disabled one too."""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            g.GetPhaserSystem().StartFiring(v)
        elif t == 30:
            g.GetPhaserSystem().TurnOff()
        elif t == 60:
            g.GetPhaserSystem().TurnOn()
            g.GetPhaserSystem().StartFiring(v)
        elif t == 90:
            for i in range(g.GetPhaserSystem().GetNumWeapons()):
                g.GetPhaserSystem().GetWeapon(i).SetCondition(0.0)

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 120)
    stops = {c[1] for c in _calls(ref, "system_stop")
             if c[2].startswith("Galaxy/")}
    assert set(range(32, 60)) <= stops, sorted(stops)
    assert set(range(92, 121)) <= stops, sorted(stops)
    _native_ran(counts)


def _tracked(w):
    return TrackedInstances({w.ships["Vorcha"]: _h.InstanceId()})


def test_patched_trace_runs_python_step(monkeypatch):
    """A test's patched host_io.ray_trace_mesh is a function K2 stands in
    for: with it patched, the whole `cb.phasers` step runs in Python, so the
    patched hit point is the one damaged."""

    def setup(w, mp):
        def fake_trace(iid, origin, direction, max_dist, rest_pose=False):
            p = w.ships["Vorcha"].GetWorldLocation()
            return (p.x + 0.25, p.y - 1.0, p.z + 0.125), (0.0, -1.0, 0.0), 1.0
        mp.setattr(host_io, "ray_trace_mesh", fake_trace)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 90,
                              instances=_tracked, setup=setup)
    normals = {c[5] for c in _calls(ref, "beam_contact")}
    assert normals == {_hx(TGPoint3(0.0, -1.0, 0.0))}, normals
    assert counts.get("k2_records", 0) == 0, counts
    assert counts.get("k2_python_steps", 0) == 90, counts
    assert counts["k2_python_step_reasons"]["patched"] == 90, counts


def test_sentinel_instances_dict_runs_python_step(monkeypatch):
    """`ship_instances` that is not the session's TrackedInstances (a test's
    plain dict) runs the whole step in Python."""

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(
        monkeypatch, GALAXY_VORCHA, script, 60,
        instances=lambda w: {w.ships["Vorcha"]: _h.InstanceId()})
    assert _calls(ref, "beam_contact")
    assert counts.get("k2_records", 0) == 0, counts
    assert counts["k2_python_step_reasons"]["instances"] == 60, counts


def test_instances_resent_after_mutation(monkeypatch):
    """A handler pops the target from `ship_instances` in the middle of a
    step: the banks after it must see "no instance" (the fallback point),
    the ones before it saw a non-InstanceId (the sphere tier). K2 learns it
    through the re-sent context (TrackedInstances.version), and the sphere
    radius makes the two tiers land on different points. Later the entry
    comes back."""

    def setup(w, mp):
        w.ships["Vorcha"].SetRadius(3.0)

        def pop_then_restore(world):
            v = world.ships["Vorcha"]
            if world.n == 70 and v in world.instances:
                world.instances.pop(v)
            elif world.n == 100 and v not in world.instances:
                world.instances[v] = _h.InstanceId()
        w.after_contact.append(pop_then_restore)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 130,
                              instances=_tracked, setup=setup)
    at = {}
    for c in _calls(ref, "beam_contact"):
        at.setdefault(c[1], []).append(c[4])
    # Several banks touch at tick 70: the first saw a stale InstanceId (the
    # trace raises: the sphere tier), the rest no instance (the fallback
    # point IS the aim point, here the Vor'cha's centre). The scenario tells
    # the two apart.
    centre = _hx(ref.ships["Vorcha"].GetWorldLocation())
    assert at[70][0] != centre and len(at[70]) > 1, at[70]
    assert all(p == centre for p in at[70][1:]), at[70]
    # Restored after tick 100's first contact: the sphere tier again.
    assert at[100][0] == centre and at[100][1] != centre, at[100]
    assert all(p != centre for p in at[101]), at[101]
    _native_ran(counts)
    # The kernel traced (the viewing set has its offset): no ASK.
    assert counts["k2_ask_queries"]["resolve_hit"] == 0, counts


def test_posed_ship_runs_python(monkeypatch):
    """A Galaxy with a part forced off its NIF pose is handed to Python whole
    (RUN_PYTHON, posed_ship); the Vor'cha firing at it stays native."""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            g.GetPhaserSystem().StartFiring(v)
            # The Vor'cha locks the Galaxy's shield generator: once the
            # Galaxy is posed, the lock's mount is Python's (ASK aim_point).
            v.SetTarget(g)
            v.SetTargetSubsystem(g.GetShields())
            v.GetPhaserSystem().StartFiring(g)
        elif t == 60:
            articulation.force_part_pose(
                g, "probe part",
                part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0))

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 140)
    assert counts["k2_python_reasons"]["posed_ship"] > 0, counts
    assert counts["k2_ask_queries"]["aim_point"] > 0, counts
    _native_ran(counts)
    assert any(c[1] > 60 and c[3] == "Galaxy"
               for c in _calls(ref, "beam_contact"))


def test_point_blank_contact_omits_shields_kwarg(monkeypatch):
    """A bank whose emit point IS the target point (distance 0): no aim
    direction, so the loop never asks shields_block; beam_contact must
    evaluate its own (the kwarg omitted), and with the Vor'cha's shields up
    it splashes the bubble."""

    def setup(w, mp):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        phasers = g.GetPhaserSystem()
        bank = phasers.GetWeapon(0)
        bank._length = 0.0
        mount = bank.GetWorldLocation()
        v.SetTranslateXYZ(mount.x, mount.y, mount.z)
        bank._firing = True
        bank._target = v
        bank._beam_on_countdown = 1.0       # still winding up: no drain
        bank._dwell = 0.0
        w.point_blank = bank

    def script(w, t):
        w.point_blank._beam_on_countdown = 1.0

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 5,
                              setup=setup)
    point_blank = [c for c in _calls(ref, "beam_contact")
                   if c[3] == "Galaxy"]
    assert point_blank, ref.calls
    assert {c[11] for c in point_blank} == {True}, point_blank
    _native_ran(counts)


def _light(bank, target, countdown=1.0):
    """Light `bank` at `target` by hand (no held trigger: the pump leaves
    it to `cb.phasers`), still winding up (no drain, no pulse)."""
    bank._target = target
    bank._firing = True
    bank._beam_on_countdown = countdown


def test_asks_answered_in_python(monkeypatch):
    """Targets the mirror cannot answer for, each with a bank lit at it: a
    Planet has no real IsDead (ASK is_dead: the stub reads dead, so the
    firing bank stops); a bare DamageableObject has a real IsDead but no
    real GetShields (ASK shields_block, then ASK bubble; beam_contact then
    evaluates its own, as the Python path does). Every stub attribute hit
    (stub telemetry) is counted the same in both arms: the native arm asks
    Python exactly the calls the Python loop makes, no more, no fewer."""
    from engine.appc.objects import DamageableObject
    from engine.core import stub_telemetry
    hits = []

    def setup(w, mp):
        mp.setattr(stub_telemetry, "ENABLED", True)     # no atexit report
        stub_telemetry.reset()
        w.cleanup = lambda: hits.append(
            stub_telemetry.snapshot()["attr_hits"])
        planet = App.Planet_Create(5.0, "")
        planet.SetTranslateXYZ(-30.0, 220.0, 5.0)
        w.set.AddObjectToSet(planet, "Planet")
        hulk = DamageableObject()
        hulk.SetTranslateXYZ(30.0, 200.0, -5.0)
        w.set.AddObjectToSet(hulk, "Hulk")
        w.labels[id(planet)] = "Planet"
        w.labels[id(hulk)] = "Hulk"
        w.targets = (planet, hulk)

    def script(w, t):
        g = w.ships["Galaxy"]
        planet, hulk = w.targets
        if t == 0:
            a = _banks_in_arc(g, planet)[0]
            b = [x for x in _banks_in_arc(g, hulk) if x is not a][0]
            w.lit = (a, b)
            _light(a, planet)
            _light(b, hulk)
        for bank in w.lit:
            bank._beam_on_countdown = 1.0

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 30,
                              setup=setup)
    assert any(c[0] == "bank_stop" and c[1] == 1 for c in ref.calls)
    assert any(c[0] == "beam_contact" and c[2] == "Hulk" for c in ref.calls)
    _native_ran(counts)
    asks = counts["k2_ask_queries"]
    assert asks["is_dead"] > 0 and asks["shields_block"] > 0, asks
    stub_telemetry.reset()
    python_hits, native_hits = hits
    assert python_hits and native_hits == python_hits, (python_hits,
                                                        native_hits)


def test_unviewed_set_asks_resolve_hit(monkeypatch):
    """The player is in another set, so the fight's set has no entry in the
    view-offset table: a target with an instance is traced by Python
    (ASK resolve_hit), exactly as _resolve_hit_point does it."""

    def setup(w, mp):
        other = App.SetClass_Create()
        App.g_kSetManager.AddSet(other, w.tag + "_other")
        player = App.ShipClass_Create("Elsewhere")
        _load_hardpoint(player, "vorcha")
        other.AddObjectToSet(player, "Elsewhere")
        mp.setattr(App, "Game_GetCurrentPlayer", lambda: player)
        w.ships["Vorcha"].SetRadius(3.0)
        w.cleanup = lambda: App.g_kSetManager.DeleteSet(w.tag + "_other")

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 60,
                              instances=_tracked, setup=setup)
    _native_ran(counts)
    assert counts["k2_ask_queries"]["resolve_hit"] > 0, counts


def test_dropped_row_mid_walk_asks_bank_step(monkeypatch):
    """A handler drops the target's mirror row after the first contact of a
    step: the Galaxy's later banks cannot be walked natively, so each is
    run in Python (ASK bank_step); from the next step its whole ship is
    (the pre-scan: an unnameable target)."""

    def setup(w, mp):
        def drop(world):
            if world.n == 50 and "_nslot" in world.ships["Vorcha"].__dict__:
                nc._drop(world.ships["Vorcha"])     # harmless when off
        w.after_contact.append(drop)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 70,
                              setup=setup)
    assert sum(1 for c in _calls(ref, "beam_contact") if c[1] == 50) > 1
    assert counts["k2_records"] > 0, counts
    assert counts["k2_ask_queries"]["bank_step"] > 0, counts
    assert counts["k2_python_ships"] > 0, counts


# ── Every stood-in function is watched ──────────────────────────────────────

# Listed HERE, independently of native_combat's own list: dropping one from
# the module's snapshot fails its case.
STOOD_IN = [
    ("engine.host_io", "ray_trace_mesh"),
    ("engine.appc.combat", "_resolve_hit_point"),
    ("engine.appc.combat", "ray_sphere_entry"),
    ("engine.appc.combat", "shields_block"),
    ("engine.appc.combat", "shield_bubble_entry"),
    ("engine.appc.combat", "cloak_shields_suspended"),
    ("engine.appc.combat", "_hull_box_for"),
    ("engine.appc.combat", "_body_frame_delta"),
    ("engine.appc.collisions", "world_radius"),
    ("engine.host_loop", "_phaser_aim_point"),
    ("engine.host_loop", "_phaser_step_ship"),
    ("engine.host_loop", "_phaser_step_bank"),
    ("engine.host_loop", "can_detect"),
    ("engine.host_loop", "_same_set"),
    ("engine.host_loop", "_emitter_in_arc"),
    ("engine.host_loop", "_resolve_bank_aim_world"),
    ("engine.host_loop", "_is_offline"),
    ("engine.systems.frames", "view_offset"),
    ("engine.systems.frames", "shifted"),
    ("engine.systems.frames", "containing_set"),
    ("engine.appc.subsystems", "subsystem_world_position"),
    ("engine.appc.subsystems", "target_offset_world"),
    ("engine.appc.subsystems", "_is_offline"),
    ("engine.appc.weapon_subsystems", "_resolve_bank_aim_world"),
    ("engine.appc.weapon_subsystems", "_emitter_in_arc"),
    ("engine.appc.weapon_subsystems", "_same_set"),
    ("engine.appc.sensor_detection", "can_detect"),
]

STOOD_IN_METHODS = [
    ("PhaserBank", n) for n in (
        "IsFiring", "IsBeamOn", "take_dwell", "accumulate_dwell",
        "_strip_emit_position", "_emitter_world_position", "GetLength")
] + [
    ("PhaserSystem", n) for n in (
        "GetNumWeapons", "GetWeapon", "IsOn", "IsDisabled", "IsDestroyed")
] + [
    ("ShipClass", n) for n in (
        "GetPhaserSystem", "GetTargetSubsystem", "is_using_target_offset",
        "GetTargetOffsetTG", "GetShields", "IsDead", "GetWorldLocation",
        "GetWorldRotation")
] + [
    ("ShipSubsystem", "GetWorldLocation"),
] + [
    ("ShieldSubsystem", n) for n in ("HasShields", "IsOn", "IsDisabled",
                                    "IsDestroyed")
]


def _class(name):
    from engine.appc import ships, subsystems
    return {"PhaserBank": ws.PhaserBank, "PhaserSystem": ws.PhaserSystem,
            "ShipClass": ships.ShipClass,
            "ShipSubsystem": subsystems.ShipSubsystem,
            "ShieldSubsystem": subsystems.ShieldSubsystem}[name]


def _one_native_step(monkeypatch, patch):
    """One combat step native and unpatched (K2 must walk), then
    `patch(mp, world)` and one more step: that step's counts. Both ships
    fire, so an override on one ship leaves the other native."""
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_watch",
                  instances=lambda w: TrackedInstances())
        try:
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])
            w.ships["Vorcha"].GetPhaserSystem().StartFiring(w.ships["Galaxy"])
            w.tick()
            assert nc.counts().get("k2_records", 0) > 0, nc.counts()
            nc.reset()
            nc.configure(ON)
            patch(mp, w)
            w.tick()
            return nc.counts()
        finally:
            w.close()


@pytest.mark.parametrize("module,name", STOOD_IN,
                         ids=["%s.%s" % mn for mn in STOOD_IN])
def test_every_stood_in_function_is_watched(monkeypatch, module, name):
    mod = importlib.import_module(module)
    orig = getattr(mod, name)

    def patch(mp, _w):
        mp.setattr(mod, name, lambda *a, **k: orig(*a, **k))
    counts = _one_native_step(monkeypatch, patch)
    assert counts.get("k2_records", 0) == 0, counts
    assert counts["k2_python_step_reasons"]["patched"] == 1, counts


@pytest.mark.parametrize("cls,name", STOOD_IN_METHODS,
                         ids=["%s.%s" % cn for cn in STOOD_IN_METHODS])
def test_every_stood_in_method_is_watched(monkeypatch, cls, name):
    klass = _class(cls)
    orig = getattr(klass, name)

    def patch(mp, _w):
        mp.setattr(klass, name, lambda self, *a, **k: orig(self, *a, **k))
    counts = _one_native_step(monkeypatch, patch)
    assert counts.get("k2_records", 0) == 0, counts
    assert counts["k2_python_step_reasons"]["patched"] == 1, counts


def test_instance_patch_sends_its_ship_to_python(monkeypatch):
    """An instance attribute shadowing a stood-in method on a ship, its
    phaser system or a bank sends THAT ship to Python (python_ships); the
    rest of the step stays native."""
    for owner, name in (("ship", "GetTargetSubsystem"), ("system", "IsOn"),
                        ("bank", "take_dwell")):
        def patch(mp, w, owner=owner, name=name):
            g = w.ships["Galaxy"]
            obj = {"ship": g, "system": g.GetPhaserSystem(),
                   "bank": g.GetPhaserSystem().GetWeapon(0)}[owner]
            mp.setattr(obj, name, getattr(obj, name), raising=False)

        counts = _one_native_step(monkeypatch, patch)
        assert counts["k2_records"] > 0, (owner, counts)
        assert counts["k2_python_reasons"]["overridden"] == 1, (owner, counts)


def test_subclass_override_sends_its_ship_to_python(monkeypatch):
    """A PhaserBank subclass overriding a K2-only method (not a K1 one, so
    the mirror's k1_overridden does not catch it) sends its ship to Python."""

    class SlowDwell(ws.PhaserBank):
        def take_dwell(self):
            return ws.PhaserBank.take_dwell(self)

    def patch(mp, w):
        bank = w.ships["Galaxy"].GetPhaserSystem().GetWeapon(0)
        mp.setattr(bank, "__class__", SlowDwell)

    counts = _one_native_step(monkeypatch, patch)
    assert counts["k2_records"] > 0, counts
    assert counts["k2_python_reasons"]["overridden"] == 1, counts


# ── The CONTACT record's points keep Python's object identity ───────────────

def test_contact_points_keep_tier_identity():
    """`_k2_points` rebuilds a CONTACT's points as the Python made them: the
    fallback tier's impact IS target_pos, the origin tier's IS emitter_pos,
    the mesh and sphere tiers' are their own points; a missing normal or
    bubble is None."""
    e, t = (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)
    for tier, impact in (("fallback", t), ("origin", e),
                         ("mesh", (7.0, 8.0, 9.0)),
                         ("sphere", (7.5, 8.5, 9.5))):
        normal = (0.0, 1.0, 0.0) if tier == "mesh" else None
        bubble = (1.5, 2.5, 3.5) if tier == "sphere" else None
        emitter, target_pos, point, n, b = nc._k2_points(
            e, t, impact, normal, tier, bubble)
        assert isinstance(point, TGPoint3)
        assert _hx(point) == _hx(TGPoint3(*impact))
        assert (point is target_pos) == (tier == "fallback"), tier
        assert (point is emitter) == (tier == "origin"), tier
        assert _hx(emitter) == _hx(TGPoint3(*e))
        assert _hx(target_pos) == _hx(TGPoint3(*t))
        assert (n is None) == (normal is None)
        assert (b is None) == (bubble is None)
        if n is not None:
            assert isinstance(n, TGPoint3) and _hx(n) == _hx(TGPoint3(*normal))
        if b is not None:
            assert isinstance(b, TGPoint3) and _hx(b) == _hx(TGPoint3(*bubble))
