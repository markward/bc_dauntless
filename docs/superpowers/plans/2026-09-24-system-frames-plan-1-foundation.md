# System Frames — Plan 1: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the durable half of the reference branch on a fresh base, at the doubled orbital scale, with every region set mapped the moment BC creates it and no set destroyed by departure.

**Architecture:** Merge the reference branch's last pre-residency commit (`67091184`) and six small independent fixes; regenerate the 32 system maps with doubled orbit spacing and raise the far plane to match; guard the ×20 radius relation in the validator; stop warp departure deleting the set you left (keeping only the render teardown); and apply the system map inside every mapped region module's `Initialize()` via the existing post-exec SDK hook, with a mapped flag and a loud alarm for a mapped-frame set realized without it.

**Tech Stack:** Python 3 (engine, tools, pytest), the project's SDK loaders (`tools/mission_harness.py` + twin in `tests/conftest.py`), git.

**Spec:** `docs/superpowers/specs/2026-09-24-system-frames-design.md` — read it first. This plan implements the spec's "Plans, in order → 1. Foundation", plus §2 (map application) and the lifetime half of §3.

## Global Constraints

- Work only in the worktree `.claude/worktrees/system-frames` on branch `feat/system-frames`. Never `cd` to the main checkout.
- **Banned git:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs only. To mutate a file temporarily for a mutation proof: `cp file /tmp/bak` → edit → run → `cp /tmp/bak file` → `diff file /tmp/bak` (must be silent).
- Never spell `game` or `sdk` as a path segment in engine/tools/tests code; use `engine.paths` (`paths.sdk_scripts()`, `paths.game_asset(rel)`). Never capture a path at import. `tests/unit/test_path_indirection.py` enforces this.
- All spatial quantities are game units (GU); name variables `*_gu`, never `*_m`.
- Never launch the game. Mark does live passes.
- The gate is `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). Never call a failure "pre-existing" by eyeball — the gate decides. Baseline today: `cat tests/known_failures.txt`.
- Both SDK loaders must stay in sync (`tools/mission_harness.py` `_SDKLoader.exec_module` and its twin in `tests/conftest.py`). A change to one is a change to both.
- **Only orbit distance doubles.** Body radii (×20 of BC's), moon spacing (proportional to planet radius) and framing (standoff from the planet) are unchanged.

## Review Focus

Input classes the spec implies that no task's core tests exercise — each has a test added to its owning task:

1. **A region module's `Initialize()` called twice** (a mission re-running setup) must leave a body at the map radius, not 20×20 of BC's. → Task 5, `test_initialize_twice_is_idempotent`.
2. **A region module whose `Initialize()` raises** must propagate the error and must not map a stale set of the same name left from earlier. → Task 5, `test_a_raising_initialize_propagates_and_maps_nothing`.
3. **Warping back into a set you left** must draw its planet at the map radius — the DRAWN-90 / TARGETED-1800 split, re-entered through teardown + re-realize. → Task 4, `test_rerealize_after_departure_uses_the_current_radius`.
4. **A BC waypoint that now sits inside a ×20 planet.** Scaling a body ×20 at a new position could swallow a waypoint BC placed beside it (ships would spawn inside a planet). → Task 3, `test_no_region_waypoint_is_inside_a_mapped_body` — if it fails, that is a real finding: STOP and report, do not adjust the test.
5. **A vacuous radius-ratio rule** — if survey and map body names never match, the rule silently checks nothing. → Task 3, `test_the_ratio_rule_actually_matches_every_mapped_body`.

---

### Task 1: Carry the durable slice onto the new branch

**Files:**
- Merge: `67091184` (brings `engine/systems/`, `tools/systems/`, `tools/gen_system_maps.py`, the 32 maps, far plane 500,000, `sun_pass` conditional virtual distance, their tests, and the two superseded specs)
- Cherry-pick: `3b55ab30`, `676cf193`, `07c396b5`, `c2f9d0c2`, `fab31c8a`, `c31a5a0d`
- Modify: `docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`, `docs/superpowers/specs/2026-09-23-celestial-layer-design.md` (superseded banner)

**Interfaces:**
- Produces: `engine.systems.map` (`available()`, `load(system)`, `save(m)`, `SystemMap`, `Body`, `Region`), `engine.systems.resolve` (`for_set(set_name) -> (SystemMap, Region) | None`, `system_of(set_name) -> str | None`, `anchor_of(set_name)`), `engine.systems.apply_map.apply_to_set(pSet, set_name) -> bool`, `engine.systems.validate.validate(m, *, sdk_set_names=None, pins=None) -> list[Problem]`, `tools.systems.layout.LayoutTuning`, `tools.systems.survey.survey_system(name)` / `system_names()`, `engine.cameras.SCENE_FAR_GU`, `tests/unit/test_camera_far_plane.py::widest_sightline_gu()`.

This task was dry-run on 2026-09-24 in a throwaway worktree: the merge and the first five cherry-picks apply cleanly; `c31a5a0d` conflicts in `tests/conftest.py` only.

- [ ] **Step 1: Confirm the starting point**

Run: `git -C .claude/worktrees/system-frames log --oneline -2 && git -C .claude/worktrees/system-frames status --short`
Expected: HEAD is the spec commit(s) on `feat/system-frames`; no uncommitted changes other than this plan file if not yet committed.

- [ ] **Step 2: Merge the durable base**

```bash
git merge --no-edit 67091184
```
Expected: `Auto-merging engine/host_loop.py`, merge commit created, no conflicts.

- [ ] **Step 3: Cherry-pick the five clean commits, in this order**

```bash
git cherry-pick -x 3b55ab30 676cf193 07c396b5 c2f9d0c2 fab31c8a
```
Expected: five commits, no conflicts. (Order matters: the three `apply_map.py` commits are sequential edits to one file.)

- [ ] **Step 4: Cherry-pick the throttle-leak fix and resolve its conftest conflict**

```bash
git cherry-pick -x c31a5a0d
```
Expected: `CONFLICT (content): Merge conflict in tests/conftest.py`. `engine/host_loop.py` applies cleanly.

Resolve `tests/conftest.py` by hand: in `_reset_leakable_engine_globals`, the conflict is between the branch's `_hl._reset_celestial_proxies()` context (which does NOT exist here and must NOT be added) and the new block. The resolved file must contain exactly this block, placed immediately before the line `# Camera shake: the Modern VFX row flips a module global, so a test that`, and no `_reset_celestial_proxies` anywhere:

```python
    # Hit-feedback emission throttles. All three are keyed by id(ship) and
    # id() is a RECYCLED address, so a dead ship's entry is inherited by a
    # LATER test's ship that happens to land there. Every decal test pins the
    # clock to the same instant, so an inherited entry makes `now - last == 0`
    # and the decal is throttled away -- the test fails, alone it passes, and
    # the culprit is whichever earlier test allocated. Diagnosed 2026-09-25
    # from test_decal_emission.py::test_dent_weight_reaches_the_decal, which
    # flaked only in full-suite runs.
    try:
        from engine.appc import hit_feedback as _hf
        _hf._last_decal_emit.clear()
        _hf._last_carve_time.clear()
        _hf._pending_carve_strength.clear()
    except Exception:
        pass
```

Then:
```bash
grep -n "_reset_celestial_proxies\|<<<<<<<\|>>>>>>>" tests/conftest.py   # expect NO output
git add tests/conftest.py
git -c core.editor=true cherry-pick --continue
```

- [ ] **Step 5: Mark the two inherited specs superseded**

Insert at the very top of BOTH `docs/superpowers/specs/2026-09-22-in-system-navigation-design.md` and `docs/superpowers/specs/2026-09-23-celestial-layer-design.md`:

```markdown
> **SUPERSEDED** by `docs/superpowers/specs/2026-09-24-system-frames-design.md`.
> Kept as the record of how the design got here. Several decisions below are
> reversed there — see its "Decisions this reverses". Do not implement from
> this document.

```

- [ ] **Step 6: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures.` with the baseline count from `tests/known_failures.txt`. (The C++ build picks up the `sun_pass` change from the merge.) If any failure is named, STOP and report it with output — do not fix unrelated code in this task.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-09-22-in-system-navigation-design.md docs/superpowers/specs/2026-09-23-celestial-layer-design.md
git commit -m "docs(systems): mark the two inherited navigation specs superseded"
```

---

### Task 2: Double the orbits, regenerate the maps, raise the far plane

**Files:**
- Modify: `tools/systems/layout.py` (`LayoutTuning` defaults)
- Regenerate: `engine/systems/maps/*.json` (all 32, via the generator — never hand-edit)
- Modify: `engine/cameras/__init__.py` (`SCENE_FAR_GU` and its comment), `engine/cameras/dof.py` (comment only, if it cites a far-plane figure)
- Modify (only if its test fails): `engine/systems/descriptions.json`
- Test: `tests/unit/test_system_maps_valid.py`

**Interfaces:**
- Consumes: `LayoutTuning`, `tools/gen_system_maps.py`, `widest_sightline_gu()` (Task 1).
- Produces: `LayoutTuning.first_orbit_clearance_gu == 60000.0`, `LayoutTuning.orbit_step_gu == 52000.0`; regenerated maps; `SCENE_FAR_GU` covering the new widest sightline.

- [ ] **Step 1: Record the before-figures for the report**

Run and save the output (the task report must include it):
```bash
uv run python - <<'EOF'
import math
from engine.systems import map as sm
from tests.unit.test_camera_far_plane import widest_sightline_gu
print("widest sightline before:", round(widest_sightline_gu()))
m = sm.load("ona"); a = next(r for r in m.regions if r.set_name == "Ona1").anchor_gu
for b in m.bodies:
    d = math.dist(a, b.position_gu)
    print(f"  from Ona1 anchor: {b.name:8s} range {d:10.0f} GU  apparent {math.degrees(2*math.atan(b.radius_gu/d)):6.2f} deg")
EOF
```

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_system_maps_valid.py`:

```python
def test_planets_orbit_at_the_doubled_scale():
    """Orbits double; radii do not (spec: "Scale"). Live feedback: the system
    read as too small because of SPACING, so the first orbit and the orbit step
    both double while every body keeps its x20 radius. The first orbit is a
    MINIMUM measured from the star's surface -- the push logic may move a
    planet further out, never nearer."""
    import math
    from engine.systems import map as system_map
    from tools.systems.layout import LayoutTuning

    t = LayoutTuning()
    assert t.first_orbit_clearance_gu == 60000.0
    assert t.orbit_step_gu == 52000.0
    checked = 0
    for name in system_map.available():
        m = system_map.load(name)
        star = next(b for b in m.bodies if b.orbits is None)
        for b in m.bodies:
            if b.orbits == star.name:
                d = math.dist(b.position_gu, star.position_gu)
                assert d >= star.radius_gu + t.first_orbit_clearance_gu - 1e-6, (
                    f"{name}/{b.name} orbits at {d:.0f} GU, inside the doubled "
                    f"first orbit {star.radius_gu + t.first_orbit_clearance_gu:.0f}")
                checked += 1
    # 87 bodies orbit their star directly across the 32 maps (measured
    # 2026-09-24); the rest are moons. Exact, so a loop that silently stops
    # seeing the maps cannot pass.
    assert checked == 87, f"{checked} planets checked, expected 87"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_system_maps_valid.py::test_planets_orbit_at_the_doubled_scale -v`
Expected: FAIL on `assert t.first_orbit_clearance_gu == 60000.0` (it is 30000.0).

- [ ] **Step 4: Double the two spacing knobs**

In `tools/systems/layout.py`, `LayoutTuning`:

```python
    first_orbit_clearance_gu: float = 60000.0
    orbit_step_gu: float = 52000.0
```

Leave every other field unchanged (radius scales, `framing_scale`, standoff factors, moon factors, margins).

- [ ] **Step 5: Run the map tests — the checked-in maps are now stale**

Run: `uv run pytest tests/unit/test_system_maps_valid.py -q`
Expected: the new test fails on the distance assert (maps still at the old scale) AND `test_regenerating_any_map_is_idempotent[...]` fails for every system. That idempotency failure is the guard proving the maps must be regenerated.

- [ ] **Step 6: Regenerate every map through the generator**

Run: `uv run python tools/gen_system_maps.py`
Expected: 32 lines `<System>: N regions, M bodies -- ok <path>` and exit code 0. If ANY system prints `PROBLEM(S)`, STOP and report the full output — a validator rule failing at the new scale is a design finding, not something to tune away in this task.

- [ ] **Step 7: Run the map tests again**

Run: `uv run pytest tests/unit/test_system_maps_valid.py tests/tools/ tests/unit/test_system_map.py tests/unit/test_system_map_validate.py tests/unit/test_system_resolve.py tests/unit/test_apply_system_map.py tests/unit/test_system_descriptions.py -q`
Expected: all pass except possibly `test_system_descriptions.py` cases whose TEXT cites orbital distances. If one fails for that reason, update only the cited figure in `engine/systems/descriptions.json` to the regenerated map's value (compute it from the map, do not estimate), and re-run. Any other failure: STOP and report.

- [ ] **Step 8: Run the far-plane guard — it now fails**

Run: `uv run pytest tests/unit/test_camera_far_plane.py -v`
Expected: FAIL — `test_the_exterior_and_viewscreen_cameras_reach_the_whole_system` reports the far plane 500,000 GU does not cover the new widest sightline (expected ≈ 930,000 GU).

- [ ] **Step 9: Raise the far plane to the derived figure**

Compute: `uv run python -c "from tests.unit.test_camera_far_plane import widest_sightline_gu as w; import math; x=w(); print(x, math.ceil(x*1.05/100000)*100000)"`

Set `SCENE_FAR_GU` in `engine/cameras/__init__.py` to the second number printed (the smallest multiple of 100,000 GU that is ≥ 1.05 × the widest sightline; expected `1_000_000.0`). Rewrite the comment above it so it states: the figure is derived from the maps by `tests/unit/test_camera_far_plane.py::widest_sightline_gu` (never restated as fact here), orbits doubled 2026-09-24 per the system-frames spec, and depth precision is governed by the near plane. If `engine/cameras/dof.py` has a comment citing a far-plane figure, replace the figure with a reference to `SCENE_FAR_GU`.

- [ ] **Step 10: Verify, including the precision guard**

Run: `uv run pytest tests/unit/test_camera_far_plane.py tests/unit/test_dof_focus.py tests/unit/test_dof_host_push.py -v`
Expected: PASS, including `test_depth_precision_is_effectively_unchanged`.

- [ ] **Step 11: Record the after-figures**

Re-run the Step 1 script. The report must include both tables side by side. Expected shape: ranges to other worlds ≈ doubled; apparent sizes of other worlds ≈ halved; Ona 1's own range and apparent size essentially unchanged (framing is unchanged).

- [ ] **Step 12: Run the gate and commit**

Run: `scripts/check_tests.sh` → expected `OK — no new failures.`

```bash
git add tools/systems/layout.py engine/systems/maps/ engine/cameras/__init__.py tests/unit/test_system_maps_valid.py
git add engine/cameras/dof.py engine/systems/descriptions.json   # only if changed
git commit -m "feat(systems): double orbital spacing, regenerate all 32 maps, far plane to match"
```

---

### Task 3: Guard the ×20 radius relation, and waypoints outside bodies

**Files:**
- Modify: `engine/systems/validate.py` (new optional rule `radius-ratio`)
- Modify: `tools/systems/survey.py` (new `bc_radii(surveyed)`)
- Modify: `tools/gen_system_maps.py` (pass the new inputs in `main()`)
- Test: `tests/unit/test_system_map_validate.py` (rule unit tests), `tests/unit/test_system_maps_valid.py` (gate over real maps)

**Interfaces:**
- Consumes: `validate()`, `survey_system()`, `LayoutTuning`.
- Produces: `validate(m, *, sdk_set_names=None, pins=None, bc_radii=None, radius_scale=None) -> list[Problem]` — the rule runs only when both new args are given; `tools.systems.survey.bc_radii(surveyed) -> dict[tuple[str, str], float]` keyed `(region_set_name, body_name)`, suns excluded.

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/unit/test_system_map_validate.py`. Build the map with the SAME helper this file already uses to construct a minimal valid `SystemMap` (read the top of the file; reuse it — do not invent a second fixture style). The tests must assert:

