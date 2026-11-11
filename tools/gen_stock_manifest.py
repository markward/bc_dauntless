"""Generate engine/stock_manifest.json: the retail stock script paths and
their known content hashes (spec 2026-11-11-no-sdk-runtime-design.md S4.1).

Holds relative paths and hashes ONLY, never BC content. Dry run by default;
`--write` replaces the manifest from the configured install, `--add` merges
the install's hashes into the committed one (a second verified retail build).
"""
import argparse
import hashlib
import json
from pathlib import Path

FORMAT = 1
HASH = "blake2b-128"
GENERATOR = "tools/gen_stock_manifest.py"


def manifest_path() -> Path:
    return Path(__file__).resolve().parent.parent / "engine" / "stock_manifest.json"


def build(scripts_root: Path, project_root: Path) -> dict:
    """The modules mapping for ONE install: rel path -> [hash]."""
    out = {}
    for f in sorted(Path(scripts_root).rglob("*.pyc")):
        rel = f.relative_to(scripts_root).as_posix()
        if (Path(project_root) / (rel[:-len(".pyc")] + ".py")).exists():
            continue
        out[rel] = [hashlib.blake2b(f.read_bytes(), digest_size=16).hexdigest()]
    return out


def merge(committed: dict, built: dict) -> dict:
    out = {p: list(hs) for p, hs in committed.items()}
    for p, hs in built.items():
        known = out.setdefault(p, [])
        known.extend(h for h in hs if h not in known)
    return out


def serialise(modules: dict) -> str:
    obj = {
        "format": FORMAT,
        "hash": HASH,
        "generator": GENERATOR,
        "modules": {p: sorted(hs) for p, hs in modules.items()},
    }
    return json.dumps(obj, indent=1, sort_keys=True) + "\n"


def main(argv=None) -> int:
    from engine import paths

    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="replace the manifest from the configured install")
    mode.add_argument("--add", action="store_true",
                      help="merge the configured install's hashes into it")
    args = ap.parse_args(argv)

    built = build(paths.stock_scripts(), paths.PROJECT_ROOT)
    target = manifest_path()
    if args.add:
        old = json.loads(target.read_text(encoding="utf-8"))["modules"]
        result = merge(old, built)
    else:
        result = built
    text = serialise(result)
    custom = [p for p in result if p.startswith("Custom/")]
    print(f"install: {paths.stock_scripts()}")
    print(f"entries: {len(result)}  hashes: {sum(len(h) for h in result.values())}"
          f"  Custom/ entries: {len(custom)}")
    if args.write or args.add:
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
    else:
        print("dry run (use --write or --add)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
