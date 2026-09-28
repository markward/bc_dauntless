"""`decals.json` writer and save routing for the Ship Property Viewer's
Decals pane (spec docs/superpowers/specs/2026-09-28-spv-decal-editing-
design.md S2.6).

Masks are PNGs Mark authors externally -- the SPV never writes images, only
the placement geometry in `decals.json`. Two responsibilities:

- `decals_target_path`: where a class's `decals.json` lives -- save where
  the reader reads (see its own docstring for the three-step precedence).
- `write_decals`: the atomic writer, format 1, preserving any unknown
  top-level key already in the file, and refusing to touch a file that
  doesn't already parse as a JSON object.
"""
from __future__ import annotations

import json
import os
import posixpath
from pathlib import Path
from typing import List, Optional

from engine import mods
from engine.ui import decal_editor

# Top-level keys write_decals itself owns. Anything else already in the file
# is preserved verbatim, in its original order, after these.
_KNOWN_KEYS = ("format", "default_registry", "decals")


def decals_target_path(model_rel: str) -> Path:
    """Where `model_rel`'s `Masks/decals.json` should be written.

    `model_rel` is the ship's declared High model as a posix path relative
    to the game root, e.g. "data/Models/Ships/Ambassador/Ambassador.nif"
    (`GetShipStats()["FilenameHigh"]`, the same string
    `host_loop.declared_model_dir` derives its directory from). This
    function needs the file, not just the directory, for step 2 below.

    **Save where the reader reads.** `hull_decals.load_decals_doc` resolves
    `<dir>/Masks/decals.json` via `paths.game_asset`, which checks the
    project replacements overlay first, then installed mods. Routing here
    follows the same three steps, in order, so a save can never land
    somewhere the reader would not find it:

    1. If `<dir>/Masks/decals.json` already exists -- in the replacements
       overlay OR in a mod -- that exact file is the target.
       `mods.game_override` is precisely this check (replacements first,
       then mods, target "game" only).
    2. Else, if a mod supplies the MODEL FILE itself -- an exact
       `mods.current().lookup(model_rel)`, not a directory match -- that
       mod owns the class, so its own `.../Masks/decals.json` is the
       target, even though the file doesn't exist there yet. A mod that
       ships only a texture alongside the model must NOT capture routing:
       only the model file itself, looked up exactly, decides ownership.
    3. Else the class is stock, and the target is the project replacements
       tree, mirroring `tools/gen_mesh_fixes.py`'s own `--decals` output
       location.
    """
    dir_rel = posixpath.dirname(model_rel)
    json_rel = f"{dir_rel}/Masks/decals.json"

    existing = mods.game_override(json_rel)
    if existing is not None:
        return existing

    mf = mods.current().lookup(model_rel)
    if mf is not None and mf.target == "game":  # paths-guard: kind label
        return mf.abs_path.parent / "Masks" / "decals.json"

    return mods.replacements_root() / dir_rel / "Masks" / "decals.json"


def save_decals(model_rel: str, placements: List["decal_editor.Placement"],
                default_registry: Optional[str]) -> Path:
    """The SPV's Save: `write_decals` at `decals_target_path(model_rel)`,
    then make the file visible to the reader (Ruling N). Returns the path.

    `mods.replacements()` and `mods.current()` are cached indexes, so a
    decals.json CREATED by this save (a class's first) would stay invisible
    to `hull_decals.load_decals_doc` until restart. After a successful write:
    a file under the replacements root drops that index (a cheap rescan of
    our own tree); a file in a mod that the mod index doesn't list yet is
    registered into it under the mod that owns the model (the same exact
    lookup `decals_target_path` routed by), rather than re-walking every
    installed mod. `hull_decals.reset()` then clears the reader's warn-once
    ledger so a fault in the new file is reported afresh.

    Raises whatever `write_decals` raises; the indexes are left alone then.
    """
    from engine.appc import hull_decals

    path = decals_target_path(model_rel)
    write_decals(path, placements, default_registry)

    json_rel = f"{posixpath.dirname(model_rel)}/Masks/decals.json"
    try:
        path.relative_to(mods.replacements_root())
        in_replacements = True
    except ValueError:
        in_replacements = False
    if in_replacements:
        mods.invalidate_replacements()
    elif mods.current().lookup(json_rel) is None:
        owner = mods.current().lookup(model_rel)
        if owner is not None:
            mods.register_game_file(json_rel, path, owner.mod_name)
    hull_decals.reset()
    return path


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
    onto `path` (the `.tmp` is unlinked again if `os.replace` itself fails).
    Missing parent directories (a new class's first-ever `Masks/` folder)
    are created. Raises on any failure -- the SPV reports it as a toast;
    this never swallows.

    A missing `path` is fine (nothing to preserve). An EXISTING `path` that
    fails to parse, or that parses to something other than a JSON object,
    raises `ValueError` naming `path` and does NOT touch the file -- the SPV
    keeps its staged edits and lets the player fix or replace the file by
    hand rather than silently clobbering whatever is wrong with it.
    """
    path = Path(path)

    existing = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"{path}: existing decals.json could not be read/parsed "
                f"({exc}) -- refusing to overwrite it") from exc
        if not isinstance(loaded, dict):
            raise ValueError(
                f"{path}: existing decals.json is not a JSON object -- "
                "refusing to overwrite it")
        existing = loaded

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
    try:
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
