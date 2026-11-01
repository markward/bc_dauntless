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
from engine.appc import physical_parents  # noqa: E402
from engine.appc import projectiles  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.events import WeaponHitEvent  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.core import step_memo  # noqa: E402
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
    """A float or a point by .hex(); None as it is; anything else with its
    type, so True and 1 (or 0 and False) never compare equal."""
    if v is None:
        return None
    if isinstance(v, float):
        return v.hex()
    if isinstance(v, TGPoint3):
        return tuple(float(c).hex() for c in (v.x, v.y, v.z))
    return ("%s" % type(v).__name__, v)


class World:
    """Real ships in one set, a pinned weapon clock, the logs.

    `ships` is ((name, hardpoint, (x, y, z), yaw[, script]), ...). Built the
    same way in both arms, so labels (ship name / subsystem name) line up.
    The spies call the real function; `after_contact` hooks run after each
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
        for name, hardpoint, at, yaw, *script in ships:
            ship = App.ShipClass_Create(name)
            if script:      # lets articulation resolve the hardpoint leaf
                ship.SetScript(script[0])
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
            # A FIRING bank's stop only: a stop of a bank not firing is pure
            # field writes, which K1 logs with no call (round trips Task 2);
            # its effect is in the per-tick record.
            if bank.__dict__.get("_firing"):
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
                self.instances, _hx(kw.get("weapon_type")),
                _hx(kw.get("radius")), _hx(acted)))
            result = beam_contact(**kw)
            for hook in list(self.after_contact):
                hook(self)
            return result

        def hit_spy(target, damage, point, **kw):
            self.calls.append((
                "apply_hit", self.n, self.label(target), _hx(damage),
                _hx(point), self.label(kw.get("source")),
                _hx(kw.get("normal")), kw.get("ship_instances") is
                self.instances, _hx(kw.get("weapon_type")),
                self.label(kw.get("hardpoint_weapon")),
                _hx(kw.get("damage_hull")), _hx(kw.get("shield_point")),
                sorted(kw)))
            return apply_hit(target, damage, point, **kw)

        mp.setattr(ws.PhaserBank, "StopFiring", bank_spy)
        mp.setattr(ws.PhaserSystem, "StopFiring", sys_spy)
        # A bank's StopFiring is in K1's override guard (round trips Task 2:
        # an idle bank's stop is logged writes): the spy only wraps the stock
        # method, so for this world K1's stock snapshot takes it as stock
        # (restored with mp). K1's logged idle stops never call it.
        names, _stock = nc._k1_stock[5]
        mp.setitem(nc._k1_stock, 5,
                   (names, nc._k1_resolve(ws.PhaserBank, names)))
        mp.setattr(hit_feedback, "beam_contact", contact_spy)
        mp.setattr(combat, "apply_hit", hit_spy)

        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            row = (evt.GetEventType(), self.label(evt.GetSource()),
                   self.label(evt.GetDestination()), self.n)
            if isinstance(evt, WeaponHitEvent):
                # GetHitPoint / GetNormal: GetObjectHitPoint and
                # GetObjectHitNormal are not engine methods (a _Stub, which
                # compares equal to any _Stub).
                row += (_hx(evt.GetDamage()), _hx(evt.GetHitPoint()),
                        _hx(evt.GetNormal()))
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
                        _hx(d.get("_firing")), d.get("_target") is None,
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
# With ship scripts: articulation resolves the hardpoint leaves, so a posed
# ship's part slots can be resolved (and the kernel can walk it).
SCRIPTED_GALAXY_VORCHA = (
    ("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0, "ships.Galaxy"),
    ("Vorcha", "vorcha", (20.0, 260.0, 15.0), math.pi, "ships.Vorcha"))


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
    assert {c[11] for c in contacts} == {_hx(True), _hx(False)}
    assert any(c[6] is not None for c in contacts)      # a bubble entry
    in_120 = [c[11] for c in contacts if c[1] == 120]
    assert in_120[0] == _hx(True) and _hx(False) in in_120, in_120
    assert all(c[11] == _hx(False) for c in contacts if c[1] > 160)
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


def test_iids_sent_only_when_their_key_changes(monkeypatch):
    """The kernel keeps the ship -> instance table across steps: a begin
    sends "iids" only when the table's key (the map, its version, the drop
    epoch) changed since it was last sent. Unchanged: no "iids" at all (the
    binding rebuilt its map every begin). A mutation (version), a dropped
    row (drop epoch), another map or no map at all: sent again. The fight's
    results are the differential's to compare; this pins the traffic."""
    sent = []
    begin, set_ctx = _h.combat_k2_begin, _h.combat_k2_set_ctx

    def begin_spy(handles, dt, now, use_memo, drift, ctx):
        sent.append(("begin", ctx.get("iids")))
        return begin(handles, dt, now, use_memo, drift, ctx)

    def set_ctx_spy(ctx):
        if "iids" in ctx:
            sent.append(("set_ctx", ctx["iids"]))
        return set_ctx(ctx)

    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_iids", instances=_tracked)
        mp.setattr(_h, "combat_k2_begin", begin_spy)
        mp.setattr(_h, "combat_k2_set_ctx", set_ctx_spy)
        try:
            vorcha = w.ships["Vorcha"]
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(vorcha)
            for _ in range(3):
                w.tick()
            first = sent[0][1]
            assert sent[0][0] == "begin" and len(first) == 1, sent
            assert list(first.values()) == [w.instances[vorcha]], first
            assert sent[1:] == [("begin", None)] * 2, sent
            # A mutation between steps: the next begin sends the new table.
            del sent[:]
            w.instances[vorcha] = _h.InstanceId()
            w.tick()
            w.tick()
            assert [k for k, _ in sent] == ["begin", "begin"], sent
            assert sent[0][1] is not None and sent[1][1] is None, sent
            # A dropped row (the drop epoch): sent again.
            del sent[:]
            nc._drop(w.ships["Galaxy"].GetPhaserSystem().GetWeapon(0))
            w.tick()
            assert sent and sent[0][1] is not None, sent
            # Another map, then none: each sent once.
            del sent[:]
            w.instances = TrackedInstances({vorcha: _h.InstanceId()})
            w.tick()
            w.tick()
            assert sent[0][1] is not None and sent[1][1] is None, sent
            del sent[:]
            w.instances = None
            w.tick()
            w.tick()
            assert sent == [("begin", {}), ("begin", None)], sent
        finally:
            w.close()


