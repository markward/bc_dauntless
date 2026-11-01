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


def test_handler_drops_the_failing_tube_row_mid_walk(monkeypatch):
    """A handler on ET_WEAPON_FIRE_FAILED makes the failing tube's row
    unencodable (its mirror row dropped) in the middle of the walk. Python
    carries on with the tube object; so must K1: the tube's `_target = None`
    goes to Python as a logged write (no row to write), its retry Fire is
    ASKed, and the dumb-fire question too. ON identical to OFF; later walks
    see a stale child and run whole in Python."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Behind", "vorcha", (-12.0, -230.0, 4.0), 0.0))
    dropped = {}

    def drop_failing_tube(w):
        def hook(evt):
            if evt.GetEventType() != App.ET_WEAPON_FIRE_FAILED or not w.hooks:
                return
            w.hooks.clear()
            tube = evt.GetDestination()
            dropped[w.native] = w.label(tube)
            nc._drop(tube)          # both arms: harmless when off
        return hook

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 2:
            w.hooks.append(drop_failing_tube(w))
            torps.StartFiring(w.ships["Behind"])

    ref, _nat, counts = _both(monkeypatch, ships, script, 60)
    assert dropped[False] and dropped[True] == dropped[False]
    assert "fire_failed" in _kinds(ref)
    assert counts["k1_asks"] > 0, counts


def test_handler_drops_the_dumb_tube_row_mid_walk(monkeypatch):
    """The dumb-fire branch with the tube's row gone: StopFiring on an
    empty tube (BANK_STOP) runs a handler-free effect, so the row is dropped
    from StopFiring itself; the walk's `GetNumTargets() == 0 and
    weapon.IsDumbFire()` must still ask Python, and FireDumb follows."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),)
    stops = {}

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 2:
            tube = torps.GetWeapon(0)
            tube.SetNumReady(0)             # CanFire refuses: BANK_STOP
            real = ws.TorpedoTube.StopFiring
            log = stops[w.native] = []

            def stop_and_drop(self, _real=real):
                if self is tube and not log:
                    log.append(w.label(self))
                    nc._drop(self)  # both arms: harmless when off
                return _real(self)
            monkeypatch.setattr(ws.TorpedoTube, "StopFiring", stop_and_drop)
            torps.StartFiring(None)
            monkeypatch.undo()

    ref, _nat, counts = _both(monkeypatch, ships, script, 30)
    assert stops[False] and stops[True] == stops[False]
    assert counts["k1_asks"] > 0, counts


@pytest.mark.parametrize("case", ("tube_failed", "phaser_fired"))
def test_walked_system_row_dropped_mid_walk_raises(monkeypatch, case):
    """The protocol invariant (k1_fire_control.h): a handler that drops the
    WALKED SYSTEM's row mid-walk cannot be followed (Python cannot resume
    update_weapons mid-loop). Native raises a RuntimeError naming the
    invariant, after abandoning the session; the mirror still equals the
    Python. Two places the kernel next reads the system: the retry after a
    tube's FIRE_FAILED, and the bookkeeping after a phaser's FIRE."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Behind", "vorcha", (-12.0, -230.0, 4.0), 0.0),
             ("Ahead", "vorcha", (0.0, 240.0, 0.0), math.pi))
    w = World(monkeypatch, True, ships, "k1_sys_drop")
    try:
        for _ in range(3):
            w.tick()        # the banks charge
        galaxy = w.ships["Galaxy"]
        if case == "tube_failed":
            system, event = galaxy.GetTorpedoSystem(), App.ET_WEAPON_FIRE_FAILED
            target = w.ships["Behind"]
        else:
            system, event = galaxy.GetPhaserSystem(), App.ET_WEAPON_FIRED
            target = w.ships["Ahead"]

        def hook(evt):
            if evt.GetEventType() == event and w.hooks:
                w.hooks.clear()
                nc._drop(system)
        w.hooks.append(hook)
        with pytest.raises(RuntimeError, match="walked system .* dropped"):
            system.StartFiring(target)
        assert not w.hooks
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
    real_spawn = ws._spawn_projectile

    def spawn(emitter, mod, *, drf_override=0.0, world_dir=None):
        bolts[nc.enabled()].append((
            now[0], emitter.GetName(),
            None if world_dir is None else tuple(
                float(c).hex() for c in (world_dir.x, world_dir.y,
                                         world_dir.z))))
        return real_spawn(emitter, mod, drf_override=drf_override,
                          world_dir=world_dir)

    def script(w, t):
        galaxy = w.ships["Galaxy"]
        cannons = w.ships["Vorcha"].GetPulseWeaponSystem()
        galaxy.SetVelocity(TGPoint3(2.0, -1.0, 0.5))
        p = galaxy.GetTranslate()
        galaxy.SetTranslateXYZ(p.x + 2.0 * DT, p.y - 1.0 * DT, p.z + 0.5 * DT)
        now[0] = t
        if t == 0:
            bolts[w.native] = []
            monkeypatch.setattr(ws, "_spawn_projectile", spawn)
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
    log = []
    _spy_records(monkeypatch, log)
    _ref, _nat, counts = _both(monkeypatch, _DUEL, _volleys, 240)
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
