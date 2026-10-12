"""Meshes -> per-mesh glow (spec 2026-10-08-bridge-emitters §13.2, §14): a
mesh is in the glow table when its resolved material (its object's link,
else its texture's) sets a glow -- a Finish emission level, a State or an
Animation (behaviour.drives_glow); otherwise the texture's default stands.
WHAT glows: the texture's `_emissive` map when it has one, else the
material's `emission_source` (its own texture, or a flat colour)."""
from engine.bridge_editor import behaviour

SRC = {"emission": 0, "texture": 1, "flat": 2}


def glow_objects(doc, resolved, meshes):
    """([(mesh, src, material, has_map)], warnings) in mesh order, from each
    mesh's resolved material (lighting_doc.resolve)."""
    has_map = {m["mesh"]: bool((m.get("maps") or {}).get("emissive")) for m in meshes}
    out = []
    for mesh in sorted(resolved):
        mat = doc["materials"].get(resolved[mesh])
        if mat is None or not behaviour.drives_glow(mat):
            continue
        mapped = has_map.get(mesh, False)
        src = "emission" if mapped else mat.get("emission_source", "texture")
        out.append((mesh, SRC[src], mat, mapped))
    return out, []


def live(objs, fade, t):
    out = []
    for mesh, src, mat, mapped in objs:
        rgb, k = fade.output(mat, t, mapped)
        out.append((mesh, src, tuple(rgb), k))
    return out
