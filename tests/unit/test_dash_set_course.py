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
# The real flash/sound hooks, captured before the fixture stubs them.
_REAL_ENGAGE_FX = dash._on_engage_fx
_REAL_DROP_OUT_FX = dash._on_drop_out_fx


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
    # The placement's rotation is reached by the arrival turn, after the
    # drop-out (Mark, 2026-09-27), not snapped at it.
    _run_until(w, lambda: not dash.is_arrival_turning(w.player))
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


def test_a_player_killed_in_flight_leaves_no_dash_smear_or_glow(
        world, monkeypatch):
    """A cancelled dash never drops out, so _on_drop_out_fx never ramps the
    dash VFX down: the cancel itself must, or the dust cap and nacelle glow
    stay at the dash's full intensity for good."""
    from engine import dash_vfx
    w = world
    stub_engage = dash._on_engage_fx

    def engage_fx(p):
        stub_engage(p)              # the fixture's record (_engaged)
        _REAL_ENGAGE_FX(p)
    monkeypatch.setattr(dash, "_on_engage_fx", engage_fx)
    monkeypatch.setattr(dash, "_on_drop_out_fx", _REAL_DROP_OUT_FX)
    _mid_flight(w)
    vfx = dash_vfx.get()
    vfx.tick(App.g_kUtopiaModule.GetGameTime())
    assert vfx.dash_intensity() == 1.0
    w.player.SetDead()
    _tick(w, GameLoop())
    assert not dash.is_dashing(w.player)
    vfx.tick(App.g_kUtopiaModule.GetGameTime() + 10.0)
    assert vfx.dash_intensity() == 0.0
    assert vfx.engine_glow() == (0.0, 0.0)


def _swap_player(w):
    """RecreatePlayer's shape: a new ship becomes the player; the host's
    identity sync then sees the change."""
    from engine import host_loop as hl
    new = ShipClass_Create("Galaxy")
    w.ona1.AddObjectToSet(new, "new player")
    App.Game_GetCurrentGame().SetPlayer(new)
    w.events.clear()                # from here: the old ship's events only
    sess = hl.MissionSession(mission_name="t")
    sess.player = w.player
    hl._sync_player_identity(sess, lambda p: None)
    assert sess.player is new
    return new


def test_a_player_swap_mid_flight_ends_the_old_ships_dash_at_rest(world):
    from engine import dash_vfx
    w = world
    _mid_flight(w)
    dash_vfx.get().engage(App.g_kUtopiaModule.GetGameTime())
    _swap_player(w)
    assert not dash.is_dashing(w.player)
    assert w.player.IsDoingInSystemWarp() == 0
    assert warp_state.get_state(w.player) == WarpEngineSubsystem.WES_NOT_WARPING
    v = w.player.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert _events_of(w, App.ET_EXITED_SET, App.ET_ENTERED_SET,
                      App.ET_EXITED_WARP) == []
    dash_vfx.get().tick(App.g_kUtopiaModule.GetGameTime())
    assert dash_vfx.get().dash_intensity() == 0.0


def test_a_player_swap_during_the_align_hands_the_queues_back(world):
    w = world
    marks = _queue_all(w)
    warp_button.press(w.button)
    assert dash.is_dashing(w.player)
    _swap_player(w)
    assert not dash.is_dashing(w.player)
    for _ in range(int(round(15.0 / TICK_DELTA))):
        _tick(w, GameLoop())
    assert w.flashes == []
    _assert_queues_back(w, marks)


def test_the_old_ship_gets_no_dash_nacelle_glow_after_a_player_swap(world):
    """The glow envelope's dash branch is player-only, like every other
    player-scene warp effect (warp._is_current_player)."""
    from engine.host_loop import _warp_glow_envelope
    w = world
    _mid_flight(w)
    assert _warp_glow_envelope(w.player) is not None
    new = ShipClass_Create("Galaxy")
    w.ona1.AddObjectToSet(new, "new player")
    App.Game_GetCurrentGame().SetPlayer(new)
    assert dash.is_dashing(w.player)        # identity not synced yet
    assert _warp_glow_envelope(w.player) is None


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


# ── the arrival turn (Mark, live 2026-09-27) ────────────────────────────────
#
# "I would prefer the ship to exit warp and then turn to that spot at impulse
# so it doesnt look wierd. the player can chose to shake out of it if they
# wish by overriding the turn." The path no longer curves onto the
# placement's forward: the ship drops out facing its travel direction, then
# turns onto the placement's rotation at its impulse turn rate.

