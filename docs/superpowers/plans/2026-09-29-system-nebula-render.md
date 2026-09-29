# System-Scale Nebula Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw the radial profile's `nebula` column as a star-centred atmosphere — a CPU-built far-field transmittance/inscatter table plus a 30,000 GU near-field march with lanes, forward scatter from the star, a faint emissive floor, and every local MetaNebula as a density bump — replacing the rejected developer spike.

**Architecture:** Python owns the profile maths (exact radial integrals, the veil coefficient `k_sys`, star transmittance for the billboard flare) and pushes the profile to C++ on system change. A pure C++ module builds the 1D radial textures and the 2D far-field table (unit-tested against a CPU reference marcher). A new GL pass `SystemNebulaPass` — infrastructure copied from `NebulaVolumetricPass` (quarter-res target, temporal ping-pong, depth-aware upsample) — marches the near field and reads the table beyond it. Developer-only until Mark approves live; production keeps today's passes.

**Tech Stack:** Python 3.11 (pytest), C++17 + GLSL 410 (gtest/ctest, headless GL), pybind11.

**Spec:** `docs/superpowers/specs/2026-09-29-system-nebula-render-design.md` (and `2026-09-23-radial-system-profile-design.md` for the profile).

## Global Constraints

- Branch `feat/radial-system-profile`, worktree `.claude/worktrees/radial-profile`. **Never commit to main. Never push.** Stage explicit paths only.
- ⛔ Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Temporary mutation: `cp f /tmp/bak` → edit → test → `cp /tmp/bak f` → `diff`.
- Never launch `./build/dauntless`. Live checks are Mark's.
- GLSL is `#version 410 core`; **no compute shaders** (macOS GL 4.1). Shader edits need `cmake --build build -j` (embedded shaders) and fail only at RUNTIME — the headless GL test is the compile check.
- Never run cmake inside `native/`. Build: `cmake --build build -j`; C++ tests: `ctest --test-dir build -R <name> --output-on-failure`.
- Spatial values are GU; never `*_m` / `*_mps`.
- TGObject subclasses vend truthy stubs: use `engine.core.ids.implements(obj, "Name")`, never `hasattr`/truthiness, on engine objects.
- **Developer-only:** the new pass runs only when `dauntless::is_developer_mode()` AND the existing volumetric-nebula setting is on. Without `--developer`, rendering is byte-identical to today (the old `NebulaVolumetricPass` / faithful `NebulaPass` stay and are NOT removed in this plan).
- Look defaults (spec, exact): veil **0.15**; lane feature size **15,000 GU**; lane contrast **0.7**; forward bias `g` **0.6**; emissive floor **0.03**; near range **30,000 GU**; ~**64** near-field steps; table **256 (radius) × 128 (μ)**; radius axis to the far plane **1,800,000 GU** (`engine.cameras.SCENE_FAR_GU`); quarter resolution.
- `k_sys = −ln(veil) / ∫ nebula(r) dr` from the star's surface to the system's outermost region anchor (Vesuvi ≈ 1.9×10⁻⁵ /GU).
- Clump fbm must stay textually identical to the existing GLSL fbm (`nebula_volumetric.frag` / `backdrop.frag`) mirrored by `engine/appc/nebula_density.py` (gameplay concealment reads it).
- Gate: `scripts/check_tests.sh` must exit 0 before the branch is done.

## Review Focus

1. **Camera inside the star's radius or exactly at the star** (r ≈ 0, μ undefined) — no NaN, no black screen. Test: Task 2 `ZeroRadiusIsFinite`.
2. **A system with no profile but local clumps (Multi5/6, unmapped sets)** — clumps still draw; no haze; no crash on an empty profile. Test: Task 4 `ClumpsWithoutProfileRender` and Task 5 `test_unmapped_set_clears_profile`.
3. **Warp tunnel / system change** — the table is rebuilt for the new system and never shows the old system's haze. Test: Task 5 `test_profile_repushed_only_on_system_change`.
4. **Veil for a profile with zero integral** (star-only profiles, nebula ≡ 0) — `k_sys` must not divide by zero. Test: Task 1 `test_k_sys_zero_integral_is_zero`.
5. **Hull between camera and star inside the near range** — the far field must not be added behind an opaque hull. Test: Task 2 `FiniteSegmentStopsAtHull` (CPU composition helper).

---

### Task 1: Profile maths in Python — radial integral, veil, star transmittance

**Files:**
- Modify: `engine/systems/profile.py`
- Test: `tests/unit/test_profile_atmosphere.py`

**Interfaces:**
- Consumes: `Profile`, `ProfileRow`, `evaluate`, `locate` (existing).
- Produces:
  - `VEIL_DEFAULT = 0.15`
  - `radial_integral(profile, r_a, r_b) -> float` — exact ∫ nebula(r) dr over [min, max] of the two radii (piecewise-linear; last row persists).
  - `k_sys(m, veil=VEIL_DEFAULT) -> float` — `−ln(veil)/radial_integral(m.profile, star.radius_gu, r_outer)`, `r_outer` = max region-anchor distance from the star; 0.0 when the integral ≤ 0 or there is no profile/star/region.
  - `star_transmittance(obj, veil=VEIL_DEFAULT) -> float` — `exp(−k_sys(m) · radial_integral(prof, star.radius_gu, r_obj))` for an object in a mapped region, else 1.0.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_profile_atmosphere.py
import math

import pytest

from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap


def _p(*rows):
    return P.Profile(rows=[P.ProfileRow(*r) for r in rows])


def test_radial_integral_is_exact_for_piecewise_linear():
    prof = _p((0.0, 0.0), (100.0, 1.0), (200.0, 0.0))
    assert P.radial_integral(prof, 0.0, 200.0) == pytest.approx(100.0)
    assert P.radial_integral(prof, 50.0, 150.0) == pytest.approx(75.0)
    assert P.radial_integral(prof, 150.0, 50.0) == pytest.approx(75.0)   # order-free


def test_radial_integral_persists_the_last_row():
    prof = _p((0.0, 0.0), (100.0, 0.5))
    assert P.radial_integral(prof, 100.0, 300.0) == pytest.approx(100.0)


def test_radial_integral_of_none_is_zero():
    assert P.radial_integral(None, 0.0, 1e6) == 0.0


def _map(prof, anchor=1000.0):
    return SystemMap(system="S",
                     bodies=[Body("Sun", "Sun", 10.0, (0.0, 0.0, 0.0))],
                     regions=[Region("R1", (anchor, 0.0, 0.0), 50.0)],
                     profile=prof)


def test_k_sys_hits_the_veil_from_the_outermost_region():
    m = _map(_p((0.0, 1.0), (2000.0, 1.0)))
    k = P.k_sys(m, veil=0.15)
    assert math.exp(-k * P.radial_integral(m.profile, 10.0, 1000.0)) == pytest.approx(0.15)


def test_k_sys_zero_integral_is_zero():
    m = _map(_p((0.0, 0.0), (2000.0, 0.0)))
    assert P.k_sys(m) == 0.0
    assert P.k_sys(_map(None)) == 0.0


def test_star_transmittance_at_the_outermost_region_is_the_veil(monkeypatch):
    from engine.systems import frames, resolve
    m = _map(_p((0.0, 1.0), (2000.0, 1.0)))
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("system", "S"), 1000.0, 0.0, 0.0))
    monkeypatch.setattr(resolve, "map_of", lambda name: m)
    assert P.star_transmittance(object(), veil=0.15) == pytest.approx(0.15)


