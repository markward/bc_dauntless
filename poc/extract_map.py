#!/usr/bin/env python3
"""
PoC: extract a first-cut 3D sector map from the BC SDK and emit poc/map.json.

This is a THROWAWAY proof-of-concept (see poc/README.md). It mines REAL signals
from sdk/Build/scripts/Systems/ and runs a crude 3D force-directed layout so the
positions reflect actual menu groupings + nebula co-visibility. It is NOT the
rigorous bearing-triangulation/bundle-adjust solve -- that's a later upgrade that
can sit behind the same map.json contract.

Signals used:
  - System -> regions     : CreateSystemMenu(...) arg list in Systems/<Sys>/<Sys>.py
  - Region nav points     : Waypoint_Create + SetTranslateXYZ, resolved against the
                            placed objects (planets/moons/stations) in <Region>_S.py
  - Nebula co-visibility  : BackdropSphere blocks (shared texture = shared landmark);
                            apparent span drives layout distance (bigger = closer)
  - Hazard nebulae        : MetaNebula_Create + SetupDamage (real colour/radius)

Run:  uv run python poc/extract_map.py
Out:  poc/map.json
"""

import json
import math
import os
import re
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SYS_DIR = os.path.join(ROOT, "sdk", "Build", "scripts", "Systems")
OUT = os.path.join(HERE, "map.json")

FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
SIMPLE_NUM = re.compile(r"^[\d\.\s/*+\-]+$")


def read(path):
    with open(path, "r", errors="replace") as f:
        return f.read()


def num(expr):
    """Evaluate a simple numeric literal like '155.0 / 255.0'. Defensive."""
    expr = expr.strip()
    if not SIMPLE_NUM.match(expr):
        return 0.0
    try:
        return float(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        return 0.0


GU_TO_KM = 0.175  # 1 game unit = 175 m (see engine/units.py)


def star_dist(pos, sun):
    """Distance of an object from its system's star (sun waypoint), GU + km.
    The BC sun is placed as a far backdrop, so this is the in-scene distance."""
    if not sun:
        return (None, None)
    d = math.sqrt(sum((pos[k] - sun[k]) ** 2 for k in range(3)))
    return (round(d, 1), round(d * GU_TO_KM, 1))


# --------------------------------------------------------------------------- #
# Texture appearance: derive a colour/density profile from the BC backdrop TGAs
# for the future procedural-starfield pass. Optional — gracefully degrades to
# None when the (gitignored) game install or Pillow is absent.
# --------------------------------------------------------------------------- #
try:
    from PIL import Image
except ImportError:
    Image = None

GAME_TEX_DIRS = [
    os.path.join(ROOT, "game", "data", "Backgrounds", "High"),
    os.path.join(ROOT, "game", "data", "Backgrounds"),
]
_tga_cache = {}


def _resolve_tex(sdk_path):
    if not sdk_path:
        return None
    base = os.path.basename(sdk_path)
    for d in GAME_TEX_DIRS:
        p = os.path.join(d, base)
        if os.path.exists(p):
            return p
    return None


def tga_appearance(sdk_path):
    """Mean colour, dominant palette, coverage and luminance for a backdrop TGA."""
    if Image is None:
        return None
    p = _resolve_tex(sdk_path)
    if not p:
        return None
    if p in _tga_cache:
        return _tga_cache[p]
    res = None
    try:
        im = Image.open(p).convert("RGBA")
        w, h = im.size
        small = im.resize((48, 48))
        raw = small.tobytes()  # RGBA bytes
        px = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
        opaque = [(r, g, b) for r, g, b, a in px if a > 16]
        lit = [c for c in opaque if max(c) > 24]
        mean = [round(sum(c[i] for c in opaque) / max(len(opaque), 1)) for i in range(3)]
        lum = round(sum(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] for c in lit) / max(len(lit), 1))
        q = small.convert("RGB").quantize(colors=5)
        pal = q.getpalette()[:15]
        doms = [[pal[i], pal[i + 1], pal[i + 2]] for i in range(0, 15, 3)]
        res = {
            "texture": os.path.basename(p),
            "meanColor": mean,
            "meanColorHex": "#%02x%02x%02x" % tuple(mean),
            "palette": doms,
            "coverage": round(len(lit) / max(len(px), 1), 3),  # density proxy
            "luminance": lum,
            "resolution": "%dx%d" % (w, h),
        }
    except Exception:
        res = None
    _tga_cache[p] = res
    return res


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def parse_menu(text):
    """Return (system_display_name, [region_module, ...]) from CreateSystemMenu."""
    m = re.search(r"CreateSystemMenu\s*\((.*?)\)", text, re.DOTALL)
    if not m:
        return None, []
    args = re.findall(r'"([^"]+)"', m.group(1))
    if not args:
        return None, []
    name = args[0]
    regions = []
    for mod in args[1:]:
        if mod not in regions:
            regions.append(mod)
    return name, regions


