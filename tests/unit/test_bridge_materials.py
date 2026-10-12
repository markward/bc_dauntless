"""Object finish overrides from materials (spec §13.2)."""
from engine.bridge_editor import lighting_doc as ld, materials


def _links(d, matched):
    """The resolved {mesh: material} for meshes with no texture: links only."""
    return ld.resolve(d, [{"mesh": i} for i in matched.values()], matched)


def test_overrides_come_from_each_objects_material():
    d = ld.empty_doc("x")
    d["materials"]["polished"] = {"roughness": 0.1}
    d["materials"]["metal"] = {"roughness": 0.3, "metalness": 1}
    d["materials"]["glow only"] = {"surface": {"src": "auto"}}
    for b, m in ((1, "polished"), (2, "metal"), (3, "glow only")):
        ld.object_entry(d, b, "x")["material"] = m
    ld.object_entry(d, 4, "x")
    got = materials.overrides(d, _links(d, {"1:x": 10, "2:x": 11, "3:x": 12, "4:x": 13}))
    assert got == [(10, 0.1, -1.0), (11, 0.3, 1.0)]


def test_a_mesh_without_an_object_gets_its_texture_material():
    d = ld.empty_doc("x")
    d["materials"]["Map 13"] = {"roughness": 0.2}
    d["textures"] = {"map 13.tga": "Map 13"}
    meshes = [{"mesh": 7, "block": 70, "name": "p", "textures": ["Map 13.tga"]}]
    assert materials.overrides(d, ld.resolve(d, meshes, {})) == [(7, 0.2, -1.0)]
