# Planet Atmosphere Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give planets a scattering shell (a halo past the limb, brightest toward the sun), a Fresnel-limb surface haze and a tinted terminator, driven by a JSON catalogue keyed by NIF stem or by `"<set>/<name>"`.

**Architecture:**
- **Catalogue.** A Python catalogue (`engine/planets/atmosphere.py` + `native/assets/planets/atmospheres.json`) resolves each realized planet. The result is pushed to a new per-instance `scenegraph::Instance::Atmosphere` via `set_instance_atmosphere`.
- **Shared maths.** A GL-free C++ module (`renderer::planet_atmo`) holds the ray/shell, optical-depth and in-scatter maths. `atmosphere.frag` mirrors it.
- **Shell pass.** A new `AtmospherePass` draws a shell per planet in **phase 2** (`render_space_vfx`: single-sample, sampleable scene depth). The march therefore ends at the nearest opaque surface.
- **Surface term.** `opaque.frag`'s geosphere branch gains the limb haze and terminator term.
- **Dev tools.** A dev toggle, a Reload action and an `"atmosphere"` dial group support live tuning.

**Tech Stack:** C++20, OpenGL 4.1 / GLSL 410, GLM, GoogleTest, pybind11, Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md`. Stacked on `feat/planet-geosphere`; its spec is `docs/superpowers/specs/2026-10-06-planet-geosphere-design.md`.

## Global Constraints

- **Worktree:** `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/planet-geosphere`, branch `feat/planet-atmosphere`. Never commit to `main` or to `feat/planet-geosphere`.
- **⛔ Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage only explicit pathspecs. For a temporary mutation: `cp file /tmp/bak`, then edit, then `cp /tmp/bak file`, then `diff file /tmp/bak`.
- **Build:** run `cmake --build build -j` from the worktree root. The tree is already configured Debug; never change the build type, and never run cmake from `native/`.
  - **Shader edits need a reconfigure** (`cmake -B build -S .`, no other flags) before building.
  - **Shader errors only appear at runtime.**
- **C++ tests:**
  - `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" ./build/native/tests/renderer/renderer_tests --gtest_filter=<pat>`
  - The same pattern for `./build/native/tests/scenegraph/scenegraph_tests` (find exact binary paths with `find build -name '*_tests' -type f`).
  - New tests must not SKIP.
- **Python tests:** `uv run pytest <path> -q`.
- **Asset paths:**
  - Never spell `game` or `sdk` as a path segment.
  - Never capture a path at import.
  - The catalogue resolves via `engine.paths.project_asset_root() / "planets" / "atmospheres.json"`, **evaluated at use**.
- **Catalogue keys (spec §3.1):**
  - **NIF stem:** basename of the NIF path, extension removed, `.casefold()`d.
  - **`"<set>/<name>"`:** exact and case-sensitive.
  - **No bare-name key.**
- **Entry fields (spec §3.2):**
  - `color` (`#RRGGBB`, sRGB, converted to linear)
  - `thickness` (0, 0.25]
  - `density` [0, 4]
  - `limb` [0, 4]
  - optional `sunset_color` (defaults to `color`)
  - `atmosphere: false` means airless
  - Unknown fields are rejected.
  - A malformed entry warns once per key and resolves to `None`.
- **Seed tiers (spec §3.4):**

  | Tier | thickness | density | limb |
  |---|---|---|---|
  | thick | 0.06 | 1.4 | 1.0 |
  | medium | 0.035 | 1.0 | 1.0 |
  | thin | 0.02 | 0.5 | 0.8 |

  Stems and colours are verbatim from spec §3.4. No per-planet overrides ship.
- **March constants:**
  - 8 view samples
  - scale height `H = 0.25·thickness·R`
  - extinction `σ = density / (thickness·R)`
  - phase = Rayleigh `3/(16π)(1+c²)` + 0.25 × HG(g = 0.6)
- **Byte-identical default:** an instance whose atmosphere is disabled (the default) renders exactly as before. `u_atmo_enabled` is set to 0 on every non-atmosphere mesh draw, because uniforms persist. The shell pass skips such instances.
- **NaN is a bug:** any NaN or Inf reaching the HDR target feeds bloom and shows as black squares. Every new shader guards degenerate intersections.
- **Test doubles mirror the real surface:** every fake renderer that realizes planets gains `set_instance_atmosphere(self, iid, params)`.
- **Gate before merge:** `scripts/check_tests.sh` exits 0, and `tests/known_failures.txt` gains no entries.

**Deviations from the spec, decided while planning:**
- **D1 (spec §5 order).** The shell draws in **phase 2** (`render_space_vfx`), sampling `target.depth_texture()`, with depth test **off**, instead of after `space.opaque` with depth test on.
  - Why: with only depth testing, a camera inside the shell (gas giants at 216 GU thickness versus 150 GU orbit) could not haze the planet disc, and ships inside the shell were overdrawn by the full air column.
  - Phase 2 is single-sample and runs for both the main view and the viewscreen render target.
- **D2 (spec §7).** `reload()` is a Developer Options **action row**, "Reload Planet Atmospheres", not a key. `dev_dial_groups.py` documents that `/ L O` are the only free keys.
- **D3 (spec §9).** Optical-depth accuracy: the sun-path optical depth uses **6** samples, and tests compare against a 256-step reference **within 5%** (the spec said 2-sample and 2%).
- **D4 (spec §7).** The dials tune the **catalogue entry** the nearest planet resolved to, re-pushing every live planet that shares it, so `pinkgasplanet` is tuned once for all nine uses.

Task 8 amends the spec text for D1–D4.

## Review Focus

1. **Camera inside the shell** (low orbit over a gas giant): haze must cover the planet disc and the sky without NaN. Test: Task 2 `AirSpan.CameraInsideShell*` and Task 4 `AtmospherePassTest.CameraInsideShellIsFiniteAndHazesTheDisc`.
2. **A ship between the camera and the planet:** the march must end at the ship's depth, not the planet surface. Test: Task 4 `AtmospherePassTest.OpaqueDepthEndsTheMarch`.
3. **The night side, and planets with no sun in the set:** no in-scatter behind the planet. With no sun, fall back to directional light 0 and never NaN. Tests: Task 2 `InScatter.NightSideIsDark` and `SunDir.NoSunsUsesFallback`.
4. **Uniform leak:** a ship drawn after a planet with an atmosphere must read `u_atmo_enabled == 0`. Test: Task 5 `AtmosphereSurfaceTest.FlagDoesNotLeakToNextDraw`.
5. **Recycled instance slots and mission swap:** a destroyed planet's atmosphere must not reappear, and the live registry must clear on teardown. `World::create_instance` resets the slot (`world.cc:18`). Test: Task 6 `test_live_registry_clears_on_teardown`.

---

### Task 1: Catalogue — `engine/planets/atmosphere.py` + seed JSON

**Files:**
- Create: `engine/planets/__init__.py` (empty, with a one-line docstring)
- Create: `engine/planets/atmosphere.py`
- Create: `native/assets/planets/atmospheres.json`
- Create: `tests/unit/test_planet_atmosphere_catalogue.py`
- Modify: `tests/conftest.py`, beside the `planet_geosphere` reset (~1569): add `atmosphere._memo.clear(); atmosphere._warned.clear()`.

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Atmosphere:
      color: tuple[float, float, float]         # linear RGB
      sunset_color: tuple[float, float, float]  # linear RGB
      thickness: float
      density: float
      limb: float
  def nif_stem(nif_path: str) -> str
  def catalogue_path() -> pathlib.Path
  def load() -> dict[str, object]                 # raw entries, memoised per path
  def reload() -> None                            # drop memo + warnings
  def resolve(set_name: str, obj_name: str, nif_path: str) -> Atmosphere | None
  def resolve_key(set_name: str, obj_name: str, nif_path: str) -> str | None   # the key that matched
  def parse_entry(key: str, entry: dict) -> Atmosphere | None   # raises ValueError on malformed
  def srgb_hex_to_linear(hex_str: str) -> tuple[float, float, float]
  STOCK_STEMS: tuple[str, ...]   # every stock planet NIF stem, from spec §3.4
  ```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_planet_atmosphere_catalogue.py`:

