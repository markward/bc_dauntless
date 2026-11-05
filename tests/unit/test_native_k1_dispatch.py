"""K1 dispatch: the held-weapons pump and StartFiring's immediate update run
through the native fire-control kernel, fire control's one copy of its rules
(phase 1b, Task 5; fire control native only, M3:
docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md).

Each scenario runs on fresh real ships, natively, and is compared after every
tick -- each system's bookkeeping and each bank's (IsFiring, _target is None,
_fire_timer.hex(), _depleted, charge.hex(), GetNumReady(), the offset and
its walk-object identity) plus the weapon event log (ET_WEAPON_FIRED,
ET_TORPEDO_FIRED, ET_WEAPON_FIRE_FAILED (= ET_CANT_FIRE),
ET_TORPEDO_AMMO_CONSUMED: type, source, destination, order, tick) -- with
RECORDED EXPECTATIONS: the same scenario's run through fire control's Python
copy, recorded at 9c3db5ec6 before that copy was deleted (Task 6, spec §4.7;
tests/fixtures/k1_dispatch/<module>__<test>.<platform>.json.gz, one file per
test, one entry per arm-run call in call order). A platform with no
recording skips, naming the missing file (as the goldens, R9). The native
run must also show that K1 actually ran (its record count), that nothing
failed to fire for want of the mirror (k1_no_fire all zero), and its mirror
must still equal the Python at the end (audit_mirror).
"""
import gzip
import importlib
import json
import math
import os
import sys
from pathlib import Path

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
    recording_setup()
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    recording_teardown()


# ── Recorded expectations (fire control's Python copy, at 9c3db5ec6) ────────
# Each comparison names its call `kind` and hands over the native run's
# value (_expect, recorded_side); the recording's next entry of that kind is
# what it must equal. RE-RECORDING (no Python copy is left to record from):
# UPDATE_K1_DISPATCH=1 takes the native run as the expectation -- every
# comparison passes, and at teardown the test's file is written and the
# test skips, naming it (as UPDATE_COMBAT_GOLDEN does for the goldens). Same
# rule as the goldens: a re-record goes only in a commit naming the
# behaviour change it records.

RECORDINGS = Path(__file__).resolve().parents[1] / "fixtures" / "k1_dispatch"
UPDATE_ENV = "UPDATE_K1_DISPATCH"
_CALLS = {}     # call kind -> the next call index, this test
_LOADED = {}    # recording file -> its calls (each gz read once)
_PENDING = []   # UPDATE_K1_DISPATCH: this test's calls, in call order


def _updating():
    return os.environ.get(UPDATE_ENV) == "1"


def recording_setup():
    """Per test (the dispatch and SDK-route modules' autouse fixtures)."""
    _CALLS.clear()
    del _PENDING[:]


def recording_teardown():
    """UPDATE_K1_DISPATCH: write the test's recording, then skip."""
    if not (_updating() and _PENDING):
        return
    out = write_recording(_recording_key(), list(_PENDING))
    del _PENDING[:]
    pytest.skip("k1 dispatch expectation re-recorded: %s" % out)


