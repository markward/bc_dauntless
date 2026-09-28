# engine/appc/hull_decals.py
"""Federation hull-name decal resolution (`data/Models/Ships/<Class>/Masks/`).

`feat/hull-name-cut-fix` merges each stock Fed hull's "ID" name patch back
into its saucer, so `ObjectClass.ReplaceTexture(".../Zhukov.tga", "ID")`
matches nothing on a patched model. This module turns that queued
ReplaceTexture into a **decal list**: per registry, per class, a JSON file
(`Masks/decals.json`) declares where a name PNG projects onto the hull in
ship-body space. See `docs/superpowers/specs/2026-09-28-hull-name-decals-design.md`
for the authoring format and the runtime flow this feeds
(`engine/host_loop.py`'s ship-realize call sites -> `renderer.load_model`).

Nothing here can fail a ship load (spec S5): every fault is caught, skips
only the decal(s) it affects, and warns at most once per (path, reason) --
tracked in the module-level `_warned` set, cleared by `reset()` on mission
swap / test teardown, the same pattern as `engine.appc.registry_texture`.
"""
import json
import math
from pathlib import Path
from typing import List, Optional, Tuple

from engine import paths

# (shape, origin, u_axis, v_axis, normal, depth, mask_abs_path) -- exactly the
# positional shape `renderer.load_model(..., decals=)` and the native binding
# (Task 4) expect. Vectors are ship-body-frame 3-tuples; `mask_abs_path` is a
# str (native code takes plain paths, not Path objects).
DecalSpec = Tuple[str, Tuple[float, float, float], Tuple[float, float, float],
                   Tuple[float, float, float], Tuple[float, float, float],
                   float, str]

_MIN_PROJECTOR_AREA = 1e-9

# (path, reason) pairs already warned about this process lifetime. `reason`
# distinguishes independent fault classes on the same path so fixing one
# doesn't silence a still-live other one.
_warned: set = set()


def reset() -> None:
    """Clear the warn-once ledger (mission swap / test teardown)."""
    _warned.clear()


def _warn_once(key: Tuple[str, str], message: str) -> None:
    if key in _warned:
        return
    _warned.add(key)
    print(f"[hull_decals] {message}", flush=True)


def registry_stem(replacements) -> Optional[str]:
    """The registry name (file stem) of the LAST ("ID", path) entry in
    `replacements` -- e.g. [("ID", "Data/.../Zhukov.tga")] -> "Zhukov".

    `replacements` is exactly `registry_texture.replacements_for(ship)`'s
    shape: `[(old_name, new_path), ...]`. Last-write-wins mirrors BC, where
    the final ReplaceTexture("...", "ID") call is the one that sticks.
    Returns None when no "ID" entry is present.
    """
    stem = None
    for old_name, new_path in (replacements or []):
        if old_name == "ID":
            stem = Path(str(new_path)).stem
    return stem


