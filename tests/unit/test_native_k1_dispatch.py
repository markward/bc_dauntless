"""K1 dispatch: the held-weapons pump and StartFiring's immediate update run
through the native fire-control kernel when native combat is on (phase 1b,
Task 5; plan docs/superpowers/plans/2026-10-31-native-combat-phase1b-fire-control.md).

Each scenario runs twice on fresh real ships -- native off (today's Python)
and native on (K1 decides, Python runs only the effects through
native_combat.run_k1) -- and compares, after every tick, each system's
bookkeeping and each bank's (IsFiring, _target is None, _fire_timer.hex(),
_depleted, charge.hex(), GetNumReady()) plus the weapon event log
(ET_WEAPON_FIRED, ET_TORPEDO_FIRED, ET_WEAPON_FIRE_FAILED (= ET_CANT_FIRE),
ET_TORPEDO_AMMO_CONSUMED: type, source, destination, order, tick). The native
arm must also show that K1 actually ran (its record count), and its mirror
must still equal the Python at the end (audit_mirror).

The neutrality of the Fire split with native off is proven by the existing
fire tests (controller ruling D), not here.
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
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")

from engine import host_loop  # noqa: E402
from engine.appc import articulation  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_pose  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import passive_weapons  # noqa: E402
from engine.appc import physical_parents  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.core import step_memo  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0

_EVENT_NAMES = {
    App.ET_WEAPON_FIRED: "fired",
    App.ET_TORPEDO_FIRED: "torpedo_fired",
    App.ET_WEAPON_FIRE_FAILED: "fire_failed",   # is ET_CANT_FIRE
    App.ET_TORPEDO_AMMO_CONSUMED: "ammo_consumed",
}


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
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


def _groups(ship):
    return [g for g in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                        ship.GetTractorBeamSystem(), ship.GetTorpedoSystem())
            if g is not None]


class World:
    """Real ships in one set, a pinned weapon clock, the event log.

    `ships` is ((name, hardpoint, (x, y, z), yaw[, script]), ...). Built the
    same way in both arms, so labels (ship name / subsystem name) line up.
    A script (e.g. "ships.BirdOfPrey") lets articulation resolve the ship's
    hardpoint leaf, so a posed ship's part slots can be resolved."""

    def __init__(self, mp, native, ships, tag, player=None):
        self.mp = mp        # the arm's patches (undone when the arm ends)
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
            if script:
                ship.SetScript(script[0])
            _load_hardpoint(ship, hardpoint)
            ship.SetTranslateXYZ(*at)
            m = TGMatrix3()
            m.MakeZRotation(yaw)
            ship.SetMatrixRotation(m)
            self.set.AddObjectToSet(ship, name)
            self.ships[name] = ship
        if player is not None:
            mp.setattr(App, "Game_GetCurrentPlayer",
                       lambda p=self.ships[player]: p)
        self.order = list(self.ships.values())
        self.systems = [g for s in self.order for g in _groups(s)]
        self.leaves = [g.GetWeapon(i) for g in self.systems
                       for i in range(g.GetNumWeapons())]
        self.labels = {}
        for s in self.order:
            self.labels[id(s)] = s.GetName()
        for g in self.systems:
            self.labels[id(g)] = "%s/%s" % (g.GetParentShip().GetName(),
                                            g.GetName())
        for w in self.leaves:
            self.labels[id(w)] = "%s/%s" % (w.GetParentSubsystem()
                                            .GetParentShip().GetName(),
                                            w.GetName())
        self.n = 0
        self.log = []
        self.events = []
        self.hooks = []
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            kind = _EVENT_NAMES.get(evt.GetEventType())
            if kind is not None:
                self.events.append((kind, self.label(evt.GetSource()),
                                    self.label(evt.GetDestination()), self.n))
            result = _orig(evt)
            for hook in list(self.hooks):
                hook(evt)
            return result

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    def label(self, obj):
        if obj is None:
            return None
        return self.labels.get(id(obj), type(obj).__name__)

    def close(self):
        App.g_kSetManager.DeleteSet(self.tag)

    def record(self):
        row = []
        for g in self.systems:
            d = g.__dict__
            row.append((self.label(g), _t(g.IsFiring()), _t(d.get("_fire_held")),
                        _t(d.get("_force_update")),
                        _t(d.get("_last_weapon_idx")),
                        _t(d.get("_last_group_fired")),
                        _t(d.get("_group_fire_mode")),
                        [self.label(t) for t in d.get("_target_list", ())]))
        for w in self.leaves:
            d = w.__dict__
            energy = isinstance(w, ws._EnergyWeaponFireMixin)
            tube = isinstance(w, ws.TorpedoTube)
            off = d.get("_target_offset")
            row.append((
                self.label(w), _t(w.IsFiring()), d.get("_target") is None,
                self.label(d.get("_target")),
                _t(d.get("_fire_timer", 0.0)),
                _t(d.get("_depleted")),
                w.GetChargeLevel().hex() if energy else None,
                _t(w.GetNumReady()) if tube else None,
                None if off is None else (
                    tuple(float(c).hex() for c in (off.x, off.y, off.z))
                    if isinstance(off, TGPoint3) else repr(off)),
                # P5: the stamp is the walk's own offset OBJECT.
                off is not None and any(
                    off is g.__dict__.get("_held_offset")
                    for g in self.systems),
            ))
        self.log.append(row)

    def tick(self, before=None):
        """One host tick: weapons' own update, then the held-weapon pump in
        a combat step block (as _advance_combat runs it)."""
        self.n += 1
        self.clock[0] += DT
        if before is not None:
            before(self)
        for s in self.order:
            passive_weapons.step_every_weapon(s, DT)
        with step_memo.combat_step():
            host_loop._pump_held_weapons(list(self.order), DT)
        self.record()


def _t(v):
    """A value with its type, so a bool written where Python writes an int
    (or a float where it writes an int) differs; floats by .hex()."""
    if isinstance(v, float):
        return ("float", v.hex())
    return (type(v).__name__, v)


def _both(monkeypatch, ships, script, ticks, player=None):
    """Run `script(world, tick)` before each of `ticks` ticks, native off then
    on; compare. Returns (reference world, native world, native counts)."""
    worlds = []
    counts = None
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = World(mp, native, ships, "k1_%d" % native, player=player)
            try:
                for t in range(ticks):
                    w.tick(before=lambda w, t=t: script(w, t))
                if native:
                    counts = nc.counts()
                    nc.audit_mirror()
                    assert nc.audit_failures() == [], nc.audit_failures()
                    assert _h.combat_k1_depth() == 0
            finally:
                w.close()
            worlds.append(w)
    ref, nat = worlds
    assert len(ref.log) == len(nat.log) >= ticks
    for i, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                i, x, y)
    assert nat.events == ref.events
    assert counts["k1_records"] > 0, counts
    return ref, nat, counts


def _kinds(world):
    return {e[0] for e in world.events}


# ── Scenarios ────────────────────────────────────────────────────────────────

def test_phaser_volley_matches(monkeypatch):
    """A Galaxy holds its phasers on a Vor'cha: banks light, drain, latch
    depleted and relight; a TurnOff mid-burst stops the system, and the
    trigger is pulled again."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (20.0, 260.0, 15.0), math.pi))

    def script(w, t):
        g = w.ships["Galaxy"].GetPhaserSystem()
        if t == 0 or t == 480:
            g.StartFiring(w.ships["Vorcha"])
        elif t == 430:
            g.TurnOff()
        elif t == 450:
            g.TurnOn()

    ref, _nat, counts = _both(monkeypatch, ships, script, 700)
    assert "fired" in _kinds(ref)
    leaves = slice(len(ref.systems), None)
    assert any(row[5][1] for rows in ref.log for row in rows[leaves]), \
        "no bank ran dry"
    assert counts["k1_python_systems"] == 0, counts


def test_pulse_lead_and_cooldown_matches(monkeypatch):
    """A Vor'cha's cannons lead a moving Galaxy with an aim offset: the
    stamp-before-arc, the cooldown, single-fire reseeds and the cannons out
    of arc retrying the list."""
    ships = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
             ("Galaxy", "galaxy", (40.0, 220.0, 12.0), math.pi))
    offset = TGPoint3(0.5, 1.0, -0.25)

    def script(w, t):
        galaxy = w.ships["Galaxy"]
        galaxy.SetVelocity(TGPoint3(6.0, -1.0, 0.5))
        p = galaxy.GetTranslate()
        galaxy.SetTranslateXYZ(p.x + 6.0 * DT, p.y - 1.0 * DT, p.z + 0.5 * DT)
        if t == 0:
            w.ships["Vorcha"].GetPulseWeaponSystem().StartFiring(galaxy,
                                                                 offset)

    ref, _nat, counts = _both(monkeypatch, ships, script, 360)
    leaves = slice(len(ref.systems), None)
    cannons = [i for i, row in enumerate(ref.log[0][leaves])
               if row[0].startswith("Vorcha/") and row[6] is not None]
    assert cannons
    # Bolts launched: some cannon's charge moved, and its cooldown ran.
    charges = {ref.log[t][leaves][i][6] for t in range(len(ref.log))
               for i in cannons}
    assert len(charges) > 1
    # The cannons stamped the walk's own offset object at least once.
    assert any(row[-1] for rows in ref.log for row in rows[leaves])
    assert counts["k1_python_systems"] == 0, counts


def test_tube_cone_failures_match(monkeypatch):
    """Torpedoes held on a target behind (forward tubes fail the cone and
    post ET_WEAPON_FIRE_FAILED once per attempt, then retry the list) and
    then re-targeted ahead without a StopFiring: the list is [behind,
    ahead], the pump gates on the held target but fires at the list head.
    The Galaxy is the player, so ET_TORPEDO_AMMO_CONSUMED posts."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Ahead", "vorcha", (10.0, 240.0, 5.0), math.pi),
             ("Behind", "vorcha", (-12.0, -230.0, 4.0), 0.0))

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            torps.StartFiring(w.ships["Behind"])
        elif t == 90:
            torps.StartFiring(w.ships["Ahead"])
        elif t == 300:
            # Dumb fire: no target, so every failed try fires dumb. The
            # tubes are reloaded by hand (their reload is 40 s).
            torps.StopFiring()
            for i in range(torps.GetNumWeapons()):
                torps.GetWeapon(i).SetNumReady(1)
            torps.StartFiring(None)

    ref, _nat, counts = _both(monkeypatch, ships, script, 480,
                              player="Galaxy")
    assert {"fire_failed", "torpedo_fired", "ammo_consumed"} <= _kinds(ref), \
        _kinds(ref)
    # The dumb volley after tick 300 launched too.
    assert any(e[0] == "torpedo_fired" and e[3] > 301 for e in ref.events)
    assert counts["k1_python_systems"] == 0, counts


def test_single_fire_and_chain_modes_match(monkeypatch):
    """Phasers toggle single fire; torpedoes walk the Galaxy's authored
    chains (Single / Dual / Quad), so the group walk advances, wraps and
    re-reads the weapon count."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (5.0, 250.0, -8.0), math.pi))

    def script(w, t):
        galaxy = w.ships["Galaxy"]
        phasers, torps = galaxy.GetPhaserSystem(), galaxy.GetTorpedoSystem()
        if t == 0:
            phasers.SetSingleFire(0)
            phasers.StartFiring(w.ships["Vorcha"])
            torps.SetFiringChainMode(1)
            torps.StartFiring(w.ships["Vorcha"])
        elif t == 120:
            phasers.SetSingleFire(1)
            torps.SetFiringChainMode(2)
        elif t == 240:
            torps.SetFiringChainMode(0)
            phasers.SetSingleFire(0)

    ref, _nat, counts = _both(monkeypatch, ships, script, 400)
    assert {"fired", "torpedo_fired"} <= _kinds(ref), _kinds(ref)
    assert counts["k1_python_systems"] == 0, counts


def test_start_firing_immediate_update_matches(monkeypatch):
    """StartFiring's own update_weapons(0.0) (force update, no memo): taps
    on every system, re-targets and stops, with the pump idle between."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (0.0, 230.0, 0.0), math.pi))

    def script(w, t):
        galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
        systems = (galaxy.GetPhaserSystem(), galaxy.GetTorpedoSystem(),
                   vorcha.GetPulseWeaponSystem())
        targets = (vorcha, vorcha, galaxy)
        g = systems[t % 3]
        if t % 7 == 6:
            g.StopFiring()
        elif t % 11 == 10:
            galaxy.GetTorpedoSystem().StartFiring(None)     # dumb
            galaxy.GetTorpedoSystem().StopFiring()
        else:
            g.StartFiring(targets[t % 3])
            g.StopFiring()      # the pump never sees it: only the tap runs

    ref, _nat, counts = _both(monkeypatch, ships, script, 150)
    assert {"fired", "torpedo_fired"} <= _kinds(ref), _kinds(ref)
    assert counts["k1_python_systems"] == 0, counts


