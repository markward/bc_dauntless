"""`decals.json` writer and save routing for the Ship Property Viewer's
Decals pane (spec docs/superpowers/specs/2026-09-28-spv-decal-editing-
design.md S2.6).

Masks are PNGs Mark authors externally -- the SPV never writes images, only
the placement geometry in `decals.json`. Two responsibilities:

- `decals_target_path`: where a class's `decals.json` lives -- the mod's own
  `.../Masks/decals.json` when a mod supplies that class's model, else the
  project replacements tree (mirrors `engine.appc.override_routing`'s
  stock/mod split, but keyed on the MODEL FILE rather than a hardpoint leaf).
- `write_decals`: the atomic writer, format 1, preserving any unknown
  top-level key already in the file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from engine import mods
from engine.ui import decal_editor

# Top-level keys write_decals itself owns. Anything else already in the file
# is preserved verbatim, in its original order, after these.
_KNOWN_KEYS = ("format", "default_registry", "decals")


def decals_target_path(nif_rel_dir: str) -> Path:
    """Where `nif_rel_dir`'s `Masks/decals.json` should be written.

    `nif_rel_dir` is the ship's declared model directory, e.g.
    "data/Models/Ships/Ambassador" (see `host_loop.declared_model_dir`).

    If an installed mod supplies any file under `nif_rel_dir/` -- checked via
    `engine.mods`' own directory index, the same one the renderer's asset
    overlay uses -- that mod owns the class's model, so its own
    `.../Masks/decals.json` is the target. Otherwise the class is stock (or
    supplied only by the project replacements overlay, which is not a mod)
    and the target is the project replacements tree, mirroring
    `tools/gen_mesh_fixes.py`'s own `--decals` output location.
    """
    dirs = mods.current().dirs_for(nif_rel_dir)
    if dirs:
        return dirs[0] / "Masks" / "decals.json"
    return mods.replacements_root() / nif_rel_dir / "Masks" / "decals.json"


def write_decals(path: Path, placements: List["decal_editor.Placement"],
                  default_registry: Optional[str]) -> None:
    """Write `path`'s `decals.json`.

    Format: `{"format": 1, "default_registry": ..., "decals": {...}}`, with
    `"default_registry"` present only when `default_registry` is truthy.
    `"decals"` is built fresh from `placements`, keyed by each `p.name` in
    list order and serialised via `decal_editor.to_json_entry` (the single
    source of the entry shape -- see that module). Any top-level key already
    in the file that isn't one of `_KNOWN_KEYS` is preserved, in its
    original order, after them.

    Write is atomic: `path` + ".tmp" is written first, then `os.replace`d
    onto `path`. Missing parent directories (a new class's first-ever
    `Masks/` folder) are created. Raises on any failure -- the SPV reports it
    as a toast; this never swallows.
    """
    path = Path(path)

    existing = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError):
            existing = {}

    doc = {"format": 1}
    if default_registry:
        doc["default_registry"] = default_registry
    doc["decals"] = {p.name: decal_editor.to_json_entry(p) for p in placements}
    for key, value in existing.items():
        if key in _KNOWN_KEYS:
            continue
        doc[key] = value

    text = json.dumps(doc, indent=2) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