def test_star_transmittance_outside_a_mapped_system_is_one(monkeypatch):
    from engine.systems import frames
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    assert P.star_transmittance(object()) == 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_profile_atmosphere.py -v`
Expected: FAIL — `AttributeError: module 'engine.systems.profile' has no attribute 'radial_integral'`.

- [ ] **Step 3: Implement** — append to `engine/systems/profile.py`:

```python
VEIL_DEFAULT = 0.15   # star transmittance through the whole cloud from the
                      # system's outermost region (spec 2026-09-29, "The veil")


def radial_integral(profile, r_a: float, r_b: float) -> float:
    """Exact integral of the `nebula` column over [min(r_a,r_b), max(...)].
    Piecewise-linear between rows; the last row persists outward."""
    if profile is None or not profile.rows:
        return 0.0
    lo, hi = (r_a, r_b) if r_a <= r_b else (r_b, r_a)
    pts = sorted({lo, hi} | {row.distance_gu for row in profile.rows
                             if lo < row.distance_gu < hi})
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += 0.5 * (evaluate(profile, a).nebula + evaluate(profile, b).nebula) * (b - a)
    return total


def _star_and_outer(m):
    star = next((b for b in m.bodies if b.orbits is None), None)
    if star is None or not m.regions:
        return None, 0.0
    r_outer = max(math.dist(tuple(r.anchor_gu), tuple(star.position_gu))
                  for r in m.regions)
    return star, r_outer


def k_sys(m, veil: float = VEIL_DEFAULT) -> float:
    """Extinction per GU per unit `nebula` so the star's transmittance seen
    from the outermost region equals `veil`. 0.0 when there is nothing to veil."""
    if m is None or m.profile is None:
        return 0.0
    star, r_outer = _star_and_outer(m)
    if star is None:
        return 0.0
    integral = radial_integral(m.profile, star.radius_gu, r_outer)
    if integral <= 0.0:
        return 0.0
    return -math.log(veil) / integral


def star_transmittance(obj, veil: float = VEIL_DEFAULT) -> float:
    """exp(-k_sys * integral from the star's surface to the object's radius):
    how much of the star shows through the cloud. The eye->star line is radial,
    so this is exact. 1.0 outside a mapped system."""
    from engine.systems import frames, resolve
    pos = frames.system_position(obj)
    if pos is None or pos[0][0] != "system":
        return 1.0
    m = resolve.map_of(pos[0][1])
    if m is None or m.profile is None:
        return 1.0
    star, _ = _star_and_outer(m)
    if star is None:
        return 1.0
    r = math.dist(pos[1:], tuple(star.position_gu))
    return math.exp(-k_sys(m, veil) * radial_integral(m.profile, star.radius_gu, r))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_profile_atmosphere.py tests/unit/test_system_profile.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/systems/profile.py tests/unit/test_profile_atmosphere.py
git commit -m "feat(systems): exact radial integral, veil coefficient, star transmittance"
```

---

### Task 2: C++ atmosphere core — radial textures, far-field table, reference marcher

**Files:**
- Create: `native/src/renderer/include/renderer/nebula_atmosphere.h`, `native/src/renderer/nebula_atmosphere.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `nebula_atmosphere.cc` to the renderer sources list beside `nebula_volumetric_pass.cc`)
- Test: `native/tests/renderer/nebula_atmosphere_test.cc` (add to the renderer test sources in `native/tests/renderer/CMakeLists.txt`, beside `dust_pass_test.cc`)

**Interfaces:**
- Produces (namespace `renderer::atmosphere`):
  - `struct RadialProfile { std::vector<float> r; std::vector<float> nebula; float k_sys; float star_radius; glm::vec3 cloud_rgb; glm::vec3 star_rgb; };`
  - `struct LookParams { float g = 0.6f; float floor = 0.03f; float scatter = 1.0f; float far_gu = 1800000.0f; };`
  - `float density(const RadialProfile&, float r)` — `nebula(r)` (linear, last row persists, clamps below first row).
  - `float tau_star(const RadialProfile&, float r)` — `k_sys · ∫_{star_radius}^{r} nebula` (0 for r ≤ star_radius).
  - `float hg(float g, float cos_theta)` — Henyey–Greenstein, normalised over the sphere.
  - `struct Segment { glm::vec3 transmittance; glm::vec3 inscatter; };`
  - `Segment reference_march(const RadialProfile&, const LookParams&, float r0, float mu, float max_dist, int steps)` — CPU truth: march from a point at radius `r0`, direction with cosine `mu` to the outward radial, for `max_dist` or until the ray leaves the far sphere or hits the star.
  - `constexpr int kRadialTexels = 4096; constexpr int kTableR = 256; constexpr int kTableMu = 128;`
  - `float radius_of_u(float u, float far_gu)` = `far_gu * u * u`; `float u_of_radius(float r, float far_gu)` = `sqrt(clamp(r/far_gu,0,1))`.
  - `std::vector<glm::vec2> build_radial_texels(const RadialProfile&, const LookParams&)` — `kRadialTexels` of (density, tau_star) at `radius_of_u(i/(N−1))`.
  - `struct Table { std::vector<glm::vec3> transmittance; std::vector<glm::vec3> inscatter; };` (row-major `[mu_index * kTableR + r_index]`)
  - `Table build_table(const RadialProfile&, const LookParams&)` — each cell = `reference_march(p, look, radius_of_u(i/(R−1)), mu_j, INFINITY, 512)` with `mu_j = −1 + 2j/(Mu−1)`.
  - `Segment compose(const Segment& near, const Segment& far)` — `{near.T*far.T, near.S + near.T*far.S}`.
  - `Segment finite(const Segment& from_a, const Segment& from_b)` — `T = from_a.T / max(from_b.T, 1e-6)`, `S = from_a.S − T * from_b.S` (clamped ≥ 0).

- [ ] **Step 1: Write the failing tests**

