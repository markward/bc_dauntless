"""WeaponSystem.StartFiring's gates and writes run natively (phase 6 AI part
3, task 6): `_dauntless_host.start_firing(system, target, offset)` is the base
body. It must gate in the Python body's order with the same early returns
(a failing gate writes nothing), write through the same descriptors (their
mirror pushes happen), then start the K1 system session through
`native_combat.k1_system` looked up on the module. Overrides and patches
still win: the three subclass bodies keep their own gates and call the base;
a patched gate function, or a non-stock method on the object, is called."""
import importlib
import math
import sys

import pytest

_h = pytest.importorskip("_dauntless_host")

import App
from engine.appc import native_combat as nc
from engine.appc import passive_state, sensor_detection
from engine.appc import weapon_subsystems as ws
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.subsystems import CloakingSubsystem
from engine.core import ids
from tests.helpers.start_firing_oracle import start_firing_py

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _reset():
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


class _World:
    """A Galaxy and a Vorcha in one set (the Vorcha 230 GU ahead: in phaser
    range), the mirror live, the weapons' clock pinned."""

    def __init__(self, mp, vorcha_at=(0.0, 230.0, 0.0)):
        nc.reset()
        nc.configure(ON)
        mp.setattr(ws, "_game_time", lambda: 100.0)
        self.tag = "start_firing_%d" % id(self)
        self.set = App.SetClass_Create()
        App.g_kSetManager.AddSet(self.set, self.tag)
        self.galaxy = self._ship("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0)
        self.vorcha = self._ship("Vorcha", "vorcha", vorcha_at, math.pi)

    def _ship(self, name, hardpoint, at, yaw):
        ship = App.ShipClass_Create(name)
        _load_hardpoint(ship, hardpoint)
        ship.SetTranslateXYZ(*at)
        m = TGMatrix3()
        m.MakeZRotation(yaw)
        ship.SetMatrixRotation(m)
        self.set.AddObjectToSet(ship, name)
        return ship

    def close(self):
        App.g_kSetManager.DeleteSet(self.tag)


# The Python functions the native body calls back (the reference body calls
# the same ones): the gates themselves and what they call. Their call order
# is the gate order.
_LEAVES = frozenset((
    "_is_offline", "_cloak_blocks_fire", "_dewarp_blocks_fire",
    "_target_undetectable", "_can_engage", "GetParentShip", "IsDisabled",
    "IsDestroyed", "IsDying", "IsDead", "_out_of_action", "implements",
    "_climb_to_ship", "GetCloakingSubsystem", "IsTryingToCloak",
    "is_arriving", "can_detect", "_target_in_system_range",
    "_target_within_range_gu", "_same_set", "push_field", "k1_system",
    "_post_cant_fire", "k1_tractor_start",
))


def _leaf_calls(fn):
    seen = []

    def prof(frame, event, arg):
        if event == "call" and frame.f_code.co_name in _LEAVES:
            seen.append(frame.f_code.co_name)
    sys.setprofile(prof)
    try:
        fn()
    finally:
        sys.setprofile(None)
    return seen


def _writes(system):
    d = system.__dict__
    return (d.get("_fire_held"), d.get("_held_target"), d.get("_held_offset"),
            list(d.get("_target_list", ())), d.get("_force_update"))


def _label(w, v):
    if v is w.galaxy:
        return "Galaxy"
    if v is w.vorcha:
        return "Vorcha"
    if isinstance(v, list):
        return [_label(w, x) for x in v]
    if isinstance(v, tuple):
        return tuple(_label(w, x) for x in v)
    if isinstance(v, TGPoint3):
        return ("pt", v.x, v.y, v.z)
    return (type(v).__name__, v)


# ── Scenarios: each makes ONE gate fail (or none) ───────────────────────────

def _off(w, mp):
    w.galaxy.GetPhaserSystem().TurnOff()
    w.galaxy.GetTorpedoSystem().TurnOff()


def _disabled(w, mp):
    for c in w.galaxy.GetPhaserSystem()._children:
        c._condition = c._disabled_percentage * c._max_condition


def _destroyed(w, mp):
    w.galaxy.GetPhaserSystem().SetDestroyed(1)


def _radiation(w, mp):
    w.galaxy.GetPhaserSystem()._radiation_out = True


def _radiation_truthy_not_true(w, mp):
    w.galaxy.GetPhaserSystem()._radiation_out = 1     # `is True` only


def _parent_radiation(w, mp):
    holder = ws.ShipSubsystem("Holder")
    holder._radiation_out = True
    w.galaxy.GetPhaserSystem()._parent_subsystem = holder


def _dying(w, mp):
    w.galaxy.SetDying(1)


def _dead(w, mp):
    w.galaxy.SetDead(1)


def _cloaked(w, mp):
    cloak = CloakingSubsystem("Cloak")
    cloak._cloak_state = CloakingSubsystem.CLOAK_CLOAKED
    w.galaxy._cloaking_subsystem = cloak


def _decloaking(w, mp):
    cloak = CloakingSubsystem("Cloak")
    cloak._cloak_state = CloakingSubsystem.CLOAK_DECLOAKING
    w.galaxy._cloaking_subsystem = cloak


def _dewarping(w, mp):
    w.galaxy.GetWarpEngineSubsystem()._dewarp_drive = object()


def _undetectable(w, mp):
    mp.setattr(sensor_detection, "can_detect", lambda ship, target: False)


def _can_detect_raises(w, mp):
    def boom(ship, target):
        raise RuntimeError("sensor fault")
    mp.setattr(sensor_detection, "can_detect", boom)


def _out_of_range(w, mp):
    w.vorcha.SetTranslateXYZ(0.0, 1000.0, 0.0)


def _cloaked_and_undetectable(w, mp):
    _cloaked(w, mp)
    _undetectable(w, mp)


def _nothing(w, mp):
    pass


_SCENARIOS = {
    "off": _off, "disabled": _disabled, "destroyed": _destroyed,
    "radiation": _radiation,
    "radiation_truthy_not_true": _radiation_truthy_not_true,
    "parent_radiation": _parent_radiation, "dying": _dying, "dead": _dead,
    "cloaked": _cloaked, "decloaking": _decloaking, "dewarping": _dewarping,
    "undetectable": _undetectable, "can_detect_raises": _can_detect_raises,
    "out_of_range": _out_of_range,
    "cloaked_and_undetectable": _cloaked_and_undetectable,
    "nothing": _nothing,
}


def _run(monkeypatch, scenario, body, system_of, target_of):
    """One fresh world, `scenario` applied, `body(system, target, offset)`
    run with k1_system recorded (not run): (leaf calls, writes, k1 calls)."""
    with monkeypatch.context() as mp:
        w = _World(mp)
        try:
            _SCENARIOS[scenario](w, mp)
            system, target = system_of(w), target_of(w)
            k1 = []
            mp.setattr(nc, "k1_system", lambda s, dt: k1.append(
                (s is system, dt)))
            before = _writes(system)
            out = []
            calls = _leaf_calls(
                lambda: out.append(body(system, target, None)))
            return (calls, _label(w, before), _label(w, _writes(system)), k1,
                    out)
        finally:
            w.close()


def test_start_firing_is_native():
    assert ws._start_firing is _h.start_firing


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_start_firing_gates_match_the_python_order(monkeypatch, scenario):
    phasers = lambda w: w.galaxy.GetPhaserSystem()      # noqa: E731
    vorcha = lambda w: w.vorcha                         # noqa: E731
    want = _run(monkeypatch, scenario, start_firing_py, phasers, vorcha)
    got = _run(monkeypatch, scenario, _h.start_firing, phasers, vorcha)
    assert got == want
    if scenario not in ("nothing", "can_detect_raises", "decloaking",
                        "radiation_truthy_not_true"):
        assert got[1] == got[2], "a failing gate wrote"
        assert got[3] == []
    else:
        assert got[3] == [(True, 0.0)]


@pytest.mark.parametrize("scenario", ["nothing", "off", "dying", "dewarping",
                                      "cloaked"])
def test_torpedo_dumb_fire_gates_match(monkeypatch, scenario):
    """The base body with target None: no detectability or engage gate."""
    torps = lambda w: w.galaxy.GetTorpedoSystem()       # noqa: E731
    none = lambda w: None                               # noqa: E731
    want = _run(monkeypatch, scenario, start_firing_py, torps, none)
    got = _run(monkeypatch, scenario, _h.start_firing, torps, none)
    assert got == want


def test_native_body_runs_its_own_surface(monkeypatch):
    """On a stock ship the native body runs StartFiring's own surface (the
    IsOn read, the writes) without calling those Python bodies back."""
    gone = {"IsOn", "_add_target", "SetForceUpdate", "__set__",
            "_push_scalar"}
    w = _World(monkeypatch)
    try:
        ph = w.galaxy.GetPhaserSystem()
        monkeypatch.setattr(nc, "k1_system", lambda s, dt: None)
        ph.StartFiring(w.vorcha)          # first call: memos warm
        direct = []

        def prof(frame, event, arg):
            # Called by the native body: the Python frame below it is the
            # thin StartFiring (a gate's own callees are not the body's).
            if (event == "call"
                    and frame.f_back.f_code.co_name == "StartFiring"):
                direct.append(frame.f_code.co_name)
        sys.setprofile(prof)
        try:
            ph.StartFiring(w.vorcha)
        finally:
            sys.setprofile(None)
        assert not gone & set(direct), direct
        # Every gate is the Python function, called back in the order.
        gates = [n for n in direct if n in (
            "_is_offline", "_cloak_blocks_fire", "_dewarp_blocks_fire",
            "_target_undetectable", "GetParentShip", "_can_engage")]
        assert gates == ["_is_offline", "_cloak_blocks_fire",
                         "_dewarp_blocks_fire", "_target_undetectable",
                         "GetParentShip", "_can_engage"], direct
    finally:
        w.close()


class _AnswersRadiation(ws.PhaserSystem):
    """A __getattr__ that is not TGObject's: a missing `_radiation_out` is
    its answer, not an AttributeError."""
    def __getattr__(self, name):
        if name == "_radiation_out":
            return True
        return super().__getattr__(name)


class _OnProperty(ws.PhaserSystem):
    """`_is_on` behind a property (a descriptor with __get__)."""
    @property
    def _is_on(self):
        return self.__dict__.get("_is_on_raw", False)

    @_is_on.setter
    def _is_on(self, v):
        self.__dict__["_is_on_raw"] = v


class _LoggedReads(ws.PhaserSystem):
    """A __getattribute__ of its own: every read goes through it (logged
    while `log` is a list)."""
    log = None

    def __getattribute__(self, name):
        log = _LoggedReads.log
        if log is not None and name.startswith("_") \
                and not name.startswith("__"):
            log.append(name)
        return object.__getattribute__(self, name)


def _logging(body, into):
    """`body`, with _LoggedReads' reads during the call kept in `into`."""
    def run(system, target, offset):
        _LoggedReads.log = into
        try:
            return body(system, target, offset)
        finally:
            _LoggedReads.log = None
    return run


@pytest.mark.parametrize("cls", [_AnswersRadiation, _OnProperty,
                                 _LoggedReads])
def test_unusual_attribute_reads_match(monkeypatch, cls):
    """The fast instance-dict reads stand in only for a type that reads
    attributes generically; any other type is read as Python reads it."""
    def scenario(w, mp):
        ph = w.galaxy.GetPhaserSystem()
        on = ph.__dict__.get("_is_on")
        ph.__class__ = cls
        if cls is _OnProperty:
            ph.__dict__["_is_on_raw"] = on
    _SCENARIOS["unusual"] = scenario
    try:
        phasers = lambda w: w.galaxy.GetPhaserSystem()      # noqa: E731
        vorcha = lambda w: w.vorcha                         # noqa: E731
        want_reads, got_reads = [], []
        want = _run(monkeypatch, "unusual",
                    _logging(start_firing_py, want_reads), phasers, vorcha)
        got = _run(monkeypatch, "unusual",
                   _logging(_h.start_firing, got_reads), phasers, vorcha)
        assert got == want
        if cls is _LoggedReads:
            assert want_reads and got_reads == want_reads
    finally:
        del _SCENARIOS["unusual"]


def test_start_firing_writes_and_pushes_match(monkeypatch):
    """The writes land as the Python body's (same objects, same types) and
    every one reaches the mirror: the audit finds no stale row."""
    def go(body):
        with monkeypatch.context() as mp:
            w = _World(mp)
            try:
                ph = w.galaxy.GetPhaserSystem()
                mp.setattr(nc, "k1_system", lambda s, dt: None)
                offset = TGPoint3(1.0, 2.0, 3.0)
                body(ph, w.vorcha, offset)
                d = ph.__dict__
                assert d["_held_offset"] is offset
                assert d["_held_target"] is w.vorcha
                got = _label(w, _writes(ph))
                nc.audit_mirror()
                assert nc.audit_failures() == [], nc.audit_failures()
                # A second call with the target already listed: no duplicate.
                body(ph, w.vorcha, None)
                got2 = _label(w, _writes(ph))
                nc.audit_mirror()
                assert nc.audit_failures() == [], nc.audit_failures()
                return got, got2
            finally:
                w.close()
    assert go(_h.start_firing) == go(start_firing_py)


def test_start_firing_runs_the_real_session(monkeypatch):
    """Unpatched, the native body's session fires like the Python body's."""
    def go(body):
        with monkeypatch.context() as mp:
            w = _World(mp)
            try:
                ph = w.galaxy.GetPhaserSystem()
                body(ph, w.vorcha, None)
                firing = [ph.GetWeapon(i).IsFiring()
                          for i in range(ph.GetNumWeapons())]
                nc.audit_mirror()
                assert nc.audit_failures() == [], nc.audit_failures()
                return firing, _label(w, _writes(ph))
            finally:
                w.close()
    want = go(start_firing_py)
    assert any(want[0])
    assert go(_h.start_firing) == want


# ── Overrides and patches still win ─────────────────────────────────────────

def test_overrides_and_patches_still_win(monkeypatch):
    w = _World(monkeypatch)
    try:
        g, v = w.galaxy, w.vorcha
        ph, torps = g.GetPhaserSystem(), g.GetTorpedoSystem()
        k1 = []
        monkeypatch.setattr(nc, "k1_system", lambda s, dt: k1.append(s))

        # Held-fire override: no target, nothing written.
        ph.StartFiring(None)
        assert not ph.__dict__.get("_fire_held") and k1 == []

        # Torpedo override: a finite empty ammo type posts can't-fire first.
        ammo = torps.GetCurrentAmmoType()
        monkeypatch.setattr(ammo, "_unlimited", False)
        monkeypatch.setattr(type(ammo), "GetAvailable", lambda self: 0)
        posted = []
        monkeypatch.setattr(type(torps), "_post_cant_fire",
                            lambda self: posted.append(self))
        torps.StartFiring(v)
        assert posted == [torps] and k1 == []

        # Tractor override: its own gates, then the native engage.
        tractor = g.GetTractorBeamSystem()
        if tractor is not None:
            engaged = []
            monkeypatch.setattr(nc, "k1_tractor_start",
                                lambda s, t, o: engaged.append((s, t)))
            tractor.TurnOn()
            tractor.StartFiring(v)
            assert engaged == [(tractor, v)] and k1 == []

        # A class patch and an instance patch of StartFiring win for an
        # attribute caller (the native FireScript's own lookup).
        hits = []
        monkeypatch.setattr(ws.PhaserSystem, "StartFiring",
                            lambda self, *a: hits.append(("class", a)))
        getattr(ph, "StartFiring")(v)
        monkeypatch.setattr(ph, "StartFiring",
                            lambda *a: hits.append(("inst", a)), raising=False)
        getattr(ph, "StartFiring")(v)
        assert hits == [("class", (v,)), ("inst", (v,))] and k1 == []
    finally:
        w.close()


@pytest.mark.parametrize("patch", [
    "gate_fn", "is_on_class", "is_on_instance", "is_disabled_class",
    "child_is_disabled_instance", "get_parent_ship_class", "implements",
    "out_of_action", "can_engage_instance", "range_fn", "add_target_class",
    "set_force_update_class", "descriptor_set",
])
def test_a_patch_is_called(monkeypatch, patch):
    """Each patch blocks the fire (or records itself) through the native
    body exactly as through the Python body."""
    def go(body):
        with monkeypatch.context() as mp:
            w = _World(mp)
            try:
                ph = w.galaxy.GetPhaserSystem()
                seen = []
                if patch == "gate_fn":
                    mp.setattr(ws, "_cloak_blocks_fire",
                               lambda s: seen.append("cloak") or True)
                elif patch == "is_on_class":
                    mp.setattr(ws.WeaponSystem, "IsOn",
                               lambda s: seen.append("IsOn") or 0,
                               raising=False)
                elif patch == "is_on_instance":
                    mp.setattr(ph, "IsOn", lambda: seen.append("IsOn") or 0,
                               raising=False)
                elif patch == "is_disabled_class":
                    mp.setattr(ws.WeaponSystem, "IsDisabled",
                               lambda s: seen.append("IsDisabled") or 1)
                elif patch == "child_is_disabled_instance":
                    for c in ph._children:
                        mp.setattr(c, "IsDisabled",
                                   lambda: seen.append("child") or 1,
                                   raising=False)
                elif patch == "get_parent_ship_class":
                    real = ws.ShipSubsystem.GetParentShip
                    mp.setattr(ws.ShipSubsystem, "GetParentShip",
                               lambda s: seen.append("parent") or real(s))
                elif patch == "implements":
                    from engine.appc import subsystems
                    mp.setattr(subsystems, "implements",
                               lambda o, n: seen.append(("impl", n)) or False)
                elif patch == "out_of_action":
                    from engine.appc import ship_death
                    mp.setattr(ship_death, "_out_of_action",
                               lambda s: seen.append("ooa") or True)
                elif patch == "can_engage_instance":
                    mp.setattr(ph, "_can_engage",
                               lambda s, t: seen.append("engage") or False,
                               raising=False)
                elif patch == "range_fn":
                    mp.setattr(ws, "_target_within_range_gu",
                               lambda s, t, r: seen.append(("range", r))
                               or False)
                elif patch == "add_target_class":
                    real = ws.WeaponSystem._add_target
                    mp.setattr(ws.WeaponSystem, "_add_target",
                               lambda s, t: seen.append("add") or real(s, t))
                elif patch == "set_force_update_class":
                    real = ws.WeaponSystem.SetForceUpdate
                    mp.setattr(ws.WeaponSystem, "SetForceUpdate",
                               lambda s, f: seen.append(("force", f))
                               or real(s, f))
                elif patch == "descriptor_set":
                    real = nc.NativeField.__set__
                    mp.setattr(nc.NativeField, "__set__",
                               lambda d, o, v: seen.append(d._name)
                               or real(d, o, v))
                k1 = []
                mp.setattr(nc, "k1_system", lambda s, dt: k1.append(s))
                body(ph, w.vorcha, None)
                return seen, _label(w, _writes(ph)), len(k1)
            finally:
                w.close()
    want = go(start_firing_py)
    assert want[0], "the patch was never reached"
    assert go(_h.start_firing) == want


def test_held_can_engage_still_calls_get_parent_ship(monkeypatch):
    """`self._can_engage(self.GetParentShip(), target)`: the argument is
    evaluated even when the stock held-fire `_can_engage` then answers True
    (every PulseWeaponSystem with a target)."""
    def go(body):
        with monkeypatch.context() as mp:
            w = _World(mp)
            try:
                pulse = w.vorcha.GetPulseWeaponSystem()
                assert isinstance(pulse, ws._HeldFireWeaponSystem)
                seen = []
                real = ws.ShipSubsystem.GetParentShip
                mp.setattr(ws.ShipSubsystem, "GetParentShip",
                           lambda s: seen.append(type(s).__name__)
                           or real(s))
                mp.setattr(nc, "k1_system", lambda s, dt: None)
                body(pulse, w.galaxy, None)
                return seen, _label(w, _writes(pulse))
            finally:
                w.close()
    want = go(start_firing_py)
    assert want[0]
    assert go(_h.start_firing) == want


def test_a_stale_binary_surfaces_as_attributeerror():
    with pytest.raises(AttributeError, match="start_firing"):
        ws._start_firing_stale(None, None, None)


# ── Session glue removed ────────────────────────────────────────────────────

def test_system_session_pins_its_system_once(monkeypatch):
    """k1_system's session pins the system (with its children and target
    list) before the kernel walks; the walk's materialise used to pin the
    same system again. Proof it was a no-op: at the moment materialise
    runs, re-pinning the system adds or changes no pin."""
    pins_calls = []
    real_pin_system = nc._K1Walk.pin_system
    real_materialise = nc._K1Walk.materialise
    noop = []

    def pin_system(self, system):
        pins_calls.append(system)
        return real_pin_system(self, system)

    def materialise(self, n, h):
        if self.walk != n:
            scratch = nc._K1Walk()
            scratch.pins = dict(self.pins)
            real_pin_system(scratch, self.obj(h))
            noop.append(scratch.pins == self.pins)
        return real_materialise(self, n, h)

    w = _World(monkeypatch)
    try:
        ph = w.galaxy.GetPhaserSystem()
        monkeypatch.setattr(nc._K1Walk, "pin_system", pin_system)
        monkeypatch.setattr(nc._K1Walk, "materialise", materialise)
        for _ in range(3):
            pins_calls.clear()
            ph.StartFiring(w.vorcha, TGPoint3(0.5, 0.5, 0.5))
            assert pins_calls == [ph]
        assert noop and all(noop), noop
        nc.audit_mirror()
        assert nc.audit_failures() == [], nc.audit_failures()
    finally:
        w.close()
