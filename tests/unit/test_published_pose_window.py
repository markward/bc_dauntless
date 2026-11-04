"""Combat reads the tick's published poses inside a read window (native
motion phase 4, Task 4).

The window opens at the motion stage's publish and closes when
host_loop._advance_combat returns (or, in a GameLoop that owns its boundary,
before effect_queue.boundary()). Inside it the combat kernels' pose accessor
(detail::xform) answers from the published copy; outside it -- AI-stage K1
calls, effect handlers, collisions, a headless owns_boundary loop -- it reads
the live transform store. A slot that was not published (a ship spawned after
the publish, a freed and reused slot) reads live inside the window too.

combat_stress with 2 ships, GameLoop(owns_boundary=False), and the host's
whole-tick body (host_loop._run_frame_sim's _whole_tick) called by hand.
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import ai_driver, effect_queue
from engine.appc.ships import ShipClass
from engine.core.loop import TICK_DELTA, GameLoop
from engine.rocks import motion as rock_motion
from tests.helpers import bc_assets, headless_mission

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_motion_published"),
    reason="native combat bindings not built")

MISSION = "engine.dev_missions.combat_stress"
FAR = (500.0, 600.0, 700.0)


@pytest.fixture
def fight(monkeypatch):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    headless_mission.clear_in_flight()
    headless_mission.load(MISSION)
    return GameLoop(owns_boundary=False)


def _whole_tick(loop):
    """The host's whole tick (_run_frame_sim's _whole_tick), by hand."""
    loop.tick()
    ships = list(host_loop._all_ships_for_tick())
    with host_loop._combat_effect_scope():
        host_loop._advance_weapons(ships, TICK_DELTA)
        host_loop._advance_combat(ships, TICK_DELTA, push_render_data=False)
    host_loop._combat_tick_boundary()


def _ship(name):
    for s in App.g_kSetManager.GetSet("QuickBattleRegion")._objects.values():
        if getattr(s, "GetName", None) and s.GetName() == name:
            return s
    raise AssertionError("no ship %r" % name)


def _hex(pose):
    pos, rot = pose
    return [x.hex() for x in pos], [x.hex() for x in rot]


def _live(ship):
    p = ship.GetWorldLocation()
    return _hex(((p.x, p.y, p.z), tuple(ship.GetWorldRotation().as_tuple())))


def _read(ship):
    return _hex(_h.combat_pose_read(ship.__dict__["_nslot"]))


def _published(ship):
    h = ship.__dict__["_nslot"]
    for row_h, pos, rot, _vel in _h.combat_motion_published()[1]:
        if row_h == h:
            return _hex((pos, rot))
    raise AssertionError("%s not published" % ship.GetName())


def _spy(mp, owner, name, before=None, after=None):
    real = getattr(owner, name)

    def wrapper(*a, **k):
        if before is not None:
            before()
        out = real(*a, **k)
        if after is not None:
            after()
        return out
    mp.setattr(owner, name, wrapper)


def test_window_open_from_publish_to_the_end_of_advance_combat(
        fight, monkeypatch):
    seen = []
    _spy(monkeypatch, ai_driver, "tick_all_ai",
         before=lambda: seen.append(("ai", _h.combat_motion_published_open())))
    _spy(monkeypatch, host_loop, "_advance_weapons",
         before=lambda: seen.append(
             ("weapons", _h.combat_motion_published_open())))
    _spy(monkeypatch, host_loop, "_advance_combat",
         after=lambda: seen.append(
             ("after combat", _h.combat_motion_published_open())))
    _whole_tick(fight)
    _whole_tick(fight)
    assert seen == [("ai", False), ("weapons", True),
                    ("after combat", False)] * 2


def test_mid_ai_teleport_seen_by_combat_same_tick(fight, monkeypatch):
    enemy = _ship("Enemy-1")
    _spy(monkeypatch, ai_driver, "tick_all_ai",
         after=lambda: enemy.SetTranslateXYZ(*FAR))
    got = []
    _spy(monkeypatch, host_loop, "_advance_weapons",
         before=lambda: got.append((_read(enemy), _live(enemy))))
    _whole_tick(fight)
    (read, live), = got
    assert read == live
    assert float.fromhex(read[0][0]) > 400.0


def test_mid_combat_teleport_seen_next_tick(fight, monkeypatch):
    enemy = _ship("Enemy-1")
    got = []

    def in_weapons():
        if not got:
            published = _published(enemy)
            enemy.SetTranslateXYZ(*FAR)
            got.append((_read(enemy), published, _live(enemy)))
        else:
            got.append((_read(enemy), _live(enemy)))
    _spy(monkeypatch, host_loop, "_advance_weapons", before=in_weapons)
    _whole_tick(fight)
    read, published, live = got[0]
    assert read == published
    assert read != live
    _whole_tick(fight)
    read, live = got[1]
    assert read == live
    assert float.fromhex(read[0][0]) > 400.0


def test_handler_after_combat_reads_live(fight, monkeypatch):
    """Review Focus 4: a teleport, then a pose read, both in the tick's
    effect delivery (the scope's exit, after _advance_combat): live."""
    enemy = _ship("Enemy-1")
    sentinel = object()
    got = []
    real_deliver = effect_queue._DELIVER

    def fire_sound(bank):
        if bank is not sentinel:
            return real_deliver[effect_queue.FIRE_SOUND](bank)
        enemy.SetTranslateXYZ(*FAR)
        got.append((_h.combat_motion_published_open(), _read(enemy),
                    _live(enemy)))
    deliver = list(real_deliver)
    deliver[effect_queue.FIRE_SOUND] = fire_sound
    monkeypatch.setattr(effect_queue, "_DELIVER", tuple(deliver))

    def post():
        assert effect_queue.deferring()
        effect_queue.post(effect_queue.FIRE_SOUND, sentinel)
    _spy(monkeypatch, host_loop, "_advance_weapons", before=post)
    _whole_tick(fight)
    (is_open, read, live), = got
    assert not is_open
    assert read == live
    assert float.fromhex(read[0][0]) == FAR[0]


def test_kernel_outside_window_reads_live(fight):
    enemy = _ship("Enemy-1")
    _whole_tick(fight)
    published = _published(enemy)
    enemy.SetTranslateXYZ(*FAR)
    assert not _h.combat_motion_published_open()
    assert _read(enemy) == _live(enemy)
    assert _read(enemy) != published


def test_ship_spawned_after_publish_reads_live(fight, monkeypatch):
    got = []

    def spawn():
        ship = ShipClass()
        ship.SetTranslateXYZ(*FAR)
        got.append((_h.combat_motion_published_open(), _read(ship),
                    _live(ship)))
    _spy(monkeypatch, host_loop, "_advance_weapons", before=spawn)
    _whole_tick(fight)
    (is_open, read, live), = got
    assert is_open
    assert read == live


def test_freed_and_reused_slot_reads_live(fight):
    """Enemy-1's published slot is freed and reused (a new generation) by a
    new ship inside the window: the new ship reads its live pose, never
    Enemy-1's published one. Driven by a bare GameLoop tick (the window is
    open after its publish: owns_boundary=False, no combat step) so no stage
    runs on Enemy-1's stale handle afterwards."""
    enemy = _ship("Enemy-1")
    fight.tick()
    assert _h.combat_motion_published_open()
    published = _published(enemy)
    index, generation = enemy._xform
    _h.transform_free(index, generation)
    ship = ShipClass()
    ship.SetTranslateXYZ(*FAR)
    assert ship._xform[0] == index and ship._xform[1] != generation
    assert _read(ship) == _live(ship)
    assert _read(ship) != published
    _h.combat_motion_published_close()


def test_owns_boundary_loop_closes_before_combat(fight, monkeypatch):
    """A GameLoop that owns its boundary (headless drivers: combat runs
    after loop.tick()) closes the window before effect_queue.boundary(), so
    the boundary and everything after the tick read live."""
    seen = []
    _spy(monkeypatch, rock_motion, "tick_all",
         before=lambda: seen.append(
             ("rocks", _h.combat_motion_published_open())))
    _spy(monkeypatch, effect_queue, "boundary",
         before=lambda: seen.append(
             ("boundary", _h.combat_motion_published_open())))
    GameLoop().tick()
    assert seen[:2] == [("rocks", True), ("boundary", False)]
    assert not _h.combat_motion_published_open()
