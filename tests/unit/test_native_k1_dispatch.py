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
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import passive_weapons  # noqa: E402
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

    `ships` is ((name, hardpoint, (x, y, z), yaw), ...). Built the same way
    in both arms, so labels (ship name / subsystem name) line up."""

    def __init__(self, mp, native, ships, tag, player=None):
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


def test_ask_answers_match_python(monkeypatch):
    """A handler on the first ET_WEAPON_FIRED of a multi-fire walk drops the
    target's mirror row: the rest of that walk cannot read it, so the kernel
    ASKs Python to run each remaining bank's whole Fire, and the walk goes on
    with the Python answers. Later walks see an unnameable list entry and
    run whole in Python."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (0.0, 240.0, 30.0), math.pi))

    def drop_target(w):
        def hook(evt):
            if evt.GetEventType() != App.ET_WEAPON_FIRED or not w.hooks:
                return
            w.hooks.clear()
            nc._drop(w.ships["Vorcha"])     # both arms: harmless when off
        return hook

    def script(w, t):
        if t == 3:
            phasers = w.ships["Galaxy"].GetPhaserSystem()
            phasers.SetSingleFire(0)
            w.hooks.append(drop_target(w))
            # With an aim offset: each asked Fire stamps the walk's object.
            phasers.StartFiring(w.ships["Vorcha"], TGPoint3(1.0, -2.0, 0.5))
            w.record()      # before the pump re-stamps the lit banks

    ref, _nat, counts = _both(monkeypatch, ships, script, 60)
    assert sum(1 for e in ref.events if e[0] == "fired") >= 2, ref.events
    assert counts["k1_asks"] > 0, counts


def test_exception_in_an_effect_abandons_the_session(monkeypatch):
    """An effect raises (the beam's fire sound, here): run_k1 abandons the
    kernel session and re-raises, and the mirror still equals the Python."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (0.0, 240.0, 0.0), math.pi))

    class Boom(Exception):
        pass

    def boom(self):
        raise Boom()

    w = World(monkeypatch, True, ships, "k1_boom")
    try:
        for _ in range(3):
            w.tick()        # the banks charge
        monkeypatch.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", boom)
        before = nc.counts()["k1_records"]
        with pytest.raises(Boom):
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(
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
    module that is not loaded any more abandons the session (raise), never
    reaching _spawn_projectile with None."""
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
        monkeypatch.delitem(sys.modules, script)
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
