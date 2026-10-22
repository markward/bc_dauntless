import pytest

from engine.ui import running_light_editor as rle


def _spec(**kw):
    s = {"name": "Nav", "position": (1, 2, 3), "color": (1, 0.5, 0),
         "radius": 1.0, "period": 3.0, "duration": 0.5}
    s.update(kw)
    return s


def test_validate_normalises():
    out = rle.validate_spec(_spec(name="  Nav "), set())
    assert out["name"] == "Nav"
    assert out["position"] == (1.0, 2.0, 3.0)
    assert all(isinstance(v, float) for v in out["position"] + out["color"])


def test_validate_rejects_taken_name():
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(), {"Nav"})


def test_validate_rejects_empty_name():
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(name="   "), set())


def test_validate_rejects_duration_over_period():
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(period=2.0, duration=2.5), set())


def test_validate_rejects_out_of_range():
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(radius=9.0), set())
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(color=(1.5, 0, 0)), set())
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(period=0.1, duration=0.1), set())
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(duration=0.05), set())


def test_nan_rejected():
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(radius=float("nan")), set())
    with pytest.raises(ValueError):
        rle.validate_spec(_spec(position=(float("inf"), 0, 0)), set())


def test_steady_zeroes_duration():
    out = rle.validate_spec(_spec(duration=-1, period=99.0), set())
    assert out["duration"] == 0.0
    assert out["period"] == 99.0


def test_steady_default_period():
    out = rle.validate_spec(_spec(duration=0), set())
    assert out["duration"] == 0.0
    s = _spec(duration=0)
    del s["period"]
    assert rle.validate_spec(s, set())["period"] == rle.STEADY_PERIOD


def test_mirror_name_swaps_port_star():
    assert rle.mirror_name("Port Dorsal Nav", set()) == "Star Dorsal Nav"
    assert rle.mirror_name("Star Dorsal Nav", set()) == "Port Dorsal Nav"
    assert rle.mirror_name("Starboard Nav", set()) == "Port Nav"


def test_mirror_name_no_swap_numbers():
    assert rle.mirror_name("Dorsal", set()) == "Dorsal 2"
    assert rle.mirror_name("Dorsal", {"Dorsal 2"}) == "Dorsal 3"


def test_mirror_name_numbers_taken_swap():
    taken = {"Port Dorsal Nav Static"}
    assert (rle.mirror_name("Star Dorsal Nav Static", taken)
            == "Port Dorsal Nav Static 2")


def test_default_name_fills_gaps():
    assert rle.default_name(set()) == "Running Light 1"
    assert rle.default_name({"Running Light 1", "Running Light 3"}) == "Running Light 2"


def test_spec_from_property():
    class P3:
        x, y, z = 1.0, 2.0, 3.0

    class C:
        r, g, b, a = 0.1, 0.2, 0.3, 1.0

    class Prop:
        def GetPosition(self): return P3()
        def GetColor(self): return C()
        def GetRadius(self): return 0.7
        def GetPeriod(self): return 4.0
        def GetDuration(self): return 0.25
        def GetName(self): return "Nav"

    assert rle.spec_from_property(Prop()) == {
        "name": "Nav", "position": (1.0, 2.0, 3.0), "color": (0.1, 0.2, 0.3),
        "radius": 0.7, "period": 4.0, "duration": 0.25}
