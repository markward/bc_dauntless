# Rock Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the far tier's tile-haze ball and uniform 405-minor tile clouds with one density field per source that drives four bands — streamed near rocks (small: mesh/billboard, large: mesh/billboard + collide-and-damage), baked mid "rock collection" sprites in nested tiles, and a quarter-resolution haze that starts at a distance.

**Architecture:** Native owns every band. A new `renderer::rockfield::NearField` streams 10 GU / 20 GU cells around the player in SYSTEM coordinates from the far tier's active `DiscSource`s (`density = a(x)·m(x)`), builds per-camera mesh bins (drawn by `MinorPass`) and impostor bins (drawn by `FarPass`), and runs the minors' exact swept contact against large rocks. A new `renderer::rockfield::MidField` picks one baked collection sprite per tile in three nested levels from the same density. `FarPass::render_haze` gains a start distance and renders at reduced resolution with the system nebula's depth-aware upsample. Python keeps owning inputs (`engine/rocks/far_tier.py`, `far_dials.py`) and applies large-rock collision responses sim-side (`engine/rocks/scenery_contact.py`).

**Tech Stack:** C++20 / GLSL 410 / GoogleTest (`renderer_tests`, `rockgen_tests`), Python 3 / pytest, the pybind host module `_dauntless_host`.

**Spec:** `docs/superpowers/specs/2026-10-02-rock-fields-design.md` (read it first). Background: `docs/superpowers/specs/2026-10-01-far-tier-design.md`, `docs/superpowers/specs/2026-10-01-minor-rocks-design.md`, BC evidence `/Users/mward/Documents/Projects/stbc_reference/spec/AsteroidField.md`.

## Global Constraints

- Work ONLY in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/rock-fields` on branch `feat/rock-fields`. Never commit to `main`; check `git branch --show-current` before every commit.
- **Banned git** (CLAUDE.md "Shared checkout"): `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs only. To mutate a file temporarily: `cp` to a backup, mutate, `cp` back, `diff` to prove identity.
- **Never launch the game** (`./build/dauntless`), never `pkill`, never interact with the desktop. Live checks are Mark's.
- Build only the one tree: `cmake -B build -S . && cmake --build build -j` from the worktree root. Never run cmake inside `native/`.
- GL tests (`renderer_tests` GL fixtures, `tests/host/*`) need the sandbox disabled (`dangerouslyDisableSandbox: true` on the Bash call).
- Every task ends with `scripts/check_tests.sh` exiting 0 before its commit (the gate builds C++, runs pytest + ctest + the in-process pass). Never call a failure "pre-existing" by eyeball.
- Units: GU everywhere (1 GU = 175 m). Never name a variable `*_m` / `*_mps`; speed is `*_gups`.
- Never capture a path at import; never spell `game`/`sdk` as a path segment (`tests/unit/test_path_indirection.py`).
- Native dial defaults MUST equal `engine/rocks/far_dials.py` `DEFAULTS` (one key, one default, both sides).
- `opaque.frag` discards must sit at the TOP of `main()` (a discard after `dFdx/dFdy` changed production output in far-tier).
- Look numbers are calibrated on the DISPLAYED value under production lighting (engine outputs linear, no sRGB encode; exposure 0.95), never on alpha.
- No game-state mutation in `render_payload` or in any render path: collision responses run sim-side from drained contacts.
- Determinism: everything generated is a pure function of (source seed, class/level, cell/tile index) in SYSTEM coordinates.
- Densities and ranges (spec R3, §2, §3; all dials):
  - small: `8` per `10³` GU³ at density 1, radius `0.05–0.5` GU power law exponent `2.5`, cell `10` GU, mesh `0–20` GU, billboard `20–30` GU
  - large: `1` per `20³` GU³, radius `1–5` GU exponent `2.5`, cell `20` GU, mesh `0–50` GU, billboard `50–60` GU
  - mid: L0 tile `150` GU (fade in `80–150` GU, out at `600`), L1 tile `600` GU (to `2,400`), L2 tile `2,400` GU to the haze hand-off `8,000` GU
- Python 1.5 is irrelevant here (no SDK-injected code), but SDK scripts must never see new behaviour except through existing surfaces.
- Subagents: tell every reviewer and implementer the banned-git list and the no-launch rule.

## Review Focus

1. **Mission swap / set change while inside a field** — a reasonable person expects no rock from the old system and no stale collision from before the swap. Pinned in Task 7 (`far_clear` drops near cells, contacts and the player sweep) and Task 8 (`scenery_contact.reset`).
2. **A rock generated on top of the ship** (mission start inside Beol 4, warp arrival, a dial edit raising density) — expected: no damage, no violent push. Pinned in Task 6 (`NearField` ghosts a large rock that overlaps the player when its cell streams in, until they separate).
3. **The viewscreen RTT camera, far from the player** — expected: it never streams or mutates the near field; it sees what is streamed plus mid and haze. Pinned in Task 5 (`build` is `const`; two cameras in one frame give identical stream state).
4. **A live dial edit mid-flight** (density, sizes, ranges, cell sizes) — expected: the field regenerates cleanly, no crash, no orphaned cooldowns. Pinned in Task 4 (`set_dials` with a generator change clears cells) and Task 6.
5. **A vast belt, full density, telephoto zoom** — expected: bounded frame cost. Pinned in Task 10 (mid sprite cap under a 1° fov) and Task 5 (near instance caps).

---

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `native/src/renderer/far_field.{h,cc}` (`include/renderer/far_field.h`) | sources, `field_density`, haze CPU twin, flagged-rock ladder, `make_impostor` helper; procedural belt generator REMOVED | 1, 2, 3, 12 |
| `native/src/renderer/shaders/far_haze.frag` | haze march: noise on every source, start distance | 1, 12 |
| `native/src/renderer/minor_field.{h,cc}` | extracted `sweep_obb_sphere` + `apply_shove` helpers | 3 |
| `native/src/renderer/minor_pass.{h,cc}`, `shaders/minor.vert` | fragment-table overload, per-instance dither | 3 |
| `native/src/renderer/rock_near.{h,cc}` (new) | `NearField`: streaming, per-camera build, contacts | 4, 5, 6 |
| `native/src/renderer/rock_mid.{h,cc}` (new) | `MidField`: nested tile levels, sprite choice | 10 |
| `native/src/renderer/far_pass.{h,cc}` | collection atlases, reduced-res haze + upsample | 11, 12 |
| `native/src/host/host_bindings.cc` | stepping, draws, bindings, profiler scopes | 7, 11, 12 |
| `native/src/rockgen/{include/rockgen/impostor.h,src/impostor.cc}` | multi-part impostor bake | 9 |
| `native/tools/rock_catalogue/{main.cc,writer.{h,cc}}` | `collections` output | 9 |
| `native/assets/rocks/{recipe.json,catalogue.json,collections/}` | committed bake | 9 |
| `engine/rocks/density.py` | sources (noise on belts; tile source without minors) | 1, 2 |
| `engine/rocks/minors.py`, `minor_dials.py` | tile clouds REMOVED | 2 |
| `engine/rocks/far_dials.py` | every rock-field dial; group "rock fields" | 1, 4, 6, 10, 12, 13 |
| `engine/rocks/far_tier.py` | pushes catalogue + collections, dials, sources, shield scale | 7, 8, 11 |
| `engine/rocks/catalogue.py` | `collections()` | 9 |
| `engine/rocks/scenery_contact.py` (new) | large-rock collision response | 8 |
| `engine/renderer.py` | wrappers for new bindings | 7, 8 |
| `engine/host_loop.py` | pump scenery contacts; dev mission list | 8, 13 |
| `engine/dev_missions/rock_fields_inside.py` (new) | "Rock Fields: inside Beol 4" | 13 |
| docs: `CLAUDE.md`, spec status, `docs/engine/frame-profiler.md` | records | 15 |

Build/test commands used throughout:

```bash
cmake --build build -j
ctest --test-dir build -R '<Regex>' --output-on-failure
./build/native/tests/renderer/renderer_tests --gtest_filter='<Suite>.<Test>'
uv run pytest tests/unit/<file>.py -q
scripts/check_tests.sh
```

(If the test binary sits elsewhere, find it with `find build -name renderer_tests -type f`; never create a second build tree.)

---

### Task 1: One density field — noise on every source, plus far-tier review follow-ups

Today only sphere (tile-field) sources carry the clumpy noise `m(x)`; belts are smooth. R1 needs `density(x) = a(x)·m(x)` for every source, because the near and mid bands will sample it.

**Files:**
- Modify: `native/src/renderer/include/renderer/far_field.h`, `native/src/renderer/far_field.cc` (`haze_noise_m`, `lattice`, `haze_value_noise`, `haze_fbm`, new `field_density`)
- Modify: `native/src/renderer/shaders/far_haze.frag` (`noise_m`, lattice hashing)
- Modify: `native/src/host/host_bindings.cc` (`disc_source_of`: clamp `noise_contrast`)
- Modify: `engine/rocks/density.py` (`profile_belt` gets noise; `to_native` always sends noise keys), `engine/rocks/far_dials.py` (belt noise dials, contrast clamp)
- Test: `native/tests/renderer/far_field_test.cc`, `native/tests/renderer/far_pass_test.cc`, `tests/unit/test_far_density.py`, `tests/unit/test_far_dials.py`

**Interfaces:**
- Produces (C++, `renderer::far`):
  - `float haze_noise_m(const DiscSource& s, const glm::dvec3& x_sys);` — now applies to BOTH shapes; still exactly `1.0f` when `noise_scale_gu <= 0`, `noise_contrast == 0` or `noise_octaves <= 0`.
  - `float field_density(const DiscSource& s, const glm::dvec3& x_sys);` — `density_a(s,x) * haze_noise_m(s,x)`. The ONE density every band samples.
  - `float noise_m_bound(const DiscSource& s);` — `1 + clamp(noise_contrast,0,1)` when noise is on, else `1`. Upper bound of `m` for rejection sampling.
- Produces (Python): `far_dials` keys `belt_noise_scale_gu` (default `4000.0`), `belt_noise_contrast` (`0.8`), `belt_noise_octaves` (`3`); `noise_contrast` values clamp to `[0, 1]` in `far_dials.step` for every `*_noise_contrast` key.

- [ ] **Step 1: Write the failing C++ tests** (append to `far_field_test.cc`)

```cpp
TEST(FarNoise, DiscSourcesNowCarryNoise) {
    far::DiscSource s;                       // a disc
    s.table = {{0.0f, 1.0f}, {50000.0f, 1.0f}};
    s.noise_scale_gu = 1000.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3; s.seed = 7;
    bool varied = false;
    for (int i = 0; i < 64; ++i) {
        const float m = far::haze_noise_m(s, glm::dvec3(i * 517.0, 300.0, 0.0));
        EXPECT_GE(m, 0.0f);
        EXPECT_LE(m, far::noise_m_bound(s));
        if (std::fabs(m - 1.0f) > 0.05f) varied = true;
    }
    EXPECT_TRUE(varied);
}

TEST(FarNoise, OffIsExactlyOneForBothShapes) {
    far::DiscSource d; d.noise_scale_gu = 0.0f; d.noise_contrast = 0.8f; d.noise_octaves = 3;
    far::DiscSource sph = d; sph.shape = far::DiscSource::Shape::Sphere;
    EXPECT_EQ(far::haze_noise_m(d, glm::dvec3(1, 2, 3)), 1.0f);
    EXPECT_EQ(far::haze_noise_m(sph, glm::dvec3(1, 2, 3)), 1.0f);
}

TEST(FarNoise, FieldDensityIsAtimesM) {
    far::DiscSource s; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = 1000.0f; s.noise_scale_gu = 250.0f; s.noise_contrast = 0.8f;
    s.noise_octaves = 3; s.seed = 11;
    const glm::dvec3 x(120.0, -40.0, 33.0);
    EXPECT_FLOAT_EQ(far::field_density(s, x), far::density_a(s, x) * far::haze_noise_m(s, x));
}

TEST(FarNoise, ContrastAboveOneIsClampedInTheBound) {
    far::DiscSource s; s.noise_scale_gu = 10.0f; s.noise_contrast = 3.0f; s.noise_octaves = 2;
    EXPECT_FLOAT_EQ(far::noise_m_bound(s), 2.0f);
}

// Golden values recorded BEFORE the per-octave hash refactor (run the current
// code once, paste the three numbers here, then refactor): identical values.
TEST(FarNoise, OncePerOctaveSeedHashKeepsValues) {
    const float a = far::haze_fbm(glm::vec3(0.3f, 1.7f, -2.2f), 3, 12345u);
    const float b = far::haze_fbm(glm::vec3(10.1f, -4.0f, 0.5f), 5, 99u);
    const float c = far::haze_value_noise(glm::vec3(-7.5f, 3.25f, 8.0f), 4242u);
    EXPECT_EQ(a, /*GOLDEN_A*/);
    EXPECT_EQ(b, /*GOLDEN_B*/);
    EXPECT_EQ(c, /*GOLDEN_C*/);
}
```

