"""Per-bridge document -> per-shape emitter glow (spec 2026-10-08-bridge-
emitters §11.2): which meshes glow and from what (static, rebuilt on a
document change), and the evaluated colour each frame (live)."""
from engine.bridge_editor import profiles

SRC = {"emissive": 0, "texture": 1, "flat": 2}


def glow_shapes(doc, matched, meshes):
    """([(mesh, src_code, profile, phase, scale)], warnings) in mesh order.
    `meshes` is model_identity's list; `src: emissive` on a mesh whose
    material has no _emissive map is skipped with a warning naming it."""
    has_map = {m["mesh"]: bool(m.get("maps", {}).get("emissive")) for m in meshes}
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        e = doc["shapes"].get(key, {}).get("emitter") or {}
        g = e.get("glow")
        if g is None:
            continue
        mesh = matched[key]
        if g["src"] == "emissive" and not has_map.get(mesh, False):
            warnings.append(f"{key}: glow src 'emissive' but its albedo has no "
                            "_emissive map; skipped")
            continue
        out.append((mesh, SRC[g["src"]], profiles.profile_of(doc, e),
                    float(e.get("phase", 0.0)), float(g.get("scale", 1.0))))
    return out, warnings


def live(shapes, fade, t):
    """[(mesh, src_code, (r, g, b), level)] this frame: rgb = tint x level x
    wave x scale (display space); level = level x wave x scale (the
    received-light dip)."""
    out = []
    for mesh, src, prof, phase, scale in shapes:
        rgb, k = fade.output(prof, t, phase)
        out.append((mesh, src, tuple(c * scale for c in rgb), k * scale))
    return out
