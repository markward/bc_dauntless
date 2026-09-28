# Radial System Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placed `Cloud`/`Volume` model with a per-system table of five intensities (nebula, dust, sensors, radiation, asteroids) keyed by distance from the star, and drive dust density, target concealment, radiation harm and (behind a spike) the visible nebula from it.

**Architecture:** A pure data module (`engine/systems/profile.py`) holds the table and its evaluation; a generator-side builder (`tools/systems/profile_builder.py`) derives each system's table from the committed map and composes a star-radiation term onto it; the runtime samples the table at an object's system-space distance from its star (`frames.system_position`) and feeds four consumers: a new `RadiationDriver` on the fixed sim tick, `concealment_at`, the C++ dust pass, and a dev-gated synthetic volume for the existing volumetric nebula pass.

**Tech Stack:** Python 3.11 (engine, tools, pytest), C++17 + pybind11 (renderer, gtest/ctest), JSON map files.

**Spec:** `docs/superpowers/specs/2026-09-23-radial-system-profile-design.md` — read it before any task.

## Global Constraints

- All work on branch `feat/radial-system-profile` in worktree `.claude/worktrees/radial-profile`. **Never commit to `main`. Never push.**
- ⛔ Shared checkout: never run `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths only. To mutate a file temporarily: `cp file /tmp/bak` → edit → test → `cp /tmp/bak file` → `diff file /tmp/bak`.
- Never launch the game (`./build/dauntless`). Live checks are Mark's; stop and ask.
- Spatial values are GU; never name a variable `*_m` / `*_mps`.
- Never spell `game` or `sdk` as a path segment; never capture a path at import (`engine/paths.py`).
- Rotation convention is irrelevant here (all distances are scalar), but positions are **system coordinates**: the star is the map body with `orbits is None`, at the origin in every committed map.
- Difficulty multiplier `m`: easy **0**, medium **0.5**, hard **1.0** (`engine.core.game.Game_GetDifficulty()` returns 0/1/2).
- Radiation scale: `1.0` = **150 hull/s**, **20 shield/s per face**. Environment event rate **16 Hz**. Outage rate `r·m / 30 s`; outage duration uniform **5–20 s**; never the hull or the power plant.
- Star radiation: `1.0` from centre to the star's surface, linear to `0` at **3 star radii**, `max`-composed onto every system's profile.
- Generator shape constants: rise start `0.5·R`, floor `0.05` reached at `2·R`, narrow band `± 2 × region radius`, visibility fit `a = 55.625`, `b = 89.375`.
- Multi systems (`multi1`–`multi7`) never contribute cloud rows; they get the star term only.
- The existing oracle tests (`tests/oracle/test_nebula.py`) and nebula tests (`tests/unit/test_nebula.py`) must pass **unchanged** except where a task says otherwise.
- Gate before declaring the branch done: `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`).

## Review Focus

1. **A ship that leaves the set, dies, or the mission swaps while a subsystem is in an outage** — the subsystem must come back online, never stay dark forever. Test: Task 8 `test_outage_clears_when_ship_leaves_the_ship_list` and `test_reset_clears_all_outages`.
2. **A handler that swallows `ET_ENVIRONMENT_DAMAGE`** (E3M2's `CoreDamage` during the stellar-core cutscene, `MissionLib.IgnoreEvent` on asteroids/probes) — no radiation damage and no outage roll for that event. Test: Task 7 `test_swallowed_event_applies_no_damage`.
3. **Inside Vesuvi 4's local cloud *and* the profile's radiation** — one event stream per ship, not two (E3M2's `CoreDamage` would double-prod). Test: Task 9 `test_ship_inside_armed_local_nebula_gets_no_profile_events`.
4. **A weapon *bank* whose parent weapon *system* is in an outage** — the bank must also read offline, or the outage is invisible. Test: Task 8 `test_child_of_an_out_subsystem_is_offline`.
5. **An override whose radii no longer match the map** after a future layout change — generation must fail, not silently misplace harm. Test: Task 3 `test_override_far_from_clump_is_a_problem`.

---

### Task 0: Worktree build setup (no commit)

The worktree has no venv or build tree yet (`memory: feedback_worktrees_runtime_deps`).

- [ ] **Step 1:** From the worktree root:

```bash
cp /Users/mward/Documents/Projects/bc_dauntless/settings.json . 2>/dev/null
mkdir -p mods && cp -Rc /Users/mward/Documents/Projects/bc_dauntless/mods/. mods/
uv sync --extra dev
cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3
cmake --build build -j
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_system_map.py tests/unit/test_nebula.py -q` → all pass. If not, STOP (BLOCKED: environment).

---

### Task 1: Profile data model and evaluation

**Files:**
- Create: `engine/systems/profile.py`
- Modify: `engine/systems/map.py` (add `SystemMap.profile`, JSON I/O)
- Test: `tests/unit/test_system_profile.py`

**Interfaces:**
- Produces: `COLUMNS`, `ProfileRow`, `Profile`, `Sample`, `CLEAR`, `evaluate(profile, r) -> Sample`, `clump_radius(region, star_position) -> float`, `locate(obj) -> tuple[Profile | None, float] | None`, `sample_for_object(obj) -> Sample`; `SystemMap.profile: Profile | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_system_profile.py
import math
import pytest

from engine.systems import profile as P
from engine.systems.map import Region, SystemMap, from_json, to_json


def _p(*rows):
    return P.Profile(rows=[P.ProfileRow(*r) for r in rows])


def test_none_and_empty_are_clear():
    assert P.evaluate(None, 5000.0) == P.CLEAR
    assert P.evaluate(P.Profile(rows=[]), 5000.0) == P.CLEAR


def test_each_column_interpolates_independently():
    prof = _p((0.0, 0.0, 1.0, 0.0, 0.2, 0.0), (100.0, 1.0, 0.0, 0.5, 0.2, 1.0))
    s = P.evaluate(prof, 25.0)
    assert s.nebula == pytest.approx(0.25)
    assert s.dust == pytest.approx(0.75)
    assert s.sensors == pytest.approx(0.125)
    assert s.radiation == pytest.approx(0.2)
    assert s.asteroids == pytest.approx(0.25)


def test_exact_row_hit_returns_that_row():
    prof = _p((0.0, 0.0), (50.0, 0.4), (100.0, 1.0))
    assert P.evaluate(prof, 50.0).nebula == pytest.approx(0.4)


def test_last_row_persists_outward_forever():
    prof = _p((0.0, 0.0), (100.0, 0.05, 0.2))
    s = P.evaluate(prof, 1.0e9)
    assert (s.nebula, s.dust) == (pytest.approx(0.05), pytest.approx(0.2))


def test_clump_radius_is_anchor_plus_first_sphere_from_the_star():
    r = Region(set_name="V4", anchor_gu=(0.0, 122000.0, 0.0), radius_gu=3566.8,
               nebula={"spheres": [(0.0, 1500.0, 0.0, 1500.0)]})
    assert P.clump_radius(r, (0.0, 0.0, 0.0)) == pytest.approx(123500.0)


def test_profile_round_trips_through_map_json():
    m = SystemMap(system="X", profile=P.Profile(
        rows=[P.ProfileRow(0.0, radiation=1.0), P.ProfileRow(300.0)],
        color=(0.5, 0.25, 0.75), full_concealment=0.4))
    back = from_json(to_json(m))
    assert back.profile == m.profile


def test_map_without_profile_key_loads_as_none():
    assert from_json('{"system": "X"}').profile is None


def test_sample_for_object_uses_system_position_and_star(monkeypatch):
    from engine.systems import frames, resolve
    from engine.systems.map import Body
    prof = _p((0.0, 0.0), (1000.0, 1.0))
    m = SystemMap(system="S", bodies=[Body("Sun", "Sun", 10.0, (0.0, 0.0, 0.0))],
                  profile=prof)
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("system", "S"), 300.0, 400.0, 0.0))
    monkeypatch.setattr(resolve, "map_of", lambda name: m if name == "S" else None)
    assert P.sample_for_object(object()).nebula == pytest.approx(0.5)
    assert P.locate(object()) == (prof, pytest.approx(500.0))


def test_sample_for_object_outside_a_mapped_system_is_clear(monkeypatch):
    from engine.systems import frames
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("set", object()), 1.0, 2.0, 3.0))
    assert P.sample_for_object(object()) == P.CLEAR
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    assert P.sample_for_object(object()) == P.CLEAR
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_system_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.systems.profile`.

- [ ] **Step 3: Implement `engine/systems/profile.py`**

```python
"""The radial system profile: space as a function of distance from the star.

Design: docs/superpowers/specs/2026-09-23-radial-system-profile-design.md.
Pure data + evaluation. Must not import engine.systems.map (map imports this).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

COLUMNS = ("nebula", "dust", "sensors", "radiation", "asteroids")


@dataclass
class ProfileRow:
    distance_gu: float
    nebula: float = 0.0
    dust: float = 0.0
    sensors: float = 0.0
    radiation: float = 0.0
    asteroids: float = 0.0


@dataclass
class Profile:
    rows: list = field(default_factory=list)   # sorted by distance_gu, first at 0.0
    color: tuple | None = None                 # the clump's RGB (0-1); None = no cloud
    full_concealment: float = 0.0              # C_V, generator-measured


@dataclass(frozen=True)
class Sample:
    nebula: float = 0.0
    dust: float = 0.0
    sensors: float = 0.0
    radiation: float = 0.0
    asteroids: float = 0.0


CLEAR = Sample()


def _sample(row) -> Sample:
    return Sample(**{c: getattr(row, c) for c in COLUMNS})


def evaluate(profile, r: float) -> Sample:
    """Every column at radius `r`: linear between rows, each column on its
    own; the last row persists outward forever; None/empty is clear space."""
    if profile is None or not profile.rows:
        return CLEAR
    rows = profile.rows
    if r <= rows[0].distance_gu:
        return _sample(rows[0])
    for a, b in zip(rows, rows[1:]):
        if r <= b.distance_gu:
            span = b.distance_gu - a.distance_gu
            t = 0.0 if span <= 0.0 else (r - a.distance_gu) / span
            return Sample(**{c: getattr(a, c) + (getattr(b, c) - getattr(a, c)) * t
                             for c in COLUMNS})
    return _sample(rows[-1])


def clump_radius(region, star_position) -> float:
    """Distance from the star to a region's authored nebula clump: the
    region anchor plus the FIRST sphere's set-local centre."""
    x, y, z, _r = region.nebula["spheres"][0]
    ax, ay, az = region.anchor_gu
    return math.dist((ax + x, ay + y, az + z), tuple(star_position))


def locate(obj):
    """(profile, distance from the star) for an object in a mapped region,
    else None. Resolved at use; never cached."""
    from engine.systems import frames, resolve
    pos = frames.system_position(obj)
    if pos is None or pos[0][0] != "system":
        return None
    m = resolve.map_of(pos[0][1])
    if m is None:
        return None
    star = next((b for b in m.bodies if b.orbits is None), None)
    if star is None:
        return None
    return m.profile, math.dist(pos[1:], tuple(star.position_gu))


