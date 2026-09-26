"""The Set Course dash within one system (in-system-warp spec section 2).

A Set Course between two regions of one mapped system flies the real
system in ~10 s flash to flash instead of the tunnel, arriving at rest at
the destination placement. Regions are real (tests/helpers/mapped_regions),
the Helm menu is the SDK's own (HelmMenuHandlers.CreateMenus), and the warp
is started by BC's own ET_WARP_BUTTON_PRESSED chain (warp_button.press).
"""
import math
import sys

import pytest

import App
from engine.appc import dash, dash_helm, warp, warp_button, warp_state
from engine.appc.actions import TGAction
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import WarpEngineSubsystem
from engine.appc.windows import TacticalControlWindow
from engine.core.loop import GameLoop, TICK_DELTA
from engine.systems import handoff
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.mapped_regions import load_region

ONA2 = "Systems.Ona.Ona2"


def _helm_menu():
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    try:
        return TacticalControlWindow.GetInstance().FindMenu(db.GetString("Helm"))
    finally:
        App.g_kLocalizationManager.Unload(db)


def _entry(menu, key):
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    try:
        label = db.GetString(key)
    finally:
        App.g_kLocalizationManager.Unload(db)
    for child in menu.__dict__.get("_children", []):
        if hasattr(child, "GetLabel") and child.GetLabel() == label:
            return child
    raise AssertionError("no Helm entry %r" % key)


_ENTRIES = ("Warp", "Set Course", "Orbit Planet", "Intercept", "Dock")


class World:
    pass


@pytest.fixture
def world(monkeypatch):
    game = _fresh_world()
    # MissionLib.SetPlayerAI -> TacticalMenuHandlers.UpdateOrders reads UI
    # globals only built with the full tactical window (see
    # tests/unit/test_helm_orbit_menu.py).
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
    w.button.set_player_destination(ONA2)
    warp.set_course_placement(w.button, ONA2)

    # Every event posted, still dispatched.
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

    # The engage / drop-out flashes (Task 6 fills the hooks).
    w.flashes = []
    monkeypatch.setattr(dash, "_on_engage_fx", lambda p: w.flashes.append(
        ("engage", App.g_kUtopiaModule.GetGameTime())))
    monkeypatch.setattr(dash, "_on_drop_out_fx", lambda p: w.flashes.append(
        ("drop", App.g_kUtopiaModule.GetGameTime())))
    w.sets_seen = set()
    yield w
    App.g_kSetManager._sets.clear()
    if saved is not None:
        sys.modules["Bridge.HelmMenuHandlers"] = saved


def _tick(w, loop):
    loop.tick()
    dash.tick(w.player, TICK_DELTA)
    s = w.player.GetContainingSet()
    w.sets_seen.add(s.GetName() if s is not None else None)


def _run_until(w, pred, bound_s=40.0, loop=None):
    loop = loop or GameLoop()
    for _ in range(int(round(bound_s / TICK_DELTA))):
        if pred():
            return loop
        _tick(w, loop)
    raise AssertionError("condition not reached in %.0f s" % bound_s)


def _engaged(w):
    return any(k == "engage" for k, _ in w.flashes)


def _events_of(w, *types):
    return [(t, n) for t, n, _ in w.events if t in types]


# ── 1. Ona 1 -> Ona 2 by Set Course ─────────────────────────────────────────

def test_set_course_dash_arrives_at_the_placement_in_ten_seconds(world):
    w = world
    warp_button.press(w.button)
    assert dash.is_dashing(w.player)
    _run_until(w, lambda: not dash.is_dashing(w.player))

    assert "warp" not in w.sets_seen
    assert (App.ET_ENTERED_SET, "warp") not in _events_of(w, App.ET_ENTERED_SET)
    assert App.g_kSetManager.GetSet("warp") is None
    kinds = [k for k, _ in w.flashes]
    assert kinds == ["engage", "drop"]
    span = w.flashes[1][1] - w.flashes[0][1]
    assert abs(span - 10.0) <= TICK_DELTA + 1e-9

    assert w.player.GetContainingSet() is w.ona2
    wp = w.ona2.GetObject("Player Start")
    p, q = w.player.GetWorldLocation(), wp.GetWorldLocation()
    assert (p.x, p.y, p.z) == pytest.approx((q.x, q.y, q.z), abs=1e-6)
    R, Rw = w.player.GetWorldRotation(), wp.GetWorldRotation()
    for i in range(3):
        a, b = R.GetCol(i), Rw.GetCol(i)
        assert (a.x, a.y, a.z) == pytest.approx((b.x, b.y, b.z), abs=1e-6)
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)

    seq = _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                     App.ET_EXITED_WARP)
    assert seq == [(App.ET_EXITED_SET, "Ona1"), (App.ET_ENTERED_SET, "Ona2"),
                   (App.ET_EXITED_WARP, None)]
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_NOT_WARPING


