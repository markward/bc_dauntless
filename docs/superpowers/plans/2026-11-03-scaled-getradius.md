# Scaled `GetRadius()` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo: one `tdd-engineer` per task, in order, commit between tasks, stop on any BLOCKED (CLAUDE.md "Executing plans").

**Goal:** `ObjectClass.GetRadius()` returns the scaled world radius (base × scale), as Bridge Commander's does. Model-space users move to a new `GetBaseRadius()`.

**Architecture:**
- **Refactor first.** Task 1 adds the base accessor and moves every base reader and every self-scaling helper onto it, with no behaviour change.
- **Then the flip.** Task 2 is a one-commit behaviour change: `GetRadius()` scaled, plus the two native readers of the bare base: K4 and the tractor stand-off.
- **Cleanup last.** Task 3 collapses the now-redundant helper branch and fixes stale prose.
- The native mirror keeps pushing the raw base `_radius` and `_scale`.

**Tech Stack:** Python 3.11 engine (`engine/`), C++ combat kernels (`native/src/combat/`), pytest, gtest via ctest.

**Spec:** `docs/superpowers/specs/2026-11-03-scaled-getradius-design.md`. Evidence: `docs/reference/engine/native-motion/radius-scale-audit.md`.

## Global Constraints

- Branch `ws/scaled-getradius` from `project/native-motion-and-proximity`, worktree `.claude/worktrees/scaled-getradius`. Never work in the main checkout; never commit to main.
- **Banned git:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths only. To mutate a file temporarily: `cp` to /tmp, mutate, `cp` back, `diff` to prove it identical.
- **Focused test files only**, exactly as named per task. Never a whole suite (`tests`, `tests/unit`, …), never an empty file list, never `scripts/check_tests.sh`. Tell every subagent the same.
- **No benchmarks or perf captures.** The machine is shared.
- **Build** only with `cmake --build build -j` from the worktree root. Never reconfigure the build type; never run cmake inside `native/`.
- **Do not edit** files the proximity project owns:
  - `engine/appc/planet.py`, `engine/appc/proximity_cache.py`, `engine/appc/proximity_table.py`;
  - the set-membership hooks in `engine/appc/sets.py`;
  - `engine/appc/transform_store.py` and `native/src/transforms/`;
  - `engine/appc/ship_motion.py`, `engine/appc/drift.py`, `impulse_fractions` in `engine/appc/subsystems.py`;
  - `IsTypeOf` in `engine/appc/objects.py`.
  The design's §7 lists the requests for them instead.
- **Golden fights:** never re-record without asking Mark first, because another session may be mid-re-record. A re-record goes in its own commit with the reason (`UPDATE_COMBAT_GOLDEN=1`).
- **BC behaviour:** cite `stbc_reference` or the audit; otherwise mark it inferred. Check `docs/stub_heatmap.md` before calling an SDK call a no-op.
- **Guard rule (design D2), verbatim:** `GetRadius()` = `_radius * _scale` if `_scale > 0.0 and math.isfinite(_scale)` else `_radius`. This is the same expression as `collisions.world_radius` today and `beam_geometry.cc:173`.

## Review Focus

1. **Non-positive or non-finite scale** (0, −2, NaN, ±inf): `GetRadius()` returns the base, exactly as `world_radius` and `beam_geometry.cc:173` do. Task 2, `test_get_radius_ignores_a_bad_scale`.
2. **The SDK's docking shrink run twice** (`DockWithStarbase.py:47-50`) lands at exactly 4.0 GU, and the second run's gate is false. Task 2, `test_dock_shrink_lands_at_four_and_is_idempotent`.
3. **A promoted field rock** (`RockClass_Create(..., exact_radius=True)`: `SetRadius(r_q)` then `SetScale(radius_gu / r_q)`) reports `GetRadius() == radius_gu`. Task 2, `test_promoted_rock_reports_its_exact_radius`.
4. **A headless hardpoint rock** with base 0 and only a hull radius: `GetRadius()` is 0, `effective_radius` is still hull × scale. Task 1, `test_radius_helpers_never_read_get_radius`; Task 2 keeps it green.
5. **A mod-scaled planet** draws at base / sphere × scale, not base × scale² / sphere. Task 1, `test_scaled_planet_natural_scale_uses_the_base_radius`.

