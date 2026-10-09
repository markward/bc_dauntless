from engine.bridge_editor import lighting_doc as ld, materials


def test_overrides_from_matched_shapes():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.3}
    ld.shape_entry(d, 7, "rail")["material"] = {"metalness": 1.0}
    ld.shape_entry(d, 9, "plain")
    assert materials.overrides(d, {"3:floor": 4, "7:rail": 1, "9:plain": 2}) == [
        (1, -1.0, 1.0), (4, 0.3, -1.0)]


def test_unmatched_shapes_are_ignored():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.3}
    assert materials.overrides(d, {}) == []
