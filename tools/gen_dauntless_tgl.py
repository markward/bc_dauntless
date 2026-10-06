"""Generate Dauntless's own crew-dialogue TGL from its JSON source.

Source:  tools/dialogue/dauntless_crew.json -- one entry per line: the TGL key,
         the subtitle text, and the voice file (game-root-relative).
Output:  <replacements>/data/TGL/Dauntless Crew.tgl, in BC's own layout
         (engine.missions.tgl_reader.write_tgl), so the SDK's
         g_kLocalizationManager.Load finds it through the replacements
         overlay exactly like a stock database.

Without --write it only reports whether the committed file is current;
tests/tools/test_dauntless_dialogue_drift.py fails on any drift.
"""
import argparse
import json
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from engine import mods  # noqa: E402
from engine.missions.tgl_reader import write_tgl  # noqa: E402

SOURCE = _PROJECT / "tools" / "dialogue" / "dauntless_crew.json"


def _load() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def entries() -> list:
    """(key, text, sound) triples in source order."""
    return [(ln["key"], ln["text"], ln.get("sound", "")) for ln in _load()["lines"]]


def tgl_path() -> Path:
    return mods.replacements_root() / _load()["tgl"]


def build() -> bytes:
    return write_tgl(entries())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="write the TGL (default: report drift only)")
    args = parser.parse_args(argv)
    out, data = tgl_path(), build()
    current = out.is_file() and out.read_bytes() == data
    if args.write and not current:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(f"wrote {out} ({len(entries())} lines)")
    else:
        print(f"{out}: {'current' if current else 'STALE -- run with --write'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