```python
"""Planet atmosphere catalogue (spec docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md §3)."""
import json

import pytest

from engine.planets import atmosphere as atmo


def _write(tmp_path, monkeypatch, data):
    root = tmp_path / "assets"
    (root / "planets").mkdir(parents=True)
    (root / "planets" / "atmospheres.json").write_text(json.dumps(data))
    monkeypatch.setattr("engine.paths.project_asset_root", lambda: root)
    atmo.reload()


GAS = {"color": "#FF9A96", "thickness": 0.06, "density": 1.4, "limb": 1.0}


def test_nif_stem_casefolds_and_drops_extension():
    assert atmo.nif_stem("data/models/environment/GreenPurplePlanet.nif") == "greenpurpleplanet"
    assert atmo.nif_stem("/abs/Environment/GreenPurplePlanet.NIF") == "greenpurpleplanet"


def test_srgb_hex_to_linear():
    assert atmo.srgb_hex_to_linear("#FFFFFF") == pytest.approx((1.0, 1.0, 1.0))
    assert atmo.srgb_hex_to_linear("#000000") == pytest.approx((0.0, 0.0, 0.0))
    r, _, _ = atmo.srgb_hex_to_linear("#808080")
    assert r == pytest.approx(0.2158605, abs=1e-5)


def test_stem_entry_resolves(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": GAS})
    a = atmo.resolve("Geble3", "Geble 3", "data/models/environment/PinkGasPlanet.nif")
    assert a is not None and a.thickness == 0.06 and a.density == 1.4 and a.limb == 1.0
    assert a.sunset_color == a.color


def test_set_name_override_wins_over_stem(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": GAS, "Geble3/Geble 3": {"atmosphere": False}})
    assert atmo.resolve("Geble3", "Geble 3", "x/PinkGasPlanet.nif") is None
    assert atmo.resolve("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif") is not None
    assert atmo.resolve_key("Geble3", "Geble 3", "x/PinkGasPlanet.nif") == "Geble3/Geble 3"
    assert atmo.resolve_key("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif") == "pinkgasplanet"


def test_bare_name_is_not_a_key(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"Geble 3": GAS})
    assert atmo.resolve("Geble3", "Geble 3", "x/RockyPlanet.nif") is None


def test_override_key_is_case_sensitive(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"geble3/geble 3": GAS})
    assert atmo.resolve("Geble3", "Geble 3", "x/RockyPlanet.nif") is None


def test_missing_is_none(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {})
    assert atmo.resolve("S", "N", "x/Unknown.nif") is None
    assert atmo.resolve_key("S", "N", "x/Unknown.nif") is None


@pytest.mark.parametrize("bad", [
    {"color": "#FF9A96", "thickness": 0.06, "density": 1.4},                # missing limb
    {**GAS, "thickness": 0.0},                                               # out of range
    {**GAS, "thickness": 0.3},
    {**GAS, "density": 5.0},
    {**GAS, "limb": -1.0},
    {**GAS, "color": "pink"},
    {**GAS, "surface": "gas"},                                               # unknown field
])
def test_malformed_entry_warns_once_and_is_none(tmp_path, monkeypatch, capsys, bad):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": bad})
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    err = capsys.readouterr().err
    assert err.count("pinkgasplanet") == 1


def test_missing_file_is_empty_and_warns_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("engine.paths.project_asset_root", lambda: tmp_path / "nowhere")
    atmo.reload()
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    assert capsys.readouterr().err.count("atmospheres.json") == 1


def test_path_is_resolved_at_use(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": GAS})
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is not None
    other = tmp_path / "other"
    (other / "planets").mkdir(parents=True)
    (other / "planets" / "atmospheres.json").write_text("{}")
    monkeypatch.setattr("engine.paths.project_asset_root", lambda: other)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None   # memo is keyed by path


def test_shipped_catalogue_is_valid_and_covers_every_stock_stem():
    atmo.reload()
    raw = atmo.load()
    assert set(atmo.STOCK_STEMS) <= set(raw)
    for key, entry in raw.items():
        atmo.parse_entry(key, entry)          # raises on malformed
    assert not any("/" in k for k in raw), "spec §3.4: no per-planet overrides ship"


def test_shipped_tiers_match_the_spec():
    atmo.reload()
    a = atmo.resolve("S", "N", "x/PinkGasPlanet.nif")
    assert (a.thickness, a.density, a.limb) == (0.06, 1.4, 1.0)
    a = atmo.resolve("S", "N", "x/GreenPurplePlanet.nif")
    assert (a.thickness, a.density, a.limb) == (0.035, 1.0, 1.0)
    a = atmo.resolve("S", "N", "x/IcePlanet.nif")
    assert (a.thickness, a.density, a.limb) == (0.02, 0.5, 0.8)
    for airless in ("moon", "rockyplanet", "grayplanet", "tanplanet"):
        assert atmo.resolve("S", "N", f"x/{airless}.nif") is None
```

- [ ] **Step 2: Run them and expect FAIL** (`ModuleNotFoundError: engine.planets`).

Run: `uv run pytest tests/unit/test_planet_atmosphere_catalogue.py -q`

- [ ] **Step 3: Implement `engine/planets/atmosphere.py`**

```python
"""Planet atmosphere catalogue (spec docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md §3).

Keys are a NIF stem (case-folded basename, no extension) -- the default for
every planet using that NIF -- or "<set>/<name>", BC's own identity for one
planet (AddSet name + AddObjectToSet name), which wins. A bare object name is
not a key: "Moon 1" exists in three sets. The JSON lives under the project
asset root and is resolved at USE, never at import.
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass

_memo: dict = {}      # str(path) -> dict of raw entries
_warned: set = set()  # (str(path), key) already reported

_FIELDS = {"color", "sunset_color", "thickness", "density", "limb", "atmosphere"}

STOCK_STEMS: tuple = (
    "pinkgasplanet", "bluewhitegasplanet", "tangasplanet", "gasgiant",
    "greenpurpleplanet", "purpleplanet", "purplewhiteplanet", "aquaplanet", "planet",
    "brownblueplanet", "snowplanet", "greenplanet", "slimegreenplanet",
    "bluegrayplanet", "bluetanplanet", "turquoiseplanet", "brightgreenplanet",
    "earth", "lavenderplanet",
    "bluerockyplanet", "brownplanet", "dryplanet", "iceplanet", "redplanet",
    "sulfurplanet", "rootbeerplanet", "redswirlplanet",
    "moon", "rockyplanet", "grayplanet", "tanplanet",
)


@dataclass(frozen=True)
class Atmosphere:
    color: tuple
    sunset_color: tuple
    thickness: float
    density: float
    limb: float


def nif_stem(nif_path: str) -> str:
    return pathlib.PurePath(nif_path.replace("\\", "/")).stem.casefold()


def srgb_hex_to_linear(hex_str: str) -> tuple:
    if not (isinstance(hex_str, str) and len(hex_str) == 7 and hex_str[0] == "#"):
        raise ValueError(f"colour must be '#RRGGBB', got {hex_str!r}")
    out = []
    for i in (1, 3, 5):
        c = int(hex_str[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def catalogue_path() -> pathlib.Path:
    from engine import paths
    return pathlib.Path(paths.project_asset_root()) / "planets" / "atmospheres.json"


def _warn(path_key: str, key: str, msg: str) -> None:
    if (path_key, key) not in _warned:
        _warned.add((path_key, key))
        print(f"[atmosphere] {key}: {msg}", file=sys.stderr)


def load() -> dict:
    path = catalogue_path()
    key = str(path)
    if key in _memo:
        return _memo[key]
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object")
    except (OSError, ValueError) as e:
        _warn(key, "atmospheres.json", f"unreadable ({e}); every planet is airless")
        raw = {}
    _memo[key] = raw
    return raw


def reload() -> None:
    _memo.clear()
    _warned.clear()


def _num(entry: dict, name: str, lo: float, hi: float, lo_open: bool = False) -> float:
    v = entry[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} must be a number")
    v = float(v)
    if (v <= lo if lo_open else v < lo) or v > hi:
        raise ValueError(f"{name}={v} out of range")
    return v


def parse_entry(key: str, entry: dict):
    if not isinstance(entry, dict):
        raise ValueError("entry must be an object")
    unknown = set(entry) - _FIELDS
    if unknown:
        raise ValueError(f"unknown field(s) {sorted(unknown)}")
    if entry.get("atmosphere") is False:
        return None
    color = srgb_hex_to_linear(entry["color"])
    sunset = srgb_hex_to_linear(entry["sunset_color"]) if "sunset_color" in entry else color
    return Atmosphere(
        color=color, sunset_color=sunset,
        thickness=_num(entry, "thickness", 0.0, 0.25, lo_open=True),
        density=_num(entry, "density", 0.0, 4.0),
        limb=_num(entry, "limb", 0.0, 4.0),
    )


def resolve_key(set_name: str, obj_name: str, nif_path: str):
    raw = load()
    override = f"{set_name}/{obj_name}"
    if set_name and override in raw:
        return override
    stem = nif_stem(nif_path)
    return stem if stem in raw else None


def resolve(set_name: str, obj_name: str, nif_path: str):
    key = resolve_key(set_name, obj_name, nif_path)
    if key is None:
        return None
    try:
        return parse_entry(key, load()[key])
    except (ValueError, KeyError, TypeError) as e:
        _warn(str(catalogue_path()), key, f"malformed ({e}); treated as airless")
        return None
```

- [ ] **Step 4: Write `native/assets/planets/atmospheres.json`.** Use exactly the spec §3.4 stems, colours and tiers. Write one key per line, sorted by tier and then as listed in the spec:

