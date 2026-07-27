from engine.ui.ship_property_viewer import region_spec_to_calls


def _box(orientation=None):
    s = {"shape": "Box", "position": (0.0, 0.0, 0.0), "scale": (0.2, 0.2, 0.05)}
    if orientation is not None:
        s["orientation"] = orientation
    return s


def test_identity_box_emits_no_orientation_call():
    calls = region_spec_to_calls(0, _box())                      # no orientation
    assert not any(c[0] == "SetGlowRegionOrientation" for c in calls)
    calls2 = region_spec_to_calls(0, _box(((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))))  # identity
    assert not any(c[0] == "SetGlowRegionOrientation" for c in calls2)


def test_tilted_box_emits_orientation_call():
    ori = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    calls = region_spec_to_calls(0, _box(ori))
    assert ("SetGlowRegionOrientation", (0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)) in calls
