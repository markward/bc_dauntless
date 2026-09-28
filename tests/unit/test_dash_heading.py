"""Warp on Heading (in-system-warp spec section 2).

A Helm entry beside Warp that sends BC's own ET_WARP_BUTTON_PRESSED through
the button's chain with no course on the button, then dashes along the nose at
HEADING_DASH_GUPS until a body ahead drops it out (at the owning region's
arrival range, else one radius above the surface), or 0 / All Stop drops it
out at rest. Regions are real (tests/helpers/mapped_regions) and the Helm menu
is the SDK's own (HelmMenuHandlers.CreateMenus).
"""
import math
import sys
import types

import pytest

import App
from engine.appc import dash, dash_helm, warp, warp_button, warp_gates
from engine.appc import warp_state
from engine.appc.actions import TGAction
from engine.appc.math import TGPoint3
from engine.appc.sets import SetClass_Create
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import WarpEngineSubsystem
from engine.appc.windows import TacticalControlWindow
from engine.core.loop import GameLoop, TICK_DELTA
from engine.systems import frames, resolve
from engine.systems.warp_path import HEADING_DASH_GUPS
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.mapped_regions import load_region

ONA2 = "Systems.Ona.Ona2"
ENGAGED = 4.5          # GU/s, the impulse speed the dash is engaged at


def _helm_menu():
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    try:
        return TacticalControlWindow.GetInstance().FindMenu(db.GetString("Helm"))
    finally:
        App.g_kLocalizationManager.Unload(db)


def _heading_entry(menu):
    for child in menu.__dict__.get("_children", []):
        if (hasattr(child, "GetLabel")
                and child.GetLabel() == dash_helm.WARP_ON_HEADING_LABEL):
            return child
    return None


class _Handle:
    """A playing-sound handle: records its Stop()."""

    def __init__(self):
        self.stopped = False

    def Stop(self):
        self.stopped = True


class World:
    pass