```json
{
  "pinkgasplanet":      {"color": "#FF9A96", "thickness": 0.06,  "density": 1.4, "limb": 1.0},
  "bluewhitegasplanet": {"color": "#BFE6FF", "thickness": 0.06,  "density": 1.4, "limb": 1.0},
  "tangasplanet":       {"color": "#E8D2B0", "thickness": 0.06,  "density": 1.4, "limb": 1.0},
  "gasgiant":           {"color": "#E6EADC", "thickness": 0.06,  "density": 1.4, "limb": 1.0},
  "greenpurpleplanet":  {"color": "#9FB0FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "purpleplanet":       {"color": "#8F93FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "purplewhiteplanet":  {"color": "#A8A4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "aquaplanet":         {"color": "#8EC8FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "planet":             {"color": "#87B4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "brownblueplanet":    {"color": "#9CC4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "snowplanet":         {"color": "#A8CCFF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "greenplanet":        {"color": "#C8D27A", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "slimegreenplanet":   {"color": "#B8C87A", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "bluegrayplanet":     {"color": "#9CC8E0", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "bluetanplanet":      {"color": "#9CC4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "turquoiseplanet":    {"color": "#8ED8E0", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "brightgreenplanet":  {"color": "#8EE0D0", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "earth":              {"color": "#87B4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "lavenderplanet":     {"color": "#B0A8FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "bluerockyplanet":    {"color": "#7F9CFF", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "brownplanet":        {"color": "#E0B080", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "dryplanet":          {"color": "#F0DCB0", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "iceplanet":          {"color": "#CFE0FF", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "redplanet":          {"color": "#E08A50", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "sulfurplanet":       {"color": "#E8E08A", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "rootbeerplanet":     {"color": "#E8C8B0", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "redswirlplanet":     {"color": "#E09070", "thickness": 0.02,  "density": 0.5, "limb": 0.8},
  "moon":               {"atmosphere": false},
  "rockyplanet":        {"atmosphere": false},
  "grayplanet":         {"atmosphere": false},
  "tanplanet":          {"atmosphere": false}
}
```

- [ ] **Step 5: Add the conftest reset.** Beside the planet_geosphere block:

```python
    try:
        from engine.planets import atmosphere as _planet_atmosphere
        _planet_atmosphere._memo.clear()
        _planet_atmosphere._warned.clear()
    except Exception:
        pass
```

- [ ] **Step 6: Run and expect PASS.** Then run `uv run pytest tests/unit/test_path_indirection.py -q` (the path guard).

- [ ] **Step 7: Commit**

```bash
git add engine/planets/__init__.py engine/planets/atmosphere.py native/assets/planets/atmospheres.json tests/unit/test_planet_atmosphere_catalogue.py tests/conftest.py
git commit -m "feat(planets): atmosphere catalogue — NIF-stem defaults, set/name overrides, seed tiers"
```

---

### Task 2: GL-free atmosphere maths — `renderer::planet_atmo`

**Files:**
- Create: `native/src/renderer/include/renderer/atmosphere_math.h`
- Create: `native/src/renderer/atmosphere_math.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `atmosphere_math.cc` to `add_library(renderer ...)`)
- Create: `native/tests/renderer/atmosphere_math_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add the test source)

**Interfaces:**
- Consumes: `renderer::SunDescriptor` (`frame.h:83-89`, position in render space).
- Produces (namespace `renderer::planet_atmo`; `renderer::atmosphere` is taken by the nebula kit):
  ```cpp
  inline constexpr int   kViewSamples = 8;
  inline constexpr int   kSunSamples  = 6;
  inline constexpr float kOpaqueTau   = 1.0e4f;   // sun ray blocked by the planet
  struct Shell { glm::vec3 center; float r_planet; float r_top; };
  struct Params { glm::vec3 color; float thickness; float density; };
  struct Span { bool hit = false; float t0 = 0.0f; float t1 = 0.0f; };
  Span  air_span(const Shell& s, glm::vec3 origin, glm::vec3 dir, float t_max);
  float scale_height(const Shell& s);                 // 0.25 * (r_top - r_planet)
  float sigma(const Shell& s, const Params& p);       // density / (r_top - r_planet)
  float rho(const Shell& s, glm::vec3 p);             // exp(-h/H), h = |p-c| - r_planet, clamped >= 0
  float sun_tau(const Shell& s, const Params& p, glm::vec3 x, glm::vec3 sun_dir);
  float phase(float cos_theta);                       // 3/(16pi)(1+c^2) + 0.25*hg(0.6, c)
  glm::vec3 in_scatter(const Shell& s, const Params& p, glm::vec3 origin, glm::vec3 dir,
                       float t_max, glm::vec3 sun_dir);   // times sun colour by the caller
  glm::vec3 sun_dir_for(glm::vec3 center, const std::vector<SunDescriptor>& suns,
                        glm::vec3 fallback_dir_ws);       // unit, toward the light
  ```
  `t_max` is the distance along `dir` to the nearest opaque surface (scene depth); pass `INFINITY` for none.

- [ ] **Step 1: Write the failing tests** (`native/tests/renderer/atmosphere_math_test.cc`):

```cpp
// native/tests/renderer/atmosphere_math_test.cc
#include <renderer/atmosphere_math.h>
#include <renderer/frame.h>

#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <cmath>
#include <limits>

namespace pa = renderer::planet_atmo;
static const float kInf = std::numeric_limits<float>::infinity();
static pa::Shell shell() { return {glm::vec3(0.0f), 100.0f, 106.0f}; }
static pa::Params params() { return {glm::vec3(1.0f), 0.06f, 1.4f}; }

TEST(AirSpan, MissesEntirely) {
    auto s = pa::air_span(shell(), {0, -500, 200}, {0, 1, 0}, kInf);
    EXPECT_FALSE(s.hit);
}

TEST(AirSpan, GrazesShellOnly) {
    // Ray at height 103 (between planet and top): passes through air, never the planet.
    auto s = pa::air_span(shell(), {-500, 103, 0}, {1, 0, 0}, kInf);
    ASSERT_TRUE(s.hit);
    const float half = std::sqrt(106.0f * 106.0f - 103.0f * 103.0f);
    EXPECT_NEAR(s.t0, 500.0f - half, 1e-2f);
    EXPECT_NEAR(s.t1, 500.0f + half, 1e-2f);
}

TEST(AirSpan, EndsAtThePlanetSurface) {
    auto s = pa::air_span(shell(), {-500, 0, 0}, {1, 0, 0}, kInf);
    ASSERT_TRUE(s.hit);
    EXPECT_NEAR(s.t0, 500.0f - 106.0f, 1e-3f);
    EXPECT_NEAR(s.t1, 500.0f - 100.0f, 1e-3f);
}

TEST(AirSpan, CameraInsideShellStartsAtTheCamera) {
    auto s = pa::air_span(shell(), {0, 103, 0}, {1, 0, 0}, kInf);
    ASSERT_TRUE(s.hit);
    EXPECT_FLOAT_EQ(s.t0, 0.0f);
    EXPECT_NEAR(s.t1, std::sqrt(106.0f * 106.0f - 103.0f * 103.0f), 1e-2f);
}

TEST(AirSpan, CameraInsideShellLookingDownEndsAtSurface) {
    auto s = pa::air_span(shell(), {0, 103, 0}, {0, -1, 0}, kInf);
    ASSERT_TRUE(s.hit);
    EXPECT_FLOAT_EQ(s.t0, 0.0f);
    EXPECT_NEAR(s.t1, 3.0f, 1e-3f);
}

TEST(AirSpan, OpaqueDepthClipsTheSpan) {
    auto s = pa::air_span(shell(), {-500, 103, 0}, {1, 0, 0}, 480.0f);
    ASSERT_TRUE(s.hit);
    EXPECT_FLOAT_EQ(s.t1, 480.0f);
    auto none = pa::air_span(shell(), {-500, 103, 0}, {1, 0, 0}, 100.0f);
    EXPECT_FALSE(none.hit);   // the opaque surface is before the shell
}

TEST(AirSpan, Tangent) {
    auto s = pa::air_span(shell(), {-500, 106, 0}, {1, 0, 0}, kInf);
    if (s.hit) EXPECT_NEAR(s.t1 - s.t0, 0.0f, 0.5f);
}

TEST(SunTau, MatchesA256StepReferenceWithin5Percent) {
    const auto s = shell(); const auto p = params();
    const glm::vec3 x(0, 102.0f, 0), L = glm::normalize(glm::vec3(1, 0.3f, 0));
    // Reference: 256 midpoint samples to the shell exit.
    const pa::Span out = pa::air_span(s, x, L, kInf);
    ASSERT_TRUE(out.hit);
    const float len = out.t1;
    double ref = 0.0;
    for (int i = 0; i < 256; ++i) {
        const float t = (i + 0.5f) * len / 256.0f;
        ref += pa::rho(s, x + L * t) * (len / 256.0f);
    }
    ref *= pa::sigma(s, p);
    EXPECT_NEAR(pa::sun_tau(s, p, x, L), ref, 0.05 * ref);
}

TEST(SunTau, BlockedByThePlanet) {
    EXPECT_GE(pa::sun_tau(shell(), params(), {0, 101.0f, 0}, {0, -1, 0}), pa::kOpaqueTau);
}

TEST(InScatter, NightSideIsDark) {
    // Both rays run along +Z through the shell at height 103 (shell air only,
    // |z| <= sqrt(106^2-103^2) ~ 25, never the planet).
    // Lit: the ray sits on the +Y side and the sun is +Y -- every sample sees the sun.
    const auto lit = pa::in_scatter(shell(), params(), {0, 103, -500}, {0, 0, 1}, kInf, {0, 1, 0});
    // Dark: the ray sits on the +X side and the sun is -X -- every sample's sun
    // ray crosses the planet (|y|,|z| < 100), so it is in shadow.
    const auto dark = pa::in_scatter(shell(), params(), {103, 0, -500}, {0, 0, 1}, kInf, {-1, 0, 0});
    EXPECT_GT(lit.r, 0.0f);
    EXPECT_LT(dark.r, 1e-6f);
}

TEST(InScatter, FiniteForDegenerateInputs) {
    for (glm::vec3 o : {glm::vec3(0), glm::vec3(0, 100, 0), glm::vec3(0, 106, 0)}) {
        const auto v = pa::in_scatter(shell(), params(), o, {0, 1, 0}, kInf, {1, 0, 0});
        EXPECT_TRUE(std::isfinite(v.r) && std::isfinite(v.g) && std::isfinite(v.b));
    }
    const auto z = pa::in_scatter({glm::vec3(0), 100.0f, 100.0f}, params(), {0, 0, -500}, {0, 0, 1}, kInf, {1, 0, 0});
    EXPECT_TRUE(std::isfinite(z.r));
}

TEST(Phase, ForwardScatterIsStrongerThanSide) {
    EXPECT_GT(pa::phase(1.0f), pa::phase(0.0f));
    EXPECT_GT(pa::phase(0.0f), 0.0f);
}

TEST(SunDir, PointsFromPlanetToNearestSun) {
    std::vector<renderer::SunDescriptor> suns(2);
    suns[0].position = {1000, 0, 0};
    suns[1].position = {0, 50000, 0};
    const glm::vec3 d = pa::sun_dir_for({0, 0, 0}, suns, {0, 0, 1});
    EXPECT_NEAR(d.x, 1.0f, 1e-5f);
}

TEST(SunDir, NoSunsUsesFallback) {
    const glm::vec3 d = pa::sun_dir_for({0, 0, 0}, {}, {0, 0, 2});
    EXPECT_NEAR(d.z, 1.0f, 1e-5f);
    const glm::vec3 z = pa::sun_dir_for({0, 0, 0}, {}, {0, 0, 0});
    EXPECT_TRUE(std::isfinite(z.x) && glm::length(z) > 0.99f);
}
```