def _rot_angle(Ra, Rb):
    """The angle of the rotation taking Ra onto Rb (radians)."""
    tr = sum(Ra.GetCol(i).x * Rb.GetCol(i).x + Ra.GetCol(i).y * Rb.GetCol(i).y
             + Ra.GetCol(i).z * Rb.GetCol(i).z for i in range(3))
    return math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0)))


def _vec(p):
    return (p.x, p.y, p.z)


def _turn_rate():
    from engine.host_loop import _PlayerControl
    return _PlayerControl.TURN_RATE_RAD_PER_S   # the fixture's Galaxy: no IES


def _to_drop_out(w):
    warp_button.press(w.button)
    path = dash._state(w.player).path
    travel = path.tangent_at(path.length_gu)
    _run_until(w, lambda: not dash.is_dashing(w.player))
    return travel


def test_the_set_course_path_is_straight_when_unobstructed(world):
    w = world
    warp_button.press(w.button)
    path = dash._state(w.player).path
    assert [p[0] for p in path._pieces] == ["line"]
    assert path.length_gu == pytest.approx(math.dist(path._start, path._end))


def test_arrival_drops_out_facing_the_travel_direction(world):
    w = world
    wp = w.ona2.GetObject("Player Start")
    travel = _to_drop_out(w)
    f_wp = _vec(wp.GetWorldRotation().GetCol(1))
    # Premise: this course arrives well off the placement's forward.
    assert sum(a * b for a, b in zip(travel, f_wp)) < math.cos(math.radians(30))

    assert w.player.GetContainingSet() is w.ona2
    assert _vec(w.player.GetWorldLocation()) == pytest.approx(
        _vec(wp.GetWorldLocation()), abs=1e-6)
    assert _vec(w.player.GetVelocity()) == (0.0, 0.0, 0.0)
    assert _vec(w.player.GetWorldRotation().GetCol(1)) == pytest.approx(
        travel, abs=1e-6)
    assert dash.is_arrival_turning(w.player)


def test_then_turns_onto_the_placement_at_the_turn_rate(world):
    w = world
    wp = w.ona2.GetObject("Player Start")
    _to_drop_out(w)
    Rw = wp.GetWorldRotation()
    pos = _vec(w.player.GetWorldLocation())
    a0 = _rot_angle(w.player.GetWorldRotation(), Rw)
    rate = _turn_rate()
    angles = [a0]
    frames_ = 0
    while dash.is_arrival_turning(w.player):
        dash.tick(w.player, TICK_DELTA)
        frames_ += 1
        angles.append(_rot_angle(w.player.GetWorldRotation(), Rw))
        assert frames_ < 1000
    for prev, cur in zip(angles, angles[1:]):
        assert cur < prev + 1e-9                     # monotone, no overshoot
        assert prev - cur <= rate * TICK_DELTA + 1e-6   # never above the rate
    assert frames_ == math.ceil(a0 / (rate * TICK_DELTA) - 1e-9)
    R = w.player.GetWorldRotation()
    for i in (1, 2):
        assert _vec(R.GetCol(i)) == pytest.approx(_vec(Rw.GetCol(i)), abs=1e-6)
    # At rest, where it dropped out, the whole turn.
    assert _vec(w.player.GetWorldLocation()) == pytest.approx(pos, abs=1e-9)
    assert _vec(w.player.GetVelocity()) == (0.0, 0.0, 0.0)


def test_a_steering_key_mid_turn_cancels_it(world):
    from engine.host_loop import _PlayerControl
    w = world
    _to_drop_out(w)
    pc = _PlayerControl()
    for _ in range(10):
        pc.apply(w.player, TICK_DELTA, _Reader())
        dash.tick(w.player, TICK_DELTA)
    assert dash.is_arrival_turning(w.player)
    pc.apply(w.player, TICK_DELTA,
             _Reader(held={pc._input_map.code("yaw_left")}))
    assert not dash.is_arrival_turning(w.player)
    # From here only the player turns the ship: with no key held, and the
    # yaw rate ramped back down, nothing rotates it.
    for _ in range(120):
        pc.apply(w.player, TICK_DELTA, _Reader())
        dash.tick(w.player, TICK_DELTA)
    r0 = _vec(w.player.GetWorldRotation().GetCol(1))
    for _ in range(30):
        pc.apply(w.player, TICK_DELTA, _Reader())
        dash.tick(w.player, TICK_DELTA)
    assert _vec(w.player.GetWorldRotation().GetCol(1)) == pytest.approx(r0)