```python
def test_radius_ratio_rule_flags_a_body_off_the_scale(<existing minimal-map fixture>):
    # A body whose map radius is 19x its BC radius, not 20x.
    m = <minimal valid map with one region "R1" owning body "P" of radius_gu 1900.0>
    probs = validate(m, bc_radii={("R1", "P"): 100.0}, radius_scale=20.0)
    assert [p.rule for p in probs] == ["radius-ratio"]
    assert "R1/P" in probs[0].detail


def test_radius_ratio_rule_accepts_the_exact_scale(<fixture>):
    m = <same map, body radius_gu 2000.0>
    assert [p for p in validate(m, bc_radii={("R1", "P"): 100.0}, radius_scale=20.0)
            if p.rule == "radius-ratio"] == []


def test_radius_ratio_rule_is_off_without_inputs(<fixture>):
    m = <same map, body radius_gu 1900.0>
    assert [p for p in validate(m) if p.rule == "radius-ratio"] == []


def test_radius_ratio_rule_is_region_scoped(<fixture>):
    """Body names collide across regions (Geble3 and Geble4 both have a
    "Moon 1"). The lookup must match name AND owner_region."""
    m = <map with regions "R1","R2", each owning a body named "Moon 1";
         R1's radius_gu 2000.0, R2's radius_gu 600.0>
    probs = validate(m, bc_radii={("R1", "Moon 1"): 100.0, ("R2", "Moon 1"): 30.0},
                     radius_scale=20.0)
    assert [p for p in probs if p.rule == "radius-ratio"] == []
```

Replace each `<...>` with concrete construction using the file's existing helper; the assertions are fixed.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_system_map_validate.py -k radius_ratio -v`
Expected: FAIL with `TypeError: validate() got an unexpected keyword argument 'bc_radii'`.

- [ ] **Step 3: Implement the rule**

In `engine/systems/validate.py` add (near the other private helpers; `math` is already imported or import it):

```python
def _radius_ratio_problems(m, bc_radii: dict, radius_scale: float) -> list:
    """Every mapped body is exactly radius_scale x the radius BC authored.

    Only orbit DISTANCE is a layout knob that moves between regenerations;
    body size is BC's radius times one scale. A regeneration that breaks this
    for one body has changed what the player sees without anyone asking.
    Region-scoped: BC display names collide within a system (Geble3 and Geble4
    both name a "Moon 1"), so match name AND owner_region, never name alone.
    """
    problems = []
    for (region_name, body_name), bc_radius in sorted(bc_radii.items()):
        body = next((b for b in m.bodies
                     if b.name == body_name and b.owner_region == region_name), None)
        if body is None:
            continue
        want = radius_scale * bc_radius
        if not math.isclose(body.radius_gu, want, rel_tol=1e-9, abs_tol=1e-9):
            problems.append(Problem(
                rule="radius-ratio",
                detail=f"{region_name}/{body_name}: map radius {body.radius_gu} GU "
                       f"is not {radius_scale} x BC's {bc_radius} = {want} GU"))
    return problems
```

Extend `validate`'s signature to `validate(m, *, sdk_set_names=None, pins=None, bc_radii=None, radius_scale=None)`, document the two new args in its docstring, and just before it returns:

```python
    if bc_radii is not None and radius_scale is not None:
        problems.extend(_radius_ratio_problems(m, bc_radii, radius_scale))
```

(If `validate` bails out early on a structurally broken map, keep that behaviour — add the rule only on the path that reaches the end.)

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `uv run pytest tests/unit/test_system_map_validate.py -v`
Expected: all PASS.

- [ ] **Step 5: Add `bc_radii` to the survey and wire the CLI**

In `tools/systems/survey.py`:

```python
def bc_radii(surveyed) -> dict:
    """{(region_set_name, body_name): BC radius in GU} for every non-sun body.

    The input the validator's radius-ratio rule compares the map against.
    Suns are excluded: the star is scaled by sun_radius_scale, not the body
    scale, and systems with no Sun_Create get a generated brown dwarf.
    """
    return {(r.set_name, b.name): b.radius_gu
            for r in surveyed.regions for b in r.bodies if not b.is_sun}
```

In `tools/gen_system_maps.py` `main()`, import `bc_radii` and `LayoutTuning` alongside the existing imports, and extend the existing `validate(...)` call:

```python
        problems = validate(m, sdk_set_names=[r.set_name for r in surveyed.regions
                                              if r.menu_listed],
                            pins=pins_from(m),
                            bc_radii=bc_radii(surveyed),
                            radius_scale=LayoutTuning().planet_radius_scale)
```

- [ ] **Step 6: Write the gate tests over the real maps (Review Focus 4 and 5)**

Append to `tests/unit/test_system_maps_valid.py`:

```python
def test_every_mapped_body_is_its_bc_radius_times_the_scale():
    from engine.systems import map as system_map
    from engine.systems.validate import validate
    from tools.systems.layout import LayoutTuning
    from tools.systems.survey import bc_radii, survey_system, system_names

    scale = LayoutTuning().planet_radius_scale
    assert LayoutTuning().moon_radius_scale == scale, (
        "the ratio rule assumes planets and moons share one scale")
    bad = []
    for name in system_names():
        m = system_map.load(name)
        bad += [p.detail for p in validate(m, bc_radii=bc_radii(survey_system(name)),
                                           radius_scale=scale)
                if p.rule == "radius-ratio"]
    assert bad == []


def test_the_ratio_rule_actually_matches_every_mapped_body():
    """Guards against a vacuous pass: if survey names stopped matching map
    names, the rule would check nothing and still be green. 118 is the
    measured count of (region, body) pairs across the 32 maps (2026-09-24);
    regeneration does not change which bodies exist, only where they are."""
    from engine.systems import map as system_map
    from tools.systems.survey import bc_radii, survey_system, system_names

    matched = 0
    for name in system_names():
        m = system_map.load(name)
        for (region_name, body_name) in bc_radii(survey_system(name)):
            if any(b.name == body_name and b.owner_region == region_name for b in m.bodies):
                matched += 1
    assert matched == 118


def test_no_region_waypoint_is_inside_a_mapped_body():
    """A x20 body at a new position must not swallow a waypoint BC placed in
    that region -- ships placed there would spawn inside a planet. Checks the
    region module's own LoadPlacements (Systems/<Sys>/<Region>.py). If this
    FAILS it is a real layout finding: report it, do not loosen the test."""
    import math
    from engine.systems import map as system_map
    from tools.systems import survey

    offenders = []
    for name in survey.system_names():
        m = system_map.load(name)
        for region in m.regions:
            path = survey._systems_dir() / name / f"{region.set_name}.py"
            if not path.exists():
                continue
            placements = survey._placements(survey._read(path))
            for b in m.bodies:
                if b.owner_region != region.set_name:
                    continue
                local = tuple(p - a for p, a in zip(b.position_gu, region.anchor_gu))
                for wp_name, xyz in placements.items():
                    if math.dist(local, xyz) < b.radius_gu:
                        offenders.append(f"{region.set_name}: waypoint {wp_name!r} "
                                         f"inside {b.name} (r={b.radius_gu})")
    assert offenders == []
```

