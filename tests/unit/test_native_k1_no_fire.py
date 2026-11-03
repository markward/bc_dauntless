"""NO FIRE: what fire control does when the mirror cannot answer (fire
control native only, Task 6; spec
docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md M6,
M8.4, M8.8, R2, R3; k1_fire_control.h, NO FIRE and THE WALK OFFSET).

Fire control has no Python copy any more (M3), so every former hand-back is
"does not fire that tick": counted by why in counts()["k1_no_fire"] and
logged once per why per session on stderr ("[native-combat] fire control:
... (no_fire <why>)").

* Before a system's first shot of the tick its unreturned writes are rolled
  back: the tick is as if it had not walked (R2).
* After a shot what happened is kept and the walk ends (R2).
* A dropped row is the same no-fire, counted "dropped" (R3).
* A ship whose part resolution raised does not fire, and the resolution is
  retried at every step (M8.4).
* A walk's offset object is made from what the kernel recorded for the walk,
  one object for every bank it stamps (M8.8).

Real ships throughout, as tests/unit/test_native_k1_dispatch.py builds them.
"""
import math

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")

from engine.appc import articulation  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_severance  # noqa: E402
from engine.appc import physical_parents  # noqa: E402
from engine.appc import projectiles  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from tests.unit import test_native_k1_dispatch as k1  # noqa: E402

_switch = k1._switch     # the dispatch module's per-test reset (autouse)

_TUBES = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
          ("Ahead", "vorcha", (10.0, 240.0, 5.0), math.pi))


def _spawned(mp):
    """Every torpedo registered from here on (a launch's SPAWN delivery)."""
    out = []
    real = projectiles.register

    def spy(torp, *a, **kw):
        out.append(torp)
        return real(torp, *a, **kw)
    mp.setattr(projectiles, "register", spy)
    return out


def _two_tubes(w):
    """The Galaxy's torpedo system with two loaded forward tubes, skew fire
    (exempt from the ship-wide stagger, so both are tried in one walk), and
    every other tube empty."""
    torps = w.ships["Galaxy"].GetTorpedoSystem()
    tubes = k1._weapons(torps)
    for t in tubes:
        t.SetNumReady(0)
    a, b = tubes[0], tubes[1]
    for t in (a, b):
        t.SetSkewFire(1)
        t.SetNumReady(1)
    return torps, a, b


def _out_of_step(tube):
    """The tube's slot lists out of step with its MaxReady: a launch the
    kernel cannot make (K1LaunchWhy::Other)."""
    tube._reload_timers = []
    tube._reload_advanced_at = []


def test_no_fire_rolls_back_before_first_shot(monkeypatch):
    """R2: the walk's first tube cannot launch, so the system has shot
    nothing: every write the walk made is rolled back -- the pruned list
    (the same list object), the fire timers, the tubes' rounds, the force
    update -- the walk ends there (the second tube is never tried), nothing
    is spawned, and the no-fire is counted (launch, its why launch_other)."""
    w = k1.World(monkeypatch, True, _TUBES, "k1_nofire_before",
                 player="Galaxy")
    try:
        spawned = _spawned(monkeypatch)
        torps, a, b = _two_tubes(w)
        _out_of_step(a)
        torps._add_target(w.ships["Ahead"])
        torps._fire_held = True
        torps._held_target = w.ships["Ahead"]
        torps.SetForceUpdate(1)
        lst = torps.__dict__["_target_list"]
        timers = (a._fire_timer, b._fire_timer)
        nc.k1_system(torps, 0.0)
        c = nc.counts()
        assert c["k1_no_fire"]["launch"] == 1, c["k1_no_fire"]
        assert c["k1_launch_reasons"]["launch_other"] == 1, c
        assert sum(c["k1_no_fire"].values()) == 1, c["k1_no_fire"]
        assert spawned == []
        assert torps.__dict__["_target_list"] is lst    # the prune undone
        assert (a._fire_timer, b._fire_timer) == timers
        assert a.GetNumReady() == 1 and b.GetNumReady() == 1
        assert torps._force_update is True               # not consumed
        assert c["k1_logged"]["tube_launch"] == 0
        nc.audit_mirror()
        assert nc.audit_failures() == [], nc.audit_failures()
    finally:
        w.close()