def test_audit_mode_runs_the_python_step(monkeypatch):
    """With DAUNTLESS_NATIVE_AUDIT=1 every can_detect is answered by both the
    native and the Python and compared (sensor_detection._audit_can_detect);
    the kernel's own native can_detect would bypass that. So under the audit
    the whole `cb.phasers` step runs in Python (reason "audit"), and the
    fight still matches."""

    def setup(w, mp):
        if w.native:
            nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1",
                          "DAUNTLESS_NATIVE_AUDIT": "1"})
            assert nc.audit_enabled()

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 60,
                              setup=setup)
    assert _calls(ref, "beam_contact")
    assert counts.get("k2_records", 0) == 0, counts
    assert counts["k2_python_steps"] == 60, counts
    assert counts["k2_python_step_reasons"]["audit"] == 60, counts


def test_forced_part_pose_ship_runs_natively(monkeypatch):
    """A Galaxy with a part forced off its NIF pose stays native (no mount
    sits on the forced part: every slot reads "no part", the authored point
    itself), and so does the Vor'cha locking its shield generator: the
    lock's mount on the posed ship is the kernel's, no ASK aim_point. (Was
    test_posed_ship_runs_python -- RUN_PYTHON posed_ship and an ASK
    aim_point -- before posed parts went native.)"""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            g.GetPhaserSystem().StartFiring(v)
            v.SetTarget(g)
            v.SetTargetSubsystem(g.GetShields())
            v.GetPhaserSystem().StartFiring(g)
        elif t == 60:
            articulation.force_part_pose(
                g, "probe part",
                part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0))

    ref, _nat, counts = _both(monkeypatch, SCRIPTED_GALAXY_VORCHA, script,
                              140)
    assert counts["k2_python_reasons"]["posed_ship"] == 0, counts
    assert counts["k2_python_reasons"]["part_stale"] == 0, counts
    assert counts["k2_python_ships"] == 0, counts
    assert counts["k2_ask_queries"]["aim_point"] == 0, counts
    assert counts["k2_posed"]["banks"] > 0, counts
    assert counts["k2_posed"]["lock_aims"] > 0, counts
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
    assert {c[11] for c in point_blank} == {_hx(True)}, point_blank
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

