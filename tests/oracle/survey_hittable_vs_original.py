"""Survey (not collected by default): IsHittableFromLocation vs the original.

Run:  ORACLE_CAPTURES=<an stbc-oracle results folder> \\
      .venv/bin/python -m pytest tests/oracle/survey_hittable_vs_original.py -s -q

Each hittable_* capture holds the original's own IsHittableFromLocation for
every subsystem of both ships, from shooter points 10 degrees apart on
spheres of 20, 57 and 150 GU around the ship's centre (its own frame; `cH`
rows: 36 azimuths, low bit first in each hex digit). Prints per capture and
per kind of subsystem how many answers Dauntless gives the same;
SURVEY_OUT writes them as JSON.
"""
import collections
import glob
import json
import math
import os

import pytest


def _captures():
    root = os.environ.get("ORACLE_CAPTURES")
    if not root:
        return []          # no captures folder set: nothing to survey
    root = os.path.expanduser(root)
    return sorted(glob.glob(os.path.join(root, "hittable_*.json*")))


def _load(path):
    import lzma
    op = lzma.open if path.endswith(".xz") else open
    with op(path, "rt") as f:
        return json.load(f)


def _kind(types):
    for k in ("PhaserBank", "PulseWeapon", "TractorBeamProjector", "TorpedoTube", "PowerSubsystem"):
        if k in types:
            return k
    return "other"


def _subs_by_name(ship):
    from engine.appc.combat import _iter_subsystems
    hull = ship.GetHull()
    out = list(_iter_subsystems(ship)) + [hull]
    out += [hull.GetChildSubsystem(i) for i in range(hull.GetNumChildSubsystems())]
    return {s.GetName().replace(" ", "_"): s for s in out if s is not None}


def _point(ship, elev, az, r):
    import App
    ce = math.cos(math.radians(elev))
    body = (r * ce * math.sin(math.radians(az)), r * ce * math.cos(math.radians(az)), r * math.sin(math.radians(elev)))
    w = ship.GetWorldLocation()
    R = ship.GetWorldRotation()
    c = [R.GetCol(i) for i in range(3)]
    p = App.TGPoint3()
    p.SetXYZ(w.x + c[0].x * body[0] + c[1].x * body[1] + c[2].x * body[2],
             w.y + c[0].y * body[0] + c[1].y * body[1] + c[2].y * body[2],
             w.z + c[0].z * body[0] + c[1].z * body[1] + c[2].z * body[2])
    return p


@pytest.mark.parametrize("path", _captures(), ids=lambda p: os.path.basename(p).split(".")[0])
def test_survey(oracle, path):
    cap = _load(path)
    prm = cap["params"]
    s = oracle(attacker=prm["attacker"], target=prm["target"], range_gu=float(prm.get("range_gu", 57.0)))
    names, types = {}, {}
    grids = collections.defaultdict(dict)
    for r in cap["raw_rows"]:
        p = r.split()
        if p[0] == "cs":
            names[(p[1], p[2])] = [x for x in p if x.startswith("name=")][0][5:]
            types[(p[1], p[2])] = [x for x in p if x.startswith("types=")][0][6:]
        elif p[0] == "cH":
            grids[(p[1], p[2])][(float(p[3][2:]), int(p[4][2:]))] = "".join(
                format(int(c, 16), "04b")[::-1] for c in p[5])
    report = collections.defaultdict(lambda: [0, 0])
    per = {}
    for side, ship in (("A", s.atk), ("T", s.tgt)):
        subs = _subs_by_name(ship)
        for key, g in grids.items():
            if key[0] != side or names[key] not in subs:
                continue
            sub = subs[names[key]]
            agree = total = 0
            for (rr, el), bits in g.items():
                for i, b in enumerate(bits):
                    got = sub.IsHittableFromLocation(_point(ship, el, i * 360.0 / len(bits), rr))
                    agree += int(int(got) == int(b))
                    total += 1
            k = _kind(types[key])
            report[k][0] += agree
            report[k][1] += total
            per["%s:%s" % (side, names[key])] = (agree, total, k)
    out = os.environ.get("SURVEY_OUT")
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, os.path.basename(path).split(".")[0] + ".json"), "w") as f:
            json.dump({"kinds": report, "subsystems": per}, f, indent=1)
    print("\n" + os.path.basename(path), " ".join("%s %d/%d" % (k, a, n) for k, (a, n) in sorted(report.items())))
