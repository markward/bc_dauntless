"""Where the player's Bridge Commander content lives — the single authority.

BC content is two roots: the game install (models, textures, icons, sounds)
and the SDK (the Python scripts and the TGL string tables). Neither has to
live inside the project tree.

HARD RULE — paths resolve at USE, never at import.
    No module in engine/ may bind a module-level name to a path from here.
    Resolving early enough for import-time constants to work would make the
    first-run picker impossible: it runs after CEF is up, so anything captured
    at import is already stale by the time the player chooses a folder.

Nothing outside this module may spell "game" or "sdk" as a path segment.
tests/unit/test_path_indirection.py enforces both halves.

Spec: docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The markers are the paths the engine actually loads. stbc.exe and scripts/
# are deliberately absent: neither is read at runtime (scripts/ is only
# tools/setup.py's instrumentation target), so requiring them would reject a
# perfectly usable content-only copy.
GAME_MARKERS: tuple[str, ...] = ("data", "data/Models", "data/Textures", "data/Icons")
SDK_MARKERS: tuple[str, ...] = ("Build/scripts/App.py", "Build/Data/TGL")

_MARKERS = {"game": GAME_MARKERS, "sdk": SDK_MARKERS}
_LABEL = {"game": "game", "sdk": "SDK"}


@dataclass(frozen=True)
class Validation:
    """The verdict on one candidate root.

    `missing` lists the markers that were absent, in declaration order.
    `hint` is a specific diagnosis of a recognisable mistake, or None.
    """
    ok: bool
    root: Path
    missing: tuple[str, ...]
    hint: Optional[str]


def normalise(path) -> Path:
    """expanduser -> abspath -> normpath. Deliberately NOT Path.resolve().

    Symlinks are not followed: an install behind a symlink to an external
    volume keeps working across remounts, where a resolved target would not.
    """
    return Path(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))


def _markers_ok(root: Path, markers: tuple[str, ...]) -> bool:
    return all((root / m).exists() for m in markers)


def _case_insensitive_spelling(root: Path, rel: str) -> Optional[str]:
    """The real on-disk spelling of `rel` under `root`, matched case-blind.

    Returns None when no case-blind match exists. On a case-INSENSITIVE
    filesystem this is never reached, because the exact check already
    succeeded.
    """
    current = root
    found: list[str] = []
    for segment in rel.split("/"):
        try:
            entries = list(current.iterdir())
        except OSError:
            return None
        match = next((e for e in entries if e.name.lower() == segment.lower()), None)
        if match is None:
            return None
        found.append(match.name)
        current = match
    return "/".join(found)


def _hint_for(root: Path, kind: str, missing: tuple[str, ...]) -> Optional[str]:
    """Diagnose the mistakes a person actually makes. Order matters: the
    case hint is unambiguous when it fires, so it wins."""
    # Case only — every missing marker has a case-blind match on disk.
    spellings = {m: _case_insensitive_spelling(root, m) for m in missing}
    if missing and all(spellings.values()):
        m = missing[0]
        return f"found '{spellings[m]}', expected '{m}' — this volume is case-sensitive"

    # The parent was picked: this folder CONTAINS a valid game/ or sdk/.
    child = root / kind
    if child.is_dir() and _markers_ok(child, _MARKERS[kind]):
        return f"That folder contains '{kind}' — did you mean {child}?"

    # Swapped: it validates as the OTHER root.
    other = "sdk" if kind == "game" else "game"
    if _markers_ok(root, _MARKERS[other]):
        return (f"That's the {_LABEL[other]} folder; "
                f"it belongs in the {_LABEL[other]} field.")

    # One level too deep: the parent is the root that was wanted.
    parent = root.parent
    if parent != root and _markers_ok(parent, _MARKERS[kind]):
        return f"That's the {root.name} folder — pick its parent ({parent})."

    return None


def _validate(path, kind: str) -> Validation:
    root = normalise(path)
    markers = _MARKERS[kind]
    missing = tuple(m for m in markers if not (root / m).exists())
    if not missing:
        return Validation(ok=True, root=root, missing=(), hint=None)
    return Validation(ok=False, root=root, missing=missing,
                      hint=_hint_for(root, kind, missing))


def validate_game_root(path) -> Validation:
    """Is `path` a usable BC game install? One stat per marker, no writes."""
    return _validate(path, "game")


def validate_sdk_root(path) -> Validation:
    """Is `path` a usable BC SDK tree? One stat per marker, no writes."""
    return _validate(path, "sdk")


# --- resolution -------------------------------------------------------------

# engine/paths.py -> engine/ -> <project root>. Kept as a module attribute
# rather than a local so tests can point the legacy fallback at a tmp_path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CLI_FLAGS = {"game": "--game-dir", "sdk": "--sdk-dir"}
ENV_VARS = {"game": "DAUNTLESS_GAME_DIR", "sdk": "DAUNTLESS_SDK_DIR"}
_PROJECT_DIR = {"game": "game", "sdk": "sdk"}
_VALIDATORS = {"game": validate_game_root, "sdk": validate_sdk_root}


class PathsUnresolved(RuntimeError):
    """No usable root for a requested half. Carries describe_failure()'s text.

    Not meant to be handled: it is a boot-time configuration error and the
    message is the whole point.
    """


@dataclass(frozen=True)
class Resolution:
    """The outcome of one resolve(). `game`/`sdk` are set ONLY when valid.

    An invalid candidate leaves the root None and records the attempt in the
    matching Validation, so describe_failure() can name the path and say what
    was wrong with it.
    """
    game: Optional[Path]
    sdk: Optional[Path]
    game_source: str            # "cli" | "env" | "settings" | "project" | ""
    sdk_source: str
    game_validation: Optional[Validation]
    sdk_validation: Optional[Validation]

    @property
    def ok(self) -> bool:
        return self.game is not None and self.sdk is not None

    def source(self, kind: str) -> str:
        return self.game_source if kind == "game" else self.sdk_source

    def validation(self, kind: str) -> Optional[Validation]:
        return self.game_validation if kind == "game" else self.sdk_validation


def _flag_value(argv, flag: str) -> Optional[str]:
    """Support both `--game-dir X` and `--game-dir=X`."""
    for i, token in enumerate(argv):
        if token == flag:
            return argv[i + 1] if i + 1 < len(argv) else ""
        if token.startswith(flag + "="):
            return token[len(flag) + 1:]
    return None


def _candidate(kind: str, argv, env, store):
    """The highest-precedence SET source for one root, as (value, source).

    Returns (None, "") when nothing is set. A set-but-wrong source is
    returned as-is and never skipped in favour of a lower one -- falling
    through would run a different install than the one that was asked for.
    """
    flag = _flag_value(argv, CLI_FLAGS[kind])
    if flag:
        return flag, "cli"

    from_env = env.get(ENV_VARS[kind])
    if from_env:
        return from_env, "env"

    if store is not None and store.has("paths", kind):
        stored = store.get("paths", kind)
        if stored:
            return stored, "settings"

    project = PROJECT_ROOT / _PROJECT_DIR[kind]
    if project.is_dir():
        return str(project), "project"

    return None, ""


def resolve(argv=None, env=None, store=None) -> Resolution:
    """Resolve both roots. PURE: no globals, no writes, no ambient state
    beyond the defaults for argv/env/store.

    settings_store is imported HERE rather than at module scope: it imports
    engine.ui.configuration_panel, and this module is imported by
    engine/audio/ and engine/appc/.
    """
    import sys

    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ
    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()

    roots: dict = {}
    sources: dict = {}
    validations: dict = {}
    for kind in ("game", "sdk"):
        value, source = _candidate(kind, argv, env, store)
        sources[kind] = source
        if value is None:
            roots[kind] = None
            validations[kind] = None
            continue
        verdict = _VALIDATORS[kind](value)
        validations[kind] = verdict
        roots[kind] = verdict.root if verdict.ok else None

    return Resolution(
        game=roots["game"], sdk=roots["sdk"],
        game_source=sources["game"], sdk_source=sources["sdk"],
        game_validation=validations["game"], sdk_validation=validations["sdk"],
    )


def persist(resolution: Resolution, store=None) -> None:
    """Write CLI-sourced roots to settings.json [paths].

    Only CLI, and only when valid. An env var is ephemeral by contract, so
    `DAUNTLESS_SDK_DIR=/fixtures pytest` cannot mutate a real config; and a
    typo never becomes the stored answer, which would make the NEXT launch
    fail for a reason the player has already forgotten about.
    """
    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()
    for kind in ("game", "sdk"):
        root = resolution.game if kind == "game" else resolution.sdk
        if root is not None and resolution.source(kind) == "cli":
            store.set("paths", kind, str(root))


# --- the cache --------------------------------------------------------------

_RESOLUTION: Optional[Resolution] = None


def configure(resolution: Optional[Resolution]) -> None:
    """Install a Resolution as the answer every accessor reads.

    Callable more than once, and later calls are observed by every consumer:
    that is what the first-run picker needs, and it is why nothing may capture
    a path at import. Pass None to clear (tests).
    """
    global _RESOLUTION
    _RESOLUTION = resolution


def current() -> Resolution:
    """The configured Resolution, resolving from ambient state if configure()
    has not run. The lazy path keeps a tools/ script or an isolated test
    working without a boot sequence."""
    global _RESOLUTION
    if _RESOLUTION is None:
        _RESOLUTION = resolve()
    return _RESOLUTION


def _root(kind: str) -> Path:
    resolution = current()
    root = resolution.game if kind == "game" else resolution.sdk
    if root is None:
        raise PathsUnresolved(describe_failure(resolution))
    return root


def game_root() -> Path:
    """The BC game install root. Never captured at module scope."""
    return _root("game")


def sdk_root() -> Path:
    """The BC SDK root. Never captured at module scope."""
    return _root("sdk")


def sdk_scripts() -> Path:
    """sdk_root()/Build/scripts — where the SDK's Python modules live."""
    return sdk_root() / "Build" / "scripts"