The golden placeholders are filled in Step 2 — this is the one place a value is captured from the running code, deliberately, to prove the refactor is value-identical.

- [ ] **Step 2: Capture goldens, run, verify the new tests fail**

Before touching `far_field.cc`, add a temporary `TEST(FarNoiseGolden, Print)` that prints the three values with `std::printf("%.9g\n", ...)`, build, run it, paste the printed literals (as `0x1.xxxxp-1f` hex-float or 9-digit decimals) into `OncePerOctaveSeedHashKeepsValues`, delete the print test.

Run: `cmake --build build -j && ./build/native/tests/renderer/renderer_tests --gtest_filter='FarNoise.*'`
Expected: FAIL — `field_density` / `noise_m_bound` undeclared (compile error), `DiscSourcesNowCarryNoise` fails.

- [ ] **Step 3: Implement**

In `far_field.cc`:
- `haze_noise_m`: drop the `s.shape != Sphere` test; use `std::clamp(s.noise_contrast, 0.0f, 1.0f)`.
- `field_density` and `noise_m_bound` as specified.
- Hash the seed once per octave: `lattice(x, y, z, hs)` takes the PRE-HASHED seed `hs = haze_hash(seed)` (it currently calls `haze_hash(seed)` inside every lattice call — 8 per noise sample). Add `float haze_value_noise_h(const glm::vec3& p, std::uint32_t hashed_seed)`; `haze_value_noise(p, seed)` becomes `haze_value_noise_h(p, haze_hash(seed))`; `haze_fbm` hashes `seed + o * 0x9E3779B9u` once per octave and calls `_h`. Values are bit-identical (same arithmetic).
- `haze_column`'s comment "m == 1 for belts" becomes "m == 1 when the noise is off".

In `far_haze.frag`: mirror exactly — `noise_m` no longer checks `u_shape`; contrast clamped to `[0,1]`; the per-octave seed hash hoisted out of `lattice`. Keep the twin comments accurate.

In `host_bindings.cc` `disc_source_of` (the `far_set_sources` dict parser): clamp `noise_contrast` to `[0,1]` on parse.

- [ ] **Step 4: Python — belts carry noise**

Test first (`tests/unit/test_far_density.py`):

```python
def test_profile_belt_carries_belt_noise_dials(monkeypatch):
    from engine.rocks import density, far_dials
    far_dials.reset()
    src = _vesuvi_belt()            # existing helper in this file; else build via profile_belt("Vesuvi")
    assert src.noise_scale_gu == far_dials.get("belt_noise_scale_gu")
    assert src.noise_contrast == far_dials.get("belt_noise_contrast")
    assert src.noise_octaves == far_dials.get("belt_noise_octaves")
    nat = density.to_native(src)
    assert nat["noise_scale_gu"] == src.noise_scale_gu   # now sent for discs too


def test_noise_contrast_dials_clamp_to_one():
    from engine.rocks import far_dials
    d = dict(far_dials.DEFAULTS, belt_noise_contrast=0.9)
    assert far_dials.step(d, "belt_noise_contrast", +1)["belt_noise_contrast"] == 1.0
    d = dict(far_dials.DEFAULTS, tile_haze_noise_contrast=0.9)
    assert far_dials.step(d, "tile_haze_noise_contrast", +1)["tile_haze_noise_contrast"] == 1.0
```

(If `_vesuvi_belt` does not exist in that file, look at how the existing tests build a belt source and reuse that.) Implement: add the three `belt_noise_*` dials (Python-owned, re-push sources), set them in `profile_belt`, drop the `if source.shape == "sphere"` guard in `to_native` so noise keys always travel, clamp in `step` for names ending `_noise_contrast`, add `belt_noise_octaves` to `_INT_FLOOR_1`.

- [ ] **Step 5: Shader twin test still pins the GLSL**

`far_pass_test.cc` already has `FarPassGLTest.NoisySphereHazeShaderMatchesTheCpuReference`. Add `FarPassGLTest.NoisyDiscHazeShaderMatchesTheCpuReference` — copy the sphere test's body, use a disc source with `table = {{0,1},{20000,1}}`, `noise_scale_gu = 4000`, `noise_contrast = 0.8`, `noise_octaves = 3`, and the same tolerance as the sphere test.

Run (sandbox disabled): `./build/native/tests/renderer/renderer_tests --gtest_filter='FarNoise.*:FarPassGLTest.*Haze*'` and `uv run pytest tests/unit/test_far_density.py tests/unit/test_far_dials.py -q`
Expected: PASS. The existing `FarHaze.DefaultBeltBrightness…` displayed-value tests may now shift because belts got noise; if a calibration test fails, re-derive the belt brightness the way its comment describes (displayed 25/255) and update `haze_brightness` in BOTH `far_dials.DEFAULTS` and the test, citing the new measured value in the comment.

