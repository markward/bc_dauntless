# Rock Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep large scenery rocks out of 0.5-density belts (Vesuvi's story scenes), promote the nearest big field rocks to targetable `RockClass` objects, and make NPCs steer round large field rocks.

**Architecture:** The native near band (`rock_near.cc`) gains a large-rock density ramp, a per-key exclusion list and a camera-independent query. A new sim-side Python module (`engine/rocks/promotion.py`) uses the query to promote/demote up to 8 rocks around the player and keeps a session record. Collision avoidance merges the same query's spheres into its avoid list and switches to scaled radii.

**Tech Stack:** C++17 (renderer, pybind11 bindings in `native/src/host/host_bindings.cc`), Python 3 engine, gtest + pytest; the gate is `scripts/check_tests.sh`.

**Spec:** `docs/superpowers/specs/2026-10-05-rock-promotion-design.md` (read it first; its "Facts" section has the file:line map).

## Global Constraints

- Work only in this worktree (`.claude/worktrees/rock-promotion`, branch `feat/rock-promotion`). Never commit to main; never push.
- Destructive git (`checkout --`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`/`add .`) is banned. Stage explicit paths. To mutate a file temporarily: `cp f /tmp/bak` … `cp /tmp/bak f` … `diff f /tmp/bak`. Never `pkill`/`killall` anything.
- Never launch the game (`./build/dauntless`). Headless tests only.
- Units are GU (1 GU = 175 m). Rotation matrices are column-vector, right-handed (`R.GetCol(1)` = forward). Never name a variable `*_m`.
- Native field coordinates are **system** coordinates; Python object positions are **viewed-set (view-space)** coordinates; `system = anchor + view`, with `anchor` from `far_tier.frame_for(view_set)[1]`.
- A near rock's key is `rock_key(cell_key(source.id, cls, ijk), index)`, `index` = its position in `generate_near_cell`'s output. Never filter inside `generate_near_cell` by key (it would shift indices and change every later key in the cell).
- Promoted rock names: `"Field Rock %04X" % (key & 0xFFFF)`; never starting with `"Asteroid"`.
- Dials (defaults verbatim): `promote_min_radius_gu` 4.0, `promote_range_gu` 300.0, `promote_max` 8, `demote_range_mult` 1.5, `promote_hz` 4.0, `large_ramp_lo` 0.5, `large_ramp_hi` 1.0, `avoid_query_radius_gu` 150.0.
- Nothing in this plan may mutate game state from `render_payload` or the render-side `_reconcile_scene`; promotion runs sim side.
- GL tests SKIP inside sandboxes: run `ctest` / gtest binaries and `scripts/check_tests.sh` with the sandbox disabled.
- Build: `cmake --build build -j` from the worktree root (never cmake from `native/`). A binding change needs the `dauntless` target rebuilt (it builds the Python module too).
- Baseline: before Task 1 the controller records which tests fail on the untouched branch (`scripts/check_tests.sh`). Any failure not in that baseline is yours.

## Review Focus

1. **A rock sitting exactly at the promotion-range edge** must not promote/demote every tick (hysteresis 300 → 450 GU) — pinned in Task 4.
2. **Targeting a promoted rock then flying away** must not demote it from under the target lock; demotion waits until it is untargeted — pinned in Task 4.
3. **Dash start with rocks promoted**: every promoted rock demotes at once (the speck band holds rocks from mesh range during a dash and would otherwise double-draw them) — pinned in Task 5.
4. **Mission swap mid-field** must leave no orphan promoted objects and no stale exclusion keys in native — pinned in Task 5.
5. **An NPC avoiding while the field is off or the set is unmapped** gets no field obstacles and no exception — pinned in Task 6.

## Rulings made while planning (deviations from the spec text)

- **R1 — No speck-band exclusion.** The spec says the exclusion "applies to the near band and the speck band". Instead: the demote distance is capped at `near_large_billboard_gu - near_fade_gu - 1` (400 GU by default, below the 405 GU speck start), and dash start demotes everything. A promoted rock is then never inside the speck band's range, so the speck band needs no change. Task 7 amends the spec.
- **R2 — Promoted rocks have no halo.** `minors.halo_spec` returns None for a rock carrying `_field_key`; scenery large rocks have no halo, so a halo would pop in at promotion.
- **R3 — Death detection by polling.** No rock-died callback exists; promotion polls `rocks.death.is_dying_rock` and set membership each promotion tick (4 Hz). A dying or vanished promoted rock's key joins the destroyed set.

---

### Task 1: Large-rock density ramp (native + Python twin + dials)

**Files:**
- Modify: `native/src/renderer/include/renderer/rock_near.h` (struct `NearDials`; new free function `large_ramp`)
- Modify: `native/src/renderer/rock_near.cc` (`generate_near_cell`, `same_generator` usage in `NearField::set_dials`)
- Modify: `native/src/host/host_bindings.cc` (`near_dials_of`, ~line 2672)
- Modify: `engine/rocks/far_dials.py` (DEFAULTS + `NATIVE_KEYS`)
- Modify: `engine/rocks/density.py` (Python twin `large_ramp`)
- Test: `native/tests/renderer/rock_near_test.cc`, `tests/unit/test_far_density.py`, `tests/unit/test_far_dials.py`

**Interfaces:**
- Produces (C++): `float renderer::rockfield::large_ramp(float a, float lo, float hi)` — 0 for `a <= lo`, 1 for `a >= hi`, linear between; `hi <= lo` → step at `lo` (0 at or below, 1 above). `NearDials::large_ramp_lo = 0.5f`, `NearDials::large_ramp_hi = 1.0f`.
- Produces (Python): `density.large_ramp(a: float, lo: float, hi: float) -> float` (same rule); far_dials keys `"large_ramp_lo": 0.5`, `"large_ramp_hi": 1.0`, both in `NATIVE_KEYS`.

- [ ] **Step 1: Write the failing C++ tests** (append to `native/tests/renderer/rock_near_test.cc`)

```cpp
TEST(NearRamp, LargeRampRule) {
    using rockfield::large_ramp;
    EXPECT_EQ(large_ramp(0.0f, 0.5f, 1.0f), 0.0f);
    EXPECT_EQ(large_ramp(0.5f, 0.5f, 1.0f), 0.0f);
    EXPECT_NEAR(large_ramp(0.75f, 0.5f, 1.0f), 0.5f, 1e-6f);
    EXPECT_EQ(large_ramp(1.0f, 0.5f, 1.0f), 1.0f);
    EXPECT_EQ(large_ramp(2.0f, 0.5f, 1.0f), 1.0f);
    EXPECT_EQ(large_ramp(0.5f, 0.5f, 0.5f), 0.0f);   // hi <= lo: a step at lo
    EXPECT_EQ(large_ramp(0.51f, 0.5f, 0.5f), 1.0f);
}

namespace {
far::DiscSource flat_belt(float a) {   // a constant `a` across a huge flat disc, no noise
    far::DiscSource s; s.id = 7; s.seed = 5; s.table = {{0.0f, a}, {1e7f, a}};
    s.scale_height_min_gu = 1e7f;
    return s;
}
double mean_count(const far::DiscSource& s, rockfield::NearClass cls, const rockfield::NearDials& d, int cells) {
    double n = 0;
    for (int i = 0; i < cells; ++i) n += rockfield::generate_near_cell(s, cls, {i, 2, 0}, d, cat()).size();
    return n / cells;
}
}

TEST(NearRamp, NoLargeRocksAtHalfDensity) {     // Vesuvi's 0.5 band: small rocks only
    rockfield::NearDials d;
    EXPECT_EQ(mean_count(flat_belt(0.5f), rockfield::NearClass::Large, d, 400), 0.0);
    EXPECT_GT(mean_count(flat_belt(0.5f), rockfield::NearClass::Small, d, 400), 0.0);
}

TEST(NearRamp, LargeDensityFollowsTheRamp) {
    rockfield::NearDials d;
    d.large.density = 1.0f / 2000.0f;   // ~62 candidates per 50 GU cell: a stable mean
    const double full = mean_count(flat_belt(1.0f), rockfield::NearClass::Large, d, 300);
    const double three_q = mean_count(flat_belt(0.75f), rockfield::NearClass::Large, d, 300);
    ASSERT_GT(full, 20.0);
    // density x a x ramp(a): 0.75 x 0.5 = 0.375 of full
    EXPECT_NEAR(three_q / full, 0.375, 0.05);
}

TEST(NearRamp, FullDensityUnchanged) {          // tile-field interiors (a = 1) keep every rock
    rockfield::NearDials on, off;
    off.large_ramp_lo = -1.0f; off.large_ramp_hi = 0.0f;   // ramp == 1 for every a >= 0
    for (int i = 0; i < 50; ++i) {
        const auto a = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, {i, 1, 1}, on, cat());
        const auto b = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, {i, 1, 1}, off, cat());
        ASSERT_EQ(a.size(), b.size());
        for (size_t k = 0; k < a.size(); ++k) EXPECT_EQ(a[k].pos_sys, b[k].pos_sys);
    }
}