- [ ] **Step 2: Build and expect a compile failure** (missing header).

- [ ] **Step 3: Implement.** `atmosphere_math.cc`:
- **`air_span`:** intersect the ray with the `r_top` sphere (`t_top0`, `t_top1`) and the `r_planet` sphere (`t_p0`).
  - `t0 = max(t_top0, 0)`, `t1 = t_top1`.
  - If the ray hits the planet with `t_p0 > 0`: `t1 = min(t1, t_p0)`.
  - `t1 = min(t1, t_max)`. `hit = t1 > t0`.
  - When the discriminant is ≤ 0, `hit = false`.
- **`rho`:** `exp(-max(len(p-c) - r_planet, 0) / H)`.
- **`sun_tau`:**
  - If the ray `x + L·t` hits the planet sphere at `t > 1e-4`, return `kOpaqueTau`.
  - Otherwise take `kSunSamples` midpoint samples of `rho` over `[0, exit of r_top]`, multiplied by `sigma`.
- **`phase`:** `3/(16π)(1+c²) + 0.25 * hg(0.6, c)`, with `hg(g, c) = (1-g²) / (4π·max(1e-6, 1+g²-2gc)^1.5)`. This mirrors `nebula_atmosphere.cc:56-60`; re-implement it locally in an anonymous namespace rather than including the nebula header.
- **`in_scatter`:**
  - Take `air_span`; if not hit, return 0.
  - Step `Δs = (t1-t0)/kViewSamples`, accumulating `τ_view += σ·ρ·Δs` (midpoint).
  - Each sample contributes `ρ · exp(-(τ_view_mid + sun_tau)) · σ · Δs`.
  - Multiply the sum by `phase(dot(dir, sun_dir)) · color`.
  - Guard: if `r_top <= r_planet`, return 0.
- **`sun_dir_for`:**
  - Use the nearest sun by `|position - center|`; if that length is > 1e-6, normalise and return it.
  - Otherwise normalise `fallback` if its length is > 1e-6.
  - Otherwise return `(0, 0, 1)`.

- [ ] **Step 4: Run `--gtest_filter='AirSpan*:SunTau*:InScatter*:Phase*:SunDir*'` and expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/atmosphere_math.h native/src/renderer/atmosphere_math.cc native/src/renderer/CMakeLists.txt native/tests/renderer/atmosphere_math_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): GL-free planet atmosphere maths — air span, optical depth, in-scatter, sun dir"
```

---

### Task 3: Per-instance atmosphere state + `set_instance_atmosphere` binding

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (add the struct after `emissive_scale`, ~94, and replace the "future planet-atmosphere effect" sentence at 73-77 with a pointer to `atmosphere`)
- Modify: `native/src/scenegraph/include/scenegraph/world.h:46-49` and `native/src/scenegraph/src/world.cc:114-120` (`set_atmosphere`)
- Modify: `native/src/host/host_bindings.cc` (binding next to `set_emissive_scale`, ~3646; a test-only read-back next to `far_debug_fade`, ~4670)
- Modify: `engine/renderer.py` (`_REQUIRED_BINDINGS` + wrapper next to `set_surface_rock`, ~1010)
- Test: a new scenegraph unit test in the existing scenegraph test binary (find its sources with `grep -n add_executable native/tests/scenegraph/CMakeLists.txt`); `tests/host/test_instance_atmosphere_binding.py`

**Interfaces:**
- Produces:
  ```cpp
  // scenegraph::Instance
  struct Atmosphere {
      bool      enabled = false;
      glm::vec3 color{1.0f};          // linear
      glm::vec3 sunset_color{1.0f};   // linear
      float     thickness = 0.0f;     // fraction of radius
      float     density = 0.0f;
      float     limb = 0.0f;
  };
  Atmosphere atmosphere;
  // scenegraph::World
  void set_atmosphere(InstanceId id, const Instance::Atmosphere& a);
  ```
- Python:
  - `engine.renderer.set_instance_atmosphere(instance_id, params)`, where `params` is `None` (disable) or an `engine.planets.atmosphere.Atmosphere`. The wrapper passes `None`, or the tuple `(color, sunset_color, thickness, density, limb)`, to `_h.set_instance_atmosphere`.
  - Test-only `_h.atmosphere_debug(iid) -> tuple | None`.

- [ ] **Step 1: Write the failing tests.**

Scenegraph:

```cpp
TEST(InstanceAtmosphere, DefaultsDisabledAndSetterStores) {
    scenegraph::World w;
    auto id = w.create_instance(1);
    EXPECT_FALSE(w.get(id)->atmosphere.enabled);
    scenegraph::Instance::Atmosphere a; a.enabled = true; a.thickness = 0.06f; a.density = 1.4f;
    w.set_atmosphere(id, a);
    EXPECT_TRUE(w.get(id)->atmosphere.enabled);
    EXPECT_FLOAT_EQ(w.get(id)->atmosphere.thickness, 0.06f);
}

