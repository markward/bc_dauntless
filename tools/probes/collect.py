"""Extract a probe's [BCProbe_q0N] section from game/BCProbe_q0N.cfg.

Each probe writes a multi-line result log into a single section of a cfg dump.
The dump also contains everything in Options.cfg (the game's whole config) --
we strip it down to just the probe section before committing to the repo.

Usage:
    uv run python tools/probes/collect.py q01
    uv run python tools/probes/collect.py --all
"""
import pathlib
import re
import sys

PROBES = pathlib.Path(__file__).parent
RESULTS = PROBES / "results"
GAME = PROBES.parent.parent / "game"


def extract_section(cfg_path: pathlib.Path, section: str) -> list[str]:
    """Return the ordered list of values in [section], skipping count/empty keys."""
    if not cfg_path.exists():
        return []
    in_section = False
    rows: dict[int, str] = {}
    with cfg_path.open(encoding="latin-1") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if line == f"[{section}]":
                in_section = True
                continue
            if line.startswith("[") and in_section:
                break
            if not in_section:
                continue
            sep = "=" if "=" in line else "|" if "|" in line else ""
            if not sep:
                continue
            key, _, val = line.partition(sep)
            m = re.match(r"r(\d+)$", key)
            if m and val:                    # skip empty values from scrub
                rows[int(m.group(1))] = val
    return [rows[k] for k in sorted(rows)]


def probe_id_from_filename(name: str) -> str:
    """tools/probes/q01_console_io.py -> 'q01'"""
    return name.split("_", 1)[0]


def collect_one(probe_file: pathlib.Path) -> bool:
    qid = probe_id_from_filename(probe_file.stem)
    section = f"BCProbe_{qid}"
    cfg = GAME / f"BCProbe_{qid}.cfg"
    if not cfg.exists():
        print(f"  {qid}: no {cfg.name} in game/ -- has the probe been run?")
        return False
    lines = extract_section(cfg, section)
    if not lines:
        print(f"  {qid}: {cfg.name} exists but [{section}] is empty")
        return False
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{probe_file.stem}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  {qid}: wrote {out.relative_to(PROBES.parent.parent)}  ({len(lines)} lines)")
    return True


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    if sys.argv[1] == "--all":
        targets = sorted(p for p in PROBES.glob("q*.py"))
    else:
        targets = sorted(p for p in PROBES.glob(f"{sys.argv[1]}*.py") if not p.name.startswith("_"))

    if not targets:
        print(f"no probe matches '{sys.argv[1]}'")
        sys.exit(1)

    any_ok = False
    for probe in targets:
        if collect_one(probe):
            any_ok = True
    if not any_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
