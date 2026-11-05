"""Tractors native (fire control native only, Task 3; spec
docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md §4.4,
decisions M4, R7, R8; the Python model they replace is
docs/reference/engine/native-combat/k1-retirement-map.md §3).

A tractor's fire decisions are K1's (k1_fire_control.h, THE TRACTOR WALK):
StartFiring's engage is a native system session
(native_combat.k1_tractor_start), the held-weapon pump's sustain, its
drop-out-of-arc and re-acquire and the emitter round robin are the pump's
tractor walk. K0 stops a holding beam on power loss or starvation. The
force is its own native step (tractor_force.h, native_combat.
tractor_force_step), and ET_TRACTOR_BEAM_STARTED_FIRING / _STOPPED_FIRING
are effect-queue entries, delivered at the boundary.

Real Galaxy and Vor'cha ships (tests/helpers/k0_fight.World, native on):
the Galaxy's four projectors fire single (two forward, two aft).
"""
import math

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import effect_queue  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import tractor  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from tests.helpers.k0_fight import DT, World  # noqa: E402

TBS = ws.TractorBeamSystem
AHEAD = 30.0            # GU: inside TRACTOR_MAX_RANGE_GU (120)


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


@pytest.fixture
def world(monkeypatch):
    """Native on; the Vor'cha AHEAD GU in front of the Galaxy; the Galaxy's
    tractors on; every ET_TRACTOR_* AddEvent noted as (type, source,
    destination, delivered while deferring)."""
    w = World(monkeypatch, True, "native_tractor")
    g, v = w.ships["Galaxy"], w.ships["Vorcha"]
    v.SetTranslateXYZ(0.0, AHEAD, 0.0)
    g.GetTractorBeamSystem().TurnOn()
    w.tractor_events = []
    types = {App.ET_TRACTOR_BEAM_STARTED_FIRING: "started",
             App.ET_TRACTOR_BEAM_STOPPED_FIRING: "stopped"}
    orig = App.g_kEventManager.AddEvent

    def add_event(evt, _orig=orig):
        kind = types.get(evt.GetEventType())
        if kind is not None:
            w.tractor_events.append((kind, evt.GetSource(),
                                     evt.GetDestination(),
                                     effect_queue.deferring()))
        return _orig(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add_event)
    nc._h.combat_k1_reset_counts()
    yield w
    w.close()


def _beams(ship):
    t = ship.GetTractorBeamSystem()
    return [t.GetWeapon(i) for i in range(t.GetNumWeapons())]


def _lit(ship):
    return [b.GetName() for b in _beams(ship) if b.IsFiring()]


def _bears(ship, target):
    return [b.GetName() for b in _beams(ship)
            if ws._emitter_in_arc(b, ship,
                                  ws._resolve_bank_aim_world(b, target))]


def _yaw(ship, angle):
    m = TGMatrix3()
    m.MakeZRotation(angle)
    ship.SetMatrixRotation(ship.GetWorldRotation().MultMatrix(m))


def _no_fallbacks():
    c = nc.counts()
    assert not any(c["k1_no_fire"].values()), c["k1_no_fire"]
    return c


# ── The decision: engage, sustain, drop and re-acquire, round robin ──────────

def test_tractor_engage_native(world):
    """StartFiring is a native session: one projector grips the target, the
    pump sustains it, and no tractor is ever handed to Python -- the
    self-managed flag and the Python decision are gone."""
    for name in ("update_weapons", "_engage_beam", "_can_engage",
                 "_pump_self_managed"):
        assert name not in vars(TBS), name
    assert not hasattr(ws, "_target_tractorable")
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    tractors = g.GetTractorBeamSystem()
    tractors.StartFiring(v)
    lit = [b for b in _beams(g) if b.IsFiring()]
    assert len(lit) == 1 and lit[0]._target is v
    assert tractors.IsEngaged() and tractors.IsFiring()
    assert tractors.__dict__["_was_firing"] is True
    for _ in range(5):
        world.tick()
    assert _lit(g) == [lit[0].GetName()]
    c = _no_fallbacks()
    assert c["k1_logged"]["tractor_start"] == 1
    assert c["k1_logged"]["tractor_walk"] == 5


def test_tractor_sustain_drop_out_of_arc_reacquires(world):
    """Turned so no projector bears, the pump drops the beam but keeps the
    engage intent; turned back, it re-grips -- each crossing one STOPPED /
    STARTED; astern, an aft projector takes over."""
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    tractors = g.GetTractorBeamSystem()
    tractors.StartFiring(v)
    first = _lit(g)
    assert len(first) == 1 and first[0].startswith("Forward")
    # Find a heading where nothing bears.
    base = g.GetWorldRotation()
    for step in range(1, 72):
        g.SetMatrixRotation(base)
        _yaw(g, math.radians(5.0 * step))
        if not _bears(g, v):
            break
    else:
        raise AssertionError("no heading hides the Vor'cha")
    world.tick()
    assert _lit(g) == []
    assert tractors.IsEngaged() and not tractors.IsFiring()
    assert tractors.__dict__["_was_firing"] is False
    g.SetMatrixRotation(base)
    world.tick()
    assert len(_lit(g)) == 1
    assert tractors.__dict__["_was_firing"] is True
    # Astern: the forward projector drops and an aft one grips in the same
    # tick (no event: the system never stopped firing).
    _yaw(g, math.pi)
    world.tick()
    lit = _lit(g)
    assert len(lit) == 1 and lit[0].startswith("Aft"), lit
    kinds = [e[0] for e in world.tractor_events]
    assert kinds == ["started", "stopped", "started"], kinds
    _no_fallbacks()


