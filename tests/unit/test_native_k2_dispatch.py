"""K2 dispatch: the `cb.phasers` step runs through the native beam kernel when
native combat is on (native combat phase 2, Task 5; plan
docs/superpowers/plans/2026-10-31-native-combat-k2-beams.md).

Each scenario runs twice on fresh real ships -- native off (today's Python
loop body, host_loop._phaser_step_ship) and native on (K2 decides, Python runs
only the effects through native_combat.run_k2) -- through the whole combat
step (host_loop._advance_combat), and compares after every tick:

- every phaser bank's (`_dwell.hex()`, `_firing`, `_target is None`,
  `_beam_on_countdown`) and every phaser system's held-fire state (what an
  offline stop writes);
- the call log of every StopFiring (bank and system) that runs with a bank
  firing (an idle one is logged writes, round trips Tasks 2-3) and every
  combat.apply_hit (arguments by .hex()), in order; and every
  hit_feedback.beam_contact (arguments by .hex(), and the shields_block it
  acted on: the kwarg when given, else its own evaluation) -- presentation,
  compared per tick as a multiset (ruling Q1, spec 2026-11-02 §5: K2
  presents resting contacts after the step's last record);
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
from engine.appc import effect_queue  # noqa: E402
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
from tests.helpers.k3_fight import (  # noqa: E402
    ShieldedContact, capture_native_shield_hits, compare_calls, contact_row,
    spy_hits)

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


def _k1_stop() -> bool:
    """Whether the StopFiring running now is one a kernel stands in for:
    K1's -- the held-weapon pump's, or a walk's (update_weapons, run_k1),
    since combat fire events Task 3 -- or K2's -- the phaser step's
    (_phaser_step_ship / _phaser_step_bank, run_k2), since Task 4 -- or
    K0's, a bank drained dry in host_loop's weapons step (_advance_weapons),
    since Task 4 too (this World steps weapons with step_every_weapon in
    BOTH arms, so it meets none of those). They log those, a firing bank's
    included, and queue its LOOP_STOP (no Python call natively), so the
    compared call log leaves them to the per-tick record and the queued
    list (a ship K2 hands to Python whole calls them in BOTH arms: left out
    alike)."""
    f = sys._getframe(2)
    while f is not None:
        if f.f_code.co_name in ("_pump_held_weapons", "update_weapons",
                                "run_k1", "_phaser_step_ship",
                                "_phaser_step_bank", "run_k2",
                                "_advance_weapons"):
            return True
        f = f.f_back
    return False


class World:
    """Real ships in one set, a pinned weapon clock, the logs.

    `ships` is ((name, hardpoint, (x, y, z), yaw[, script]), ...). Built the
    same way in both arms, so labels (ship name / subsystem name) line up.
    The spies call the real function; `after_hit` hooks run after each
    combat.apply_hit (a stand-in for a damage pulse's handler). There is no
    such hook after a beam_contact: a resting contact is presentation only,
    and K2 presents it at the drain after the step's DONE (spec 2026-11-02
    §4.3), so nothing it runs may change what the walk reads."""

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
        self.sys_stops = []
        self.events = []
        self.after_hit = []
        self._spy(mp)

    def _spy(self, mp):
        bank_stop = ws.PhaserBank.StopFiring
        sys_stop = ws.PhaserSystem.StopFiring
        beam_contact = hit_feedback.beam_contact
        apply_hit = combat.apply_hit

        def bank_spy(bank, _orig=bank_stop):
            # A FIRING bank's stop only: a stop of a bank not firing is pure
            # field writes, which K1 logs with no call (round trips Task 2);
            # its effect is in the per-tick record. Nor one of K1's: K1 logs
            # a firing bank's stop too (combat fire events Task 3).
            if bank.__dict__.get("_firing") and not _k1_stop():
                self.calls.append(("bank_stop", self.n, self.label(bank)))
            return _orig(bank)

        def sys_spy(sys_, *args, _orig=sys_stop):
            # Every stop, for the tests that count them (sys_stops); the
            # compared call log only a stop that still runs Python with a
            # bank FIRING: an offline system whose banks are all idle is
            # stopped with logged writes and no call (round trips Task 3);
            # its effect is in the per-tick record.
            self.sys_stops.append((self.n, self.label(sys_)))
            if any(b.__dict__.get("_firing")
                   for b in sys_.__dict__.get("_children", ())) \
                    and not _k1_stop():
                self.calls.append(("system_stop", self.n, self.label(sys_)))
            return _orig(sys_, *args)

        def contact_spy(**kw):
            # What it acts on: the kwarg (K2 passes the loop's answer) or its
            # own evaluation (the Python path; K2 when the loop had none).
            # A shielded contact on a target with an instance id is a
            # ShieldedContact: its shield hit stands for it in the compare
            # (the drain presents most natively).
            if "shields_block" in kw:
                acted = kw["shields_block"]
            else:
                acted = bool(combat.shields_block(kw["ship"]))
            self.calls.append(contact_row((
                "beam_contact", self.n, self.label(kw["ship"]),
                self.label(kw["source"]), _hx(kw["point"]),
                _hx(kw["normal"]), _hx(kw["shield_point"]),
                _hx(kw["tick_damage"]), kw["ship_instances"] is
                self.instances, _hx(kw.get("weapon_type")),
                _hx(kw.get("radius")), _hx(acted)), acted,
                kw["ship_instances"], kw["ship"]))
            return beam_contact(**kw)

        def shield_row(point, rgba, intensity, radius):
            return ("shield_hit", self.n,
                    tuple(_hx(float(c)) for c in point), tuple(rgba),
                    _hx(float(intensity)), _hx(float(radius)))

        shield_hit = host_io.shield_hit

        def shield_spy(iid, point, rgba=(0.0, 0.0, 0.0, 0.0), intensity=1.0,
                       radius=0.0):
            self.calls.append(shield_row(point, rgba, intensity, radius))
            return shield_hit(iid, point, rgba, intensity, radius)

        def native_hit(item):
            # A splash the K2 drain presented natively (its capture): the
            # row shield_spy logs for the same push.
            _b, _t, _iid, view, _rel, rgba, intensity, radius = item
            self.calls.append(shield_row(view, rgba, intensity, radius))

        def hit_spy(target, damage, point, **kw):
            self.calls.append((
                "apply_hit", self.n, self.label(target), _hx(damage),
                _hx(point), self.label(kw.get("source")),
                _hx(kw.get("normal")), kw.get("ship_instances") is
                self.instances, _hx(kw.get("weapon_type")),
                self.label(kw.get("hardpoint_weapon")),
                _hx(kw.get("damage_hull")), _hx(kw.get("shield_point")),
                sorted(kw)))
            result = apply_hit(target, damage, point, **kw)
            for hook in list(self.after_hit):
                hook(self)
            return result

        mp.setattr(ws.PhaserBank, "StopFiring", bank_spy)
        mp.setattr(ws.PhaserSystem, "StopFiring", sys_spy)
        # (K0 has no override guard, phase 6 A2: the bank spy does not make
        # it stand down; a drained bank's stop is logged natively.)
        mp.setattr(hit_feedback, "beam_contact", contact_spy)
        mp.setattr(host_io, "shield_hit", shield_spy)
        capture_native_shield_hits(mp, native_hit)
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
            # `_firing` and `_beam_on_countdown` are what a bank's idle
            # StopFiring writes: K1's idle stops and K2's offline stops LOG
            # them since round trips Tasks 2-3, so this row compares them.
            row.append((self.label(b), d.get("_dwell").hex(),
                        _hx(d.get("_firing")), d.get("_target") is None,
                        self.label(d.get("_target")),
                        _hx(d.get("_beam_on_countdown"))))
        for s in self.order:
            g = s.GetPhaserSystem()
            if g is None:
                continue
            d = g.__dict__
            row.append((self.label(g), _hx(d.get("_fire_held")),
                        self.label(d.get("_held_target")),
                        _hx(d.get("_held_offset")),
                        tuple(self.label(t) for t in d.get("_target_list")),
                        _hx(d.get("_last_group_fired"))))
        for s in self.order:
            row.append((self.label(s),
                        _hx(float(s.GetHull().GetCondition()))))
        self.log.append(row)

    def tick(self, before=None):
        """One host tick: the weapons' own update, then the whole combat
        step (K1's pump, then `cb.phasers`) inside the effect queue's scope,
        opened in BOTH arms, as is the script before it (its StartFiring):
        the queued weapon events and sounds are then delivered at the end
        in both, so the one event log compares (a K1 session outside any
        scope defers its own to its end, ruling F3)."""
        self.n += 1
        self.clock[0] += DT
        if before is not None:
            with effect_queue.scope():
                before(self)
        for s in self.order:
            passive_weapons.step_every_weapon(s, DT)
        with effect_queue.scope():
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
    compare_calls(ref.calls, nat.calls)
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
    # The arc fail's stop: logged writes and a LOOP_STOP (no BANK_STOP).
    assert counts["k2_logged_bank_stop"] > 0, counts
    assert counts["k2_entries"]["LOOP_STOP"] > 0, counts
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
    up. Right after the first damage pulse from tick 120 on, a handler turns
    the disable-NPC-shields cheat on (K2 learns it through the re-sent
    context): the banks after it in that step no longer stop at the bubble.
    At tick 150 it is off again; at 160 the shields go off for good.

    (The handler runs after a PULSE, a record's effect: a resting contact
    is presentation only and is queued -- round trips Task 3 -- so nothing
    it runs may change what the walk reads. It ran after any contact
    before.)"""
    import engine.dev_combat_cheats as cheats
    import engine.dev_mode as dev_mode

    def setup(w, mp):
        w.ships["Vorcha"]._shield_hull_box = ((0.0, 0.5, 0.0),
                                              (1.2, 2.5, 0.6))
        mp.setattr(dev_mode, "is_enabled", lambda: True)
        mp.setattr(cheats, "_disable_npc_shields", False)
        nc.push_globals()       # the mirror's dev_mode global follows it
        w.cheat_at = None

        def cheat_on(world):
            if world.n >= 120 and world.cheat_at is None:
                world.cheat_at = world.n
                cheats._disable_npc_shields = True
        w.after_hit.append(cheat_on)

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if w.n == 1:
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
        elif w.n == 150:
            cheats._disable_npc_shields = False
        elif w.n == 160:
            v.GetShields().TurnOff()

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 220,
                              setup=setup)
    contacts = _calls(ref, "beam_contact")
    assert {c[11] for c in contacts} == {_hx(True), _hx(False)}
    assert any(c[6] is not None for c in contacts)      # a bubble entry
    at = ref.cheat_at
    assert at is not None and at < 150, at
    pulses = [c[11] for c in _calls(ref, "apply_hit") if c[1] == at]
    # The first pulse met the bubble, the ones after it in the step do not.
    assert len(pulses) > 1 and pulses[0] is not None, pulses
    assert all(p is None for p in pulses[1:]), pulses
    assert all(c[11] == _hx(False) for c in contacts if at < c[1] < 150)
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

    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 120)
    # Python's StopFiring ran on every one of those ticks (sys_stops: every
    # stop, firing banks or not); in the native arm a stop whose banks are
    # all idle is logged writes (round trips Task 3), whose effect the
    # per-tick record compares.
    stops = {n for n, label in ref.sys_stops if label.startswith("Galaxy/")}
    assert set(range(32, 60)) <= stops, sorted(stops)
    assert set(range(92, 121)) <= stops, sorted(stops)
    native_stops = {n for n, label in nat.sys_stops
                    if label.startswith("Galaxy/")}
    # K1's pump logs its stop too (combat fire events Task 3).
    logged = counts["k2_logged_system_stop"] + \
        counts["k1_logged"]["system_stop"]
    assert logged >= len(stops - native_stops) > 0, (
        counts, sorted(native_stops))
    _native_ran(counts)