Before running, read `survey._placements`, `survey._read` and `survey._systems_dir` and confirm: `_placements` returns `{name: (x, y, z)}`; `_systems_dir()` is the SDK `Systems` directory; the system's directory name equals `name` as returned by `system_names()`. If any of those differs, adapt ONLY the access code (not the assertion) and say so in the report.

- [ ] **Step 7: Run them**

Run: `uv run pytest tests/unit/test_system_maps_valid.py -k "radius or ratio or waypoint" -v`
Expected: all PASS. If `test_no_region_waypoint_is_inside_a_mapped_body` fails, STOP and report the offender list verbatim — that is a finding for Mark, not a test to fix. If `matched` is not 118, report the actual number and investigate why before changing it.

- [ ] **Step 8: Prove the ratio gate bites (mutation)**

```bash
cp engine/systems/maps/ona.json /tmp/ona.bak
# edit /tmp-free: change Ona 2's "radius_gu": 1800.0 to 1700.0 in engine/systems/maps/ona.json
uv run pytest tests/unit/test_system_maps_valid.py::test_every_mapped_body_is_its_bc_radius_times_the_scale -q   # expect FAIL naming Ona2/Ona 2
cp /tmp/ona.bak engine/systems/maps/ona.json
diff engine/systems/maps/ona.json /tmp/ona.bak   # expect no output
```

- [ ] **Step 9: Run the gate and commit**

Run: `uv run python tools/gen_system_maps.py --check` → 32 `ok` lines. Then `scripts/check_tests.sh` → `OK — no new failures.`

```bash
git add engine/systems/validate.py tools/systems/survey.py tools/gen_system_maps.py tests/unit/test_system_map_validate.py tests/unit/test_system_maps_valid.py
git commit -m "feat(systems): validate that every body is exactly x20 its BC radius"
```

---

### Task 4: Departure leaves the set you left standing