def parse_waypoints(text):
    """Map waypoint name -> (x, y, z) from a region loader's LoadPlacements."""
    out = {}
    # Split on Waypoint_Create so each chunk owns one waypoint's SetTranslateXYZ.
    chunks = re.split(r"Waypoint_Create\s*\(", text)
    for chunk in chunks[1:]:
        nm = re.match(r'\s*"([^"]+)"', chunk)
        if not nm:
            continue
        pos = re.search(
            r"SetTranslateXYZ\s*\((%s)\s*,\s*(%s)\s*,\s*(%s)\)" % (FLOAT, FLOAT, FLOAT),
            chunk,
        )
        if not pos:
            continue
        out[nm.group(1)] = [float(pos.group(1)), float(pos.group(2)), float(pos.group(3))]
    return out


def parse_backdrops(text):
    """Return list of {texture, forward:[x,y,z], span} for each BackdropSphere."""
    out = []
    chunks = re.split(r"BackdropSphere_Create\s*\(\s*\)", text)
    for chunk in chunks[1:]:
        tex = re.search(r'SetTextureFileName\s*\(\s*"([^"]+)"', chunk)
        if not tex:
            continue
        # First SetXYZ after create is the forward vector (kForward).
        fwd = re.search(
            r"SetXYZ\s*\((%s)\s*,\s*(%s)\s*,\s*(%s)\)" % (FLOAT, FLOAT, FLOAT), chunk
        )
        h = re.search(r"SetHorizontalSpan\s*\((%s)\)" % FLOAT, chunk)
        v = re.search(r"SetVerticalSpan\s*\((%s)\)" % FLOAT, chunk)
        if not (fwd and h and v):
            continue
        tname = os.path.basename(tex.group(1)).lower()
        if tname.startswith("stars"):
            continue
        out.append(
            {
                "texture": tname,
                "forward": [float(fwd.group(1)), float(fwd.group(2)), float(fwd.group(3))],
                "span": (float(h.group(1)) + float(v.group(1))) / 2.0,
            }
        )
    return out


def parse_placed_objects(static_text, waypoints):
    """
    From a <Region>_S.py, pair AddObjectToSet(p, "Display") with the following
    PlaceObjectByName("Waypoint") and resolve to coords via the waypoint table.
    Returns [{name, position:[x,y,z]}], filtering far-away suns.
    """
    out = []
    # Ordered scan of the two calls.
    tokens = re.finditer(
        r'AddObjectToSet\s*\(\s*\w+\s*,\s*"([^"]+)"\s*\)'
        r"|"
        r'PlaceObjectByName\s*\(\s*"([^"]+)"\s*\)',
        static_text,
    )
    pending = None
    for t in tokens:
        if t.group(1) is not None:  # AddObjectToSet display name
            pending = t.group(1)
        elif t.group(2) is not None and pending is not None:  # PlaceObjectByName
            wp = t.group(2)
            if wp in waypoints:
                pos = waypoints[wp]
                dist = math.sqrt(sum(c * c for c in pos))
                # Drop suns / far backdrop anchors (tens of thousands of GU).
                if dist <= 5000.0 and pending.lower() != "sun":
                    out.append({"name": pending, "position": pos})
            pending = None
    return out


