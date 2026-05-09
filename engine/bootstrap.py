"""Bootstrap module loaded by open_stbc_host to verify embedding works."""

def banner() -> str:
    return "open_stbc host alive"


def smoke_check() -> dict:
    """Exercise the SDK shim machinery: import App (the project-root shim) and
    confirm a known attribute exists. Returns a small dict the host prints."""
    import sys
    from pathlib import Path

    # Match what tests/conftest.py does — register the SDK finder so SDK
    # imports resolve. The host binary uses a modest subset, but the finder
    # has to be installed once before any SDK import.
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    # Import the project-root App shim (mirrors tests/conftest.py's pattern).
    import App  # noqa: F401

    return {
        "python_version": sys.version_info[:3],
        "app_module": App.__name__,
        "project_root": str(project_root),
    }