@pytest.fixture
def world(monkeypatch):
    game = _fresh_world()
    import Bridge.TacticalMenuHandlers as T
    monkeypatch.setattr(T, "UpdateOrders", lambda *a, **k: None)
    saved = sys.modules.pop("Bridge.HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as H
    H.CreateMenus()

    w = World()
    w.ona1 = load_region("Ona", "Ona1")
    w.ona2 = load_region("Ona", "Ona2")
    w.player = ShipClass_Create("Galaxy")
    w.ona1.AddObjectToSet(w.player, "player")
    w.player.PlaceObjectByName("Player Start")
    game.SetPlayer(w.player)
    w.helm = _helm_menu()
    w.button = App.SortedRegionMenu_GetWarpButton()
    dash_helm.sync(w.player)
    w.entry = _heading_entry(w.helm)

    w.events = []
    orig = App.g_kEventManager.AddEvent

    def _add(evt):
        name = None
        if evt.GetEventType() == App.ET_EXITED_SET:
            name = evt.GetCString()
        if evt.GetEventType() == App.ET_ENTERED_SET:
            s = evt.GetDestination().GetContainingSet()
            name = s.GetName() if s is not None else None
        w.events.append((evt.GetEventType(), name, evt))
        orig(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", _add)

    w.flashes = []
    monkeypatch.setattr(dash, "_on_engage_fx", lambda p: w.flashes.append(
        ("engage", App.g_kUtopiaModule.GetGameTime())))
    monkeypatch.setattr(dash, "_on_drop_out_fx", lambda p: w.flashes.append(
        ("drop", App.g_kUtopiaModule.GetGameTime())))
    # Every ship-attached warp sound: (name, ship, game time, handle).
    w.sounds = []

    def _play(name, ship):
        h = _Handle()
        w.sounds.append((name, ship, App.g_kUtopiaModule.GetGameTime(), h))
        return h
    monkeypatch.setattr(warp, "_play_attached", _play)
    yield w
    for n in ("_t_heading",):
        sys.modules.pop(n, None)
    App.g_kSetManager._sets.clear()
    if saved is not None:
        sys.modules["Bridge.HelmMenuHandlers"] = saved


def _tick(w, loop):
    loop.tick()
    dash.tick(w.player, TICK_DELTA)


def _run_until(w, pred, bound_s=40.0):
    loop = GameLoop()
    for _ in range(int(round(bound_s / TICK_DELTA))):
        if pred():
            return loop
        _tick(w, loop)
    raise AssertionError("condition not reached in %.0f s" % bound_s)


def _until_engaged(w):
    """Through the "Enter Warp" pre-roll (warp._SFX_ENTER_FLASH_AT) to the
    engage."""
    return _run_until(w, lambda: bool(w.flashes), bound_s=5.0)


def _sys(obj):
    return tuple(frames.system_position(obj)[1:])


def _body(name):
    m = resolve.map_of("Ona")
    return next(b for b in m.bodies if b.name == name)


def _aim(w, point):
    """Nose at a system-coordinate point, moving at ENGAGED along it."""
    p = _sys(w.player)
    d = [point[i] - p[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    h = tuple(c / n for c in d)
    w.player.AlignToVectors(TGPoint3(*h), TGPoint3(0.0, 0.0, 1.0))
    w.player.SetVelocity(TGPoint3(h[0] * ENGAGED, h[1] * ENGAGED,
                                  h[2] * ENGAGED))
    return h


def _press(w):
    """Click the Helm entry: its activation event, as the crew menu does."""
    w.entry.SendActivationEvent()


def _events_of(w, *types_):
    return [(t, n) for t, n, _ in w.events if t in types_]


# ── 1. the Helm entry ───────────────────────────────────────────────────────

def test_the_helm_gains_warp_on_heading_right_after_warp(world):
    w = world
    kids = w.helm.__dict__["_children"]
    assert w.entry is not None
    assert kids.index(w.entry) == kids.index(w.button) + 1
    assert w.entry.IsEnabled()
    dash_helm.sync(w.player)                 # once per Helm menu
    assert [k for k in kids if k is w.entry] == [w.entry]
    assert len([k for k in kids if getattr(k, "GetLabel", lambda: None)()
                == dash_helm.WARP_ON_HEADING_LABEL]) == 1


def _move_player_to_unmapped(w, name="QuickBattleRegion"):
    """QuickBattle's setup region is an unmapped placeholder set: its own
    one-set frame, no system map."""
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, name)
    w.ona1.RemoveObjectFromSet("player")
    other.AddObjectToSet(w.player, "player")
    w.player.SetTranslateXYZ(0.0, 0.0, 0.0)
    w.player.UpdateNodeOnly()
    return other


def test_warp_on_heading_is_enabled_in_an_unmapped_set(world):
    """Features are consistent everywhere (Mark, 2026-09-27): Warp on
    Heading is offered in any space set, mapped or not."""
    w = world
    other = _move_player_to_unmapped(w)
    dash_helm.sync(w.player)
    assert w.entry.IsEnabled()
    other.RemoveObjectFromSet("player")
    w.ona1.AddObjectToSet(w.player, "player")
    dash_helm.sync(w.player)
    assert w.entry.IsEnabled()


def test_a_heading_dash_in_an_unmapped_set_drops_out_at_a_planet(world):
    """The dash flies an unmapped set on its own Planet/Sun objects: no
    regions, so no hand-off -- it drops out at 2*radius from the planet and
    posts ET_EXITED_WARP, staying in the set."""
    from engine.appc.planet import Planet_Create
    w = world
    other = _move_player_to_unmapped(w)
    planet = Planet_Create(170.0, "")
    other.AddObjectToSet(planet, "Planet")
    planet.SetTranslateXYZ(0.0, 60000.0, 0.0)
    planet.UpdateNodeOnly()
    dash_helm.sync(w.player)
    h = _aim(w, (0.0, 60000.0, 0.0))
    w.events.clear()
    _press(w)
    assert dash.is_dashing(w.player)
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=30.0)
    p = _sys(w.player)
    assert math.dist(p, (0.0, 60000.0, 0.0)) == pytest.approx(
        2.0 * 170.0, abs=1e-3)
    assert w.player.GetContainingSet() is other
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == [(App.ET_EXITED_WARP, None)]
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == pytest.approx(
        (h[0] * ENGAGED, h[1] * ENGAGED, h[2] * ENGAGED), abs=1e-9)


def _set_course_entry(w):
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    try:
        label = str(db.GetString("Set Course"))
    finally:
        App.g_kLocalizationManager.Unload(db)
    return next(c for c in w.helm.__dict__["_children"]
                if hasattr(c, "GetLabel") and c.GetLabel() == label)


def test_warp_on_heading_is_greyed_while_a_mission_bars_set_course(world):
    """Ruling R15: a mission holds the player by disabling Helm > Set Course
    (E3M1:286 exactly as here; E1M1 through BridgeUtils.DisableButton,
    which needs a Helm character); "no course is available" bars a heading
    dash too."""
    import MissionLib
    w = world
    MissionLib.GetCharacterSubmenu("Helm", "Set Course").SetDisabled()
    assert not _set_course_entry(w).IsEnabled(), "premise: the SDK call"
    dash_helm.sync(w.player)
    assert not w.entry.IsEnabled()
    _set_course_entry(w).SetEnabled()
    dash_helm.sync(w.player)
    assert w.entry.IsEnabled()


def test_a_dash_leaves_warp_on_heading_enabled_after_its_drop_out(world):
    """The dash itself disables Set Course while it runs; that must not
    read as a mission's bar once it drops out."""
    w = world
    p0 = _sys(w.player)
    _aim(w, (p0[0], p0[1], p0[2] - 1.0e6))
    _press(w)
    _tick(w, GameLoop())
    assert not _set_course_entry(w).IsEnabled()
    dash.drop_out(w.player, "stopped")
    assert _set_course_entry(w).IsEnabled()
    assert w.entry.IsEnabled()


# ── 2. a heading dash at Ona 2 drops out at its arrival range ──────────────

def test_a_heading_dash_at_ona2_drops_out_at_its_arrival_range(world):
    w = world
    centre = tuple(_body("Ona 2").position_gu)
    h = _aim(w, centre)
    _press(w)
    assert dash.is_dashing(w.player)
    _until_engaged(w)
    assert w.player._insystem_warp_transit.speed_policy == "heading"
    w.events.clear()
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=20.0)

    standoff = math.dist(centre, _sys(w.ona2.GetObject("Player Start")))
    p = _sys(w.player)
    assert math.dist(p, centre) == pytest.approx(standoff, abs=1e-3)
    expect = tuple(centre[i] - h[i] * standoff for i in range(3))
    assert p == pytest.approx(expect, abs=1e-3)
    region = resolve.map_of("Ona").region("Ona2")
    assert math.dist(p, region.anchor_gu) <= region.radius_gu
    assert w.player.GetContainingSet() is w.ona2
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == [
        (App.ET_EXITED_SET, "Ona1"), (App.ET_ENTERED_SET, "Ona2"),
        (App.ET_EXITED_WARP, None)]
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == pytest.approx(
        (h[0] * ENGAGED, h[1] * ENGAGED, h[2] * ENGAGED), abs=1e-9)
    assert [k for k, _ in w.flashes] == ["engage", "drop"]
    # ~10,000 GU/s: 100,000-odd GU in ~10 s.
    span = w.flashes[1][1] - w.flashes[0][1]
    assert span == pytest.approx(
        (math.dist(centre, _sys(w.ona1.GetObject("Player Start"))) - standoff)
        / HEADING_DASH_GUPS, abs=2 * TICK_DELTA)
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_NOT_WARPING


def test_a_reversing_ship_drops_out_still_reversing(world):
    """The engaged impulse speed is SIGNED (the forward component, as
    _PlayerControl keeps it): a ship backing at 2 GU/s when it engages drops
    out backing at 2 GU/s along the heading."""
    w = world
    h = _aim(w, tuple(_body("Ona 2").position_gu))
    w.player.SetVelocity(TGPoint3(-2.0 * h[0], -2.0 * h[1], -2.0 * h[2]))
    _press(w)
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=20.0)
    assert w.player.GetContainingSet() is w.ona2
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == pytest.approx(
        (-2.0 * h[0], -2.0 * h[1], -2.0 * h[2]), abs=1e-9)