def test_tractor_round_robin_single_fire(world):
    """Single fire: the first in-arc projector from `_next_emitter_index`
    grips and the cursor moves past it, so the next engage takes the next
    one in arc. Multi fire: every in-arc projector grips."""
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    tractors = g.GetTractorBeamSystem()
    bearing = _bears(g, v)
    assert len(bearing) >= 2, bearing
    names = [b.GetName() for b in _beams(g)]
    tractors.StartFiring(v)
    a = _lit(g)
    assert len(a) == 1
    assert tractors.__dict__["_next_emitter_index"] == (
        names.index(a[0]) + 1) % len(names)
    tractors.StopFiring()
    tractors.StartFiring(v)
    b = _lit(g)
    assert len(b) == 1 and b != a and b[0] in bearing, (a, b, bearing)
    tractors.StopFiring()
    tractors.SetSingleFire(0)
    tractors.StartFiring(v)
    assert sorted(_lit(g)) == sorted(bearing)
    _no_fallbacks()


# ── The force ────────────────────────────────────────────────────────────────

def _speed(ship):
    m = ship.GetMass()
    if m <= 0.0:
        m = tractor.TRACTOR_FALLBACK_MASS
    s = (tractor.TRACTOR_REFERENCE_SPEED_GUPS * tractor.TRACTOR_REFERENCE_MASS
         / m)
    return s if s < tractor.TRACTOR_MAX_SPEED_GUPS else \
        tractor.TRACTOR_MAX_SPEED_GUPS


