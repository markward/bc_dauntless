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
CONTENT_DIRS = frozenset({"data", "scripts", "sfx"})

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
    "sfx": "game",      # paths-guard: kind label, keys paths.game_root()
}


def fold(rel) -> str:
    """The index key for a relative path: lowercase, forward slashes.

    BC ran on a case-insensitive filesystem, so mod authors were never
    forced to be consistent and overwhelmingly are not -- the reference mod
    alone spells Data/data, Ships/ships and .NIF/.nif. Folding here makes
    resolution correct on case-sensitive filesystems too.
    """
    return str(rel).replace("\\", "/").strip("/").lower()


_MULTI_SEP_RE = re.compile(r"/{2,}")


def fold_search_prefix(rel) -> str:
    """fold(), plus collapsing INTERNAL duplicate separators.

    Only for prefix matching over index keys (dirs_for). Deliberately NOT
    part of fold(): fold() is mirrored byte-for-byte by
    native/src/renderer/asset_path.cc:fold_key(), and the index keys it
    builds are assembled from path PARTS, so they can never contain a double
    separator. Callers, however, can -- host_loop composes
    f"{share}/{tier}" from a SetTextureSharePath a mod author may have
    written with a trailing slash, and "data/x//high/" then prefix-matches
    nothing and degrades that group to stock-only with no diagnostic.
    """
    return _MULTI_SEP_RE.sub("/", fold(rel))


@dataclass(frozen=True)
class ModFile:
    abs_path: Path
    mod_name: str
    target: str          # "game" or "sdk" -- a kind label, not a path segment
    rel: str             # folded, relative to that target root
    # The SAME relative path in the mod author's own spelling. Kept because
    # classify() stats it against the stock root: the folded spelling only
    # finds a stock file when the stock file happens to be all-lowercase, so
    # on a case-sensitive filesystem "Data/Icons/Ships/Galaxy.tga" would be
    # reported as a pure addition rather than the override it is.
    raw_rel: str = ""


@dataclass
class ModStatus:
    name: str
    content_root: Optional[Path]
    placed: int = 0
    ignored: int = 0
    unplaced: list = None        # top-level dir names we could not place
    read_error: bool = False     # set if any directory of this mod was unreadable
    requires: list = None        # frameworks this mod imports that are unavailable
    # Ship names this mod carries a hardpoint for while NOTHING -- stock, this
    # mod, or any other installed mod -- provides the ship script. The mod
    # upgrades a hull it expects you to already have (VoyagerCubeHP's readme:
    # "Requirements: ... Voyager Borg Cube installed"). Its ship cannot appear,
    # and without this the player has no way to learn why.
    orphan_hardpoints: list = None
    # Stock ship scripts this mod replaces in place. Such a mod deliberately
    # adds NO new row to the ship picker -- CGSovereign becomes *the*
    # Sovereign -- which is indistinguishable from "the mod failed to load"
    # unless we say so.
    replaces_ships: list = None

    def __post_init__(self):
        if self.unplaced is None:
            self.unplaced = []
        if self.requires is None:
            self.requires = []
        if self.orphan_hardpoints is None:
            self.orphan_hardpoints = []
        if self.replaces_ships is None:
            self.replaces_ships = []


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
        prefix = fold_search_prefix(rel) + "/"
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


def _walk_files(content_root: Path, status: "ModStatus") -> list:
    """Every file under `content_root`, sorted, recording read failures.

    os.walk(onerror=...) rather than Path.rglob(): rglob SWALLOWS a
    permission error and simply does not descend, so an unreadable subtree
    used to be indistinguishable from an empty one -- the mod reported
    "0 files" with no problem language, which is the single most likely real
    failure reporting as a clean success. onerror is the only way to observe
    it. The global sort reproduces sorted(rglob("*")) exactly, so which file
    wins a within-mod case collision does not change.
    """
    def _on_error(_exc: OSError) -> None:
        status.read_error = True

    found: list = []
    for dirpath, dirnames, filenames in os.walk(content_root, onerror=_on_error):
        for name in filenames:
            found.append(Path(dirpath) / name)
    return sorted(found)


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
            for path in _walk_files(candidate.content_root, status):
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
                raw_rel = "/".join(keep)
                rel = fold(raw_rel)
                existing = files.get(rel)
                if existing is not None and existing.mod_name != candidate.name:
                    conflicts.append((rel, existing.mod_name, candidate.name))
                files[rel] = ModFile(abs_path=path, mod_name=candidate.name,
                                     target=target, rel=rel, raw_rel=raw_rel)
                status.placed += 1
        except OSError:
            # Belt and braces: _walk_files() already routes every directory
            # read failure to status.read_error, so this catches only a
            # failure in the per-file work above (a stat on a file whose
            # directory became unreadable mid-walk).
            status.read_error = True

    return ModIndex(files=files, mods=statuses, conflicts=conflicts)