TEST(InstanceAtmosphere, RecycledSlotStartsDisabled) {
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance::Atmosphere a; a.enabled = true;
    w.set_atmosphere(id, a);
    w.destroy_instance(id);
    auto id2 = w.create_instance(1);
    EXPECT_FALSE(w.get(id2)->atmosphere.enabled);
}
```

Adjust the `World` API names (`get`, `destroy_instance`) to the real ones in `world.h`.

`tests/host/test_instance_atmosphere_binding.py`: mirror the fixture of an existing `tests/host` test that creates instances, e.g. `grep -ln create_instance tests/host/*.py`. Then:

```python
def test_set_instance_atmosphere_round_trips(<fixture>):
    from engine.planets.atmosphere import Atmosphere
    iid = r.create_instance(0)
    assert r._h.atmosphere_debug(iid) is None
    r.set_instance_atmosphere(iid, Atmosphere((1.0, 0.5, 0.25), (0.9, 0.4, 0.2), 0.06, 1.4, 1.0))
    color, sunset, thickness, density, limb = r._h.atmosphere_debug(iid)
    assert color == pytest.approx((1.0, 0.5, 0.25)) and thickness == pytest.approx(0.06)
    r.set_instance_atmosphere(iid, None)
    assert r._h.atmosphere_debug(iid) is None
```

Adapt `r._h` / `create_instance(0)` to how the chosen fixture accesses the module and to a valid model handle.

- [ ] **Step 2: Build/run and expect FAIL.**

- [ ] **Step 3: Implement** the struct, `World::set_atmosphere` (`if (auto* inst = get(id)) inst->atmosphere = a;`), and the binding:

```cpp
    m.def("set_instance_atmosphere",
          [](scenegraph::InstanceId id, py::object params) {
              scenegraph::Instance::Atmosphere a;
              if (!params.is_none()) {
                  auto t = params.cast<py::tuple>();
                  auto c = t[0].cast<std::array<float, 3>>();
                  auto s = t[1].cast<std::array<float, 3>>();
                  a.enabled = true;
                  a.color = {c[0], c[1], c[2]};
                  a.sunset_color = {s[0], s[1], s[2]};
                  a.thickness = t[2].cast<float>();
                  a.density = t[3].cast<float>();
                  a.limb = t[4].cast<float>();
              }
              g_world.set_atmosphere(id, a);
          },
          py::arg("id"), py::arg("params"),
          "Planet atmosphere (spec 2026-10-07): None disables; else "
          "(color, sunset_color, thickness, density, limb), colours linear RGB.");
    m.def("atmosphere_debug",
          [](scenegraph::InstanceId id) -> py::object {
              const auto* inst = g_world.get(id);
              if (inst == nullptr) throw py::value_error("unknown instance");
              const auto& a = inst->atmosphere;
              if (!a.enabled) return py::none();
              return py::make_tuple(py::make_tuple(a.color.r, a.color.g, a.color.b),
                                    py::make_tuple(a.sunset_color.r, a.sunset_color.g, a.sunset_color.b),
                                    a.thickness, a.density, a.limb);
          },
          py::arg("id"), "Test-only read-back of an instance's atmosphere.");
```

Wrapper in `engine/renderer.py`:

```python
def set_instance_atmosphere(instance_id: InstanceId, params) -> None:
    """Planet atmosphere (spec 2026-10-07). `params` is None (airless) or an
    engine.planets.atmosphere.Atmosphere."""
    if params is None:
        _h.set_instance_atmosphere(instance_id, None)
        return
    _h.set_instance_atmosphere(instance_id, (tuple(params.color), tuple(params.sunset_color),
                                             params.thickness, params.density, params.limb))
```

Add `"set_instance_atmosphere"` to `_REQUIRED_BINDINGS`. If `tests/unit/test_renderer_binding_manifest.py` requires test-only names to be listed, add `"atmosphere_debug"` too. Read that test to learn the convention.

- [ ] **Step 4: Rebuild; run the scenegraph test, the host test and `uv run pytest tests/unit/test_renderer_binding_manifest.py -q`, and expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h native/src/scenegraph/include/scenegraph/world.h native/src/scenegraph/src/world.cc native/src/host/host_bindings.cc engine/renderer.py <scenegraph test file + CMakeLists if changed> tests/host/test_instance_atmosphere_binding.py
git commit -m "feat(scenegraph): per-instance planet atmosphere state + set_instance_atmosphere binding"
```

---

### Task 4: Shell pass — `AtmospherePass` in phase 2

**Files:**
- Create: `native/src/renderer/include/renderer/atmosphere_pass.h`, `native/src/renderer/atmosphere_pass.cc`
- Create: `native/src/renderer/shaders/atmosphere.vert`, `native/src/renderer/shaders/atmosphere.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (`embed_shader(SHADER_ATMOSPHERE_VS shaders/atmosphere.vert atmosphere_vs)`, `embed_shader(SHADER_ATMOSPHERE_FS shaders/atmosphere.frag atmosphere_fs)`, and `atmosphere_pass.cc` in the library)
- Modify: `native/src/renderer/include/renderer/pipeline.h` / `pipeline.cc` (`Shader& atmosphere_shader()`, constructed like `sun_`)
- Modify: `native/src/host/host_bindings.cc`:
  - global `std::unique_ptr<renderer::AtmospherePass> g_atmosphere_pass;` next to `g_sun_pass`;
  - create it in init next to `g_sun_pass` (~966);
  - reset it in shutdown next to `g_sun_pass.reset()` (~1046);
  - call it at the **start** of `render_space_vfx`, after `target.bind();` and before the dust block (~1593).
- Create: `native/tests/renderer/atmosphere_pass_test.cc`; modify `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: `planet_atmo::*` (Task 2), `Instance::atmosphere` (Task 3), `Model::sphere_map` (SP1), `renderer::Lighting`, `std::vector<SunDescriptor>`.
- Produces:
  ```cpp
  class AtmospherePass {
  public:
      // Additive HDR draw of every visible Space instance whose atmosphere is
      // enabled and whose model has a sphere_map. `scene_depth` is the target's
      // resolved depth texture (sampled to end the march); depth test is off.
      void render(const scenegraph::World& world, const scenegraph::Camera& cam,
                  Pipeline& pipeline, const ModelLookup& lookup, const Lighting& lighting,
                  const std::vector<SunDescriptor>& suns, std::uint32_t scene_depth,
                  int viewport_w, int viewport_h);
      int last_draw_count() const noexcept;
  };
  ```

- [ ] **Step 1: Write the failing GL tests** in `atmosphere_pass_test.cc`.

**Fixture.** Copy the `GeosphereDrawTest` fixture (`native/tests/renderer/geosphere_draw_test.cc:51-147`): the 256×256 window, Pipeline, `keep_cpu_data` cache, `load_planet(true)`, `read_rgba`, and the `NonfiniteProbe` pattern.

**Each test draws in two steps:**
1. Draw the planet with `submit_opaque_in_pass` into an `HdrTarget`, so depth is populated.
2. Call `AtmospherePass::render` with that target's `depth_texture()`, a `Lighting` whose directional 0 is the sun, and a `suns` vector.

**Setup:**
- Planet: IcePlanet geosphere, world scale 20 at the origin (R ≈ 1800).
- Atmosphere: `enabled`, color (1, 1, 1), thickness 0.06, density 1.4.
- Sun at `(1e6, 0, 0)`.
- Camera on +Z looking at the origin, far enough that the whole disc plus shell fits: `eye = (0, 0, 9000)`, `aspect = 1`.

**Tests:**
- `LitLimbIsBrighterThanFarLimb`: sample a pixel just outside the planet silhouette on +X (toward the sun) and its mirror on −X. Find the silhouette column by scanning the centre row for the first and last pixels with luminance > 0 in the planet-only render. Lum(+X halo) > 4 × lum(−X halo).
- `NoNanAnywhereOutside`: `NonfiniteProbe` reports zero non-finite pixels, and a full `std::isfinite` sweep agrees.
- `CameraInsideShellIsFiniteAndHazesTheDisc`: eye at `(0, 0, R + 0.5·thickness·R)` looking at the origin. There are no non-finite pixels, and the centre pixel (planet surface) is brighter after the atmosphere pass than before it. Lighting: the sun at +Z behind the camera, so the disc is lit.
- `OpaqueDepthEndsTheMarch`: render the planet, then also a small opaque occluder in front of the halo pixel on +X (for example the Galaxy NIF from frame_test's constants, scaled and placed so it covers the halo pixel). The halo pixel's added luminance must be smaller than without the occluder. Use `submit_opaque_in_pass` for both meshes in one `World`.
- `DisabledAtmosphereDrawsNothing`: atmosphere disabled → `last_draw_count() == 0`, and the frame is unchanged, comparing `read_rgba` before and after `render`.
- `NonGeosphereModelIsSkipped`: plain load (no `sphere_map`) with the atmosphere enabled → `last_draw_count() == 0`.

- [ ] **Step 2: Build/run and expect FAIL** (missing class).

- [ ] **Step 3: Implement the shaders.**

`atmosphere.vert`:

```glsl
#version 410 core
layout(location = 0) in vec3 a_position;   // unit geosphere
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_center;     // render space
uniform float u_r_top;
out vec3 v_world;
void main() {
    v_world = u_center + a_position * u_r_top;
    gl_Position = u_proj * u_view * vec4(v_world, 1.0);
}
```

`atmosphere.frag` mirrors `planet_atmo` exactly: same constants, the same `air_span`, `rho`, `sun_tau`, `phase`, `in_scatter`.

```glsl
#version 410 core
in vec3 v_world;
out vec4 frag_color;
uniform vec3  u_camera_pos;
uniform vec3  u_center;
uniform float u_r_planet;
uniform float u_r_top;
uniform vec3  u_color;       // linear
uniform float u_density;
uniform vec3  u_sun_dir;     // unit, toward the sun
uniform vec3  u_sun_color;   // directional 0 colour (carries intensity)
uniform sampler2D u_scene_depth;
uniform vec2  u_viewport;
uniform mat4  u_inv_proj;
const int   VIEW_SAMPLES = 8;
const int   SUN_SAMPLES  = 6;
const float OPAQUE_TAU   = 1.0e4;
const float PI = 3.14159265;

// Ray-sphere: returns (t_near, t_far); t_near > t_far means miss.
vec2 sphere(vec3 o, vec3 d, float r) {
    vec3 oc = o - u_center;
    float b = dot(oc, d);
    float c = dot(oc, oc) - r * r;
    float disc = b * b - c;
    if (disc <= 0.0) return vec2(1.0, -1.0);
    float s = sqrt(disc);
    return vec2(-b - s, -b + s);
}
float H()     { return 0.25 * (u_r_top - u_r_planet); }
float sigma() { return u_density / max(u_r_top - u_r_planet, 1e-6); }
float rho(vec3 p) { return exp(-max(length(p - u_center) - u_r_planet, 0.0) / max(H(), 1e-6)); }
float sun_tau(vec3 x) {
    vec2 hp = sphere(x, u_sun_dir, u_r_planet);
    if (hp.x <= hp.y && hp.x > 1e-4) return OPAQUE_TAU;
    vec2 ht = sphere(x, u_sun_dir, u_r_top);
    float len = max(ht.y, 0.0);
    float acc = 0.0;
    for (int i = 0; i < SUN_SAMPLES; ++i)
        acc += rho(x + u_sun_dir * ((float(i) + 0.5) * len / float(SUN_SAMPLES)));
    return acc * (len / float(SUN_SAMPLES)) * sigma();
}
float hg(float g, float c) { float g2 = g * g; return (1.0 - g2) / (4.0 * PI * pow(max(1e-6, 1.0 + g2 - 2.0 * g * c), 1.5)); }
float phase(float c) { return 3.0 / (16.0 * PI) * (1.0 + c * c) + 0.25 * hg(0.6, c); }

float scene_t(vec3 dir) {
    // Distance along `dir` to the opaque surface in the depth buffer; +inf when none (depth == 1).
    float d = texture(u_scene_depth, gl_FragCoord.xy / u_viewport).r;
    if (d >= 1.0) return 1e30;
    vec4 ndc = vec4(gl_FragCoord.xy / u_viewport * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    vec4 v = u_inv_proj * ndc;
    return length(v.xyz / v.w);
}

void main() {
    if (u_r_top <= u_r_planet) { frag_color = vec4(0.0); return; }
    vec3 o = u_camera_pos;
    vec3 dir = normalize(v_world - o);
    vec2 top = sphere(o, dir, u_r_top);
    if (top.x > top.y) { frag_color = vec4(0.0); return; }
    float t0 = max(top.x, 0.0);
    float t1 = top.y;
    vec2 pl = sphere(o, dir, u_r_planet);
    if (pl.x <= pl.y && pl.x > 0.0) t1 = min(t1, pl.x);
    t1 = min(t1, scene_t(dir));
    if (!(t1 > t0)) { frag_color = vec4(0.0); return; }
    float ds = (t1 - t0) / float(VIEW_SAMPLES);
    float tau_view = 0.0;
    vec3 acc = vec3(0.0);
    for (int i = 0; i < VIEW_SAMPLES; ++i) {
        vec3 x = o + dir * (t0 + (float(i) + 0.5) * ds);
        float r = rho(x);
        float dt = sigma() * r * ds;
        float t_mid = tau_view + 0.5 * dt;
        acc += vec3(r * exp(-(t_mid + sun_tau(x))) * sigma() * ds);
        tau_view += dt;
    }
    vec3 c = acc * phase(dot(dir, u_sun_dir)) * u_color * u_sun_color;
    frag_color = vec4(clamp(c, vec3(0.0), vec3(65000.0)), 0.0);
}
```

Before writing `scene_t`, check how `nebula_volumetric.frag` linearises depth and reuse its convention. If it uses a different reconstruction (for example `u_near` / `u_far`), copy that instead: depth conventions must match the scene's projection. `scene_t` returns view-space distance from the eye along the fragment's ray, which is the same metric as `t`, because `dir` is normalised and the camera sits at `o`.

- [ ] **Step 4: Implement `AtmospherePass::render`.**
- **Lazy setup:** on first use, upload `assets::upload_mesh(assets::build_geosphere(4, 1.0f))`.
- **Per frame:**
  - `shader.use()`; set `u_view`, `u_proj`, `u_inv_proj = inverse(proj)`, `u_camera_pos = vec3(inverse(view)[3])`, `u_viewport`.
  - Bind `scene_depth` to unit 0 → `u_scene_depth`.
  - `u_sun_color = lighting.directional_count > 0 ? lighting.directional_color[0] : vec3(1)`.
  - GL state: `glDisable(GL_DEPTH_TEST)`, `glDepthMask(GL_FALSE)`, `glEnable(GL_BLEND)`, `glBlendFunc(GL_ONE, GL_ONE)`.
- **Per instance:** `world.for_each_visible_in_pass(Pass::Space, ...)`; skip unless `inst.atmosphere.enabled`, `lookup(inst.model_handle)` is non-null, and it has a `sphere_map`.
  - `center = vec3(inst.world * vec4(sm.center_body, 1))`, `scale = length(vec3(inst.world[0]))`, `R = sm.radius * scale`, `r_top = R * (1 + thickness)`.
  - `sun_dir = planet_atmo::sun_dir_for(center, suns, lighting.directional_count > 0 ? lighting.directional_dir_ws[0] : vec3(0, 0, 1))`.
  - Cull: when the camera is outside `r_top`, `glCullFace(GL_BACK)`, so front faces draw. When inside, `glCullFace(GL_FRONT)`, so back faces draw. `glEnable(GL_CULL_FACE)`.
  - Draw, and count draws.
- **Restore:** reset GL state to what `render_space_vfx` expects (read the dust pass's prologue/epilogue for the convention: depth test on, blend off, `glCullFace(GL_BACK)`) and `glBindVertexArray(0)`.

In `host_bindings.cc`, inside `render_space_vfx` right after `target.bind();`:

```cpp
        if (g_atmosphere_pass) {
            DAUNTLESS_FRAME_SCOPE("space.atmosphere");
            g_atmosphere_pass->render(g_world, cam, *g_pipeline, resolve_model_lookup /* same lookup as phase 1 */,
                                      g_lighting, g_suns, target.depth_texture(), vw, vh);
        }