```cpp
// native/tests/renderer/nebula_atmosphere_test.cc
#include <gtest/gtest.h>
#include <renderer/nebula_atmosphere.h>
#include <cmath>

using namespace renderer::atmosphere;

namespace {
RadialProfile constant(float n, float k) {
    RadialProfile p;
    p.r = {0.0f, 1.0e7f};
    p.nebula = {n, n};
    p.k_sys = k;
    p.star_radius = 100.0f;
    p.cloud_rgb = glm::vec3(1.0f);
    p.star_rgb = glm::vec3(1.0f);
    return p;
}
}  // namespace

TEST(NebulaAtmosphere, DensityInterpolatesAndPersists) {
    RadialProfile p;
    p.r = {0.0f, 100.0f, 200.0f};
    p.nebula = {0.0f, 1.0f, 0.5f};
    EXPECT_FLOAT_EQ(density(p, 50.0f), 0.5f);
    EXPECT_FLOAT_EQ(density(p, 150.0f), 0.75f);
    EXPECT_FLOAT_EQ(density(p, 5000.0f), 0.5f);
}

TEST(NebulaAtmosphere, TauStarMatchesClosedForm) {
    const auto p = constant(0.5f, 1.0e-4f);
    EXPECT_NEAR(tau_star(p, 1100.0f), 1.0e-4f * 0.5f * 1000.0f, 1e-6f);
    EXPECT_FLOAT_EQ(tau_star(p, 50.0f), 0.0f);
}

TEST(NebulaAtmosphere, HgIsNormalised) {
    double sum = 0.0;
    const int n = 20000;
    for (int i = 0; i < n; ++i) {
        const float c = -1.0f + 2.0f * (i + 0.5f) / n;
        sum += hg(0.6f, c) * (2.0f / n) * 2.0 * M_PI;
    }
    EXPECT_NEAR(sum, 1.0, 1e-3);
}

TEST(NebulaAtmosphere, ConstantDensityTransmittanceIsClosedForm) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    // outward ray from r0 = 1000 straight out (mu = 1) for 50,000 GU
    const Segment s = reference_march(p, look, 1000.0f, 1.0f, 50000.0f, 2048);
    EXPECT_NEAR(s.transmittance.x, std::exp(-2.0e-5f * 50000.0f), 1e-3f);
}

TEST(NebulaAtmosphere, TransmittanceIsMonotonicAlongARay) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    float prev = 1.0f;
    for (float d : {1000.0f, 5000.0f, 20000.0f, 80000.0f}) {
        const float t = reference_march(p, look, 5000.0f, 0.3f, d, 1024).transmittance.x;
        EXPECT_LE(t, prev + 1e-6f);
        prev = t;
    }
}

TEST(NebulaAtmosphere, InwardRayStopsAtTheStar) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    // from r0 = 1100 straight in: only 1000 GU of cloud before the star surface
    const Segment s = reference_march(p, look, 1100.0f, -1.0f, INFINITY, 2048);
    EXPECT_NEAR(s.transmittance.x, std::exp(-2.0e-5f * 1000.0f), 1e-3f);
}

TEST(NebulaAtmosphere, FloorIntegratesFinitelyToTheFarPlane) {
    const auto p = constant(0.05f, 2.0e-5f);
    LookParams look;
    const Segment s = reference_march(p, look, 330000.0f, 1.0f, INFINITY, 4096);
    EXPECT_TRUE(std::isfinite(s.transmittance.x));
    EXPECT_GT(s.transmittance.x, 0.0f);
}

TEST(NebulaAtmosphere, ZeroRadiusIsFinite) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    const Segment s = reference_march(p, look, 0.0f, 0.0f, 10000.0f, 256);
    EXPECT_TRUE(std::isfinite(s.transmittance.x));
    EXPECT_TRUE(std::isfinite(s.inscatter.x));
}

TEST(NebulaAtmosphere, NearPlusFarEqualsWholeRay) {
    RadialProfile p;
    p.r = {0.0f, 60000.0f, 120000.0f, 240000.0f};
    p.nebula = {0.0f, 0.0f, 1.0f, 0.05f};
    p.k_sys = 2.0e-5f; p.star_radius = 2000.0f;
    p.cloud_rgb = glm::vec3(0.6f, 0.35f, 0.7f); p.star_rgb = glm::vec3(1.0f);
    LookParams look;
    const float r0 = 300000.0f, mu = -0.9f, near = 30000.0f;
    const Segment whole = reference_march(p, look, r0, mu, INFINITY, 8192);
    const Segment n = reference_march(p, look, r0, mu, near, 2048);
    // end point of the near segment, in the ray's plane
    const float x = std::sqrt(1.0f - mu * mu) * near, y = r0 + mu * near;
    const float r_end = std::sqrt(x * x + y * y);
    const float mu_end = (x * std::sqrt(1.0f - mu * mu) + y * mu) / r_end;
    const Segment f = reference_march(p, look, r_end, mu_end, INFINITY, 8192);
    const Segment c = compose(n, f);
    EXPECT_NEAR(c.transmittance.x, whole.transmittance.x, 2e-3f);
    EXPECT_NEAR(c.inscatter.x, whole.inscatter.x, 2e-2f * std::max(1e-3f, whole.inscatter.x));
}

TEST(NebulaAtmosphere, FiniteSegmentStopsAtHull) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    const Segment a = reference_march(p, look, 5000.0f, 1.0f, INFINITY, 4096);
    const Segment b = reference_march(p, look, 45000.0f, 1.0f, INFINITY, 4096);
    const Segment direct = reference_march(p, look, 5000.0f, 1.0f, 40000.0f, 4096);
    const Segment seg = finite(a, b);
    EXPECT_NEAR(seg.transmittance.x, direct.transmittance.x, 2e-3f);
}

TEST(NebulaAtmosphere, TableMatchesReferenceAtCellCentres) {
    const auto p = constant(0.5f, 2.0e-5f);
    LookParams look;
    const Table t = build_table(p, look);
    ASSERT_EQ(static_cast<int>(t.transmittance.size()), kTableR * kTableMu);
    const int i = 40, j = 100;
    const float r = radius_of_u(static_cast<float>(i) / (kTableR - 1), look.far_gu);
    const float mu = -1.0f + 2.0f * j / (kTableMu - 1);
    const Segment ref = reference_march(p, look, r, mu, INFINITY, 512);
    EXPECT_NEAR(t.transmittance[j * kTableR + i].x, ref.transmittance.x, 1e-5f);
}
```

- [ ] **Step 2: Build to verify failure**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile error — `renderer/nebula_atmosphere.h` not found.

- [ ] **Step 3: Implement** `native/src/renderer/include/renderer/nebula_atmosphere.h` with exactly the declarations in **Interfaces** (includes `<glm/glm.hpp>`, `<vector>`, `<cmath>`), and `native/src/renderer/nebula_atmosphere.cc`:

```cpp
// native/src/renderer/nebula_atmosphere.cc
// Star-centred atmosphere maths for the system-scale nebula
// (docs/superpowers/specs/2026-09-29-system-nebula-render-design.md).
// Pure CPU, no GL: the far-field table, the radial texels the shader reads,
// and a reference marcher the tests treat as truth.
#include "renderer/nebula_atmosphere.h"

#include <algorithm>
#include <cmath>

namespace renderer::atmosphere {

float density(const RadialProfile& p, float r) {
    if (p.r.empty()) return 0.0f;
    if (r <= p.r.front()) return p.nebula.front();
    for (size_t i = 1; i < p.r.size(); ++i) {
        if (r <= p.r[i]) {
            const float span = p.r[i] - p.r[i - 1];
            const float t = span > 0.0f ? (r - p.r[i - 1]) / span : 0.0f;
            return p.nebula[i - 1] + (p.nebula[i] - p.nebula[i - 1]) * t;
        }
    }
    return p.nebula.back();
}

float tau_star(const RadialProfile& p, float r) {
    if (r <= p.star_radius || p.k_sys <= 0.0f) return 0.0f;
    // exact trapezoid over the profile's own breakpoints
    std::vector<float> pts{p.star_radius, r};
    for (float x : p.r) if (x > p.star_radius && x < r) pts.push_back(x);
    std::sort(pts.begin(), pts.end());
    double sum = 0.0;
    for (size_t i = 1; i < pts.size(); ++i)
        sum += 0.5 * (density(p, pts[i - 1]) + density(p, pts[i])) * (pts[i] - pts[i - 1]);
    return static_cast<float>(p.k_sys * sum);
}

float hg(float g, float c) {
    const float g2 = g * g;
    const float denom = std::pow(std::max(1e-6f, 1.0f + g2 - 2.0f * g * c), 1.5f);
    return (1.0f - g2) / (4.0f * static_cast<float>(M_PI) * denom);
}

float radius_of_u(float u, float far_gu) { return far_gu * u * u; }
float u_of_radius(float r, float far_gu) {
    return std::sqrt(std::clamp(r / far_gu, 0.0f, 1.0f));
}

namespace {
// Distance along a ray (origin radius r0, direction cosine mu to the outward
// radial) to the sphere of radius R, the far exit (largest root), or -1.
float exit_distance(float r0, float mu, float R) {
    const float b = r0 * mu;
    const float c = r0 * r0 - R * R;
    const float disc = b * b - c;
    if (disc < 0.0f) return -1.0f;
    return -b + std::sqrt(disc);
}
// Nearest positive hit on the star sphere, or INFINITY.
float star_hit(float r0, float mu, float Rs) {
    const float b = r0 * mu;
    const float c = r0 * r0 - Rs * Rs;
    if (c <= 0.0f) return 0.0f;                 // already inside the star
    const float disc = b * b - c;
    if (disc < 0.0f) return INFINITY;
    const float t = -b - std::sqrt(disc);
    return t > 0.0f ? t : INFINITY;
}
}  // namespace

Segment reference_march(const RadialProfile& p, const LookParams& look,
                        float r0, float mu, float max_dist, int steps) {
    mu = std::clamp(mu, -1.0f, 1.0f);
    float len = std::min(max_dist, exit_distance(r0, mu, look.far_gu));
    len = std::min(len, star_hit(r0, mu, p.star_radius));
    Segment out{glm::vec3(1.0f), glm::vec3(0.0f)};
    if (!(len > 0.0f) || steps < 1) return out;
    const float dt = len / static_cast<float>(steps);
    const float sin0 = std::sqrt(std::max(0.0f, 1.0f - mu * mu));
    float transm = 1.0f;
    glm::vec3 lit(0.0f);
    for (int i = 0; i < steps; ++i) {
        const float t = (i + 0.5f) * dt;
        const float x = sin0 * t, y = r0 + mu * t;         // ray in its own plane
        const float r = std::sqrt(x * x + y * y);
        const float sigma = p.k_sys * density(p, r);
        if (sigma <= 0.0f) continue;
        // scattering angle: light travels outward (r-hat), toward the eye is -dir
        const float cos_theta = r > 1e-3f ? -(x * sin0 + y * mu) / r : 0.0f;
        const glm::vec3 light = look.scatter * hg(look.g, cos_theta) * p.star_rgb
                                * p.cloud_rgb * std::exp(-tau_star(p, r));
        const glm::vec3 emit = look.floor * p.cloud_rgb;
        const float ext = sigma * dt;
        lit += transm * (light + emit) * ext;
        transm *= std::exp(-ext);
    }
    out.transmittance = glm::vec3(transm);
    out.inscatter = lit;
    return out;
}

std::vector<glm::vec2> build_radial_texels(const RadialProfile& p, const LookParams& look) {
    std::vector<glm::vec2> out(kRadialTexels);
    for (int i = 0; i < kRadialTexels; ++i) {
        const float r = radius_of_u(static_cast<float>(i) / (kRadialTexels - 1), look.far_gu);
        out[i] = glm::vec2(density(p, r), tau_star(p, r));
    }
    return out;
}

Table build_table(const RadialProfile& p, const LookParams& look) {
    Table t;
    t.transmittance.resize(kTableR * kTableMu);
    t.inscatter.resize(kTableR * kTableMu);
    for (int j = 0; j < kTableMu; ++j) {
        const float mu = -1.0f + 2.0f * j / (kTableMu - 1);
        for (int i = 0; i < kTableR; ++i) {
            const float r = radius_of_u(static_cast<float>(i) / (kTableR - 1), look.far_gu);
            const Segment s = reference_march(p, look, r, mu, INFINITY, 512);
            t.transmittance[j * kTableR + i] = s.transmittance;
            t.inscatter[j * kTableR + i] = s.inscatter;
        }
    }
    return t;
}

Segment compose(const Segment& n, const Segment& f) {
    return {n.transmittance * f.transmittance, n.inscatter + n.transmittance * f.inscatter};
}

Segment finite(const Segment& a, const Segment& b) {
    const glm::vec3 T = a.transmittance / glm::max(b.transmittance, glm::vec3(1e-6f));
    return {glm::min(T, glm::vec3(1.0f)),
            glm::max(a.inscatter - T * b.inscatter, glm::vec3(0.0f))};
}

}  // namespace renderer::atmosphere
```

Note `tau_star` is O(rows) per call; `build_table` calls it inside `reference_march` 256×128×512 times. If the build exceeds ~2 s in the test run, precompute `build_radial_texels` once and have `reference_march` take an optional texel-lookup fast path — but only after measuring, and keep the reference path for the tests.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && ctest --test-dir build -R NebulaAtmosphere --output-on-failure`
Expected: 11/11 PASS. Report the `TableMatchesReferenceAtCellCentres` wall time.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/nebula_atmosphere.h native/src/renderer/nebula_atmosphere.cc native/src/renderer/CMakeLists.txt native/tests/renderer/nebula_atmosphere_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): star-centred nebula atmosphere table and reference marcher"
```

---

### Task 3: `SystemNebulaPass` — haze only (profile), developer-gated

**Files:**
- Create: `native/src/renderer/include/renderer/system_nebula_pass.h`, `native/src/renderer/system_nebula_pass.cc` — start from `cp` of `nebula_volumetric_pass.{h,cc}`, class renamed `SystemNebulaPass`, then the edits below.
- Create: `native/src/renderer/shaders/system_nebula.frag` (vertex shader: reuse `nebula_volumetric.vert`)
- Modify: `native/src/renderer/CMakeLists.txt` (`embed_shader(SHADER_SYSTEM_NEBULA_FS shaders/system_nebula.frag system_nebula_fs)`, add `system_nebula_pass.cc`), `native/src/renderer/include/renderer/pipeline.h` + `pipeline.cc` (`system_nebula_shader()` built from `nebula_volumetric_vs` + `system_nebula_fs`), `native/src/host/host_bindings.cc`
- Test: `native/tests/renderer/system_nebula_pass_test.cc` (headless GL, modelled on the existing renderer GL tests that construct a `Pipeline`)

**Interfaces:**
- Consumes: `renderer::atmosphere::*` (Task 2).
- Produces:
  - `void SystemNebulaPass::set_profile(const atmosphere::RadialProfile&, const atmosphere::LookParams&)` — builds the radial texels + table on the CPU and uploads them: radial → `GL_RG32F` 2D texture `kRadialTexels × 1` (LINEAR, CLAMP); table → two `GL_RGB16F` 2D textures `kTableR × kTableMu` (LINEAR, CLAMP). Sets `has_profile_`.
  - `void SystemNebulaPass::clear_profile()`.
  - `bool SystemNebulaPass::has_profile() const`.
  - `void SystemNebulaPass::set_star(const glm::vec3& render_pos)`.
  - `render(...)` — same signature as `NebulaVolumetricPass::render`; early-out when `!has_profile_ && volumes.empty()`.
  - Python bindings: `set_system_nebula_profile(dict | None)` with keys `r` (list), `nebula` (list), `k_sys`, `star_radius`, `cloud_rgb` (3-tuple), `star_rgb` (3-tuple), optional `g`, `floor`, `scatter`, `far_gu`; `set_system_nebula_star(tuple3)`; `system_nebula_has_profile() -> bool`.

