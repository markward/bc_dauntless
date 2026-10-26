"""The Tau Ceti shuttle service in every mode: a Quick Battle in Tau Ceti
(a battle is a simulation: what it damaged or destroyed comes back docked,
and nothing is recorded as lost), free roam arriving at Starbase 12, and the
E1M1 tutorial loading and running with the service present.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.helpers import headless_mission as hm  # noqa: E402
from tests.integration.test_home_stations_free_roam import (  # noqa: E402
    _warp_to_starbase_12)
from tests.integration.test_home_stations_quickbattle import (  # noqa: E402
    _end, _into_region)
from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, world)

_NAMES = ["SB12 Shuttle %d" % i for i in range(1, 11)]


def _ss():
    from engine.systems import shuttle_service
    return shuttle_service


def _wrapped(fn) -> bool:
    """`fn` or a function it wraps carries the service's marker."""
    from engine.quickbattle.sim_restore import _chain
    return any("_dauntless_shuttle_service_orig" in getattr(f, "__dict__", {})
               for f in _chain(fn))


def _objects_named(name):
    import App
    return [pSet.GetObject(name) for pSet in App.g_kSetManager.GetAllSets()
            if pSet.GetObject(name) is not None]


def _into_set(s, set_name):
    """Shuttle `s`, launched, moved into `set_name` at its own lane point
    (the way its warp leaves it)."""
    import App
    ss = _ss()
    if s.ship is None:
        ss._launch(s)
    ss._release_bay(s)
    ship = s.ship
    held = ship.GetContainingSet()
    dest = App.g_kSetManager.GetSet(set_name)
    if held is not dest:
        held.RemoveObjectFromSet(s.name)
        dest.AddObjectToSet(ship, s.name)
    ship.SetTranslate(dest.GetObject(ss._lane_name(s)).GetWorldLocation())
    ship.UpdateNodeOnly()
    ss._enter(s, ss.Phase.TO_DOCK)


def _kill(ship, killer):
    from engine.appc import combat, ship_death
    combat.apply_hit(ship, 1.0e6, ship.GetWorldLocation(), killer,
                     weapon_type="phaser")
    assert ship.IsDying() or ship.IsDead()
    ship_death.advance(ship_death.MAX_THROES_DURATION + 0.1)
    assert ship.IsDead()


def test_a_battle_in_tau_ceti_restores_shuttles_docked_and_records_nothing(
        world, capsys):
    hl, _c, panel, QB = world
    import App
    from tests.helpers.mapped_regions import load_region
    ss = _ss()
    assert _wrapped(QB.StartSimulation2) and _wrapped(QB.EndSimulation)
    home = _into_region("TauCeti", "Starbase12")
    load_region("TauCeti", "DryDock")
    hm.tick(1.0)
    r = ss.roster()
    assert len(r) == 10 and r[0].ship is not None
    hit, grazed, killed, idle = r[0], r[1], r[2], r[3]
    ss._launch(grazed)
    _into_set(killed, "DryDock")
    _into_set(idle, "DryDock")
    assert hit.ship.GetContainingSet() is home
    assert grazed.ship.GetContainingSet() is home
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert QB.g_pSet is home
    warbird = home.GetObject("Warbird-1")
    old_hit, grazed_ship, old_killed, idle_ship = (
        hit.ship, grazed.ship, killed.ship, idle.ship)
    # Hull damage: docked at the end. A shield-only graze is not damage.
    hull = old_hit.GetHull()
    hull.SetCondition(hull.GetCondition() * 0.5)
    shields = grazed_ship.GetShields()
    assert shields.GetCurShields(0) > 0.0
    shields.SetCurShields(0, shields.GetCurShields(0) * 0.5)
    _kill(old_killed, warbird)
    assert killed.phase is ss.Phase.LOST
    assert ss.losses() == []
    _end(hl, QB)
    out = capsys.readouterr().out
    assert "[sim-restore]" not in out and "[shuttles]" not in out
    assert ss.losses() == []
    for s in (hit, killed):
        assert s.phase is ss.Phase.DOCKED and s.ship is None, s.name
    for s, ship in ((grazed, grazed_ship), (idle, idle_ship)):
        assert s.ship is ship and s.phase is not ss.Phase.DOCKED, s.name
    # R1: one object per shuttle index across every set, and no record
    # pointing at an object out of the world.
    for name in _NAMES:
        assert len(_objects_named(name)) <= 1, name
    sets = App.g_kSetManager.GetAllSets()
    for s in r:
        if s.phase is ss.Phase.DOCKED:
            continue
        pSet = s.ship.GetContainingSet()
        assert any(x is pSet for x in sets), s.name
        assert pSet.GetObject(s.name) is s.ship, s.name
    for old in (old_hit, old_killed):
        assert old.GetContainingSet() is None
    # The service carries on after the battle.
    hm.tick(1.0)
    assert "[shuttles]" not in capsys.readouterr().out