def test_unregistered_ship_runs_python_in_order(monkeypatch):
    """A ship with no mirror row is run by today's Python loop body at its
    place in the pump's order: the kernel hands back RUN_PYTHON for each of
    its four getters, and the events interleave exactly as the Python's."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Rowless", "vorcha", (8.0, 240.0, 0.0), math.pi),
             ("Vorcha", "vorcha", (-8.0, 250.0, 3.0), math.pi))
    ticks = 200

    def script(w, t):
        if t == 0:
            nc._drop(w.ships["Rowless"])     # both arms: harmless when off
            galaxy = w.ships["Galaxy"]
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])
            w.ships["Rowless"].GetTorpedoSystem().StartFiring(galaxy)
            w.ships["Vorcha"].GetTorpedoSystem().StartFiring(galaxy)

    ref, _nat, counts = _both(monkeypatch, ships, script, ticks)
    sources = {e[1].split("/")[0] for e in ref.events if e[0] == "fired"}
    assert {"Galaxy", "Rowless", "Vorcha"} <= sources, ref.events
    # Four getters for the row-less ship, every pump.
    assert counts["k1_python_systems"] >= 4 * ticks, counts


def _launch_hook(mp, act):
    """Run `act(tube)` inside every torpedo or bolt spawn (the launch
    Python of a tube's or cannon's FIRE record: the Python that still runs
    mid-walk, now that a beam's edge and a failed aim are queue entries
    delivered at the session's end), before the spawn itself."""
    spawn = ws._spawn_projectile

    def hooked(emitter, *a, **kw):
        act(emitter)
        return spawn(emitter, *a, **kw)
    mp.setattr(ws, "_spawn_projectile", hooked)


def test_ask_answers_match_python(monkeypatch):
    """The first torpedo launch of a multi-fire walk drops the target's
    mirror row (its launch Python, mid-walk): the rest of that walk cannot
    read it, so the kernel ASKs Python to run each remaining tube's whole
    Fire, and the walk goes on with the Python answers. Later walks see an
    unnameable list entry and run whole in Python."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (0.0, 240.0, 30.0), math.pi))
    dropped = []

    def script(w, t):
        if t == 3:
            torps = w.ships["Galaxy"].GetTorpedoSystem()
            torps.SetSingleFire(0)
            torps.SetFiringChainMode(2)     # Quad: four tubes in one walk
            del dropped[:]

            def drop_target(_tube, _w=w):
                if not dropped:
                    dropped.append(True)
                    nc._drop(_w.ships["Vorcha"])    # both arms: harmless off
            _launch_hook(w.mp, drop_target)
            # With an aim offset: each asked Fire stamps the walk's object.
            torps.StartFiring(w.ships["Vorcha"], TGPoint3(1.0, -2.0, 0.5))

    ref, _nat, counts = _both(monkeypatch, ships, script, 60)
    assert sum(1 for e in ref.events if e[0] == "torpedo_fired") >= 2, \
        ref.events
    assert counts["k1_asks"] > 0, counts


def test_exception_in_an_effect_abandons_the_session(monkeypatch):
    """An effect raises (a tube's launch, here: the Python a FIRE record
    runs mid-walk): run_k1 abandons the kernel session and re-raises, and
    the mirror still equals the Python."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (0.0, 240.0, 0.0), math.pi))

    class Boom(Exception):
        pass

    def boom(*a, **kw):
        raise Boom()

    w = World(monkeypatch, True, ships, "k1_boom")
    try:
        for _ in range(3):
            w.tick()
        monkeypatch.setattr(ws, "_spawn_projectile", boom)
        before = nc.counts()["k1_records"]
        with pytest.raises(Boom):
            w.ships["Galaxy"].GetTorpedoSystem().StartFiring(
                w.ships["Vorcha"])
        assert nc.counts()["k1_records"] > before
        assert _h.combat_k1_depth() == 0
        nc.audit_mirror()
        assert nc.audit_failures() == []
    finally:
        w.close()


def test_apply_writes_wakes_sleeping_bank(monkeypatch):
    """apply_writes writes each value WITHOUT pushing (the kernel already
    wrote the mirror), but a passive-state field still wakes its sleeping
    owner; a ref field maps handles to objects; a plain field lands in the
    instance dict."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (0.0, 240.0, 0.0), math.pi))
    w = World(monkeypatch, True, ships, "k1_wake")
    try:
        galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
        passive_weapons.advance([galaxy], DT)       # full idle banks sleep
        bank = galaxy.GetPhaserSystem().GetWeapon(0)
        assert passive_state.is_asleep(bank)
        h = bank.__dict__["_nslot"]
        mirrored = _h.combat_dump(h)["_charge_level"]
        new = bank._charge_level * 0.5
        assert float(new).hex() != float(mirrored).hex()

        nc.apply_writes([(h, "_charge_level", new),
                         (h, "_fire_timer", 0.25),
                         (h, "_target", vorcha.__dict__["_nslot"])])

        assert not passive_state.is_asleep(bank)            # woke
        assert bank.__dict__["_charge_level"] == new
        assert bank.__dict__["_fire_timer"] == 0.25
        assert bank.__dict__["_target"] is vorcha
        row = _h.combat_dump(h)
        # Not pushed: the mirror keeps what it had (the kernel's job).
        assert float(row["_charge_level"]).hex() == float(mirrored).hex()
        assert float(row["_fire_timer"]).hex() != (0.25).hex()

        sys_ = galaxy.GetPhaserSystem()
        sh = sys_.__dict__["_nslot"]
        nc.apply_writes([(sh, "_target_list", [vorcha.__dict__["_nslot"]]),
                         (sh, "_last_weapon_idx", 3)])
        assert sys_.__dict__["_target_list"] == [vorcha]
        assert sys_.__dict__["_target_list"][0] is vorcha
        assert sys_.__dict__["_last_weapon_idx"] == 3
        assert _h.combat_dump(sh)["_target_list"] == []
    finally:
        w.close()


# ── Task 5 fix round ─────────────────────────────────────────────────────────

class _CountingTube(ws.TorpedoTube):
    """A mod-style subclass whose Fire does something of its own."""
    calls = []

    def Fire(self, target=None, offset=None):
        _CountingTube.calls.append(self.GetName())
        return ws.TorpedoTube.Fire(self, target, offset)


def _python_reasons(counts, session="pump"):
    return {k: v for k, v in counts["k1_python_reasons"][session].items() if v}


def test_class_override_runs_python(monkeypatch):
    """A tube whose CLASS overrides Fire: K1 must not stand in for it, so its
    system runs in Python (counted as overridden), with the same results and
    the override called the same number of times, ON and OFF."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (10.0, 240.0, 5.0), math.pi))
    calls = {}

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            _CountingTube.calls = []
            tube = torps.GetWeapon(0)
            tube.__class__ = _CountingTube
            nc.reclassify(tube)         # the row's class flags (both arms)
            torps.StartFiring(w.ships["Vorcha"])
        calls[w.native] = list(_CountingTube.calls)

    _ref, _nat, counts = _both(monkeypatch, ships, script, 120)
    assert calls[False] and calls[True] == calls[False]
    assert _python_reasons(counts).get("overridden", 0) > 0, counts
    assert _python_reasons(counts, "system").get("overridden", 0) > 0, counts


def test_k1_overridden_flag_follows_the_class(monkeypatch):
    """The row flag is 1 for a class overriding a K1 method (leaf or
    system), 0 for every stock class."""
    nc.configure(ON)
    stock = ws.TorpedoTube("t")
    sub = _CountingTube("s")

    class _Sys(ws.PhaserSystem):
        def update_weapons(self, dt):
            return ws.PhaserSystem.update_weapons(self, dt)

    system = _Sys("p")
    stock_sys = ws.PhaserSystem("q")
    flag = lambda o: _h.combat_dump(o.__dict__["_nslot"])["k1_overridden"]
    assert (flag(stock), flag(sub), flag(system), flag(stock_sys)) == \
        (0, 1, 1, 0)


def test_instance_patch_runs_python(monkeypatch):
    """`tube.Fire = ...` on one instance (as tests and tools do): found at
    WALK_START, the system runs in Python (instance_patch), ON == OFF."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (10.0, 240.0, 5.0), math.pi))
    calls = {}

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            log = calls[w.native] = []
            tube = torps.GetWeapon(0)
            real = tube.Fire

            def patched(target=None, offset=None):
                log.append(target is None)
                return real(target, offset)
            tube.Fire = patched
            torps.StartFiring(w.ships["Vorcha"])

    _ref, _nat, counts = _both(monkeypatch, ships, script, 120)
    assert calls[False] and calls[True] == calls[False]
    assert _python_reasons(counts).get("instance_patch", 0) > 0, counts


def test_pulse_effect_uses_the_decided_module(monkeypatch):
    """Python's decision carries the module it resolved; on the K1 path a
    module that no longer imports abandons the session (raise), never
    reaching _spawn_projectile with None. (One merely unloaded from
    sys.modules is imported again, as decide does:
    test_unloaded_pulse_module_reimports_like_python.)"""
    ships = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
             ("Galaxy", "galaxy", (40.0, 220.0, 12.0), math.pi))
    w = World(monkeypatch, False, ships, "k1_mod_off")
    try:
        for _ in range(3):
            w.tick()
        cannon = w.ships["Vorcha"].GetPulseWeaponSystem().GetWeapon(0)
        script = ws.pulse_module_script(cannon)
        d = cannon._fire_decide(None, None)
        assert d is not None and d[2] is sys.modules[script]
        # One property read and one module-name read per Fire, as before
        # the split (no second resolve in the effect).
        reads = []
        prop_cls = type(cannon.GetProperty())
        real = prop_cls.GetModuleName
        monkeypatch.setattr(prop_cls, "GetModuleName",
                            lambda self: reads.append(1) or real(self))
        cannon._cooldown_remaining = 0.0
        cannon._charge_level = cannon._max_charge
        assert cannon.Fire(None, None) is True
        assert len(reads) == 1
    finally:
        w.close()

    w = World(monkeypatch, True, ships, "k1_mod_on")
    try:
        for _ in range(3):
            w.tick()
        vorcha = w.ships["Vorcha"]
        script = ws.pulse_module_script(
            vorcha.GetPulseWeaponSystem().GetWeapon(0))
        # None in sys.modules: import_module raises ModuleNotFoundError.
        monkeypatch.setitem(sys.modules, script, None)
        with pytest.raises(RuntimeError, match="pulse module"):
            vorcha.GetPulseWeaponSystem().StartFiring(w.ships["Galaxy"])
        assert _h.combat_k1_depth() == 0
    finally:
        w.close()


def test_apply_writes_thaws_frozen_consumers(monkeypatch):
    """A NativeFrozenField write (`_is_on`) thaws its frozen consumer, and a
    NativeThawParentWakeField write (a tractor beam's `_firing`) thaws the
    frozen parent system -- without pushing either value."""
    from engine.appc import passive_power
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),)
    w = World(monkeypatch, True, ships, "k1_thaw")
    try:
        galaxy = w.ships["Galaxy"]
        phasers = galaxy.GetPhaserSystem()
        h = phasers.__dict__["_nslot"]
        phasers.__dict__["_power_frozen"] = True
        before = _h.combat_dump(h)["_is_on"]
        nc.apply_writes([(h, "_is_on", 0 if before else 1)])
        assert phasers.__dict__["_power_frozen"] is False
        assert _h.combat_dump(h)["_is_on"] == before          # not pushed

        tractors = galaxy.GetTractorBeamSystem()
        beam = tractors.GetWeapon(0)
        bh = beam.__dict__["_nslot"]
        assert not beam._firing
        tractors.__dict__["_power_frozen"] = True
        thawed = passive_power.counts()["thawed"]
        nc.apply_writes([(bh, "_firing", True)])
        assert tractors.__dict__["_power_frozen"] is False
        assert passive_power.counts()["thawed"] == thawed + 1
        assert _h.combat_dump(bh)["_firing"] == 0              # not pushed
    finally:
        w.close()


# ── Final fix wave ───────────────────────────────────────────────────────────

def test_weapon_system_target_offset_starts_none():
    """`_target_offset` is a NativeField (no __get__): never assigned, the
    class lookup returns the descriptor itself. Every system starts None."""
    for cls in (ws.PhaserSystem, ws.PulseWeaponSystem, ws.TorpedoSystem,
                ws.TractorBeamSystem):
        system = cls("s")
        assert getattr(system, "_target_offset", None) is None, cls
        assert "_target_offset" in system.__dict__, cls


def test_tuple_offset_reads_unset_like_python(monkeypatch):
    """An aim offset that is not a TGPoint3 (a plain tuple) is "no offset"
    to every Python reader (`isinstance(offset, TGPoint3)`): the tube aims
    at the target's centre, the pulse stamp is None. The mirror must read it
    unset too, or the next native tube decision aims off-centre."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (10.0, 240.0, 5.0), math.pi))
    offset = (300.0, -9.0, 4.0)

    def script(w, t):
        galaxy = w.ships["Galaxy"]
        torps, phasers = galaxy.GetTorpedoSystem(), galaxy.GetPhaserSystem()
        if t == 0:
            torps.StartFiring(w.ships["Vorcha"], offset)
            phasers.StartFiring(w.ships["Vorcha"], offset)
        elif t % 40 == 0:
            for i in range(torps.GetNumWeapons()):
                torps.GetWeapon(i).SetNumReady(1)

    ref, _nat, counts = _both(monkeypatch, ships, script, 240)
    assert {"fired", "torpedo_fired"} <= _kinds(ref), _kinds(ref)
    leaves = slice(len(ref.systems), None)
    assert any(row[8] == repr(offset) for rows in ref.log
               for row in rows[leaves]), "no bank stamped the tuple"
    assert counts["k1_python_systems"] == 0, counts


def _counting_can_fire(calls):
    real = ws.PhaserBank.CanFire

    def can_fire(self):
        calls.append(self.GetName())
        return real(self)
    return can_fire


def _phaser_duel(w, t):
    if t == 0:
        w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])


_DUEL = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
         ("Vorcha", "vorcha", (0.0, 240.0, 0.0), math.pi))


def test_stock_class_patch_runs_python(monkeypatch):
    """A STOCK class's own method patched (as a test or a mod does with
    `setattr(PhaserBank, "CanFire", ...)`): K1 must not stand in for it, so
    the system runs in Python (overridden) and the patch is called exactly
    as often ON as OFF."""
    calls = {}

    def script(w, t):
        if t == 0:
            calls[w.native] = []
            monkeypatch.setattr(ws.PhaserBank, "CanFire",
                                _counting_can_fire(calls[w.native]))
        _phaser_duel(w, t)
        if t == 119:
            monkeypatch.undo()

    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 120)
    assert calls[False] and calls[True] == calls[False]
    assert _python_reasons(counts).get("overridden", 0) > 0, counts


def test_stock_class_patch_before_registration_runs_python(monkeypatch):
    """The same patch made before the ships exist: their rows are flagged
    at registration against the import-time snapshot of the stock class."""
    calls = []
    monkeypatch.setattr(ws.PhaserBank, "CanFire", _counting_can_fire(calls))
    seen = {}

    def script(w, t):
        if t == 0:
            del calls[:]
        _phaser_duel(w, t)
        seen[w.native] = list(calls)

    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 120)
    assert seen[False] and seen[True] == seen[False]
    assert _python_reasons(counts).get("overridden", 0) > 0, counts


def test_unloaded_pulse_module_reimports_like_python(monkeypatch):
    """The cannons' projectile module leaves sys.modules mid-fight (an SDK
    reload): Python's _fire_decide simply imports it again, and so must
    K1's effect -- ON identical to OFF, bolts still launching."""
    ships = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
             ("Galaxy", "galaxy", (40.0, 220.0, 12.0), math.pi))
    seen = {}

    def script(w, t):
        cannons = w.ships["Vorcha"].GetPulseWeaponSystem()
        if t == 0:
            cannons.StartFiring(w.ships["Galaxy"])
        if t % 30 == 15:
            name = ws.pulse_module_script(cannons.GetWeapon(0))
            monkeypatch.delitem(sys.modules, name, raising=False)
            seen.setdefault(w.native, []).append(t)

    ref, _nat, counts = _both(monkeypatch, ships, script, 240)
    assert seen[False] == seen[True]
    leaves = slice(len(ref.systems), None)
    cannons = [i for i, row in enumerate(ref.log[0][leaves])
               if row[0].startswith("Vorcha/") and row[6] is not None]
    after = {ref.log[t][leaves][i][6] for t in range(20, len(ref.log))
             for i in cannons}
    assert len(after) > 1, "no bolt after the first unload"
    assert counts["k1_python_systems"] == 0, counts


def _drop_a_failing_tube(mp, w, dropped, clear_list=False):
    """The Galaxy's tubes held on a Bird of Prey BEHIND it, in cruise, each
    tube's stored aim offset on its wing where no authored mount is: each
    tube's Fire is ASKed (no_mount), so Python runs it mid-walk; a forward
    tube's fails
    the cone, and its failure Python -- the arm's first
    TorpedoTube._broadcast_weapon_fire_failed -- drops the failing tube's
    row (and, `clear_list`, empties the system's list). Both arms: _drop is
    harmless with native off."""
    real = ws.TorpedoTube._broadcast_weapon_fire_failed

    def failing(tube):
        if "tube" not in dropped:
            dropped["tube"] = w.label(tube)
            if clear_list:
                tube.GetParentSubsystem()._target_list = []
            nc._drop(tube)
        return real(tube)
    mp.setattr(ws.TorpedoTube, "_broadcast_weapon_fire_failed", failing)
    bop = w.ships["BoP"]
    articulation.force_pose(bop, "cruise")
    torps = w.ships["Galaxy"].GetTorpedoSystem()
    pick = _wing_pick(bop)
    # A tube aims at its STORED offset (the previous shot's): the pick.
    for i in range(torps.GetNumWeapons()):
        torps.GetWeapon(i)._target_offset = TGPoint3(*pick)
    torps.StartFiring(bop, TGPoint3(*pick))


_BEHIND_BOP = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
               ("BoP", "birdofprey", (-12.0, -200.0, 4.0), 0.0,
                "ships.BirdOfPrey"))


def test_handler_drops_the_failing_tube_row_mid_walk(monkeypatch):
    """The failing tube's row is made unencodable (its mirror row dropped)
    in the middle of the walk, by the Python of its own asked Fire. Python
    carries on with the tube object; so must K1: the tube's `_target = None`
    goes to Python as a logged write (no row to write), and its retry Fire
    is ASKed. ON identical to OFF; later walks see a stale child and run
    whole in Python."""
    dropped = {}

    def script(w, t):
        if t == 2:
            dropped[w.native] = d = {}
            _drop_a_failing_tube(w.mp, w, d)

    ref, _nat, counts = _both(monkeypatch, _BEHIND_BOP, script, 60)
    assert dropped[False].get("tube"), dropped
    assert dropped[True] == dropped[False]
    assert dropped[False]["tube"].startswith("Galaxy/Forward"), dropped
    assert "fire_failed" in _kinds(ref)
    assert counts["k1_fire_ask_reasons"]["no_mount"] > 0, counts


def test_handler_drops_the_dumb_tube_row_mid_walk(monkeypatch):
    """The dumb-fire branch with the tube's row gone: the Python of the
    tube's asked Fire drops its row and empties the system's list, and the
    Fire fails; `GetNumTargets() == 0 and weapon.IsDumbFire()` must then ask
    Python (the row is gone), and FireDumb follows. Per tick equal to
    Python."""
    asks = []
    real_next = _h.combat_k1_next
    names = {v: k for k, v in _h.combat_k1_kinds().items()}

    def spy():
        rec = real_next()
        if names[rec[0]] == "ASK":
            asks.append(rec[1])
        return rec
    monkeypatch.setattr(_h, "combat_k1_next", spy)
    dropped = {}

    def script(w, t):
        if t == 2:
            dropped[w.native] = d = {}
            _drop_a_failing_tube(w.mp, w, d, clear_list=True)

    _ref, _nat, counts = _both(monkeypatch, _BEHIND_BOP, script, 30)
    assert dropped[True] == dropped[False] and dropped[False].get("tube")
    assert "is_dumb" in asks, asks
    assert counts["k1_asks"] > 0, counts


