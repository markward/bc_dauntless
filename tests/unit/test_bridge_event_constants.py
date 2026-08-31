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
    "ET_SCANNABLE_CHANGE", "ET_NAV_POINT_CHANGED",
]


def test_bridge_event_constants_are_distinct_ints():
    values = [getattr(App, n) for n in BRIDGE_ET_NAMES]
    assert all(type(v) is int for v in values)
    assert len(set(values)) == len(values)


def test_bridge_event_constants_do_not_collide_with_the_dynamic_allocator():
    """Game_GetNextEventType allocates sequential ids from 1200 up for
    ephemeral per-instance event types; static constants must never fall in
    a range that allocator could plausibly reach.

    Before Task 5 (q13 constant-surface sweep) these were our own invented
    numbers, kept below 1200 by construction. Task 5 replaced them with BC's
    real measured values, which live in a completely different, much higher
    band -- BC's smallest real ET_* constant is ET_KEYBOARD = 0x30002 (see
    engine/appc/events.py) -- so the allocator starting at 1200 would need
    hundreds of thousands of calls within a single process to reach it,
    which does not happen in practice.
    """
    for n in BRIDGE_ET_NAMES:
        v = getattr(App, n)
        assert v < 1200 or v >= 0x30000, "%s (%r) collides with the dynamic allocator's plausible range" % (n, v)


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
