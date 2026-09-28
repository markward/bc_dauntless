"""Campaign transitions end to end, headless (spec: Testing, "Mission changes,
headless" and "Warp set").

Each case loads a real Maelstrom mission the way the dev picker does, sets
the mission's own preconditions through its module globals, plots a course
on the real Warp button, presses it (ET_WARP_BUTTON_PRESSED through the
mission's own WarpHandler and the engine step) and ticks until the warp
detaches. The warp takes the fallback branch headless (no flythrough VFX),
which still plays the queues, holds on WaitForQueued and runs the change at
_MissionChangePoint. The E6M5 case also runs the production branch -- the
flythrough, which is always on live -- with the real WarpVFX driven on game
time as host_loop.run() drives it.
"""
import pytest

import App
from engine.appc import warp
from engine.appc.bridge_set import BridgeSet
from engine.core import mission_change
from tests.helpers import headless_mission as hm
from tests.helpers.headless_mission import no_logged_failures  # noqa: F401 (fixture)


@pytest.fixture
def changes(monkeypatch):
    """Every mission_change.change call, as (kwargs, returned, the Game's
    player once the next mission's Initialize has run)."""
    calls = []
    real = mission_change.change

    def _spy(**kw):
        ok = real(**kw)
        calls.append((kw, ok, App.Game_GetCurrentPlayer()))
        return ok
    monkeypatch.setattr(mission_change, "change", _spy)
    return calls


def _spy_terminate(monkeypatch, mod):
    ran = []
    real = mod.Terminate

    def _t(pMission):
        ran.append(pMission)
        return real(pMission)
    monkeypatch.setattr(mod, "Terminate", _t)
    return ran


def _mark_hull(player):
    hull = player.GetHull()
    hull.SetCondition(hull.GetMaxCondition() * 0.5)
    return hull.GetCondition()


def _old_sets():
    return list(App.g_kSetManager._sets.values())


def _surviving(old_sets):
    live = list(App.g_kSetManager._sets.values())
    return [s for s in old_sets if any(s is l for l in live)]


def _only_bridge_and_warp(sets):
    for s in sets:
        assert (s.GetName() in ("bridge", "warp")
                or isinstance(s, BridgeSet)), s.GetName()


def _move(ship, set_name):
    ship.GetContainingSet().RemoveObjectFromSet(ship.GetName())
    App.g_kSetManager.GetSet(set_name).AddObjectToSet(ship, ship.GetName())


def _assert_carried(player, pid, condition, changes):
    """The same ship all the way through -- including to the next mission's
    Initialize, whose CreatePlayerShip must find it rather than build a
    second "player" that the warp's arrival then silently displaces."""
    now = App.Game_GetCurrentPlayer()
    assert id(now) == pid and now is player
    assert [p for _, _, p in changes] == [player]
    assert now.GetHull().GetCondition() == pytest.approx(condition)


@pytest.fixture(params=["hard_cut", "flythrough"])
def warp_branch(request):
    """The warp branch to run, and the per-tick host work it needs. For the
    flythrough, the hooks host_loop.run() installs (configure_warp_vfx: the
    predicate is always True live; start/stop drive the engine.warp_vfx
    singleton on game time; vantages from the sector model) plus the
    per-frame WarpVFX tick; restored afterwards."""
    from engine import warp_vfx
    from engine.appc import warp
    if request.param == "hard_cut":
        yield request.param, None
        return
    vfx = warp_vfx.get()
    vfx.stop()

    def _vantage_of(key):
        # host_loop.run()'s _vantage_of: a live SetClass or a module string.
        from engine.appc import sector_model, sky_projection
        try:
            model = sky_projection.load_sector_model()
            if hasattr(key, "GetName"):
                v = sky_projection.vantage_for_set(key, model)
            else:
                set_name = warp._set_name_from_module(key)
                if not set_name:
                    return None
                sysid = sector_model.system_id_for_set(set_name)
                v = None
                for s in model.get("systems", []):
                    if s.get("id") == sysid:
                        v = s.get("position")
                        break
            return None if v is None else (v[0], v[1], v[2])
        except Exception:
            return None

    def _start(heading, t_align, t_transit, vantage=None, dst_vantage=None,
               t_hold=0.0):
        vfx.start(heading, t_align, t_transit,
                  App.g_kUtopiaModule.GetGameTime(), vantage, dst_vantage,
                  t_hold=t_hold)

    def _tick():
        if vfx.is_active():
            vfx.tick(App.g_kUtopiaModule.GetGameTime())

    warp.configure_warp_vfx(start=_start, stop=vfx.stop,
                            enabled=lambda: True, vantage_of=_vantage_of)
    try:
        yield request.param, _tick
    finally:
        warp.configure_warp_vfx(start=None, stop=None, enabled=None,
                                vantage_of=None)
        vfx.stop()


