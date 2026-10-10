"""Per-bridge document -> spot lights (spec §6.2, §11.4)."""
import pytest

from engine.bridge_editor import lighting_doc as ld, lights, profiles


def _doc():
    d = ld.empty_doc("x")
    d["profiles"]["alcove"] = {
        "fade_s": 0.5,
        "green": {"tint": [1, 1, 1], "level": 1},
        "red": {"tint": [1, 0.5, 0.5], "level": 0.5,
                "wave": {"shape": "sine", "period_s": 2.0, "min": 0.2}},
    }
    e = ld.shape_entry(d, 5, "roof")
    e["emitter"] = {"profile": "alcove",
                    "light": {"position": [1, 2, 3], "direction": [0, 0, -1], "intensity": 100}}
    w = ld.shape_entry(d, 6, "lamp")
    w["emitter"] = {"light": {"position": [0, 0, 9], "direction": [0, 0, -1],
                              "inner_deg": 10, "outer_deg": 20, "range": 50,
                              "intensity": 900, "light_scale": 2}}
    return d


def test_to_linear_is_gamma_2_2_and_clamps_negative():
    assert lights.to_linear((1.0, 0.5, -1.0)) == pytest.approx((1.0, 0.5 ** 2.2, 0.0))


def test_no_profile_is_steady_white_with_light_scale():
    spots, warnings = lights.spots(_doc(), {"6:lamp": 0})
    assert spots == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 1800,
                      (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))]
    assert warnings == []


def test_capture_colours_are_the_steady_states_and_zero_when_off_or_pulsing():
    (spot,), _ = lights.spots(_doc(), {"5:roof": 1})
    *_, intensity, cap_green, cap_alert = spot
    assert intensity == 100
    assert cap_green == pytest.approx((1.0, 1.0, 1.0))
    assert cap_alert == (0.0, 0.0, 0.0)          # no yellow state: off


def test_a_pulsing_capture_state_is_zero():
    d = _doc()
    d["profiles"]["alcove"]["yellow"] = d["profiles"]["alcove"]["red"]
    (spot,), _ = lights.spots(d, {"5:roof": 1})
    assert spot[-1] == (0.0, 0.0, 0.0)


def test_off_state_keeps_the_spot_with_zero_colour():
    d = _doc()
    spots, _ = lights.spots(d, {"5:roof": 1, "6:lamp": 2})
    fade = profiles.AlertFade(1)                 # yellow: roof off
    live = lights.live_colours(d, {"5:roof": 1, "6:lamp": 2}, fade, 0.0)
    assert len(live) == len(spots) == 2
    assert live[0] == (0.0, 0.0, 0.0)
    assert live[1] == pytest.approx((1800.0, 1800.0, 1800.0))


def test_live_colour_is_linear_radiance_of_the_evaluated_state():
    fade = profiles.AlertFade(2)
    (c,) = lights.live_colours(_doc(), {"5:roof": 1}, fade, 0.0)   # sine peak: level 0.5
    assert c == pytest.approx(tuple(100 * x for x in lights.to_linear((0.5, 0.25, 0.25))))


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    matched = {}
    for i in range(34):
        ld.shape_entry(d, i, f"s{i}")["emitter"] = {
            "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
        matched[f"{i}:s{i}"] = i
    spots, warnings = lights.spots(d, matched)
    assert len(spots) == 32
    assert len(lights.live_colours(d, matched, profiles.AlertFade(0), 0.0)) == 32
    assert warnings == ["32:s32: dropped (more than 32 bridge lights)",
                        "33:s33: dropped (more than 32 bridge lights)"]
