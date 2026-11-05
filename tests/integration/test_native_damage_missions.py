"""Mission beats that depend on the native-damage semantics (spec
docs/superpowers/specs/2026-11-02-native-damage-design.md §6), each driven
through the real SDK mission script headlessly:

* M1: SetInvincible means "cannot die" -- damage lands. E8M2's Matan and
  E3M1's drill ships are invincible and still take damage; E3M1's
  invincible player takes collision damage.
* M3 + M5: a critical subsystem at 0 kills, at the tick boundary -- E7M1's
  StarbaseCollision and E7M2's DestroyShip kill by SetConditionPercentage
  (hull, 0); E3M5's KillGonDev zeroes a hull, THEN sets the ship invincible,
  and the derelict survives.
* Bug 2: SetConditionPercentage is real -- E8M2's MatanDisableHandler holds
  Matan's systems above disabled.

A headless GameLoop tick is the boundary the death check runs at
(engine/appc/death_check.py), and where a write's events reach their
handlers (native damage M2).

Every beat runs with the native-combat switch off (the Python reference)
and on (the native hit and condition chain), final review M-3.
"""
import sys

import App
import pytest

from engine.appc import combat
from engine.appc import native_combat as nc
from engine.appc.math import TGPoint3
from tests.helpers import headless_mission

E3M1 = "Maelstrom.Episode3.E3M1.E3M1"
E3M5 = "Maelstrom.Episode3.E3M5.E3M5"
E7M1 = "Maelstrom.Episode7.E7M1.E7M1"
E7M2 = "Maelstrom.Episode7.E7M2.E7M2"
E8M2 = "Maelstrom.Episode8.E8M2.E8M2"


@pytest.fixture(autouse=True, params=("off", "on"))
def switch(request, monkeypatch):
    """The native-combat switch, off and on. Each headless GameLoop re-reads
    it (engine/core/loop.py). _load's nc.configure() runs AFTER the mission's
    own creation-time script writes (they happen inside headless_mission.load,
    with native still off), so those are never counted; a beat that wants the
    native chain counted must write after _load. Repairs run in the native
    subsystem stage and are deliberately not counted either. On, the native
    chain must have done some of the work."""
    on = request.param == "on"
    if on and not nc.available():
        pytest.skip("native combat bindings not built")
    monkeypatch.setenv("DAUNTLESS_NATIVE_COMBAT", "1" if on else "0")
    monkeypatch.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
    nc.reset()
    yield request.param
    if on:
        assert nc.enabled()
        counts = nc.damage_counts()
        assert (counts["hits"] + counts["conditions"]
                + counts["damage_systems"]) > 0, counts
    nc.reset()


def _load(name):
    """headless_mission.load on a fresh import of the mission module: its
    globals (E7M1's bStarbaseCollision) would otherwise carry one arm's
    beat into the other's."""
    sys.modules.pop(name, None)
    loaded = headless_mission.load(name)
    nc.configure()
    return loaded


def _ship(set_name, name):
    return App.ShipClass_GetObject(App.g_kSetManager.GetSet(set_name), name)


def _hit_hull(ship, damage, source=None):
    """A weapon hit on `ship`'s hull through the real combat path, its shields
    out of the way (bypass) so the damage reaches the hull."""
    combat.apply_hit(ship, float(damage), ship.GetWorldLocation(), source,
                     weapon_type="phaser", bypass_shields=True)


def _alive(ship):
    return not ship.IsDying() and not ship.IsDead()


# ── E7M1 / E7M2: a scripted hull 0 kills ──────────────────────────────────────

def test_e7m2_destroy_ship_kills_by_a_scripted_hull_zero():
    mission, episode, game, mod = _load(E7M2)
    station = _ship("Albirea3", "Lyra Station")
    assert station is not None and _alive(station)
    mod.DestroyShip(None, station)
    assert station.GetHull().GetCondition() == 0.0
    headless_mission.tick(1.0 / 60.0)
    assert station.IsDying() or station.IsDead()