def _tracked(w):
    return TrackedInstances({w.ships["Vorcha"]: _h.InstanceId()})


def _native_only(monkeypatch, ships, script, ticks, instances=None,
                 setup=None):
    """`script` under native on only (a patch the two arms would disagree
    on: Part A, it is not obeyed natively). Returns (world, counts)."""
    with monkeypatch.context() as mp:
        w = World(mp, True, ships, "k2_native_only", instances=instances)
        try:
            if setup is not None:
                setup(w, mp)
            for t in range(ticks):
                w.tick(before=lambda w, t=t: script(w, t))
            counts = nc.counts()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()
    return w, counts


def test_a_patched_trace_is_not_honoured(monkeypatch):
    """A test's patched host_io.ray_trace_mesh, a function K2 stands in
    for, does not send the step to Python (spec Part A, phase 6 A3): the
    kernel traces the real mesh, and the patch is never called for it."""
    called = []

    def setup(w, mp):
        def fake_trace(iid, origin, direction, max_dist, rest_pose=False):
            called.append(iid)
            p = w.ships["Vorcha"].GetWorldLocation()
            return (p.x + 0.25, p.y - 1.0, p.z + 0.125), (0.0, -1.0, 0.0), 1.0
        mp.setattr(host_io, "ray_trace_mesh", fake_trace)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    nat, counts = _native_only(monkeypatch, GALAXY_VORCHA, script, 90,
                               instances=_tracked, setup=setup)
    _native_ran(counts)
    assert counts["k2_python_step_reasons"]["patched"] == 0, counts
    assert _calls(nat, "apply_hit")         # the beam bit
    assert called == []


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
    comes back. The handler runs after a damage PULSE (a record's effect;
    a resting contact is queued, round trips Task 3)."""

    def setup(w, mp):
        w.ships["Vorcha"].SetRadius(3.0)
        w.popped = w.restored = None

        def pop_then_restore(world):
            v = world.ships["Vorcha"]
            if world.popped is None and world.n >= 60:
                world.popped = world.n
                world.instances.pop(v)
            elif (world.restored is None and world.n >= 90
                  and world.n > world.popped):
                world.restored = world.n
                world.instances[v] = _h.InstanceId()
        w.after_hit.append(pop_then_restore)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 130,
                              instances=_tracked, setup=setup)
    at = {}
    for c in _calls(ref, "apply_hit"):
        at.setdefault(c[1], []).append(c[4])
    contacts = {}
    for c in _calls(ref, "beam_contact"):
        contacts.setdefault(c[1], []).append(c[4])
    popped, restored = ref.popped, ref.restored
    assert popped is not None and restored is not None, (popped, restored)
    # Several banks pulse at the pop's tick: the first saw a stale
    # InstanceId (the trace raises: the sphere tier), the rest no instance
    # (the fallback point IS the aim point, here the Vor'cha's centre). The
    # scenario tells the two apart.
    centre = _hx(ref.ships["Vorcha"].GetWorldLocation())
    assert at[popped][0] != centre and len(at[popped]) > 1, at[popped]
    assert all(p == centre for p in at[popped][1:]), at[popped]
    assert all(p == centre for p in contacts[popped + 1]), contacts
    # Restored after that tick's first pulse: the sphere tier again.
    assert at[restored][0] == centre, at[restored]
    assert all(p != centre for p in at[restored][1:]), at[restored]
    assert all(p != centre for p in contacts[restored + 1]), contacts
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
    real GetShields (ASK shields_block, then ASK bubble). Every stub
    attribute hit (stub telemetry) is counted the same in both arms -- the
    native arm asks Python exactly the calls the Python loop makes, no
    more, no fewer -- except shields_block's: the Python arm evaluates it
    three times per Hulk contact (the loop, the World's beam_contact spy,
    beam_contact itself), the native arm once (the ASK), carrying the
    answer to the drain (spec 2026-11-02 §4.3), which passes it on."""
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
    assert counts["k2_logged_bank_stop"] > 0, counts    # tick 1's stop
    assert any(c[0] == "beam_contact" and c[2] == "Hulk" for c in ref.calls)
    _native_ran(counts)
    asks = counts["k2_ask_queries"]
    assert asks["is_dead"] > 0 and asks["shields_block"] > 0, asks
    stub_telemetry.reset()
    python_hits, native_hits = hits
    shields = {k for k in python_hits if k[1].startswith("GetShields")}
    assert shields and set(native_hits) == set(python_hits)
    assert {k: 3 * native_hits[k] for k in shields} == \
        {k: python_hits[k] for k in shields}, (python_hits, native_hits)
    assert {k: v for k, v in native_hits.items() if k not in shields} == \
        {k: v for k, v in python_hits.items() if k not in shields}, (
            python_hits, native_hits)


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
    """A handler drops the target's mirror row after the first damage pulse
    of a step (a record's effect; a resting contact is queued, round trips
    Task 3): the Galaxy's later banks cannot be walked natively, so each is
    run in Python (ASK bank_step); from the next step its whole ship is
    (the pre-scan: an unnameable target)."""

    def setup(w, mp):
        w.dropped = None

        def drop(world):
            if world.n >= 50 and world.dropped is None:
                world.dropped = world.n
                if "_nslot" in world.ships["Vorcha"].__dict__:
                    nc._drop(world.ships["Vorcha"])     # none when off
        w.after_hit.append(drop)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 90,
                              setup=setup)
    assert ref.dropped is not None
    assert sum(1 for c in _calls(ref, "apply_hit")
               if c[1] == ref.dropped) > 1
    assert counts["k2_records"] > 0, counts
    assert counts["k2_ask_queries"]["bank_step"] > 0, counts
    assert counts["k2_python_ships"] > 0, counts