def test_e6m5_warps_into_episode_7(monkeypatch, changes, no_logged_failures,
                                   warp_branch):
    from engine import warp_vfx
    branch, after_tick = warp_branch
    _, _, game, mod = hm.load("Maelstrom.Episode6.E6M5.E6M5")
    terminated = _spy_terminate(monkeypatch, mod)
    player = App.Game_GetCurrentPlayer()
    pid, condition = id(player), _mark_hull(player)
    assert player.GetContainingSet().GetName() != "Tezle1"
    # The Strike Force has reached Tezle1, so the player's arrival there
    # registers E6M5's WarpHandler (E6M5.py:2066) -- its only registration.
    mod.g_bStrikeForceInTezle1 = 1
    mod.PlayerArrivesTezle1()
    btn = hm.the_warp_button()
    hm.plot_course(btn, "Systems.Beol.Beol4")
    old = _old_sets()
    started = []
    if branch == "flythrough":
        real_start = warp._vfx_start
        monkeypatch.setattr(warp, "_vfx_start",
                            lambda *a, **k: (started.append(a),
                                             real_start(*a, **k)))

    hm.warp_and_wait(btn, player, after_tick=after_tick)

    if branch == "flythrough":
        assert len(started) == 1, "the flythrough branch did not run"
    # Not left holding the streak, nor running the tunnel.
    assert warp_vfx.get().is_held() is False
    assert warp_vfx.get().is_active() is False
    assert hm.current_mission_name(game) == "Maelstrom.Episode7.E7M1.E7M1"
    assert game.GetCurrentEpisode()._module_name == \
        "Maelstrom.Episode7.Episode7"
    _assert_carried(player, pid, condition, changes)
    assert player.GetContainingSet().GetName() == "Starbase12"
    start = hm.placement_location("Starbase12", "Player Start")
    assert start is not None
    loc = player.GetWorldLocation()
    assert (loc.x, loc.y, loc.z) == pytest.approx((start.x, start.y, start.z))
    assert len(terminated) == 1
    _only_bridge_and_warp(_surviving(old))
    assert [ok for _, ok, _ in changes] == [True]


def test_e7m6_warps_into_episode_8(monkeypatch, changes, no_logged_failures):
    _, _, game, mod = hm.load("Maelstrom.Episode7.E7M6.E7M6")
    terminated = _spy_terminate(monkeypatch, mod)
    player = App.Game_GetCurrentPlayer()
    pid, condition = id(player), _mark_hull(player)
    assert player.GetContainingSet().GetName() != "Alioth6"
    mod.g_bDataRescued = 1
    btn = hm.the_warp_button()
    hm.plot_course(btn, "Systems.Starbase12.Starbase12")
    old = _old_sets()

    hm.warp_and_wait(btn, player)

    assert hm.current_mission_name(game) == "Maelstrom.Episode8.E8M1.E8M1"
    _assert_carried(player, pid, condition, changes)
    assert len(terminated) == 1
    _only_bridge_and_warp(_surviving(old))
    assert [ok for _, ok, _ in changes] == [True]


def test_e6m1_warps_into_e6m2_through_the_set_course_menu(
        monkeypatch, changes, no_logged_failures):
    _, _, game, mod = hm.load("Maelstrom.Episode6.E6M1.E6M1")
    terminated = _spy_terminate(monkeypatch, mod)
    player = App.Game_GetCurrentPlayer()
    pid, condition = id(player), _mark_hull(player)
    # E6M1.py:3694: the rescue ship has sat by the Savoy 1 station long
    # enough (StationClear*), so the Starbase 12 course starts E6M2. The
    # player is at Savoy 1 then; the course is plotted on that menu.
    _move(player, "Savoy1")
    mod.LinkToE6M2(None)
    btn = hm.the_warp_button()
    hm.plot_course(btn, "Systems.Starbase12.Starbase12")
    assert btn.get_mission_name() == "Maelstrom.Episode6.E6M2.E6M2"
    old = _old_sets()

    hm.warp_and_wait(btn, player)

    assert hm.current_mission_name(game) == "Maelstrom.Episode6.E6M2.E6M2"
    _assert_carried(player, pid, condition, changes)
    assert len(terminated) == 1
    _only_bridge_and_warp(_surviving(old))
    assert [ok for _, ok, _ in changes] == [True]


def test_e2m6_direct_load_starts_episode_3(monkeypatch, changes,
                                           no_logged_failures):
    """A direct LoadEpisode is not a warp: the player's region goes with the
    player (Ruling R9) and E3M1's CreatePlayerShip builds a new ship."""
    _, _, game, mod = hm.load("Maelstrom.Episode2.E2M6.E2M6")
    terminated = _spy_terminate(monkeypatch, mod)
    assert mod.g_bMissionTerminate == 1     # 1 == running (E2M6.py:2773)
    old = _old_sets()

    mod.StartEpisode3(None)

    assert game.GetCurrentEpisode()._module_name == \
        "Maelstrom.Episode3.Episode3"
    assert hm.current_mission_name(game) == "Maelstrom.Episode3.E3M1.E3M1"
    assert len(terminated) == 1
    _only_bridge_and_warp(_surviving(old))
    assert App.Game_GetCurrentPlayer() is not None
    assert [ok for _, ok, _ in changes] == [True]


def test_e6m1_artrus_ships_made_in_the_tunnel_exist_on_arrival(
        monkeypatch, no_logged_failures):
    """E6M1 creates the Artrus ships from PlayerEntersWarpSet (E6M1.py:1552),
    i.e. while the player is in BC's "warp" set, and gives them AI on
    arrival in Artrus3 (TrackPlayer -> GiveArtrusShipsAI)."""
    _, _, game, mod = hm.load("Maelstrom.Episode6.E6M1.E6M1")
    seen = []
    real = mod.GiveArtrusShipsAI

    def _give():
        pSet = App.g_kSetManager.GetSet("Artrus3")
        seen.append([App.ShipClass_GetObject(pSet, n) is not None
                     for n in ("San Francisco", "Galor 1", "Galor 2")])
        return real()
    monkeypatch.setattr(mod, "GiveArtrusShipsAI", _give)
    player = App.Game_GetCurrentPlayer()
    assert not mod.g_bPlayerArriveArtrus
    btn = hm.the_warp_button()
    hm.plot_course(btn, "Systems.Artrus.Artrus3")

    hm.warp_and_wait(btn, player)

    assert player.GetContainingSet().GetName() == "Artrus3"
    assert seen == [[True, True, True]]
    assert hm.current_mission_name(game) == "Maelstrom.Episode6.E6M1.E6M1"