- [ ] **Step 1: Write the failing headless GL test**

```cpp
// native/tests/renderer/system_nebula_pass_test.cc
// Uses the same headless GL context + Pipeline fixture as the other renderer
// GL tests in this directory (see how frame_test.cc creates them).
#include <gtest/gtest.h>
#include <renderer/system_nebula_pass.h>
#include <renderer/nebula_atmosphere.h>

TEST(SystemNebulaPass, ProfileUploadAndRenderDoNotError) {
    // fixture: headless context + Pipeline (copy the setup helper used by frame_test.cc)
    renderer::SystemNebulaPass pass;
    renderer::atmosphere::RadialProfile p;
    p.r = {0.0f, 60000.0f, 120000.0f, 240000.0f};
    p.nebula = {0.0f, 0.0f, 1.0f, 0.05f};
    p.k_sys = 2.0e-5f; p.star_radius = 2000.0f;
    p.cloud_rgb = glm::vec3(0.6f, 0.35f, 0.7f); p.star_rgb = glm::vec3(1.0f);
    pass.set_profile(p, renderer::atmosphere::LookParams{});
    EXPECT_TRUE(pass.has_profile());
    pass.clear_profile();
    EXPECT_FALSE(pass.has_profile());
}
```

Extend it with a render into an HDR target of 64×64 with the camera at (0, 300000, 0) render-relative to a star at the origin, looking at the star, and assert: no `glGetError`, the shader compiled (the pipeline would have thrown), and the centre pixel's alpha is in (0, 1). Follow the exact fixture pattern of the existing GL tests in `native/tests/renderer/` for context, target and readback.

- [ ] **Step 2: Build to verify failure** — `cmake --build build -j 2>&1 | tail -5` → missing header.

- [ ] **Step 3: Write `shaders/system_nebula.frag`** (haze only; clumps come in Task 4):

```glsl
#version 410 core
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_depth;
uniform sampler2D u_radial;     // RG: density(r), tau_star(r); u = sqrt(r/far)
uniform sampler2D u_table_T;    // far-field transmittance [u(r), (mu+1)/2]
uniform sampler2D u_table_S;    // far-field inscatter
uniform mat4  u_inv_view_proj;
uniform vec3  u_eye;
uniform vec3  u_star;           // render-space star centre
uniform float u_far_gu;
uniform float u_k_sys;
uniform vec3  u_cloud_rgb;
uniform vec3  u_star_rgb;
uniform float u_g;
uniform float u_floor;
uniform float u_scatter;
uniform float u_near_range;
uniform int   u_steps;
uniform float u_lane_size;
uniform float u_lane_contrast;
uniform vec3  u_noise_origin;
uniform int   u_has_profile;
// temporal (same contract as nebula_volumetric.frag)
uniform sampler2D u_prev;
uniform mat4  u_prev_view_proj;
uniform float u_temporal_weight;
uniform vec2  u_half_texel;
uniform float u_dither_amount;
uniform vec2  u_jitter;

// --- fbm copy of backdrop.frag / nebula_density.py (keep in sync) ---
float hash13(vec3 p3){ p3=fract(p3*0.1031); p3+=dot(p3,p3.zyx+31.32); return fract((p3.x+p3.y)*p3.z); }
float vnoise(vec3 p){
    vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    float n000=hash13(i),               n100=hash13(i+vec3(1,0,0));
    float n010=hash13(i+vec3(0,1,0)),   n110=hash13(i+vec3(1,1,0));
    float n001=hash13(i+vec3(0,0,1)),   n101=hash13(i+vec3(1,0,1));
    float n011=hash13(i+vec3(0,1,1)),   n111=hash13(i+vec3(1,1,1));
    return mix(mix(mix(n000,n100,f.x),mix(n010,n110,f.x),f.y),
               mix(mix(n001,n101,f.x),mix(n011,n111,f.x),f.y), f.z);
}
float fbm(vec3 p){ float a=0.5,s=0.0; for(int k=0;k<5;k++){ s+=a*vnoise(p); p*=2.02; a*=0.5; } return s; }

const float PI = 3.14159265;
float hg(float g, float c){ float g2=g*g; return (1.0-g2)/(4.0*PI*pow(max(1e-6,1.0+g2-2.0*g*c),1.5)); }
vec2 radial(float r){ return texture(u_radial, vec2(sqrt(clamp(r/u_far_gu,0.0,1.0)), 0.5)).rg; }
float lanes(vec3 p){
    float n = fbm((p+u_noise_origin)/u_lane_size);          // ~0.5 mean
    return max(0.0, mix(1.0, 2.0*n, u_lane_contrast));
}
float sky_lanes(vec3 dir){ return max(0.0, mix(1.0, 2.0*fbm(dir*6.0+13.0), u_lane_contrast)); }
vec3 world_from_depth(vec2 uv, float d){ vec4 c=vec4(uv*2.0-1.0, d*2.0-1.0, 1.0); vec4 w=u_inv_view_proj*c; return w.xyz/w.w; }
float dither(vec2 fc){ return fract(sin(dot(fc, vec2(12.9898, 78.233))) * 43758.5453); }

// far-field lookup at a point: returns T in .rgb of first, S in second
void far_at(vec3 p, vec3 dir, out vec3 T, out vec3 S){
    vec3 rel = p - u_star; float r = length(rel);
    float mu = r > 1e-3 ? dot(dir, rel/r) : 0.0;
    vec2 uv = vec2(sqrt(clamp(r/u_far_gu,0.0,1.0)), mu*0.5+0.5);
    T = texture(u_table_T, uv).rgb; S = texture(u_table_S, uv).rgb;
}

void main(){
    float dsc = texture(u_depth, v_uv).r;
    vec3 wp = world_from_depth(v_uv, dsc);
    float scene_dist = (dsc >= 1.0) ? 1e20 : length(wp - u_eye);
    vec3 dir = normalize(world_from_depth(v_uv, 0.5) - u_eye);

    vec3 transm = vec3(1.0); vec3 lit = vec3(0.0);
    if (u_has_profile == 1) {
        float near_end = min(scene_dist, u_near_range);
        // geometric steps: t_i = near_end * ((1+q)^i - 1)/((1+q)^N - 1)
        float q = 0.06; float denom = pow(1.0+q, float(u_steps)) - 1.0;
        float jit = u_dither_amount * dither(gl_FragCoord.xy + u_jitter);
        float t_prev = 0.0;
        for (int i = 1; i <= u_steps; ++i) {
            float t = near_end * (pow(1.0+q, float(i) - 1.0 + jit) - 1.0) / denom;
            t = min(t, near_end);
            float dt = t - t_prev; t_prev = t;
            if (dt <= 0.0) continue;
            vec3 p = u_eye + dir * (t - 0.5*dt);
            vec3 rel = p - u_star; float r = length(rel);
            vec2 rd = radial(r);
            float sigma = u_k_sys * rd.x * lanes(p);
            if (sigma <= 0.0) continue;
            float cos_t = r > 1e-3 ? -dot(dir, rel/r) : 0.0;
            vec3 light = u_scatter * hg(u_g, cos_t) * u_star_rgb * u_cloud_rgb * exp(-rd.y);
            vec3 emit  = u_floor * u_cloud_rgb;
            float ext = sigma * dt;
            lit += transm * (light + emit) * ext;
            transm *= exp(-ext);
        }
        vec3 p_end = u_eye + dir * near_end;
        vec3 Ta, Sa; far_at(p_end, dir, Ta, Sa);
        if (scene_dist <= u_near_range) {
            // a hull inside the near field: nothing behind it
        } else if (scene_dist < 1e19) {
            vec3 Tb, Sb; far_at(u_eye + dir*scene_dist, dir, Tb, Sb);
            vec3 T = min(Ta / max(Tb, vec3(1e-6)), vec3(1.0));
            vec3 S = max(Sa - T*Sb, vec3(0.0));
            lit += transm * S * sky_lanes(dir); transm *= T;
        } else {
            lit += transm * Sa * sky_lanes(dir); transm *= Ta;
        }
    }
    float alpha = 1.0 - dot(transm, vec3(1.0/3.0));
    vec4 cur = vec4(lit, alpha);   // premultiplied
    // temporal blend: copy the block from nebula_volumetric.frag verbatim
    // (reproject the midpoint u_eye + dir * 0.5*min(scene_dist,u_near_range)).
    frag = cur;
}
```