def write_recording(key, calls, root=None):
    """Write `calls` as test `key`'s recording for this platform: gzip
    (mtime 0) of {"test": key, "calls": calls}. Returns the path."""
    out = (RECORDINGS if root is None else root) / (
        "%s.%s.json.gz" % (key, sys.platform))
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"test": key, "calls": calls},
                     separators=(",", ":")).encode()
    with open(out, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
            gz.write(raw)
    _LOADED.pop(out, None)
    return out


def _norm(v):
    """`v` as the recording holds it (JSON: tuples are lists)."""
    return json.loads(json.dumps(v))


def _recording_key():
    path, rest = os.environ["PYTEST_CURRENT_TEST"].split("::", 1)
    return Path(path).stem + "__" + rest.rsplit(" (", 1)[0]


def _recording():
    key = _recording_key()
    f = RECORDINGS / ("%s.%s.json.gz" % (key, sys.platform))
    calls = _LOADED.get(f)
    if calls is None:
        if not f.exists():
            pytest.skip("no recorded expectation for %s on %s: %s is "
                        "missing (recordings are per platform; %s=1 "
                        "records one)" % (key, sys.platform, f.name,
                                          UPDATE_ENV))
        with gzip.open(f, "rt") as fh:
            calls = _LOADED[f] = json.load(fh)["calls"]
    return calls


def _next(kind, calls, what):
    i = _CALLS.get(kind, 0)
    _CALLS[kind] = i + 1
    assert i < len(calls), "no recorded %s #%d" % (what, i)
    return calls[i]


def _expect(kind, got):
    """The next recorded call of `kind` in this test (in call order): a
    dict the native run's `got` (a dict of the same keys) is compared
    with. Under UPDATE_K1_DISPATCH=1, `got` itself, recorded."""
    if _updating():
        entry = dict(_norm(got), kind=kind)
        _PENDING.append(entry)
        return entry
    return _next(kind, [c for c in _recording() if c["kind"] == kind],
                 "%s call" % kind)


def recorded_side(name, got):
    """A value the test compares with the recording's "side" entries (by
    name, in order). Under UPDATE_K1_DISPATCH=1, `got`, recorded."""
    if _updating():
        _PENDING.append({"kind": "side", "name": name, "value": _norm(got)})
        return _norm(got)
    return _next("side:" + name,
                 [c for c in _recording()
                  if c["kind"] == "side" and c["name"] == name],
                 "side value %r" % name)["value"]


def _same_log(want, got, what="tick"):
    assert len(got) == len(want), (len(got), len(want))
    for i, (a, b) in enumerate(zip(want, got), start=1):
        assert len(a) == len(b), (what, i)
        for x, y in zip(a, b):
            assert x == y, "%s %d differs:\n python %r\n native %r" % (
                what, i, x, y)


def _no_fire_free(counts):
    """Nothing failed to fire for want of the mirror (R2, R3)."""
    assert not any(counts["k1_no_fire"].values()), counts["k1_no_fire"]


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
    same way as the recordings' Python runs, so labels (ship name /
    subsystem name) line up. A script (e.g. "ships.BirdOfPrey") lets
    articulation resolve the ship's hardpoint leaf, so a posed ship's part
    slots can be resolved. `native` must be True: fire control has no other
    copy (M3); the argument stays for the call sites' shape."""

    def __init__(self, mp, native, ships, tag, player=None):
        assert native, "fire control is native only"
        self.mp = mp        # the arm's patches (undone when the arm ends)
        nc.reset()
        nc.configure(ON)
        assert nc.enabled()
        self.native = True
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
    """Run `script(world, tick)` before each of `ticks` ticks natively and
    compare with the recorded Python run. Returns (world, world, counts):
    the native world stands for the reference too, being equal to it."""
    with monkeypatch.context() as mp:
        w = World(mp, True, ships, "k1_1", player=player)
        try:
            for t in range(ticks):
                w.tick(before=lambda w, t=t: script(w, t))
            counts = nc.counts()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
            assert _h.combat_k1_depth() == 0
        finally:
            w.close()
    assert len(w.log) >= ticks
    want = _expect("both", {"log": w.log, "events": w.events})
    _same_log(want["log"], _norm(w.log))
    assert _norm(w.events) == want["events"]
    assert counts["k1_records"] > 0, counts
    _no_fire_free(counts)
    return w, w, counts


def _kinds(world):
    return {e[0] for e in world.events}


def test_update_mode_records_the_native_run(monkeypatch, tmp_path):
    """UPDATE_K1_DISPATCH=1: each comparison takes the native value as the
    expectation and records it; teardown writes the test's file and skips,
    naming it; read back, each gz is opened once and its calls come back by
    kind in order. (Writes only under tmp_path.)"""
    monkeypatch.setattr(sys.modules[__name__], "RECORDINGS", tmp_path)
    monkeypatch.setenv(UPDATE_ENV, "1")
    try:
        assert _expect("both", {"log": [(1, 2)], "events": []}) == {
            "log": [[1, 2]], "events": [], "kind": "both"}
        assert recorded_side("seen", (3,)) == [3]
        assert _expect("both", {"log": [], "events": [4]})["events"] == [4]
        with pytest.raises(pytest.skip.Exception) as skip:
            recording_teardown()
    finally:
        del _PENDING[:]
    key = _recording_key()
    out = tmp_path / ("%s.%s.json.gz" % (key, sys.platform))
    assert str(out) in str(skip.value)
    monkeypatch.delenv(UPDATE_ENV)
    opened = []
    real_open = gzip.open
    monkeypatch.setattr(gzip, "open",
                        lambda *a, **kw: opened.append(a[0]) or
                        real_open(*a, **kw))
    recording_setup()
    assert _expect("both", {})["log"] == [[1, 2]]
    assert recorded_side("seen", None) == [3]
    assert _expect("both", {})["events"] == [4]
    assert opened == [out], opened
    recording_setup()                   # the next test: its own call index
    assert _expect("both", {})["log"] == [[1, 2]]
    assert opened == [out], opened      # and no second read


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
    _no_fire_free(counts)


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
    _no_fire_free(counts)


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
    _no_fire_free(counts)


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
    _no_fire_free(counts)


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
    _no_fire_free(counts)


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

