"""Run the host binary and assert it can call a Phase 1 SDK-importing function."""
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOST_BIN = PROJECT_ROOT / "build" / "dauntless"


def _require_host_bin():
    if not HOST_BIN.exists():
        import pytest
        pytest.skip(f"host binary not built at {HOST_BIN}")


def test_host_runs_smoke_check():
    _require_host_bin()
    result = subprocess.run(
        [str(HOST_BIN), "--smoke-check"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"host exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "app_module" in result.stdout
    assert "python_version" in result.stdout


def test_host_launched_by_bare_name_through_path(tmp_path):
    """A launch through PATH from a foreign cwd must start and enter the root.

    Two defects met here, both measured rather than reasoned about:

    * canonical(argv[0]) resolved a bare name against the cwd and threw. With
      no handler that aborted the process -- exit 134 and one libc++abi line on
      macOS, 0xC0000409 and zero bytes of output on Windows.
    * Once it started, cwd was still the caller's. Every renderer asset path is
      relative to the project root, so all 36 "game/data/..." load sites
      dangled (4 "[breach] failed to open" lines from /tmp, 0 from the root)
      while the process carried on and drew untextured passes.

    The cwd assertion is the part a green suite could not otherwise see: no
    asset loads happen under --smoke-check, so nothing else here would notice.
    """
    _require_host_bin()
    env = dict(os.environ)
    env["PATH"] = str(HOST_BIN.parent) + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        [HOST_BIN.name, "--smoke-check"],   # bare name: resolved via PATH
        capture_output=True,
        text=True,
        cwd=str(tmp_path),                  # NOT the project root
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"host exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    printed = eval(result.stdout.strip())   # the host prints repr(dict)
    assert Path(printed["cwd"]).resolve() == PROJECT_ROOT.resolve(), (
        f"host ran with cwd {printed['cwd']!r}; every renderer asset path is "
        f"relative to {PROJECT_ROOT}, so assets would fail to load"
    )