@pytest.mark.parametrize("case", ("tube_fired", "pulse_fired"))
def test_walked_system_row_dropped_mid_walk_raises(monkeypatch, case):
    """The protocol invariant (k1_fire_control.h): Python that drops the
    WALKED SYSTEM's row mid-walk cannot be followed (Python cannot resume
    update_weapons mid-loop). Native raises a RuntimeError naming the
    invariant, after abandoning the session; the mirror still equals the
    Python. The Python is a launch's (a tube's, a cannon's FIRE record);
    the kernel next reads the system in the bookkeeping after it."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Ahead", "vorcha", (0.0, 240.0, 0.0), math.pi))
    w = World(monkeypatch, True, ships, "k1_sys_drop")
    try:
        for _ in range(3):
            w.tick()        # the banks charge
        if case == "tube_fired":
            system = w.ships["Galaxy"].GetTorpedoSystem()
            target = w.ships["Ahead"]
        else:
            system = w.ships["Ahead"].GetPulseWeaponSystem()
            target = w.ships["Galaxy"]
        dropped = []

        def drop_system(_emitter):
            if not dropped:
                dropped.append(True)
                nc._drop(system)
        _launch_hook(monkeypatch, drop_system)
        # The message names the system of the last walk Python saw, as
        # that -- not "the walked system" -- is what the driver knows.
        with pytest.raises(RuntimeError, match=(
                "%r, the system of the last walk Python saw, lost its "
                "mirror row" % (system.GetName(),))):
            system.StartFiring(target)
        assert dropped
        assert _h.combat_k1_depth() == 0
        nc.audit_mirror()
        assert nc.audit_failures() == []
    finally:
        w.close()


def test_pulse_params_refresh_across_a_mission_swap_reset(monkeypatch):
    """The mission-swap reset (_reset_projectile_module_cache) with native
    on, and the projectile module now answering a different launch speed.
    Python's decide reads the module live; K1's lead solve uses the params
    cached at registration (ruling P6), so the stale ones must be re-read
    before the next K1 decision -- even a StartFiring with no GameLoop.tick
    between the reset and it (one made during the swap). Every bolt's launch
    direction, by .hex(), ON identical to OFF."""
    ships = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
             ("Galaxy", "galaxy", (6.0, 70.0, 3.0), math.pi))
    swap_at, ticks = 90, 240
    bolts = {}
    now = [0]
    from engine.appc import projectiles
    real_register = projectiles.register

    def register(torp, *a, **kw):
        # Not a launch function (_K1_LAUNCH_FUNCS): the native arm's bolts
        # still spawn through SPAWN at the session's end, the same tick.
        v = torp._velocity
        bolts[nc.enabled()].append((
            now[0], torp._source_ship.GetName(),
            tuple(float(c).hex() for c in (v.x, v.y, v.z))))
        return real_register(torp, *a, **kw)

    def script(w, t):
        galaxy = w.ships["Galaxy"]
        cannons = w.ships["Vorcha"].GetPulseWeaponSystem()
        galaxy.SetVelocity(TGPoint3(2.0, -1.0, 0.5))
        p = galaxy.GetTranslate()
        galaxy.SetTranslateXYZ(p.x + 2.0 * DT, p.y - 1.0 * DT, p.z + 0.5 * DT)
        now[0] = t
        if t == 0:
            bolts[w.native] = []
            monkeypatch.setattr(projectiles, "register", register)
            cannons.StartFiring(galaxy)
        elif t == swap_at:
            mod = importlib.import_module(
                ws.pulse_module_script(cannons.GetWeapon(0)))
            slow = float(mod.GetLaunchSpeed()) * 0.5
            monkeypatch.setattr(mod, "GetLaunchSpeed", lambda: slow)
            ws._reset_projectile_module_cache()     # the mission swap's
            for i in range(cannons.GetNumWeapons()):
                bank = cannons.GetWeapon(i)
                bank._cooldown_remaining = 0.0
                bank._charge_level = bank._max_charge
            cannons.StartFiring(galaxy)             # before any GameLoop.tick
        elif t == ticks - 1:
            monkeypatch.undo()                      # and swap back
            ws._reset_projectile_module_cache()
        if w.native:
            nc.refresh_stale_pulse_params()         # what GameLoop.tick does

    try:
        _ref, _nat, counts = _both(monkeypatch, ships, script, ticks)
    finally:
        ws._reset_projectile_module_cache()
    assert bolts[True] == bolts[False]
    assert sum(1 for b in bolts[False] if b[0] >= swap_at) > 2, bolts[False]
    assert counts["k1_python_systems"] == 0, counts


def test_reset_clears_the_per_class_caches(monkeypatch):
    """nc.reset() forgets every per-class answer (weapon kind, override
    flag), so a class patched between two runs is judged afresh."""
    assert nc._k1_overridden(ws.PhaserBank) == 0
    assert nc._weapon_kind_of_class(ws.PhaserBank) == 5
    monkeypatch.setattr(ws.PhaserBank, "CanFire", lambda self: 0)
    nc.reset()
    assert ws.PhaserBank not in nc._kind_by_type
    assert nc._k1_overridden(ws.PhaserBank) == 1


def test_reset_lets_go_of_a_class_the_field_caches_saw():
    """nc.reset() drops the class-keyed field caches (`_class_fields`,
    `_class_hidden`, `_quiet_setters`) too, so a class a test defined
    is freed once the test is done with it. A strong key there kept a
    test-local PhaserSystem subclass alive for the rest of the process,
    where every later `WeaponSystem.__subclasses__()` walk saw it
    (tests/unit/test_subsystem_obj_type.py's classification check)."""
    import gc
    import weakref

    class Local(ws.PhaserSystem):
        pass

    nc._fields_of(Local)
    nc._hidden_fields(Local)
    nc._quiet_setter(Local, "_target_list")
    gone = weakref.ref(Local)
    del Local
    nc.reset()
    gc.collect()
    assert gone() is None


# ── Posed parts (native-combat posed parts, Task 4) ─────────────────────────
#
# A Bird of Prey swung for cruise carries its disruptor cannons on its wings;
# a Galaxy with a forced "probe part" carries its phaser banks on it (an
# explicit physical parent: headless there are no part boxes, so the name is
# taken as given). K1 walks both natively from the pushed pose tables and
# part slots, and aims tubes and cannons at a posed target's mount natively.

_HINGE = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
#: Every reason a posed ship or target (or its part slots) could send K1 to
#: Python.
_POSED_REASONS = ("posed_ship", "posed_target", "part_stale",
                  "mount_unknown", "no_mount")


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


def _weapons(system):
    return [system.GetWeapon(i) for i in range(system.GetNumWeapons())]


def _charges(world, prefix):
    """Every charge (by .hex()) a leaf labelled `prefix` held."""
    leaves = slice(len(world.systems), None)
    return {row[6] for rows in world.log for row in rows[leaves]
            if row[0].startswith(prefix)}


def _posed_reasons(counts):
    """The posed-part hand-backs: RUN_PYTHON (pump, StartFiring) and the
    Fire ASKs, by reason."""
    out = {}
    for session in ("pump", "system"):
        why = counts["k1_python_reasons"][session]
        for r in _POSED_REASONS:
            out[(session, r)] = why[r]
    for r in _POSED_REASONS:
        out[("fire_ask", r)] = counts["k1_fire_ask_reasons"][r]
    return out


def test_posed_ship_fires_natively(monkeypatch):
    """A Bird of Prey in cruise fires its wing cannons and its torpedo tube,
    and a Galaxy fires phaser banks sitting on a forced part: per tick
    equal to Python, with no posed hand-back at all."""
    ships = (("BoP", "birdofprey", (0.0, 0.0, 0.0), 0.0, "ships.BirdOfPrey"),
             ("Galaxy", "galaxy", (80.0, 0.0, 0.0), 0.0, "ships.Galaxy"),
             ("Vorcha", "vorcha", (40.0, 260.0, 15.0), math.pi))
    moved = []

    def script(w, t):
        bop, g, v = w.ships["BoP"], w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            _pose_galaxy_phasers(g)
            cannons = bop.GetPulseWeaponSystem()
            cannons.SetSingleFire(0)
            moved.append([_moved(bop, c) for c in _weapons(cannons)]
                         + [_moved(g, b) for b in
                            _weapons(g.GetPhaserSystem())])
            cannons.StartFiring(v)
            bop.GetTorpedoSystem().StartFiring(v)
            g.GetPhaserSystem().StartFiring(v)

    ref, _nat, counts = _both(monkeypatch, ships, script, 360)
    assert all(moved[0]) and all(moved[1]), moved
    sources = {e[1].split("/")[0] for e in ref.events
               if e[0] in ("fired", "torpedo_fired")}
    assert {"BoP", "Galaxy"} <= sources, ref.events
    assert "torpedo_fired" in _kinds(ref)
    # The wing cannons fired (a bolt posts no weapon event: their charge).
    assert len(_charges(ref, "BoP/Port Cannon")) > 1
    assert len(_charges(ref, "BoP/Star Cannon")) > 1
    assert counts["k1_python_systems"] == 0, counts
    assert set(_posed_reasons(counts).values()) == {0}, counts
    assert counts["k1_posed"]["walks"] > 0, counts


def test_posed_target_tube_aim_native(monkeypatch):
    """Torpedo tubes and disruptor cannons aim at the wing mounts of a Bird
    of Prey in cruise (`_RESOLVE`: the first mount at the offset, posed
    natively): per tick equal to Python, with no posed hand-back."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (30.0, 0.0, 0.0), 0.0),
             ("BoP", "birdofprey", (15.0, 200.0, 5.0), math.pi,
              "ships.BirdOfPrey"))
    moved = []

    def script(w, t):
        bop, g, v = w.ships["BoP"], w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            port, star = _weapons(bop.GetPulseWeaponSystem())
            moved.append((_moved(bop, port), _moved(bop, star)))
            off = port.GetPosition()
            # The tubes aim with the previous shot's stored offset.
            for tube in _weapons(g.GetTorpedoSystem()):
                tube._target_offset = TGPoint3(off.x, off.y, off.z)
            g.GetTorpedoSystem().StartFiring(bop, off)
            v.GetPulseWeaponSystem().StartFiring(bop, star.GetPosition())

    ref, _nat, counts = _both(monkeypatch, ships, script, 360)
    assert moved == [(True, True)] * 2, moved     # both arms
    assert {"fired", "torpedo_fired"} <= _kinds(ref), ref.events
    assert counts["k1_python_systems"] == 0, counts
    assert set(_posed_reasons(counts).values()) == {0}, counts
    assert counts["k1_posed"]["target_aims"] > 0, counts


@pytest.mark.parametrize("where", ["boundary", "mid_walk"])
def test_stale_slot_falls_back_part_stale(monkeypatch, where):
    """A part slot that is not current is never read: at the system's
    pre-scan the whole system runs in Python (RUN_PYTHON part_stale); after
    an effect bumped the part-map generation mid-walk, the next cannon's
    Fire is Python's (ASK fire, counted part_stale). Equal to Python either
    way; never posed_ship."""
    ships = (("BoP", "birdofprey", (0.0, 0.0, 0.0), 0.0, "ships.BirdOfPrey"),
             ("Vorcha", "vorcha", (5.0, 80.0, 3.0), math.pi))
    if where == "boundary":
        # No step boundary resolves the slots: every one stays unresolved.
        monkeypatch.setattr(nc, "resolve_stale_part_slots",
                            lambda ships: None)
    else:
        # A bolt's spawn (the first cannon's Fire effect) bumps the part-map
        # generation, as any effect's handler may: the second cannon's mount
        # slot is stale within the same walk.
        spawn = ws._spawn_projectile

        def spawn_then_bump(*a, **kw):
            result = spawn(*a, **kw)
            nc.bump_part_gen()
            return result

        monkeypatch.setattr(ws, "_spawn_projectile", spawn_then_bump)

    def script(w, t):
        bop, v = w.ships["BoP"], w.ships["Vorcha"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            cannons = bop.GetPulseWeaponSystem()
            cannons.SetSingleFire(0)
            cannons.StartFiring(v)
            bop.GetTorpedoSystem().StartFiring(v)

    ref, _nat, counts = _both(monkeypatch, ships, script, 240)
    assert len(_charges(ref, "BoP/Star Cannon")) > 1
    reasons = _posed_reasons(counts)
    assert reasons[("pump", "posed_ship")] == 0, counts
    assert reasons[("system", "posed_ship")] == 0, counts
    if where == "boundary":
        assert reasons[("pump", "part_stale")] > 0, counts
        assert reasons[("system", "part_stale")] > 0, counts
    else:
        assert reasons[("fire_ask", "part_stale")] > 0, counts


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


def test_manual_aim_on_posed_target_native(monkeypatch):
    """The Vor'cha's Manual Aim pick sits on a Bird of Prey's wing in
    cruise: its cannons (the walk's offset) and tubes (the stored offset)
    aim through its Manual Aim slot natively -- no no_mount Fire ASK."""
    ships = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
             ("BoP", "birdofprey", (15.0, 200.0, 5.0), math.pi,
              "ships.BirdOfPrey"))
    moved = []

    def script(w, t):
        v, bop = w.ships["Vorcha"], w.ships["BoP"]
        if t == 0:
            articulation.force_pose(bop, "cruise")
            v.SetTarget(bop)
            p = _wing_pick(bop)
            moved.append(_manual_moved(bop, p))
            v.set_manual_target_offset(TGPoint3(*p))
            for tube in _weapons(v.GetTorpedoSystem()):
                tube._target_offset = TGPoint3(*p)
            v.GetPulseWeaponSystem().SetSingleFire(0)
            v.GetPulseWeaponSystem().StartFiring(bop)
            v.GetTorpedoSystem().StartFiring(bop)

    ref, _nat, counts = _both(monkeypatch, ships, script, 240)
    assert moved == [True, True], moved
    assert "torpedo_fired" in _kinds(ref), ref.events
    assert len(_charges(ref, "Vorcha/")) > 1
    assert counts["k1_python_systems"] == 0, counts
    assert set(_posed_reasons(counts).values()) == {0}, counts
    assert counts["k1_posed"]["target_aims"] > 0, counts


# ── Round trips, Task 1: no WALK_START record ───────────────────────────────
#
# Spec docs/superpowers/specs/2026-11-01-native-combat-round-trips-design.md
# §4.1. The kernel computes the walk's aim offset VALUE itself; Python fetches
# the offset OBJECT (walked._live_held_offset(), ruling P5) and pins the walk
# only when the walk's first record arrives, or when a logged write naming
# the walk's offset is applied, whichever comes first
# (native_combat._K1Walk.materialise). A walk that hands nothing back runs no
# Python at all.

from engine.appc.ships import ShipClass  # noqa: E402
from engine.core import ids  # noqa: E402


def _spy_records(mp, log):
    """Wrap combat_k1_next: log (kind name, walk tag) for every record. The
    walk tag (rec[-2]) is None, or (walk, system handle) on the first record
    a walk hands back."""
    real = _h.combat_k1_next
    names = {v: k for k, v in _h.combat_k1_kinds().items()}

    def spy():
        rec = real()
        log.append((names[rec[0]], rec[-2]))
        return rec
    mp.setattr(_h, "combat_k1_next", spy)


def _volleys(w, t):
    """Phasers and torpedoes (with an aim offset) one way, cannons the
    other: every K1 system kind walks."""
    galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
    if t == 0:
        galaxy.GetPhaserSystem().StartFiring(vorcha)
        galaxy.GetTorpedoSystem().StartFiring(vorcha,
                                              TGPoint3(0.5, -1.0, 0.25))
        vorcha.GetPulseWeaponSystem().StartFiring(galaxy)


def test_no_walk_start_records(monkeypatch):
    """No WALK_START reaches Python: every walk starts in the kernel
    (k1_logged.walk_start counts them), and the first record a walk hands
    back carries the walk's tag. Per tick equal to Python."""
    def script(w, t):
        if t == 0:
            _forget_launches(w)     # a FIRE record (uncached) to tag
        _volleys(w, t)

    log = []
    _spy_records(monkeypatch, log)
    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 240)
    kinds = [k for k, _tag in log]
    assert kinds.count("WALK_START") == 0, kinds[:20]
    assert counts["k1_logged"]["walk_start"] > 0, counts
    # Most walks hand nothing back: fewer tagged records than walks.
    tagged = [tag for _k, tag in log if tag is not None]
    assert tagged, log[:20]
    assert len(tagged) < counts["k1_logged"]["walk_start"], counts
    assert counts["k1_python_systems"] == 0, counts


def _hexes3(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def test_offset_value_matches_live_held_offset(monkeypatch):
    """The kernel's walk offset (combat_k1_walk_offset, the predicate the
    walk uses) against WeaponSystem._live_held_offset(), by .hex(): none,
    held, a non-TGPoint3 held value (unset), Manual Aim (the manual offset
    wins), the use flag without a manual offset (held), and a firing ship
    that is not a ShipClass (held, whatever its row says)."""
    from engine.appc.objects import DamageableObject
    w = World(monkeypatch, True, _DUEL, "k1_offset")
    try:
        galaxy = w.ships["Galaxy"]
        torps = galaxy.GetTorpedoSystem()

        def check(system, want):
            py = system._live_held_offset()
            nat = _h.combat_k1_walk_offset(system.__dict__["_nslot"])
            if want is None:
                assert not isinstance(py, TGPoint3), py
                assert nat is None, nat
            else:
                assert isinstance(py, TGPoint3)
                assert _hexes3(py) == want
                assert nat is not None
                assert tuple(float(c).hex() for c in nat) == want

        check(torps, None)                                    # none
        held = TGPoint3(0.1, -2.5, 1.0 / 3.0)
        torps._held_offset = held
        check(torps, _hexes3(held))                           # held
        torps._held_offset = (300.0, -9.0, 4.0)
        check(torps, None)                                    # unset
        signed = TGPoint3(-0.0, 0.0, -0.0)
        torps._held_offset = signed
        check(torps, _hexes3(signed))                         # -0.0 kept
        nan = TGPoint3(float("nan"), 1.0, float("nan"))
        torps._held_offset = nan
        check(torps, _hexes3(nan))                            # NaN kept
        torps._held_offset = held
        manual = TGPoint3(2.0 / 7.0, -5.0 / 11.0, 13.0 / 3.0)
        galaxy.set_manual_target_offset(manual)
        check(torps, _hexes3(manual))                         # Manual Aim
        galaxy.UseTargetOffsetTG(0)
        check(torps, _hexes3(held))                           # off again
        galaxy._use_target_offset = True      # the flag, no manual offset
        assert galaxy._manual_target_offset is None
        check(torps, _hexes3(held))

        # A firing ship that is not a ShipClass: Python's probe finds no
        # is_using_target_offset, so it reads the held offset -- even when
        # the row's manual-aim fields say otherwise.
        hulk = DamageableObject()
        assert "_nslot" in hulk.__dict__
        system = ws.TorpedoSystem("hulk torps")
        system._parent_ship = hulk
        assert system.GetParentShip() is hulk
        hh = hulk.__dict__["_nslot"]
        _h.combat_set_i(hh, nc._fid("_use_target_offset"), 1)
        _h.combat_set_fv(hh, nc._fid("_manual_target_offset"),
                         [9.0, 9.0, 9.0])
        system._held_offset = held
        check(system, _hexes3(held))
        system._held_offset = None
        check(system, None)
    finally:
        w.close()


def _no_mount_cannons(w, t):
    """The Vor'cha's cannons held on a Bird of Prey in cruise with an aim
    offset on its wing that is no authored mount, and no Manual Aim: the
    lead solve cannot be made natively (no_mount), so the cannon's Fire is
    an ASK -- the FIRST record of its walk."""
    v, bop = w.ships["Vorcha"], w.ships["BoP"]
    if t == 0:
        articulation.force_pose(bop, "cruise")
        cannons = v.GetPulseWeaponSystem()
        cannons.SetSingleFire(0)
        cannons.StartFiring(bop, TGPoint3(*_wing_pick(bop)))


_NO_MOUNT = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
             ("BoP", "birdofprey", (15.0, 200.0, 5.0), math.pi,
              "ships.BirdOfPrey"))


def test_first_record_ask_sees_pinned_offset_object(monkeypatch):
    """Review Focus 1: a walk whose first record is an ASK. The walk's
    offset object is fetched, and the walk pinned, BEFORE the ASK's Python
    runs (it Fires with that object, which the cannon stamps: identity, the
    P5 column of every row), in today's order: pin, then the offset."""
    order = []
    _spy_records(monkeypatch, order)
    real_mat = nc._K1Walk.materialise
    real_pin = nc._K1Walk.pin_system
    real_answer = nc._k1_answer

    def materialise(walk, n, h):
        order.append(("materialise", n))
        return real_mat(walk, n, h)

    def pin_system(walk, system):
        order.append(("pin", system.GetName()))
        return real_pin(walk, system)

    def answer(rec, walk, dt):
        order.append(("answer", rec[1]))
        return real_answer(rec, walk, dt)

    monkeypatch.setattr(nc._K1Walk, "materialise", materialise)
    monkeypatch.setattr(nc._K1Walk, "pin_system", pin_system)
    monkeypatch.setattr(nc, "_k1_answer", answer)
    _ref, _nat, counts = _both(monkeypatch, _NO_MOUNT, _no_mount_cannons, 120)
    assert counts["k1_fire_ask_reasons"]["no_mount"] > 0, counts
    first_asks = [i for i, e in enumerate(order)
                  if e[0] == "ASK" and e[1] is not None]
    assert first_asks, order[:20]
    for i in first_asks:
        n = order[i][1][0]
        j = order.index(("answer", "fire"), i)
        # The walk's materialise (pin, then its offset) is the last Python
        # before the ASK's own.
        assert order[j - 2:j] == [("materialise", n),
                                  ("pin", "Disruptor Cannons")], order[i:j + 1]


def test_target_list_write_on_every_walk_is_a_new_list(monkeypatch):
    """Python's _prune_targets builds a NEW list on every update_weapons
    (AddTarget appends in place, so an older list object must never be the
    live one). The kernel keeps the `_target_list` write on every walk --
    a walk that hands nothing back too: its writes ride the next record or
    DONE. Each tick's list is a new object, ON as OFF."""
    seen = {}

    def script(w, t):
        _volleys(w, t)
        galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
        for g in (galaxy.GetPhaserSystem(), galaxy.GetTorpedoSystem(),
                  vorcha.GetPulseWeaponSystem()):
            seen.setdefault((w.native, w.label(g)), []).append(
                g.__dict__["_target_list"])     # held: never reused

    _both(monkeypatch, _DUEL, script, 120)
    assert len(seen) == 6, sorted(seen)
    for (arm, label), lists in seen.items():
        assert len(lists) == 120
        assert all(a is not b for a, b in zip(lists, lists[1:])), \
            (arm, label)


@pytest.mark.parametrize("where", ["system_class", "ship_class",
                                   "ship_instance", "system_instance"])
def test_live_held_offset_override_runs_python(monkeypatch, where):
    """While the Python copies exist, the walk-offset methods the kernel now
    stands in for are guarded: a patched `_live_held_offset` (system),
    `is_using_target_offset` / `GetTargetOffsetTG` (ship), on the class or
    on the instance, runs Python's own, exactly as often ON as OFF."""
    calls = {}

    def counting(real, key):
        def f(self, *a):
            calls[key].append(self.GetName())
            return real(self, *a)
        return f

    def script(w, t):
        galaxy = w.ships["Galaxy"]
        torps = galaxy.GetTorpedoSystem()
        if t == 0:
            key = w.native
            calls[key] = []
            galaxy.set_manual_target_offset(TGPoint3(0.25, 1.5, -0.5))
            if where == "system_class":
                monkeypatch.setattr(ws.WeaponSystem, "_live_held_offset",
                                    counting(ws.WeaponSystem._live_held_offset,
                                             key))
            elif where == "ship_class":
                monkeypatch.setattr(ShipClass, "GetTargetOffsetTG",
                                    counting(ShipClass.GetTargetOffsetTG, key))
            elif where == "ship_instance":
                f = counting(ShipClass.is_using_target_offset, key)
                monkeypatch.setattr(galaxy, "is_using_target_offset",
                                    lambda: f(galaxy), raising=False)
            else:
                f = counting(ws.WeaponSystem._live_held_offset, key)
                monkeypatch.setattr(torps, "_live_held_offset",
                                    lambda: f(torps), raising=False)
            torps.StartFiring(w.ships["Vorcha"], TGPoint3(1.0, 2.0, 3.0))
        if t == 119:
            monkeypatch.undo()

    _both(monkeypatch, _DUEL, script, 120)
    assert calls[False], calls
    assert calls[True] == calls[False]


def test_no_getattr_stub_on_live_held_offset_path(monkeypatch):
    """MAP §3.1 flagged it inferred: no TGObject.__getattr__ stub sits on
    `_live_held_offset`'s path (a stub would answer for a method the kernel
    reads from the mirror). A ShipClass parent with and without Manual Aim,
    a non-ShipClass parent and no parent: the stub hook is never reached."""
    from engine.appc.objects import DamageableObject
    reached = []
    real = ids.TGObject.__getattr__

    def spy(self, name):
        reached.append((type(self).__name__, name))
        return real(self, name)

    w = World(monkeypatch, True, _DUEL, "k1_stub")
    try:
        galaxy = w.ships["Galaxy"]
        torps = galaxy.GetTorpedoSystem()
        torps._held_offset = TGPoint3(1.0, 2.0, 3.0)
        hulk = DamageableObject()
        on_hulk = ws.TorpedoSystem("hulk torps")
        on_hulk._parent_ship = hulk
        orphan = ws.TorpedoSystem("orphan torps")
        monkeypatch.setattr(ids.TGObject, "__getattr__", spy)
        assert torps._live_held_offset() is torps._held_offset
        galaxy.set_manual_target_offset(TGPoint3(4.0, 5.0, 6.0))
        assert _hexes3(torps._live_held_offset()) == _hexes3(
            TGPoint3(4.0, 5.0, 6.0))
        assert on_hulk._live_held_offset() is None
        assert orphan._live_held_offset() is None
        assert reached == [], reached
    finally:
        w.close()


# ── Round trips Task 2: beam sustain and idle stops as logged writes ─────────

def _spy_fire_records(mp, log):
    """Wrap combat_k1_next: log (kind name, the named bank's object or None,
    the bank's _firing as Python holds it, the FIRE decision or None) for
    every record. `_firing` is read when the record is returned: the
    binding has already applied the record's own writes (C-applied write
    logs), so it is the value its effect (a BANK_STOP's StopFiring) really
    sees, a logged `_firing` among those writes included."""
    real = _h.combat_k1_next
    names = {v: k for k, v in _h.combat_k1_kinds().items()}

    def spy():
        rec = real()
        kind = names[rec[0]]
        bank = None
        if kind in ("FIRE", "BANK_STOP", "FIRE_FAILED", "FIRE_DUMB"):
            bank = nc._registry.get(rec[1])
        firing = bank.__dict__.get("_firing") if bank is not None else None
        log.append((kind, bank, firing, rec[3] if kind == "FIRE" else None))
        return rec
    mp.setattr(_h, "combat_k1_next", spy)


def _is_beam_decision(d):
    return d is not None and len(d) == 1 and type(d[0]) is bool


def test_beam_sustain_logged_not_recorded(monkeypatch):
    """A Fire on a beam that is ALREADY firing is three field writes in
    Python (_firing, _target, _target_offset): no sound, no event. K1 logs
    them and returns no record (k1_logged.beam_sustain counts them); since
    its edge is logged too (combat fire events), no beam FIRE record is
    left at all. Per tick equal to Python."""
    log = []
    _spy_fire_records(monkeypatch, log)
    _ref, _nat, counts = _both(monkeypatch, _DUEL, _phaser_duel, 240)
    beams = [d for kind, _b, _f, d in log
             if kind == "FIRE" and _is_beam_decision(d)]
    assert beams == [], beams
    assert counts["k1_logged"]["beam_sustain"] > 0, counts
    assert counts["k1_logged"]["beam_edge"] > 0, counts
    assert counts["k1_python_systems"] == 0, counts


def test_beam_edge_is_logged_writes_and_entries(monkeypatch):
    """The was-not-firing edge (combat fire events §4.3): its writes are
    logged and its fire sound and ET_WEAPON_FIRED are queue entries, no
    FIRE record. The sound plays exactly as often ON as OFF (the events are
    compared by _both), once per logged edge and per FIRE_SOUND entry."""
    log = []
    _spy_fire_records(monkeypatch, log)
    sounds = {}
    real = ws._EnergyWeaponFireMixin._play_fire_sfx

    def script(w, t):
        if t == 0:
            sounds[w.native] = []

            def sfx(self, _log=sounds[w.native], _w=w):
                _log.append((_w.n, _w.label(self)))
                return real(self)
            monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx",
                                sfx)
        _phaser_duel(w, t)
        if t == 239:
            monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx",
                                real)

    ref, _nat, counts = _both(monkeypatch, _DUEL, script, 240)
    assert "fired" in _kinds(ref)
    assert sounds[False] and sounds[True] == sounds[False]
    assert not [d for kind, _b, _f, d in log if kind == "FIRE"
                and _is_beam_decision(d)]
    assert counts["k1_logged"]["beam_edge"] == len(sounds[True]), counts
    assert counts["k1_entries"]["FIRE_SOUND"] == len(sounds[True]), counts
    assert counts["k1_entries"]["WEAPON_FIRED"] == len(sounds[True]), counts


