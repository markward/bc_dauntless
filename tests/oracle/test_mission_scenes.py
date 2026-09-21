"""Bible §13 — what a stock mission puts in the player's set, with nobody
touching anything (`scene_<mission>.json`, `docs/mission-scenes.md`).

Only the missions whose cast does not depend on campaign state the mission-
only harness never initialises are used here: E7M6/E8M1 gate their escorts
on `Maelstrom.bGeronimoAlive` (set by the campaign's own init, 0 at import),
E2M6 needs `DynamicMusic.LoadMusic` from Episode init, and E4M5's Enterprise
arrives after a dialogue sequence whose timing needs audio.
"""
import importlib

import pytest

from engine.core.loop import TICK_DELTA

GREEN, YELLOW, RED = 0, 1, 2

# mission module → (player script, expected non-player cast at t = 0)
SCENES = {
    "Maelstrom.Episode1.E1M1.E1M1": ("Galaxy", {
        "Dry Dock", "Dry Dock2", "Dry Dock3", "Station", "Nightingale",
        "Shuttle1", "Shuttle2", "Shuttle3"}),
    "Maelstrom.Episode2.E2M0.E2M0": ("Galaxy", {"Sovereign", "RanKuf", "Trayor"}),
    "Maelstrom.Episode4.E4M4.E4M4": ("Sovereign", {
        "Asteroid 1", "Asteroid 2", "Asteroid 3", "Asteroid 4", "Asteroid 5",
        "Asteroid 6", "Asteroid 7", "Mavjop"}),
}


@pytest.fixture
def scene(monkeypatch):
    """`scene(module)` → (player, [other ships in the player's set], tick)."""
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    import tools.mission_harness as _mh
    _mh.setup_sdk()
    import App
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.events import TGEvent
    from engine.host_loop import reset_sdk_globals
    from engine.core.loop import GameLoop
    from engine.appc.ship_iter import iter_ships

    def _build(module):
        mission, episode, game = Mission(), Episode(), Game()
        episode.SetCurrentMission(mission)
        game.SetCurrentEpisode(episode)
        _set_current_game(game)
        reset_sdk_globals()
        importlib.import_module(module).Initialize(mission)
        evt = TGEvent()
        evt.SetEventType(App.ET_MISSION_START)
        evt.SetDestination(episode)
        App.g_kEventManager.AddEvent(evt)
        loop = GameLoop()
        loop.tick()
        player = App.Game_GetCurrentPlayer()
        pset = player.GetContainingSet()
        others = [s for s in iter_ships()
                  if s is not player and s.GetContainingSet() is pset]
        return player, others, loop

    yield _build
    _set_current_game(None)
    _mh.purge_run_modules()


def _speed(ship):
    v = ship.GetVelocity()
    return (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5


@pytest.mark.parametrize("module", sorted(SCENES))
def test_n1_player_parked_at_green_with_full_hull_and_shields(scene, module):
    """N1 — a freshly loaded mission has the player ship parked at the
    scripted placement (speed 0, green alert, full hull/shields, no target)
    and it stays parked for 90 s without input."""
    player, _, loop = scene(module)
    assert player.GetAlertLevel() == GREEN
    assert player.GetTarget() is None
    hull = player.GetHull()
    assert hull.GetCondition() == hull.GetMaxCondition()
    sh = player.GetShields()
    assert all(sh.GetCurShields(i) == sh.GetMaxShields(i) for i in range(6))
    p0 = player.GetWorldLocation()
    loop.advance(int(90.0 / TICK_DELTA))
    p1 = player.GetWorldLocation()
    assert (p0.x, p0.y, p0.z) == pytest.approx((p1.x, p1.y, p1.z), abs=0.01)
    assert _speed(player) == 0.0


@pytest.mark.parametrize("module", sorted(SCENES))
def test_n2_cast_is_present_with_full_hull(scene, module):
    """N2 — the non-player cast at t = 0, every one with full hull; nothing
    hidden, cloaked or dying."""
    _, others, _ = scene(module)
    names = {s.GetName() for s in others}
    assert names == SCENES[module][1]
    for s in others:
        hull = s.GetHull()
        assert hull.GetCondition() == hull.GetMaxCondition(), s.GetName()
        assert not s.IsDead(), s.GetName()


@pytest.mark.xfail(strict=True, reason=(
    "bible N2: every non-player object spawns at RED alert unless the mission "
    "scripts otherwise (E1M1's dock scene is green by its GreenAlert AI); "
    "Dauntless spawns them green — only ships whose script sets an alert are red"))
@pytest.mark.parametrize("module", ["Maelstrom.Episode2.E2M0.E2M0",
                                    "Maelstrom.Episode4.E4M4.E4M4"])
def test_n2_non_player_ships_spawn_at_red_alert(scene, module):
    """N2 — `scene_E2M0`, `scene_E4M4`: RanKuf/Trayor, Mavjop and the
    asteroids all read alert 2 from the first snapshot; the player is the only
    object at green."""
    _, others, _ = scene(module)
    assert all(s.GetAlertLevel() == RED for s in others), \
        [(s.GetName(), s.GetAlertLevel()) for s in others]


def test_n3_e1m1_shuttles_cruise_at_4_gu_per_s(scene):
    """N3 — `scene_E1M1`: Shuttle1/2 run `AvoidObstacles` at 4.0 GU/s and
    travel 185 / 347 GU in 90 s (± 5 %); nothing else moves."""
    _, others, loop = scene("Maelstrom.Episode1.E1M1.E1M1")
    by_name = {s.GetName(): s for s in others}
    start = {n: s.GetWorldLocation() for n, s in by_name.items()}
    loop.advance(int(90.0 / TICK_DELTA))
    moved = {}
    for n, s in by_name.items():
        p, q = start[n], s.GetWorldLocation()
        moved[n] = ((p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2) ** 0.5
    assert moved["Shuttle1"] == pytest.approx(185.4, rel=0.05)
    assert moved["Shuttle2"] == pytest.approx(346.8, rel=0.05)
    assert _speed(by_name["Shuttle1"]) == pytest.approx(4.0, abs=0.05)
    for n, d in moved.items():
        if n not in ("Shuttle1", "Shuttle2"):
            assert d < 0.5, (n, d)


@pytest.mark.xfail(strict=True, reason=(
    "bible N3 / scene_E3M2: the Warbird is in Vesuvi6 at t = 0 — E3M2 creates "
    "the player (line 328) BEFORE registering its ET_ENTERED_SET handler (671), "
    "and BC's queued event still reaches it; Dauntless dispatches inline, so "
    "the handler is never called and the Warbird never exists"))
def test_n3_e3m2_warbird_spawns_on_the_players_queued_entered_set_event(scene):
    _, others, _ = scene("Maelstrom.Episode3.E3M2.E3M2")
    assert "Warbird" in {s.GetName() for s in others}
