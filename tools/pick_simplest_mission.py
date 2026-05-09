"""Rank SDK missions by simplicity and print the smallest.

Heuristic: source-line count + 10 * (count of strings 'CreateShip' or
'AddObject' or 'CreateShipSet'). Lower is simpler. Ties broken alphabetically.

Usage:
    uv run python tools/pick_simplest_mission.py
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SDK_SCRIPTS = PROJECT_ROOT / "sdk" / "Build" / "scripts"

SPAWN_PATTERNS = [
    re.compile(r"\bCreateShip\b"),
    re.compile(r"\bAddObject\b"),
    re.compile(r"\bCreateShipSet\b"),
]


def discover_missions():
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
        missions.append((py_file, text))
    return missions


def score(text):
    lines = sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))
    spawns = sum(len(p.findall(text)) for p in SPAWN_PATTERNS)
    return lines + 10 * spawns


def main():
    missions = discover_missions()
    if not missions:
        print("no missions found", file=sys.stderr)
        return 1
    ranked = sorted((score(text), str(p.relative_to(SDK_SCRIPTS)), p, text) for p, text in missions)
    print("ranked by simplicity (lower = simpler):")
    for s, rel, _, _ in ranked[:5]:
        print(f"  {s:5d}  {rel}")
    s, rel, p, _ = ranked[0]
    rel_module = ".".join(p.relative_to(SDK_SCRIPTS).with_suffix("").parts)
    print(f"winner: {rel_module} (score {s}, path {rel})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
