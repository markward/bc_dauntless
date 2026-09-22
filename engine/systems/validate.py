"""System-map validation.

Every rule here exists because breaking it would surface as a broken MISSION
rather than as a broken map: a BC set with nowhere to live, regions nested
inside one another, a mission's staging waypoints no longer beside the body
they were authored against (see the design doc's "pins"), or a spawn point
inside a planet.

validate() returns a list of Problems -- empty means valid. It never raises:
callers are a CLI that wants to print them all and a test that wants to name
them all.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Problem:
    rule: str
    detail: str


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def validate(m, *, sdk_set_names=None, pins=None) -> list:
    problems = []
    by_name = {b.name: b for b in m.bodies}

    if sdk_set_names is not None:
        have = {r.set_name for r in m.regions}
        for name in sdk_set_names:
            if name not in have:
                problems.append(Problem(
                    "region-coverage",
                    f"BC set {name!r} has no region in system {m.system!r}"))

    for r in m.regions:
        for other in m.regions:
            if other is r:
                continue
            if _dist(r.anchor_gu, other.anchor_gu) < r.radius_gu:
                problems.append(Problem(
                    "region-overlap",
                    f"region {r.set_name!r} (radius {r.radius_gu:.0f} GU) "
                    f"contains the anchor of {other.set_name!r}"))

    for r in m.regions:
        for name in r.body_names:
            body = by_name.get(name)
            if body is None:
                problems.append(Problem(
                    "body-owner",
                    f"region {r.set_name!r} names body {name!r}, which does not exist"))
                continue
            if body.owner_region != r.set_name:
                problems.append(Problem(
                    "body-owner",
                    f"body {name!r} is listed by region {r.set_name!r} but its "
                    f"owner_region is {body.owner_region!r}"))
            # NO `continue` here. A bad back-reference is a bookkeeping
            # error; engulfing the anchor is "you would spawn inside a
            # planet". They are independent, and the geometry is measured
            # against the LISTING region's anchor either way, so a body can
            # and must report both. Only the dangling-name branch above
            # continues -- there, there is no body left to measure.
            if body.radius_gu >= _dist(body.position_gu, r.anchor_gu):
                problems.append(Problem(
                    "body-engulfs-anchor",
                    f"body {name!r} (radius {body.radius_gu:.0f} GU) reaches the "
                    f"anchor of region {r.set_name!r}"))

    if pins is not None:
        anchors = {r.set_name: r.anchor_gu for r in m.regions}
        for name, want_offset in pins.items():
            body = by_name.get(name)
            if body is None or body.owner_region not in anchors:
                problems.append(Problem(
                    "pin-respected",
                    f"pinned body {name!r} is missing or has no region"))
                continue
            anchor = anchors[body.owner_region]
            have = tuple(p - a for p, a in zip(body.position_gu, anchor))
            if _dist(have, want_offset) > 1.0:
                problems.append(Problem(
                    "pin-respected",
                    f"pinned body {name!r} sits at set-local {have} but the "
                    f"mission stages content at {tuple(want_offset)}"))

    for b in m.bodies:
        if b.orbits is not None and b.orbits not in by_name:
            problems.append(Problem(
                "orbit-target",
                f"body {b.name!r} orbits {b.orbits!r}, which is not in this map"))

    return problems
