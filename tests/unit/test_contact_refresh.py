"""The contact list is re-derived on the sensor sweep and on events, not every
frame; distances are refreshed every frame (perf tier 1, spec
docs/superpowers/specs/2026-11-08-perf-tier1-design.md §2.1 "Contacts").

Each test drives the REAL `host_loop._pump_contacts` with a real target menu,
and counts calls to `perception.perceived_by` (the full re-derivation). A
"rebuild" is one more call; a clean frame is none.

What marks the list dirty (engine/appc/contact_refresh.py): the player's sensor
sweep, a ship's death, a set's contact view changing, a cloak transition, an
identification commit or a lost track, SetPlayer, a target change, and the
player's (menu, player, set) key changing. The current target's
identified / subsystems_targetable are re-checked every frame and a flip
rebuilds in the same frame.
"""
import ast

import pytest

from engine import host_loop
from engine.appc import contact_index, contact_refresh, perception
from engine.appc import sensor_contacts, sensor_identification, sensor_media
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem
from engine.core.game import Game, _set_current_game
from tests.helpers import host_frame_source


def _placed(pSet, name, x):
    s = ShipClass_Create("Galaxy")
    s.SetName(name)
    s.SetTranslateXYZ(float(x), 0.0, 0.0)
    pSet.AddObjectToSet(s, name)
    return s


class _World:
    pass


@pytest.fixture
def world(monkeypatch):
    import App
    contact_index.reset()
    App._reset_target_menu_singleton()
    w = _World()
    w.menu = App.STTargetMenu_CreateW("Targets")
    w.pSet = SetClass()
    w.player = ShipClass_Create("Galaxy")
    w.player.SetName("player")
    w.player.SetTranslateXYZ(0.0, 0.0, 0.0)
    w.sensors = SensorSubsystem("Sensors")
    w.sensors._max_condition = 100.0
    w.sensors._condition = 100.0
    w.sensors.SetBaseSensorRange(2000.0)
    w.player.SetSensorSubsystem(w.sensors)
    w.pSet.AddObjectToSet(w.player, "player")
    w.alpha = _placed(w.pSet, "Alpha", 100.0)
    w.bravo = _placed(w.pSet, "Bravo", 200.0)
    w.alpha.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    w.game = Game()
    w.game.SetPlayer(w.player)
    _set_current_game(w.game)

    w.calls = 0
    real = perception.perceived_by

    def counting(observer):
        w.calls += 1
        return real(observer)
    monkeypatch.setattr(perception, "perceived_by", counting)

    def pump():
        return host_loop._pump_contacts(w.menu, w.player)
    w.pump = pump

    def settle():
        """One rebuild, then a clean frame, then zero the counter."""
        w.pump()
        w.pump()
        w.calls = 0
    w.settle = settle
    yield w
    _set_current_game(None)


# ── Clean frames ────────────────────────────────────────────────────────────

def test_clean_frame_does_not_rederive(world):
    world.pump()
    assert world.calls == 1
    world.pump()
    assert world.calls == 1


def test_clean_frame_updates_distance(world):
    world.settle()
    before = world.menu.surface_gu_to(world.alpha, world.player)
    world.alpha.SetTranslateXYZ(150.0, 0.0, 0.0)
    contacts = world.pump()
    after = world.menu.surface_gu_to(world.alpha, world.player)
    assert world.calls == 0
    assert after == pytest.approx(before + 50.0)
    # The pump still returns the contacts, with the refreshed distance.
    rec = next(c for c in contacts if c.ship is world.alpha)
    assert rec.surface_gu == pytest.approx(after)


def test_clean_frame_keeps_membership_and_posts_nothing(world, monkeypatch):
    world.settle()
    posted = []
    monkeypatch.setattr(type(world.menu), "_post_membership",
                        lambda self, et, ship: posted.append((et, ship)))
    world.pump()
    assert posted == []
    assert world.menu.GetObjectEntry(world.alpha) is not None
    assert world.menu.GetObjectEntry(world.bravo) is not None


def test_refresh_distances_keeps_a_ship_absent_from_the_set():
    from engine.appc.perception import Contact, refresh_distances
    contact_index.reset()
    pSet = SetClass()
    player = _placed(pSet, "player", 0.0)
    here = _placed(pSet, "Here", 100.0)
    gone = ShipClass_Create("Galaxy")
    stale = Contact(ship=gone, surface_gu=12.5, perceivable=True,
                    targetable=True)
    out = refresh_distances(
        (Contact(ship=here, surface_gu=1.0, perceivable=True,
                 targetable=True), stale), player)
    assert out[1] is stale
    assert out[0].surface_gu == pytest.approx(
        perception.measure_surface_gu_to(here, player))


