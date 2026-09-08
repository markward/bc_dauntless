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


IGNORED_NAMES = frozenset({".ds_store", "thumbs.db"})
IGNORED_SUFFIXES = (".txt", ".html", ".htm", ".pdf", ".rtf", ".doc")

# Mod top-level directory -> target root kind. The values are KIND LABELS
# keying paths.py's own vocabulary, not path segments.
_TARGET_FOR = {
    "data": "game",     # paths-guard: kind label, keys paths.game_root()
    "scripts": "sdk",   # paths-guard: kind label, keys paths.sdk_scripts()
}


def fold(rel) -> str:
    """The index key for a relative path: lowercase, forward slashes.

    BC ran on a case-insensitive filesystem, so mod authors were never
    forced to be consistent and overwhelmingly are not -- the reference mod
    alone spells Data/data, Ships/ships and .NIF/.nif. Folding here makes
    resolution correct on case-sensitive filesystems too.
    """
    return str(rel).replace("\\", "/").strip("/").lower()


@dataclass(frozen=True)
class ModFile:
    abs_path: Path
    mod_name: str
    target: str          # "game" or "sdk" -- a kind label, not a path segment
    rel: str             # folded, relative to that target root


@dataclass
class ModStatus:
    name: str
    content_root: Optional[Path]
    placed: int = 0
    ignored: int = 0
    unplaced: list = None        # top-level dir names we could not place

    def __post_init__(self):
        if self.unplaced is None:
            self.unplaced = []


@dataclass
class ModIndex:
    files: dict
    mods: list

    def lookup(self, rel) -> Optional[ModFile]:
        return self.files.get(fold(rel))

    def dirs_for(self, rel) -> list:
        """Every mod directory that provides files under `rel`.

        For the one consumer that hands a directory LIST to C++; a single
        file lookup should use lookup() instead.
        """
        prefix = fold(rel) + "/"
        seen = []
        for key, mf in self.files.items():
            if not key.startswith(prefix):
                continue
            depth = len(key[len(prefix):].split("/")) - 1
            d = mf.abs_path
            for _ in range(depth + 1):
                d = d.parent
            if d not in seen:
                seen.append(d)
        return seen


def _is_ignored(path: Path, content_root: Path) -> bool:
    if path.name.lower() in IGNORED_NAMES:
        return True
    # Documents at the content root only -- a readme buried in a model
    # folder is harmless to place, and BC content does include stray .txt.
    if path.parent == content_root and path.suffix.lower() in IGNORED_SUFFIXES:
        return True
    return False


def build_index(root: Path) -> ModIndex:
    """Index every enabled mod under `root`. O(mod files), never the install.

    Later mods win, and discover_mods() sorts by name, so the winner is
    deterministic across runs.
    """
    files: dict = {}
    statuses: list = []

    for candidate in discover_mods(root):
        status = ModStatus(name=candidate.name, content_root=candidate.content_root)
        statuses.append(status)
        if candidate.content_root is None:
            continue

        for path in sorted(candidate.content_root.rglob("*")):
            if not path.is_file():
                continue
            if _is_ignored(path, candidate.content_root):
                status.ignored += 1
                continue
            rel_parts = path.relative_to(candidate.content_root).parts
            top = rel_parts[0].lower()
            target = _TARGET_FOR.get(top)
            if target is None:
                if rel_parts[0] not in status.unplaced:
                    status.unplaced.append(rel_parts[0])
                continue
            # Under "scripts" the target root IS the scripts dir, so the
            # segment itself is dropped; under "data" it is kept, because
            # game_asset() is called with "data/..." paths.
            keep = rel_parts if target == "game" else rel_parts[1:]  # paths-guard: kind label
            rel = fold("/".join(keep))
            files[rel] = ModFile(abs_path=path, mod_name=candidate.name,
                                 target=target, rel=rel)
            status.placed += 1

    return ModIndex(files=files, mods=statuses)