def test_logged_target_offset_is_the_walk_object(monkeypatch):
    """Review Focus 2 (round trips): a lit beam's logged stamp, then a
    LATER record of the same pump session runs Python -- a tube's launch,
    whose spawn reads each lit bank's _target_offset. It must already be
    that walk's offset OBJECT (identity, not a copy, and not last tick's):
    the held offset is a new object every tick, and the phaser walk
    returns no record of its own (its edges and sustains are logged), so
    the walk is materialised by the apply of the tube's record."""
    seen = {}

    def script(w, t):
        galaxy = w.ships["Galaxy"]
        g, torps = galaxy.GetPhaserSystem(), galaxy.GetTorpedoSystem()
        if t == 0:
            obs = seen[w.native] = []
            g.SetSingleFire(0)
            g.StartFiring(w.ships["Vorcha"], TGPoint3(0.5, 1.0, -0.25))
            torps.StartFiring(w.ships["Vorcha"])

            def spy(_tube, _w=w, _g=g, _obs=obs):
                for i in range(_g.GetNumWeapons()):
                    bank = _g.GetWeapon(i)
                    if not bank.__dict__.get("_firing"):
                        continue
                    off = bank.__dict__.get("_target_offset")
                    _obs.append((_w.n, _w.label(bank),
                                 off is _g.__dict__.get("_held_offset"),
                                 _w.label(bank.__dict__.get("_target"))))
            _launch_hook(w.mp, spy)
        elif t % 40 == 20:
            # One bank drops out; it relights (an edge) while the others
            # sustain; the tubes are reloaded by hand to launch again.
            g.GetWeapon((t // 40) % g.GetNumWeapons()).StopFiring()
            for i in range(torps.GetNumWeapons()):
                torps.GetWeapon(i).SetNumReady(1)
        # A new offset object every tick (the same value).
        g._held_offset = TGPoint3(0.5, 1.0, -0.25)

    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 700)
    assert seen[True] == seen[False]
    # Some launch read a stamp made in the same tick's pump.
    assert any(o[2] for o in seen[False] if o[0] > 1), seen[False][:20]
    assert counts["k1_logged"]["beam_sustain"] > 0, counts


def _sleepy_duel(monkeypatch, native, ticks):
    """The Galaxy holds its phasers (all banks, not single fire) on the
    Vor'cha with bank 0 disabled (CanFire always refuses: idle stops).
    Bank 0 is put to sleep right before each pump, after the passive
    weapons walk, so only the pump's writes can wake it. Returns (per-tick asleep-after-pump, world log,
    counts or None)."""
    with monkeypatch.context() as mp:
        w = World(mp, native, _DUEL, "k1_sleepy_%d" % native)
        try:
            galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
            g = galaxy.GetPhaserSystem()
            bank = g.GetWeapon(0)
            bank.SetDisabledPercentage(1.5)
            g.SetSingleFire(0)
            g.StartFiring(vorcha)
            asleep = []
            for _t in range(ticks):
                w.n += 1
                w.clock[0] += DT
                passive_weapons.advance(w.order, DT)
                if not passive_state.is_asleep(bank):
                    passive_state.put_to_sleep(bank)
                with step_memo.combat_step():
                    host_loop._pump_held_weapons(list(w.order), DT)
                asleep.append(passive_state.is_asleep(bank))
                w.record()
            counts = None
            if native:
                counts = nc.counts()
                nc.audit_mirror()
                assert nc.audit_failures() == [], nc.audit_failures()
            return asleep, w.log, counts
        finally:
            w.close()


def test_idle_bank_stop_wakes_sleeping_bank(monkeypatch):
    """Review Focus 3: an idle bank's stop is logged writes now, and
    `_firing` is a WakeField -- the logged write still wakes the sleeping
    bank through apply_writes' quiet setter, exactly as Python's
    `self._firing = False` in StopFiring does. Per tick equal to Python."""
    ref_asleep, ref_log, _ = _sleepy_duel(monkeypatch, False, 120)
    nat_asleep, nat_log, counts = _sleepy_duel(monkeypatch, True, 120)
    assert False in ref_asleep and True in ref_asleep, ref_asleep
    assert nat_asleep == ref_asleep
    assert nat_log == ref_log
    assert counts["k1_logged"]["idle_bank_stop"] > 0, counts


class _Loop:
    def __init__(self, log, label):
        self.log, self.label = log, label

    def Stop(self):
        self.log.append(self.label)


def test_firing_bank_stop_is_logged_with_its_loop_stop(monkeypatch):
    """A FIRING bank's stop (combat fire events §4.3): its writes are
    logged and its loop sound's stop is a LOOP_STOP entry, no BANK_STOP
    record. The loop stops happen exactly as often, in the same order, ON
    as OFF."""
    log = []
    # _firing as StopFiring sees it: after the record's writes are applied.
    _spy_fire_records(monkeypatch, log)
    stops = {}
    real = ws._EnergyWeaponFireMixin._play_fire_sfx

    def script(w, t):
        if t == 0:
            stops[w.native] = []

            def sfx(self, _log=stops[w.native], _w=w):
                self._loop_handle = _Loop(_log, (_w.n, _w.label(self)))
            monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx",
                                sfx)
        _phaser_duel(w, t)
        if t in (100, 300, 500):
            # The lit bank becomes unable to fire: K1 stops it, firing.
            g = w.ships["Galaxy"].GetPhaserSystem()
            for i in range(g.GetNumWeapons()):
                if g.GetWeapon(i).__dict__.get("_firing"):
                    g.GetWeapon(i).SetDisabledPercentage(1.5)
                    break
        if t == 699:
            monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx",
                                real)

    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 700)
    assert stops[False] and stops[True] == stops[False]
    assert [k for k, _b, _f, _d in log if k == "BANK_STOP"] == []
    assert counts["k1_logged"]["firing_bank_stop"] > 0, counts
    assert counts["k1_entries"]["LOOP_STOP"] > 0, counts


_TRACED = ("_firing", "_beam_on_countdown", "_target", "_target_offset")


def _trace_value(w, name, value):
    if name == "_target":
        return w.label(value)
    if name == "_target_offset":
        if value is None:
            return None
        held = any(value is g.__dict__.get("_held_offset") for g in w.systems)
        return (_hexes3(value) if isinstance(value, TGPoint3)
                else repr(value), held)
    return _t(value)


