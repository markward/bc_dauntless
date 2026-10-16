"""Packaged builds: everything written to fds 1 and 2 goes to a log file,
and is mirrored to the console.

Spec 2026-10-16 per-user data dirs, §5.5. The capture is at the FILE
DESCRIPTOR level, not sys.stdout/sys.stderr, because most of the process's
output never passes through Python: C++ `fprintf(stderr)`, CEF's console
`printf`, and Python's own fatal-error dumps all write straight to fd 1/2.

Mechanism (Ruling 8): fds 1 and 2 are dup2'd onto the log FILE itself,
opened for append. Every writer -- Python, C++, CEF, inherited children --
writes straight into the kernel file, so no writer ever waits on a reader,
and the log is complete even when the process dies without stopping it.
A daemon "follower" thread reads what is appended through its own read
handle and copies it to a saved duplicate of the original stderr. The
follower is best effort: while C++ holds the GIL it can't run, so the
console lags, but nothing blocks.

(The first design dup2'd pipes onto fd 1/2 with Python reader threads. A
GIL-holding C++ call writing more than about two pipe buffers then blocked
on a full pipe that the reader could never drain without the GIL: measured
at 200 KB on macOS, a permanent freeze. tests/unit/test_log_tee.py
reproduces it.)

The console mirror merges stdout and stderr onto the original stderr (or
the original stdout when there is no stderr): one file can't say which
stream a byte came from, and stderr is the diagnostic stream, so stdout's
consumers never see interleaved diagnostics. With no console at all (a
GUI-subsystem exe has no std handles) only the mirror is off; fds 1/2 still
go to the log.

Windows console: sys.stdout/sys.stderr sit on _WindowsConsoleIO, which
calls WriteConsoleW on the fd's handle -- a file after the redirect, where it
fails. Those streams are swapped for plain UTF-8 text streams on the same
fd while the tee runs, and put back by stop().

The follower uses only os.read/os.write. It never touches sys.stdout or
sys.stderr, which now point at the log, so it cannot feed back into it.

Stdlib only, and nothing here resolves a path: the caller passes it
(engine/__init__.py, from paths.log_file_path()).
"""
from __future__ import annotations

import atexit
import io
import os
import sys
import threading
from pathlib import Path
from typing import Optional

_STREAM_FDS = (1, 2)
_STREAM_NAMES = {1: "stdout", 2: "stderr"}
_POLL_S = 0.05              # follower's idle wait between reads
_DRAIN_S = 0.5              # how long stop() lets the follower catch up
_READ_CHUNK = 65536

_lock = threading.Lock()
_state: Optional["_Tee"] = None
_atexit_registered = False


class _Tee:
    def __init__(self, log_fd: int):
        self.log_fd = log_fd        # append handle the fds were dup2'd from
        self.read_fd: Optional[int] = None   # the follower's read handle
        self.saved: dict = {}       # stream fd -> duplicate of the original;
        #                             absent when that fd was not open
        self.redirected: set = set()          # fds already dup2'd to the log
        self.swapped: dict = {}     # "stdout"/"stderr" -> original stream
        self.stopping = threading.Event()
        self.follower: Optional[threading.Thread] = None


