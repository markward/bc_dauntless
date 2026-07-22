from engine.appc.character_position_zoom import (
    PositionZoomTable, POSITION_ZOOM_SENTINEL,
)


def test_add_and_get_value():
    t = PositionZoomTable()
    t.add_position_zoom("DBHelm", 0.45, "Helm")
    assert t.get_position_zoom("DBHelm") == 0.45


def test_look_at_name_resolves_and_defaults_none():
    t = PositionZoomTable()
    t.add_position_zoom("DBHelm", 0.45, "Helm")
    t.add_position_zoom("EBEngineer", 0.5)          # no zoom_name
    assert t.get_position_look_at_name("DBHelm") == "Helm"
    assert t.get_position_look_at_name("EBEngineer") is None


def test_append_only_if_absent():
    t = PositionZoomTable()
    t.add_position_zoom("DBHelm", 0.45, "Helm")
    t.add_position_zoom("DBHelm", 0.99, "Other")     # BC dedupe: ignored
    assert t.get_position_zoom("DBHelm") == 0.45
    assert t.get_position_look_at_name("DBHelm") == "Helm"


def test_miss_returns_sentinel():
    t = PositionZoomTable()
    assert t.get_position_zoom("nope") == POSITION_ZOOM_SENTINEL
    assert t.get_position_look_at_name("nope") is None
