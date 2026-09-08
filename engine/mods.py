"""Where the player's installed mods live, and what they provide.

A mod is a BC-shaped tree the player drops into mods/. Nothing here ever
writes, copies, or symlinks: the index answers "who provides this file?"
and the stock roots answer everything else.

HARD RULE -- like engine/paths.py, paths resolve at USE, never at import.

Spec: docs/superpowers/specs/2026-09-08-mod-overlay-design.md
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine import paths

# Top-level directories inside a mod that we know how to place. Lowercase
# because every comparison here is case-folded.
CONTENT_DIRS = frozenset({"data", "scripts"})

CLI_FLAG = "--mods-dir"
ENV_VAR = "DAUNTLESS_MODS_DIR"

KNOWN_FRAMEWORKS = frozenset({
    "Foundation", "FoundationTech", "FoundationTriggers", "Registry",
})

# Regex patterns for import statement fallback (Python 1.5 syntax tolerance).
# Separate patterns for import and from...import to handle comma-separated imports.
_IMPORT_LIST_RE = re.compile(
    r"^\s*import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*)",
    re.MULTILINE)
_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+([A-Za-z_][\w.]*)\s+import",
    re.MULTILINE)


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
    read_error: bool = False     # set if rglob walk failed for this mod
    requires: list = None        # frameworks this mod imports that are unavailable

    def __post_init__(self):
        if self.unplaced is None:
            self.unplaced = []
        if self.requires is None:
            self.requires = []


@dataclass
class ModIndex:
    files: dict
    mods: list
    conflicts: list = field(default_factory=list)
    overrides: list = field(default_factory=list)

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
    deterministic across runs. A missing mod root is not an error; a
    permission or symlink failure for one mod does not prevent indexing
    the others.
    """
    files: dict = {}
    statuses: list = []
    conflicts: list = []

    for candidate in discover_mods(root):
        status = ModStatus(name=candidate.name, content_root=candidate.content_root)
        statuses.append(status)
        if candidate.content_root is None:
            continue

        try:
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
                existing = files.get(rel)
                if existing is not None and existing.mod_name != candidate.name:
                    conflicts.append((rel, existing.mod_name, candidate.name))
                files[rel] = ModFile(abs_path=path, mod_name=candidate.name,
                                     target=target, rel=rel)
                status.placed += 1
        except OSError:
            # Permission denied, broken symlink, or other read failure for this mod.
            # Mark it so describe() can emit explicit problem language.
            status.read_error = True

    return ModIndex(files=files, mods=statuses, conflicts=conflicts)


def classify(index: ModIndex, game_root: Path, sdk_scripts: Path) -> None:
    """Fill index.overrides. Costs one stat PER MOD KEY -- never a walk of
    the install."""
    roots = {"game": game_root, "sdk": sdk_scripts}  # paths-guard: kind labels
    index.overrides = [
        rel for rel, mf in sorted(index.files.items())
        if (roots[mf.target] / mf.rel).exists()
    ]


def _imported_names(source: str) -> set:
    """Root module names imported by `source`.

    Mod scripts are Python 1.5 era and may not parse under Python 3
    (backtick-repr, `has_key`), so a regex fallback covers what ast cannot.
    Same posture tests/unit/test_path_indirection.py takes for tools/probes/.
    """
    names = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fallback for Python 1.5 syntax. Split on semicolons first to handle
        # multiple statements on one line (e.g., "import App; import Foundation").
        # The regex anchors to line start (^\s*), so this preserves correct
        # behaviour for commented-out imports and indentation.
        for statement in source.split(';'):
            # Handle import statements with comma-separated names
            for m in _IMPORT_LIST_RE.finditer(statement):
                names_str = m.group(1)
                for name in names_str.split(','):
                    name = name.strip()
                    if name:
                        names.add(name.split(".")[0])
            # Handle from...import statements
            for m in _FROM_IMPORT_RE.finditer(statement):
                raw = m.group(1)
                names.add(raw.split(".")[0])
        return names

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def detect_frameworks(index: ModIndex) -> None:
    """Record which unavailable frameworks each mod imports.

    A mod that SUPPLIES the framework does not require it -- checked against
    the index, so a bundled Foundation counts as present.
    """
    provided = {Path(mf.rel).stem for mf in index.files.values()
                if mf.rel.endswith(".py")}
    by_mod: dict = {status.name: status for status in index.mods}
    for status in index.mods:
        status.requires = []

    for mf in index.files.values():
        if not mf.rel.endswith(".py"):
            continue
        try:
            source = mf.abs_path.read_text(errors="replace")
        except OSError:
            continue
        status = by_mod[mf.mod_name]
        for name in sorted(_imported_names(source)):
            if name in KNOWN_FRAMEWORKS and name.lower() not in provided \
                    and name not in status.requires:
                status.requires.append(name)


_INDEX: Optional[ModIndex] = None


def configure(index: Optional[ModIndex]) -> None:
    """Install the index every consumer reads. Pass None to clear (tests)."""
    global _INDEX
    _INDEX = index


def current() -> ModIndex:
    """The configured index, or an EMPTY one.

    Deliberately unlike paths.current(): it never builds from ambient state.
    A tool or test that has not opted in must see stock content, and an
    implicit disk scan on first asset lookup would be a surprising cost.
    """
    global _INDEX
    if _INDEX is None:
        _INDEX = ModIndex(files={}, mods=[])
    return _INDEX


def game_override(rel) -> Optional[Path]:
    """The mod file for a game-root-relative path, or None."""
    hit = current().lookup(rel)
    if hit is None or hit.target != "game":  # paths-guard: kind label
        return None
    return hit.abs_path


def describe(index: ModIndex) -> str:
    """The boot report. Empty when no mods are installed."""
    if not index.mods:
        return ""
    lines = []
    for status in index.mods:
        if status.content_root is None:
            lines.append(f"  {status.name}: no BC content found -- not loaded")
            continue
        if status.read_error:
            lines.append(f"  {status.name}: could not read mod contents -- placed 0 files")
            continue
        line = f"  {status.name}: {status.placed} files"
        if status.ignored:
            line += f", {status.ignored} ignored"
        if status.unplaced:
            line += f", unplaced: {', '.join(status.unplaced)}"
        if status.requires:
            line += f", requires: {', '.join(status.requires)} (unsupported)"
        lines.append(line)
    if index.overrides:
        lines.append(f"  {len(index.overrides)} stock file(s) overridden")
    for rel, loser, winner in index.conflicts:
        lines.append(f"  WARNING conflict: {rel} -- {winner} wins over {loser}")
    return "mods:\n" + "\n".join(lines)
