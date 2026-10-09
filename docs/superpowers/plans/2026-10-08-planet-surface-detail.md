# Planet Surface Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Procedural high-frequency surface detail on the planet you are near — relief, crisp coasts, glint, ice cracks, gas turbulence — baked into a budgeted toroidal clipmap and sampled by a `PLANET_SURFACE` variant of `opaque.frag`, over BC's own colour maps.

**Architecture:** A per-NIF `surface` entry in `atmospheres.json` resolves in Python and is pushed to `Instance::Surface`. Each frame a top-level `planet_detail` pass picks one target planet and bakes clipmap strips under a fixed cost budget (GL-free scheduler + GL atlas layer + `planet_bake.frag`). The target planet's sphere-LOD draw uses a new `planet_` program (opaque.frag compiled with `#define PLANET_SURFACE`) that samples the atlas; every other draw is byte-identical to today.

**Tech Stack:** C++17, OpenGL 4.1 core / GLSL 410, glm, gtest, pybind11; Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-planet-surface-detail-design.md` — read it before any task.

## Global Constraints

- Work ONLY in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/planet-surface-detail` on branch `feat/planet-surface-detail`. Never commit to `main`.
- ⛔ Banned git (shared checkout rules, CLAUDE.md): `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths. To mutate a file temporarily: `cp f /tmp/bak` … `cp /tmp/bak f` … `diff f /tmp/bak`.
- Build: `cmake --build build -j` (the tree is configured Debug; never reconfigure CMAKE_BUILD_TYPE; never run cmake from `native/`). Shader edits are embedded at build time — rebuild after every `.frag` change.
- Python tests: `uv run pytest <path> -q`. C++ renderer tests: `./build/native/tests/renderer/renderer_tests --gtest_filter=<Suite>.*`.
- ⛔ When `opaque.frag` changes, run the **FULL** `renderer_tests` binary, not a filter — a disabled-path change once broke 16 tests outside the canary (memory `project_opaque_frag_sampler3d_miscompile`). No `sampler3D`, no `samplerCube`, no texture arrays — `sampler2D` only. Every new sampler gets a free unit (the atlas is **unit 12**) on every program that compiles it.
- In `opaque.frag`: derivatives (`dFdx`/`dFdy`) only in the existing unconditional sphere-map derivative block region, never inside a branch, never after a `discard` that follows them. All new code inside `#ifdef PLANET_SURFACE` so `opaque_`, `skinned_`, `minor_`, `impostor_` compile from identical text.
- NaN feeds bloom (black squares): every `normalize` guarded, outputs finite.
- Render-only: no gameplay/SDK behaviour change. Never capture a path at import (`engine/paths.py` rule). Units are GU (never `_m`).
- Default constants (spec): `ts0 = 0.1` GU, level size 1024, band rows 1026, max levels 5, re-anchor at `0.5·R`, budget `65536 × 8` cost units/frame, cold-start ×2, transition band 10%, detail fade `smoothstep(2, 8, px per BC texel)`, hysteresis 10%, gas period 40 s, water f0 0.02, `ocean_tolerance` default 0.15.
- Gate before declaring the branch done: `scripts/check_tests.sh` (pytest + ctest + in-process gtest, diffed against `tests/known_failures.txt`, which has no failure entries — keep it that way).

## Review Focus

1. **A planet that is not the target must render byte-identically** (other planets in view, ships, the bridge viewscreen of a different region) — Task 7 pins it with a pixel-equality test against a draw through `opaque_`.
2. **Moving between planets / warping / mission swap must never draw stale detail onto the wrong planet** — Task 8 pins reset on target change and on target instance destruction.
3. **Pole and seam fragments** (nadir directly over a pole; camera over BC's u-seam) must stay finite and seam-free — Task 3 (anchor at a pole) and Task 7 (finite probe at pole/seam).
4. **Tiny moons** (R = 140 GU) must not get a clipmap that extends past the horizon — Task 4 (`level_count_for`) and Task 8 (target with 2 levels renders).
5. **Toggle off / catalogue malformed** must leave the atmosphere intact and give exactly today's render — Task 1 (malformed `surface` keeps atmosphere) and Task 5 (toggle off pushes `None`).

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/planets/surface.py` (new) | `Surface` dataclass, `parse_surface`, `resolve_surface_key`, `resolve_surface`, `to_binding`, live registry |
| `engine/planets/atmosphere.py` (modify) | accept `surface` as a known field; doc the new `atmosphere:false` rule |
| `native/assets/planets/atmospheres.json` (modify) | seed `surface` for all 31 stems |
| `engine/planet_surface.py` (new) | dev toggle |
| `engine/host_loop.py` (modify) | `_apply_planet_surface` hook + registry clears |
| `native/src/scenegraph/include/scenegraph/instance.h`, `world.{h,cc}` (modify) | `Instance::Surface`, `World::set_surface` |
| `native/src/host/host_bindings.cc` (modify) | `set_instance_surface`, tuning/debug bindings, frame() integration |
| `native/src/renderer/planet_detail_noise.{h,cc}` (new, GL-free) | pcg3d, analytic noise, type table, field functions, gnomonic anchor |
| `native/src/renderer/planet_clipmap_schedule.{h,cc}` (new, GL-free) | rects, strips, wrap split, guard rows, cost budget, level count, re-anchor |
| `native/src/renderer/shaders/planet_bake.frag` (new) | bakes one strip piece; GLSL twin of `planet_detail_noise` |
| `native/src/renderer/planet_clipmap_atlas.{h,cc}` (new) | atlas texture + bake program; draws `BakeRect`s |
| `native/src/renderer/planet_detail_pass.{h,cc}` (new) | target pick, anchor, schedule→atlas, sampling uniforms |
| `native/src/renderer/shaders/opaque.frag` (modify) | `#ifdef PLANET_SURFACE` sampling + shading |
| `native/src/renderer/pipeline.{h,cc}` (modify) | `planet_` program |
| `native/src/renderer/frame.{h,cc}` (modify) | target draw through `planet_` |
| `engine/planets/surface_dials.py` (new), `engine/ui/developer_options_panel.py` (modify) | dial group, toggles, reload |
| tests: `tests/unit/test_planet_surface_catalogue.py`, `tests/unit/test_planet_surface_wiring.py`, `tests/unit/test_planet_surface_dials.py`, `tests/host/test_instance_surface_binding.py`, `native/tests/renderer/planet_detail_noise_test.cc`, `planet_clipmap_schedule_test.cc`, `planet_clipmap_atlas_test.cc`, `planet_surface_draw_test.cc`, `planet_detail_pass_test.cc`, `planet_detail_bench_test.cc` |

---

### Task 1: `surface` catalogue parsing (Python)

**Files:**
- Create: `engine/planets/surface.py`
- Modify: `engine/planets/atmosphere.py` (`_FIELDS`, module docstring)
- Test: `tests/unit/test_planet_surface_catalogue.py`

**Interfaces:**
- Consumes: `engine.planets.atmosphere.load()`, `nif_stem()`, `srgb_hex_to_linear()`, `catalogue_path()`, `_warn` pattern.
- Produces:
  - `TYPE_CODES: dict[str, int] = {"none": 0, "rocky": 1, "desert": 2, "ice": 3, "gas": 4, "ocean": 5}`
  - `@dataclass(frozen=True) class Surface: type: str; ocean: tuple | None; ocean_tolerance: float = 0.15; strength: float = 1.0; albedo: float = 1.0; scale: float = 1.0; seed: int = 0`
  - `parse_surface(obj: dict, seed: int) -> Surface | None` (raises `ValueError` on malformed; `type == "none"` → `None`)
  - `resolve_surface_key(set_name, obj_name, nif_path) -> str | None`
  - `resolve_surface(set_name, obj_name, nif_path) -> Surface | None`
  - `to_binding(s: Surface | None) -> tuple | None` = `(type_code, ocean_rgb, has_ocean, ocean_tolerance, strength, albedo, scale, seed)`; `ocean_rgb` is `(0.0, 0.0, 0.0)` when no ocean.
  - Live registry: `record_live(iid, set_name, obj_name, nif_path, source="set")`, `forget_live(iid)`, `clear_live()`, `clear_live_for_set(set_name)`, `live() -> tuple`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_planet_surface_catalogue.py
import json
import zlib

import pytest

from engine.planets import atmosphere as atmo
from engine.planets import surface as surf


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    path = tmp_path / "atmospheres.json"

    def write(obj):
        path.write_text(json.dumps(obj))
        atmo.reload()
    monkeypatch.setattr(atmo, "catalogue_path", lambda: path)
    yield write
    atmo.reload()


def test_each_type_parses(catalogue):
    for t in ("rocky", "desert", "ice", "gas", "ocean"):
        catalogue({"x": {"atmosphere": False, "surface": {"type": t}}})
        s = surf.resolve_surface("S", "N", "data/x.nif")
        assert s is not None and s.type == t


def test_type_none_is_no_detail(catalogue):
    catalogue({"x": {"atmosphere": False, "surface": {"type": "none"}}})
    assert surf.resolve_surface("S", "N", "x.NIF") is None


def test_airless_entry_keeps_surface(catalogue):
    catalogue({"moon": {"atmosphere": False, "surface": {"type": "rocky"}}})
    assert atmo.resolve("S", "Moon 1", "data/moon.nif") is None
    assert surf.resolve_surface("S", "Moon 1", "data/moon.nif").type == "rocky"


def test_unknown_surface_field_rejected_but_atmosphere_survives(catalogue, capsys):
    catalogue({"p": {"color": "#87B4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0,
                     "surface": {"type": "rocky", "bogus": 1}}})
    assert surf.resolve_surface("S", "N", "p.nif") is None
    assert atmo.resolve("S", "N", "p.nif") is not None
    assert "bogus" in capsys.readouterr().err


def test_bad_type_rejected(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "lava"}}})
    assert surf.resolve_surface("S", "N", "p.nif") is None


@pytest.mark.parametrize("field,value", [("ocean_tolerance", 0.0), ("ocean_tolerance", 1.5),
                                         ("strength", -0.1), ("strength", 4.1),
                                         ("albedo", 5.0), ("scale", 0.2), ("scale", 4.5)])
def test_ranges_enforced(catalogue, field, value):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky", field: value}}})
    assert surf.resolve_surface("S", "N", "p.nif") is None


