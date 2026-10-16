"""engine.log_tee: packaged builds tee fds 1 and 2 to a rotated log
(spec 2026-10-16 per-user data dirs, §5.5; review focus 4).

The tee rewires the process's own file descriptors, so every test runs it in
a child interpreter. `-I` ignores PYTHONPATH, so the child puts the project
root on sys.path itself (argv[1]).
"""
import os
import subprocess
import sys
import textwrap
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


def _run(body: str, log: Path, cwd: Path) -> subprocess.CompletedProcess:
    script = _PRELUDE + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-I", "-c", script, str(PROJECT_ROOT), str(log)],
        capture_output=True, timeout=60, cwd=str(cwd))


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
    assert b"py-out" in proc.stdout
    assert b"py-err" in proc.stderr
    assert b"fd-err" in proc.stderr


def test_tee_flushes_buffered_c_stdout_into_the_log(tmp_path):
    """CEF's console lines are C `printf` to stdout, which is fully
    buffered once fd 1 is a pipe. stop() must flush it into the log."""
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
    assert b"c-out" in proc.stdout


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
    assert b"last-words" in proc.stdout


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
    console = proc.stdout + proc.stderr
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
    """A reader that can't start would leave fd 1/2 on a pipe nobody drains
    (the process blocks once it fills), so start() must undo everything."""
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
        os.write(1, b"x" * 200000 + b"\\nstill-running\\n")   # > any pipe
    """, log, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert b"still-running" in proc.stdout
    assert len(_lines(proc.stderr, "cannot redirect")) == 1, proc.stderr