def test_no_fire_after_shot_keeps_shot(monkeypatch):
    """R2: the first tube launches, then the second cannot: the shot is
    kept -- its torpedo spawned, its round spent, the cursor moved -- and
    the walk ends there (the force update is not consumed); the no-fire is
    counted once."""
    w = k1.World(monkeypatch, True, _TUBES, "k1_nofire_after",
                 player="Galaxy")
    try:
        spawned = _spawned(monkeypatch)
        torps, a, b = _two_tubes(w)
        _out_of_step(b)
        torps.StartFiring(w.ships["Ahead"])
        c = nc.counts()
        assert c["k1_no_fire"]["launch"] == 1, c["k1_no_fire"]
        assert sum(c["k1_no_fire"].values()) == 1, c["k1_no_fire"]
        assert c["k1_logged"]["tube_launch"] == 1, c["k1_logged"]
        assert len(spawned) == 1 and spawned[0]._target_ship is \
            w.ships["Ahead"]
        assert a.GetNumReady() == 0 and b.GetNumReady() == 1
        assert torps._last_weapon_idx == 0
        assert torps._force_update is True
        nc.audit_mirror()
        assert nc.audit_failures() == [], nc.audit_failures()
    finally:
        w.close()


def test_fire_no_fire_returns_false_and_never_fires_twice(monkeypatch):
    """The SDK's Fire on a launch the kernel cannot make returns False with
    nothing written -- no round spent, no torpedo -- and no other copy can
    make the shot afterwards (Task 4 review: a handed-back launch could
    double-fire). The no-fire is counted once per call, its launch why once
    (the FIRE_DUMB hand-back counted it twice)."""
    w = k1.World(monkeypatch, True, _TUBES, "k1_nofire_fire",
                 player="Galaxy")
    try:
        spawned = _spawned(monkeypatch)
        _torps, a, _b = _two_tubes(w)
        _out_of_step(a)
        assert a.Fire(w.ships["Ahead"]) is False
        assert a.GetNumReady() == 1 and spawned == []
        c = nc.counts()
        assert c["k1_no_fire"]["launch"] == 1, c["k1_no_fire"]
        assert c["k1_launch_reasons"]["launch_other"] == 1, c
        a.FireDumb(0, 1)
        assert a.GetNumReady() == 1 and spawned == []
        c = nc.counts()
        assert c["k1_no_fire"]["launch"] == 2, c["k1_no_fire"]
        assert c["k1_launch_reasons"]["launch_other"] == 2, c
        a._resize_slots()                   # the lists back in step
        assert a.Fire(w.ships["Ahead"]) is True
        assert len(spawned) == 1 and a.GetNumReady() == 0
    finally:
        w.close()


def test_no_fire_logged_once_per_reason(monkeypatch, capsys):
    """Every why is logged once per session through `[native-combat]` on
    stderr, the kernel's and the driver's alike; reset() clears the
    logged-once set (the next session logs it again)."""
    w = k1.World(monkeypatch, True, _TUBES, "k1_nofire_log",
                 player="Galaxy")
    try:
        _torps, a, _b = _two_tubes(w)
        _out_of_step(a)
        stranger = object()     # a Fire target the mirror cannot name
        capsys.readouterr()
        for _ in range(3):
            assert a.Fire(w.ships["Ahead"]) is False
            assert a.Fire(stranger) is False
        err = capsys.readouterr().err
        assert err.count("(no_fire launch)") == 1, err
        assert err.count("(no_fire unnamed_target)") == 1, err
        assert all(line.startswith("[native-combat] fire control: ")
                   for line in err.splitlines() if "no_fire" in line), err
        c = nc.counts()["k1_no_fire"]
        assert c["launch"] == 3 and c["unnamed_target"] == 3, c
        nc.reset()
        nc.configure(k1.ON)
        assert nc.counts()["k1_no_fire"]["launch"] == 0
        assert a.Fire(w.ships["Ahead"]) is False
        err = capsys.readouterr().err
        assert err.count("(no_fire launch)") == 1, err
    finally:
        w.close()