TEST(NearRamp, RampDialChangeClearsCells) {
    rockfield::NearField f;
    f.set_catalogue(cat());
    f.set_sources({full_sphere()});
    f.stream({0, 0, 0});
    ASSERT_GT(f.stats().cells, 0);
    rockfield::NearDials d = f.dials();
    d.large_ramp_lo = 0.25f;
    f.set_dials(d);
    EXPECT_EQ(f.stats().cells, 0);
}
```

- [ ] **Step 2: Build and run to verify they fail**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -5` (if the target name differs, `grep -n rock_near_test native/tests/CMakeLists.txt` names it), then `./build/native/tests/renderer_tests --gtest_filter='NearRamp.*'` (path: `find build -name 'renderer_tests' -type f`).
Expected: compile error (`large_ramp` / `large_ramp_lo` undeclared).

- [ ] **Step 3: Implement**

In `rock_near.h`, inside `struct NearDials` after `large{...}`:

```cpp
    // Large rocks follow the majors threshold (rock-promotion spec P2): their
    // density is multiplied by large_ramp(a), 0 at or below lo, 1 at or above
    // hi. a is the source's a(x) (far::density_a), never the noise-multiplied
    // field density, so a clump cannot lift a 0.5 band over the threshold.
    float large_ramp_lo = 0.5f;
    float large_ramp_hi = 1.0f;
```

and after `struct NearDials`:

```cpp
// 0 for a <= lo, 1 for a >= hi, linear between; hi <= lo is a step at lo.
float large_ramp(float a, float lo, float hi);
```

In `rock_near.cc` (namespace scope, before `generate_near_cell`):

```cpp
float large_ramp(float a, float lo, float hi) {
    if (!(a > lo)) return 0.0f;
    if (!(hi > lo) || a >= hi) return 1.0f;
    return (a - lo) / (hi - lo);
}
```

In `generate_near_cell`, replace the `n_bound` and accept lines:

```cpp
    const bool large = cls == NearClass::Large;
    const float a_hi_cell = far::a_bound(s, lo + 0.5 * L, 0.5 * L);
    const float ramp_bound = large ? large_ramp(a_hi_cell, d.large_ramp_lo, d.large_ramp_hi) : 1.0f;
    const double n_bound = static_cast<double>(c.density) * a_hi_cell * ramp_bound *
                           far::noise_m_bound(s);
```

```cpp
        float dens = far::field_density(s, p);
        if (large) dens *= large_ramp(far::density_a(s, p), d.large_ramp_lo, d.large_ramp_hi);
        if (accept >= c.density * dens / n_bound) continue;
```

(`large_ramp` is monotonic and `a_bound >= density_a` inside the cell, so `ramp_bound` bounds the per-point ramp and the rejection stays exact.)

In `NearField::set_dials`, the ramp changes which large rocks exist, so it must regenerate:

```cpp
    const bool regen = !same_generator(d.small, dials_.small) || !same_generator(d.large, dials_.large) ||
                       d.large_ramp_lo != dials_.large_ramp_lo || d.large_ramp_hi != dials_.large_ramp_hi;
```

Check `rock_speck.cc`'s `set_near_dials` regenerate test the same way (it calls `generate_near_cell` with its `near_` copy): if it compares only `same_generator(...)` on the classes, add the same two ramp comparisons there.

In `host_bindings.cc` `near_dials_of`, beside `f("near_tumble_scale", o.tumble_scale);`:

```cpp
    f("large_ramp_lo", o.large_ramp_lo);
    f("large_ramp_hi", o.large_ramp_hi);
```

In `engine/rocks/far_dials.py` DEFAULTS add `"large_ramp_lo": 0.5, "large_ramp_hi": 1.0,` (comment: `# rock-promotion P2: large rocks 0 at a <= 0.5, full at 1.0`) and add both names to `NATIVE_KEYS`.

In `engine/rocks/density.py`:

```python
def large_ramp(a: float, lo: float, hi: float) -> float:
    """renderer::rockfield::large_ramp's twin: 0 for a <= lo, 1 for a >= hi,
    linear between; hi <= lo is a step at lo (rock-promotion spec P2)."""
    if not a > lo:
        return 0.0
    if not hi > lo or a >= hi:
        return 1.0
    return (a - lo) / (hi - lo)
```

- [ ] **Step 4: Python tests** (append to `tests/unit/test_far_density.py`)

```python
import pytest
from engine.rocks import density


@pytest.mark.parametrize("a,expected", [
    (0.0, 0.0), (0.5, 0.0), (0.75, 0.5), (1.0, 1.0), (2.0, 1.0)])
def test_large_ramp_matches_the_native_rule(a, expected):
    assert density.large_ramp(a, 0.5, 1.0) == pytest.approx(expected)


def test_large_ramp_step_when_hi_not_above_lo():
    assert density.large_ramp(0.5, 0.5, 0.5) == 0.0
    assert density.large_ramp(0.51, 0.5, 0.5) == 1.0


def test_vesuvi_band_is_exactly_the_ramp_floor():
    """The Geki -> Haven band (226k-330k GU) is a = 0.5, so ramp 0: no large
    rocks in Vesuvi's story scenes."""
    s = density.profile_belt("Vesuvi")
    assert s is not None
    for r in (230000.0, 280000.0, 327000.0):
        a = density.evaluate(s, (r, 0.0, 0.0))
        assert density.large_ramp(a, 0.5, 1.0) == 0.0
```

and to `tests/unit/test_far_dials.py`:

```python
def test_large_ramp_dials_are_native_with_the_spec_defaults():
    from engine.rocks import far_dials as fd
    assert fd.DEFAULTS["large_ramp_lo"] == 0.5
    assert fd.DEFAULTS["large_ramp_hi"] == 1.0
    assert {"large_ramp_lo", "large_ramp_hi"} <= fd.NATIVE_KEYS
```

(If `test_far_dials.py` has a test asserting the native/Python default parity list — e.g. comparing DEFAULTS to `NearDials` — extend it with the two keys rather than duplicating.)

- [ ] **Step 5: Run everything touched**

