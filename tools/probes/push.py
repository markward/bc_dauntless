"""Copy a probe file from tools/probes/ to game/ so the operator can execfile() it.

Usage:
    uv run python tools/probes/push.py q01
    uv run python tools/probes/push.py q01_console_io     # full prefix also works
    uv run python tools/probes/push.py --all              # push every probe
"""
import pathlib
import shutil
import sys

PROBES = pathlib.Path(__file__).parent
GAME = PROBES.parent.parent / "game"


def find_probes(query: str) -> list[pathlib.Path]:
    return sorted(p for p in PROBES.glob(f"{query}*.py") if not p.name.startswith("_"))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    if not GAME.exists():
        print(f"game/ not found at {GAME}")
        sys.exit(1)

    if sys.argv[1] == "--all":
        targets = sorted(p for p in PROBES.glob("q*.py"))
    else:
        targets = find_probes(sys.argv[1])

    if not targets:
        print(f"no probe matches '{sys.argv[1]}' in {PROBES}")
        sys.exit(1)

    for probe in targets:
        dest = GAME / probe.name
        shutil.copy2(probe, dest)
        print(f"  {probe.name} -> {dest}")

    print()
    print("In the -TestMode REPL, run:")
    for probe in targets:
        print(f"  execfile('{probe.name}')")


if __name__ == "__main__":
    main()
