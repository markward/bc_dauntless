"""The SDK's own weapon routes native (fire control native only, Task 4;
spec docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md
§4.5, rulings M8.1-3 and M8.6; the routes are KRM §2.6-2.7,
docs/reference/engine/native-combat/k1-retirement-map.md).

* ``Weapon.FireDumb`` (SDK AI/Preprocessors.py:458) is a one-tube native
  session on the kernel's dumb_fire (M8.1).
* ``CanFire`` and ``Fire`` are thin wrappers over the native rule
  (fire_gates can_fire; a one-weapon K1 session), ``CanFire``'s ``_depleted``
  clear included (M8.6).
* A tube with no ammo type fires its property's slot-0 script, from the
  launch cache (M8.2).
* A stale launch cache -- a re-imported pulse module, a projectile-cache
  reset in the middle of a K1 session -- launches from the cache it has and
  is re-pushed at the next K1 entry: no hand-back, no no-fire (M8.3).

Each runs with native combat on (the K1 pump's predicate,
native_combat.fire_control_native); with it off the Python path is kept
until Task 6. Real ships, as tests/unit/test_native_k1_dispatch.py builds
them; where Python is the reference, both arms run and must be equal.
"""
import importlib
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

from engine.appc import effect_queue as eq  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.core import step_memo  # noqa: E402
from tests.unit import test_native_k1_dispatch as k1  # noqa: E402


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _t(v):
    """A value with its type; floats by .hex()."""
    if isinstance(v, float):
        return ("float", v.hex())
    return (type(v).__name__, v)


# ── M8.1: the SDK's dumb fire ────────────────────────────────────────────────

def test_sdk_fire_dumb_is_native(monkeypatch):
    """`pTube.FireDumb(0, 1)` is a one-tube native session: a launch is
    logged writes plus a SPAWN (no FIRE_DUMB record, no Python decision),
    a dumb fire Python would refuse (the ship-wide stagger, an empty tube)
    writes nothing. Every torpedo, field by field, and every launch event,
    in order, equal the Python reference's."""
    def script(w, t):
        tubes = k1._weapons(w.ships["Galaxy"].GetTorpedoSystem())
        if t == 0:
            tubes[0].FireDumb(0, 1)         # launches
            tubes[1].FireDumb(0, 1)         # the 0.5 s stagger
        elif t == 45:
            tubes[1].FireDumb(0, 1)         # past it: launches
            tubes[0].FireDumb(0, 1)         # fired, reloading

    (rw, rl, _), (nw, nl, counts) = k1._launch_arms(monkeypatch, script, 60)
    assert len(rl.spawned) == len(nl.spawned) >= 2, rl.events
    assert all(s[9] is None for s in nl.spawned)        # no target: dumb
    logged = counts["k1_logged"]
    assert logged["dumb_launch"] == len(nl.spawned), logged
    assert logged["dumb_launch"] + logged["dumb_refused"] == 4, logged
    assert not any(counts["k1_launch_reasons"].values()), counts
    assert counts["k1_python_systems"] == 0, counts


# ── M8.6: CanFire and Fire ───────────────────────────────────────────────────

def _can_fire_sweep(w):
    """Every leaf kind's CanFire over its charge (latched and not), its
    parent on and off; a cannon's cooldown; a tube's rounds. Each row is
    (what, answer, `_depleted` after), typed."""
    galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
    galaxy.GetTractorBeamSystem().TurnOn()
    rows = []
    for system in (galaxy.GetPhaserSystem(), galaxy.GetTractorBeamSystem(),
                   vorcha.GetPulseWeaponSystem()):
        weapon = system.GetWeapon(0)
        mx, mn = weapon._max_charge, weapon._min_firing_charge
        charges = sorted({0.0, mn * 0.5, mn - 1e-9, mn, mn + 1e-9,
                          mx * 0.5, mx})
        for on in (1, 0):
            if on:
                system.TurnOn()
            else:
                system.TurnOff()
            for depleted in (False, True):
                for c in charges:
                    weapon._charge_level = c
                    weapon._depleted = depleted
                    r = weapon.CanFire()
                    rows.append((w.label(weapon), on, depleted, c.hex(),
                                 _t(r), _t(weapon._depleted)))
        system.TurnOn()
    cannon = vorcha.GetPulseWeaponSystem().GetWeapon(0)
    cannon._charge_level = cannon._max_charge
    for cooldown in (0.0, 0.25):
        cannon._cooldown_remaining = cooldown
        rows.append((w.label(cannon), "cooldown", cooldown,
                     _t(cannon.CanFire())))
    tube = galaxy.GetTorpedoSystem().GetWeapon(0)
    for ready in (1, 0):
        tube.SetNumReady(ready)
        rows.append((w.label(tube), "ready", ready, _t(tube.CanFire())))
    return rows


