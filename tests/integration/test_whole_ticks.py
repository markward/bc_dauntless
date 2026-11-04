"""Each sim tick runs whole (native motion phase 4, ruling 2): GameLoop tick
i (AI, motion), then weapons and combat tick i, then the tick boundary,
before tick i+1 starts. The per-frame input and session stages (swap drain,
preload-done spawn, deletions, input, fire keys, Manual Aim) run at frame
start, before tick 0. Real host frames (host_loop._run_frame_sim, headless,
tests/helpers/host_frame_fight.py) on combat_stress with 2 ships.

The Behaviour shifts these pin are listed in
docs/reference/engine/perf-cadences-and-latency.md, "Whole ticks (ruling 2)".
"""
import types

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine import manual_aim
from engine.appc import sensor_contacts
from engine.core.loop import GameLoop
from tests.helpers import bc_assets, headless_mission
from tests.helpers import host_frame_fight as hff

pytestmark = pytest.mark.skipif(_h is None, reason="native module not built")


@pytest.fixture
def fight(monkeypatch):
    """(scene, loop, order, frame) for a 2-ship combat_stress. `order` is the
    spies' shared log; `hook` (a list) holds the tick_hook's extra actions,
    each called with the frame's 1-based GameLoop tick index."""
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    headless_mission.clear_in_flight()
    headless_mission.load(hff.MISSION)
    loop = GameLoop(owns_boundary=False)
    scene = types.SimpleNamespace(player=App.Game_GetCurrentPlayer())
    order = []
    state = types.SimpleNamespace(gl_in_frame=0, hooks=[])

    def tick_hook():
        state.gl_in_frame += 1
        order.append("gl")
        for hook in state.hooks:
            hook(state.gl_in_frame)

    ctx = hff.headless_context(monkeypatch, scene, loop, tick_hook=tick_hook)

    def spy(name, label, before=None):
        real = getattr(host_loop, name)

        def wrapper(*a, **k):
            if before is not None:
                before(*a, **k)
            order.append(label)
            return real(*a, **k)
        monkeypatch.setattr(host_loop, name, wrapper)

    spy("_advance_weapons", "weapons")
    spy("_advance_combat", "combat")
    spy("_combat_tick_boundary", "boundary")

    def run(frame_ticks, frames=None, on_frame=None):
        def end(f, result):
            state.gl_in_frame = 0
            order.append(("frame end", f))
            if on_frame is not None:
                on_frame(f, result)
        return hff.drive(ctx, frame_ticks,
                         len(frame_ticks) if frames is None else frames,
                         on_frame=end)

    return types.SimpleNamespace(scene=scene, ctx=ctx, order=order,
                                 state=state, spy=spy, run=run, mp=monkeypatch)


def _ship(name):
    for s in App.g_kSetManager.GetSet("QuickBattleRegion")._objects.values():
        if getattr(s, "GetName", None) and s.GetName() == name:
            return s
    return None


def _assert_world_stayed_live(fight, session, capfd):
    """The swap tests' pending swap drains through host_frame_fight's
    controller stand-in, whose _drain_pending_swap only clears the request:
    no mission load, no teardown. So the ordering is asserted against the
    live world: the same session and player, Enemy-1 still in its set, and
    nothing printed a traceback."""
    assert fight.ctx.controller.session is session
    assert App.Game_GetCurrentPlayer() is fight.scene.player
    assert _ship("Enemy-1") is not None
    out, err = capfd.readouterr()
    assert "Traceback" not in out + err, out + err


def _frame(order, f):
    """The entries of frame `f` (0-based) in `order`."""
    out, cur = [], 0
    for e in order:
        if e == ("frame end", cur):
            if cur == f:
                return out
            cur += 1
            out = []
            continue
        out.append(e)
    raise AssertionError("frame %d not found" % f)


def test_each_tick_runs_whole(fight):
    fight.run((3,))
    assert _frame(fight.order, 0) == ["gl", "weapons", "combat",
                                      "boundary"] * 3


