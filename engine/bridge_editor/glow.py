"""Meshes -> per-mesh emitter glow (spec 2026-10-08-bridge-emitters §13.2):
a mesh glows when its resolved material (its object's link, else its
texture's) has an emitter. WHAT glows follows the
roughness/metalness rule (Mark 2026-10-11): the object's `_emissive` map
whenever its texture has one, else the material's `without_map` (its own
texture, or a flat colour). Strength 0 glows nothing but still owns the
object's glow (the texture-level default stays off)."""
from engine.bridge_editor import behaviour

SRC = {"emission": 0, "texture": 1, "flat": 2}


def glow_objects(doc, resolved, meshes):
    """([(mesh, src, material, strength)], warnings) in mesh order, from each
    mesh's resolved material (lighting_doc.resolve)."""
    has_map = {m["mesh"]: bool((m.get("maps") or {}).get("emissive")) for m in meshes}
    out = []
    for mesh in sorted(resolved):
        mat = doc["materials"].get(resolved[mesh])
        if mat is None or not behaviour.has_emitter(mat):
            continue
        emission = mat.get("emission", {})
        src = "emission" if has_map.get(mesh) else emission.get("without_map", "texture")
        out.append((mesh, SRC[src], mat, float(emission.get("strength", 1.0))))
    return out, []


def live(objs, fade, t):
    out = []
    for mesh, src, mat, strength in objs:
        rgb, k = fade.output(mat, t)
        out.append((mesh, src, tuple(c * strength for c in rgb), k * strength))
    return out