```

Use the same `lookup` object that phase 1 passes to `submit_opaque_in_pass`; capture it if it isn't in scope.

- [ ] **Step 5: Reconfigure (new shaders), build, run `--gtest_filter='AtmospherePassTest*'`, then the WHOLE `renderer_tests` binary. Expect PASS with no skips.**

Run: `cmake -B build -S . && cmake --build build -j && DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" ./build/native/tests/renderer/renderer_tests`

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/atmosphere_pass.h native/src/renderer/atmosphere_pass.cc native/src/renderer/shaders/atmosphere.vert native/src/renderer/shaders/atmosphere.frag native/src/renderer/CMakeLists.txt native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/src/host/host_bindings.cc native/tests/renderer/atmosphere_pass_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): planet atmosphere shell pass in phase 2, march ends at scene depth"
```

---

### Task 5: Surface limb haze + terminator in `opaque.frag`

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h`:
  - `draw_model` gains trailing `const scenegraph::Instance::Atmosphere* atmo = nullptr, glm::vec3 atmo_sun_dir = glm::vec3(0.0f)`;
  - `submit_opaque_in_pass` gains trailing `const std::vector<SunDescriptor>* suns = nullptr`.
- Modify: `native/src/renderer/frame.cc`:
  - `draw_model`: set uniforms beside `u_sphere_map` (~891) on every draw;
  - `submit_opaque_in_pass` (~1224): compute the sun direction for sphere-mapped instances with an enabled atmosphere and pass `&inst.atmosphere`.
- Modify: `native/src/host/host_bindings.cc` (~1418): pass `&g_suns` to `submit_opaque_in_pass`.
- Modify: `native/src/renderer/shaders/opaque.frag` (uniforms next to `u_sphere_map`, ~125; the term inserted after line 1570 `vec3 lit = ...`)
- Create: `native/tests/renderer/atmosphere_surface_test.cc`; modify `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: `Instance::Atmosphere` (Task 3), `planet_atmo::sun_dir_for` (Task 2).
- Produces: shader uniforms `u_atmo_enabled`, `u_atmo_color`, `u_atmo_sunset`, `u_atmo_limb`, `u_atmo_sun_dir_ws`.

- [ ] **Step 1: Write the failing GL tests** (fixture copied from `GeosphereDrawTest` as in Task 4):
- `LimbHazeTintsTheEdge`: IcePlanet geosphere with the atmosphere enabled, `color` pure blue (0, 0, 1), `limb` 4, sun from the camera side. Take a pixel just inside the silhouette on the lit side. Its blue/red ratio must be greater than the same pixel with the atmosphere disabled.
- `TerminatorTakesTheSunsetTint`: sun along +X, camera on +Z, `sunset_color` (1, 0, 0). On the centre row, the pixel at the terminator (the first lit column from −X) has red/green greater than with the atmosphere disabled.
- `DisabledAtmosphereIsByteIdentical`: the same frame with `atmo.enabled = false` equals the frame from the SP1 path (no atmosphere argument), comparing `read_rgba` exactly.
- `FlagDoesNotLeakToNextDraw`: draw the atmosphere planet, then a Galaxy instance, in one `submit_opaque_in_pass`, with the Galaxy drawn last (order the `World` creation accordingly). `glGetUniformiv` for `u_atmo_enabled` on the opaque program reads 0. Copy the existing `u_sphere_map` leak test in `geosphere_draw_test.cc`.
- `NoNan`: `NonfiniteProbe` reads zero for the limb test frame.

- [ ] **Step 2: Build/run and expect FAIL.**

- [ ] **Step 3: Implement C++.** In `draw_model`, right next to `prog.set_int("u_sphere_map", this_sphere ? 1 : 0);`:

```cpp
            const bool this_atmo = this_sphere && atmo != nullptr && atmo->enabled;
            prog.set_int("u_atmo_enabled", this_atmo ? 1 : 0);
            if (this_atmo) {
                prog.set_vec3("u_atmo_color", atmo->color);
                prog.set_vec3("u_atmo_sunset", atmo->sunset_color);
                prog.set_float("u_atmo_limb", atmo->limb);
                prog.set_vec3("u_atmo_sun_dir_ws", atmo_sun_dir);
            }
