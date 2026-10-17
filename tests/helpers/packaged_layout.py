"""A packaged-build install folder, built from this checkout (plan Task 13).

`build` copies (never links) what a shipped build reads at run time: the
`engine/` package, the project-root `*.py` shims and `native/assets/`, plus
the packaged marker. It never copies anything a player's machine writes
(settings.json, Options.cfg, Keybindings.cfg, saves/, cache/, mods/), so a
read of one of those from the install is a read of nothing.

`make_readonly` / `restore_writable` flip every file and folder, and
`tree_digest` hashes relative paths and bytes, so a test can prove nothing
under the install changed.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

from engine import paths

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def build(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = paths.PROJECT_ROOT
    shutil.copytree(root / "engine", dest / "engine", ignore=_IGNORE)
    for shim in sorted(root.glob("*.py")):
        shutil.copy2(shim, dest / shim.name)
    shutil.copytree(root / "native" / "assets",
                    dest / "native" / "assets", ignore=_IGNORE)
    (dest / paths.PACKAGED_MARKER).write_text("{}\n", encoding="utf-8")
    return dest


def _walk(root: Path):
    for base, dirs, files in os.walk(root):
        yield Path(base), dirs, files


def make_readonly(root: Path) -> None:
    for base, dirs, files in _walk(Path(root)):
        for name in files:
            p = base / name
            if not p.is_symlink():
                os.chmod(p, stat.S_IREAD)
    for base, _dirs, _files in reversed(list(_walk(Path(root)))):
        os.chmod(base, stat.S_IREAD | stat.S_IEXEC)


def restore_writable(root: Path) -> None:
    for base, dirs, files in _walk(Path(root)):
        os.chmod(base, stat.S_IRWXU)
        for name in files:
            p = base / name
            if not p.is_symlink():
                os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def tree_digest(root: Path) -> str:
    """sha256 over every file's relative path and bytes, and every folder's
    relative path (so an added empty folder or a new file changes it)."""
    root = Path(root)
    h = hashlib.sha256()
    entries = []
    for base, dirs, files in _walk(root):
        for name in dirs:
            entries.append((str((base / name).relative_to(root)), None))
        for name in files:
            entries.append((str((base / name).relative_to(root)), base / name))
    for rel, path in sorted(entries, key=lambda e: e[0]):
        h.update(rel.replace("\\", "/").encode("utf-8") + b"\0")
        if path is not None:
            h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()
