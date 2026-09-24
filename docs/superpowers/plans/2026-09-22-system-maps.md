# System Maps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a validated, checked-in system-map data file per BC star system
— bodies on orbits around one sun, regions anchored to match the original
artist's framing — starting with Ona for human review.

**Architecture:** Three separable pieces. `engine/systems/` owns the *format* (a
dataclass model + JSON I/O) and the *validator*, because the runtime reads them.
`tools/systems/` owns the *survey* (read the SDK, measure what is there) and the
*layout* (decide where bodies and anchors go), because only the generator needs
them. `tools/gen_system_maps.py` is the CLI that joins them. Generated content
and hand overrides live in separate blocks of the same file so regeneration never
clobbers art direction.

**Tech Stack:** Python 3.11, stdlib `json` and `dataclasses`, pytest. No new
dependencies. No C++ in this plan.

**Spec:** [`docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`](../specs/2026-09-22-in-system-navigation-design.md)
— read §1 (the system map), §2 (bodies stay in their sets) and the "What exists
today" section before starting. This plan implements §1 only.

**Scope:** This plan stops at "Ona is generated and looks right". The runtime —
hand-off, streamer, celestial layer, dash, flash, dev mission (spec §3–§6) — is a
second plan, deliberately not written yet: the Ona review is a checkpoint that
can change the layout rules, and planning past it is speculative.

## Global Constraints

- **Units are BC game units (GU) everywhere.** 1 GU = 175 m. Never name a
  variable `*_m` or `*_km`. (`engine/units.py`)
- **Never spell `game` or `sdk` as a path segment** in `engine/` or `tools/`.
  Ask `paths.sdk_scripts()`. Enforced by `tests/unit/test_path_indirection.py`,
  which parses rather than greps. A string that *describes* the layout rather
  than building a path is exempted in place with a `# paths-guard: <reason>`
  comment.
- **Never capture a path at import time** in `engine/`. No module-level constant
  may hold one. Compute inside the function. The one permitted idiom for
  package-local data is `Path(__file__).parent / ...` *inside a function* — the
  precedent is `engine/appc/sector_model.py:12`.
- **Shared checkout:** stage with an explicit pathspec. Never `git add -A`,
  `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, or
  `git reset --hard`.
- **Run the gate, don't eyeball:** `scripts/check_tests.sh`. The ledger
  (`tests/known_failures.txt`) holds exactly one pytest entry and zero ctest
  entries. Nothing in this plan may be added to it.
- **Test command in this worktree:** `uv run pytest <path> -v`. A bare `pytest`
  picks up the main checkout's venv from PATH and can segfault against
  worktree-built native modules.

---

### Task 1: The system-map format

**Files:**
- Create: `engine/systems/__init__.py`
- Create: `engine/systems/map.py`
- Test: `tests/unit/test_system_map.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Appearance(kind: str, model: str = "")` — `kind` is `"nif"` today.
  - `Body(name: str, display_name: str, radius_gu: float, position_gu: tuple[float, float, float], orbits: str | None, appearance: Appearance, owner_region: str | None)`
  - `Region(set_name: str, anchor_gu: tuple[float, float, float], radius_gu: float, body_names: list[str])`
  - `SystemMap(system: str, bodies: list[Body], regions: list[Region], overrides: dict, generated: dict)`
  - `SystemMap.body(name) -> Body | None`
  - `SystemMap.region(set_name) -> Region | None`
  - `to_json(m: SystemMap) -> str`
  - `from_json(text: str) -> SystemMap`
  - `map_dir() -> Path` — `Path(__file__).parent / "maps"`, computed per call.
  - `load(system: str) -> SystemMap` — reads `map_dir() / f"{system.lower()}.json"`.
  - `save(m: SystemMap) -> Path` — writes it, returns the path.
  - `available() -> list[str]` — system names with a checked-in map, sorted.

**Why the appearance split:** the spec requires body *identity* (name, radius,
position, orbit) to be separable from *how it looks*, so procedurally generated
planets can replace NIFs later without touching the map format.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_system_map.py`:

```python
"""The system-map format: dataclasses, JSON round-trip, package-local location.

Body identity (name/radius/position/orbit) is deliberately separate from
Appearance so a future procedural planet is a different appearance on the same
body -- see the design doc, section 1.
"""
from pathlib import Path

from engine.systems.map import (
    Appearance, Body, Region, SystemMap, available, from_json, map_dir, to_json,
)


def _ona() -> SystemMap:
    return SystemMap(
        system="Ona",
        bodies=[
            Body(
                name="Ona 1",
                display_name="Ona 1",
                radius_gu=1800.0,
                position_gu=(0.0, 24000.0, 0.0),
                orbits="Ona",
                appearance=Appearance(kind="nif",
                                      model="data/models/environment/RedPlanet.nif"),
                owner_region="Ona1",
            ),
        ],
        regions=[
            Region(set_name="Ona1", anchor_gu=(0.0, 20000.0, 0.0),
                   radius_gu=6000.0, body_names=["Ona 1"]),
        ],
        overrides={},
        generated={"tool": "gen_system_maps"},
    )


def test_round_trip_preserves_every_field():
    m = _ona()
    back = from_json(to_json(m))
    assert back == m


def test_lookup_helpers():
    m = _ona()
    assert m.body("Ona 1").radius_gu == 1800.0
    assert m.body("nope") is None
    assert m.region("Ona1").body_names == ["Ona 1"]
    assert m.region("nope") is None


def test_appearance_is_separable_from_identity():
    m = _ona()
    body = m.body("Ona 1")
    swapped = from_json(to_json(m)).body("Ona 1")
    swapped.appearance = Appearance(kind="procedural", model="")
    # Identity is untouched by an appearance swap.
    assert (swapped.name, swapped.radius_gu, swapped.position_gu, swapped.orbits) == \
           (body.name, body.radius_gu, body.position_gu, body.orbits)


def test_map_dir_is_package_local_and_computed_per_call():
    d = map_dir()
    assert d.name == "maps"
    assert d.parent.name == "systems"
    # Computed fresh, not a module constant -- same value, distinct objects.
    assert map_dir() == d


def test_available_returns_sorted_system_names():
    names = available()
    assert names == sorted(names)
    assert all(isinstance(n, str) for n in names)


def test_json_is_stable_and_human_diffable():
    text = to_json(_ona())
    assert text.endswith("\n")
    assert '"system": "Ona"' in text
    # Two dumps of equal maps are byte-identical, so regeneration diffs cleanly.
    assert to_json(_ona()) == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_system_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.systems'`

- [ ] **Step 3: Write minimal implementation**

Create `engine/systems/__init__.py`:

```python
"""Star-system maps: one solar system per star, with BC's original sets placed
in it as regions. See docs/superpowers/specs/2026-09-22-in-system-navigation-design.md.
"""
```

Create `engine/systems/map.py`:

```python
"""The system-map data format and its JSON I/O.

A map describes ONE star system: its bodies (sun, planets, moons) at positions
in system coordinates, and its regions -- the original BC sets -- each anchored
at a position in that same space.

Body IDENTITY (name, radius, position, what it orbits) is deliberately held
apart from APPEARANCE. Today every appearance is a BC NIF; a procedurally
generated body later is a different Appearance on an unchanged Body, so nothing
but the renderer and one field has to move.

Files live beside this module in maps/, like engine/appc/sector_model.json.
The directory is computed per call, never captured at import: engine/paths.py
is re-configurable at runtime and module-level path constants go stale.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Appearance:
    kind: str = "nif"
    model: str = ""


@dataclass
class Body:
    name: str
    display_name: str
    radius_gu: float
    position_gu: tuple
    orbits: str | None = None
    appearance: Appearance = field(default_factory=Appearance)
    owner_region: str | None = None


@dataclass
class Region:
    set_name: str
    anchor_gu: tuple
    radius_gu: float
    body_names: list = field(default_factory=list)


@dataclass
class SystemMap:
    system: str
    bodies: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)
    generated: dict = field(default_factory=dict)

    def body(self, name: str):
        for b in self.bodies:
            if b.name == name:
                return b
        return None

    def region(self, set_name: str):
        for r in self.regions:
            if r.set_name == set_name:
                return r
        return None


def to_json(m: SystemMap) -> str:
    return json.dumps(asdict(m), indent=2, sort_keys=False) + "\n"


def from_json(text: str) -> SystemMap:
    raw = json.loads(text)
    bodies = [
        Body(
            name=b["name"],
            display_name=b["display_name"],
            radius_gu=float(b["radius_gu"]),
            position_gu=tuple(b["position_gu"]),
            orbits=b.get("orbits"),
            appearance=Appearance(**b.get("appearance", {})),
            owner_region=b.get("owner_region"),
        )
        for b in raw.get("bodies", [])
    ]
    regions = [
        Region(
            set_name=r["set_name"],
            anchor_gu=tuple(r["anchor_gu"]),
            radius_gu=float(r["radius_gu"]),
            body_names=list(r.get("body_names", [])),
        )
        for r in raw.get("regions", [])
    ]
    return SystemMap(
        system=raw["system"],
        bodies=bodies,
        regions=regions,
        overrides=raw.get("overrides", {}),
        generated=raw.get("generated", {}),
    )


def map_dir() -> Path:
    """Where checked-in system maps live. Computed per call, never cached."""
    return Path(__file__).parent / "maps"


def load(system: str) -> SystemMap:
    path = map_dir() / f"{system.lower()}.json"
    return from_json(path.read_text(encoding="utf-8"))


def save(m: SystemMap) -> Path:
    d = map_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{m.system.lower()}.json"
    path.write_text(to_json(m), encoding="utf-8")
    return path


def available() -> list:
    d = map_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
```

Note `asdict` turns the `position_gu` tuple into a list; `from_json` turns it
back. That is why the round-trip test compares reconstructed maps rather than
raw JSON structures.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_system_map.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Confirm the path guard still passes**

Run: `uv run pytest tests/unit/test_path_indirection.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add engine/systems/__init__.py engine/systems/map.py tests/unit/test_system_map.py
git commit -m "feat(systems): the system-map format, with appearance split from identity"
```

---

### Task 2: The map validator

**Files:**
- Create: `engine/systems/validate.py`
- Test: `tests/unit/test_system_map_validate.py`

**Interfaces:**
- Consumes: `engine.systems.map.{SystemMap, Body, Region, Appearance, available, load}`
- Produces:
  - `Problem(rule: str, detail: str)` — dataclass, `rule` is a short slug.
  - `validate(m: SystemMap, *, sdk_set_names: list[str] | None = None, pins: dict | None = None) -> list[Problem]` — empty list means valid.

**The rules**, each named by its slug:

| slug | rule |
|---|---|
| `region-coverage` | Every set name in `sdk_set_names` has a region. Skipped when `sdk_set_names` is None. |
| `region-overlap` | No region's sphere (anchor, radius) contains another region's anchor. |
| `body-owner` | Every `Region.body_names` entry names a real body whose `owner_region` points back at that region. |
| `body-engulfs-anchor` | No body's radius reaches its own region's anchor — you must not spawn inside a planet. |
| `pin-respected` | For each pinned body, `position_gu - anchor_gu` equals the pin's original set-local offset within 1 GU. Keys are `"Region/Body"` — see Task 6. Skipped when `pins` is None. |
| `orbit-target` | Every non-None `orbits` names a body in this map. |

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_system_map_validate.py`:

```python
"""Validator rules for a system map.

These are the failures that would otherwise surface as a broken mission weeks
later: a BC set with nowhere to live, two regions sitting inside each other, a
mission's staging waypoints no longer beside the body they were authored
against, or a spawn point inside a planet.
"""
import pytest

from engine.systems.map import Appearance, Body, Region, SystemMap
from engine.systems.validate import validate


def _body(name, pos, radius=100.0, owner="Ona1", orbits="Ona"):
    return Body(name=name, display_name=name, radius_gu=radius, position_gu=pos,
                orbits=orbits, appearance=Appearance(), owner_region=owner)


def _valid() -> SystemMap:
    return SystemMap(
        system="Ona",
        bodies=[
            Body(name="Ona", display_name="Ona", radius_gu=5000.0,
                 position_gu=(0.0, 0.0, 0.0), orbits=None,
                 appearance=Appearance(), owner_region=None),
            _body("Ona 1", (0.0, 22000.0, 0.0), radius=1800.0, owner="Ona1"),
            _body("Ona 2", (0.0, 60000.0, 0.0), radius=1800.0, owner="Ona2"),
        ],
        regions=[
            Region("Ona1", (0.0, 18000.0, 0.0), 3000.0, ["Ona 1"]),
            Region("Ona2", (0.0, 56000.0, 0.0), 3000.0, ["Ona 2"]),
        ],
    )


def _slugs(problems):
    return sorted(p.rule for p in problems)


def test_a_valid_map_has_no_problems():
    assert validate(_valid()) == []


def test_region_coverage_flags_a_set_with_no_region():
    m = _valid()
    assert _slugs(validate(m, sdk_set_names=["Ona1", "Ona2", "Ona3"])) == ["region-coverage"]


def test_region_coverage_is_skipped_without_sdk_names():
    assert validate(_valid(), sdk_set_names=None) == []


def test_region_overlap_flags_a_neighbour_anchor_inside_a_radius():
    m = _valid()
    # Ona2's anchor is 38000 GU away; widen Ona1 past it.
    m.regions[0].radius_gu = 40000.0
    assert "region-overlap" in _slugs(validate(m))


def test_body_owner_flags_a_dangling_name():
    m = _valid()
    m.regions[0].body_names = ["Ona 9"]
    assert "body-owner" in _slugs(validate(m))


def test_body_owner_flags_a_back_reference_mismatch():
    m = _valid()
    m.body("Ona 1").owner_region = "Ona2"
    assert "body-owner" in _slugs(validate(m))


def test_body_engulfs_anchor_flags_a_planet_swallowing_its_own_spawn():
    m = _valid()
    # Ona 1 sits 4000 GU from its anchor; a 5000 GU radius swallows it.
    m.body("Ona 1").radius_gu = 5000.0
    assert "body-engulfs-anchor" in _slugs(validate(m))


