"""The GenerateShips hook against the real SDK QuickBattle, headless.
Pattern: tests/host/test_quickbattle_boot.py."""
import math

import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: E402


@pytest.fixture
def qb(monkeypatch):
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB
    from engine.quickbattle import spawn
    spawn.install_generate_ships_hook(QB)      # Task 8 moves this into boot; idempotent
    yield hl, controller, QB
    spawn.set_provider(None)


def _plan(groups):
    """groups: list of (allegiance, direction, distance, difficulty, [ship ids])."""
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.delete_group(s.groups[1].id)
    for alleg, d, dist, diff, ships in groups:
        g = s.add_group()
        s.update_details(g.id, alleg, d, dist, diff)
        for ship in ships:
            s.add_ship(g.id, ship)
    return s, sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))


def _start(hl, controller):
    import App
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()


def _ship(name):
    import App
    import QuickBattle.QuickBattle as QB
    return App.ShipClass_GetObject(QB.g_pSet, name)


def test_groups_spawn_with_membership_ai_and_levels(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "fore", "standard", "high", ["Warbird", "Galor"]),
                      ("neutral", "port", "close", "medium", ["Transport"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    assert QB.bInSimulation == 1
    assert QB.g_iNumEnemies == 2
    sides = sorted(v[2] for v in QB.g_kShips.values())
    assert sides == ["Enemy", "Enemy"]                       # neutral: no g_kShips entry
    assert all(v[3] == 1.0 for v in QB.g_kShips.values())   # high
    import App
    mission = App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission()
    assert mission.GetNeutralGroup().IsNameInGroup("Transport-3")
    assert QB.pEnemies.IsNameInGroup("Warbird-1")


def test_positions_follow_direction_and_distance(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "aft", "long", "medium", ["Warbird"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    pp, fwd = player.GetWorldLocation(), player.GetWorldRotation().GetCol(1)
    wp = _ship("Warbird-1").GetWorldLocation()
    d = (wp.x - pp.x, wp.y - pp.y, wp.z - pp.z)
    dist = math.sqrt(sum(c * c for c in d))
    assert dist == pytest.approx(80.0 / 0.175, rel=0.05)
    assert (d[0] * fwd.x + d[1] * fwd.y + d[2] * fwd.z) / dist < -0.95   # behind


def test_enemies_face_player_friendlies_keep_heading(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird"]),
                      ("friendly", "starboard", "close", "medium", ["Akira"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    pf = player.GetWorldRotation().GetCol(1)
    ef = _ship("Warbird-1").GetWorldRotation().GetCol(1)
    ff = _ship("Akira-2").GetWorldRotation().GetCol(1)
    assert ef.x * pf.x + ef.y * pf.y + ef.z * pf.z < -0.99
    assert ff.x * pf.x + ff.y * pf.y + ff.z * pf.z > 0.99


def test_named_ship_registry_queued_and_display_name(qb):
    hl, controller, QB = qb
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    s, _ = _plan([("enemy", "fore", "standard", "medium", ["Galaxy"])])
    e = s.groups[1].entries[0]
    s.set_variant(e.id, "USS Venture")
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    plan = sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    ship = _ship("Galaxy-1")
    # GetDisplayName() is a plain python str in this shim (engine/appc/objects.py),
    # not a TGString -- see every other call site (e.g. tests/unit/test_hailable_
    # broadcast.py), so there is no .GetCString() to chain.
    assert ship.GetDisplayName() == "USS Venture"
    reps = registry_texture.replacements_for(ship)
    # replacements_for returns [(old_name, new_texture), ...], not a dict.
    assert any(new.endswith("Venture.tga") for _old, new in reps)


def test_generate_ships_reads_provider_at_call_time(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, first = _plan([("enemy", "fore", "standard", "medium", ["Warbird"])])
    _s, second = _plan([("enemy", "fore", "standard", "medium", ["Galor", "Keldon"])])
    box = {"plan": first}
    spawn.set_provider(lambda: box["plan"])
    _start(hl, controller)
    QB.EndSimulation()
    hl._process_object_deletions()
    box["plan"] = second                    # e.g. XO Restart without opening the screen
    _start(hl, controller)
    assert QB.g_iNumEnemies == 2


def test_one_failing_ship_does_not_stop_the_rest(qb, monkeypatch):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    import loadspacehelper
    real = loadspacehelper.CreateShip

    def flaky(ship_file, *a, **k):
        if ship_file == "Galor":
            raise RuntimeError("broken mod ship")
        return real(ship_file, *a, **k)

    monkeypatch.setattr(loadspacehelper, "CreateShip", flaky)
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Galor", "Warbird"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    assert QB.g_iNumEnemies == 1 and _ship("Warbird-2") is not None


def test_no_provider_falls_back_to_bc(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    spawn.set_provider(None)
    QB.g_kEnemyList = [("Galaxy", "Galaxy", "msg", "QuickBattleAI", "Enemy", 0.5)]
    _start(hl, controller)
    assert len(QB.g_kShips) == 1


def test_install_is_idempotent(qb):
    _hl, _c, QB = qb
    from engine.quickbattle import spawn
    first = QB.GenerateShips
    assert not spawn.install_generate_ships_hook(QB)       # already installed by boot
    assert QB.GenerateShips is first


def test_sync_sdk_sets_player_manifests_and_xo_start(qb):
    _hl, _c, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird"]),
                      ("neutral", "port", "close", "medium", ["Transport"])])
    spawn.sync_sdk(QB, plan)
    assert QB.g_sPlayerType == "Galaxy"
    assert [t[0] for t in QB.g_kEnemyList + QB.g_kFriendList] == ["Warbird", "Transport"]
    btn = QB.g_pXOMenu.GetButtonW(QB.g_pMissionDatabase.GetString("Start Simulation"))
    assert btn.IsEnabled()