---

### Task 1: `GetBaseRadius()` and every base reader moved to it (no behaviour change)

**Files:**
- Modify:
  - `engine/appc/objects.py:210-214`: add `GetBaseRadius`; `SetRadius` docstring;
  - `engine/appc/collisions.py:117-143` (`world_radius`);
  - `engine/rocks/rock.py:60-70` (`effective_radius`);
  - `engine/host_loop.py:6519, 7121, 7126, 8269, 8437, 8442`;
  - `engine/ui/spv_decals_pane.py:320`;
  - `engine/ui/phaser_overlay.py:186`;
  - `engine/systems/apply_map.py:195`;
  - `engine/dev_missions/felix_destroy.py:88`;
  - `engine/dev_missions/combat_stress.py:232, 255`;
  - `engine/appc/native_combat.py:4641` (`_K2_OBJECT_NAMES`) and `:5419` (`_STEP_SHIP_PATCHES`).
- Test:
  - `tests/unit/test_physics_object.py`;
  - `tests/unit/test_collision_radius_scale.py`;
  - `tests/unit/test_realize_set.py`.

**Interfaces:**
- Produces: `ObjectClass.GetBaseRadius(self) -> float`, which returns `self._radius`. Engine surface, not SDK: the docstring says BC has no such call, and that `SetRadius` sets this base value.
- Produces: `collisions.world_radius(obj) -> float`. For an `ObjectClass`, it returns `GetBaseRadius() × scale` under the guard rule. A `DebrisChunk` and any non-ObjectClass duck type keep today's code path unchanged.
- Produces: `rocks.rock.effective_radius(rock) -> float`. base = `rock.GetBaseRadius()`, falling back to the hull's `GetRadius()` when the base is ≤ 0; the result is base × `GetScale()`.

- [ ] **Step 0: Set up the worktree**

Already done (2026-11-03): the worktree and branch exist (`git worktree add .claude/worktrees/scaled-getradius -b ws/scaled-getradius project/native-motion-and-proximity`, at `0b55cda86`), and the audit, design and plan are committed there as docs. Items 1–5 below are not done; the build was left until execution so it doesn't load the shared machine early.

Inside the worktree:
1. `cp <main>/settings.json .`
2. `mkdir -p mods && cp -Rc <main>/mods/. mods/`
3. `uv sync --extra dev`
4. Configure the build, using the uv 3.11 pins from the memory note "worktree runtime deps": `cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=<uv cpython-3.11> -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION`
5. `cmake --build build -j`
6. (Done.) The audit, the design and this plan are committed as docs.

Expected: the build succeeds, and `build/python/_dauntless_host.cpython-*.so` exists.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_physics_object.py`:

```python
def test_base_radius_is_the_set_radius_at_any_scale():
    obj = ObjectClass()
    obj.SetRadius(500.0)
    obj.SetScale(2.5)
    assert obj.GetBaseRadius() == 500.0
```

In `tests/unit/test_collision_radius_scale.py`, reusing the file's `_rock` helper:

```python
def test_radius_helpers_never_read_get_radius(monkeypatch):
    """The two radius x scale helpers read the BASE, so the GetRadius flip
    cannot double-scale them."""
    from engine.appc.objects import ObjectClass
    from engine.rocks.rock import effective_radius
    rock = _rock(1.2, 5.0)
    bare = _rock(1.0, 5.0)
    bare.SetRadius(0.0)                  # headless hardpoint rock: hull only
    bare.GetHull().SetRadius(0.8)

    def _boom(self):
        raise AssertionError("helper read GetRadius()")
    monkeypatch.setattr(ObjectClass, "GetRadius", _boom)
    assert collisions.world_radius(rock) == 1.2 * 5.0
    assert effective_radius(rock) == 1.2 * 5.0
    assert effective_radius(bare) == 0.8 * 5.0