# ── A stood-in function or method patched is not honoured (Part A) ───────

# What K2 stands in for (the snapshot these were once watched against is
# gone, phase 6 A3): patching one leaves the step native.
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
        "GetChildSubsystem", "IsOn", "IsDisabled", "IsDestroyed",
        "GetPowerLevel")
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
def test_a_patched_stood_in_function_is_not_honoured(
        monkeypatch, module, name):
    """Patching a function K2 stands in for leaves the step native (spec
    Part A, phase 6 A3: no module-patch fallback)."""
    mod = importlib.import_module(module)
    orig = getattr(mod, name)

    def patch(mp, _w):
        mp.setattr(mod, name, lambda *a, **k: orig(*a, **k))
    counts = _one_native_step(monkeypatch, patch)
    _native_ran(counts)
    assert counts["k2_python_step_reasons"]["patched"] == 0, counts


@pytest.mark.parametrize("cls,name", STOOD_IN_METHODS,
                         ids=["%s.%s" % cn for cn in STOOD_IN_METHODS])
def test_a_patched_stood_in_method_is_not_honoured(monkeypatch, cls, name):
    """Patching a stock-class method K2 stands in for (or making one
    appear) leaves the step native (spec Part A, phase 6 A3: no class-patch
    fallback)."""
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
    _native_ran(counts)
    assert counts["k2_python_step_reasons"]["patched"] == 0, counts


def test_instance_patch_sends_its_ship_to_python(monkeypatch):
    """An instance attribute shadowing a stood-in method on a ship, its
    phaser system or a bank sends THAT ship to Python (python_ships); the
    rest of the step stays native."""
    for owner, name in (("ship", "GetTargetSubsystem"), ("system", "IsOn"),
                        ("system", "GetPowerLevel"), ("bank", "take_dwell")):
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


def test_power_level_override_matches_python(monkeypatch):
    """A PhaserSystem subclass whose GetPowerLevel answers PP_LOW while its
    `_power_level` (the mirror's) stays PP_HIGH: the kernel would carry the
    mirror's level on a resting contact, so the ship goes to Python whole
    (RUN_PYTHON "overridden") and every rest and pulse matches Python's."""

    class FixedLevel(ws.PhaserSystem):
        def GetPowerLevel(self):
            return self.PP_LOW

    def setup(w, mp):
        g = w.ships["Galaxy"].GetPhaserSystem()
        mp.setattr(g, "__class__", FixedLevel)
        assert g.__dict__["_power_level"] == g.PP_HIGH

    def script(w, t):
        if t == 0:
            g = w.ships["Galaxy"].GetPhaserSystem()
            g.SetSingleFire(0)
            g.StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 60,
                              setup=setup)
    assert _calls(ref, "beam_contact")
    assert counts["k2_records"] > 0, counts
    assert counts["k2_python_reasons"]["overridden"] > 0, counts


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


def test_a_host_bindings_test_double_is_not_honoured(monkeypatch):
    """host_io._h replaced by a test double (its own instance_translation
    and ray_trace_mesh): the kernel's installed trace is the REAL
    renderer's, and the double does not send the step to Python (spec Part
    A, phase 6 A3): its hit is never the one damaged."""

    class FakeHost:
        """The real bindings, but for the two calls the trace makes."""

        def __getattr__(self, name):
            return getattr(_h, name)

        def instance_translation(self, iid):
            return (0.0, 0.0, 0.0)

        def ray_trace_mesh(self, iid, origin, direction, max_dist):
            traced.append(iid)
            return (20.0, 255.0, 15.0), (0.0, 1.0, 0.0), 1.0

    traced = []

    def setup(w, mp):
        mp.setattr(host_io, "_h", FakeHost())

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    nat, counts = _native_only(monkeypatch, GALAXY_VORCHA, script, 90,
                               instances=_tracked, setup=setup)
    hit = _hx(TGPoint3(20.0, 255.0, 15.0))
    points = {c[4] for c in _calls(nat, "apply_hit") if c[2] == "Vorcha"}
    assert points and hit not in points, points
    assert traced == []
    _native_ran(counts)
    assert counts["k2_python_step_reasons"]["patched"] == 0, counts


