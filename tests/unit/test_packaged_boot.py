"""`import engine` in a packaged build stops bytecode writes and starts the
log tee; in a checkout it does neither (spec 2026-10-16 per-user data dirs,
§5.4 P15 and §5.5)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from engine import paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_CHILD = """\
import sys
sys.path.insert(0, sys.argv[1])
import engine
print("dont_write_bytecode=%s" % sys.dont_write_bytecode)
import engine.units
print("boot-line")
"""


def _packaged_import(tmp_path: Path, data: Path):
    """Run _CHILD against a tmp copy of engine/ carrying the marker."""
    install = tmp_path / "install"
    shutil.copytree(PROJECT_ROOT / "engine", install / "engine",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (install / paths.PACKAGED_MARKER).write_text("{}")
    env = dict(os.environ)
    env[paths.DATA_DIR_ENV] = str(data)
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD, str(install)],
        capture_output=True, timeout=60, env=env, cwd=str(tmp_path))
    return install, proc


def test_packaged_import_disables_bytecode_and_starts_tee(tmp_path):
    data = tmp_path / "data"
    install, proc = _packaged_import(tmp_path, data)

    assert proc.returncode == 0, proc.stderr
    log = data / "logs" / "dauntless.log"
    assert log.is_file()
    assert "dont_write_bytecode=True" in log.read_text()
    assert "boot-line" in log.read_text()
    # The console mirror merges stdout onto the original stderr.
    assert b"boot-line" in proc.stdout + proc.stderr
    # Modules imported after the switch leave no bytecode in the install.
    assert not list((install / "engine").glob("__pycache__/units.*"))


def test_packaged_import_survives_an_unusable_log_dir(tmp_path):
    data = tmp_path / "data"
    data.write_text("a file where the data folder should be")
    _, proc = _packaged_import(tmp_path, data)

    assert proc.returncode == 0, proc.stderr
    assert b"dont_write_bytecode=True" in proc.stdout
    assert b"boot-line" in proc.stdout
    assert proc.stderr.count(b"log file disabled") == 1, proc.stderr


def test_checkout_import_starts_nothing():
    import engine  # noqa: F401  (already imported by the suite; must be inert)

    assert not paths.is_packaged()
    assert sys.dont_write_bytecode == bool(sys.flags.dont_write_bytecode)
    assert not paths.log_file_path().exists()
    log_tee = sys.modules.get("engine.log_tee")
    assert log_tee is None or not log_tee.is_active()