def test_a_throttle_key_mid_turn_cancels_it(world):
    from engine.host_loop import _PlayerControl
    w = world
    _to_drop_out(w)
    pc = _PlayerControl()
    pc.apply(w.player, TICK_DELTA, _Reader(pressed={_Keys.KEY_5}))
    assert not dash.is_arrival_turning(w.player)
    assert pc.impulse_level == 5


def test_a_scroll_throttle_nudge_mid_turn_cancels_it(world):
    from engine.host_loop import _PlayerControl
    w = world
    _to_drop_out(w)
    pc = _PlayerControl()
    pc.nudge_throttle(1)
    pc.apply(w.player, TICK_DELTA, _Reader())
    assert not dash.is_arrival_turning(w.player)


def test_death_mid_turn_cancels_it(world):
    w = world
    _to_drop_out(w)
    w.player.SetDead()
    R0 = w.player.GetWorldRotation()
    dash.tick(w.player, TICK_DELTA)
    assert not dash.is_arrival_turning(w.player)
    assert _rot_angle(w.player.GetWorldRotation(), R0) == 0.0


def test_a_new_dash_mid_turn_cancels_it(world):
    w = world
    _to_drop_out(w)
    w.button.set_player_destination("Systems.Ona.Ona1")
    warp.set_course_placement(w.button, "Systems.Ona.Ona1")
    warp_button.press(w.button)
    assert dash.is_dashing(w.player)
    assert not dash.is_arrival_turning(w.player)


def test_a_player_swap_mid_turn_cancels_it(world):
    w = world
    _to_drop_out(w)
    _swap_player(w)
    assert not dash.is_arrival_turning(w.player)


def test_an_ai_order_mid_turn_cancels_it(world):
    import AI.Player.Stay
    w = world
    _to_drop_out(w)
    w.player.SetAI(AI.Player.Stay.CreateAI(w.player))
    R0 = w.player.GetWorldRotation()
    dash.tick(w.player, TICK_DELTA)
    assert not dash.is_arrival_turning(w.player)
    assert _rot_angle(w.player.GetWorldRotation(), R0) == 0.0


# ── the whole-trip curve (Mark, live 2026-09-28) ────────────────────────────
#
# "set out on a heading which avoids the planet and then turn over the
# course of the entire warp in order to make it look like a path we have
# plotted around the object or objects".

def test_a_course_round_the_sun_sets_off_angled_away_on_a_smooth_curve(world):
    from engine.systems import resolve
    from engine.systems.warp_path import comfort_gu
    w = world
    w.ona3 = load_region("Ona", "Ona3")
    w.button.set_player_destination("Systems.Ona.Ona3")
    warp.set_course_placement(w.button, "Systems.Ona.Ona3")
    warp_button.press(w.button)
    path = dash._state(w.player).path
    assert path.smooth and path.comfort_kept

    sun = resolve.map_of("Ona").body("Ona")
    start, end = path.point_at(0.0), path.end
    chord = [b - a for a, b in zip(start, end)]
    n = math.sqrt(sum(v * v for v in chord))
    ex = [v / n for v in chord]
    to_sun = [c - a for c, a in zip(sun.position_gu, start)]
    along = sum(a * b for a, b in zip(to_sun, ex))
    lateral = [v - along * e for v, e in zip(to_sun, ex)]

    # The align turn ends on the curve's first tangent -- off the chord,
    # away from the sun ...
    _run_until(w, lambda: _engaged(w))
    f = _vec(w.player.GetWorldRotation().GetCol(1))
    assert f == pytest.approx(path.tangent_at(0.0), abs=1e-6)
    assert sum(a * b for a, b in zip(f, lateral)) < 0.0
    assert sum(a * b for a, b in zip(f, ex)) < math.cos(math.radians(5.0))

    # ... and the flight still takes ten seconds flash to flash, clear of
    # the sun by the comfort margin.
    from engine.appc import warp_flight
    gaps = []

    def fly():
        p = warp_flight.to_system(w.player, _vec(w.player.GetTranslate()))
        gaps.append(math.dist(p, sun.position_gu))
        return not dash.is_dashing(w.player)

    _run_until(w, fly)
    span = w.flashes[1][1] - w.flashes[0][1]
    assert abs(span - 10.0) <= TICK_DELTA + 1e-9
    assert min(gaps) >= sun.radius_gu + comfort_gu(sun.radius_gu) - 1.0
    assert w.player.GetContainingSet() is w.ona3
