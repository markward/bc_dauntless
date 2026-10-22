"""engine.log_tee: packaged builds send fds 1 and 2 to a rotated log and
mirror it to the console (spec 2026-10-16 per-user data dirs, §5.5; review
focus 4; Ruling 8: writers go straight to the file, a follower thread copies
the file to the console, so no writer can ever block on a reader).

The tee rewires the process's own file descriptors, so every test runs it in
a child interpreter. `-I` ignores PYTHONPATH, so the child puts the project
root on sys.path itself (argv[1]). The console mirror merges stdout and
stderr (the file can't tell them apart), so console checks read both.
"""
import os
import queue
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_PRELUDE = """\
import os, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from engine import log_tee
LOG = Path(sys.argv[2])
"""


def _run(body: str, log: Path, cwd: Path,
         timeout: float = 60) -> subprocess.CompletedProcess:
    script = _PRELUDE + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-I", "-c", script, str(PROJECT_ROOT), str(log)],
        capture_output=True, timeout=timeout, cwd=str(cwd))


def _console(proc: subprocess.CompletedProcess) -> bytes:
    return proc.stdout + proc.stderr


def _lines(blob: bytes, needle: str) -> list[str]:
    return [ln for ln in blob.decode("utf-8", "replace").splitlines()
            if needle in ln]