def test_frame_start_stages_run_before_tick_0(fight, capfd):
    ctrl = fight.ctx.controller
    session = ctrl.session
    real_drain = ctrl._drain_pending_swap

    def drain():
        if ctrl.pending_swap is not None:
            fight.order.append("drain")
        return real_drain()
    fight.mp.setattr(ctrl, "_drain_pending_swap", drain)
    ctrl.pending_swap = object()
    fight.spy("_fire_pending_preload_done", "preload_done")
    fight.spy("_process_object_deletions", "deletions")
    fight.mp.setattr(host_loop, "_poll_fire_keys",
                     lambda *_a: fight.order.append("fire_keys"))
    fight.mp.setattr(manual_aim, "update",
                     lambda **_k: fight.order.append("manual_aim"))
    fight.run((2,))
    frame = _frame(fight.order, 0)
    first_gl = frame.index("gl")
    for stage in ("drain", "preload_done", "deletions", "fire_keys",
                  "manual_aim"):
        assert stage in frame, stage
        assert frame.index(stage) < first_gl, (stage, frame)
    _assert_world_stayed_live(fight, session, capfd)


def _phasers_and_target(fight):
    """The player's phasers and Enemy-1. Headless, this scene's sensors read
    no power after the first tick (GetNormalPowerPercentage 0, so range 0),
    so StartFiring's detectability gate is opened: these tests pin WHEN a
    press reaches combat, not whether the target is detectable."""
    from engine.appc import sensor_detection
    fight.mp.setattr(sensor_detection, "can_detect", lambda *_a, **_k: True)
    system = fight.scene.player.GetPhaserSystem()
    target = _ship("Enemy-1")
    assert system is not None and target is not None
    return system, target


def _firing_at_first_weapons_call(fight):
    system, target = _phasers_and_target(fight)
    seen = []
    real = host_loop._advance_weapons

    def weapons(ships, dt, *a, **k):
        seen.append(system.IsFiring())
        return real(ships, dt, *a, **k)
    fight.mp.setattr(host_loop, "_advance_weapons", weapons)
    return system, target, seen


def test_fire_press_reaches_the_frames_first_combat_tick(fight):
    system, target, seen = _firing_at_first_weapons_call(fight)
    fight.mp.setattr(host_loop, "_poll_fire_keys",
                     lambda *_a: system.StartFiring(target))
    fight.run((3,))
    assert seen and seen[0], seen


def test_fire_press_on_a_zero_tick_frame_reaches_the_next_combat_tick(fight):
    system, target, seen = _firing_at_first_weapons_call(fight)
    pressed = {"done": False}

    def poll(*_a):
        if not pressed["done"]:
            pressed["done"] = True
            system.StartFiring(target)
    fight.mp.setattr(host_loop, "_poll_fire_keys", poll)
    calls = []
    fight.run((0, 1), on_frame=lambda f, _r: calls.append(len(seen)))
    assert calls[0] == 0, "a zero-tick frame ran weapons"
    assert calls[1] >= 1 and seen[0], seen


def test_swap_requested_during_a_tick_drains_at_next_frame_start(fight,
                                                                 capfd):
    ctrl = fight.ctx.controller
    session = ctrl.session
    real_drain = ctrl._drain_pending_swap

    def drain():
        if ctrl.pending_swap is not None:
            fight.order.append("drain")
        return real_drain()
    fight.mp.setattr(ctrl, "_drain_pending_swap", drain)
    requested = {"done": False}

    def request(gl_index):
        if gl_index == 1 and not requested["done"]:
            requested["done"] = True
            ctrl.pending_swap = object()
    fight.state.hooks.append(request)
    fight.run((3, 2))
    first = _frame(fight.order, 0)
    assert "drain" not in first, first
    assert first.count("combat") == 3, first
    second = _frame(fight.order, 1)
    assert "drain" in second, second
    assert second.index("drain") < second.index("gl"), second
    _assert_world_stayed_live(fight, session, capfd)


