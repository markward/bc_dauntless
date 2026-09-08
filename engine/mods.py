"""Where the player's installed mods live, and what they provide.

A mod is a BC-shaped tree the player drops into mods/. Nothing here ever
writes, copies, or symlinks: the index answers "who provides this file?"
and the stock roots answer everything else.

HARD RULE -- like engine/paths.py, paths resolve at USE, never at import.

Spec: docs/superpowers/specs/2026-09-08-mod-overlay-design.md
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine import paths

# Top-level directories inside a mod that we know how to place. Lowercase
# because every comparison here is case-folded.
CONTENT_DIRS = frozenset({"data", "scripts"})

CLI_FLAG = "--mods-dir"
ENV_VAR = "DAUNTLESS_MODS_DIR"


@dataclass(frozen=True)
class ModCandidate:
    """One subdirectory of the mods root, before its files are indexed."""
    name: str
    mod_dir: Path
    content_root: Optional[Path]


def mods_root(argv=None, env=None) -> Path:
    """Where mods live. CLI flag, then env, then PROJECT_ROOT/mods.

    Deliberately simpler than paths.resolve(): there is no settings tier and
    no validation, because an absent or empty mods root is not an error --
    it just means no mods.
    """
    import sys

    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ

    flag = paths._flag_value(argv, CLI_FLAG)
    if flag is not paths._UNSET and str(flag).strip():
        return paths.normalise(flag)

    from_env = env.get(ENV_VAR)
    if from_env:
        return paths.normalise(from_env)

    return paths.PROJECT_ROOT / "mods"


def find_content_root(mod_dir: Path, max_depth: int = 3) -> Optional[Path]:
    """The directory inside `mod_dir` that holds Data/ and/or Scripts/.

    Archives are inconsistent: some extract to <mod>/{Data,Scripts}, others
    add a redundant <mod>/<name>/ level. Descend only while the answer is
    unambiguous -- exactly one subdirectory and no content dir here.
    """
    current = mod_dir
    for _ in range(max_depth + 1):
        try:
            entries = [e for e in current.iterdir() if e.is_dir()]
        except OSError:
            return None
        if any(e.name.lower() in CONTENT_DIRS for e in entries):
            return current
        if len(entries) != 1:
            return None
        current = entries[0]
    return None


def discover_mods(root: Path) -> list[ModCandidate]:
    """Every immediate subdirectory of `root`, sorted by name.

    A missing root is not an error -- it means no mods.
    """
    try:
        dirs = sorted((e for e in root.iterdir() if e.is_dir()),
                      key=lambda p: p.name)
    except OSError:
        return []
    return [ModCandidate(name=d.name, mod_dir=d, content_root=find_content_root(d))
            for d in dirs]