def test_forget_rows_forgets_the_seen_classes():
    """The conftest's mirror wipe (combat_clear + forget_rows) forgets the
    classes seen before it: with no row left, none has been seen (a test's
    class, here, must not outlive its test in _k2_seen)."""
    from engine.appc.ships import ShipClass

    class _TestOnlyShip(ShipClass):
        def GetWorldRotation(self):     # a stood-in name, from a test
            return ShipClass.GetWorldRotation(self)

    nc.configure(ON)
    _TestOnlyShip()
    assert _TestOnlyShip in nc._k2_seen
    assert _TestOnlyShip in nc._k2_seen_set
    _h.combat_clear()
    nc.forget_rows()
    assert _TestOnlyShip not in nc._k2_seen
    assert _TestOnlyShip not in nc._k2_seen_set


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
    """With no step boundary resolving the slots for K2, every one stays
    unresolved there: a posed firing ship ("ship") or a lock on a posed
    ship ("lock") hands the firing ship to Python with reason part_stale --
    never posed_ship, never a stale part read. Equal to Python. (K1 resolves
    at its own entry and fires: a posed ship with stale slots does not fire
    at all since fire control went native only, M8.4; K2 then sees the
    slots stale -- the generation bumped after the pump -- and resolves
    none.)"""
    real_k2 = nc.k2_phasers

    def k2_stale(*a, **kw):
        nc.bump_part_gen()
        with monkeypatch.context() as mp:
            mp.setattr(nc, "resolve_stale_part_slots",
                       lambda ships, drop=True: None)
            return real_k2(*a, **kw)
    monkeypatch.setattr(nc, "k2_phasers", k2_stale)

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
    # K1's entries (the pump, StartFiring's sessions) resolve through
    # native_combat._k1_entry.
    assert {"step_scan", "_k1_entry", "k2_phasers"} <= set(
        callers), callers
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_python_reasons"]["part_stale"] == 0, counts
    assert counts["k2_ask_queries"]["aim_point"] == 0, counts
    assert counts["k2_posed"]["lock_aims"] > 0, counts
    assert counts["k1_no_fire"]["part_stale"] == 0, counts
    assert counts["k1_no_fire"]["decision"] == 0, counts
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
    cruise, or swinging home tick by tick): the aim point is the pick as a
    plain body point (fire control native only, M5), natively -- no ASK
    aim_point -- also after the pick moves mid-fight, and per tick equal to
    Python."""
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


# ── Review fixes (posed parts, Task 4 fix round 1) ──────────────────────────

def _unnameable_lock(w):
    """The Galaxy fires at the Bird of Prey locked on a cannon whose mirror
    row is dropped (native arm only: the off arm has no row): the beam's
    aim point is Python's (ASK aim_point). (Was a Manual Aim pick for
    another target, Python's while the box rule aimed: a pick is a plain
    body point since fire control native only, M5.)"""
    g, bop = w.ships["Galaxy"], w.ships["BoP"]
    cannon = _port_cannon(bop)
    articulation.force_pose(bop, "cruise")
    g.SetTarget(bop)
    g.SetTargetSubsystem(cannon)
    g.GetPhaserSystem().SetSingleFire(0)
    g.GetPhaserSystem().StartFiring(bop)
    nc._drop(cannon)


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
            _unnameable_lock(w)

    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 60)
    assert bumps, "no aim_point ASK was answered"
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_ask_queries"]["aim_point"] > 0, counts
    assert counts["k2_python_reasons"]["part_stale"] == 0, counts
    assert counts["k2_posed"]["banks"] > 0, counts


def test_remaining_aim_point_asks_match_python(monkeypatch):
    """The aim point that is still Python's, end to end: a lock the mirror
    cannot name (its row dropped). It ASKs aim_point after the drop, per
    tick equal to Python. (A Manual Aim pick for another target or with a
    stale slot was Python's too, until a pick became a plain body point:
    fire control native only, M5.)"""

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        cannon = _port_cannon(bop)
        if t == 0:
            articulation.force_pose(bop, "cruise")
            v.SetTarget(bop)
            v.SetTargetSubsystem(cannon)
            v.GetPhaserSystem().SetSingleFire(0)
            v.GetPhaserSystem().StartFiring(bop)
        elif t == 30:
            nc._drop(cannon)        # native arm only: the off arm has no row

    ref, _nat, counts = _both(monkeypatch, LOCK_ON_BOP, script, 90)
    assert any(c[2] == "BoP" for c in _calls(ref, "beam_contact"))
    _native_ran(counts)
    assert counts["k2_ask_queries"]["aim_point"] > 0, counts
    assert counts["k2_posed"]["lock_aims"] > 0, counts


# ── Round trips Task 3: resting contacts batched, offline stops logged ──────
#
# A resting CONTACT (`flush_dwell <= 0`: _phaser_contact's beam_contact
# branch, presentation only) never comes back on a record: the kernel queues
# it, in walk order, with its power level, shields answer, instance and view
# offset as they were at contact time, and the queue is presented once,
# after DONE (combat_k2_drain; spec 2026-11-02 §4.3-4.4): the shield splashes
# it can, natively, by the drain itself; the rest by run_k2's Python batch,
# from the entries the drain returns. A SYSTEM_STOP on an
# offline system whose banks are all idle is the system's five writes and
# each bank's StopFiring writes, logged.

def _spy_k2_records(mp, log):
    """Log every K2 record as it is returned, before Python acts on it --
    (kind, its own flush (CONTACT) or None) -- and every drain: ("DRAIN",
    [(flush, level, shields) of each entry it returned], how many it
    presented natively)."""
    names = {v: k for k, v in _h.combat_k2_kinds().items()}
    real, real_drain = _h.combat_k2_next, _h.combat_k2_drain

    def spy():
        rec = real()
        kind = names[rec[0]]
        log.append((kind, rec[14] if kind == "CONTACT" else None))
        return rec

    def drain_spy():
        before = _h.combat_k2_counts()["k2_present_native"]
        entries = real_drain()
        log.append(("DRAIN", [(e[13], e[14], e[12]) for e in entries],
                    _h.combat_k2_counts()["k2_present_native"] - before))
        return entries
    mp.setattr(_h, "combat_k2_next", spy)
    mp.setattr(_h, "combat_k2_drain", drain_spy)


def _mark_contacts(w, mp, log):
    """Each beam_contact also marks the record log (native arm), so a test
    sees where the presentations ran among the records."""
    inner = hit_feedback.beam_contact

    def mark(**kw):
        if w.native:
            log.append(("beam_contact", w.n))
        return inner(**kw)
    mp.setattr(hit_feedback, "beam_contact", mark)


def _spy_presentation(w, mp):
    """What a hull contact presents, into the compared call log: every hit
    VFX spawn, with its arguments. (Every shield hit, Python's and the
    drain's native ones, is in the log already: World._spy.)"""
    from engine.appc import hit_vfx
    spawn = hit_vfx.spawn

    def spawn_spy(position, **kw):
        w.calls.append(("vfx", w.n, _hx(position), _hx(kw.get("normal")),
                        repr(kw.get("severity")), kw.get("weapon_kind"),
                        kw.get("spark_count"), repr(kw.get("body_point")),
                        w.label(kw.get("pSet"))))
        return spawn(position, **kw)

    mp.setattr(hit_vfx, "spawn", spawn_spy)


def test_resting_contacts_presented_after_the_steps_last_record(
        monkeypatch):
    """A volley each way, the Vor'cha's shields up and then down. No
    resting contact comes back on a record (a CONTACT record is a damage
    pulse): each tick's resting contacts are presented after the step's
    DONE, from its one drain -- the Vor'cha's shield splashes by the drain
    itself (it has an instance in the viewed set), in walk order, exactly
    the shield hits the Python step pushes; every other contact (the
    Galaxy has no instance; the Vor'cha unshielded) by the Python batch,
    the same beam_contact calls, in the same order, as the Python step
    makes -- and the hit VFX they draw equal Python's (per tick, as a
    multiset)."""
    log = []
    _spy_k2_records(monkeypatch, log)

    def setup(w, mp):
        _spy_presentation(w, mp)
        _mark_contacts(w, mp, log)

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
        elif t == 20:
            v.GetPhaserSystem().SetSingleFire(0)
            v.GetPhaserSystem().StartFiring(g)
        elif t == 90:
            v.GetShields().TurnOff()

    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 160,
                             instances=_tracked, setup=setup)
    assert _calls(ref, "vfx") and _calls(ref, "shield_hit"), ref.calls[:10]
    _native_ran(counts)
    assert counts["k2_python_ships"] == 0, counts
    resting = _calls(nat, "beam_contact")
    native = counts.get("k2_present_native", 0)
    assert native > 0 and resting, (counts, len(resting))
    assert counts.get("k2_batched_contacts", 0) == len(resting) + native, \
        counts
    assert counts.get("k2_present_python", 0) == len(resting), counts
    contacts = [r[1] for r in log if r[0] == "CONTACT"]
    assert contacts and all(f > 0.0 for f in contacts), contacts
    # Every presentation follows the step's DONE and its drain: the drain
    # presents its native ones, then one beam_contact per entry it returned;
    # nothing is presented between records.
    drained = presented = 0
    for i, row in enumerate(log):
        if row[0] != "DRAIN":
            continue
        assert log[i - 1][0] == "DONE", log[i - 1:i + 1]
        assert all(f == 0.0 for f, _l, _s in row[1]), row
        n = len(row[1])
        assert [r[0] for r in log[i + 1:i + 1 + n]] == ["beam_contact"] * n
        drained += n
        presented += row[2]
    assert drained == len(resting) == sum(
        1 for r in log if r[0] == "beam_contact")
    assert presented == native
    assert max(len(r[1]) + r[2] for r in log if r[0] == "DRAIN") > 1, \
        log[:20]
    # Walk order: each tick's natively presented splashes are the Python
    # step's Vor'cha shield hits, in its order; its other contacts are the
    # Python batch's, in its order.
    for t in range(1, 161):
        assert [c for c in _calls(nat, "shield_hit") if c[1] == t] == \
            [c for c in _calls(ref, "shield_hit") if c[1] == t], t
        assert [c for c in _calls(nat, "beam_contact") if c[1] == t] == \
            [c for c in _calls(ref, "beam_contact") if c[1] == t
             and not (isinstance(c, ShieldedContact)
                      and c[2] == "Vorcha")], t