```

In `tests/unit/test_realize_set.py`, following `test_rerealize_after_departure_uses_the_current_radius`'s setup: `test_scaled_planet_natural_scale_uses_the_base_radius`.
- Realise a planet with `SetRadius(90.0)` and `SetScale(2.0)`.
- First **simulate the flip**: monkeypatch `ObjectClass.GetRadius` to `lambda self: self._radius * self._scale`. A raising patch won't do, because DRAWN readers on the same realise path, such as `host_loop.py:7583`, legitimately call `GetRadius()`.
- Assert `sess.planet_natural_scale[planet] == pytest.approx(90.0 / sphere)`, where `sphere` is the divisor the existing test derives. That is the base radius, not 180 / sphere.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_physics_object.py tests/unit/test_collision_radius_scale.py tests/unit/test_realize_set.py -v`

Expected:
- `test_base_radius_is_the_set_radius_at_any_scale` fails: `TGObject.__getattr__` returns a `_Stub`, which is not 500.0;
- the helper test fails with "helper read GetRadius()";
- the planet test fails: it sees 180 / sphere.

- [ ] **Step 3: Implement**

1. `GetBaseRadius` in `objects.py`.
2. `world_radius` and `effective_radius` per Interfaces.
3. Swap `GetRadius()` for `GetBaseRadius()` at each listed `host_loop.py`, `spv_decals_pane.py`, `phaser_overlay.py`, `apply_map.py`, `felix_destroy.py` and `combat_stress.py` line.
4. Add `"GetBaseRadius"` to `_K2_OBJECT_NAMES` and `_STEP_SHIP_PATCHES`, next to `"GetRadius"`.

`GetRadius()` itself is **not** touched in this task.

- [ ] **Step 4: Run the focused files; everything passes, and existing tests pass unmodified**

Run:

```bash
uv run pytest tests/unit/test_physics_object.py tests/unit/test_collision_radius_scale.py tests/unit/test_realize_set.py tests/unit/test_rock_create.py tests/unit/test_rock_death.py tests/unit/test_rock_promotion.py tests/unit/test_camera_modes.py tests/unit/test_native_beam_geometry.py tests/unit/test_native_projectile_geometry.py tests/unit/test_native_k2_dispatch.py tests/unit/test_native_k3_dispatch.py tests/unit/test_native_k2_override_guard.py tests/unit/test_native_combat_mirror.py tests/unit/test_hull_bounds.py tests/unit/test_phaser_overlay.py tests/unit/test_apply_system_map.py tests/unit/test_appc_suns.py tests/unit/test_rock_redirect_realise.py tests/ui/test_spv_decals_pane.py tests/host/test_planet_render_scale.py tests/host/test_native_beam_trace.py tests/integration/test_collision_avoidance.py tests/integration/test_native_can_detect_differential.py tests/integration/test_e1m2_target_zoom_fit.py -q
```

