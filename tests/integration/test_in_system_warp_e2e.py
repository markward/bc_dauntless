"""In-system warp end to end, headless (in-system-warp spec, Testing).

Loads the developer "System Preview" mission (engine.dev_missions.
system_preview: Ona 1, player Galaxy at "Player Start") the way the dev
picker does, brings up Ona's sibling regions the way host_loop's per-tick
system_loader.ensure_loaded call does, then presses Warp exactly as the Helm
does -- warp_button.press on BC's own Warp button after plotting a course,
or warp_button.press_heading for Warp on Heading -- and ticks the sim plus
the host's per-frame dash.tick (tests/helpers/headless_mission._sim_tick).

The headless flythrough is off, so a system-to-system warp takes the hard-cut
tunnel through BC's "warp" set; a Set Course within one system dashes
through real space and never enters that set.
"""
import math

import pytest

import App
from engine.appc import dash, warp_button
from engine.appc.math import TGPoint3
from engine.core.loop import GameLoop, TICK_DELTA
from engine.systems import celestial, frames, resolve, system_loader
from engine.systems.warp_path import clearance_gu
from tests.helpers import headless_mission as hm
from tests.helpers.headless_mission import no_logged_failures  # noqa: F401 (fixture)

PREVIEW = "engine.dev_missions.system_preview"
ONA1, ONA2, ONA3 = ("Systems.Ona.Ona1", "Systems.Ona.Ona2",
                    "Systems.Ona.Ona3")
ENGAGED = 4.5          # GU/s, the impulse speed a heading dash engages at
DASH_BOUND_S = 40.0


class World:
    pass