```

In `submit_opaque_in_pass`:

```cpp
        glm::vec3 atmo_sun{0.0f};
        const scenegraph::Instance::Atmosphere* atmo = nullptr;
        if (m && m->sphere_map && inst.atmosphere.enabled) {
            atmo = &inst.atmosphere;
            const glm::vec3 c = glm::vec3(inst.world * glm::vec4(m->sphere_map->center_body, 1.0f));
            atmo_sun = planet_atmo::sun_dir_for(
                c, suns ? *suns : std::vector<SunDescriptor>{},
                lighting.directional_count > 0 ? lighting.directional_dir_ws[0] : glm::vec3(0, 0, 1));
        }
        // ... existing draw_model call, appending: , atmo, atmo_sun
```

Avoid building a temporary vector per instance: hoist `static const std::vector<SunDescriptor> kNoSuns;` and use `suns ? *suns : kNoSuns`.

- [ ] **Step 4: Implement the shader.** Uniforms next to `u_sphere_map`:

```glsl
uniform int   u_atmo_enabled;     // 1 = planet with an atmosphere (spec 2026-10-07 §6)
uniform vec3  u_atmo_color;       // linear
uniform vec3  u_atmo_sunset;      // linear
uniform float u_atmo_limb;
uniform vec3  u_atmo_sun_dir_ws;  // unit, toward the sun
```

Directly after `vec3 lit = (amb + lit_dir + lit_dyn) * u_diffuse_color * base.rgb;`:

```glsl
    if (u_atmo_enabled != 0) {
        vec3  La   = normalize(u_atmo_sun_dir_ws);
        float x    = dot(n, La);
        float wrap = clamp((x + 0.2) / 1.2, 0.0, 1.0);
        vec3  sunc = u_dir_light_count > 0 ? u_dir_light_color[0] : vec3(1.0);
        // Terminator: a band where the sun grazes takes the sunset tint.
        float band = smoothstep(0.25, 0.0, x) * step(-0.1, x) * 0.6;
        lit *= mix(vec3(1.0), u_atmo_sunset, band);
        // Fresnel limb: the surface hazes toward the air colour at grazing view angles.
        float f = pow(1.0 - clamp(dot(n, V), 0.0, 1.0), 3.0) * u_atmo_limb;
        lit = mix(lit, u_atmo_color * sunc * wrap, clamp(f, 0.0, 1.0));
    }
```

The branch is uniform, and no derivatives or discards are added, so the SP1 ordering note still holds.

- [ ] **Step 5: Reconfigure, build, run `--gtest_filter='AtmosphereSurfaceTest*'`, then the WHOLE `renderer_tests` binary** (including HullClipTest, HullFieldClipTest, GeosphereDrawTest, FrameTest). Expect PASS with no skips.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/frame.cc native/src/host/host_bindings.cc native/src/renderer/shaders/opaque.frag native/tests/renderer/atmosphere_surface_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): planet surface Fresnel limb haze + sunset terminator"
```

---

### Task 6: Python wiring — toggle, realize helper, live registry, Developer Options

**Files:**
- Create: `engine/planet_atmosphere.py` (toggle, mirroring `engine/planet_geosphere.py`)
- Modify: `engine/planets/atmosphere.py` (live registry)
- Modify: `engine/host_loop.py`:
  - add `_apply_planet_atmosphere(r_, iid, set_name, obj_name, nif_path)`;
  - call it in the three realize paths right after `create_instance`: mission load at 7462 (`planet.GetContainingSetName()`, `planet.GetName()`, `planet.GetModelPath()`), `realize_set_objects` at 6293 (`pSet.GetName()`, `planet.GetName()`, `planet.GetModelPath()`), and `_reconcile_celestial_instances` at 6676 (`body.key[1]`, `body.name`, `body.model`);
  - call `atmosphere.clear_live()` in `MissionSession.teardown` (~6015) and `teardown_set_objects` (~6311).
- Modify: `engine/ui/developer_options_panel.py`:
  - add a `planet_atmosphere` toggle after every `planet_geosphere` occurrence (26, 106, 142, 170, 200, 279-282, 337-340);
  - add the `reload_atmospheres` action (`_ACTION_CONTROLS`, dispatch `action:reload_atmospheres`, Environments focusables).
- Modify: `native/assets/ui-cef/js/developer_options.js`:
  - toggle row after the Geosphere row (175-176), label exactly `'Planet Atmospheres (off = airless; applies to planets realized after toggling)'`;
  - action row `_doActionRow('Reload Planet Atmospheres', 'reload_atmospheres', 'Reload', isFoc('reload_atmospheres'))`;
  - focusables (~41).
- Modify: `tests/conftest.py` (reset `planet_atmosphere._enabled = True` and `atmosphere._live.clear()`)
- Modify the fake renderers that realize planets (add `def set_instance_atmosphere(self, iid, params): self.atmospheres.append((iid, params))` or a no-op that mirrors the signature): `tests/unit/test_realize_set.py`, `tests/host/test_celestial_instances.py`, `tests/host/test_render_scope_viewed_frame.py`, `tests/integration/test_sky_round_trip.py`, `tests/unit/test_rock_redirect_realise.py`, `tests/unit/test_reconcile_runtime_ships.py`, `tests/unit/test_part_detach_render.py`, plus any others the full suite reveals.
- Test: `tests/unit/test_planet_atmosphere_wiring.py` (new); extend `tests/unit/test_developer_options_panel.py` (the default settings dict at ~132 gains `"planet_atmosphere": True`; toggle and action tests in the style of 525-557).

**Interfaces:**
- Consumes: `atmosphere.resolve`, `atmosphere.resolve_key` (Task 1), `renderer.set_instance_atmosphere` (Task 3).
- Produces:
  ```python
  # engine/planet_atmosphere.py
  def enabled() -> bool; def set_enabled(value: bool) -> None
  # engine/planets/atmosphere.py
  _live: list   # [LivePlanet]
  @dataclass
  class LivePlanet:
      iid: object; key: str | None; set_name: str; obj_name: str; nif_path: str
  def record_live(iid, key, set_name, obj_name, nif_path) -> None
  def live() -> tuple
  def clear_live() -> None
  # engine/host_loop.py
  def _apply_planet_atmosphere(r_, iid, set_name: str, obj_name: str, nif_path: str) -> None
  ```
  `_apply_planet_atmosphere`:
  - When the toggle is off: `r_.set_instance_atmosphere(iid, None)`.
  - Otherwise: `key = resolve_key(...)`, `a = resolve(...)`, `r_.set_instance_atmosphere(iid, a)`, `record_live(iid, key, set_name, obj_name, nif_path)`.
  - It is always called, so a toggle-off realize explicitly pushes `None`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_planet_atmosphere_wiring.py`:

```python
"""Planet atmosphere wiring (spec 2026-10-07 §4)."""
from engine import host_loop, planet_atmosphere
from engine.planets import atmosphere as atmo


class _R:
    def __init__(self):
        self.calls = []

    def set_instance_atmosphere(self, iid, params):
        self.calls.append((iid, params))


def test_toggle_defaults_on():
    assert planet_atmosphere.enabled() is True


def test_apply_pushes_resolved_params_and_records_live():
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid1", "Albirea3", "Albirea 3",
                                       "data/models/environment/PinkGasPlanet.nif")
    (iid, params), = r.calls
    assert iid == "iid1" and params is not None and params.thickness == 0.06
    (lp,) = atmo.live()
    assert lp.key == "pinkgasplanet" and lp.set_name == "Albirea3"


def test_apply_pushes_none_for_airless():
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid2", "Vesuvi5", "Mori", "x/moon.nif")
    assert r.calls == [("iid2", None)]


def test_apply_pushes_none_when_toggle_off():
    planet_atmosphere.set_enabled(False)
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid3", "Albirea3", "Albirea 3", "x/PinkGasPlanet.nif")
    assert r.calls == [("iid3", None)]
    assert atmo.live() == ()


def test_live_registry_clears_on_teardown():
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid4", "S", "N", "x/PinkGasPlanet.nif")
    atmo.clear_live()
    assert atmo.live() == ()
