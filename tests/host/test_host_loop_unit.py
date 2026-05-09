"""host_loop module imports cleanly and exposes the public symbols."""


def test_imports():
    from engine import host_loop
    assert hasattr(host_loop, "run")
    assert isinstance(host_loop.SHIP_GATE_MISSION, str)
    assert host_loop.SHIP_GATE_MISSION == "Custom.Tutorial.Episode.M1Basic.M1Basic"


def test_renderer_module_exposes_bindings():
    from engine import renderer
    for name in ("init", "shutdown", "frame", "load_model",
                 "create_instance", "set_world_transform", "set_camera"):
        assert hasattr(renderer, name)


def test_run_M1_Basic_for_a_few_ticks():
    import os
    from pathlib import Path
    import pytest

    PROJECT_ROOT = Path(__file__).parent.parent.parent
    GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    from engine import host_loop
    rc = host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic", max_ticks=5)
    assert rc == 0


def test_run_M1_Basic_in_clean_subprocess():
    """Regression: in-process pytest tests don't catch the case where
    setup_sdk's _SDKFinder masks stdlib `string` (which BC's
    sdk/Build/scripts/string.py shadows with Python 1.5 syntax). pytest
    itself transitively imports logging -> string before any test runs,
    so stdlib string is already cached in sys.modules when setup_sdk()
    installs the finder. A fresh subprocess imports modules in the same
    order the host binary does and surfaces the bug."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    import pytest

    project_root = Path(__file__).parent.parent.parent
    if not (project_root / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif").is_file():
        pytest.skip("BC assets not available")
    if not (project_root / "build" / "python").is_dir():
        pytest.skip("native _open_stbc_host module not built")

    env = dict(os.environ)
    env["OPEN_STBC_HOST_HEADLESS"] = "1"
    snippet = (
        "import sys\n"
        f"sys.path.insert(0, {str(project_root)!r})\n"
        f"sys.path.insert(0, {str(project_root / 'build' / 'python')!r})\n"
        "from engine import host_loop\n"
        "sys.exit(host_loop.run(max_ticks=3))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=str(project_root), env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"host_loop.run failed in clean subprocess (returncode {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
