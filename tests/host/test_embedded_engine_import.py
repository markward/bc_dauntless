"""Run the host binary and assert it imports engine.bootstrap successfully."""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOST_BIN = PROJECT_ROOT / "build" / "bin" / "open_stbc_host"


def test_host_imports_engine_bootstrap():
    if not HOST_BIN.exists():
        import pytest
        pytest.skip(f"host binary not built at {HOST_BIN}")
    result = subprocess.run(
        [str(HOST_BIN)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15,
    )
    assert result.returncode == 0, (
        f"host exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "open_stbc host alive" in result.stdout, (
        f"banner missing from stdout:\n{result.stdout}"
    )