def parse_meta_nebula(static_text):
    """Return hazard/ambient nebula volumes + full appearance spec from
    MetaNebula_Create blocks. Params: r, g, b, visibilityDist, sensorDensity,
    internalTex, externalTex; plus SetupDamage and one or more AddNebulaSphere."""
    out = []
    chunks = re.split(r"MetaNebula_Create\s*\(", static_text)
    for chunk in chunks[1:]:
        head = chunk.split(")", 1)[0]
        parts = [p.strip() for p in head.split(",")]
        if len(parts) < 5:
            continue

        def texarg(i):
            if len(parts) > i:
                m = re.search(r'"([^"]+)"', parts[i])
                return m.group(1) if m else None
            return None

        spheres = [
            [float(x) for x in m]
            for m in re.findall(
                r"AddNebulaSphere\s*\((%s)\s*,\s*(%s)\s*,\s*(%s)\s*,\s*(%s)\)"
                % (FLOAT, FLOAT, FLOAT, FLOAT),
                chunk,
            )
        ]
        if not spheres:
            continue
        dmg = re.search(r"SetupDamage\s*\(\s*(%s)(?:\s*,\s*(%s))?" % (FLOAT, FLOAT), chunk)
        out.append(
            {
                "color": [num(parts[0]), num(parts[1]), num(parts[2])],
                "hazard": "SetupDamage" in chunk,
                "local": spheres[0][:3],
                "radius_gu": spheres[0][3],
                "spheres": spheres,
                "visibility_gu": num(parts[3]),
                "sensor_density": num(parts[4]),
                "internal_tex": texarg(5),
                "external_tex": texarg(6),
                "hull_damage": float(dmg.group(1)) if dmg else 0.0,
                "shield_damage": float(dmg.group(2)) if (dmg and dmg.group(2)) else 0.0,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def region_id(module):
    return module.split(".")[-1]


def extract_missions(valid_ids):
    """Mine system co-occurrence from campaign missions.

    A mission that loads >=2 systems implies those systems are travelled
    between / near each other. Edge weight uses inverse mission-frequency
    (idf) on both endpoints so the universal Starbase 12 hub (in every
    mission) is suppressed, and is split across the mission's pairs so a
    many-system mission doesn't bind every pair at full strength.
    Returns (edges {(a,b): {w, missions:[...]}}, df {sys: count}).
    """
    base = os.path.join(ROOT, "sdk", "Build", "scripts", "Maelstrom")
    missions = []
    if os.path.isdir(base):
        for ep in sorted(os.listdir(base)):
            epdir = os.path.join(base, ep)
            if not os.path.isdir(epdir):
                continue
            for mdir in sorted(os.listdir(epdir)):
                mpath = os.path.join(epdir, mdir)
                if not os.path.isdir(mpath):
                    continue
                sys_ids = set()
                for fn in os.listdir(mpath):
                    if not fn.endswith(".py"):
                        continue
                    for nm in re.findall(r"import\s+Systems\.([A-Za-z0-9]+)", read(os.path.join(mpath, fn))):
                        sid = MEMBER_TO_PARENT.get(nm.lower(), nm.lower())
                        if sid in valid_ids:
                            sys_ids.add(sid)
                if len(sys_ids) >= 2:
                    missions.append((mdir, sys_ids))

    df = {}
    for _, s in missions:
        for sid in s:
            df[sid] = df.get(sid, 0) + 1

    def idf(s):
        return 1.0 / (1.0 + math.log(df.get(s, 1)))

    edges = {}
    for name, s in missions:
        sl = sorted(s)
        n = len(sl)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = sl[i], sl[j]
                w = idf(a) * idf(b) / (n - 1)
                e = edges.setdefault((a, b), {"w": 0.0, "missions": []})
                e["w"] += w
                e["missions"].append(name)
    return edges, df


def extract():
    systems = []
    landmark_obs = {}  # texture -> list of system_id
    landmark_spans = {}  # texture -> list of span

    for sysname in sorted(os.listdir(SYS_DIR)):
        sdir = os.path.join(SYS_DIR, sysname)
        if not os.path.isdir(sdir):
            continue
        menu_path = os.path.join(sdir, sysname + ".py")
        if not os.path.exists(menu_path):
            continue
        menu_text = read(menu_path)
        disp, region_mods = parse_menu(menu_text)
        is_base = False
        if not region_mods:
            # No Set Course menu, but a region loader (Starbase 12, DeepSpace,
            # DryDock) is still a real navigable location -> single-region system.
            if "SetClass_Create" in menu_text or "AddSet" in menu_text:
                region_mods = ["Systems.%s.%s" % (sysname, sysname)]
                is_base = True
            else:
                continue
        disp = disp or sysname
        if is_base:
            disp = re.sub(r"([A-Za-z])(\d+)$", r"\1 \2", disp)  # "Starbase12" -> "Starbase 12"

        regions = []
        sys_backdrops = []
        sys_nebulae = []
        for mod in region_mods:
            rid = region_id(mod)
            rpath = os.path.join(sdir, rid + ".py")
            if not os.path.exists(rpath):
                continue
            rtext = read(rpath)
            waypoints = parse_waypoints(rtext)
            sys_backdrops.extend(parse_backdrops(rtext))

            navpoints = []
            if "Player Start" in waypoints:
                navpoints.append({"name": "Player Start", "position": waypoints["Player Start"]})
            spath = os.path.join(sdir, rid + "_S.py")
            if os.path.exists(spath):
                stext = read(spath)
                navpoints.extend(parse_placed_objects(stext, waypoints))
                sys_nebulae.extend(parse_meta_nebula(stext))

            # Distance of each nav point (and the region itself) from the star.
            sun = waypoints.get("Sun")
            for np in navpoints:
                g, k = star_dist(np["position"], sun)
                if g is not None:
                    np["distFromStarGu"], np["distFromStarKm"] = g, k
            rg, rk = star_dist(waypoints.get("Player Start", [0.0, 0.0, 0.0]), sun)
            regions.append(
                {
                    "id": rid,
                    "name": re.sub(r"(\d+)$", r" \1", rid).strip(),
                    "navPoints": navpoints,
                    "distFromStarGu": rg,
                    "distFromStarKm": rk,
                }
            )

        if not regions:
            continue

        # Record which shared backdrops this system observes.
        seen = {}
        for bd in sys_backdrops:
            seen.setdefault(bd["texture"], []).append(bd["span"])
        observer = MEMBER_TO_PARENT.get(sysname.lower(), sysname.lower())
        for tex, spans in seen.items():
            landmark_obs.setdefault(tex, []).append(observer)
            landmark_spans.setdefault(tex, []).extend(spans)

        systems.append(
            {
                "id": sysname.lower(),
                "name": disp,
                "regions": regions,
                "_backdrops": list(seen.keys()),
                "_hazards": sys_nebulae,
                "multiplayer": sysname.lower().startswith("multi") or sysname == "QuickBattle",
                "base": is_base,
            }
        )

    # Shared landmarks = backdrops observed by >= 1 system (keep all; render later).
    landmarks = {}
    for tex, sysids in landmark_obs.items():
        landmarks[tex] = {
            "id": tex.replace(".tga", ""),
            "texture": tex,
            "systems": sysids,
            "mean_span": sum(landmark_spans[tex]) / len(landmark_spans[tex]),
            "shared": len(set(sysids)) > 1,
        }
    systems = apply_synthetic(systems)
    return systems, landmarks


# --------------------------------------------------------------------------- #
# Real-star anchors: systems named after real stars, pinned at their true 3D
# positions (equatorial cartesian, light-years). RA/dec J2000, distances ly.
# 'confident' = genuine catalogue name; speculative ones flagged.
# --------------------------------------------------------------------------- #
REAL_STARS = {
    "alioth":        {"star": "Alioth (ε UMa)",   "ra": 193.507, "dec":  55.960, "ly":  82.6, "confident": True},
    "cebalrai":      {"star": "Cebalrai (β Oph)", "ra": 265.868, "dec":   4.567, "ly":  81.9, "confident": True},
    "ascella":       {"star": "Ascella (ζ Sgr)",  "ra": 285.653, "dec": -29.880, "ly":  88.0, "confident": True},
    "omegadraconis": {"star": "Omega Draconis",        "ra": 264.237, "dec":  68.758, "ly":  76.4, "confident": True},
    "albirea":       {"star": "Albireo (β Cyg)",  "ra": 292.680, "dec":  27.960, "ly": 415.0, "confident": True},
    "artrus":        {"star": "Arcturus (α Boo)", "ra": 213.915, "dec":  19.182, "ly":  36.7, "confident": False},
    "tauceti":       {"star": "Tau Ceti (τ Cet)", "ra":  26.017, "dec": -15.937, "ly":  11.9, "confident": True},
}


# Synthetic parent systems: fold existing menu-less locations under one star.
# (DryDock's planet is "Tau Ceti Prime" and Starbase 12 shares its blue-white
# sun, so both are facilities of the Tau Ceti system.)
SYNTHETIC_SYSTEMS = {
    "tauceti": {
        "name": "Tau Ceti",
        "members": ["drydock", "starbase12"],
        "starbase": True,   # Federation starbase here -> render the Starfleet delta
    },
}
MEMBER_TO_PARENT = {m: p for p, cfg in SYNTHETIC_SYSTEMS.items() for m in cfg["members"]}


def apply_synthetic(systems):
    """Replace member systems with their synthetic parent (regions become children)."""
    by_id = {s["id"]: s for s in systems}
    out = [s for s in systems if s["id"] not in MEMBER_TO_PARENT]
    for pid, cfg in SYNTHETIC_SYSTEMS.items():
        members = [by_id[m] for m in cfg["members"] if m in by_id]
        if not members:
            continue
        regions, hazards, backdrops = [], [], []
        for m in members:
            regions.extend(m["regions"])
            hazards.extend(m.get("_hazards", []))
            backdrops.extend(m.get("_backdrops", []))
        out.append(
            {
                "id": pid,
                "name": cfg["name"],
                "regions": regions,
                "_backdrops": backdrops,
                "_hazards": hazards,
                "multiplayer": False,
                "base": True,
                "starbase": cfg.get("starbase", False),
            }
        )
    return out


def equ_to_cart(ra_deg, dec_deg, dist):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return [
        dist * math.cos(dec) * math.cos(ra),
        dist * math.cos(dec) * math.sin(ra),
        dist * math.sin(dec),
    ]


def anchor_positions(system_ids, target_sep=4.0):
    """Real-star positions scaled into the layout's working regime.

    Recenters on the bubble centroid and scales so the median *bubble* anchor
    separation maps to ~target_sep working units (Albireo, a far outlier, is
    excluded from the scale estimate so it doesn't squash the bubble).
    Returns (working_pos {sysid:[x,y,z]}, name_map {sysid: star name}).
    """
    present = {s: REAL_STARS[s] for s in system_ids if s in REAL_STARS}
    cart = {s: equ_to_cart(v["ra"], v["dec"], v["ly"]) for s, v in present.items()}
    if not cart:
        return {}, {}
    centroid = [sum(c[k] for c in cart.values()) / len(cart) for k in range(3)]
    cart = {s: [c[k] - centroid[k] for k in range(3)] for s, c in cart.items()}

    near = [s for s, v in present.items() if v["ly"] < 200.0]
    seps = []
    keys = near or list(cart)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = cart[keys[i]], cart[keys[j]]
            seps.append(math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3))))
    seps.sort()
    median = seps[len(seps) // 2] if seps else 1.0
    scale = target_sep / max(median, 1e-6)
    working = {s: [c[k] * scale for k in range(3)] for s, c in cart.items()}
    return working, {s: present[s]["star"] for s in present}


# --------------------------------------------------------------------------- #
# Crude 3D force-directed layout (with optional pinned anchors)
# --------------------------------------------------------------------------- #
def layout(systems, landmarks, anchors=None, cooc=None, iterations=700, seed=42):
    anchors = anchors or {}
    cooc = cooc or {}
    rng = random.Random(seed)
    nodes = {}  # id -> [x,y,z]
    for s in systems:
        nodes["sys:" + s["id"]] = [rng.uniform(-1, 1) for _ in range(3)]
    for tex, lm in landmarks.items():
        nodes["lm:" + tex] = [rng.uniform(-1, 1) for _ in range(3)]
    # Pin real-star anchors at their fixed positions.
    pinned = set()
    for sid, pos in anchors.items():
        key = "sys:" + sid
        if key in nodes:
            nodes[key] = list(pos)
            pinned.add(key)

    # Springs: system <-> landmark it observes. Ideal length ~ 1/span (apparent
    # size -> proximity). Plus weak system<->system pull for shared landmarks.
    springs = []
    for tex, lm in landmarks.items():
        ideal = max(0.6, min(6.0, 0.18 / max(lm["mean_span"], 0.02)))
        for sid in set(lm["systems"]):
            springs.append(("sys:" + sid, "lm:" + tex, ideal, 1.0))
    # System-system tightening for pairs that share >=2 landmarks (keystone cluster).
    share_count = {}
    for tex, lm in landmarks.items():
        uniq = sorted(set(lm["systems"]))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                key = (uniq[i], uniq[j])
                share_count[key] = share_count.get(key, 0) + 1
    for (a, b), c in share_count.items():
        if c >= 2:
            springs.append(("sys:" + a, "sys:" + b, 1.2, 0.5 * c))
    # Mission co-occurrence: systems travelled between in one mission pull together.
    IDEAL_CO, W_CO = 2.2, 2.5
    sys_ids_present = set("sys:" + s["id"] for s in systems)
    for (a, b), e in cooc.items():
        ka, kb = "sys:" + a, "sys:" + b
        if ka in sys_ids_present and kb in sys_ids_present:
            springs.append((ka, kb, IDEAL_CO, W_CO * e["w"]))

    ids = list(nodes.keys())
    k_rep = 0.9
    temp = 2.0
    for it in range(iterations):
        disp = {i: [0.0, 0.0, 0.0] for i in ids}
        # Repulsion (all pairs; ~50 nodes so trivial).
        for ai in range(len(ids)):
            for bi in range(ai + 1, len(ids)):
                a, b = ids[ai], ids[bi]
                d = [nodes[a][k] - nodes[b][k] for k in range(3)]
                dist2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2] + 1e-6
                dist = math.sqrt(dist2)
                f = (k_rep * k_rep) / dist2
                for k in range(3):
                    u = d[k] / dist
                    disp[a][k] += u * f
                    disp[b][k] -= u * f
        # Springs (attraction toward ideal length).
        for a, b, ideal, w in springs:
            d = [nodes[a][k] - nodes[b][k] for k in range(3)]
            dist = math.sqrt(sum(c * c for c in d)) + 1e-6
            f = w * (dist - ideal) / ideal
            for k in range(3):
                u = d[k] / dist
                disp[a][k] -= u * f
                disp[b][k] += u * f
        # Integrate with cooling (pinned anchors never move).
        for i in ids:
            if i in pinned:
                continue
            dl = math.sqrt(sum(c * c for c in disp[i])) + 1e-9
            step = min(dl, temp)
            for k in range(3):
                nodes[i][k] += (disp[i][k] / dl) * step
        temp = max(0.05, temp * 0.992)

    # Normalize to a tidy cube centred at origin.
    pts = list(nodes.values())
    mins = [min(p[k] for p in pts) for k in range(3)]
    maxs = [max(p[k] for p in pts) for k in range(3)]
    span = max(maxs[k] - mins[k] for k in range(3)) or 1.0
    scale = 1000.0 / span
    for i in ids:
        for k in range(3):
            nodes[i][k] = round((nodes[i][k] - (mins[k] + maxs[k]) / 2.0) * scale, 2)
    return nodes