def test_bank_write_order_matches_python(monkeypatch):
    """Per bank class (a disabled phaser bank among them), the pump's writes of _firing, _beam_on_countdown,
    _target and _target_offset on every leaf, in order, with their values
    (offsets by .hex() and walk-object identity): ON equal to OFF. Python
    writes go through the class's __setattr__; K1's logged writes through
    apply_writes' quiet setters, traced at the setter. Phasers, cannons and
    tubes all walk (_volleys), and both new logged paths run."""
    traces = {}
    real_quiet = nc._quiet_setter
    real_pump = host_loop._pump_held_weapons
    state = {"w": None, "on": False, "leaves": set()}

    def note(obj, name, value):
        w = state["w"]
        if state["on"] and name in _TRACED and id(obj) in state["leaves"]:
            traces[w.native].append((w.n, type(obj).__name__, w.label(obj),
                                     name, _trace_value(w, name, value)))

    def quiet(cls, name):
        setter, kind = real_quiet(cls, name)

        def traced(obj, value, _s=setter, _n=name):
            note(obj, _n, value)
            return _s(obj, value)
        return traced, kind

    def pump(ships, dt):
        state["on"] = True
        try:
            return real_pump(ships, dt)
        finally:
            state["on"] = False

    for cls in (ws.PhaserBank, ws.PulseWeapon, ws.TorpedoTube):
        real_set = cls.__setattr__

        def setattr_(self, name, value, _real=real_set):
            note(self, name, value)
            _real(self, name, value)
        monkeypatch.setattr(cls, "__setattr__", setattr_)
    monkeypatch.setattr(nc, "_quiet_setter", quiet)
    monkeypatch.setattr(host_loop, "_pump_held_weapons", pump)

    def script(w, t):
        if t == 0:
            state["w"] = w
            state["leaves"] = {id(leaf) for leaf in w.leaves}
            traces[w.native] = []
            # A phaser bank that cannot fire, all banks tried: idle energy
            # bank stops too.
            g = w.ships["Galaxy"].GetPhaserSystem()
            g.GetWeapon(0).SetDisabledPercentage(1.5)
            g.SetSingleFire(0)
        _volleys(w, t)

    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 240)
    assert traces[True] == traces[False]
    classes = {c for _n, c, _l, _f, _v in traces[False]}
    assert classes == {"PhaserBank", "PulseWeapon", "TorpedoTube"}, classes
    assert any(f == "_beam_on_countdown" for _n, _c, _l, f, _v
               in traces[False]), "no energy bank stop"
    assert counts["k1_logged"]["beam_sustain"] > 0, counts
    assert counts["k1_logged"]["idle_bank_stop"] > 0, counts


def test_ship_class_without_is_using_target_offset_hands_walk_back(
        monkeypatch):
    """A ShipClass whose class no longer resolves is_using_target_offset
    (deleted): Python's probe is None and it reads the HELD offset; the
    kernel's row says ShipClass + Manual Aim. The walk check must hand such
    a walk back (Python answers it) -- the cannons' stamps and the mirror
    then agree with Python."""
    monkeypatch.delattr(ShipClass, "is_using_target_offset")

    def script(w, t):
        v = w.ships["Vorcha"]
        if t == 0:
            v.set_manual_target_offset(TGPoint3(2.0, -3.0, 0.5))
            v.GetPulseWeaponSystem().StartFiring(w.ships["Galaxy"],
                                                 TGPoint3(0.5, 1.0, -0.25))

    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 120)
    assert counts["k1_records"] > 0, counts


@pytest.mark.parametrize("where", ["class", "instance"])
def test_stop_firing_override_runs_python(monkeypatch, where):
    """While the Python copies exist, a bank's StopFiring -- which K1 now
    stands in for on an idle bank (logged writes) -- is guarded: patched on
    the class (k1_overridden) or on the instance (the walk check), Python's
    own runs, exactly as often ON as OFF."""
    calls = {}

    def counting(real, key):
        def f(self):
            calls[key].append(self.GetName())
            return real(self)
        return f

    def script(w, t):
        g = w.ships["Galaxy"].GetPhaserSystem()
        if t == 0:
            key = w.native
            calls[key] = []
            bank = g.GetWeapon(0)
            bank.SetDisabledPercentage(1.5)     # idle stops
            if where == "class":
                monkeypatch.setattr(ws.PhaserBank, "StopFiring",
                                    counting(ws.PhaserBank.StopFiring, key))
            else:
                f = counting(ws.PhaserBank.StopFiring, key)
                monkeypatch.setattr(bank, "StopFiring", lambda: f(bank),
                                    raising=False)
            g.SetSingleFire(0)
            g.StartFiring(w.ships["Vorcha"])
        if t == 119:
            monkeypatch.undo()

    _both(monkeypatch, _DUEL, script, 120)
    assert calls[False], calls
    assert calls[True] == calls[False]


# ── Final review A1: the walk check never builds an instance dict ───────────
#
# k1_walk_check runs inside combat_k1_next with the GIL held. On CPython 3.11+
# an instance's __dict__ may still be "values only" (not materialised);
# _PyObject_GetDictPtr would BUILD it -- a GC-tracked allocation that can run
# cyclic GC, so weakref.finalize -> unregister_handle could free a mirror row
# mid-walk. The check must instead hand such a walk back to Python.

def _dict_materialised(obj):
    """True when `obj`'s managed instance dict exists as a dict object. The
    managed-dict slot sits three pointers before the object (3.11: the dict
    pointer; 3.12: the dict, or the values pointer tagged with bit 0; 3.13:
    the dict pointer)."""
    import ctypes
    slot = ctypes.c_size_t.from_address(
        id(obj) - 3 * ctypes.sizeof(ctypes.c_void_p)).value
    return slot != 0 and not slot & 1


class _ValuesOnly:
    """An ordinary class: its instances start with a values-only dict."""

    def __init__(self):
        self.a = 1


@pytest.mark.skipif(sys.version_info < (3, 11) or sys.version_info >= (3, 14),
                    reason="managed-dict layout known for 3.11-3.13 only")
def test_walk_check_hands_back_an_unmaterialised_dict(monkeypatch):
    """The walked system's registry entry resolves to an object whose
    instance dict is not materialised: the walk check answers "Python" (a
    WALK_START record) and leaves the dict unbuilt."""
    fresh = _ValuesOnly()
    assert type(fresh).__flags__ & (1 << 4), "not a managed-dict class"
    assert not _dict_materialised(fresh)
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_values_only")
        log = []
        _spy_records(mp, log)
        try:
            phasers = w.ships["Galaxy"].GetPhaserSystem()
            phasers.StartFiring(w.ships["Vorcha"])
            w.tick()
            nc._k1_send_walk_check()
            h = phasers.__dict__["_nslot"]
            import weakref
            fake = dict(nc._registry.data)
            fake[h] = weakref.KeyedRef(fresh, None, h)
            cls, (iu, gto) = nc._k1_ship_stock
            _h.combat_k1_set_walk_check(fake, nc._K1_SYSTEM_PATCHES,
                                        nc._K1_LEAF_PATCHES,
                                        nc._K1_SHIP_PATCHES, iu, gto, cls)
            mp.setattr(nc, "_k1_walk_check_sent", True)
            del log[:]
            for _ in range(3):
                w.tick()
            assert [k for k, _t in log].count("WALK_START") >= 3, log[:20]
            assert not _dict_materialised(fresh)
        finally:
            nc._k1_send_walk_check()
            w.close()


@pytest.mark.skipif(sys.version_info < (3, 11) or sys.version_info >= (3, 14),
                    reason="managed-dict layout known for 3.11-3.13 only")
def test_walk_check_hands_back_a_ship_with_an_unmaterialised_dict(
        monkeypatch):
    """The firing SHIP's registry entry resolves to an object whose instance
    dict is not materialised: its walks are handed back (WALK_START) and the
    dict stays unbuilt."""
    fresh = _ValuesOnly()
    assert not _dict_materialised(fresh)
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_values_only_ship")
        log = []
        _spy_records(mp, log)
        try:
            galaxy = w.ships["Galaxy"]
            galaxy.GetPhaserSystem().StartFiring(w.ships["Vorcha"])
            w.tick()
            nc._k1_send_walk_check()
            h = galaxy.__dict__["_nslot"]
            import weakref
            fake = dict(nc._registry.data)
            fake[h] = weakref.KeyedRef(fresh, None, h)
            cls, (iu, gto) = nc._k1_ship_stock
            _h.combat_k1_set_walk_check(fake, nc._K1_SYSTEM_PATCHES,
                                        nc._K1_LEAF_PATCHES,
                                        nc._K1_SHIP_PATCHES, iu, gto, cls)
            mp.setattr(nc, "_k1_walk_check_sent", True)
            del log[:]
            for _ in range(3):
                w.tick()
            assert [k for k, _t in log].count("WALK_START") >= 3, log[:20]
            assert not _dict_materialised(fresh)
        finally:
            nc._k1_send_walk_check()
            w.close()


# ── The walk check out of the kernel (spec 2026-11-02-combat-launch-deferral
# §4.2; k1-walk-check-map.md §4.1): verdicts scanned in the binding at
# session begin and re-validated before every combat_k1_next ───────────────

@pytest.mark.parametrize("where", ["ship", "leaf"])
def test_walk_check_names_changing_drop_the_caches(monkeypatch, where):
    """The walk check's verdicts are cached on the objects' dict versions.
    Re-sending the check with other names (a name an instance attribute
    already present now matches, on the firing ship or on a bank) must drop
    them: the next walks are handed back though no dict changed."""
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_names_drop_" + where)
        log = []
        _spy_records(mp, log)
        try:
            galaxy = w.ships["Galaxy"]
            phasers = galaxy.GetPhaserSystem()
            owner = galaxy if where == "ship" else phasers.GetWeapon(0)
            owner._k1_probe_name = 1
            phasers.StartFiring(w.ships["Vorcha"])
            for _ in range(3):
                w.tick()
            assert "WALK_START" not in [k for k, _t in log], log[:20]
            nc._k1_send_walk_check()
            cls, (iu, gto) = nc._k1_ship_stock
            leaf = nc._K1_LEAF_PATCHES
            ship = nc._K1_SHIP_PATCHES
            if where == "ship":
                ship = ship + ("_k1_probe_name",)
            else:
                leaf = leaf + ("_k1_probe_name",)
            _h.combat_k1_set_walk_check(nc._registry.data,
                                        nc._K1_SYSTEM_PATCHES, leaf, ship,
                                        iu, gto, cls)
            mp.setattr(nc, "_k1_walk_check_sent", True)
            del log[:]
            for _ in range(3):
                w.tick()
            assert [k for k, _t in log].count("WALK_START") >= 3, log[:20]
        finally:
            nc._k1_send_walk_check()
            w.close()


# The Vor'cha's cannons ASK their Fire (no_mount, _no_mount_cannons), so a
# cannon's whole Python Fire -- its bolt's _spawn_projectile -- runs inside
# an ASK answer, in the middle of the pump; the Galaxy, later in the ship
# list, is walked after it in the same pump.
_ASK_THEN_LATER = (
    ("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
    ("BoP", "birdofprey", (15.0, 200.0, 5.0), math.pi, "ships.BirdOfPrey"),
    ("Galaxy", "galaxy", (30.0, 360.0, 0.0), math.pi))


def _on_first_ask_spawn(w, hook):
    """Run `hook(w)` once, inside the first bolt spawn of the cannons' ASKed
    Fire (the same Python ON and OFF, at the same tick)."""
    real = ws._spawn_projectile
    done = []

    def spawn(*a, **k):
        if not done:
            done.append(w.n)
            hook(w)
        return real(*a, **k)
    w.mp.setattr(ws, "_spawn_projectile", spawn)
    return done


def test_mid_pump_instance_patch_is_obeyed_the_same_tick(monkeypatch):
    """Review Focus 3: Python running in the middle of the pump (an ASK
    answer) patches a method K1 stands in for on a LATER system's instance
    (`phasers.try_fire_weapon = ...`). Python's pump calls it at that
    system's walk in the same tick; so must K1 -- the verdicts are
    re-validated before every combat_k1_next, so that walk is handed back.
    ON == OFF, tick by tick."""
    calls = {}
    spawned = {}

    def patch_later_system(w):
        phasers = w.ships["Galaxy"].GetPhaserSystem()
        real = phasers.try_fire_weapon
        log = calls[w.native]

        def try_fire_weapon(*a):
            log.append(w.n)
            return real(*a)
        phasers.try_fire_weapon = try_fire_weapon

    def script(w, t):
        _no_mount_cannons(w, t)
        if t == 0:
            calls[w.native] = []
            spawned[w.native] = _on_first_ask_spawn(w, patch_later_system)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["BoP"])

    _ref, _nat, counts = _both(monkeypatch, _ASK_THEN_LATER, script, 90)
    assert spawned[False] and spawned[True] == spawned[False], spawned
    assert counts["k1_fire_ask_reasons"]["no_mount"] > 0, counts
    assert calls[False], calls
    assert calls[True] == calls[False]
    assert calls[False][0] == spawned[False][0], (calls, spawned)
    assert _python_reasons(counts).get("instance_patch", 0) > 0, counts


def test_nested_session_keeps_its_own_walk_check(monkeypatch):
    """A K1 session begun inside another (StartFiring from Python the pump
    runs: an ASK answer) scans its own system: a tube Fire patched on the
    instance just before is obeyed by the nested walk, though the outer
    pump's verdicts never cover that system (its ship is not in the pump's
    list). ON == OFF, tick by tick."""
    calls = {}
    spawned = {}

    def patch_and_start(w):
        galaxy = w.ships["Galaxy"]
        torps = galaxy.GetTorpedoSystem()
        tube = torps.GetWeapon(0)
        real = tube.Fire
        log = calls[w.native]

        def fire(target=None, offset=None):
            log.append(w.n)
            return real(target, offset)
        tube.Fire = fire
        torps.StartFiring(w.ships["BoP"])

    def script(w, t):
        _no_mount_cannons(w, t)
        if t == 0:
            # The Galaxy fires only through StartFiring's own walk.
            w.order = [s for s in w.order if s.GetName() != "Galaxy"]
            calls[w.native] = []
            spawned[w.native] = _on_first_ask_spawn(w, patch_and_start)

    _ref, _nat, counts = _both(monkeypatch, _ASK_THEN_LATER, script, 90)
    assert spawned[False] and spawned[True] == spawned[False], spawned
    assert calls[False], calls
    assert calls[True] == calls[False]
    assert calls[False][0] == spawned[False][0], (calls, spawned)
    assert _python_reasons(counts, "system").get("instance_patch", 0) > 0, \
        counts


# ── Final review A2: a raise in materialise does not strand later writes ────

class _OffsetBoom(Exception):
    pass


def test_materialise_raise_applies_later_writes(monkeypatch):
    """The binding's write apply fetches the walk's offset object
    (materialise -> system._live_held_offset()) mid-log, inside
    combat_k1_next (C-applied write logs). If that raises, the writes
    logged after it -- already in the mirror -- are still applied, in order,
    and the exception propagates out of run_k1 as it is: the mirror still
    equals Python. (The log-level semantics, notes included, are pinned
    against apply_writes by tests/unit/test_native_write_apply.py.)"""
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_materialise_raise")
        phasers = w.ships["Galaxy"].GetPhaserSystem()
        real = _h.combat_k1_next
        real_mat = nc._K1Walk.materialise
        armed, inside, fired = [], [], []

        def boom():
            raise _OffsetBoom("offset")

        def spy():
            inside.append(True)
            try:
                return real()
            finally:
                inside.pop()

        def materialise(walk, n, h):
            # A logged marker of the phasers' walk, first fetched while the
            # binding applies a record's writes.
            if armed and inside and walk.walk != n \
                    and h == phasers.__dict__["_nslot"]:
                del armed[:]
                fired.append(n)
                mp.setattr(phasers, "_live_held_offset", boom, raising=False)
            return real_mat(walk, n, h)
        mp.setattr(_h, "combat_k1_next", spy)
        mp.setattr(nc._K1Walk, "materialise", materialise)
        try:
            phasers.StartFiring(w.ships["Vorcha"])
            for _ in range(5):
                w.tick()
            phasers.SetForceUpdate(1)
            armed.append(True)
            with pytest.raises(_OffsetBoom):
                w.tick()
            assert fired, "no logged marker reached materialise"
            assert phasers.__dict__["_force_update"] is False
            assert _h.combat_k1_depth() == 0
            mp.delattr(phasers, "_live_held_offset")
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()


# ── The effect queue (combat fire events, Task 2) ────────────────────────────
# Inside the tick's scope (host_loop._combat_effect_scope, native on) the
# sounds and events of K1's effects are queued and delivered, in order, when
# the scope closes (engine/appc/effect_queue.py).

def _scoped_tick(w, before=None):
    with host_loop._combat_effect_scope():
        w.tick(before=before)


def test_bank_fired_natively_and_stopped_from_python_plays_then_stops(
        monkeypatch):
    """Review Focus 1. K1 lights the Galaxy's banks inside the tick's scope
    and Python stops them in the same tick (a death, a K2 Python record):
    nothing sounds until the boundary, then each bank's loop starts and
    stops, in that order; none is left playing."""
    from engine.appc import effect_queue as eq
    sounds = []

    def sfx(self):
        sounds.append(("play", self.GetName(), eq.deferring()))
        self._loop_handle = _Loop(sounds, ("stop", self.GetName()))
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", sfx)
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_eq_stop")
        try:
            g = w.ships["Galaxy"].GetPhaserSystem()
            before = nc.counts()["k1_records"]
            with host_loop._combat_effect_scope():
                g.StartFiring(w.ships["Vorcha"])
                w.tick()
                lit = [b for b in _weapons(g) if b._firing]
                assert lit, "K1 lit no bank"
                g.StopFiring()
                assert sounds == []
            assert nc.counts()["k1_records"] > before
            names = [b.GetName() for b in lit]
            plays = [s for s in sounds if s[0] == "play"]
            assert [s[1] for s in plays] == names
            assert not any(s[2] for s in plays)    # delivered, scope closed
            for name in names:
                assert sounds.index(("stop", name)) > sounds.index(
                    ("play", name, False))
            assert all(b._loop_handle is None for b in _weapons(g))
        finally:
            w.close()