**Files:**
- Modify: `engine/appc/warp.py` (`_WarpDepartAction._do_play` step 3, `_ArriveFinalizeAction._do_play`, the `_WARP_TRANSIT_SET_NAME` comment block at the top, both classes' docstrings)
- Modify: `tests/unit/test_warp_spine.py`, `tests/unit/test_warp_vfx_sequence.py`, `tests/integration/test_warp_end_to_end.py` (assertions that pin the old deletion)
- Create: `tests/unit/test_warp_leaves_the_set_standing.py`
- Test: `tests/unit/test_realize_set.py` (Review Focus 3)

**Interfaces:**
- Consumes: `warp.configure_warp_hooks(realize=None, teardown=None, current_player=None)`, `host_loop.realize_set_objects`, `host_loop.teardown_set_objects`.
- Produces: warp departure and arrival never call `DeleteSet` on the source set; both still call `_teardown_hook(src)` (render instances only) when the source is not the rendered set. `_WARP_TRANSIT_SET_NAME` handling is unchanged (the tunnel is made and deleted per warp).

Why the teardown stays (spec §3): BC never deletes a set on warp (all 102 region modules call `DeleteSet` only in `Terminate()`, which nothing calls), so `DeleteSet` goes. `_teardown_hook` destroys render instances only, never objects; removing it too is what gave the reference branch its ghost planet. Returning re-realizes through `_realize_hook`.

- [ ] **Step 1: Write the new test file**

Create `tests/unit/test_warp_leaves_the_set_standing.py`:

```python
"""Warping away leaves the set you left standing -- only its render instances go.

BC's region modules expose Initialize / GetSet / Terminate, and `DeleteSet`
appears in all 102 of them only inside `Terminate()`. Nothing in BC's warp path
deletes a set, and no mission calls `Terminate()` -- the bound is the mission
change. Destroying the source set on departure was ours, and E7M3 shows why it
cannot be BC's: it stocks four sensor posts across four star systems at mission
start, for a player who tours them later.

The render teardown is a different call and STAYS (system-frames spec, sec. 3):
it destroys instances, never objects, and returning re-realizes them.
"""
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    # g_kSetManager._sets and the rendered-set name are global and conftest
    # does not auto-clear them; both warp paths refuse to touch the set that is
    # currently rendered, so a stale one would decide this test's outcome.
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    warp.configure_warp_hooks(realize=None, teardown=None)


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    warp.configure_warp_hooks(realize=None, teardown=None)


def _space_set(name):
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, name)
    return pSet


def _ship_in(pSet, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    pSet.AddObjectToSet(ship, name)
    return ship


def _depart(src):
    ship = _ship_in(src, "player")
    warp._WarpDepartAction(src, ship).Play()
    return ship


def _arrive(src, ship, to):
    dest = _space_set(to)
    App.g_kSetManager.MakeRenderedSet(to)
    warp._ArriveFinalizeAction(src, ship).Play()
    return dest


def test_departure_alone_leaves_the_source_set_standing():
    src = _space_set("Ona1")
    _depart(src)
    assert App.g_kSetManager.GetSet("Ona1") is src


def test_arrival_finalize_alone_leaves_the_source_set_standing():
    """The instant (non-flythrough) path never ran departure; finalize used to
    be its fallback delete."""
    src = _space_set("Ona1")
    ship = _ship_in(src, "player")
    _arrive(src, ship, to="Ona2")
    assert App.g_kSetManager.GetSet("Ona1") is src


def test_content_staged_in_the_source_set_survives_a_full_warp():
    """The property the change exists for: a mission's ship is still there
    when you come back."""
    src = _space_set("Ona1")
    post = _ship_in(src, "Sensor Post 1")
    ship = _depart(src)
    _arrive(src, ship, to="Ona2")
    assert App.g_kSetManager.GetSet("Ona1").GetObject("Sensor Post 1") is post


def test_the_warp_transit_set_is_still_cleaned_up():
    """The tunnel is not a region. Leaking one per warp is a slow leak nobody
    would attribute to this change."""
    src = _space_set("Ona1")
    ship = _depart(src)
    _arrive(src, ship, to="Ona2")
    assert App.g_kSetManager.GetSet(warp._WARP_TRANSIT_SET_NAME) is None


def test_the_render_teardown_still_fires_for_the_source_set():
    """Instances go, the set stays. Without this the left set's Planet
    instance survives and draws in the next system's sky (the reference
    branch's ghost planet)."""
    seen = []
    warp.configure_warp_hooks(teardown=lambda s: seen.append(s.GetName()))
    src = _space_set("Ona1")
    ship = _depart(src)
    _arrive(src, ship, to="Ona2")
    assert "Ona1" in seen
    assert App.g_kSetManager.GetSet("Ona1") is src


def test_departing_a_set_that_is_not_a_region_is_fine():
    """QuickBattle, a mission's own set: no region module, nothing to consult."""
    src = _space_set("QuickBattle")
    ship = _depart(src)
    _arrive(src, ship, to="Ona1")
    assert App.g_kSetManager.GetSet("QuickBattle") is src
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_warp_leaves_the_set_standing.py -v`
Expected: the three "standing"/"survives" tests and the not-a-region test FAIL (`GetSet(...)` is `None`); transit and teardown tests PASS already.

- [ ] **Step 3: Remove the source-set deletes**

In `engine/appc/warp.py`, `_WarpDepartAction._do_play`, replace step 3 (the block starting `# 3. Tear the source system down`) so it calls only the render teardown. Keep the surrounding `try/except` shape and whatever the existing `except` body does:

```python
        # 3. Drop the source set's RENDER instances. The set itself stands:
        #    departure is not a lifetime operation. BC's region modules delete
        #    a set only in Terminate(), which nothing calls; the bound is the
        #    mission change (host_loop's _sets.clear()). Returning to this set
        #    re-realizes it through _realize_hook.
        if src is not None and _teardown_hook is not None:
            try:
                _teardown_hook(src)
            except Exception:
                <existing except body>
```

In `_ArriveFinalizeAction._do_play`, the "Terminate the source set" block becomes:

```python
        # Drop the source set's render instances if departure did not (the
        # instant path has no departure). The set itself stands -- see
        # _WarpDepartAction step 3.
        if src is not None and App.g_kSetManager.GetSet(src.GetName()) is src:
            if App.g_kSetManager.get_explicit_rendered_set() is not src:
                if _teardown_hook is not None:
                    _teardown_hook(src)
```

Leave both `_WARP_TRANSIT_SET_NAME` deletions exactly as they are.

- [ ] **Step 4: Correct every statement of the old behaviour**

Rewrite, so each states what the code now does:
- the comment above `_WARP_TRANSIT_SET_NAME` (lines ~15-18: "The source system is torn down at burst…") → the player is parked in the tunnel set and the SOURCE set's render instances are dropped; the source set itself stands;
- `_WarpDepartAction`'s docstring ("…and deletes the source set (render teardown + DeleteSet …")");
- `_ArriveFinalizeAction`'s docstring ("terminate the source set (render teardown + DeleteSet)");
- the step-1 comment "before the set is deleted".

Then run `grep -n "DeleteSet\|torn down\|tear.*down\|terminat" engine/appc/warp.py engine/host_loop.py tests/engine/test_host_loop_backdrops.py` and fix any remaining sentence that claims warp departure deletes or terminates the source set (the reference branch found two such sites in `host_loop.py`'s warp-streak comment block and in `test_transit_holds_the_static_starbox_when_sky_is_off`'s docstring). Transit-set deletions are correct and stay.

- [ ] **Step 5: Run the new file and the warp suites**

Run: `uv run pytest tests/unit/test_warp_leaves_the_set_standing.py tests/unit/test_warp_spine.py tests/unit/test_warp_vfx_sequence.py tests/integration/test_warp_end_to_end.py tests/unit/test_warp_arrival_adopts.py -v`
Expected: the new file PASSES. These four existing tests FAIL, each on one assertion that pins the removed deletion:
- `test_warp_spine.py::test_warp_sequence_moves_player_and_terminates_source`
- `test_warp_spine.py::test_depart_tears_down_source_and_parks_player_in_transit`
- `test_warp_vfx_sequence.py::test_flythrough_off_is_instant`
- `tests/integration/test_warp_end_to_end.py::test_set_course_then_warp_engage_switches_system`

- [ ] **Step 6: Update the four pinned assertions**

- `test_warp_spine.py`: rename `test_warp_sequence_moves_player_and_terminates_source` → `test_warp_sequence_moves_player_and_leaves_source_standing`; replace `assert App.g_kSetManager.GetSet("Source") is None` with
  ```python
      assert App.g_kSetManager.GetSet("Source") is src           # source stands
      assert src.GetObject("player") is None                     # but empty of us
  ```
- `test_warp_spine.py`: rename `test_depart_tears_down_source_and_parks_player_in_transit` → `test_depart_parks_player_in_transit_and_leaves_source_standing`; update its leading comment; replace `assert App.g_kSetManager.GetSet("SrcDepart") is None` with
  ```python
      assert App.g_kSetManager.GetSet("SrcDepart") is src        # source stands
      assert src.GetObject("enemy") is enemy                     # and keeps its ships
  ```
  (read the test first and use the variable names it actually defines for the source set and the non-player ship.)
- `test_warp_vfx_sequence.py::test_flythrough_off_is_instant`: replace `assert App.g_kSetManager.GetSet("Src2") is None` with
  ```python
      assert App.g_kSetManager.GetSet("D2").GetObject("player") is player
      assert App.g_kSetManager.GetSet(warp._WARP_TRANSIT_SET_NAME) is None
      assert App.g_kSetManager.GetSet("Src2") is src
  ```
- `test_warp_end_to_end.py`: replace `assert App.g_kSetManager.GetSet("Src") is None` with
  ```python
      assert App.g_kSetManager.GetSet("Src") is src           # source stands
      assert src.GetObject("player") is None                  # but empty of us
  ```

If a test does not bind the source set or ship to a variable, bind it at creation — do not weaken the assertion.

- [ ] **Step 7: Add the re-realize test (Review Focus 3)**

Append to `tests/unit/test_realize_set.py` (it already defines `_FakeRenderer`):

```python
def test_rerealize_after_departure_uses_the_current_radius(monkeypatch):
    """Warping back into a set you left: departure tore its instances down,
    arrival re-realizes them. planet_natural_scale is cached per realize, so
    the re-realized planet must be scaled from its CURRENT radius -- the map's
    -- never a stale one. The failure this guards is a body DRAWN at one
    radius and TARGETED at another."""
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_planet_nif_path", lambda planet, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    planet = App.Planet_Create(90.0, "data/models/environment/RedPlanet.nif")
    s.AddObjectToSet(planet, "Ona 1")

    hl.realize_set_objects(sess, s, r)
    scale_at_90 = sess.planet_natural_scale[planet]
    hl.teardown_set_objects(sess, s, r)
    assert planet not in sess.planet_instances

    planet.SetRadius(1800.0)
    hl.realize_set_objects(sess, s, r)
    assert sess.planet_natural_scale[planet] == pytest.approx(20.0 * scale_at_90)
```

Add `import pytest` at the top of the file if it is not already imported.

- [ ] **Step 8: Run everything touched**

Run: `uv run pytest tests/unit/test_warp_leaves_the_set_standing.py tests/unit/test_warp_spine.py tests/unit/test_warp_vfx_sequence.py tests/integration/test_warp_end_to_end.py tests/unit/test_warp_arrival_adopts.py tests/unit/test_realize_set.py tests/engine/test_host_loop_backdrops.py -v`
Expected: all PASS.

- [ ] **Step 9: Prove the new tests bite (mutation)**

```bash
cp engine/appc/warp.py /tmp/warp.bak
# re-insert `App.g_kSetManager.DeleteSet(src.GetName())` after the _teardown_hook(src) call in _ArriveFinalizeAction
uv run pytest tests/unit/test_warp_leaves_the_set_standing.py -q     # expect >=3 FAIL
cp /tmp/warp.bak engine/appc/warp.py
diff engine/appc/warp.py /tmp/warp.bak                               # expect no output
```

- [ ] **Step 10: Run the gate and commit**

Run: `scripts/check_tests.sh` → `OK — no new failures.`

```bash
git add engine/appc/warp.py tests/unit/test_warp_leaves_the_set_standing.py tests/unit/test_warp_spine.py tests/unit/test_warp_vfx_sequence.py tests/integration/test_warp_end_to_end.py tests/unit/test_realize_set.py
git add engine/host_loop.py tests/engine/test_host_loop_backdrops.py   # only if Step 4 changed them
git commit -m "fix(warp): departure leaves the set you left standing; only its render instances go"
```

**Known, carried to Plan 2 (do not fix here):** ships left in a standing set keep simulating, and `engine/audio/tg_sound.py` tags positional sounds with the player's rendered set rather than the emitter's, so a left-behind ship firing can be audible after you warp out. The spec schedules the audio conversion early in Plan 2.

---

### Task 5: Every mapped region set is mapped the moment BC creates it

**Files:**
- Create: `engine/systems/region_hooks.py`
- Modify: `engine/appc/sdk_overrides.py` (route `Systems.*`), `tools/mission_harness.py` and `tests/conftest.py` (both loader gates — keep in sync), `engine/systems/apply_map.py` (set the mapped flag), `engine/host_loop.py` (`realize_set_objects` alarm)
- Test: `tests/unit/test_region_map_on_initialize.py` (new)

**Interfaces:**
- Consumes: `apply_map.apply_to_set(pSet, set_name) -> bool`, `resolve.system_of(set_name)`, `sdk_overrides.on_sdk_module_exec(module, qualname)`.
- Produces:
  - `engine.systems.region_hooks.on_region_module_exec(module, qualname) -> None` — wraps a mapped region module's `Initialize`.
  - `engine.systems.region_hooks.is_mapped(pSet) -> bool` — reads the flag.
  - `engine.systems.region_hooks.check_realized(pSet) -> bool` — True if fine; on a mapped-frame set without the flag, prints one `[systems] ALARM` line, appends the set name to `region_hooks.unmapped_realized`, returns False.
  - `engine.systems.region_hooks.reset() -> None` — clears `unmapped_realized` (called from `tests/conftest.py`'s `_reset_leakable_engine_globals`).
  - `apply_to_set` sets `pSet._system_map_applied = True` on its success path.

Why here (spec §2): BC's `<Region>_S.py` adds a body **then** calls `PlaceObjectByName`, so the map cannot be applied at `AddObjectToSet`; it must run after `Initialize()` returns. All four creation paths (warp arrival, `MissionLib.SetupSpaceSet`, a mission calling `Systems.X.Y.Initialize()` directly like E7M3, and Plan 3's system loading) end in that call. Wrapping it covers them all and runs before anything realizes the set.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_region_map_on_initialize.py`:

```python
"""A mapped region set takes the map the moment BC's region module creates it.

Wrapping Initialize() is the one interception point every creation path goes
through: warp arrival, MissionLib.SetupSpaceSet, a mission calling
Systems.X.Y.Initialize() directly (E7M3), and system loading. It cannot be
done at AddObjectToSet: BC's <Region>_S.py adds a body THEN places it.
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

import App
from engine.appc import sdk_overrides
from engine.appc.sets import SetClass_Create
from engine.systems import region_hooks, resolve

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def setup_function(_):
    App.g_kSetManager._sets.clear()
    region_hooks.reset()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    region_hooks.reset()


def _fake_region_module(qualname, set_name, planet_name, bc_radius=90.0, raises=False):
    """A region module shaped like Systems/Ona/Ona1.py: Initialize creates and
    registers the set, adds the planet, then places it."""
    mod = types.ModuleType(qualname)

    def Initialize():
        pSet = SetClass_Create()
        App.g_kSetManager.AddSet(pSet, set_name)
        planet = App.Planet_Create(bc_radius, "data/models/environment/RedPlanet.nif")
        pSet.AddObjectToSet(planet, planet_name)
        planet.SetTranslateXYZ(100.0, 500.0, 0.0)   # BC's placement, AFTER the add
        if raises:
            raise ImportError("Ona1_S missing")

    mod.Initialize = Initialize
    mod.GetSetName = lambda: set_name
    return mod


def _map_radius(set_name, body_name):
    m, region = resolve.for_set(set_name)
    return next(b.radius_gu for b in m.bodies
                if b.name == body_name and b.owner_region == region.set_name)


def test_dispatcher_routes_a_region_module(monkeypatch):
    calls = []
    monkeypatch.setattr(region_hooks, "on_region_module_exec",
                        lambda mod, q: calls.append(q))
    sdk_overrides.on_sdk_module_exec(types.ModuleType("x"), "Systems.Ona.Ona1")
    assert calls == ["Systems.Ona.Ona1"]


def test_dispatcher_ignores_static_modules_and_packages(monkeypatch):
    calls = []
    monkeypatch.setattr(region_hooks, "on_region_module_exec",
                        lambda mod, q: calls.append(q))
    for q in ("Systems", "Systems.Ona", "Systems.Ona.Ona1_S", "Systems.Utils"):
        sdk_overrides.on_sdk_module_exec(types.ModuleType("x"), q)
    assert calls == []


def test_initialize_applies_the_map_after_bc_places_the_body():
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    mod.Initialize()
    pSet = App.g_kSetManager.GetSet("Ona1")
    planet = pSet.GetObject("Ona 1")
    assert planet.GetRadius() == pytest.approx(_map_radius("Ona1", "Ona 1"))
    loc = planet.GetWorldLocation()
    assert (loc.x, loc.y) != (100.0, 500.0), "BC's placement was not overridden"
    assert region_hooks.is_mapped(pSet)


def test_an_unmapped_region_is_left_alone():
    mod = _fake_region_module("Systems.Starbase12.Starbase12", "Starbase12", "Planet")
    original = mod.Initialize
    region_hooks.on_region_module_exec(mod, "Systems.Starbase12.Starbase12")
    assert mod.Initialize is original


def test_wrapping_twice_does_not_double_wrap():
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    wrapped = mod.Initialize
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    assert mod.Initialize is wrapped


def test_a_reexecuted_module_is_wrapped_again():
    """importlib.reload re-runs the module body, rebinding a pristine
    Initialize; the loader hook fires again and must re-wrap it."""
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    fresh = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    mod.Initialize = fresh.Initialize
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    mod.Initialize()
    assert region_hooks.is_mapped(App.g_kSetManager.GetSet("Ona1"))


def test_initialize_twice_is_idempotent():
    """Review Focus 1: a mission re-running setup must leave the body at the
    map radius, not the map radius scaled again."""
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    mod.Initialize()
    mod.Initialize()
    planet = App.g_kSetManager.GetSet("Ona1").GetObject("Ona 1")
    assert planet.GetRadius() == pytest.approx(_map_radius("Ona1", "Ona 1"))


def test_a_raising_initialize_propagates_and_maps_nothing():
    """Review Focus 2: fail loud, and never map a stale same-named set."""
    stale = SetClass_Create()
    App.g_kSetManager.AddSet(stale, "Ona1")
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1", raises=True)
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    with pytest.raises(ImportError):
        mod.Initialize()
    # BC's Initialize re-registered "Ona1" before raising, so the set now
    # under that name is the half-built one. Neither it nor the stale one
    # may be mapped: a wrap that swallowed the error and applied anyway
    # would map whichever GetSet("Ona1") returned.
    assert not region_hooks.is_mapped(App.g_kSetManager.GetSet("Ona1"))
    assert not region_hooks.is_mapped(stale)


def test_apply_to_set_sets_the_flag_and_only_on_success():
    from engine.systems import apply_map
    mapped = SetClass_Create()
    App.g_kSetManager.AddSet(mapped, "Ona1")
    assert apply_map.apply_to_set(mapped, "Ona1") is True
    assert region_hooks.is_mapped(mapped)
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "QuickBattle")
    assert apply_map.apply_to_set(other, "QuickBattle") is False
    assert not region_hooks.is_mapped(other)


def test_the_alarm_fires_for_a_mapped_frame_set_realized_unmapped(capsys):
    raw = SetClass_Create()
    App.g_kSetManager.AddSet(raw, "Ona2")
    assert region_hooks.check_realized(raw) is False
    assert region_hooks.unmapped_realized == ["Ona2"]
    assert "[systems] ALARM" in capsys.readouterr().out


def test_the_alarm_is_silent_for_mapped_and_unmapped_frames(capsys):
    from engine.systems import apply_map
    mapped = SetClass_Create()
    App.g_kSetManager.AddSet(mapped, "Ona1")
    apply_map.apply_to_set(mapped, "Ona1")
    qb = SetClass_Create()
    App.g_kSetManager.AddSet(qb, "QuickBattle")
    assert region_hooks.check_realized(mapped) is True
    assert region_hooks.check_realized(qb) is True
    assert region_hooks.unmapped_realized == []
    assert "ALARM" not in capsys.readouterr().out


def test_both_sdk_loaders_route_region_modules():
    """The runtime loader (tools/mission_harness.py) and its test twin
    (tests/conftest.py) must gate identically -- a hook in one only passes
    or fails asymmetrically."""
    gate = '_qual.startswith(("ships.", "Systems."))'
    for rel in ("tools/mission_harness.py", "tests/conftest.py"):
        assert gate in (PROJECT_ROOT / rel).read_text(), f"{rel} does not route Systems.*"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_region_map_on_initialize.py -v`
Expected: collection ERROR — `ImportError: cannot import name 'region_hooks'`.

- [ ] **Step 3: Implement `region_hooks`**

Create `engine/systems/region_hooks.py`:

```python
"""Apply the system map to a region set the moment BC's region module makes it.

Every path that creates a mapped region set -- warp arrival
(warp.ChangeRenderedSetAction), MissionLib.SetupSpaceSet, a mission calling
Systems.X.Y.Initialize() directly (E7M3 does eight), and system loading --
ends in that region module's Initialize(). So that call is wrapped: BC's body
runs unchanged, then apply_map.apply_to_set. Installed from the SDK loaders'
post-exec hook (engine/appc/sdk_overrides.py), the same place ship-data
overrides are installed.

Not at AddObjectToSet: BC's <Region>_S.py adds a body THEN calls
PlaceObjectByName, which would overwrite a position applied at the add.

Ordering is load-bearing: the map must be applied before anything realizes the
set, because host_loop's planet_natural_scale caches GetRadius() at realize --
applied after, a body is DRAWN at BC's radius and TARGETED at the map's.
check_realized() is the alarm for that: a set whose name resolves to a system
but which apply_to_set never marked.
"""
from __future__ import annotations

_WRAPPED_ATTR = "_dauntless_region_map_wrap"
_FLAG_ATTR = "_system_map_applied"

# Names of mapped-frame sets realized without the map, in order. Test-visible.
unmapped_realized: list = []


def reset() -> None:
    unmapped_realized.clear()


def is_mapped(pSet) -> bool:
    return bool(getattr(pSet, _FLAG_ATTR, False))


def on_region_module_exec(module, qualname: str) -> None:
    """Wrap a just-executed Systems.<System>.<Region> module's Initialize.

    No-op for anything that is not a mapped region module: packages, the
    <Region>_S static modules, helpers like Systems.Utils, and regions no map
    covers (Starbase12, DeepSpace, the multiplayer sets).
    """
    parts = qualname.split(".")
    if len(parts) != 3 or parts[0] != "Systems" or parts[2].endswith("_S"):
        return
    init = getattr(module, "Initialize", None)
    get_name = getattr(module, "GetSetName", None)
    if not callable(init) or not callable(get_name):
        return
    if getattr(init, _WRAPPED_ATTR, False):
        return
    set_name = get_name()
    from engine.systems import resolve
    if resolve.system_of(set_name) is None:
        return

    def Initialize(*args, **kwargs):
        result = init(*args, **kwargs)
        import App
        from engine.systems import apply_map
        pSet = App.g_kSetManager.GetSet(set_name)
        if pSet is not None:
            apply_map.apply_to_set(pSet, set_name)
        return result

    setattr(Initialize, _WRAPPED_ATTR, True)
    module.Initialize = Initialize


def check_realized(pSet) -> bool:
    """False, with one loud line, when a mapped-frame set is realized unmapped."""
    if pSet is None or is_mapped(pSet):
        return True
    from engine.systems import resolve
    name = pSet.GetName()
    if resolve.system_of(name) is None:
        return True
    unmapped_realized.append(name)
    print(f"[systems] ALARM: set {name!r} belongs to a mapped system but was "
          f"realized without the map -- its bodies will draw at BC's radius and "
          f"position. It was created by a path that bypassed its region module's "
          f"Initialize().", flush=True)
    return False
```

Note the `raises` test: when BC's `Initialize` raises, `init(...)` raises before `apply_to_set` runs, so nothing is mapped and the exception propagates — no try/except is wanted here.

- [ ] **Step 4: Set the flag in `apply_to_set`**

In `engine/systems/apply_map.py` `apply_to_set`, immediately before its final `return True`:

```python
    # Read by region_hooks.check_realized: the fact that this set was mapped,
    # rather than a guess from its bodies' radii.
    pSet._system_map_applied = True
```

- [ ] **Step 5: Route `Systems.*` in the dispatcher**

In `engine/appc/sdk_overrides.py` `on_sdk_module_exec`, before the `ships` check, add:

```python
    if parts[0] == "Systems":
        from engine.systems import region_hooks
        _dispatch(region_hooks.on_region_module_exec, module, qualname)
        return
```

and extend the module docstring and the function docstring with one line each: `Systems.<System>.<Region> -> region_hooks.on_region_module_exec` (applies the system map after the region's Initialize()).

- [ ] **Step 6: Widen both loader gates, identically**

In `tools/mission_harness.py` and in `tests/conftest.py`, in `_SDKLoader.exec_module`'s second pass, change

```python
        if _qual.startswith("ships."):
```
to
```python
        if _qual.startswith(("ships.", "Systems.")):
```

and change each adjacent comment's first line to `# Second pass: engine-owned overrides -- ship data, and the system map on region modules --` (keep the rest, including "Keep in sync with the twin in …").

- [ ] **Step 7: Clear the alarm list between tests**

In `tests/conftest.py` `_reset_leakable_engine_globals`, beside the other resets:

```python
    try:
        from engine.systems import region_hooks as _rh
        _rh.reset()
    except Exception:
        pass
```

- [ ] **Step 8: Run the unit tests**

Run: `uv run pytest tests/unit/test_region_map_on_initialize.py -v`
Expected: all PASS.

- [ ] **Step 9: Wire the alarm into realization**

In `engine/host_loop.py` `realize_set_objects`, as the first statement after the docstring:

```python
    from engine.systems import region_hooks
    region_hooks.check_realized(pSet)
```

Add to `tests/unit/test_region_map_on_initialize.py`:

```python
def test_realizing_an_unmapped_region_set_raises_the_alarm():
    from engine import host_loop as hl
    from tests.unit.test_realize_set import _FakeRenderer
    raw = SetClass_Create()
    App.g_kSetManager.AddSet(raw, "Ona3")
    hl.realize_set_objects(hl.MissionSession(mission_name="t"), raw, _FakeRenderer())
    assert region_hooks.unmapped_realized == ["Ona3"]
```

Run: `uv run pytest tests/unit/test_region_map_on_initialize.py -v` → all PASS.

- [ ] **Step 10: Integration — the real SDK, three creation paths**

Add to `tests/unit/test_region_map_on_initialize.py`. These drive BC's real region modules through the real loader (`tools.mission_harness.setup_sdk`, as `tests/unit/test_ship_data_overrides.py` does):

```python
def _fresh(qualname):
    import tools.mission_harness as mh
    mh.setup_sdk()
    sys.modules.pop(qualname, None)
    return importlib.import_module(qualname)


def _assert_mapped(set_name, body_name):
    pSet = App.g_kSetManager.GetSet(set_name)
    assert pSet is not None
    assert region_hooks.is_mapped(pSet)
    assert pSet.GetObject(body_name).GetRadius() == pytest.approx(
        _map_radius(set_name, body_name))


def test_real_sdk_direct_initialize_is_mapped():
    """E7M3's path: import Systems.X.Y, then call its Initialize()."""
    _fresh("Systems.Ona.Ona1").Initialize()
    _assert_mapped("Ona1", "Ona 1")


def test_real_sdk_setup_space_set_is_mapped():
    """How campaign missions stand up their starting set -- the path the
    reference branch left unmapped."""
    import MissionLib
    _fresh("Systems.Ona.Ona2")
    MissionLib.SetupSpaceSet("Systems.Ona.Ona2")
    _assert_mapped("Ona2", "Ona 2")


def test_real_sdk_warp_arrival_is_mapped():
    from engine.appc import warp
    warp.configure_warp_hooks(realize=None, teardown=None)
    sys.modules.pop("Systems.Ona.Ona3", None)
    warp.ChangeRenderedSetAction_Create("Systems.Ona.Ona3")._do_play()
    _assert_mapped("Ona3", "Ona 3")
    App.g_kSetManager.ClearRenderedSet()
```

Run: `uv run pytest tests/unit/test_region_map_on_initialize.py -k real_sdk -v`
Expected: all three PASS. If `MissionLib` or `Systems.Ona.*` cannot be imported headlessly, read how `tests/unit/test_ship_data_overrides.py` and the reference branch's `tests/unit/test_warp_arrival_maps_the_region.py` (`git show 9efad5fb:tests/unit/test_warp_arrival_maps_the_region.py`) set up the SDK, mirror that setup, and say so in the report. Do not stub the region module — these tests exist to prove the REAL module is wrapped.

- [ ] **Step 11: Prove the wrap bites (mutation)**

```bash
cp engine/systems/region_hooks.py /tmp/rh.bak
# make on_region_module_exec return immediately (first line: `return`)
uv run pytest tests/unit/test_region_map_on_initialize.py -q     # expect the real_sdk tests and the apply test to FAIL
cp /tmp/rh.bak engine/systems/region_hooks.py
diff engine/systems/region_hooks.py /tmp/rh.bak                  # expect no output
```

- [ ] **Step 12: Run the gate and commit**

Run: `scripts/check_tests.sh` → `OK — no new failures.` Then check the alarm stayed quiet across the suite: `uv run pytest -q 2>&1 | grep -c "\[systems\] ALARM"` — report the number. Non-zero means some test (or production path) realizes a mapped-name set it built by hand; list which, in the report. It is information for Plan 3, not a failure of this task, unless the set was created through a real region module (that would be a bug in the wrap — STOP and report).

```bash
git add engine/systems/region_hooks.py engine/systems/apply_map.py engine/appc/sdk_overrides.py tools/mission_harness.py tests/conftest.py engine/host_loop.py tests/unit/test_region_map_on_initialize.py
git commit -m "feat(systems): map every region set inside its module's Initialize, with an unmapped-realize alarm"
```

**Visible consequence, for the report:** any campaign mission whose starting set is a mapped region now shows that region's own bodies at map scale and position (×20 radius, star at its system position). Sibling regions are not loaded and nothing is drawn from the map yet — that is Plan 3.

---

## After the last task

Run `scripts/check_tests.sh` one final time on the branch tip and paste its summary line. Then hand back to the controller for the whole-branch review. **Plan 1 has no live pass** — Mark flies after Plan 3.

---

### Task 6: No body may swallow content a mission stages in its region (Prendel 3)

**Added 2026-09-24 after Task 3's finding, on Mark's choice of option A.**

Measured: 7 of the 8 waypoints E5M2 and E6M4 stage in Prendel 3 (`E5M2/Prendel3_P.py`, `E6M4/E6M4_Prendel3_P.py`) lie INSIDE the x20 Prendel 3 body (radius 7200 GU) — the base, three Galors, "Strange Readings" and E5M2's own Player Start (164 GU inside). Across 50 mission placement files matched to mapped regions, Prendel 3 is the only region affected. Task 3's ratchet saw only the region module's own waypoints (which are the bodies' own placement points) and missed all of these. Sliding the planet along the Player-Start→planet ray makes it worse; pushing it directly away from the content clears it (measured: 2,140 GU at 1,000 GU clearance; planet then fills ~90° of sky from Player Start instead of 121°).

**Rule (general, not a Prendel 3 special case):** after a region's bodies are placed and its anchor fixed, no body the region owns may have its surface within `LayoutTuning.staged_clearance_gu = 1000.0` GU of any waypoint STAGED in that region. Staged waypoints = the region module's own `LoadPlacements` waypoints EXCEPT those a body is placed at (a waypoint coinciding with a surveyed body's BC `offset_gu`), plus every mission placement the survey attributes to that set (the same attribution `_mission_extent` already uses). If any body violates it, the region's whole body group (primary and its moons, together, so moon geometry is preserved) is translated directly away from the centroid of the offending waypoints, in steps, until every body clears. The ANCHOR does not move — staged content is set-local, so the anchor is what keeps it where BC put it relative to the player.

**Files:**
- Modify: `tools/systems/survey.py` — expose staged waypoints per region: `SurveyedRegion.staged_points: list[tuple[str, str, tuple]]` (source label, waypoint name, set-local xyz). Refactor `_mission_extent` so extent and staged points come from ONE scan (extent = max norm over the same points) — never two parsers that can disagree.
- Modify: `tools/systems/layout.py` — `LayoutTuning.staged_clearance_gu: float = 1000.0`; the push in `_place`, after pins and anchor, before `reach`. Bounded: if it has not converged within a generous bound, raise with the region name (a layout that cannot clear its content must fail loudly, not ship).
- Modify: `engine/systems/validate.py` — optional rule `staged-clearance` driven by new keyword args `staged_points=None` (dict set_name → list of (label, xyz)) and `staged_clearance_gu=None`; runs only when both are given; region-scoped body lookup (name AND owner_region).
- Modify: `tools/gen_system_maps.py` — pass the new inputs to `validate()`.
- Regenerate: `engine/systems/maps/*.json` via the generator (expected: prendel.json changes; report every map that changes and why).
- Test: `tests/tools/test_system_layout.py` (the push: synthetic region with a waypoint inside the primary → pushed clear, moons move with it, anchor unchanged, direction is away from the content; a region with no violation is byte-identical to before), `tests/unit/test_system_map_validate.py` (rule unit tests: flags, accepts, off without inputs, region-scoped), `tests/unit/test_system_maps_valid.py` — REPLACE the Task 3 ratchet (`KNOWN_WAYPOINTS_INSIDE_BODIES` and `test_no_region_waypoint_is_inside_a_mapped_body`) with `test_no_staged_waypoint_is_within_clearance_of_a_body` over every system using `SurveyedRegion.staged_points`, asserting no problems; plus a non-vacuity test that Prendel3's staged points include E5M2's "Base Location" and "Galor Start" and E6M4's "Base Location".

**Evidence the report must carry:** RED for each new test; the list of regenerated maps; for Prendel 3, before/after: the planet's set-local centre, the push distance and direction, the nearest staged waypoint's clearance, and its apparent angular size from the region's Player Start (`2·asin(r/d)`); the generator `--check` output; the far-plane guard still green (the derived widest sightline may move); the gate summary line.
