"""Meshes -> per-mesh glow (spec 2026-10-08-bridge-emitters §13.2, §14): a
mesh is in the glow table when its resolved material (its object's link,
else its texture's) sets a glow -- a Finish emission level, a State or an
Animation (behaviour.drives_glow); otherwise the texture's default stands.
WHAT glows: the texture's `_emissive` map when it has one, else the
material's `emission_source` (its own texture, or a flat colour)."""
from engine.bridge_editor import behaviour

SRC = {"emission": 0, "texture": 1, "flat": 2}


class GlowObject(tuple):
    """(mesh, src, material, has_map), unpackable as before, that also knows
    the NAME of its material (`.name`) -- captures() asks the probe plan by
    name."""
    name = None


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
        obj = GlowObject((mesh, SRC[src], mat, mapped))
        obj.name = resolved[mesh]
        out.append(obj)
    return out, []


def live(objs, fade, t):
    out = []
    for mesh, src, mat, mapped in objs:
        rgb, k = fade.output(mat, t, mapped)
        out.append((mesh, src, tuple(rgb), k))
    return out


def captures(objs, plan):
    """What each glow shape contributes to the probes (spec 2026-10-17 §4.5):
    [(mesh, src, caps5, layers5, layer_rgbs5)] in `objs` order, state order,
    DISPLAY space (C++ decodes). caps5[i] = the steady output, 0 where the
    material animates in that state; layer_rgbs5[i] = the at-peak output for
    a kept layer. `objs` = glow_objects output (each knows its material
    name)."""
    out = []
    zero = (0.0, 0.0, 0.0)
    for obj in objs:
        mesh, src, mat, mapped = obj
        name = obj.name
        caps, layers, rgbs = [], [], []
        for state in sorted(behaviour.STATES, key=behaviour.state_index):
            animated = plan.animated(name, state)
            rgb, _ = behaviour.output(mat, state, 0.0, mapped)
            caps.append(zero if animated else tuple(rgb))
            layer = plan.layer_of(name, state)
            layers.append(layer)
            if layer >= 0:
                peak, _ = behaviour.output(mat, state, 0.0, mapped, waves=False)
                rgbs.append(tuple(peak))
            else:
                rgbs.append(zero)
        out.append((mesh, src, caps, layers, rgbs))
    return out