def test_unimportable_pulse_module_does_not_fire(monkeypatch):
    """A module that no longer imports is re-read at the K1 entry (fire
    control native only, M8.3: _refresh_stale_launches) as unresolved, so
    the cannon does not fire -- a counted no-fire (pulse_module, logged
    once), nothing raised, no bolt. (One merely unloaded from sys.modules
    is imported again: test_unloaded_pulse_module_reimports_like_python.)"""
    ships = (("Vorcha", "vorcha", (0.0, 0.0, 0.0), 0.0),
             ("Galaxy", "galaxy", (40.0, 220.0, 12.0), math.pi))
    w = World(monkeypatch, True, ships, "k1_mod_on")
    try:
        for _ in range(3):
            w.tick()
        vorcha = w.ships["Vorcha"]
        script = ws.pulse_module_script(
            vorcha.GetPulseWeaponSystem().GetWeapon(0))
        # None in sys.modules: import_module raises ModuleNotFoundError.
        monkeypatch.setitem(sys.modules, script, None)
        _h.combat_k1_reset_counts()
        vorcha.GetPulseWeaponSystem().StartFiring(w.ships["Galaxy"])
        cannon = vorcha.GetPulseWeaponSystem().GetWeapon(0)
        assert _h.combat_dump(cannon.__dict__["_nslot"])["module_ok"] == 0
        counts = nc.counts()
        assert counts["k1_logged"]["pulse_launch"] == 0
        assert counts["k1_no_fire"]["pulse_module"] == 1, counts["k1_no_fire"]
        assert _h.combat_k1_depth() == 0
    finally:
        w.close()


def test_apply_writes_store_quietly(monkeypatch):
    """A logged write of a plain NativeField (`_is_on`) and of a
    NativeWakeField (a tractor beam's `_firing`, which wakes the sleeping
    weapon) land on the object without pushing either value (the kernel
    already holds it)."""
    from engine.appc import passive_state
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),)
    w = World(monkeypatch, True, ships, "k1_quiet")
    try:
        galaxy = w.ships["Galaxy"]
        phasers = galaxy.GetPhaserSystem()
        h = phasers.__dict__["_nslot"]
        before = _h.combat_dump(h)["_is_on"]
        nc.apply_writes([(h, "_is_on", 0 if before else 1)])
        assert bool(phasers.__dict__["_is_on"]) is (not before)
        assert _h.combat_dump(h)["_is_on"] == before          # not pushed

        tractors = galaxy.GetTractorBeamSystem()
        beam = tractors.GetWeapon(0)
        bh = beam.__dict__["_nslot"]
        assert not beam._firing
        beam.__dict__["_passive_asleep"] = True
        nc.apply_writes([(bh, "_firing", True)])
        assert beam.__dict__["_firing"] is True
        assert not passive_state.is_asleep(beam)              # woken
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
    _no_fire_free(counts)


def _phaser_duel(w, t):
    if t == 0:
        w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])


_DUEL = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
         ("Vorcha", "vorcha", (0.0, 240.0, 0.0), math.pi))


def test_unloaded_pulse_module_reimports_like_python(monkeypatch):
    """The cannons' projectile module leaves sys.modules mid-fight (an SDK
    reload): Python's decide simply imported it again, and K1 re-reads it
    at its next entry (M8.3) -- equal to the recorded Python, bolts still
    launching."""
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
    assert _norm(seen[True]) == recorded_side("seen", seen[True])
    leaves = slice(len(ref.systems), None)
    cannons = [i for i, row in enumerate(ref.log[0][leaves])
               if row[0].startswith("Vorcha/") and row[6] is not None]
    after = {ref.log[t][leaves][i][6] for t in range(20, len(ref.log))
             for i in cannons}
    assert len(after) > 1, "no bolt after the first unload"
    _no_fire_free(counts)


def test_pulse_params_refresh_across_a_mission_swap_reset(monkeypatch):
    """The mission-swap reset (_reset_projectile_module_cache) with native
    on, and the projectile module now answering a different launch speed.
    Python's decide read the module live; K1's lead solve uses the params
    cached at registration (ruling P6), so the stale ones must be re-read
    before the next K1 decision -- even a StartFiring with no GameLoop.tick
    between the reset and it (one made during the swap). Every bolt's launch
    direction, by .hex(), equal to the recorded Python."""
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
    assert _norm(bolts[True]) == recorded_side("bolts", bolts[True])
    assert sum(1 for b in bolts[True] if b[0] >= swap_at) > 2, bolts[True]
    _no_fire_free(counts)


def test_reset_clears_the_per_class_caches(monkeypatch):
    """nc.reset() forgets every per-class answer (the weapon kind), so a
    class re-based between two runs is judged afresh."""
    assert nc._weapon_kind_of_class(ws.PhaserBank) == 5
    assert ws.PhaserBank in nc._kind_by_type
    nc.reset()
    assert ws.PhaserBank not in nc._kind_by_type