def sdk_data() -> Path:
    """sdk_root()/Build/Data — TGL string tables and friends."""
    return sdk_root() / "Build" / "Data"


def game_asset(rel) -> Path:
    """Absolutise a BC-relative asset path, e.g. "data/Textures/x.tga"."""
    return game_root() / rel


# --- the failure message ----------------------------------------------------

def describe_failure(resolution: Resolution) -> str:
    """Every source consulted and what each said. Empty when nothing failed."""
    if resolution.ok:
        return ""

    lines = ["dauntless: cannot locate your Bridge Commander install.", ""]
    for kind, label in (("game", "game folder"), ("sdk", "sdk folder ")):
        root = resolution.game if kind == "game" else resolution.sdk
        if root is not None:
            lines.append(f"  {label}: {root}")
            lines.append("")
            continue

        verdict = resolution.validation(kind)
        if verdict is None:
            lines.append(f"  {label}: not found")
            lines.append(f"     {CLI_FLAGS[kind]:<18}(not given)")
            lines.append(f"     {ENV_VARS[kind]:<18}(not set)")
            lines.append(f"     {'settings.json':<18}(not set)")
            project = PROJECT_ROOT / _PROJECT_DIR[kind]
            lines.append(f"     {str(project):<18}(does not exist)")
        else:
            lines.append(f"  {label}: invalid — {verdict.root}")
            lines.append(f"     missing: {', '.join(verdict.missing)}")
            lines.append(f"     source : {resolution.source(kind)}")
            if verdict.hint:
                lines.append(f"     hint   : {verdict.hint}")
        lines.append("")

    lines += [
        "Set them once and they persist:",
        "",
        "  ./build/dauntless \\",
        '      --game-dir "/path/to/Star Trek Bridge Commander/game" \\',
        '      --sdk-dir  "/path/to/Star Trek Bridge Commander/sdk"',
        "",
    ]
    return "\n".join(lines)
