"""
Mission Initialize harness for open_stbc.

Discovers all SDK mission scripts and attempts Initialize(pMission) on each,
reporting a ranked summary of failures.

Usage:
    uv run python tools/mission_harness.py
"""
import ast
import importlib
import importlib.abc
import importlib.machinery
import sys
import types
import warnings
from collections import Counter
from pathlib import Path

# Ensure project root is on sys.path whether run as script or imported in tests
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SDK_SCRIPTS = _PROJECT_ROOT / "sdk" / "Build" / "scripts"


def discover_missions() -> list[str]:
    """Return sorted list of dotted module names for all SDK mission scripts.

    A mission script is any .py file (not __init__.py) that contains the
    string 'def Initialize(pMission)'.  Episode-level scripts use
    'def Initialize(pEpisode)' and are therefore excluded automatically.
    """
    missions = []
    for py_file in sorted(SDK_SCRIPTS.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "def Initialize(pMission)" not in text:
            continue
        rel = py_file.relative_to(SDK_SCRIPTS)
        module_name = ".".join(rel.with_suffix("").parts)
        missions.append(module_name)
    return missions
