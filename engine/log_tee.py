"""Packaged builds: tee everything written to fds 1 and 2 into a log file.

Spec 2026-10-16 per-user data dirs, §5.5. The capture is at the FILE
DESCRIPTOR level, not sys.stdout/sys.stderr, because most of the process's
output never passes through Python: C++ `fprintf(stderr)`, CEF's console
`printf`, and Python's own fatal-error dumps all write straight to fd 1/2.

Mechanism: one pipe per stream is dup2'd onto fd 1 / fd 2. A daemon reader
thread per pipe copies each chunk to a saved duplicate of the ORIGINAL fd
(so the console still sees it, on the same stream) and to the log file,
flushed per chunk. The readers use only os.read/os.write and the file
object; they never touch sys.stdout/sys.stderr, which now feed the very pipe
being read.

Stdlib only, and nothing here resolves a path: the caller passes it
(engine/__init__.py, from paths.log_file_path()).
"""
from __future__ import annotations

import atexit
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_STREAM_FDS = (1, 2)
# How long stop() waits, in total, for the readers to drain after the pipes close.
# A child process that inherited fd 1/2 (a CEF helper) keeps the pipe's write
# end open, so EOF can be late; the daemon thread must never hold up exit.
_JOIN_TIMEOUT_S = 2.0
_READ_CHUNK = 65536

_lock = threading.Lock()
_state: Optional["_Tee"] = None
_atexit_registered = False


class _Tee:
    def __init__(self, log, saved: dict, readers: list):
        self.log = log
        self.saved = saved          # stream fd -> duplicate of the original
        self.readers = readers      # reader threads
        self.write_lock = threading.Lock()


def _console(message: str) -> None:
    """One line on the console's stderr, straight to the fd (sys.stderr may
    be None in a GUI process, and must not be used while the tee is live)."""
    try:
        os.write(2, ("dauntless: %s\n" % message).encode("utf-8", "replace"))
    except OSError:
        pass


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _flush_python_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            pass


def _flush_c_stdio() -> None:
    """fflush(NULL): C stdout is fully buffered once fd 1 is a pipe, so CEF's
    console `printf` lines would otherwise be flushed at C exit -- after
    stop() restored the fds, i.e. to the console but never into the log.

    POSIX only. On Windows the C++ host's CRT instance is not knowable from
    here, so it is left alone (unverified there)."""
    if sys.platform == "win32":
        return
    try:
        import ctypes
        ctypes.CDLL(None).fflush(None)
    except Exception:  # noqa: BLE001 -- best effort; never block start/stop
        pass


def is_active() -> bool:
    return _state is not None


def rotate(path: Path) -> Optional[str]:
    """Rename `path` to `<stem>.prev.log`, replacing any previous one.

    Returns None on success (or when there is nothing to rotate) and a
    one-line reason on failure -- never raises. A failure is expected when
    another instance holds the log open on Windows, or when the .prev.log
    name is taken by a directory.
    """
    path = Path(path)
    previous = path.with_name(path.stem + ".prev.log")
    try:
        if not os.path.lexists(path):
            return None
        os.replace(path, previous)
    except OSError as exc:
        return "could not rotate %s to %s (%s)" % (
            path, previous, exc.strerror or exc)
    return None


def _pump(read_fd: int, console_fd: int, tee: _Tee) -> None:
    try:
        while True:
            try:
                chunk = os.read(read_fd, _READ_CHUNK)
            except OSError:
                break
            if not chunk:
                break
            try:
                _write_all(console_fd, chunk)
            except OSError:
                pass        # a closed console must not stop the log
            with tee.write_lock:
                try:
                    tee.log.write(chunk)
                    tee.log.flush()
                except (OSError, ValueError):
                    pass
    finally:
        try:
            os.close(read_fd)
        except OSError:
            pass


def _dismantle(tee: _Tee, unread_pipes: tuple = ()) -> None:
    """Put fds 1 and 2 back and let the readers drain, then release what the
    tee owns. dup2 over fd 1/2 drops the last pipe write ends this process
    holds, so each reader sees EOF once it has copied what was written.
    `unread_pipes` are read ends whose reader never started (start() failed).
    """
    for fd, original in tee.saved.items():
        try:
            os.dup2(original, fd)
        except OSError:
            pass
    for read_fd in unread_pipes:
        try:
            os.close(read_fd)
        except OSError:
            pass
    deadline = time.monotonic() + _JOIN_TIMEOUT_S
    for reader in tee.readers:
        reader.join(max(0.0, deadline - time.monotonic()))
    if any(reader.is_alive() for reader in tee.readers):
        return      # still draining: it owns the fds and file until exit
    for original in tee.saved.values():
        try:
            os.close(original)
        except OSError:
            pass
    with tee.write_lock:
        try:
            tee.log.close()
        except OSError:
            pass


def start(path: Path) -> bool:
    """Tee fds 1 and 2 into `path` (rotating the previous run's log first).

    Returns True when the tee is running (including when it already was).
    Returns False, after one console line saying why, when the log can't be
    used; the process's fds are then left exactly as they were.
    """
    global _state, _atexit_registered
    with _lock:
        if _state is not None:
            return True
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _console("log file disabled: cannot create %s (%s)"
                     % (path.parent, exc.strerror or exc))
            return False
        rotation_error = rotate(path)
        try:
            # Append, so a failed rotation never destroys the previous run.
            # After a successful rotation the file is new anyway.
            log = open(path, "ab")
        except OSError as exc:
            _console("log file disabled: cannot open %s (%s)"
                     % (path, exc.strerror or exc))
            return False

        _flush_python_streams()
        _flush_c_stdio()
        saved: dict = {}
        pipes: list = []
        tee = _Tee(log, saved, [])
        try:
            for fd in _STREAM_FDS:
                saved[fd] = os.dup(fd)
            for fd in _STREAM_FDS:
                read_fd, write_fd = os.pipe()
                pipes.append(read_fd)
                try:
                    os.dup2(write_fd, fd)
                finally:
                    os.close(write_fd)
            for fd, read_fd in zip(_STREAM_FDS, pipes):
                reader = threading.Thread(
                    target=_pump, args=(read_fd, saved[fd], tee),
                    name="dauntless-log-tee-%d" % fd, daemon=True)
                reader.start()
                tee.readers.append(reader)
        except (OSError, RuntimeError) as exc:
            # A redirected fd with no reader would block once its pipe
            # fills, so any failure here puts every fd back first.
            _dismantle(tee, tuple(pipes[len(tee.readers):]))
            _console("log file disabled: cannot redirect output to %s (%s)"
                     % (path, getattr(exc, "strerror", None) or exc))
            return False

        _state = tee
        if not _atexit_registered:
            atexit.register(stop)
            _atexit_registered = True

    if rotation_error:
        # Through the tee, so it reaches the console AND the log.
        _console("%s; appending to the old log instead" % rotation_error)
    return True


def stop() -> None:
    """Restore fds 1 and 2 and let the readers drain. Safe to call twice."""
    global _state
    with _lock:
        tee = _state
        _state = None
    if tee is None:
        return
    _flush_python_streams()
    _flush_c_stdio()
    _dismantle(tee)