# The k2_beams.h header's FULL role list ("a STOCK CLASS resolves one of its
# role's names"), written out here independently of native_combat._K2_ROLES:
# every SUBSYSTEM role (the first five) also watches the subsystem names.
_SUBSYSTEM_NAMES = ("GetWorldLocation", "GetPosition", "_climb_to_ship")
STOOD_IN_METHODS = [
    ("PhaserBank", n) for n in _SUBSYSTEM_NAMES + (
        "IsFiring", "IsBeamOn", "take_dwell", "accumulate_dwell",
        "_strip_emit_position", "_emitter_world_position", "GetLength",
        "GetDirection", "GetUp", "GetArcWidthAngles", "GetArcHeightAngles",
        "IsDisabled", "IsDestroyed")
] + [
    ("PhaserSystem", n) for n in _SUBSYSTEM_NAMES + (
        "GetNumWeapons", "GetWeapon", "GetNumChildSubsystems",
        "GetChildSubsystem", "IsOn", "IsDisabled", "IsDestroyed")
] + [
    ("ShieldSubsystem", n) for n in _SUBSYSTEM_NAMES + (
        "HasShields", "IsOn", "IsDisabled", "IsDestroyed")
] + [
    ("CloakingSubsystem", n) for n in _SUBSYSTEM_NAMES + (
        "IsCloaking", "IsDecloaking")
] + [
    ("ShipSubsystem", n) for n in _SUBSYSTEM_NAMES
] + [
    ("ShipClass", n) for n in (
        "IsDead", "GetWorldLocation", "GetWorldRotation", "GetContainingSet",
        "GetScale", "GetRadius", "GetShields", "GetPhaserSystem",
        "GetTargetSubsystem", "is_using_target_offset", "GetTargetOffsetTG",
        "GetCloakingSubsystem")
] + [
    ("ObjectClass", n) for n in (
        "IsDead", "GetWorldLocation", "GetWorldRotation", "GetContainingSet",
        "GetScale", "GetRadius", "GetShields")
]


def _class(name):
    from engine.appc import objects, ships, subsystems
    return {"PhaserBank": ws.PhaserBank, "PhaserSystem": ws.PhaserSystem,
            "ShipClass": ships.ShipClass,
            "ShipSubsystem": subsystems.ShipSubsystem,
            "ShieldSubsystem": subsystems.ShieldSubsystem,
            "CloakingSubsystem": subsystems.CloakingSubsystem,
            "ObjectClass": objects.ObjectClass}[name]


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
    orig = getattr(klass, name, None)

    def patch(mp, _w):
        if orig is None:
            # A name the stock class lacks (ObjectClass.IsDead: the stub
            # path) is watched for APPEARING.
            mp.setattr(klass, name, lambda self, *a, **k: None,
                       raising=False)
        else:
            mp.setattr(klass, name,
                       lambda self, *a, **k: orig(self, *a, **k))
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


def _py_clean(ship):
    """The per-ship clean check as the Python driver made it before it moved
    into the binding (combat_k2_scan_ships): the reference."""
    d = ship.__dict__
    seen = nc._k2_seen_set
    sys_ = d.get("_phaser_system")
    clean = type(ship) in seen and d.keys().isdisjoint(nc._K2_SHIP_PATCHES)
    if clean and sys_ is not None:
        if type(sys_) is nc._k2_stock_system:
            sd = sys_.__dict__
            clean = sd.keys().isdisjoint(nc._K2_SYSTEM_PATCHES)
            if clean:
                for b in sd.get("_children", ()):
                    if type(b) is not nc._k2_stock_bank:
                        return False
                    bd = b.__dict__
                    target = bd.get("_target")
                    if not bd.keys().isdisjoint(nc._K2_BANK_PATCHES) or (
                            target is not None
                            and type(target) not in seen):
                        return False
        else:
            clean = False
    return clean


