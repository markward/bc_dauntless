"""Run the host binary and assert it can call a Phase 1 SDK-importing function."""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOST_BIN = PROJECT_ROOT / "build" / "dauntless"


def test_host_runs_smoke_check():
    if not HOST_BIN.exists():
        import pytest
        pytest.skip(f"host binary not built at {HOST_BIN}")
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