def test_xi_entrades_4_from_xi_entrades_1_drops_at_its_arrival_range(world):
    """Mark 2026-09-28 (R14 retired). XiEntrades4's sphere is centred near
    its Player Start (~29,000 GU from the body), so from Xi Entrades 1 -- the
    far side -- the arrival range lands outside the sphere. The dash still
    stops at the plain arrival range, dead centre, and IS handed off: the
    region contains every point within reach of the body it owns."""
    from engine.systems import handoff
    w = world
    xe1 = load_region("XiEntrades", "XiEntrades1")
    xe4 = load_region("XiEntrades", "XiEntrades4")
    w.ona1.RemoveObjectFromSet("player")
    xe1.AddObjectToSet(w.player, "player")
    w.player.PlaceObjectByName("Player Start")
    dash_helm.sync(w.player)
    m = resolve.map_of("XiEntrades")
    body = next(b for b in m.bodies if b.name == "Xi Entrades 4")
    region = m.region("XiEntrades4")
    centre = tuple(body.position_gu)
    arrival = math.dist(centre, _sys(xe4.GetObject("Player Start")))
    assert handoff.arrival_range(body) == pytest.approx(arrival)
    h = _aim(w, centre)
    _press(w)
    w.events.clear()
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=60.0)
    p = _sys(w.player)
    assert p == pytest.approx(
        tuple(centre[i] - h[i] * arrival for i in range(3)), abs=1e-3)
    assert math.dist(p, region.anchor_gu) > region.radius_gu   # off-sphere
    assert w.player.GetContainingSet() is xe4
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == [
        (App.ET_EXITED_SET, "XiEntrades1"), (App.ET_ENTERED_SET, "XiEntrades4"),
        (App.ET_EXITED_WARP, None)]


