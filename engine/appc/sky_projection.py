"""Project the sector model into camera-anchored backdrop descriptors.

The in-game sky is a view of the persistent galaxy model from the current
system's position. See docs/superpowers/specs/2026-06-20-map-driven-starsphere-design.md.
"""
import json
import math
import re
import zlib
from functools import lru_cache
from pathlib import Path

_MODEL_PATH = Path(__file__).with_name("sector_model.json")

# Synthetic members folded under one star (mirrors the extractor's SYNTHETIC_SYSTEMS).
_MEMBER_TO_PARENT = {"drydock": "tauceti", "starbase12": "tauceti"}


@lru_cache(maxsize=1)
def load_sector_model():
    try:
        return json.loads(_MODEL_PATH.read_text())
    except (OSError, ValueError):
        return {"systems": [], "nebulae": [], "starclouds": []}


def system_id_for_set(set_name):
    name = set_name.lower()
    if name in _MEMBER_TO_PARENT:
        return _MEMBER_TO_PARENT[name]
    base = re.sub(r"\d+$", "", name)        # "vesuvi6" -> "vesuvi"
    return _MEMBER_TO_PARENT.get(base, base)


def vantage_for_set(pSet, model=None):
    if pSet is None:
        return None
    model = model or load_sector_model()
    sysid = system_id_for_set(pSet.GetName())
    for s in model.get("systems", []):
        if s["id"] == sysid:
            return s["position"]
    return None


# --- projection -----------------------------------------------------------
_SIZE_SCALE = 6.0       # span per (extent/distance) — apparent-size tuning
_MIN_SPAN = 0.08
_ENVELOP_SPAN = 8.0     # near-field: fills the sphere on the existing shader
_REF_DIST = 120.0       # distance-falloff reference
_DEFAULT_COVERAGE = 0.5
_STAR_SEED = 1.0


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _norm(a):
    m = math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2]) or 1.0
    return (a[0]/m, a[1]/m, a[2]/m)


def _basis_from_forward(fwd):
    """Column-major mat3 [right, forward, up] (9 floats) with forward = fwd.
    Patch is radially symmetric, so the roll (right/up) is arbitrary."""
    f = _norm(fwd)
    up_hint = (0.0, 0.0, 1.0) if abs(f[2]) < 0.99 else (0.0, 1.0, 0.0)
    right = _norm(_cross(f, up_hint))
    up = _cross(right, f)
    return [right[0], right[1], right[2], f[0], f[1], f[2], up[0], up[1], up[2]]


def _seed_for(label):
    return (zlib.crc32(label.encode("utf-8")) % 100000) / 1000.0


def _base_starfield():
    return {"texture_path": "", "kind": "star", "h_tile": 1.0, "v_tile": 1.0,
            "h_span": 1.0, "v_span": 1.0,
            "world_rotation": [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0],
            "target_poly_count": 256,
            "proc_kind": "stars", "color": [0.0, 0.0, 0.0], "coverage": 0.0, "seed": _STAR_SEED}


def _project_feature(vantage, pos, extent, color, proc_kind, label):
    d = _sub(pos, vantage)
    dist = math.sqrt(d[0]*d[0] + d[1]*d[1] + d[2]*d[2])
    if dist < 1e-3:
        direction, near = (0.0, 1.0, 0.0), True
    else:
        direction, near = (d[0]/dist, d[1]/dist, d[2]/dist), dist < extent
    if near:
        span = _ENVELOP_SPAN
        coverage = min(1.0, _DEFAULT_COVERAGE * 2.0)
        col = list(color)
    else:
        span = max(_MIN_SPAN, min(_ENVELOP_SPAN, _SIZE_SCALE * extent / dist))
        falloff = max(0.15, min(1.0, _REF_DIST / dist))
        col = [c * falloff for c in color]
        coverage = _DEFAULT_COVERAGE
    return {"texture_path": "", "kind": "backdrop", "h_tile": 1.0, "v_tile": 1.0,
            "h_span": span, "v_span": span,
            "world_rotation": _basis_from_forward(direction),
            "target_poly_count": 256,
            "proc_kind": proc_kind, "color": col, "coverage": coverage,
            "seed": _seed_for(label)}


def project_sky(vantage, model):
    out = [_base_starfield()]
    for i, n in enumerate(model.get("nebulae", [])):
        out.append(_project_feature(vantage, n["position"], n["radius"], n["color"],
                                    "nebula", "neb%d" % i))
    for i, g in enumerate(model.get("starclouds", [])):
        out.append(_project_feature(vantage, g["position"], g["size"], g["color"],
                                    "starcloud", "sc%d" % i))
    return out