def test_tube_launch_events_keep_bcs_order_at_the_boundary(monkeypatch):
    """Review Focus 2. A tube launch inside the scope: ET_TORPEDO_FIRED,
    ET_WEAPON_FIRED, ET_TORPEDO_AMMO_CONSUMED are delivered at the boundary,
    in that order, with the torpedo still alive at delivery."""
    from engine.appc import effect_queue as eq
    from engine.appc import projectiles
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Ahead", "vorcha", (10.0, 240.0, 5.0), math.pi))
    with monkeypatch.context() as mp:
        w = World(mp, True, ships, "k1_eq_tube", player="Galaxy")
        alive = []

        def hook(evt):
            if evt.GetEventType() == App.ET_TORPEDO_FIRED:
                alive.append(evt.GetSource() in projectiles._active)
        w.hooks.append(hook)
        try:
            torps = w.ships["Galaxy"].GetTorpedoSystem()
            with host_loop._combat_effect_scope():
                torps.StartFiring(w.ships["Ahead"])
                w.tick()
                assert w.events == []
                assert eq.deferring()
            kinds = [e[0] for e in w.events]
            assert kinds[:3] == ["torpedo_fired", "fired", "ammo_consumed"], \
                kinds
            assert len(kinds) % 3 == 0 and kinds == kinds[:3] * (
                len(kinds) // 3), kinds
            assert alive and all(alive), alive
        finally:
            w.close()


def test_a_failing_delivery_still_delivers_the_rest(monkeypatch):
    """Review Focus 4. The first delivered bank's fire sound raises: every
    later entry (its ET_WEAPON_FIRED, any other bank's) is still
    delivered, the error is re-raised after the flush (tests are the loud
    mode), and the queue is empty."""
    from engine.appc import effect_queue as eq

    class Boom(Exception):
        pass
    played = []

    def sfx(self):
        if not played:
            played.append(None)
            raise Boom("sound")
        played.append(self.GetName())
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", sfx)
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_eq_raise")
        try:
            g = w.ships["Galaxy"].GetPhaserSystem()
            with pytest.raises(Boom):
                with host_loop._combat_effect_scope():
                    g.StartFiring(w.ships["Vorcha"])
                    w.tick()
                    lit = sum(1 for b in _weapons(g) if b._firing)
            assert lit >= 1, lit
            assert len(played) == lit
            # Each bank's ET_WEAPON_FIRED followed its sound in the queue.
            fired = [e for e in w.events if e[0] == "fired"]
            assert len(fired) == lit, (fired, lit)
            assert eq.counts()["failed"] == 1
            assert _h.combat_effect_take() == []
            assert not eq.deferring()
        finally:
            w.close()


# ── K1 appends to the queue (combat fire events, Task 3) ─────────────────────
# A beam's edge, a FIRE_FAILED and a firing bank's stop are queue entries
# K1 appends; a K1 session that begins while nothing defers opens its own
# deferral (effect_queue.session(), ruling F3) and delivers at its end.

def _event_log(w):
    return [e[:3] for e in w.events]


def test_ai_session_fire_failed_then_launch_keep_emission_order(monkeypatch):
    """Review Focus 3 and ruling F3 (a). An AI-style StartFiring outside the
    tick's scope runs a K1 system session: the forward tubes fail the cone
    at the target behind (native WEAPON_FIRE_FAILED entries), then an aft
    tube launches (Python's ET_TORPEDO_FIRED, ET_WEAPON_FIRED). Native delivers
    them in the Python's order -- the failure first -- and by the time
    StartFiring returns (the session's end), not at the next tick."""
    from engine.appc import effect_queue as eq
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Ahead", "vorcha", (10.0, 240.0, 5.0), math.pi),
             ("Behind", "vorcha", (-12.0, -230.0, 4.0), 0.0))
    logs, depth_at_post = {}, {}
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = World(mp, native, ships, "k1_ai_order_%d" % native)
            seen = depth_at_post[native] = []
            w.hooks.append(lambda evt: seen.append(_h.combat_k1_depth())
                           if evt.GetEventType() in _EVENT_NAMES else None)
            try:
                torps = w.ships["Galaxy"].GetTorpedoSystem()
                torps.StartFiring(w.ships["Behind"])
                logs[native] = _event_log(w)
                assert not eq.deferring()
                assert _h.combat_effect_take() == []
            finally:
                w.close()
    kinds = [e[0] for e in logs[False]]
    assert "fire_failed" in kinds and "torpedo_fired" in kinds, kinds
    assert kinds.index("fire_failed") < kinds.index("torpedo_fired"), kinds
    assert logs[True] == logs[False]
    # Native: every event delivered at the session's end, none mid-walk.
    assert depth_at_post[True] and not any(depth_at_post[True])


def test_bank_lit_and_stopped_in_one_out_of_scope_session(monkeypatch):
    """Ruling F3 (b). One pump session outside the scope: K1 lights the
    Galaxy's phasers (native FIRE_SOUND entries), then a tube's launch
    Python (the same session) stops the phaser system. Each lit bank plays,
    then stops, its loop -- as in the Python -- and none is left playing."""
    sounds = {}
    for native in (False, True):
        log = sounds[native] = []

        def sfx(self, log=log):
            log.append(("play", self.GetName()))
            self._loop_handle = _Loop(log, ("stop", self.GetName()))
        with monkeypatch.context() as mp:
            mp.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", sfx)
            w = World(mp, native, _DUEL, "k1_lit_stop_%d" % native)
            try:
                g = w.ships["Galaxy"].GetPhaserSystem()
                torps = w.ships["Galaxy"].GetTorpedoSystem()
                banks, tubes = _weapons(g), _weapons(torps)
                charge = [b.GetChargeLevel() for b in banks]
                for b in banks:
                    b.SetChargeLevel(0.0)
                for t in tubes:
                    t.SetNumReady(0)
                # Held, nothing lit or launched yet.
                g.StartFiring(w.ships["Vorcha"])
                torps.StartFiring(w.ships["Vorcha"])
                assert not any(b._firing for b in banks) and log == []
                for b, c in zip(banks, charge):
                    b.SetChargeLevel(c)
                for t in tubes:
                    t.SetNumReady(1)
                g.SetForceUpdate(1)
                torps.SetForceUpdate(1)
                spawn = ws._spawn_projectile
                stopped = []

                def stop_on_launch(*a, **kw):
                    if not stopped:
                        stopped.append(True)
                        g.StopFiring()
                    return spawn(*a, **kw)
                mp.setattr(ws, "_spawn_projectile", stop_on_launch)
                w.tick()        # one pump session: phasers, then tubes
                assert stopped
                assert all(b._loop_handle is None for b in banks)
            finally:
                w.close()
    plays = [s for s in sounds[False] if s[0] == "play"]
    assert plays, sounds[False]
    for _, name in plays:
        log = sounds[False]
        assert log.index(("stop", name)) > log.index(("play", name))
    assert sounds[True] == sounds[False]


def test_session_started_by_a_delivery_delivers_nested_in_order(
        monkeypatch):
    """Ruling F3 (c). Inside the tick's scope a handler on the first
    delivered ET_WEAPON_FIRED (a Galaxy phaser's edge) starts the Vor'cha's
    phasers: that K1 session runs inside the delivery, defers its own
    entries (the Vor'cha's edges) and delivers them at its end -- nested,
    before the rest of the tick's batch (the Galaxy's other edges) -- in
    the Python's order."""
    from engine.appc import effect_queue as eq
    logs = {}
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = World(mp, native, _DUEL, "k1_nested_%d" % native)
            started = []

            def hook(evt, w=w, started=started):
                if evt.GetEventType() == App.ET_WEAPON_FIRED and not started:
                    started.append(eq._draining)
                    w.ships["Vorcha"].GetPhaserSystem().StartFiring(
                        w.ships["Galaxy"])
            w.hooks.append(hook)
            try:
                for _ in range(3):
                    w.tick()        # the banks charge
                g = w.ships["Galaxy"].GetPhaserSystem()
                g.SetSingleFire(0)
                with eq.scope():    # the tick's scope, in both arms
                    g.StartFiring(w.ships["Vorcha"])
                    assert w.events == []
                assert started == [True]
                logs[native] = _event_log(w)
            finally:
                w.close()
    srcs = [e[1].split("/")[0] for e in logs[False] if e[0] == "fired"]
    # Galaxy's first edge, the Vor'cha's (nested), then the Galaxy's rest.
    assert srcs[0] == "Galaxy" and srcs[1] == "Vorcha", srcs
    assert "Galaxy" in srcs[srcs.index("Vorcha"):], srcs
    assert logs[True] == logs[False]


def test_an_abandoned_session_still_delivers_its_entries(monkeypatch):
    """Ruling F5 (replaces Review Focus 5's truncation). Inside the tick's
    scope a pump session lights the Galaxy's phasers (native entries,
    appended once their writes were applied) and then a tube's launch
    raises: the session is abandoned, but its entries stand for effects
    that already happened, so they are delivered at the scope's end with
    the one queued before the session: every lit bank's sound and its
    ET_WEAPON_FIRED."""
    from engine.appc import effect_queue as eq

    class Boom(Exception):
        pass
    played = []
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx",
                        lambda self: played.append(self.GetName()))
    w = World(monkeypatch, True, _DUEL, "k1_abandon")
    try:
        g = w.ships["Galaxy"].GetPhaserSystem()
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        banks, tubes = _weapons(g), _weapons(torps)
        charge = [b.GetChargeLevel() for b in banks]
        for b in banks:
            b.SetChargeLevel(0.0)
        for t in tubes:
            t.SetNumReady(0)
        g.StartFiring(w.ships["Vorcha"])
        torps.StartFiring(w.ships["Vorcha"])
        for b, c in zip(banks, charge):
            b.SetChargeLevel(c)
        for t in tubes:
            t.SetNumReady(1)
        g.SetForceUpdate(1)
        torps.SetForceUpdate(1)

        def boom(*a, **kw):
            raise Boom("launch")
        monkeypatch.setattr(ws, "_spawn_projectile", boom)
        other = w.ships["Vorcha"].GetPhaserSystem().GetWeapon(0)
        del w.events[:]
        with pytest.raises(Boom):
            with host_loop._combat_effect_scope():
                eq.post(eq.FIRE_SOUND, other)       # before the session
                w.tick()
        lit = [b.GetName() for b in banks if b._firing]
        assert lit                                   # lit (its writes stay)
        assert played == [other.GetName()] + lit, played
        fired = [e[1] for e in w.events if e[0] == "fired"]
        assert fired == ["Galaxy/" + n for n in lit], w.events
        assert _h.combat_k1_depth() == 0
        assert _h.combat_effect_take() == []
    finally:
        w.close()


def test_system_instance_stop_patch_runs_python(monkeypatch):
    """The pump's `sys_.StopFiring()` (a held system switched off) is logged
    natively only when no StopFiring K1 stands in for is patched: an
    instance-patched StopFiring on the SYSTEM itself runs Python's own,
    exactly as often ON as OFF (_K1_SYSTEM_PATCHES, the walk check)."""
    calls = {}

    def script(w, t):
        g = w.ships["Galaxy"].GetPhaserSystem()
        if t == 0:
            key = w.native
            calls[key] = []
            g.StartFiring(w.ships["Vorcha"])
            real = ws.PhaserSystem.StopFiring

            def stop(*a, _g=g, _key=key):
                calls[_key].append((w.n, _g.GetName()))
                return real(_g, *a)
            w.mp.setattr(g, "StopFiring", stop, raising=False)
        elif t == 5:
            g.TurnOff()

    _both(monkeypatch, _DUEL, script, 12)
    assert calls[False], calls
    assert calls[True] == calls[False]


# ── Launches at the boundary (spec 2026-11-02-combat-launch-deferral) ────────
# A tube's launch is logged writes plus a SPAWN entry delivered at the tick
# boundary (or the K1 session's end); the delivery builds the torpedo from
# the fire-time record. Every launch inside the deferral spawns there, a
# module whose Create draws random numbers included (rulings L5, L6): the
# test-local fixture modules below (never a mod's).

_PURE_TORP = '''
import App

def Create(pTorp):
    kGlow = App.TGColorA()
    kGlow.SetRGBA(255.0 / 255.0, 0.5, 0.0, 1.0)
    pTorp.CreateTorpedoModel("a.tga", kGlow, 0.2, 1.2, "b.tga", kGlow, 3.0,
                             0.3, 0.6, "c.tga", kGlow, 8, 0.7, 0.4)
    pTorp.SetDamage(GetDamage())
    pTorp.SetDamageRadiusFactor(0.13)
    pTorp.SetGuidanceLifetime(GetGuidanceLifetime())
    pTorp.SetMaxAngularAccel(-(-0.15))
    return(0)

def GetLaunchSpeed():
    return(21.0)

def GetLaunchSound():
    return("Photon Torpedo")

def GetDamage():
    return 444.0

def GetGuidanceLifetime():
    return 5.0
'''

# A Create that draws a random number (ruling L6: it launches through SPAWN
# like any other).
_IMPURE_TORP = _PURE_TORP.replace(
    "    pTorp.SetDamage(GetDamage())\n",
    "    pTorp.SetDamage(App.g_kSystemWrapper.GetRandomNumber(500))\n")


def _fixture_module(tmp_path, monkeypatch, name, source):
    """Write `source` as module `name` under tmp_path and import it."""
    (tmp_path / (name + ".py")).write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module(name)


_LAUNCH_SHIPS = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
                 ("Ahead", "vorcha", (10.0, 240.0, 5.0), math.pi))

_LAUNCH_EVENTS = {
    App.ET_TORPEDO_ENTERED_SET: "entered",
    App.ET_TORPEDO_FIRED: "torpedo_fired",
    App.ET_WEAPON_FIRED: "fired",
    App.ET_TORPEDO_AMMO_CONSUMED: "ammo_consumed",
}


def _hx(p):
    if p is None:
        return None
    if isinstance(p, TGPoint3):
        p = (p.x, p.y, p.z)
    return tuple(float(c).hex() for c in p)


class _Launches:
    """One arm's launches: every spawned torpedo (numbered in creation
    order, labelled "T<n>"), the launch events in order, and each torpedo's
    fields (`spawned`) as they were when it entered its set."""

    def __init__(self, w):
        from engine.appc import projectiles
        self.w = w
        self.torps = []
        self.events = []
        self.spawned = []
        register = projectiles.register

        def spy(torp, *a, _orig=register, **kw):
            self.torps.append(torp)
            _orig(torp, *a, **kw)
        w.mp.setattr(projectiles, "register", spy)
        w.hooks.append(self._hook)

    def label(self, obj):
        for i, t in enumerate(self.torps):
            if t is obj:
                return "T%d" % i
        return self.w.label(obj)

    def _hook(self, evt):
        kind = _LAUNCH_EVENTS.get(evt.GetEventType())
        if kind is None:
            return
        self.events.append((kind, self.label(evt.GetSource()),
                            self.label(evt.GetDestination()), self.w.n))
        if kind == "entered":
            self.spawned.append(self.fields(evt.GetDestination()))

    def fields(self, t):
        """Every value the spawn sets, by .hex()."""
        g = lambda name: getattr(t, name, None)  # noqa: E731
        baked = g("_baked_offset")
        return (
            self.label(t), _hx(t.GetTranslate()), _hx(t._velocity),
            _t(g("_damage")), _t(g("_damage_radius_factor")),
            _t(g("_ttl")), _t(g("_guidance_lifetime")),
            _t(g("_guidance_initial")), _t(g("_max_angular_accel")),
            self.label(g("_target_ship")), _hx(g("_target_offset")),
            None if baked is None else (self.label(baked[0]),
                                        _hx(baked[1:4]), _hx(baked[4])),
            self.label(t._source_ship),
            t.GetContainingSet() is self.w.set,
            g("_core_texture"), _t(g("_is_disruptor")),
        )


def _learn_launches(w):
    """Python's first launch of a script caches its launch; here, as if one
    had run: every ammo type's script, learned (native arm only)."""
    if not w.native:
        return
    for s in w.order:
        torps = s.GetTorpedoSystem()
        if torps is None:
            continue
        for ammo in torps._ammo_by_slot.values():
            script = ammo.GetTorpedoScript()
            nc.learn_tube_launch(script, ws._resolve_projectile_module(script))


def _forget_launches(w):
    """Every ammo type's launch forgotten without the re-read -- as a
    projectile-cache reset made inside a K1 session leaves them (THE P6
    WINDOW) -- so its next launch is handed back uncached and Python's
    launch learns it (native arm only)."""
    if not w.native:
        return
    ws._tube_launch_cache.clear()
    for h, obj in list(nc._registry.items()):
        if isinstance(obj, ws.TorpedoAmmoType):
            nc._push_ammo_row(obj)