- [ ] **Step 6: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/far_field.h native/src/renderer/far_field.cc native/src/renderer/shaders/far_haze.frag native/src/host/host_bindings.cc engine/rocks/density.py engine/rocks/far_dials.py native/tests/renderer/far_field_test.cc native/tests/renderer/far_pass_test.cc tests/unit/test_far_density.py tests/unit/test_far_dials.py
git commit -m "feat(rock-fields): one density field a*m on every source; clamp contrast; hash noise seed once per octave"
```

---

### Task 2: Remove the superseded far-tier parts (belt generator, tile minor clouds)

Spec §1 "Removed": the tile fields' 405-minor clouds and the procedural belt speck/impostor generator. Keep: sources, haze, flagged mission/breakup rock ladder (mesh → impostor → speck), halos, breakup debris minors, speck pass.

**Files:**
- Modify: `native/src/renderer/include/renderer/far_field.h`, `far_field.cc` — delete `GenParams`, `ClassBin`, `size_classes`, `FarRock`, `generate_cell`, the cell cache (`CachedCell`, `cache_`, `fetch`, `evict`, `frame_counter_` if unused), `FarField::build` steps 4–5, `FarOutput::generated/cells`, `cached_cells()`; `FarDials` loses `gen`, `max_far_rocks`, `cell_cache_max`, `max_cells_per_axis`
- Modify: `native/src/renderer/include/renderer/far_math.h`, `far_math.cc` — delete `Kind::ProceduralMajor/ProceduralMinor` and their branches
- Modify: `native/src/host/host_bindings.cc` — `far_set_dials` parser and `far_stats` (drop `generated`, `cells`, `cached_cells`)
- Modify: `engine/rocks/far_dials.py` — drop `k_ref`, `size_classes`, `cells_per_range`, `max_far_rocks`, `cell_cache_max`, `max_cells_per_axis` (DEFAULTS, NATIVE_KEYS, `_INT_FLOOR_1`)
- Modify: `engine/rocks/minors.py` — `desired_clouds` no longer emits `tile:` clouds; `tile_spec` deleted
- Modify: `engine/rocks/minor_dials.py` — drop `tile_count_mult`, `tile_orbit_rate` (keep `tile_r_min_gu`, `tile_r_per_size_factor`, `tile_size_exponent` ONLY if Step 3 still reads them; move them otherwise — see Step 3)
- Modify: `engine/rocks/density.py` — `tile_field_source` computes its population directly from the field (no `minors.tile_spec`)
- Delete or update tests: `native/tests/renderer/far_field_test.cc` (generator tests), `far_math_test.cc` (procedural kinds), `far_field_bench_test.cc` (the belt-generation bench — delete the file and its CMake line), `tests/unit/test_minor_registry.py` (tile cloud tests), `tests/unit/test_far_registry.py`, `tests/host/test_far_bindings.py`, `tests/host/test_minors_bindings.py` as they reference removed names

**Interfaces:**
- Produces: `FarOutput { impostors, specks, fades }` only. `far_stats()` keys: `sources`, `rocks`, `impostors`, `specks`, `draw_calls` (later tasks add `near_*`, `mid_*`).
- Produces (Python): `density.tile_field_source(field_obj, view_set, set_name, offset)` — unchanged signature and IDENTICAL output values (the haze calibration `tile_haze_gain = 14140` depends on them).

- [ ] **Step 1: Pin `tile_field_source` before refactoring it**

Add to `tests/unit/test_far_density.py`:

```python
class _Field:
    def __init__(self): pass
    def GetNumTilesPerAxis(self): return 3
    def GetNumAsteroidsPerTile(self): return 15
    def GetFieldRadius(self): return 1000.0
    def GetAsteroidSizeFactor(self): return 7.0
    def GetName(self): return "Asteroid Field 1"
    def GetWorldLocation(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(797.7, 977.2, 1268.9)


def test_tile_field_source_values_are_pinned(monkeypatch):
    from engine.rocks import density, far_dials, minor_dials
    far_dials.reset(); minor_dials.reset()
    monkeypatch.setattr("engine.systems.frames.containing_set", lambda o: None)
    s = density.tile_field_source(_Field(), None, "Beol4", (0.0, 0.0, 0.0))
    (pop,) = s.pops
    assert s.shape == "sphere" and s.procedural is False and s.view_space is True
    assert s.centre_gu == (797.7, 977.2, 1268.9)
    assert s.sphere_radius_gu == 1000.0
    assert pop.density_at_1 == pytest.approx(EXPECTED_DENSITY, rel=1e-12)
    assert (pop.r_min, pop.r_max, pop.exponent) == pytest.approx(EXPECTED_SIZES)
    assert s.seed == EXPECTED_SEED
```

Fill `EXPECTED_DENSITY`, `EXPECTED_SIZES`, `EXPECTED_SEED` by running the CURRENT code once (print them) before refactoring — this is a characterization test. (If `minor_dials.reset` does not exist, use whatever reset the module offers.) Run: PASS on the current code.

- [ ] **Step 2: Remove tile clouds (TDD)**

Change the existing tile-cloud tests in `tests/unit/test_minor_registry.py` into one assertion of the new contract:

```python
def test_asteroid_fields_get_no_minor_cloud():
    from engine.rocks import minors
    desired = minors.desired_clouds(view_set=None, rock_instances={}, fields=[_Field()])
    assert not any(k.startswith("tile:") for k in desired)
```

Run → FAIL. Then remove the tile branch from `desired_clouds`, delete `tile_spec`, and inline the numbers `tile_field_source` needs (count = `tiles**3 * per_tile * tile_count_mult`, `r_min`, `r_max`, `size_exponent`, `seed = crc32("tile:<set>:<name>")`, `point`, `family`) directly into `density.tile_field_source`. Keep reading the same `minor_dials` keys it reads today so Step 1's pinned values hold; delete only `tile_orbit_rate` (render-only for clouds). Run both tests → PASS.

- [ ] **Step 3: Remove the native belt generator**

Delete the generator code and its tests listed under **Files**. `FarField::build` keeps: output clear, flagged-rock loop (step 2), impostor bins. Keep `make_view_basis`, `gltf_to_bc`, haze, `set_sources/set_frame/refresh_active/active_sources/anchor` untouched. `set_sources` no longer needs `same_generators` (no cache): delete it.

Replace the deleted generator tests with:

```cpp
TEST(FarField, NoProceduralRocksFromABelt) {
    far::FarField f;
    far::DiscSource belt; belt.id = 1; belt.frame = "Vesuvi";
    belt.table = {{0.0f, 1.0f}, {50000.0f, 1.0f}};
    far::Population p; p.density_at_1 = 1e-3f; p.rocks = {0}; p.weights = {1.0f};
    belt.pops = {p};
    f.set_catalogue({far::CatalogueRock{glm::vec3(0.4f), true}}, {glm::vec3(0, 0, 1)});
    f.set_sources({belt});
    f.set_frame(std::string("Vesuvi"), glm::dvec3(0.0));
    far::BuildInput in;
    in.proj = glm::perspective(glm::radians(30.0f), 1.0f, 0.1f, 1e6f);
    far::FarOutput out;
    f.build(in, out);
    EXPECT_TRUE(out.impostors.empty());
    EXPECT_TRUE(out.specks.empty());
}
```

- [ ] **Step 4: Python dials and bindings**

Remove the generator dials from `far_dials.py`; update `tests/unit/test_far_dials.py` (any test that iterates `NATIVE_KEYS` or `DEFAULTS` must still pass — there is likely a test asserting Python defaults equal native defaults: keep it green). Update `far_stats` and its tests.

Run: `cmake --build build -j && ctest --test-dir build -R 'Far|Minor' --output-on-failure` and `uv run pytest tests/unit -q -k "far or minor or rock"`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add <every file changed or deleted above, explicitly, including the CMake list line for far_field_bench_test.cc>
git commit -m "refactor(rock-fields): drop the far-tier belt generator and tile minor clouds (superseded by rock fields)"
```

---

### Task 3: Shared helpers — swept contact, shove, impostor emit, minor dither

No behaviour change. Pulls the minors' exact swept test and shove response, and the far tier's impostor emit, into free functions the near band reuses; gives `MinorPass` a fragment-table overload and per-instance dither.

**Files:**
- Modify: `native/src/renderer/include/renderer/minor_field.h`, `native/src/renderer/minor_field.cc`
- Modify: `native/src/renderer/include/renderer/far_field.h`, `native/src/renderer/far_field.cc`
- Modify: `native/src/renderer/include/renderer/minor_pass.h`, `native/src/renderer/minor_pass.cc`, `native/src/renderer/shaders/minor.vert`
- Test: `native/tests/renderer/minor_field_test.cc`, `far_field_test.cc`, `minor_pass_test.cc`

**Interfaces:**
- Produces (`renderer::minors`, minor_field.h):

```cpp
// The player's oriented contact box in RENDER space for one step.
struct SweepBox {
    glm::vec3 axes[3];     // unit
    glm::vec3 half;        // GU, already inflated by any margin
    float bound = 0.0f;    // |half|
};
SweepBox sweep_box_of(const PlayerBox& box, float margin_gu, float inflate = 1.0f);
// Closest point on the box centred at `centre`.
glm::vec3 closest_on_box(const SweepBox& b, const glm::vec3& centre, const glm::vec3& p);
// Exact swept distance (golden-section; f is convex for a fixed orientation):
// the minimum over s in [0,1] of |p - closest_on_box(seg0 + seg*s)|; `s_out`
// gets the minimiser (ties prefer s = 1, the current pose).
float sweep_min_distance(const SweepBox& b, const glm::vec3& seg0, const glm::vec3& seg,
                         const glm::vec3& p, float& s_out);
```

  `MinorField::step_contact` is rewritten on top of these; `inflate` scales `half` before the margin is added (used by Task 6 for the shield bubble).
- Produces: `struct ShoveState { glm::vec3 offset{0}, vel{0}; float spin = 0, spin_rate = 0; double last_contact = -1e9; };` and `void apply_shove(ShoveState&, const glm::vec3& push_dir, float rel_speed, double now, const Dials&);` plus `void advance_shove(ShoveState&, float dt, const Dials&);` — exactly MinorField's current shove arithmetic (`MinorField::Shove` becomes an alias of `ShoveState`).
- Produces (`renderer::far`, far_field.h):

```cpp
// The impostor instance for a rock at render-space centre c, rotation R
// (rock -> render), radius r, seen from `eye`, with signed dither `dither`
// (0 = solid; >0 a mesh-side fade keeping the upper 1-d; <0 an impostor
// fading in keeping the lower |d|). Chooses the baked view nearest the eye.
ImpostorGpu make_impostor(const std::vector<glm::vec3>& view_dirs_gltf, const glm::vec3& eye,
                          const glm::vec3& c, const glm::mat3& R, float r, float dither);
```

  `FarField::build`'s `emit_impostor` lambda calls it with `dither = -w`.
- Produces (`renderer`, minor_pass.h):

```cpp
using FragmentLookup = std::function<const minors::Fragment*(int family, int slot)>;
void render(const FragmentLookup& fragments, const std::vector<minors::Bin>& bins,
            const scenegraph::Camera& cam, Pipeline& pipeline,
            const std::function<const assets::Model*(std::uint64_t)>& lookup,
            const Lighting& lighting, float ambient_scale, float rim_strength);
```

  The two existing overloads forward to it. `minors::InstanceGpu` grows a 4th `glm::vec4 extra` (x = signed dither, yzw 0) → 64 bytes; `minor.vert` reads it at location 10 and writes `v_dither = a_extra.x`. Every existing producer writes `extra = vec4(0)` so output is byte-identical.

- [ ] **Step 1: Characterize before extracting**

Run the existing suites and record they pass: `./build/native/tests/renderer/renderer_tests --gtest_filter='MinorField*:MinorPass*:FarField*:FarPass*:FarDither*'` (sandbox disabled). They are the regression net for this task.

- [ ] **Step 2: Write the new unit tests (failing: names undeclared)**

```cpp
TEST(MinorSweep, FindsAHitMidSegmentAtDashSpeed) {
    minors::PlayerBox pb;                       // unit cube hull at origin
    pb.half_mu = glm::vec3(1.0f);
    const auto b = minors::sweep_box_of(pb, 0.0f);
    // 1,000 GU in one step straight through a 2 GU rock 500 GU along +Y.
    float s = -1.0f;
    const float d = minors::sweep_min_distance(b, glm::vec3(0, -500, 0), glm::vec3(0, 1000, 0),
                                               glm::vec3(0, 0, 0), s);
    EXPECT_NEAR(d, 0.0f, 1e-3f);
    EXPECT_NEAR(s, 0.5f, 2e-3f);
}

TEST(MinorSweep, InflateScalesHalfBeforeMargin) {
    minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f, 2.0f, 3.0f);
    const auto b = minors::sweep_box_of(pb, 0.1f, 2.0f);
    EXPECT_FLOAT_EQ(b.half.x, 2.1f);
    EXPECT_FLOAT_EQ(b.half.z, 6.1f);
}

TEST(FarImpostor, MakeImpostorDitherAndSize) {
    const std::vector<glm::vec3> dirs = {glm::vec3(0, 0, 1), glm::vec3(0, 0, -1)};
    const auto g = far::make_impostor(dirs, glm::vec3(0, 0, 10), glm::vec3(0), glm::mat3(1.0f),
                                      2.0f, -0.25f);
    EXPECT_FLOAT_EQ(g.centre_half.w, 2.0f * 1.02f);
    EXPECT_FLOAT_EQ(g.up_dither.w, -0.25f);
}
```

Plus in `minor_pass_test.cc` a GL test `MinorPassGLTest.InstanceDitherDiscardsAboutHalf`: draw one fragment instance filling the view with `extra.x = 0.5f`, count lit pixels, expect 40–60% of the solid draw's count; and `MinorPassGLTest.ZeroDitherIsByteIdentical`: compare the framebuffer of a draw with `extra = 0` against the pre-change reference image produced by the existing test helper (or compare against the same draw through the old overload).

- [ ] **Step 3: Extract and implement**

Move the arithmetic out of `MinorField::step_contact` (lines ~293–420 today: OBB set-up, `closest_on_box`, golden-section sweep, shove) into the free functions; `step_contact` calls them. Move `emit_impostor`'s body into `make_impostor`. Add `FragmentLookup` overload; the old overloads build a lookup over `field.fragments(family)`. Add `extra` to `InstanceGpu`, the VAO attribute at location 10 (`glVertexAttribDivisor(10, 1)`), and the shader input.

- [ ] **Step 4: Run** — new tests + Step 1's suites all PASS (sandbox disabled).

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/minor_field.h native/src/renderer/minor_field.cc native/src/renderer/include/renderer/far_field.h native/src/renderer/far_field.cc native/src/renderer/include/renderer/minor_pass.h native/src/renderer/minor_pass.cc native/src/renderer/shaders/minor.vert native/tests/renderer/minor_field_test.cc native/tests/renderer/far_field_test.cc native/tests/renderer/minor_pass_test.cc
git commit -m "refactor(rocks): extract swept contact, shove and impostor emit; MinorPass fragment lookup + per-instance dither"
```

---

### Task 4: NearField — deterministic cells and streaming

**Files:**
- Create: `native/src/renderer/include/renderer/rock_near.h`, `native/src/renderer/rock_near.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `rock_near.cc`), `native/tests/renderer/CMakeLists.txt` (add `rock_near_test.cc`)
- Create: `native/tests/renderer/rock_near_test.cc`
- Modify: `engine/rocks/far_dials.py` (near dials, NATIVE)

**Interfaces:**
- Consumes: `far::DiscSource`, `far::field_density`, `far::noise_m_bound`, `far::density_a` (Task 1); `renderer::rockrand::Rng`, `rockrand::power_law`, `rockrand::unit_vector` (`renderer/rock_random.h`).
- Produces (`renderer::rockfield`, rock_near.h):

```cpp
enum class NearClass : std::uint8_t { Small = 0, Large = 1 };

struct NearClassDials {
    float density = 0.008f;     // rocks / GU^3 where field_density == 1
    float r_min = 0.05f, r_max = 0.5f, exponent = 2.5f;
    float cell_gu = 10.0f;
    float mesh_gu = 20.0f;      // mesh out to here (camera distance)
    float billboard_gu = 30.0f; // billboard out to here; streamed radius
    int max_instances = 4000;   // per camera build
};

struct NearDials {   // defaults MUST equal far_dials.py DEFAULTS near_* keys
    NearClassDials small{};
    NearClassDials large{1.0f / 8000.0f, 1.0f, 5.0f, 2.5f, 20.0f, 50.0f, 60.0f, 1000};
    float fade_gu = 4.0f;                 // dither band width at each tier edge
    float stream_margin_gu = 10.0f;       // keep cells this far past range (hysteresis)
    float collide_cooldown_s = 0.5f;      // per large rock
    float collide_margin_gu = 0.0f;
};

struct NearRock {
    glm::dvec3 pos_sys{0.0};
    float radius = 0.0f;
    int rock = 0;                    // catalogue index (fragment for Small, major for Large)
    glm::vec3 tumble_axis{0, 0, 1};
    float tumble_rate = 0.0f, phase = 0.0f;
};

struct NearCatalogue {               // pushed with far_set_catalogue
    std::vector<int> small_rocks;    // catalogue indices of silicate-family fragments
    std::vector<int> large_rocks;    // catalogue indices of silicate-family majors
};

// Pure: the rocks of one cell. Poisson(n_bound * L^3) candidates, each
// accepted with probability density * field_density(x) / n_bound, where
// n_bound = density * a_bound(cell) * noise_m_bound(s). Fixed draw order per
// candidate: position (3), accept, size, rock, tumble axis (2), rate, phase.
std::vector<NearRock> generate_near_cell(const far::DiscSource& s, NearClass cls,
                                         const glm::i64vec3& ijk, const NearDials& d,
                                         const NearCatalogue& cat);

struct NearStats { int cells = 0; int small = 0; int large = 0; int ghosted = 0; };

class NearField {
public:
    void set_dials(const NearDials&);      // a generator change clears every cell
    const NearDials& dials() const { return dials_; }
    void set_catalogue(NearCatalogue);     // clears every cell
    // The far tier's active sources (FarField::active_sources(), system coords).
    void set_sources(const std::vector<far::DiscSource>& active);  // clears on change
    // Generate cells newly in range of `centre_sys`, drop cells out of range +
    // stream_margin_gu. Range per class = billboard_gu.
    void stream(const glm::dvec3& centre_sys);
    void clear();                          // cells, contacts, sweep state, cooldowns, ghosts
    NearStats stats() const;
    // Every rock currently streamed, per class (tests, build, contacts).
    void for_each(NearClass cls, const std::function<void(std::uint64_t key, const NearRock&)>& fn) const;
private:
    struct Cell { NearClass cls; std::vector<NearRock> rocks; };
    // key: mix(source id, class, i, j, k) as far_field.cc's cell_key; rock key = cell key ^ (index+1) hashed
    std::unordered_map<std::uint64_t, Cell> cells_;
    // ...
};
}
```

  A sphere source generates too (unlike the old belt generator): `a_bound` for a sphere cell is `1` if the cell's bounding sphere reaches inside `sphere_radius_gu`, else `0`; for a disc reuse far_field.cc's `a_bound` logic (move it into a header-visible `float a_bound(const DiscSource&, const glm::dvec3& centre, double half)` in far_field.h). Rocks inside a source's `explicit_regions` are rejected (same as before).