def test_reset_lets_go_of_a_class_the_field_caches_saw():
    """nc.reset() drops the class-keyed field caches (`_class_fields`,
    `_class_hidden`, `_quiet_setters`, `_repair_bay_by_type`,
    `_power_kind_by_type`) too, so a class a test defined
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
    # The subsystem stage's per-class answers (phase 6 A1) key it too.
    nc._is_repair_bay(Local)
    nc._power_kind(Local)
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


def test_posed_ship_fires_natively(monkeypatch):
    """A Bird of Prey in cruise fires its wing cannons and its torpedo tube,
    and a Galaxy fires phaser banks sitting on a forced part: per tick
    equal to the recorded Python, with no no-fire at all."""
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
    assert len(moved) == 1 and all(moved[0]), moved
    sources = {e[1].split("/")[0] for e in ref.events
               if e[0] in ("fired", "torpedo_fired")}
    assert {"BoP", "Galaxy"} <= sources, ref.events
    assert "torpedo_fired" in _kinds(ref)
    # The wing cannons fired (a bolt posts no weapon event: their charge).
    assert len(_charges(ref, "BoP/Port Cannon")) > 1
    assert len(_charges(ref, "BoP/Star Cannon")) > 1
    _no_fire_free(counts)
    assert counts["k1_posed"]["walks"] > 0, counts


def test_posed_target_tube_aim_native(monkeypatch):
    """Torpedo tubes and disruptor cannons aim at the wing mounts of a Bird
    of Prey in cruise (`_RESOLVE`: the first mount at the offset, posed
    natively): per tick equal to the recorded Python, with no no-fire."""
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
    assert moved == [(True, True)], moved
    assert {"fired", "torpedo_fired"} <= _kinds(ref), ref.events
    _no_fire_free(counts)
    assert counts["k1_posed"]["target_aims"] > 0, counts


# ── Manual Aim on a posed target (posed parts, Task 4b) ──────────────────────


def _wing_pick(bop, part="left wing", frac=(0.5, 0.5, 0.5)):
    """A Manual Aim pick on a Bird of Prey wing: a point inside that part's
    box the box rule gives to it, and no subsystem's mount (so _RESOLVE
    finds none and the pick is a plain body point)."""
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
    aim at it as a plain body point natively (fire control native only,
    M5), equal to the recorded Python. (No Fire ASK: K1 has no ASK left at
    all -- tests/unit/test_fire_control_python_retired.py.)"""
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
    assert moved == [True], moved
    assert "torpedo_fired" in _kinds(ref), ref.events
    assert len(_charges(ref, "Vorcha/")) > 1
    _no_fire_free(counts)
    assert counts["k1_posed"]["target_aims"] > 0, counts


# ── The walk offset (round trips, Task 1; fire control native only, M8.8) ───
#
# The kernel computes the walk's aim offset VALUE itself; Python makes the
# offset OBJECT (ruling P5) when a logged write naming the walk's offset is
# applied (native_combat._K1Walk.materialise): the system's own _held_offset,
# or a TGPoint3 of the Manual Aim pick the kernel recorded for the walk.

from engine.appc.ships import ShipClass  # noqa: E402
from engine.core import ids  # noqa: E402


def _volleys(w, t):
    """Phasers and torpedoes (with an aim offset) one way, cannons the
    other: every K1 system kind walks."""
    galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
    if t == 0:
        galaxy.GetPhaserSystem().StartFiring(vorcha)
        galaxy.GetTorpedoSystem().StartFiring(vorcha,
                                              TGPoint3(0.5, -1.0, 0.25))
        vorcha.GetPulseWeaponSystem().StartFiring(galaxy)