# Systems nudged radially outward to the rim, as a fraction of Albirea's radius
# (Albireo ~430 ly is the outermost anchor). Overrides their force-directed spot.
OUTWARD_BIAS = {"vesuvi": 0.69, "deepspace": 0.82}


def apply_outward_bias(nodes):
    ref = nodes.get("sys:albirea")
    if not ref:
        return
    ref_dist = math.sqrt(sum(c * c for c in ref))
    for sid, frac in OUTWARD_BIAS.items():
        v = nodes.get("sys:" + sid)
        if not v:
            continue
        cur = math.sqrt(sum(c * c for c in v)) or 1.0
        scale = (ref_dist * frac) / cur
        nodes["sys:" + sid] = [round(c * scale, 2) for c in v]


def pretty_landmark(texid):
    m = re.match(r"([a-z]+)(\d*)", texid)
    if not m:
        return texid
    word, n = m.group(1), m.group(2)
    base = {"treknebula": "Nebula", "galaxy": "Distant Galaxy"}.get(word, word.title())
    return ("%s %s" % (base, n)).strip()


def galaxy_name(texid):
    """Galaxy backdrops = areas of denser stars -> 'Star Cloud N'."""
    m = re.match(r"galaxy(\d*)", texid)
    n = m.group(1) if m else ""
    return ("Star Cloud %s" % n).strip()


