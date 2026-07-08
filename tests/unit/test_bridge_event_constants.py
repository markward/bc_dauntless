"""Bridge-interaction ET_* constants are real distinct ints (spec:
2026-06-12-tg-widget-tree-crew-menus-design.md)."""
import App

BRIDGE_ET_NAMES = [
    "ET_ST_BUTTON_CLICKED", "ET_COMMUNICATE", "ET_HAIL", "ET_SCAN",
    "ET_SET_COURSE", "ET_ALL_STOP", "ET_DOCK", "ET_MANAGE_POWER",
    "ET_MANEUVER", "ET_HAILABLE_CHANGE", "ET_SENSORS_SHIP_IDENTIFIED",
    "ET_CLOAK_COMPLETED", "ET_DECLOAK_COMPLETED", "ET_CHARACTER_MENU",
    "ET_CONTACT_STARFLEET", "ET_ORBIT_PLANET", "ET_AI_ORBITTING",
    "ET_PLAYER_DOCKED_WITH_STARBASE", "ET_TRACTOR_TARGET_DOCKED",
]


def test_bridge_event_constants_are_distinct_ints():
    values = [getattr(App, n) for n in BRIDGE_ET_NAMES]
    assert all(type(v) is int for v in values)
    assert len(set(values)) == len(values)


def test_bridge_event_constants_below_allocator_start():
    # Game_GetNextEventType allocates from 1200 up; static constants must
    # never collide with allocated ids.
    for n in BRIDGE_ET_NAMES:
        assert getattr(App, n) < 1200


def test_character_est_constants():
    from engine.appc.characters import CharacterClass
    # Spot-check the ones the helm/bridge menu files reference.
    assert type(CharacterClass.EST_SET_COURSE_INTERCEPT) is int
    assert CharacterClass.EST_ALERT_GREEN == 0
    assert CharacterClass.EST_SCAN_OBJECT != CharacterClass.EST_SCAN_AREA


def test_character_est_constants_are_distinct():
    from engine.appc.characters import CharacterClass
    values = [v for n, v in vars(CharacterClass).items() if n.startswith("EST_")]
    assert len(values) == 43
    assert len(set(values)) == len(values)