def test_binding_scan_matches_the_python_clean_check(monkeypatch):
    """combat_k2_scan_ships (the per-ship, per-bank clean check, a C loop
    over the dicts): each ship's Object handle (-1: no row), and the ships
    that are NOT clean -- for _k2_python_ship to decide -- in order, as the
    Python check decided them. Clean, then each way a ship stops being
    clean, one at a time."""

    class Unseen:
        pass

    class SubBank(ws.PhaserBank):
        pass

    class SubSystem(ws.PhaserSystem):
        pass

    def scan(w):
        return _h.combat_k2_scan_ships(
            w.order, nc._kind("Object"), nc._KIND_SHIFT, nc._k2_seen_set,
            nc._k2_stock_system, nc._k2_stock_bank, nc._K2_SHIP_PATCHES,
            nc._K2_SYSTEM_PATCHES, nc._K2_BANK_PATCHES)

    def unclean(w):
        return [(s, nc.slot(s)) for s in w.order if not _py_clean(s)]

    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_scan")
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            g.GetPhaserSystem().StartFiring(v)
            v.GetPhaserSystem().StartFiring(g)
            w.tick()        # the stock snapshot is taken; targets set
            handles, bad = scan(w)
            assert handles == [nc.slot(s) for s in w.order], handles
            assert all(h is not None for h in handles)
            assert bad == [] == unclean(w)
            bank = g.GetPhaserSystem().GetWeapon(1)
            system = g.GetPhaserSystem()
            # (setitem: an instance attribute must be GONE afterwards; a
            # monkeypatch.setattr would put the bound method back on it.)
            cases = (
                lambda m: m.setitem(v.__dict__, "IsDead", v.IsDead),
                lambda m: m.setitem(system.__dict__, "IsOn", system.IsOn),
                lambda m: m.setitem(bank.__dict__, "take_dwell",
                                    bank.take_dwell),
                lambda m: m.setitem(bank.__dict__, "_target", Unseen()),
                lambda m: m.setattr(bank, "__class__", SubBank),
                lambda m: m.setattr(system, "__class__", SubSystem),
                lambda m: m.setattr(v, "__class__",
                                    type("Unseen", (type(v),), {})),
            )
            for i, case in enumerate(cases):
                with monkeypatch.context() as m:
                    case(m)
                    handles, bad = scan(w)
                    want = unclean(w)
                    assert want, i
                    assert bad == want, (i, bad, want)
                    assert handles == [nc.slot(s) for s in w.order], i
            # No row: -1, and never handed to the check.
            with monkeypatch.context() as m:
                m.delitem(v.__dict__, "_nslot")
                handles, bad = scan(w)
                assert handles == [nc.slot(g), nc.REF_NONE], handles
                assert bad == [], bad
            # A ship with no phaser system is clean on its own flags.
            with monkeypatch.context() as m:
                m.setitem(v.__dict__, "_phaser_system", None)
                assert scan(w)[1] == [] == unclean(w)
        finally:
            w.close()


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


# ── A target (or walked ship) whose class K2 never saw (Ruling C2, item 2) ──

def test_unseen_target_class_with_foreign_override_runs_python_step(
        monkeypatch):
    """The Vor'cha's class is swapped after it registered (no reclassify)
    to one overriding GetRadius from outside the engine: K2 never saw the
    class, and it concerns every bank aiming at the Vor'cha, so the whole
    step runs in Python."""
    from engine.appc.ships import ShipClass

    class Bigger(ShipClass):
        def GetRadius(self):
            return 2.0 * ShipClass.GetRadius(self)

    def patch(mp, w):
        mp.setattr(w.ships["Vorcha"], "__class__", Bigger)

    counts = _one_native_step(monkeypatch, patch)
    assert counts.get("k2_records", 0) == 0, counts
    assert counts["k2_python_step_reasons"]["patched"] == 1, counts


