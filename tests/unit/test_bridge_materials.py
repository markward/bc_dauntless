"""Object finish overrides from materials (spec §13.2)."""
from engine.bridge_editor import lighting_doc as ld, materials


def test_overrides_come_from_each_objects_material():
    d = ld.empty_doc("x")
    d["materials"]["polished"] = {"roughness": 0.1}
    d["materials"]["metal"] = {"roughness": 0.3, "metalness": 1}
    d["materials"]["glow only"] = {"surface": {"src": "auto"}}
    for b, m in ((1, "polished"), (2, "metal"), (3, "glow only")):
        ld.object_entry(d, b, "x")["material"] = m
    ld.object_entry(d, 4, "x")
    got = materials.overrides(d, {"1:x": 10, "2:x": 11, "3:x": 12, "4:x": 13})
    assert got == [(10, 0.1, -1.0), (11, 0.3, 1.0)]
