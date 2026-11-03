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

Fire control has no Python copy (M3): each runs natively, on real ships
as tests/unit/test_native_k1_dispatch.py builds them; where Python was the
reference, the run is compared with its recording (that module's RECORDED
EXPECTATIONS, tests/fixtures/k1_dispatch/).
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
    k1.recording_setup()
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    k1.recording_teardown()


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
    in order, equal the recorded Python reference's."""
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
    k1._no_fire_free(counts)


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
    answer and every latch equal the recorded Python rule's, the mirror
    agrees, and every call was the native one."""
    with monkeypatch.context() as mp:
        w = k1.World(mp, True, k1._PULSE_SHIPS, "k1_canfire_1")
        try:
            _h.combat_k1_reset_counts()
            nat = k1._norm(_can_fire_sweep(w))
            counts = nc.counts()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()
    ref = k1._expect("rows", {"rows": nat})["rows"]
    assert len(ref) == len(nat) > 50
    for a, b in zip(ref, nat):
        assert a == b, "python %r\nnative %r" % (a, b)
    # A latch cleared: the sweep did reach the side effect.
    assert any(r[2] is True and r[5] == ["bool", False] for r in ref[:-4])
    assert counts["k1_logged"].get("sdk_can_fire", 0) == len(nat), counts


def test_fire_wrapper_native(monkeypatch):
    """Fire is a one-weapon native session (the walk's decision and effect,
    M8.6): a beam's edge and sustain (a TractorBeam's without its
    ET_WEAPON_FIRED), a tube's launch and a refused aim, a cannon's bolt at
    a target and at its ship's target. Every answer, every bolt and torpedo
    field by field, every event in order: as the recorded Python
    reference."""
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
    assert k1._norm(nw.fired) == rw.recorded["fired"]
    assert ("bool", True) in nw.fired and ("bool", False) in nw.fired
    assert len(nl.spawned) >= 3, rl.events
    logged = counts["k1_logged"]
    assert logged.get("sdk_fire", 0) == len(nw.fired), logged
    assert logged["tube_launch"] + logged["pulse_launch"] \
        == len(nl.spawned), logged
    assert not any(counts["k1_launch_reasons"].values()), counts
    k1._no_fire_free(counts)


# ── M8.2: a tube with no ammo type ───────────────────────────────────────────

def test_tube_without_ammo_type_fires_slot0_script(tmp_path, monkeypatch):
    """A torpedo system with no ammo type launches its property's slot-0
    script (the deleted _spawn_torpedo's fallback): that script's launch
    is in the launch cache, pushed with the property (and again by its
    SetTorpedoScript), so the kernel makes the launch -- every torpedo
    field by field as the recorded Python's, its module the slot-0 one."""
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
# No Python runs inside a K1 session (fire control native only, M3), so a
# cache goes stale only between sessions: the next K1 entry re-pushes it
# (_refresh_stale_launches) -- never a hand-back, never a no-fire.

def _pump(ships):
    """One pump session over `ships` in the tick's scope."""
    with eq.scope(), step_memo.combat_step():
        nc.k1_pump(list(ships), k1.DT)


def test_reimported_pulse_module_repushed_not_no_fire(monkeypatch):
    """A cannon's module re-imported between two K1 sessions (a new module
    object in sys.modules): the next K1 entry re-pushes the new one, which
    every later bolt carries -- not a hand-back, not a no-fire, not
    counted."""
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
            cannons.StartFiring(galaxy, TGPoint3(0.5, 1.0, -0.25))
            pkg, _dot, leaf = script.rpartition(".")
            mp.setattr(sys.modules[pkg], leaf, old)     # restored after
            mp.delitem(sys.modules, script)
            new = importlib.import_module(script)
            assert new is not old
            mp.setattr(new, "Create",
                       lambda t, _c=new.Create: (created.append("new"),
                                                 _c(t))[1])
            w.clock[0] += 1.0
            for c in k1._weapons(cannons):
                c._cooldown_remaining = 0.0
                c._charge_level = c._max_charge
            cannons.SetForceUpdate(1)       # the walk tries this tick
            _h.combat_k1_reset_counts()
            _pump([galaxy, vorcha])
            assert ws.pulse_module(script) is new
            c = nc.counts()
            assert c["k1_logged"]["pulse_launch"] >= 1, c["k1_logged"]
            assert created and set(created) == {"new"}, created
            assert not any(c["k1_launch_reasons"].values()), c
            assert not any(c["k1_no_fire"].values()), c["k1_no_fire"]
            assert launches.torps
        finally:
            w.close()


def test_cache_reset_mid_session_repushed(monkeypatch):
    """The projectile-cache reset (a mission swap's) made between two K1
    sessions (THE P6 WINDOW): the rows keep the launch they hold until the
    next K1 entry, which re-reads every type -- its launch native, not
    handed back uncached, not a no-fire, not counted."""
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
            ws._reset_projectile_module_cache()     # between sessions
            assert script not in ws._tube_launch_cache
            row = _h.combat_dump(ammo.__dict__["_nslot"])
            assert row["ammo_launch_state"] == ws.LAUNCH_CACHED  # as it was
            w.clock[0] += 1.0
            for tube in k1._weapons(torps):
                tube.SetNumReady(1)
            torps.SetForceUpdate(1)         # the walk tries this tick
            _h.combat_k1_reset_counts()
            fired = len(launches.torps)
            _pump([galaxy])
            assert script in ws._tube_launch_cache  # re-read at the entry
            row = _h.combat_dump(ammo.__dict__["_nslot"])
            assert row["ammo_launch_state"] == ws.LAUNCH_CACHED
            c = nc.counts()
            assert c["k1_logged"]["tube_launch"] == 1, c["k1_logged"]
            assert len(launches.torps) == fired + 1
            assert not any(c["k1_launch_reasons"].values()), c
            assert not any(c["k1_no_fire"].values()), c["k1_no_fire"]
        finally:
            w.close()