def test_unseen_target_class_sends_its_ship_to_python(monkeypatch):
    """A class K2 never saw but that overrides nothing: every ship with a
    bank aiming at an object of it runs in Python (its class flags were
    never pushed), and so does the object itself when it is a walked ship;
    the step stays native."""
    from engine.appc.ships import ShipClass

    class Unseen(ShipClass):
        pass

    def patch(mp, w):
        mp.setattr(w.ships["Vorcha"], "__class__", Unseen)

    counts = _one_native_step(monkeypatch, patch)
    assert counts["k2_records"] > 0, counts
    assert counts["k2_python_steps"] == 0, counts
    # The Galaxy (its banks aim at the Vor'cha) and the Vor'cha (walked).
    assert counts["k2_python_reasons"]["overridden"] == 2, counts


# ── host_io._h: none (no trace hooks) or a test double (Ruling C2, item 3) ──

def test_no_host_bindings_traces_nothing(monkeypatch):
    """host_io._h None (bindings not built, or a headless context): Python's
    ray_trace_mesh returns None for every instance, so a target with one
    takes the sphere tier; the kernel is told (ctx "trace" False) and must
    land on the same points natively."""

    def setup(w, mp):
        w.ships["Vorcha"].SetRadius(3.0)
        mp.setattr(host_io, "_h", None)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 90,
                              instances=_tracked, setup=setup)
    centre = _hx(ref.ships["Vorcha"].GetWorldLocation())
    points = [c[4] for c in _calls(ref, "beam_contact") if c[2] == "Vorcha"]
    assert points and all(p != centre for p in points), points
    _native_ran(counts)
    assert counts["k2_ask_queries"]["resolve_hit"] == 0, counts


def test_host_bindings_test_double_runs_python_step(monkeypatch):
    """host_io._h replaced by a test double (its own instance_translation
    and ray_trace_mesh): the kernel's installed trace is the REAL renderer's,
    not the double's, so the whole step runs in Python ("patched") and the
    double's hit is the one damaged."""

    class FakeHost:
        """The real bindings, but for the two calls the trace makes."""

        def __getattr__(self, name):
            return getattr(_h, name)

        def instance_translation(self, iid):
            return (0.0, 0.0, 0.0)

        def ray_trace_mesh(self, iid, origin, direction, max_dist):
            return (20.0, 255.0, 15.0), (0.0, 1.0, 0.0), 1.0

    def setup(w, mp):
        mp.setattr(host_io, "_h", FakeHost())

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 60,
                              instances=_tracked, setup=setup)
    hit = _hx(TGPoint3(20.0, 255.0, 15.0))
    assert {c[4] for c in _calls(ref, "beam_contact")
            if c[2] == "Vorcha"} == {hit}
    assert counts.get("k2_records", 0) == 0, counts
    assert counts["k2_python_steps"] == 60, counts
    assert counts["k2_python_step_reasons"]["patched"] == 60, counts


def test_forget_rows_forgets_the_seen_classes():
    """A test-defined ShipClass subclass is non-engine code, so K2 flags it
    "whole" and every later step runs in Python ("patched"). The conftest's
    mirror wipe (combat_clear + forget_rows) must forget the classes seen
    before it, or one such class (tests/host/test_alert_keys.py's _FakeShip)
    turned the rest of a full suite's native steps into Python steps."""
    from engine.appc.ships import ShipClass

    class _TestOnlyShip(ShipClass):
        def GetWorldRotation(self):     # a stood-in name, from a test
            return ShipClass.GetWorldRotation(self)

    nc.configure(ON)
    _TestOnlyShip()
    assert _TestOnlyShip in nc._k2_seen
    assert not nc._k2_classes_unchanged()
    _h.combat_clear()
    nc.forget_rows()
    assert _TestOnlyShip not in nc._k2_seen
    assert nc._k2_classes_unchanged()


# ── Posed parts (native-combat posed parts, Task 4) ─────────────────────────
#
# A Galaxy whose phaser banks sit on a forced "probe part" (an explicit
# physical parent; headless there are no part boxes, so the name is taken as
# given) beams natively from the pushed pose table and part slots; a lock on
# a Bird of Prey's wing cannon (in cruise) is aimed at natively.

_HINGE = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
#: A Bird of Prey ahead of the Vor'cha's bow (the Vor'cha faces -Y).
LOCK_ON_BOP = SCRIPTED_GALAXY_VORCHA + (
    ("BoP", "birdofprey", (20.0, 160.0, 15.0), 0.0, "ships.BirdOfPrey"),)


