"""Survey (not collected by default): Dauntless vs the original's own answers.

Run:  ORACLE_CAPTURES=<an stbc-oracle results folder> \
      .venv/bin/python -m pytest tests/oracle/survey_arcs_vs_original.py -s -q

For every capture (arcs150_*, rough_*): each weapon's CanHit / IsInArc grid
(elevation -90..90 step 5, azimuth 0..355 step 5 at the capture's arc_r, from
the ship's centre in its own frame), each subsystem's GetPosition and
GetDamagePoint, and each weapon's CalculateRoughDirection (model frame).
Prints one summary line per ship and a total; writes JSON to $SURVEY_OUT.
"""
import glob
import json
import lzma
import math
import os

import pytest



def _load(path):
    op = lzma.open if path.endswith(".xz") else open
    with op(path, "rt") as f:
        return json.load(f)


def _captures():
    root = os.environ.get("ORACLE_CAPTURES")
    if not root:
        return []          # no captures folder set: nothing to survey
    root = os.path.expanduser(root)
    out = []
    for pat in ("arcs150_*.json*", "rough_*.json*"):
        out += sorted(glob.glob(os.path.join(root, pat)))
    return out


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


def _subs_by_name(ship):
    from engine.appc.combat import _iter_subsystems
    hull = ship.GetHull()
    out = list(_iter_subsystems(ship)) + [hull]
    out += [hull.GetChildSubsystem(i) for i in range(hull.GetNumChildSubsystems())]
    return {s.GetName().replace(" ", "_"): s for s in out if s is not None}


def _parse(cap):
    names, grids, pos, dmg, rough, types = {}, {}, {}, {}, {}, {}
    for r in cap["raw_rows"]:
        p = r.split()
        k = p[0]
        if k == "cs":
            nm = [x for x in p if x.startswith("name=")][0][5:]
            names[(p[1], p[2])] = nm
            types[(p[1], p[2])] = [x for x in p if x.startswith("types=")][0][6:]
        elif k == "ca":
            side, idx, fn, el, bits = p[1], p[2], p[3], int(p[4][2:]), p[5]
            # 18 hex digits = 72 azimuths 5 deg apart, each digit low bit first.
            grids.setdefault((side, idx, fn), {})[el] = "".join(
                format(int(c, 16), "04b")[::-1] for c in bits)
        elif k == "cr":
            side, idx = p[1], p[2]
            key, _, val = p[3].partition("=")
            if key == "ShipSubsystem.GetPosition":
                pos[(side, idx)] = tuple(float(v) for v in val.split(","))
            elif key == "ShipSubsystem.GetDamagePoint":
                dmg[(side, idx)] = tuple(float(v) for v in val.split(","))
        elif k == "cd":
            rough[(p[1], p[2])] = tuple(float(v) for v in p[3][2:].split(","))
    return names, grids, pos, dmg, rough, types


def _body(ship, w):
    R = ship.GetWorldRotation()
    return [w.x * R.GetCol(i).x + w.y * R.GetCol(i).y + w.z * R.GetCol(i).z for i in range(3)]


@pytest.mark.parametrize("path", _captures(), ids=lambda p: os.path.basename(p).split(".")[0])
def test_survey(oracle, path):
    cap = _load(path)
    prm = cap["params"]
    s = oracle(attacker=prm["attacker"], target=prm["target"], range_gu=float(prm.get("range_gu", 57.0)))
    r_arc = float(prm.get("arc_r", 150.0))
    names, grids, pos, dmg, rough, types = _parse(cap)
    report = {"capture": os.path.basename(path), "ships": {}}
    for side, ship in (("A", s.atk), ("T", s.tgt)):
        subs = _subs_by_name(ship)
        row = {"grid": {}, "pos_err": {}, "dmg_err": {}, "rough_deg": {},
               "types": {names[k]: v for k, v in types.items() if k[0] == side}}
        for (sd, idx, fn), by_el in grids.items():
            if sd != side:
                continue
            nm = names.get((sd, idx))
            sub = subs.get(nm)
            if sub is None:
                continue
            meth = getattr(sub, fn.split(".")[1], None)
            agree = total = 0
            for el, bits in by_el.items():
                for i, b in enumerate(bits):
                    az = i * 360.0 / len(bits)
                    try:
                        got = int(bool(meth(_point(ship, el, az, r_arc)))) if callable(meth) else -1
                    except Exception:  # noqa: BLE001
                        got = -1
                    total += 1
                    agree += int(got == int(b))
            row["grid"]["%s %s" % (nm, fn)] = (agree, total)
        for key, want in pos.items():
            if key[0] != side or names.get(key) not in subs:
                continue
            g = subs[names[key]].GetPosition()
            row["pos_err"][names[key]] = math.dist((g.x, g.y, g.z), want)
        for key, want in dmg.items():
            if key[0] != side or names.get(key) not in subs:
                continue
            sub = subs[names[key]]
            if not hasattr(sub, "GetDamagePoint"):
                continue
            g = sub.GetDamagePoint()
            row["dmg_err"][names[key]] = math.dist((g.x, g.y, g.z), want)
        for key, want in rough.items():
            if key[0] != side or names.get(key) not in subs:
                continue
            sub = subs[names[key]]
            try:
                w = sub.CalculateRoughDirection()
                got = _body(ship, w)
            except Exception:  # noqa: BLE001
                row["rough_deg"][names[key]] = 180.0
                continue
            n1 = math.sqrt(sum(x * x for x in got)) or 1.0
            n2 = math.sqrt(sum(x * x for x in want)) or 1.0
            if n2 < 1e-6:
                continue
            c = sum(a * b for a, b in zip(got, want)) / n1 / n2
            row["rough_deg"][names[key]] = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        report["ships"][side + ":" + (prm["attacker"] if side == "A" else prm["target"])] = row
    out = os.environ.get("SURVEY_OUT")
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, os.path.basename(path).split(".")[0] + ".json"), "w") as f:
            json.dump(report, f, indent=1)
    for ship, row in report["ships"].items():
        ag = sum(a for a, _ in row["grid"].values())
        tt = sum(t for _, t in row["grid"].values())
        print("\n%s %s grid %d/%d pos>0.01:%d/%d dmg>0.01:%d/%d rough>1deg:%d/%d" % (
            report["capture"], ship, ag, tt,
            sum(e > 0.01 for e in row["pos_err"].values()), len(row["pos_err"]),
            sum(e > 0.01 for e in row["dmg_err"].values()), len(row["dmg_err"]),
            sum(e > 1.0 for e in row["rough_deg"].values()), len(row["rough_deg"])))
