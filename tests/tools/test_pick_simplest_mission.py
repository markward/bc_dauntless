"""Verify pick_simplest_mission.py produces a deterministic top result."""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT = PROJECT_ROOT / "tools" / "pick_simplest_mission.py"


def test_script_runs_and_picks_a_mission():
    if not (PROJECT_ROOT / "sdk" / "Build" / "scripts").is_dir():
        import pytest
        pytest.skip("SDK not available")
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT)],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "winner:" in result.stdout