- Produces (Python): `far_dials` NATIVE keys `near_small_density` 0.008, `near_small_r_min` 0.05, `near_small_r_max` 0.5, `near_small_exponent` 2.5, `near_small_cell_gu` 10.0, `near_small_mesh_gu` 20.0, `near_small_billboard_gu` 30.0, `near_small_max` 4000, `near_large_density` 1.25e-4, `near_large_r_min` 1.0, `near_large_r_max` 5.0, `near_large_exponent` 2.5, `near_large_cell_gu` 20.0, `near_large_mesh_gu` 50.0, `near_large_billboard_gu` 60.0, `near_large_max` 1000, `near_fade_gu` 4.0, `near_stream_margin_gu` 10.0, `collide_cooldown_s` 0.5. (Task 7 parses them natively.)

- [ ] **Step 1: Write the failing tests** (`rock_near_test.cc`)

```cpp
#include <gtest/gtest.h>
#include <renderer/rock_near.h>
using namespace renderer;
namespace {
far::DiscSource full_sphere() {          // density 1 everywhere within 10,000 GU, no noise
    far::DiscSource s; s.id = 3; s.seed = 99; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = 10000.0f; s.sphere_edge_frac = 0.0f; s.view_space = true;
    return s;
}
rockfield::NearCatalogue cat() { return {{1, 2, 3}, {10, 11}}; }
}

TEST(NearCells, DeterministicPerCell) {
    rockfield::NearDials d;
    const auto a = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Small, {4, -2, 7}, d, cat());
    const auto b = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Small, {4, -2, 7}, d, cat());
    ASSERT_EQ(a.size(), b.size());
    for (size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].pos_sys, b[i].pos_sys);
        EXPECT_EQ(a[i].radius, b[i].radius);
        EXPECT_EQ(a[i].rock, b[i].rock);
    }
}

TEST(NearCells, MeanCountMatchesDensityAtFullField) {
    rockfield::NearDials d;
    double n = 0; const int cells = 400;
    for (int i = 0; i < cells; ++i)
        n += rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Small, {i, 0, 0}, d, cat()).size();
    const double expected = d.small.density * std::pow(d.small.cell_gu, 3.0);   // 8 per cell
    EXPECT_NEAR(n / cells, expected, 0.6);
}

TEST(NearCells, DensityFollowsField) {     // a 0.05 belt floor gets ~5%
    far::DiscSource belt; belt.id = 5; belt.seed = 1; belt.table = {{0.0f, 0.05f}, {1e6f, 0.05f}};
    belt.scale_height_min_gu = 1e6f;        // flat in z near the plane
    rockfield::NearDials d;
    double n = 0; const int cells = 2000;
    for (int i = 0; i < cells; ++i)
        n += rockfield::generate_near_cell(belt, rockfield::NearClass::Small, {i, 3, 0}, d, cat()).size();
    EXPECT_NEAR(n / cells, 0.05 * 8.0, 0.08);
}

TEST(NearCells, SizesInRangeAndRocksFromTheClassList) {
    rockfield::NearDials d;
    for (int i = 0; i < 50; ++i)
        for (const auto& r : rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, {i, 1, 1}, d, cat())) {
            EXPECT_GE(r.radius, d.large.r_min); EXPECT_LE(r.radius, d.large.r_max);
            EXPECT_TRUE(r.rock == 10 || r.rock == 11);
        }
}

TEST(NearStream, BoundedAndDropsCellsBehind) {
    rockfield::NearField f;
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const int first = f.stats().cells;
    EXPECT_GT(first, 0); EXPECT_LT(first, 1200);       // "a few hundred cells"
    f.stream(glm::dvec3(5000.0, 0.0, 0.0));            // jump far away
    EXPECT_LE(f.stats().cells, first + 10);            // old cells gone, not accumulated
    int near_origin = 0;
    f.for_each(rockfield::NearClass::Small, [&](std::uint64_t, const rockfield::NearRock& r) {
        if (glm::length(r.pos_sys) < 100.0) ++near_origin; });
    EXPECT_EQ(near_origin, 0);
}

TEST(NearStream, SameStateRegardlessOfPath) {   // returning to a place gives the same rocks
    rockfield::NearField a, b;
    for (auto* f : {&a, &b}) { f->set_catalogue(cat()); f->set_sources({full_sphere()}); }
    a.stream(glm::dvec3(0.0));
    b.stream(glm::dvec3(900.0, 0, 0)); b.stream(glm::dvec3(0.0));
    std::set<std::uint64_t> ka, kb;
    a.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock&) { ka.insert(k); });
    b.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock&) { kb.insert(k); });
    // b may still hold margin cells; every rock in range of the origin must match
    EXPECT_TRUE(std::includes(kb.begin(), kb.end(), ka.begin(), ka.end()));
}

TEST(NearStream, DialChangeClearsCells) {      // Review Focus 4
    rockfield::NearField f;
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearDials d; d.small.density *= 2.0f;
    f.set_dials(d);
    EXPECT_EQ(f.stats().cells, 0);
    f.stream(glm::dvec3(0.0));
    EXPECT_GT(f.stats().small, 0);
}

TEST(NearStream, NoSourcesNoRocks) {
    rockfield::NearField f; f.set_catalogue(cat());
    f.stream(glm::dvec3(0.0));
    EXPECT_EQ(f.stats().small + f.stats().large, 0);
}
```

- [ ] **Step 2: Run** — `cmake --build build -j` fails to compile (header missing). Expected.

