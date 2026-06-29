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

# Authoritative Maelstrom campaign structure, transcribed from the original
# game's hardcoded test/new-game menu builder
# (sdk/Build/scripts/MainMenu/mainmenu.py:BuildTestGamePane). Each episode maps
# to its missions IN MENU ORDER as (on-disk directory, Options.tgl display key).
# The original loads directory <dir> (via ET_<dir> -> RunOverrideMission) but
# labels the row with Options.tgl[<key>] — e.g. directory "E2M0" displays as
# Options.tgl["E2M1"] == "E1M3". Directory order is NOT lexical (Episode4 plays
# E4M6 first), so this table is the source of truth for both order and label.
MAELSTROM_CAMPAIGN: dict[str, list[tuple[str, str]]] = {
    "Episode1": [("E1M1", "E1M1"), ("E1M2", "E1M2")],
    "Episode2": [("E2M0", "E2M1"), ("E2M1", "E2M2"),
                 ("E2M2", "E2M3"), ("E2M6", "E2M4")],
    "Episode3": [("E3M1", "E3M1"), ("E3M2", "E3M2"),
                 ("E3M4", "E3M3"), ("E3M5", "E3M4")],
    "Episode4": [("E4M6", "E4M1"), ("E4M4", "E4M2"), ("E4M5", "E4M3")],
    "Episode5": [("E5M2", "E5M1"), ("E5M4", "E5M2")],
    "Episode6": [("E6M1", "E6M1"), ("E6M2", "E6M2"), ("E6M3", "E6M3"),
                 ("E6M4", "E6M4"), ("E6M5", "E6M5")],
    "Episode7": [("E7M1", "E7M1"), ("E7M2", "E7M2"),
                 ("E7M3", "E7M3"), ("E7M6", "E7M4")],
    "Episode8": [("E8M1", "E8M1"), ("E8M2", "E8M2")],
}


def _maelstrom_key(episode_dir: str, mission_dir: str) -> Optional[str]:
    """Options.tgl display-label key for a Maelstrom mission directory, or
    None if the directory is absent from the campaign table."""
    for d, key in MAELSTROM_CAMPAIGN.get(episode_dir, ()):
        if d == mission_dir:
            return key
    return None


def maelstrom_order_index(episode_dir: str, mission_dir: str) -> int:
    """Position of a Maelstrom mission within its episode's menu order.
    Directories not in the table sort last (sentinel = table length)."""
    episode = MAELSTROM_CAMPAIGN.get(episode_dir, [])
    for i, (d, _key) in enumerate(episode):
        if d == mission_dir:
            return i
    return len(episode)


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
        key = _maelstrom_key(episode_dir, mission_dir)
        if key is None:
            return mission_dir
        return _tgl_string("Options.tgl", key, mission_dir)

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