def _lit_volley(w):
    """The Galaxy's banks that hold the Vor'cha, lit by hand with beams on:
    the walk's earlier banks rest, its last one pulses on the first tick."""
    v = w.ships["Vorcha"]
    for bank in w.lit:
        _light(bank, v, countdown=0.0)
        bank._dwell = 0.0
    w.lit[-1]._dwell = 0.6          # past the flush: pulses at once


def _lit_setup(w, mp):
    g, v = w.ships["Galaxy"], w.ships["Vorcha"]
    banks = _banks_in_arc(g, v)
    assert len(banks) >= 2, banks
    w.lit = banks


def test_rest_keeps_level_and_shields_from_contact_time(monkeypatch):
    """Review Focus. The pulse's handler (after_hit) drops the Galaxy's
    phasers to PP_LOW and the Vor'cha's shields. Python presents the earlier
    banks' resting contacts BEFORE the pulse, at PP_HIGH on the shields; K2
    presents them after the step, from the values its queue took at contact
    time, so tick_damage (PHASER_INTENSITY_SCALE[level]) and the shield
    branch still equal Python's."""
    log = []
    _spy_k2_records(monkeypatch, log)

    def setup(w, mp):
        _spy_presentation(w, mp)
        _lit_setup(w, mp)
        w.dropped = []

        def drop(w):
            if not w.dropped:
                w.dropped.append(w.n)
                g = w.ships["Galaxy"].GetPhaserSystem()
                g.SetPowerLevel(g.PP_LOW)
                w.ships["Vorcha"].GetShields().TurnOff()
        w.after_hit.append(drop)

    def script(w, t):
        if t == 0:
            _lit_volley(w)

    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 3,
                             setup=setup)
    _native_ran(counts)
    assert ref.dropped == nat.dropped == [1]
    rest = len(nat.lit) - 1
    first = [c for c in ref.calls if c[1] == 1
             and c[0] in ("beam_contact", "apply_hit")]
    assert [c[0] for c in first[:rest + 1]] == \
        ["beam_contact"] * rest + ["apply_hit"], first
    assert all(c[-1] == _hx(True) for c in first[:rest]), first
    # The pulse's record comes first; the drain after DONE carries the
    # earlier banks, each with the level it had at contact time.
    pulse = next(i for i, r in enumerate(log) if r[0] == "CONTACT")
    drain = next(r for r in log[pulse:] if r[0] == "DRAIN")
    ws_ = nat.ships["Galaxy"].GetPhaserSystem()
    assert [(lvl, sh) for _f, lvl, sh in drain[1]][:rest] == \
        [(ws_.PP_HIGH, True)] * rest, drain
    assert ws_.GetPowerLevel() == ws_.PP_LOW


def test_rest_keeps_level_from_contact_time_on_the_hull(monkeypatch):
    """The carried power level alone, on the hull branch. The Vor'cha's
    shields are off from the start, so every resting contact takes the hull
    path, where tick_damage (PHASER_INTENSITY_SCALE[level]) sets the flash
    and its spark burst; the pulse's handler only drops the Galaxy's
    phasers to PP_LOW. Python presents the earlier banks' rests BEFORE the
    pulse, at PP_HIGH; K2 presents them after the step from the level its
    queue took at contact time, so their beam_contact rows (tick_damage by
    .hex()) and the hit VFX they spawn still equal Python's -- a level read
    at the drain would present them at PP_LOW."""
    log = []
    _spy_k2_records(monkeypatch, log)

    def setup(w, mp):
        _spy_presentation(w, mp)
        _lit_setup(w, mp)
        w.ships["Vorcha"].GetShields().TurnOff()
        w.dropped = []

        def drop(w):
            if not w.dropped:
                w.dropped.append(w.n)
                g = w.ships["Galaxy"].GetPhaserSystem()
                g.SetPowerLevel(g.PP_LOW)
        w.after_hit.append(drop)

    def script(w, t):
        if t == 0:
            _lit_volley(w)

    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 3,
                             setup=setup)
    _native_ran(counts)
    assert ref.dropped == nat.dropped == [1]
    ws_ = nat.ships["Galaxy"].GetPhaserSystem()
    assert host_loop.PHASER_INTENSITY_SCALE[ws_.PP_HIGH] != \
        host_loop.PHASER_INTENSITY_SCALE[ws_.PP_LOW]
    rest = len(nat.lit) - 1
    first = [c for c in ref.calls if c[1] == 1
             and c[0] in ("beam_contact", "apply_hit")]
    assert [c[0] for c in first[:rest + 1]] == \
        ["beam_contact"] * rest + ["apply_hit"], first
    # The hull branch, and compared (not a ShieldedContact).
    assert all(c[-1] == _hx(False) and not isinstance(c, ShieldedContact)
               for c in first[:rest]), first
    pulse = next(i for i, r in enumerate(log) if r[0] == "CONTACT")
    drain = next(r for r in log[pulse:] if r[0] == "DRAIN")
    assert [(lvl, sh) for _f, lvl, sh in drain[1]][:rest] == \
        [(ws_.PP_HIGH, False)] * rest, drain
    assert ws_.GetPowerLevel() == ws_.PP_LOW


def test_rest_on_target_killed_later_in_step_presents_once(monkeypatch):
    """Review Focus 1 (ruling Q4). The pulse's handler kills the Vor'cha
    (SetDead) after the earlier banks' contacts were queued: each still
    presents exactly once, on the dead target, and nothing raises; the next
    tick the banks see a dead target and present nothing more."""

    def setup(w, mp):
        _lit_setup(w, mp)
        w.killed = []

        def kill(w):
            if not w.killed:
                w.killed.append(w.n)
                w.ships["Vorcha"].SetDead()
        w.after_hit.append(kill)

    def script(w, t):
        if t == 0:
            _lit_volley(w)

    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 3,
                             setup=setup)
    _native_ran(counts)
    assert ref.killed == nat.killed == [1]
    rest = len(nat.lit) - 1
    at = [c[1] for c in _calls(nat, "beam_contact")]
    assert at == [1] * rest, at
    assert counts["k2_present_python"] == rest, counts


def test_drained_rest_naming_a_freed_object_is_skipped(monkeypatch):
    """A drained entry whose bank, target, ship or system was freed between
    its queueing and the drain (its handle names no pinned or live object)
    is skipped and counted, never raised: Python would have presented it
    before the free. The other entries still present."""
    nc.configure(ON)
    ran = []
    monkeypatch.setattr(nc, "_k2_run_contact",
                        lambda c, *a, **kw: ran.append(c[0]))
    walk = nc._K2Walk()
    live = App.ShipClass_Create("Live")
    h = nc.slot(live)
    gone = h + 1 if nc._registry.get(h + 1) is None else h + 2
    assert nc._registry.get(gone) is None
    row = (h, h, h, h) + (None,) * 10 + (2, None, None)
    dead = (h, gone, h, h) + (None,) * 10 + (2, None, None)
    nc._k2_present_batch([dead, row], walk, DT, None)
    assert ran == [h]
    c = nc.counts()
    assert (c["k2_present_gone"], c["k2_present_python"]) == (1, 1), c


def test_batch_reraises_the_first_raise_noting_the_later_ones(monkeypatch):
    """Review Focus 2. Two of three presentations raise: all three run, the
    first exception is re-raised, and the later one rides on it as a note
    (its type and message), never dropped silently."""
    nc.configure(ON)
    ran = []

    def run(c, *a, **kw):
        ran.append(len(ran))
        if len(ran) == 1:
            raise KeyError("first")
        if len(ran) == 3:
            raise ValueError("third")
    monkeypatch.setattr(nc, "_k2_run_contact", run)
    ship = App.ShipClass_Create("Live")
    h = nc.slot(ship)
    row = (h, h, h, h) + (None,) * 10 + (2, None, None)
    with pytest.raises(KeyError) as e:
        nc._k2_present_batch([row, row, row], nc._K2Walk(), DT, None)
    assert ran == [0, 1, 2]
    notes = getattr(e.value, "__notes__", [])
    assert len(notes) == 1 and "ValueError" in notes[0] \
        and "third" in notes[0], notes