def test_a_bad_back_reference_does_not_mask_an_engulfed_anchor():
    """Two independent faults on one body must both be reported. A bookkeeping
    error about which region owns a body must never hide "you would spawn
    inside this planet" -- that is the hazard the validator exists for."""
    m = _valid()
    m.body("Ona 1").owner_region = "Ona2"      # back-reference mismatch
    m.body("Ona 1").radius_gu = 5000.0          # engulfs Ona1's anchor
    assert _slugs(validate(m)) == ["body-engulfs-anchor", "body-owner"]


def test_pin_respected_accepts_the_authored_offset():
    m = _valid()
    pins = {"Ona 1": (0.0, 4000.0, 0.0)}   # matches 22000 - 18000
    assert validate(m, pins=pins) == []


def test_pin_respected_flags_a_moved_body():
    m = _valid()
    pins = {"Ona 1": (0.0, 500.0, 0.0)}
    assert "pin-respected" in _slugs(validate(m, pins=pins))


def test_orbit_target_flags_an_unknown_parent():
    m = _valid()
    m.body("Ona 1").orbits = "Nowhere"
    assert "orbit-target" in _slugs(validate(m))


def test_problems_carry_a_readable_detail():
    m = _valid()
    m.body("Ona 1").orbits = "Nowhere"
    problem = [p for p in validate(m) if p.rule == "orbit-target"][0]
    assert "Ona 1" in problem.detail and "Nowhere" in problem.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_system_map_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.systems.validate'`

- [ ] **Step 3: Write minimal implementation**

Create `engine/systems/validate.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_system_map_validate.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/systems/validate.py tests/unit/test_system_map_validate.py
git commit -m "feat(systems): map validator — coverage, overlap, ownership, pins, orbits"
```

---

### Task 3: The SDK survey

**Files:**
- Create: `tools/systems/__init__.py`
- Create: `tools/systems/survey.py`
- Test: `tests/tools/test_system_survey.py`

**Interfaces:**
- Consumes: `engine.paths.sdk_scripts()`
- Produces:
  - `SurveyedBody(name: str, radius_gu: float, model: str, offset_gu: tuple, is_sun: bool)` — `offset_gu` is the body's position in the ORIGINAL set, i.e. its offset from that set's `Player Start`.
  - `SurveyedRegion(set_name: str, ordinal: int | None, bodies: list[SurveyedBody], content_extent_gu: float, player_start_gu: tuple)`
  - `SurveyedSystem(name: str, regions: list[SurveyedRegion], pins: dict)`
  - `survey_system(system: str) -> SurveyedSystem`
  - `survey_all() -> list[SurveyedSystem]`
  - `system_names() -> list[str]` — directory names under `Systems/` that define a `CreateSystemMenu`.

**How it works.** This reads Python 1.5 source as TEXT, never imports it. The
SDK's placement files are flat generated code — a `*_Create("Name", sSetName,
...)` line followed by a `SetTranslateXYZ(...)` line — which is why a line
scanner is sufficient and an AST parse is not needed.

Per region:
1. Parse `<Sys>N.py` for placements: name → xyz.
2. Parse `<Sys>N_S.py` for `App.Planet_Create(radius, model)` /
   `App.Sun_Create(...)`, each followed by `AddObjectToSet(var, "Display Name")`
   and `var.PlaceObjectByName("Waypoint")`. Resolve the waypoint through step 1.
   **Do not look bodies up by waypoint name** — the spec records four spellings
   for "the planet" and six for "moon".
3. `content_extent_gu` = the largest distance from the origin of any placement
   that is *not* a body's placement and not `Sun`, across `<Sys>N.py` and every
   mission `*_P.py` that loads placements into this set.
4. `ordinal` = the trailing integer of the set name, else None.

Pins are surveyed but left for the layout task to interpret.

- [ ] **Step 1: Write the failing test**

Create `tests/tools/test_system_survey.py`:

```python
"""The survey reads the real SDK. Ona is the reference case: three numbered
regions, one planet each, no moons, no pins.

Values here are read out of sdk/.../Systems/Ona/ -- if the SDK changes, these
change with it, which is the point: the survey must track the source of truth,
not a snapshot of it.
"""
import pytest

from tools.systems.survey import survey_system, system_names


def test_ona_has_three_numbered_regions():
    ona = survey_system("Ona")
    assert [r.set_name for r in ona.regions] == ["Ona1", "Ona2", "Ona3"]
    assert [r.ordinal for r in ona.regions] == [1, 2, 3]


def test_ona_regions_each_hold_one_planet_and_one_sun():
    ona = survey_system("Ona")
    for r in ona.regions:
        planets = [b for b in r.bodies if not b.is_sun]
        suns = [b for b in r.bodies if b.is_sun]
        assert len(planets) == 1, r.set_name
        assert len(suns) == 1, r.set_name


def test_ona1_planet_is_read_with_its_authored_offset_and_model():
    ona = survey_system("Ona")
    r = [x for x in ona.regions if x.set_name == "Ona1"][0]
    planet = [b for b in r.bodies if not b.is_sun][0]
    assert planet.name == "Ona 1"
    assert planet.radius_gu == pytest.approx(90.0)
    assert planet.model == "data/models/environment/RedPlanet.nif"
    assert planet.offset_gu == pytest.approx((-97.183075, 591.702881, -7.431804))


def test_each_ona_region_uses_a_different_planet_model():
    ona = survey_system("Ona")
    models = sorted(b.model for r in ona.regions for b in r.bodies if not b.is_sun)
    assert models == [
        "data/models/environment/RedPlanet.nif",
        "data/models/environment/SulfurPlanet.nif",
        "data/models/environment/TanGasPlanet.nif",
    ]


def test_ona_player_starts_are_at_the_set_origin():
    ona = survey_system("Ona")
    for r in ona.regions:
        assert r.player_start_gu == pytest.approx((0.0, 0.0, 0.0)), r.set_name


def test_content_extent_excludes_bodies_and_includes_mission_placements():
    ona = survey_system("Ona")
    by_name = {r.set_name: r for r in ona.regions}
    # Ona1 and Ona2 have nothing but Player Start at the origin.
    assert by_name["Ona1"].content_extent_gu == pytest.approx(0.0, abs=1.0)
    # Ona3 is staged by E6M1_Ona3_P (Keldon starts ~300 GU out); the 515 GU
    # planet and the 70000 GU sun must NOT count.
    assert 250.0 < by_name["Ona3"].content_extent_gu < 600.0


def test_system_names_covers_the_campaign_and_excludes_utils():
    names = system_names()
    assert "Ona" in names and "Vesuvi" in names and "Alioth" in names
    assert "Utils" not in names
    assert names == sorted(names)


def test_regions_without_bodies_survey_cleanly():
    """Two shapes must not raise: Vesuvi1 has no _S file at all, and Vesuvi4's
    _S file builds a MetaNebula and no Planet or Sun."""
    vesuvi = survey_system("Vesuvi")
    names = {r.set_name for r in vesuvi.regions}
    assert {"Vesuvi1", "Vesuvi4"} <= names
    for set_name in ("Vesuvi1", "Vesuvi4"):
        region = [r for r in vesuvi.regions if r.set_name == set_name][0]
        assert region.bodies == [], set_name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_system_survey.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.systems'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/systems/__init__.py`:

```python
"""Generator-side helpers for system maps: reading the SDK (survey) and
deciding where bodies and anchors go (layout). Not imported by the engine.
"""
```

Create `tools/systems/survey.py`:

```python
"""Read BC's Systems/ tree and report what each region actually contains.

Reads Python 1.5 source as TEXT and never imports it. The SDK's placement
files are flat generated code -- a `*_Create("Name", sSetName, ...)` line
followed by a `SetTranslateXYZ(...)` line -- so a line scanner is sufficient
and correct. (tools/probes/ aside, modern `ast` cannot parse 1.5 sources
anyway.)

Two things this deliberately does NOT do:

* It never looks a body up by waypoint name. The design doc records four
  spellings for "the planet" (`Planet Location` x52, `Planet` x20, `Planet1`
  x13, `Planet Placement`) plus `Colony` and two named after the set itself,
  and six for moons. The only reliable route is Planet_Create -> the variable
  -> its AddObjectToSet display name and PlaceObjectByName waypoint.
* It never decides layout. Where a body ENDS UP is tools/systems/layout.py's
  job; this module only reports where BC put it.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine import paths

_CREATE_PLACEMENT = re.compile(r'App\.(\w+)_Create\("([^"]+)",\s*("([^"]+)"|\w+)')
_TRANSLATE = re.compile(r'SetTranslateXYZ\(([^)]*)\)')
_BODY_CREATE = re.compile(r'(\w+)\s*=\s*App\.(Planet|Sun)_Create\((.*)\)\s*$')
_LOAD_PLACEMENTS_DEFAULT = re.compile(r'def LoadPlacements\(\s*sSetName\s*=\s*"([^"]+)"')
_TRAILING_INT = re.compile(r'(\d+)$')


@dataclass
class SurveyedBody:
    name: str
    radius_gu: float
    model: str
    offset_gu: tuple
    is_sun: bool


@dataclass
class SurveyedRegion:
    set_name: str
    ordinal: int | None
    bodies: list = field(default_factory=list)
    content_extent_gu: float = 0.0
    player_start_gu: tuple = (0.0, 0.0, 0.0)


@dataclass
class SurveyedSystem:
    name: str
    regions: list = field(default_factory=list)
    pins: dict = field(default_factory=dict)


def _systems_dir() -> Path:
    return paths.sdk_scripts() / "Systems"


def _missions_dir() -> Path:
    return paths.sdk_scripts() / "Maelstrom"


def _read(path: Path) -> str:
    return path.read_text(encoding="latin-1")


def _uncommented(text: str):
    for line in text.splitlines():
        if not line.lstrip().startswith("#"):
            yield line


def _xyz(raw: str):
    try:
        parts = [float(v) for v in raw.split(",")]
    except ValueError:
        return None
    return tuple(parts) if len(parts) == 3 else None


def _placements(text: str) -> dict:
    """name -> xyz for every placement created in this file."""
    out, pending = {}, None
    for line in _uncommented(text):
        m = _CREATE_PLACEMENT.search(line)
        if m:
            pending = m.group(2)
            continue
        m = _TRANSLATE.search(line)
        if m and pending is not None:
            xyz = _xyz(m.group(1))
            if xyz is not None:
                out[pending] = xyz
            pending = None
    return out


def _bodies(static_text: str, placements: dict) -> tuple:
    """(bodies, waypoint names consumed by bodies)."""
    bodies, used = [], set()
    lines = list(_uncommented(static_text))
    for i, line in enumerate(lines):
        m = _BODY_CREATE.search(line)
        if not m:
            continue
        var, kind, args = m.group(1), m.group(2), m.group(3)
        try:
            radius = float(args.split(",")[0])
        except ValueError:
            radius = 0.0
        model = ""
        model_match = re.search(r'"([^"]*\.nif)"', args)
        if model_match:
            model = model_match.group(1)
        display, waypoint = None, None
        for later in lines[i + 1:]:
            if display is None:
                m2 = re.search(r'AddObjectToSet\(\s*%s\s*,\s*"([^"]+)"' % re.escape(var), later)
                if m2:
                    display = m2.group(1)
            if waypoint is None:
                m2 = re.search(r'%s\.PlaceObjectByName\(\s*"([^"]+)"' % re.escape(var), later)
                if m2:
                    waypoint = m2.group(1)
            if display is not None and waypoint is not None:
                break
        if display is None:
            continue
        offset = placements.get(waypoint, (0.0, 0.0, 0.0)) if waypoint else (0.0, 0.0, 0.0)
        if waypoint:
            used.add(waypoint)
        bodies.append(SurveyedBody(name=display, radius_gu=radius, model=model,
                                   offset_gu=offset, is_sun=(kind == "Sun")))
    return bodies, used


def _mission_extent(set_name: str) -> float:
    """Largest distance from the origin of any placement a mission puts in this set."""
    best = 0.0
    root = _missions_dir()
    if not root.is_dir():
        return best
    for path in root.rglob("*.py"):
        text = _read(path)
        if set_name not in text:
            continue
        default = None
        m = _LOAD_PLACEMENTS_DEFAULT.search(text)
        if m:
            default = m.group(1)
        # A module is "about" this set if it names it literally, or if its own
        # filename does and its placements take sSetName.
        filename_hint = ("_%s_" % set_name) in path.name or path.stem == f"{set_name}_P"
        pending = None
        for line in _uncommented(text):
            m = _CREATE_PLACEMENT.search(line)
            if m:
                literal = m.group(4)
                target = literal if literal else (default or (set_name if filename_hint else None))
                pending = target
                continue
            m = _TRANSLATE.search(line)
            if m and pending is not None:
                if pending == set_name:
                    xyz = _xyz(m.group(1))
                    if xyz is not None:
                        best = max(best, math.sqrt(sum(c * c for c in xyz)))
                pending = None
    return best


def system_names() -> list:
    out = []
    root = _systems_dir()
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        head = d / f"{d.name}.py"
        if head.is_file() and "CreateSystemMenu" in _read(head):
            out.append(d.name)
    return sorted(out)


def survey_system(system: str) -> SurveyedSystem:
    d = _systems_dir() / system
    result = SurveyedSystem(name=system)
    for path in sorted(d.glob("*.py")):
        stem = path.stem
        if stem in ("__init__", system) or stem.endswith("_S"):
            continue
        text = _read(path)
        placements = _placements(text)
        static = d / f"{stem}_S.py"
        bodies, used = ([], set())
        if static.is_file():
            bodies, used = _bodies(_read(static), placements)
        skip = used | {"Sun"}
        extent = 0.0
        for name, xyz in placements.items():
            if name in skip:
                continue
            extent = max(extent, math.sqrt(sum(c * c for c in xyz)))
        extent = max(extent, _mission_extent(stem))
        ordinal_match = _TRAILING_INT.search(stem)
        result.regions.append(SurveyedRegion(
            set_name=stem,
            ordinal=int(ordinal_match.group(1)) if ordinal_match else None,
            bodies=bodies,
            content_extent_gu=extent,
            player_start_gu=placements.get("Player Start", (0.0, 0.0, 0.0)),
        ))
    result.regions.sort(key=lambda r: (r.ordinal is None, r.ordinal or 0, r.set_name))
    return result


def survey_all() -> list:
    return [survey_system(n) for n in system_names()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_system_survey.py -v`