def test_can_fire_is_native_and_clears_depleted(monkeypatch):
    """CanFire is the native rule (fire_gates.cc can_fire), with Python's
    side effect: a latched bank whose charge is back at MinFiringCharge has
    `_depleted` cleared, whatever it then answers. Over the sweep every
    answer and every latch equal the Python rule's, the mirror agrees, and
    every call was the native one."""
    arms = []
    for native in (False, True):
        with monkeypatch.context() as mp:
            w = k1.World(mp, native, k1._PULSE_SHIPS,
                         "k1_canfire_%d" % native)
            try:
                _h.combat_k1_reset_counts()
                rows = _can_fire_sweep(w)
                if native:
                    counts = nc.counts()
                    nc.audit_mirror()
                    assert nc.audit_failures() == [], nc.audit_failures()
            finally:
                w.close()
            arms.append(rows)
    ref, nat = arms
    assert len(ref) == len(nat) > 50
    for a, b in zip(ref, nat):
        assert a == b, "python %r\nnative %r" % (a, b)
    # A latch cleared: the sweep did reach the side effect.
    assert any(r[2] is True and r[5] == ("bool", False) for r in ref[:-4])
    assert counts["k1_logged"].get("sdk_can_fire", 0) == len(nat), counts


def test_fire_wrapper_native(monkeypatch):
    """Fire is a one-weapon native session (the walk's decision and effect,
    M8.6): a beam's edge and sustain (a TractorBeam's without its
    ET_WEAPON_FIRED), a tube's launch and a refused aim, a cannon's bolt at
    a target and at its ship's target. Every answer, every bolt and torpedo
    field by field, every event in order: as the Python reference."""
    def script(w, t):
        galaxy, ahead = w.ships["Galaxy"], w.ships["Ahead"]
        if t == 0:
            w.fired = []
            galaxy.GetTractorBeamSystem().TurnOn()
            ahead.SetTarget(galaxy)
        elif t == 1:
            for bank in k1._weapons(galaxy.GetPhaserSystem()):
                w.fired.append(_t(bank.Fire(ahead)))
            for beam in k1._weapons(galaxy.GetTractorBeamSystem()):
                w.fired.append(_t(beam.Fire(ahead, TGPoint3(0.5, 0.0, 0.0))))
        elif t == 2:
            for bank in k1._weapons(galaxy.GetPhaserSystem()):
                w.fired.append(_t(bank.Fire(ahead)))          # sustain
            tubes = k1._weapons(galaxy.GetTorpedoSystem())
            w.fired.append(_t(tubes[0].Fire(ahead, TGPoint3(0.25, -0.5,
                                                            0.125))))
            w.fired.append(_t(tubes[-1].Fire(ahead)))      # aft: the cone
            cannons = k1._weapons(ahead.GetPulseWeaponSystem())
            w.fired.append(_t(cannons[0].Fire(galaxy)))
            w.fired.append(_t(cannons[1].Fire()))       # the ship's target

    arms = k1._launch_arms(monkeypatch, script, 30, player="Galaxy")
    (rw, rl, _), (nw, nl, counts) = arms
    assert nw.fired == rw.fired
    assert ("bool", True) in rw.fired and ("bool", False) in rw.fired
    assert len(nl.spawned) >= 3, rl.events
    logged = counts["k1_logged"]
    assert logged.get("sdk_fire", 0) == len(nw.fired), logged
    assert logged["tube_launch"] + logged["pulse_launch"] \
        == len(nl.spawned), logged
    assert not any(counts["k1_launch_reasons"].values()), counts
    assert counts["k1_python_systems"] == 0, counts


# ── M8.2: a tube with no ammo type ───────────────────────────────────────────

def test_tube_without_ammo_type_fires_slot0_script(tmp_path, monkeypatch):
    """A torpedo system with no ammo type launches its property's slot-0
    script (_spawn_torpedo's fallback): that script's launch is in the
    launch cache, pushed with the property (and again by its
    SetTorpedoScript), so the kernel makes the launch -- every torpedo
    field by field as Python's, its module the slot-0 one, no hand-back."""
    name = "k1fx_slot0_launch"
    fixture = k1._fixture_module(tmp_path, monkeypatch, name, k1._PURE_TORP)

    def script(w, t):
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        if t == 0:
            torps._ammo_by_slot.clear()
            nc.push_field(torps, "_ammo_by_slot")
            torps.GetProperty().SetTorpedoScript(0, name)
            assert torps.GetCurrentAmmoType() is None
        k1._tube_volley(w, t)

    (rw, rl, _), (nw, nl, counts) = k1._launch_arms(monkeypatch, script, 64)
    assert len(nl.spawned) >= 2, rl.events
    assert all(t._damage == fixture.GetDamage() for t in nl.torps)
    assert counts["k1_logged"]["tube_launch"] == len(nl.spawned), counts
    assert not any(counts["k1_launch_reasons"].values()), counts


# ── M8.3: a stale launch cache ───────────────────────────────────────────────

def _mid_session_pump(ships, body):
    """One pump session over `ships` in the tick's scope, the first ship's
    phaser system row dropped so the kernel hands that getter (0) to Python
    (RUN_PYTHON) BEFORE it walks any other: `body(ship, getter)` is Python
    run in the middle of the session."""
    nc._drop(ships[0].GetPhaserSystem())
    with eq.scope(), step_memo.combat_step():
        nc.k1_pump(list(ships), k1.DT, body)