def test_abandoned_step_presents_nothing_next_step(monkeypatch):
    """Review Focus 3. The pulse's handler raises after the earlier banks'
    contacts were queued: run_k2 abandons the session, so those contacts
    are never presented -- not that tick, and not by the next tick's
    drain, which presents only its own."""

    class Boom(Exception):
        pass

    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_abandon")
        try:
            _lit_setup(w, mp)
            raised = []

            def boom(w):
                if not raised:
                    raised.append(w.n)
                    raise Boom()
            w.after_hit.append(boom)
            log = []
            _spy_k2_records(mp, log)
            with pytest.raises(Boom):
                w.tick(before=lambda w: _lit_volley(w))
            assert raised == [1]
            assert not _h.combat_k2_open()
            assert _calls(w, "beam_contact") == []
            assert not any(r[0] == "DRAIN" for r in log), log
            assert _h.combat_k2_drain() == []
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
            before = nc.counts()["k2_batched_contacts"]
            del log[:]
            w.tick()
            queued = nc.counts()["k2_batched_contacts"] - before
            drains = [r for r in log if r[0] == "DRAIN"]
            assert len(drains) == 1 \
                and len(drains[0][1]) + drains[0][2] == queued > 0
            assert [c[1] for c in _calls(w, "beam_contact")] == [2] * queued
        finally:
            w.close()


_STOP_TRACED = ("_fire_held", "_held_target", "_held_offset", "_target_list",
                "_last_group_fired", "_firing", "_beam_on_countdown")


def _stop_value(w, name, value):
    if name == "_held_target":
        return w.label(value)
    if name == "_target_list":
        return ("list", tuple(w.label(t) for t in value))
    return _hx(value)


def _offline_run(monkeypatch, native, ticks, off_at):
    """The Galaxy holds its phasers on the Vor'cha, then its phaser system is
    switched off (tick off_at + 1) and stays off. From then on bank 0 is put
    to sleep before each combat step, after the passive weapons walk, so
    only the stop's `_firing` write can wake it. Traces every write of the
    stop's fields on the system and its banks during the combat step:
    Python's through the class __setattr__, the kernels' logged ones
    through apply_writes' quiet setters. Returns (traces, per-tick
    `_target_list` objects, per-tick asleep-after-step, world log, calls,
    counts or None)."""
    traces, lists, asleep = [], [], []
    with monkeypatch.context() as mp:
        w = World(mp, native, GALAXY_VORCHA, "k2_offline_%d" % native)
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            system = g.GetPhaserSystem()
            owned = {id(system)} | {id(system.GetWeapon(i))
                                    for i in range(system.GetNumWeapons())}
            state = {"on": False}

            def note(obj, name, value):
                if state["on"] and name in _STOP_TRACED \
                        and id(obj) in owned:
                    traces.append((w.n, type(obj).__name__, w.label(obj),
                                   name, _stop_value(w, name, value)))

            real_quiet = nc._quiet_setter

            def quiet(cls, name):
                setter, kind = real_quiet(cls, name)

                def traced(obj, value, _s=setter, _n=name):
                    note(obj, _n, value)
                    return _s(obj, value)
                return traced, kind

            mp.setattr(nc, "_quiet_setter", quiet)
            for cls in (ws.PhaserSystem, ws.PhaserBank):
                def setattr_(self, name, value, _real=cls.__setattr__):
                    note(self, name, value)
                    _real(self, name, value)
                mp.setattr(cls, "__setattr__", setattr_)
            bank0 = system.GetWeapon(0)
            system.SetSingleFire(0)
            system.StartFiring(v)
            for t in range(ticks):
                w.n += 1
                w.clock[0] += DT
                if t == off_at:
                    system.TurnOff()
                passive_weapons.advance(w.order, DT)
                if t > off_at and not passive_state.is_asleep(bank0):
                    passive_state.put_to_sleep(bank0)
                state["on"] = True
                try:
                    host_loop._advance_combat(list(w.order), DT,
                                              ship_instances=None,
                                              push_render_data=False)
                finally:
                    state["on"] = False
                asleep.append(passive_state.is_asleep(bank0))
                lists.append(system.__dict__["_target_list"])  # held
                w.record()
            counts = None
            if native:
                counts = nc.counts()
                nc.audit_mirror()
                assert nc.audit_failures() == [], nc.audit_failures()
            return traces, lists, asleep, w.log, w.calls, counts
        finally:
            w.close()


def test_offline_system_stop_logged_new_list_every_tick(monkeypatch):
    """Review Focus 5. An offline phaser system whose banks are all idle is
    stopped EVERY tick with logged writes, no record: the system's five
    (`_target_list` a NEW empty list each tick, as Python's StopFiring
    builds one), then each bank's, in Python's order and with its values.
    The bank `_firing` write still wakes a sleeping bank."""
    ticks, off_at = 60, 20
    ref = _offline_run(monkeypatch, False, ticks, off_at)
    nat = _offline_run(monkeypatch, True, ticks, off_at)
    r_traces, r_lists, r_asleep, r_log, r_calls, _ = ref
    n_traces, n_lists, n_asleep, n_log, n_calls, counts = nat
    assert n_log == r_log
    assert n_calls == r_calls
    assert n_traces == r_traces
    assert n_asleep == r_asleep
    assert False in r_asleep[off_at + 2:], r_asleep
    for lists in (r_lists, n_lists):
        after = lists[off_at + 1:]
        assert all(a is not b for a, b in zip(after, after[1:]))
        assert all(x == [] for x in after)
    # The order of one logged stop, written out: the system's five, then
    # each bank's two, in GetWeapon order.
    last = [(c, f, val) for n, c, _l, f, val in r_traces if n == ticks]
    n_banks = len({label for _n, c, label, _f, _v in r_traces
                   if c == "PhaserBank"})
    assert n_banks > 1, r_traces[-12:]
    want = [("PhaserSystem", "_fire_held", _hx(False)),
            ("PhaserSystem", "_held_target", None),
            ("PhaserSystem", "_held_offset", None),
            ("PhaserSystem", "_target_list", ("list", ())),
            ("PhaserSystem", "_last_group_fired", _hx(-1))]
    want += [("PhaserBank", "_firing", _hx(False)),
             ("PhaserBank", "_beam_on_countdown", _hx(0.0))] * n_banks
    assert last == want, last
    assert counts.get("k2_logged_system_stop", 0) >= ticks - off_at - 2, \
        counts


class _Loop:
    def __init__(self, log, label):
        self.log, self.label = log, label

    def Stop(self):
        self.log.append(self.label)


def test_firing_bank_on_offline_system_is_logged_with_loop_stop(
        monkeypatch):
    """A bank lit by hand on a phaser system that is off: the stop has a
    FIRING bank, so besides its logged writes it queues the bank's
    LOOP_STOP (combat fire events Task 4), and the loop sound stops at the
    scope's end -- exactly as often, at the same ticks, ON as OFF -- with no
    SYSTEM_STOP record. The ticks after it, every bank idle, log only."""
    log = []
    _spy_k2_records(monkeypatch, log)
    stops = {}

    def script(w, t):
        g = w.ships["Galaxy"].GetPhaserSystem()
        if t == 0:
            stops[w.native] = []
            g.TurnOff()
        if t in (10, 25):
            bank = _banks_in_arc(w.ships["Galaxy"], w.ships["Vorcha"])[0]
            _light(bank, w.ships["Vorcha"])
            bank._loop_handle = _Loop(stops[w.native], (w.n, w.label(bank)))

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 40)
    assert stops[False] == [(11, stops[False][0][1]),
                            (26, stops[False][0][1])], stops
    assert stops[True] == stops[False]
    assert sum(1 for r in log if r[0] == "SYSTEM_STOP") == 0, log
    assert counts.get("k2_logged_system_stop", 0) > 0, counts
    assert counts["k2_logged_firing_system_stop"] == 2, counts
    assert counts["k2_entries"]["LOOP_STOP"] == 2, counts