Run: `./<renderer_tests> --gtest_filter='NearRamp.*:NearCells.*:NearStream.*:Rock*'` and `uv run pytest tests/unit/test_far_density.py tests/unit/test_far_dials.py tests/host/test_far_bindings.py tests/host/test_rock_near_host.py -q` (sandbox disabled).
Expected: all pass. Also run the `RockPerfEquivalence.*` tests and confirm their pass/fail set equals the controller's baseline (their sources are full density, so the ramp is 1 and digests must not move; if one changes, stop and report — it means `a < 1` somewhere in that fixture).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/rock_near.h native/src/renderer/rock_near.cc native/src/renderer/rock_speck.cc native/src/host/host_bindings.cc engine/rocks/far_dials.py engine/rocks/density.py native/tests/renderer/rock_near_test.cc tests/unit/test_far_density.py tests/unit/test_far_dials.py
git commit -m "feat(rock-promotion): large near rocks follow the majors ramp (0 at a<=0.5, full at 1.0)"
```

(Drop `rock_speck.cc` from the list if it needed no change.)

---

### Task 2: Native per-key exclusion and the large-rock query

**Files:**
- Modify: `native/src/renderer/include/renderer/rock_near.h` (`NearField`: `set_excluded`, `excluded`, `query_large`, query cache)
- Modify: `native/src/renderer/rock_near.cc`
- Modify: `native/src/host/host_bindings.cc` (two bindings; `far_clear` clears the exclusion)
- Modify: `engine/renderer.py` (façade wrappers, following the existing `rockfield_*` wrappers there)
- Test: `native/tests/renderer/rock_near_test.cc`, `tests/host/test_rock_near_host.py`

**Interfaces:**
- Consumes: Task 1's `generate_near_cell` (unchanged signature).
- Produces (C++):
  - `void NearField::set_excluded(std::unordered_set<std::uint64_t> keys)` — Large-class keys that `build()` draws nothing for and `step()` reports no contact for. Kept across `stream()`; cleared by `clear()`.
  - `struct NearQueryHit { std::uint64_t key; NearRock rock; };`
  - `std::vector<NearQueryHit> NearField::query_large(const glm::dvec3& centre_sys, double radius_gu, float min_radius_gu) const` — every Large rock of every current source with `radius >= min_radius_gu` and `|pos_sys - centre_sys| <= radius_gu`, **including excluded keys**, sorted by distance ascending (ties by key). Generates the cells it needs with `generate_near_cell(s, Large, ijk, dials_, cat_)`; keys are `rock_key(cell_key(s.id, Large, ijk), index)` — identical to the streamed keys. Independent of `stream()`/camera.
- Produces (Python, `_dauntless_host` and `engine.renderer`):
  - `rockfield_set_promoted(keys: list[int]) -> None`
  - `rockfield_query_large(centre_sys: tuple[float,float,float], radius_gu: float, min_radius_gu: float) -> list[dict]`, each dict `{"key": int, "pos": (x,y,z) system, "radius": float, "rock": int (catalogue index), "axis": (x,y,z), "rate": float, "phase": float}`.

- [ ] **Step 1: Write the failing C++ tests** (append to `rock_near_test.cc`)

```cpp
namespace {
rockfield::NearField streamed_field() {
    rockfield::NearField f;
    f.set_catalogue(cat());
    f.set_sources({full_sphere()});
    f.stream({0, 0, 0});
    return f;
}
std::map<std::uint64_t, rockfield::NearRock> streamed_large(const rockfield::NearField& f) {
    std::map<std::uint64_t, rockfield::NearRock> m;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock& r) { m[k] = r; });
    return m;
}
}

TEST(NearQuery, MatchesTheStreamedRocksInRange) {
    auto f = streamed_field();
    const auto streamed = streamed_large(f);
    const glm::dvec3 c{12.0, -30.0, 7.0};
    const auto hits = f.query_large(c, 200.0, 0.0f);
    ASSERT_FALSE(hits.empty());
    std::size_t in_range = 0;
    for (const auto& [k, r] : streamed) if (glm::length(r.pos_sys - c) <= 200.0) ++in_range;
    EXPECT_EQ(hits.size(), in_range);
    for (const auto& h : hits) {
        const auto it = streamed.find(h.key);
        ASSERT_NE(it, streamed.end());
        EXPECT_EQ(it->second.pos_sys, h.rock.pos_sys);
        EXPECT_EQ(it->second.radius, h.rock.radius);
        EXPECT_EQ(it->second.rock, h.rock.rock);
        EXPECT_EQ(it->second.phase, h.rock.phase);
    }
    for (std::size_t i = 1; i < hits.size(); ++i)
        EXPECT_LE(glm::length(hits[i - 1].rock.pos_sys - c), glm::length(hits[i].rock.pos_sys - c));
}

TEST(NearQuery, IndependentOfStreaming) {   // works far from anything streamed (NPCs)
    rockfield::NearField a = streamed_field();
    rockfield::NearField b; b.set_catalogue(cat()); b.set_sources({full_sphere()});   // never streamed
    const glm::dvec3 c{3000.0, 0.0, 0.0};
    const auto ha = a.query_large(c, 150.0, 0.0f), hb = b.query_large(c, 150.0, 0.0f);
    ASSERT_EQ(ha.size(), hb.size());
    for (std::size_t i = 0; i < ha.size(); ++i) EXPECT_EQ(ha[i].key, hb[i].key);
}

TEST(NearQuery, MinRadiusFilters) {
    auto f = streamed_field();
    for (const auto& h : f.query_large({0, 0, 0}, 300.0, 4.0f)) EXPECT_GE(h.rock.radius, 4.0f);
}

TEST(NearExclude, ExcludedKeyIsNotDrawnButNeighboursAre) {
    auto f = streamed_field();
    rockfield::NearBuildInput in;
    in.view = glm::lookAt(glm::vec3(0, 0, 0), glm::vec3(0, 1, 0), glm::vec3(0, 0, 1));
    in.proj = glm::perspective(glm::radians(170.0f), 1.0f, 0.1f, 5000.0f);   // nearly everything in view
    rockfield::NearOutput before; f.build(in, before);
    const auto hits = f.query_large({0, 0, 0}, 50.0, 0.0f);   // inside mesh range
    ASSERT_FALSE(hits.empty());
    f.set_excluded({hits[0].key});
    rockfield::NearOutput after; f.build(in, after);
    EXPECT_EQ(after.mesh_count + after.billboard_count, before.mesh_count + before.billboard_count - 1);
    f.stream({1.0, 0.0, 0.0});                                // survives a stream
    rockfield::NearOutput again; f.build(in, again);
    EXPECT_EQ(again.mesh_count + again.billboard_count, after.mesh_count + after.billboard_count);
}

TEST(NearExclude, ExcludedKeyMakesNoContact) {
    rockfield::NearField f; f.set_catalogue(cat());
    rockfield::NearRock r; r.pos_sys = {0, 10, 0}; r.radius = 3.0f;
    f.debug_add_rock(rockfield::NearClass::Large, 42, r);
    f.set_excluded({42});
    rockfield::NearStepInput in;
    minors::PlayerBox box;   // fill exactly as the existing contact tests in this file do
    // ... sweep the box from (0,-20,0) to (0,10,0) over two steps, as an
    //     existing large-contact test here does (copy its setup verbatim) ...
    EXPECT_TRUE(f.drain_large_contacts().empty());
}

TEST(NearExclude, ClearDropsTheExclusion) {
    auto f = streamed_field();
    f.set_excluded({1, 2, 3});
    f.clear();
    EXPECT_TRUE(f.excluded().empty());
}
```

For `ExcludedKeyMakesNoContact`, find the existing large-contact test in this file (`grep -n "drain_large_contacts" native/tests/renderer/rock_near_test.cc`), copy its box/sweep setup exactly, and assert the same sweep yields a contact **without** `set_excluded` (a control line in the same test) and none with it.

- [ ] **Step 2: Build; verify failure** (compile errors: `query_large`, `set_excluded`, `excluded` undeclared).

- [ ] **Step 3: Implement**

`rock_near.h`, inside `NearField` public:

```cpp
    // Rock promotion (rock-promotion spec §2): Large-class keys promoted to
    // real objects. build() draws nothing for them and step() reports no
    // contact; kept across stream(), dropped by clear().
    void set_excluded(std::unordered_set<std::uint64_t> keys) { excluded_ = std::move(keys); }
    const std::unordered_set<std::uint64_t>& excluded() const { return excluded_; }
    // Every Large rock of every current source with radius >= min_radius_gu
    // within radius_gu of centre_sys (system coords), excluded keys included,
    // nearest first (ties by key). Generates the cells it needs exactly as
    // stream() does (same keys); never depends on what is streamed.
    std::vector<NearQueryHit> query_large(const glm::dvec3& centre_sys, double radius_gu,
                                          float min_radius_gu) const;
```

with `struct NearQueryHit { std::uint64_t key = 0; NearRock rock; };` declared before `class NearField`, and private members:

```cpp
    std::unordered_set<std::uint64_t> excluded_;
    // query_large's cell cache: cell key -> generated rocks. Bounded (cleared
    // whole past kQueryCacheMax); cleared with the cells on any generator,
    // source or catalogue change.
    static constexpr std::size_t kQueryCacheMax = 4096;
    mutable std::unordered_map<std::uint64_t, std::vector<NearRock>> query_cache_;