```

Add one integration-style test per realize path. Reuse the fakes in `tests/unit/test_realize_set.py` (`realize_set_objects`) and `tests/host/test_celestial_instances.py` (map bodies): assert their fake recorded a `set_instance_atmosphere` call with the planet's iid, and for map bodies with `set_name == body.key[1]`. Extend those files' existing planet tests rather than writing new fakes. Then add a test that `MissionSession.teardown()` empties `atmo.live()`; find an existing teardown test with `grep -rn "def test.*teardown" tests/unit | head`.

- [ ] **Step 2: Run them and expect FAIL.**

- [ ] **Step 3: Implement** the toggle module (a copy of `planet_geosphere.py` with its docstring adapted), the registry, the helper and the three calls, the teardown clears, the panel and JS rows, the conftest resets, and the fake-renderer signatures. The panel's `action:reload_atmospheres` handler calls `atmosphere.reload()` and prints `[atmosphere] catalogue reloaded` to stderr. Changes apply to planets realized after a reload, and to dial pushes (Task 7).

- [ ] **Step 4: Run the targeted tests, then the full Python suite.** Expect PASS.

Run: `uv run pytest tests/unit/test_planet_atmosphere_wiring.py tests/unit/test_developer_options_panel.py tests/unit/test_realize_set.py tests/host/test_celestial_instances.py -q && uv run pytest tests -q`

- [ ] **Step 5: Commit** (stage every changed file explicitly)

```bash
git add engine/planet_atmosphere.py engine/planets/atmosphere.py engine/host_loop.py engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/conftest.py tests/unit/test_planet_atmosphere_wiring.py tests/unit/test_developer_options_panel.py <each fake-renderer test file changed>
git commit -m "feat(planets): realize planets with catalogue atmospheres behind a dev toggle; reload action"
```

---

### Task 7: `"atmosphere"` dev dial group — tune the nearest planet's catalogue entry live

**Files:**
- Create: `engine/planets/atmosphere_dials.py`
- Modify: `engine/planets/atmosphere.py` (`set_override(key, Atmosphere)`, an in-memory overlay consulted by `resolve`; cleared by `reload()`)
- Modify: `engine/host_loop.py` (register at boot next to `_sensor_dials.register()`, ~10024, inside the same `dev_mode.is_enabled()` block; `_nearest_live_planet()` helper)
- Test: `tests/unit/test_planet_atmosphere_dials.py`

**Interfaces:**
- Consumes: `atmosphere.live()`, `resolve`, `resolve_key`, `set_override` (Tasks 1, 6); `engine.renderer.set_instance_atmosphere`; `engine.dev_dial_groups.register_group(name, order, get_dials, step)`.
- Produces:
  ```python
  # engine/planets/atmosphere_dials.py
  DIAL_ORDER = ("thickness", "density", "limb", "color_r", "color_g", "color_b")
  STEPS = {"thickness": 0.005, "density": 0.1, "limb": 0.1, "color_r": 0.05, "color_g": 0.05, "color_b": 0.05}
  def set_target_fn(fn) -> None   # fn() -> engine.planets.atmosphere.LivePlanet | None (nearest)
  def set_push_fn(fn) -> None     # fn(iid, Atmosphere | None) -> None
  def current() -> dict           # dials of the target's resolved entry ({} when no target)
  def step(name: str, direction: int) -> None
  def register() -> None          # dev_dial_groups.register_group("atmosphere", DIAL_ORDER, current, step)
  # engine/planets/atmosphere.py
  def set_override(key: str, a: Atmosphere) -> None
  ```
  `step`:
  - finds the target LivePlanet; with no target or `key is None`, prints `[atmosphere] no atmospheric planet nearby` once per call and returns;
  - resolves its current `Atmosphere` (override first);
  - applies the step, clamped to the spec ranges (thickness (0, 0.25], density [0, 4], limb [0, 4], colour channels [0, 1] linear);
  - `set_override(key, new)`;
  - re-pushes **every** live planet whose `key == target.key` through the push fn.

  `_nearest_live_planet()` in host_loop:
  - gets the player (`engine.appc.sensor_contacts.current_player()`) and its world location in the viewed frame;
  - for each `atmo.live()` entry, finds that planet's centre and radius: unmapped planets come from `session.planet_instances`, by matching the iid back to the planet object, and use `GetWorldLocation` / `GetRadius`; map bodies come from `session.celestial_placed[key]`, by matching `celestial_instances[key] == iid`, and use `position` / `radius_gu`;
  - returns the entry with the smallest `|p_player − centre| − radius`, or `None`.

  Keep this helper small and tested with plain fakes.

- [ ] **Step 1: Write the failing tests:**

```python
"""Atmosphere dial group (spec 2026-10-07 §7, plan deviation D4)."""
import pytest

from engine.planets import atmosphere as atmo
from engine.planets import atmosphere_dials as dials


def _setup():
    pushes = []
    atmo.reload()
    atmo.record_live("a", "pinkgasplanet", "Albirea3", "Albirea 3", "x/PinkGasPlanet.nif")
    atmo.record_live("b", "pinkgasplanet", "Geble3", "Geble 3", "x/PinkGasPlanet.nif")
    atmo.record_live("c", "iceplanet", "Savoy2", "Savoy 2", "x/IcePlanet.nif")
    dials.set_target_fn(lambda: atmo.live()[0])
    dials.set_push_fn(lambda iid, a: pushes.append((iid, a)))
    return pushes


def test_current_reports_the_targets_entry():
    _setup()
    d = dials.current()
    assert d["thickness"] == 0.06 and d["density"] == 1.4


def test_step_updates_every_planet_sharing_the_key_only():
    pushes = _setup()
    dials.step("thickness", +1)
    assert sorted(i for i, _ in pushes) == ["a", "b"]
    assert all(a.thickness == pytest.approx(0.065) for _, a in pushes)
    assert atmo.resolve("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").thickness == pytest.approx(0.065)


def test_step_clamps_to_spec_ranges():
    _setup()
    for _ in range(100):
        dials.step("thickness", -1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").thickness > 0.0
    for _ in range(100):
        dials.step("density", +1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").density == 4.0


def test_reload_drops_overrides():
    _setup()
    dials.step("thickness", +1)
    atmo.reload()
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").thickness == 0.06


def test_no_target_is_a_noop(capsys):
    pushes = _setup()
    dials.set_target_fn(lambda: None)
    dials.step("thickness", +1)
    assert pushes == []
    assert "no atmospheric planet nearby" in capsys.readouterr().err


def test_register_adds_the_group():
    from engine import dev_dial_groups
    dev_dial_groups.reset()
    dials.register()
    assert "atmosphere" in dev_dial_groups.groups()
```

Add `_nearest_live_planet` tests in the same file, using `types.SimpleNamespace` fakes for session, player and bodies: (a) picks the smaller surface distance, not the smaller centre distance; (b) returns `None` with no live planets.

Conftest: also reset the module-level target and push functions, and `atmosphere._overrides`.

- [ ] **Step 2: Run and expect FAIL.**

- [ ] **Step 3: Implement.**
- `set_override` stores into `_overrides: dict[str, Atmosphere]`. `resolve` checks `_overrides.get(key)` after computing `key` and before parsing. `reload()` clears `_overrides`.
- In host_loop's dev block, register the group and wire its functions:

  ```python
  from engine.planets import atmosphere_dials as _atmo_dials
  _atmo_dials.set_target_fn(lambda: _nearest_live_planet(controller.session))
  _atmo_dials.set_push_fn(lambda iid, a: r.set_instance_atmosphere(iid, a))
  _atmo_dials.register()
  ```

  Use the real local names for the controller and renderer in that block.

- [ ] **Step 4: Run the targeted tests, then `uv run pytest tests/unit/test_dev_key_collisions.py tests/unit -q`.** Expect PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/planets/atmosphere_dials.py engine/planets/atmosphere.py engine/host_loop.py tests/unit/test_planet_atmosphere_dials.py tests/conftest.py
git commit -m "feat(planets): atmosphere dev dial group tunes the nearest planet's catalogue entry live"
```

---

### Task 8: Gate, spec amendments, CLAUDE.md row

**Files:**
- Modify: `docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md` (amend §5 order/depth, §7 reload + dial scope, §9 tolerance, per D1–D4 in this plan's Global Constraints)
- Modify: `CLAUDE.md` (one row after the "Planet geosphere" row)

- [ ] **Step 1: Run the gate:** `scripts/check_tests.sh`. It must exit 0, with no `tests/known_failures.txt` changes. Fix a failure in the task that owns it.

- [ ] **Step 2: Amend the spec.**
- **§5:** "draws in phase 2 (`render_space_vfx`) after `target.bind()`, sampling `target.depth_texture()` to end the march at the nearest opaque surface; depth test off, depth writes off, additive" (D1).
- **§5 step 3:** 6 sun samples (D3).
- **§7:** reload is a Developer Options action row; dials edit the nearest planet's resolved catalogue entry and re-push every live planet sharing it (D2, D4).
- **§9:** optical depth within 5% of a 256-step reference (D3).

Keep each edit minimal.

- [ ] **Step 3: Add the CLAUDE.md row:**

```markdown
| Planet atmospheres — catalogue + shell scattering + surface limb | `engine/planets/atmosphere.py`, `native/assets/planets/atmospheres.json`, `native/src/renderer/{atmosphere_math,atmosphere_pass}.{h,cc}`, `shaders/atmosphere.{vert,frag}`, `opaque.frag` (`u_atmo_*`), `docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md` | BC identifies a planet ONLY by (set name, AddObjectToSet name); its look comes from the NIF. Catalogue keys: `"<set>/<name>"` override (exact) else the case-folded NIF stem; NO bare-name key ("Moon 1" is in 3 sets). Fields color/thickness/density/limb/sunset_color, `atmosphere:false` = airless; unknown fields REJECTED (SP2 adds `surface` by extending the validator). BC's `SetAtmosphereRadius` is gameplay-only (one AI keep-out) and is NOT used. Shell pass runs in PHASE 2 sampling scene depth (march ends at ships/planet; correct from inside the shell); 8 view / 6 sun samples, CPU twin `renderer::planet_atmo` pins the maths. Needs the geosphere variant (`sphere_map`). Dev: Developer Options → Environments → Planet Atmospheres / Reload; dial group "atmosphere" tunes the nearest planet's ENTRY (all planets sharing it). ⚠️ **Not live-verified.** |
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md CLAUDE.md
git commit -m "docs: planet atmosphere CLAUDE.md row; spec amended for phase-2 draw, reload action, dial scope"
```