# ── 2. state during the flight, restored after ─────────────────────────────

def test_during_the_dash_warp_state_and_helm_entries(world):
    w = world
    for key in _ENTRIES:
        _entry(w.helm, key).SetEnabled()
    warp_button.press(w.button)
    _run_until(w, lambda: _engaged(w))
    _tick(w, GameLoop())

    assert w.player.IsDoingInSystemWarp() == 1
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_WARPING
    for key in _ENTRIES:
        assert not _entry(w.helm, key).IsEnabled(), key
    assert w.helm.IsEnabled()

    _run_until(w, lambda: not dash.is_dashing(w.player))
    assert w.player.IsDoingInSystemWarp() == 0
    for key in _ENTRIES:
        assert _entry(w.helm, key).IsEnabled(), key
    assert w.helm.IsEnabled()


def test_the_helm_restores_only_what_it_disabled(world):
    w = world
    _entry(w.helm, "Warp").SetEnabled()
    _entry(w.helm, "Dock").SetDisabled()
    warp_button.press(w.button)
    _run_until(w, lambda: not dash.is_dashing(w.player))
    assert _entry(w.helm, "Warp").IsEnabled()
    assert not _entry(w.helm, "Dock").IsEnabled()


# ── 3. rule C: other systems and mission courses keep the tunnel ───────────

def test_a_course_naming_a_mission_takes_the_tunnel(world, monkeypatch):
    w = world
    from engine.core import mission_change
    changed = []
    monkeypatch.setattr(mission_change, "change",
                        lambda **k: changed.append(k))
    w.button.set_course_mission("E2M1", "")
    assert not dash.is_same_system_dash(w.player, ONA2, "E2M1", "")
    warp_button.press(w.button)
    assert not dash.is_dashing(w.player)
    _run_until(w, lambda: not warp_button.is_warp_active(w.player))
    assert (App.ET_ENTERED_SET, "warp") in _events_of(w, App.ET_ENTERED_SET)
    assert changed


def test_a_course_to_another_system_takes_the_tunnel(world):
    w = world
    dest = "Systems.Vesuvi.Vesuvi4"
    load_region("Vesuvi", "Vesuvi4")
    w.button.set_player_destination(dest)
    warp.set_course_placement(w.button, dest)
    assert not dash.is_same_system_dash(w.player, dest, "", "")
    warp_button.press(w.button)
    assert not dash.is_dashing(w.player)
    _run_until(w, lambda: not warp_button.is_warp_active(w.player))
    assert (App.ET_ENTERED_SET, "warp") in _events_of(w, App.ET_ENTERED_SET)
    assert w.player.GetContainingSet().GetName() == "Vesuvi4"


def test_the_predicate_accepts_a_same_system_course(world):
    assert dash.is_same_system_dash(world.player, ONA2, "", "")
    assert dash.is_same_system_dash(world.player, ONA2, None, None)


# ── 4. the 0 key drops out at rest where it is ─────────────────────────────

class _Keys:
    KEY_W, KEY_S, KEY_A, KEY_D, KEY_Q, KEY_E, KEY_R = 87, 83, 65, 68, 81, 69, 82
    KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5 = 48, 49, 50, 51, 52, 53
    KEY_6, KEY_7, KEY_8, KEY_9 = 54, 55, 56, 57
    KEY_LEFT_ALT, KEY_RIGHT_ALT = 342, 346
    KEY_LEFT_CONTROL, KEY_RIGHT_CONTROL = 341, 345
    KEY_LEFT_SHIFT, KEY_RIGHT_SHIFT = 340, 344


class _Reader:
    keys = _Keys()

    def __init__(self, held=(), pressed=()):
        self.held, self.pressed = set(held), set(pressed)

    def key_state(self, key):
        return key in self.held

    def key_pressed(self, key):
        return key in self.pressed


def _mid_flight(w, seconds=5.0):
    warp_button.press(w.button)
    loop = _run_until(w, lambda: _engaged(w))
    for _ in range(int(round(seconds / TICK_DELTA))):
        _tick(w, loop)
    assert w.player.IsDoingInSystemWarp() == 1
    return loop