def test_recreate_player_inside_a_tick_reaches_the_post_tick_pass(fight):
    new_player = _ship("Friend-1")
    assert new_player is not None
    seen = []
    real_tick = sensor_contacts.tick

    def contacts(player, *a, **k):
        seen.append(player)
        return real_tick(player, *a, **k)
    fight.mp.setattr(sensor_contacts, "tick", contacts)

    def recreate(gl_index):
        if gl_index == 1 and not seen:
            App.Game_GetCurrentGame().SetPlayer(new_player)
    fight.state.hooks.append(recreate)
    results = fight.run((3,))
    assert seen == [new_player], seen
    assert results[0].player is new_player


def test_ship_flagged_for_deletion_mid_frame_leaves_at_next_frame_start(fight):
    enemy = _ship("Enemy-1")
    assert enemy is not None
    lists = []
    real = host_loop._advance_weapons

    def weapons(ships, dt, *a, **k):
        lists.append(list(ships))
        return real(ships, dt, *a, **k)
    fight.mp.setattr(host_loop, "_advance_weapons", weapons)
    after_start = []

    def hook(gl_index):
        if gl_index == 1 and not lists:
            enemy.SetDeleteMe(1)
        elif gl_index == 1 and len(lists) == 3:
            # The next frame's first GameLoop tick: its frame-start stages
            # have run.
            after_start.append(_ship("Enemy-1"))
    fight.state.hooks.append(hook)
    fight.run((3, 1))
    assert len(lists) >= 3
    for i in range(3):
        assert enemy in lists[i], "combat tick %d lost Enemy-1" % (i + 1)
    assert after_start == [None], after_start


def test_ship_spawned_in_tick_2_reaches_combat_tick_2_only(fight):
    import loadspacehelper
    lists = []
    real = host_loop._advance_weapons

    def weapons(ships, dt, *a, **k):
        lists.append([s.GetName() for s in ships])
        return real(ships, dt, *a, **k)
    fight.mp.setattr(host_loop, "_advance_weapons", weapons)

    def spawn(gl_index):
        if gl_index == 2 and _ship("Spawned") is None:
            pset = App.g_kSetManager.GetSet("QuickBattleRegion")
            ship = loadspacehelper.CreateShip("Galaxy", pset, "Spawned", "")
            assert ship is not None
            ship.SetTranslateXYZ(0.0, 400.0, 0.0)
    fight.state.hooks.append(spawn)
    fight.run((3,))
    assert "Spawned" not in lists[0], lists[0]
    assert "Spawned" in lists[1], lists[1]


def test_zero_tick_frame_builds_the_ship_list_once(fight):
    builds = []
    real = host_loop._all_ships_for_tick

    def all_ships():
        builds.append(1)
        return real()
    fight.mp.setattr(host_loop, "_all_ships_for_tick", all_ships)
    results = fight.run((0,))
    assert len(builds) == 1
    assert isinstance(results[0].ships_this_tick, list)
    assert "gl" not in _frame(fight.order, 0)


def test_frame_frozen_mid_frame_still_runs_its_whole_ticks(fight):
    pause = fight.ctx.pause
    real = host_loop._route_scroll_wheel

    def route(*a, **k):
        pause.set_external_freeze(True)
        return real(*a, **k)
    fight.mp.setattr(host_loop, "_route_scroll_wheel", route)
    seen = []
    fight.mp.setattr(sensor_contacts, "tick",
                     lambda *a, **k: seen.append(a))
    fight.run((2,))
    assert _frame(fight.order, 0).count("combat") == 2
    assert seen == []


def test_reseat_runs_after_the_penultimate_boundary(fight):
    buf = fight.ctx.xform_buf
    real = buf.reseat_from_live

    def reseat():
        fight.order.append("reseat")
        return real()
    fight.mp.setattr(buf, "reseat_from_live", reseat)
    fight.run((3,))
    frame = _frame(fight.order, 0)
    i = frame.index("reseat")
    boundaries = [j for j, e in enumerate(frame) if e == "boundary"]
    gls = [j for j, e in enumerate(frame) if e == "gl"]
    assert boundaries[1] < i < gls[2], frame