def test_xi_entrades_4_from_its_anchor_side_keeps_the_far_arrival_range(world):
    """Fix round 1's case, kept: approached from its anchor's side, Xi
    Entrades 4's arrival range (more than the 20,000 GU lookahead above its
    surface) is inside the sphere, so the dash stops exactly there."""
    w = world
    xe1 = load_region("XiEntrades", "XiEntrades1")
    xe4 = load_region("XiEntrades", "XiEntrades4")
    w.ona1.RemoveObjectFromSet("player")
    xe1.AddObjectToSet(w.player, "player")
    m = resolve.map_of("XiEntrades")
    body = next(b for b in m.bodies if b.name == "Xi Entrades 4")
    region = m.region("XiEntrades4")
    centre = tuple(body.position_gu)
    a = [region.anchor_gu[i] - centre[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in a))
    start = tuple(centre[i] + 90000.0 * a[i] / n for i in range(3))
    o1 = resolve.anchor_of("XiEntrades1")
    w.player.SetTranslateXYZ(*(start[i] - o1[i] for i in range(3)))
    dash_helm.sync(w.player)
    arrival = math.dist(centre, _sys(xe4.GetObject("Player Start")))
    assert arrival - body.radius_gu > 20000.0
    h = _aim(w, centre)
    _press(w)
    w.events.clear()
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=20.0)
    p = _sys(w.player)
    assert p == pytest.approx(
        tuple(centre[i] - h[i] * arrival for i in range(3)), abs=1e-3)
    assert w.player.GetContainingSet() is xe4