def test_free_roam_warp_to_starbase_12_finds_the_service_running(world):
    _hl, _c, _panel, QB = world
    from engine.systems import owners
    ss = _ss()
    assert _wrapped(QB.EndSimulation)
    player = _warp_to_starbase_12()
    # What the host's frame does on arrival in a system (headless ticks do
    # not): build every region of it, so the Dry Docks set exists too.
    from engine.systems import system_loader
    system_loader.ensure_loaded(player)
    hm.tick(2.0)
    r = ss.roster()
    assert [s.name for s in r] == _NAMES
    first = r[0]
    assert first.phase is not ss.Phase.DOCKED
    assert first.ship.GetContainingSet() is player.GetContainingSet()
    owner, key = owners.owner_of(first.ship)
    assert (owner.name, key) == ("tau_ceti_shuttles", 1)


def test_e1m1_runs_with_shuttles_circling_the_dry_docks(monkeypatch, capsys):
    """E1M1 ends the mission on any non-player death in DryDock (SDK
    E1M1.py:993-1000; accepted, spec §6). With the service running, shuttles
    reach the Dry Docks and circle there (first arrival ~105 s, circling
    ~145 s) for the run, with no exception and no GameOver."""
    hm.load("Maelstrom.Episode1.E1M1.E1M1")
    import MissionLib
    over = []
    real = MissionLib.GameOver
    monkeypatch.setattr(MissionLib, "GameOver",
                        lambda *a: over.append(a) or real(*a))
    ss = _ss()
    in_dry_dock, circling = set(), set()
    for _ in range(210):
        hm.tick(1.0)
        for s in ss.roster():
            pSet = None if s.ship is None else s.ship.GetContainingSet()
            if pSet is not None and pSet.GetName() == "DryDock":
                in_dry_dock.add(s.name)
                if s.phase is ss.Phase.CIRCLING:
                    circling.add(s.name)
    assert len(ss.roster()) == 10
    assert in_dry_dock, "no shuttle reached the Dry Docks in 210 s"
    assert circling, "no shuttle circled a dry dock in 210 s"
    assert ss.losses() == []
    assert over == []
    assert not MissionLib.g_bFFGameOver
    assert "[shuttles]" not in capsys.readouterr().out


def test_e8m2_runs_with_every_shuttle_docked(capsys):
    """R9: E8M2's EnterSet targets, for the player, every ship but the Chairo
    that enters Starbase12 before Omega Draconis 5 (SDK E8M2.py:1533-1537),
    so the service stays out of E8M2: with Tau Ceti built, no shuttle ever
    launches and the player's target is never a shuttle."""
    import App
    hm.load("Maelstrom.Episode8.E8M2.E8M2")
    from engine.systems import system_loader
    ss = _ss()
    player = App.Game_GetCurrentPlayer()
    assert player.GetContainingSet().GetName() == "Starbase12"
    system_loader.ensure_loaded(player)
    assert App.g_kSetManager.GetSet("DryDock") is not None
    targets = set()
    for _ in range(90):
        hm.tick(1.0)
        target = player.GetTarget()
        if target is not None:
            targets.add(target.GetName())
    assert not targets & set(_NAMES), targets
    assert len(ss.roster()) == 10
    assert all(s.phase is ss.Phase.DOCKED and s.ship is None
               for s in ss.roster())
    for name in _NAMES:
        assert _objects_named(name) == [], name
    assert "[shuttles]" not in capsys.readouterr().out
