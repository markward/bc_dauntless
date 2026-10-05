"""E2M1 end-to-end: a major rock on the line of sight hides an already-known
contact for the continuity window, and it is recoverable (sensor
continuity/occlusion spec, Task 6).

Drives the REAL mission module (E2M1.CreateAsteroids / CreateBeolShips build
the Karoon and its asteroid field exactly as the mission does) rather than a
synthetic fixture, so this is the integration proof the unit and
mission-guard tests (test_sensor_occlusion.py, test_sensor_continuity_science.py)
cannot give: BC's own asteroid data satisfies `min_blocker_radius_gu` (every
one of the 16 Beol4 asteroids' `effective_radius`, as `CreateAsteroids`
actually builds them, is >= 2.0 -- checked by instrumenting this test) and
the mission's own Karoon/player objects exercise the whole chain --
can_detect's occlusion gate, the continuity clock, lost track via the real
Helm `ExitedSet`, and recovery via a real scan.

The player boards at Vesuvi6 (`CreateStartingObjects`) while the Karoon lives
in Beol4 (created on demand by `CreateBeolShips`, normally deferred to
`PlayerExitsSet`); moving the player into Beol4 directly is the same
set-reassignment idiom `tests/integration/test_condition_all_in_same_set_live.py`
uses, and it is what puts the player, the Karoon and the asteroid in one set
-- occlusion only ever looks at rocks in the OBSERVER's own set.
"""
import App
import MissionLib
from engine import host_loop
from engine.appc import perception, sensor_contacts
from engine.appc.sensor_detection import can_detect
from tests.integration.test_sdk_bridge_load import _fresh_world

E2M1_MODULE = "Maelstrom.Episode2.E2M1.E2M1"


def _init_e2m1():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E2M1_MODULE)
    return mod


def _move_player_to_beol4(player, beol4):
    old_set = player.GetContainingSet()
    old_set.RemoveObjectFromSet("player")
    beol4.AddObjectToSet(player, "player")


def test_e2m1_karoon_hidden_then_recovered():
    mod = _init_e2m1()
    beol4 = App.g_kSetManager.GetSet("Beol4")
    if beol4.GetObject("Asteroid 3") is None:
        mod.CreateAsteroids()
    if beol4.GetObject("Karoon") is None:
        mod.CreateBeolShips()

    karoon = App.ShipClass_GetObject(beol4, "Karoon")
    rock = App.ShipClass_GetObject(beol4, "Asteroid 3")
    assert karoon is not None and rock is not None

    player = MissionLib.GetPlayer()
    _move_player_to_beol4(player, beol4)

    kx, ky, kz = karoon.GetWorldLocation().x, karoon.GetWorldLocation().y, karoon.GetWorldLocation().z
    player.SetTranslateXYZ(kx + 100.0, ky, kz)   # 100 GU from the Karoon, well inside sensor range
    sensors = player.GetSensorSubsystem()

    # Identify the Karoon up front -- this proves LOSS of an already-known
    # contact, the continuity half of the spec, not first identification.
    sensors.ForceObjectIdentified(karoon)
    assert sensors.IsObjectKnown(karoon) == 1

    # The rock sits exactly on the player-Karoon line (the midpoint), its
    # 12.0 GU effective_radius comfortably engulfing the segment.
    rock.SetTranslateXYZ(kx + 50.0, ky, kz)

    assert can_detect(player, karoon) is False   # blocked outright, not a range question

    for t in range(1000, 1005):
        sensor_contacts.tick(player, float(t))
        assert sensors.IsObjectKnown(karoon) == 1, t   # inside the continuity window

    sensor_contacts.tick(player, 1005.0)
    assert sensors.IsObjectKnown(karoon) == 0   # continuity_window_s (5.0 s) elapsed: lost track

    for t in (1006.0, 1007.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(karoon) == 0

    # Move the rock well clear of the player-Karoon line. A new `tick()` is
    # required before the next `can_detect` to fold a fresh time into
    # `sensor_occlusion`'s cache signature via `begin_tick` -- otherwise the
    # per-(observer, target) cache would still answer from the rock's old
    # position (sensor_occlusion.py's module docstring; see
    # tests/unit/test_sensor_occlusion.py::test_begin_tick_invalidates_cache_on_rock_move).
    rock.SetTranslateXYZ(kx + 50.0, ky + 5000.0, kz + 5000.0)
    sensor_contacts.tick(player, 1008.0)
    assert can_detect(player, karoon) is True

    contacts = [c for c in perception.perceived_by(player) if c.ship is karoon]
    assert len(contacts) == 1 and contacts[0].targetable is True
    assert contacts[0].identified is False   # still Unknown -- not re-identified yet

    # schedule_scan's due time is `now_gt + GetIdentificationTime()`, and
    # `IdentifyObject` (the SDK path) always lets it default to the real
    # `App.g_kUtopiaModule.GetGameTime()` -- which this headless harness never
    # advances (it stays 0.0) -- NOT the synthetic clock this test drives
    # `sensor_contacts.tick` on. So the scan's due time (~`dwell`) is already
    # behind any of this test's t>=1000 values the moment it is scheduled;
    # one more tick is enough to pass it.
    sensors.IdentifyObject(karoon)   # the SDK scan path (Science "Scan Object")
    sensor_contacts.tick(player, 1009.0)
    assert sensors.IsObjectKnown(karoon) == 1   # re-identified after the dwell