def _start_beyond_ona2(w, angle_deg):
    """Put the player (still in Ona1's set) 60,000 GU from Ona 2's centre, in
    the direction ``angle_deg`` away from Ona2's anchor, and aim at the
    centre. Returns (centre, heading)."""
    from engine.systems import resolve as _r
    centre = tuple(_body("Ona 2").position_gu)
    anchor = _r.map_of("Ona").region("Ona2").anchor_gu
    a = [anchor[i] - centre[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in a))
    a = [c / n for c in a]
    e = [-a[1], a[0], 0.0]                    # perpendicular, in the xy plane
    n = math.sqrt(sum(c * c for c in e))
    e = [c / n for c in e]
    th = math.radians(angle_deg)
    u = [math.cos(th) * a[i] + math.sin(th) * e[i] for i in range(3)]
    start = tuple(centre[i] + 60000.0 * u[i] for i in range(3))
    o1 = _r.anchor_of("Ona1")
    w.player.SetTranslateXYZ(*(start[i] - o1[i] for i in range(3)))
    return centre, _aim(w, centre)


@pytest.mark.parametrize("angle_deg", [133.0, 180.0])
def test_ona2_from_the_far_side_drops_at_its_arrival_range_and_hands_off(
        world, angle_deg):
    """Mark 2026-09-28 (R14 retired): from the side away from Ona2's anchor
    the arrival range (4,058 GU) lands outside the sphere, yet the dash stops
    exactly there and IS handed off -- within reach of Ona 2 is inside its
    region."""
    w = world
    centre, h = _start_beyond_ona2(w, angle_deg)
    region = resolve.map_of("Ona").region("Ona2")
    arrival = math.dist(centre, _sys(w.ona2.GetObject("Player Start")))
    at_arrival = tuple(centre[i] - h[i] * arrival for i in range(3))
    assert math.dist(at_arrival, region.anchor_gu) > region.radius_gu
    _press(w)
    w.events.clear()
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=20.0)
    p = _sys(w.player)
    assert p == pytest.approx(at_arrival, abs=1e-3)
    assert w.player.GetContainingSet() is w.ona2
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == [
        (App.ET_EXITED_SET, "Ona1"), (App.ET_ENTERED_SET, "Ona2"),
        (App.ET_EXITED_WARP, None)]


# ── 3. a heading dash at the sun stops one radius above it ─────────────────

def test_a_heading_dash_at_the_sun_stops_one_radius_above_it(world):
    w = world
    sun = _body("Ona")
    h = _aim(w, tuple(sun.position_gu))
    _press(w)
    w.events.clear()
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=30.0)
    p = _sys(w.player)
    assert math.dist(p, sun.position_gu) == pytest.approx(
        2.0 * sun.radius_gu, abs=1e-3)
    assert w.player.GetContainingSet() is w.ona1
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == [(App.ET_EXITED_WARP, None)]
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == pytest.approx(
        (h[0] * ENGAGED, h[1] * ENGAGED, h[2] * ENGAGED), abs=1e-9)


def test_a_heading_dash_at_the_planet_it_starts_beside_stops_at_clearance(
        world):
    """Ruling R9: from Ona 1's own Player Start (inside its arrival range),
    a dash at Ona 1 ends at radius + clearance from its centre -- not on its
    first tick, and never through the planet."""
    from engine.systems.warp_path import clearance_gu
    w = world
    ona1 = _body("Ona 1")
    centre = tuple(ona1.position_gu)
    assert math.dist(_sys(w.player), centre) <= math.dist(
        centre, _sys(w.ona1.GetObject("Player Start"))) + 1e-6
    _aim(w, centre)
    _press(w)
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=5.0)
    assert math.dist(_sys(w.player), centre) == pytest.approx(
        ona1.radius_gu + clearance_gu(ona1.radius_gu), abs=1e-3)
    assert w.player.GetContainingSet() is w.ona1


# ── 4. Review Focus 2: open space, then 0 ──────────────────────────────────

class _Keys:
    KEY_W, KEY_S, KEY_A, KEY_D, KEY_Q, KEY_E, KEY_R = 87, 83, 65, 68, 81, 69, 82
    KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5 = 48, 49, 50, 51, 52, 53
    KEY_6, KEY_7, KEY_8, KEY_9 = 54, 55, 56, 57
    KEY_LEFT_ALT, KEY_RIGHT_ALT = 342, 346
    KEY_LEFT_CONTROL, KEY_RIGHT_CONTROL = 341, 345
    KEY_LEFT_SHIFT, KEY_RIGHT_SHIFT = 340, 344