Expected: PASS (8 tests)

If `test_content_extent_excludes_bodies_and_includes_mission_placements` fails
on Ona3, print `_mission_extent("Ona3")` — the expected contributor is
`Maelstrom/Episode6/E6M1/E6M1_Ona3_P.py`, whose farthest waypoint is
`Keldon2Start` at `(-281.445221, 154.570984, 26.904606)` ≈ 322 GU.

- [ ] **Step 5: Confirm the path guard still passes**

`survey.py` asks `paths.sdk_scripts()` and never spells the segment itself.

Run: `uv run pytest tests/unit/test_path_indirection.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/systems/__init__.py tools/systems/survey.py tests/tools/test_system_survey.py
git commit -m "feat(systems): survey BC's Systems tree — bodies, extents, ordinals"
```

---

### Task 4: Layout — orbits and anchors

**Files:**
- Create: `tools/systems/layout.py`
- Test: `tests/tools/test_system_layout.py`

**Interfaces:**
- Consumes: `tools.systems.survey.{SurveyedSystem, SurveyedRegion, SurveyedBody}`, `engine.systems.map.{SystemMap, Body, Region, Appearance}`
- Produces:
  - `LayoutTuning` dataclass with defaults:
    `planet_radius_gu = 1800.0`, `moon_radius_gu = 600.0`, `sun_radius_gu = 9000.0`,
    `first_orbit_gu = 30000.0`, `orbit_step_gu = 26000.0`,
    `anchor_standoff_factor = 2.2` (standoff = factor × primary radius),
    `region_margin_gu = 1500.0`,
    `moon_first_orbit_factor = 4.0`, `moon_orbit_step_factor = 1.5`
    (a moon sits at `primary_radius × (first + step × index)`)
  - `layout(s: SurveyedSystem, tuning: LayoutTuning | None = None) -> SystemMap`
  - `ambiguities(s: SurveyedSystem) -> list[str]` — human-readable notes about
    guesses made (unnumbered regions, companion bodies assumed to be moons).

**The rules, from spec §1:**

- **Sun** at the origin, named for the system, `orbits=None`, `owner_region=None`.
- **Orbit order** from `SurveyedRegion.ordinal`; unnumbered regions go after the
  numbered ones in survey order, and are reported by `ambiguities()`.
- **Orbit radius** `first_orbit_gu + orbit_step_gu * i` for the i-th region,
  placed on the +Y axis rotated by a per-region angle so regions are spread
  rather than collinear: angle = `i * 2.399963` rad (the golden angle) about +Z.
- **Which body is the planet:** the largest non-sun body in the region. The rest
  become moons of it, on small circular offsets. `ambiguities()` names every
  region where a demoted body's name does not contain "Moon".
- **Radii:** primary → `planet_radius_gu`, companions → `moon_radius_gu`,
  scaled by the body's *relative* original size within its region so a big moon
  stays bigger than a small one: `radius = base * (orig / max_orig_in_region)`,
  floored at 25% of base.
