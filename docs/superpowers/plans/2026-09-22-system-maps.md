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
| `pin-respected` | For each pinned body, `position_gu - anchor_gu` equals the pin's original set-local offset within 1 GU. Skipped when `pins` is None. |
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
                continue
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
Expected: PASS (11 tests)

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
    `region_margin_gu = 1500.0`
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
            distance = primary_radius * (4.0 + 1.5 * j)
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
Expected: PASS (14 tests)

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
  - `main(argv=None) -> int` — CLI. `--system NAME` (repeatable, default: all),
    `--check` (validate only, write nothing), `--list-ambiguities`.

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
    problems = validate(m, sdk_set_names=[r.set_name for r in sdk.regions])
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


def generate(system: str):
    surveyed = survey_system(system)
    fresh = layout(surveyed)
    old = None
    if system.lower() in available():
        try:
            old = load(system)
        except Exception:
            old = None
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
        m, notes = generate(name)
        surveyed = survey_system(name)
        problems = validate(m, sdk_set_names=[r.set_name for r in surveyed.regions])
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
Expected: PASS (7 tests, one parametrised over `ona`)

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

### Task 6: The remaining 24 systems

**Prerequisite:** the Task 5 checkpoint is signed off and `LayoutTuning` defaults
are settled. Do not start this task before that.

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

## Self-review

**Spec coverage (§1 only — §2–§6 are the second plan):**

| Spec requirement | Task |
|---|---|
| One file per system, checked in | 1, 5 |
| Bodies: identity separate from appearance | 1 |
| Regions: anchor, radius, owned bodies | 1 |
| Pins | 2 (validated), 3 (surveyed) |
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
| Ona first, reviewed before the rest | 5 (checkpoint), 6 |
| Project-local, no hardcoded BC path | 1, 3 |

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