Paste the temporal-reprojection block from `nebula_volumetric.frag` (the `if(u_temporal_weight > 0.0){ ... }` section) before `frag = cur;`, anchoring at `u_eye + dir * 0.5 * min(scene_dist, u_near_range)` instead of the sphere midpoint.

- [ ] **Step 4: Implement the pass** — after `cp`:
  1. Rename the class and guards; add members: `GLuint radial_tex_ = 0, table_T_ = 0, table_S_ = 0; bool has_profile_ = false; atmosphere::RadialProfile profile_; atmosphere::LookParams look_; glm::vec3 star_{0.0f};` and the four methods from **Interfaces** (`set_profile` builds via `atmosphere::build_radial_texels` / `build_table` and uploads with `glTexImage2D`; `clear_profile` deletes the three textures and clears the flag; destructor deletes them).
  2. In `render`: replace the early-out with `if (!has_profile_ && volumes.empty()) return;`; drop the sphere flattening (Task 4 restores clumps); swap `pipeline.nebula_volumetric_shader()` for `pipeline.system_nebula_shader()`; replace the uniform block with the shader's uniforms above: `u_star` = `star_`, `u_far_gu` = `look_.far_gu`, `u_k_sys`, `u_cloud_rgb`, `u_star_rgb`, `u_g`, `u_floor`, `u_scatter` from `profile_`/`look_`, `u_near_range` 30000, `u_steps` 64, `u_lane_size` 15000, `u_lane_contrast` 0.7, `u_has_profile`; bind `u_radial` (unit 2), `u_table_T` (unit 3), `u_table_S` (unit 4) alongside `u_depth` (0) and `u_prev` (1). Keep the quarter-res target, ping-pong, temporal and upsample code unchanged. Name the dials as `constexpr` at file top (`kNearRangeGu = 30000.0f`, `kSteps = 64`, `kLaneSizeGu = 15000.0f`, `kLaneContrast = 0.7f`).
  3. `host_bindings.cc`: global `std::unique_ptr<renderer::SystemNebulaPass> g_system_nebula_pass;` created/reset beside `g_nebula_volumetric_pass`; bindings from **Interfaces**; in `frame()` replace the nebula block's condition with:

```cpp
        const bool sys_neb = dauntless_volumetric_nebulae::enabled()
            && dauntless::is_developer_mode() && g_system_nebula_pass
            && (g_system_nebula_pass->has_profile() || !g_nebulae.empty());
        if (sys_neb) {
            DAUNTLESS_FRAME_SCOPE("space.system_nebula");
            const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());
            g_system_nebula_pass->render(cam, *g_pipeline, g_nebulae, g_lighting,
                target.color_texture(), target.depth_texture(), inv_vp, cam.eye,
                static_cast<float>(now), g_world.render_origin());
        } else if (!g_nebulae.empty()) {
            // ... the existing block, unchanged ...
        }
```

  Keep the wake draw where it is (inside the existing branch). Reset the new pass's history wherever `g_nebula_volumetric_pass->reset_history()` is called.

- [ ] **Step 5: Build and run**