def _as_vec3(value) -> Optional[Tuple[float, float, float]]:
    """A finite (x, y, z) float tuple, or None if `value` isn't one."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        out = (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(c) for c in out):
        return None
    return out


def _cross(a: Tuple[float, float, float], b: Tuple[float, float, float]
           ) -> Tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a: Tuple[float, float, float]) -> float:
    return math.sqrt(_dot(a, a))


def _projector_is_degenerate(
        u_axis: Tuple[float, float, float],
        v_axis: Tuple[float, float, float],
        normal: Tuple[float, float, float]) -> bool:
    """True if `u_axis`, `v_axis` and `normal` don't span a usable 3D basis:
    `u_axis x v_axis` near zero (parallel/zero axes), `normal` near zero
    (normalizing it would divide by zero), or `normal` lying in the
    span(u_axis, v_axis) plane (det([u_axis v_axis normal_hat]) near zero --
    the native decal_body_to_mask's matrix inverse would return inf/NaN).
    Mirrors model_build.cc's decal_projector_is_degenerate exactly, so a
    hand-edited decals.json that would build a bad projector natively is
    already rejected here.
    """
    cross = _cross(u_axis, v_axis)
    cross_len = _length(cross)
    if cross_len <= _MIN_PROJECTOR_AREA:
        return True

    normal_len = _length(normal)
    if normal_len <= _MIN_PROJECTOR_AREA:
        return True

    normal_hat = (normal[0] / normal_len, normal[1] / normal_len,
                  normal[2] / normal_len)
    det = _dot(cross, normal_hat)  # == det([u_axis v_axis normal_hat])
    return abs(det) <= _MIN_PROJECTOR_AREA * cross_len


def decals_for(nif_rel_dir: str, registry: Optional[str]) -> List[DecalSpec]:
    """Resolve `<nif_rel_dir>/Masks/decals.json` for `registry` into decal
    specs ready for `renderer.load_model(..., decals=)`.

    `nif_rel_dir` is the ship model's own BC-relative folder (the NIF's
    parent, relative to the game root -- see `host_loop._ship_texture_search`
    for the same relative-path computation). `registry` is normally
    `registry_stem(registry_texture.replacements_for(ship))`; None (no
    queued "ID" swap) resolves nothing.

    Every fault (spec S5) is caught here and skips only what it affects; a
    missing decals.json is the common case (most classes have none) and is
    silent. Resolution goes through `paths.game_asset`, so mod / project
    overlays apply exactly like every other BC asset.
    """
    if registry is None:
        return []

    json_path = paths.game_asset(f"{nif_rel_dir}/Masks/decals.json")
    if not json_path.is_file():
        return []

    try:
        data = json.loads(json_path.read_text())
    except (OSError, ValueError):
        _warn_once((str(json_path), "parse"),
                    f"{json_path}: could not read/parse decals.json")
        return []

    if not isinstance(data, dict) or data.get("format") != 1:
        got = data.get("format") if isinstance(data, dict) else None
        _warn_once((str(json_path), "format"),
                    f"{json_path}: unsupported decals.json format {got!r} "
                    "(expected 1)")
        return []

    decals = data.get("decals")
    if not isinstance(decals, dict):
        _warn_once((str(json_path), "shape"),
                    f"{json_path}: 'decals' is missing or not an object")
        return []

    out: List[DecalSpec] = []
    for placement, spec in decals.items():
        mask_path = paths.game_asset(
            f"{nif_rel_dir}/Masks/{registry}/{placement}.png")
        if not isinstance(spec, dict):
            _warn_once((str(mask_path), "shape"),
                        f"{json_path}: placement {placement!r} is not an "
                        "object")
            continue

        shape = spec.get("shape")
        origin = _as_vec3(spec.get("origin"))
        u_axis = _as_vec3(spec.get("u_axis"))
        v_axis = _as_vec3(spec.get("v_axis"))
        normal = _as_vec3(spec.get("normal"))
        try:
            depth = float(spec.get("depth"))
        except (TypeError, ValueError):
            depth = float("nan")

        if (not isinstance(shape, str) or not shape or origin is None
                or u_axis is None or v_axis is None or normal is None
                or not math.isfinite(depth) or depth <= 0.0):
            _warn_once((str(mask_path), "invalid"),
                        f"{json_path}: placement {placement!r} has an "
                        "invalid shape/vector/depth")
            continue

        if _projector_is_degenerate(u_axis, v_axis, normal):
            _warn_once((str(mask_path), "degenerate"),
                        f"{json_path}: placement {placement!r} has a "
                        "degenerate projector (u_axis/v_axis parallel or "
                        "zero, or normal doesn't leave their plane)")
            continue

        if not mask_path.is_file():
            _warn_once((str(mask_path), "missing"),
                        f"{mask_path}: registry mask not found for "
                        f"placement {placement!r}")
            continue

        out.append((shape, origin, u_axis, v_axis, normal, depth,
                     str(mask_path)))

    return out