def test_full_stop_key_drops_out_at_rest_where_it_is(world):
    from engine.host_loop import _PlayerControl
    w = world
    _mid_flight(w)
    pc = _PlayerControl()
    before = w.player.GetWorldLocation()
    w.events.clear()
    pc.apply(w.player, TICK_DELTA, _Reader(pressed={pc._input_map.code("full_stop")}))

    assert not dash.is_dashing(w.player)
    assert w.player.IsDoingInSystemWarp() == 0
    after = w.player.GetWorldLocation()
    assert (after.x, after.y, after.z) == pytest.approx(
        (before.x, before.y, before.z))
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert handoff.region_at(w.player) is None
    assert w.player.GetContainingSet() is w.ona1
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == [(App.ET_EXITED_WARP, None)]
    assert [k for k, _ in w.flashes] == ["engage", "drop"]
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_NOT_WARPING
    # And it stays at rest: the next frames do not resume the old throttle.
    for _ in range(10):
        _tick(w, GameLoop())
        pc.apply(w.player, TICK_DELTA, _Reader())
    v = w.player.GetVelocity()
    assert math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) == pytest.approx(0.0)


# ── 5. All Stop drops out, and the SDK AllStop still runs ──────────────────

def test_all_stop_drops_out_and_passes_the_event_on(world):
    import MissionLib
    w = world
    _mid_flight(w)
    w.events.clear()
    evt = App.TGIntEvent_Create()
    evt.SetEventType(App.ET_ALL_STOP)
    evt.SetDestination(w.helm)
    App.g_kEventManager.AddEvent(evt)

    assert not dash.is_dashing(w.player)
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert (App.ET_EXITED_WARP, None) in _events_of(w, App.ET_EXITED_WARP)
    # SDK HelmMenuHandlers.AllStop ran after us: Stay AI, Helm in control.
    assert w.player.GetAI() is not None
    assert MissionLib.g_sPlayerShipController == "Helm"


# ── R10: an AI order that ends the flight still runs the drop-out ──────────

def test_set_ai_mid_dash_runs_the_drop_out(world):
    w = world
    _mid_flight(w)
    w.events.clear()
    import AI.Player.Stay
    w.player.SetAI(AI.Player.Stay.CreateAI(w.player))
    assert (App.ET_IN_SYSTEM_WARP in
            [t for t, _, _ in w.events])
    _tick(w, GameLoop())
    assert not dash.is_dashing(w.player)
    assert (App.ET_EXITED_WARP, None) in _events_of(w, App.ET_EXITED_WARP)
    assert [k for k, _ in w.flashes] == ["engage", "drop"]


# ── 6. Warp pressed again mid-flight starts nothing ────────────────────────

def test_pressing_warp_again_during_the_dash_starts_nothing(world):
    w = world
    _mid_flight(w, seconds=1.0)
    flight = w.player._insystem_warp_transit
    warp_button.press(w.button)
    assert w.player._insystem_warp_transit is flight
    assert w.player.GetWarpEngineSubsystem().GetWarpSequence() is None
    assert w.helm.IsEnabled()
    assert [k for k, _ in w.flashes] == ["engage"]


# ── 7. steering and impulse keys are inert while dashing ───────────────────

def test_steering_and_impulse_keys_are_inert_during_the_dash(world):
    from engine.host_loop import _PlayerControl
    w = world
    _mid_flight(w, seconds=1.0)
    pc = _PlayerControl()
    k = _Keys
    held = {k.KEY_W, k.KEY_A, k.KEY_Q, k.KEY_S, k.KEY_D, k.KEY_E}
    for code in (k.KEY_1, k.KEY_5, k.KEY_9, k.KEY_R):
        p0 = w.player.GetWorldLocation()
        r0 = w.player.GetWorldRotation().GetCol(1)
        pc.apply(w.player, TICK_DELTA, _Reader(held=held, pressed={code}))
        p1 = w.player.GetWorldLocation()
        r1 = w.player.GetWorldRotation().GetCol(1)
        assert (p1.x, p1.y, p1.z) == (p0.x, p0.y, p0.z)
        assert (r1.x, r1.y, r1.z) == (r0.x, r0.y, r0.z)
        assert pc.impulse_level == 0
        assert dash.is_dashing(w.player)
        _tick(w, GameLoop())


# ── 8. the button's queues play at their points ────────────────────────────

class _Mark(TGAction):
    def __init__(self, w, tag):
        super().__init__()
        self._w, self._tag = w, tag

    def _do_play(self):
        w = self._w
        w.played.append((self._tag, App.g_kUtopiaModule.GetGameTime(),
                         w.player.IsDoingInSystemWarp(),
                         dash.is_dashing(w.player)))