Expected: all pass. `git diff --stat -- tests/` shows only the three new tests.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/objects.py engine/appc/collisions.py engine/rocks/rock.py engine/host_loop.py engine/ui/spv_decals_pane.py engine/ui/phaser_overlay.py engine/systems/apply_map.py engine/dev_missions/felix_destroy.py engine/dev_missions/combat_stress.py engine/appc/native_combat.py tests/unit/test_physics_object.py tests/unit/test_collision_radius_scale.py tests/unit/test_realize_set.py
git commit -F <msgfile>
```

Message: `refactor(radius): GetBaseRadius; base readers and radius x scale helpers read it (no behaviour change)`.

---

### Task 2: `GetRadius()` returns the scaled world radius (the behaviour change)

**Files:**
- Modify:
  - `engine/appc/objects.py:210-211` (`GetRadius` and its docstring);
  - `native/src/combat/src/k4_eligibility.cc:86-89, 104`;
  - `native/src/combat/src/tractor_force.cc:74-78` (`Step::standoff`);
  - `tests/unit/test_collision_radius_scale.py:47-56`: rewrite the guard test.
- Test:
  - `tests/unit/test_physics_object.py`;
  - `tests/unit/test_collision_radius_scale.py`;
  - `tests/unit/test_rock_create.py`;
  - `tests/unit/test_native_k4_eligibility.py`;
  - `native/tests/combat/k4_eligibility_test.cc`;
  - `native/tests/combat/tractor_force_test.cc`.

**Interfaces:**
- Consumes: `ObjectClass.GetBaseRadius()`, and the Task 1 helpers, which no longer read `GetRadius()`.
- Produces: `ObjectClass.GetRadius(self) -> float`, implementing the guard rule in Global Constraints.
- Produces: K4 reads `world_radius(m, handle)` (`dauntless/combat/beam_geometry.h`) wherever it read `r->_radius`, with the `isfinite` check on that value.
- Produces: the tractor stand-off is `world_radius(m, source.h) + world_radius(m, target.h) + TRACTOR_STANDOFF_MARGIN_GU`. It has had no Python twin since `engine/appc/tractor.py` became a driver for the native step, so no Python change goes with it.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_physics_object.py`:

```python
def test_get_radius_is_base_times_scale():
    obj = ObjectClass()
    obj.SetRadius(2.0)
    obj.SetScale(3.0)
    assert obj.GetRadius() == 6.0
    assert obj.GetBaseRadius() == 2.0

@pytest.mark.parametrize("bad", [0.0, -2.0, math.nan, math.inf, -math.inf])
def test_get_radius_ignores_a_bad_scale(bad):
    obj = ObjectClass()
    obj.SetRadius(2.0)
    obj.SetScale(bad)
    assert obj.GetRadius() == 2.0

def test_dock_shrink_lands_at_four_and_is_idempotent():
    """AI/Compound/DockWithStarbase.py:47-50, verbatim arithmetic."""
    ship = ObjectClass()
    ship.SetRadius(4.4)
    for _ in range(2):
        if ship.GetRadius() > 4.0:
            ship.SetScale(ship.GetScale() * 4.0 / ship.GetRadius())
    assert ship.GetRadius() == pytest.approx(4.0)
    assert ship.GetScale() == pytest.approx(4.0 / 4.4)
```

In `tests/unit/test_collision_radius_scale.py`, replace `test_get_radius_stays_unscaled_and_effective_radius_scales_once` with `test_get_radius_is_scaled_and_effective_radius_scales_once`. For `_rock(1.2, 5.0)`, assert:
- `GetRadius() == pytest.approx(6.0)`;
- `GetBaseRadius() == pytest.approx(1.2)`;
- `effective_radius(rock) == pytest.approx(6.0)`;
- `collisions._resolve_body(rock).radius == pytest.approx(rock.GetRadius())`.