def _launch_arms(monkeypatch, script, ticks, *, ships=_LAUNCH_SHIPS,
                 learn=True, inside=None, player="Galaxy"):
    """Both arms over `ticks` scoped ticks (the tick's effect scope, as in
    play): `script(w, t)` before each tick, `inside(w, t)` inside the scope
    after it (what the rest of the step does after the weapons: in the
    reference it runs after the launches too). Returns (ref, nat) as
    (world, launches, counts)."""
    arms = []
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = World(mp, native, ships, "k1_launch_%d" % native,
                      player=player)
            launches = _Launches(w)
            try:
                if learn:
                    _learn_launches(w)
                for t in range(ticks):
                    with host_loop._combat_effect_scope():
                        w.tick(before=lambda w, t=t: script(w, t))
                        if inside is not None:
                            inside(w, t)
                counts = nc.counts() if native else None
                if native:
                    nc.audit_mirror()
                    assert nc.audit_failures() == [], nc.audit_failures()
                    assert _h.combat_k1_depth() == 0
                    assert _h.combat_effect_take() == []
            finally:
                w.close()
            arms.append((w, launches, counts))
    (rw, rl, _), (nw, nl, _) = arms
    for i, (a, b) in enumerate(zip(rw.log, nw.log), start=1):
        assert a == b, "tick %d differs:\n python %r\n native %r" % (i, a, b)
    assert nl.events == rl.events
    for i, (a, b) in enumerate(zip(rl.spawned, nl.spawned)):
        for j, (x, y) in enumerate(zip(a, b)):
            assert x == y, "torpedo %d field %d:\n python %r\n native %r" % (
                i, j, x, y)
    assert len(nl.spawned) == len(rl.spawned)
    return arms


def _tube_volley(w, t):
    torps = w.ships["Galaxy"].GetTorpedoSystem()
    if t == 0:
        torps.StartFiring(w.ships["Ahead"], TGPoint3(0.25, -0.5, 0.125))
    elif t % 31 == 0:
        for tube in _weapons(torps):
            tube.SetNumReady(1)


def test_native_tube_launch_spawns_at_the_boundary(monkeypatch):
    """Spec §4.1, ruling L2. The Galaxy's tubes launch at the Vor'cha: with
    native on each launch is logged writes plus a SPAWN delivered at the
    tick's boundary -- no FIRE record -- and every spawned torpedo, field by
    field, and every launch event, in order, equals Python's: the spawn
    (ENTERED_SET), TORPEDO_FIRED, WEAPON_FIRED, AMMO_CONSUMED (the
    player's)."""
    (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, _tube_volley, 95)
    assert len(rl.spawned) >= 3, rl.events
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned), counts
    assert not any(counts["k1_launch_reasons"].values()), counts
    kinds = [e[0] for e in nl.events]
    assert kinds == ["entered", "torpedo_fired", "fired",
                     "ammo_consumed"] * (len(kinds) // 4), kinds
    for spawned in nl.spawned:          # aimed: the held offset, baked
        assert spawned[9] == "Ahead" and spawned[10] is not None


def test_a_type_is_cached_when_loaded(monkeypatch):
    """Task 5: a type's launch is read when its ammo type is loaded, not
    learned from its first shot: with nothing launched before, the first
    launch of each script is native (no launch_uncached), every torpedo
    field by field as the reference's."""
    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, _tube_volley, 95, learn=False)
    assert counts["k1_launch_reasons"]["launch_uncached"] == 0, counts
    assert not any(counts["k1_launch_reasons"].values()), counts
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned) >= 3


def test_first_launch_of_a_script_is_python_then_cached(monkeypatch):
    """P6 extended: a type whose launch is not cached (forgotten without the
    re-read: THE P6 WINDOW) hands its next launch back (the FIRE record,
    launch_uncached); Python's launch caches it and every later launch of
    any ammo type of that script is native."""
    def script(w, t):
        if t == 0:
            _forget_launches(w)
        _tube_volley(w, t)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 95, learn=False)
    assert counts["k1_launch_reasons"]["launch_uncached"] == 1, counts
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned) - 1 >= 2


def test_a_launcher_freed_before_the_boundary_still_spawns(monkeypatch):
    """Final review 1: a launch's queue entries hold the launcher, ship and
    set as objects from fire time, as they hold the target. A tube row
    freed between the fire and the boundary (unregistered behind the
    registry's back, as its finalizer would) loses neither the torpedo nor
    its events once the launch writes have applied: every launch is still
    the spawn, ENTERED_SET, TORPEDO_FIRED, WEAPON_FIRED, AMMO_CONSUMED, and
    nothing is skipped."""
    from engine.appc import effect_queue as eq
    with monkeypatch.context() as mp:
        w = World(mp, True, _LAUNCH_SHIPS, "k1_freed_launcher",
                  player="Galaxy")
        launches = _Launches(w)
        freed = []
        try:
            for t in range(40):
                before = nc.counts()["k1_logged"]["tube_launch"]
                with host_loop._combat_effect_scope():
                    w.tick(before=lambda w, t=t: _tube_volley(w, t))
                    if nc.counts()["k1_logged"]["tube_launch"] > before:
                        torps = w.ships["Galaxy"].GetTorpedoSystem()
                        for tube in _weapons(torps):
                            freed.append(tube)
                            nc.unregister_handle(tube.__dict__.pop("_nslot"))
                if freed:
                    break
            launched = nc.counts()["k1_logged"]["tube_launch"]
            gone = eq.counts()["skipped_gone"]
        finally:
            w.close()
    assert freed and launched >= 1
    assert gone == 0
    assert len(launches.spawned) == launched, launches.events
    kinds = [e[0] for e in launches.events]
    assert kinds == ["entered", "torpedo_fired", "fired",
                     "ammo_consumed"] * launched, kinds


def test_spawn_is_where_the_ship_was_at_fire_time(monkeypatch):
    """Review Focus 1. After the weapons the rest of the step moves the
    firing ship (a tractor): the torpedo still spawns, and flies, from
    where the tube was when it fired -- as in the reference, which spawned
    it there mid-walk."""
    def tractor(w, t):
        g = w.ships["Galaxy"]
        p = g.GetTranslate()
        g.SetTranslateXYZ(p.x + 3.0, p.y - 2.0, p.z + 1.0)
        g.SetVelocity(TGPoint3(t * 0.5, 1.0, -0.25))

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, _tube_volley, 95, inside=tractor)
    assert counts["k1_logged"]["tube_launch"] >= 3, counts


def test_last_round_debits_like_python(monkeypatch):
    """Review Focus 2. A finite magazine down to its last rounds: the ammo
    debit, `_num_ready`, the slot cooldown and the fire stamps are Python's
    exactly, the magazine ends empty, and the player's
    ET_TORPEDO_AMMO_CONSUMED follows each spawn."""
    state = {}

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            ammo = torps.GetCurrentAmmoType()
            ammo.SetMaxTorpedoes(4)
            ammo.SetAvailable(2)
        _tube_volley(w, t)
        tube_rows = []
        for tube in _weapons(torps):
            d = tube.__dict__
            tube_rows.append((_t(d["_num_ready"]), _t(d["_last_fire_time"]),
                              [x.hex() for x in d["_reload_timers"]],
                              [x.hex() for x in d["_reload_advanced_at"]]))
        state.setdefault(w.native, []).append((
            _t(torps.GetCurrentAmmoType().GetAvailable()),
            _t(torps.__dict__["_last_system_fire_time"]), tube_rows))

    (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 95)
    assert state[True] == state[False]
    assert state[False][-1][0] == ("int", 0)
    assert len(nl.spawned) == 2 and counts["k1_logged"]["tube_launch"] == 2
    assert [e[0] for e in nl.events].count("ammo_consumed") == 2


def test_dead_or_dropped_target_keeps_the_fire_time_values(monkeypatch):
    """Review Focus 5. The target dies after the weapons (and, the next
    volley, its row is dropped: a value the mirror cannot hold) before the
    boundary: the torpedo is spawned anyway with the target it fired at,
    as the reference -- which spawned it mid-walk, the target still alive
    -- did."""
    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        ahead = w.ships["Ahead"]
        if t in (0, 31):
            ahead.SetDead(False)
            for tube in _weapons(torps):
                tube.SetNumReady(1)
            torps.StartFiring(ahead, TGPoint3(0.25, -0.5, 0.125))

    def kill(w, t):
        if t == 0:
            w.ships["Ahead"].SetDead(True)
        elif t == 31 and w.native:
            nc._drop(w.ships["Ahead"])

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 40, inside=kill)
    assert [s[9] for s in nl.spawned] == ["Ahead", "Ahead"], nl.spawned
    assert counts["k1_logged"]["tube_launch"] == 2, counts


_MATAN = []


def _matan_like_handler(TGObject, pEvent):
    """E8M2.TorpedoEnterSet's shape: a torpedo entering its set locked on
    the one ship gets a 10 s lifetime."""
    pTorpedo = App.Torpedo_Cast(pEvent.GetDestination())
    if pTorpedo and _MATAN and pTorpedo.GetTargetID() == _MATAN[0]:
        pTorpedo.SetLifetime(10)
    TGObject.CallNextHandler(pEvent)


def test_entered_set_handler_acts_on_the_spawned_torpedo(monkeypatch):
    """Ruling L2: ET_TORPEDO_ENTERED_SET moves to the boundary with the
    spawn, and a handler like E8M2's that shortens a torpedo's life sees
    the torpedo there and sets it, exactly as mid-walk."""
    def script(w, t):
        if t == 0:
            _MATAN[:] = [w.ships["Ahead"].GetObjID()]
            App.g_kEventManager.AddBroadcastPythonFuncHandler(
                App.ET_TORPEDO_ENTERED_SET, w.ships["Galaxy"],
                __name__ + "._matan_like_handler")
        _tube_volley(w, t)

    try:
        (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 40)
    finally:
        _MATAN[:] = []
    lives = [t._ttl for t in nl.torps]
    assert lives and all(life == 10.0 for life in lives), lives
    assert counts["k1_logged"]["tube_launch"] >= 2, counts


def test_launches_the_kernel_cannot_make_run_python(monkeypatch):
    """Review Focus 4. An ammo type with no script (Python reads the
    property's: launch_unresolved) and a patched spawn function
    (launch_patched): each launch is the FIRE record, run in Python, never
    guessed -- and equal to the reference."""
    for case in ("unresolved", "patched"):
        def script(w, t, case=case):
            torps = w.ships["Galaxy"].GetTorpedoSystem()
            if t == 0:
                ammo = torps.GetCurrentAmmoType()
                if case == "unresolved":
                    ammo.SetTorpedoScript(None)
                else:
                    spawn = ws._spawn_projectile
                    w.mp.setattr(ws, "_spawn_projectile",
                                 lambda *a, **kw: spawn(*a, **kw))
            _tube_volley(w, t)

        (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 64)
        assert len(nl.spawned) >= 2, case
        why = counts["k1_launch_reasons"]
        assert why["launch_" + case] >= 1, (case, why)
        assert counts["k1_logged"]["tube_launch"] == 0, (case, counts)


def test_python_fallback_launch_defers_its_spawn(monkeypatch):
    """Ruling E4 for launches: the launch K1 hands back (here uncached, its
    launch forgotten) runs Python's effect mid-walk, but its spawn -- and
    its ET_TORPEDO_ENTERED_SET -- wait for the boundary like the kernel's,
    so every launch in the scope spawns there in emission order."""
    from engine.appc import effect_queue as eq
    spawned_while = []

    def script(w, t):
        if t == 0:
            _forget_launches(w)
        _tube_volley(w, t)
        if t == 0:
            w.hooks.append(lambda evt: spawned_while.append(
                (eq._draining, _h.combat_k1_depth()))
                if evt.GetEventType() == App.ET_TORPEDO_ENTERED_SET
                else None)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 40, learn=False)
    assert counts["k1_launch_reasons"]["launch_uncached"] == 1, counts
    native = spawned_while[len(spawned_while) // 2:]
    assert native and all(d and depth == 0 for d, depth in native), \
        spawned_while


def test_impure_module_launches_through_spawn(tmp_path, monkeypatch):
    """Ruling L6: a module whose Create draws a random number is no reason
    to hand a launch back: it is cached like any other, the kernel makes
    the launch, and Create runs (and draws) at the boundary. With nothing
    else drawing in the tick the torpedo equals the reference's."""
    impure = "k1fx_impure_launch"
    _fixture_module(tmp_path, monkeypatch, impure, _IMPURE_TORP)

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            torps.GetCurrentAmmoType().SetTorpedoScript(impure)
            App.g_kSystemWrapper.SetRandomSeed(7)
        _tube_volley(w, t)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 64)
    assert len(nl.spawned) >= 2
    # SetTorpedoScript cached it (Task 5): every launch native.
    assert counts["k1_launch_reasons"]["launch_uncached"] == 0, counts
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned) >= 2


_PULSE_SHIPS = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
                ("Galaxy", "galaxy", (40.0, 220.0, 12.0), math.pi))


def test_python_pulse_launch_defers_its_spawn(monkeypatch):
    """Ruling L5. Inside the deferral a cannon's bolt is a SPAWN (the
    kernel's since Task 3; a launch it hands back runs Python's, which
    defers too: test_pulse_launch_with_an_unloaded_module_runs_python):
    built at the boundary with the fire-time values, scaled by the
    fire-time power setting after its set entry, then its ET_WEAPON_FIRED
    -- every bolt, field by field, and every event, as the reference."""
    def script(w, t):
        if t == 0:
            w.ships["Vorcha"].GetPulseWeaponSystem().StartFiring(
                w.ships["Galaxy"], TGPoint3(0.5, 1.0, -0.25))
            for c in _weapons(w.ships["Vorcha"].GetPulseWeaponSystem()):
                c.SetPowerSetting(2)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 240, ships=_PULSE_SHIPS, player="Vorcha")
    assert len(nl.spawned) >= 2
    assert all(s[15] == ("bool", True) for s in nl.spawned)  # bolts
    kinds = [e[0] for e in nl.events]
    assert kinds == ["entered", "fired"] * (len(kinds) // 2), kinds
    damages = [t._damage for t in nl.torps]
    assert damages == [t._damage for t in rl.torps]


def _pulse_volley(w, t):
    """The Vor'cha's cannons held on the Galaxy with an aim offset, each at
    its own power setting (LOW, MED, HIGH, ...: the bolt's damage scale and
    the shot's cost); the cooldown and the charge as they stand before each
    tick, by .hex(), in `w.pulse_state`."""
    cannons = w.ships["Vorcha"].GetPulseWeaponSystem()
    if t == 0:
        w.pulse_state = []
        for i, c in enumerate(_weapons(cannons)):
            c.SetPowerSetting(i % 3)
        cannons.StartFiring(w.ships["Galaxy"], TGPoint3(0.5, 1.0, -0.25))
    w.pulse_state.append([(c.__dict__["_charge_level"].hex(),
                           c.__dict__["_cooldown_remaining"].hex())
                          for c in _weapons(cannons)])


def test_native_pulse_launch_spawns_at_the_boundary(monkeypatch):
    """Task 3. A cannon's Fire decided natively is no FIRE record any more:
    the drain and the cooldown are logged writes, and the bolt a SPAWN whose
    fire-time record the kernel computed -- the mount, unit(the led
    direction) x launch speed + the ship's velocity, the target, its offset
    and bake, the DamageRadiusFactor and the power setting's damage scale.
    Every bolt, field by field, its damage (scaled after its set entry, as
    Python does), every launch event in order (the spawn, then its
    ET_WEAPON_FIRED from the delivery), the drains and the cooldowns: as the
    reference."""
    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, _pulse_volley, 240, ships=_PULSE_SHIPS, player="Vorcha")
    assert nw.pulse_state == rw.pulse_state
    assert len(nl.spawned) >= 3, rl.events
    assert counts["k1_logged"]["pulse_launch"] == len(nl.spawned), counts
    assert not any(counts["k1_launch_reasons"].values()), counts
    kinds = [e[0] for e in nl.events]
    assert kinds == ["entered", "fired"] * (len(kinds) // 2), kinds
    damages = [t._damage for t in nl.torps]
    assert damages == [t._damage for t in rl.torps]
    assert len(set(damages)) > 1, damages      # more than one power setting
    for spawned in nl.spawned:          # aimed: the held offset, baked
        assert spawned[9] == "Galaxy" and spawned[10] is not None


def test_pulse_spawn_is_where_the_ship_was_at_fire_time(monkeypatch):
    """Review Focus 1 for cannons: the rest of the step moves the firing
    Vor'cha (a tractor) after its weapons: each bolt still spawns where the
    cannon was when it fired, with the velocity it had then, as in the
    reference (which spawned it mid-walk)."""
    def tractor(w, t):
        v = w.ships["Vorcha"]
        p = v.GetTranslate()
        v.SetTranslateXYZ(p.x + 3.0, p.y - 2.0, p.z + 1.0)
        v.SetVelocity(TGPoint3(t * 0.5, 1.0, -0.25))

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, _pulse_volley, 120, ships=_PULSE_SHIPS, player="Vorcha",
        inside=tractor)
    assert counts["k1_logged"]["pulse_launch"] == len(nl.spawned) >= 2


def test_pulse_launch_with_an_unloaded_module_runs_python(monkeypatch):
    """Review Focus 4 for cannons. The cannons' module gone from sys.modules
    -- an SDK reload: Python's decide imports it again, a module the
    kernel's cached one is not (launch_unresolved, THE LAUNCH CHECK): each
    launch is the FIRE record, run in Python, never guessed -- equal to the
    reference."""
    def script(w, t):
        if t == 0:                  # before StartFiring's own walk
            cannon = w.ships["Vorcha"].GetPulseWeaponSystem().GetWeapon(0)
            # (Not yet imported in the reference arm: nothing pushed it.)
            w.mp.delitem(sys.modules, ws.pulse_module_script(cannon),
                         raising=False)
        _pulse_volley(w, t)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 120, ships=_PULSE_SHIPS, player="Vorcha")
    assert nw.pulse_state == rw.pulse_state
    assert len(nl.spawned) >= 2
    why = counts["k1_launch_reasons"]
    assert why["launch_unresolved"] == len(nl.spawned), why
    assert counts["k1_logged"]["pulse_launch"] == 0, counts