def _pose_galaxy_phasers(galaxy):
    articulation.force_part_pose(galaxy, "probe part", _HINGE)
    phasers = galaxy.GetPhaserSystem()
    for i in range(phasers.GetNumWeapons()):
        physical_parents.property_of(
            phasers.GetWeapon(i)).SetPhysicalParent("probe part")


def _moved(ship, sub):
    """`sub`'s mount, carried by its part, is off its rest point."""
    p = sub.GetPosition()
    rest = (p.x, p.y, p.z)
    q = articulation.part_transform_point(
        ship, rest, prop=physical_parents.property_of(sub))
    return tuple(q) != rest


def _port_cannon(bop):
    return bop.GetPulseWeaponSystem().GetWeapon(0)


def test_posed_ship_beams_natively(monkeypatch):
    """Every phaser bank of the Galaxy sits on a posed part: strip centres
    and arc mounts are posed natively, per tick equal to Python, and no
    ship goes to Python."""
    moved = []

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            _pose_galaxy_phasers(g)
            sys_ = g.GetPhaserSystem()
            moved.extend(_moved(g, sys_.GetWeapon(i))
                         for i in range(sys_.GetNumWeapons()))
            sys_.SetSingleFire(0)
            sys_.StartFiring(v)
        elif t == 20:
            w.ships["Vorcha"].GetPhaserSystem().StartFiring(w.ships["Galaxy"])

    ref, _nat, counts = _both(monkeypatch, SCRIPTED_GALAXY_VORCHA, script,
                              240)
    assert moved and all(moved), moved
    assert any(c[3] == "Galaxy" for c in _calls(ref, "beam_contact")), \
        "the posed Galaxy never hit"
    _native_ran(counts)
    assert counts["k2_python_ships"] == 0, counts
    assert counts["k2_python_reasons"]["posed_ship"] == 0, counts
    assert counts["k2_python_reasons"]["part_stale"] == 0, counts
    assert counts["k2_posed"]["banks"] > 0, counts


def test_lock_on_posed_ship_needs_no_aim_ask(monkeypatch):
    """The Vor'cha locks a Bird of Prey's wing cannon in cruise: the aim
    point (and the arc aim) is the posed mount on the lock's own ship,
    computed natively -- no ASK aim_point."""
    moved = []

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            moved.append(_moved(bop, _port_cannon(bop)))
            v.SetTarget(bop)
            v.SetTargetSubsystem(_port_cannon(bop))
            v.GetPhaserSystem().SetSingleFire(0)
            v.GetPhaserSystem().StartFiring(bop)

    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 200)
    assert moved == [True, True]        # both arms
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_python_ships"] == 0, counts
    assert counts["k2_ask_queries"]["aim_point"] == 0, counts
    assert counts["k2_posed"]["lock_aims"] > 0, counts


@pytest.mark.parametrize("case", ["ship", "lock"])
def test_stale_slot_falls_back_part_stale(monkeypatch, case):
    """With no step boundary resolving the slots, every one stays
    unresolved: a posed firing ship ("ship") or a lock on a posed ship
    ("lock") hands the firing ship to Python with reason part_stale --
    never posed_ship, never a stale part read. Equal to Python."""
    monkeypatch.setattr(nc, "resolve_stale_part_slots", lambda ships: None)

    def script(w, t):
        g, v, bop = w.ships["Galaxy"], w.ships["Vorcha"], w.ships["BoP"]
        if t == 0:
            if case == "ship":
                _pose_galaxy_phasers(g)
                g.GetPhaserSystem().StartFiring(v)
            else:
                articulation.force_pose(bop, "cruise")
                v.SetTarget(bop)
                v.SetTargetSubsystem(_port_cannon(bop))
                v.GetPhaserSystem().StartFiring(bop)

    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 120)
    assert _calls(ref, "beam_contact")
    assert counts["k2_python_reasons"]["part_stale"] > 0, counts
    assert counts["k2_python_reasons"]["posed_ship"] == 0, counts
    assert counts["k2_ask_queries"]["aim_point"] == 0, counts