def hexcolor(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * 255))) for c in rgb)


def display_tint(rgb, target=205):
    """Brighten a (often dim) texture mean colour to a vivid display hue,
    preserving the relative channel ratios (hue)."""
    m = max(rgb) or 1
    f = target / m
    return "#%02x%02x%02x" % tuple(min(255, round(c * f)) for c in rgb)


def merge_components(items, shared_min=2):
    """Union-find over landmark textures: edge if they share >= shared_min observers."""
    parent = {t: t for t in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    keys = list(items.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if len(items[a]["observers"] & items[b]["observers"]) >= shared_min:
                union(a, b)

    comps = {}
    for t in keys:
        comps.setdefault(find(t), []).append(t)
    return list(comps.values())


# Backdrop landmark textures that are actually the SAME physical object as a
# system's local MetaNebula, seen from afar (local fog inside, backdrop outside).
# Fold them into that nebula instead of rendering a separate backdrop patch.
# (Domain knowledge / artistic call — extend as more identities are recognised.)
BACKDROP_TO_NEBULA = {
    "treknebula2": "belaruz",   # Nebula 3 Complex == the Belaruz nebula
    "treknebula3": "belaruz",
}

# Invented proper names for the shared backdrop nebulae (keyed by texture id).
LANDMARK_NEBULA_NAMES = {
    "treknebula6": "The Draconis Veil",   # purple, deep core cluster
    "treknebula7": "Auric Remnant",       # gold, late-campaign frontier
    "treknebula8": "Vermilion Shroud",    # magenta, the multiplayer arena
}


def build(systems, landmarks, nodes, cooc=None):
    cooc = cooc or {}
    out_systems = []
    out_nebulae = []
    mp = {s["id"]: s["multiplayer"] for s in systems}

    # Fold designated backdrop textures into their host system's MetaNebula.
    folded, consumed = {}, set()
    for tex, lm in landmarks.items():
        host = BACKDROP_TO_NEBULA.get(lm["id"])
        if not host:
            continue
        f = folded.setdefault(host, {"observers": set(), "textures": [], "swatches": [], "spans": []})
        f["observers"] |= set(lm["systems"])
        f["textures"].append(tex)
        sw = tga_appearance("data/Backgrounds/" + tex)
        if sw:
            f["swatches"].append(sw)
        f["spans"].append(lm["mean_span"])
        consumed.add(tex)

    for s in systems:
        pos = nodes["sys:" + s["id"]]
        out_systems.append(
            {
                "id": s["id"],
                "name": s["name"],
                "position": pos,
                "multiplayer": s["multiplayer"],
                "base": s.get("base", False),
                "starbase": s.get("starbase", False),
                "realStar": s.get("real_star"),
                "regions": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "navPoints": r["navPoints"],
                        "distFromStarGu": r.get("distFromStarGu"),
                        "distFromStarKm": r.get("distFromStarKm"),
                    }
                    for r in s["regions"]
                ],
            }
        )
        # Hazard / ambient nebulae authored inside this system's regions.
        # Dedupe by colour (one MetaNebula_Create with N spheres, or repeats,
        # collapses to a single patch — keep the largest radius).
        by_color = {}
        for neb in s["_hazards"]:
            key = hexcolor(neb["color"])
            if key not in by_color or neb["radius_gu"] > by_color[key]["radius_gu"]:
                by_color[key] = neb
        for i, (hexcol, neb) in enumerate(sorted(by_color.items())):
            # Hazard/ambient nebulae are INTRA-system features (they live inside
            # one system), so on a sector map they must stay small — smaller than
            # typical inter-system spacing — or they engulf neighbouring systems.
            # sqrt keeps the size order (Vesuvi biggest) in a tight local band.
            # (Distant BACKDROP nebulae, handled separately below, stay large.)
            r = max(16.0, min(30.0, 14.0 + 0.4 * math.sqrt(neb["radius_gu"])))
            entry = {
                "id": "%s-haz%d" % (s["id"], i),
                "name": "%s Nebula" % s["name"],
                "type": "hazard" if neb["hazard"] else "ambient",
                "position": [round(pos[k] + neb["local"][k] * 0.02, 2) for k in range(3)],
                "radius": round(r, 1),
                "color": hexcol,
                "hazard": neb["hazard"],
                "multiplayer": s["multiplayer"],
                "damage": (
                    {"hullPerSec": neb["hull_damage"], "shieldPerSec": neb["shield_damage"]}
                    if neb["hazard"] else None
                ),
                "appearance": {
                    "source": "metanebula",         # appearance comes from the SDK call
                    "tintColor": [round(c * 255) for c in neb["color"]],
                    "tintColorHex": hexcol,
                    "textures": {"internal": neb["internal_tex"], "external": neb["external_tex"]},
                    "visibilityGu": neb["visibility_gu"],   # how thick the fog reads
                    "sensorDensity": neb["sensor_density"],
                    "spheresGu": neb["spheres"],            # true shape, in game units
                    "externalSwatch": tga_appearance(neb["external_tex"]),
                },
            }
            # Fold any backdrop landmark that IS this nebula seen from afar.
            fb = folded.get(s["id"]) if i == 0 else None
            if fb:
                entry["visibleFrom"] = sorted(fb["observers"] - {s["id"]})
                entry["appearance"]["backdropTextures"] = sorted(fb["textures"])
                entry["appearance"]["backdropSwatches"] = fb["swatches"]
                entry["appearance"]["apparentSpan"] = round(sum(fb["spans"]) / len(fb["spans"]), 4)
            out_nebulae.append(entry)

    # Split backdrop landmarks: treknebula* -> nebula patches, galaxy* -> star clouds.
    neb_info, gal_info = {}, {}
    for tex, lm in landmarks.items():
        is_galaxy = tex.startswith("galaxy")
        if tex in consumed:
            continue  # folded into a system's MetaNebula above
        if not is_galaxy and not lm["shared"]:
            continue  # singleton nebulae stay unmapped (unchanged behaviour)
        rec = {
            "observers": set(lm["systems"]),
            "pos": nodes["lm:" + tex],
            "radius": max(60.0, min(220.0, 12.0 / max(lm["mean_span"], 0.02))),
            "pretty": pretty_landmark(lm["id"]),
            "obs_count": len(set(lm["systems"])),
            "id": lm["id"],
            "texfile": tex,
            "mean_span": lm["mean_span"],
        }
        (gal_info if is_galaxy else neb_info)[tex] = rec

    # Nebulae: merge co-observed (>= 2 shared observers) into one patch each.
    for comp in merge_components(neb_info, shared_min=2):
        members = [neb_info[t] for t in comp]
        observers = set().union(*[m["observers"] for m in members])
        cx = [round(sum(m["pos"][k] for m in members) / len(members), 2) for k in range(3)]
        # Same small ballpark as the hazard/ambient nebulae; mild growth by how
        # many systems observe the (merged) backdrop. (Galaxy 'size' is unaffected
        # — it still uses the per-record radius computed above.)
        radius = max(18.0, min(32.0, 16.0 + 4.0 * math.sqrt(len(observers))))
        rep = max(members, key=lambda m: (m["obs_count"], m["radius"]))
        swatches = [a for a in
                    (tga_appearance("data/Backgrounds/" + m["texfile"]) for m in members) if a]
        rep_sw = tga_appearance("data/Backgrounds/" + rep["texfile"])
        # Patch colour from the real texture mean colour (fallback to blue if no TGA).
        color = display_tint(rep_sw["meanColor"]) if rep_sw else "#5b6cff"
        name = next((LANDMARK_NEBULA_NAMES[m["id"]] for m in members if m["id"] in LANDMARK_NEBULA_NAMES),
                    rep["pretty"] + (" Complex" if len(members) > 1 else ""))
        out_nebulae.append(
            {
                "id": "+".join(sorted(comp)),
                "name": name,
                "type": "landmark",
                "position": cx,
                "radius": round(radius, 1),
                "color": color,
                "hazard": False,
                "seenBy": sorted(observers),
                "members": sorted(m["id"] for m in members),
                "multiplayer": all(mp.get(o, False) for o in observers),
                "appearance": {
                    "source": "backdrop",       # appearance derived from the TGA(s)
                    "apparentSpan": round(sum(m["mean_span"] for m in members) / len(members), 4),
                    "textures": sorted(m["texfile"] for m in members),
                    "swatches": swatches,
                },
            }
        )

    # Galaxies = areas of denser stars: own 3D position + size, icon-only on the
    # map. 'size' is a density-extent proxy for future starsphere variety.
    out_galaxies = []
    for tex, g in sorted(gal_info.items()):
        out_galaxies.append(
            {
                "id": g["id"],
                "name": galaxy_name(g["id"]),
                "position": g["pos"],
                "size": round(g["radius"], 1),
                "seenBy": sorted(g["observers"]),
                "multiplayer": all(mp.get(o, False) for o in g["observers"]),
                "appearance": {
                    "source": "backdrop",
                    "apparentSpan": round(g["mean_span"], 4),
                    "swatch": tga_appearance("data/Backgrounds/" + g["texfile"]),
                },
            }
        )

    # Render routes between systems, but NOT to/from hub bases (Starbase 12 etc.):
    # "returned to base between missions" is not spatial adjacency. Bases stay in
    # the layout springs (so they're positioned), just without 20+ visual spokes.
    base_ids = {s["id"] for s in systems if s.get("base")}
    out_links = []
    for (a, b), e in sorted(cooc.items(), key=lambda kv: -kv[1]["w"]):
        if a in base_ids or b in base_ids:
            continue
        out_links.append(
            {
                "a": a,
                "b": b,
                "weight": round(e["w"], 3),
                "missions": sorted(set(e["missions"])),
                "multiplayer": mp.get(a, False) or mp.get(b, False),
            }
        )

    return {
        "meta": {
            "source": "BC SDK Systems/ + Maelstrom missions (first-cut layout)",
            "note": "Throwaway PoC. Positions are inferred, not canonical.",
            "systemCount": len(out_systems),
            "nebulaCount": len(out_nebulae),
            "galaxyCount": len(out_galaxies),
            "linkCount": len(out_links),
        },
        "systems": out_systems,
        "nebulae": out_nebulae,
        "galaxies": out_galaxies,
        "links": out_links,
    }