def sample_for_object(obj) -> Sample:
    found = locate(obj)
    if found is None:
        return CLEAR
    return evaluate(found[0], found[1])
```

- [ ] **Step 4: Add the field and JSON I/O to `engine/systems/map.py`**

Add `from engine.systems.profile import Profile, ProfileRow` to the imports. Add to `SystemMap` (after `generated`, keep `clouds` for now — Task 4 removes it):

```python
    profile: Profile | None = None
```

Add beside `_nebula_from_json`:

```python
def _profile_from_json(raw: dict | None) -> Profile | None:
    if raw is None:
        return None
    color = raw.get("color")
    return Profile(
        rows=[ProfileRow(**row) for row in raw.get("rows", [])],
        color=None if color is None else tuple(color),
        full_concealment=float(raw.get("full_concealment", 0.0)),
    )
```

In `from_json`, pass `profile=_profile_from_json(raw.get("profile"))` to the `SystemMap(...)` constructor. `to_json` needs no change (`asdict` recurses; `color` becomes a list and `_profile_from_json` turns it back into a tuple).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_system_profile.py tests/unit/test_system_map.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/systems/profile.py engine/systems/map.py tests/unit/test_system_profile.py
git commit -m "feat(systems): radial profile data model and evaluation"
```

---

### Task 2: Profile builder (derivation, star term, composition)

**Files:**
- Create: `tools/systems/profile_builder.py`
- Test: `tests/tools/test_profile_builder.py`

**Interfaces:**
- Consumes: Task 1's `Profile`, `ProfileRow`, `COLUMNS`, `evaluate`, `clump_radius`.
- Produces: `nebula_intensity(visibility_gu) -> float`, `core_concealment(spheres) -> float`, `FULL_CONCEALMENT: float` (C_V), `VESUVI_4_SPHERES`, `star_rows(star_radius_gu) -> list[ProfileRow]`, `cloud_rows(region, star_position, full_concealment) -> list[ProfileRow]`, `compose_max(a_rows, b_rows) -> list[ProfileRow]`, `override_rows(raw) -> list[ProfileRow]`, `build_profile(m, override, *, campaign: bool) -> Profile`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tools/test_profile_builder.py
import pytest

from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap
from tools.systems import profile_builder as B

V4 = {"color": (0.6, 0.35, 0.72), "spheres": [(0.0, 1500.0, 0.0, 1500.0)],
      "visibility_gu": 145.0, "sensor_density": 10.5,
      "damage_hull_per_s": 150.0, "damage_shield_per_s": 20.0}