- [ ] **Step 3: Implement** `rock_near.{h,cc}` per the interface. Streaming enumerates, per source and class, cells whose AABB is within `billboard_gu` of `centre_sys` (sphere-vs-AABB test like far_field's old `(a)` filter) and skips sources whose bounds cannot reach (sphere: `|centre - c| > R + range`; disc: `a_bound == 0`). Drop cells whose AABB distance exceeds `billboard_gu + stream_margin_gu`. Add the Python dials (Python-side only; native parse arrives in Task 7) and a `tests/unit/test_far_dials.py` case asserting each `near_*` default equals the C++ default listed in this task (hard-code the numbers in the test with a comment pointing at `rock_near.h`).

- [ ] **Step 4: Run** `./build/native/tests/renderer/renderer_tests --gtest_filter='Near*'` and `uv run pytest tests/unit/test_far_dials.py -q` → PASS.

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/rock_near.h native/src/renderer/rock_near.cc native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt native/tests/renderer/rock_near_test.cc native/src/renderer/include/renderer/far_field.h native/src/renderer/far_field.cc engine/rocks/far_dials.py tests/unit/test_far_dials.py
git commit -m "feat(rock-fields): NearField deterministic cells streamed around a centre"
```

---

### Task 5: NearField per-camera build — one tier per rock, dither fades

**Files:**
- Modify: `native/src/renderer/include/renderer/rock_near.h`, `native/src/renderer/rock_near.cc`
- Test: `native/tests/renderer/rock_near_test.cc`

**Interfaces:**
- Consumes: `minors::Bin`, `minors::InstanceGpu` (with `extra`, Task 3), `far::ImpostorBin`, `far::make_impostor` (Task 3), `far::gltf_to_bc`.
- Produces:

```cpp
// Family codes in NearOutput::meshes bins, resolved by the host's FragmentLookup:
constexpr int kNearSmallFamily = 1000;   // slot = index into NearCatalogue::small_rocks
constexpr int kNearLargeFamily = 1001;   // slot = index into NearCatalogue::large_rocks

struct NearBuildInput {
    glm::mat4 view{1}, proj{1};
    float viewport_h = 720.0f;
    glm::dvec3 render_origin{0.0};   // view space of render space's origin
    glm::dvec3 anchor_sys{0.0};      // system position of view space's origin (FarField::anchor())
    double game_time = 0.0;
    float lod0_pixel_radius = 24.0f; // minors' dial: lod0 above, lod1 below
};
struct NearOutput {
    std::vector<minors::Bin> meshes;          // family kNearSmallFamily/kNearLargeFamily
    std::vector<far::ImpostorBin> billboards; // .rock = catalogue index
    int mesh_count = 0, billboard_count = 0;
};
struct NearWeights { float mesh = 0, billboard = 0; };
// Pure tier rule for camera distance d (spec §2): mesh 1 below mesh_gu - fade,
// ramps to 0 at mesh_gu; billboard = 1 - mesh up to billboard_gu - fade, then
// ramps to 0 at billboard_gu; nothing beyond.
NearWeights near_weights(float d, const NearClassDials& c, float fade_gu);

// In NearField:
void build(const NearBuildInput& in, NearOutput& out) const;   // const: never streams
```

  Mesh dither: a mesh at weight w < 1 gets `extra.x = 1 - w` (positive: mesh fading out keeps upper w); a billboard at weight w gets `dither = -w` via `make_impostor`. Weight 1 ⇒ dither exactly 0. Pose: rotation `R = rotate(phase + tumble_rate * game_time, tumble_axis)`; mesh model matrix rows `[R * s | t]` where `s = radius / bound_radius_mu` is applied by the host's fragment table? — NO: the bin item must carry the full scale, so `NearCatalogue` gains `std::vector<float> small_bound_mu, large_bound_mu` (parallel to the index lists; model-unit bound radius at load scale 1) and the item scale is `radius / bound_mu`. Frustum-cull each rock's sphere. LOD: `lod = (radius * k / d >= lod0_pixel_radius) ? 0 : 1` with `k = far::pixels_per_gu(proj, viewport_h)`. Cap: stop adding a class's instances at `max_instances` (nearest-first: sort candidates by distance before emitting).

- [ ] **Step 1: Write the failing tests**

```cpp
TEST(NearTiers, WeightsAtTheBoundaries) {
    rockfield::NearClassDials c;  // small: 20 / 30, fade 4
    auto w = [&](float d) { return rockfield::near_weights(d, c, 4.0f); };
    EXPECT_EQ(w(10).mesh, 1.0f);  EXPECT_EQ(w(10).billboard, 0.0f);
    EXPECT_NEAR(w(18).mesh + w(18).billboard, 1.0f, 1e-6f);   // inside the mesh->billboard fade
    EXPECT_EQ(w(20).mesh, 0.0f);  EXPECT_EQ(w(20).billboard, 1.0f);
    EXPECT_EQ(w(25).billboard, 1.0f);
    EXPECT_NEAR(w(28).billboard, 0.5f, 1e-5f);                // dithering in at the outer edge
    EXPECT_EQ(w(30).mesh + w(30).billboard, 0.0f);
    EXPECT_EQ(w(31).mesh + w(31).billboard, 0.0f);
}

TEST(NearBuild, OneTierPerRockOutsideFades) {
    rockfield::NearField f;
    rockfield::NearCatalogue k = cat(); k.small_bound_mu = {57.0f, 57.0f, 57.0f}; k.large_bound_mu = {57.0f, 57.0f};
    f.set_catalogue(k); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearBuildInput in;
    in.proj = glm::perspective(glm::radians(90.0f), 1.0f, 0.01f, 1e5f);
    in.view = glm::lookAt(glm::vec3(0), glm::vec3(0, 1, 0), glm::vec3(0, 0, 1));
    rockfield::NearOutput out;
    f.build(in, out);
    EXPECT_GT(out.mesh_count, 0);
    EXPECT_GT(out.billboard_count, 0);
    // every emitted mesh is within mesh_gu of the eye, every billboard beyond mesh_gu - fade
    for (const auto& b : out.meshes)
        for (const auto& it : b.items) {
            const float d = glm::length(glm::vec3(it.row0.w, it.row1.w, it.row2.w));
            const float lim = b.family == rockfield::kNearSmallFamily ? 20.0f : 50.0f;
            EXPECT_LE(d, lim + 1e-3f);
            if (d < lim - 4.0f) EXPECT_EQ(it.extra.x, 0.0f);       // solid: byte-identical path
        }
    for (const auto& b : out.billboards)
        for (const auto& it : b.items) {
            const float d = glm::length(glm::vec3(it.centre_half));
            EXPECT_GE(d, 16.0f - 1e-3f);       // >= small mesh_gu - fade
            EXPECT_LE(d, 60.0f + 1e-3f);
            EXPECT_LT(it.up_dither.w, 0.0f + 1e-9f);
        }
}

TEST(NearBuild, BuildIsConstAcrossCameras) {   // Review Focus 3
    rockfield::NearField f;
    rockfield::NearCatalogue k = cat(); k.small_bound_mu = {57, 57, 57}; k.large_bound_mu = {57, 57};
    f.set_catalogue(k); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const auto before = f.stats();
    rockfield::NearBuildInput far_cam;
    far_cam.proj = glm::perspective(glm::radians(10.0f), 1.0f, 0.01f, 1e6f);
    far_cam.view = glm::lookAt(glm::vec3(5000, 0, 0), glm::vec3(5000, 1, 0), glm::vec3(0, 0, 1));
    rockfield::NearOutput out;
    f.build(far_cam, out);
    EXPECT_EQ(out.mesh_count + out.billboard_count, 0);    // nothing streamed out there
    EXPECT_EQ(f.stats().cells, before.cells);
}

TEST(NearBuild, InstanceCapHolds) {             // Review Focus 5
    rockfield::NearDials d; d.small.max_instances = 50;
    rockfield::NearField f; f.set_dials(d);
    rockfield::NearCatalogue k = cat(); k.small_bound_mu = {57, 57, 57}; k.large_bound_mu = {57, 57};
    f.set_catalogue(k); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearBuildInput in;
    in.proj = glm::perspective(glm::radians(170.0f), 1.0f, 0.01f, 1e5f);
    rockfield::NearOutput out; f.build(in, out);
    int small = 0;
    for (const auto& b : out.meshes) if (b.family == rockfield::kNearSmallFamily) small += (int)b.items.size();
    for (const auto& b : out.billboards) small += 0;   // billboards counted with their class below
    EXPECT_LE(small, 50);
}
```

(Adapt the cap test to count small billboards too: the cap is per class over meshes + billboards; keep a per-class counter in `build` and expose nothing new — count by checking `b.rock` against `cat().small_rocks`.)

- [ ] **Step 2: Run** → FAIL (undeclared). **Step 3: Implement.** **Step 4: Run** `--gtest_filter='Near*'` → PASS.

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/rock_near.h native/src/renderer/rock_near.cc native/tests/renderer/rock_near_test.cc
git commit -m "feat(rock-fields): NearField per-camera build -- mesh/billboard tiers with dither fades"
```

---

### Task 6: NearField contacts — large rocks collide, small rocks shove

**Files:**
- Modify: `native/src/renderer/include/renderer/rock_near.h`, `native/src/renderer/rock_near.cc`
- Test: `native/tests/renderer/rock_near_test.cc`

**Interfaces:**
- Consumes: `minors::PlayerBox`, `minors::sweep_box_of`, `minors::closest_on_box`, `minors::sweep_min_distance`, `minors::ShoveState`, `minors::apply_shove`, `minors::advance_shove`, `minors::Dials`, `minors::Contact` (Task 3).
- Produces:

```cpp
// One large-rock touch (spec §2 "Collisions"), drained by Python
// (engine/rocks/scenery_contact.py). VIEW space; normal points rock -> ship.
struct NearContact {
    glm::dvec3 point_view{0.0};        // closest point on the ship's contact shape at first touch
    glm::vec3 normal{0, 0, 1};
    glm::dvec3 rock_centre_view{0.0};
    float rock_radius = 0.0f;
    float rel_speed = 0.0f;            // GU/s, the ship's sweep speed this step
    float pen = 0.0f;                  // rock_radius - distance(centre, shape) at the CURRENT pose, >= 0
};

struct NearStepInput {
    double game_time = 0.0;
    glm::dvec3 render_origin{0.0};
    glm::dvec3 anchor_sys{0.0};
    std::optional<minors::PlayerBox> player;   // unset: no contacts, sweep state reset
    float shield_inflate = 0.0f;               // > 0: the box half extents x this (shields up)
    minors::Dials minor_dials;                 // shove + contact margin + teleport guard
};

// In NearField:
void step(const NearStepInput& in);   // advances shoves, runs contacts
std::vector<NearContact> drain_large_contacts();
std::vector<minors::Contact> drain_small_contacts();   // same shape as MinorField's
void reset_player();                  // forget the previous pose
```

  Rules:
  - Large rocks: solid, fixed, player only. For each large rock within `bound + radius` of the swept segment: `d = sweep_min_distance(box, seg0, seg, p, s)`; touch when `d <= radius + collide_margin_gu`. Per-rock cooldown `collide_cooldown_s` (keyed by rock key; cooldowns for rocks no longer streamed are dropped).
  - **Ghosting (Review Focus 2):** a large rock whose cell streams in while the player's CURRENT box already overlaps it is ghosted (no contacts) until a step finds the box clear of it; `stats().ghosted` counts them. Also on the first step after `reset_player()` (no previous pose), any rock overlapping the box is ghosted.
  - Small rocks: the minors' shove — `apply_shove` on touch, `advance_shove` every step, contact appended as `minors::Contact{point_view, radius, rel_speed}`; shove offsets apply to the rock's drawn position in `build` (keep a `std::unordered_map<std::uint64_t, minors::ShoveState>` and drop entries whose rock left the stream).
  - Teleport guard: travel > `minor_dials.teleport_gu` ⇒ current pose only (as minors).
  - Shield inflate: `sweep_box_of(box, margin, shield_inflate > 0 ? shield_inflate : 1)`.
  - Contacts are capped at `minor_dials.max_shoves_per_frame` per class per step.

- [ ] **Step 1: Write the failing tests**

```cpp
namespace {
// A field with exactly one large rock of radius 2 at system (0, 100, 0):
// build the NearField, stream, then find that rock via for_each, or construct
// the test with a test-only injector:
}
// Add a TEST-ONLY hook to NearField:
//   void debug_add_rock(NearClass cls, std::uint64_t key, const NearRock& r);
// which inserts into a dedicated test cell (never streamed out unless clear()).

TEST(NearContact, SweptHitAtDashSpeed) {
    rockfield::NearField f;
    rockfield::NearRock r; r.pos_sys = {0, 500, 0}; r.radius = 2.0f;
    f.debug_add_rock(rockfield::NearClass::Large, 42, r);
    minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f);
    rockfield::NearStepInput in; in.player = pb;
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 0, 0));
    in.game_time = 1.0; f.step(in);
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 1000, 0));   // 1,000 GU in one step
    in.game_time = 1.0 + 1.0 / 60.0; f.step(in);
    const auto c = f.drain_large_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_NEAR(c[0].rock_radius, 2.0f, 1e-6f);
    EXPECT_NEAR(c[0].rel_speed, 60000.0f, 10.0f);
}

TEST(NearContact, CooldownSuppressesRepeats) {
    // touch, then step again 0.1 s later still touching: no second contact;
    // 0.6 s later: a second contact.
}

TEST(NearContact, OverlapOnStreamInIsGhosted) {          // Review Focus 2
    rockfield::NearField f;
    minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f);
    rockfield::NearStepInput in; in.player = pb; in.game_time = 1.0;
    rockfield::NearRock r; r.pos_sys = {0, 0.5, 0}; r.radius = 2.0f;   // inside the ship
    f.debug_add_rock(rockfield::NearClass::Large, 7, r);
    f.step(in);
    EXPECT_TRUE(f.drain_large_contacts().empty());
    EXPECT_EQ(f.stats().ghosted, 1);
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, -20, 0)); in.game_time = 2.0; f.step(in);  // separate
    EXPECT_EQ(f.stats().ghosted, 0);
    in.player->world = glm::mat4(1); in.game_time = 3.0; f.step(in);   // come back: now it hits
    EXPECT_EQ(f.drain_large_contacts().size(), 1u);
}

TEST(NearContact, ShieldInflateTouchesEarlier) {
    // rock radius 1 at distance 2.5 from a unit-half box: no contact at inflate 0,
    // a contact at inflate sqrt(3).
}

TEST(NearContact, NoPlayerNoContactsAndSweepResets) {
    // step with player unset after a pose: no contacts; the next posed step
    // must not sweep from the old pose (place a rock on the old->new segment:
    // expect no contact).
}

TEST(NearContact, SmallRocksShoveAndReportMinorContacts) {
    // a small rock radius 0.2 on the swept path: drain_small_contacts() has 1
    // entry; build() draws it displaced from pos_sys (shove offset != 0).
}

TEST(NearContact, ClearDropsContactsCooldownsGhosts) {   // Review Focus 1
    // touch, do not drain, clear(): drains are empty, stats zero.
}
```

Write every stub test body fully in the file (the comments above state each one's arrange/act/assert; use the `SweptHitAtDashSpeed` pattern).

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `--gtest_filter='Near*'` → PASS.

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/rock_near.h native/src/renderer/rock_near.cc native/tests/renderer/rock_near_test.cc
git commit -m "feat(rock-fields): near contacts -- swept large-rock touches with cooldown and spawn ghosting; small-rock shove"
```

---

### Task 7: Host integration of the near band

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`, `engine/rocks/far_tier.py`
- Test: `tests/host/test_far_bindings.py` (extend), new `tests/host/test_rock_near_host.py`, `tests/unit/test_far_registry.py`

**Interfaces:**
- Consumes: `NearField` (Tasks 4–6), `MinorPass::render(FragmentLookup, …)` (Task 3), `FarPass::render_impostors`.
- Produces (host, in `host_bindings.cc`):
  - globals `renderer::rockfield::NearField g_near_field; NearOutput g_near_out;`
  - `far_set_dials` parses the `near_*` and `collide_cooldown_s` keys into `NearDials` and calls `g_near_field.set_dials` (an omitted key resets to its default, as the rest of `far_set_dials`).
  - `far_set_catalogue` entries gain optional `"kind"` (`"fragment"`/`"major"`), `"family"`, `"lod0"`/`"lod1"` model handles and `"bound_radius_mu"`; the host builds `NearCatalogue` from the silicate fragments / majors that have both handles, and a `FragmentLookup` for `kNearSmallFamily`/`kNearLargeFamily`.
  - `far_set_sources` / `far_set_frame` → `g_near_field.set_sources(g_far_field.active_sources())`.
  - In `frame()`, inside the `xform_sync` block after the minors step: scope `rock.near.stream` — centre = the minors' player box centre (system: `render_origin + centre_render + g_far_field.anchor()`), else the main camera eye; `g_near_field.stream(centre)`; then `g_near_field.step(...)` with the player box, `g_near_shield_inflate`, and the minors' dials.
  - In `render_space_geometry`, after the minors draw: scope `rock.near.draw` — `g_near_field.build(...)` for THIS camera, `g_minor_pass->render(near_lookup, g_near_out.meshes, …)`, `g_far_pass->render_impostors(g_near_out.billboards, …)` (the near billboards' atlases are catalogue atlases already loaded by `FarPass`).
  - Everything is gated on `g_far_enabled`.
  - `far_clear()` also clears `g_near_field` (Review Focus 1) and `reset_player()`; `minors_set_player(None)` also calls `g_near_field.reset_player()`.
  - New bindings: `rockfield_drain_contacts() -> list[dict]` (`point`, `normal`, `rock_centre`, `rock_radius`, `rel_speed`, `pen`; tuples), `rockfield_set_shield_inflate(float)`.
  - `far_stats()` gains `near_cells`, `near_small`, `near_large`, `near_meshes`, `near_billboards`, `near_ghosted`.
  - `minors_drain_contacts()` returns MinorField's contacts followed by `g_near_field.drain_small_contacts()` (so `minor_contact.pump` handles small near rocks unchanged).
- Produces (Python `engine/renderer.py`): `rockfield_drain_contacts() -> list`, `rockfield_set_shield_inflate(scale: float) -> None`, docstrings in the file's style.
- Produces (`engine/rocks/far_tier.py`): `_push_catalogue` sends `kind`, `family`, `bound_radius_mu` and, for silicate fragments and majors, `lod0`/`lod1` handles loaded with `r.load_model(path, [], None, decals=None, scale=1.0)` exactly as `minors._ensure_fragments` loads fragments.

- [ ] **Step 1: Write the failing host test** (`tests/host/test_rock_near_host.py`, modelled on `tests/host/test_far_bindings.py`'s fixture — headless init, skip without GL)

```python
def test_inside_a_tile_field_streams_and_draws_near_rocks(host):
    far_tier.reset()
    # One full-density sphere source around the view origin, the real catalogue.
    _push_real_catalogue(host)                 # far_tier._push_catalogue(host) via a reconcile
    host.far_set_sources([_sphere_source(radius=2000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))
    _set_camera_at_origin(host)                # the same helper test_far_bindings uses
    host.frame()
    st = host.far_stats()
    assert st["near_cells"] > 0
    assert st["near_meshes"] > 0 and st["near_billboards"] > 0


def test_far_clear_drops_the_near_field(host):
    ...  # stream as above, then host.far_clear(); far_stats()["near_cells"] == 0 and
         # rockfield_drain_contacts() == []


def test_disabled_far_tier_streams_nothing(host):
    ...  # far_set_enabled(False); frame(); near_cells == 0
```

Fill the helpers from the existing host tests (`tests/host/test_far_bindings.py`, `tests/host/test_minors_bindings.py`). Unit test (`tests/unit/test_far_registry.py`): `_push_catalogue` entries for a silicate fragment carry `kind == "fragment"`, `lod0`, `lod1`, `bound_radius_mu` (use the existing fake renderer double — extend its `load_model` to return incrementing handles, mirroring the real signature).

- [ ] **Step 2: Run** (sandbox disabled) → FAIL. **Step 3: Implement.** **Step 4: Run** `uv run pytest tests/host/test_rock_near_host.py tests/host/test_far_bindings.py tests/unit/test_far_registry.py -q` → PASS.

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/host/host_bindings.cc engine/renderer.py engine/rocks/far_tier.py tests/host/test_rock_near_host.py tests/host/test_far_bindings.py tests/unit/test_far_registry.py
git commit -m "feat(rock-fields): host streams, steps and draws the near band (rock.near.* scopes)"
```

---

### Task 8: Large-rock collision response (sim side)

**Files:**
- Create: `engine/rocks/scenery_contact.py`
- Modify: `engine/host_loop.py` (pump beside `_pump_minor_contact`; reset on mission swap), `engine/rocks/far_tier.py` (push shield inflate each reconcile), `engine/rocks/far_dials.py` (`collide_damage_scale` 1.0, `collide_ref_radius_gu` 5.0 — Python-owned)
- Test: `tests/unit/test_scenery_contact.py`

**Interfaces:**
- Consumes: `renderer.rockfield_drain_contacts()` (Task 7); `engine.appc.collisions._resolve_body`, `_Body`, `_bubble_contact`, `_BUBBLE_MISS`, `_ke_damage`, `_ensure_overlay`, `_trace_own_hull`, `scuff_radius_gu`, `COLLISION_RESTITUTION`; `engine.appc.combat.apply_hit`, `shields_block`, `SHIELD_ELLIPSOID_AXIS_SCALE`; `engine.appc.hit_feedback.SHIELD_SPLASH_REACH_PER_RADIUS`; `engine.rocks.minor_contact._muted` (reuse the same mute rule).
- Produces:

```python
def reset() -> None: ...
def shield_inflate(player) -> float:
    """SHIELD_ELLIPSOID_AXIS_SCALE when combat.shields_block(player), else 0.0."""
def respond(player, contact: dict, ship_instances=None) -> dict | None:
    """Apply one large-rock touch. Returns {"shielded": bool, "damage": float,
    "impulse": (x, y, z)} when it responded, None when it did not (receding,
    shield bubble missed, player not in the viewed set)."""
def pump(player, contacts=None, session=None) -> list:
    """Drain (or take `contacts`), skip all when muted (dashing / "warp" set),
    respond to each; returns the non-None results."""
```

  Response (spec §2): rock is immovable, so the ship takes the full impulse and de-penetration.
  - Only when `frames.containing_set(player) is frames.viewing_set()` (contacts are view-space; record the cross-region case as a limitation in the docstring).
  - `ship = collisions._resolve_body(player)`; `rock = collisions._Body(None, TGPoint3(*contact["rock_centre"]), contact["rock_radius"], 0.0, False, TGPoint3(0,0,0), TGPoint3(0,0,0), 1.0)`.
  - Shields up (`combat.shields_block(player)`): `hit = collisions._bubble_contact(ship, rock)`; `_BUBBLE_MISS` → `None`; a tuple `(point, n_ship_to_rock, pen)` → normal `n = -n_ship_to_rock`, shield point = `point`, `shielded = True`; `None` (rock inside the bubble / no hull box) → hull path with `shielded = True` and no shield point.
  - Hull path: `n = contact["normal"]`, `pen = contact["pen"]`, point = `contact["point"]`.
  - `v_rel = dot(ship.velocity, n)`; `v_rel >= 0` → `None` (receding: the debounce, as `_respond_pair`).
  - Impulse: `_ensure_overlay(player) += -(1 + COLLISION_RESTITUTION) * v_rel * n`; de-penetrate: `SetTranslateXYZ(p + n * pen)`.
  - `damage = _ke_damage(ship.inv_mass, v_rel) * far_dials.get("collide_damage_scale") * min(1.0, rock_radius / far_dials.get("collide_ref_radius_gu"))`.
  - `apply_hit(player, damage, pt, None, normal=…, ship_instances=…, weapon_type="collision", hit_tangent=…, decal_radius=scuff_radius_gu(rock_radius, pen), decal_dent=1.0, bypass_shields=not shielded, shield_point=bubble_point_or_None, single_impact=True, shield_radius=rock_radius / SHIELD_SPLASH_REACH_PER_RADIUS)`; hull path refines `pt`/normal via `_trace_own_hull(ship_instances, ship, point, n_into_ship, reach=2*(ship.contact+rock_radius))`. If `apply_hit` rejects `source=None`, pass the player's own set's `None`-safe sentinel the function documents — check `apply_hit`'s body first and adapt; the test below pins that it is called.
  - No ET_OBJECT_COLLISION / planet / cloaked events (scenery is not an object).
  - `far_tier.reconcile` calls `r.rockfield_set_shield_inflate(scenery_contact.shield_inflate(player))` every frame (wrapped like its other pushes).
  - `host_loop`: `_pump_scenery_contact(player, session)` next to `_pump_minor_contact` (same call site, same try/log pattern); `scenery_contact.reset()` next to `_minor_contact.reset()` on mission swap.

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_scenery_contact.py`)

```python
import pytest
from engine.appc.math import TGPoint3
from engine.rocks import scenery_contact as sc, far_dials


@pytest.fixture(autouse=True)
def _reset():
    sc.reset(); far_dials.reset()
    yield
    sc.reset(); far_dials.reset()


def _contact(normal=(0.0, -1.0, 0.0), pen=0.1, radius=2.0):
    return {"point": (0.0, 1.0, 0.0), "normal": normal, "rock_centre": (0.0, 3.0, 0.0),
            "rock_radius": radius, "rel_speed": 6.0, "pen": pen}


def test_hull_hit_bounces_and_damages(player_moving_up, calls):
    # player_moving_up: a fresh-world Galaxy at the origin, velocity (0, 6, 0),
    # shields down, in the viewed set (build from tests/helpers/fresh_world, as
    # tests/unit/test_rock_shield_collision.py does). `calls` monkeypatches
    # combat.apply_hit to record kwargs.
    out = sc.respond(player_moving_up, _contact())
    assert out is not None and out["shielded"] is False
    assert out["impulse"][1] < 0.0                     # pushed back down -Y
    (hit,) = calls
    assert hit["bypass_shields"] is True and hit["weapon_type"] == "collision"
    assert hit["damage"] > 0.0


def test_shield_up_bounces_at_the_bubble(player_moving_up_shielded, calls):
    out = sc.respond(player_moving_up_shielded, _contact())
    assert out["shielded"] is True
    (hit,) = calls
    assert hit["bypass_shields"] is False and hit["shield_point"] is not None


def test_receding_does_nothing(player_moving_down, calls):
    assert sc.respond(player_moving_down, _contact()) is None
    assert calls == []


def test_damage_scales_with_speed_and_size(player_factory, calls):
    slow = sc.respond(player_factory(vy=2.0), _contact(radius=5.0))["damage"]
    fast = sc.respond(player_factory(vy=6.0), _contact(radius=5.0))["damage"]
    small = sc.respond(player_factory(vy=6.0), _contact(radius=1.0))["damage"]
    assert fast == pytest.approx(slow * 9.0, rel=1e-6)
    assert small == pytest.approx(fast / 5.0, rel=1e-6)


def test_muted_while_dashing_or_in_warp(player_moving_up, calls, monkeypatch):
    monkeypatch.setattr("engine.rocks.minor_contact._muted", lambda p: True)
    assert sc.pump(player_moving_up, contacts=[_contact()]) == []
    assert calls == []


def test_shield_inflate_follows_shields(player_moving_up, player_moving_up_shielded):
    from engine.appc.combat import SHIELD_ELLIPSOID_AXIS_SCALE
    assert sc.shield_inflate(player_moving_up) == 0.0
    assert sc.shield_inflate(player_moving_up_shielded) == pytest.approx(SHIELD_ELLIPSOID_AXIS_SCALE)
```

Write the fixtures in the test file, reusing the fresh-world helpers that `tests/unit/test_rock_shield_collision.py` uses to make a ship and raise/lower its shields. Also add a host-wiring test to `tests/unit/test_far_host_wiring.py` (whatever pattern it uses to assert `host_loop` calls the far pumps) asserting `_pump_scenery_contact` is called where `_pump_minor_contact` is.

- [ ] **Step 2: Run** → FAIL (module missing). **Step 3: Implement.** **Step 4: Run** `uv run pytest tests/unit/test_scenery_contact.py tests/unit/test_far_host_wiring.py tests/unit/test_minor_contact.py -q` → PASS.

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add engine/rocks/scenery_contact.py engine/host_loop.py engine/rocks/far_tier.py engine/rocks/far_dials.py tests/unit/test_scenery_contact.py tests/unit/test_far_host_wiring.py
git commit -m "feat(rock-fields): large scenery rocks collide and damage the player (shield bounce / hull hit)"
```

---

### Task 9: Baked rock-collection sprites

**Files:**
- Modify: `native/src/rockgen/include/rockgen/impostor.h`, `native/src/rockgen/src/impostor.cc`
- Modify: `native/tools/rock_catalogue/main.cc`, `writer.h`, `writer.cc`
- Modify: `native/src/rockgen/include/rockgen/recipe.h`, `src/recipe.cc` (parse `collections`)
- Modify: `native/assets/rocks/recipe.json`, regenerate `native/assets/rocks/catalogue.json` and add `native/assets/rocks/collections/`
- Modify: `native/assets/rocks/README.md`, `engine/rocks/catalogue.py`
- Test: `native/tests/rockgen/*_test.cc` (new `collection_test.cc` + CMake line), `tests/tools/test_rock_catalogue_drift.py`, `tests/unit/test_rock_catalogue.py`

**Interfaces:**
- Produces (`rockgen`):

```cpp
struct ImpostorPart {
    const assets::MeshCpu* mesh;     // glTF frame, metres
    const RockSurface* surface;
    glm::mat4 xform;                 // part -> collection frame (glTF, metres)
};
// Like bake_impostor but rasterises every part into the same 16 views, framed
// on the union's bounding sphere. bake_impostor(mesh, s, n) == bake_impostor_parts({{&mesh,&s,I}}, n)
// byte-for-byte (the catalogue drift test guards it).
Impostor bake_impostor_parts(const std::vector<ImpostorPart>& parts, int view_size);

struct CollectionSpec { std::string id; std::string variant; std::uint64_t seed; int rocks; };
// recipe.json "collections": {"count": 16, "family": "silicate", "view_size": 128,
//   "variants": [{"name": "sparse", "rocks": [20, 30]}, {"name": "medium", "rocks": [30, 45]},
//                {"name": "dense", "rocks": [45, 60]}],
//   "size": [0.03, 0.15], "exponent": 2.5}
// Arrangement (deterministic from the recipe seed + id): positions uniform in
// the unit ball (rejection), radii power-law in `size` (fractions of the
// collection radius), random orientation; rock meshes drawn from the family's
// fragments (r < 0.08) and majors (r >= 0.08), lod1; scaled so the union's
// bound radius is exactly 1 m in the bake.
```

  Output per collection `collections/<variant>_<NN>/impostor_base.png`, `impostor_normal.png`; `catalogue.json` gains `"collections": [{"id", "variant", "impostor": {"albedo","normal","grid","view_size"}, "avg_albedo"}]` (`avg_albedo` = mean of the coverage-weighted albedo atlas). Contact sheet unchanged (rocks only).
- Produces (Python `engine/rocks/catalogue.py`): `@dataclass(frozen=True) class Collection: id: str; variant: str; impostor_albedo: str; impostor_normal: str; avg_albedo: tuple` and `collections() -> list[Collection]` (cached like `load()`, resolved at use, empty list when the manifest has none).

- [ ] **Step 1: Failing tests**

`native/tests/rockgen/collection_test.cc`:

```cpp
TEST(CollectionBake, SinglePartEqualsBakeImpostor) {
    // generate one fragment spec from the committed recipe (as the existing
    // rockgen tests do), bake both ways, compare albedo and normal pixel bytes.
}
TEST(CollectionBake, ArrangementIsDeterministicAndInsideTheUnitBall) {
    // expand the recipe's collections twice; identical specs; every part's
    // centre + radius <= 1 + 1e-5 in the bake frame.
}
TEST(CollectionBake, CoverageGrowsWithVariant) {
    // mean alpha of a sparse vs dense bake from the same index: dense > sparse.
}
```

`tests/tools/test_rock_catalogue_drift.py`: add `"collections/dense_00"` to `SAMPLES` (the tool's `--only` must accept a collection id) and a manifest test:

```python
def test_manifest_lists_every_collection():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    cols = man["collections"]
    assert len(cols) == 48
    assert {c["variant"] for c in cols} == {"sparse", "medium", "dense"}
    for c in cols:
        assert (ROCKS / c["impostor"]["albedo"]).is_file()
```

`tests/unit/test_rock_catalogue.py`: `catalogue.collections()` returns 48 entries with existing atlas files under `catalogue_root()`.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, then regenerate: `./build/native/tools/rock_catalogue/rock_catalogue --recipe native/assets/rocks/recipe.json --out native/assets/rocks`. Verify every existing rock directory is byte-identical (`git diff --stat native/assets/rocks/majors native/assets/rocks/fragments` must show nothing); only `catalogue.json`, `recipe.json` and the new `collections/` change. Document the collections in `native/assets/rocks/README.md`.

- [ ] **Step 4: Run** `ctest --test-dir build -R 'CollectionBake|Rockgen' --output-on-failure`, `uv run pytest tests/tools/test_rock_catalogue_drift.py tests/unit/test_rock_catalogue.py -q` → PASS.

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/rockgen/include/rockgen/impostor.h native/src/rockgen/src/impostor.cc native/src/rockgen/include/rockgen/recipe.h native/src/rockgen/src/recipe.cc native/tools/rock_catalogue/main.cc native/tools/rock_catalogue/writer.h native/tools/rock_catalogue/writer.cc native/tests/rockgen/collection_test.cc native/tests/rockgen/CMakeLists.txt native/assets/rocks/recipe.json native/assets/rocks/catalogue.json native/assets/rocks/collections native/assets/rocks/README.md engine/rocks/catalogue.py tests/tools/test_rock_catalogue_drift.py tests/unit/test_rock_catalogue.py
git commit -m "feat(rock-fields): bake 48 rock-collection impostors (16 x sparse/medium/dense) with a drift test"
```

---

### Task 10: MidField — nested collection tiles

**Files:**
- Create: `native/src/renderer/include/renderer/rock_mid.h`, `native/src/renderer/rock_mid.cc`, `native/tests/renderer/rock_mid_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt`, `native/tests/renderer/CMakeLists.txt`, `engine/rocks/far_dials.py`

**Interfaces:**
- Consumes: `far::DiscSource`, `far::field_density`, `far::make_impostor`, `far::pixels_per_gu`.
- Produces (`renderer::rockfield`):

```cpp
struct MidDials {   // defaults MUST equal far_dials.py mid_* / haze_handoff_* keys
    float l0_tile_gu = 150.0f, l1_tile_gu = 600.0f, l2_tile_gu = 2400.0f;
    float in_lo_gu = 80.0f, in_hi_gu = 150.0f;     // L0 fades in over [in_lo, in_hi]
    float l0_out_gu = 600.0f, l1_out_gu = 2400.0f; // level boundaries
    float xfade_frac = 0.25f;                      // boundary b crossfades over [b(1-f), b]
    float handoff_gu = 8000.0f, handoff_band_gu = 2000.0f;  // L2 fades out over [handoff-band, handoff]
    float fill = 1.0f;                             // chance = clamp(density * fill, 0, 1)
    float sprite_scale = 1.0f;                     // sprite diameter = tile * sprite_scale * (0.8 + 0.4 u)
    int max_sprites = 4000;                        // per camera build, nearest first
};
struct MidCollection { int atlas_index; int variant; };   // variant 0 sparse, 1 medium, 2 dense
// Pure: the weight of level `lvl` at camera distance d (0..1).
float mid_level_weight(int lvl, float d, const MidDials& m);
struct MidBuildInput { glm::mat4 view{1}, proj{1}; float viewport_h = 720; glm::dvec3 render_origin{0}, anchor_sys{0}; };
struct MidOutput { std::vector<far::ImpostorBin> sprites; int count = 0; int tiles = 0; };
class MidField {
public:
    void set_dials(const MidDials&);
    void set_collections(std::vector<MidCollection>);   // atlas_index = FarPass atlas slot
    void set_sources(const std::vector<far::DiscSource>& active);
    void build(const MidBuildInput& in, MidOutput& out) const;
};
```

  Build: for each level, enumerate tiles (cubes of the level's tile size, fixed in system coordinates) whose centre distance from the eye lies where `mid_level_weight > 0`, frustum-cull (sphere of half-diagonal), then per tile: `dens = min(1, Σ_sources field_density(centre))`; `u0..u5` = hashes of (level, i, j, k, source-independent salt); present iff `u0 < clamp(dens * fill, 0, 1)`; variant = `dens*fill < 1/3 ? 0 : (< 2/3 ? 1 : 2)`; collection = the `u1`-th collection of that variant; centre jittered by `(u2..u4 - 0.5) * 0.5 * tile`; orientation from `u5` (axis via `rockrand::unit_vector` seeded by the tile hash) ; half-size = `0.5 * tile * sprite_scale * (0.8 + 0.4*u1')`. Weight `w = mid_level_weight(lvl, d)`: emit with dither `-w` when the level is fading IN at d, `+(1-w)` when fading OUT (Task 3's sign convention), 0 at w == 1. Never emit within `in_lo_gu` (no double drawing with the near band). Cap `max_sprites` nearest-first.
- Python dials (NATIVE): `mid_l0_tile_gu`, `mid_l1_tile_gu`, `mid_l2_tile_gu`, `mid_in_lo_gu`, `mid_in_hi_gu`, `mid_l0_out_gu`, `mid_l1_out_gu`, `mid_xfade_frac`, `haze_handoff_gu`, `haze_handoff_band_gu`, `mid_fill`, `mid_sprite_scale`, `mid_max_sprites` with the defaults above.

- [ ] **Step 1: Failing tests** (`rock_mid_test.cc`)

```cpp
TEST(MidLevels, WeightsCrossfadeAndSumToOneInside) {
    rockfield::MidDials m;
    for (float d : {200.0f, 500.0f, 560.0f, 1000.0f, 2000.0f, 3000.0f, 5000.0f}) {
        const float s = rockfield::mid_level_weight(0, d, m) + rockfield::mid_level_weight(1, d, m) +
                        rockfield::mid_level_weight(2, d, m);
        EXPECT_NEAR(s, 1.0f, 1e-5f) << d;
    }
    EXPECT_EQ(rockfield::mid_level_weight(0, 79.0f, m), 0.0f);   // near band owns < 80
    EXPECT_NEAR(rockfield::mid_level_weight(0, 115.0f, m), 0.5f, 1e-5f);
    EXPECT_EQ(rockfield::mid_level_weight(2, 8000.0f, m), 0.0f); // haze owns past the hand-off
    EXPECT_NEAR(rockfield::mid_level_weight(2, 7000.0f, m), 0.5f, 1e-5f);
}

TEST(MidTiles, DeterministicAndDensityDriven) {
    // full-density sphere around the origin vs a 0.05 belt: sprite count ratio
    // ~0.05 (+-0.03) for the same camera; two builds give identical sprites.
}

TEST(MidTiles, VoidsShowNothing) { /* no sources -> no sprites */ }

TEST(MidTiles, NothingInsideTheNearBand) {
    // every emitted sprite centre is >= in_lo_gu - 0.25 * l0_tile_gu * sqrt(3) from the eye
    // (jitter allowance), and none is emitted for tiles whose centre is < in_lo_gu.
}

TEST(MidTiles, TelephotoCapHolds) {   // Review Focus 5
    rockfield::MidDials m; m.max_sprites = 300;
    // vast full-density sphere (radius 1e6), 1 degree fov looking along +Y:
    // out.count <= 300 and out.tiles bounded (< 200000).
}
```

Write the elided bodies fully, following the pattern of Task 4's tests.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `--gtest_filter='Mid*'` → PASS; `uv run pytest tests/unit/test_far_dials.py -q` → PASS (add default-equality asserts for the mid keys).

- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/rock_mid.h native/src/renderer/rock_mid.cc native/tests/renderer/rock_mid_test.cc native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt engine/rocks/far_dials.py tests/unit/test_far_dials.py
git commit -m "feat(rock-fields): MidField -- nested 150/600/2400 GU collection tiles driven by the field density"
```

---

### Task 11: Mid band in the host

**Files:**
- Modify: `native/src/host/host_bindings.cc`, `native/src/renderer/far_pass.{h,cc}` (atlas slots beyond the catalogue), `engine/rocks/far_tier.py`, `engine/renderer.py` (docstring of `far_set_catalogue`)
- Test: `tests/host/test_rock_mid_host.py`, `tests/unit/test_far_registry.py`

**Interfaces:**
- Consumes: `MidField` (Task 10), `catalogue.collections()` (Task 9).
- Produces:
  - `far_set_catalogue(entries, view_dirs, collections=[])` — new optional third argument `[{"albedo", "normal", "avg_albedo", "variant"}]`; the host appends their atlas paths after the catalogue's (`atlas_index = len(entries) + i`) and calls `g_mid_field.set_collections`.
  - `far_set_dials` parses the mid keys into `MidDials`; `far_set_sources/frame` feed `g_mid_field.set_sources(active)`.
  - In `render_space_geometry` after the near draw: scope `rock.mid.draw` — `g_mid_field.build` for THIS camera, then `g_far_pass->render_impostors(g_mid_out.sprites, …)`; skip a bin whose atlas fails to load (as the far build does).
  - `far_stats()` gains `mid_sprites`, `mid_tiles`.
  - `far_tier._push_catalogue` sends `catalogue.collections()` as the third argument (variant → 0/1/2).

- [ ] **Step 1: Failing tests** — host test: from 1,500 GU outside a full-density 1,000 GU sphere looking at it, one `frame()` gives `far_stats()["mid_sprites"] > 0` and `near_meshes == 0`; inside it at the centre `mid_sprites` counts only sprites ≥ 80 GU away (assert the stat is > 0 and the near stats are > 0 too). Unit test: `_push_catalogue` passes 48 collection dicts.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** (sandbox disabled) `uv run pytest tests/host/test_rock_mid_host.py tests/unit/test_far_registry.py -q` → PASS.
- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/host/host_bindings.cc native/src/renderer/include/renderer/far_pass.h native/src/renderer/far_pass.cc engine/rocks/far_tier.py engine/renderer.py tests/host/test_rock_mid_host.py tests/unit/test_far_registry.py
git commit -m "feat(rock-fields): draw mid collection tiles per camera (rock.mid.draw)"
```

---

### Task 12: Haze starts at a distance, at reduced resolution

**Files:**
- Modify: `native/src/renderer/include/renderer/far_field.h`, `far_field.cc` (`haze_column` start ramp), `native/src/renderer/shaders/far_haze.frag`, `native/src/renderer/include/renderer/far_pass.h`, `far_pass.cc` (low-res targets + upsample composite), `native/src/host/host_bindings.cc` (scope `rock.haze`), `engine/rocks/far_dials.py`
- Test: `native/tests/renderer/far_field_test.cc`, `far_pass_test.cc`, `tests/host/test_far_haze_displayed.py`

**Interfaces:**
- Produces:
  - `FarDials` gains `float haze_start_gu = 6000.0f; float haze_start_ramp_gu = 2000.0f; int haze_res_divisor = 4;` — the defaults make the haze ramp in exactly over the L2 fade-out band (`haze_handoff_gu - haze_handoff_band_gu` … `haze_handoff_gu`). Python: `haze_start_gu` and `haze_start_ramp_gu` are NOT separate dials — `far_tier` derives them from `haze_handoff_gu` / `haze_handoff_band_gu` when pushing native dials (single source of truth); `haze_res_divisor` is a NATIVE dial (default 4, floor 1).
  - `haze_column(..., float start_gu, float ramp_gu)` — new trailing params (default 0, 0 = today's behaviour): each sample's `dtau` is multiplied by `smoothstep(start_gu, start_gu + ramp_gu, t)` (a hard step at `start_gu` when `ramp_gu == 0`). The shader gets `u_start_gu`, `u_start_ramp_gu` with the identical rule.
  - `FarPass::render_haze` marches into its own RGBA16F target at `(w / haze_res_divisor, h / haze_res_divisor)` (divisor 1 = draw straight into the HDR target as today), then composites premultiplied over the HDR target through the system nebula's depth-aware upsample shader (`nebula_upsample.frag`, via the pipeline accessor `SystemNebulaPass` uses — read `system_nebula_pass.cc` for the bind/uniform sequence and copy it, including `ensure_half_targets`' resize handling and the `HdrTarget::resize()` active-texture-unit trap noted in far-tier).
  - Host wraps the haze draw in `DAUNTLESS_FRAME_SCOPE("rock.haze")` (keep the old `space.far.haze` name if one exists? — rename it to `rock.haze`).

- [ ] **Step 1: Failing tests**

```cpp
TEST(FarHazeStart, NothingBeforeTheStart) {
    far::DiscSource s = /* full-density sphere radius 20,000 around the origin, one population */;
    const auto near = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 5000.0f, 4.0f, 48,
                                       1000.0f, glm::vec3(1), 6000.0f, 2000.0f);
    EXPECT_EQ(near.alpha, 0.0f);
    const auto far_ = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 19000.0f, 4.0f, 48,
                                       1000.0f, glm::vec3(1), 6000.0f, 2000.0f);
    EXPECT_GT(far_.alpha, 0.0f);
}
TEST(FarHazeStart, ZeroStartIsTodaysColumn) { /* bitwise equal to the 8-arg call */ }
```

GL: extend `FarPassGLTest.HazeShaderMatchesTheCpuReference`-style test with `start 300, ramp 200` (sizes scaled to the test's scene) — shader vs CPU within the existing tolerance, at divisor 1 (exact pixel compare path); and `FarPassGLTest.QuarterResHazeMatchesFullResInOpenSpace` — divisor 4 vs divisor 1 over a depth-free patch: mean absolute difference < 2/255.

Host: `tests/host/test_far_haze_displayed.py` — keep the existing outside-the-field assertion (≥ 20/255 displayed from Beol 4's view at 6,000 GU — with the new start distance the haze still covers the far part of the field; if the measured value drops below the target, recalibrate `tile_haze_brightness` on the displayed value per the far-tier lesson and record the new number in the dial's comment).

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** (sandbox disabled) `--gtest_filter='FarHaze*:FarPassGLTest.*'` and `uv run pytest tests/host/test_far_haze_displayed.py -q` → PASS.
- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/far_field.h native/src/renderer/far_field.cc native/src/renderer/shaders/far_haze.frag native/src/renderer/include/renderer/far_pass.h native/src/renderer/far_pass.cc native/src/host/host_bindings.cc engine/rocks/far_dials.py engine/rocks/far_tier.py native/tests/renderer/far_field_test.cc native/tests/renderer/far_pass_test.cc tests/host/test_far_haze_displayed.py
git commit -m "feat(rock-fields): haze starts at the L2 hand-off and marches at quarter resolution with a depth-aware upsample"
```