def classify(index: ModIndex, game_root: Path, sdk_scripts: Path) -> None:
    """Fill index.overrides. Costs one stat PER MOD KEY -- never a walk of
    the install."""
    roots = {"game": game_root, "sdk": sdk_scripts}  # paths-guard: kind labels

    def _shadows_stock(mf: ModFile) -> bool:
        # Stat the mod author's OWN spelling as well as the folded one. On a
        # case-insensitive filesystem the two are the same question; on a
        # case-sensitive one the folded spelling finds a stock file only when
        # the stock file is all-lowercase, so a mod shipping
        # Data/Icons/Ships/Galaxy.tga over the identically-spelled stock file
        # was reported as a pure addition. Reporting only -- resolution is
        # always by the folded key.
        root = roots[mf.target]
        if mf.raw_rel and (root / mf.raw_rel).exists():
            return True
        return (root / mf.rel).exists()

    index.overrides = [
        rel for rel, mf in sorted(index.files.items()) if _shadows_stock(mf)
    ]
    _classify_ship_scripts(index, sdk_scripts)


# ``ships/<name>.py`` and ``ships/hardpoints/<name>.py`` as folded index keys.
# Both live under ships/, so the hardpoint pattern must be tested FIRST or a
# hardpoint reads as a ship script of the same name.
_HARDPOINT_KEY = re.compile(r"^ships/hardpoints/([^/]+)\.py$")
_SHIP_KEY = re.compile(r"^ships/([^/]+)\.py$")

# A ship script NAMES its hardpoint in GetShipStats:
#     "HardpointFile": "LCintrepidHP"
# That declaration is the only link between the two files. The names often
# coincide -- stock Galaxy.py declares "galaxy" -- but they need not, and
# assuming they must reported the working LC Intrepid pack (LCintrepidZZ.py ->
# "LCintrepidHP") as three broken hardpoints.
_HARDPOINT_DECL = re.compile(
    r"""["']HardpointFile["']\s*:\s*["']([^"']+)["']""")


def _classify_ship_scripts(index: ModIndex, sdk_scripts) -> None:
    """Fill each mod's `orphan_hardpoints` and `replaces_ships`.

    Both answer the same player question -- "why is this mod's ship not in the
    picker?" -- for the two cases where the honest answer is "it was never
    going to be":

    * a hardpoint whose ship script nothing provides (an upgrade mod missing
      its base mod), and
    * a mod that replaces a stock ship in place rather than adding one.

    Reads the mod's OWN ship scripts (already indexed, typically a few dozen
    small files) to learn which hardpoints they claim, plus one stat per mod
    hardpoint against the stock root. Never walks the install.
    """
    by_mod = {}
    for status in index.mods:
        by_mod[status.name] = status
        # classify() may be called more than once on one index (tests, and a
        # re-classify after a mod is toggled); accumulate nothing stale.
        status.orphan_hardpoints = []
        status.replaces_ships = []

    claimed = _hardpoints_claimed_by_ship_scripts(index)

    for key, mf in sorted(index.files.items()):
        status = by_mod.get(mf.mod_name)
        if status is None:
            continue

        hp = _HARDPOINT_KEY.match(key)
        if hp is not None:
            name = hp.group(1)
            # A stock ship script may claim this hardpoint too. Reading all 52
            # stock ship scripts at boot to find out would be the walk this
            # function promises not to do, so fall back to the stock naming
            # convention (ships/<hardpoint name>.py), which every stock ship
            # follows -- Galaxy.py declares "galaxy".
            if name in claimed:
                continue
            if (sdk_scripts / "ships" / f"{name}.py").exists():
                continue
            # Preserve the mod author's own capitalisation for the report;
            # the index key is folded.
            status.orphan_hardpoints.append(_raw_stem(mf, name))
            continue

        ship = _SHIP_KEY.match(key)
        if ship is not None:
            name = ship.group(1)
            if (sdk_scripts / "ships" / f"{name}.py").exists():
                status.replaces_ships.append(_raw_stem(mf, name))


def _hardpoints_claimed_by_ship_scripts(index: ModIndex) -> set:
    """Folded hardpoint names declared by any installed mod's ship script.

    Cross-mod on purpose: VoyagerCubeHP upgrades a hull whose ship script
    belongs to a DIFFERENT mod, so scoping this per-mod would report a
    correctly-installed pair as broken.
    """
    claimed = set()
    for key, mf in index.files.items():
        if _SHIP_KEY.match(key) is None:
            continue
        try:
            text = mf.abs_path.read_text(errors="replace")
        except OSError:
            # Unreadable ship script: say nothing rather than invent an
            # orphan. read_error already flags the mod.
            continue
        for m in _HARDPOINT_DECL.finditer(text):
            claimed.add(m.group(1).strip().lower())
    return claimed