def test_e7m1_starbase_collision_kills_the_freighter():
    from engine.appc import collisions
    mission, episode, game, mod = _load(E7M1)
    mod.CreateKamikazeFreighters(None)
    starbase = _ship("Starbase12", "Starbase 12")
    freighter = _ship("Starbase12", "Freighter1")
    assert freighter is not None and _alive(freighter)
    # The collision events the engine posts, one per object (collisions.py).
    # E7M1's StarbaseCollision handler calls MissionLib.SetConditionPercentage
    # (hull, 0), which sets the hull's CHILDREN when it has any
    # (MissionLib.py:2293-2301): the freighter's hull carries a critical
    # child hull, and that child at 0 is what kills it (M3).
    collisions._emit_object_collision(starbase, freighter,
                                      starbase.GetWorldLocation(), 1.0)
    assert mod.bStarbaseCollision
    hull = freighter.GetHull()
    zeroed = [hull.GetChildSubsystem(i)
              for i in range(hull.GetNumChildSubsystems())] or [hull]
    assert all(s.GetCondition() == 0.0 for s in zeroed)
    assert any(s.IsCritical() for s in zeroed)
    assert _alive(freighter)                  # not inside the write (M5)
    headless_mission.tick(1.0 / 60.0)
    assert freighter.IsDying() or freighter.IsDead()


# ── E3M5: the derelict survives its creation at hull 0 ───────────────────────

def test_e3m5_gondev_survives_creation_at_hull_zero():
    mission, episode, game, mod = _load(E3M5)
    headless_mission.tick(2.0)
    gondev = _ship("Belaruz4", "Derelict Bird of Prey")
    assert gondev is not None
    assert gondev.GetHull().GetCondition() == 0.0      # KillGonDev's hull 0
    assert gondev.IsInvincible()
    assert _alive(gondev)
    # KillGonDev's creation-time write ran before native was configured. Refill
    # the hull and run it again, now through the native condition chain, so the
    # [on] arm genuinely exercises (and counts) native damage.
    gondev.GetHull().SetCondition(gondev.GetHull().GetMaxCondition())
    assert gondev.GetHull().GetCondition() > 0.0
    mod.KillGonDev(gondev)
    headless_mission.tick(1.0 / 60.0)
    assert gondev.GetHull().GetCondition() == 0.0
    assert gondev.IsInvincible()
    assert _alive(gondev)
    # R5: an invincible hulk keeps its systems (no hull cascade).
    headless_mission.tick(3.0)
    assert _alive(gondev)
    assert gondev.GetSensorSubsystem().GetCondition() > 0.0


# ── E8M2: Matan takes damage, is held above disabled, never dies ─────────────

def test_e8m2_matan_takes_damage_and_never_dies():
    mission, episode, game, mod = _load(E8M2)
    mod.MatanCometh(None)
    matan = _ship("OmegaDraconis3", "Matan's Keldon")
    assert matan is not None and matan.IsInvincible()
    hull = matan.GetHull()
    full = hull.GetCondition()
    _hit_hull(matan, full * 0.5)
    assert hull.GetCondition() < full                   # damage lands (M1)
    _hit_hull(matan, full * 10.0)
    headless_mission.tick(1.0)
    assert hull.GetCondition() == 0.0
    assert _alive(matan)                                # cannot die (M1)


def test_e8m2_matan_disable_handler_holds_his_systems_above_disabled():
    """Before the disable beat (bCanDisableMatan FALSE) MatanDisableHandler
    answers ET_SUBSYSTEM_DISABLED with SetConditionPercentage(disabled +
    0.1): a no-op stub before bug 2, so his systems stayed disabled."""
    mission, episode, game, mod = _load(E8M2)
    mod.MatanCometh(None)
    matan = _ship("OmegaDraconis3", "Matan's Keldon")
    assert not mod.bCanDisableMatan
    impulse = matan.GetImpulseEngineSubsystem()
    assert impulse is not None
    # Just past disabled (a hit to 0 posts ET_SUBSYSTEM_DESTROYED instead,
    # which this handler does not listen for).
    target = impulse.GetDisabledPercentage() - 0.05
    matan.DamageSystem(impulse, impulse.GetCondition()
                       - target * impulse.GetMaxCondition())
    assert impulse.IsDisabled()                 # the write lands at once
    headless_mission.tick(1.0 / 60.0)           # the handler, at the boundary
    assert impulse.GetConditionPercentage() == pytest.approx(
        impulse.GetDisabledPercentage() + 0.1)
    assert not impulse.IsDisabled()