def _console(message: str) -> None:
    """One line on stderr, straight to the fd: sys.stderr may be None in a
    GUI process, and points at the log while the tee is live."""
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
    """fflush(NULL): C stdout is fully buffered once fd 1 is a file, so CEF's
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


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _above_std(fd: int) -> int:
    """Move `fd` above 0-2. With std fds closed at launch, os.open/os.dup
    hand out 1 or 2, which the dup2 onto fds 1/2 would then clobber."""
    low = []
    try:
        while fd <= 2:
            low.append(fd)
            fd = os.dup(fd)
    finally:
        for taken in low:
            _close(taken)
    return fd


def _console_io_types() -> tuple:
    """Raw stream types that write to a console handle, not to the fd's
    file. Windows only; a function so tests can inject a stand-in."""
    windows_console_io = getattr(io, "_WindowsConsoleIO", None)
    return (windows_console_io,) if windows_console_io is not None else ()


def _rewrap_console_streams(tee: _Tee) -> None:
    types = _console_io_types()
    if not types:
        return
    for fd, name in _STREAM_NAMES.items():
        stream = getattr(sys, name, None)
        raw = getattr(getattr(stream, "buffer", None), "raw", None)
        if raw is None or not isinstance(raw, types):
            continue
        replacement = open(fd, "w", encoding="utf-8",
                           errors="backslashreplace", buffering=1,
                           closefd=False)
        setattr(sys, name, replacement)
        tee.swapped[name] = stream


def _restore_console_streams(tee: _Tee) -> None:
    for name, original in tee.swapped.items():
        replacement = getattr(sys, name, None)
        try:
            if replacement is not None:
                replacement.flush()     # into the log, before fds go back
        except Exception:  # noqa: BLE001 -- restoring must not stop here
            pass
        setattr(sys, name, original)
    tee.swapped.clear()


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


def _follow(tee: _Tee, console: int) -> None:
    """Copy what is appended to the log onto the console until stop() asks,
    then drain to EOF once (bounded by stop()'s join) and return."""
    while True:
        # Sample the flag BEFORE reading: an EOF only proves the drain is
        # complete if stop() had already asked when the read began. (An EOF
        # read just before a final write + stop() would otherwise end the
        # follower with that write never copied.)
        stopping = tee.stopping.is_set()
        try:
            chunk = os.read(tee.read_fd, _READ_CHUNK)
        except OSError:
            return
        if chunk:
            try:
                _write_all(console, chunk)
            except OSError:
                pass        # a closed console must not stop the follower
            continue
        if stopping:
            return          # caught up after stop(): done
        tee.stopping.wait(_POLL_S)


def _dismantle(tee: _Tee) -> None:
    """Put sys.stdout/err and fds 1 and 2 back as they were, let the
    follower catch up, release the rest. Safe on a half-built tee (start()
    failing part way)."""
    _restore_console_streams(tee)
    for fd in tee.redirected:
        try:
            if fd in tee.saved:
                os.dup2(tee.saved[fd], fd)
            else:
                os.close(fd)    # it was not open before start()
        except OSError:
            pass
    tee.redirected.clear()
    tee.stopping.set()
    if tee.follower is not None:
        tee.follower.join(_DRAIN_S)
        if tee.follower.is_alive():
            return      # still copying: it owns its fds until exit
    owned = [tee.log_fd, *tee.saved.values()]
    if tee.read_fd is not None:
        owned.append(tee.read_fd)
    for fd in owned:
        _close(fd)


def start(path: Path) -> bool:
    """Send fds 1 and 2 to `path` (rotating the previous run's log first)
    and mirror it to the console.

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

        def fail(reason: str) -> bool:
            if rotation_error:
                _console(rotation_error)
            _console("log file disabled: " + reason)
            return False

        binary = getattr(os, "O_BINARY", 0)
        try:
            # Append, so a failed rotation never destroys the previous run.
            # After a successful rotation the file is new anyway.
            log_fd = _above_std(os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | binary, 0o644))
        except OSError as exc:
            return fail("cannot open %s (%s)" % (path, exc.strerror or exc))

        _flush_python_streams()
        _flush_c_stdio()
        tee = _Tee(log_fd)
        try:
            for fd in _STREAM_FDS:
                try:
                    tee.saved[fd] = _above_std(os.dup(fd))
                except OSError:
                    pass    # no such stream (GUI exe): nothing to mirror to
            console = tee.saved.get(2, tee.saved.get(1))
            if console is not None:
                tee.read_fd = _above_std(os.open(path, os.O_RDONLY | binary))
                # The mirror starts at this run, not at an old one.
                os.lseek(tee.read_fd, 0, os.SEEK_END)
            for fd in _STREAM_FDS:
                os.dup2(log_fd, fd)
                tee.redirected.add(fd)
            _rewrap_console_streams(tee)
            if console is not None:
                follower = threading.Thread(
                    target=_follow, args=(tee, console),
                    name="dauntless-log-follower", daemon=True)
                follower.start()
                tee.follower = follower
        except (OSError, RuntimeError) as exc:
            # A half-built tee (say, a console with no follower) is worse
            # than none: undo it all.
            _dismantle(tee)
            return fail("cannot redirect output to %s (%s)"
                        % (path, getattr(exc, "strerror", None) or exc))

        _state = tee
        if not _atexit_registered:
            atexit.register(stop)
            _atexit_registered = True

    if rotation_error:
        # Through the log, so it reaches the file AND the console.
        _console("%s; appending to the old log instead" % rotation_error)
    return True


def stop() -> None:
    """Restore fds 1 and 2 and let the follower drain. Safe to call twice.

    Children that inherited fd 1/2 (CEF helpers) keep appending to the file
    after this; that is never waited on and never mirrored."""
    global _state
    with _lock:
        tee = _state
        _state = None
    if tee is None:
        return
    try:
        _flush_python_streams()
        _flush_c_stdio()
    finally:
        _dismantle(tee)
