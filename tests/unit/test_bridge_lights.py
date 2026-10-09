from engine.bridge_editor import lighting_doc as ld, lights


def _doc():
    d = ld.empty_doc("x")
    d["profiles"]["red_bar"] = {
        "green": {"tint": [1, 0.2, 0.1], "level": 0},
        "red": {"tint": [1, 0.1, 0.05], "level": 4},
    }
    e = ld.shape_entry(d, 5, "bar")
    e["emitter"] = {"profile": "red_bar",
                    "light": {"position": [1, 2, 3], "direction": [0, 0, -1]}}
    w = ld.shape_entry(d, 6, "lamp")
    w["emitter"] = {"light": {"position": [0, 0, 9], "direction": [0, 0, -1],
                              "inner_deg": 10, "outer_deg": 20, "range": 50, "intensity": 900}}
    return d


def test_no_profile_is_steady_white():
    spots, warnings = lights.spots(_doc(), {"6:lamp": 0}, alert_level=0)
    assert spots == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 900)]
    assert warnings == []


def test_profile_state_for_the_alert_gives_the_colour():
    spots, _ = lights.spots(_doc(), {"5:bar": 1}, alert_level=2)
    (pos, dirn, inner, outer, rng, colour, intensity), = spots
    assert colour == (4.0, 0.4, 0.2)
    assert (inner, outer, rng, intensity) == (30, 60, 200, lights.DEFAULT_INTENSITY)


def test_missing_state_turns_the_light_off():
    spots, _ = lights.spots(_doc(), {"5:bar": 1}, alert_level=1)   # no yellow state
    assert spots == []


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    matched = {}
    for i in range(34):
        ld.shape_entry(d, i, f"s{i}")["emitter"] = {
            "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
        matched[f"{i}:s{i}"] = i
    spots, warnings = lights.spots(d, matched, alert_level=0)
    assert len(spots) == 32
    assert len(warnings) == 2 and "dropped" in warnings[0]