class _Reader:
    keys = _Keys()

    def __init__(self, pressed=()):
        self.pressed = set(pressed)

    def key_state(self, key):
        return False

    def key_pressed(self, key):
        return key in self.pressed


def test_a_heading_dash_into_open_space_runs_and_stops_at_rest_on_0(world):
    from engine.host_loop import _PlayerControl
    w = world
    p0 = _sys(w.player)
    _aim(w, (p0[0], p0[1], p0[2] - 1.0e6))        # straight down: no bodies
    _press(w)
    loop = _until_engaged(w)
    p0 = _sys(w.player)
    for _ in range(int(round(30.0 / TICK_DELTA))):
        _tick(w, loop)
    assert dash.is_dashing(w.player)
    assert w.player.GetContainingSet() is w.ona1
    assert p0[2] - _sys(w.player)[2] == pytest.approx(
        30.0 * HEADING_DASH_GUPS, rel=0.01)
    w.events.clear()
    pc = _PlayerControl()
    pc.apply(w.player, TICK_DELTA,
             _Reader(pressed={pc._input_map.code("full_stop")}))
    assert not dash.is_dashing(w.player)
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert w.player.GetContainingSet() is w.ona1
    assert _events_of(w, App.ET_EXITED_WARP) == [(App.ET_EXITED_WARP, None)]


# ── 5. the chain runs with no destination; the course is restored ──────────

class _Mark(TGAction):
    def __init__(self, w, tag):
        super().__init__()
        self._w, self._tag = w, tag

    def _do_play(self):
        self._w.played.append((self._tag, dash.is_dashing(self._w.player)))


def test_the_chain_sees_no_destination_and_the_course_is_restored(world):
    w = world
    b = w.button
    b.set_player_destination(ONA2)
    warp.set_course_placement(b, ONA2)
    b.set_course_mission("E2M1", "Episode2")
    b.SetPlacementName("PlayerSpecialStart")
    placement = b.GetPlacementName()
    seen = []
    w.played = []

    def H(o, e):
        seen.append((o.GetDestination(), o.get_mission_name(),
                     o.get_episode_name(), o.GetPlacementName()))
        # Anything a handler sets on the button is ignored by the dash...
        o.SetDestination("Systems.Vesuvi.Vesuvi4", "E3M2", "Somewhere")
        # ...but its queued actions play at the dash's points.
        o.AddActionBeforeWarp(_Mark(w, "before"))
        o.AddActionAfterWarp(_Mark(w, "after"))
        o.CallNextHandler(e)
    m = types.ModuleType("_t_heading")
    m.H = H
    sys.modules["_t_heading"] = m
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED,
                                      "_t_heading.H")
    _aim(w, tuple(_body("Ona 2").position_gu))
    _press(w)

    assert placement != "Player Start"
    assert seen == [(None, "", "", "Player Start")]
    assert b.GetDestination() == ONA2
    assert b.get_mission_name() == "E2M1"
    assert b.get_episode_name() == "Episode2"
    assert b.GetPlacementName() == placement
    assert dash.is_dashing(w.player)
    assert w.played == []                    # "before" plays at the engage
    _until_engaged(w)
    assert w.player._insystem_warp_transit.speed_policy == "heading"
    assert App.g_kSetManager.GetSet("warp") is None
    assert w.played == [("before", True)]
    _run_until(w, lambda: not dash.is_dashing(w.player), bound_s=20.0)
    assert w.played == [("before", True), ("after", False)]


# ── 6. rule D: a swallowing handler, or the gate, refuses it ───────────────

def test_a_swallowing_handler_stops_a_heading_dash(world):
    w = world
    m = types.ModuleType("_t_heading")
    m.H = lambda o, e: None
    sys.modules["_t_heading"] = m
    w.button.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED,
                                             "_t_heading.H")
    _press(w)
    assert not dash.is_dashing(w.player)
    assert w.flashes == []


