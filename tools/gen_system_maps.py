"""Generate system maps from the BC SDK.

Usage:
    uv run python tools/gen_system_maps.py --system Ona
    uv run python tools/gen_system_maps.py                 # every system
    uv run python tools/gen_system_maps.py --check         # validate, write nothing

A map has a GENERATED part and an OVERRIDES part. This tool rewrites the
former and preserves the latter, so hand art-direction survives regeneration.
Read the design doc before changing the layout rules:
docs/superpowers/specs/2026-09-22-in-system-navigation-design.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path whether run as script or imported in tests.
# Same shim as tools/tgl_harness.py:17-20.
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.systems.map import available, load, save  # noqa: E402
from engine.systems.validate import validate  # noqa: E402
from tools.systems.layout import LayoutTuning, ambiguities, layout  # noqa: E402
from tools.systems.survey import (  # noqa: E402
    bc_offsets, bc_radii, staged_points, survey_system, system_names,
)


def _merge_overrides(fresh, old) -> None:
    """Carry the hand-edited overrides block forward onto a fresh map."""
    if old is not None and getattr(old, "overrides", None):
        fresh.overrides = dict(old.overrides)


def pins_from(m):
    """Declared pins as {body_name: (x, y, z)}, or None when there are none.

    A pin is a body a mission stages ships beside, so the layout must not move
    it away from that content. They are hand-declared rather than detected:
    there are two across all 89 regions, and Xi Entrades 5's is keyed to a
    PHANTOM waypoint (`Moon1` at (400, 5000, 0)) that no body occupies, which
    any body-keyed heuristic would miss.
    """
    raw = (getattr(m, "overrides", None) or {}).get("pins") or {}
    if not raw:
        return None
    return {name: tuple(float(c) for c in offset) for name, offset in raw.items()}


def star_from(m):
    """The map's declared star override as a dict, or None.

    A system that authors no Sun_Create at all (Belaruz, Vesuvi) falls to a
    generic brown_dwarf. `overrides.star` corrects that by hand where the
    player-facing description says something else and is better-evidenced --
    see layout()'s `star` argument, which this feeds the same way pins_from()
    feeds `pins`.
    """
    if m is None:
        return None
    return (getattr(m, "overrides", None) or {}).get("star")


def cloud_from(m):
    """The map's declared cloud override as a dict, or None.

    Mirrors star_from() exactly: only two systems (Belaruz, Vesuvi) carry
    a nebula at all, and `overrides.cloud` is the only place a system-scale
    shell/lobe shape and name can be hand-declared -- see layout()'s `cloud`
    argument, which this feeds the same way star_from() feeds `star`.
    """
    if m is None:
        return None
    return (getattr(m, "overrides", None) or {}).get("cloud")


def generate(system: str):
    """Survey, lay out, and carry the existing map's overrides forward.

    Deliberately does NOT swallow a read failure. The overrides block is the
    only place hand art-direction lives, and main() writes the result straight
    back over the file -- so treating an unreadable map as "no prior map"
    would silently replace a human's work with a fresh layout. Let it raise;
    main() reports it and refuses to save that system.
    """
    surveyed = survey_system(system)
    old = load(system) if system.lower() in available() else None
    cloud = cloud_from(old) if old is not None else None
    fresh = layout(surveyed,
                    pins=pins_from(old) if old is not None else None,
                    star=star_from(old) if old is not None else None,
                    cloud=cloud)
    _merge_overrides(fresh, old)
    return fresh, ambiguities(surveyed, cloud=cloud)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", action="append", default=None,
                        help="system name; repeatable. Default: every system.")
    parser.add_argument("--check", action="store_true",
                        help="validate only; write nothing")
    parser.add_argument("--list-ambiguities", action="store_true",
                        help="print the guesses the layout made")
    args = parser.parse_args(argv)

    names = args.system or system_names()
    failed = 0
    for name in names:
        try:
            m, notes = generate(name)
        except Exception as exc:
            # Refuse to overwrite a map we could not read. Losing a hand-authored
            # overrides block is worse than any stale layout.
            print(f"{name}: CANNOT READ THE EXISTING MAP -- refusing to "
                  f"overwrite it ({type(exc).__name__}: {exc})")
            failed += 1
            continue
        surveyed = survey_system(name)
        # Only the places BC's own menu offers. region-coverage asks "does
        # every destination have a region", and an orphan still in the tree
        # (Vesuvi1) is not a destination -- see _ordered() in layout.
        problems = validate(m, sdk_set_names=[r.set_name for r in surveyed.regions
                                              if r.menu_listed],
                            pins=pins_from(m),
                            bc_radii=bc_radii(surveyed),
                            radius_scale=LayoutTuning().planet_radius_scale,
                            staged_points=staged_points(surveyed),
                            staged_clearance_gu=LayoutTuning().staged_clearance_gu,
                            bc_offsets=bc_offsets(surveyed))
        status = "ok" if not problems else f"{len(problems)} PROBLEM(S)"
        where = "(not written)" if args.check else save(m)
        print(f"{name}: {len(m.regions)} regions, {len(m.bodies)} bodies -- "
              f"{status} {where}")
        for p in problems:
            print(f"    {p.rule}: {p.detail}")
            failed += 1
        if args.list_ambiguities:
            for n in notes:
                print(f"    ? {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