def test_malformed_warns_once(catalogue, capsys):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "lava"}}})
    surf.resolve_surface("S", "N", "p.nif")
    surf.resolve_surface("S", "N", "p.nif")
    assert capsys.readouterr().err.count("lava") == 1


def test_ocean_hex_to_linear(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky", "ocean": "#FF0000"}}})
    s = surf.resolve_surface("S", "N", "p.nif")
    assert s.ocean == pytest.approx((1.0, 0.0, 0.0))


def test_override_without_surface_inherits_stem(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "ice"}},
               "Vesuvi6/Haven": {"color": "#87B4FF", "thickness": 0.02, "density": 1.0, "limb": 1.0}})
    assert surf.resolve_surface_key("Vesuvi6", "Haven", "p.nif") == "p"
    assert surf.resolve_surface("Vesuvi6", "Haven", "p.nif").type == "ice"


def test_override_with_surface_wins(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "ice"}},
               "Vesuvi6/Haven": {"atmosphere": False, "surface": {"type": "desert"}}})
    assert surf.resolve_surface("Vesuvi6", "Haven", "p.nif").type == "desert"


def test_seed_is_crc32_of_key(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    assert surf.resolve_surface("S", "N", "p.nif").seed == zlib.crc32(b"p")


def test_to_binding_shapes():
    assert surf.to_binding(None) is None
    s = surf.Surface(type="gas", ocean=None, seed=7)
    assert surf.to_binding(s) == (4, (0.0, 0.0, 0.0), False, 0.15, 1.0, 1.0, 1.0, 7)
    s2 = surf.Surface(type="rocky", ocean=(0.1, 0.2, 0.3), seed=1)
    assert surf.to_binding(s2)[1:3] == ((0.1, 0.2, 0.3), True)


def test_live_registry_set_scoping():
    surf.clear_live()
    surf.record_live("a", "S1", "P", "p.nif")
    surf.record_live("b", "S2", "P", "p.nif")
    surf.record_live("c", "S1", "Q", "q.nif", source="celestial")
    surf.clear_live_for_set("S1")
    assert [lp.iid for lp in surf.live()] == ["b", "c"]
    surf.forget_live("b")
    assert [lp.iid for lp in surf.live()] == ["c"]
    surf.clear_live()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_planet_surface_catalogue.py -q`
Expected: FAIL — `ModuleNotFoundError: engine.planets.surface`.

- [ ] **Step 3: Implement**

In `engine/planets/atmosphere.py` add `"surface"` to `_FIELDS` (the atmosphere parser keeps ignoring its contents — a malformed `surface` must never drop the air). Update the module docstring: "`atmosphere: false` disables only the air; a sibling `surface` still applies (planet-surface-detail spec §7)."

```python
# engine/planets/surface.py
"""Planet surface-detail catalogue entries (spec
docs/superpowers/specs/2026-10-08-planet-surface-detail-design.md §7).

`surface` is a nested object inside an atmospheres.json entry. It resolves
INDEPENDENTLY of the atmosphere fields: a "<set>/<name>" override that has no
`surface` inherits the NIF stem's, and `atmosphere: false` disables only the
air. A malformed `surface` warns once and drops only the detail. Resolved at
USE through atmosphere.load(), never at import.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass

from engine.planets import atmosphere as _atmo

TYPE_CODES: dict = {"none": 0, "rocky": 1, "desert": 2, "ice": 3, "gas": 4, "ocean": 5}
_FIELDS = {"type", "ocean", "ocean_tolerance", "strength", "albedo", "scale"}

_live: list = []


@dataclass(frozen=True)
class Surface:
    type: str
    ocean: tuple | None          # linear RGB water key, or None
    ocean_tolerance: float = 0.15
    strength: float = 1.0
    albedo: float = 1.0
    scale: float = 1.0
    seed: int = 0                # crc32 of the resolved catalogue key


@dataclass(frozen=True)
class LiveSurface:
    iid: object
    set_name: str
    obj_name: str
    nif_path: str
    source: str = "set"


def _num(obj: dict, name: str, lo: float, hi: float, default: float,
         lo_open: bool = False) -> float:
    if name not in obj:
        return default
    v = obj[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"surface.{name} must be a number")
    v = float(v)
    if (v <= lo if lo_open else v < lo) or v > hi:
        raise ValueError(f"surface.{name}={v} out of range")
    return v


def parse_surface(obj, seed: int):
    if not isinstance(obj, dict):
        raise ValueError("surface must be an object")
    unknown = set(obj) - _FIELDS
    if unknown:
        raise ValueError(f"unknown surface field(s) {sorted(unknown)}")
    t = obj.get("type")
    if t not in TYPE_CODES:
        raise ValueError(f"surface.type {t!r} not one of {sorted(TYPE_CODES)}")
    if t == "none":
        return None
    ocean = _atmo.srgb_hex_to_linear(obj["ocean"]) if "ocean" in obj else None
    return Surface(
        type=t, ocean=ocean,
        ocean_tolerance=_num(obj, "ocean_tolerance", 0.0, 1.0, 0.15, lo_open=True),
        strength=_num(obj, "strength", 0.0, 4.0, 1.0),
        albedo=_num(obj, "albedo", 0.0, 4.0, 1.0),
        scale=_num(obj, "scale", 0.25, 4.0, 1.0),
        seed=seed,
    )


def resolve_surface_key(set_name: str, obj_name: str, nif_path: str):
    raw = _atmo.load()
    override = f"{set_name}/{obj_name}"
    if set_name and isinstance(raw.get(override), dict) and "surface" in raw[override]:
        return override
    stem = _atmo.nif_stem(nif_path)
    if isinstance(raw.get(stem), dict) and "surface" in raw[stem]:
        return stem
    return None


def resolve_surface(set_name: str, obj_name: str, nif_path: str):
    key = resolve_surface_key(set_name, obj_name, nif_path)
    if key is None:
        return None
    try:
        return parse_surface(_atmo.load()[key]["surface"],
                             seed=zlib.crc32(key.encode("utf-8")))
    except (ValueError, KeyError, TypeError) as e:
        _atmo._warn(str(_atmo.catalogue_path()), key + "#surface",
                    f"malformed surface ({e}); no surface detail")
        return None


def to_binding(s):
    if s is None:
        return None
    ocean = tuple(float(c) for c in s.ocean) if s.ocean is not None else (0.0, 0.0, 0.0)
    return (TYPE_CODES[s.type], ocean, s.ocean is not None, float(s.ocean_tolerance),
            float(s.strength), float(s.albedo), float(s.scale), int(s.seed))


def record_live(iid, set_name: str, obj_name: str, nif_path: str, source: str = "set") -> None:
    _live.append(LiveSurface(iid, set_name, obj_name, nif_path, source))


def forget_live(iid) -> None:
    _live[:] = [lp for lp in _live if not _atmo.iid_eq(lp.iid, iid)]


def clear_live() -> None:
    _live.clear()


def clear_live_for_set(set_name: str) -> None:
    _live[:] = [lp for lp in _live if not (lp.source == "set" and lp.set_name == set_name)]


def live() -> tuple:
    return tuple(_live)
```

(`_atmo._warn` prints `[atmosphere] <key>#surface: …` — the key suffix keeps the warn-once key distinct from the atmosphere entry's own.)

Also add `surface.clear_live()` to the autouse reset in `tests/conftest.py` beside the existing atmosphere live-registry reset (grep `clear_live` there).

- [ ] **Step 4: Run tests — PASS**

Run: `uv run pytest tests/unit/test_planet_surface_catalogue.py tests/unit/test_planet_atmosphere_catalogue.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/planets/surface.py engine/planets/atmosphere.py tests/unit/test_planet_surface_catalogue.py tests/conftest.py
git commit -m "feat(planets): surface catalogue entries resolve independently of the atmosphere"
```

---

### Task 2: Seed `surface` content for every stock stem

**Files:**
- Modify: `native/assets/planets/atmospheres.json`
- Test: `tests/unit/test_planet_surface_catalogue.py` (append)

**Interfaces:** Consumes Task 1. Produces the shipped catalogue.

- [ ] **Step 1: Failing test** (append)

```python
SEED = {
    "rocky": {"moon", "grayplanet", "rockyplanet", "tanplanet", "redplanet", "brownplanet",
              "greenplanet", "slimegreenplanet", "rootbeerplanet", "aquaplanet",
              "bluegrayplanet", "greenpurpleplanet", "purplewhiteplanet", "earth", "planet",
              "lavenderplanet"},
    "desert": {"sulfurplanet", "dryplanet", "bluetanplanet", "brownblueplanet"},
    "ice": {"snowplanet", "iceplanet"},
    "gas": {"pinkgasplanet", "bluewhitegasplanet", "tangasplanet", "gasgiant", "redswirlplanet"},
    "ocean": {"purpleplanet", "brightgreenplanet", "turquoiseplanet", "bluerockyplanet"},
}
WITH_OCEAN = {"aquaplanet", "bluegrayplanet", "greenpurpleplanet", "purplewhiteplanet", "earth",
              "planet", "dryplanet", "bluetanplanet", "brownblueplanet", "iceplanet"}


def test_shipped_catalogue_seeds_every_stock_stem():
    atmo.reload()
    seen = set()
    for t, stems in SEED.items():
        for stem in stems:
            s = surf.resolve_surface("", "", f"data/models/environment/{stem}.nif")
            assert s is not None and s.type == t, stem
            assert (s.ocean is not None) == (stem in WITH_OCEAN), stem
            seen.add(stem)
    assert seen == set(atmo.STOCK_STEMS)
    for stem in atmo.STOCK_STEMS:   # air untouched by the edit
        atmo.resolve("", "", f"{stem}.nif")
```

- [ ] **Step 2: Run — FAIL** (`s is None`).

- [ ] **Step 3: Edit the JSON.** Add a `"surface"` object to each of the 31 existing entries, leaving every other field byte-identical. Ocean keys (sampled from each texture's dominant sea colour, 2026-10-08; tuned live later):

| stem | surface |
|---|---|
| aquaplanet | `{"type": "rocky", "ocean": "#4E6B69"}` |
| bluegrayplanet | `{"type": "rocky", "ocean": "#7A9C9F"}` |
| greenpurpleplanet | `{"type": "rocky", "ocean": "#94889F"}` |
| purplewhiteplanet | `{"type": "rocky", "ocean": "#7470A0"}` |
| earth | `{"type": "rocky", "ocean": "#352E57"}` |
| planet | `{"type": "rocky", "ocean": "#405870"}` |
| dryplanet | `{"type": "desert", "ocean": "#66A794"}` |
| bluetanplanet | `{"type": "desert", "ocean": "#6F97B5"}` |
| brownblueplanet | `{"type": "desert", "ocean": "#7A9C9E"}` |
| iceplanet | `{"type": "ice", "ocean": "#888CAA"}` |
| every other stem | `{"type": "<its SEED type>"}` |

Keep one entry per line, as the file is today, e.g.
`"moon": {"atmosphere": false, "surface": {"type": "rocky"}},`

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_planet_surface_catalogue.py tests/unit/test_planet_atmosphere_catalogue.py -q` → PASS.

- [ ] **Step 5: Commit** `git add native/assets/planets/atmospheres.json tests/unit/test_planet_surface_catalogue.py && git commit -m "feat(planets): seed surface types and ocean keys for the 31 stock planets"`

---

### Task 3: `planet_detail_noise` — GL-free noise, fields, type table, gnomonic anchor

**Files:**
- Create: `native/src/renderer/include/renderer/planet_detail_noise.h`, `native/src/renderer/planet_detail_noise.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add the .cc to the renderer library sources, next to `atmosphere_math.cc`), `native/tests/renderer/CMakeLists.txt` (add `planet_detail_noise_test.cc`)
- Test: `native/tests/renderer/planet_detail_noise_test.cc`

**Interfaces:**
- Produces (namespace `renderer::planet_detail`):

```cpp
enum class SurfaceType : int { None = 0, Rocky = 1, Desert = 2, Ice = 3, Gas = 4, Ocean = 5 };

struct TypeParams {
    float base_wavelength_gu;  // octave-0 wavelength before Surface::scale
    int   max_octaves;
    float gain;                // amplitude ratio per octave
    float ridged;              // 1 = ridged multifractal, 0 = fBm
    float amplitude;           // height amplitude
    float bump;                // shading-normal tilt per unit gradient
    float albedo;              // log-luminance variation per unit height
    float roughness;           // water/sheen GGX roughness
    float roughness_var;       // A-channel modulation of roughness
    float crack_width;         // ice only: crack line half-width in noise units
    float stretch;             // gas only: latitude-frequency multiplier (bands)
    float warp;                // gas only: domain-warp strength
    float gas_rate_gups;       // gas only: peak eastward flow, GU/s
    float gas_period_s;        // gas only: two-phase period
    float coast_k;             // coast smoothstep half-width
    float coast_a;             // coast height perturbation
};

TypeParams default_params(SurfaceType t);
// Runtime-tunable copy (dev dials); starts at the defaults.
TypeParams& live_params(SurfaceType t);
void reset_live_params();
// A hash of every field that changes the BAKED field (base_wavelength_gu,
// max_octaves, gain, ridged, amplitude, crack_width, stretch, warp): the pass
// resets the clipmap when it changes.
std::uint32_t shape_hash(const TypeParams& p);

glm::uvec3 pcg3d(glm::uvec3 v);
// Gradient noise with analytic derivative: {value, d/dx, d/dy, d/dz}.
glm::vec4 noised(const glm::vec3& x, std::uint32_t seed);

struct FieldSample { float h; glm::vec3 grad; float a; };  // grad wrt q = p / wavelength0
// p_local_gu: planet-local position (body frame, centre removed, scaled to GU).
FieldSample field(SurfaceType t, const TypeParams& p, const glm::vec3& p_local_gu,
                  std::uint32_t seed, float scale, int octaves);
// Octaves whose wavelength >= 2 texels at this texel size, clamped [1, max_octaves].
int octaves_for_texel(const TypeParams& p, float scale, float texel_gu);

struct Anchor { glm::vec3 A, E, N; float R; };
Anchor make_anchor(const glm::vec3& dir_local, float R);   // E = normalize(cross(Z, A)), X-fallback near poles
glm::vec2 to_plane(const Anchor& a, const glm::vec3& p_local);   // gnomonic
glm::vec3 from_plane(const Anchor& a, const glm::vec2& xy);      // point ON the sphere (|p| = R)
```

- [ ] **Step 1: Failing tests**

```cpp
// native/tests/renderer/planet_detail_noise_test.cc
#include <gtest/gtest.h>
#include <renderer/planet_detail_noise.h>
#include <cmath>

using namespace renderer::planet_detail;

TEST(PlanetDetailNoise, Pcg3dIsDeterministicAndMixes) {
    EXPECT_EQ(pcg3d({1u, 2u, 3u}), pcg3d({1u, 2u, 3u}));
    EXPECT_NE(pcg3d({1u, 2u, 3u}), pcg3d({1u, 2u, 4u}));
}

TEST(PlanetDetailNoise, AnalyticGradientMatchesCentralDifference) {
    for (int i = 0; i < 50; ++i) {
        glm::vec3 x(0.37f * i, 1.3f - 0.11f * i, 5.0f + 0.07f * i);
        glm::vec4 n = noised(x, 99u);
        const float e = 1e-3f;
        for (int k = 0; k < 3; ++k) {
            glm::vec3 d(0.0f); d[k] = e;
            float fd = (noised(x + d, 99u).x - noised(x - d, 99u).x) / (2 * e);
            EXPECT_NEAR(n[k + 1], fd, 2e-2f) << i << " axis " << k;
        }
    }
}

TEST(PlanetDetailNoise, FieldGradientMatchesCentralDifferenceForEveryType) {
    for (int t = 1; t <= 5; ++t) {
        auto ty = static_cast<SurfaceType>(t);
        TypeParams p = default_params(ty);
        glm::vec3 x(812.0f, -3401.0f, 1203.0f);
        FieldSample s = field(ty, p, x, 7u, 1.0f, 4);
        const float e = 1e-3f * p.base_wavelength_gu;
        for (int k = 0; k < 3; ++k) {
            glm::vec3 d(0.0f); d[k] = e;
            float fd = (field(ty, p, x + d, 7u, 1.0f, 4).h - field(ty, p, x - d, 7u, 1.0f, 4).h)
                       / (2 * e / p.base_wavelength_gu);
            EXPECT_NEAR(s.grad[k], fd, 0.05f + 0.05f * std::fabs(fd)) << "type " << t << " axis " << k;
        }
    }
}

TEST(PlanetDetailNoise, FieldsFiniteAndBounded) {
    for (int t = 1; t <= 5; ++t) {
        auto ty = static_cast<SurfaceType>(t);
        TypeParams p = default_params(ty);
        for (int i = 0; i < 400; ++i) {
            glm::vec3 x(std::sin(i * 1.7f) * 3600.0f, std::cos(i * 0.3f) * 3600.0f, (i - 200) * 9.0f);
            FieldSample s = field(ty, p, x, 1u, 1.0f, p.max_octaves);
            ASSERT_TRUE(std::isfinite(s.h) && std::isfinite(s.a));
            ASSERT_TRUE(std::isfinite(s.grad.x) && std::isfinite(s.grad.y) && std::isfinite(s.grad.z));
            EXPECT_LE(std::fabs(s.h), 2.0f);
            EXPECT_GE(s.a, 0.0f); EXPECT_LE(s.a, 1.0f);
        }
    }
}

TEST(PlanetDetailNoise, SeedChangesTheField) {
    TypeParams p = default_params(SurfaceType::Rocky);
    glm::vec3 x(100.0f, 200.0f, 300.0f);
    EXPECT_NE(field(SurfaceType::Rocky, p, x, 1u, 1.0f, 6).h,
              field(SurfaceType::Rocky, p, x, 2u, 1.0f, 6).h);
}

TEST(PlanetDetailNoise, OctavesForTexel) {
    TypeParams p = default_params(SurfaceType::Rocky);   // 40 GU base, max 9
    EXPECT_EQ(octaves_for_texel(p, 1.0f, 0.1f), 9);      // 40 -> 0.2 GU needs 8 halvings + 1, capped at 9
    EXPECT_EQ(octaves_for_texel(p, 1.0f, 1.6f), 4);      // 40/3.2 = 12.5 -> floor(log2)=3, +1
    EXPECT_EQ(octaves_for_texel(p, 1.0f, 100.0f), 1);
}

TEST(PlanetDetailNoise, GnomonicRoundTrip) {
    Anchor a = make_anchor(glm::normalize(glm::vec3(0.3f, 0.5f, 0.8f)), 3600.0f);
    for (glm::vec2 xy : {glm::vec2(0, 0), glm::vec2(120.5f, -40.0f), glm::vec2(-1700.0f, 900.0f)}) {
        glm::vec3 p = from_plane(a, xy);
        EXPECT_NEAR(glm::length(p), 3600.0f, 1e-2f);
        glm::vec2 back = to_plane(a, p);
        EXPECT_NEAR(back.x, xy.x, 1e-4f * 3600.0f);
        EXPECT_NEAR(back.y, xy.y, 1e-4f * 3600.0f);
    }
}

TEST(PlanetDetailNoise, AnchorAtPoleIsOrthonormal) {
    for (glm::vec3 d : {glm::vec3(0, 0, 1), glm::vec3(0, 0, -1), glm::vec3(1e-5f, 0, 1)}) {
        Anchor a = make_anchor(glm::normalize(d), 140.0f);
        EXPECT_NEAR(glm::length(a.E), 1.0f, 1e-5f);
        EXPECT_NEAR(glm::length(a.N), 1.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(a.A, a.E), 0.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(a.A, a.N), 0.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(a.E, a.N), 0.0f, 1e-5f);
    }
}

TEST(PlanetDetailNoise, ShapeHashTracksBakedFieldsOnly) {
    TypeParams p = default_params(SurfaceType::Rocky);
    TypeParams q = p; q.bump = 9.0f; q.roughness = 0.9f;
    EXPECT_EQ(shape_hash(p), shape_hash(q));
    q.base_wavelength_gu = 41.0f;
    EXPECT_NE(shape_hash(p), shape_hash(q));
}
```

- [ ] **Step 2: Run** `cmake --build build -j` → FAIL (header missing).

- [ ] **Step 3: Implement** `planet_detail_noise.cc`. Exact maths (the GLSL twin in Task 6 copies it line for line):

```cpp
// pcg3d (Jarzynski & Olano 2020)
glm::uvec3 pcg3d(glm::uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return v;
}
static glm::vec3 grad3(glm::ivec3 c, std::uint32_t seed) {
    glm::uvec3 h = pcg3d(glm::uvec3(c) + glm::uvec3(seed, seed * 7919u, seed * 104729u));
    return glm::vec3(h) * (2.0f / 4294967295.0f) - 1.0f;
}
glm::vec4 noised(const glm::vec3& x, std::uint32_t seed) {
    glm::vec3 fl = glm::floor(x); glm::ivec3 i(fl); glm::vec3 f = x - fl;
    glm::vec3 u  = f*f*f*(f*(f*6.0f-15.0f)+10.0f);
    glm::vec3 du = 30.0f*f*f*(f*(f-2.0f)+1.0f);
    // corners a..h = (000,100,010,110,001,101,011,111); g* = grad3(i+corner), v* = dot(g*, f-corner)
    // value  v  = va + u.x(vb-va) + u.y(vc-va) + u.z(ve-va) + u.x u.y(va-vb-vc+vd)
    //           + u.y u.z(va-vc-ve+vg) + u.z u.x(va-vb-ve+vf) + u.x u.y u.z(-va+vb+vc-vd+ve-vf-vg+vh)
    // deriv  d  = ga + u.x(gb-ga) + u.y(gc-ga) + u.z(ge-ga) + u.x u.y(ga-gb-gc+gd)
    //           + u.y u.z(ga-gc-ge+gg) + u.z u.x(ga-gb-ge+gf) + u.x u.y u.z(-ga+gb+gc-gd+ge-gf-gg+gh)
    //           + du * ( vec3(vb-va, vc-va, ve-va)
    //                  + u.yzx * vec3(va-vb-vc+vd, va-vc-ve+vg, va-vb-ve+vf)
    //                  + u.zxy * vec3(va-vb-ve+vf, va-vb-vc+vd, va-vc-ve+vg)
    //                  + u.yzx * u.zxy * (-va+vb+vc-vd+ve-vf-vg+vh) )
    // (Inigo Quilez, "gradient noise derivatives"; write it out in full.)
}
```

Octave loop shared by every type (`kRot` = `mat3(0.00,0.80,0.60, -0.80,0.36,-0.48, -0.60,-0.48,0.64)` column-major as GLSL; rotation between octaves; chain rule through `m`):

```cpp
struct Acc { float h; glm::vec3 g; };
// q = p_local / (base_wavelength * scale). Returns height and d h / d q.
static Acc fbm(glm::vec3 q, int n, float gain, float ridged, std::uint32_t seed) {
    float a = 0.5f, s = 1.0f; glm::mat3 m(1.0f); Acc r{0.0f, glm::vec3(0.0f)};
    for (int k = 0; k < n; ++k) {
        glm::vec4 nd = noised(m * q * s, seed + std::uint32_t(k) * 1013u);
        glm::vec3 dn = s * (glm::transpose(m) * glm::vec3(nd.y, nd.z, nd.w));
        if (ridged > 0.5f) {   // ridge = (1 - |n|)^2, derivative -2 (1-|n|) sign(n) dn
            float an = std::fabs(nd.x), rr = 1.0f - an, sg = nd.x >= 0.0f ? 1.0f : -1.0f;
            r.h += a * (rr * rr - 0.5f);
            r.g += a * (-2.0f * rr * sg) * dn;
        } else {
            r.h += a * nd.x; r.g += a * dn;
        }
        s *= 2.0f; m = kRot * m; a *= gain;
    }
    return r;
}
```

Per-type `field()` (all heights × `amplitude`; `a` clamped to [0,1]):
- **Rocky:** `fbm(q, oct, gain, ridged=1, seed)`; `a = clamp(0.5 + 0.5*noised(q*4, seed^0xA5A5).x, 0, 1)` (wind roughness).
- **Desert:** `fbm(q, oct, gain, 0, seed)` + dune term: wind axis `W = (cos θ, sin θ, 0)` with `θ = (seed % 360) degrees`; `qd = q*8 + W*dot(q*8, W)*5` (stretch ×6 along W); `nd = noised(qd, seed^0x5A5A)`; `h += 0.15*nd.x`, `g += 0.15 * (8*(I + 5 W Wᵀ)) * nd.yzw` (chain rule). `a` as Rocky.
- **Ice:** `fbm(q, oct, gain, 0, seed)` (amplitude low via table); `c = noised(q*2, seed^0x3C3C).x`; `a = 1 - smoothstep(0, crack_width, |c|)` (crack mask; `smoothstep(e0,e1,x)` = standard cubic).
- **Gas:** stretch `qs = (q.x, q.y, q.z*stretch)`; warp `w = (noised(qs*0.5+11, seed).x, noised(qs*0.5+23, seed).x, noised(qs*0.5+37, seed).x)`; `qw = qs + warp*w`; `fbm(qw, oct, gain, 0, seed)`; gradient: ignore the warp Jacobian but apply the stretch: `g = (g.x, g.y, g.z*stretch)` — gas has no bump, the gradient is informational. `a = clamp(0.5 + 0.5*fbm(qw, oct, gain, 0, seed+1).h, 0, 1)` (phase-2 field).
- **Ocean:** `h = 0`, `g = 0`, `a` as Rocky.

Default table (calibration starts here; the dials tune `live_params`):

| type | λ0 GU | max_oct | gain | ridged | amp | bump | albedo | rough | rough_var | crack | stretch | warp | gas_rate | gas_period | coast_k | coast_a |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Rocky | 40 | 9 | 0.5 | 1 | 1.0 | 0.35 | 0.10 | 0.30 | 0.5 | 0 | 1 | 0 | 0 | 40 | 0.08 | 0.25 |
| Desert | 60 | 8 | 0.45 | 0 | 0.6 | 0.20 | 0.08 | 0.30 | 0.5 | 0 | 1 | 0 | 0 | 40 | 0.08 | 0.25 |
| Ice | 50 | 8 | 0.5 | 0 | 0.3 | 0.12 | 0.06 | 0.12 | 0.3 | 0.06 | 1 | 0 | 0 | 40 | 0.06 | 0.20 |
| Gas | 200 | 7 | 0.55 | 0 | 0.8 | 0.0 | 0.12 | 0.5 | 0.0 | 0 | 4 | 0.6 | 0.5 | 40 | 0.0 | 0.0 |
| Ocean | 40 | 3 | 0.5 | 0 | 0.0 | 0.0 | 0.0 | 0.25 | 0.6 | 0 | 1 | 0 | 0 | 40 | 0.0 | 0.0 |

`octaves_for_texel`: `λ = base_wavelength_gu*scale`; `n = floor(log2(λ / (2*texel_gu))) + 1`; clamp `[1, max_octaves]`.
`make_anchor`: `A = normalize(dir)`; `Z = (0,0,1)`; `E = cross(Z, A)`; if `|E| < 1e-3` use `E = cross((1,0,0) projected…)` — concretely `E = normalize(cross(A, (0,1,0)) )` fallback, then `E = normalize(E)`; `N = cross(A, E)`.
`to_plane`: `P = p * (R / dot(p, A))`; return `(dot(P,E), dot(P,N))`. `from_plane`: `normalize(A*R + E*x + N*y) * R`.
`shape_hash`: FNV-1a over the bytes of the eight shape fields listed in the interface.

- [ ] **Step 4: Run** `cmake --build build -j && ./build/native/tests/renderer/renderer_tests --gtest_filter=PlanetDetailNoise.*` → PASS.

- [ ] **Step 5: Commit** `git add native/src/renderer/include/renderer/planet_detail_noise.h native/src/renderer/planet_detail_noise.cc native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt native/tests/renderer/planet_detail_noise_test.cc && git commit -m "feat(renderer): planet detail noise — pcg3d analytic noise, per-type fields, gnomonic anchor"`

---

### Task 4: Clipmap scheduler (GL-free)

**Files:**
- Create: `native/src/renderer/include/renderer/planet_clipmap_schedule.h`, `native/src/renderer/planet_clipmap_schedule.cc`
- Modify: both CMakeLists (as Task 3)
- Test: `native/tests/renderer/planet_clipmap_schedule_test.cc`

**Interfaces:**
- Produces (namespace `renderer::planet_detail`):

```cpp
constexpr int kLevelSize = 1024;
constexpr int kBandRows  = 1026;      // 1024 + two guard rows
constexpr int kMaxLevels = 5;

struct Rect { int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
              bool empty() const { return x0 >= x1 || y0 >= y1; }
              long long area() const { return empty() ? 0 : (long long)(x1 - x0) * (y1 - y0); } };

// One scissored draw into one level's band. abs_* = absolute texel index of the
// piece's lower-left texel; tor_x in [0,1024), band_row in [0,1026).
struct BakeRect { int level; int abs_x, abs_y; int tor_x, band_row; int w, h; };

int  level_count_for(float R_gu, float ts0_gu);                  // largest n<=5 with 512*ts0*2^(n-1) <= R, min 1
bool needs_reanchor(glm::vec2 nadir_plane_gu, float R_gu);       // |nadir| > 0.5 R

class ClipmapSchedule {
public:
    ClipmapSchedule(float ts0_gu, std::vector<int> octaves_per_level);   // size = level count
    void reset();                                                        // all valid rects empty
    // Grow valid rects toward the targets around `nadir`, coarse level first,
    // until `budget` cost units (texels x octaves) are spent. Appends draws to
    // `out`. Returns the cost spent. Never exceeds budget by more than one strip.
    long long update(glm::vec2 nadir_plane_gu, long long budget, std::vector<BakeRect>& out);
    Rect target(int level, glm::vec2 nadir_plane_gu) const;   // 1024^2 centred on the nadir texel
    const Rect& valid(int level) const;
    bool complete(glm::vec2 nadir_plane_gu) const;            // every valid == target
    int  levels() const;
    float texel_gu(int level) const;                          // ts0 * 2^level
};
```

- [ ] **Step 1: Failing tests** — write these (each a `TEST(ClipmapSchedule, ...)`):

```cpp
#include <gtest/gtest.h>
#include <renderer/planet_clipmap_schedule.h>
#include <set>
#include <utility>
using namespace renderer::planet_detail;

static std::vector<int> oct5() { return {9, 8, 7, 6, 5}; }

// Every (level, toroidal x, toroidal row) written, counting guard rows separately.
static void paint(const std::vector<BakeRect>& rs, std::vector<std::set<std::pair<int,int>>>& px) {
    for (auto& r : rs) for (int y = 0; y < r.h; ++y) for (int x = 0; x < r.w; ++x)
        px[r.level].insert({r.tor_x + x, r.band_row + y});
}

TEST(ClipmapSchedule, LevelCountCapsForSmallPlanets) {
    EXPECT_EQ(level_count_for(3600.0f, 0.1f), 5);
    EXPECT_EQ(level_count_for(140.0f, 0.1f), 2);    // 51.2*2^1=102.4 <= 140 < 204.8
    EXPECT_EQ(level_count_for(10.0f, 0.1f), 1);
}

TEST(ClipmapSchedule, ReanchorThreshold) {
    EXPECT_FALSE(needs_reanchor({1799.0f, 0.0f}, 3600.0f));
    EXPECT_TRUE(needs_reanchor({1300.0f, 1300.0f}, 3600.0f));
}

TEST(ClipmapSchedule, ColdFillCompletesAndCoversEveryTexelOnce) {
    ClipmapSchedule s(0.1f, oct5());
    std::vector<std::set<std::pair<int,int>>> px(5);
    long long total = 0; int frames = 0;
    const long long budget = 65536LL * 8;
    while (!s.complete({0, 0}) && frames < 1000) {
        std::vector<BakeRect> out;
        long long c = s.update({0, 0}, budget, out);
        EXPECT_LE(c, budget + 1024LL * 9 + 2 * 1024LL * 9);   // one strip (+ its guard rows) of slack
        total += c; paint(out, px); ++frames;
    }
    ASSERT_TRUE(s.complete({0, 0}));
    for (int L = 0; L < 5; ++L) EXPECT_EQ(px[L].size(), 1024u * 1026u) << L;   // 1024 rows + 2 guards
    EXPECT_GT(frames, 20); EXPECT_LT(frames, 200);
}

TEST(ClipmapSchedule, NoOverlapWithinOneColdFill) {
    ClipmapSchedule s(0.1f, oct5());
    std::vector<std::multiset<std::pair<int,int>>> seen(5);
    for (int f = 0; f < 1000 && !s.complete({0, 0}); ++f) {
        std::vector<BakeRect> out; s.update({0, 0}, 65536LL * 8, out);
        for (auto& r : out) for (int y = 0; y < r.h; ++y) for (int x = 0; x < r.w; ++x)
            seen[r.level].insert({r.tor_x + x, r.band_row + y});
    }
    for (int L = 0; L < 5; ++L)
        for (auto& p : seen[L]) ASSERT_EQ(seen[L].count(p), 1u) << L;
}

TEST(ClipmapSchedule, OneTexelMoveBakesOneColumnPerLevelThatMoved) {
    ClipmapSchedule s(0.1f, oct5());
    for (int f = 0; f < 1000 && !s.complete({0.05f, 0.05f}); ++f) { std::vector<BakeRect> o; s.update({0.05f, 0.05f}, 1LL << 40, o); }
    std::vector<BakeRect> out;
    s.update({0.15f, 0.05f}, 1LL << 40, out);     // level 0 nadir texel moves +1 in x
    long long l0 = 0; for (auto& r : out) if (r.level == 0) l0 += (long long)r.w * r.h;
    EXPECT_EQ(l0, 1024 + 2);                       // one column + its 2 guard texels
    for (auto& r : out) EXPECT_EQ(r.level, 0);     // coarser levels' nadir texel did not change
}

TEST(ClipmapSchedule, WrapSplitPiecesStayInsideTheBand) {
    ClipmapSchedule s(0.1f, oct5());
    for (float x = 0; x < 300.0f; x += 7.3f) {     // drive far enough to wrap every level
        std::vector<BakeRect> out; s.update({x, -x * 0.5f}, 65536LL * 8, out);
        for (auto& r : out) {
            EXPECT_GE(r.tor_x, 0); EXPECT_LE(r.tor_x + r.w, 1024);
            EXPECT_GE(r.band_row, 0); EXPECT_LE(r.band_row + r.h, 1026);
        }
    }
}

TEST(ClipmapSchedule, GuardRowsMirrorEdgeRows) {
    ClipmapSchedule s(0.1f, oct5());
    std::vector<BakeRect> all;
    for (int f = 0; f < 1000 && !s.complete({0, 0}); ++f) s.update({0, 0}, 65536LL * 8, all);
    // band row 0 must carry the abs row whose toroidal row is 1023; band row 1025 the one at toroidal 0.
    for (auto& r : all) {
        if (r.band_row == 0) { EXPECT_EQ(r.h, 1); EXPECT_EQ(((r.abs_y % 1024) + 1024) % 1024, 1023); }
        if (r.band_row + r.h - 1 == 1025 && r.h == 1) EXPECT_EQ(((r.abs_y % 1024) + 1024) % 1024, 0);
    }
}

TEST(ClipmapSchedule, DashStarvesFineLevelsButCostStaysCapped) {
    ClipmapSchedule s(0.1f, oct5());
    float x = 0;
    for (int f = 0; f < 300; ++f) {
        x += 400.0f / 60.0f;
        std::vector<BakeRect> out;
        EXPECT_LE(s.update({x, 0}, 65536LL * 8, out), 65536LL * 8 + 3 * 1024LL * 9);
    }
    EXPECT_FALSE(s.complete({x, 0}));
}
```

- [ ] **Step 2: Run** → FAIL (no header).

- [ ] **Step 3: Implement.** Algorithm (from the spike `scratchpad/spike/clip.cc`, now with guards and cost units):
  - `target(L, n)`: `c = floor(n / texel_gu(L))` per axis; `{c.x-512, c.y-512, c.x+512, c.y+512}`.
  - `update`: `left = budget`. For `L = levels-1 … 0` while `left > 0`: `D = target(L)`; `B = intersect(B, D)` (empty if disjoint). If `B` empty: `B = {D.x0, cy, D.x1, cy}` (zero-height, full width). Loop while `B != D` and `left > 0`, with `cost_per_texel = octaves[L]`:
    - if `B.y1 == B.y0`: set `B.x0=D.x0, B.x1=D.x1` (free) and fall to row growth;
    - else if `B.x0 > D.x0`: `k = min(B.x0-D.x0, max(1, left / (h*cost)))`; strip `{B.x0-k, B.y0, B.x0, B.y1}`; `B.x0 -= k`;
    - else if `B.x1 < D.x1`: mirror on the right;
    - else grow rows toward whichever of `B.y0-D.y0` / `D.y1-B.y1` is larger (ties → down), `k = min(gap, max(1, left / (w*cost)))`.
    - `emit(L, strip)`; `left -= cost of everything emitted`.
  - `emit(L, strip)`: split by toroidal wrap into ≤4 pieces: for x runs `tor_x = mod(xs,1024)`, `w = min(x1-xs, 1024-tor_x)`; for y runs `ty = mod(ys,1024)`, `h = min(y1-ys, 1024-ty)`; `band_row = ty + 1`. For each piece also emit guards: if the piece covers `ty == 1023` (i.e. `ty + h - 1 == 1023`), emit `{L, abs_x, abs_y_of_row1023, tor_x, band_row=0, w, h=1}`; if it covers `ty == 0`, emit `{L, abs_x, abs_y_of_row0, tor_x, band_row=1025, w, h=1}`. Guards count toward cost.
  - `complete(n)`: every level's `valid == target(n)`.
  - Valid-rect bookkeeping: `valid(L)` is `B`. (Guards are content copies of rows inside `B`, so they never extend validity.)

- [ ] **Step 4: Run** `--gtest_filter=ClipmapSchedule.*` → PASS.

- [ ] **Step 5: Commit** `git add <the 5 files> && git commit -m "feat(renderer): budgeted toroidal clipmap scheduler with guard rows"`

---

### Task 5: `Instance::Surface`, binding, Python hook and toggle

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (beside `struct Atmosphere`), `native/src/scenegraph/include/scenegraph/world.h` + `world.cc` (`set_surface`, mirror `set_atmosphere`), `native/src/host/host_bindings.cc` (beside `set_instance_atmosphere`, ~line 3668), `engine/renderer.py` / `engine/host_io.py` if `set_instance_atmosphere` is re-exported there (grep and mirror exactly), `engine/host_loop.py`
- Create: `engine/planet_surface.py`
- Test: `tests/host/test_instance_surface_binding.py`, `tests/unit/test_planet_surface_wiring.py`

**Interfaces:**
- Produces:

```cpp
// instance.h, inside Instance, after Atmosphere:
/// Planet surface detail (spec 2026-10-08). type 0 = none (default), so an
/// un-configured instance renders byte-identically.
struct Surface {
    int           type = 0;            // planet_detail::SurfaceType
    glm::vec3     ocean{0.0f};         // linear
    bool          has_ocean = false;
    float         ocean_tol = 0.15f;
    float         strength = 1.0f;
    float         albedo = 1.0f;
    float         scale = 1.0f;
    std::uint32_t seed = 0;
};
Surface surface;
```
  - `World::set_surface(InstanceId, const Instance::Surface&)`.
  - Python binding `set_instance_surface(id, params)`: `None` → default `Surface{}`; else the 8-tuple from `surface.to_binding`.
  - `engine/planet_surface.py`: `enabled()` / `set_enabled(v)`, default `True` (copy `engine/planet_atmosphere.py`'s shape and docstring style).
  - `host_loop._apply_planet_surface(r_, iid, set_name, obj_name, nif_path, source="set")`.

- [ ] **Step 1: Failing tests**
  - `tests/host/test_instance_surface_binding.py`: mirror `tests/host/test_instance_atmosphere_binding.py` exactly (same fixture/import of `_dauntless_host`); assert `set_instance_surface(iid, None)` and `set_instance_surface(iid, (1, (0.1, 0.2, 0.3), True, 0.15, 1.0, 1.0, 1.0, 123))` both succeed, and that a 7-tuple raises.
  - `tests/unit/test_planet_surface_wiring.py`, mirroring `tests/unit/test_planet_atmosphere_wiring.py`'s fake renderer (its fake must grow a `set_instance_surface(iid, params)` that records calls — fakes mirror the real binding signature):

```python
def test_apply_pushes_resolved_surface(fake_r, catalogue):        # use the wiring test's fixtures
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    host_loop._apply_planet_surface(fake_r, "iid1", "S", "N", "data/p.nif")
    assert fake_r.surface_calls == [("iid1", (1, (0.0, 0.0, 0.0), False, 0.15, 1.0, 1.0, 1.0, zlib.crc32(b"p")))]
    assert [lp.iid for lp in surface.live()] == ["iid1"]

def test_toggle_off_pushes_none(fake_r, catalogue, monkeypatch):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    planet_surface.set_enabled(False)
    host_loop._apply_planet_surface(fake_r, "iid1", "S", "N", "data/p.nif")
    assert fake_r.surface_calls == [("iid1", None)]

def test_every_realize_path_calls_the_surface_hook(...):
    # Reuse whatever the atmosphere wiring test does to drive each of the three
    # realize paths (mission load, realize_set_objects, _reconcile_celestial_instances)
    # and assert one set_instance_surface call per planet instance.
```
  Add `planet_surface.set_enabled(True)` to `tests/conftest.py`'s autouse reset next to the atmosphere toggle reset.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**
  - C++ struct + `World::set_surface` (copy `set_atmosphere`'s body shape).
  - Binding:

```cpp
m.def("set_instance_surface",
      [](scenegraph::InstanceId id, py::object params) {
          scenegraph::Instance::Surface s;
          if (!params.is_none()) {
              auto t = params.cast<py::tuple>();
              if (t.size() != 8) throw py::value_error("set_instance_surface: expected an 8-tuple");
              s.type = t[0].cast<int>();
              auto o = t[1].cast<std::array<float, 3>>();
              s.ocean = {o[0], o[1], o[2]};
              s.has_ocean = t[2].cast<bool>();
              s.ocean_tol = t[3].cast<float>();
              s.strength = t[4].cast<float>();
              s.albedo = t[5].cast<float>();
              s.scale = t[6].cast<float>();
              s.seed = t[7].cast<std::uint32_t>();
          }
          g_world.set_surface(id, s);
      },
      py::arg("id"), py::arg("params"),
      "Planet surface detail (spec 2026-10-08): None disables; else "
      "(type, ocean_rgb, has_ocean, ocean_tolerance, strength, albedo, scale, seed).");
```
  - `host_loop._apply_planet_surface`:

```python
def _apply_planet_surface(r_, iid, set_name: str, obj_name: str,
                          nif_path: str, source: str = "set") -> None:
    """Push this planet instance's surface-detail decision (planet-surface-detail
    spec §7). Called from _apply_planet_atmosphere so all three realize paths
    get it; resolved at USE so a toggle flip or catalogue reload applies to
    planets realized after."""
    from engine import planet_surface as _planet_surface
    from engine.planets import surface as _surface
    if not _planet_surface.enabled():
        r_.set_instance_surface(iid, None)
        return
    r_.set_instance_surface(iid, _surface.to_binding(
        _surface.resolve_surface(set_name, obj_name, nif_path)))
    _surface.record_live(iid, set_name, obj_name, nif_path, source=source)
```
    Call it as the **first statement** of `_apply_planet_atmosphere` (before its early return), passing the same arguments.
  - Registry lifetime: at each `_atmosphere.clear_live()` / `forget_live(iid)` / `clear_live_for_set(...)` call in `host_loop.py` (lines ~6145, ~6443, ~6452, ~6779), add the matching `engine.planets.surface` call immediately after.

- [ ] **Step 4: Run** `cmake --build build -j && uv run pytest tests/host/test_instance_surface_binding.py tests/unit/test_planet_surface_wiring.py tests/unit/test_planet_atmosphere_wiring.py tests/unit/test_host_loop_planets.py -q` → PASS (the last two are in `tests/unit` or `tests/host` — run whichever exist).

- [ ] **Step 5: Commit** (explicit paths) `-m "feat(planets): push surface detail params to planet instances"`

---

### Task 6: Bake shader + atlas (GL)

**Files:**
- Create: `native/src/renderer/shaders/planet_bake.frag`, `native/src/renderer/include/renderer/planet_clipmap_atlas.h`, `native/src/renderer/planet_clipmap_atlas.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (`embed_shader(SHADER_PLANET_BAKE_FS shaders/planet_bake.frag planet_bake_fs)` + source), tests CMakeLists
- Test: `native/tests/renderer/planet_clipmap_atlas_test.cc`

**Interfaces:**
- Consumes: Task 3 (`TypeParams`, `Anchor`, `field`), Task 4 (`BakeRect`, constants).
- Produces:

```cpp
namespace renderer::planet_detail {
struct BakeParams {
    Anchor anchor; SurfaceType type; TypeParams params;
    float scale; std::uint32_t seed; float ts0_gu;
    std::vector<int> octaves_per_level;
};
class ClipmapAtlas {
public:
    explicit ClipmapAtlas(int levels);      // GL_RGBA16F, 1024 x (1026*levels), LINEAR, S=REPEAT, T=CLAMP
    ~ClipmapAtlas();                        // move-only
    void bake(const std::vector<BakeRect>& rects, const BakeParams& p);  // restores FBO, viewport, scissor, program
    GLuint texture() const;
    int levels() const;
};
}
```

- [ ] **Step 1: Failing test** — a GL test (use the window/context fixture other renderer GL tests use, e.g. `atmosphere_pass_test.cc`'s setup):
  - Create a 2-level atlas, build a `ClipmapSchedule(0.1f, {9, 8})`, cold-fill it at nadir (3.0, -2.0) with an unlimited budget, `bake()` every emitted rect for `SurfaceType::Rocky`, anchor `make_anchor(normalize((0.3,0.5,0.8)), 3600)`.
  - Read back the atlas (`glGetTexImage`, `GL_RGBA`, `GL_FLOAT`). For 64 random valid texels per level: compute the absolute texel → plane `(abs+0.5)*ts`, `from_plane`, `field(...)` with `octaves_for_texel`, then compare R to `h`, G to `dot(grad,E)`, B to `dot(grad,N)`, A to `a` within `2e-2 + 2e-2*|expected|` (fp16 + GPU float).
  - Guard rows: band row 0 equals band row 1024 and band row 1025 equals band row 1, texel for texel.
  - State restore: after `bake`, `GL_FRAMEBUFFER_BINDING`, `GL_VIEWPORT`, `GL_SCISSOR_TEST` and `GL_CURRENT_PROGRAM` equal their values before.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**
  - Vertex shader: reuse `shader_src::nebula_volumetric_vs` (full-screen triangle).
  - `planet_bake.frag` (`#version 410 core`): uniforms `u_abs` (vec2), `u_tor` (vec2: tor_x, band_row), `u_ts`, `u_oct`, `u_A/u_E/u_N`, `u_R`, `u_type`, `u_seed` (uint), `u_scale`, and every `TypeParams` field as `u_p_<name>`. Body: `absi = u_abs + (gl_FragCoord.xy - 0.5 - u_tor)`; `pl = (absi + 0.5) * u_ts`; `p = normalize(u_A*u_R + u_E*pl.x + u_N*pl.y) * u_R`; evaluate the **GLSL transcription of Task 3's `pcg3d`, `noised`, `fbm` and per-type `field`** (keep the same function names, constants and order — this file is the twin; put a comment at the top naming `planet_detail_noise.cc` as the authority); `o = vec4(h, dot(g, u_E), dot(g, u_N), a)`.
  - `bake()`: save FBO/viewport/scissor/program; bind the atlas FBO; viewport `0,0,1024,1026*levels`; enable scissor; per rect: `glScissor(tor_x, level*1026 + band_row, w, h)`, set `u_abs = (abs_x, abs_y)` and `u_tor = (tor_x, level*1026 + band_row)` — the shader's `absi = u_abs + (frag - 0.5 - u_tor)` then yields the right absolute texel for ordinary pieces and guard rows alike (a guard rect's `abs_y` is the mirrored row's absolute index); per-level uniforms `u_ts = ts0*2^level`, `u_oct = octaves_per_level[level]`; `glDrawArrays(GL_TRIANGLES, 0, 3)`; restore state.

- [ ] **Step 4: Run** `--gtest_filter=PlanetClipmapAtlas*` → PASS.

- [ ] **Step 5: Commit** `-m "feat(renderer): planet clipmap atlas and bake shader (GLSL twin of planet_detail_noise)"`

---

### Task 7: `planet_` program and `PLANET_SURFACE` sampling + land shading

**Files:**
- Modify: `native/src/renderer/pipeline.{h,cc}`, `native/src/renderer/shaders/opaque.frag`
- Create: `native/src/renderer/include/renderer/planet_detail_uniforms.h` (+ `.cc`)
- Test: `native/tests/renderer/planet_surface_draw_test.cc`

**Interfaces:**
- Produces:

```cpp
// pipeline.h
Shader& planet_shader() noexcept { return *planet_; }   // opaque.frag with PLANET_SURFACE

// planet_detail_uniforms.h
namespace renderer::planet_detail {
struct SampleUniforms {
    bool  enabled = false;           // u_pd_enabled
    GLuint atlas = 0;                // bound to unit 12
    int   levels = 0;
    float ts0 = 0.1f;
    std::array<glm::vec4, kMaxLevels> valid{};   // abs texel rect per level (x0,y0,x1,y1); empty = (1e9,1e9,-1e9,-1e9)
    glm::vec3 A{0,0,1}, E{1,0,0}, N{0,1,0};      // anchor frame, planet-local
    float R = 1.0f;                  // GU
    float scale_local = 1.0f;        // body units -> GU (instance world scale)
    int   type = 0;
    glm::vec3 ocean{0}; bool has_ocean = false; float ocean_tol = 0.15f;
    float strength = 1, albedo = 1, scale = 1;
    TypeParams params{};
    int   debug = 0;
};
void apply(Shader& s, const SampleUniforms& u);   // sets every u_pd_* and binds unit 12; enabled=false sets ONLY u_pd_enabled=0
}
```

- [ ] **Step 1: Failing tests** (`planet_surface_draw_test.cc`, modelled on `geosphere_draw_test.cc` / `atmosphere_surface_test.cc`, which already load `IcePlanet.NIF` through the content root and draw a sphere LOD):
  1. `PlanetSurfaceDraw.ProgramCompilesAndOthersUnchanged` — `Pipeline` constructs; `planet_shader()` links; `opaque_shader()`'s source text equals `shader_src::opaque_fs` (no define leaked).
  2. `PlanetSurfaceDraw.DisabledMatchesOpaqueExactly` — draw the planet with `opaque_` and again with `planet_` and `SampleUniforms{enabled=false}`; read back RGBA16F; every pixel equal.
  3. `PlanetSurfaceDraw.EnabledChangesNearNadirOnly` — fill a 2-level atlas by hand (Task 6 path), enable, camera 150 GU above the surface; pixels differ from the disabled render near screen centre; far planet (camera at 50·R) renders identical to disabled (detail weight 0).
  4. `PlanetSurfaceDraw.FiniteEverywhere` — enable, render with camera outside, at the limb, over a pole (anchor at the pole), over BC's u-seam; run the existing `nonfinite_probe` pass on the output (see `HullClipTest` for usage) — zero non-finite cells.
  5. `PlanetSurfaceDraw.NoSeamAcrossLevelBand` — valid rect for level 0 set to a 200-texel square inside a complete level 1; render a pixel row crossing level 0's edge; max adjacent-pixel luminance step across the band ≤ 1.5× the max step inside level 0.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**
  - `Pipeline`: `planet_ = std::make_unique<Shader>(shader_src::opaque_vs, with_define(shader_src::opaque_fs, "PLANET_SURFACE"));` add it to the sampler-unit loop, and after the loop `planet_->use(); planet_->set_int("u_pd_atlas", 12);`.
  - `opaque.frag`, all inside `#ifdef PLANET_SURFACE`:
    - Declarations: `uniform sampler2D u_pd_atlas;` and every `u_pd_*` from `SampleUniforms` (params as `u_pd_p_<field>`), plus `u_decal_time` already exists.
    - **Derivatives**, placed immediately after the existing sphere-map derivative block (`sp_dy` line), unconditional:
      `vec3 pd_p = (sp_body) * u_pd_scale_local;` (planet-local GU — `sp_body` already has the centre removed) `vec3 pd_dx = dFdx(pd_p), pd_dy = dFdy(pd_p);` and `vec2 pd_tex = vec2(textureSize(u_base_color, 0));` `float pd_px_per_texel = 1.0 / max(max(length(sp_dx * pd_tex), length(sp_dy * pd_tex)), 1e-6);`
    - Helpers: `pd_plane(p)` (gnomonic, as Task 3); `pd_valid(L, t)` with a 1-texel margin; `pd_fetch(L, plane_xy)`: `t = xy / (ts0*2^L)`; `u = fract(t.x/1024)`; `row = fract(t.y/1024)*1024 + 1 + L*1026` ; `textureLod(u_pd_atlas, vec2(u, row / (1026*levels)), 0)` — note `row` is the band row in texel centres: convert as `(row) / H` where `H = 1026*levels` (centre offset is already in `t`).
    - `pd_sample(p, fp) -> vec4 (h, gE, gN, a)`: `lf = clamp(log2(fp/ts0), 0, levels-1)`; `L = int(floor(lf))`, `w = fract(lf)`; advance `L` while not `pd_valid`; if none → return weight 0 via an out param. Band blend: `e = min over axes of (distance from t to the valid rect edge) / (0.1*1024)`; `w = max(w, 1 - clamp(e, 0, 1))`; sample `L` and (if `L+1 < levels` and valid) `L+1`, `mix` by `w`. Coverage fade = 1 inside level `levels-1`, fading to 0 over its outer 10% band.
    - **Detail weight** `pd_w = u_pd_enabled != 0 ? smoothstep(2.0, 8.0, pd_px_per_texel) * coverage : 0.0`.
    - **Land (this task)**: after the `base` fetch (`vec4 base = ... textureGrad(...)`) and after `n_shade` exists:
      inside `if (pd_w > 0.0) { ... }`, derive world-space axes exactly as the sphere normal is derived: `vec3 Ews = normalize(transpose(mat3(u_ship_world_inv)) * u_pd_E); vec3 Nws = normalize(transpose(mat3(u_ship_world_inv)) * u_pd_N);` and let `vec4 s = pd_sample(...)` (h, gE, gN, a); `float land = (1.0 - m_s) * pd_w` with `m_s = 0` in this task (water arrives in Task 9); bump: `vec3 nb = n_shade - land * u_pd_strength * u_pd_p_bump * (s.y * Ews + s.z * Nws); float lb = length(nb); n_shade = lb > 1e-6 ? nb / lb : n_shade;`; albedo: `base.rgb *= exp(land * u_pd_albedo * u_pd_p_albedo * (s.x - 0.0) )` with `s.x` already zero-mean by construction (ridged term subtracts 0.5).
    - Debug (`u_pd_debug != 0`): `base.rgb = mix(base.rgb, level_tint(L), 0.5)` with tints red/green/blue/yellow/magenta for L0..L4.
  - `planet_detail_uniforms.cc::apply` — sets every uniform; binds `GL_TEXTURE12` to `atlas` then restores `glActiveTexture(GL_TEXTURE0)`. When `enabled == false` set only `u_pd_enabled = 0` (the program still has unit 12 pointing at whatever is bound — sampler2D only, never read).

- [ ] **Step 4: Run** the five tests, then the **FULL** `./build/native/tests/renderer/renderer_tests` → all pass (no filter).

- [ ] **Step 5: Commit** `-m "feat(renderer): PLANET_SURFACE opaque variant — clipmap sampling, transition bands, land relief"`

---

### Task 8: `PlanetDetailPass` — target selection, bake per frame, target draw through `planet_`

**Files:**
- Create: `native/src/renderer/include/renderer/planet_detail_pass.h`, `native/src/renderer/planet_detail_pass.cc`
- Modify: `native/src/renderer/frame.{h,cc}` (`submit_opaque_in_pass` + `configure_common`), `native/src/host/host_bindings.cc` (`frame()`: new top-level scope; teardown/reset)
- Test: `native/tests/renderer/planet_detail_pass_test.cc`

**Interfaces:**
- Consumes: Tasks 3, 4, 6, 7.
- Produces:

```cpp
namespace renderer::planet_detail {
struct Candidate { scenegraph::InstanceId id; glm::vec3 center_ws; float radius_gu; int bc_tex_w; };
// Index of the candidate to detail, or -1. Visible = nadir px per BC texel >= 2:
// (2*pi*R / bc_tex_w) / max(altitude, 1) * focal_px >= 2. Hysteresis: keep
// `current` unless another candidate's surface distance < 0.9 x current's.
int pick_target(const std::vector<Candidate>& c, const glm::vec3& cam_ws, float focal_px,
                std::optional<scenegraph::InstanceId> current);

class PlanetDetailPass {
public:
    // Once per frame, main camera only. Picks the target, (re)anchors, schedules
    // and bakes under the budget. GL current.
    void update(const scenegraph::World& world, const scenegraph::Camera& cam, int viewport_h,
                const std::function<const assets::Model*(scenegraph::ModelHandle)>& lookup);
    // Uniforms for drawing instance `id` (enabled only when id is the target).
    SampleUniforms uniforms_for(scenegraph::InstanceId id) const;
    std::optional<scenegraph::InstanceId> target() const;
    void reset();                                   // drop target + clipmap
    void set_budget(long long cost_units);          // default 65536*8
    void set_debug(bool on);
    long long last_cost() const;
};
}
```

- [ ] **Step 1: Failing tests**
  - `pick_target`: none visible far away (camera at 100·R) → -1; nearest by surface distance wins; hysteresis keeps current when the other is only 5% nearer, switches at 15%; a 140 GU moon at 150 GU altitude is visible.
  - `PlanetDetailPass` with a real `World` holding two geosphere planets (IcePlanet.NIF via content root, as in `atmosphere_surface_test.cc`), surface type Rocky on both:
    - camera 200 GU above planet A → `target() == A`; `uniforms_for(A).enabled`; `!uniforms_for(B).enabled`;
    - move camera above B (≥ 10% nearer) → target B and the schedule was reset (`valid` rects shrink — expose `debug_valid_area()` for the test);
    - destroy A's instance while it is the target → next `update` drops it without touching freed state;
    - `last_cost()` ≤ budget + one strip each frame over 120 frames of motion;
    - target with R = 140 → `uniforms_for(id).levels == 2`.
  - `FrameSubmitter`: draw a world with two surface planets in view through `submit_opaque_in_pass` with a pass whose target is A; B's pixels equal a render where no pass exists (byte-identical to today) — **Review Focus #1**.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**
  - `update`: build candidates from `world.for_each_visible_in_pass(Pass::Space, ...)` where `inst.surface.type != 0`, the model has a `sphere_map`, centre `inst.world * vec4(center_body,1)`, `R = sphere_map.radius * length(inst.world[0])`, `bc_tex_w` = width of the sphere mesh's base texture (look it up through the material's base texture; default 256). `focal_px = proj[1][1] * viewport_h / 2`. Pick; on change → reset. Planet-local camera: `p = (inverse(world) * cam) - center_body` scaled by `length(world[0])`. Anchor when empty or `needs_reanchor(to_plane(anchor, p), R)` → `make_anchor(normalize(p), R)` + schedule reset. If `shape_hash(live_params(type))` or `(scale, seed)` changed → reset. Budget = `budget * (schedule.complete() ? 1 : 2)`. `update` the schedule at `to_plane(anchor, normalize(p)*R)`; `atlas.bake(rects, BakeParams{...})`. Levels from `level_count_for(R, 0.1)`; octaves per level from `octaves_for_texel`. Atlas recreated only when the level count changes.
  - `uniforms_for`: fill `SampleUniforms` from the target instance's `Surface`, `live_params(type)`, schedule valid rects, anchor, `scale_local = length(world[0])`.
  - `frame.cc::submit_opaque_in_pass`: give it a `const planet_detail::PlanetDetailPass* detail` parameter (default `nullptr`; update the two other call sites / tests that construct it only if the signature requires). Call `configure_common(pipeline.planet_shader())` too. Per instance: if `detail && detail->target() == inst.id && m->sphere_map && level >= 0` → `apply(pipeline.planet_shader(), detail->uniforms_for(inst.id))` and pass `pipeline.planet_shader()` as `draw_model`'s static shader; else exactly today's call.
  - `host_bindings.cc`: global `std::unique_ptr<renderer::planet_detail::PlanetDetailPass> g_planet_detail;` created beside `g_atmosphere_pass` (line ~971), reset beside its reset (~1054). In `frame()` after the `shadow` block and before the viewscreen RTT: `{ DAUNTLESS_FRAME_SCOPE("planet_detail"); g_planet_detail->update(g_world, g_camera, fh, lookup); }` (top-level ⇒ GPU-timed). Pass `g_planet_detail.get()` to `submit_opaque_in_pass` (~line 1428). Also call `g_planet_detail->reset()` wherever the world is cleared on mission swap (grep `g_world.clear` / the atmosphere live-registry clear points on the native side).

- [ ] **Step 4: Run** the new tests + FULL `renderer_tests` + `uv run pytest tests/host -q` → PASS.

- [ ] **Step 5: Commit** `-m "feat(renderer): planet_detail pass — target pick, per-frame budgeted bake, target drawn through planet_"`

---

### Task 9: Water, ice and gas shading

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (inside `#ifdef PLANET_SURFACE`)
- Test: `native/tests/renderer/planet_surface_draw_test.cc` (append)

**Interfaces:** Consumes Task 7's uniforms; no new C++ API.

- [ ] **Step 1: Failing tests** (append; reuse Task 7's harness):
  1. `WaterMaskFollowsOceanKey` — base texture solid `#405870`, `has_ocean` with that key: the land bump is suppressed (pixels equal a `strength=0` render) and a sun placed in the mirror direction produces a brighter centre pixel than with `has_ocean=false`.
  2. `OceanTypeIsAllWater` — `type=Ocean`: no bump (equal to `strength=0` render) but glint present.
  3. `GasHasNoBumpAndAnimates` — `type=Gas`: rendering with `strength=4` equals `strength=0` in normal-only probe (n_shade unchanged; compare a render with the sun at grazing incidence); two renders at `u_decal_time` 0 and 5 s differ; with `gas_rate=0` they are equal.
  4. `IceCracksDarken` — `type=Ice` atlas with A=1 everywhere renders darker on average than with A=0.
  5. Re-run `FiniteEverywhere` for each type.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** (spec §6):
  - Water mask before the land block: `vec3 bl = base.rgb;` (already linear — the base sampler is sRGB-decoded; confirm with the existing pipeline, else convert); `float m = u_pd_has_ocean != 0 ? 1.0 - smoothstep(0.5*u_pd_ocean_tol, 1.5*u_pd_ocean_tol, length(bl - u_pd_ocean)) : 0.0;` `float m_s = smoothstep(0.5 - u_pd_p_coast_k, 0.5 + u_pd_p_coast_k, m + u_pd_p_coast_a * s.x);` when `u_pd_p_coast_k == 0` use `m_s = m`; `if (u_pd_type == 5) m_s = 1.0;` coast pull: `base.rgb = mix(base.rgb, u_pd_ocean, max(m_s - m, 0.0) * pd_w);`.
  - Land weight `(1 - m_s) * pd_w` (replace Task 7's `m_s = 0`).
  - Water specular, added to `lit` after the existing lighting sum and **before** the atmosphere block: `float rough = clamp(u_pd_p_roughness * (1.0 + u_pd_p_roughness_var * (s.w - 0.5)), 0.02, 1.0);` GGX D with `α = rough²`, Smith-Schlick G, Schlick F with f0 = 0.02, light = directional 0 (`u_dir_light_dir_ws[0]`, `u_dir_light_color[0]`) using geometric `n`; `lit += m_s * pd_w * spec * NdotL * u_dir_light_color[0];` all terms clamped finite.
  - Ice: `if (u_pd_type == 3) base.rgb *= mix(vec3(1.0), vec3(0.80, 0.86, 1.0), s.w * land_w);` and water roughness for ice sheen uses `u_pd_p_roughness` (already low in the table).
  - Gas (`u_pd_type == 4`): skip the bump entirely; advect the sample: `vec3 east = normalize(cross(vec3(0,0,1), pd_dir))` (guard poles: zero offset when `length < 1e-4`); `lat = asin(pd_dir.z)`; `flow = u_pd_p_gas_rate_gups * (0.6*sin(3.0*lat + seedphase) + 0.4*sin(7.0*lat + 2.0*seedphase))` with `seedphase = float(u_pd_seed % 628u) * 0.01`; `ph = fract(u_decal_time / u_pd_p_gas_period_s)`; offsets `o1 = flow*ph*P`, `o2 = flow*fract(ph+0.5)*P` (P = period) along `east` projected onto the plane (`vec2(dot(east,E), dot(east,N))`); sample twice; `h = mix(h1, h2_from_A_channel, abs(2*ph - 1))` (phase 2 uses the A field); albedo modulation only.
  - Debug tint unchanged.

- [ ] **Step 4: Run** new tests + **FULL** `renderer_tests` → PASS.

- [ ] **Step 5: Commit** `-m "feat(renderer): planet surface water glint and coasts, ice cracks, gas advection"`

---

### Task 10: Developer tooling — toggles, dial group, reload

**Files:**
- Create: `engine/planets/surface_dials.py`
- Modify: `engine/ui/developer_options_panel.py` (+ its JS/HTML if rows are declared there — mirror the `planet_atmosphere` / `reload_atmospheres` rows exactly), `native/src/host/host_bindings.cc` (tuning bindings), `engine/host_loop.py` (dial wiring at boot, mirroring the atmosphere dial wiring)
- Test: `tests/unit/test_planet_surface_dials.py`, and the existing `test_every_setting_is_in_the_render_snapshot`

**Interfaces:**
- Bindings: `planet_detail_target_type() -> int` (0 = none), `get_surface_type_params(type: int) -> dict[str, float]`, `set_surface_type_params(type: int, params: dict) -> None` (writes `live_params`; unknown keys raise), `set_planet_detail_budget(cost: int)`, `set_planet_detail_debug(on: bool)`.
- `surface_dials.py`: `DIAL_ORDER = ("strength", "albedo", "scale", "bump", "roughness", "coast_k", "ocean_tolerance", "gas_rate_gups", "gas_period_s", "budget")` — `bump`, `roughness`, `coast_k`, `gas_*` edit the **type table** via `set_surface_type_params`; `strength`, `albedo`, `scale`, `ocean_tolerance` edit the target planet's **catalogue entry** override and re-push `set_instance_surface` to every live planet resolving to that key (as `atmosphere_dials` does); `budget` calls `set_planet_detail_budget`. Steps: strength/albedo/bump 0.05, scale 0.05, roughness 0.02, coast_k 0.01, ocean_tolerance 0.01, gas_rate 0.05, gas_period 5, budget ×/÷ 2. `repush_live()` re-resolves every `surface.live()` entry.

- [ ] **Step 1: Failing tests** — mirror `tests/unit/test_planet_atmosphere_dials.py`: registers as `"surface"`; with no target `current()` is `{}`; stepping `bump` calls a fake `set_surface_type_params` with the incremented value for the target's type; stepping `strength` re-pushes to every live planet with the same key and leaves others alone; clamps at ranges (spec §7). Developer Options: `toggle:planet_surface` flips `engine.planet_surface.enabled()`; `toggle:surface_debug` calls the debug binding; `action:reload_surfaces` reloads the catalogue and calls `repush_live`; snapshot test includes both toggles.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** following `atmosphere_dials.py` and the panel's atmosphere rows line for line. Row labels: "Planet Surface Detail (off = BC texture only; applies to planets realized after toggling)", "Surface Detail Debug (tint by clipmap level)", "Reload Planet Surfaces".

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_planet_surface_dials.py tests/ui -q -k "developer or surface"` and the snapshot test → PASS.

- [ ] **Step 5: Commit** `-m "feat(dev): planet surface toggles, surface dial group, reload action"`

---

### Task 11: Performance bench with budgets

**Files:**
- Create: `native/tests/renderer/planet_detail_bench_test.cc` (add to CMakeLists)
- Test: itself

- [ ] **Step 1: Write the bench** (it is the test). Model gating/skip behaviour on `rock_near_bench_test.cc` (same skip rules when GL/content is absent). Offscreen 3840×1200 RGBA16F target; IcePlanet.NIF geosphere instance scaled to R = 3600 with `Surface{type=Rocky}`; camera 270 GU above, tilted 15°. Segments: cold 120 frames, still 240, orbit 6 GU/s 300, fast 60 GU/s 300, dash 400 GU/s 300, cut (re-anchor) 120 — moving the camera along the surface at 60 Hz steps. Time `PlanetDetailPass::update` and the planet draw each frame with `GL_TIME_ELAPSED` queries (blocking read is fine). Print a table like the spike. Assert: bake p95 ≤ 0.35 ms and max ≤ 0.6 ms; planet draw p50 with detail − planet draw p50 with `enabled=false` ≤ 0.35 ms. Skip the timing asserts (but still run and print) when `GL_QUERY_COUNTER_BITS` for `GL_TIME_ELAPSED` is 0.

- [ ] **Step 2: Run** `--gtest_filter=PlanetDetailBench.*`. If a budget fails, report the table — do not loosen the budget without saying so in the commit message and the final report.

- [ ] **Step 3: Commit** `-m "test(renderer): planet detail bench — bake and sampling budgets on GL_TIME_ELAPSED"`

---

### Task 12: Docs, gate, hand-off for live calibration

**Files:**
- Modify: `CLAUDE.md` (new row after "Planet atmospheres"), `docs/superpowers/specs/2026-10-08-planet-surface-detail-design.md` (append "As built" notes: deviations, bench table), `docs/engine/frame-profiler.md` (one line: `planet_detail` is a top-level GPU-timed scope)

- [ ] **Step 1:** CLAUDE.md row: `| Planet surface detail — procedural detail over BC maps via a budgeted clipmap | engine/planets/surface.py, native/src/renderer/{planet_detail_noise,planet_clipmap_schedule,planet_clipmap_atlas,planet_detail_pass}.{h,cc}, shaders/planet_bake.frag, opaque.frag #ifdef PLANET_SURFACE, docs/superpowers/specs/2026-10-08-planet-surface-detail-design.md | ONE target planet (nearest, detail visible) gets a 5×1024² toroidal clipmap baked under a fixed cost budget per frame (top-level planet_detail scope, GPU-timed); its sphere-LOD draw uses the planet_ program (opaque.frag + PLANET_SURFACE) — every other draw byte-identical. surface key in atmospheres.json resolves independently of the air; atmosphere:false keeps surface. Per-type defaults in planet_detail_noise's table; dials "surface" on / L O. planet_bake.frag is the GLSL twin of planet_detail_noise.cc — change both. ⚠️ Not live-verified until Mark calibrates by eye. |`
- [ ] **Step 2:** Run `scripts/check_tests.sh` → exits 0. Fix anything it names (never baseline).
- [ ] **Step 3:** Commit `-m "docs(planets): surface detail as built"`.
