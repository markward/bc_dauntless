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
from engine.ui import decal_editor

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
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a JSON integer has no size limit (json.loads keeps
        # an arbitrary-precision int), but float() of one too large to
        # represent raises rather than returning inf.
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


_MAX_DECALS = 16
_MAX_DECAL_MASKS = 4


def load_decals_doc(nif_rel_dir: str) -> Optional[dict]:
    """The parsed `<nif_rel_dir>/Masks/decals.json`, or None.

    None covers three cases, only two of which warn: the file doesn't exist
    (silent -- most classes have none), it fails to parse (warn-once,
    reason "parse"), or its "format" isn't 1 (warn-once, reason "format").
    Resolution goes through `paths.game_asset`, so mod / project overlays
    apply exactly like every other BC asset.

    Split out of `decals_for` so `resolve_registry` can see the doc's
    optional "default_registry" *before* a registry is known -- see
    `host_loop._ship_decals` for how the two compose. `decals_for` also
    calls this (re-reading the same file); the warn-once ledger means a
    caller that already loaded the doc via this function and hit a
    parse/format fault won't warn a second time when `decals_for` re-reads
    it.
    """
    json_path = paths.game_asset(f"{nif_rel_dir}/Masks/decals.json")
    if not json_path.is_file():
        return None

    try:
        data = json.loads(json_path.read_text())
    except (OSError, ValueError):
        _warn_once((str(json_path), "parse"),
                    f"{json_path}: could not read/parse decals.json")
        return None

    if not isinstance(data, dict) or data.get("format") != 1:
        got = data.get("format") if isinstance(data, dict) else None
        _warn_once((str(json_path), "format"),
                    f"{json_path}: unsupported decals.json format {got!r} "
                    "(expected 1)")
        return None

    return data


def resolve_registry(replacements, decals_doc: Optional[dict]
                      ) -> Optional[str]:
    """The registry to resolve `Masks/` under, from the first of:

    1. The stem of the last queued `("ID", path)` ReplaceTexture
       (`registry_stem(replacements)`, as today).
    2. `decals_doc`'s optional `"default_registry"` string.
    3. None, meaning no decals for this ship.

    `decals_doc` is normally `load_decals_doc(nif_rel_dir)`'s result (or
    None, e.g. no decals.json at all -- then only (1) can resolve).
    """
    stem = registry_stem(replacements)
    if stem is not None:
        return stem
    if isinstance(decals_doc, dict):
        default = decals_doc.get("default_registry")
        if isinstance(default, str) and default:
            return default
    return None


def decals_for(nif_rel_dir: str, registry: Optional[str]) -> List[DecalSpec]:
    """Resolve `<nif_rel_dir>/Masks/decals.json` for `registry` into decal
    specs ready for `renderer.load_model(..., decals=)`.

    `nif_rel_dir` is the ship's own BC-relative folder, taken from the
    ship script's DECLARED model path (`host_loop.declared_model_dir`) so a
    mod-supplied model (outside `game_root()`) still finds its own Masks/.
    `registry` is normally `resolve_registry(...)`; None (no ID swap and no
    `default_registry`) resolves nothing.

    Every fault (spec S5) is caught here and skips only what it affects; a
    missing decals.json is the common case (most classes have none) and is
    silent. Resolution goes through `paths.game_asset`, so mod / project
    overlays apply exactly like every other BC asset.

    A per-model list of more than `_MAX_DECALS` (16) declared placements is
    truncated to the first 16 (JSON object order), with one warning. Each
    placement's mask defaults to its own name, or an explicit `"mask"` key
    (`<Registry>/<mask>.png`) so several placements can share one texture --
    see `_resolve_mask_name`. At most `_MAX_DECAL_MASKS` (4) DISTINCT masks
    (by resolved path) may back the returned list; a placement that would
    need a 5th is skipped, with one warning, and never occupies a slot --
    matching the native dedupe (spec S2.4a), which the same way never
    counts a placement that native itself would drop. A `registry` for
    which NONE of the declared placements' masks resolve short-circuits to
    no decals with one warning, rather than one missing-mask warning per
    declared placement (this is the common `default_registry`-names-an-
    unpopulated-folder case, but the check itself is registry-source-
    agnostic). `paths.game_asset` is file-keyed (mod/replacement overlays
    index individual files, not directories), so this is a per-file
    existence check, not a directory check -- a directory check would miss
    real content that resolves only through the project-replacements
    overlay. `shape` is optional: a missing or empty value passes through
    as `""` (native side: applies to every mesh it projects onto); any
    other non-string value is invalid.
    """
    if registry is None:
        return []

    data = load_decals_doc(nif_rel_dir)
    if data is None:
        return []

    json_path = paths.game_asset(f"{nif_rel_dir}/Masks/decals.json")

    decals = data.get("decals")
    if not isinstance(decals, dict):
        _warn_once((str(json_path), "shape"),
                    f"{json_path}: 'decals' is missing or not an object")
        return []

    items = list(decals.items())
    if len(items) > _MAX_DECALS:
        _warn_once((str(json_path), "too_many"),
                    f"{json_path}: {len(items)} placements declared, "
                    f"using the first {_MAX_DECALS}")
        items = items[:_MAX_DECALS]

    resolved = []
    for placement, spec in items:
        mask_name = _resolve_mask_name(placement, spec)
        mask_path = (paths.game_asset(
            f"{nif_rel_dir}/Masks/{registry}/{mask_name}.png")
            if mask_name is not None else None)
        resolved.append((placement, spec, mask_name, mask_path))

    if not any(mask_path is not None and mask_path.is_file()
               for _, _, _, mask_path in resolved):
        registry_dir = paths.game_asset(f"{nif_rel_dir}/Masks/{registry}")
        _warn_once((str(registry_dir), "registry_missing"),
                    f"{registry_dir}: registry folder not found (none of "
                    "the declared masks resolved under it)")
        return []

    out: List[DecalSpec] = []
    seen_masks: set = set()
    for placement, spec, mask_name, mask_path in resolved:
        if not isinstance(spec, dict):
            _warn_once((str(mask_path), "shape"),
                        f"{json_path}: placement {placement!r} is not an "
                        "object")
            continue

        if mask_name is None:
            _warn_once((str(json_path), f"mask_invalid:{placement}"),
                        f"{json_path}: placement {placement!r} has an "
                        "invalid 'mask' value")
            continue

        shape_raw = spec.get("shape")
        if shape_raw is None:
            shape = ""
        elif isinstance(shape_raw, str):
            shape = shape_raw
        else:
            shape = None  # invalid type; caught below alongside the vectors

        origin = _as_vec3(spec.get("origin"))
        u_axis = _as_vec3(spec.get("u_axis"))
        v_axis = _as_vec3(spec.get("v_axis"))
        normal = _as_vec3(spec.get("normal"))
        try:
            depth = float(spec.get("depth"))
        except (TypeError, ValueError, OverflowError):
            depth = float("nan")

        if (shape is None or origin is None
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

        mask_key = str(mask_path)
        if mask_key not in seen_masks and len(seen_masks) >= _MAX_DECAL_MASKS:
            _warn_once((str(json_path), "mask_cap"),
                        f"{json_path}: placement {placement!r} needs a "
                        f"{_MAX_DECAL_MASKS + 1}th distinct mask, only "
                        f"{_MAX_DECAL_MASKS} are allowed per model -- "
                        "skipped")
            continue
        seen_masks.add(mask_key)

        out.append((shape, origin, u_axis, v_axis, normal, depth, mask_key))

    return out


def _resolve_mask_name(placement: str, spec) -> Optional[str]:
    """The mask filename stem `placement`'s entry `spec` should resolve
    under `<Registry>/` -- `spec["mask"]` when present and a valid,
    non-empty filename stem, else `placement` itself (spec S2.4a: several
    placements sharing one mask). Returns None when `spec` names an
    explicit `"mask"` that is invalid (non-string, or fails the same
    stem rule as a placement name -- `decal_editor.valid_name`); the
    caller warns and skips that placement. A non-dict `spec` -- or a dict
    with no `"mask"` key, or `"mask": null`/`""` -- falls back to
    `placement` without judgement; `decals_for`'s own "not an object"
    check reports a non-dict `spec` separately.
    """
    if not isinstance(spec, dict):
        return placement
    mask_raw = spec.get("mask")
    if mask_raw is None or mask_raw == "":
        return placement
    if not isinstance(mask_raw, str):
        return None
    if decal_editor.valid_name(mask_raw, []) is not None:
        return None
    return mask_raw