B1 = {"color": (0.39, 0.39, 0.57), "spheres": [(-17.1, 844.7, -30.3, 900.0)],
      "visibility_gu": 200.0, "sensor_density": 6.5,
      "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0}


def _vesuvi_like():
    return SystemMap(
        system="Vesuvi",
        bodies=[Body("Vesuvi", "Vesuvi", 2000.0, (0.0, 0.0, 0.0))],
        regions=[Region("Vesuvi4", (0.0, 122000.0, 0.0), 3566.8, nebula=V4),
                 Region("Vesuvi5", (229468.0, 0.0, 0.0), 13301.0)])


def test_visibility_fit_hits_both_campaign_samples():
    assert B.nebula_intensity(145.0) == pytest.approx(1.0)
    assert B.nebula_intensity(200.0) == pytest.approx(6.5 / 10.5, abs=1e-3)


def test_full_concealment_is_vesuvi_4s_measured_core():
    assert B.FULL_CONCEALMENT == pytest.approx(B.core_concealment(B.VESUVI_4_SPHERES))
    assert 0.0 < B.FULL_CONCEALMENT <= 1.0


def test_star_rows_are_one_at_the_surface_and_zero_at_three_radii():
    prof = P.Profile(rows=B.star_rows(2000.0))
    assert P.evaluate(prof, 0.0).radiation == 1.0
    assert P.evaluate(prof, 2000.0).radiation == 1.0
    assert P.evaluate(prof, 4000.0).radiation == pytest.approx(0.5)
    assert P.evaluate(prof, 6000.0).radiation == 0.0
    assert P.evaluate(prof, 1.0e6).radiation == 0.0


def test_cloud_rows_peak_at_the_clump_radius():
    rows = B.cloud_rows(_vesuvi_like().regions[0], (0.0, 0.0, 0.0), B.FULL_CONCEALMENT)
    prof = P.Profile(rows=rows)
    peak = P.evaluate(prof, 123500.0)
    assert (peak.nebula, peak.dust, peak.radiation) == (
        pytest.approx(1.0), pytest.approx(1.0), pytest.approx(1.0))
    assert peak.sensors == pytest.approx(1.0)
    assert P.evaluate(prof, 61750.0).nebula == 0.0            # rise starts at 0.5 R
    assert P.evaluate(prof, 247000.0).nebula == pytest.approx(0.05)  # floor at 2 R
    assert P.evaluate(prof, 1.0e7).nebula == pytest.approx(0.05)     # persists
    band = 2 * 3566.8
    assert P.evaluate(prof, 123500.0 + band).radiation == 0.0
    assert P.evaluate(prof, 123500.0 - band).sensors == 0.0
    assert P.evaluate(prof, 1.0e7).radiation == 0.0


def test_belaruz_cloud_has_an_authored_zero_radiation():
    region = Region("Belaruz1", (128000.0, 0.0, 0.0), 2229.6, nebula=B1)
    prof = P.Profile(rows=B.cloud_rows(region, (0.0, 0.0, 0.0), B.FULL_CONCEALMENT))
    r = P.clump_radius(region, (0.0, 0.0, 0.0))
    assert P.evaluate(prof, r).radiation == 0.0
    assert P.evaluate(prof, r).nebula == pytest.approx(6.5 / 10.5, abs=1e-3)


def test_compose_max_is_exact_across_crossings():
    a = [P.ProfileRow(0.0, radiation=1.0), P.ProfileRow(100.0, radiation=0.0)]
    b = [P.ProfileRow(0.0, radiation=0.0), P.ProfileRow(100.0, radiation=1.0)]
    prof = P.Profile(rows=B.compose_max(a, b))
    for r in (0.0, 25.0, 50.0, 75.0, 100.0):
        assert P.evaluate(prof, r).radiation == pytest.approx(max(1 - r / 100, r / 100))


def test_campaign_system_gets_cloud_plus_star():
    prof = B.build_profile(_vesuvi_like(), None, campaign=True)
    assert P.evaluate(prof, 0.0).radiation == 1.0
    assert P.evaluate(prof, 123500.0).nebula == pytest.approx(1.0)
    assert prof.color == V4["color"]
    assert prof.full_concealment == pytest.approx(B.FULL_CONCEALMENT)


def test_multi_system_gets_only_the_star_term():
    prof = B.build_profile(_vesuvi_like(), None, campaign=False)
    assert P.evaluate(prof, 123500.0) == P.CLEAR
    assert P.evaluate(prof, 0.0).radiation == 1.0
    assert prof.color is None


def test_override_replaces_derived_rows_and_keeps_the_star_term():
    override = {"rows": [{"distance_gu": 0.0, "dust": 0.1, "radiation": 0.4},
                         {"distance_gu": 500000.0, "dust": 0.1}]}
    prof = B.build_profile(_vesuvi_like(), override, campaign=True)
    assert P.evaluate(prof, 123500.0).nebula == 0.0          # derived rows gone
    assert P.evaluate(prof, 1000.0).radiation == 1.0         # star term on top
    assert P.evaluate(prof, 10000.0).radiation == pytest.approx(0.4 - 0.4 * 10000 / 500000)
    assert prof.color == V4["color"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_profile_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: tools.systems.profile_builder`.

- [ ] **Step 3: Implement `tools/systems/profile_builder.py`**

```python
"""Derive a system's radial profile from its committed map.

Design: docs/superpowers/specs/2026-09-23-radial-system-profile-design.md
("How the profiles get authored"). Every number is derived from the map at
generation time -- never hard-code a clump radius (two layout doublings made
the first draft's literals wrong within two days).
"""
from __future__ import annotations

from engine.appc.nebula import MetaNebula
from engine.appc.nebula_density import density, seed_for
from engine.systems.profile import COLUMNS, Profile, ProfileRow, clump_radius, evaluate

RISE_START = 0.5          # nebula/dust start rising at 0.5 R
FLOOR_AT = 2.0            # ... fall to FLOOR at 2 R, which persists outward
FLOOR = 0.05
BAND_REGION_RADII = 2.0   # sensors/radiation: 0 at R +- 2 x region radius
STAR_REACH_RADII = 3.0    # star radiation reaches 0 at 3 star radii
VIS_A, VIS_B = 55.625, 89.375   # visibility = a + b / i, exact through BC's two samples

# BC's authored Vesuvi 4 sphere (Systems/Vesuvi/Vesuvi4_S.py AddNebulaSphere).
# Pinned against the surveyed map by tests/unit/test_system_maps_valid.py.
VESUVI_4_SPHERES = [(0.0, 1500.0, 0.0, 1500.0)]


def nebula_intensity(visibility_gu: float) -> float:
    if visibility_gu <= VIS_A:
        return 1.0
    return min(1.0, VIS_B / (visibility_gu - VIS_A))


def core_concealment(spheres) -> float:
    """Mean fbm concealment over a 5x5x5 grid within half the first sphere's
    radius, with the runtime's own default dials and seed, drift_t = 0.
    Measured, not guessed -- this is what concealment_at would read there."""
    cx, cy, cz, radius = spheres[0]
    freq, gain, floor = MetaNebula().GetFbmDials()
    seed = seed_for(cx, cy, cz)
    steps = [(-0.5 + i / 4.0) * radius for i in range(5)]
    total = 0.0
    for dx in steps:
        for dy in steps:
            for dz in steps:
                total += density(cx + dx, cy + dy, cz + dz, spheres, seed,
                                 freq, gain, floor, drift_t=0.0)
    return total / 125.0


FULL_CONCEALMENT = core_concealment(VESUVI_4_SPHERES)


def star_rows(star_radius_gu: float) -> list:
    return [ProfileRow(0.0, radiation=1.0),
            ProfileRow(star_radius_gu, radiation=1.0),
            ProfileRow(STAR_REACH_RADII * star_radius_gu, radiation=0.0)]


def cloud_rows(region, star_position, full_concealment: float) -> list:
    neb = region.nebula
    R = clump_radius(region, star_position)
    band = BAND_REGION_RADII * region.radius_gu
    peak_neb = nebula_intensity(neb["visibility_gu"])
    peak_sens = (core_concealment(neb["spheres"]) / full_concealment
                 if full_concealment > 0.0 else 0.0)
    peak_rad = 1.0 if (neb["damage_hull_per_s"] > 0.0
                       or neb["damage_shield_per_s"] > 0.0) else 0.0

    def wide(r):
        if r <= RISE_START * R:
            return 0.0
        if r <= R:
            return peak_neb * (r - RISE_START * R) / ((1.0 - RISE_START) * R)
        if r <= FLOOR_AT * R:
            return peak_neb + (FLOOR - peak_neb) * (r - R) / ((FLOOR_AT - 1.0) * R)
        return FLOOR

    def narrow(r, peak):
        d = abs(r - R)
        return 0.0 if d >= band else peak * (1.0 - d / band)

    points = sorted({0.0, RISE_START * R, max(0.0, R - band), R, R + band, FLOOR_AT * R})
    return [ProfileRow(d, nebula=min(1.0, wide(d)), dust=min(1.0, wide(d)),
                       sensors=min(1.0, narrow(d, peak_sens)),
                       radiation=narrow(d, peak_rad))
            for d in points]


def compose_max(a_rows: list, b_rows: list) -> list:
    """Per-column max of two piecewise-linear profiles, exact: breakpoints of
    both plus every point where a column's leader changes."""
    pa, pb = Profile(rows=list(a_rows)), Profile(rows=list(b_rows))
    pts = sorted({0.0} | {r.distance_gu for r in a_rows} | {r.distance_gu for r in b_rows})
    extra = set()
    for lo, hi in zip(pts, pts[1:]):
        a0, a1, b0, b1 = evaluate(pa, lo), evaluate(pa, hi), evaluate(pb, lo), evaluate(pb, hi)
        for c in COLUMNS:
            d0 = getattr(a0, c) - getattr(b0, c)
            d1 = getattr(a1, c) - getattr(b1, c)
            if d0 * d1 < 0.0:
                extra.add(lo + (hi - lo) * d0 / (d0 - d1))
    out = []
    for d in sorted(set(pts) | extra):
        sa, sb = evaluate(pa, d), evaluate(pb, d)
        out.append(ProfileRow(d, **{c: max(getattr(sa, c), getattr(sb, c)) for c in COLUMNS}))
    return out


def override_rows(raw: dict) -> list:
    return [ProfileRow(**row) for row in raw["rows"]]


def build_profile(m, override, *, campaign: bool) -> Profile:
    star = next(b for b in m.bodies if b.orbits is None)
    clouds = [r for r in m.regions if r.nebula is not None and r.nebula.get("spheres")] \
        if campaign else []
    if override is not None:
        base = override_rows(override)
    else:
        base = []
        for region in clouds:
            base = compose_max(base, cloud_rows(region, star.position_gu, FULL_CONCEALMENT))
    rows = compose_max(base, star_rows(star.radius_gu))
    color = tuple(clouds[0].nebula["color"]) if clouds else None
    return Profile(rows=rows, color=color, full_concealment=FULL_CONCEALMENT)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tools/test_profile_builder.py -v`
Expected: PASS. If `test_cloud_rows_peak_at_the_clump_radius`'s `peak.sensors` is not 1.0, check `cloud_rows` computes `core_concealment` on the region's own set-local spheres (Vesuvi 4's are identical to `VESUVI_4_SPHERES`, so the ratio is exactly 1).

- [ ] **Step 5: Commit**

```bash
git add tools/systems/profile_builder.py tests/tools/test_profile_builder.py
git commit -m "feat(tools): derive radial profiles from the map, compose star radiation"
```

---

### Task 3: Validator rules for profiles

**Files:**
- Modify: `engine/systems/validate.py` (add `_profile_problems`, call it at the end of `validate()` before `return problems`)
- Test: `tests/unit/test_system_map_validate.py` (append)

**Interfaces:**
- Consumes: `Profile`, `ProfileRow`, `COLUMNS`, `clump_radius` (Task 1).
- Produces: rules `profile-rows-ordered`, `profile-radiation-clears`, `profile-override-tracks-clump`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_system_map_validate.py`)

```python
from engine.systems.profile import Profile, ProfileRow
from engine.systems.validate import _profile_problems
from engine.systems.map import Body, Region, SystemMap as _SM


def _pm(rows, overrides=None, regions=None):
    return _SM(system="T", bodies=[Body("Sun", "Sun", 100.0, (0.0, 0.0, 0.0))],
               regions=regions or [], overrides=overrides or {},
               profile=Profile(rows=rows))


def _rules(m):
    return sorted({p.rule for p in _profile_problems(m)})


def test_ordered_profile_is_clean():
    assert _rules(_pm([ProfileRow(0.0, radiation=1.0), ProfileRow(300.0)])) == []


def test_none_profile_is_clean():
    m = _pm([])
    m.profile = None
    assert _rules(m) == []


def test_unsorted_first_nonzero_or_out_of_range_rows_are_problems():
    assert _rules(_pm([ProfileRow(10.0)])) == ["profile-rows-ordered"]
    assert _rules(_pm([ProfileRow(0.0), ProfileRow(50.0), ProfileRow(20.0)])) == ["profile-rows-ordered"]
    assert _rules(_pm([ProfileRow(0.0, dust=1.5)])) == ["profile-rows-ordered"]
    assert _rules(_pm([ProfileRow(0.0, nebula=float("nan"))])) == ["profile-rows-ordered"]


def test_radiation_in_the_last_row_is_a_problem():
    assert _rules(_pm([ProfileRow(0.0), ProfileRow(10.0, radiation=0.1)])) == [
        "profile-radiation-clears"]


def test_radiation_near_the_star_is_fine():
    assert _rules(_pm([ProfileRow(0.0, radiation=1.0), ProfileRow(300.0)])) == []


def _cloud_region(anchor_y):
    return Region("C1", (0.0, anchor_y, 0.0), 2000.0,
                  nebula={"spheres": [(0.0, 0.0, 0.0, 500.0)]})


def test_override_near_clump_is_clean():
    rows = [ProfileRow(0.0), ProfileRow(100000.0, nebula=1.0), ProfileRow(200000.0)]
    m = _pm(rows, overrides={"profile": {"rows": []}}, regions=[_cloud_region(101000.0)])
    assert _rules(m) == []


def test_override_far_from_clump_is_a_problem():
    rows = [ProfileRow(0.0), ProfileRow(100000.0, nebula=1.0), ProfileRow(200000.0)]
    m = _pm(rows, overrides={"profile": {"rows": []}}, regions=[_cloud_region(150000.0)])
    assert _rules(m) == ["profile-override-tracks-clump"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_system_map_validate.py -k profile -v`
Expected: FAIL — `ImportError: cannot import name '_profile_problems'`.

- [ ] **Step 3: Implement** in `engine/systems/validate.py` (add the import `from engine.systems.profile import COLUMNS, clump_radius` at the top; add the helper beside the other `_*_problems` helpers; add `problems.extend(_profile_problems(m))` immediately before the final `return problems` of `validate()`):

```python
def _profile_problems(m) -> list:
    """Radial profile rules (spec: 'Validator rules'). Never raises."""
    prof = getattr(m, "profile", None)
    if prof is None or not getattr(prof, "rows", None):
        return []
    rows = prof.rows
    out = []
    ordered = rows[0].distance_gu == 0.0 and all(
        a.distance_gu <= b.distance_gu for a, b in zip(rows, rows[1:]))
    in_range = all(
        math.isfinite(getattr(r, c)) and 0.0 <= getattr(r, c) <= 1.0
        for r in rows for c in COLUMNS) and all(math.isfinite(r.distance_gu) for r in rows)
    if not (ordered and in_range):
        out.append(Problem("profile-rows-ordered",
                           f"{m.system}: rows must be sorted, start at 0 and hold "
                           f"finite values in 0-1"))
    if rows[-1].radiation != 0.0:
        out.append(Problem("profile-radiation-clears",
                           f"{m.system}: last row radiation {rows[-1].radiation} persists "
                           f"outward forever; it must be 0"))
    if (getattr(m, "overrides", None) or {}).get("profile") is not None:
        star = next((b for b in m.bodies if b.orbits is None), None)
        peak = max(rows, key=lambda r: r.nebula)
        for region in m.regions:
            neb = region.nebula
            if star is None or not neb or not neb.get("spheres"):
                continue
            R = clump_radius(region, star.position_gu)
            if peak.nebula > 0.0 and abs(peak.distance_gu - R) > region.radius_gu:
                out.append(Problem("profile-override-tracks-clump",
                                   f"{m.system}: override nebula peak at {peak.distance_gu:.0f} GU "
                                   f"but {region.set_name}'s clump is at {R:.0f} GU "
                                   f"(tolerance {region.radius_gu:.0f})"))
    return out
```

(`math` and `Problem` already exist in `validate.py`; if `math` is not imported, add it.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_system_map_validate.py tests/unit/test_system_maps_valid.py -v`
Expected: PASS (committed maps have `profile=None` until Task 5, so no new problems).

- [ ] **Step 5: Commit**

```bash
git add engine/systems/validate.py tests/unit/test_system_map_validate.py
git commit -m "feat(systems): validate radial profiles"
```

---

### Task 4: Remove the placed cloud model

The spec's "What comes out of the tree" is the checklist. Nothing at runtime reads `SystemMap.clouds` (audited 2026-09-28).

**Files:**
- Delete: `engine/systems/clouds.py`, `tests/unit/test_cloud_profiles.py`
- Modify: `engine/systems/map.py`, `engine/systems/validate.py`, `tools/systems/layout.py`, `tools/gen_system_maps.py`, `engine/systems/maps/belaruz.json`, `engine/systems/maps/vesuvi.json`, all 32 `engine/systems/maps/*.json` (regenerated), `engine/systems/resolve.py:26` docstring, `tests/unit/test_system_map.py`, `tests/unit/test_system_map_validate.py`, `tests/unit/test_system_maps_valid.py`, `tests/tools/test_system_layout.py`, `tests/tools/test_system_survey.py`, `docs/superpowers/specs/2026-09-23-celestial-layer-design.md` (≈358), `docs/superpowers/plans/2026-09-24-celestial-layer.md` (≈623), `docs/superpowers/specs/2026-09-24-system-frames-design.md` (≈551).

**Interfaces:**
- Consumes: nothing new.
- Produces: `SystemMap` with no `clouds` field; `layout(...)`, `_place(...)`, `_first_orbit_push(...)`, `ambiguities(...)` with no `cloud` parameter; `generate()` with no `cloud_from`.

- [ ] **Step 1: Rewrite the survey pin first (the one test whose intent survives).** In `tests/tools/test_system_survey.py`, drop the `clouds` import (line ≈10) and replace `test_the_bc_profiles_match_what_the_sdk_actually_says` (≈275) with a test that pins the surveyed SDK numbers directly — the calibration now depends on them:

```python
def test_the_campaign_nebulae_match_what_the_sdk_actually_says():
    """The radial profile is calibrated on these four numbers per cloud
    (spec: 'The columns'). If the survey drifts, the calibration drifts."""
    v4 = next(r for r in survey_system("Vesuvi").regions if r.set_name == "Vesuvi4").nebula
    b1 = next(r for r in survey_system("Belaruz").regions if r.set_name == "Belaruz1").nebula
    assert (v4["visibility_gu"], v4["sensor_density"]) == (145.0, 10.5)
    assert (v4["damage_hull_per_s"], v4["damage_shield_per_s"]) == (150.0, 20.0)
    assert (b1["visibility_gu"], b1["sensor_density"]) == (200.0, 6.5)
    assert (b1["damage_hull_per_s"], b1["damage_shield_per_s"]) == (0.0, 0.0)
```

(Use whatever `survey_system` import the file already has.) Run it: `uv run pytest tests/tools/test_system_survey.py -v` → PASS.

- [ ] **Step 2: Delete the cloud tests** (each is named in the audit; delete only these):
  - `tests/unit/test_cloud_profiles.py` — whole file (`git rm`).
  - `tests/unit/test_system_map.py`: `test_a_map_with_no_clouds_key_still_loads`, `test_clouds_round_trip_through_json`, `test_cloud_lookup_by_name`.
  - `tests/unit/test_system_maps_valid.py`: `test_the_two_cloud_systems_carry_their_clouds`, `test_no_other_system_grew_a_cloud`, `test_ambiguities_itself_reports_a_bogus_cloud_kind`, `test_a_bogus_cloud_kind_reaches_the_generators_ambiguities_output`.
  - `tests/unit/test_system_map_validate.py`: remove the `cloud_profiles`/`Cloud`/`Volume` imports, the cloud fixture (≈49–76), every test asserting a `cloud-*` rule or a cloud-driven `malformed-geometry` problem, and `"clouds"` from the parametrized field lists (≈390, ≈407). Keep the Task 3 profile tests.
  - `tests/tools/test_system_layout.py`: every test that builds or inspects clouds / passes `cloud=` (≈634–817). **Keep** `test_a_regions_nebula_is_carried_into_the_map` (≈541) and the survey-ambiguity test at ≈718 if it does not pass `cloud=`.
  - `tests/unit/test_system_maps_valid.py::test_belaruzs_description_matches_where_its_cloud_actually_is`: keep clause 1 only, re-derived from `Region.nebula` instead of `m.clouds`:

```python
    import math
    from engine.systems.profile import clump_radius
    region = m.region("Belaruz1")
    pocket = clump_radius(region, star.position_gu)
    assert all(math.dist(p.position_gu, star.position_gu) > pocket for p in planets)
```

  Delete its clause-2 (lobe) assertions. Task 12 rewrites the text and this test together.

- [ ] **Step 3: Run the suite to see what now fails for the right reason**

Run: `uv run pytest tests/unit tests/tools -q -x -k "system or survey or layout or cloud"`
Expected: PASS (you removed tests; nothing yet references removed code).

- [ ] **Step 4: Remove the code**
  - `engine/systems/map.py`: delete `Volume`, `Cloud`, `SystemMap.clouds`, `SystemMap.cloud()`, `_volume_from_json`, `_cloud_from_json`, the `clouds = [...]` line and `clouds=clouds` argument in `from_json`.
  - `git rm engine/systems/clouds.py`.
  - `engine/systems/validate.py`: delete `from .clouds import PROFILES, params_for` (≈18), `_looks_like_volume`, `_volume_geometry_ok`, `_volume_extent`, `_PARAM_KEYS`, `_pocket_param_details`, `_sphere_entries`, `_match_pockets_to_region`, `_pocket_inside_large`, the `clouds = _sequence_field(m, "clouds", problems)` line (≈478), the `star_origin` setup (≈698–700) and the whole cloud rule block (≈684–866), including the cloud problems filed under `malformed-geometry`.
  - `tools/systems/layout.py`: delete the `clouds as cloud_profiles` import and `Cloud`, `Volume` from the map import (≈30–31), `_build_cloud_large_volume`, `_build_clouds`, the `m.clouds = _build_clouds(m, cloud)` line (≈879), the `cloud=` parameter and its forwarding in `_first_orbit_push`, `_place`, `layout` and `ambiguities`, and the cloud-kind check in `ambiguities` (≈594–604). Update the docstrings that mention `cloud`.
  - `tools/gen_system_maps.py`: delete `cloud_from` and its use in `generate()`; `layout(...)` and `ambiguities(surveyed)` lose `cloud=`.
  - `engine/systems/maps/belaruz.json`, `vesuvi.json`: delete the `"cloud"` key from `"overrides"` (the `why` string citing "Belaruz 4 at 121,181 GU" goes with it).
  - `engine/systems/resolve.py:26` docstring and the three doc lines listed under **Files**: remove the `clouds` references (celestial-layer spec/plan: "`SystemMap.clouds` is checked in and stays unread" → "system clouds are the radial profile (2026-09-23-radial-system-profile-design.md)"; system-frames item 10: same pointer).

- [ ] **Step 5: Regenerate every map**

Run: `uv run python tools/gen_system_maps.py`
Expected: every system `ok`, no `PROBLEM(S)`. Then `git diff --stat engine/systems/maps/` — only the `"clouds"` key (and Belaruz/Vesuvi `overrides.cloud`) disappears; **no position or radius changes**. If any position moved, STOP (BLOCKED: layout changed during cloud removal).

- [ ] **Step 6: Prove nothing still references the model**

Run: `grep -rn "clouds\b\|\bCloud\b\|\bVolume\b\|cloud_from\|cloud_profiles\|params_for" engine tools tests --include=*.py`
Expected: no hits except unrelated uses (e.g. "star-clouds" comments, `Dust Cloud` set names). Fix any real hit.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/unit tests/tools -q`
Expected: PASS (or only baselined failures — confirm with `cat tests/known_failures.txt`).

- [ ] **Step 8: Commit**

```bash
git add -u engine/systems tools tests docs/superpowers/specs/2026-09-23-celestial-layer-design.md docs/superpowers/plans/2026-09-24-celestial-layer.md docs/superpowers/specs/2026-09-24-system-frames-design.md
git commit -m "refactor(systems): remove the placed cloud model, superseded by the radial profile"
```

(`git add -u` stages only tracked files under the named paths, including the deletions; check `git status --short` shows nothing unexpected staged.)

---

### Task 5: The generator writes profiles; Vesuvi's hand profile

**Files:**
- Modify: `tools/gen_system_maps.py` (add `profile_from`, call `build_profile` in `generate()`)
- Modify: `engine/systems/maps/vesuvi.json` (add `overrides.profile`), then all 32 maps (regenerated)
- Test: `tests/unit/test_system_maps_valid.py` (append), `tests/tools/test_gen_system_maps_profile.py` (create)

**Interfaces:**
- Consumes: `build_profile(m, override, *, campaign)` (Task 2); rules (Task 3).
- Produces: every committed map carries `"profile"`; `profile_from(m) -> dict | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tools/test_gen_system_maps_profile.py
from engine.systems.map import SystemMap
from tools.gen_system_maps import profile_from


def test_profile_from_reads_the_override():
    m = SystemMap(system="X", overrides={"profile": {"rows": [{"distance_gu": 0.0}]}})
    assert profile_from(m) == {"rows": [{"distance_gu": 0.0}]}
    assert profile_from(SystemMap(system="X")) is None
    assert profile_from(None) is None
```

Append to `tests/unit/test_system_maps_valid.py`:

```python
def test_every_committed_map_carries_a_profile_with_star_radiation():
    from engine.systems.profile import evaluate
    for name in available():
        m = load(name)
        assert m.profile is not None, name
        star = [b for b in m.bodies if b.orbits is None][0]
        assert evaluate(m.profile, star.radius_gu).radiation == 1.0, name
        assert evaluate(m.profile, 3.0 * star.radius_gu + 1.0).radiation < 1.0, name


def test_no_region_sits_inside_its_stars_radiation():
    """Star radiation reaches 3 star radii; every region must clear it."""
    import math
    for name in available():
        m = load(name)
        star = [b for b in m.bodies if b.orbits is None][0]
        for r in m.regions:
            d = math.dist(r.anchor_gu, star.position_gu) - r.radius_gu
            assert d > 3.0 * star.radius_gu, (name, r.set_name)


def test_multi_systems_have_no_cloud_rows():
    from engine.systems.profile import evaluate
    for name in available():
        if not name.startswith("multi"):
            continue
        m = load(name)
        star = [b for b in m.bodies if b.orbits is None][0]
        for row in m.profile.rows:
            assert (row.nebula, row.dust, row.sensors, row.asteroids) == (0, 0, 0, 0), name
        assert m.profile.color is None


def test_belaruz_profile_peaks_at_its_clump_and_does_not_burn():
    from engine.systems.profile import clump_radius, evaluate
    m = load("belaruz")
    star = [b for b in m.bodies if b.orbits is None][0]
    R = clump_radius(m.region("Belaruz1"), star.position_gu)
    s = evaluate(m.profile, R)
    assert s.nebula == pytest.approx(6.5 / 10.5, abs=1e-3)
    assert s.radiation == 0.0


def test_vesuvi_profile_is_its_override_composed_with_the_star():
    from engine.systems.profile import evaluate
    from tools.systems.profile_builder import override_rows, star_rows, compose_max
    from engine.systems.profile import Profile
    m = load("vesuvi")
    star = [b for b in m.bodies if b.orbits is None][0]
    expected = Profile(rows=compose_max(override_rows(m.overrides["profile"]),
                                        star_rows(star.radius_gu)))
    for r in (0.0, 3000.0, 6000.0, 100000.0, 123500.0, 175000.0, 250000.0, 335000.0, 1e7):
        assert evaluate(m.profile, r) == evaluate(expected, r), r
    s = evaluate(m.profile, 150000.0)
    assert s.radiation >= 0.4 and s.dust >= 0.2 and s.asteroids >= 0.05
    assert evaluate(m.profile, 280000.0).asteroids == pytest.approx(0.5)
    assert evaluate(m.profile, 229620.0).radiation == 0.0   # Vesuvi 5 colonies clear


def test_vesuvi_4_sphere_constant_matches_the_survey():
    from tools.systems.profile_builder import VESUVI_4_SPHERES
    assert [tuple(s) for s in load("vesuvi").region("Vesuvi4").nebula["spheres"]] == \
        [tuple(s) for s in VESUVI_4_SPHERES]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_gen_system_maps_profile.py tests/unit/test_system_maps_valid.py -v`
Expected: FAIL — `ImportError: profile_from`, `m.profile is None`.

- [ ] **Step 3: Implement** in `tools/gen_system_maps.py`:

```python
from tools.systems.profile_builder import build_profile  # noqa: E402


def profile_from(m):
    """The map's hand profile (overrides.profile) as a dict, or None.
    Replaces the derived cloud rows wholesale; the star term still composes
    on top (tools/systems/profile_builder.build_profile)."""
    if m is None:
        return None
    return (getattr(m, "overrides", None) or {}).get("profile")
```

In `generate()`, after `fresh = layout(...)` and before `_merge_overrides(fresh, old)`:

```python
    fresh.profile = build_profile(
        fresh, profile_from(old),
        campaign=not system.lower().startswith("multi"))
```

- [ ] **Step 4: Add Vesuvi's hand profile** to `engine/systems/maps/vesuvi.json` under `"overrides"` (values from the spec's table, Mark 2026-09-28):

```json
"profile": {
  "why": "Mark 2026-09-28: dust >= 0.1 (0.2 beyond the cloud), sensors reduced system-wide, radiation >= 0.4 to ~170k, asteroid band Geki->Haven. Nebula keeps the derived curve. Absolute GU against the layout at 10129269; profile-override-tracks-clump fails generation if the cloud moves.",
  "rows": [
    {"distance_gu": 0.0,      "nebula": 0.0,  "dust": 0.1, "sensors": 0.3, "radiation": 0.4, "asteroids": 0.05},
    {"distance_gu": 61750.0,  "nebula": 0.0,  "dust": 0.1, "sensors": 0.3, "radiation": 0.4, "asteroids": 0.05},
    {"distance_gu": 116366.0, "nebula": 0.88, "dust": 0.1, "sensors": 0.3, "radiation": 0.4, "asteroids": 0.05},
    {"distance_gu": 123500.0, "nebula": 1.0,  "dust": 1.0, "sensors": 1.0, "radiation": 1.0, "asteroids": 0.05},
    {"distance_gu": 130634.0, "nebula": 0.95, "dust": 0.2, "sensors": 0.3, "radiation": 0.4, "asteroids": 0.05},
    {"distance_gu": 170000.0, "nebula": 0.64, "dust": 0.2, "sensors": 0.3, "radiation": 0.4, "asteroids": 0.05},
    {"distance_gu": 180000.0, "nebula": 0.56, "dust": 0.2, "sensors": 0.3, "radiation": 0.0, "asteroids": 0.05},
    {"distance_gu": 215000.0, "nebula": 0.3,  "dust": 0.2, "sensors": 0.3, "radiation": 0.0, "asteroids": 0.05},
    {"distance_gu": 226000.0, "nebula": 0.21, "dust": 0.2, "sensors": 0.3, "radiation": 0.0, "asteroids": 0.5},
    {"distance_gu": 247000.0, "nebula": 0.05, "dust": 0.2, "sensors": 0.3, "radiation": 0.0, "asteroids": 0.5},
    {"distance_gu": 330000.0, "nebula": 0.05, "dust": 0.2, "sensors": 0.3, "radiation": 0.0, "asteroids": 0.5},
    {"distance_gu": 340000.0, "nebula": 0.05, "dust": 0.2, "sensors": 0.3, "radiation": 0.0, "asteroids": 0.05}
  ]
}
```

`override_rows` must ignore the `"why"` key — it reads only `raw["rows"]`, so it already does.

- [ ] **Step 5: Regenerate**

Run: `uv run python tools/gen_system_maps.py`
Expected: every system `ok`. `git diff --stat engine/systems/maps/` shows all 32 files gaining `"profile"`, nothing else moved.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/tools/test_gen_system_maps_profile.py tests/unit/test_system_maps_valid.py tests/unit/test_system_map_validate.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/gen_system_maps.py engine/systems/maps/*.json tests/tools/test_gen_system_maps_profile.py tests/unit/test_system_maps_valid.py
git commit -m "feat(systems): every map carries a radial profile; Vesuvi's is hand-authored"
```

---

### Task 6: Know whether an event reached the end of its handler chain

BC's `ET_ENVIRONMENT_DAMAGE` is cancelled by a handler that returns without `CallNextHandler` (E3M2 `CoreDamage` during the stellar-core cutscene; `MissionLib.IgnoreEvent`). Radiation damage must land only when the chain completes.

**Files:**
- Modify: `engine/appc/events.py` (`TGEventHandlerObject.ProcessEvent`, `_invoke_next_handler`; add `dispatch_passes`)
- Test: `tests/unit/test_event_chain_passes.py`

**Interfaces:**
- Produces: `engine.appc.events.dispatch_passes(event) -> bool` — posts `event` through `App.g_kEventManager.AddEvent` and returns True iff no destination handler stopped the chain.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_event_chain_passes.py
import sys
import types

import App
from engine.appc.events import TGEventHandlerObject, dispatch_passes


def _event(dest):
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_ENVIRONMENT_DAMAGE)
    evt.SetDestination(dest)
    return evt


def _install(name, fn):
    mod = types.ModuleType(name)
    mod.h = fn
    sys.modules[name] = mod
    return name + ".h"


def test_no_handlers_passes():
    assert dispatch_passes(_event(TGEventHandlerObject())) is True


def test_handler_that_calls_next_passes():
    obj = TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, _install("_chain_next", lambda o, e: o.CallNextHandler(e)))
    assert dispatch_passes(_event(obj)) is True


def test_handler_that_returns_swallows():
    obj = TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, _install("_chain_stop", lambda o, e: None))
    assert dispatch_passes(_event(obj)) is False


def test_ignore_event_swallows():
    obj = TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "MissionLib.IgnoreEvent")
    assert dispatch_passes(_event(obj)) is False


def test_destination_without_process_event_passes():
    class Plain:
        pass
    assert dispatch_passes(_event(Plain())) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_event_chain_passes.py -v`
Expected: FAIL — `ImportError: dispatch_passes`. (If `MissionLib.IgnoreEvent` cannot resolve in the unit environment, `_resolve_handler` returns None and the chain *skips* it — then that test fails for a different reason; check how `tests/unit/test_nebula.py::test_ignore_event_opt_out_takes_no_damage` registers it and mirror that setup.)

- [ ] **Step 3: Implement** in `engine/appc/events.py`:

In `TGEventHandlerObject.ProcessEvent`, before `if not names: return`, nothing changes; after computing `names` and before building `frame`:

```python
        names = self._handlers.get(event.GetEventType(), [])
        if not names:
            return
        event._chain_passed = False
```

In `_invoke_next_handler`, the end-of-chain branch:

```python
        if index >= len(chain):
            event._chain_passed = True
            return
```

Add at module level (after the classes):

```python
def dispatch_passes(event) -> bool:
    """Post `event` and report whether its destination's instance-handler
    chain ran to the end. A handler that returns without CallNextHandler
    stops the chain -- BC's way of cancelling an event's default effect
    (E3M2 CoreDamage; MissionLib.IgnoreEvent). No handlers = passes."""
    import App
    event._chain_passed = True
    App.g_kEventManager.AddEvent(event)
    return event._chain_passed is True
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_event_chain_passes.py tests/unit/test_nebula.py -v` and `uv run pytest tests/unit -q -k "event or handler or hail"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/events.py tests/unit/test_event_chain_passes.py
git commit -m "feat(events): report whether an event's handler chain ran to the end"
```

---

### Task 7: Radiation driver — drain and events

**Files:**
- Create: `engine/appc/radiation.py`
- Test: `tests/unit/test_radiation.py`

**Interfaces:**
- Consumes: `dispatch_passes` (Task 6); `Sample` (Task 1); `nebula_runtime._shields_up`; `warp_state.is_ship_warping`; `Game_GetDifficulty`.
- Produces: `RadiationDriver(sample_for, rng=None)` with `update(ships, dt, shared=frozenset())`, `apply_chunk(ship, radiation, mult)`, `reset()`; constants `EVENT_HZ`, `HULL_PER_S`, `SHIELD_PER_S`, `DIFFICULTY_MULT`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_radiation.py
import sys
import types

import pytest

import App
from engine.appc.events import TGEventHandlerObject
from engine.appc.radiation import RadiationDriver
from engine.core import game
from engine.systems.profile import Sample


class _Faces:
    NUM_SHIELDS = 6

    def __init__(self, v, on=True):
        self._v = [v] * 6
        self._on = on

    def IsOn(self):
        return 1 if self._on else 0

    def GetCurrentShields(self, f):
        return self._v[f]

    def SetCurrentShields(self, f, v):
        self._v[f] = v


class _Hull:
    def __init__(self, c):
        self._c = c

    def GetCondition(self):
        return self._c

    def SetCondition(self, v):
        self._c = v


class _Ship(TGEventHandlerObject):
    def __init__(self, hull=1000.0, shield=500.0, shields_on=True):
        super().__init__()
        self._hull = _Hull(hull)
        self._shield = _Faces(shield, shields_on)

    def GetHull(self):
        return self._hull

    def GetShieldSubsystem(self):
        return self._shield

    def GetSubsystems(self):
        return []

    def GetSensorSubsystem(self):
        return None


@pytest.fixture(autouse=True)
def _hard():
    before = game.Game_GetDifficulty()
    game.Game_SetDifficulty(2)
    yield
    game.Game_SetDifficulty(before)


def _run(driver, ships, seconds):
    # 61 ticks for "1 s": the 16th event falls exactly on t = 1.0, where
    # summed 1/60 steps can land a hair short.
    for _ in range(int(round(seconds * 60)) + 1):
        driver.update(ships, 1.0 / 60.0)


def test_shields_up_drain_twenty_per_face_per_second_at_full_hard():
    ship = _Ship()
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetShieldSubsystem().GetCurrentShields(0) == pytest.approx(480.0, abs=1.5)
    assert ship.GetHull().GetCondition() == 1000.0


def test_shields_down_drain_the_hull():
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=0.5)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == pytest.approx(1000.0 - 75.0, abs=5.0)


@pytest.mark.parametrize("level,expected", [(0, 1000.0), (1, 925.0), (2, 850.0)])
def test_difficulty_scales_the_drain(level, expected):
    game.Game_SetDifficulty(level)
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == pytest.approx(expected, abs=10.0)


def test_events_fire_at_sixteen_hz_while_irradiated():
    ship = _Ship()
    seen = []
    mod = types.ModuleType("_rad_count")
    mod.h = lambda o, e: (seen.append(e), o.CallNextHandler(e))
    sys.modules["_rad_count"] = mod
    ship.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "_rad_count.h")
    _run(RadiationDriver(lambda s: Sample(radiation=0.1)), [ship], 1.0)
    assert len(seen) == 16


def test_no_events_or_damage_in_clear_space():
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample()), [ship], 1.0)
    assert ship.GetHull().GetCondition() == 1000.0


def test_swallowed_event_applies_no_damage():
    ship = _Ship(shields_on=False)
    ship.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "MissionLib.IgnoreEvent")
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == 1000.0


def test_no_drain_while_dashing(monkeypatch):
    from engine.appc import warp_state
    monkeypatch.setattr(warp_state, "is_ship_warping", lambda obj: True)
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == 1000.0


def test_hull_drain_goes_through_damage_system_when_the_ship_has_one():
    calls = []

    class _Real(_Ship):
        def DamageSystem(self, sub, amount, source=None):
            calls.append(amount)
            sub.SetCondition(sub.GetCondition() - amount)

    ship = _Real(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert len(calls) == 16 and calls[0] == pytest.approx(150.0 / 16.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_radiation.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.radiation`.

- [ ] **Step 3: Implement `engine/appc/radiation.py`**

```python
"""Profile radiation: a deliberate departure from BC.

BC's SetupDamage nebula deals ONE hit at creation (bible §15 E1; see
nebula_runtime). The radial profile adds real harm, scaled by BC's own
Vesuvi 4 numbers. Damage is carried by ET_ENVIRONMENT_DAMAGE at 16 Hz: each
event that runs its destination's handler chain to the end lands 1/16 s of
drain (and one outage roll, Task 8); a handler that stops the chain cancels
it, as E3M2's CoreDamage and MissionLib.IgnoreEvent do in BC.

Design: docs/superpowers/specs/2026-09-23-radial-system-profile-design.md.
"""
from __future__ import annotations

import random

import App

from engine.core.ids import implements

EVENT_HZ = 16.0
HULL_PER_S = 150.0
SHIELD_PER_S = 20.0
DIFFICULTY_MULT = (0.0, 0.5, 1.0)


def _mult() -> float:
    from engine.core.game import Game_GetDifficulty
    level = Game_GetDifficulty()
    return DIFFICULTY_MULT[max(0, min(2, int(level)))]


def _fire(ship) -> bool:
    from engine.appc.events import dispatch_passes
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_ENVIRONMENT_DAMAGE)
    evt.SetDestination(ship)
    return dispatch_passes(evt)


class RadiationDriver:
    def __init__(self, sample_for, rng=None):
        self._sample_for = sample_for
        self._rng = rng if rng is not None else random.Random()
        self._accum = {}     # id(ship) -> seconds banked toward the next event

    def reset(self) -> None:
        self._accum.clear()

    def update(self, ships, dt, shared=frozenset()) -> None:
        """One fixed sim tick. `shared`: ids of ships inside an ARMED local
        MetaNebula -- their events come from NebulaTracker (Task 9)."""
        from engine.appc import warp_state
        m = _mult()
        period = 1.0 / EVENT_HZ
        live = set()
        for ship in ships:
            sid = id(ship)
            if m <= 0.0 or warp_state.is_ship_warping(ship) or sid in shared:
                continue
            r = self._sample_for(ship).radiation
            if r <= 0.0:
                continue
            live.add(sid)
            acc = self._accum.get(sid, 0.0) + dt
            while acc >= period:
                acc -= period
                if _fire(ship):
                    self.apply_chunk(ship, r, m)
            self._accum[sid] = acc
        for sid in list(self._accum):
            if sid not in live:
                del self._accum[sid]

    def apply_chunk(self, ship, radiation: float, mult: float) -> None:
        """1/16 s of drain: shields per face while up, else the hull."""
        from engine.appc.nebula_runtime import _shields_up
        dt = 1.0 / EVENT_HZ
        shields = _shields_up(ship)
        if shields is not None:
            per_face = SHIELD_PER_S * radiation * mult * dt
            for face in range(shields.NUM_SHIELDS):
                cur = shields.GetCurrentShields(face) - per_face
                shields.SetCurrentShields(face, cur if cur > 0.0 else 0.0)
        else:
            hull = ship.GetHull() if hasattr(ship, "GetHull") else None
            amount = HULL_PER_S * radiation * mult * dt
            if hull is not None and amount > 0.0:
                if implements(ship, "DamageSystem"):
                    ship.DamageSystem(hull, amount)
                else:
                    new = hull.GetCondition() - amount
                    hull.SetCondition(new if new > 0.0 else 0.0)
```

If `implements` rejects the test's `_Real.DamageSystem` (it checks the class MRO), read `engine/core/ids.py:implements` and adjust the fake, not the production check.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_radiation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/radiation.py tests/unit/test_radiation.py
git commit -m "feat(radiation): profile radiation drains shields/hull via 16 Hz environment events"
```

---

### Task 8: Radiation outages

**Files:**
- Modify: `engine/appc/radiation.py` (outage roll in `apply_chunk`, outage bookkeeping in `update`/`reset`)
- Modify: `engine/appc/subsystems.py` (`ShipSubsystem.__init__` gains `self._radiation_out = False`; `_is_offline` honours it and the parent's)
- Test: `tests/unit/test_radiation.py` (append)

**Interfaces:**
- Consumes: Task 7's driver.
- Produces: constants `OUTAGE_MEAN_INTERVAL_S = 30.0`, `OUTAGE_MIN_S = 5.0`, `OUTAGE_MAX_S = 20.0`; `RadiationDriver.active_outages() -> dict[int, float]` (id(sub) → seconds left); `ShipSubsystem._radiation_out: bool`.

- [ ] **Step 1: Write the failing tests** (append)

```python
import random as _random

from engine.appc.subsystems import (
    HullSubsystem, PowerSubsystem, SensorSubsystem, ShieldSubsystem, _is_offline)


class _SubShip(_Ship):
    def __init__(self):
        super().__init__(shields_on=True)
        self.subs = [HullSubsystem("Hull"), PowerSubsystem("Power"),
                     SensorSubsystem("Sensors"), ShieldSubsystem("Shields")]

    def GetSubsystems(self):
        return list(self.subs)


class _AlwaysRoll(_random.Random):
    def random(self):
        return 0.0


def test_outage_never_picks_hull_or_power():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_random.Random(7))
    for _ in range(400):
        d.apply_chunk(ship, 1.0, 1.0)
        d._tick_outages(1.0 / 16.0, {id(ship)})
    hull, power = ship.subs[0], ship.subs[1]
    assert hull._radiation_out is False and power._radiation_out is False


def test_outage_rate_is_about_one_per_thirty_seconds_at_full_hard():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_random.Random(1))
    starts = 0
    for _ in range(int(16 * 3000)):          # 3000 s of events
        before = set(d.active_outages())
        d.apply_chunk(ship, 1.0, 1.0)
        starts += len(set(d.active_outages()) - before)
        d._tick_outages(1.0 / 16.0, {id(ship)})
    assert 70 <= starts <= 130               # expectation 100


def test_outage_lasts_between_five_and_twenty_seconds():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    (sid, left), = d.active_outages().items()
    assert 5.0 <= left <= 20.0


def test_out_subsystem_is_offline_until_expiry():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=0.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    out = [s for s in ship.subs if s._radiation_out]
    assert len(out) == 1 and _is_offline(out[0])
    for _ in range(21 * 60):
        d.update([ship], 1.0 / 60.0)
    assert not out[0]._radiation_out and not _is_offline(out[0])


def test_outage_clears_when_ship_leaves_the_ship_list():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=0.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    d.update([], 1.0 / 60.0)
    assert not any(s._radiation_out for s in ship.subs)
    assert d.active_outages() == {}


def test_reset_clears_all_outages():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=0.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    d.reset()
    assert not any(s._radiation_out for s in ship.subs)


def test_child_of_an_out_subsystem_is_offline():
    parent = SensorSubsystem("Parent")
    child = SensorSubsystem("Child")
    child._parent_subsystem = parent
    parent._radiation_out = True
    assert _is_offline(child)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_radiation.py -v`
Expected: new tests FAIL (`active_outages` missing / `_radiation_out` missing).

- [ ] **Step 3: Implement**

`engine/appc/subsystems.py` — in `ShipSubsystem.__init__` add `self._radiation_out = False` (TGObject's `__getattr__` vends truthy stubs for unknown names, so the attribute must exist). In `_is_offline`, immediately after the `sub is None` guard:

```python
    # Radiation outage (engine/appc/radiation.py): this subsystem, or the
    # system it belongs to. `is True`, never truthiness -- a stubbed fake
    # would answer a truthy _Stub.
    if getattr(sub, "_radiation_out", False) is True:
        return True
    parent = getattr(sub, "_parent_subsystem", None)
    if parent is not None and getattr(parent, "_radiation_out", False) is True:
        return True
```

`engine/appc/radiation.py` — add:

```python
OUTAGE_MEAN_INTERVAL_S = 30.0
OUTAGE_MIN_S = 5.0
OUTAGE_MAX_S = 20.0
```

In `__init__`: `self._outages = {}  # id(sub) -> [sub, id(ship), seconds_left]`.

```python
    def active_outages(self) -> dict:
        return {sid: entry[2] for sid, entry in self._outages.items()}

    def _end(self, sid) -> None:
        sub = self._outages.pop(sid)[0]
        sub._radiation_out = False

    def _tick_outages(self, dt, ship_ids) -> None:
        for sid in list(self._outages):
            entry = self._outages[sid]
            entry[2] -= dt
            if entry[2] <= 0.0 or entry[1] not in ship_ids:
                self._end(sid)

    def _maybe_start_outage(self, ship, radiation, mult) -> None:
        p = radiation * mult * (1.0 / EVENT_HZ) / OUTAGE_MEAN_INTERVAL_S
        if self._rng.random() >= p:
            return
        from engine.appc.subsystems import HullSubsystem, PowerSubsystem
        subs = ship.GetSubsystems() if hasattr(ship, "GetSubsystems") else []
        pool = [s for s in subs
                if s is not None
                and not isinstance(s, (HullSubsystem, PowerSubsystem))
                and id(s) not in self._outages]
        if not pool:
            return
        sub = self._rng.choice(pool)
        sub._radiation_out = True
        self._outages[id(sub)] = [sub, id(ship),
                                  self._rng.uniform(OUTAGE_MIN_S, OUTAGE_MAX_S)]
```

Call `self._maybe_start_outage(ship, radiation, mult)` at the end of `apply_chunk`. At the **start** of `update`, add `self._tick_outages(dt, {id(s) for s in ships if not _dying(s)})` where:

```python
def _dying(ship) -> bool:
    return bool(implements(ship, "IsDying") and ship.IsDying()) or \
        bool(implements(ship, "IsDead") and ship.IsDead())
```

In `reset`, end every outage: `for sid in list(self._outages): self._end(sid)` then clear `_accum`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_radiation.py tests/unit -q -k "offline or subsystem or radiation"`
Expected: PASS. Then the full unit suite: `uv run pytest tests/unit -q` — `_is_offline` is hot and widely used; any new failure here is a regression.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/radiation.py engine/appc/subsystems.py tests/unit/test_radiation.py
git commit -m "feat(radiation): random 5-20 s subsystem outages while irradiated"
```

---

### Task 9: One event stream per ship, and host-loop wiring

**Files:**
- Modify: `engine/appc/nebula_runtime.py` (`_fire` returns the chain result; `NebulaTracker.env_listeners`, `ships_in_armed_nebula()`)
- Modify: `engine/appc/radiation.py` (`on_local_event`)
- Modify: `engine/host_loop.py` (≈10436 tick block; ≈4410 reset; ≈4690 global)
- Test: `tests/unit/test_radiation.py` (append), `tests/unit/test_nebula.py` must still pass unchanged

**Interfaces:**
- Consumes: Tasks 6–8.
- Produces: `NebulaTracker.env_listeners: list[callable(ship, passed: bool)]`, `NebulaTracker.ships_in_armed_nebula() -> set[int]`, `RadiationDriver.on_local_event(ship, passed)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_radiation.py`)

```python
from engine.appc.nebula_runtime import NebulaTracker


def _armed_set_with(ship_pos):
    s = App.SetClass_Create()
    n = App.MetaNebula_Create(0.6, 0.35, 0.72, 145.0, 10.5, "i.tga", "e.tga")
    n.SetupDamage(150.0, 20.0)
    n.AddNebulaSphere(0.0, 0.0, 0.0, 1500.0)
    s.AddObjectToSet(n, "neb")
    return s


class _PosShip(_Ship):
    def GetWorldLocation(self):
        return App.TGPoint3(0.0, 0.0, 0.0)


def test_ship_inside_armed_local_nebula_gets_no_profile_events():
    ship = _PosShip()
    seen = []
    mod = types.ModuleType("_rad_count2")
    mod.h = lambda o, e: (seen.append(e), o.CallNextHandler(e))
    sys.modules["_rad_count2"] = mod
    ship.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "_rad_count2.h")
    s = _armed_set_with((0.0, 0.0, 0.0))
    tracker = NebulaTracker()
    d = RadiationDriver(lambda sh: Sample(radiation=1.0))
    tracker.env_listeners.append(d.on_local_event)
    for _ in range(61):
        tracker.update(s, [ship], 1.0 / 60.0)
        d.update([ship], 1.0 / 60.0, shared=tracker.ships_in_armed_nebula())
    assert len(seen) == 16                    # the tracker's stream only


def test_local_nebula_events_carry_the_profile_drain():
    ship = _PosShip(shields_on=False)
    s = _armed_set_with((0.0, 0.0, 0.0))
    tracker = NebulaTracker()
    d = RadiationDriver(lambda sh: Sample(radiation=1.0))
    tracker.env_listeners.append(d.on_local_event)
    tracker.update(s, [ship], 1.0 / 60.0)     # first sighting: BC's one-off hit
    after_creation = ship.GetHull().GetCondition()
    for _ in range(61):
        tracker.update(s, [ship], 1.0 / 60.0)
        d.update([ship], 1.0 / 60.0, shared=tracker.ships_in_armed_nebula())
    assert after_creation - ship.GetHull().GetCondition() == pytest.approx(150.0, abs=15.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_radiation.py -k local -v`
Expected: FAIL — `AttributeError: env_listeners`.

- [ ] **Step 3: Implement**

`engine/appc/nebula_runtime.py`: make `_fire` return whether the chain passed, only for environment damage:

```python
def _fire(event_type, nebula, ship):
    evt = App.TGEvent_Create()
    evt.SetEventType(event_type)
    evt.SetSource(nebula)
    evt.SetDestination(ship)
    from engine.appc.events import dispatch_passes
    return dispatch_passes(evt)
```

(Read the existing `_fire` first and keep its exact event construction; only the last line changes from `App.g_kEventManager.AddEvent(evt)` to `return dispatch_passes(evt)`.)

In `NebulaTracker.__init__` add `self.env_listeners = []` and `self._armed = {}  # id(nebula) -> bool`; in `reset` clear `_armed`. In `update`, after computing `armed`, `self._armed[key] = armed`; replace the env-fire line with:

```python
                    if fire_env:
                        passed = _fire(App.ET_ENVIRONMENT_DAMAGE, nebula, ship)
                        for listener in self.env_listeners:
                            listener(ship, passed)
```

Add:

```python
    def ships_in_armed_nebula(self) -> set:
        """ids of ships currently inside a nebula that raises
        ET_ENVIRONMENT_DAMAGE -- the profile's radiation rides those events
        instead of firing its own (one stream per ship)."""
        out = set()
        for key, ships in self._inside.items():
            if self._armed.get(key):
                out |= ships
        return out
```

`engine/appc/radiation.py`:

```python
    def on_local_event(self, ship, passed) -> None:
        """NebulaTracker listener: a local armed nebula fired this ship's
        environment event; land the profile's chunk on it if it passed."""
        from engine.appc import warp_state
        m = _mult()
        if not passed or m <= 0.0 or warp_state.is_ship_warping(ship):
            return
        r = self._sample_for(ship).radiation
        if r > 0.0:
            self.apply_chunk(ship, r, m)
```

`engine/host_loop.py`: beside `_nebula_tracker = None` (≈4690) add `_radiation_driver = None  # RadiationDriver | None`. Where `_nebula_tracker.reset()` runs (≈4410) add, in the same guard style:

```python
    if _radiation_driver is not None:
        _radiation_driver.reset()
```

(Add `_radiation_driver` to that function's `global` statement.) In the sim-tick block right after `_nebula_tracker.update(...)` (≈10451):

```python
                    # Radial-profile radiation (engine/appc/radiation.py):
                    # drain + outages via 16 Hz ET_ENVIRONMENT_DAMAGE. Ships
                    # inside an armed local nebula ride the tracker's events.
                    global _radiation_driver
                    if _radiation_driver is None:
                        from engine.appc.radiation import RadiationDriver
                        from engine.systems import profile as _profile
                        _radiation_driver = RadiationDriver(_profile.sample_for_object)
                        _nebula_tracker.env_listeners.append(
                            _radiation_driver.on_local_event)
                    _radiation_driver.update(
                        _neb_set.GetClassObjectList(App.CT_SHIP), TICK_DT,
                        shared=_nebula_tracker.ships_in_armed_nebula())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_radiation.py tests/unit/test_nebula.py tests/oracle/test_nebula.py -v`
Expected: PASS — the nebula and oracle tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/nebula_runtime.py engine/appc/radiation.py engine/host_loop.py tests/unit/test_radiation.py
git commit -m "feat(radiation): wire the driver into the sim tick, one event stream per ship"
```

---

### Task 10: Profile concealment

**Files:**
- Modify: `engine/appc/sensor_detection.py` (`concealment_at`)
- Test: `tests/unit/test_profile_concealment.py`

**Interfaces:**
- Consumes: `profile.locate`, `profile.evaluate` (Task 1).
- Produces: `concealment_at(ship) = max(local fbm, sensors(r) · full_concealment)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_profile_concealment.py
import pytest

from engine.appc import sensor_detection
from engine.systems import profile as P


def _prof(sensors):
    return P.Profile(rows=[P.ProfileRow(0.0, sensors=sensors)], full_concealment=0.4)


def test_profile_concealment_applies_with_no_local_nebula(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.5), 1000.0))
    ship = type("S", (), {})()
    assert sensor_detection.concealment_at(ship) == pytest.approx(0.2)


def test_the_larger_of_local_and_profile_wins(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.25), 1000.0))
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.3)
    assert sensor_detection.concealment_at(object()) == pytest.approx(0.3)
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.05)
    assert sensor_detection.concealment_at(object()) == pytest.approx(0.1)


def test_unmapped_object_gets_no_profile_concealment(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: None)
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.0)
    assert sensor_detection.concealment_at(object()) == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_profile_concealment.py -v`
Expected: FAIL (`_local_concealment` does not exist; profile ignored).

- [ ] **Step 3: Implement** — rename the existing body of `concealment_at` to `_local_concealment(ship) -> float` (unchanged code, including its docstring's first line adjusted to "Max local MetaNebula density..."), then:

```python
def concealment_at(ship) -> float:
    """Concealment at *ship*: the larger of the local MetaNebula fbm density
    and the radial profile's `sensors` column scaled by its measured full
    concealment (docs/superpowers/specs/2026-09-23-radial-system-profile-design.md)."""
    local = _local_concealment(ship)
    from engine.systems import profile as _profile
    found = _profile.locate(ship)
    if found is None or found[0] is None:
        return local
    prof, r = found
    return max(local, _profile.evaluate(prof, r).sensors * prof.full_concealment)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_profile_concealment.py tests/unit -q -k "concealment or sensor or detect or cloak"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_detection.py tests/unit/test_profile_concealment.py
git commit -m "feat(sensors): radial-profile concealment, max with the local nebula"
```

---

### Task 11: Dust density from the profile

**Files:**
- Modify: `native/src/renderer/include/renderer/dust_pass.h`, `native/src/renderer/dust_pass.cc` (extra `profile_dust` arg on `compute_dust_influence` and `DustPass::render`)
- Modify: `native/src/host/host_bindings.cc` (`g_dust_profile`, `set_dust_profile`, pass into `render`, clear with the other feeds at ≈599)
- Modify: `engine/host_loop.py` (`_push_environment_feeds` gets `player`; pushes the dust sample)
- Test: `native/tests/renderer/dust_pass_test.cc` (append), `tests/unit/test_dust_profile_feed.py`

**Interfaces:**
- Produces: `renderer::compute_dust_influence(camera_pos, suns, planets, float profile_dust = 0.0f)`; Python binding `set_dust_profile(dust: float)`.

- [ ] **Step 1: Write the failing C++ test** (append to `dust_pass_test.cc`)

```cpp
TEST(DustInfluence, ProfileDustLiftsDensityLinearlyToTheCeiling) {
    const std::vector<renderer::SunDescriptor> suns;
    const std::vector<glm::vec4> planets;
    const glm::vec3 cam(0.0f);
    EXPECT_FLOAT_EQ(renderer::compute_dust_influence(cam, suns, planets, 0.0f).density_mult, 1.0f);
    EXPECT_FLOAT_EQ(renderer::compute_dust_influence(cam, suns, planets, 0.5f).density_mult, 5.5f);
    EXPECT_FLOAT_EQ(renderer::compute_dust_influence(cam, suns, planets, 1.0f).density_mult,
                    static_cast<float>(renderer::DustPass::kMaxDensityMult));
}

TEST(DustInfluence, ProfileDustNeverLowersABodyBoostAndNeverTints) {
    std::vector<glm::vec4> planets{glm::vec4(0.0f, 0.0f, 0.0f, 10.0f)};
    const std::vector<renderer::SunDescriptor> suns;
    const glm::vec3 cam(0.0f, 10.0f, 0.0f);               // on the planet surface
    const auto base = renderer::compute_dust_influence(cam, suns, planets, 0.0f);
    const auto with = renderer::compute_dust_influence(cam, suns, planets, 0.1f);
    EXPECT_FLOAT_EQ(with.density_mult, base.density_mult);
    EXPECT_FLOAT_EQ(with.sun_tint, base.sun_tint);
}
```

- [ ] **Step 2: Build to verify failure**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile error — too many arguments to `compute_dust_influence`.

- [ ] **Step 3: Implement C++**

`dust_pass.h`: add `float profile_dust = 0.0f` as the last parameter of `compute_dust_influence` (doc: "radial-profile `dust` column at the camera, 0-1; lifts density only: max(body boost, 1 + (kMaxDensityMult-1)·dust)") and as the last parameter of `DustPass::render`.

`dust_pass.cc`, end of `compute_dust_influence` before `return out;`:

```cpp
    // Radial system profile (spec 2026-09-23-radial-system-profile): the
    // `dust` column lifts density only -- never tint, never drift.
    const float profile_mult =
        1.0f + std::clamp(profile_dust, 0.0f, 1.0f) *
                   (static_cast<float>(DustPass::kMaxDensityMult) - 1.0f);
    out.density_mult = std::max(out.density_mult, profile_mult);
```

(`#include <algorithm>` if absent.) In `DustPass::render`, pass `profile_dust` through: `compute_dust_influence(camera.eye, suns, planets, profile_dust)`.

`host_bindings.cc`: beside `g_dust_planets` (≈243) add `float g_dust_profile = 0.0f;`; reset it to `0.0f` where `g_suns.clear(); g_dust_planets.clear();` run (≈599); append `g_dust_profile` as the final argument of `g_dust_pass->render(...)` (≈1042); add a binding next to `set_dust_planets`:

```cpp
    m.def("set_dust_profile",
          [](float dust) { g_dust_profile = dust; },
          py::arg("dust"),
          "Radial-profile dust column at the camera (0-1), applied each frame().");
```

- [ ] **Step 4: Build and run the C++ tests**

Run: `cmake --build build -j && ctest --test-dir build -R DustInfluence --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Write the failing Python test**

```python
# tests/unit/test_dust_profile_feed.py
from engine import host_loop
from engine.systems import profile as P


class _R:
    def __init__(self):
        self.dust = None

    def __getattr__(self, name):
        if name == "set_dust_profile":
            return lambda v: setattr(self, "dust", v)
        return lambda *a, **k: None


def test_dust_sample_is_pushed_for_the_player(monkeypatch):
    monkeypatch.setattr(P, "sample_for_object", lambda obj: P.Sample(dust=0.3))
    r = _R()
    host_loop._push_dust_profile(r, player=object(), warp_streaking=False)
    assert r.dust == 0.3


def test_no_player_or_warp_tunnel_pushes_zero(monkeypatch):
    monkeypatch.setattr(P, "sample_for_object", lambda obj: P.Sample(dust=0.3))
    r = _R()
    host_loop._push_dust_profile(r, player=None, warp_streaking=False)
    assert r.dust == 0.0
    host_loop._push_dust_profile(r, player=object(), warp_streaking=True)
    assert r.dust == 0.0
```

Run: `uv run pytest tests/unit/test_dust_profile_feed.py -v` → FAIL (`_push_dust_profile` missing).

- [ ] **Step 6: Implement Python** in `engine/host_loop.py`, beside `_push_environment_feeds`:

```python
def _push_dust_profile(r, player, warp_streaking) -> None:
    """The radial profile's dust column at the player (the dust volume is
    camera-anchored and the camera stays within a few hundred GU of the
    player; the profile varies over thousands). Zero in the warp tunnel."""
    dust = 0.0
    if player is not None and not warp_streaking:
        from engine.systems import profile as _profile
        dust = _profile.sample_for_object(player).dust
    r.set_dust_profile(dust)
```

Add a `player=None` parameter to `_push_environment_feeds`, call `_push_dust_profile(r, player, warp_streaking)` right after `r.set_dust_planets(planets)`, and pass `player` at the call site (≈11387: `_push_environment_feeds(r, active_set, _warp_streaking, player=player)` — `player` is already a local there; confirm by reading the surrounding lines).

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/unit/test_dust_profile_feed.py -v` and `uv run pytest tests -q -k "environment_feeds or dust"`
Expected: PASS. If a test double for `r` lacks `set_dust_profile`, add it to that double (doubles must mirror the real surface).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h native/src/renderer/dust_pass.cc native/src/host/host_bindings.cc native/tests/renderer/dust_pass_test.cc engine/host_loop.py tests/unit/test_dust_profile_feed.py
git commit -m "feat(dust): radial-profile dust column lifts dust density"
```

---

### Task 12: System descriptions — ⛔ STOP for Mark's wording

**Files:**
- Modify: `engine/systems/descriptions.json` (Belaruz and Vesuvi `detail`)
- Modify: `tests/unit/test_system_maps_valid.py` (the Belaruz description test and the `"stretches out ahead of it"` assertion near line 240)

- [ ] **Step 1: Present these drafts to Mark and STOP until he approves or edits them.** Report DONE_WITH_CONCERNS / NEEDS_CONTEXT with the drafts; do not write them unapproved.

  **Belaruz `detail` (draft):** "Not a casualty. Belaruz sits inside a body of interstellar dust and gas, and the star is brighter for it -- feeding on the infalling material. The cloud surrounds the whole system: it is thickest in a shell just beyond Belaruz 1, closer to the star than any of the three planets, and thins to a haze everywhere else. Cold material, unlike Vesuvi's. It will blind your sensors but it will not burn you."

  **Vesuvi `detail` — last sentence only (draft):** replace "The dust is hazardous to shields and hull; route around it or accept the damage." with "The inner system is still hot: radiation drains shields and knocks systems offline anywhere inside the debris, worst at its heart. Raise shields and keep moving."

- [ ] **Step 2: After approval, write the approved text** into `descriptions.json`, and pin it: replace the Belaruz description test's text assertions with the approved sentence's facts —

```python
    detail = for_system("Belaruz").detail          # use the file's existing accessor
    assert "ahead" not in detail
    assert "just beyond Belaruz 1" in detail        # adjust to the approved wording
    from engine.systems.profile import clump_radius, evaluate
    R = clump_radius(m.region("Belaruz1"), star.position_gu)
    assert evaluate(m.profile, R).radiation == 0.0   # "will not burn you"
```

and delete the `"stretches out ahead of it"` assertion.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit/test_system_maps_valid.py -v -k "description or belaruz or vesuvi"`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add engine/systems/descriptions.json tests/unit/test_system_maps_valid.py
git commit -m "docs(systems): Belaruz and Vesuvi descriptions match the radial profile"
```

---

### Task 13: System-scale nebula spike (developer-only) — ⛔ STOP for Mark's live check

The cheapest honest look: feed the **existing** volumetric/faithful nebula pass one synthetic volume around the player, scaled by the `nebula` column, in the system's cloud colour. No new GL. Gated behind `--developer`, so production rendering is byte-identical until Mark approves.

**Files:**
- Create: `engine/systems/profile_render.py`
- Modify: `engine/host_loop.py` (`_push_environment_feeds` appends the synthetic volume under `dev_mode.is_enabled()`)
- Test: `tests/unit/test_profile_render.py`

**Interfaces:**
- Consumes: `profile.locate`, `profile.evaluate`, the `_aggregate_nebulae` descriptor dict shape (`spheres`, `rgb`, `visibility`, `external_tex`, `internal_tex`, `fbm`, `seed`).
- Produces: `profile_render.synthetic_volume(player) -> dict | None`, `SPIKE_RADIUS_GU = 3000.0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_profile_render.py
import pytest

from engine.systems import profile as P
from engine.systems import profile_render as PR


class _Loc:
    x, y, z = 10.0, 20.0, 30.0


class _Player:
    def GetWorldLocation(self):
        return _Loc()


def _prof(neb, color=(0.6, 0.35, 0.72)):
    return P.Profile(rows=[P.ProfileRow(0.0, nebula=neb)], color=color)


def test_no_volume_in_clear_space_or_without_a_colour(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.0), 5.0))
    assert PR.synthetic_volume(_Player()) is None
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.5, color=None), 5.0))
    assert PR.synthetic_volume(_Player()) is None
    monkeypatch.setattr(P, "locate", lambda obj: None)
    assert PR.synthetic_volume(_Player()) is None


def test_volume_is_centred_on_the_player_in_the_cloud_colour(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(1.0), 5.0))
    v = PR.synthetic_volume(_Player())
    assert v["spheres"] == [(10.0, 20.0, 30.0, PR.SPIKE_RADIUS_GU)]
    assert v["rgb"] == (0.6, 0.35, 0.72)
    assert v["visibility"] == pytest.approx(145.0)


def test_thinner_nebula_sees_further_and_is_sparser(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(1.0), 5.0))
    thick = PR.synthetic_volume(_Player())
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.2), 5.0))
    thin = PR.synthetic_volume(_Player())
    assert thin["visibility"] > thick["visibility"]
    assert thin["fbm"][2] > thick["fbm"][2]          # higher floor = sparser
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_profile_render.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `engine/systems/profile_render.py`**

```python
"""SPIKE (developer-only): the radial profile's `nebula` column drawn by the
existing nebula passes as one synthetic volume around the player.

Throwaway until Mark approves the look live (plan Task 13). Visibility uses
the spec's fit (a + b / i); sparseness raises the fbm floor as i falls.
"""
from __future__ import annotations

from engine.appc.nebula import MetaNebula
from engine.appc.nebula_density import seed_for

SPIKE_RADIUS_GU = 3000.0
VIS_A, VIS_B = 55.625, 89.375
MIN_NEBULA = 0.01


def synthetic_volume(player):
    from engine.systems import profile as _profile
    found = _profile.locate(player)
    if found is None or found[0] is None or found[0].color is None:
        return None
    prof, r = found
    i = _profile.evaluate(prof, r).nebula
    if i < MIN_NEBULA:
        return None
    loc = player.GetWorldLocation()
    freq, gain, floor = MetaNebula().GetFbmDials()
    return {
        "spheres": [(loc.x, loc.y, loc.z, SPIKE_RADIUS_GU)],
        "rgb": tuple(prof.color),
        "visibility": VIS_A + VIS_B / i,
        "external_tex": "",
        "internal_tex": "",
        "fbm": (freq, gain, floor + (1.0 - i) * 0.6),
        "seed": seed_for(0.0, 0.0, 0.0),
    }
```

- [ ] **Step 4: Wire it (developer-only)** in `_push_environment_feeds`, where the nebula descriptors from `_aggregate_nebulae(active_set)` are pushed: read the lines first, then append — **after** the set's own volumes, so a local MetaNebula stays `volumes[0]` and keeps its dials in the volumetric pass:

```python
    from engine import dev_mode
    if dev_mode.is_enabled() and player is not None:
        from engine.systems.profile_render import synthetic_volume
        extra = synthetic_volume(player)
        if extra is not None:
            nebulae = nebulae + [extra]     # use the local variable name the function already has
```

(Positions must go through the same render-space conversion the function applies to the other nebula descriptors; apply it to `extra` identically.)

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_profile_render.py -v` and `uv run pytest tests -q -k "environment_feeds or nebula"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/systems/profile_render.py engine/host_loop.py tests/unit/test_profile_render.py
git commit -m "spike(nebula): developer-only system-scale nebula from the radial profile"
```

- [ ] **Step 7: ⛔ STOP.** Ask Mark to run `./build/dauntless --developer` from the main checkout on this branch and fly Vesuvi (E3M2) and Belaruz, reporting: does it read as being inside a nebula; does the edge of the 3,000 GU sphere show; cost via the `` ` `` frame profiler (CPU only — GPU timing is dead on this Mac). Do not proceed or tune without his verdict. If the look needs real design work, the plan ends here and the spike stays developer-only.

---

### Task 14: Reference row and gate

**Files:**
- Modify: `CLAUDE.md` (Key reference material table — one row)

- [ ] **Step 1:** Add a row after "Game-unit conversion":

```markdown
| Radial system profile | `engine/systems/profile.py`, `tools/systems/profile_builder.py`, `engine/appc/radiation.py`, `docs/superpowers/specs/2026-09-23-radial-system-profile-design.md` | Space as a per-system table keyed by distance from the star: `nebula`, `dust`, `sensors`, `radiation`, `asteroids` (0-1, linear between rows, last row persists outward). Replaced the placed `Cloud`/`Volume` model. ⚠️ **Radiation is a deliberate departure from BC** (BC's nebula hits once, at creation — bible §15 E1): 16 Hz `ET_ENVIRONMENT_DAMAGE` carries 1/16 s of drain + an outage roll, and a handler that stops the chain cancels it, as in BC. Every star radiates within 3 radii. Vesuvi's table is a hand `overrides.profile` in absolute GU — `profile-override-tracks-clump` fails generation if the layout moves the cloud. `asteroids` is data only, pending a modern-asteroids design. |
```

- [ ] **Step 2: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression from this branch — fix it before proceeding. Never call a failure "pre-existing" by eye.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md reference row for the radial system profile"
```

- [ ] **Step 4:** Report to Mark: branch `feat/radial-system-profile` ready for his live check (E3M2 radiation/outages, Vesuvi/Belaruz dust, the nebula spike). **Do not merge; do not push.**