```

`rock_near.cc`:

```cpp
std::vector<NearQueryHit> NearField::query_large(const glm::dvec3& c, double radius,
                                                 float min_r) const {
    std::vector<NearQueryHit> out;
    const double L = dials_.large.cell_gu;
    if (!(L > 0.0) || !(radius >= 0.0)) return out;
    const glm::i64vec3 lo_i(glm::floor((c - radius) / L)), hi_i(glm::floor((c + radius) / L));
    for (const far::DiscSource& s : sources_) {
        if (!reaches(s, c, radius)) continue;
        for (std::int64_t i = lo_i.x; i <= hi_i.x; ++i)
        for (std::int64_t j = lo_i.y; j <= hi_i.y; ++j)
        for (std::int64_t k = lo_i.z; k <= hi_i.z; ++k) {
            const glm::i64vec3 ijk{i, j, k};
            if (aabb_distance(c, glm::dvec3(ijk) * L, L) > radius) continue;
            const std::uint64_t ck = cell_key(s.id, NearClass::Large, ijk);
            auto it = query_cache_.find(ck);
            if (it == query_cache_.end()) {
                if (query_cache_.size() >= kQueryCacheMax) query_cache_.clear();
                it = query_cache_.emplace(ck, generate_near_cell(s, NearClass::Large, ijk, dials_, cat_)).first;
            }
            const auto& rocks = it->second;
            for (std::size_t n = 0; n < rocks.size(); ++n) {
                const NearRock& r = rocks[n];
                if (r.radius < min_r || glm::length(r.pos_sys - c) > radius) continue;
                out.push_back({rock_key(ck, n), r});
            }
        }
    }
    std::sort(out.begin(), out.end(), [&c](const NearQueryHit& a, const NearQueryHit& b) {
        const double da = glm::length(a.rock.pos_sys - c), db = glm::length(b.rock.pos_sys - c);
        return da != db ? da < db : a.key < b.key;
    });
    return out;
}
```

Use the member that holds the current sources (`grep -n "sources_" native/src/renderer/include/renderer/rock_near.h`; if it is named differently, use that name). Add `query_cache_.clear();` and `excluded_.clear();` to `NearField::clear()`, and `query_cache_.clear();` wherever `set_sources` decides the sources changed (it calls `clear()` then — confirm).

Skip excluded keys:
- In `build()`'s candidate gathering for the Large class (the `visit(key, *cp, ...)` lambda computes each rock's key via the line at `:541`, `c.pinned ? c.keys[i] : rock_key(cell, i)`): `if (cls == NearClass::Large && !excluded_.empty() && excluded_.count(rk)) continue;` — find the loop that emits `Cand`s and add it where the rock key is known.
- In `step()`'s `process_large` lambda: return early when the rock's key is excluded, before any contact or ghost bookkeeping.

`host_bindings.cc` (beside `rockfield_rearm`):

```cpp
    m.def("rockfield_set_promoted",
          [](py::list keys) {
              std::unordered_set<std::uint64_t> s;
              for (const auto& k : keys) s.insert(k.cast<std::uint64_t>());
              g_near_field.set_excluded(std::move(s));
          },
          py::arg("keys"),
          "Large near-rock keys promoted to real objects (rock-promotion): the "
          "near band draws nothing and reports no contact for them. Replaces the list.");
    m.def("rockfield_query_large",
          [](std::tuple<double, double, double> c, double radius, float min_r) {
              py::list out;
              for (const auto& h : g_near_field.query_large(
                       {std::get<0>(c), std::get<1>(c), std::get<2>(c)}, radius, min_r)) {
                  py::dict d;
                  d["key"] = h.key;
                  d["pos"] = py::make_tuple(h.rock.pos_sys.x, h.rock.pos_sys.y, h.rock.pos_sys.z);
                  d["radius"] = h.rock.radius;
                  d["rock"] = h.rock.rock;
                  d["axis"] = py::make_tuple(h.rock.tumble_axis.x, h.rock.tumble_axis.y, h.rock.tumble_axis.z);
                  d["rate"] = h.rock.tumble_rate;
                  d["phase"] = h.rock.phase;
                  out.append(d);
              }
              return out;
          },
          py::arg("centre_sys"), py::arg("radius_gu"), py::arg("min_radius_gu"),
          "Large near rocks (every current source) with radius >= min_radius_gu "
          "within radius_gu of centre_sys (SYSTEM coords), nearest first: "
          "[{'key', 'pos' (system), 'radius', 'rock' (catalogue index), 'axis', "
          "'rate', 'phase'}, ...]. Includes promoted keys. Camera-independent.");
```

`far_clear` already calls `g_near_field.clear()`, which now drops the exclusion — no extra line needed; verify.

`engine/renderer.py`: add `rockfield_set_promoted(keys)` and `rockfield_query_large(centre_sys, radius_gu, min_radius_gu)` wrappers next to `rockfield_drain_contacts`, copying that wrapper's shape exactly (including its behaviour when `_h` is unavailable).

- [ ] **Step 4: Host test** (append to `tests/host/test_rock_near_host.py`; reuse that file's existing source/catalogue setup helpers — read its top first)

```python
def test_query_large_returns_system_space_rocks_and_promoted_set_hides_one():
    _setup_full_field()          # the file's existing helper that pushes a full-density source + catalogue
    hits = h.rockfield_query_large((0.0, 0.0, 0.0), 300.0, 0.0)
    assert hits, "a full-density field has large rocks within 300 GU"
    d = [((x["pos"][0] ** 2 + x["pos"][1] ** 2 + x["pos"][2] ** 2) ** 0.5) for x in hits]
    assert d == sorted(d)
    assert all(set(x) >= {"key", "pos", "radius", "rock", "axis", "rate", "phase"} for x in hits)
    h.rockfield_set_promoted([hits[0]["key"]])
    again = h.rockfield_query_large((0.0, 0.0, 0.0), 300.0, 0.0)
    assert [x["key"] for x in again] == [x["key"] for x in hits]   # query ignores the exclusion
    h.far_clear()
```

If the file has no such helper, write `_setup_full_field()` at the top of the test using `tests/host/test_far_bindings.py::_source` with `"shape": "sphere"`, `"sphere_radius_gu": 10000.0`, `"view_space": False`, `"sphere_edge_frac": 0.0` and a `far_set_catalogue` call shaped like the one in `test_rock_near_host.py`.

- [ ] **Step 5: Build `dauntless` + tests; run**

Run: `cmake --build build -j` then the gtest filter `'NearQuery.*:NearExclude.*:NearCells.*:NearStream.*'` and `uv run pytest tests/host/test_rock_near_host.py tests/host/test_far_bindings.py -q` (sandbox disabled). Expected: pass; RockPerfEquivalence pass/fail set unchanged from baseline.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/rock_near.h native/src/renderer/rock_near.cc native/src/host/host_bindings.cc engine/renderer.py native/tests/renderer/rock_near_test.cc tests/host/test_rock_near_host.py
git commit -m "feat(rock-promotion): near band per-key exclusion and camera-independent large-rock query"
```

---

### Task 3: `RockClass_Create` — forced catalogue rock and exact radius

**Files:**
- Modify: `engine/rocks/rock.py` (`RockClass_Create`, `_catalogue_model`)
- Test: `tests/unit/test_rock_create.py` (create it if no `RockClass_Create` test file exists; `grep -rln "RockClass_Create" tests/unit` first and append there instead if one does)

**Interfaces:**
- Produces: `RockClass_Create(radius_gu, *, family="silicate", seed="", name="", kind="fragment", hull=None, mass=None, catalogue_index=None, exact_radius=False)`.
  - `catalogue_index` (int): use `catalogue.load()[catalogue_index]` as the model (its family becomes `_rock_family`), bypassing `catalogue.pick`. Out of range → fall back to the normal pick.
  - `exact_radius=True`: the model still loads at `r_q = stats.quantise_radius(radius_gu)` (shared models), and the rock is given `SetScale(radius_gu / r_q)`, so `effective_radius(rock) == radius_gu` (within 1e-9). Default `False` keeps today's behaviour byte-identical.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from engine.rocks import catalogue, rock as rockmod


def _major_index():
    for i, r in enumerate(catalogue.load()):
        if r.kind == "major":
            return i
    pytest.skip("catalogue has no majors")


def test_catalogue_index_forces_that_model():
    i = _major_index()
    want = catalogue.load()[i]
    rk = rockmod.RockClass_Create(4.37, name="Field Rock 0001", kind="major", catalogue_index=i)
    assert rk._model_override[0] == str(want.lod_paths[0])
    assert rk._rock_family == want.family


def test_exact_radius_scales_the_quantised_model():
    rk = rockmod.RockClass_Create(4.37, name="Field Rock 0002", kind="major", exact_radius=True)
    assert rk.GetRadius() == pytest.approx(4.4)          # 2 significant figures
    assert rk.GetScale() == pytest.approx(4.37 / 4.4)
    assert rockmod.effective_radius(rk) == pytest.approx(4.37, abs=1e-9)


