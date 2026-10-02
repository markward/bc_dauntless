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
    spawn.set_radius_fn(None)


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
    # StartSimulation2 runs `if len(g_kEnemyList) > 0: bWonOrLost = 0`
    # immediately after GenerateShips() returns (QuickBattle.py ~3148) -- our
    # hook must leave g_kEnemyList populated or the win/lose message never
    # arms for a hook-driven Start.
    assert QB.bWonOrLost == 0


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
    """Enemy facing must point AT the player from wherever the group anchors,
    not just antiparallel to the player's own forward -- a "fore" enemy group
    makes those look identical, which is exactly how the GetWorldBackwardTG
    bug (an aft group facing away, a port group side-on) escaped the first
    pass. Cover fore, aft, port and dorsal."""
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird"]),
                      ("enemy", "aft", "standard", "medium", ["Galor"]),
                      ("enemy", "port", "standard", "medium", ["Keldon"]),
                      ("enemy", "dorsal", "standard", "medium", ["Ambassador"]),
                      ("friendly", "starboard", "close", "medium", ["Akira"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    pf = player.GetWorldRotation().GetCol(1)
    pp = player.GetWorldLocation()

    def _unit_toward_player(ship):
        wp = ship.GetWorldLocation()
        d = (pp.x - wp.x, pp.y - wp.y, pp.z - wp.z)
        n = math.sqrt(sum(c * c for c in d))
        return tuple(c / n for c in d)

    for name in ("Warbird-1", "Galor-2", "Keldon-3", "Ambassador-4"):
        ship = _ship(name)
        fwd = ship.GetWorldRotation().GetCol(1)
        ux, uy, uz = _unit_toward_player(ship)
        assert fwd.x * ux + fwd.y * uy + fwd.z * uz > 0.99, name

    ff = _ship("Akira-5").GetWorldRotation().GetCol(1)
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


def _non_player_ships(QB):
    import App
    return [s for s in QB.g_pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT)
            if s.GetName() != "Player"]


def test_two_groups_at_the_same_anchor_dont_overlap(qb, monkeypatch):
    """Two groups sharing direction + distance get IDENTICAL anchors
    (placement.py knows nothing of other groups), and IsLocationEmptyTG is a
    Phase-1 stub that always reports empty (engine/appc/sets.py ~312) -- so
    nothing but spawn.py's own overlap bookkeeping can keep them apart."""
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    import loadspacehelper
    real = loadspacehelper.CreateShip

    def sized(ship_file, *a, **k):
        # Freshly created ships report GetRadius() == 0.0 until the post-sim
        # scene reconcile realizes them (see test_chase_camera_radius_catches_
        # up_after_recreate_player), which runs AFTER GenerateShips -- give
        # them a radius here so this test can assert something non-trivial.
        ship = real(ship_file, *a, **k)
        if ship is not None:
            ship.SetRadius(5.0)
        return ship

    monkeypatch.setattr(loadspacehelper, "CreateShip", sized)
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird"]),
                      ("enemy", "fore", "standard", "medium", ["Galor"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)

    ships = [_ship("Warbird-1"), _ship("Galor-2")]
    assert all(s is not None for s in ships)
    for i in range(len(ships)):
        for j in range(i + 1, len(ships)):
            a, b = ships[i].GetWorldLocation(), ships[j].GetWorldLocation()
            d = (a.x - b.x, a.y - b.y, a.z - b.z)
            dist = math.sqrt(sum(c * c for c in d))
            min_sep = ships[i].GetRadius() + ships[j].GetRadius()
            assert dist >= min_sep, (ships[i].GetName(), ships[j].GetName(), dist, min_sep)


def test_exception_after_creation_does_not_double_spawn(qb, monkeypatch):
    """Spec §4.5 step 3: fall back to BC's original GenerateShips only when
    the hook raises BEFORE spawning anything. An exception in the placement
    pass -- which runs strictly after every ship is created -- must not
    reach install_generate_ships_hook's wrapper, or it calls orig() which
    re-spawns under the SAME deterministic names ("Warbird-1", "Galor-2").
    AddObjectToSet's dict-keyed _objects (engine/appc/sets.py) means that
    replacement doesn't even show up as a bigger count -- it silently
    overwrites the name -> object mapping, so plain ship-count is not enough
    to detect it. Capture the objIDs CreateShip actually produced and assert
    those exact objects are still the ones live in the set afterwards."""
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    import loadspacehelper
    real = loadspacehelper.CreateShip
    created_ids = []

    def recording(ship_file, *a, **k):
        ship = real(ship_file, *a, **k)
        # a = (pSet, pcIdentifier, pcLocationName); skip RecreatePlayer's own
        # CreateShip("Player") call, which is not part of the plan's roster.
        if ship is not None and a[1] != "Player":
            created_ids.append(ship.GetObjID())
        return ship

    monkeypatch.setattr(loadspacehelper, "CreateShip", recording)

    def boom(*_a, **_k):
        raise RuntimeError("placement pass exploded")

    monkeypatch.setattr(spawn, "_cols", boom)
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird", "Galor"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)

    live_ids = sorted(s.GetObjID() for s in _non_player_ships(QB))
    assert len(live_ids) == len(plan.orders) == 2
    assert live_ids == sorted(created_ids), (
        "the ships live in the set after the failure must be the exact objects "
        "created before it raised -- not a second, BC-fallback roster that "
        "silently overwrote them under the same names")


def test_escorts_sit_beside_player_with_players_heading(qb):
    """The player group's own non-player entries (escorts) line abreast
    beside the player -- no fore/aft offset, starboard slot first -- and
    share the player's heading rather than facing it (spec §4.4)."""
    hl, controller, QB = qb
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    from engine.quickbattle import spawn
    s = sc.default_scenario()
    s.delete_group(s.groups[1].id)
    pg = s.player_group()
    s.add_ship(pg.id, "Akira")
    s.add_ship(pg.id, "Nebula")
    plan = sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))
    spawn.set_provider(lambda: plan)
    _start(hl, controller)

    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    pf = player.GetWorldRotation().GetCol(1)
    stbd = player.GetWorldRotation().GetCol(0)
    pp = player.GetWorldLocation()

    escort1, escort2 = _ship("Akira-1"), _ship("Nebula-2")
    assert escort1 is not None and escort2 is not None

    for ship in (escort1, escort2):
        fwd = ship.GetWorldRotation().GetCol(1)
        assert fwd.x * pf.x + fwd.y * pf.y + fwd.z * pf.z > 0.999   # player's heading
        wp = ship.GetWorldLocation()
        d = (wp.x - pp.x, wp.y - pp.y, wp.z - pp.z)
        along_fore = d[0] * pf.x + d[1] * pf.y + d[2] * pf.z
        assert abs(along_fore) < 1e-6                               # no fore/aft offset

    wp1 = escort1.GetWorldLocation()
    d1 = (wp1.x - pp.x, wp1.y - pp.y, wp1.z - pp.z)
    lateral1 = d1[0] * stbd.x + d1[1] * stbd.y + d1[2] * stbd.z
    assert lateral1 > 0                                              # slot 1: starboard first