- **Anchor** = centroid of the region's bodies, displaced back along the
  **original viewing direction** — the unit vector from the set's `Player Start`
  to its primary body's original offset — by `anchor_standoff_factor × primary
  radius`. A region with no bodies (Vesuvi 4) anchors at its orbit position with
  no displacement.
- **Region radius** = `max(content_extent_gu, distance from anchor to the
  farthest of its bodies' surfaces) + region_margin_gu`.

- [ ] **Step 1: Write the failing test**

Create `tests/tools/test_system_layout.py`:

```python
"""Layout turns a survey into a map: bodies on orbits, anchors placed to
reproduce the original framing.

The anchor rule is the one with real content -- the original set records which
DIRECTION the artist had you looking to see the planet, and the anchor must
reproduce that bearing at the new, larger scale.
"""
import math

import pytest

from tools.systems.layout import LayoutTuning, ambiguities, layout
from tools.systems.survey import SurveyedBody, SurveyedRegion, SurveyedSystem


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _sys_one_planet_per_region():
    return SurveyedSystem(
        name="Ona",
        regions=[
            SurveyedRegion(
                set_name=f"Ona{i}", ordinal=i,
                bodies=[
                    SurveyedBody(f"Ona {i}", 90.0, f"m{i}.nif", offset, False),
                    SurveyedBody("Sun", 5000.0, "sun.nif", (-70000.0, 0.0, 0.0), True),
                ],
                content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))
            for i, offset in enumerate(
                [(-97.183075, 591.702881, -7.431804),
                 (158.69548, 369.396637, 54.861767),
                 (5.948907, 506.339661, -93.216759)], start=1)
        ],
    )


def test_every_region_becomes_a_region_in_the_map():
    m = layout(_sys_one_planet_per_region())
    assert [r.set_name for r in m.regions] == ["Ona1", "Ona2", "Ona3"]


def test_exactly_one_sun_at_the_origin_owned_by_no_region():
    m = layout(_sys_one_planet_per_region())
    suns = [b for b in m.bodies if b.orbits is None]
    assert len(suns) == 1
    assert suns[0].position_gu == (0.0, 0.0, 0.0)
    assert suns[0].owner_region is None
    assert suns[0].name == "Ona"


def test_per_set_suns_are_discarded_not_carried_over():
    # BC gives each set its own sun at +-70000 GU in a different direction
    # (Ona1's at -X, Ona3's at +X, in nominally the same system). None of them
    # survives: the only star is the one at the centre, named for the system.
    m = layout(_sys_one_planet_per_region())
    assert not any(b.name == "Sun" for b in m.bodies)
    assert [b.name for b in m.bodies if b.orbits is None] == ["Ona"]


def test_orbits_increase_with_the_region_ordinal():
    t = LayoutTuning()
    m = layout(_sys_one_planet_per_region(), t)
    d = [math.dist(m.body(f"Ona {i}").position_gu, (0.0, 0.0, 0.0)) for i in (1, 2, 3)]
    assert d[0] == pytest.approx(t.first_orbit_gu)
    assert d[1] == pytest.approx(t.first_orbit_gu + t.orbit_step_gu)
    assert d[2] == pytest.approx(t.first_orbit_gu + 2 * t.orbit_step_gu)


def test_planets_are_resized_to_the_tuning():
    t = LayoutTuning()
    m = layout(_sys_one_planet_per_region(), t)
    assert m.body("Ona 1").radius_gu == pytest.approx(t.planet_radius_gu)


def test_anchor_reproduces_the_original_viewing_direction():
    """The artist put Ona 1 mostly +Y of Player Start. From the new anchor the
    planet must lie in that same direction."""
    s = _sys_one_planet_per_region()
    m = layout(s)
    region = m.region("Ona1")
    planet = m.body("Ona 1")
    original = _unit(s.regions[0].bodies[0].offset_gu)
    now = _unit(tuple(p - a for p, a in zip(planet.position_gu, region.anchor_gu)))
    assert now == pytest.approx(original, abs=1e-6)


def test_anchor_standoff_scales_with_the_new_planet_radius():
    t = LayoutTuning(anchor_standoff_factor=3.0)
    m = layout(_sys_one_planet_per_region(), t)
    d = math.dist(m.body("Ona 1").position_gu, m.region("Ona1").anchor_gu)
    assert d == pytest.approx(3.0 * t.planet_radius_gu)


def test_region_radius_covers_its_bodies_and_its_content():
    t = LayoutTuning()
    s = _sys_one_planet_per_region()
    s.regions[2].content_extent_gu = 322.0
    m = layout(s, t)
    r = m.region("Ona3")
    surface = math.dist(m.body("Ona 3").position_gu, r.anchor_gu) + t.planet_radius_gu
    assert r.radius_gu >= surface + t.region_margin_gu - 1e-6
    assert r.radius_gu >= 322.0


def test_the_largest_body_becomes_the_planet_and_the_rest_moons():
    s = SurveyedSystem(name="Beol", regions=[SurveyedRegion(
        set_name="Beol1", ordinal=1,
        bodies=[
            SurveyedBody("Beol 1", 185.0, "p.nif", (35.0, -274.9, -206.6), False),
            SurveyedBody("Beol 1 Moon 1", 110.0, "m.nif", (726.9, -540.7, -246.6), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s)
    assert m.body("Beol 1").orbits == "Beol"
    assert m.body("Beol 1 Moon 1").orbits == "Beol 1"


def test_a_moon_keeps_its_relative_size():
    s = SurveyedSystem(name="Beol", regions=[SurveyedRegion(
        set_name="Beol1", ordinal=1,
        bodies=[
            SurveyedBody("Beol 1", 200.0, "p.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Big Moon", 100.0, "m.nif", (0.0, 900.0, 0.0), False),
            SurveyedBody("Small Moon", 25.0, "m.nif", (0.0, 700.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s)
    assert m.body("Big Moon").radius_gu > m.body("Small Moon").radius_gu


def test_ambiguities_flags_a_companion_that_is_not_named_moon():
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi5", ordinal=5,
        bodies=[
            SurveyedBody("Geki", 110.0, "a.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Inyo", 85.0, "b.nif", (0.0, 700.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    notes = ambiguities(s)
    assert any("Inyo" in n for n in notes)


def test_moon_spacing_is_tunable_not_hardcoded():
    s = SurveyedSystem(name="Beol", regions=[SurveyedRegion(
        set_name="Beol1", ordinal=1,
        bodies=[
            SurveyedBody("Beol 1", 200.0, "p.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Beol 1 Moon 1", 100.0, "m.nif", (0.0, 900.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    near = layout(s, LayoutTuning(moon_first_orbit_factor=2.0))
    far = layout(s, LayoutTuning(moon_first_orbit_factor=8.0))
    d_near = math.dist(near.body("Beol 1 Moon 1").position_gu,
                       near.body("Beol 1").position_gu)
    d_far = math.dist(far.body("Beol 1 Moon 1").position_gu,
                      far.body("Beol 1").position_gu)
    assert d_far == pytest.approx(4.0 * d_near)


def test_ambiguities_flags_a_body_sitting_on_player_start():
    """A body coincident with Player Start has no viewing direction, so the
    anchor would silently default to +Y. Measured against the real SDK on
    2026-09-22 this happens in 0 of 90 regions -- so if it ever fires, the
    survey failed to resolve a waypoint and must say so, not guess."""
    s = SurveyedSystem(name="Broken", regions=[SurveyedRegion(
        set_name="Broken1", ordinal=1,
        bodies=[SurveyedBody("Ghost", 90.0, "g.nif", (0.0, 0.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    notes = ambiguities(s)
    assert any("Ghost" in n and "Player Start" in n for n in notes)


def test_ambiguities_flags_an_unnumbered_region():
    s = SurveyedSystem(name="Starbase12", regions=[SurveyedRegion(
        set_name="Starbase12", ordinal=None, bodies=[],
        content_extent_gu=100.0, player_start_gu=(0.0, 0.0, 0.0))])
    assert any("Starbase12" in n for n in ambiguities(s))


def test_a_bodiless_region_still_gets_an_anchor_and_a_radius():
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi4", ordinal=4, bodies=[],
        content_extent_gu=1870.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s)
    r = m.region("Vesuvi4")
    assert r.radius_gu >= 1870.0
    assert r.anchor_gu != (0.0, 0.0, 0.0)


def test_the_generated_map_validates():
    from engine.systems.validate import validate
    m = layout(_sys_one_planet_per_region())
    assert validate(m, sdk_set_names=["Ona1", "Ona2", "Ona3"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_system_layout.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.systems.layout'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/systems/layout.py`:

```python
"""Turn a survey into a system map: bodies on orbits, anchors placed to
reproduce the original artist's framing.

THE ANCHOR RULE is the part with real content. The original set records, for
each body, which DIRECTION you looked to see it (the unit vector from that
set's Player Start to the body) and how far away it was. Distance is discarded
-- bodies are re-authored much larger, so the standoff comes from the new
radius -- but the DIRECTION is reproduced exactly: from the new anchor, the
primary body lies on the same bearing it did in BC.

Because a region's anchor is a translation only (never a rotation), and system
axes are the region's local axes, reproducing that bearing is simply
    anchor = primary_position - view_direction * standoff

With companions the anchor moves to the group centroid first, so a planet and
its moon frame you between them -- which is what "anchor between the two" means.

WHAT THIS CANNOT PRESERVE: lighting direction. Each BC set carries its own sun
at +-70000 GU in whatever direction suited that one map (Alioth1's at +X,
Alioth3's at -X, in nominally the same system). With one real sun at the
centre, light comes from wherever the region actually sits. Per-set suns are
discarded here on purpose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from engine.systems.map import Appearance, Body, Region, SystemMap

_GOLDEN_ANGLE = 2.399963229728653


@dataclass
class LayoutTuning:
    planet_radius_gu: float = 1800.0
    moon_radius_gu: float = 600.0
    sun_radius_gu: float = 9000.0
    first_orbit_gu: float = 30000.0
    orbit_step_gu: float = 26000.0
    anchor_standoff_factor: float = 2.2
    region_margin_gu: float = 1500.0
    moon_first_orbit_factor: float = 4.0
    moon_orbit_step_factor: float = 1.5


def _norm(v) -> float:
    return math.sqrt(sum(c * c for c in v))


def _unit(v):
    n = _norm(v)
    if n <= 0.0:
        return (0.0, 1.0, 0.0)
    return tuple(c / n for c in v)


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _scale(v, k):
    return tuple(c * k for c in v)


def _orbit_position(index: int, t: LayoutTuning):
    r = t.first_orbit_gu + t.orbit_step_gu * index
    a = _GOLDEN_ANGLE * index
    return (r * math.sin(a), r * math.cos(a), 0.0)


def _ordered(s):
    numbered = [r for r in s.regions if r.ordinal is not None]
    unnumbered = [r for r in s.regions if r.ordinal is None]
    numbered.sort(key=lambda r: r.ordinal)
    return numbered + unnumbered


def _split(region):
    """(primary, companions) -- the largest non-sun body wins."""
    planets = [b for b in region.bodies if not b.is_sun]
    if not planets:
        return None, []
    primary = max(planets, key=lambda b: b.radius_gu)
    return primary, [b for b in planets if b is not primary]


def ambiguities(s) -> list:
    notes = []
    for region in s.regions:
        primary_check, _ = _split(region)
        if (primary_check is not None
                and _norm(_sub(primary_check.offset_gu, region.player_start_gu)) <= 0.0):
            # _unit() falls back to +Y for a zero-length vector, which would
            # silently frame the region northward. Measured 2026-09-22: this
            # fires on 0 of the 90 real regions, so reaching it means the survey
            # failed to resolve a waypoint -- say so rather than guess.
            notes.append(
                f"{region.set_name}: {primary_check.name!r} sits exactly on "
                f"Player Start, so there is no original viewing direction -- "
                f"the anchor defaults to +Y and is probably wrong")
        if region.ordinal is None:
            notes.append(
                f"{region.set_name}: no trailing number, so its orbit order is a "
                f"guess -- set it in overrides")
        primary, companions = _split(region)
        for c in companions:
            if "moon" not in c.name.lower():
                notes.append(
                    f"{region.set_name}: {c.name!r} was demoted to a moon of "
                    f"{primary.name!r}, but its name does not say 'Moon' -- it may "
                    f"be a separate world needing its own orbit")
    return notes


def layout(s, tuning: LayoutTuning | None = None) -> SystemMap:
    t = tuning or LayoutTuning()
    m = SystemMap(system=s.name, generated={"tool": "gen_system_maps"})

    m.bodies.append(Body(
        name=s.name, display_name=s.name, radius_gu=t.sun_radius_gu,
        position_gu=(0.0, 0.0, 0.0), orbits=None,
        appearance=Appearance(kind="nif", model=""), owner_region=None))

    for index, region in enumerate(_ordered(s)):
        centre = _orbit_position(index, t)
        primary, companions = _split(region)

        if primary is None:
            m.regions.append(Region(set_name=region.set_name, anchor_gu=centre,
                                    radius_gu=region.content_extent_gu + t.region_margin_gu,
                                    body_names=[]))
            continue

        biggest = max(b.radius_gu for b in [primary] + companions) or 1.0
        placed = []

        primary_radius = t.planet_radius_gu
        m.bodies.append(Body(
            name=primary.name, display_name=primary.name,
            radius_gu=primary_radius, position_gu=centre, orbits=s.name,
            appearance=Appearance(kind="nif", model=primary.model),
            owner_region=region.set_name))
        placed.append(primary.name)

        for j, c in enumerate(companions):
            share = max(c.radius_gu / biggest, 0.25)
            radius = t.moon_radius_gu * share
            # Keep each moon's original bearing from the primary, at a distance
            # scaled to the new primary radius.
            direction = _unit(_sub(c.offset_gu, primary.offset_gu))
            distance = primary_radius * (t.moon_first_orbit_factor
                                         + t.moon_orbit_step_factor * j)
            m.bodies.append(Body(
                name=c.name, display_name=c.name, radius_gu=radius,
                position_gu=_add(centre, _scale(direction, distance)),
                orbits=primary.name,
                appearance=Appearance(kind="nif", model=c.model),
                owner_region=region.set_name))
            placed.append(c.name)

        # The anchor: the group's centroid, displaced back along the ORIGINAL
        # viewing direction by a standoff scaled to the new primary radius.
        # With one body the centroid IS the primary, so the primary's bearing
        # from the anchor is exactly the bearing BC gave it. With companions the
        # centroid shifts and the bearing is approximate -- which is the point:
        # "anchor between the two" frames the group, not just the planet.
        view = _unit(_sub(primary.offset_gu, region.player_start_gu))
        members = [m.body(n) for n in placed]
        centroid = tuple(
            sum(b.position_gu[axis] for b in members) / len(members) for axis in range(3))
        standoff = t.anchor_standoff_factor * primary_radius
        anchor = _sub(centroid, _scale(view, standoff))

        reach = max(
            _norm(_sub(b.position_gu, anchor)) + b.radius_gu for b in members)
        m.regions.append(Region(
            set_name=region.set_name, anchor_gu=anchor,
            radius_gu=max(reach, region.content_extent_gu) + t.region_margin_gu,
            body_names=placed))

    return m
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_system_layout.py -v`
Expected: PASS (16 tests)

Note what `test_anchor_reproduces_the_original_viewing_direction` does and does
not pin. The anchor is always `centroid − view × standoff`. With one body the
centroid *is* the primary, so the primary's bearing from the anchor is exactly
BC's — that is what the test asserts, and it covers 64 of the 89 regions. With
companions the centroid shifts and the bearing is deliberately approximate: the
anchor frames the *group*, which is what "anchor between the planet and its
moon" means. Do not add correction arithmetic to force the primary's bearing in
the multi-body case; it would undo the framing the centroid exists to provide.

- [ ] **Step 5: Commit**

```bash
git add tools/systems/layout.py tests/tools/test_system_layout.py
git commit -m "feat(systems): layout — orbits, resized bodies, anchors on the original bearing"
```

---

### Task 5: The generator CLI, and Ona

**Files:**
- Create: `tools/gen_system_maps.py`
- Create: `engine/systems/maps/ona.json` (generated output, committed)
- Test: `tests/unit/test_system_maps_valid.py`

**Interfaces:**
- Consumes: `tools.systems.survey.{survey_system, system_names}`,
  `tools.systems.layout.{layout, ambiguities}`,
  `engine.systems.map.{save, load, available}`,
  `engine.systems.validate.validate`
- Produces:
  - `generate(system: str) -> tuple[SystemMap, list[str]]` — `(map, ambiguity notes)`.
    Merges any existing file's `overrides` block into the fresh map before
    returning, so regeneration never discards hand edits.
  - `pins_from(m: SystemMap) -> dict | None` — reads `m.overrides["pins"]`,
    returning `{body_name: (x, y, z)}` or `None` when the map declares none.
  - `main(argv=None) -> int` — CLI. `--system NAME` (repeatable, default: all),
    `--check` (validate only, write nothing), `--list-ambiguities`.

**Pins are hand-declared, not auto-detected.** The spec names pins as one of the
three things a map holds, and Task 2 built the `pin-respected` rule — but nothing
populates them, so without this the rule never fires on a real map. Three reasons
they belong in the overrides block rather than in the survey:

1. There are only two across all 89 regions (Prendel 3, Xi Entrades 5).
2. Xi Entrades 5's is keyed to a **phantom** waypoint — `Moon1` at
   `(400, 5000, 0)`, which no body ever occupies — so any body-keyed heuristic
   misses it entirely.
3. Deciding "this mission stages content *beside that body*" is a judgement
   call, which is exactly what the overrides block is for.

`SurveyedSystem.pins` (Task 3) stays unpopulated and is reserved for a future
auto-detection pass. Authoring the two known pins is a Task 6 step.

The overrides shape is:

```json
"overrides": {
  "pins": { "Prendel3/Moon 2": [400.0, 5000.0, 0.0] }
}
```

The key is `"<region>/<body>"`, not a bare body name. **BC reuses bare
companion names across regions of one system** — `Geble3` and `Geble4` both
contain a body called `"Moon 1"`, and `Itari3`, `Itari5` and `Itari8` each
contain one — so a bare name cannot identify a body. (Prendel's own moon is
named just `"Moon 2"`; only Prendel 3 has moons, so it happens not to collide,
but the mechanism must not depend on that luck.)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_system_maps_valid.py`:

```python
"""Every checked-in system map must validate against the live SDK.

This is the gate rule: a bad regeneration fails the build here rather than
surfacing as a broken mission weeks later. It is vacuous until the first map
is committed, which is deliberate -- the file lands with Ona in the same task.
"""
import pytest

from engine.systems.map import available, load
from engine.systems.validate import validate
from tools.systems.survey import survey_system


@pytest.mark.parametrize("name", available() or ["__none__"])
def test_checked_in_map_validates(name):
    if name == "__none__":
        pytest.skip("no system maps checked in yet")
    m = load(name)
    sdk = survey_system(m.system)
    from tools.gen_system_maps import pins_from
    problems = validate(m, sdk_set_names=[r.set_name for r in sdk.regions],
                        pins=pins_from(m))
    assert problems == [], "\n".join(f"{p.rule}: {p.detail}" for p in problems)


def test_ona_is_checked_in():
    assert "ona" in available()


def test_ona_covers_all_three_bc_sets():
    m = load("ona")
    assert sorted(r.set_name for r in m.regions) == ["Ona1", "Ona2", "Ona3"]


def test_ona_has_exactly_one_sun():
    m = load("ona")
    assert len([b for b in m.bodies if b.orbits is None]) == 1


def test_ona_planets_are_large():
    m = load("ona")
    planets = [b for b in m.bodies if b.owner_region is not None]
    assert len(planets) == 3
    # BC authored these at 90 GU; the whole point is that they are now big.
    assert all(b.radius_gu >= 1000.0 for b in planets)


def test_regenerating_ona_is_idempotent():
    """Running the generator again must reproduce the committed file byte for
    byte, so a regeneration diff shows only real changes."""
    from engine.systems.map import to_json
    from tools.gen_system_maps import generate
    fresh, _notes = generate("Ona")
    assert to_json(fresh) == to_json(load("ona"))


def test_overrides_survive_regeneration():
    from tools.gen_system_maps import _merge_overrides
    from engine.systems.map import SystemMap
    old = SystemMap(system="Ona", overrides={"note": "hand tuned"})
    fresh = SystemMap(system="Ona")
    _merge_overrides(fresh, old)
    assert fresh.overrides == {"note": "hand tuned"}


def test_a_malformed_existing_map_is_never_overwritten(tmp_path, monkeypatch):
    """The overrides block is the only place hand art-direction lives, and the
    generator writes straight back over the file it read. So an unreadable map
    must stop the write, not be treated as "no prior map" -- otherwise one bad
    character silently replaces a human's work with a fresh layout."""
    import engine.systems.map as smap
    from tools.gen_system_maps import main
    maps = tmp_path / "maps"
    maps.mkdir()
    bad = maps / "ona.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(smap, "map_dir", lambda: maps)
    rc = main(["--system", "Ona"])
    assert rc != 0
    assert bad.read_text(encoding="utf-8") == "{ this is not json"


def test_pins_from_reads_the_overrides_block():
    """Pins are hand-declared in overrides -- there are only two across all 89
    regions, and one of them is keyed to a waypoint no body occupies."""
    from engine.systems.map import SystemMap
    from tools.gen_system_maps import pins_from
    assert pins_from(SystemMap(system="Ona")) is None
    assert pins_from(SystemMap(system="Ona", overrides={"pins": {}})) is None
    m = SystemMap(system="Prendel",
                  overrides={"pins": {"Prendel 3 Moon 2": [400.0, 5000.0, 0.0]}})
    assert pins_from(m) == {"Prendel 3 Moon 2": (400.0, 5000.0, 0.0)}


def test_the_cli_enforces_declared_pins():
    """A declared pin that the layout has moved must be reported, not ignored.
    Without this wiring the pin-respected rule never fires on a real map."""
    from engine.systems.map import SystemMap
    from engine.systems.validate import validate
    from tools.gen_system_maps import pins_from
    m = load("ona")
    m.overrides = {"pins": {m.regions[0].body_names[0]: [1.0, 2.0, 3.0]}}
    problems = validate(m, pins=pins_from(m))
    assert any(p.rule == "pin-respected" for p in problems)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_system_maps_valid.py -v`
Expected: FAIL — `test_ona_is_checked_in` fails (no map yet), and the
`generate` import raises `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `tools/gen_system_maps.py`:

```python
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
from tools.systems.layout import ambiguities, layout  # noqa: E402
from tools.systems.survey import survey_system, system_names  # noqa: E402


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


def generate(system: str):
    """Survey, lay out, and carry the existing map's overrides forward.

    Deliberately does NOT swallow a read failure. The overrides block is the
    only place hand art-direction lives, and main() writes the result straight
    back over the file -- so treating an unreadable map as "no prior map"
    would silently replace a human's work with a fresh layout. Let it raise;
    main() reports it and refuses to save that system.
    """
    surveyed = survey_system(system)
    fresh = layout(surveyed)
    old = load(system) if system.lower() in available() else None
    _merge_overrides(fresh, old)
    return fresh, ambiguities(surveyed)


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
        problems = validate(m, sdk_set_names=[r.set_name for r in surveyed.regions],
                            pins=pins_from(m))
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
```

- [ ] **Step 4: Generate Ona**

Run: `uv run python tools/gen_system_maps.py --system Ona --list-ambiguities`
Expected: `Ona: 3 regions, 4 bodies -- ok <path>/engine/systems/maps/ona.json`,
with no ambiguity notes (Ona's regions are all numbered and hold one planet each).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_system_maps_valid.py -v`
Expected: PASS (10 tests, one parametrised over `ona`)

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add tools/gen_system_maps.py engine/systems/maps/ona.json tests/unit/test_system_maps_valid.py
git commit -m "feat(systems): generator CLI, and the Ona map"
```

- [ ] **Step 8: STOP — human review checkpoint**

Do **not** generate the remaining 24 systems. Print the Ona map and report:

- each region's anchor and radius,
- each body's radius and distance from the sun,
- the angular size of each region's planet from its own anchor, in degrees
  (`2 * atan(radius / distance)`), which is the number that answers "does it
  fill the sky?",
- the ambiguity notes.

Then hand back for a human decision on the tuning constants before Task 6.

---

### Task 6: BC-proportional sizes and per-region framing

**Why.** The Task 5 checkpoint showed the layout flattening *two* kinds of
authored variety:

- Every planet came out at a flat `planet_radius_gu = 1800`, discarding BC's
  **15x spread** (30-450 GU across 87 primaries, 23 distinct radii, with real
  within-system variation: Alioth 90-360, Itari 220-450, Chambana 120-360).
- Every planet subtended an identical **48.89 deg**, because the standoff was a
  single constant times a single radius. BC's own framings varied (Ona 1/2/3 at
  17.1 / 25.0 / 19.8 deg) because the artist chose each distance.

Both are fixed by deriving from BC instead of fixing a constant. Bodies scale by
a multiplier; the standoff becomes BC's own distance-to-radius **ratio**,
divided by a framing constant.

**The property that makes this work:** the standoff is measured in *planet
radii*, so the size multiplier cancels out of the apparent size.
`planet_radius_scale` controls how big a body physically is (orbit times, region
size, km on the readout) and `framing_scale` controls how much sky it fills,
with **no crosstalk**. Verified: at x10, x20 and x40 the Ona angular sizes are
identical to 2 d.p.

At `framing_scale = 1.0` the new apparent size equals BC's **exactly** (not
approximately -- the radii cancel), which Step 1 asserts as an invariant.

**Files:**
- Modify: `tools/systems/layout.py`
- Modify: `engine/systems/validate.py` (two new rules)
- Modify: `engine/systems/maps/ona.json` (regenerated)
- Test: `tests/tools/test_system_layout.py`, `tests/unit/test_system_map_validate.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4, unchanged.
- Produces — `LayoutTuning` gains and loses fields:

| Field | Default | Meaning |
|---|---|---|
| `planet_radius_scale` | `20.0` | planet radius = BC radius x this |
| `moon_radius_scale` | `20.0` | moon radius = BC radius x this |
| `sun_radius_scale` | `2.0` | sun radius = BC sun radius x this |
| `framing_scale` | `2.0` | apparent size vs BC; `1.0` reproduces BC exactly |
| `min_standoff_factor` | `1.5` | closest allowed, in planet radii (67.4 deg) |
| `max_standoff_factor` | `12.0` | furthest allowed, in planet radii (9.5 deg) |
| `default_sun_radius_gu` | `9000.0` | sun radius for a system that authors none (Belaruz, Vesuvi) |
| `first_orbit_clearance_gu` | `30000.0` | innermost orbit sits this far from the **sun's surface** |
| `orbit_step_gu` | `26000.0` | unchanged |
| `region_margin_gu` | `1500.0` | unchanged |
| `anchor_standoff_factor` | `2.2` | **now only the fallback** for a region whose BC geometry is degenerate |

  **REMOVED:** `planet_radius_gu`, `moon_radius_gu`, `sun_radius_gu`,
  `first_orbit_gu`. Every one encoded a flat size the new rules derive.
  (`sun_radius_gu`'s old value, 9000.0, survives as `default_sun_radius_gu`,
  which is now only reached by the two sunless systems.)

- Two new `validate()` rules:

| slug | rule |
|---|---|
| `body-overlap` | No two bodies' surfaces intersect: `dist(a, b) > a.radius_gu + b.radius_gu`. |
| `anchor-inside-body` | No region's anchor falls inside ANY body. (`body-engulfs-anchor` only checks a region's *own* bodies, so an anchor inside the **sun** slips through it entirely.) |

**Measured against all 25 real systems before writing this task** — these are the
numbers the implementation must reproduce:

- **Zero** body overlaps of any kind.
- Apparent sizes span **9.5 deg to 67.4 deg**, clustered 20-50 deg.
- The `min` floor clamps **3** regions (Alioth6, Beol1, Savoy2 -> 67.4 deg).
- The `max` cap clamps **4** regions (Geble4 16.7, OmegaDraconis1 17.1,
  Savoy1 24.1, XiEntrades4 16.1 -> all 9.5 deg). Savoy 1 is why the cap exists:
  BC placed it 5041 GU from a 100 GU planet, a 50:1 ratio, which without a cap
  puts the anchor 48,142 GU away -- far enough to land past the sun.
- Ona: 33.4 / 47.8 / 38.5 deg, orbits at 40,000 / 66,000 / 92,000 GU
  (sun r=10,000 + 30,000 clearance).
- Largest system: Itari, outermost orbit 226,000 GU (39,550 km).

- [ ] **Step 1: Write the failing tests**

Add to `tests/tools/test_system_layout.py` (keep every existing test; three of
them need the edits in Step 3):

```python
def test_framing_scale_one_reproduces_bc_apparent_size_exactly():
    """The radii cancel: standoff is measured in planet radii, so at
    framing_scale 1.0 the new angular size EQUALS BC's, not approximates it."""
    s = _sys_one_planet_per_region()
    m = layout(s, LayoutTuning(framing_scale=1.0))
    for region in s.regions:
        bc = region.bodies[0]
        d_bc = math.dist(bc.offset_gu, region.player_start_gu)
        want = 2.0 * math.atan(bc.radius_gu / d_bc)
        body = m.body(bc.name)
        d_new = math.dist(body.position_gu, m.region(region.set_name).anchor_gu)
        got = 2.0 * math.atan(body.radius_gu / d_new)
        assert got == pytest.approx(want, rel=1e-9), region.set_name


def test_apparent_size_is_independent_of_the_size_scale():
    """planet_radius_scale and framing_scale must not interact."""
    s = _sys_one_planet_per_region()
    angles = []
    for scale in (10.0, 20.0, 40.0):
        m = layout(s, LayoutTuning(planet_radius_scale=scale))
        body = m.body("Ona 1")
        d = math.dist(body.position_gu, m.region("Ona1").anchor_gu)
        angles.append(2.0 * math.atan(body.radius_gu / d))
    assert angles[1] == pytest.approx(angles[0], rel=1e-12)
    assert angles[2] == pytest.approx(angles[0], rel=1e-12)


def test_planets_keep_bcs_relative_sizes():
    """BC authored a 15x spread across 87 primaries. A flat radius threw it away."""
    s = SurveyedSystem(name="Alioth", regions=[
        SurveyedRegion(set_name="Alioth1", ordinal=1, bodies=[
            SurveyedBody("Alioth 1", 90.0, "a.nif", (0.0, 1000.0, 0.0), False)],
            content_extent_gu=0.0, player_start_gu=(0.0, -500.0, 0.0)),
        SurveyedRegion(set_name="Alioth6", ordinal=6, bodies=[
            SurveyedBody("Alioth 6", 360.0, "b.nif", (0.0, 1000.0, 0.0), False)],
            content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0)),
    ])
    m = layout(s, LayoutTuning(planet_radius_scale=20.0))
    assert m.body("Alioth 1").radius_gu == pytest.approx(1800.0)
    assert m.body("Alioth 6").radius_gu == pytest.approx(7200.0)


def test_moons_keep_bcs_relative_sizes():
    s = SurveyedSystem(name="Serris", regions=[SurveyedRegion(
        set_name="Serris3", ordinal=3,
        bodies=[
            SurveyedBody("Serris 3", 100.0, "p.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Serris 3 Moon 1", 7.0, "m.nif", (0.0, 600.0, 0.0), False),
            SurveyedBody("Serris 3 Moon 2", 20.0, "m.nif", (0.0, 700.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s, LayoutTuning(moon_radius_scale=20.0))
    assert m.body("Serris 3 Moon 1").radius_gu == pytest.approx(140.0)
    assert m.body("Serris 3 Moon 2").radius_gu == pytest.approx(400.0)


def test_the_sun_scales_from_bcs_authored_radius():
    s = _sys_one_planet_per_region()          # its suns are authored at 5000 GU
    m = layout(s, LayoutTuning(sun_radius_scale=2.0))
    sun = [b for b in m.bodies if b.orbits is None][0]
    assert sun.radius_gu == pytest.approx(10000.0)


def test_a_system_with_no_authored_sun_still_gets_one():
    """Belaruz and Vesuvi build a MetaNebula and no Sun_Create at all."""
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi5", ordinal=5,
        bodies=[SurveyedBody("Geki", 110.0, "g.nif", (0.0, 538.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s, LayoutTuning(default_sun_radius_gu=9000.0))
    sun = [b for b in m.bodies if b.orbits is None][0]
    assert sun.radius_gu == pytest.approx(9000.0)


def test_the_first_orbit_clears_the_suns_surface():
    """first_orbit_clearance_gu is measured from the SUN'S SURFACE, so a bigger
    sun pushes every orbit out rather than swallowing the innermost planet."""
    s = _sys_one_planet_per_region()
    m = layout(s, LayoutTuning(sun_radius_scale=2.0,
                               first_orbit_clearance_gu=30000.0))
    sun = [b for b in m.bodies if b.orbits is None][0]
    innermost = math.dist(m.body("Ona 1").position_gu, (0.0, 0.0, 0.0))
    assert innermost == pytest.approx(sun.radius_gu + 30000.0)


def test_the_standoff_is_clamped_at_both_ends():
    """Savoy 1 is why the cap exists: BC put a 100 GU planet 5041 GU away, a
    50:1 ratio, which uncapped throws the anchor far enough to pass the sun."""
    def one(radius, distance, tuning):
        s = SurveyedSystem(name="X", regions=[SurveyedRegion(
            set_name="X1", ordinal=1,
            bodies=[SurveyedBody("P", radius, "p.nif", (0.0, distance, 0.0), False)],
            content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
        m = layout(s, tuning)
        return (math.dist(m.body("P").position_gu, m.region("X1").anchor_gu)
                / m.body("P").radius_gu)

    t = LayoutTuning(min_standoff_factor=1.5, max_standoff_factor=12.0,
                     framing_scale=2.0)
    assert one(100.0, 5041.0, t) == pytest.approx(12.0)     # Savoy 1, capped
    assert one(200.0, 400.0, t) == pytest.approx(1.5)       # very close, floored
    assert one(90.0, 600.4, t) == pytest.approx(600.4 / 90.0 / 2.0)  # untouched


def test_ambiguities_reports_every_clamped_region():
    """A clamp overrides BC's intent, so the art-direction pass must see it."""
    s = SurveyedSystem(name="Savoy", regions=[SurveyedRegion(
        set_name="Savoy1", ordinal=1,
        bodies=[SurveyedBody("Savoy 1", 100.0, "p.nif", (0.0, 5041.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    assert any("Savoy 1" in n and "clamp" in n.lower() for n in ambiguities(s))
```

Add to `tests/unit/test_system_map_validate.py`:

```python
def test_body_overlap_flags_two_bodies_whose_surfaces_intersect():
    m = _valid()
    m.body("Ona 2").position_gu = (0.0, 24000.0, 0.0)   # 2000 GU from Ona 1
    assert "body-overlap" in _slugs(validate(m))


def test_body_overlap_accepts_bodies_that_merely_come_close():
    m = _valid()
    # Ona 1 r=1800 at y=22000; put Ona 2 r=1800 at y=25601 -> 3601 GU apart.
    m.body("Ona 2").position_gu = (0.0, 25601.0, 0.0)
    assert "body-overlap" not in _slugs(validate(m))


def test_anchor_inside_body_flags_an_anchor_swallowed_by_the_sun():
    """body-engulfs-anchor only checks a region's OWN bodies, so an anchor
    inside the sun would otherwise pass every rule."""
    m = _valid()
    m.regions[0].anchor_gu = (0.0, 100.0, 0.0)          # inside the r=5000 sun
    assert "anchor-inside-body" in _slugs(validate(m))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_system_layout.py tests/unit/test_system_map_validate.py -v`
Expected: the eight new layout tests fail (`TypeError: unexpected keyword
argument 'planet_radius_scale'` and friends), and the three new validator tests
fail on the missing rules. Existing tests still pass at this point.

- [ ] **Step 3: Implement**

In `tools/systems/layout.py`:

1. Replace the four removed fields in `LayoutTuning` with the new ones from the
   Interfaces table. Keep `anchor_standoff_factor` and document it as the
   degenerate-case fallback only.

2. Add the standoff helper:

```python
def _standoff_factor(primary, region, t) -> float:
    """How many NEW planet-radii the anchor sits back from the planet's centre.

    Derived from BC's own framing. The artist placed each planet at a distance
    that gave it a particular apparent size, and that varied per map -- Ona 2
    read close, Ona 1 distant. A single constant flattened all of it.

    Because the standoff is measured in radii, the planet's SIZE cancels out of
    the apparent angle: `planet_radius_scale` and `framing_scale` are
    independent knobs. At framing_scale 1.0 the result equals BC's apparent
    size exactly.

    Clamped at both ends. The floor keeps the anchor outside the planet; the
    cap exists because BC's most distant framing (Savoy 1: a 100 GU planet
    5041 GU away, 50:1) would otherwise throw the anchor far enough to pass the
    sun. Both clamps are reported by ambiguities() -- they override BC's intent.
    """
    r_bc = primary.radius_gu
    d_bc = _norm(_sub(primary.offset_gu, region.player_start_gu))
    if r_bc <= 0.0 or d_bc <= 0.0:
        return t.anchor_standoff_factor
    raw = (d_bc / r_bc) / t.framing_scale
    return min(max(raw, t.min_standoff_factor), t.max_standoff_factor)
```

3. In `layout()`:
   - sun radius becomes `sun_bc * t.sun_radius_scale`, where `sun_bc` is the
     largest `is_sun` body radius found anywhere in the survey. **Two systems
     — Belaruz and Vesuvi — author no sun object at all**, so `sun_bc` is 0.0
     there; use `t.default_sun_radius_gu` in that case.
   - `first_orbit = sun_radius + t.first_orbit_clearance_gu`, replacing the
     `first_orbit_gu` term in `_orbit_position`. Pass it in rather than reading
     a constant.
   - primary radius becomes `primary.radius_gu * t.planet_radius_scale`.
   - companion radius becomes `c.radius_gu * t.moon_radius_scale` — the
     `share` / `biggest` / 25%-floor logic is DELETED, since scaling BC's own
     radius preserves relative size directly.
   - `standoff = _standoff_factor(primary, region, t) * primary_radius`.

4. In `ambiguities()`, report each clamped region, naming the body and which
   clamp fired, so the art-direction pass sees every place BC's intent was
   overridden.

5. Update these three existing tests, whose expectations the new rules change:
   `test_planets_are_resized_to_the_tuning` (now asserts BC radius x scale),
   `test_orbits_increase_with_the_region_ordinal` (orbits now start at
   `sun_radius + clearance`), and `test_anchor_standoff_scales_with_the_new_planet_radius`
   (rewrite to assert that doubling `planet_radius_scale` doubles the standoff
   distance, which stays true because the factor is in radii).

In `engine/systems/validate.py`, add the two rules from the Interfaces table.
`anchor-inside-body` must test a region's anchor against EVERY body in the map,
not just the region's own.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/tools/test_system_layout.py tests/unit/test_system_map_validate.py -v`
Expected: PASS — 25 layout tests, 15 validator tests.

- [ ] **Step 5: Regenerate Ona and check it against the measured values**

Run: `uv run python tools/gen_system_maps.py --system Ona --list-ambiguities`
Expected: `Ona: 3 regions, 4 bodies -- ok <path>`, no ambiguity notes (none of
Ona's regions is clamped), and the regenerated file must show:
- sun radius **10,000 GU** (BC 5000 x 2)
- orbits at **40,000 / 66,000 / 92,000 GU**
- planets all **1800 GU** (BC 90 x 20)
- apparent sizes **33.4 / 47.8 / 38.5 degrees**

If any of those differ, the implementation is wrong — do not adjust the
expectation. Report the mismatch.

- [ ] **Step 6: Check every system lays out cleanly**

Run: `uv run python tools/gen_system_maps.py --check --list-ambiguities`
Expected: 25 lines, every one `ok`, exit code 0, and the ambiguity notes must
include exactly these seven clamped regions: Alioth6, Beol1, Savoy2 (floored)
and Geble4, OmegaDraconis1, Savoy1, XiEntrades4 (capped). No map is written by
`--check`.

- [ ] **Step 7: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add tools/systems/layout.py engine/systems/validate.py \
        engine/systems/maps/ona.json \
        tests/tools/test_system_layout.py tests/unit/test_system_map_validate.py
git commit -m "feat(systems): sizes and framing derived from BC, not flattened"
```

---

### Task 7: The remaining 24 systems

**Prerequisite:** Task 6 is complete and the `LayoutTuning` defaults are settled.

**Files:**
- Create: `engine/systems/maps/*.json` (24 more)
- Modify: `tools/systems/layout.py` only if the checkpoint changed the rules
- Test: `tests/unit/test_system_maps_valid.py` (no change — it parametrises over
  whatever is checked in)

- [ ] **Step 1: Generate every system and read the report**

Run: `uv run python tools/gen_system_maps.py --list-ambiguities`
Expected: 25 lines, every one `ok`. Capture the ambiguity notes — the expected
ones are the unnumbered regions (Starbase 12, Dry Dock, the Colony-named Vesuvi
regions) and the companion bodies in Vesuvi 5 (Inyo, Mori) and Beol 3 (Kerry,
Legare).

- [ ] **Step 2: Resolve each ambiguity in an overrides block**

For every note, decide and record it. There is no correct mechanical answer;
this is the art-direction pass. Leave a one-line reason in the overrides block
next to each decision.

- [ ] **Step 2a: Declare the two known pins**

A pin is a body a mission stages ships beside; the layout must not move it away
from that content. Two exist across all 89 regions, both found by measuring
mission placements against body positions (see the spec's "How much space a
region actually needs"):

- **Prendel 3** — E5M2 and E6M4 stage a base and three Galors at 6100–6368 GU,
  just past `Moon 2` at `(400, 5000, 0)`.
- **Xi Entrades 5** — E7M3 stages the Akira/Kessok fight at 5494–5615 GU around
  a waypoint named `Moon1` at `(400, 5000, 0)` that **no body ever occupies**.
  There is nothing to pin, so this one is resolved by giving the region a radius
  that still contains the staged content, not by a pin entry. Record that
  decision in the overrides block with its reason.

Add the Prendel entry to `engine/systems/maps/prendel.json` (the body is `"Moon 2"`, keyed by its region):

```json
"overrides": {
  "pins": { "Prendel3/Moon 2": [400.0, 5000.0, 0.0] }
}
```

Note the body is called just `"Moon 2"` — BC does not prefix companion names
with their planet — which is exactly why pin keys carry the region.

Then confirm the pin rule actually fires when violated — temporarily change that
offset to `[0.0, 0.0, 0.0]`, run `--check`, see `pin-respected` reported, and put
it back. A pin nobody has watched fail is a pin you cannot trust.

- [ ] **Step 3: Re-run and confirm clean**

Run: `uv run python tools/gen_system_maps.py --check`
Expected: 25 lines, all `ok`, exit code 0.

- [ ] **Step 4: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 5: Commit**

```bash
git add engine/systems/maps
git commit -m "feat(systems): maps for the remaining 24 star systems"
```

---

---

### Task 8: Make `layout()` honour a pin

**Why this exists.** Task 7 found that the pin feature is **enforcement without a
mechanism**. `engine/systems/validate.py` has a `pin-respected` rule, and
`tools/gen_system_maps.py` reads pins from a map's `overrides` and hands them to
it — but `tools/systems/layout.py` has no `pins` parameter and contains **zero**
references to pins. It places every companion body at a *derived* distance,
`primary_radius * (moon_first_orbit_factor + moon_orbit_step_factor * j)`,
deliberately discarding BC's absolute distance.

So a declared pin can never hold: Task 7 measured the authored Prendel pin as
violated by **~38,500 GU** even when written exactly as the plan specified. The
Task 7 implementer correctly refused to ship that declaration and recorded the
derivation in `engine/systems/maps/prendel.json`'s `overrides.notes` instead.

A pin exists so a mission's staged ships stay beside the body they were authored
beside. E5M2 and E6M4 park a base and three Galors at 6100–6368 GU in Prendel 3,
just past `Moon 2`'s authored position. Without a working pin those ships sit in
empty space.

**Files:**
- Modify: `tools/systems/layout.py`
- Modify: `tools/gen_system_maps.py`
- Modify: `engine/systems/maps/prendel.json` (declare the pin; regenerated)
- Test: `tests/tools/test_system_layout.py`, `tests/unit/test_system_maps_valid.py`

**Interfaces:**
- `layout(s, tuning=None, pins=None) -> SystemMap` — `pins` is
  `{"<region>/<body>": (x, y, z)}` or `None`, the same shape
  `gen_system_maps.pins_from()` already returns and `validate()` already takes.
- `generate()` passes the existing map's pins into `layout()`.

**The rule.** After a region's bodies and anchor are placed as now, reposition
each of that region's pinned bodies to `anchor + offset`. Order matters and is
the whole subtlety:

1. Place bodies and compute the anchor exactly as today. The anchor is derived
   from the group centroid, which uses the pinned body's *pre-pin* position.
2. Then move each pinned body to `anchor_gu + offset`.
3. Do **not** recompute the anchor afterwards. It is a fixed-point problem —
   moving the body shifts the centroid, which shifts the anchor, which moves the
   body — and one pass is both stable and good enough. The centroid shift only
   nudges framing; the pin itself is then exact, which is what `pin-respected`
   checks. Say this in the docstring so nobody "fixes" it into a loop.

A pin naming a region or body that does not exist is **ignored by `layout()`**,
not an error — `validate()` already reports those four failure modes, and
duplicating the diagnosis in two places invites them to disagree.

- [ ] **Step 1: Write the failing tests**

Add to `tests/tools/test_system_layout.py`:

```python
def test_a_pinned_body_lands_at_its_authored_offset_from_the_anchor():
    """A pin exists so a mission's staged ships stay beside the body they were
    authored beside. E5M2 parks a base and three Galors just past Prendel 3's
    Moon 2, so that moon must keep its set-local position exactly."""
    s = SurveyedSystem(name="Prendel", regions=[SurveyedRegion(
        set_name="Prendel3", ordinal=3,
        bodies=[
            SurveyedBody("Prendel 3", 360.0, "p.nif", (-1000.0, 1500.0, 0.0), False),
            SurveyedBody("Moon 1", 90.0, "m.nif", (-5000.0, 0.0, 0.0), False),
            SurveyedBody("Moon 2", 90.0, "m.nif", (400.0, 5000.0, 0.0), False),
        ],
        content_extent_gu=6368.0, player_start_gu=(0.0, 0.0, 0.0))])
    pins = {"Prendel3/Moon 2": (400.0, 5000.0, 0.0)}
    m = layout(s, pins=pins)
    anchor = m.region("Prendel3").anchor_gu
    moon = m.body("Moon 2")
    have = tuple(p - a for p, a in zip(moon.position_gu, anchor))
    assert have == pytest.approx((400.0, 5000.0, 0.0), abs=1e-6)


def test_an_unpinned_body_in_the_same_region_is_not_moved():
    """Pinning one companion must not disturb its siblings."""
    s = SurveyedSystem(name="Prendel", regions=[SurveyedRegion(
        set_name="Prendel3", ordinal=3,
        bodies=[
            SurveyedBody("Prendel 3", 360.0, "p.nif", (-1000.0, 1500.0, 0.0), False),
            SurveyedBody("Moon 1", 90.0, "m.nif", (-5000.0, 0.0, 0.0), False),
            SurveyedBody("Moon 2", 90.0, "m.nif", (400.0, 5000.0, 0.0), False),
        ],
        content_extent_gu=6368.0, player_start_gu=(0.0, 0.0, 0.0))])
    free = layout(s).body("Moon 1").position_gu
    pinned = layout(s, pins={"Prendel3/Moon 2": (400.0, 5000.0, 0.0)}).body("Moon 1")
    assert pinned.position_gu == pytest.approx(free)


def test_layout_ignores_a_pin_naming_something_that_does_not_exist():
    """validate() reports those; layout() must not also decide, or the two can
    disagree about the same map."""
    s = _sys_one_planet_per_region()
    m = layout(s, pins={"Nowhere/Ghost": (0.0, 0.0, 0.0),
                        "Ona1/Ghost": (0.0, 0.0, 0.0),
                        "malformed key": (0.0, 0.0, 0.0)})
    assert m.region("Ona1") is not None
    assert m.body("Ona 1") is not None


def test_a_pinned_map_passes_the_pin_rule_end_to_end():
    """The whole point: declare a pin, lay out, and validate() must be happy."""
    from engine.systems.validate import validate
    s = SurveyedSystem(name="Prendel", regions=[SurveyedRegion(
        set_name="Prendel3", ordinal=3,
        bodies=[
            SurveyedBody("Prendel 3", 360.0, "p.nif", (-1000.0, 1500.0, 0.0), False),
            SurveyedBody("Moon 2", 90.0, "m.nif", (400.0, 5000.0, 0.0), False),
        ],
        content_extent_gu=6368.0, player_start_gu=(0.0, 0.0, 0.0))])
    pins = {"Prendel3/Moon 2": (400.0, 5000.0, 0.0)}
    m = layout(s, pins=pins)
    assert validate(m, pins=pins) == []
```

Add to `tests/unit/test_system_maps_valid.py`:

```python
def test_prendels_declared_pin_holds_in_the_committed_map():
    """Regression: layout() once ignored pins entirely, so this pin was
    violated by ~38,500 GU while every map still reported ok."""
    from engine.systems.validate import validate
    from tools.gen_system_maps import pins_from
    m = load("prendel")
    pins = pins_from(m)
    assert pins, "prendel.json must declare its pin"
    assert [p for p in validate(m, pins=pins) if p.rule == "pin-respected"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_system_layout.py tests/unit/test_system_maps_valid.py -v`
Expected: the four layout tests fail (`TypeError: layout() got an unexpected
keyword argument 'pins'`), and the Prendel test fails because no pin is declared
yet.

- [ ] **Step 3: Implement**

1. `layout()` takes `pins=None` and, after each region's anchor is computed,
   repositions that region's pinned bodies to `anchor + offset`. Resolve a pin
   key as `"<region>/<body>"`, splitting on the first `/`, and skip silently
   when the region or body does not match — `validate()` owns the diagnosis.
2. `generate()` passes `pins_from(old)` into `layout()`. `old` is already loaded
   there for the overrides merge; reuse it rather than loading twice.
3. Declare the pin in `engine/systems/maps/prendel.json`'s `overrides`:

```json
"pins": { "Prendel3/Moon 2": [400.0, 5000.0, 0.0] }
```

   and REPLACE the `overrides.notes` entry for `"Prendel3/Moon 2"` — it
   currently explains why the pin could not be declared, which will no longer be
   true — with one line saying what the pin protects (E5M2/E6M4 stage a base and
   three Galors at 6100–6368 GU, just past this moon).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/tools/test_system_layout.py tests/unit/test_system_map_validate.py tests/unit/test_system_maps_valid.py -v`
Expected: all pass.

- [ ] **Step 5: Regenerate and prove the pin actually bites**

Run: `uv run python tools/gen_system_maps.py --system Prendel`
Expected: `Prendel: 5 regions, 8 bodies -- ok <path>`.

Then temporarily change the declared offset to `[0.0, 0.0, 0.0]`, run
`uv run python tools/gen_system_maps.py --system Prendel --check`, and confirm a
`pin-respected` problem IS reported and the exit code is non-zero. Restore the
real offset and confirm `ok` returns. **Back up and restore by `cp`, never by
git** — this is a shared checkout. Record both outputs in your report; a pin
nobody has watched fail is a pin you cannot trust.

- [ ] **Step 6: Check every system still lays out cleanly**

Run: `uv run python tools/gen_system_maps.py --check --list-ambiguities`
Expected: all 32 `ok`, exit code 0, and the same seven clamped regions
(Alioth6, Beol1, Savoy2 floored; Geble4, OmegaDraconis1, Savoy1, XiEntrades4
capped).

- [ ] **Step 7: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add tools/systems/layout.py tools/gen_system_maps.py \
        engine/systems/maps/prendel.json \
        tests/tools/test_system_layout.py tests/unit/test_system_maps_valid.py
git commit -m "feat(systems): layout honours a pin, so pin-respected can pass"
```

---

### Task 9: Push the first orbit out until no region reaches its star

**Why.** The final review found, and the atlas made visible, that **7 regions'
spheres intersect the star they orbit** — `Alioth1`, `Cebalrai1`, `Chambana1`,
`Itari1`, `Serris1`, `Voltair1`, `XiEntrades1`. `Voltair1` is worst: its radius
is 24,291 GU but its anchor sits only 20,202 GU from the star, so the sphere
**contains the star's centre**. Inert today (nothing reads these files) but under
spec §3 a region boundary would pass through a sun.

`anchor-inside-body` does not catch it because no *anchor* is inside a star — the
sphere overlaps while its centre stays outside.

**The fix, and why it is exact rather than iterative.** All 7 are the INNERMOST
region of their system, and every orbit is `first_orbit + orbit_step_gu * i`, so
raising the first orbit moves every region outward by the same amount — it can
fix the inner ones and can never create a new clip further out.

A region's radius is `max(reach, content_extent) + margin`, where `reach` is
measured **from its own anchor**. Moving the whole system outward changes neither
term. So the radius is invariant under this adjustment, one corrective pass
suffices, and a second pass is only a cheap guard against floating-point drift.

**Files:**
- Modify: `tools/systems/layout.py`
- Modify: `engine/systems/validate.py` (one new rule)
- Modify: `engine/systems/maps/*.json` (regenerate all 32)
- Test: `tests/tools/test_system_layout.py`, `tests/unit/test_system_map_validate.py`

**Interfaces:**
- `LayoutTuning.first_orbit_clearance_gu` (30000.0) becomes a **minimum**: the
  innermost orbit sits at least that far from the star's surface, and further
  when a region would otherwise reach the star. Its docstring must say so.
- `LayoutTuning` gains `star_clearance_gu: float = 500.0` — the margin left
  between a region's sphere and the star's surface after the push, so the two are
  clear rather than exactly tangent.
- New `validate()` rule `region-reaches-star`: no region's sphere may intersect
  the system's star, i.e. `dist(anchor, star.position_gu) > region.radius_gu +
  star.radius_gu`. The star is the body with `orbits is None`; skip the rule when
  a map has none.
- `ambiguities()` reports any system whose first orbit was pushed, naming the
  distance — this changes numbers a human chose, so it must not happen silently.

**Implementation shape.** Extract the current body-and-region placement from
`layout()` into a helper that takes the first-orbit distance as a parameter and
returns a `SystemMap`. `layout()` then:

1. calls it with `sun_radius + t.first_orbit_clearance_gu`;
2. computes the largest intrusion across regions —
   `max(0, region.radius_gu + sun_radius + t.star_clearance_gu - dist(anchor, star))`;
3. if that is positive, calls the helper again with the first orbit raised by it,
   and keeps the second result;
4. records the push so `ambiguities()` can report it.

Do NOT loop more than twice. If a second pass still intrudes, that means the
invariant above is false and something else is wrong — report it rather than
iterating blindly.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_system_map_validate.py`:

```python
def test_region_reaches_star_flags_a_sphere_overlapping_the_sun():
    """anchor-inside-body misses this: the anchor stays outside the star while
    the region's SPHERE overlaps it. Under streaming, a region boundary would
    pass through a sun."""
    m = _valid()
    # The star is r=5000 at the origin; Ona1's radius is 3000.
    m.region("Ona1").anchor_gu = (0.0, 7000.0, 0.0)   # 7000 < 3000 + 5000
    assert "region-reaches-star" in _slugs(validate(m))


def test_region_reaches_star_accepts_a_region_that_merely_comes_close():
    m = _valid()
    m.region("Ona1").anchor_gu = (0.0, 8100.0, 0.0)   # 8100 > 3000 + 5000
    assert "region-reaches-star" not in _slugs(validate(m))


def test_region_reaches_star_is_skipped_when_a_map_has_no_star():
    m = _valid()
    m.bodies = [b for b in m.bodies if b.orbits is not None]
    assert "region-reaches-star" not in _slugs(validate(m))
```

Add to `tests/tools/test_system_layout.py`:

```python
def test_the_first_orbit_is_pushed_out_until_no_region_reaches_the_star():
    """Voltair 1's sphere contained its star's centre. The innermost orbit must
    move out far enough to clear it -- and every other orbit moves with it."""
    s = SurveyedSystem(name="Tight", regions=[
        SurveyedRegion(set_name="Tight1", ordinal=1, bodies=[
            SurveyedBody("Sun", 4000.0, "", (-70000.0, 0.0, 0.0), True),
            SurveyedBody("Tight 1", 150.0, "p.nif", (0.0, 400.0, 0.0), False),
        ], content_extent_gu=20000.0, player_start_gu=(0.0, 0.0, 0.0)),
        SurveyedRegion(set_name="Tight2", ordinal=2, bodies=[
            SurveyedBody("Sun", 4000.0, "", (-70000.0, 0.0, 0.0), True),
            SurveyedBody("Tight 2", 150.0, "p.nif", (0.0, 400.0, 0.0), False),
        ], content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0)),
    ])
    m = layout(s)
    star = [b for b in m.bodies if b.orbits is None][0]
    for r in m.regions:
        gap = math.dist(r.anchor_gu, star.position_gu) - r.radius_gu - star.radius_gu
        assert gap > 0.0, f"{r.set_name} reaches the star by {-gap:.0f} GU"


def test_a_system_that_already_clears_its_star_is_not_moved():
    """The push must be corrective, not a blanket increase -- most systems are
    already clear and their numbers must not drift."""
    s = _sys_one_planet_per_region()
    t = LayoutTuning()
    m = layout(s, t)
    sun = [b for b in m.bodies if b.orbits is None][0]
    innermost = min(math.dist(b.position_gu, (0.0, 0.0, 0.0))
                    for b in m.bodies if b.orbits is not None)
    assert innermost == pytest.approx(sun.radius_gu + t.first_orbit_clearance_gu)


def test_ambiguities_reports_a_pushed_first_orbit():
    s = SurveyedSystem(name="Tight", regions=[SurveyedRegion(
        set_name="Tight1", ordinal=1, bodies=[
            SurveyedBody("Sun", 4000.0, "", (-70000.0, 0.0, 0.0), True),
            SurveyedBody("Tight 1", 150.0, "p.nif", (0.0, 400.0, 0.0), False),
        ], content_extent_gu=20000.0, player_start_gu=(0.0, 0.0, 0.0))])
    assert any("first orbit" in n.lower() for n in ambiguities(s))
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/tools/test_system_layout.py tests/unit/test_system_map_validate.py -v`
Expected: the validator tests fail on the missing rule; the layout tests fail
because the orbit is not pushed and `ambiguities()` says nothing about it.

- [ ] **Step 3: Implement**, per the shape above.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/tools/ tests/unit/test_system_map.py tests/unit/test_system_map_validate.py tests/unit/test_system_maps_valid.py -v`
Expected: all pass.

- [ ] **Step 5: Regenerate every map and confirm the finding is gone**

Run: `uv run python tools/gen_system_maps.py --list-ambiguities`

Then verify with this exact check — **zero** regions may reach their star:

```bash
uv run python -c "
import json, math, glob
bad = []
for f in sorted(glob.glob('engine/systems/maps/*.json')):
    d = json.load(open(f))
    star = next((b for b in d['bodies'] if b['orbits'] is None), None)
    if not star: continue
    for r in d['regions']:
        gap = math.dist(r['anchor_gu'], star['position_gu']) - r['radius_gu'] - star['radius_gu']
        if gap <= 0: bad.append((f, r['set_name'], round(gap)))
print('regions reaching their star:', len(bad)); [print(' ', *b) for b in bad]
"
```

Expected: `regions reaching their star: 0`.

Report which systems were pushed and by how much, from the ambiguity notes. The
seven known offenders live in Alioth, Cebalrai, Chambana, Itari, Serris, Voltair
and XiEntrades — expect those systems, and ideally only those, to move.

- [ ] **Step 6: Confirm nothing else changed**

Run: `uv run python tools/gen_system_maps.py --check --list-ambiguities`
Expected: all 32 `ok`, exit code 0, and the same seven clamped regions —
Alioth6, Beol1, Savoy2 (MIN floor); Geble4, OmegaDraconis1, Savoy1, XiEntrades4
(MAX cap). Clamps are about standoff, not orbit, so pushing an orbit must not
change them.

- [ ] **Step 7: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add tools/systems/layout.py engine/systems/validate.py engine/systems/maps \
        tests/tools/test_system_layout.py tests/unit/test_system_map_validate.py
git commit -m "fix(systems): no region sphere may reach its own star"
```

---

### Task 10: Star colours and nebulae, recovered from BC

**Why.** The survey reads `Sun_Create(radius, atmosphere, damage, baseTexture,
flareTexture)` and `MetaNebula_Create(r, g, b, ...)` but keeps only the radius,
throwing away every colour BC authored. Measured across the tree:

| Base texture | Systems |
|---|---|
| `SunYellow.tga` | Alioth, Geble, OmegaDraconis, Prendel, Savoy, Tevron |
| `SunRed.tga` | Albirea, Cebalrai, Ona, Serris, Voltair |
| `SunRedOrange.tga` | Ascella, Chambana, XiEntrades, Yiles |
| `SunBlueWhite.tga` | Artrus, Beol, Tezle, Starbase12, DryDock |
| *(none passed — BC's default)* | Biranu, Itari, Nepenthe, Poseidon, Riha |

Nebulae carry explicit RGB: `Belaruz1` is `#646392` with a 900 GU sphere at
set-local `(-17, 845, -30)`; `Vesuvi4` is `#9b5ab9` with a 1500 GU sphere at
`(0, 1500, 0)`.

**Belaruz and Vesuvi author no sun at all.** They currently get a generic
`default_sun_radius_gu` placeholder. They become **brown dwarfs** — dim, and
smaller than any real star in the data.

This is exactly what `Appearance` was split from identity for (spec §1): the
body keeps its name, radius and orbit; how it *looks* travels separately.

**Files:**
- Modify: `tools/systems/survey.py`, `tools/systems/layout.py`, `engine/systems/map.py`
- Modify: `engine/systems/maps/*.json` (regenerate all 32)
- Test: `tests/tools/test_system_survey.py`, `tests/tools/test_system_layout.py`, `tests/unit/test_system_map.py`

**Interfaces:**

- `SurveyedBody` gains `base_texture: str = ""` — the 4th `Sun_Create` argument,
  empty when BC passed fewer than four (that is BC's own default, not a failure).
- `SurveyedRegion` gains `nebula: dict | None = None` —
  `{"color": (r, g, b), "spheres": [(x, y, z, radius_gu), ...]}`, colours as
  0–1 floats exactly as BC wrote them, sphere positions in **set-local** GU.
- `Appearance` gains `star_class: str = ""` and `color: tuple | None = None`.
  `color` is `(r, g, b)` 0–1. `from_json` must restore `color` to a tuple like
  it does other vectors, or the round-trip test fails.
- `Region` gains `nebula: dict | None = None`, carried through `to_json` /
  `from_json` unchanged.
- `LayoutTuning` gains `brown_dwarf_radius_gu: float = 2000.0`, replacing
  `default_sun_radius_gu` for a system that authors no sun. Note this **shrinks**
  those two stars from 9000 GU, so their first orbits move in — that is correct
  and the existing `region-reaches-star` rule guards the result.

**Star class mapping** — put this table in `layout.py` as a module constant, keyed
by the texture's basename, with these exact values:

| `star_class` | from | `color` |
|---|---|---|
| `yellow` | `SunYellow.tga` | `(1.0, 0.85, 0.40)` |
| `red` | `SunRed.tga` | `(0.91, 0.35, 0.24)` |
| `red_orange` | `SunRedOrange.tga` | `(0.94, 0.54, 0.24)` |
| `blue_white` | `SunBlueWhite.tga` | `(0.74, 0.84, 1.0)` |
| `white` | anything else, including no texture (BC's default `SunBase`) | `(1.0, 0.95, 0.80)` |
| `brown_dwarf` | a system with no `Sun_Create` at all | `(0.42, 0.25, 0.18)` |

A system whose regions disagree about the texture takes the most common one, and
`ambiguities()` reports the disagreement — do not silently pick one.

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_system_survey.py`:

```python
def test_sun_textures_are_surveyed():
    """BC's Sun_Create carries the texture that gives a star its colour."""
    ona = survey_system("Ona")
    suns = [b for r in ona.regions for b in r.bodies if b.is_sun]
    assert suns, "Ona authors suns"
    assert all(s.base_texture.endswith("SunRed.tga") for s in suns), \
        [s.base_texture for s in suns]


def test_a_sun_with_no_texture_argument_surveys_as_empty_not_missing():
    """Itari calls Sun_Create with only three arguments -- BC's own default,
    not a parse failure."""
    itari = survey_system("Itari")
    suns = [b for r in itari.regions for b in r.bodies if b.is_sun]
    assert suns
    assert all(s.base_texture == "" for s in suns)


def test_nebulae_are_surveyed_with_colour_and_spheres():
    vesuvi = survey_system("Vesuvi")
    v4 = [r for r in vesuvi.regions if r.set_name == "Vesuvi4"][0]
    assert v4.nebula is not None
    r, g, b = v4.nebula["color"]
    assert (round(r, 3), round(g, 3), round(b, 3)) == (0.608, 0.353, 0.725)
    assert len(v4.nebula["spheres"]) == 1
    x, y, z, radius = v4.nebula["spheres"][0]
    assert (x, y, z) == pytest.approx((0.0, 1500.0, 0.0))
    assert radius == pytest.approx(1500.0)


def test_a_region_with_no_nebula_surveys_as_none():
    ona = survey_system("Ona")
    assert all(r.nebula is None for r in ona.regions)
```

`tests/tools/test_system_layout.py`:

```python
def test_the_star_takes_bcs_authored_colour():
    s = _sys_one_planet_per_region()
    for r in s.regions:
        for b in r.bodies:
            if b.is_sun:
                b.base_texture = "data/Textures/SunBlueWhite.tga"
    star = [b for b in layout(s).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "blue_white"
    assert star.appearance.color == pytest.approx((0.74, 0.84, 1.0))


def test_a_sun_with_no_texture_is_white_not_unclassified():
    s = _sys_one_planet_per_region()          # its fixtures carry no texture
    star = [b for b in layout(s).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "white"


def test_a_system_with_no_sun_gets_a_brown_dwarf():
    """Belaruz and Vesuvi author no Sun_Create at all."""
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi5", ordinal=5,
        bodies=[SurveyedBody("Geki", 110.0, "g.nif", (0.0, 538.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    t = LayoutTuning(brown_dwarf_radius_gu=2000.0)
    star = [b for b in layout(s, t).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "brown_dwarf"
    assert star.radius_gu == pytest.approx(2000.0)


def test_a_regions_nebula_is_carried_into_the_map():
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi4", ordinal=4, bodies=[],
        content_extent_gu=1870.0, player_start_gu=(0.0, 0.0, 0.0),
        nebula={"color": (0.608, 0.353, 0.725),
                "spheres": [(0.0, 1500.0, 0.0, 1500.0)]})])
    region = layout(s).region("Vesuvi4")
    assert region.nebula["color"] == pytest.approx((0.608, 0.353, 0.725))
    assert region.nebula["spheres"][0][3] == pytest.approx(1500.0)


def test_ambiguities_reports_a_system_whose_suns_disagree():
    s = _sys_one_planet_per_region()
    suns = [b for r in s.regions for b in r.bodies if b.is_sun]
    suns[0].base_texture = "data/Textures/SunRed.tga"
    suns[1].base_texture = "data/Textures/SunBlueWhite.tga"
    suns[2].base_texture = "data/Textures/SunBlueWhite.tga"
    notes = ambiguities(s)
    assert any("colour" in n.lower() or "texture" in n.lower() for n in notes)
```

`tests/unit/test_system_map.py` — extend the existing round-trip so the new
fields survive. Add to `_ona()`'s body an `Appearance(kind="nif", model="x.nif",
star_class="red", color=(0.91, 0.35, 0.24))`, give its `Region` a
`nebula={"color": (0.6, 0.35, 0.72), "spheres": [(0.0, 1500.0, 0.0, 1500.0)]}`,
and add:

```python
def test_star_colour_and_nebula_survive_the_round_trip():
    m = _ona()
    back = from_json(to_json(m))
    assert back.bodies[0].appearance.color == (0.91, 0.35, 0.24)
    assert isinstance(back.bodies[0].appearance.color, tuple)
    assert back.regions[0].nebula["spheres"][0] == (0.0, 1500.0, 0.0, 1500.0)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/tools/test_system_survey.py tests/tools/test_system_layout.py tests/unit/test_system_map.py -v`
Expected: failures on the missing `base_texture`, `nebula`, `star_class`,
`color`, and `brown_dwarf_radius_gu`.

- [ ] **Step 3: Implement**, per the Interfaces block and the mapping table.

In `survey.py`, `Sun_Create`'s arguments are positional and unquoted in places —
parse the 4th argument's string literal if present, else leave `""`. The
`MetaNebula_Create` colours are written as expressions like `100.0 / 255.0`;
evaluate them numerically rather than pattern-matching the literal text, and
read every `AddNebulaSphere` that follows in the same file.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/tools/ tests/unit/test_system_map.py tests/unit/test_system_map_validate.py tests/unit/test_system_maps_valid.py -v`
Expected: all pass.

- [ ] **Step 5: Regenerate and check the colours landed**

Run: `uv run python tools/gen_system_maps.py --list-ambiguities`

Then verify:

```bash
uv run python -c "
import json, glob, collections
c = collections.Counter()
neb = []
for f in sorted(glob.glob('engine/systems/maps/*.json')):
    d = json.load(open(f))
    star = next((b for b in d['bodies'] if b['orbits'] is None), None)
    if star: c[star['appearance'].get('star_class')] += 1
    for r in d['regions']:
        if r.get('nebula'): neb.append((d['system'], r['set_name'], r['nebula']['color']))
print('star classes:', dict(c))
print('nebulae:', neb)
"
```

Expected: `yellow` 6, `red` 5, `red_orange` 4, `blue_white` 5, `white` 5,
`brown_dwarf` 2 (Belaruz, Vesuvi) — plus the 5 `Multi*` and `QuickBattle`
placeholder systems, whose class you should report rather than predict. Nebulae:
Belaruz1 and Vesuvi4 with the colours above.

- [ ] **Step 6: Confirm nothing regressed**

Run: `uv run python tools/gen_system_maps.py --check --list-ambiguities`
Expected: all 32 `ok`, exit code 0; the same seven clamped regions
(Alioth6, Beol1, Savoy2 min; Geble4, OmegaDraconis1, Savoy1, XiEntrades4 max).
Belaruz and Vesuvi's first orbits will move because their star shrank from 9000
to 2000 GU — report the new values. No region may reach its star.

- [ ] **Step 7: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add tools/systems/survey.py tools/systems/layout.py engine/systems/map.py \
        engine/systems/maps tests/tools/test_system_survey.py \
        tests/tools/test_system_layout.py tests/unit/test_system_map.py
git commit -m "feat(systems): recover BC's star colours and nebulae"
```

---

### Task 11: Belaruz has a living star; Vesuvi has a remnant

**Why.** Both systems currently get `brown_dwarf`, a generic fallback for
"authors no `Sun_Create`". The nav-map descriptions shipped in `21ed51cc` say
something else, and they are right:

- **Vesuvi** — the star's core was destabilised by a Kessok Solarformer (BC's
  own opening: *"the star… its core is destabilising!"*). What remains is a
  **hot remnant**: small, luminous, blue-white. BC's own lighting agrees —
  Vesuvi 5's authored directional is `(0.6, 0.6, 0.8)`, and across the 18
  systems that author a star texture the light matches the star in 17.
- **Belaruz** — not a casualty. A living system crossing a dust cloud, the star
  brighter for the material falling into it. Belaruz 1 carries the **brightest
  directional in the game**, pure white at full strength, which a dead star
  cannot produce.

Player-facing text currently contradicts the data. That is the drift this whole
branch has been guarding against, so it gets closed rather than noted.

**Files:**
- Modify: `tools/systems/layout.py`, `tools/gen_system_maps.py`
- Modify: `engine/systems/maps/belaruz.json`, `engine/systems/maps/vesuvi.json`
- Test: `tests/tools/test_system_layout.py`, `tests/unit/test_system_maps_valid.py`

**Interfaces:**

- `_STAR_CLASS_TABLE` gains `remnant_hot: (0.78, 0.86, 1.0)`. It is not keyed by
  a texture — no BC texture produces it — so key the table by class name and
  look textures up through a separate texture→class map, or add it alongside
  with a comment saying why it has no texture. Either shape is fine; say which.
- **A per-system star override**, read from the map's `overrides.star`:

```json
"overrides": {
  "star": {
    "star_class": "white",
    "color": [1.0, 0.97, 0.93],
    "radius_gu": 8000.0,
    "why": "Belaruz is not a casualty ..."
  }
}
```

  Every field optional except `star_class`. An absent `color` falls back to the
  class table; an absent `radius_gu` leaves the derived radius alone. `why` is
  documentation and is never read by code.

- `layout(s, tuning=None, pins=None, star=None)` — `star` is that dict or None.
  When given it wins over everything derived from BC. When absent, behaviour is
  exactly as today, including `brown_dwarf` for the seven `Multi*` systems.
- `gen_system_maps.star_from(m)` — reads `m.overrides["star"]`, returning the
  dict or `None`. `generate()` passes it into `layout()` the same way it already
  passes `pins_from(old)`.

**Ruling to implement, not to revisit:** Belaruz's class is `white` with an
explicit near-pure colour and a radius of **8000 GU** — an ordinary star made
bright by infall, rather than a new class invented for one system. The accretion
is fiction the description carries and the renderer may express later; it is not
a star class. Vesuvi keeps radius **2000 GU** so its geometry does not move.

**Belaruz's orbits WILL move** (star 2000 → 8000 GU, and the first orbit is
`sun_radius + clearance`). That is correct. `region-reaches-star` guards it.

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_system_layout.py`:

```python
def _sunless(name="Vesuvi", set_name="Vesuvi5"):
    return SurveyedSystem(name=name, regions=[SurveyedRegion(
        set_name=set_name, ordinal=5,
        bodies=[SurveyedBody("Geki", 110.0, "g.nif", (0.0, 538.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])


def test_a_star_override_wins_over_the_derived_class():
    m = layout(_sunless(), star={"star_class": "remnant_hot"})
    star = [b for b in m.bodies if b.orbits is None][0]
    assert star.appearance.star_class == "remnant_hot"
    assert star.appearance.color == pytest.approx((0.78, 0.86, 1.0))


def test_a_star_override_may_set_an_explicit_colour_and_radius():
    m = layout(_sunless(), star={"star_class": "white",
                                 "color": [1.0, 0.97, 0.93],
                                 "radius_gu": 8000.0})
    star = [b for b in m.bodies if b.orbits is None][0]
    assert star.appearance.color == pytest.approx((1.0, 0.97, 0.93))
    assert star.radius_gu == pytest.approx(8000.0)


def test_a_bigger_overridden_star_pushes_its_first_orbit_out():
    """first_orbit is measured from the star's SURFACE, so a larger star must
    carry every orbit outward rather than swallowing the innermost planet."""
    t = LayoutTuning()
    small = layout(_sunless())
    big = layout(_sunless(), star={"star_class": "white", "radius_gu": 8000.0})
    d_small = math.dist(small.body("Geki").position_gu, (0.0, 0.0, 0.0))
    d_big = math.dist(big.body("Geki").position_gu, (0.0, 0.0, 0.0))
    assert d_small == pytest.approx(t.brown_dwarf_radius_gu
                                    + t.first_orbit_clearance_gu)
    assert d_big == pytest.approx(8000.0 + t.first_orbit_clearance_gu)


def test_no_override_leaves_todays_behaviour_untouched():
    star = [b for b in layout(_sunless()).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "brown_dwarf"
```

`tests/unit/test_system_maps_valid.py`:

```python
def test_belaruz_and_vesuvi_carry_the_stars_their_descriptions_claim():
    """The nav-map text says Belaruz's star is alive and Vesuvi's is a remnant.
    Data and prose disagreeing is exactly the drift this branch exists to stop."""
    belaruz = load("belaruz")
    star = [b for b in belaruz.bodies if b.orbits is None][0]
    assert star.appearance.star_class == "white"
    assert star.radius_gu == pytest.approx(8000.0)

    vesuvi = load("vesuvi")
    star = [b for b in vesuvi.bodies if b.orbits is None][0]
    assert star.appearance.star_class == "remnant_hot"

    assert not any(b.appearance.star_class == "brown_dwarf"
                   for name in ("belaruz", "vesuvi")
                   for b in load(name).bodies)
```

- [ ] **Step 2: Run them and confirm they fail** —
`uv run pytest tests/tools/test_system_layout.py tests/unit/test_system_maps_valid.py -v`

- [ ] **Step 3: Implement**, per the Interfaces block.

- [ ] **Step 4: Author the two overrides**, each with a `why` line: Belaruz as
specified above; Vesuvi `{"star_class": "remnant_hot", "radius_gu": 2000.0}`.
Add them beside the existing `notes` — do not disturb those.

- [ ] **Step 5: Regenerate and verify**

Run: `uv run python tools/gen_system_maps.py --system Belaruz --system Vesuvi --list-ambiguities`

Then:

```bash
uv run python -c "
import json
for n in ('belaruz', 'vesuvi'):
    d = json.load(open(f'engine/systems/maps/{n}.json'))
    s = next(b for b in d['bodies'] if b['orbits'] is None)
    print(n, s['appearance']['star_class'], s['radius_gu'], s['appearance']['color'])
"
```

Expected: `belaruz white 8000.0 [1.0, 0.97, 0.93]` and `vesuvi remnant_hot 2000.0
[0.78, 0.86, 1.0]`. Report Belaruz's new first-orbit distance.

- [ ] **Step 6: Confirm nothing else moved**

`uv run python tools/gen_system_maps.py --check --list-ambiguities` — all 32
`ok`, exit 0; the same seven clamped regions (Alioth6, Beol1, Savoy2 min;
Geble4, OmegaDraconis1, Savoy1, XiEntrades4 max); no region reaches its star;
and `git status --porcelain engine/systems/maps` shows **only** belaruz.json and
vesuvi.json.

- [ ] **Step 7: Gate** — `scripts/check_tests.sh`, expect
`OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add tools/systems/layout.py tools/gen_system_maps.py \
        engine/systems/maps/belaruz.json engine/systems/maps/vesuvi.json \
        tests/tools/test_system_layout.py tests/unit/test_system_maps_valid.py
git commit -m "fix(systems): Belaruz's star is alive, Vesuvi's is a remnant"
```

## Self-review

**Spec coverage (§1 only — §2–§6 are the second plan):**

| Spec requirement | Task |
|---|---|
| One file per system, checked in | 1, 5 |
| Bodies: identity separate from appearance | 1 |
| Regions: anchor, radius, owned bodies | 1 |
| Pins | 2 (validated), 3 (surveyed), 8 (honoured by the layout) |
| Overrides block the generator never rewrites | 5 |
| Generator reads the SDK | 3 |
| Radius measured from non-body content, system + mission files | 3 |
| Regions ordered by trailing number | 3, 4 |
| Sun at centre, planets on orbits, moons around planets | 4 |
| Anchor rule: centroid displaced along the original view direction | 4 |
| Lighting direction not preserved (per-set suns discarded) | 4 |
| Unnumbered regions flagged | 4 |
| Moon-or-planet guess flagged | 4 |
| Validator in the gate | 2, 5 |
| Ona first, reviewed before the rest | 5 (checkpoint), 7 |
| Project-local, no hardcoded BC path | 1, 3 |
| Bodies keep BC's relative sizes | 6 |
| Anchors reproduce BC's per-region framing | 6 |

**Placeholders:** none. Every code step carries the code; every test step carries
the assertions; every run step carries the command and the expected result.

**Type consistency:** `SurveyedBody.offset_gu`, `Body.position_gu`,
`Region.anchor_gu` are all 3-tuples of float in GU. `layout()` consumes
`SurveyedSystem` and produces `SystemMap`; `generate()` returns
`(SystemMap, list[str])`; `validate()` returns `list[Problem]` and is called with
the same `sdk_set_names` keyword in Tasks 2, 5 and 6. `ambiguities()` takes a
`SurveyedSystem`, not a `SystemMap` — it reports on the *input*, since the
guesses are made while reading.

**Known soft spots, both deliberate:**

1. **Multi-body anchors are approximate by design.** The anchor is
   `centroid − view × standoff` for every region; only the single-primary case
   (64 of 89 regions) reproduces BC's bearing exactly. Task 4 Step 4 says why,
   and says not to "fix" it.
2. **The sun carries an empty appearance model.** BC builds suns with
   `Sun_Create(radius, atmosphere, damage, baseTexture, flareTexture)` — two
   textures, not a NIF — so `Appearance(kind="nif", model="")` is a placeholder
   for the *data* plan. How a sun is realized is a runtime question and belongs
   to the second plan, which may add `kind="bc_sun"` with the two texture paths.
   Nothing in this plan reads the field.
