"""Bake each charted system's sun TEXTURE CLASS into sector_model.json.

BC carries a star's colour in a texture name, not as a value. Every
Systems/<Name>/*_S.py that has a star calls:

    App.Sun_Create(fRadius, fAtmosphereThickness, fDamagePerSec,
                   fBaseTexture, fFlareTexture)

with one of four base textures — SunYellow, SunRedOrange, SunRed,
SunBlueWhite — or with the texture arguments omitted entirely, which is the
engine's default and reads as SunBase.tga.

Only the CLASS is baked. The colours live in engine/ui/star_map.py beside the
rest of the map palette, so tuning one costs a page refresh rather than a
re-bake; this file records only what the SDK actually says.

Idempotent, and additive: it rewrites `star` on the systems it can resolve and
leaves every other field (positions, warp points, nebulae) untouched.

    uv run python tools/bake_star_colors.py [--check]

--check exits non-zero if the baked file disagrees with the SDK, without
writing — for use when the SDK tree changes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_SYSTEMS = ROOT / "sdk" / "Build" / "scripts" / "Systems"
OUT = ROOT / "engine" / "appc" / "sector_model.json"

# A Sun_Create call with no texture arguments gets the engine's own default,
# which ships as SunBase.tga alongside the four named ones.
DEFAULT_TEXTURE = "SunBase"

_SUN_CALL = re.compile(r"Sun_Create\s*\(")
_BASE_TEXTURE = re.compile(r'"data/Textures/(Sun\w*)\.tga"')


def sun_texture_for(system_dir: Path):
    """The sun texture class this system declares, or None if it has no star.

    Comment lines are skipped: every *_S.py carries the API signature as a
    commented-out example call, and counting those would give every system a
    star. Returns None on a disagreement rather than guessing — no stock
    system has one (checked: 27 systems, zero mixed), so a hit means the SDK
    changed shape and a human should look.
    """
    found = set()
    for path in sorted(system_dir.glob("*.py")):
        for line in path.read_text(errors="ignore").splitlines():
            if line.lstrip().startswith("#") or not _SUN_CALL.search(line):
                continue
            m = _BASE_TEXTURE.search(line)
            found.add(m.group(1) if m else DEFAULT_TEXTURE)
    if len(found) > 1:
        print("  ! %s declares several sun textures: %s"
              % (system_dir.name, ", ".join(sorted(found))), file=sys.stderr)
        return None
    return found.pop() if found else None


def collect():
    """{map system id: texture class} for every system that declares a star."""
    sys.path.insert(0, str(ROOT))
    from engine.appc.sector_model import system_id_for_set

    out = {}
    for d in sorted(SDK_SYSTEMS.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        texture = sun_texture_for(d)
        if texture is None:
            continue
        # Several SDK dirs fold onto one charted system — Starbase12 and
        # DryDock are both Tau Ceti. They agree in stock content; if they ever
        # did not, first-writer-wins would be arbitrary, so say so.
        sid = system_id_for_set(d.name)
        if out.get(sid, texture) != texture:
            print("  ! %s: %s and %s disagree" % (sid, out[sid], texture),
                  file=sys.stderr)
        out[sid] = texture
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report disagreement with the SDK; write nothing")
    args = ap.parse_args(argv)

    stars = collect()
    model = json.loads(OUT.read_text(encoding="utf-8"))

    changed, unmatched = [], set(stars)
    for entry in model.get("systems", []):
        sid = entry.get("id")
        unmatched.discard(sid)
        want = stars.get(sid)
        if want is None:
            # A charted system with no Sun_Create keeps no `star` key at all;
            # star_map falls back to STAR_COLOR for it.
            if entry.pop("star", None) is not None:
                changed.append(sid + " (star removed)")
            continue
        if entry.get("star") != want:
            changed.append("%s -> %s" % (sid, want))
            entry["star"] = want

    # multi* is multiplayer map scaffolding, which sector_model deliberately
    # does not chart (sector_model.is_real_system). Warning about it every run
    # would train the reader to ignore this channel, so only unexpected gaps
    # are reported.
    from engine.appc.sector_model import is_real_system
    for sid in sorted(s for s in unmatched if is_real_system(s)):
        print("  ! %s has a sun but is not charted in sector_model.json" % sid,
              file=sys.stderr)

    starred = sum(1 for e in model.get("systems", []) if e.get("star"))
    print("systems charted: %d | with a star: %d | changed: %d"
          % (len(model.get("systems", [])), starred, len(changed)))
    for line in changed:
        print("  " + line)

    if args.check:
        return 1 if changed else 0
    if changed:
        OUT.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
        print("wrote " + str(OUT.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