# ── Marks: the next pump rebuilds ───────────────────────────────────────────

def test_sweep_marks_dirty(world):
    world.settle()
    sensor_contacts._sweep(world.player, world.sensors, 0.0)
    world.pump()
    assert world.calls == 1


def test_death_rebuilds_next_frame(world):
    world.settle()
    world.alpha.SetDead()
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(world.alpha) is None


def test_set_removal_rebuilds_next_frame(world):
    world.settle()
    world.pSet.RemoveObjectFromSet("Alpha")
    world.pump()
    assert world.calls == 1
    assert world.menu.contact_for(world.alpha) is None


def test_set_add_rebuilds_next_frame(world):
    world.settle()
    charlie = _placed(world.pSet, "Charlie", 300.0)
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(charlie) is not None


def test_cloak_completed_rebuilds_next_frame(world):
    world.settle()
    world.alpha.GetCloakingSubsystem().InstantCloak()     # ET_CLOAK_COMPLETED
    world.pump()
    assert world.calls == 1


def test_native_cloak_completion_marks_dirty(world):
    """The native cloak piece's completion goes through
    native_subsystems._cloak_done -> the device's _fire."""
    from engine.appc import native_subsystems
    cloak = world.alpha.GetCloakingSubsystem()
    world.settle()
    native_subsystems._cloak_done(world.alpha, 1, 0.0, 0.0, 7, {7: cloak})
    world.pump()
    assert world.calls == 1


def test_decloak_beginning_rebuilds_next_frame(world):
    world.alpha.GetCloakingSubsystem().InstantCloak()
    world.settle()
    world.alpha.GetCloakingSubsystem().StopCloaking()     # ET_DECLOAK_BEGINNING
    world.pump()
    assert world.calls == 1


def test_identification_commit_rebuilds(world):
    world.settle()
    rec = world.menu.contact_for(world.alpha)
    assert rec.identified is False
    assert sensor_identification._identify_one(world.sensors, world.alpha)
    world.pump()
    assert world.calls == 1
    assert world.menu.contact_for(world.alpha).identified is True


def test_lose_track_rebuilds(world):
    world.sensors.AddKnownObject(world.alpha)
    world.settle()
    assert world.menu.contact_for(world.alpha).identified is True
    sensor_contacts._lose_track(world.player, world.sensors, world.alpha)
    world.pump()
    assert world.calls == 1
    assert world.menu.contact_for(world.alpha).identified is False


def test_exited_set_marks_dirty(world):
    world.settle()
    sensor_contacts.on_exited_set(world.pSet, world.alpha)
    world.pump()
    assert world.calls == 1


def test_clear_target_list_rebuilds(world):
    """SDK MissionShared.ClearShips empties the list; rows come back on the
    next push if the ships are still present."""
    world.settle()
    world.menu.ClearTargetList()
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(world.alpha) is not None


def test_set_player_rebuilds(world):
    world.settle()
    world.game.SetPlayer(world.player)
    world.pump()
    assert world.calls == 1


def test_player_set_change_rebuilds(world):
    world.settle()
    other = SetClass()
    world.pSet.RemoveObjectFromSet("player")
    other.AddObjectToSet(world.player, "player")
    contact_refresh.consume()          # no other mark: only the key changed
    contacts = world.pump()
    assert world.calls == 1
    assert contacts == ()


def test_new_menu_rebuilds(world):
    import App
    world.settle()
    App._reset_target_menu_singleton()
    world.menu = App.STTargetMenu_CreateW("Targets")
    contact_refresh.consume()
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(world.alpha) is not None


def test_target_change_rebuilds():
    """run()'s existing target-identity compare marks the list dirty (run()
    cannot execute headless; the call site is pinned by its source)."""
    tree = host_frame_source.run_tree()
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "_last_target_key" not in ast.unparse(node.test):
            continue
        for sub in node.body:
            for call in ast.walk(sub):
                if (isinstance(call, ast.Call)
                        and ast.unparse(call.func) == "contact_refresh.mark_dirty"
                        and [ast.unparse(a) for a in call.args] == ["'target'"]):
                    hits.append(call)
    assert len(hits) == 1