def test_queued_actions_play_at_engage_in_flight_and_after(world):
    w = world
    w.played = []
    b = w.button
    b.AddActionBeforeWarp(_Mark(w, "before"))
    b.AddActionBeforeDuringWarp(_Mark(w, "before_during"))
    b.AddActionDuringWarp(_Mark(w, "during"))
    b.AddActionAfterDuringWarp(_Mark(w, "after_during"))
    b.AddActionAfterWarp(_Mark(w, "after"))
    warp_button.press(b)
    assert w.played == []                     # nothing during the align
    _run_until(w, lambda: not dash.is_dashing(w.player))

    tags = [t for t, *_ in w.played]
    assert tags == ["before", "before_during", "during", "after_during",
                    "after"]
    engage_t = w.flashes[0][1]
    drop_t = w.flashes[1][1]
    by = {t: (gt, flying, dashing) for t, gt, flying, dashing in w.played}
    assert by["before"][0] == pytest.approx(engage_t)
    for t in ("before_during", "during", "after_during"):
        assert engage_t - 1e-9 <= by[t][0] < drop_t
        assert by[t][2]                        # still dashing
    assert by["after"][0] >= drop_t - 1e-9
    assert not by["after"][2]


# ── fix round 1 ─────────────────────────────────────────────────────────────

def _queue_all(w):
    w.played = []
    marks = {k: _Mark(w, k) for k in ("before", "before_during", "during",
                                      "after_during", "after")}
    b = w.button
    b.AddActionBeforeWarp(marks["before"])
    b.AddActionBeforeDuringWarp(marks["before_during"])
    b.AddActionDuringWarp(marks["during"])
    b.AddActionAfterDuringWarp(marks["after_during"])
    b.AddActionAfterWarp(marks["after"], 1.5)
    return marks


def _assert_queues_back(w, marks):
    back = w.button.take_queues()
    assert {k: [a for a, _ in v] for k, v in back.items()} == {
        k: [m] for k, m in marks.items()}
    assert back["after"][0][1] == 1.5
    assert w.played == []


def test_full_stop_during_the_align_puts_the_queues_back(world):
    from engine.host_loop import _PlayerControl
    w = world
    marks = _queue_all(w)
    warp_button.press(w.button)
    assert dash.is_dashing(w.player) and not _engaged(w)
    pc = _PlayerControl()
    pc.apply(w.player, TICK_DELTA,
             _Reader(pressed={pc._input_map.code("full_stop")}))
    assert not dash.is_dashing(w.player)
    for _ in range(30):
        _tick(w, GameLoop())
    _assert_queues_back(w, marks)
    assert w.flashes == []


def test_a_player_killed_during_the_align_stops_dashing(world):
    w = world
    marks = _queue_all(w)
    warp_button.press(w.button)
    w.player.SetDead()
    _tick(w, GameLoop())
    assert not dash.is_dashing(w.player)
    for _ in range(int(round(15.0 / TICK_DELTA))):
        _tick(w, GameLoop())
    assert w.flashes == []
    assert w.player.IsDoingInSystemWarp() == 0
    _assert_queues_back(w, marks)


def test_a_player_killed_in_flight_ends_it_with_no_hand_off(world):
    w = world
    _mid_flight(w)
    w.events.clear()
    w.player.SetDead()
    _tick(w, GameLoop())
    assert not dash.is_dashing(w.player)
    assert w.player.IsDoingInSystemWarp() == 0
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == []
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_NOT_WARPING


def test_the_dash_clears_targets_and_stands_the_ai_down_like_the_tunnel(world):
    """Ruling R12: _ClearTargetsAction's semantics."""
    import AI.Player.Stay
    w = world
    enemy = ShipClass_Create("Galaxy")
    w.ona1.AddObjectToSet(enemy, "enemy")
    w.player.SetTarget(enemy)
    w.player.SetAI(AI.Player.Stay.CreateAI(w.player))
    assert w.player.GetTarget() is enemy
    warp_button.press(w.button)
    assert dash.is_dashing(w.player)
    assert w.player.GetTarget() is None
    assert w.player.GetAI() is None


def test_helm_sync_reads_the_tgl_once_per_helm_menu(world, monkeypatch):
    calls = []
    real = dash_helm._labels
    monkeypatch.setattr(dash_helm, "_labels",
                        lambda: (calls.append(1), real())[1])
    monkeypatch.setattr(dash_helm, "_cache", None)
    for _ in range(5):
        dash_helm.sync(world.player)
    assert len(calls) == 1


def test_the_headless_warp_wait_completes_a_dash(world):
    from tests.helpers import headless_mission as hm
    w = world
    took = hm.warp_and_wait(w.button, w.player)
    assert 10.0 < took < 30.0
    assert not dash.is_dashing(w.player)
    assert w.player.GetContainingSet() is w.ona2