def test_pulse_launch_with_a_patched_launch_function_runs_python(
        monkeypatch):
    """Review Focus 4 for cannons: a launch function patched (a test's
    spy, a tool) -- every cannon launch is the FIRE record (launch_patched)
    and spawns mid-walk through the patch (ruling L7). Native only: two
    cannons launching in one walk then order their events unlike the
    reference (the spawns mid-walk, the ET_WEAPON_FIRED at the boundary),
    as a patched tube's do (test_patched_launch_function_seen_by_the_next_
    walk); parity under a patch is not what this pins."""
    spawned = []
    with monkeypatch.context() as mp:
        w = World(mp, True, _PULSE_SHIPS, "k1_pulse_patch", player="Vorcha")
        spawn = ws._spawn_projectile

        def spy(*a, **kw):
            torp = spawn(*a, **kw)
            spawned.append(torp)
            return torp
        mp.setattr(ws, "_spawn_projectile", spy)
        try:
            for t in range(120):
                with host_loop._combat_effect_scope():
                    w.tick(before=lambda w, t=t: _pulse_volley(w, t))
            counts = nc.counts()
        finally:
            w.close()
    assert len(spawned) >= 2
    assert counts["k1_launch_reasons"]["launch_patched"] == len(spawned)
    assert counts["k1_logged"]["pulse_launch"] == 0, counts


def test_launch_check_moves_the_epoch_only_on_a_change(monkeypatch):
    """The launch check runs before every combat_k1_next: it sets its
    flags only when they change, so a record that changes nothing leaves
    the mirror's epoch where it was (K0's and K2's caches key on it)."""
    w = World(monkeypatch, True, (("Galaxy", "galaxy", (0.0, 0.0, 0.0),
                                   0.0),), "k1_epoch")
    try:
        w.tick()
        before = _h.combat_epoch()
        for _ in range(3):
            with step_memo.combat_step():
                host_loop._pump_held_weapons([], DT)
        assert _h.combat_epoch() == before
    finally:
        w.close()


def test_launch_modules_are_released_with_their_rows(monkeypatch):
    """A row's launch module (an ammo type's, a cannon's) is an owned
    reference in the bindings: dropped when the row is unregistered, not
    kept until the mirror is cleared."""
    nc.configure(ON)
    ship = App.ShipClass_Create("Holder")
    _load_hardpoint(ship, "vorcha")
    cannon = ship.GetPulseWeaponSystem().GetWeapon(0)
    torps = ship.GetTorpedoSystem()
    ammo = torps.GetCurrentAmmoType()
    script = ammo.GetTorpedoScript()
    nc.learn_tube_launch(script, ws._resolve_projectile_module(script))
    for row, mod in ((ammo, ws._projectile_modules[script]),
                     (cannon, sys.modules[ws.pulse_module_script(cannon)])):
        held = sys.getrefcount(mod)
        h = row.__dict__["_nslot"]
        nc._drop(row)
        assert sys.getrefcount(mod) == held - 1, row
        # A handle no longer live takes no module: nothing would free it.
        _h.combat_set_launch_module(h, mod)
        assert sys.getrefcount(mod) == held - 1, row


def test_native_dumb_fire_matches_python(monkeypatch):
    """A torpedo system held with no target: every walk's try_fire fails
    its timer gate and the tubes dumb-fire (Weapon.FireDumb) -- decided
    natively now: the launch with no target, no FIRE_DUMB record."""
    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            torps.StartFiring(None)
        elif t % 31 == 0:
            for tube in _weapons(torps):
                tube.SetNumReady(1)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 64)
    assert len(nl.spawned) >= 2
    assert all(s[9] is None for s in nl.spawned)
    # StartFiring's own forced walk fires Fire(None) (a tube launch with no
    # target); every later one is the dumb fire past the timer gate.
    logged = counts["k1_logged"]
    assert logged["dumb_launch"] >= 1, counts
    assert logged["dumb_launch"] + logged["tube_launch"] == len(nl.spawned)
    assert logged["dumb_refused"] > 0, counts


def test_tube_launch_cache_follows_a_mission_swap_reset(monkeypatch):
    """P6 extended, with today's invalidation: the mission-swap reset
    (_reset_projectile_module_cache) with the torpedo module now answering
    a different launch speed, and a launch made before any GameLoop.tick.
    The cached launch is forgotten and re-read at the next K1 entry (Task
    5): no launch is handed back, every one is native, those after the
    reset at the new speed -- each torpedo as the reference's."""
    from engine.appc import projectiles
    state = {}

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            torps.StartFiring(w.ships["Ahead"], TGPoint3(0.25, -0.5, 0.125))
        elif t == 31:
            mod = importlib.import_module(
                torps.GetCurrentAmmoType().GetTorpedoScript())
            state["slow"] = slow = float(mod.GetLaunchSpeed()) * 0.5
            w.mp.setattr(mod, "GetLaunchSpeed", lambda: slow)
            ws._reset_projectile_module_cache()     # the mission swap's
            for tube in _weapons(torps):
                tube.SetNumReady(1)
            torps.StartFiring(w.ships["Ahead"],     # before any tick
                              TGPoint3(0.25, -0.5, 0.125))
        elif t == 62:
            for tube in _weapons(torps):
                tube.SetNumReady(1)

    try:
        (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 95)
    finally:
        ws._reset_projectile_module_cache()
    assert not any(counts["k1_launch_reasons"].values()), counts
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned) >= 3
    # The launches after the reset left at the new speed.
    ship_v = nw.ships["Galaxy"].GetVelocityTG()
    after = [t for t in nl.torps
             if nl.events[[e[1] for e in nl.events].index(nl.label(t))][3]
             > 31]
    assert len(after) >= 2, nl.events
    for t in after:
        v = t._velocity
        d = TGPoint3(v.x - ship_v.x, v.y - ship_v.y, v.z - ship_v.z)
        assert abs(d.Length() - state["slow"]) < 1e-9, (d.Length(), state)


def test_swap_reloaded_module_launches_natively(tmp_path, monkeypatch):
    """Task 5 after a mission swap that reloads the SDK tree: the torpedo
    script is a new module object answering other params (a test-local
    fixture). The reset's re-read at the next K1 entry caches it, so every
    launch after it is native and launches the new module -- its speed,
    its Create -- each torpedo as the reference's."""
    fresh = _fixture_module(tmp_path, monkeypatch, "k1fx_reloaded_torp",
                            _PURE_TORP)

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            # Each arm resolves afresh: the module memo outlives an arm.
            ws._reset_projectile_module_cache()
            torps.StartFiring(w.ships["Ahead"], TGPoint3(0.25, -0.5, 0.125))
        elif t == 31:
            w.mp.setitem(sys.modules,
                         torps.GetCurrentAmmoType().GetTorpedoScript(), fresh)
            ws._reset_projectile_module_cache()     # the mission swap's
            for tube in _weapons(torps):
                tube.SetNumReady(1)
            torps.StartFiring(w.ships["Ahead"],     # before any tick
                              TGPoint3(0.25, -0.5, 0.125))
        elif t == 62:
            for tube in _weapons(torps):
                tube.SetNumReady(1)

    try:
        (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 95)
    finally:
        ws._reset_projectile_module_cache()
    assert not any(counts["k1_launch_reasons"].values()), counts
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned) >= 3
    ship_v = nw.ships["Galaxy"].GetVelocityTG()
    fired = {e[1]: e[3] for e in nl.events if e[0] == "entered"}
    after = [t for t in nl.torps if fired[nl.label(t)] > 31]
    assert len(after) >= 2 and len(after) < len(nl.torps), fired
    for t in after:
        assert t._damage == 444.0, t._damage
        v = t._velocity
        d = TGPoint3(v.x - ship_v.x, v.y - ship_v.y, v.z - ship_v.z)
        assert abs(d.Length() - 21.0) < 1e-9, d.Length()


def test_a_type_that_does_not_resolve_keeps_its_fallbacks(monkeypatch):
    """Task 5 keeps the resolve's own fallbacks, and loading never raises:
    a script that does not import is cached as the stock photon Python's
    launch substitutes (every launch native, as the reference's); one whose
    photon fallback fails too is unresolved -- every launch handed back
    (launch_unresolved, never launch_uncached) and Python spawns nothing,
    as before."""
    for case in ("photon", "unresolved"):
        def script(w, t, case=case):
            torps = w.ships["Galaxy"].GetTorpedoSystem()
            if t == 0:
                ws._reset_projectile_module_cache()     # each arm resolves
                if case == "unresolved":
                    w.mp.setattr(ws, "_FALLBACK_PROJECTILE",
                                 "k1fx_no_such_fallback")
                torps.GetCurrentAmmoType().SetTorpedoScript(
                    "k1fx_no_such_torpedo")
            _tube_volley(w, t)

        try:
            (rw, rl, _), (nw, nl, counts) = _launch_arms(
                monkeypatch, script, 64)
        finally:
            ws._reset_projectile_module_cache()
        why = counts["k1_launch_reasons"]
        logged = counts["k1_logged"]["tube_launch"]
        assert why["launch_uncached"] == 0, (case, why)
        if case == "photon":
            assert not any(why.values()), why
            assert logged == len(nl.spawned) >= 2, counts
        else:
            assert why["launch_unresolved"] >= 2, why
            assert logged == 0 and nl.spawned == [], counts


# A GetLaunchSpeed that raises while RAISE[0] is set (test-local).
_RAISING_SPEED_TORP = _PURE_TORP.replace(
    "def GetLaunchSpeed():\n    return(21.0)\n",
    "RAISE = [1]\n\n"
    "def GetLaunchSpeed():\n"
    "    if RAISE[0]:\n"
    "        raise RuntimeError('k1fx: no launch speed yet')\n"
    "    return(21.0)\n")


def test_a_raising_launch_speed_at_load_stays_uncached(tmp_path, monkeypatch):
    """Task 5 review: the type's module raises from GetLaunchSpeed when
    the type is loaded (SetTorpedoScript). Loading succeeds, the type stays
    uncached (as tube_launch_params always left it), and its first launch
    is handed back (launch_uncached): Python's launch, as before, which
    learns it -- by then the getter answers -- so the rest are native,
    every torpedo as the reference's (which never read it at load)."""
    name = "k1fx_raising_speed"
    mod = _fixture_module(tmp_path, monkeypatch, name, _RAISING_SPEED_TORP)
    assert "RAISE" in vars(mod)         # the replace took
    states = []

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            ws._reset_projectile_module_cache()     # each arm resolves
            mod.RAISE[0] = 1
            ammo = torps.GetCurrentAmmoType()
            ammo.SetTorpedoScript(name)             # loads: must not raise
            if w.native:
                states.append(_h.combat_dump(
                    ammo.__dict__["_nslot"])["ammo_launch_state"])
            mod.RAISE[0] = 0
        _tube_volley(w, t)

    try:
        (rw, rl, _), (nw, nl, counts) = _launch_arms(monkeypatch, script, 95)
    finally:
        ws._reset_projectile_module_cache()
    assert states == [ws.LAUNCH_UNCACHED]
    assert counts["k1_launch_reasons"]["launch_uncached"] == 1, counts
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned) - 1 >= 2


def test_kernel_spawn_launches_the_fire_time_module(monkeypatch):
    """A kernel SPAWN carries the module resolved when the launch was
    decided (as Python's own does): a module cache changed between the walk
    and the boundary does not change what is launched."""
    class _Other:
        @staticmethod
        def Create(pTorp):
            pTorp.SetDamage(1.0)

    held = []

    def swap(w, t):
        # After the walk, before the boundary; put back by the next tick.
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        script = torps.GetCurrentAmmoType().GetTorpedoScript()
        if t < 39:
            held.append((script, ws._projectile_modules.get(script)))
            ws._projectile_modules[script] = _Other

    def script(w, t):
        while held:
            name, mod = held.pop()
            ws._projectile_modules[name] = mod
        _tube_volley(w, t)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 40, inside=swap)
    assert counts["k1_logged"]["tube_launch"] >= 2, counts
    assert all(x[3] != ("float", 1.0) for x in nl.spawned), nl.spawned


def test_posed_target_offset_hand_back_has_its_own_reason(monkeypatch):
    """A posed target and an offset no Manual Aim slot holds (an AI's held
    offset): the kernel cannot bake it, so the launch is handed back as
    launch_posed_offset (not launch_other), and equals the reference."""
    def script(w, t):
        if t == 0:
            _pose_ahead(w)
        _tube_volley(w, t)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 40, ships=_POSED_LAUNCH_SHIPS)
    why = counts["k1_launch_reasons"]
    assert why["launch_posed_offset"] >= 1, why
    assert why["launch_other"] == 0, why


_TWO_LAUNCHERS = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
                  ("Galaxy2", "galaxy", (20.0, 0.0, 0.0), 0.0),
                  ("Ahead", "vorcha", (10.0, 240.0, 5.0), math.pi))


def test_patched_launch_function_seen_by_the_next_walk(monkeypatch):
    """M3: a launch function patched mid-session -- here by the Python of
    the session's first launch, a FIRE record (uncached: its launch
    forgotten) -- is seen at the
    next record's re-validation, not only at the next K1 entry: the second
    ship's launch in the same pump is handed back (launch_patched)."""
    from engine.appc import subsystems
    real = subsystems.subsystem_world_position
    learn = nc.learn_tube_launch

    def spy(*a, **kw):
        return real(*a, **kw)

    def script(w, t):
        if t == 0:
            _forget_launches(w)

            def learn_and_patch(*a, **kw):
                w.mp.setattr(subsystems, "subsystem_world_position", spy)
                return learn(*a, **kw)
            w.mp.setattr(nc, "learn_tube_launch", learn_and_patch)
            for name in ("Galaxy", "Galaxy2"):
                torps = w.ships[name].GetTorpedoSystem()
                for tube in _weapons(torps):
                    tube.SetNumReady(0)
                torps.StartFiring(w.ships["Ahead"])
        elif t == 1:
            for name in ("Galaxy", "Galaxy2"):
                for tube in _weapons(w.ships[name].GetTorpedoSystem()):
                    tube.SetNumReady(1)

    # Native only: under a patch Python's launches spawn at once through it
    # (the spy is the point), so a tick with two launches orders its events
    # unlike the reference's; parity under a patch is not what this pins.
    with monkeypatch.context() as mp:
        w = World(mp, True, _TWO_LAUNCHERS, "k1_patch_mid", player="Galaxy")
        try:
            for t in range(40):
                with host_loop._combat_effect_scope():
                    w.tick(before=lambda w, t=t: script(w, t))
            counts = nc.counts()
        finally:
            w.close()
    why = counts["k1_launch_reasons"]
    assert why["launch_uncached"] == 1, why
    assert why["launch_patched"] >= 1, why
    assert counts["k1_logged"]["tube_launch"] == 0, counts
    names = nc._k1_launch_funcs_names()
    for name in ("_launch_reads", "_defer_spawn", "spawn_launch",
                 "subsystem_world_position", "source_set"):
        assert name in names, name


_POSED_LAUNCH_SHIPS = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
                       ("Ahead", "birdofprey", (10.0, 240.0, 5.0), math.pi,
                        "ships.BirdOfPrey"))


def _pose_ahead(w):
    articulation.force_pose(w.ships["Ahead"], "cruise")


def test_warp_engine_slot_write_pushes_arriving(monkeypatch):
    """Every writer of what `arriving` reads pushes it: a warp engine whose
    slide is under way, given to a ship (SetWarpEngineSubsystem), makes its
    row's `arriving` 1 (FireDumb's hold), and the audit agrees."""
    from engine.appc.subsystems import WarpEngineSubsystem
    nc.configure(ON)
    ship = App.ShipClass_Create("Arriver")
    h = ship.__dict__["_nslot"]
    assert _h.combat_dump(h)["arriving"] == 0
    warp = WarpEngineSubsystem("Warp")
    warp._dewarp_drive = object()       # a slide under way
    ship.SetWarpEngineSubsystem(warp)
    assert _h.combat_dump(h)["arriving"] == 1
    warp._end_dewarp_drive()
    assert _h.combat_dump(h)["arriving"] == 0
    nc.audit_mirror()
    assert [f for f in nc.audit_failures() if f[1] == "arriving"] == []


def test_python_dumb_fire_spawn_is_tagged_dumb(monkeypatch):
    """Python's FireDumb (a dumb fire the kernel hands back) defers its
    SPAWN tagged as the dumb kind, like the kernel's."""
    from engine.appc import effect_queue as eq
    kinds = []
    post = eq.post

    def spy(kind, *ops):
        if kind == eq.SPAWN:
            kinds.append(ops[1])
        return post(kind, *ops)
    monkeypatch.setattr(eq, "post", spy)
    with monkeypatch.context() as mp:
        w = World(mp, True, _LAUNCH_SHIPS, "k1_dumb_tag", player="Galaxy")
        try:
            tube = w.ships["Galaxy"].GetTorpedoSystem().GetWeapon(0)
            with eq.scope():
                tube.FireDumb(0, 1)
            assert kinds == [ws.SPAWN_DUMB], kinds
        finally:
            w.close()
