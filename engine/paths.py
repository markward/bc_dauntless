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
