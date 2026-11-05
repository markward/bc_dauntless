"""Target list: no expansion; distance, side filter and sort (Task 3)."""
import json

import App
from engine.appc.perception import Contact
from engine.appc.ships import ShipClass
from engine.units import GU_TO_KM
from tests.helpers.native_off import native_switch_zero  # noqa: F401
from tests.unit.test_target_list_view import _setup_game_with_player


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _setup(specs):
    """specs: list of (name, side, surface_gu). Returns (view, player, ships)."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    ships, contacts = {}, []
    for name, side, gu in specs:
        s = _ship(name)
        ships[name] = s
        if side == "FRIENDLY":
            mission.GetFriendlyGroup().AddName(name)
        elif side == "ENEMY":
            mission.GetEnemyGroup().AddName(name)
        elif side == "NEUTRAL":
            mission.GetNeutralGroup().AddName(name)
        contacts.append(Contact(ship=s, surface_gu=gu,
                                perceivable=True, targetable=True))
    menu.set_contacts(contacts)
    menu.ResetAffiliationColors()
    return TargetListView(), player, ships


def _state(view):
    script = view.render_payload()
    assert script is not None
    return json.loads(script[len("setTargetList("):-2])


def _labels(state):
    return [r["label"] for r in state["rows"]]


def _teardown():
    from engine.core.game import _set_current_game
    _set_current_game(None)


def test_default_sort_is_name_and_all_filters_on():
    view, _p, _s = _setup([("USS Venture", "FRIENDLY", 5.0),
                           ("Keldon 1", "ENEMY", 3.0),
                           ("galor 2", "ENEMY", 9.0)])
    try:
        st = _state(view)
        assert st["sort"] == "name"
        assert st["filters"] == {"FRIENDLY": True, "NEUTRAL": True, "ENEMY": True}
        assert _labels(st) == ["galor 2", "Keldon 1", "USS Venture"]
    finally:
        _teardown()


def test_sort_distance_closest_first_ties_by_name():
    view, _p, _s = _setup([("Far", "ENEMY", 50.0), ("Bravo", "ENEMY", 5.0),
                           ("Alpha", "ENEMY", 5.0), ("Mid", "ENEMY", 20.0)])
    try:
        assert view.dispatch_event("__sort__/distance") is True
        st = _state(view)
        assert st["sort"] == "distance"
        assert _labels(st) == ["Alpha", "Bravo", "Mid", "Far"]
    finally:
        _teardown()


def test_sort_health_hull_then_shields_then_name_shieldless_counts_zero():
    import engine.ui.target_list_view as tlv
    view, _p, _s = _setup([("A", "ENEMY", 1.0), ("B", "ENEMY", 1.0),
                           ("C", "ENEMY", 1.0), ("D", "ENEMY", 1.0),
                           ("Rock", "NEUTRAL", 1.0)])
    hull = {"A": 100, "B": 100, "C": 64, "D": 23, "Rock": 100}
    shields = {"A": 95, "B": 30, "C": 10, "D": 10, "Rock": 100}
    has = {"A": True, "B": True, "C": True, "D": True, "Rock": False}
    orig = (tlv._query_hull_percentage, tlv._query_shield_percentage,
            tlv._query_has_shields)
    try:
        tlv._query_hull_percentage = lambda s: hull[s.GetName()]
        tlv._query_shield_percentage = lambda s: shields[s.GetName()]
        tlv._query_has_shields = lambda s: has[s.GetName()]
        view.dispatch_event("__sort__/health")
        assert _labels(_state(view)) == ["D", "C", "Rock", "B", "A"]
    finally:
        (tlv._query_hull_percentage, tlv._query_shield_percentage,
         tlv._query_has_shields) = orig
        _teardown()


def test_filter_hides_a_side_and_unknown_always_shows():
    view, _p, _s = _setup([("Friend", "FRIENDLY", 1.0), ("Foe", "ENEMY", 1.0),
                           ("Mystery", None, 1.0)])
    try:
        before = _state(view)
        assert {r["label"]: r["affiliation"] for r in before["rows"]}[
            "Mystery"] == "UNKNOWN"
        assert view.dispatch_event("__filter__/ENEMY") is True
        st = _state(view)
        assert st["filters"]["ENEMY"] is False
        assert _labels(st) == ["Friend", "Mystery"]
        assert view.dispatch_event("__filter__/ENEMY") is True
        assert _state(view)["filters"]["ENEMY"] is True
    finally:
        _teardown()


def test_every_side_hidden_leaves_empty_rows_not_an_error():
    view, _p, _s = _setup([("Friend", "FRIENDLY", 1.0), ("Foe", "ENEMY", 1.0),
                           ("Rock", "NEUTRAL", 1.0)])
    try:
        for side in ("FRIENDLY", "NEUTRAL", "ENEMY"):
            assert view.dispatch_event("__filter__/" + side) is True
        st = _state(view)
        assert st["rows"] == []
        assert st["filters"] == {"FRIENDLY": False, "NEUTRAL": False,
                                 "ENEMY": False}
    finally:
        _teardown()


def test_dist_km_is_surface_distance_in_km_rounded_2dp():
    view, _p, _s = _setup([("Far", "ENEMY", 123.456)])
    try:
        row = _state(view)["rows"][0]
        assert row["dist_km"] == round(123.456 * GU_TO_KM, 2)
    finally:
        _teardown()


def test_filter_and_sort_events_do_not_retarget():
    view, player, ships = _setup([("Foe", "ENEMY", 1.0)])
    try:
        player.SetTarget("Foe")
        target = player.GetTarget()
        view.dispatch_event("__filter__/ENEMY")
        view.dispatch_event("__sort__/health")
        assert player.GetTarget() is target
    finally:
        _teardown()


def test_unknown_sort_or_filter_is_refused():
    view, _p, _s = _setup([("Foe", "ENEMY", 1.0)])
    try:
        assert view.dispatch_event("__sort__/bogus") is False
        assert view.dispatch_event("__filter__/BOGUS") is False
        st = _state(view)
        assert st["sort"] == "name"
        assert st["filters"] == {"FRIENDLY": True, "NEUTRAL": True, "ENEMY": True}
    finally:
        _teardown()


def test_rows_carry_no_subsystem_tree():
    view, _p, _s = _setup([("Foe", "ENEMY", 1.0)])
    try:
        row = _state(view)["rows"][0]
        for key in ("subsystems", "expanded", "has_subsystems"):
            assert key not in row
        assert set(row) == {"name", "label", "affiliation", "hull", "shields",
                            "has_shields", "dist_km", "marker"}
    finally:
        _teardown()


def test_sort_key_shapes():
    from engine.ui.target_list_view import sort_key, SORTS, FILTERABLE
    assert SORTS == ("name", "distance", "health")
    assert FILTERABLE == ("FRIENDLY", "NEUTRAL", "ENEMY")
    row = {"label": "Zed", "dist_km": 4.0, "hull": 50, "shields": 70,
           "has_shields": False}
    assert sort_key(row, "name") == (("zed",),)
    assert sort_key(row, "distance") == (4.0, ("zed",))
    assert sort_key(row, "health") == (50, 0, ("zed",))


def test_sort_key_orders_names_naturally():
    from engine.ui.target_list_view import sort_key
    def row(label):
        return {"label": label, "dist_km": 0.0, "hull": 1.0,
                "shields": 0.0, "has_shields": False}
    names = ["Unknown 10", "unknown 2", "Unknown 1", "Alpha"]
    for sort in ("name", "distance", "health"):
        got = sorted(names, key=lambda n: sort_key(row(n), sort))
        assert got == ["Alpha", "Unknown 1", "unknown 2", "Unknown 10"], sort