def test_neutral_group_keeps_players_heading(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("neutral", "port", "close", "medium", ["Transport"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)

    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    pf = player.GetWorldRotation().GetCol(1)
    fwd = _ship("Transport-1").GetWorldRotation().GetCol(1)
    assert fwd.x * pf.x + fwd.y * pf.y + fwd.z * pf.z > 0.999


def _fake_radius_5(ship):
    if ship.GetRadius() <= 0.0:
        ship.SetRadius(5.0)


def _dist(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def test_radius_fn_spaces_a_group_by_seeded_radii(qb):
    """At GenerateShips time nothing is realised yet, so every ship reports
    GetRadius() == 0 unless the registered radius_fn seeds it first. With a
    seeder giving 5 GU, two ships of one group sit >= 5 + 5 + MARGIN_GU apart."""
    hl, controller, QB = qb
    from engine.quickbattle import placement, spawn
    spawn.set_radius_fn(_fake_radius_5)
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird", "Galor"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    a, b = _ship("Warbird-1"), _ship("Galor-2")
    assert a.GetRadius() == 5.0 and b.GetRadius() == 5.0
    assert _dist(a.GetWorldLocation(), b.GetWorldLocation()) >= \
        5.0 + 5.0 + placement.MARGIN_GU - 1e-6


def test_radius_fn_spaces_an_escort_from_the_player(qb):
    hl, controller, QB = qb
    from engine import ship_catalog
    from engine.quickbattle import placement, scenario as sc, spawn
    spawn.set_radius_fn(_fake_radius_5)
    s = sc.default_scenario()
    s.delete_group(s.groups[1].id)
    s.add_ship(s.player_group().id, "Akira")
    plan = sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    assert player.GetRadius() == 5.0
    escort = _ship("Akira-1")
    assert _dist(escort.GetWorldLocation(), player.GetWorldLocation()) >= \
        player.GetRadius() + escort.GetRadius() + placement.MARGIN_GU - 1e-6


def test_no_radius_fn_behaves_as_before(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    spawn.set_radius_fn(None)
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    assert _ship("Warbird-1") is not None
    assert _ship("Warbird-1").GetRadius() == 0.0
