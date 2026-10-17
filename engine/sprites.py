# engine/sprites.py
"""Sprite library: a texture path given to CreateTarget is a NAME for a kind
of effect, resolved to Dauntless-owned art, a stock BC sprite, a native
effect, or nothing (spec 2026-10-16 §7).

Data: native/assets/sprites/manifest.json (entries) and legacy_aliases.json
(folded legacy path / folder prefix -> id). Both resolved at USE and memoised;
an unreadable file means "no library" -- every path passes through unchanged.

Stock entries with "match_stock" carry today's per-texture grid/brightness for
the stock sheets (they replace particles._KNOWN_SHEET_TEXTURES); they match a
caller's path by BASENAME and keep the caller's own path, so production
descriptors are byte-identical. Other stock entries exist only as fallbacks.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from engine import paths

PLAYBACK_CODES = {"life_columns": 0, "life_sequence": 1, "loop": 2}
ORIENT_CODES = {"camera": 0, "emit_dir": 1}

_memo: dict = {}


@dataclass(frozen=True)
class SpriteRef:
    sprite_id: str
    kind: str                 # "sprite" | "native" | "none"
    texture_path: str         # absolute PNG, or a game-relative stock path; "" if not a sprite
    cols: int = 1
    rows: int = 1
    playback: str = "life_columns"
    fps: float = 0.0
    scale: float = 1.0
    brightness: float = 1.0
    pivot: tuple = (0.0, 0.0)
    orient: str = "camera"
    native: Optional[dict] = None


def sprites_root() -> Path:
    return paths.project_asset_root() / "sprites"


def fold_path(p) -> str:
    s = str(p).replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.strip("/").lower()


def reset() -> None:
    _memo.clear()


def _load(name: str) -> dict:
    path = sprites_root() / name
    key = str(path)
    if key not in _memo:
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("top level must be an object")
        except (OSError, ValueError) as e:
            print(f"[sprites] {name} unreadable ({e}); legacy paths pass through",
                  file=sys.stderr)
            data = {}
        _memo[key] = data
    return _memo[key]


def _entries() -> dict:
    s = _load("manifest.json").get("sprites", {})
    return s if isinstance(s, dict) else {}


def _ref(sprite_id: str, entry: dict, texture_path: str) -> SpriteRef:
    grid = entry.get("grid", [1, 1])
    return SpriteRef(
        sprite_id=sprite_id,
        kind=entry.get("kind", "sprite"),
        texture_path=texture_path,
        cols=int(grid[0]), rows=int(grid[1]),
        playback=entry.get("playback", "life_columns"),
        fps=float(entry.get("fps", 0.0)),
        scale=float(entry.get("scale", 1.0)),
        brightness=float(entry.get("brightness", 1.0)),
        pivot=tuple(float(v) for v in entry.get("pivot", [0.0, 0.0])),
        orient=entry.get("orient", "camera"),
        native=entry.get("native"),
    )


def _sprite_ref(sprite_id: str, seen: tuple = ()) -> Optional[SpriteRef]:
    entry = _entries().get(sprite_id)
    if not isinstance(entry, dict):
        return None
    if entry.get("kind", "sprite") != "sprite":
        return _ref(sprite_id, entry, "")
    file_name = entry.get("file")
    if file_name:
        png = sprites_root() / file_name
        if png.is_file():
            return _ref(sprite_id, entry, str(png))
    if entry.get("stock"):
        return _ref(sprite_id, entry, entry["stock"])
    fallback = entry.get("fallback")
    if fallback and fallback not in seen:
        ref = _sprite_ref(fallback, seen + (sprite_id,))
        if ref is not None:
            # The fallback's runtime fields, under our id.
            return replace(ref, sprite_id=sprite_id)
    return None


def resolve_legacy(path) -> Optional[SpriteRef]:
    key = fold_path(path)
    aliases = _load("legacy_aliases.json")
    sprite_id = (aliases.get("exact") or {}).get(key)
    if sprite_id is None:
        best = ""
        for prefix, pid in (aliases.get("prefix") or {}).items():
            if key.startswith(prefix) and len(prefix) > len(best):
                best, sprite_id = prefix, pid
    return _sprite_ref(sprite_id) if sprite_id else None


def stock_ref(path) -> Optional[SpriteRef]:
    base = fold_path(path).rsplit("/", 1)[-1]
    for sprite_id, entry in _entries().items():
        if not (isinstance(entry, dict) and entry.get("match_stock")):
            continue
        if fold_path(entry.get("stock", "")).rsplit("/", 1)[-1] == base:
            return _ref(sprite_id, entry, str(path))
    return None


def resolve(path) -> Optional[SpriteRef]:
    return resolve_legacy(path) or stock_ref(path)