def main():
    systems, landmarks = extract()
    valid_ids = set(s["id"] for s in systems)
    anchors, star_names = anchor_positions([s["id"] for s in systems])
    for s in systems:
        if s["id"] in star_names:
            s["real_star"] = star_names[s["id"]]
    cooc, df = extract_missions(valid_ids)
    nodes = layout(systems, landmarks, anchors, cooc)
    apply_outward_bias(nodes)
    data = build(systems, landmarks, nodes, cooc)
    print("  anchored: %d real-star systems pinned -> %s" % (
        len(star_names), ", ".join(sorted(star_names.values()))))
    print("  mission links: %d edges from co-occurrence" % len(cooc))
    with open(OUT, "w") as f:
        json.dump(data, f, indent=2)
    # Also emit a JS global so the renderer works from file:// (no fetch/CORS).
    with open(os.path.join(HERE, "map.js"), "w") as f:
        f.write("window.SECTOR_MAP = ")
        json.dump(data, f, indent=2)
        f.write(";\n")
    print("Wrote %s (+ map.js)" % OUT)
    print("  systems : %d" % len(data["systems"]))
    print("  nebulae : %d (%d shared landmarks, %d hazard/ambient)" % (
        len(data["nebulae"]),
        sum(1 for n in data["nebulae"] if n["type"] == "landmark"),
        sum(1 for n in data["nebulae"] if n["type"] in ("hazard", "ambient")),
    ))
    print("  galaxies: %d star clouds -> %s" % (
        len(data["galaxies"]), ", ".join(g["name"] for g in data["galaxies"])))
    total_nav = sum(len(r["navPoints"]) for s in data["systems"] for r in s["regions"])
    print("  nav pts : %d across %d regions" % (
        total_nav, sum(len(s["regions"]) for s in data["systems"])))


if __name__ == "__main__":
    main()