def test_resolve_runs_at_step_boundary(monkeypatch):
    """The part slots are resolved at every step boundary a kernel reads
    them after: the step scan (K3), the held-weapon pump (K1), StartFiring's
    system session (K1, inside gl.ai) and the phaser step (K2). The
    generation is bumped right before each of them, so a missing boundary
    reads part_stale; none may."""
    callers = []
    real = nc.resolve_stale_part_slots

    def spy(ships):
        callers.append(sys._getframe(1).f_code.co_name)
        return real(ships)

    monkeypatch.setattr(nc, "resolve_stale_part_slots", spy)
    update_all = projectiles.update_all
    pump = host_loop._pump_held_weapons

    def update_then_bump(*a, **kw):
        hits = update_all(*a, **kw)
        nc.bump_part_gen()          # between K3 and the K1 pump
        return hits

    def pump_then_bump(*a, **kw):
        pump(*a, **kw)
        nc.bump_part_gen()          # between the K1 pump and K2

    monkeypatch.setattr(projectiles, "update_all", update_then_bump)
    monkeypatch.setattr(host_loop, "_pump_held_weapons", pump_then_bump)

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        nc.bump_part_gen()          # before the step scan
        if t == 0:
            articulation.force_pose(bop, "cruise")
            v.SetTarget(bop)
            v.SetTargetSubsystem(_port_cannon(bop))
            nc.bump_part_gen()      # before a StartFiring session
            v.GetPhaserSystem().StartFiring(bop)
            cannons = bop.GetPulseWeaponSystem()
            cannons.SetSingleFire(0)
            nc.bump_part_gen()
            cannons.StartFiring(v)

    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 120)
    assert {"step_scan", "k1_pump", "k1_system", "k2_phasers"} <= set(
        callers), callers
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_python_reasons"]["part_stale"] == 0, counts
    assert counts["k2_ask_queries"]["aim_point"] == 0, counts
    assert counts["k2_posed"]["lock_aims"] > 0, counts
    for session in ("pump", "system"):
        assert counts["k1_python_reasons"][session]["part_stale"] == 0, counts
    assert counts["k1_fire_ask_reasons"]["part_stale"] == 0, counts
    assert counts["k1_posed"]["walks"] > 0, counts


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


@pytest.mark.parametrize("wings", ["settled", "transition"])
def test_manual_aim_on_posed_target_native(monkeypatch, wings):
    """The Galaxy's Manual Aim pick sits on a Bird of Prey's wing (swung for
    cruise, or swinging home tick by tick): the aim point is the box rule's
    part through the Galaxy's Manual Aim slot, natively -- no ASK
    aim_point -- also after the pick moves mid-fight (re-resolved at the
    next boundary)."""
    moved = []

    def script(w, t):
        g, bop = w.ships["Galaxy"], w.ships["BoP"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            if wings == "transition":
                bop.SetTarget(g)            # red: home over the rig's 2 s
            g.SetTarget(bop)
            p = _wing_pick(bop)
            moved.append(_manual_moved(bop, p))
            g.set_manual_target_offset(TGPoint3(*p))
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(bop)
        elif t == 40:
            p = _wing_pick(bop, "left wing01", (0.4, 0.6, 0.5))
            moved.append(_manual_moved(bop, p))
            g.set_manual_target_offset(TGPoint3(*p))
        if wings == "transition":
            articulation.tick_ship(bop, DT)

    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 100)
    assert moved and all(moved), moved
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_python_ships"] == 0, counts
    assert counts["k2_ask_queries"]["aim_point"] == 0, counts
    assert counts["k2_posed"]["manual_aims"] > 0, counts


# ── Review fixes (posed parts, Task 4 fix round 1) ──────────────────────────

def _manual_aim_elsewhere(w):
    """The Galaxy fires at the Bird of Prey while its Manual Aim pick is in
    the Vor'cha's frame (its own target): the beam's aim point at the posed
    BoP is the pick through `_RESOLVE` -- no mount, and the Galaxy's Manual
    Aim slot is for the Vor'cha -- so it is Python's (ASK aim_point)."""
    g, v, bop = w.ships["Galaxy"], w.ships["Vorcha"], w.ships["BoP"]
    articulation.force_pose(bop, "cruise")
    g.GetPhaserSystem().SetSingleFire(0)
    g.GetPhaserSystem().StartFiring(bop)
    g.SetTarget(v)
    g.set_manual_target_offset(TGPoint3(0.1, 0.2, 0.0))