def _hexes3(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def test_offset_value_matches_live_held_offset(monkeypatch):
    """The kernel's walk offset (combat_k1_walk_offset, the predicate the
    walk uses) against the recorded answers of the deleted
    WeaponSystem._live_held_offset(), by .hex(): none, held, a non-TGPoint3
    held value (unset), Manual Aim (the manual offset wins), the use flag
    without a manual offset (held), and a firing ship that is not a
    ShipClass (held, whatever its row says)."""
    from engine.appc.objects import DamageableObject
    w = World(monkeypatch, True, _DUEL, "k1_offset")
    try:
        galaxy = w.ships["Galaxy"]
        torps = galaxy.GetTorpedoSystem()

        def check(system, want):
            nat = _h.combat_k1_walk_offset(system.__dict__["_nslot"])
            if want is None:
                assert nat is None, nat
            else:
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

        # A firing ship that is not a ShipClass: Python's probe found no
        # is_using_target_offset, so it read the held offset -- even when
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


def test_target_list_write_on_every_walk_is_a_new_list(monkeypatch):
    """Python's _prune_targets builds a NEW list on every update_weapons
    (AddTarget appends in place, so an older list object must never be the
    live one). The kernel keeps the `_target_list` write on every walk --
    a walk that hands nothing back too: its writes ride the next record or
    DONE. Each tick's list is a new object, as Python's was."""
    seen = {}

    def script(w, t):
        _volleys(w, t)
        galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
        for g in (galaxy.GetPhaserSystem(), galaxy.GetTorpedoSystem(),
                  vorcha.GetPulseWeaponSystem()):
            seen.setdefault((w.native, w.label(g)), []).append(
                g.__dict__["_target_list"])     # held: never reused

    _both(monkeypatch, _DUEL, script, 120)
    assert len(seen) == 3, sorted(seen)
    for (arm, label), lists in seen.items():
        assert len(lists) == 120
        assert all(a is not b for a, b in zip(lists, lists[1:])), \
            (arm, label)


# ── Round trips Task 2: beam sustain and idle stops as logged writes ─────────

def _spawn_hook(mp, act):
    """Run `act(launcher)` at every launch's SPAWN delivery (the session's
    end or the tick's boundary), before the spawn itself."""
    real = ws.spawn_launch

    def hooked(launcher, *a, **kw):
        act(launcher)
        return real(launcher, *a, **kw)
    mp.setattr(ws, "spawn_launch", hooked)


def test_beam_sustain_logged_not_recorded(monkeypatch):
    """A Fire on a beam that is ALREADY firing is three field writes in
    Python (_firing, _target, _target_offset): no sound, no event. K1 logs
    them (k1_logged.beam_sustain counts them), as its edge (combat fire
    events). Per tick equal to the recorded Python."""
    _ref, _nat, counts = _both(monkeypatch, _DUEL, _phaser_duel, 240)
    assert counts["k1_logged"]["beam_sustain"] > 0, counts
    assert counts["k1_logged"]["beam_edge"] > 0, counts
    _no_fire_free(counts)


def test_beam_edge_is_logged_writes_and_entries(monkeypatch):
    """The was-not-firing edge (combat fire events §4.3): its writes are
    logged and its fire sound and ET_WEAPON_FIRED are queue entries. The
    sound plays exactly as often as in the recorded Python (the events are
    compared by _both), once per logged edge and per FIRE_SOUND entry."""
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
    assert sounds[True] and _norm(sounds[True]) == recorded_side("sounds", sounds[True])
    assert counts["k1_logged"]["beam_edge"] == len(sounds[True]), counts
    assert counts["k1_entries"]["FIRE_SOUND"] == len(sounds[True]), counts
    assert counts["k1_entries"]["WEAPON_FIRED"] == len(sounds[True]), counts


def test_logged_target_offset_is_the_walk_object(monkeypatch):
    """Review Focus 2 (round trips): a lit beam's logged stamp, then a
    tube's launch of the same pump session, whose spawn (its SPAWN
    delivery at the session's end) reads each lit bank's _target_offset.
    It must be that walk's offset OBJECT (identity, not a copy, and not
    last tick's: fire control native only, M8.8): the held offset is a new
    object every tick. As the recorded Python, which read it mid-walk."""
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
            _spawn_hook(w.mp, spy)
        elif t % 40 == 20:
            # One bank drops out; it relights (an edge) while the others
            # sustain; the tubes are reloaded by hand to launch again.
            g.GetWeapon((t // 40) % g.GetNumWeapons()).StopFiring()
            for i in range(torps.GetNumWeapons()):
                torps.GetWeapon(i).SetNumReady(1)
        # A new offset object every tick (the same value).
        g._held_offset = TGPoint3(0.5, 1.0, -0.25)

    _ref, _nat, counts = _both(monkeypatch, _DUEL, script, 700)
    assert _norm(seen[True]) == recorded_side("seen", seen[True])
    # Some launch read a stamp made in the same tick's pump.
    assert any(o[2] for o in seen[True] if o[0] > 1), seen[True][:20]
    assert counts["k1_logged"]["beam_sustain"] > 0, counts


def _sleepy_duel(monkeypatch, ticks):
    """The Galaxy holds its phasers (all banks, not single fire) on the
    Vor'cha with bank 0 disabled (CanFire always refuses: idle stops).
    Bank 0 is put to sleep right before each pump, after the passive
    weapons walk, so only the pump's writes can wake it. Returns (per-tick
    asleep-after-pump, world log, counts)."""
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_sleepy_1")
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
    `self._firing = False` in StopFiring did. Per tick equal to the
    recorded Python."""
    nat_asleep, nat_log, counts = _sleepy_duel(monkeypatch, 120)
    want = _expect("sleepy", {"asleep": nat_asleep, "log": nat_log})
    assert False in want["asleep"] and True in want["asleep"], want["asleep"]
    assert nat_asleep == want["asleep"]
    _same_log(want["log"], _norm(nat_log))
    assert counts["k1_logged"]["idle_bank_stop"] > 0, counts
    _no_fire_free(counts)


class _Loop:
    def __init__(self, log, label):
        self.log, self.label = log, label

    def Stop(self):
        self.log.append(self.label)


def test_firing_bank_stop_is_logged_with_its_loop_stop(monkeypatch):
    """A FIRING bank's stop (combat fire events §4.3): its writes are
    logged and its loop sound's stop is a LOOP_STOP entry. The loop stops
    happen exactly as often, in the same order, as in the recorded
    Python."""
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
    assert stops[True] and _norm(stops[True]) == recorded_side("stops", stops[True])
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


#: The beam sustain's stamps K1 skips when they change nothing (phase 6
#: A3: `_firing` already True, `_target` the same object, `_target_offset`
#: the same held-offset object).
_NO_OP_SKIPPABLE = ("_firing", "_target", "_target_offset")


def _without_no_op_stamps(want, got, starts):
    """Check the native trace `got` is the recorded Python trace `want`
    with only no-op stamps left out, and return how many were: walking
    `want` in order, each entry is either the next native entry (equal) or
    a stamp of a _NO_OP_SKIPPABLE field whose value is the one the leaf
    already holds natively at that point (its pump-start value, `starts`,
    then each matched native write of that tick). By traced value, so an
    offset by .hex() and held-object identity; the goldens pin the offset
    OBJECT."""
    got = _norm(got)
    i = skipped = 0
    tick, cur = None, {}
    for r in want:
        n, _cls, label, name, val = r
        if n != tick:
            tick = n
            cur = {k: _norm(v) for k, v in starts.get(n, {}).items()}
        if i < len(got) and got[i] == r:
            cur[(label, name)] = val
            i += 1
            continue
        assert name in _NO_OP_SKIPPABLE and cur.get((label, name)) == val, \
            ("a Python write K1 did not make, and not a no-op", r,
             cur.get((label, name)), got[i] if i < len(got) else None)
        skipped += 1
    assert i == len(got), ("native writes Python did not make", got[i:i + 5])
    return skipped


def test_bank_write_order_matches_python(monkeypatch):
    """Per bank class (a disabled phaser bank among them), the pump's writes of _firing, _beam_on_countdown,
    _target and _target_offset on every leaf, in order, with their values
    (offsets by .hex() and walk-object identity): equal to the recorded
    Python, whose writes went through the class's __setattr__; K1's logged
    writes go through apply_writes' quiet setters, traced at the setter. Phasers, cannons and
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

    starts = {}     # tick -> {(label, field): traced value at pump start}

    def pump(ships, dt):
        w = state["w"]
        if w is not None and w.native:
            assert w.n not in starts, "one pump a tick"
            starts[w.n] = {
                (w.label(leaf), name): _trace_value(
                    w, name, leaf.__dict__.get(name))
                for leaf in w.leaves for name in _NO_OP_SKIPPABLE}
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
    want = recorded_side("traces", traces[True])
    skipped = _without_no_op_stamps(want, traces[True], starts)
    # Phase 6 A3: the sustain's stamps that change nothing are not written;
    # every one the recorded Python wrote and K1 did not is such a stamp.
    assert skipped > 0
    assert skipped == counts["k1_logged"]["beam_sustain_skips"], \
        (skipped, counts["k1_logged"])
    classes = {c for _n, c, _l, _f, _v in traces[True]}
    assert classes == {"PhaserBank", "PulseWeapon", "TorpedoTube"}, classes
    assert any(f == "_beam_on_countdown" for _n, _c, _l, f, _v
               in traces[True]), "no energy bank stop"
    assert counts["k1_logged"]["beam_sustain"] > 0, counts
    assert counts["k1_logged"]["idle_bank_stop"] > 0, counts


# ── Final review A2: a raise in materialise does not strand later writes ────

class _OffsetBoom(Exception):
    pass


def test_materialise_raise_applies_later_writes(monkeypatch):
    """The binding's write apply fetches the walk's offset object
    (materialise) mid-log, inside combat_k1_next (C-applied write logs).
    If that raises, the writes
    logged after it -- already in the mirror -- are still applied, in order,
    and the exception propagates out of run_k1 as it is: the mirror still
    equals the objects. (The log-level semantics, notes included, are pinned
    against apply_writes by tests/unit/test_native_write_apply.py.)"""
    with monkeypatch.context() as mp:
        w = World(mp, True, _DUEL, "k1_materialise_raise")
        phasers = w.ships["Galaxy"].GetPhaserSystem()
        real = _h.combat_k1_next
        real_mat = nc._K1Walk.materialise
        armed, inside, fired = [], [], []

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
                raise _OffsetBoom("offset")
            return real_mat(walk, n, h)
        mp.setattr(_h, "combat_k1_next", spy)
        mp.setattr(nc._K1Walk, "materialise", materialise)
        try:
            phasers.StartFiring(w.ships["Vorcha"])
            for _ in range(5):
                w.tick()
            phasers.SetForceUpdate(1)
            # A lit bank's stamp is logged only when its held-offset object
            # is new (phase 6 A3): re-assigning it (a push) stamps them all.
            phasers._held_offset = phasers.__dict__.get("_held_offset")
            armed.append(True)
            with pytest.raises(_OffsetBoom):
                w.tick()
            assert fired, "no logged marker reached materialise"
            assert phasers.__dict__["_force_update"] is False
            assert _h.combat_k1_depth() == 0
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
            # The raise left the banks without what K1 stamped, so no
            # offset source is trusted: the next tick stamps them again.
            seen = []
            mp.setattr(nc._K1Walk, "materialise",
                       lambda walk, n, h: (seen.append(h) if walk.walk != n
                                           else None,
                                           real_mat(walk, n, h))[1])
            w.tick()
            assert phasers.__dict__["_nslot"] in seen, seen
        finally:
            w.close()


# ── The effect queue (combat fire events, Task 2) ────────────────────────────
# Inside the tick's scope (host_loop._combat_effect_scope, native on) the
# sounds and events of K1's effects are queued and delivered, in order, when
# the scope closes (engine/appc/effect_queue.py).

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
    tube launches (ET_TORPEDO_FIRED, ET_WEAPON_FIRED). Native delivers them
    in the recorded Python's order -- the failure first -- and by the time
    StartFiring returns (the session's end), not at the next tick."""
    from engine.appc import effect_queue as eq
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Ahead", "vorcha", (10.0, 240.0, 5.0), math.pi),
             ("Behind", "vorcha", (-12.0, -230.0, 4.0), 0.0))
    logs, depth_at_post = {}, {}
    for native in (True,):
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
    assert _norm(logs[True]) == _expect(
        "events", {"events": logs[True]})["events"]
    assert _norm(logs[True]) == recorded_side("logs", logs[True])
    kinds = [e[0] for e in logs[True]]
    assert "fire_failed" in kinds and "torpedo_fired" in kinds, kinds
    assert kinds.index("fire_failed") < kinds.index("torpedo_fired"), kinds
    # Native: every event delivered at the session's end, none mid-walk.
    assert depth_at_post[True] and not any(depth_at_post[True])


def test_session_started_by_a_delivery_delivers_nested_in_order(
        monkeypatch):
    """Ruling F3 (c). Inside the tick's scope a handler on the first
    delivered ET_WEAPON_FIRED (a Galaxy phaser's edge) starts the Vor'cha's
    phasers: that K1 session runs inside the delivery, defers its own
    entries (the Vor'cha's edges) and delivers them at its end -- nested,
    before the rest of the tick's batch (the Galaxy's other edges) -- in
    the recorded Python's order."""
    from engine.appc import effect_queue as eq
    logs = {}
    for native in (True,):
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
    assert _norm(logs[True]) == _expect(
        "events", {"events": logs[True]})["events"]
    assert _norm(logs[True]) == recorded_side("logs", logs[True])
    srcs = [e[1].split("/")[0] for e in logs[True] if e[0] == "fired"]
    # Galaxy's first edge, the Vor'cha's (nested), then the Galaxy's rest.
    assert srcs[0] == "Galaxy" and srcs[1] == "Vorcha", srcs
    assert "Galaxy" in srcs[srcs.index("Vorcha"):], srcs


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
        return (
            self.label(t), _hx(t.GetTranslate()), _hx(t._velocity),
            _t(g("_damage")), _t(g("_damage_radius_factor")),
            _t(g("_ttl")), _t(g("_guidance_lifetime")),
            _t(g("_guidance_initial")), _t(g("_max_angular_accel")),
            self.label(g("_target_ship")), _hx(g("_target_offset")),
            self.label(t._source_ship),
            t.GetContainingSet() is self.w.set,
            g("_core_texture"), _t(g("_is_disruptor")),
        )


def _learn_launches(w):
    """Every ammo type's launch cached and pushed (as its loading already
    did: push_ammo_launch; kept so a scene's caches are as its recording
    run's)."""
    for s in w.order:
        torps = s.GetTorpedoSystem()
        if torps is None:
            continue
        for ammo in torps._ammo_by_slot.values():
            nc.push_ammo_launch(ammo)


def _launch_arms(monkeypatch, script, ticks, *, ships=_LAUNCH_SHIPS,
                 learn=True, inside=None, player="Galaxy", recorded=True,
                 until=None):
    """`ticks` scoped ticks natively (the tick's effect scope, as in play):
    `script(w, t)` before each tick, `inside(w, t)` inside the scope after
    it (what the rest of the step does after the weapons: in the recorded
    reference it ran after the launches too), compared with the recorded
    Python run -- every tick's state, every launch event in order, every
    spawned torpedo field by field. Returns (ref, nat) as (world,
    launches, counts), the native run standing for both; the reference's
    `pulse_state` and `fired`, which the native run's are compared with,
    as recorded (`ref.recorded`). `until`: compare only the ticks (and
    events) up to that tick -- the scene diverges from the recording after
    it by design (a no-fire, R2, R3) --, and every spawned torpedo.
    `recorded` False: no recording (a scene whose Python is no reference
    any more, the test's own assertions stand alone)."""
    with monkeypatch.context() as mp:
        w = World(mp, True, ships, "k1_launch_1", player=player)
        launches = _Launches(w)
        try:
            if learn:
                _learn_launches(w)
            for t in range(ticks):
                with host_loop._combat_effect_scope():
                    w.tick(before=lambda w, t=t: script(w, t))
                    if inside is not None:
                        inside(w, t)
            counts = nc.counts()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
            assert _h.combat_k1_depth() == 0
            assert _h.combat_effect_take() == []
        finally:
            w.close()
    want = _expect("launch", {
        "log": w.log, "events": launches.events,
        "spawned": launches.spawned,
        "pulse_state": getattr(w, "pulse_state", None),
        "fired": getattr(w, "fired", None)}) if recorded else None
    if want is None:
        w.recorded = None
        return [(w, launches, counts), (w, launches, counts)]
    if until is None:
        _same_log(want["log"], _norm(w.log))
        assert _norm(launches.events) == want["events"]
    else:
        _same_log(want["log"][:until], _norm(w.log[:until]))
        assert _norm([e for e in launches.events if e[3] <= until]) == [
            e for e in want["events"] if e[3] <= until]
    got = _norm(launches.spawned)
    for i, (a, b) in enumerate(zip(want["spawned"], got)):
        for j, (x, y) in enumerate(zip(a, b)):
            assert x == y, "torpedo %d field %d:\n python %r\n native %r" % (
                i, j, x, y)
    assert len(got) == len(want["spawned"])
    for name in ("pulse_state", "fired"):
        assert _norm(getattr(w, name, None)) == want[name], name
    w.recorded = want
    return [(w, launches, counts), (w, launches, counts)]


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
    exactly (recorded), the magazine ends empty, and the player's
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
    assert _norm(state[True]) == recorded_side("state", state[True])
    assert state[True][-1][0] == ("int", 0)
    assert len(nl.spawned) == 2 and counts["k1_logged"]["tube_launch"] == 2
    assert [e[0] for e in nl.events].count("ammo_consumed") == 2


def test_dead_or_dropped_target_keeps_the_fire_time_values(monkeypatch):
    """Review Focus 5. The target dies after the weapons (and, the next
    volley, its row is dropped: a value the mirror cannot hold) before the
    boundary: the torpedo is spawned anyway with the target it fired at,
    as the recorded reference -- which spawned it mid-walk, the target
    still alive -- did. From the drop on the Galaxy's torpedoes, whose
    target list names a row gone, do not fire (fire control native only,
    R3: counted, stale_row; the drop itself is counted, dropped), where
    the reference walked on: compared up to the drop's tick."""
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
        elif t == 31:
            nc._drop(w.ships["Ahead"])

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 40, inside=kill, until=32)
    assert [s[9] for s in nl.spawned] == ["Ahead", "Ahead"], nl.spawned
    assert counts["k1_logged"]["tube_launch"] == 2, counts
    assert counts["k1_no_fire"]["dropped"] == 1, counts["k1_no_fire"]
    assert counts["k1_no_fire"]["stale_row"] > 0, counts["k1_no_fire"]


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


def test_pulse_launch_with_an_unloaded_module_is_repushed(monkeypatch):
    """Review Focus 4 for cannons, since fire control native only (M8.3).
    The cannons' module gone from sys.modules -- an SDK reload: Python's
    decide imports it again, a module the kernel's cached one is not. The
    next K1 entry (StartFiring's session) re-reads it, so every launch is
    the kernel's, carrying the re-imported module -- no hand-back -- and
    equal to the reference."""
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
    assert not any(why.values()), why
    assert counts["k1_logged"]["pulse_launch"] == len(nl.spawned), counts


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
    nc.push_ammo_launch(ammo)
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
    launch substitutes (every launch native, as the recorded reference's);
    one whose photon fallback fails too is unresolved -- its launch does
    not fire (fire control native only, M6: a counted no-fire, launch, its
    why launch_unresolved, never launch_uncached; the tubes keep their
    rounds), where the reference's spawned nothing but spent the round."""
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
                monkeypatch, script, 64, recorded=case == "photon")
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
            assert counts["k1_no_fire"]["launch"] == \
                why["launch_unresolved"], counts["k1_no_fire"]
            assert logged == 0 and nl.spawned == [], counts
            tubes = _weapons(nw.ships["Galaxy"].GetTorpedoSystem())
            assert all(t.GetNumReady() == 1 for t in tubes)


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


def test_posed_target_offset_launches_natively(monkeypatch):
    """A posed target and an AI's held offset no mount claims: the launch
    carries the offset as it is (no bake, fire control native only, M5), so
    the kernel makes it -- no launch hand-back -- and equals the
    reference. (Was launch_posed_offset, a hand-back.)"""
    def script(w, t):
        if t == 0:
            _pose_ahead(w)
        _tube_volley(w, t)

    (rw, rl, _), (nw, nl, counts) = _launch_arms(
        monkeypatch, script, 40, ships=_POSED_LAUNCH_SHIPS)
    why = counts["k1_launch_reasons"]
    assert "launch_posed_offset" not in why, why
    assert set(why.values()) == {0}, why
    assert counts["k1_logged"]["tube_launch"] >= 1, counts
    assert nl.spawned, nl.spawned


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


