"""The tractor force runs in the motion stage (native motion phase 2,
Task 7; Mark, 2026-11-04).

``ship_motion.tick_all_ship_motion`` is: every motion row, then
``tick_tractors`` (the native tractor force step,
``tractor.advance_tractors`` over the whole ``iter_ships()`` roster), then
the publish -- so motion is the only ship-pose writer, the published buffer
holds the tractor-moved poses, and a headless ``GameLoop.tick`` moves a
tractored ship. ``host_loop._advance_combat`` no longer runs it
(``cb.tractors`` is gone). The accepted cost: a beam the K1 tractor walk
grips in a tick's combat step first pulls in the NEXT tick's motion stage.

Real Galaxy and Vor'cha ships (tests/helpers/k0_fight.World, native on).
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_motion_published"),
    reason="native combat bindings not built")

from engine import host_loop  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import native_motion as nm  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import ship_motion  # noqa: E402
from engine.appc import tractor  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.core.game import _set_current_game  # noqa: E402
from engine.core.loop import GameLoop  # noqa: E402
from tests.helpers.k0_fight import DT, World  # noqa: E402

TBS = ws.TractorBeamSystem
AHEAD = 30.0            # GU: inside TRACTOR_MAX_RANGE_GU (120)
FAR = 135.0             # GU: past it


@pytest.fixture(autouse=True)
def _clean():
    # The order test pins the WHOLE iter_ships() roster, so a set an earlier
    # test left behind (test_trace_accel_prewarm's "S2"/"hull2") must go.
    App.g_kSetManager._sets.clear()
    _set_current_game(None)
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    App.g_kModelPropertyManager.ClearLocalTemplates()


@pytest.fixture
def world(monkeypatch):
    """Native on (combat and motion); the Vor'cha AHEAD GU in front of the
    Galaxy; the Galaxy's tractors on, in PULL."""
    w = World(monkeypatch, True, "tractor_motion_stage")
    nm.configure({})
    g, v = w.ships["Galaxy"], w.ships["Vorcha"]
    v.SetTranslateXYZ(0.0, AHEAD, 0.0)
    tractors = g.GetTractorBeamSystem()
    tractors.TurnOn()
    tractors.SetMode(TBS.TBS_PULL)
    yield w
    w.close()


def _xyz(p):
    return (p.x, p.y, p.z)


def _hexes(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def _combat_step(w):
    """The host's combat half of a tick: the weapons, then the combat step
    (K1's tractor walk is its held-weapon pump), in the effect scope, then
    the tick boundary."""
    with host_loop._combat_effect_scope():
        host_loop._advance_weapons(w.order, DT)
        host_loop._advance_combat(w.order, DT, push_render_data=False)
    host_loop._combat_tick_boundary()


def test_gameloop_tick_moves_a_tractored_ship_headless(world):
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    g.GetTractorBeamSystem().StartFiring(v)
    assert g.GetTractorBeamSystem().IsFiring()
    before = _xyz(v.GetWorldLocation())
    loop = GameLoop()
    loop.tick()
    after = _xyz(v.GetWorldLocation())
    assert after[1] < before[1], (before, after)


def test_advance_combat_no_longer_moves_a_tractored_ship(world):
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    g.GetTractorBeamSystem().StartFiring(v)
    before_v, before_g = _hexes(v.GetWorldLocation()), \
        _hexes(g.GetWorldLocation())
    for _ in range(5):
        _combat_step(world)
    assert g.GetTractorBeamSystem().IsFiring()
    assert _hexes(v.GetWorldLocation()) == before_v
    assert _hexes(g.GetWorldLocation()) == before_g


@pytest.mark.parametrize("native", [True, False], ids=["kernel", "python"])
def test_tractor_runs_after_every_motion_row_and_before_publish(
        world, monkeypatch, native):
    calls = []
    if native:
        orig_step = nm.step_all

        def step_all(dt):
            calls.append("rows")
            return orig_step(dt)
        monkeypatch.setattr(nm, "step_all", step_all)
    else:
        nm.configure({"DAUNTLESS_NATIVE_MOTION": "0"})
        orig_row = ship_motion._step_ship_motion

        def step_row(ship, dt):
            calls.append("row")
            return orig_row(ship, dt)
        monkeypatch.setattr(ship_motion, "_step_ship_motion", step_row)
    orig_tractors = tractor.advance_tractors

    def advance(ships, dt):
        ships = list(ships)
        calls.append(("tractors", tuple(s.GetName() for s in ships), dt))
        return orig_tractors(ships, dt)
    monkeypatch.setattr(tractor, "advance_tractors", advance)
    orig_publish = nm.publish_stage

    def publish():
        calls.append("publish")
        return orig_publish()
    monkeypatch.setattr(nm, "publish_stage", publish)

    ship_motion.tick_all_ship_motion(DT)
    rows = ["rows"] if native else ["row", "row"]
    # The whole iter_ships() roster (rocks included), as cb.tractors had.
    assert calls == rows + [("tractors", ("Galaxy", "Vorcha"), DT),
                            "publish"]


def test_published_buffer_holds_the_tractored_pose(world):
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    g.GetTractorBeamSystem().StartFiring(v)
    before = _hexes(v.GetWorldLocation())
    ship_motion.tick_all_ship_motion(DT)
    assert _hexes(v.GetWorldLocation()) != before
    _tick, rows = _h.combat_motion_published()
    buf = {h: p for h, p, _r, _v in rows}
    for s in (g, v):
        got = buf[s.__dict__["_nslot"]]
        assert tuple(float(c).hex() for c in got) == \
            _hexes(s.GetWorldLocation())


def test_pull_starts_one_tick_after_the_k1_walk_engages(world):
    """Engaged out of range, then brought in: the K1 tractor walk (the
    combat step's held-weapon pump) grips it in tick 1's combat step, after
    tick 1's motion stage, so the target first moves in tick 2's motion
    stage (it moved in tick 1 when the force ran in cb.tractors, after
    K2)."""
    g, v = world.ships["Galaxy"], world.ships["Vorcha"]
    tractors = g.GetTractorBeamSystem()
    v.SetTranslateXYZ(0.0, FAR, 0.0)
    tractors.StartFiring(v)
    assert tractors.IsEngaged() and not tractors.IsFiring()
    v.SetTranslateXYZ(0.0, AHEAD, 0.0)
    start = _hexes(v.GetWorldLocation())
    loop = GameLoop(owns_boundary=False)

    loop.tick()                                 # tick 1: motion
    assert not tractors.IsFiring()
    assert _hexes(v.GetWorldLocation()) == start
    _combat_step(world)                         # tick 1: K1 grips
    assert tractors.IsFiring()
    assert _hexes(v.GetWorldLocation()) == start

    loop.tick()                                 # tick 2: the first pull
    assert v.GetWorldLocation().y < AHEAD
