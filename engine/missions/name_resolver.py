"""Per-family display-name resolution.

Each adapter is wrapped so any exception falls back to the directory
name — a broken TGL or a misnamed module never bricks the picker.
"""
from __future__ import annotations

import importlib
from functools import lru_cache
from pathlib import Path
from typing import Optional

from engine.missions.tgl_reader import read_tgl, TGLFile

PROJECT_ROOT = Path(__file__).parent.parent.parent
TGL_ROOTS: tuple[Path, ...] = (
    PROJECT_ROOT / "sdk" / "Build" / "Data" / "TGL",
    PROJECT_ROOT / "game" / "data" / "TGL",
)


def resolve_family(family_dir: str) -> str:
    return family_dir


def resolve_episode(family_dir: str, episode_dir: str) -> str:
    if family_dir == "Maelstrom":
        m = _match_episode_number(episode_dir)
        if m is not None:
            return _tgl_string(
                "Maelstrom/Maelstrom.tgl", f"Ep{m}Title", episode_dir)
    return episode_dir


def resolve_mission(family_dir: str, episode_dir: str,
                    mission_dir: str, module_name: str) -> str:
    if family_dir == "Multiplayer":
        name_mod = module_name.rsplit(".", 1)[0] + "." + mission_dir + "Name"
        try:
            mod = importlib.import_module(name_mod)
            s = mod.GetMissionName()
        except Exception:
            return mission_dir
        return str(s) if s else mission_dir

    if family_dir == "Maelstrom":
        return _tgl_string(
            "Maelstrom/Maelstrom.tgl", f"{mission_dir}Title", mission_dir)

    if family_dir == "Tutorial":
        return _tgl_string(
            "Tutorial/Tutorial.tgl", mission_dir, mission_dir)

    return mission_dir


def _match_episode_number(episode_dir: str) -> Optional[str]:
    if episode_dir.startswith("Episode") and episode_dir[7:].isdigit():
        return episode_dir[7:]
    return None


@lru_cache(maxsize=None)
def _load_tgl(relpath: str) -> Optional[TGLFile]:
    for root in TGL_ROOTS:
        path = root / relpath
        if path.is_file():
            try:
                return read_tgl(path)
            except Exception:
                return None
    return None


def _tgl_string(relpath: str, key: str, fallback: str) -> str:
    tgl = _load_tgl(relpath)
    if tgl is None:
        return fallback
    value = tgl.strings.get(key)
    if not value:
        return fallback
    return value