# ── E3M1: the drill knocks invincible ships out; nobody dies ────────────────

def _move_to(ship, set_name):
    old = ship.GetContainingSet()
    name = ship.GetName()
    old.RemoveObjectFromSet(name)
    App.g_kSetManager.GetSet(set_name).AddObjectToSet(ship, name)


def test_e3m1_the_drill_knocks_out_an_invincible_geronimo(monkeypatch):
    """The Geronimo is invincible from creation; its drill AI (the mission's
    GeronimoAttackAI) ends the fight when its hull drops below 25%. Under the
    old "invincible = immune" meaning no hit ever landed."""
    mission, episode, game, mod = _load(E3M1)
    import Maelstrom.Episode3.E3M1.GeronimoAttackAI as geronimo_ai
    knocked = []
    monkeypatch.setattr(mod, "BOPCutscene",
                        lambda bPlayerWinning: knocked.append(bPlayerWinning))
    geronimo = _ship("Starbase12", "USS Geronimo")
    assert geronimo.IsInvincible()
    mod.MakeMacCrayAnEnemy()                # what the drill does first
    geronimo.SetAI(geronimo_ai.CreateAI(geronimo))
    hull = geronimo.GetHull()
    _hit_hull(geronimo, hull.GetMaxCondition() * 0.8,
              source=App.Game_GetCurrentPlayer())
    headless_mission.tick_until(lambda: knocked, bound_s=10.0)
    assert knocked[0] == 1                              # "player winning"
    assert _alive(geronimo)


def test_e3m1_a_knocked_out_ship_is_repaired_and_nobody_dies():
    mission, episode, game, mod = _load(E3M1)
    geronimo = _ship("Starbase12", "USS Geronimo")
    _move_to(geronimo, "Savoy1")                       # where the drill is
    hull = geronimo.GetHull()
    _hit_hull(geronimo, hull.GetMaxCondition() * 10.0)  # far past knocked out
    headless_mission.tick(1.0)
    assert hull.GetCondition() == 0.0
    assert _alive(geronimo)                             # invincible: no death
    mod.EndShipSimulation("USS Geronimo")
    assert hull.GetCondition() == hull.GetMaxCondition()  # repaired
    headless_mission.tick(1.0)
    assert _alive(geronimo) and geronimo.IsInvincible()


def test_e3m1_a_collision_damages_the_invincible_player():
    """StartSimulation makes the player invincible and installs
    PlayerCollisionHandler. A crash still damages the player (the original
    complaint, campaign bug 3), and the player does not die of it."""
    from engine.appc import collisions
    mission, episode, game, mod = _load(E3M1)
    mod.StartSimulation(None)
    player = App.Game_GetCurrentPlayer()
    assert player.IsInvincible()
    rammer = _ship("Starbase12", "USS Excalibur")
    for o in (player, rammer):            # the host realises a hull radius
        if o.GetRadius() <= 0.0:
            o.SetRadius(o.GetHull().GetRadius())
    p = player.GetWorldLocation()
    reach = player.GetRadius() + rammer.GetRadius()
    rammer.SetTranslateXYZ(p.x + reach * 0.5, p.y, p.z)
    rammer.SetVelocity(TGPoint3(-1.0, 0.0, 0.0))
    player.SetVelocity(TGPoint3(1.0, 0.0, 0.0))
    hull = player.GetHull()
    before = hull.GetCondition()
    collisions.resolve_collisions([player, rammer])
    headless_mission.tick(1.0 / 60.0)
    assert hull.GetCondition() < before
    assert player.IsInvincible()                       # the handler re-armed it
    assert _alive(player)