In `tests/unit/test_rock_create.py`: `test_promoted_rock_reports_its_exact_radius`. For `RockClass_Create(4.37, exact_radius=True)` (the file's promotion form), assert:
- `GetRadius() == pytest.approx(4.37)`;
- `GetBaseRadius() == pytest.approx(4.4)`.

In `tests/unit/test_native_k4_eligibility.py`: `test_k4_matches_select_eligible_with_scaled_ships(pool)`. It is `test_k4_matches_select_eligible`, except that `_randomise` also does `ship.SetScale(rng.choice((1.0, 1.0, 2.5, 0.5, 3.0, 8.5, 0.0, -2.0, math.nan, math.inf)))`. Run 500 scenes. Reset every pool ship to `SetScale(1.0)` in a `finally`. Assert `got == want` per scene and `_reasons() == {}`.

In `native/tests/combat/k4_eligibility_test.cc`: `TEST(K4, SizeUsesScaledRadius)`. Build it with the file's `World` helper as `MaxROrOne` does. Two ships of base radius 1.0 and 2.0; set the first's scale with `w.m.set_f(h, Field::_scale, 3.0)`. With proximity weight 0 and size weight 1, `k4_eligible(..., -1, 1, 0.0, 1.0)` returns index 0. Then set that scale to NaN: the call still succeeds and returns index 1, because a bad scale falls back to the base.

In `native/tests/combat/tractor_force_test.cc`: `TEST(TractorForce, StandoffUsesScaledRadius)`. Use the file's `World` helper and `kCases`' PULL and DOCK cases. For each mode, run one step in these worlds, all with the source at base radius 4.0:
- **A:** target base 2.5, `w.m.set_f(t, Field::_scale, 2.0)`;
- **B:** target base 5.0, scale never set;
- **C:** target base 2.5, scale NaN;
- **D:** target base 2.5, scale never set.

Assert, hex-exact through `w.at(...)`:
- A's source and target positions equal B's: a scaled radius tows exactly like the equal base radius;
- C's equal D's: a bad scale falls back to the base (the guard rule).

- [ ] **Step 2: Run to verify the failures**

Run: `uv run pytest tests/unit/test_physics_object.py tests/unit/test_collision_radius_scale.py tests/unit/test_rock_create.py tests/unit/test_native_k4_eligibility.py -v`

Expected: the new scaled-radius tests and the rewritten guard test fail (`GetRadius()` is still the base). `test_get_radius_ignores_a_bad_scale` passes already; that is fine. The K4 scaled test may still pass, since both sides read base today; it is the guard for Step 3.

Then run `cmake --build build -j && ctest --test-dir build -R 'combat_(K4|TractorForce)\.' --output-on-failure`. Expected: `combat_K4.SizeUsesScaledRadius` and `combat_TractorForce.StandoffUsesScaledRadius` fail.

- [ ] **Step 3: Implement**

1. Write `GetRadius` per the guard rule. Its docstring cites `stbc_reference/spec/CameraModes.md` §3.1 and the audit.
2. In K4, replace the three `_radius` reads with `world_radius(m, handle)`, computed once per row.
3. In `tractor_force.cc`, `Step::standoff` uses `world_radius` for both bodies (include `dauntless/combat/beam_geometry.h`), and its comment says the stand-off is the scaled radii.

No other file changes.

- [ ] **Step 4: Run the Task 1 focused list plus Task 2's files; all pass**

Run:
1. Task 1 Step 4's command, with `tests/unit/test_native_k4_eligibility.py tests/unit/test_damage_eligibility.py tests/integration/test_native_k3_differential.py tests/integration/test_native_damage_differential.py tests/unit/test_native_tractor.py` added.
2. `ctest --test-dir build -R 'combat_' --output-on-failure`.

Expected: all pass.

- [ ] **Step 5: Golden fights and the campaign sweep**

Run: `uv run pytest tests/integration/test_golden_fights.py tests/integration/test_warp_button_handler_sweep.py tests/integration/test_campaign_warp_transitions.py -q`

The golden harness came from `ws/native-default` (`aae2cdaa2`). If `test_golden_fights.py` is not on the base branch, report BLOCKED rather than skip it.

Expected: **all pass, byte-identical goldens** (no golden scene calls `SetScale`).
- **If a golden moves:** stop and report BLOCKED with the scene name and the first differing tick. Do not re-record. A re-record needs Mark's go-ahead, and goes in its own commit.
- If the sweep fails, report BLOCKED with the mission.

- [ ] **Step 6: Commit (the behaviour change, alone)**

```bash
git add engine/appc/objects.py native/src/combat/src/k4_eligibility.cc native/src/combat/src/tractor_force.cc tests/unit/test_physics_object.py tests/unit/test_collision_radius_scale.py tests/unit/test_rock_create.py tests/unit/test_native_k4_eligibility.py native/tests/combat/k4_eligibility_test.cc native/tests/combat/tractor_force_test.cc
git commit -F <msgfile>
```

Message: `feat(radius): GetRadius() is the scaled world radius, as BC's (Mark 2026-11-03)`. The body says:
- goldens unchanged;
- sweep green;
- live check owed.

---

### Task 3: Collapse `world_radius` onto `GetRadius()`, and fix stale prose (no behaviour change)

**Files:**
- Modify:
  - `engine/appc/collisions.py:117-143`;
  - `tests/host/test_native_k3_differential.py:196, 221`;
  - every stale docstring or comment in the audit's Annex A §4, Annex B §B (rows marked **yes**) and Annex C C8. Exclude `planet.py`, `ai.py`'s ProximityCheck block and any other owned file.
  - `engine/cameras/__init__.py:113-118`: replace "within 10% … Galaxy 4.03 vs 4.46" with the audit §2.3 numbers (BC live 4.366; corner rule −8% to +64% across the fleet);
  - native comments at `native/src/combat/src/sensor_detect.cc:432-439`, `projectile_geometry.cc:132`, `beam_geometry.h:77`, `k4_eligibility.cc:80`.
- Test: `tests/unit/test_collision_radius_scale.py`.

**Interfaces:**
- Consumes: Task 2's `GetRadius()`.
- Produces: `collisions.world_radius(obj)`. For an `ObjectClass` it returns `float(obj.GetRadius())`; the DebrisChunk and duck-type paths are unchanged.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_collision_radius_scale.py`:

```python
def test_world_radius_is_get_radius_for_objects(monkeypatch):
    from engine.appc.objects import ObjectClass
    rock = _rock(1.2, 5.0)
    monkeypatch.setattr(ObjectClass, "GetRadius", lambda self: 42.0)
    assert collisions.world_radius(rock) == 42.0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_collision_radius_scale.py::test_world_radius_is_get_radius_for_objects -v`

Expected: it fails, returning 6.0 (`world_radius` still reads base × scale).

- [ ] **Step 3: Implement**

1. Make the ObjectClass branch of `world_radius` return `GetRadius()`.
2. Change `test_native_k3_differential.py`'s `GetRadius() * GetScale()` to `GetRadius()`.
3. Rewrite the stale prose.

Code otherwise unchanged.

- [ ] **Step 4: Run the Task 2 Step 4 list again, plus `tests/host/test_native_k3_differential.py`**

Expected: all pass. That `test_native_beam_geometry.py:519` (`world_radius` bad-scale fuzz) and `test_native_beam_trace.py:283` stay green proves the collapse matches the C++ bit for bit.

- [ ] **Step 5: Commit**

Stage `engine/appc/collisions.py`, `tests/host/test_native_k3_differential.py`, `tests/unit/test_collision_radius_scale.py`, and each prose file by explicit path.

Message: `refactor(radius): world_radius is GetRadius(); docs no longer call GetRadius unscaled`.

---

### Task 4: Hand-off for the live check and the merge (no code)

**Files:**
- Modify: `docs/reference/engine/native-motion/radius-scale-audit.md`: add an "Outcome" section with the Task 2 sweep and golden results.

- [ ] **Step 1: Record the outcome.** Add the commit ids, "goldens byte-identical: yes/no", and "sweep: N passed" to the audit's Outcome section. Commit that file alone.
- [ ] **Step 2: Give Mark the live check** (design §9 item 4) as a plain launch command, `cd .claude/worktrees/scaled-getradius && ./build/dauntless --developer`, plus the four things to look at:
  1. the E1M2 intercept tutorial on a fragment;
  2. the reticle and range readout on Vesuvi rocks;
  3. a course through the rocks;
  4. a starbase docking.
- [ ] **Step 3: Send the proximity session the design's §7 requests.** Do not edit their files.
- [ ] **Step 4: Stop.** The merge into `project/native-motion-and-proximity` happens only when Mark says.

---

## D1 (merged bounding sphere): not on this branch

Mark ruled (a) on 2026-11-03: the corner rule stays, and this plan has no D1 task. The sphere rule is a later, separate change; had (b) been chosen, a fifth task would have followed Task 3:
- the merged world-bound sphere is computed in the NIF loader from `NiTriShapeData` bounds and node transforms;
- `_seed_ship_radius` uses it;
- it lands as its own behaviour commit, with its own sweep, goldens and live check.