@pytest.mark.parametrize("where", ["system_class", "system_instance",
                                   "bank_class", "bank_instance"])
def test_system_stop_override_runs_python(monkeypatch, where):
    """While K2's Python copy exists, the StopFiring an offline stop stands
    in for -- the phaser system's and each bank's -- patched on an instance
    (the K2 instance-patch names) is obeyed: Python's own runs, exactly as
    often ON as OFF. Patched on the CLASS it is not any more: that guard was
    K1's (k1_overridden), deleted with fire control's Python copy (fire
    control native only, M8.7) -- K2's native stop logs its writes and
    never calls it, while the Python reference arm does."""
    calls = {}

    def counting(real, key):
        def f(self, *args):
            calls[key].append(self.GetName())
            return real(self, *args)
        return f

    def script(w, t):
        g = w.ships["Galaxy"].GetPhaserSystem()
        if t == 0:
            key = w.native
            calls[key] = []
            g.TurnOff()
            bank = g.GetWeapon(0)
            if where == "system_class":
                monkeypatch.setattr(ws.PhaserSystem, "StopFiring",
                                    counting(ws.PhaserSystem.StopFiring, key))
            elif where == "system_instance":
                f = counting(ws.PhaserSystem.StopFiring, key)
                monkeypatch.setattr(g, "StopFiring", lambda *a: f(g, *a),
                                    raising=False)
            elif where == "bank_class":
                monkeypatch.setattr(ws.PhaserBank, "StopFiring",
                                    counting(ws.PhaserBank.StopFiring, key))
            else:
                f = counting(ws.PhaserBank.StopFiring, key)
                monkeypatch.setattr(bank, "StopFiring", lambda: f(bank),
                                    raising=False)
        if t == 29:
            monkeypatch.undo()

    _both(monkeypatch, GALAXY_VORCHA, script, 30)
    assert len(calls[False]) >= 25, calls
    if where.endswith("_class"):
        assert calls[True] == [], calls      # not obeyed (M8.7)
    else:
        assert calls[True] == calls[False]


def test_raise_in_a_batch_presentation_presents_the_rest_then_raises(
        monkeypatch):
    """Review Focus 2. One drained resting contact's presentation raises
    (beam_contact itself, on the tick's first entry): run_k2 presents every
    other entry of the batch, then re-raises; the session is abandoned
    after DONE (every write already applied: the mirror equals Python), the
    queue is gone, and the fight goes on natively."""
    raise_at = 40

    class Boom(Exception):
        pass

    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_raise")
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
            spied = hit_feedback.beam_contact
            tried, shown = [], []

            def boom(**kw):
                tried.append(w.n)
                if w.n == raise_at and tried.count(raise_at) == 1:
                    raise Boom()
                shown.append(w.n)
                return spied(**kw)
            mp.setattr(hit_feedback, "beam_contact", boom)
            log = []
            _spy_k2_records(mp, log)
            for _ in range(raise_at - 1):
                w.tick()
            del log[:]
            with pytest.raises(Boom):
                w.tick()
            assert not _h.combat_k2_open()
            (drain,) = [r for r in log if r[0] == "DRAIN"]
            n = len(drain[1])
            assert n > 1, log
            assert log[-1] == drain and log[-2][0] == "DONE", log[-3:]
            assert _h.combat_k2_drain() == []
            assert tried.count(raise_at) == n
            assert shown.count(raise_at) == n - 1
            assert nc.counts()["k2_present_python"] >= n
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
            # ... and the fight goes on natively.
            before = nc.counts()["k2_records"]
            w.tick()
            assert nc.counts()["k2_records"] > before
            assert shown.count(raise_at + 1) > 0
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()


@pytest.mark.parametrize("entry,firing", [
    ("combat_k2_next", True), ("combat_k2_end", True),
    ("combat_k2_abandon", True), ("combat_k2_drain", True),
    ("combat_k2_next", False), ("combat_k2_abandon", False)])
def test_reentrant_k2_call_during_delivery_fails_loudly(monkeypatch, entry,
                                                        firing):
    """A record's writes are applied by the binding while Python runs (here
    passive_state.wake, for the Vor'cha offline stop's WAKE-kind `_firing`
    write on a sleeping bank), inside combat_k2_next. `firing`: the Galaxy
    fires too, so resting contacts are queued for the drain. A
    combat_k2_next / _end / _abandon / _drain from that Python would step,
    free or drain the session under the apply: each must raise the
    delivery protocol error instead; the session is abandoned, the mirror
    equals Python and the next tick runs natively."""
    seen = []
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_reenter")
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            vsys = v.GetPhaserSystem()
            vsys.TurnOff()
            if firing:
                g.GetPhaserSystem().SetSingleFire(0)
                g.GetPhaserSystem().StartFiring(v)
            for _ in range(39):
                w.tick()
            vbank = vsys.GetWeapon(0)
            wake = passive_state.wake

            def hook(obj):
                if obj is vbank and not seen:
                    try:
                        getattr(_h, entry)()
                    except RuntimeError as e:
                        seen.append(str(e))
                        raise
                    seen.append("re-entered")
                return wake(obj)

            def sleep(_w):
                if "_passive_slot" not in vbank.__dict__:
                    passive_weapons._build(v)   # the passive walk's registry
                passive_state.put_to_sleep(vbank)
                mp.setattr(passive_state, "wake", hook)
            with pytest.raises(RuntimeError, match="deliver"):
                w.tick(before=sleep)
            assert len(seen) == 1 and "deliver" in seen[0], seen
            assert not _h.combat_k2_open()
            mp.setattr(passive_state, "wake", wake)
            passive_state.wake(vbank)
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
            before = nc.counts()["k2_records"]
            w.tick()                                # the next tick runs
            assert nc.counts()["k2_records"] > before
            assert not _h.combat_k2_open()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()


def test_damage_pulse_handler_starts_another_ships_k1_session(monkeypatch):
    """Final review, Review Focus 2. A damage pulse's apply_hit handler
    (after_hit) pulls another ship's trigger -- StartFiring, whose immediate
    update_weapons runs a K1 session nested inside the K2 step -- while
    resting contacts queued before the pulse wait for the drain, and a
    third ship's offline phaser stop is logged writes later in the same
    step. Per tick, every call, event and field equals the Python arm
    (presentation as a multiset)."""
    log = []
    _spy_k2_records(monkeypatch, log)
    ships = GALAXY_VORCHA + (("Dark", "vorcha", (-30.0, -240.0, 0.0), 0.0),)

    def setup(w, mp):
        _spy_presentation(w, mp)
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        w.ships["Dark"].GetPhaserSystem().TurnOff()
        w.lit = _banks_in_arc(g, v)
        assert len(w.lit) >= 2, w.lit
        w.started = []
        w.at_hook = None

        def start_other(w):
            if w.started:
                return
            w.started.append(w.n)
            if w.native:
                w.at_hook = len(log) - 1
            vs = w.ships["Vorcha"].GetPhaserSystem()
            vs.SetSingleFire(0)
            vs.StartFiring(w.ships["Galaxy"])
        w.after_hit.append(start_other)

    def script(w, t):
        if t == 0:
            v = w.ships["Vorcha"]
            for bank in w.lit:
                _light(bank, v, countdown=0.0)
                bank._dwell = 0.0
            w.lit[-1]._dwell = 0.6          # past the flush: pulses at once

    ref, nat, counts = _both(monkeypatch, ships, script, 60, setup=setup)
    _native_ran(counts)
    assert ref.started == nat.started == [1]
    kind, flush = log[nat.at_hook]
    assert kind == "CONTACT" and flush > 0.0, log[nat.at_hook]
    drain = next(r for r in log[nat.at_hook:] if r[0] == "DRAIN")
    assert drain[1], drain              # the rests queued before the pulse
    assert counts["k2_logged_system_stop"] > 0, counts
    assert counts["k1_records"] > 0, counts
    assert any(e[0] == App.ET_WEAPON_FIRED and e[1].startswith("Vorcha/")
               for e in ref.events), ref.events[:20]