def test_defaults_unchanged():
    rk = rockmod.RockClass_Create(4.37, name="Rock X")
    assert rk.GetScale() == pytest.approx(1.0)
    assert rk.GetRadius() == pytest.approx(4.4)


def test_bad_catalogue_index_falls_back_to_the_pick():
    rk = rockmod.RockClass_Create(2.0, name="Rock Y", kind="major", catalogue_index=10 ** 6)
    assert rk._model_override is not None
```

(Check the attribute names on the catalogue `Rock` record — `kind`, `family`, `lod_paths` — with `grep -n "class Rock\|kind\|family\|lod_paths" engine/rocks/catalogue.py`; adjust the test to the real names if they differ.)

- [ ] **Step 2: Run to verify failure**: `uv run pytest tests/unit/test_rock_create.py -q` → TypeError (unexpected keyword).

- [ ] **Step 3: Implement** in `rock.py`:

```python
def _catalogue_model(seed: str, kind: str, family: str, index=None):
    """(catalogue Rock or None, family actually used). `index` forces that
    catalogue entry (rock promotion: the generator's exact rock); an index
    out of range falls back to the seeded pick. Works with the catalogue
    toggle off: that toggle only governs redirecting stock NIFs."""
    from engine.rocks import catalogue
    if index is not None:
        rocks = catalogue.load()
        if 0 <= int(index) < len(rocks):
            r = rocks[int(index)]
            return r, getattr(r, "family", family)
    rock = catalogue.pick(seed, kind=kind, family=family)
    if rock is None:
        rock = catalogue.pick(seed, kind=kind, family="silicate")
        family = "silicate"
    if rock is None:
        return None, family
    return rock, family
```

In `RockClass_Create` add the two keyword parameters, pass `index=catalogue_index` to `_catalogue_model`, and after the model is set:

```python
    if exact_radius and r_q > 0.0:
        # Rock promotion: models are shared at the quantised radius; the
        # scale carries the remainder so effective_radius is the exact one.
        ship.SetScale(float(radius_gu) / r_q)
```

Update the docstring to describe both options.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_rock_create.py tests/unit -q -k "rock"` → pass.

- [ ] **Step 5: Commit**

```bash
git add engine/rocks/rock.py tests/unit/test_rock_create.py
git commit -m "feat(rock-promotion): RockClass_Create can force a catalogue rock and an exact radius"
```

---

### Task 4: `engine/rocks/promotion.py` — selection, promote, demote, session record

**Files:**
- Create: `engine/rocks/promotion.py`
- Modify: `engine/rocks/far_dials.py` (Python-only promotion dials)
- Modify: `engine/rocks/far_tier.py` (`on_dials_changed` ignores promotion keys)
- Modify: `engine/rocks/minors.py` (`halo_spec`: no halo for promoted rocks — ruling R2)
- Test: `tests/unit/test_rock_promotion.py`

**Interfaces:**
- Consumes: `renderer.rockfield_query_large`, `renderer.rockfield_set_promoted` (Task 2); `RockClass_Create(..., catalogue_index=, exact_radius=True)` (Task 3); `far_tier.frame_for(view_set) -> (system, anchor)`.
- Produces:
  - `promotion.tick(player, view_set, now, r) -> None` — the promotion step (rate-limited internally to `promote_hz`).
  - `promotion.demote_all(r) -> None` — every promoted rock back to scenery (hull fractions recorded).
  - `promotion.reset(r=None) -> None` — demote_all, then forget the session record.
  - `promotion.promoted() -> dict[int, object]` (key → rock, read-only view for tests and Task 6).
  - `promotion.field_name(key: int) -> str` = `"Field Rock %04X" % (key & 0xFFFF)`.
  - Rock attribute `_field_key` (int) set on every promoted rock.
- far_dials keys (Python-only, NOT in `NATIVE_KEYS`): `promote_min_radius_gu` 4.0, `promote_range_gu` 300.0, `promote_max` 8, `demote_range_mult` 1.5, `promote_hz` 4.0, `avoid_query_radius_gu` 150.0. Add a module constant `PROMOTION_KEYS` (frozenset of these six) in far_dials.

**Behaviour (implement exactly):**
- Rate limit: act only when `now - _last >= 1 / promote_hz` (first call always acts).
- Muted (no new promotions; existing ones still demote by distance): `player is None`, field disabled (`renderer.far_enabled()` false), player's containing set is not `view_set`, `minor_contact._muted(player)` (dashing or in `"warp"`), or `far_tier.frame_for(view_set)` gives no usable frame **and** no sources — simply: when the query returns `[]`, nothing promotes.
- Player system position: `anchor + player.GetWorldLocation()`.
- Candidates: `r.rockfield_query_large(p_sys, promote_range_gu, promote_min_radius_gu)`, minus keys in `_destroyed`, first `promote_max` (already nearest-first).
- Demote rule, per promoted key not in candidates: distance from player > `min(promote_range_gu * demote_range_mult, near_large_billboard_gu - near_fade_gu - 1.0)` (ruling R1) **and** `player.GetTarget() is not rock` **and** not `rocks.death.is_dying_rock(rock)`. A promoted rock that is dying, or is no longer in its set (`rock.GetContainingSet() is None`), moves its key to `_destroyed` and leaves `_promoted` without any set call (ruling R3). Demotion also happens when the count would exceed `promote_max` with a nearer candidate waiting: drop the farthest untargeted promoted rock.
- Promote, per candidate key not yet promoted: build with
  `RockClass_Create(hit["radius"], name=field_name(key), kind="major", catalogue_index=hit["rock"], exact_radius=True, seed=field_name(key))`;
  `rock._field_key = key`; position `hit["pos"] - anchor` via `SetTranslateXYZ`;
  rotation `R = TGMatrix3().MakeRotation(phase + rate * near_tumble_scale * now, axis)` via `SetMatrixRotation` (use `engine.appc.math.TGMatrix3` / `TGPoint3`; `near_tumble_scale` from `far_dials.get`);
  `SetAngularVelocity(TGPoint3(*(a * rate * near_tumble_scale for a in axis)), DIRECTION_WORLD_SPACE)`;
  `SetVelocity(TGPoint3(0,0,0))`; `SetTargetable(1)`, `SetScannable(1)`, `SetHailable(0)`;
  if `key in _damaged`: `GetHull().SetCondition(GetHull().GetMaxCondition() * _damaged.pop(key))`;
  `view_set.AddObjectToSet(rock, name)` (skip, logging via `dev_mode.log_swallowed`, if the name is taken).