def test_generation_bump_inside_an_aim_answer_heals(monkeypatch):
    """An ASK aim_point answer that bumps the part-map generation (any
    trigger may fire in Python) must not leave the posed firing ship's bank
    slots stale for the GEOMETRY that follows (k2_beams.h protocol
    invariant): run_k2 re-resolves before handing the answer back. The step
    completes, equal to Python."""
    real = nc._k2_answer
    bumps = []

    def answer_then_bump(rec, *a, **kw):
        out = real(rec, *a, **kw)
        if rec[1] == "aim_point":
            nc.bump_part_gen()
            # ... and the step memo forgotten (as a hit does), so GEOMETRY
            # computes the bank's mount afresh instead of reusing K1's.
            step_memo.forget()
            bumps.append(rec[1])
        return out

    monkeypatch.setattr(nc, "_k2_answer", answer_then_bump)

    def script(w, t):
        if t == 0:
            _pose_galaxy_phasers(w.ships["Galaxy"])
            _manual_aim_elsewhere(w)

    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 60)
    assert bumps, "no aim_point ASK was answered"
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_ask_queries"]["aim_point"] > 0, counts
    assert counts["k2_python_reasons"]["part_stale"] == 0, counts
    assert counts["k2_posed"]["banks"] > 0, counts


@pytest.mark.parametrize("case", ["other_target", "stale_manual",
                                  "unnameable_lock"])
def test_remaining_aim_point_asks_match_python(monkeypatch, case):
    """The aim points that are still Python's after Manual Aim on posed
    targets went native (Task 4b), end to end: a pick whose Manual Aim slot
    is for another target ("other_target"), a pick whose slot is held stale
    for a window ("stale_manual": the generation bumped and its
    re-resolution withheld), and a lock the mirror cannot name
    ("unnameable_lock": its row dropped). Each ASKs aim_point in its window,
    per tick equal to Python."""
    window = [False]
    if case == "stale_manual":
        real = nc._resolve_manual_slot

        def resolve_unless_held(ship, h, drop=True):
            if not window[0]:
                real(ship, h, drop)

        monkeypatch.setattr(nc, "_resolve_manual_slot", resolve_unless_held)

    def script(w, t):
        g, v, bop = w.ships["Galaxy"], w.ships["Vorcha"], w.ships["BoP"]
        if case == "other_target":
            if t == 0:
                _manual_aim_elsewhere(w)
            return
        if case == "stale_manual":
            if t == 0:
                articulation.force_pose(bop, "cruise")
                g.SetTarget(bop)
                g.set_manual_target_offset(TGPoint3(*_wing_pick(bop)))
                g.GetPhaserSystem().SetSingleFire(0)
                g.GetPhaserSystem().StartFiring(bop)
            window[0] = 30 <= t < 60
            if t == 30:
                nc.bump_part_gen()
            return
        cannon = _port_cannon(bop)
        if t == 0:
            articulation.force_pose(bop, "cruise")
            v.SetTarget(bop)
            v.SetTargetSubsystem(cannon)
            v.GetPhaserSystem().SetSingleFire(0)
            v.GetPhaserSystem().StartFiring(bop)
        elif t == 30:
            nc._drop(cannon)        # native arm only: the off arm has no row

    asks = []
    real_answer = nc._k2_answer

    def count(rec, *a, **kw):
        if rec[1] == "aim_point":
            asks.append(window[0] if case == "stale_manual" else True)
        return real_answer(rec, *a, **kw)

    monkeypatch.setattr(nc, "_k2_answer", count)
    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 90)
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_ask_queries"]["aim_point"] > 0, counts
    assert all(asks), "an aim_point ASK outside the window"
    if case == "stale_manual":
        assert counts["k2_posed"]["manual_aims"] > 0, counts
    if case == "unnameable_lock":
        assert counts["k2_posed"]["lock_aims"] > 0, counts