# ── Combat fire events, Task 4: K2's firing stops are queued ────────────────

def _sound_log(mp, log, w):
    """Each bank sound as it is delivered: a play makes a loop handle (as a
    registered fire sound would) whose Stop is logged; the real
    _stop_loop_sound then stops and clears it."""
    def play(bank):
        log.append(("play", w.label(bank)))
        bank._loop_handle = _Loop(log, ("stop", w.label(bank)))
    mp.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play)


def test_lit_by_k1_and_stopped_by_k2_in_one_scope_plays_then_stops(
        monkeypatch):
    """Review Focus 1. Inside one scope a Galaxy's StartFiring lights its
    banks (K1 natively: FIRE_SOUND queued), the trigger is let go with the
    banks lit, its target dies, and the phaser step stops every lit bank (K2 natively: logged writes and LOOP_STOP
    queued, no BANK_STOP record). At the scope's end each loop plays, then
    stops -- none left playing -- exactly as the Python reference with the
    same scope."""
    from engine.appc import effect_queue as eq
    logs, counts = {}, None
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = World(mp, native, GALAXY_VORCHA, "k2_rf1_%d" % native)
            try:
                log = logs[native] = []
                _sound_log(mp, log, w)
                g, v = w.ships["Galaxy"], w.ships["Vorcha"]
                g.GetPhaserSystem().SetSingleFire(0)
                with eq.scope():
                    g.GetPhaserSystem().StartFiring(v)
                    phasers = g.GetPhaserSystem()
                    banks = [phasers.GetWeapon(i)
                             for i in range(phasers.GetNumWeapons())]
                    lit = [b for b in banks if b.__dict__.get("_firing")]
                    assert lit, "nothing lit"
                    # The trigger released (the pump leaves the system to
                    # `cb.phasers`), the banks still lit; the target dies.
                    phasers._fire_held = False
                    v.SetDead(1)
                    host_loop._advance_combat(list(w.order), DT,
                                              ship_instances=w.instances,
                                              push_render_data=False)
                    assert log == []        # nothing delivered mid-scope
                assert not any(b.__dict__.get("_firing") for b in lit)
                assert all(b.__dict__.get("_loop_handle") is None
                           for b in banks)
                if native:
                    counts = nc.counts()
            finally:
                w.close()
    assert logs[True] == logs[False], logs
    plays = [x for x in logs[True] if x[0] == "play"]
    assert plays and len(logs[True]) == 2 * len(plays)
    for name in {lbl for _k, lbl in plays}:
        assert [k for k, lbl in logs[True] if lbl == name] == ["play", "stop"]
    assert counts["k2_logged_bank_stop"] >= len(plays), counts
    assert counts["k2_entries"]["LOOP_STOP"] >= len(plays), counts
    assert counts["k1_entries"]["FIRE_SOUND"] == len(plays), counts


def test_a_k2_session_outside_the_scope_delivers_at_its_end(monkeypatch):
    """Ruling F3 for K2: `cb.phasers` run with no scope open (a tool, a
    test) opens the session's own deferral, so its LOOP_STOPs are delivered
    when the K2 session ends -- nothing left queued for a later tick."""
    from engine.appc import effect_queue as eq
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_outside")
        try:
            log = []
            _sound_log(mp, log, w)
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            bank = _banks_in_arc(g, v)[0]
            _light(bank, v)
            bank._loop_handle = _Loop(log, ("stop", w.label(bank)))
            v.SetDead(1)
            assert not eq.deferring()
            assert nc.k2_phasers(list(w.order), DT, w.instances)
            assert _h.combat_effect_size() == 0
            assert log == [("stop", w.label(bank))]
            assert bank._loop_handle is None
            assert nc.counts()["k2_logged_bank_stop"] == 1
        finally:
            w.close()


# ── THE DAMAGE PULSE (native damage, Task 4) ────────────────────────────────
#
# The World spies on combat.apply_hit, and a spy ON it is obeyed: every
# pulse is then a CONTACT record and Python's (every scenario above runs
# that path). These setups take the spy off, so the pulses land in the
# walk; the hits are compared as their HIT_PRESENT delivers them.

_STOCK_APPLY_HIT = combat.apply_hit


def _native_hits(w, mp):
    mp.setattr(combat, "apply_hit", _STOCK_APPLY_HIT)
    spy_hits(mp, w.calls, lambda: w.n, w.label, _hx)


def _volley(w, t):
    if t == 0:
        w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
        w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])
    elif t == 20:
        w.ships["Vorcha"].GetPhaserSystem().StartFiring(w.ships["Galaxy"])


def test_pulses_land_in_the_walk(monkeypatch):
    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, _volley, 240,
                             setup=_native_hits)
    assert _calls(ref, "hit_present")
    assert any(e[0] == App.ET_WEAPON_HIT for e in ref.events)
    _native_ran(counts)
    assert counts["k2_native_pulses"] > 0, counts
    assert counts["k2_pulse_python"] == 0, counts["k2_pulse_python_reasons"]


def test_a_spy_on_apply_hit_hands_every_pulse_back(monkeypatch):
    _ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, _volley, 240)
    assert counts["k2_native_pulses"] == 0, counts
    assert counts["k2_pulse_python_reasons"]["not_ok"] > 0, counts


def test_an_instance_patch_on_a_targets_subsystem_hands_its_pulses_back(
        monkeypatch):
    """Override-guard gap 1: the Vor'cha's shield generator shadows
    ApplyDamage on the instance (only a hit calls it). The guard's scan
    finds it, so every pulse on the Vor'cha is Python's -- the patch is
    obeyed, in both arms -- and every pulse on the Galaxy native."""
    seen = []

    def setup(w, mp):
        _native_hits(w, mp)
        shields = w.ships["Vorcha"].GetShields()
        stock = type(shields).ApplyDamage

        def patched(face, amount, _s=shields, _w=w):
            seen.append(_w.native)
            return stock(_s, face, amount)
        mp.setattr(shields, "ApplyDamage", patched, raising=False)

    _ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, _volley, 240,
                               setup=setup)
    assert counts["k2_pulse_python_reasons"]["unscanned"] > 0, counts
    assert counts["k2_native_pulses"] > 0, counts      # the Galaxy's
    assert True in seen and False in seen


@pytest.mark.parametrize("name", ("GetMaxDamage", "GetMaxDamageDistance",
                                  "GetDamageRadiusFactor"))
def test_an_instance_patch_on_a_banks_damage_getter_hands_its_pulses_back(
        monkeypatch, name):
    """The pulse reads a bank's GetMaxDamage, GetMaxDamageDistance and
    GetDamageRadiusFactor from the mirror. One shadowed on a Galaxy bank's
    instance is obeyed by handing THAT bank's pulses to Python (reason
    `python`), not its ship: the Galaxy is still walked natively (its
    resting contacts still reach the drain, which calls the bank's own
    DamageRadiusFactor: spec 2026-11-02 combat-effect-queue §4.4), and the
    Vor'cha's pulses stay native. The patch returns a different value, so a
    pulse that ignored it would differ from the reference."""
    seen = []

    def setup(w, mp):
        _native_hits(w, mp)
        for bank in _banks_in_arc(w.ships["Galaxy"], w.ships["Vorcha"]):
            stock = getattr(bank, name)

            def patched(_stock=stock, _w=w):
                seen.append(_w.native)
                return _stock() * 1.5 + 0.25
            mp.setattr(bank, name, patched, raising=False)

    _ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, _volley, 240,
                               setup=setup)
    _native_ran(counts)
    assert counts["k2_python_reasons"]["overridden"] == 0, counts
    assert counts["k2_pulse_python_reasons"].get("python", 0) > 0, counts
    assert counts["k2_native_pulses"] > 0, counts      # the Vor'cha's
    assert True in seen and False in seen