Run: `cmake --build build -j && ctest --test-dir build -R "SystemNebulaPass|NebulaAtmosphere" --output-on-failure`
Expected: PASS. Then `uv run pytest tests -q -k "renderer or binding"` (the renderer façade's `_REQUIRED_BINDINGS` must not break — do not add the new bindings to it yet; Task 5 does).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/system_nebula_pass.h native/src/renderer/system_nebula_pass.cc native/src/renderer/shaders/system_nebula.frag native/src/renderer/CMakeLists.txt native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/src/host/host_bindings.cc native/tests/renderer/system_nebula_pass_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): system-scale nebula pass (profile haze), developer-gated"
```

---

### Task 4: Clumps as density bumps with their own dials

**Files:**
- Modify: `native/src/renderer/shaders/system_nebula.frag`, `native/src/renderer/system_nebula_pass.cc`
- Test: `native/tests/renderer/system_nebula_pass_test.cc` (append), `tests/unit/test_nebula_fbm_parity.py` (new)

**Interfaces:**
- Consumes: `NebulaVolume` (`spheres`, `rgb`, `visibility`, `fbm`, `seed`) as today.
- Produces: shader uniforms `u_clump_count` (≤ 8), `u_clump_sphere[8]` (vec4), `u_clump_rgb[8]`, `u_clump_fbm[8]`, `u_clump_seed[8]`, `u_clump_ext[8]` (= 1/visibility per GU); one sphere per clump (each volume's first sphere; volumes beyond 8 dropped).

- [ ] **Step 1: Failing tests**
  - Append to the GL test: `ClumpsWithoutProfileRender` — no `set_profile`, one `NebulaVolume` sphere at the camera's look point, render; centre alpha > 0; no GL error.
  - `tests/unit/test_nebula_fbm_parity.py`:

```python
"""The clump fbm in system_nebula.frag must stay the function gameplay reads
(engine/appc/nebula_density.py mirrors nebula_volumetric.frag)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "native" / "src" / "renderer" / "shaders"


def _block(text):
    m = re.search(r"float hash13.*?float fbm\(vec3 p\)\{.*?\}", text, re.S)
    assert m, "fbm block not found"
    return re.sub(r"\s+", " ", m.group(0))


def test_system_nebula_fbm_matches_the_volumetric_fbm():
    a = _block((SHADERS / "nebula_volumetric.frag").read_text())
    b = _block((SHADERS / "system_nebula.frag").read_text())
    assert a == b
```

Run: `uv run pytest tests/unit/test_nebula_fbm_parity.py -v` → PASS already (Task 3 copied the block); the GL clump test fails.

- [ ] **Step 2: Implement** — in the shader add, inside the near-field loop, the clump density per clump `i`:

```glsl
float clump_density(int i, vec3 p){
    vec4 s = u_clump_sphere[i]; if (s.w <= 0.0) return 0.0;
    float d = length(p - s.xyz);
    float tb = clamp((s.w - d)/(0.3*s.w), 0.0, 1.0); float b = tb*tb*(3.0-2.0*tb);
    if (b <= 0.0) return 0.0;
    vec3 w = p + u_noise_origin; vec3 f = u_clump_fbm[i]; vec3 sd = u_clump_seed[i];
    float n = fbm(vec3(w.x*f.x+sd.x, w.y*f.x+sd.y, w.z*f.x+sd.z));
    return b * clamp(n*f.y - f.z, 0.0, 1.0);
}
```

and in the loop: `float sig_c = 0.0; vec3 col_c = vec3(0.0); for (int i=0;i<u_clump_count;++i){ float dc=clump_density(i,p)*u_clump_ext[i]; sig_c+=dc; col_c+=dc*u_clump_rgb[i]; }` — total `sigma = haze + sig_c`, with the lit colour weighted: haze uses `u_cloud_rgb`, clumps use `col_c/sig_c`. Run the loop when `u_has_profile == 1 || u_clump_count > 0`; when there is no profile, `near_end = min(scene_dist, u_near_range)` still applies and the far-field lookups are skipped. In the pass, fill the clump uniforms from `volumes` (render-space sphere centres as delivered; `u_clump_ext = 1/max(visibility, 1)`).

- [ ] **Step 3: Build, run** `ctest --test-dir build -R SystemNebulaPass --output-on-failure` and the parity test → PASS.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/system_nebula.frag native/src/renderer/system_nebula_pass.cc native/tests/renderer/system_nebula_pass_test.cc tests/unit/test_nebula_fbm_parity.py
git commit -m "feat(renderer): local MetaNebulae as density bumps in the system nebula pass"
```

---

### Task 5: Python wiring — push the profile on system change, the star each frame; remove the spike

**Files:**
- Modify: `engine/host_loop.py` (`_push_environment_feeds`), `engine/renderer.py` (façade wrappers + `_REQUIRED_BINDINGS`)
- Delete: `engine/systems/profile_render.py`, `tests/unit/test_profile_render.py`; remove the spike hook in `_push_environment_feeds` and its host test `test_dev_mode_off_leaves_the_nebula_feed_untouched_by_a_player` in `tests/host/test_render_space_feeds.py` (replace with the byte-identity test below)
- Test: `tests/unit/test_system_nebula_feed.py`

**Interfaces:**
- Consumes: `profile.locate`, `profile.k_sys`, `resolve.map_of`, bindings from Task 3.
- Produces: `host_loop._push_system_nebula(r, player, suns, warp_streaking) -> None`; module global `_system_nebula_pushed_for` (map system name or None).

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_system_nebula_feed.py
from engine import host_loop
from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap


class _R:
    def __init__(self):
        self.profiles = []
        self.stars = []

    def set_system_nebula_profile(self, d):
        self.profiles.append(d)

    def set_system_nebula_star(self, pos):
        self.stars.append(pos)


def _map(name="Vesuvi"):
    return SystemMap(system=name,
                     bodies=[Body("Star", "Star", 2000.0, (0.0, 0.0, 0.0))],
                     regions=[Region("R", (100000.0, 0.0, 0.0), 1000.0)],
                     profile=P.Profile(rows=[P.ProfileRow(0.0, nebula=1.0),
                                             P.ProfileRow(200000.0, nebula=1.0)],
                                       color=(0.6, 0.35, 0.72)))


def _patch(monkeypatch, m):
    from engine.systems import frames, resolve
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("system", m.system), 1.0, 2.0, 3.0))
    monkeypatch.setattr(resolve, "map_of", lambda name: m if name == m.system else None)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", None)


def test_profile_repushed_only_on_system_change(monkeypatch):
    m = _map()
    _patch(monkeypatch, m)
    r = _R()
    suns = [{"position": (5.0, 6.0, 7.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 1
    d = r.profiles[0]
    assert d["r"] == [0.0, 200000.0] and d["nebula"] == [1.0, 1.0]
    assert d["k_sys"] == P.k_sys(m) and d["star_radius"] == 2000.0
    assert r.stars[-1] == (5.0, 6.0, 7.0)
    m2 = _map("Belaruz")
    _patch(monkeypatch, m2)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", "Vesuvi")
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2


def test_unmapped_set_clears_profile(monkeypatch):
    from engine.systems import frames
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", "Vesuvi")
    r = _R()
    host_loop._push_system_nebula(r, object(), [], False)
    assert r.profiles == [None]


def test_warp_tunnel_clears_profile(monkeypatch):
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", "Vesuvi")
    r = _R()
    host_loop._push_system_nebula(r, object(), [], True)
    assert r.profiles == [None]
```

Run: `uv run pytest tests/unit/test_system_nebula_feed.py -v` → FAIL (`_push_system_nebula` missing).

- [ ] **Step 2: Implement** in `engine/host_loop.py`:

```python
_system_nebula_pushed_for = None   # system name whose profile the pass holds


def _push_system_nebula(r, player, suns, warp_streaking) -> None:
    """Feed the system-scale nebula pass: the profile once per system (the
    pass builds its far-field table from it), the star's render position every
    frame. Cleared in the warp tunnel and outside mapped systems."""
    global _system_nebula_pushed_for
    from engine.systems import frames, resolve
    from engine.systems import profile as _profile
    m = None
    if player is not None and not warp_streaking:
        pos = frames.system_position(player)
        if pos is not None and pos[0][0] == "system":
            m = resolve.map_of(pos[0][1])
    if m is None or m.profile is None:
        if _system_nebula_pushed_for is not None:
            r.set_system_nebula_profile(None)
            _system_nebula_pushed_for = None
        return
    if _system_nebula_pushed_for != m.system:
        star = next(b for b in m.bodies if b.orbits is None)
        colour = m.profile.color or (0.0, 0.0, 0.0)
        star_rgb = tuple(star.appearance.color) if star.appearance.color else (1.0, 1.0, 1.0)
        from engine.cameras import SCENE_FAR_GU
        r.set_system_nebula_profile({
            "r": [row.distance_gu for row in m.profile.rows],
            "nebula": [row.nebula for row in m.profile.rows],
            "k_sys": _profile.k_sys(m),
            "star_radius": star.radius_gu,
            "cloud_rgb": tuple(colour),
            "star_rgb": star_rgb,
            "far_gu": SCENE_FAR_GU,
        })
        _system_nebula_pushed_for = m.system
    if suns:
        r.set_system_nebula_star(tuple(suns[0]["position"]))
```

In `_push_environment_feeds`: delete the `synthetic_volume` block (restore `nebulae = [] if warp_streaking else _aggregate_nebulae(active_set)` → `r.set_nebulae(...)` exactly as before the spike), and after `r.set_suns(suns)` add `_push_system_nebula(r, player, suns, warp_streaking)`. Note the warp-tunnel test expects a clear when a profile was held: with `warp_streaking=True`, `m` stays None and the clear branch runs.

In `engine/renderer.py` add wrappers `set_system_nebula_profile(d)`, `set_system_nebula_star(pos)` (thin `_h.` calls, docstrings citing the spec) and add both names to `_REQUIRED_BINDINGS`. Add them to any renderer test double that lists the real surface (grep for `set_dust_profile` in tests to find them). Reset `_system_nebula_pushed_for = None` wherever `_reset_sensor_state` resets `_radiation_driver` (mission swap) — the native pass keeps the old table otherwise.

- [ ] **Step 3: Delete the spike** — `git rm engine/systems/profile_render.py tests/unit/test_profile_render.py`; replace the removed host test with one asserting `set_nebulae` receives exactly `_render_nebulae(_aggregate_nebulae(...))` whether or not developer mode is on (production byte-identity of the faithful/volumetric feed).

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_system_nebula_feed.py tests/host/test_render_space_feeds.py -q` and `uv run pytest tests -q -k "environment_feeds or nebula or renderer"` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py engine/renderer.py tests/unit/test_system_nebula_feed.py tests/host/test_render_space_feeds.py
git commit -m "feat(nebula): feed the system nebula pass; remove the rejected spike"
```

---

### Task 6: Veil the billboard lens flare

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h` (`LensFlareDescriptor` gains `float brightness = 1.0f;`), `native/src/renderer/lens_flare_pass.cc` (set `u_brightness` per flare from `f.brightness` inside the loop, not once before it), `native/src/host/host_bindings.cc` (`set_lens_flares` reads optional `"brightness"`, default 1.0), `engine/host_loop.py` (`_push_environment_feeds`)
- Test: `native/tests/renderer/lens_flare_brightness_test.cc` (or append to an existing lens-flare test file if one exists), `tests/unit/test_flare_veil.py`

**Interfaces:**
- Consumes: `profile.star_transmittance(obj)` (Task 1).
- Produces: `host_loop._veil_flares(flares, player) -> list` — returns copies with `"brightness"` = `star_transmittance(player)` when the setting-on + developer condition holds, else unchanged.

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_flare_veil.py
from engine import dev_mode, host_loop
from engine.systems import profile as P


def test_flares_take_the_star_transmittance_under_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(P, "star_transmittance", lambda obj: 0.2)
    out = host_loop._veil_flares([{"source_world_pos": (1.0, 2.0, 3.0), "elements": []}], object())
    assert out[0]["brightness"] == 0.2


def test_flares_untouched_without_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    flares = [{"source_world_pos": (1.0, 2.0, 3.0), "elements": []}]
    assert host_loop._veil_flares(flares, object()) == flares
    assert "brightness" not in flares[0]
```

C++: a test that a descriptor with `brightness = 0.0f` draws nothing visible (readback zero) while `1.0f` draws — follow the existing lens-flare GL test pattern; if no GL lens-flare test exists, assert only that `set_lens_flares` accepts and stores the key (host binding test pattern in `tests/host/`).

- [ ] **Step 2: Implement** — C++ as listed. Python:

```python
def _veil_flares(flares, player):
    """Billboard flares see no fog (their visibility is one depth read), so
    under the system nebula pass they take the exact eye->star transmittance
    (spec 2026-09-29, "The sun and its flares")."""
    if not dev_mode.is_enabled() or player is None or not flares:
        return flares
    from engine.systems import profile as _profile
    t = _profile.star_transmittance(player)
    return [dict(f, brightness=t) for f in flares]
```

and in `_push_environment_feeds` pass the flare list through `_veil_flares(lens_flares, player)` before `r.set_lens_flares`.

- [ ] **Step 3: Build and run** the C++ test and `uv run pytest tests/unit/test_flare_veil.py -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/lens_flare_pass.cc native/src/host/host_bindings.cc engine/host_loop.py tests/unit/test_flare_veil.py
git commit -m "feat(flare): billboard lens flare veiled by the nebula's star transmittance"
```

---

### Task 7: Live-tunable dials under `--developer`

**Files:**
- Modify: `native/src/renderer/include/renderer/system_nebula_pass.h`, `system_nebula_pass.cc` (the file-top constants become defaults of a `struct Dials { float veil_scale=1, lane_size=15000, lane_contrast=0.7, g=0.6, floor=0.03, near_range=30000; }` member with `set_dials`), `native/src/host/host_bindings.cc` (`system_nebula_set_dials(dict)` / `system_nebula_dials() -> dict`), `engine/renderer.py`
- Create: `engine/dev_nebula_dials.py`
- Test: `tests/unit/test_dev_nebula_dials.py`

**Interfaces:**
- Produces: `dev_nebula_dials.register()` — registers developer keybindings (via `dev_mode.register_dev_keybinding`, see `engine/dev_mode.py` for its signature) that step `floor` (×/÷ 1.25), `g` (±0.05, clamped 0–0.95), `lane_contrast` (±0.1, 0–1) and `near_range` (×/÷ 1.5), each call pushing the whole dial dict with `r.system_nebula_set_dials` and printing `[nebula dials] {...}` so Mark can report values. `floor`/`g` changes need the far-field table rebuilt: `set_dials` on the pass re-runs `set_profile` with the new `LookParams` when `g` or `floor` changed.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_dev_nebula_dials.py
from engine import dev_nebula_dials as D


def test_step_functions_clamp_and_scale():
    d = dict(D.DEFAULTS)
    d = D.step(d, "g", +1)
    assert abs(d["g"] - 0.65) < 1e-9
    for _ in range(40):
        d = D.step(d, "g", +1)
    assert d["g"] <= 0.95
    d = D.step(dict(D.DEFAULTS), "floor", -1)
    assert abs(d["floor"] - 0.03 / 1.25) < 1e-9


def test_defaults_match_the_spec():
    assert D.DEFAULTS == {"floor": 0.03, "g": 0.6, "lane_contrast": 0.7,
                          "lane_size": 15000.0, "near_range": 30000.0}
```

- [ ] **Step 2: Implement** `engine/dev_nebula_dials.py` with `DEFAULTS`, a pure `step(dials, name, direction) -> dict` (rules above), and `register()` wiring keys (choose four unused key pairs; check `engine/dev_keybindings.py` / `dev_mode.register_dev_keybinding` for what is free and list them in the module docstring). Call `register()` from wherever other dev keybindings are registered at boot, only under `dev_mode.is_enabled()`. C++: `Dials` struct + binding; the shader reads `u_floor`, `u_g`, `u_lane_contrast`, `u_lane_size`, `u_near_range` from `dials_` instead of the constants.

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_dev_nebula_dials.py -q`; `cmake --build build -j && ctest --test-dir build -R SystemNebulaPass --output-on-failure` → PASS.

- [ ] **Step 4: Commit**

```bash
git add engine/dev_nebula_dials.py tests/unit/test_dev_nebula_dials.py native/src/renderer/include/renderer/system_nebula_pass.h native/src/renderer/system_nebula_pass.cc native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(nebula): developer keys to live-tune the system nebula dials"
```

---

### Task 8: Docs, spec correction, gate

**Files:**
- Modify: `docs/superpowers/specs/2026-09-29-system-nebula-render-design.md` — "What is removed" becomes: *the spike now; `nebula_volumetric_pass` only after Mark approves the new pass live (production keeps it until then)*.
- Modify: `CLAUDE.md` — extend the "Radial system profile" row's spike sentence to name `system_nebula_pass` (developer-only, awaiting live check; dials on developer keys). Keep the row under the 1,200-char budget enforced by `tests/docs/test_doc_consistency.py`.

- [ ] **Step 1:** Edit both files.
- [ ] **Step 2:** Run `scripts/check_tests.sh` (long; generous timeout). Exit 0 required. Any failure not in `tests/known_failures.txt` is this branch's to fix.
- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-29-system-nebula-render-design.md CLAUDE.md
git commit -m "docs: system nebula pass is developer-only; old pass retires after live approval"
```

- [ ] **Step 4:** Report to Mark for the live check (spec "Testing → Live"): run with `--developer`, fly Vesuvi from Haven inward; report dial values via the developer keys.