def test_reimported_pulse_module_repushed_not_no_fire(monkeypatch):
    """A cannon's module re-imported in the middle of a K1 session (a new
    module object in sys.modules): the rest of that session launches from
    the module it cached, natively -- not a hand-back, not a no-fire, not
    counted -- and the next K1 entry re-pushes the new one, which every
    later bolt carries."""
    with monkeypatch.context() as mp:
        w = k1.World(mp, True, k1._PULSE_SHIPS, "k1_reimport",
                     player="Vorcha")
        launches = k1._Launches(w)
        try:
            vorcha, galaxy = w.ships["Vorcha"], w.ships["Galaxy"]
            cannons = vorcha.GetPulseWeaponSystem()
            script = ws.pulse_module_script(cannons.GetWeapon(0))
            old = sys.modules[script]
            created = []
            mp.setattr(old, "Create",
                       lambda t, _c=old.Create: (created.append("old"),
                                                 _c(t))[1])
            cannons.StartFiring(galaxy, TGPoint3(0.5, 1.0, -0.25))
            pkg, _dot, leaf = script.rpartition(".")
            mp.setattr(sys.modules[pkg], leaf, old)     # restored after
            new = []

            def body(ship, getter):
                mp.delitem(sys.modules, script)
                mod = importlib.import_module(script)
                mp.setattr(mod, "Create",
                           lambda t, _c=mod.Create: (created.append("new"),
                                                     _c(t))[1])
                new.append(mod)

            def rearm():
                w.clock[0] += 1.0
                for c in k1._weapons(cannons):
                    c._cooldown_remaining = 0.0
                    c._charge_level = c._max_charge
                cannons.SetForceUpdate(1)       # the walk tries this tick

            rearm()
            _h.combat_k1_reset_counts()
            created.clear()
            _mid_session_pump([galaxy, vorcha], body)
            assert len(new) == 1 and new[0] is not old
            c = nc.counts()
            assert c["k1_launch_reasons"] == dict.fromkeys(
                c["k1_launch_reasons"], 0), c["k1_launch_reasons"]
            assert c["k1_logged"]["pulse_launch"] >= 1, c["k1_logged"]
            assert created and set(created) == {"old"}, created
            assert not any(c["k1_no_fire"].values()), c["k1_no_fire"]
            # The next K1 entry re-pushes the new module.
            rearm()
            created.clear()
            with eq.scope():
                cannons.StartFiring(galaxy, TGPoint3(0.5, 1.0, -0.25))
            assert ws.pulse_module(script) is new[0]
            c = nc.counts()
            assert created and set(created) == {"new"}, created
            assert not any(c["k1_launch_reasons"].values()), c
            assert not any(c["k1_no_fire"].values()), c["k1_no_fire"]
            assert len(launches.torps) >= 2
        finally:
            w.close()


def test_cache_reset_mid_session_repushed(monkeypatch):
    """The projectile-cache reset (a mission swap's) made in the middle of
    a K1 session (THE P6 WINDOW): the rest of that session's launches come
    from the launch cache the rows hold, natively -- not handed back
    uncached, not a no-fire, not counted -- and the next K1 entry re-reads
    every type."""
    with monkeypatch.context() as mp:
        w = k1.World(mp, True, k1._LAUNCH_SHIPS, "k1_reset_window",
                     player="Galaxy")
        launches = k1._Launches(w)
        try:
            galaxy, ahead = w.ships["Galaxy"], w.ships["Ahead"]
            torps = galaxy.GetTorpedoSystem()
            ammo = torps.GetCurrentAmmoType()
            script = ammo.GetTorpedoScript()
            torps.StartFiring(ahead)
            resets = []

            def body(ship, getter):
                ws._reset_projectile_module_cache()     # mid-session
                resets.append((ship.GetName(), getter))

            def rearm():
                w.clock[0] += 1.0
                for tube in k1._weapons(torps):
                    tube.SetNumReady(1)
                torps.SetForceUpdate(1)         # the walk tries this tick

            rearm()
            _h.combat_k1_reset_counts()
            fired = len(launches.torps)
            _mid_session_pump([galaxy], body)
            assert resets == [("Galaxy", 0)]
            c = nc.counts()
            assert c["k1_launch_reasons"] == dict.fromkeys(
                c["k1_launch_reasons"], 0), c["k1_launch_reasons"]
            assert c["k1_logged"]["tube_launch"] == 1, c["k1_logged"]
            assert len(launches.torps) == fired + 1
            assert not any(c["k1_no_fire"].values()), c["k1_no_fire"]
            # Not re-read inside the window: at the next K1 entry.
            assert script not in ws._tube_launch_cache
            rearm()
            with eq.scope():
                torps.StartFiring(ahead)
            assert script in ws._tube_launch_cache
            row = _h.combat_dump(ammo.__dict__["_nslot"])
            assert row["ammo_launch_state"] == ws.LAUNCH_CACHED
            c = nc.counts()
            assert c["k1_logged"]["tube_launch"] == 2, c["k1_logged"]
            assert not any(c["k1_launch_reasons"].values()), c
        finally:
            w.close()
