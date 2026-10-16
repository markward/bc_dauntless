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
    text = log.read_text()
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
    assert "c-out" in log.read_text()
    assert b"c-out" in _console(proc)


def test_stop_runs_at_exit_without_an_explicit_call(tmp_path):
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        assert log_tee.start(LOG) is True
        print("last-words")
        os.write(2, b"fd-last\\n")
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    text = log.read_text()
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
    assert "third-run" in log.read_text()
    assert "second-run" not in log.read_text()
    assert "second-run" in prev.read_text()
    assert "first-run" not in prev.read_text()


def test_rotate_returns_an_error_string_instead_of_raising(tmp_path):
    from engine import log_tee

    log = tmp_path / "dauntless.log"
    assert log_tee.rotate(log) is None           # nothing to rotate
    log.write_text("old")
    (tmp_path / "dauntless.prev.log").mkdir()
    err = log_tee.rotate(log)
    assert isinstance(err, str) and "dauntless.prev.log" in err
    assert log.read_text() == "old"


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
    text = log.read_text()
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
    The follower's first EOF read is held here until stop() has asked, which
    forces that interleaving every time."""
    log = tmp_path / "logs" / "dauntless.log"
    proc = _run("""
        import threading, types
        released = threading.Event()
        class _Os(types.ModuleType):
            def __getattr__(self, name):
                return getattr(os, name)
        proxy = _Os("os")
        def read(fd, n):
            data = os.read(fd, n)
            if (threading.current_thread().name == "dauntless-log-follower"
                    and not data and not released.is_set()):
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
        os.write(2, b"just-before-stop\\\\n")
        log_tee.stop()
    """, log, tmp_path, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert b"just-before-stop" in log.read_bytes()
    assert b"just-before-stop" in _console(proc)