def test_a_gate_refusal_stops_a_heading_dash_with_the_deny_line(
        world, monkeypatch):
    w = world
    monkeypatch.setattr(warp_gates, "_warp_disabled", lambda s: True)
    spoken = []
    monkeypatch.setattr(warp_gates, "speak_deny",
                        lambda ship, key: spoken.append(key))
    _press(w)
    assert not dash.is_dashing(w.player)
    assert w.player.IsDoingInSystemWarp() == 0
    assert spoken == ["CantWarp1"]
    assert w.flashes == []


# ── 7. Review Focus 3: Warp on Heading during a dash does nothing ──────────

def test_warp_on_heading_during_a_dash_does_nothing(world):
    w = world
    _aim(w, tuple(_body("Ona 2").position_gu))
    _press(w)
    _until_engaged(w)
    flight = w.player._insystem_warp_transit
    assert not w.entry.IsEnabled()           # greyed while dashing
    warp_button.press_heading(w.button)
    assert w.player._insystem_warp_transit is flight
    assert [k for k, _ in w.flashes] == ["engage"]
    assert w.helm.IsEnabled()


# ── 8. a player swap mid-dash ends the old ship's heading dash ─────────────

def test_a_player_swap_ends_the_old_ships_heading_dash_at_rest(world):
    """A heading flight never ends on its own in open space: without the
    identity sync ending it, the old ship would fly on forever."""
    from engine import host_loop as hl
    w = world
    p0 = _sys(w.player)
    _aim(w, (p0[0], p0[1], p0[2] - 1.0e6))        # straight down: no bodies
    _press(w)
    loop = GameLoop()
    for _ in range(int(round(2.0 / TICK_DELTA))):
        _tick(w, loop)
    assert dash.is_dashing(w.player)
    new = ShipClass_Create("Galaxy")
    w.ona1.AddObjectToSet(new, "new player")
    App.Game_GetCurrentGame().SetPlayer(new)
    sess = hl.MissionSession(mission_name="t")
    sess.player = w.player
    w.events.clear()
    hl._sync_player_identity(sess, lambda p: None)
    assert not dash.is_dashing(w.player)
    assert w.player.IsDoingInSystemWarp() == 0
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_NOT_WARPING
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert _events_of(w, App.ET_EXITED_WARP) == []


# ── 9. the hold for articulated parts: cruise at impulse, then engage ──────

def _parts(monkeypatch, seconds):
    from engine.appc import articulation
    monkeypatch.setattr(articulation, "time_to_reach",
                        lambda ship, state: seconds if state == "warp" else 0.0)


def _open_space(w):
    p0 = _sys(w.player)
    return _aim(w, (p0[0], p0[1], p0[2] - 1.0e6))  # straight down: no bodies


def test_a_heading_dash_with_parts_cruises_then_engages(world, monkeypatch):
    w = world
    _parts(monkeypatch, 3.0)
    h = _open_space(w)
    p0 = _sys(w.player)
    t0 = App.g_kUtopiaModule.GetGameTime()
    _press(w)
    assert dash.is_dashing(w.player)
    assert w.flashes == []
    assert w.player.IsDoingInSystemWarp() == 0
    assert warp_state.get_state(w.player) == \
        WarpEngineSubsystem.WES_WARP_INITIATED
    loop = GameLoop()
    while not w.flashes:
        _tick(w, loop)
        assert App.g_kUtopiaModule.GetGameTime() - t0 < 10.0
        if not w.flashes:
            assert warp_state.get_state(w.player) == \
                WarpEngineSubsystem.WES_WARP_INITIATED
            v = w.player.GetVelocity()
            assert (v.x, v.y, v.z) == pytest.approx(
                tuple(c * ENGAGED for c in h), abs=1e-9)
    t_engage = w.flashes[0][1] - t0
    assert 3.0 + TICK_DELTA - 1e-9 <= t_engage <= 3.0 + 2 * TICK_DELTA + 1e-9
    # Cruised at the impulse speed along the nose, not at warp.
    flown = math.dist(p0, _sys(w.player))
    assert flown == pytest.approx(ENGAGED * t_engage, rel=0.02)
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_WARPING
    assert w.player.IsDoingInSystemWarp() == 1