def test_dropped_row_is_counted_no_fire(monkeypatch):
    """R3: a row dropped (a value the mirror cannot encode, a stale handle)
    is a no-fire, counted "dropped" and logged once; the ship it was then
    never fires (the pump's unslotted_ship), nothing else does instead."""
    w = k1.World(monkeypatch, True, k1._DUEL, "k1_nofire_drop")
    try:
        galaxy = w.ships["Galaxy"]
        g = galaxy.GetPhaserSystem()
        g.StartFiring(w.ships["Vorcha"])
        for _ in range(3):
            w.tick()
        assert nc.counts()["k1_logged"]["beam_edge"] > 0
        nc._drop(galaxy)
        assert "_nslot" not in galaxy.__dict__
        c = nc.counts()["k1_no_fire"]
        assert c["dropped"] == 1, c
        before = nc.counts()["k1_logged"]["beam_edge"]
        lit = [b for b in k1._weapons(g) if b._firing]
        for b in lit:
            b.StopFiring()
        w.tick()
        c = nc.counts()
        assert c["k1_no_fire"]["unslotted_ship"] == 1, c["k1_no_fire"]
        assert c["k1_logged"]["beam_edge"] == before   # it fired no more
        assert not any(b._firing for b in k1._weapons(g))
    finally:
        w.close()


_BOP = (("BoP", "birdofprey", (0.0, 0.0, 0.0), 0.0, "ships.BirdOfPrey"),
        ("Vorcha", "vorcha", (40.0, 260.0, 15.0), math.pi))


def test_part_resolution_error_retries_each_step(monkeypatch):
    """M8.4: a posed ship whose part resolution raises does not fire (its
    slots are stale: part_stale, logged once), and the resolution is tried
    again at EVERY step boundary -- not only when the part-map generation
    moves -- so the ship fires again as soon as it resolves."""
    w = k1.World(monkeypatch, True, _BOP, "k1_nofire_parts")
    try:
        bop, v = w.ships["BoP"], w.ships["Vorcha"]
        articulation.force_pose(bop, "cruise")
        cannons = bop.GetPulseWeaponSystem()
        cannons.SetSingleFire(0)
        calls = []

        def boom(*a, **kw):
            calls.append(1)
            raise RuntimeError("part resolution")
        with monkeypatch.context() as mp:
            mp.setattr(part_severance, "part_for_mount", boom)
            mp.setattr(physical_parents, "part_for_property", boom)
            nc._resolved_gen.clear()    # resolved at load: resolve again
            cannons.StartFiring(v)
            n0 = len(calls)
            assert n0 > 0
            w.tick()
            n1 = len(calls)
            w.tick()
            n2 = len(calls)
            assert n1 > n0 and n2 > n1, (n0, n1, n2)   # retried every step
            c = nc.counts()["k1_no_fire"]
            assert c["part_stale"] >= 3, c
            assert set(k for k, n in c.items() if n) == {"part_stale"}, c
            assert nc.counts()["k1_logged"]["pulse_launch"] == 0
        for cannon in k1._weapons(cannons):
            cannon._cooldown_remaining = 0.0
            cannon._charge_level = cannon._max_charge
        cannons.SetForceUpdate(1)
        before = nc.counts()["k1_no_fire"]["part_stale"]
        cannons.StartFiring(v)
        c = nc.counts()
        assert c["k1_no_fire"]["part_stale"] == before, c["k1_no_fire"]
        assert c["k1_logged"]["pulse_launch"] > 0, c["k1_logged"]
    finally:
        w.close()