def test_tee_captures_python_and_fd_level_writes(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        assert log_tee.start(LOG) is True
        assert log_tee.start(LOG) is True      # idempotent: no second tee
        print("py-out")
        sys.stderr.write("py-err\\n")
        os.write(2, b"fd-err\\n")              # stand-in for C++ fprintf
        log_tee.stop()
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    text = log.read_text(encoding="utf-8")
    for line in ("py-out", "py-err", "fd-err"):
        assert text.count(line) == 1, (line, text)
    assert not log.with_name("dauntless.prev.log").exists()   # no re-rotate
    for line in (b"py-out", b"py-err", b"fd-err"):
        assert _console(proc).count(line) == 1, (line, _console(proc))


def test_tee_flushes_buffered_c_stdout_into_the_log(tmp_path):
    """CEF's console lines are C `printf` to stdout, which is fully
    buffered once fd 1 is a file. stop() must flush it into the log."""
    if sys.platform == "win32":
        pytest.skip("C stdio flush is POSIX-only")
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        import ctypes
        assert log_tee.start(LOG) is True
        ctypes.CDLL(None).puts(b"c-out")
        log_tee.stop()
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "c-out" in log.read_text(encoding="utf-8")
    assert b"c-out" in _console(proc)


def test_stop_runs_at_exit_without_an_explicit_call(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        assert log_tee.start(LOG) is True
        print("last-words")
        os.write(2, b"fd-last\\n")
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    text = log.read_text(encoding="utf-8")
    assert "last-words" in text and "fd-last" in text
    assert b"last-words" in _console(proc) and b"fd-last" in _console(proc)


def test_rotation_keeps_one_previous(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    for run in ("first-run", "second-run", "third-run"):
        proc = _run("""
            assert log_tee.start(LOG) is True
            print(%r)
        """ % run, log, tmp_path)
        assert proc.returncode == 0, proc.stderr
    prev = log.with_name("dauntless.prev.log")
    assert "third-run" in log.read_text(encoding="utf-8")
    assert "second-run" not in log.read_text(encoding="utf-8")
    assert "second-run" in prev.read_text(encoding="utf-8")
    assert "first-run" not in prev.read_text(encoding="utf-8")


def test_rotate_returns_an_error_string_instead_of_raising(tmp_path):
    from engine import log_tee

    log = tmp_path / "dauntless.log"
    assert log_tee.rotate(log) is None           # nothing to rotate
    log.write_text("old")
    (tmp_path / "dauntless.prev.log").mkdir()
    err = log_tee.rotate(log)
    assert isinstance(err, str) and "dauntless.prev.log" in err
    assert log.read_text(encoding="utf-8") == "old"


def test_rotation_failure_does_not_block_start(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    log.parent.mkdir()
    log.write_text("old-run\n")
    (log.parent / "dauntless.prev.log").mkdir()
    proc = _run("""
        assert log_tee.start(LOG) is True
        print("new-run")
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    text = log.read_text(encoding="utf-8")
    assert "new-run" in text
    assert "old-run" in text          # rotation failed: appended, not lost
    console = _console(proc)
    assert b"old-run" not in console  # the mirror starts at this run
    rotation_lines = _lines(console, "dauntless.prev.log")
    assert len(rotation_lines) == 1, console
    assert "rotate" in rotation_lines[0]


def test_unwritable_log_dir_returns_false_and_continues(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the log folder should be")
    log = blocker / "logs" / "dauntless.log"
    proc = _run("""
        before = (os.fstat(1).st_ino, os.fstat(2).st_ino)
        assert log_tee.start(LOG) is False
        assert (os.fstat(1).st_ino, os.fstat(2).st_ino) == before
        print("still-running")
        log_tee.stop()                         # harmless when never started
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert b"still-running" in proc.stdout
    console = proc.stdout + proc.stderr
    assert len(_lines(console, str(log.parent))) == 1, console
    assert not log.exists()


def test_failed_redirect_puts_the_fds_back(tmp_path):
    """With no follower the console would go silent, so a follower that
    can't start undoes the redirect and reports, like any other failure."""
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        import threading
        before = (os.fstat(1).st_ino, os.fstat(2).st_ino)
        def refuse(self):
            raise RuntimeError("can't start new thread")
        threading.Thread.start = refuse
        assert log_tee.start(LOG) is False
        assert not log_tee.is_active()
        assert (os.fstat(1).st_ino, os.fstat(2).st_ino) == before
        os.write(1, b"still-running\\n")
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert b"still-running" in proc.stdout
    assert len(_lines(proc.stderr, "cannot redirect")) == 1, proc.stderr


def test_gil_holding_writer_is_never_blocked(tmp_path):
    """The measured Concern-1 hang: one 1 MB write from C code that holds
    the GIL (as every pybind11 binding here does). With a pipe and a Python
    reader this froze forever; writers must go straight to the file."""
    if sys.platform == "win32":
        pytest.skip("ctypes.PyDLL(None) needs a POSIX process handle")
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        import ctypes
        log_tee._DRAIN_S = 30.0          # load-proof: copy all 1 MB to console
        assert log_tee.start(LOG) is True
        data = (b"y" * 99 + b"\\n") * 10000 + b"gil-done\\n"
        libc = ctypes.PyDLL(None)        # PyDLL: the call HOLDS the GIL
        libc.write.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t)
        assert libc.write(2, data, len(data)) == len(data)
        log_tee.stop()
    """, log, tmp_path, timeout=20)
    assert proc.returncode == 0, proc.stderr[-300:]
    text = log.read_bytes()
    assert text.count(b"y" * 99 + b"\n") == 10000
    assert b"gil-done" in text
    assert _console(proc).count(b"y" * 99 + b"\n") == 10000
    assert b"gil-done" in _console(proc)


def test_log_is_complete_when_the_process_dies_without_stop(tmp_path):
    """A crash skips atexit. Everything written before it is in the log."""
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        assert log_tee.start(LOG) is True
        os.write(2, b"z" * 300000 + b"\\nlast-before-crash\\n")
        os._exit(3)
    """, log, tmp_path)
    assert proc.returncode == 3
    text = log.read_bytes()
    assert text.count(b"z") == 300000
    assert b"last-before-crash" in text


def test_console_mirror_is_live_while_running(tmp_path):
    """The follower copies to the console during the run, not only when
    stop() drains: the parent sees the line while the child still waits."""
    log = tmp_path / "logs" / "dauntless.log"
    script = _PRELUDE + textwrap.dedent("""
        assert log_tee.start(LOG) is True
        os.write(2, b"live-ping\\n")
        sys.stdin.readline()               # held until the parent saw it
        log_tee.stop()
    """)
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", script, str(PROJECT_ROOT), str(log)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(tmp_path))
    lines: "queue.Queue[bytes]" = queue.Queue()

    def collect(stream):
        for line in iter(stream.readline, b""):
            lines.put(line)

    for stream in (child.stdout, child.stderr):
        threading.Thread(target=collect, args=(stream,), daemon=True).start()
    try:
        seen = b""
        while b"live-ping" not in seen:
            seen += lines.get(timeout=10)
    finally:
        child.stdin.write(b"go\n")
        child.stdin.close()
        assert child.wait(timeout=30) == 0


def test_follower_copies_a_write_that_lands_just_before_stop(tmp_path):
    """Race found while stress-running the GIL test (about 1 run in 15):
    the follower reads EOF, a final write lands and stop() runs before the
    follower gets the GIL back, and it took that stale EOF as "drained".
    Forced here: the final write waits for the follower's first EOF, and that
    EOF read is held until stop() has asked."""
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        import threading, types
        first_eof = threading.Event()
        released = threading.Event()
        class _Os(types.ModuleType):
            def __getattr__(self, name):
                return getattr(os, name)
        proxy = _Os("os")
        def read(fd, n):
            data = os.read(fd, n)
            if (threading.current_thread().name == "dauntless-log-follower"
                    and not data and not released.is_set()):
                first_eof.set()
                released.wait(5)      # stale EOF, observed before stop()
            return data
        proxy.read = read
        log_tee.os = proxy
        assert log_tee.start(LOG) is True
        stopping = log_tee._state.stopping
        real_set = stopping.set
        def set_and_release():
            real_set()
            released.set()
        stopping.set = set_and_release
        assert first_eof.wait(5)
        os.write(2, b"just-before-stop\\n")
        log_tee.stop()
    """, log, tmp_path, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert b"just-before-stop\n" in log.read_bytes()
    assert b"just-before-stop\n" in _console(proc)


def test_windows_console_streams_are_rewrapped_and_restored(tmp_path):
    """On a Windows console, sys.stdout/err sit on _WindowsConsoleIO, which
    calls WriteConsoleW on the fd's handle -- a FILE after the redirect, so
    every print would raise. Faked here with a raw type that refuses regular
    files, injected as the console-IO type."""
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        import io, stat
        class FakeConsoleIO(io.FileIO):
            def write(self, b):
                if stat.S_ISREG(os.fstat(self.fileno()).st_mode):
                    raise OSError(22, "WriteConsoleW on a file handle")
                return super().write(b)
        fake = io.TextIOWrapper(
            io.BufferedWriter(FakeConsoleIO(1, "w", closefd=False)),
            encoding="utf-8", line_buffering=True)
        sys.stdout = fake
        plain_err = sys.stderr
        log_tee._console_io_types = lambda: (FakeConsoleIO,)
        assert log_tee.start(LOG) is True
        assert sys.stdout is not fake
        assert sys.stderr is plain_err          # not console IO: untouched
        print("swapped-print \\u00e9")
        log_tee.stop()
        assert sys.stdout is fake
        print("after-stop")
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    text = log.read_text(encoding="utf-8")
    assert "swapped-print é" in text
    assert "after-stop" not in text
    assert b"after-stop" in proc.stdout


def test_no_console_still_writes_the_log(tmp_path):
    """A GUI-subsystem exe has no std handles. That disables only the
    console mirror; fds 1/2 still go to the log. (Closed std fds also make
    os.open hand out fd 1 or 2, which must not be clobbered.)

    sys.stdout/sys.stderr are None there, so print(), the
    report_write_failure line and an uncaught exception's traceback would
    all be dropped by Python before reaching any fd. The tee installs text
    streams on fds 1/2 for its lifetime and puts None back at stop(); the
    checks after stop run in an atexit handler registered BEFORE start(),
    so it runs after the tee's own atexit stop."""
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        import atexit, threading
        from engine import paths
        sys.stdout = sys.stderr = None
        os.close(1)
        os.close(2)
        def closed(fd):
            try:
                os.fstat(fd)
            except OSError:
                return True
            return False
        def after_stop():
            ok = (not log_tee.is_active() and closed(1) and closed(2)
                  and sys.stdout is None and sys.stderr is None)
            os._exit(0 if ok else 8)
        atexit.register(after_stop)
        ok = log_tee.start(LOG) is True and log_tee.is_active()
        ok = ok and log_tee._state.log_fd > 2      # not handed fd 1 or 2
        ok = ok and not [t for t in threading.enumerate()
                         if t.name == "dauntless-log-follower"]
        if not ok:
            os._exit(7)
        os.write(1, b"gui-out\\n")
        os.write(2, b"gui-err\\n")
        print("gui-print \\u00e9")
        paths.report_write_failure("/no/such/gui-target", OSError(13, "denied"))
        raise RuntimeError("gui-uncaught")
    """, log, tmp_path)
    assert proc.returncode == 0, proc.returncode
    text = log.read_text(encoding="utf-8")
    assert "gui-out" in text and "gui-err" in text
    assert "gui-print \u00e9" in text
    assert "[dauntless] could not write /no/such/gui-target" in text
    assert "RuntimeError: gui-uncaught" in text


def test_closed_stdout_keeps_the_mirror_and_the_log(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        sys.stdout = None
        os.close(1)
        assert log_tee.start(LOG) is True
        assert log_tee._state.log_fd > 2 and log_tee._state.read_fd > 2
        os.write(1, b"half-out\\n")
        os.write(2, b"half-err\\n")
        log_tee.stop()
        try:
            os.fstat(1)
        except OSError:
            pass
        else:
            raise AssertionError("fd 1 was closed before start; stop left it open")
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    text = log.read_text(encoding="utf-8")
    assert text.count("half-out") == 1 and text.count("half-err") == 1
    assert b"half-out" in proc.stderr and b"half-err" in proc.stderr


def test_closed_stderr_mirrors_to_stdout(tmp_path):
    """With fd 2 closed, saving fd 1 hands out fd 2 -- which the redirect
    would then turn into the log, so the mirror would copy the log into
    itself."""
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        sys.stderr = None
        os.close(2)
        assert log_tee.start(LOG) is True
        os.write(1, b"solo-out\\n")
        log_tee.stop()
        os.write(1, b"after-stop\\n")          # fd 1 is the console again
        try:
            os.fstat(2)
        except OSError:
            pass
        else:
            os.write(1, b"fd 2 left open\\n")
    """, log, tmp_path)
    assert proc.returncode == 0
    text = log.read_text(encoding="utf-8")
    assert text.count("solo-out") == 1
    assert "after-stop" not in text
    assert b"solo-out" in proc.stdout and b"after-stop" in proc.stdout
    assert b"fd 2 left open" not in proc.stdout


def test_rotation_and_open_both_failing_reports_both(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    log.mkdir(parents=True)                         # can't be opened
    prev = log.with_name("dauntless.prev.log")
    (prev / "keep").mkdir(parents=True)             # can't be replaced
    proc = _run("""
        assert log_tee.start(LOG) is False
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert len(_lines(proc.stderr, "could not rotate")) == 1, proc.stderr
    assert len(_lines(proc.stderr, "cannot open")) == 1, proc.stderr


def test_stop_restores_the_fds_even_if_a_flush_raises(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        before = os.fstat(1).st_ino
        assert log_tee.start(LOG) is True
        class Broken:
            def flush(self):
                raise RuntimeError("flush exploded")
        real_stdout, sys.stdout = sys.stdout, Broken()
        try:
            log_tee.stop()
        except RuntimeError:
            pass
        sys.stdout = real_stdout
        assert os.fstat(1).st_ino == before
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