def test_0_during_the_heading_hold_cancels_at_rest(world, monkeypatch):
    from engine.host_loop import _PlayerControl
    w = world
    _parts(monkeypatch, 3.0)
    _open_space(w)
    _press(w)
    loop = GameLoop()
    for _ in range(int(round(1.0 / TICK_DELTA))):
        _tick(w, loop)
    w.events.clear()
    pc = _PlayerControl()
    pc.apply(w.player, TICK_DELTA,
             _Reader(pressed={pc._input_map.code("full_stop")}))
    assert not dash.is_dashing(w.player)
    assert warp_state.get_state(w.player) == \
        WarpEngineSubsystem.WES_NOT_WARPING
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    for _ in range(int(round(5.0 / TICK_DELTA))):
        _tick(w, loop)
    assert w.flashes == []
    assert w.player.IsDoingInSystemWarp() == 0
    assert _events_of(w, App.ET_EXITED_WARP, App.ET_IN_SYSTEM_WARP) == []
    assert w.entry.IsEnabled()


# ── 10. "Enter Warp" leads the engage by its crack ────────────────────────

PREROLL = warp._SFX_ENTER_FLASH_AT


def _enter_sounds(w):
    return [s for s in w.sounds if s[0] == "Enter Warp"]


def test_a_heading_dash_cruises_through_the_preroll_then_engages(
        world, monkeypatch):
    """No parts: "Enter Warp" on the player at the press; the ship cruises on
    at its impulse speed (no early warp state) and engages PREROLL s later."""
    w = world
    _parts(monkeypatch, 0.0)
    h = _open_space(w)
    p0 = _sys(w.player)
    t0 = App.g_kUtopiaModule.GetGameTime()
    _press(w)
    [(_, ship, t_sound, handle)] = _enter_sounds(w)
    assert ship is w.player and t_sound == t0
    assert w.flashes == []
    loop = GameLoop()
    while not w.flashes:
        assert warp_state.get_state(w.player) == \
            WarpEngineSubsystem.WES_NOT_WARPING
        _tick(w, loop)
        assert App.g_kUtopiaModule.GetGameTime() - t0 < 5.0
        if not w.flashes:
            v = w.player.GetVelocity()
            assert (v.x, v.y, v.z) == pytest.approx(
                tuple(c * ENGAGED for c in h), abs=1e-9)
    t_engage = w.flashes[0][1] - t0
    assert abs(t_engage - PREROLL) <= TICK_DELTA + 1e-9
    assert math.dist(p0, _sys(w.player)) == pytest.approx(
        ENGAGED * t_engage, rel=0.02)
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_WARPING
    assert not handle.stopped


def test_a_heading_parts_hold_leads_the_engage_by_the_preroll(
        world, monkeypatch):
    w = world
    _parts(monkeypatch, 3.0)
    _open_space(w)
    _press(w)
    assert _enter_sounds(w) == []
    loop = GameLoop()
    for _ in range(int(round(10.0 / TICK_DELTA))):
        if w.flashes:
            break
        _tick(w, loop)
    [(_, ship, t_sound, _)] = _enter_sounds(w)
    assert ship is w.player
    assert abs(w.flashes[0][1] - t_sound - PREROLL) <= TICK_DELTA + 1e-9


def test_0_during_the_heading_preroll_stops_enter_warp(world, monkeypatch):
    from engine.host_loop import _PlayerControl
    w = world
    _parts(monkeypatch, 0.0)
    _open_space(w)
    _press(w)
    loop = GameLoop()
    for _ in range(int(round(0.5 / TICK_DELTA))):
        _tick(w, loop)
    pc = _PlayerControl()
    pc.apply(w.player, TICK_DELTA,
             _Reader(pressed={pc._input_map.code("full_stop")}))
    assert not dash.is_dashing(w.player)
    [(_, _, _, handle)] = _enter_sounds(w)
    assert handle.stopped
    for _ in range(int(round(3.0 / TICK_DELTA))):
        _tick(w, loop)
    assert w.flashes == []