def _raw_stem(mf: ModFile, folded_name: str) -> str:
    """The mod author's spelling of a ship name, falling back to the folded
    one when raw_rel is absent."""
    if mf.raw_rel:
        stem = mf.raw_rel.rsplit("/", 1)[-1]
        if stem.lower().endswith(".py"):
            return stem[:-3]
    return folded_name


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


# Frameworks the ENGINE itself implements, mapped to the module that proves
# it. `requires` means UNAVAILABLE, so a framework we reimplement must not be
# listed -- every mod in the corpus imports Foundation, and reporting all six
# as "requires: Foundation (unsupported)" told the player their mods would not
# work while Foundation was registering 45 of their ships.
#
# Proved by import rather than asserted by a literal: if engine/foundation/ is
# ever removed or renamed, the report corrects itself instead of lying in the
# other direction. That failure mode is the entire reason this mapping exists.
_ENGINE_FRAMEWORKS = {
    "Foundation": "engine.foundation",
}


def _engine_provides(name: str) -> bool:
    module = _ENGINE_FRAMEWORKS.get(name)
    if module is None:
        return False
    import importlib
    try:
        importlib.import_module(module)
    except Exception:
        return False
    return True


def detect_frameworks(index: ModIndex) -> None:
    """Record which unavailable frameworks each mod imports.

    Unavailable means neither the ENGINE nor a mod supplies it. A mod that
    bundles its own copy does not require it -- checked against the index --
    and neither does one importing a framework we reimplement.
    """
    provided = {Path(mf.rel).stem for mf in index.files.values()
                if mf.rel.endswith(".py")}
    provided |= {name.lower() for name in KNOWN_FRAMEWORKS
                 if _engine_provides(name)}
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


def sdk_override(module_rel) -> Optional[Path]:
    """The mod file for an SDK-scripts-relative path, or None."""
    hit = current().lookup(module_rel)
    if hit is None or hit.target != "sdk":  # paths-guard: kind label
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
        line = f"  {status.name}: {status.placed} files"
        if status.ignored:
            line += f", {status.ignored} ignored"
        if status.unplaced:
            line += f", unplaced: {', '.join(status.unplaced)}"
        if status.requires:
            line += f", requires: {', '.join(status.requires)} (unsupported)"
        if status.replaces_ships:
            # Said plainly because it explains an ABSENCE: a replacement mod
            # adds no picker row on purpose.
            line += (f", replaces stock ship "
                     f"{', '.join(repr(s) for s in status.replaces_ships)}")
        if status.orphan_hardpoints:
            line += (f", hardpoint "
                     f"{', '.join(repr(s) for s in status.orphan_hardpoints)}"
                     f" has no ship script -- needs the base mod")
        if status.read_error:
            # An unreadable subtree is a PARTIAL failure: some files may have
            # been placed already, so the count stays and the warning is
            # appended rather than replacing the line.
            line += " -- WARNING: could not read mod contents, some files were skipped"
        lines.append(line)
    if index.overrides:
        lines.append(f"  {len(index.overrides)} stock file(s) overridden")
    for rel, loser, winner in index.conflicts:
        lines.append(f"  WARNING conflict: {rel} -- {winner} wins over {loser}")
    return "mods:\n" + "\n".join(lines)


def renderer_overrides(index: ModIndex) -> dict:
    """The game-targeted subset, as {folded_rel: abs_path_str}, for C++."""
    return {rel: str(mf.abs_path) for rel, mf in sorted(index.files.items())
            if mf.target == "game"}  # paths-guard: kind label


def install(argv=None, env=None, game_root=None, sdk_scripts=None) -> ModIndex:
    """Build, classify, scan and install the index. Called once at boot,
    AFTER paths.configure() -- mapping Data/ and Scripts/ to their targets
    needs the resolved roots.

    `game_root`/`sdk_scripts` let a caller that already holds a resolved
    Resolution (host_loop's boot sequence) pass those roots directly rather
    than going through paths.game_root()/paths.sdk_scripts() -- those read
    the global paths._RESOLUTION, which a caller may have deliberately left
    unconfigured (e.g. a test that monkeypatches paths.configure to a no-op
    while holding its own fake Resolution). When either is omitted, this
    falls back to the ambient paths accessors exactly as before, so every
    existing caller (tools/, tests with no Resolution in hand) is unaffected.
    """
    if game_root is None:
        game_root = paths.game_root()
    if sdk_scripts is None:
        sdk_scripts = paths.sdk_scripts()
    index = build_index(mods_root(argv=argv, env=env))
    classify(index, game_root, sdk_scripts)
    detect_frameworks(index)
    configure(index)
    return index