@pytest.fixture
def world(no_logged_failures, monkeypatch):  # noqa: F811 (fixture)
    system_loader.reset()
    w = World()
    w.mission, w.episode, w.game, _ = hm.load(PREVIEW)
    w.player = App.Game_GetCurrentPlayer()
    assert w.player is not None and w.player.GetContainingSet().GetName() == "Ona1"
    # host_loop's per-tick call, once the player sits in a mapped region.
    assert sorted(system_loader.ensure_loaded(w.player)) == ["Ona2", "Ona3"]
    w.button = App.SortedRegionMenu_GetWarpButton()
    # Every set the player enters from here on, from its ET_ENTERED_SET (a
    # hard-cut tunnel can run whole inside the press, between two ticks).
    w.entered = []
    orig = App.g_kEventManager.AddEvent

    def _add(evt):
        if evt.GetEventType() == App.ET_ENTERED_SET:
            dest = evt.GetDestination()
            s = dest.GetContainingSet() if dest is not None else None
            if dest is App.Game_GetCurrentPlayer() and s is not None:
                w.entered.append(s.GetName())
        orig(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", _add)
    w.sets_seen = set()
    w.samples = []
    yield w
    system_loader.reset()
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def _set(name):
    return App.g_kSetManager.GetSet(name)


def _sys(obj):
    return tuple(frames.system_position(obj)[1:])


def _body(name):
    return next(b for b in resolve.map_of("Ona").bodies if b.name == name)


def _sun():
    suns = [b for b in resolve.map_of("Ona").bodies if b.orbits is None]
    assert len(suns) == 1, "premise: Ona has one star"
    return suns[0]


def _run(w, pred, bound_s=DASH_BOUND_S):
    """Tick (sim + host dash tick) until pred(); every tick records the
    player's set and its system position."""
    loop = GameLoop()
    for _ in range(int(round(bound_s / TICK_DELTA))):
        if pred():
            return
        hm._sim_tick(loop, w.player)
        s = w.player.GetContainingSet()
        w.sets_seen.add(s.GetName() if s is not None else None)
        if dash.is_dashing(w.player):
            w.samples.append(_sys(w.player))
    raise AssertionError("condition not reached in %.0f s" % bound_s)


def _set_course_and_warp(w, module):
    """Helm > Set Course > module, then Warp: record_course_selection's two
    writes to the button, then the button's own press."""
    hm.plot_course(w.button, module)
    warp_button.press(w.button)


def _dash_to(w, module):
    _set_course_and_warp(w, module)
    assert dash.is_dashing(w.player), "a same-system course dashes"
    _run(w, lambda: not warp_button.is_warp_active(w.player))


def _assert_parked_at(w, set_name):
    pSet = _set(set_name)
    assert w.player.GetContainingSet() is pSet
    assert App.Game_GetCurrentPlayer() is w.player, "the same ship"
    wp = pSet.GetObject("Player Start")
    p, q = w.player.GetWorldLocation(), wp.GetWorldLocation()
    assert (p.x, p.y, p.z) == pytest.approx((q.x, q.y, q.z), abs=1e-6)
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert "warp" not in w.sets_seen, "a dash never enters the warp set"
    assert "warp" not in w.entered
    assert _set("warp") is None


def _assert_draw_list_is_ona_from(set_name):
    """The celestial draw list for the viewed set is Ona's planets, in that
    set's own coordinates (tests/integration/test_sky_round_trip.py)."""
    view = frames.viewing_set()
    assert view is _set(set_name)
    m = resolve.map_of("Ona")
    ax, ay, az = resolve.anchor_of(set_name)
    expect = {(m.system, b.owner_region or "", b.name):
              (b.position_gu[0] - ax, b.position_gu[1] - ay,
               b.position_gu[2] - az)
              for b in m.bodies if b.orbits is not None}
    got = {b.key: b.position for b in celestial.draw_list(view)}
    assert len(expect) == 3, "premise: Ona's three planets"
    assert got.keys() == expect.keys()
    for k in got:
        assert got[k] == pytest.approx(expect[k])


# ── 1-2. Ona 1 -> Ona 2 -> Ona 1 by Set Course ─────────────────────────────

def test_set_course_ona1_to_ona2_and_back(world):
    w = world
    _dash_to(w, ONA2)
    _assert_parked_at(w, "Ona2")
    _assert_draw_list_is_ona_from("Ona2")

    _dash_to(w, ONA1)
    _assert_parked_at(w, "Ona1")
    _assert_draw_list_is_ona_from("Ona1")


# ── 3. Ona 1 -> Ona 3 keeps clear of the sun (Review Focus 1) ──────────────

def test_set_course_ona1_to_ona3_keeps_clear_of_the_sun(world):
    w = world
    sun = _sun()
    centre = tuple(float(c) for c in sun.position_gu)
    keep = float(sun.radius_gu) + clearance_gu(float(sun.radius_gu))
    # Premise: the straight chord runs through the sun itself, so only the
    # routing keeps the ship out.
    a = _sys(w.player)
    b = _sys(_set("Ona3").GetObject("Player Start"))
    assert _segment_distance(a, b, centre) < float(sun.radius_gu)

    _dash_to(w, ONA3)
    _assert_parked_at(w, "Ona3")

    assert len(w.samples) > 100, "the dash was sampled every tick"
    closest = min(math.dist(p, centre) for p in w.samples)
    assert closest >= keep - 1e-6, (closest, keep)


def _segment_distance(a, b, c):
    ab = [b[i] - a[i] for i in range(3)]
    t = sum((c[i] - a[i]) * ab[i] for i in range(3)) / sum(x * x for x in ab)
    t = max(0.0, min(1.0, t))
    return math.dist([a[i] + t * ab[i] for i in range(3)], c)


# ── 4. Warp on Heading at Ona 2 from Ona 1 ─────────────────────────────────

def test_warp_on_heading_at_ona2_hands_off_at_its_arrival_range(world):
    """The geometry of tests/unit/test_dash_heading.py's hand-off case: from
    Ona 1's Player Start straight at Ona 2's centre, whose region sphere the
    ray passes through (ruling R14)."""
    w = world
    centre = tuple(float(c) for c in _body("Ona 2").position_gu)
    p = _sys(w.player)
    d = [centre[i] - p[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    h = tuple(c / n for c in d)
    w.player.AlignToVectors(TGPoint3(*h), TGPoint3(0.0, 0.0, 1.0))
    w.player.SetVelocity(TGPoint3(h[0] * ENGAGED, h[1] * ENGAGED, h[2] * ENGAGED))

    warp_button.press_heading(w.button)
    assert dash.is_dashing(w.player)
    assert w.player._insystem_warp_transit.speed_policy == "heading"
    _run(w, lambda: not dash.is_dashing(w.player), bound_s=20.0)

    ona2 = _set("Ona2")
    assert w.player.GetContainingSet() is ona2, "handed off into Ona 2"
    arrival = math.dist(centre, _sys(ona2.GetObject("Player Start")))
    here = _sys(w.player)
    assert math.dist(here, centre) == pytest.approx(arrival, abs=1e-3)
    assert here == pytest.approx(
        tuple(centre[i] - h[i] * arrival for i in range(3)), abs=1e-3)
    region = resolve.map_of("Ona").region("Ona2")
    assert math.dist(here, region.anchor_gu) <= region.radius_gu
    # Headless there is no _PlayerControl to resync; the ship itself carries
    # the engaged impulse speed along the heading.
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == pytest.approx(
        (h[0] * ENGAGED, h[1] * ENGAGED, h[2] * ENGAGED), abs=1e-9)
    assert "warp" not in w.sets_seen and "warp" not in w.entered
    assert w.entered == ["Ona2"]


# ── 5. another system still tunnels ────────────────────────────────────────

def test_set_course_to_another_system_takes_the_tunnel(world):
    """The preview's Set Course menu offers only Ona, so the course is built
    directly on the button, as Helm > Set Course would for Vesuvi."""
    w = world
    dest = "Systems.Vesuvi.Vesuvi4"
    assert not dash.is_same_system_dash(w.player, dest, "", "")
    _set_course_and_warp(w, dest)
    assert not dash.is_dashing(w.player)
    _run(w, lambda: not warp_button.is_warp_active(w.player),
         bound_s=hm.WARP_BOUND_S)
    assert w.entered == ["warp", "Vesuvi4"], (
        "the tunnel passes through the warp set")
    assert w.player.GetContainingSet().GetName() == "Vesuvi4"
    assert App.Game_GetCurrentPlayer() is w.player