- Demote: if hull fraction < 1, `_damaged[key] = fraction`; `rock.GetContainingSet().RemoveObjectFromSet(rock.GetName())`; drop from `_promoted`.
- After any change, push `r.rockfield_set_promoted(sorted(set(_promoted) | _destroyed))` (destroyed keys stay excluded so the field never regrows them).
- `now` is game time (`App.g_kUtopiaModule.GetGameTime()`, the clock the near band's `damage_decals_tick` feeds), supplied by the caller.
- Every renderer call wrapped in try/except → `dev_mode.log_swallowed("rock promotion …", e)`; `tick` never raises.

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_rock_promotion.py`). Use a fake renderer and a real `SetClass` (look at `tests/unit/test_scenery_contact.py` / `test_rock_*` for how they build a set + player ship headlessly, and reuse that fixture pattern):

```python
import math
import pytest

from engine.rocks import promotion


class FakeR:
    def __init__(self, hits):
        self.hits = hits              # list of query dicts, system coords
        self.promoted_pushes = []
    def far_enabled(self):
        return True
    def rockfield_query_large(self, c, radius, min_r):
        out = [h for h in self.hits
               if h["radius"] >= min_r and math.dist(h["pos"], c) <= radius]
        return sorted(out, key=lambda h: (math.dist(h["pos"], c), h["key"]))
    def rockfield_set_promoted(self, keys):
        self.promoted_pushes.append(list(keys))


def hit(key, x, y=0.0, z=0.0, radius=4.5, rock=0):
    return {"key": key, "pos": (x, y, z), "radius": radius, "rock": rock,
            "axis": (0.0, 0.0, 1.0), "rate": 0.3, "phase": 1.0}


@pytest.fixture
def world(monkeypatch):
    """A viewed set holding the player at the origin, anchor (0,0,0)."""
    # Build exactly as the existing headless rock tests do (SetClass + a
    # player ShipClass added to it, App.Game player set) -- copy that fixture.
    ...
    monkeypatch.setattr("engine.rocks.far_tier.frame_for", lambda vs: ("Test", (0.0, 0.0, 0.0)))
    promotion.reset()
    yield pset, player
    promotion.reset()


def test_promotes_the_nearest_up_to_the_cap(world):
    pset, player = world
    r = FakeR([hit(k, 20.0 * k) for k in range(1, 13)])   # 12 rocks, 20..240 GU
    promotion.tick(player, pset, 0.0, r)
    assert sorted(promotion.promoted()) == list(range(1, 9))
    assert r.promoted_pushes[-1] == list(range(1, 9))


def test_promoted_rock_matches_its_generator_rock(world):
    pset, player = world
    r = FakeR([hit(77, 100.0, 5.0, -3.0, radius=4.37)])
    promotion.tick(player, pset, 2.0, r)
    rock = promotion.promoted()[77]
    loc = rock.GetWorldLocation()
    assert (loc.x, loc.y, loc.z) == pytest.approx((100.0, 5.0, -3.0))
    from engine.rocks.rock import effective_radius
    assert effective_radius(rock) == pytest.approx(4.37)
    assert rock.GetName() == "Field Rock 004D"
    assert not rock.GetName().startswith("Asteroid")
    assert rock.IsTargetable() and rock.IsScannable() and not rock.IsHailable()
    assert pset.GetObject("Field Rock 004D") is rock


def test_small_rocks_and_far_rocks_are_not_promoted(world):
    pset, player = world
    r = FakeR([hit(1, 50.0, radius=3.9), hit(2, 350.0, radius=4.9)])
    promotion.tick(player, pset, 0.0, r)
    assert promotion.promoted() == {}


def test_no_flicker_at_the_range_edge(world):     # Review Focus 1
    pset, player = world
    r = FakeR([hit(5, 299.0)])
    promotion.tick(player, pset, 0.0, r)
    assert 5 in promotion.promoted()
    r.hits = [hit(5, 301.0)]                       # just outside promote range, inside demote range
    _move_rock(promotion.promoted()[5], 301.0)
    for t in (1.0, 2.0, 3.0):
        promotion.tick(player, pset, t, r)
    assert 5 in promotion.promoted()


def test_demotes_beyond_the_capped_demote_range(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    _move_player(player, -350.0)                    # rock now 450 GU away (> 400 cap)
    r.hits = []
    promotion.tick(player, pset, 1.0, r)
    assert promotion.promoted() == {}
    assert pset.GetObject("Field Rock 0005") is None
    assert r.promoted_pushes[-1] == []


def test_targeted_rock_is_not_demoted(world):     # Review Focus 2
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    player.SetTarget(promotion.promoted()[5].GetName())
    _move_player(player, -600.0)
    r.hits = []
    promotion.tick(player, pset, 1.0, r)
    assert 5 in promotion.promoted()


def test_damaged_rock_comes_back_damaged(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    hull = promotion.promoted()[5].GetHull()
    hull.SetCondition(hull.GetMaxCondition() * 0.25)
    _move_player(player, -600.0); r.hits = []
    promotion.tick(player, pset, 1.0, r)
    _move_player(player, 0.0); r.hits = [hit(5, 100.0)]
    promotion.tick(player, pset, 2.0, r)
    h2 = promotion.promoted()[5].GetHull()
    assert h2.GetCondition() / h2.GetMaxCondition() == pytest.approx(0.25)


def test_destroyed_rock_never_regrows(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    rock = promotion.promoted()[5]
    pset.RemoveObjectFromSet(rock.GetName())        # what ship_death.retire does
    promotion.tick(player, pset, 1.0, r)
    assert 5 not in promotion.promoted()
    promotion.tick(player, pset, 2.0, r)
    assert 5 not in promotion.promoted()
    assert 5 in r.promoted_pushes[-1]               # stays excluded natively


def test_rate_limited(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    n = len(r.promoted_pushes)
    r.hits = [hit(5, 100.0), hit(6, 110.0)]
    promotion.tick(player, pset, 0.1, r)            # < 1/4 s later
    assert 6 not in promotion.promoted() and len(r.promoted_pushes) == n


def test_muted_while_dashing(world, monkeypatch):
    pset, player = world
    monkeypatch.setattr("engine.rocks.minor_contact._muted", lambda p: True)
    promotion.tick(player, pset, 0.0, FakeR([hit(5, 100.0)]))
    assert promotion.promoted() == {}


def test_reset_removes_objects_and_forgets(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    promotion.reset(r)
    assert promotion.promoted() == {}
    assert pset.GetObject("Field Rock 0005") is None
    assert r.promoted_pushes[-1] == []


def test_promoted_rocks_get_no_halo(world):
    pset, player = world
    promotion.tick(player, pset, 0.0, FakeR([hit(5, 100.0)]))
    from engine.rocks import minors
    assert minors.halo_spec(promotion.promoted()[5], iid=1) is None


def test_promotion_dials_are_python_only():
    from engine.rocks import far_dials as fd
    assert fd.DEFAULTS["promote_min_radius_gu"] == 4.0
    assert fd.DEFAULTS["promote_range_gu"] == 300.0
    assert fd.DEFAULTS["promote_max"] == 8
    assert fd.DEFAULTS["demote_range_mult"] == 1.5
    assert fd.DEFAULTS["promote_hz"] == 4.0
    assert fd.DEFAULTS["avoid_query_radius_gu"] == 150.0
    assert not (fd.PROMOTION_KEYS & fd.NATIVE_KEYS)
```

`_move_player(player, x)` and `_move_rock(rock, x)` are two-line helpers in the test file calling `SetTranslateXYZ(x, 0, 0)`. Fill the `world` fixture from an existing headless set+player fixture (grep `tests/unit/test_scenery_contact.py` and `tests/unit/test_rock_*` for one); it must produce a player whose `GetContainingSet()` is `pset` and `GetTarget()` works with `SetTarget(name)` as `ShipClass` defines (check `engine/appc/ships.py` around line 1597 for the setter name and adjust).

- [ ] **Step 2: Run to verify failure**: `uv run pytest tests/unit/test_rock_promotion.py -q` → ImportError.

- [ ] **Step 3: Implement `engine/rocks/promotion.py`** to the behaviour list above. Skeleton:

```python
"""Rock promotion (docs/superpowers/specs/2026-10-05-rock-promotion-design.md §2-§3).

The nearest big near-band rocks around the player become real RockClass
objects -- the generator's exact rock -- so they can be targeted, scanned
and broken, and block torpedoes. Sim side (host_loop's rock_breakup scope),
never render side. Native draws nothing for a promoted or destroyed key
(rockfield_set_promoted). Session record: damaged keys come back damaged,
destroyed keys never regrow; reset() (mission swap) forgets both.
"""
from __future__ import annotations

import engine.dev_mode as dev_mode

_promoted: dict = {}      # key -> RockClass
_damaged: dict = {}       # key -> hull fraction (0, 1)
_destroyed: set = set()   # keys whose promoted rock died
_last = None              # game time of the last acting tick
_pushed = None            # last list sent to rockfield_set_promoted


def field_name(key: int) -> str:
    return "Field Rock %04X" % (int(key) & 0xFFFF)


def promoted() -> dict:
    return dict(_promoted)
```

followed by `_dial(name)` (reads `far_dials.get`), `_demote_cap()` (ruling R1), `_player_sys(player, anchor)`, `_promote(view_set, anchor, key, hit, now)`, `_demote(key)`, `_reap()` (R3), `_push(r)`, `tick`, `demote_all`, `reset` — each a few lines, implementing the behaviour list. Keep `tick` under ~50 lines by delegating to these helpers.

In `far_dials.py` add the six DEFAULTS (comment `# rock promotion (spec 2026-10-05 §5); Python-only, read at use`) and `PROMOTION_KEYS = frozenset({...})`. If far_dials has a "dial group" registration list for the `/ L O` keys (grep `dev_dial_groups` usage in far_dials.py), add the six keys to the "rock fields" group with sensible steps (radius 0.25, range 25, max 1, mult 0.1, hz 1, avoid radius 25).

In `far_tier.on_dials_changed`: `names = set(names) - fd.PROMOTION_KEYS` at the top, so a promotion dial never re-pushes sources.

In `minors.halo_spec`, first line after the docstring: `if getattr(rock, "_field_key", None) is not None: return None` with comment `# rock promotion R2: scenery large rocks have no halo; neither does their promoted twin`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_rock_promotion.py tests/unit/test_far_dials.py tests/unit/test_far_registry.py tests/unit -q -k "minor or far or promotion"` → pass.

- [ ] **Step 5: Commit**

```bash
git add engine/rocks/promotion.py engine/rocks/far_dials.py engine/rocks/far_tier.py engine/rocks/minors.py tests/unit/test_rock_promotion.py
git commit -m "feat(rock-promotion): promote the nearest big field rocks to RockClass with a session record"
```

---

### Task 5: Host wiring and lifecycle

**Files:**
- Modify: `engine/host_loop.py` (sim-side pump beside `_pump_scenery_contact` ~line 11294; mission-swap reset beside `_far_tier.reset` ~line 6887)
- Modify: `engine/rocks/promotion.py` (view-set change and dash-start demote-all)
- Test: `tests/unit/test_rock_promotion.py` (lifecycle tests), `tests/unit/test_far_host_wiring.py` (swap reset)

**Interfaces:**
- Consumes: Task 4's `promotion.tick / demote_all / reset`.
- Produces: `host_loop._pump_rock_promotion(player, session)`; promotion remembers the view set it promoted into (`_view_set`) and demotes all when the view set changes or when the player starts dashing / enters `"warp"` (Review Focus 3).

- [ ] **Step 1: Failing tests** (append to `tests/unit/test_rock_promotion.py`, reusing the `world` fixture and `FakeR`)

```python
def test_view_set_change_demotes_all_but_keeps_the_record(world):
    pset, player = world
    r = FakeR([hit(5, 100.0)])
    promotion.tick(player, pset, 0.0, r)
    hull = promotion.promoted()[5].GetHull()
    hull.SetCondition(hull.GetMaxCondition() * 0.5)
    other = _new_set("Other")                       # a second SetClass (same helper the fixture uses)
    promotion.tick(player, other, 1.0, FakeR([]))
    assert promotion.promoted() == {}
    assert pset.GetObject("Field Rock 0005") is None
    promotion.tick(player, pset, 2.0, r)            # back: comes back damaged
    h = promotion.promoted()[5].GetHull()
    assert h.GetCondition() / h.GetMaxCondition() == pytest.approx(0.5)


def test_dash_start_demotes_everything(world, monkeypatch):   # Review Focus 3
    pset, player = world
    r = FakeR([hit(5, 100.0), hit(6, 120.0)])
    promotion.tick(player, pset, 0.0, r)
    assert len(promotion.promoted()) == 2
    monkeypatch.setattr("engine.rocks.minor_contact._muted", lambda p: True)
    promotion.tick(player, pset, 1.0, r)
    assert promotion.promoted() == {}
    assert r.promoted_pushes[-1] == []
```

and in `tests/unit/test_far_host_wiring.py`, beside the existing swap test that uses `_FakeSwapRenderer` (line ~105), a test that the swap path calls `promotion.reset` — monkeypatch `engine.rocks.promotion.reset` with a recorder and assert it ran with the renderer (Review Focus 4). Follow the existing test's way of driving `_drain_pending_swap`.

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement**

In `promotion.tick`: if `_view_set is not None and view_set is not _view_set` → `demote_all(r)`; set `_view_set = view_set`. If muted (`minor_contact._muted(player)`) and anything is promoted → `demote_all(r)` and return. These two checks run **before** the rate limit, so a dash start or set change demotes on the very next tick.

In `host_loop.py`, beside `_pump_scenery_contact`:

```python
def _pump_rock_promotion(player, session) -> None:
    """Rock promotion (rock-promotion spec §2): the nearest big field rocks
    become real RockClass objects. Sim side -- it adds and removes set
    objects -- beside the scenery contacts; a raise never breaks the frame."""
    try:
        import App
        from engine import renderer
        from engine.rocks import promotion
        from engine.systems import frames
        promotion.tick(player, frames.viewing_set(),
                       float(App.g_kUtopiaModule.GetGameTime()), renderer)
    except Exception as e:
        from engine import dev_mode
        dev_mode.log_swallowed("rock promotion pump", e)
```

and call it right after `_pump_scenery_contact(player, session=session)` inside a `with frame_profiler.scope("sim.rock_promotion"):` block. In the mission-swap block beside `_far_tier.reset(self.renderer)` add:

```python
        from engine.rocks import promotion as _promotion
        _promotion.reset(self.renderer)
```

placed **before** `_far_tier.reset` (so promoted objects leave their set while native still holds the exclusion; `far_clear` then wipes it).

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_rock_promotion.py tests/unit/test_far_host_wiring.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py engine/rocks/promotion.py tests/unit/test_rock_promotion.py tests/unit/test_far_host_wiring.py
git commit -m "feat(rock-promotion): sim-side pump, swap reset, demote all on set change and dash"
```

---

### Task 6: NPC avoidance of field rocks + scaled radii

**Files:**
- Modify: `engine/appc/collision_avoidance.py` (`_avoid_objects` ~387, `_test_course_override` ~485 and its loop end, `_build_obstacle_snapshot` ~827)
- Create: `engine/rocks/field_obstacles.py`
- Test: `tests/unit/test_field_obstacles.py`, `tests/integration/test_collision_avoidance.py` (append)

**Interfaces:**
- Consumes: `renderer.rockfield_query_large` (Task 2), `promotion.promoted()` (Task 4), `far_tier.frame_for`, `frames.viewing_set`, `collisions.world_radius`.
- Produces: `field_obstacles.near(pSet, centre_view: tuple, radius_gu: float, r=None) -> list[tuple[float, float, float, float]]` — `(x, y, z, radius)` in `pSet`'s coordinates for every large field rock (`min_radius` = the `near_large_r_min` dial) within `radius_gu` of `centre_view`, excluding promoted keys. `[]` when `pSet` is not the viewed set, the frame has no anchor, the field is disabled, or anything raises.

- [ ] **Step 1: Failing tests**

`tests/unit/test_field_obstacles.py`:

```python
from engine.rocks import field_obstacles, promotion


class R:
    def __init__(self, hits, enabled=True):
        self.hits, self.enabled, self.calls = hits, enabled, []
    def far_enabled(self):
        return self.enabled
    def rockfield_query_large(self, c, radius, min_r):
        self.calls.append((c, radius, min_r))
        return self.hits


def test_returns_view_space_spheres_minus_promoted(monkeypatch):
    vs = object()
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: vs)
    monkeypatch.setattr("engine.rocks.far_tier.frame_for", lambda s: ("Sys", (1000.0, 0.0, 0.0)))
    monkeypatch.setattr(promotion, "promoted", lambda: {9: object()})
    r = R([{"key": 1, "pos": (1100.0, 5.0, 0.0), "radius": 2.0},
           {"key": 9, "pos": (1050.0, 0.0, 0.0), "radius": 4.5}])
    out = field_obstacles.near(vs, (90.0, 0.0, 0.0), 150.0, r=r)
    assert out == [(100.0, 5.0, 0.0, 2.0)]
    assert r.calls[0][0] == (1090.0, 0.0, 0.0)          # system = anchor + view


def test_empty_when_not_the_viewed_set_or_disabled(monkeypatch):    # Review Focus 5
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: object())
    assert field_obstacles.near(object(), (0.0, 0.0, 0.0), 150.0, r=R([])) == []
    vs = object()
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: vs)
    monkeypatch.setattr("engine.rocks.far_tier.frame_for", lambda s: ("Sys", (0.0, 0.0, 0.0)))
    assert field_obstacles.near(vs, (0.0, 0.0, 0.0), 150.0, r=R([], enabled=False)) == []


def test_never_raises(monkeypatch):
    vs = object()
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: vs)
    monkeypatch.setattr("engine.rocks.far_tier.frame_for", lambda s: 1 / 0)
    assert field_obstacles.near(vs, (0.0, 0.0, 0.0), 150.0, r=R([])) == []
```

In `tests/integration/test_collision_avoidance.py`, following that file's existing pattern for "an AI ship on a collision course steers away" (read it first; reuse its ship/set builders and its way of calling `_test_course_override` / `tick_collision_avoidance`):

```python
def test_npc_steers_round_an_unpromoted_field_rock(monkeypatch):
    # An AI ship at the origin flying +Y at speed; a 4 GU field rock 40 GU ahead,
    # supplied through field_obstacles.near (monkeypatched), no set object there.
    ...
    monkeypatch.setattr("engine.rocks.field_obstacles.near",
                        lambda pSet, c, radius, r=None: [(0.0, 40.0, 0.0, 4.0)])
    heading, speed = collision_avoidance._test_course_override(ship)
    assert heading is not None          # an override: it avoids
    monkeypatch.setattr("engine.rocks.field_obstacles.near", lambda *a, **k: [])
    heading2, _ = collision_avoidance._test_course_override(ship)
    assert heading2 is None             # control: nothing to avoid without the rock


def test_scaled_obstacle_is_avoided_at_its_drawn_size():
    # A rock-sized obstacle with GetRadius() 1.0 and SetScale(8.0), placed so that
    # a 1 GU sphere would be missed but an 8 GU sphere is on the ship's path.
    ...
    heading, _ = collision_avoidance._test_course_override(ship)
    assert heading is not None
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement**

`engine/rocks/field_obstacles.py`:

```python
"""Large field rocks as avoidance obstacles (rock-promotion spec §4).

NPCs steer round every large near-band rock -- promoted or not -- through
the native camera-independent query. Only for the viewed set (the field's
anchor is known only there). Promoted rocks are set objects already, so
their keys are left out. Never raises.
"""
from __future__ import annotations


def near(pSet, centre_view, radius_gu, r=None) -> list:
    try:
        from engine.systems import frames
        if pSet is None or pSet is not frames.viewing_set():
            return []
        from engine.rocks import far_tier, far_dials, promotion
        system, anchor = far_tier.frame_for(pSet)
        if r is None:
            from engine import renderer as r
        if not r.far_enabled():
            return []
        c = tuple(a + p for a, p in zip(anchor, centre_view))
        skip = set(promotion.promoted())
        out = []
        for h in r.rockfield_query_large(c, float(radius_gu),
                                         float(far_dials.get("near_large_r_min"))):
            if h["key"] in skip:
                continue
            p = h["pos"]
            out.append((p[0] - anchor[0], p[1] - anchor[1], p[2] - anchor[2],
                        float(h["radius"])))
        return out
    except Exception as e:
        from engine import dev_mode
        dev_mode.log_swallowed("field obstacles", e)
        return []
```

(Tile fields are view-space spheres whose rocks are generated in system coordinates via the same anchor, so the same conversion holds. If `frame_for` returns `(None, (0,0,0))` — a one-set frame like Multi7 — the anchor is the origin and the conversion is still correct.)

`collision_avoidance.py`:
- `_avoid_objects`: `ship_r = world_radius(ship)` (import `from engine.appc.collisions import world_radius` at function top, as the file imports elsewhere).
- `_test_course_override`: `ship_r = world_radius(ship)`; after the snapshot loop and before `return _avoid_objects(...)`:

```python
    # Large rock-field rocks (rock-promotion spec §4): not set objects, so the
    # snapshot never sees them. Static spheres; the same gate as a set body.
    from engine.rocks import field_obstacles
    from engine.rocks import far_dials as _fd
    zero = TGPoint3(0.0, 0.0, 0.0)
    for fx, fy, fz, fr in field_obstacles.near(
            pSet, (px, py, pz), max(check_radius, float(_fd.get("avoid_query_radius_gu")))):
        if _need_to_avoid_xyz(slx, sly, slz, svx, svy, svz, personal_space,
                              fx, fy, fz, 0.0, 0.0, 0.0, fr):
            avoid_list.append((TGPoint3(fx, fy, fz), zero, fr))
```

- `_build_obstacle_snapshot`: `r = float(world_radius(other))` in place of `float(other.GetRadius())` (import alongside the existing `_collision_disabled_ids` import). Keep the `bound_radius` widening as is.

The query is made per avoiding ship per avoidance decision (4 Hz evading cadence). Wrap the field loop in `with frame_profiler.scope("avoid.field_query"):` if `collision_avoidance.py` already imports a profiler (grep `_prof\|frame_profiler` there); otherwise skip the scope.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_field_obstacles.py tests/integration/test_collision_avoidance.py tests/integration/test_e1m2_rocks.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add engine/rocks/field_obstacles.py engine/appc/collision_avoidance.py tests/unit/test_field_obstacles.py tests/integration/test_collision_avoidance.py
git commit -m "feat(rock-promotion): NPCs avoid large field rocks; avoidance uses drawn (scaled) radii"
```

---

### Task 7: End-to-end, docs, gate

**Files:**
- Create: `tests/host/test_rock_promotion_e2e.py`
- Modify: `CLAUDE.md` ("Rock class" or "Minor rocks"/rock-fields row: one clause; keep the row within its budget — `tests/docs/test_doc_consistency.py` or the row-budget test will say)
- Modify: `docs/superpowers/specs/2026-10-05-rock-promotion-design.md` (an "Amended during planning" section listing rulings R1–R3)
- Modify: `docs/engine/perf-cadences-and-latency.md` only if it lists sim scopes (add `sim.rock_promotion` at 4 Hz)

- [ ] **Step 1: Failing E2E test** (`tests/host/test_rock_promotion_e2e.py`, with `h = pytest.importorskip("_dauntless_host")`; real native field, real `promotion` module, real `SetClass`):

```python
def test_flying_through_a_full_density_field_promotes_targets_destroys_and_demotes():
    # 1. Push a full-density sphere source (view_space False, centre origin,
    #    radius 10,000) and the real near catalogue the way
    #    tests/host/test_rock_near_host.py does; push far dials.
    # 2. Build a viewed set + player at the origin (reuse the Task 4 fixture
    #    helpers -- import them from tests/unit/test_rock_promotion.py if they
    #    are module-level, else copy).
    # 3. promotion.tick(player, pset, t, engine.renderer) at t = 0:
    #    assert 1 <= len(promoted) <= 8, every promoted rock radius >= 4 GU,
    #    each matches h.rockfield_query_large's entry for its key (position,
    #    effective radius), and every promoted name is "Field Rock ...".
    # 4. Target one (player.SetTarget(name)); kill it through
    #    engine.rocks.death.begin(rock, killer=None) then death.advance(1.0);
    #    tick; assert its key is no longer promoted and h.rockfield_query_large
    #    still lists it while the promoted push contains it (stays excluded).
    # 5. Move the player 2,000 GU away; tick; assert promoted() == {} and the
    #    set holds no "Field Rock" objects. Move back; tick; assert the
    #    destroyed key is not re-promoted.
    ...
```

Write it fully, using the real helpers; it must run headless (no GL context: the near field and query are CPU-only).

- [ ] **Step 2: Run → fail if anything is unwired; fix within the owning module** (stay inside files of Tasks 1–6; report any fix).

- [ ] **Step 3: Docs.** Spec: append

```markdown
## Amended during planning (2026-10-05)

- **R1 — no speck-band exclusion.** Demotion is capped below the speck band's start
  (`near_large_billboard_gu - near_fade_gu - 1`, 400 GU by default) and a dash start
  demotes every promoted rock, so a promoted rock is never inside the speck band.
- **R2 — promoted rocks have no halo** (scenery large rocks have none).
- **R3 — death is detected by polling** (`rocks.death.is_dying_rock`, set membership)
  each promotion tick; there is no rock-died callback.
```

CLAUDE.md: in the rock-fields/minor-rocks row (whichever names `rock_near`), add: `Large rocks: 0 at a≤0.5 → full at 1 (large_ramp_*); the nearest 8 ≥4 GU within 300 GU are promoted to targetable RockClass "Field Rock XXXX" (engine/rocks/promotion.py, rockfield_set_promoted/query_large); NPCs avoid field rocks (field_obstacles).` Trim elsewhere in the row if the budget test fails.

- [ ] **Step 4: Gate.** `scripts/check_tests.sh` (sandbox disabled). Expected: exit 0, or exactly the controller's recorded baseline failures and nothing else. Fix anything new.

- [ ] **Step 5: Commit**

```bash
git add tests/host/test_rock_promotion_e2e.py CLAUDE.md docs/superpowers/specs/2026-10-05-rock-promotion-design.md
git commit -m "test(rock-promotion): headless end-to-end; docs and spec amendments"
```

(Add `docs/engine/perf-cadences-and-latency.md` to the list if it changed.)
