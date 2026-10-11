"""Objects -> per-mesh emitter glow (spec 2026-10-08-bridge-emitters §13.2):
an object glows when its material has an emitter; WHAT glows is the
material's surface resolved against the object's own texture (`auto`: its
emission map if it has one, else its own texture)."""
from engine.bridge_editor import behaviour

SRC = {"emission": 0, "texture": 1, "flat": 2}


def glow_objects(doc, matched, meshes):
    has_map = {m["mesh"]: bool((m.get("maps") or {}).get("emissive")) for m in meshes}
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        name = doc["objects"].get(key, {}).get("material")
        mat = doc["materials"].get(name) if name else None
        if mat is None or not behaviour.has_emitter(mat):
            continue
        mesh = matched[key]
        surface = mat.get("surface", {})
        src = surface.get("src", "auto")
        if src == "none":
            continue
        if src == "auto":
            src = "emission" if has_map.get(mesh) else "texture"
        if src == "emission" and not has_map.get(mesh):
            warnings.append(f"{key}: material {name!r} glows through an emission map but "
                            "this object's texture has none; skipped")
            continue
        out.append((mesh, SRC[src], mat, float(surface.get("strength", 1.0))))
    return out, warnings


def live(objs, fade, t):
    out = []
    for mesh, src, mat, strength in objs:
        rgb, k = fade.output(mat, t)
        out.append((mesh, src, tuple(c * strength for c in rgb), k * strength))
    return out
