"""Dynamic write guard: a `sys.addaudithook` that records every filesystem
write the code under test makes, wherever the path came from.

The static guard (tests/unit/test_install_write_guard.py) reads source and
cannot follow a path through another module, an SDK script or the working
directory. This hook sees the write itself, so it is the net for those
(Ruling 12). It is the scoping run's sitecustomize hook (scoping note §2)
turned into a test helper.

Usage::

    write_audit.install_once()
    with write_audit.recording() as records:
        ...code under test...
    assert not write_audit.stray_writes(records, paths.PROJECT_ROOT)

Each record is ``(event, abs_path, first_project_frame)``:

  * ``event`` is the audit event name ("open", "os.mkdir", "os.rename",
    "shutil.copyfile", ...);
  * ``abs_path`` is the written path made absolute against the working
    directory AT THE TIME OF THE WRITE (a cwd-relative write is the trap the
    scoping note §1 names);
  * ``first_project_frame`` is ``"file:line"`` of the innermost stack frame
    in the project or the SDK scripts, or "" when none is on the stack.

Audit hooks can never be removed, so `install_once` adds one per process and
the hook checks a module-level flag first: outside `recording()` it costs one
global read per audit event.
"""
from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import Iterator, Optional

Record = tuple[str, str, str]

# os.open flags that make an open a write.
_WRITE_FLAGS = (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND
                | os.O_TRUNC)

# Single-path write events: (path, ...).
_PATH_EVENTS = frozenset({"os.mkdir", "os.remove", "os.rmdir"})

# shutil events: indices of the args that are WRITTEN (a copy's source is
# only read). shutil.move removes its source, so both count.
_SHUTIL_WRITTEN_ARGS = {
    "shutil.copyfile": (1,),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.copytree": (1,),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.chown": (0,),
    "shutil.make_archive": (0,),
    "shutil.unpack_archive": (1,),
}

_installed = False
_records: Optional[list[Record]] = None
# Frame-attribution roots, set on entering recording() (resolved at use).
_frame_roots: tuple[str, ...] = ()
_frame_excludes: tuple[str, ...] = ()
_THIS_FILE = os.path.abspath(__file__)


def install_once() -> None:
    """Add the process's one audit hook (idempotent)."""
    global _installed
    if _installed:
        return
    sys.addaudithook(_hook)
    _installed = True


@contextlib.contextmanager
def recording() -> Iterator[list[Record]]:
    """Record writes for the duration of the block; yields the live list.

    Not reentrant: a nested recording() would steal the outer one's records.
    """
    global _records, _frame_roots, _frame_excludes
    if _records is not None:
        raise RuntimeError("write_audit.recording() is not reentrant")
    install_once()
    from engine import paths
    root = str(paths.PROJECT_ROOT)
    _frame_roots = (root + os.sep, str(paths.sdk_scripts()) + os.sep)
    _frame_excludes = (_THIS_FILE, os.path.join(root, ".venv") + os.sep)
    records: list[Record] = []
    _records = records
    try:
        yield records
    finally:
        _records = None


def _hook(event: str, args: tuple) -> None:
    records = _records
    if records is None:
        return
    try:
        written = _written_paths(event, args)
        if not written:
            return
        frame = _first_project_frame()
        for p in written:
            records.append((event, p, frame))
    except Exception:
        # An audit hook that raises aborts the audited call: never do that.
        pass


def _written_paths(event: str, args: tuple) -> list[str]:
    if event == "open":
        path, mode, flags = args
        if isinstance(mode, str):
            is_write = any(c in mode for c in "wax+")
        else:
            is_write = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        return [_abs(path)] if is_write and _is_path(path) else []
    if event in _PATH_EVENTS:
        # A dir_fd-relative op (shutil.rmtree's inner unlinks) is relative to
        # an fd, not the cwd; its enclosing shutil.* event carries the path.
        if _fd_relative(args[-1]):
            return []
        return [_abs(args[0])] if _is_path(args[0]) else []
    if event == "os.rename":  # os.rename AND os.replace raise this event
        src, dst, src_dir_fd, dst_dir_fd = args
        if _fd_relative(src_dir_fd) or _fd_relative(dst_dir_fd):
            return []
        return [_abs(p) for p in (src, dst) if _is_path(p)]
    idx = _SHUTIL_WRITTEN_ARGS.get(event)
    if idx is not None:
        return [_abs(args[i]) for i in idx
                if i < len(args) and _is_path(args[i])]
    return []


def _fd_relative(dir_fd) -> bool:
    """True for a real dir_fd. CPython audits the default (AT_FDCWD) as -1."""
    return dir_fd is not None and dir_fd != -1


def _is_path(p) -> bool:
    return isinstance(p, (str, bytes, os.PathLike))


def _abs(p) -> str:
    p = os.fsdecode(p)
    return os.path.abspath(p)


def _first_project_frame() -> str:
    # Start at _hook's own frame, which always exists (this file is
    # excluded), so a write with no Python caller still gets recorded.
    f = sys._getframe(1)
    while f is not None:
        fn = f.f_code.co_filename
        if fn.startswith(_frame_roots) and not fn.startswith(_frame_excludes):
            return "%s:%d" % (fn, f.f_lineno)
        f = f.f_back
    return ""


# --- filtering --------------------------------------------------------------

def _real(p) -> str:
    return os.path.realpath(os.fspath(p))


def _is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def under(records: list[Record], *roots) -> list[Record]:
    """The records whose path lies under any of `roots`.

    Paths are compared after realpath, so /var vs /private/var on macOS
    cannot hide a hit.
    """
    real_roots = [_real(r) for r in roots]
    return [rec for rec in records
            if any(_is_within(_real(rec[1]), r) for r in real_roots)]


def stray_writes(records: list[Record], *roots) -> list[Record]:
    """`under(records, *roots)`, minus the writes that are allowed there.

    Allowed: `__pycache__` segments (bytecode is the packaged build's
    concern, Task 10), anything under the user-data dir active when this
    is called (tests/conftest.py's temp DAUNTLESS_DATA_DIR, or a test's own
    override; where writes SHOULD land, even if a developer points it
    inside the checkout) and pytest's own temp dirs.
    """
    from engine import paths
    allowed = [_real(d) for d in _allowed_dirs(paths)]
    return [rec for rec in under(records, *roots)
            if "__pycache__" not in Path(rec[1]).parts
            and not any(_is_within(_real(rec[1]), d) for d in allowed)]


def _allowed_dirs(paths) -> list:
    dirs = []
    override = paths.data_dir_override()
    if override is not None:
        dirs.append(override)
    dirs.append(Path(os.environ.get("PYTEST_DEBUG_TEMPROOT")
                     or _system_temp()) / ("pytest-of-" + _user()))
    return dirs


def _system_temp() -> str:
    import tempfile
    return tempfile.gettempdir()


def _user() -> str:
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"