def test_pulse_held_target_dying_stops_the_system(monkeypatch):
    """The pump's stop gates run before the walk-only pre-scan (fire control
    native only, fix round 1): a pulse system held on a target that dies is
    stopped on that tick's pump, as host_loop._pump_held_system's
    `held.IsDead()` gate did (`_fire_held` False, IsFiring 0) -- not left
    held for good behind a pulse_ship_target no-fire every tick (its dead
    target is no live target-list entry, which only the WALK needs)."""
    w = k1.World(monkeypatch, True, _BOP, "k1_pulse_held_dies")
    try:
        bop, v = w.ships["BoP"], w.ships["Vorcha"]
        cannons = bop.GetPulseWeaponSystem()
        cannons.StartFiring(v)
        assert cannons._fire_held and cannons.IsFiring()
        v.SetDead()
        w.tick()
        assert cannons._fire_held is False
        assert cannons.IsFiring() == 0
        for _ in range(4):
            w.tick()
        c = nc.counts()["k1_no_fire"]
        assert not any(c.values()), c
    finally:
        w.close()


def test_walk_offset_object_built_natively(monkeypatch):
    """M8.8: every bank a walk stamps holds ONE offset object (ruling P5),
    made from what the kernel recorded for the walk: the system's own
    `_held_offset` object, or -- with a Manual Aim pick on the firing ship --
    one new TGPoint3 of the pick (neither the ship's stored pick nor a copy
    per bank). No Python walk offset method exists to ask."""
    w = k1.World(monkeypatch, True, k1._DUEL, "k1_walk_offset")
    try:
        galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
        g = galaxy.GetPhaserSystem()
        g.SetSingleFire(0)
        held = TGPoint3(0.5, 1.0, -0.25)
        g.StartFiring(vorcha, held)
        lit = [b for b in k1._weapons(g) if b._firing]
        assert len(lit) >= 2, "fewer than two banks lit"
        assert all(b._target_offset is held for b in lit)
        pick = TGPoint3(2.0 / 7.0, -5.0 / 11.0, 13.0 / 3.0)
        galaxy.set_manual_target_offset(pick)
        w.tick()
        offs = [b._target_offset for b in k1._weapons(g) if b._firing]
        assert len(offs) >= 2, offs
        first = offs[0]
        assert all(o is first for o in offs)            # one object
        assert isinstance(first, TGPoint3)
        assert first is not galaxy._manual_target_offset
        assert first is not held
        assert (first.x, first.y, first.z) == (pick.x, pick.y, pick.z)
        assert not hasattr(type(g), "_live_held_offset")
    finally:
        w.close()


def test_held_planet_stops_the_system(monkeypatch):
    """Final review m1: a planet (ObjectClass: no IsDead) AI or a script
    can SetTarget. Python's `hasattr(held, "IsDead") and held.IsDead()` was a
    truthy _Stub -- dead -- so the pump stopped the system; natively it
    reads as dead too (k1_fire_control.cc object_dead). A phaser system and
    a tractor held on one stop on the next pump: no stub_or_unplaced every
    tick, no tractor rolled back with its beam held (draining power)."""
    w = k1.World(monkeypatch, True, k1._DUEL, "k1_held_planet")
    try:
        import App
        galaxy = w.ships["Galaxy"]
        planet = App.Planet_Create(20.0, "")
        planet.SetTranslateXYZ(0.0, 60.0, 0.0)
        w.set.AddObjectToSet(planet, "Planet")
        phasers = galaxy.GetPhaserSystem()
        tractors = galaxy.GetTractorBeamSystem()
        phasers.StartFiring(planet)
        tractors.StartFiring(planet)
        assert phasers._fire_held and tractors._fire_held
        w.tick()
        assert phasers._fire_held is False
        assert tractors._fire_held is False
        assert not any(b.IsFiring() for b in k1._weapons(tractors))
        w.tick()
        c = nc.counts()["k1_no_fire"]
        assert not any(c.values()), c
    finally:
        w.close()