def _hexes(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def _toward(p, dest, speed):
    """One kinematic step of p toward dest at `speed` (snap within it)."""
    ex, ey, ez = dest[0] - p.x, dest[1] - p.y, dest[2] - p.z
    elen = (ex * ex + ey * ey + ez * ez) ** 0.5
    if elen < 1e-6:
        return (p.x, p.y, p.z)
    step = speed * DT
    if elen <= step:
        return dest
    f = step / elen
    return (p.x + ex * f, p.y + ey * f, p.z + ez * f)


@pytest.mark.parametrize("mode", [TBS.TBS_HOLD, TBS.TBS_TOW, TBS.TBS_PULL,
                                  TBS.TBS_PUSH, TBS.TBS_DOCK_STAGE_1,
                                  TBS.TBS_DOCK_STAGE_2])
def test_tractor_force_matches_law(world, mode):
    """One tick of each mode: the speed is clamp(5*100/mass, 0, 20) GU/s
    (ruling R7: a mass-capped kinematic displacement, not a spring), every
    coordinate by .hex() against the law written out here."""
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    v.SetTranslateXYZ(3.0, AHEAD, 1.5)
    v.SetVelocity(TGPoint3(0.5, 0.0, 0.0))
    for ship, r in ((g, 4.0), (v, 2.5)):
        ship.SetRadius(r)
    tractors = g.GetTractorBeamSystem()
    tractors.SetMode(mode)
    tractors.StartFiring(v)
    assert _lit(g)
    sp, tp = g.GetWorldLocation(), v.GetWorldLocation()
    dx, dy, dz = tp.x - sp.x, tp.y - sp.y, tp.z - sp.z
    L = (dx * dx + dy * dy + dz * dz) ** 0.5
    u = (dx / L, dy / L, dz / L)
    s_t, s_s = _speed(v), _speed(g)
    standoff = 4.0 + 2.5 + tractor.TRACTOR_STANDOFF_MARGIN_GU
    near = tuple(sp_c + u_c * standoff for sp_c, u_c in
                 zip((sp.x, sp.y, sp.z), u))
    want_t, want_s = (tp.x, tp.y, tp.z), (sp.x, sp.y, sp.z)
    if mode == TBS.TBS_PULL:
        want_t = _toward(tp, near, s_t)
        want_s = _toward(sp, tuple(t_c - u_c * standoff for t_c, u_c in
                                   zip((tp.x, tp.y, tp.z), u)), s_s)
    elif mode == TBS.TBS_PUSH:
        want_t = tuple(t_c + u_c * s_t * DT for t_c, u_c in
                       zip((tp.x, tp.y, tp.z), u))
        want_s = tuple(s_c + -u_c * s_s * DT for s_c, u_c in
                       zip((sp.x, sp.y, sp.z), u))
    elif mode == TBS.TBS_TOW:
        drag = s_s * tractor.TRACTOR_TOW_DRAG_FRACTION
        want_s = tuple(s_c + u_c * drag * DT for s_c, u_c in
                       zip((sp.x, sp.y, sp.z), u))
    elif mode in (TBS.TBS_DOCK_STAGE_1, TBS.TBS_DOCK_STAGE_2):
        want_t = _toward(tp, near,
                         s_t * tractor.TRACTOR_DOCK_GENTLE_FRACTION)
    tractor.advance_tractors([g, v], DT)
    assert _hexes(v.GetWorldLocation()) == tuple(float(c).hex()
                                                 for c in want_t)
    assert _hexes(g.GetWorldLocation()) == tuple(float(c).hex()
                                                 for c in want_s)
    state = tractors.__dict__["_engage_state"]
    if mode == TBS.TBS_HOLD:
        # Pinned where it was grabbed, its velocity damped.
        assert _hexes(v.GetVelocityTG()) == _hexes(TGPoint3(0, 0, 0))
        assert _hexes(state["hold_point"]) == _hexes(tp)
    elif mode == TBS.TBS_TOW:
        assert set(state) == {"tow_offset"}
    else:
        assert state is None
    assert nc.counts()["k1_no_fire"] == dict.fromkeys(
        nc.counts()["k1_no_fire"], 0)


# ── The events ───────────────────────────────────────────────────────────────

def test_tractor_events_are_queue_entries(world):
    """ET_TRACTOR_BEAM_STARTED_FIRING / _STOPPED_FIRING are effect-queue
    entries (ruling R8): none is posted while the queue defers; they arrive
    at the boundary, in order, source the tractor system and destination the
    ship -- the kernel's (a grip, a drop) and Python's (StopFiring) alike."""
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    tractors = g.GetTractorBeamSystem()
    with effect_queue.scope():
        tractors.StartFiring(v)
        tractors.StopFiring()
        tractors.StartFiring(v)
        assert world.tractor_events == []
    assert [(k, s, d) for k, s, d, _ in world.tractor_events] == [
        ("started", tractors, g), ("stopped", tractors, g),
        ("started", tractors, g)]
    assert not any(e[3] for e in world.tractor_events)
    del world.tractor_events[:]
    # The pump's drop (out of range), inside the tick's scope.
    v.SetTranslateXYZ(0.0, ws.TRACTOR_MAX_RANGE_GU + 10.0, 0.0)
    world.tick()
    assert [(k, s, d) for k, s, d, _ in world.tractor_events] == [
        ("stopped", tractors, g)]
    # Outside any scope a StopFiring's STOPPED waits for the boundary.
    v.SetTranslateXYZ(0.0, AHEAD, 0.0)
    world.tick()
    del world.tractor_events[:]
    tractors.StopFiring()
    assert world.tractor_events == []
    effect_queue.boundary()
    assert [e[0] for e in world.tractor_events] == ["stopped"]
    c = nc.counts()
    assert c["k1_entries"]["TRACTOR_STARTED"] >= 2
    assert c["k1_entries"]["TRACTOR_STOPPED"] >= 1


# ── The power starvation stop ────────────────────────────────────────────────

def test_firing_write_and_the_starvation_stop(world):
    """A `_firing` write the kernels log goes through the beam's own setter
    (NativeWakeField): K1's grip lights the beam, and K0's power-starvation
    stop puts it out natively."""
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    tractors = g.GetTractorBeamSystem()
    tractors.StartFiring(v)
    assert _lit(g)
    # Starved: GetPowerPercentage() 0 while it wants power. K0 stops it.
    tractors._normal_power = 600.0
    tractors._efficiency = 0.0
    with effect_queue.scope():
        from engine import host_loop
        host_loop._advance_weapons(list(world.order), DT)
    assert _lit(g) == []
    assert nc.counts()["k0_python_reasons"].get("tractor", 0) == 0


# ── Fix round 1: a tractor is never handed back ──────────────────────────────

@pytest.mark.parametrize("dropped", ["tractor_system", "ship"])
def test_unnamed_tractor_is_never_handed_to_python(world, monkeypatch,
                                                   dropped):
    """A ship whose tractor system has no mirror row (its ref pushes -2, as
    after an unencodable `_engage_state` drops it) or a ship with no row:
    the pump's tractor getter (the ship's, for a ship with no row) is a
    counted no-fire -- tractor_row, unslotted_ship -- and the drop itself
    one ("dropped", fire control native only, R3): nothing stops the engage
    intent or runs a group walk on the projectors."""
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    tractors = g.GetTractorBeamSystem()
    tractors.StartFiring(v)
    assert tractors.IsEngaged() and _lit(g)
    nc._drop(tractors if dropped == "tractor_system" else g)
    assert nc.counts()["k1_no_fire"]["dropped"] == 1
    why = "tractor_row" if dropped == "tractor_system" else "unslotted_ship"
    before = nc.counts()["k1_no_fire"][why]
    world.tick()
    assert nc.counts()["k1_no_fire"][why] == before + 1
    # The intent and the grip are as they were: nothing ran the generic
    # held-weapon path on the tractor.
    assert tractors.IsEngaged() and _lit(g)