---

### Task 13: Dials group "rock fields" and the "inside Beol 4" dev mission

**Files:**
- Modify: `engine/rocks/far_dials.py` (group name, `_LOOK_FIRST`), `engine/dev_missions/_far_tier_common.py` (`start_on_far_dials` targets the renamed group), `engine/host_loop.py` (dev mission list near line 3459), Developer Options label "Far Tier" → "Rock Fields" (find it with `grep -rn '"Far Tier"' engine native/assets/ui-cef`)
- Create: `engine/dev_missions/rock_fields_inside.py`
- Test: `tests/unit/test_far_dials.py`, `tests/unit/test_dev_far_tier_preview.py`

**Interfaces:**
- Produces: `dev_dial_groups` group `"rock fields"` (registered by `far_dials.register()`); `_LOOK_FIRST` = `("near_small_density", "near_large_density", "near_small_mesh_gu", "near_small_billboard_gu", "near_large_mesh_gu", "near_large_billboard_gu", "mid_fill", "mid_sprite_scale", "mid_l0_out_gu", "mid_l1_out_gu", "haze_handoff_gu", "haze_brightness", "tile_haze_brightness", "haze_gain", "tile_haze_gain", "tile_haze_noise_contrast", "belt_noise_contrast", "collide_damage_scale")`, then every other key.
- Produces: mission module `engine.dev_missions.rock_fields_inside`, listed as "Rock Fields: inside Beol 4" in the developer mission list beside the two Far Tier missions. It loads Beol 4 through its SDK `Initialize()`, places the player 300 GU inside "Asteroid Field 1" (from the field centre toward Beol 4's "Player Start", nose toward the centre) with `common.create_aimed_player`, and calls `common.start_on_far_dials("near_large_density")`.

- [ ] **Step 1: Failing tests**

```python
def test_dial_group_is_rock_fields_with_look_dials_first(monkeypatch):
    from engine.rocks import far_dials
    from engine import dev_dial_groups
    registered = {}
    monkeypatch.setattr(dev_dial_groups, "register_group",
                        lambda name, order, cur, step: registered.setdefault(name, order))
    far_dials.register()
    assert list(registered) == ["rock fields"]
    assert registered["rock fields"][0] == "near_small_density"


def test_inside_beol4_mission_is_listed_and_starts_inside_the_field():
    # follow tests/unit/test_dev_far_tier_preview.py's pattern for the two
    # existing missions: the module imports, is in the dev mission list, and a
    # headless Initialize puts the player within 1,000 GU of the field centre.
    ...
```

Write the second test fully from the existing preview-mission test's pattern.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `uv run pytest tests/unit/test_far_dials.py tests/unit/test_dev_far_tier_preview.py -q` → PASS.
- [ ] **Step 5: Gate and commit**

```bash
scripts/check_tests.sh
git add engine/rocks/far_dials.py engine/dev_missions/_far_tier_common.py engine/dev_missions/rock_fields_inside.py engine/host_loop.py tests/unit/test_far_dials.py tests/unit/test_dev_far_tier_preview.py <the Developer Options label file>
git commit -m "feat(rock-fields): 'rock fields' dial group (look dials first) and the 'inside Beol 4' dev mission"
```

---

### Task 14: Displayed-value acceptance, no-double-draw checks, benchmarks

**Files:**
- Create: `tests/host/test_rock_fields_displayed.py`, `native/tests/renderer/rock_near_bench_test.cc`, `native/tests/renderer/rock_mid_bench_test.cc` (CMake lines)
- Test only (fix code only if a test exposes a real defect — report it, do not loosen the test)

**Interfaces:**
- Consumes: everything above through the real host, the pattern of `tests/host/test_far_haze_displayed.py` (real SDK content, `far_tier.reconcile_with`, `host_loop._aggregate_lights`, the full post chain).

- [ ] **Step 1: Write the tests**

`tests/host/test_rock_fields_displayed.py`:
- `test_field_visible_from_outside` — Beol 4 from 6,000 GU (the "Far Tier: Beol 4 field" view): displayed far-on minus far-off at the view centre ≥ 20/255 (haze + mid tiles together).
- `test_rocks_visible_from_inside` — Beol 4, 300 GU inside the field (the new mission's pose): `far_stats()` near meshes > 0 and billboards > 0, and the displayed far-on minus far-off over the whole frame has at least 0.5% of pixels changed by ≥ 10/255 (rocks are discrete; a mean would hide them).
- `test_no_mid_sprite_within_the_near_band` — at the inside pose, project every mid sprite centre (expose a test-only `far_debug_mid_centres()` binding returning render-space centres, or reuse `far_stats` if Task 11 exposed per-sprite data) and assert none is closer than `mid_in_lo_gu` minus the jitter allowance.
- `test_haze_absent_before_its_start` — inside the field looking along a ray that stays inside the sphere for < `haze_start_gu`: far-on minus far-off with near and mid disabled via `far_set_dials` (set both class densities and `mid_fill` to 0) is < 2/255.

Benches (report-only, never fail on time; print with `std::printf` like `far_field_bench_test.cc` did):
- `NearBench.StreamAt100kGups` — stream 600 steps at 100,000 GU/s / 60 Hz through a full-density sphere; report mean ms/step and max cells.
- `MidBench.VastBelt` — build at three points in a 1e6 GU full-density belt; report ms/build and sprite count; ASSERT the cap holds.

- [ ] **Step 2: Run** (sandbox disabled) `uv run pytest tests/host/test_rock_fields_displayed.py -q` and `ctest --test-dir build -R 'Bench' --output-on-failure`. Expected: PASS. A failure here is a real defect in an earlier task: fix it in that task's files with a regression test, and say so in the report.
- [ ] **Step 3: Gate and commit**

```bash
scripts/check_tests.sh
git add tests/host/test_rock_fields_displayed.py native/tests/renderer/rock_near_bench_test.cc native/tests/renderer/rock_mid_bench_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "test(rock-fields): displayed-value acceptance inside/outside Beol 4, no double draw, near/mid benches"
```

---

### Task 15: Records

**Files:**
- Modify: `CLAUDE.md` (the "Far tier" row → "Rock fields" row; restore the pointer to sub-project 4's `explicit_regions`; profiler scopes `rock.near.stream`, `rock.near.draw`, `rock.mid.draw`, `rock.haze`; dial group "rock fields"; collisions sim-side in `scenery_contact.py`; the "Minor rocks" row no longer lists `tile:<set>:<field>` clouds), `docs/superpowers/specs/2026-10-02-rock-fields-design.md` (Status: implemented on `feat/rock-fields`, awaiting live check; list the recorded limitations: NPCs/weapons pass through, AI does not avoid, no targeting/scan/break, headless sim has no scenery rocks, contacts respond only when the player's set is the viewed set, the "Far Tier" dev toggle also disables scenery collisions), `docs/engine/frame-profiler.md` (new scopes; the toggle lives in Developer Options → Diagnostics)
- Test: `tests/docs/test_doc_consistency.py` must stay green

- [ ] **Step 1:** Edit the docs. Keep the CLAUDE.md row the density of its neighbours (one row, `⚠️` for traps).
- [ ] **Step 2:** `uv run pytest tests/docs -q` → PASS.
- [ ] **Step 3: Gate and commit**

```bash
scripts/check_tests.sh
git add CLAUDE.md docs/superpowers/specs/2026-10-02-rock-fields-design.md docs/engine/frame-profiler.md
git commit -m "docs(rock-fields): CLAUDE.md row, spec status and limitations, profiler scopes"
```

---

## Live check (Mark, after the final review)

From the worktree: `./build/dauntless --developer`, then Developer missions:
- "Far Tier: Beol 4 field" — haze far, collection tiles as you close in, large rocks then gravel; no pops at 150 / 60 / 30 GU.
- "Rock Fields: inside Beol 4" — density, collisions with shields up and down, dash through.
- "Far Tier: Vesuvi belt" — the same ladder at belt scale, sparse at the 0.05 floor.
- Developer Options → Diagnostics profiler: `rock.*` scopes; frame rate.