def test_mark_dirty_rebuilds(world):
    world.settle()
    contact_refresh.mark_dirty("target")
    world.pump()
    assert world.calls == 1


# ── The current target is exact every frame ──────────────────────────────────

def test_target_verdict_unchanged_does_not_rebuild(world):
    world.sensors.AddKnownObject(world.alpha)
    world.player.SetTarget(world.alpha)
    world.settle()
    world.pump()
    assert world.calls == 0


def test_target_verdict_flip_rebuilds_same_frame(world, monkeypatch):
    world.sensors.AddKnownObject(world.alpha)
    world.sensors.AddKnownObject(world.bravo)
    world.player.SetTarget(world.alpha)
    world.settle()
    assert world.menu.contact_for(world.alpha).subsystems_targetable is True
    real = sensor_media.subsystems_hidden
    monkeypatch.setattr(
        sensor_media, "subsystems_hidden",
        lambda obj, *, concealment=None: (
            obj is world.alpha or real(obj, concealment=concealment)))
    world.pump()
    assert world.calls == 1
    assert world.menu.contact_for(world.alpha).subsystems_targetable is False
    assert world.menu.contact_for(world.bravo).subsystems_targetable is True


def test_target_verdict_matches_perceived_by(world):
    world.sensors.AddKnownObject(world.alpha)
    for c in perception.perceived_by(world.player):
        assert perception.target_verdict(world.player, c.ship) == (
            c.identified, c.subsystems_targetable)


# ── Reset ──────────────────────────────────────────────────────────────────

def test_reset_mission_state_leaves_dirty(world):
    world.settle()
    host_loop.reset_mission_state(None)
    assert contact_refresh.consume() is True


def test_a_sensorless_player_rebuilds_every_frame(world):
    """No sensor subsystem means no sweep (sensor_contacts.tick returns
    early), so nothing would ever re-derive a range crossing: such a player
    keeps the old every-frame re-derivation."""
    world.player.SetSensorSubsystem(None)
    world.settle()
    sensor_contacts.tick(world.player, 0.0)
    world.pump()
    assert world.calls == 1


# ── Out of action without ship_death (review fix round 1) ──────────────────
#
# targetable = perceivable and (not _out_of_action or is_targetable_wreck),
# and IsDying() = _dying or _life_time < DYING_THRESHOLD. is_targetable_wreck
# only covers ship_death's own entries, so SetDying / SetLifeTime from
# anywhere else (rocks.death, SDK E7M1 / E3M2 SetLifeTime) drops the row.

def test_set_dying_rebuilds_next_frame(world):
    world.settle()
    world.alpha.SetDying(True)
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(world.alpha) is None


def test_set_dying_false_rebuilds_next_frame(world):
    world.alpha.SetDying(True)
    world.settle()
    assert world.menu.GetObjectEntry(world.alpha) is None
    world.alpha.SetDying(False)
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(world.alpha) is not None


def test_set_life_time_rebuilds_next_frame(world):
    world.settle()
    world.alpha.SetLifeTime(4.0)             # SDK E7M1's doomed freighter
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(world.alpha) is None


def test_lifetime_countdown_never_crosses_the_threshold(world):
    """The only per-tick writer of _life_time is object_lifetime.advance, and
    it holds only objects registered BELOW the threshold, so IsDying cannot
    flip by counting down: SetLifeTime is the crossing."""
    from engine.appc import object_lifetime
    from engine.appc.objects import DYING_THRESHOLD
    world.alpha.SetLifeTime(DYING_THRESHOLD * 2.0)
    assert not any(o is world.alpha for o in object_lifetime._timed)
    assert world.alpha.IsDying() == 0


def test_rock_death_rebuilds_next_frame(world):
    import App
    from engine.rocks import death as rock_death
    from tests.unit.test_rock_class import _make
    rock = _make(App.GENUS_ASTEROID)
    rock.SetTranslateXYZ(50.0, 0.0, 0.0)
    world.pSet.AddObjectToSet(rock, "Asteroid 1")
    world.settle()
    assert world.menu.GetObjectEntry(rock) is not None
    contact_refresh.counts.clear()
    rock_death.begin(rock)
    assert contact_refresh.counts.get("dying", 0) >= 1
    world.pump()
    assert world.calls == 1
    assert world.menu.GetObjectEntry(rock) is None
