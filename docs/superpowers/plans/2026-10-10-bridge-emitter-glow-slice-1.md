# Bridge Emitter Glow — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-shape glow and cast light on the bridge driven by per-alert profiles (tint, level, pulse, fade), so the DBridge alcove roofs go white → off → pulsing dim red with their floor lights, and the roof panels dim at alert.

**Architecture:** Python owns all timing: pure profile functions evaluate each glow and light per frame on one bridge clock (paused-aware dt) and push two small arrays to the renderer. C++ `BridgePass` gets a per-mesh glow table (src + colour + level) read by `bridge.frag`, and spots split into a static part (geometry + per-probe capture colours, which dirties the probes) and a per-frame live colour (which never does). The shader adds `src × rgb` after the diffuse ceiling, exactly where today's `_emissive` term goes, and dips the received light by the glow level.

**Tech Stack:** Python 3.11 (engine, pytest), C++20 + GLSL 410 (renderer, gtest), pybind11 bindings.

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` §11 (amends §6.1, §7, §9.7). Read §6.3, §9.4, §9.7 and §11 before starting.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/dbridge-round7`, branch `feat/dbridge-round7`. Run everything from there.
- ⛔ Never run `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs. To mutate a file temporarily, back it up and restore by `cp`, then `diff` to prove it.
- Asset-backed tests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"` or they SKIP.
- Build: `cmake --build build -j` (the tree is configured Debug — never reconfigure `CMAKE_BUILD_TYPE`). Python: `uv run pytest ...`.
- Shader edits are runtime-compiled: a GLSL error shows only when a GL test or the game runs the program. Run the bridge GL frame tests after every shader change.
- Glow and light colours are DISPLAY space; spot radiance is LINEAR: linear = (display)^2.2 per channel (spec §11.4).
- `src` codes everywhere: 0 = `emissive`, 1 = `texture`, 2 = `flat`; -1 = no glow (the texture-level `_emissive` default, unchanged).
- A glow never dirties the reflection probes; neither does a live spot colour. Only `set_spots` with a changed geometry/capture list does.
- Commit message trailer: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Before declaring done: `scripts/check_tests.sh` (with `DAUNTLESS_GAME_DIR`) exits 0.

## Review Focus

1. **A glow on a shape whose texture is shared** (alcove roofs on `Map 19.tga`, 22 shapes): only the matched shapes glow — Task 5 test `GlowAppliesOnlyToItsMesh`.
2. **An alert change mid-pulse and a second change mid-fade:** output is continuous through the first fade and never NaN — Task 3 tests `test_fade_is_continuous` / `test_second_change_mid_fade_starts_from_the_new_previous`.
3. **A spot that is OFF in the current state** must stay in the spot list (zero live colour) so live colours stay index-aligned — Task 4 `test_off_state_keeps_the_spot_with_zero_colour`.
4. **Pause:** `_player_dt` is 0 under pause, so pulses and fades freeze — Task 7 `test_tick_with_zero_dt_keeps_the_same_output`.
5. **`src: emissive` on a shape with no `_emissive` map:** skipped with a warning naming the shape, never a crash — Task 4 `test_emissive_src_without_a_map_is_skipped_with_a_warning`.

---

### Task 1: Red emissive falls back to yellow; model_identity reports an emissive map

**Files:**
- Modify: `native/src/renderer/bridge_pass.cc:35-41` (`bridge_emissive_texture`)
- Modify: `native/src/renderer/include/renderer/bridge_pass.h:63-67` (doc comment)
- Modify: `native/src/host/model_identity_maps.h`, `native/src/host/model_identity_maps.cc`
- Modify: `native/src/host/host_bindings.cc` (`model_identity`: `maps["emissive"]`, docstring)
- Modify: `engine/host_io.py` (`_NO_MAPS`, `model_identity` docstring)
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc`, `native/tests/host/model_identity_maps_test.cc`

**Interfaces:**
- Produces: `bridge_emissive_texture(mat, 2)` → Red, else Yellow, else Emissive. `model_identity(...)["meshes"][i]["maps"]["emissive"]: bool` (Task 4 reads it).

- [ ] **Step 1: Update the selection tests to the new fallback**

In `native/tests/renderer/bridge_pbr_frame_test.cc`, replace `TEST(BridgeEmissiveSelect, MissingVariantFallsBackToTheDefault)` with:

```cpp
TEST(BridgeEmissiveSelect, MissingVariantFallsBackToTheDefault) {
    EXPECT_EQ(renderer::bridge_emissive_texture(emissive_material(4, -1, -1), 1), 4);
    EXPECT_EQ(renderer::bridge_emissive_texture(emissive_material(4, -1, -1), 2), 4);
}

// Spec §11.1: yellow and red share the alert look, so red tries the yellow
// map before the default.
TEST(BridgeEmissiveSelect, RedFallsBackToYellowBeforeTheDefault) {
    EXPECT_EQ(renderer::bridge_emissive_texture(emissive_material(4, 5, -1), 2), 5);
    EXPECT_EQ(renderer::bridge_emissive_texture(emissive_material(-1, 5, -1), 2), 5);
}
```

In `TEST(BridgeEmissiveSelect, NoMapsIsNone)` keep every line. In `TEST_F(BridgePbrFrame, AlertLevelPicksTheEmissiveVariant)` replace the last block (after `// No red variant:`) with:

```cpp
    // No red variant: red alert falls back to the YELLOW map (spec §11.1).
    model->materials[0].stages[static_cast<std::size_t>(
        assets::Material::StageSlot::EmissiveRed)].texture_index = -1;
    c = render_floor();
    EXPECT_NEAR(c.r, 0.0f, 1e-3f); EXPECT_NEAR(c.g, 0.5f, 3e-3f); EXPECT_NEAR(c.b, 0.0f, 1e-3f);
```

In `native/tests/host/model_identity_maps_test.cc` add (follow the file's existing model-building pattern — find the test that sets the Bump stage and copy its setup):

```cpp
TEST(ModelIdentityMaps, ReportsAnEmissiveMap) {
    assets::Model model;
    model.materials.resize(1);
    model.materials[0].stages[static_cast<std::size_t>(
        assets::Material::StageSlot::Emissive)].texture_index = 0;
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, 0);
    EXPECT_TRUE(maps.emissive);
    EXPECT_FALSE(dauntless::mesh_identity_maps(model, -1).emissive);
}
```

- [ ] **Step 2: Build and watch them fail**

Run: `cmake --build build -j 2>&1 | tail -3` — `model_identity_maps_test.cc` fails to compile (`no member named 'emissive'`). That is the expected RED for the maps test; the selection tests fail at run time after Step 3's struct change compiles.

- [ ] **Step 3: Implement**

`bridge_pass.cc`:

```cpp
int bridge_emissive_texture(const assets::Material& mat, int alert) {
    using S = assets::Material::StageSlot;
    auto slot = [&](S s) { return mat.stages[static_cast<std::size_t>(s)].texture_index; };
    // Red tries its own map, then the yellow one (spec §11.1: yellow and red
    // share the alert look, §9.4), then the default.
    if (alert == 2 && slot(S::EmissiveRed) >= 0) return slot(S::EmissiveRed);
    if ((alert == 1 || alert == 2) && slot(S::EmissiveYellow) >= 0)
        return slot(S::EmissiveYellow);
    return slot(S::Emissive) >= 0 ? slot(S::Emissive) : -1;
}
```

`bridge_pass.h` doc comment above it becomes:

```cpp
/// The Model::textures index of the emissive map a bridge material shows at
/// alert level `alert` (0 green, 1 yellow, 2 red; anything else is green):
/// yellow -> EmissiveYellow, red -> EmissiveRed then EmissiveYellow, each
/// falling back to Emissive; green -> Emissive. -1 = no emissive map.
```

`model_identity_maps.h`: add `bool emissive = false;` to `MeshMaps` and mention emissive in its comment. `model_identity_maps.cc`: add
`maps.emissive = mat.stages[static_cast<std::size_t>(S::Emissive)].texture_index >= 0;`.

`host_bindings.cc` (`model_identity`): after `maps["normal"] = mm.normal;` add `maps["emissive"] = mm.emissive;`, and change the docstring's `maps is {roughness, metalness, normal}` to `maps is {roughness, metalness, normal, emissive}`.

`engine/host_io.py`: `_NO_MAPS = {"roughness": False, "metalness": False, "normal": False, "emissive": False}` and the `model_identity` docstring's `{roughness, metalness, normal}` → `{roughness, metalness, normal, emissive}`.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j 2>&1 | tail -2 && ctest --test-dir build -R "BridgeEmissiveSelect|AlertLevelPicksTheEmissiveVariant|ModelIdentityMaps" 2>&1 | tail -3`
Expected: all pass. Then `uv run pytest tests/host/test_bridge_editor_bindings.py -q` — pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/bridge_pass.cc native/src/renderer/include/renderer/bridge_pass.h native/src/host/model_identity_maps.h native/src/host/model_identity_maps.cc native/src/host/host_bindings.cc engine/host_io.py native/tests/renderer/bridge_pbr_frame_test.cc native/tests/host/model_identity_maps_test.cc
git commit -m "feat(bridge): red emissive falls back to yellow; model_identity reports an emissive map

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Glow schema — `src` emissive/texture/flat, `scale`; no `mask`

**Files:**
- Modify: `engine/bridge_editor/lighting_doc.py` (`_glow`)
- Test: `tests/unit/test_bridge_lighting_doc.py`

**Interfaces:**
- Produces: `ld.GLOW_SRCS = ("emissive", "texture", "flat")`; a valid glow is `{"src": <one of those>, "scale"?: number >= 0}`; any other key is rejected.

- [ ] **Step 1: Update the tests**

In `full_doc()` change the glow to `"glow": {"src": "flat", "scale": 1.0},`. In the parametrize list replace the row `...glow"].update(mask="map"), "map")` with `...glow"].update(mask="whole"), "mask")`, and add rows:

```python
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["glow"].update(scale=-1), "scale"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["glow"].pop("src"), "src"),
```

Add:

```python
@pytest.mark.parametrize("src", ["emissive", "texture", "flat"])
def test_every_glow_source_validates(src):
    d = full_doc()
    d["shapes"]["137:wall inset slot left"]["emitter"]["glow"] = {"src": src}
    assert ld.validate(d)
```

- [ ] **Step 2: Run, watch fail**

Run: `uv run pytest tests/unit/test_bridge_lighting_doc.py -q`
Expected: FAIL — `glow.src` rejects `emissive`/`texture` is accepted but `emissive` is not in the old enum, `mask` is required.

- [ ] **Step 3: Implement**

Replace `_glow` in `lighting_doc.py`:

```python
GLOW_SRCS = ("emissive", "texture", "flat")


def _glow(g, where):
    """Spec §11.2: what glows (`src`) and a per-shape multiplier (`scale`).
    The colour, level and pulse come from the emitter's profile."""
    _obj(g, where, {"src", "scale"}, ("src",))
    _enum(g["src"], f"{where}.src", GLOW_SRCS)
    if "scale" in g:
        _num(g["scale"], f"{where}.scale", lo=0)
```

- [ ] **Step 4: Run, pass**

Run: `uv run pytest tests/unit/test_bridge_lighting_doc.py tests/unit/test_bridge_lighting_writer.py -q` — pass.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/lighting_doc.py tests/unit/test_bridge_lighting_doc.py
git commit -m "feat(bridge): glow schema is src emissive/texture/flat + scale (spec §11.2)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Profile evaluation — waves, states, alert fades

**Files:**
- Create: `engine/bridge_editor/profiles.py`
- Test: `tests/unit/test_bridge_profiles.py`

**Interfaces:**
- Produces:
  - `profiles.STATES = ("green", "yellow", "red")`, `profiles.DEFAULT_FADE_S = 0.5`
  - `profiles.STEADY_WHITE: dict` — tint `[1,1,1]`, level 1, in every state
  - `profiles.state_name(alert_level) -> str` (1 yellow, 2 red, else green)
  - `profiles.profile_of(doc, emitter) -> dict` (`STEADY_WHITE` when the emitter has no `profile`)
  - `profiles.wave_factor(wave, t, phase=0.0) -> float` in `[min, 1]`
  - `profiles.state_output(profile, state, t, phase=0.0) -> ((r, g, b), k)` — `rgb = tint × level × wave`, `k = level × wave`; a missing state → `((0, 0, 0), 0)`
  - `profiles.AlertFade(alert_level=0)` with `.set_alert(level)`, `.advance(dt)`, `.output(profile, t, phase=0.0) -> ((r, g, b), k)`

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_bridge_profiles.py`:

```python
"""Emitter profiles over time (spec 2026-10-08-bridge-emitters §6.3, §11.3)."""
import math

import pytest

from engine.bridge_editor import profiles as pr

PROF = {
    "fade_s": 0.5,
    "green": {"tint": [1, 1, 1], "level": 1},
    "red": {"tint": [1, 0.1, 0.1], "level": 0.5,
            "wave": {"shape": "sine", "period_s": 2.0, "min": 0.2}},
}


def test_state_names():
    assert [pr.state_name(a) for a in (0, 1, 2, 7, -1)] == ["green", "yellow", "red", "green", "green"]


def test_steady_and_missing_waves_are_one():
    assert pr.wave_factor(None, 3.0) == 1.0
    assert pr.wave_factor({"shape": "steady"}, 3.0) == 1.0


def test_sine_peaks_at_phase_zero_and_bottoms_at_min():
    w = {"shape": "sine", "period_s": 2.0, "min": 0.2}
    assert pr.wave_factor(w, 0.0) == pytest.approx(1.0)
    assert pr.wave_factor(w, 1.0) == pytest.approx(0.2)
    assert pr.wave_factor(w, 2.0) == pytest.approx(1.0)
    assert pr.wave_factor(w, 0.0, phase=0.5) == pytest.approx(0.2)


def test_hard_square_is_on_for_its_duty():
    w = {"shape": "square", "period_s": 1.0, "duty": 0.25}
    assert pr.wave_factor(w, 0.1) == 1.0
    assert pr.wave_factor(w, 0.5) == 0.0


def test_soft_square_ramps_over_soft():
    w = {"shape": "square", "period_s": 1.0, "duty": 0.5, "soft": 0.2}
    assert pr.wave_factor(w, 0.0) == pytest.approx(0.0)
    assert pr.wave_factor(w, 0.1) == pytest.approx(0.5)      # half way up (smoothstep 0.5)
    assert pr.wave_factor(w, 0.3) == pytest.approx(1.0)
    assert pr.wave_factor(w, 0.6) == pytest.approx(0.5)      # half way down
    assert pr.wave_factor(w, 0.8) == pytest.approx(0.0)


def test_state_output_is_tint_times_level_times_wave():
    rgb, k = pr.state_output(PROF, "red", 1.0)              # sine trough: 0.2
    assert k == pytest.approx(0.1)
    assert rgb == pytest.approx((0.1, 0.01, 0.01))


def test_missing_state_is_off():
    assert pr.state_output(PROF, "yellow", 0.0) == ((0.0, 0.0, 0.0), 0.0)


def test_profile_of_defaults_to_steady_white():
    doc = {"profiles": {"p": PROF}}
    assert pr.profile_of(doc, {}) is pr.STEADY_WHITE
    assert pr.profile_of(doc, {"profile": "p"}) is PROF
    for s in pr.STATES:
        assert pr.state_output(pr.STEADY_WHITE, s, 0.0) == ((1.0, 1.0, 1.0), 1.0)


def test_alert_fade_starts_settled():
    f = pr.AlertFade(2)
    assert f.output(PROF, 0.0) == pr.state_output(PROF, "red", 0.0)


def test_fade_is_continuous():
    f = pr.AlertFade(0)
    f.set_alert(1)                        # green -> yellow (off)
    assert f.output(PROF, 0.0)[1] == pytest.approx(1.0)     # still all green
    f.advance(0.25)
    assert f.output(PROF, 0.0)[1] == pytest.approx(0.5)     # half way
    f.advance(0.25)
    assert f.output(PROF, 0.0)[1] == pytest.approx(0.0)     # settled: off
    f.advance(10.0)
    assert f.output(PROF, 0.0)[1] == pytest.approx(0.0)


def test_second_change_mid_fade_starts_from_the_new_previous():
    f = pr.AlertFade(0)
    f.set_alert(1)
    f.advance(0.25)
    f.set_alert(2)                        # yellow -> red, from yellow (off)
    rgb, k = f.output(PROF, 0.0)
    assert k == pytest.approx(0.0)
    assert all(math.isfinite(c) for c in rgb)


def test_zero_fade_switches_at_once():
    p = dict(PROF, fade_s=0)
    f = pr.AlertFade(0)
    f.set_alert(2)
    assert f.output(p, 0.0) == pr.state_output(p, "red", 0.0)


def test_same_alert_is_not_a_change():
    f = pr.AlertFade(0)
    f.set_alert(0)
    assert f.output(PROF, 0.0) == pr.state_output(PROF, "green", 0.0)
```

- [ ] **Step 2: Run, watch fail**

Run: `uv run pytest tests/unit/test_bridge_profiles.py -q` — FAIL, `ModuleNotFoundError: engine.bridge_editor.profiles`.

- [ ] **Step 3: Implement** — `engine/bridge_editor/profiles.py`:

```python
"""Emitter profiles evaluated over time (spec 2026-10-08-bridge-emitters
§6.3, §11.3). Pure functions, no GL: one profile drives a shape's glow and
its cast light, so both read the same numbers.

A state is {tint, level, wave}; a missing state is off. `rgb = tint x level
x wave` is DISPLAY space (the glow adds it as is; lights convert, lights.py).
The wave runs on the bridge clock `t` (seconds, frozen under pause);
`phase` is a fraction of a period. An alert change cross-fades from the old
state to the new over the profile's `fade_s`, both evaluated live."""
import math

STATES = ("green", "yellow", "red")
DEFAULT_FADE_S = 0.5
STEADY_WHITE = {s: {"tint": [1, 1, 1], "level": 1} for s in STATES}


def state_name(alert_level) -> str:
    return {1: "yellow", 2: "red"}.get(int(alert_level), "green")


def profile_of(doc, emitter) -> dict:
    """The emitter's named profile, or the built-in steady white (§9.6)."""
    name = emitter.get("profile")
    return STEADY_WHITE if name is None else doc["profiles"][name]


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def wave_factor(wave, t, phase=0.0) -> float:
    """1 at the peak, `min` at the trough. `sine` peaks at phase 0. `square`
    is on for `duty` of the period; `soft` is its rise (and fall) time as a
    fraction of the period, eased with a smoothstep (0 = a hard blink)."""
    if not wave or wave["shape"] == "steady":
        return 1.0
    lo = float(wave.get("min", 0.0))
    x = (float(t) / float(wave["period_s"]) + float(phase)) % 1.0
    if wave["shape"] == "sine":
        f = 0.5 + 0.5 * math.cos(2.0 * math.pi * x)
    else:
        duty = float(wave.get("duty", 0.5))
        soft = float(wave.get("soft", 0.0))
        if soft <= 0.0:
            f = 1.0 if x < duty else 0.0
        else:
            f = min(_smooth(x / soft), 1.0 - _smooth((x - duty) / soft))
    return lo + (1.0 - lo) * f


def state_output(profile, state, t, phase=0.0):
    """((r, g, b), k) for one state at time t: rgb = tint x level x wave,
    k = level x wave. A missing state is off."""
    st = profile.get(state)
    if st is None:
        return (0.0, 0.0, 0.0), 0.0
    k = float(st["level"]) * wave_factor(st.get("wave"), t, phase)
    return tuple(float(c) * k for c in st["tint"]), k


class AlertFade:
    """Which state the bridge shows and how far through the cross-fade from
    the previous one it is. One per bridge: every profile fades on the same
    alert change, each over its own `fade_s`. A change mid-fade restarts the
    fade from the state it was heading to (a small step, accepted)."""

    def __init__(self, alert_level=0):
        self.state = state_name(alert_level)
        self.prev = self.state
        self.since = math.inf

    def set_alert(self, alert_level):
        s = state_name(alert_level)
        if s != self.state:
            self.prev, self.state, self.since = self.state, s, 0.0

    def advance(self, dt):
        self.since += max(float(dt), 0.0)

    def output(self, profile, t, phase=0.0):
        new_rgb, new_k = state_output(profile, self.state, t, phase)
        fade = float(profile.get("fade_s", DEFAULT_FADE_S))
        if fade <= 0.0 or self.since >= fade:
            return new_rgb, new_k
        old_rgb, old_k = state_output(profile, self.prev, t, phase)
        f = self.since / fade
        return (tuple(a + (b - a) * f for a, b in zip(old_rgb, new_rgb)),
                old_k + (new_k - old_k) * f)
```

- [ ] **Step 4: Run, pass**

Run: `uv run pytest tests/unit/test_bridge_profiles.py -q` — 13 pass.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/profiles.py tests/unit/test_bridge_profiles.py
git commit -m "feat(bridge): emitter profiles -- waves, per-alert states, cross-fades (spec §11.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Lights and glows from the document — static lists, live values

**Files:**
- Modify (rewrite): `engine/bridge_editor/lights.py`
- Create: `engine/bridge_editor/glow.py`
- Test (rewrite): `tests/unit/test_bridge_lights.py`; Create: `tests/unit/test_bridge_glow.py`

**Interfaces:**
- Consumes: `profiles.profile_of`, `profiles.state_output`, `profiles.AlertFade` (Task 3); `meshes[i]["maps"]["emissive"]` (Task 1).
- Produces:
  - `lights.MAX_SPOTS = 32`, `lights.DEFAULT_INTENSITY = 2000.0`, `lights.GAMMA = 2.2`
  - `lights.to_linear(rgb) -> (r, g, b)` = per channel `max(c, 0) ** 2.2`
  - `lights.spots(doc, matched) -> (list, warnings)`; each spot is the 9-tuple `(pos3, dir3, inner_deg, outer_deg, range, colour3, intensity, capture_green3, capture_alert3)`; `colour3 == capture_green3`; `intensity` already includes `light_scale`. EVERY emitter with a light is listed (state off or not), in mesh order, capped at 32.
  - `lights.live_colours(doc, matched, fade, t) -> [(r, g, b)]` — linear RADIANCE (colour × intensity) per spot, same order as `spots`.
  - `glow.SRC = {"emissive": 0, "texture": 1, "flat": 2}`
  - `glow.glow_shapes(doc, matched, meshes) -> ([(mesh, src_code, profile, phase, scale)], warnings)`
  - `glow.live(shapes, fade, t) -> [(mesh, src_code, (r, g, b), level)]`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_lights.py` (replace the whole file):

```python
"""Per-bridge document -> spot lights (spec §6.2, §11.4)."""
import pytest

from engine.bridge_editor import lighting_doc as ld, lights, profiles


def _doc():
    d = ld.empty_doc("x")
    d["profiles"]["alcove"] = {
        "fade_s": 0.5,
        "green": {"tint": [1, 1, 1], "level": 1},
        "red": {"tint": [1, 0.5, 0.5], "level": 0.5,
                "wave": {"shape": "sine", "period_s": 2.0, "min": 0.2}},
    }
    e = ld.shape_entry(d, 5, "roof")
    e["emitter"] = {"profile": "alcove",
                    "light": {"position": [1, 2, 3], "direction": [0, 0, -1], "intensity": 100}}
    w = ld.shape_entry(d, 6, "lamp")
    w["emitter"] = {"light": {"position": [0, 0, 9], "direction": [0, 0, -1],
                              "inner_deg": 10, "outer_deg": 20, "range": 50,
                              "intensity": 900, "light_scale": 2}}
    return d


def test_to_linear_is_gamma_2_2_and_clamps_negative():
    assert lights.to_linear((1.0, 0.5, -1.0)) == pytest.approx((1.0, 0.5 ** 2.2, 0.0))


def test_no_profile_is_steady_white_with_light_scale():
    spots, warnings = lights.spots(_doc(), {"6:lamp": 0})
    assert spots == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 1800,
                      (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))]
    assert warnings == []


def test_capture_colours_are_the_steady_states_and_zero_when_off_or_pulsing():
    (spot,), _ = lights.spots(_doc(), {"5:roof": 1})
    *_, intensity, cap_green, cap_alert = spot
    assert intensity == 100
    assert cap_green == pytest.approx((1.0, 1.0, 1.0))
    assert cap_alert == (0.0, 0.0, 0.0)          # no yellow state: off


def test_a_pulsing_capture_state_is_zero():
    d = _doc()
    d["profiles"]["alcove"]["yellow"] = d["profiles"]["alcove"]["red"]
    (spot,), _ = lights.spots(d, {"5:roof": 1})
    assert spot[-1] == (0.0, 0.0, 0.0)


def test_off_state_keeps_the_spot_with_zero_colour():
    d = _doc()
    spots, _ = lights.spots(d, {"5:roof": 1, "6:lamp": 2})
    fade = profiles.AlertFade(1)                 # yellow: roof off
    live = lights.live_colours(d, {"5:roof": 1, "6:lamp": 2}, fade, 0.0)
    assert len(live) == len(spots) == 2
    assert live[0] == (0.0, 0.0, 0.0)
    assert live[1] == pytest.approx((1800.0, 1800.0, 1800.0))


def test_live_colour_is_linear_radiance_of_the_evaluated_state():
    fade = profiles.AlertFade(2)
    (c,) = lights.live_colours(_doc(), {"5:roof": 1}, fade, 0.0)   # sine peak: level 0.5
    assert c == pytest.approx(tuple(100 * x for x in lights.to_linear((0.5, 0.25, 0.25))))


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    matched = {}
    for i in range(34):
        ld.shape_entry(d, i, f"s{i}")["emitter"] = {
            "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
        matched[f"{i}:s{i}"] = i
    spots, warnings = lights.spots(d, matched)
    assert len(spots) == 32
    assert len(lights.live_colours(d, matched, profiles.AlertFade(0), 0.0)) == 32
    assert warnings == ["32:s32: dropped (more than 32 bridge lights)",
                        "33:s33: dropped (more than 32 bridge lights)"]
```

`tests/unit/test_bridge_glow.py`:

```python
"""Per-bridge document -> per-shape glow (spec §11.2)."""
import pytest

from engine.bridge_editor import glow, lighting_doc as ld, profiles

MESHES = [{"mesh": 3, "maps": {"emissive": True}}, {"mesh": 4, "maps": {"emissive": False}}]


def _doc():
    d = ld.empty_doc("x")
    d["profiles"]["roof"] = {"green": {"tint": [1, 1, 1], "level": 1},
                             "red": {"tint": [0.5, 0.5, 1], "level": 0.6}}
    ld.shape_entry(d, 10, "panel")["emitter"] = {"profile": "roof", "phase": 0.25,
                                                 "glow": {"src": "emissive", "scale": 2}}
    ld.shape_entry(d, 11, "alcove")["emitter"] = {"glow": {"src": "texture"}}
    ld.shape_entry(d, 12, "lamp")["emitter"] = {"light": {"position": [0, 0, 0],
                                                          "direction": [0, 0, -1]}}
    return d


MATCHED = {"10:panel": 3, "11:alcove": 4, "12:lamp": 5}


def test_glow_shapes_lists_every_glow_in_mesh_order():
    shapes, warnings = glow.glow_shapes(_doc(), MATCHED, MESHES)
    assert [(m, s, ph, sc) for m, s, _, ph, sc in shapes] == [(3, 0, 0.25, 2.0), (4, 1, 0.0, 1.0)]
    assert shapes[1][2] is profiles.STEADY_WHITE
    assert warnings == []


def test_emissive_src_without_a_map_is_skipped_with_a_warning():
    d = _doc()
    d["shapes"]["11:alcove"]["emitter"]["glow"]["src"] = "emissive"
    shapes, warnings = glow.glow_shapes(d, MATCHED, MESHES)
    assert [s[0] for s in shapes] == [3]
    assert warnings == ["11:alcove: glow src 'emissive' but its albedo has no "
                        "_emissive map; skipped"]


def test_live_scales_the_evaluated_state():
    shapes, _ = glow.glow_shapes(_doc(), MATCHED, MESHES)
    out = glow.live(shapes, profiles.AlertFade(2), 0.0)
    assert out[0][0:2] == (3, 0)
    assert out[0][2] == pytest.approx((0.6, 0.6, 1.2))     # tint x level x scale 2
    assert out[0][3] == pytest.approx(1.2)
    assert out[1] == (4, 1, (1.0, 1.0, 1.0), 1.0)          # steady white
```

- [ ] **Step 2: Run, watch fail**

Run: `uv run pytest tests/unit/test_bridge_lights.py tests/unit/test_bridge_glow.py -q` — FAIL (`spots()` takes alert_level; no `glow` module).

- [ ] **Step 3: Implement**

`engine/bridge_editor/lights.py` (replace the file):

```python
"""Per-bridge document -> bridge spot lights (spec 2026-10-08-bridge-emitters
§6.2, §11.4). The spot LIST is static -- geometry plus each spot's colour for
the green and the yellow/red probe captures -- and changes only with the
document, so an alert change or a pulse never recaptures the probes. The
live colour is evaluated every frame (`live_colours`), in the same order.

Colours: a profile's rgb is DISPLAY space (the glow adds it as is); a spot
lights in LINEAR, so it takes rgb^2.2 per channel. A capture colour is the
state's steady value, 0 when the state is off or pulsing (a pulsing light
is lit live but absent from the reflections until the probe layers)."""
from engine.bridge_editor import profiles

MAX_SPOTS = 32               # kBridgeMaxSpots
DEFAULT_INTENSITY = 2000.0   # kBridgeDefaultSpotIntensity; calibrate live
GAMMA = 2.2


def to_linear(rgb):
    return tuple(max(float(c), 0.0) ** GAMMA for c in rgb)


def _intensity(light):
    return light.get("intensity", DEFAULT_INTENSITY) * light.get("light_scale", 1.0)


def _capture(profile, state):
    st = profile.get(state)
    if st is None:
        return (0.0, 0.0, 0.0)
    wave = st.get("wave")
    if wave is not None and wave["shape"] != "steady":
        return (0.0, 0.0, 0.0)
    rgb, _ = profiles.state_output(profile, state, 0.0)
    return to_linear(rgb)


def _lit(doc, matched):
    """[(key, emitter)] for every emitter with a light, in mesh order, capped."""
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        emitter = doc["shapes"].get(key, {}).get("emitter") or {}
        if emitter.get("light") is None:
            continue
        if len(out) >= MAX_SPOTS:
            warnings.append(f"{key}: dropped (more than {MAX_SPOTS} bridge lights)")
            continue
        out.append((key, emitter))
    return out, warnings


def spots(doc, matched):
    """([(pos3, dir3, inner_deg, outer_deg, range, colour3, intensity,
    capture_green3, capture_alert3)], warnings). Every lit emitter is listed,
    off or not, so live_colours stays index-aligned; `colour3` starts as the
    green capture and is replaced every frame."""
    lit, warnings = _lit(doc, matched)
    out = []
    for _key, e in lit:
        light, prof = e["light"], profiles.profile_of(doc, e)
        green = _capture(prof, "green")
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", 200), green, _intensity(light),
                    green, _capture(prof, "yellow")))
    return out, warnings


def live_colours(doc, matched, fade, t):
    """Per spot (spots() order), this frame's linear radiance: the profile
    evaluated through `fade` at bridge time `t`, ^2.2, x intensity."""
    lit, _ = _lit(doc, matched)
    out = []
    for _key, e in lit:
        rgb, _k = fade.output(profiles.profile_of(doc, e), t, e.get("phase", 0.0))
        k = _intensity(e["light"])
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out
```

`engine/bridge_editor/glow.py`:

```python
"""Per-bridge document -> per-shape emitter glow (spec 2026-10-08-bridge-
emitters §11.2): which meshes glow and from what (static, rebuilt on a
document change), and the evaluated colour each frame (live)."""
from engine.bridge_editor import profiles

SRC = {"emissive": 0, "texture": 1, "flat": 2}


def glow_shapes(doc, matched, meshes):
    """([(mesh, src_code, profile, phase, scale)], warnings) in mesh order.
    `meshes` is model_identity's list; `src: emissive` on a mesh whose
    material has no _emissive map is skipped with a warning naming it."""
    has_map = {m["mesh"]: bool(m.get("maps", {}).get("emissive")) for m in meshes}
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        e = doc["shapes"].get(key, {}).get("emitter") or {}
        g = e.get("glow")
        if g is None:
            continue
        mesh = matched[key]
        if g["src"] == "emissive" and not has_map.get(mesh, False):
            warnings.append(f"{key}: glow src 'emissive' but its albedo has no "
                            "_emissive map; skipped")
            continue
        out.append((mesh, SRC[g["src"]], profiles.profile_of(doc, e),
                    float(e.get("phase", 0.0)), float(g.get("scale", 1.0))))
    return out, warnings


def live(shapes, fade, t):
    """[(mesh, src_code, (r, g, b), level)] this frame: rgb = tint x level x
    wave x scale (display space); level = level x wave x scale (the
    received-light dip)."""
    out = []
    for mesh, src, prof, phase, scale in shapes:
        rgb, k = fade.output(prof, t, phase)
        out.append((mesh, src, tuple(c * scale for c in rgb), k * scale))
    return out
```

- [ ] **Step 4: Run, pass**

Run: `uv run pytest tests/unit/test_bridge_lights.py tests/unit/test_bridge_glow.py -q` — pass. (`tests/unit/test_bridge_runtime.py` may now fail where it calls `lights.spots(..., alert)` indirectly — Task 7 fixes the runtime; leave it.)

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/lights.py engine/bridge_editor/glow.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_glow.py
git commit -m "feat(bridge): static spot list with capture colours + live colours; per-shape glow table (spec §11.2, §11.4)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: BridgePass + bridge.frag — per-mesh glow, received-light dip, spot capture vs live colour

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_pass.h`
- Modify: `native/src/renderer/bridge_pass.cc`
- Modify: `native/src/renderer/shaders/bridge.frag`
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc`

**Interfaces:**
- Produces:
  - `struct renderer::BridgeGlow { int mesh = -1; int src = 0; glm::vec3 rgb{0.0f}; float level = 0.0f; };`
  - `BridgeSpot` gains `bool has_capture = false; glm::vec3 capture_radiance[2] = {glm::vec3(0.0f), glm::vec3(0.0f)};` (appended after `radiance`, so existing aggregate initialisers still compile)
  - `void BridgePass::set_glow(unsigned long long model_handle, std::vector<BridgeGlow> glow);`, `void clear_glow();`, `std::size_t glow_count() const;`
  - `void BridgePass::set_spot_radiance(const std::vector<glm::vec3>& radiance);`
  - Shader uniforms `u_glow_src` (int, -1 none), `u_glow_rgb` (vec3), `u_glow_level` (float).

- [ ] **Step 1: Write the failing frame tests** — append to `native/tests/renderer/bridge_pbr_frame_test.cc` (inside the same anonymous namespace / after the emissive tests):

```cpp
// ── Emitter glow (spec 2026-10-08-bridge-emitters §11.2) ───────────────────

TEST_F(BridgePbrFrame, FlatGlowAddsItsColour) {
    set_base({0, 0, 0, 1});
    pass->set_glow(handle(), {{0, 2, {0.4f, 0.2f, 0.1f}, 0.0f}});
    const glm::vec3 c = render_floor();
    EXPECT_NEAR(c.r, 0.4f, 3e-3f); EXPECT_NEAR(c.g, 0.2f, 3e-3f); EXPECT_NEAR(c.b, 0.1f, 3e-3f);
}

// level 1 removes the received light (the dip), so the pixel is the glow
// alone: albedo x rgb.
TEST_F(BridgePbrFrame, TextureGlowIsTheAlbedoTimesItsColour) {
    set_base({0.5f, 0.25f, 0.1f, 1.0f});
    pass->set_glow(handle(), {{0, 1, {2.0f, 2.0f, 2.0f}, 1.0f}});
    const glm::vec3 c = render_floor();
    EXPECT_NEAR(c.r, 1.0f, 5e-3f); EXPECT_NEAR(c.g, 0.5f, 5e-3f); EXPECT_NEAR(c.b, 0.2f, 5e-3f);
}

// src emissive multiplies the alert's map, and REPLACES the texture-level
// default (which would add another 0.5).
TEST_F(BridgePbrFrame, EmissiveGlowMultipliesTheMapAndReplacesTheDefault) {
    set_base({0, 0, 0, 1});
    set_map(assets::Material::StageSlot::Emissive, {0.5f, 0.5f, 0.5f, 1.0f});
    pass->set_glow(handle(), {{0, 0, {0.2f, 0.4f, 1.0f}, 0.0f}});
    const glm::vec3 c = render_floor();
    EXPECT_NEAR(c.r, 0.1f, 3e-3f); EXPECT_NEAR(c.g, 0.2f, 3e-3f); EXPECT_NEAR(c.b, 0.5f, 3e-3f);
}

TEST_F(BridgePbrFrame, GlowLevelDipsTheReceivedLight) {
    set_base({1, 1, 1, 1});
    const glm::vec3 lit = render_floor();
    ASSERT_GT(lit.r, 0.1f);
    pass->set_glow(handle(), {{0, 2, {0.0f, 0.0f, 0.0f}, 0.0f}});
    EXPECT_NEAR(render_floor().r, lit.r, 1e-4f);          // level 0: an ordinary receiver
    pass->set_glow(handle(), {{0, 2, {0.0f, 0.0f, 0.0f}, 0.5f}});
    // The dip halves LINEAR received light; displayed that is ~0.73x (the
    // 2.2 curve), so only bound it.
    const float half = render_floor().r;
    EXPECT_GT(half, 0.3f * lit.r);
    EXPECT_LT(half, 0.95f * lit.r);
    pass->set_glow(handle(), {{0, 2, {0.0f, 0.0f, 0.0f}, 1.0f}});
    EXPECT_LT(render_floor().r, 1e-3f);
}

TEST_F(BridgePbrFrame, GlowAppliesOnlyToItsMeshAndModel) {
    set_base({0, 0, 0, 1});
    pass->set_glow(handle(), {{1, 2, {0.5f, 0.5f, 0.5f}, 0.0f}});   // another mesh
    EXPECT_LT(render_floor().r, 1e-3f);
    pass->set_glow(handle() + 1, {{0, 2, {0.5f, 0.5f, 0.5f}, 0.0f}}); // another model
    EXPECT_LT(render_floor().r, 1e-3f);
    pass->clear_glow();
    EXPECT_EQ(pass->glow_count(), 0u);
}

TEST_F(BridgePbrFrame, ACommSetNeverGlows) {
    set_base({0, 0, 0, 1});
    pass->set_glow(handle(), {{0, 2, {0.5f, 0.5f, 0.5f}, 0.0f}});
    EXPECT_LT(render_as_comm_set().r, 1e-3f);
}

TEST_F(BridgePbrFrame, GlowNeverDirtiesTheProbes) {
    ASSERT_FALSE(pass->probe_capture_pending());
    pass->set_glow(handle(), {{0, 2, {1.0f, 1.0f, 1.0f}, 1.0f}});
    EXPECT_FALSE(pass->probe_capture_pending());
}

// Spec §11.4: capture colours dirty the probes; live colours never do.
TEST_F(BridgePbrFrame, LiveSpotColourNeverDirtiesTheProbes) {
    renderer::BridgeSpot sp{{70.0f, 0.0f, 60.0f}, {0.0f, 0.0f, -1.0f}, 0.9f, 0.5f, 200.0f,
                            glm::vec3(0.0f)};
    sp.has_capture = true;
    sp.capture_radiance[0] = glm::vec3(100.0f);
    pass->set_spots({sp});
    EXPECT_TRUE(pass->probe_capture_pending());
    pass->reset_probes();
    pass->set_spot_radiance({glm::vec3(5000.0f)});
    EXPECT_FALSE(pass->probe_capture_pending());
    sp.radiance = glm::vec3(7.0f);                         // live differs, capture same
    pass->set_spots({sp});
    EXPECT_FALSE(pass->probe_capture_pending());
    sp.capture_radiance[1] = glm::vec3(3.0f);
    pass->set_spots({sp});
    EXPECT_TRUE(pass->probe_capture_pending());
}

TEST_F(BridgePbrFrame, LiveSpotColourLightsTheFloor) {
    set_base({1, 1, 1, 1});
    renderer::Lighting dark;
    dark.ambient = glm::vec3(0.0f);
    renderer::BridgeSpot sp{{70.0f, 0.0f, 60.0f}, {0.0f, 0.0f, -1.0f}, 0.9f, 0.5f, 200.0f,
                            glm::vec3(0.0f)};
    sp.has_capture = true;
    pass->set_spots({sp});
    EXPECT_LT(render_floor_with(dark).r, 1e-3f);
    pass->set_spot_radiance({glm::vec3(2000.0f)});
    EXPECT_GT(render_floor_with(dark).r, 0.05f);
    pass->set_spot_radiance({glm::vec3(2000.0f), glm::vec3(1.0f)});   // extra entry ignored
    pass->set_spot_radiance({});                                       // missing: kept
    EXPECT_GT(render_floor_with(dark).r, 0.05f);
}
```

- [ ] **Step 2: Build, watch fail**

Run: `cmake --build build -j 2>&1 | grep -E "error" | head -5` — compile errors: no `set_glow`, `has_capture`, `set_spot_radiance`.

- [ ] **Step 3: Implement the C++**

`bridge_pass.h` — after `struct BridgeSpot { ... radiance ... }` fields add, inside the struct:

```cpp
    /// Spec 2026-10-08-bridge-emitters §11.4: the radiance each probe capture
    /// sees -- [0] the green probe, [1] the yellow/red one -- separate from the
    /// live `radiance` (set_spot_radiance), so a pulsing or fading light never
    /// recaptures. false = both captures use `radiance` (the PBR-step rule).
    bool      has_capture = false;
    glm::vec3 capture_radiance[2] = {glm::vec3(0.0f), glm::vec3(0.0f)};
```

and after the struct:

```cpp
/// One per-shape emitter glow (spec 2026-10-08-bridge-emitters §11.2),
/// pushed every frame. `src`: 0 the alert's emissive sibling map, 1 the
/// albedo (the current flipbook frame), 2 flat. `rgb` = profile tint x level
/// x wave x scale, DISPLAY space, added after the diffuse ceiling; `level` =
/// level x wave x scale, which dips the received light (1 - m x clamp(level)).
struct BridgeGlow {
    int       mesh = -1;
    int       src = 0;
    glm::vec3 rgb{0.0f};
    float     level = 0.0f;
};
```

Public methods (beside `set_spots`):

```cpp
    /// Per-shape glow for ONE model (the bridge), replacing the previous set;
    /// a later entry for the same mesh wins. Main bridge view only. Never
    /// dirties the probes: glow is not captured (§9.7).
    void set_glow(unsigned long long model_handle, std::vector<BridgeGlow> glow);
    void clear_glow() { glow_.clear(); glow_model_ = 0; }
    std::size_t glow_count() const { return glow_.size(); }
    /// Live radiance for the current spots in set_spots order (spec §11.4).
    /// Extra entries are ignored, missing ones keep their value, non-finite
    /// becomes 0. Never dirties the probes.
    void set_spot_radiance(const std::vector<glm::vec3>& radiance);
```

Private members (beside `spots_`):

```cpp
    unsigned long long glow_model_ = 0;
    std::unordered_map<int, BridgeGlow> glow_;
    /// Which probe a capture pass is drawing: 0 green, 1 yellow/red.
    int capture_probe_ = 0;
```

`bridge_pass.cc`:

1. `draw_mesh(...)` — add three trailing parameters `int glow_src = -1, glm::vec3 glow_rgb = glm::vec3(0.0f), float glow_level = 0.0f` and, beside the `u_pbr` uniforms, set every draw:

```cpp
    // Emitter glow (spec §11.2): -1 = none (the texture-level emissive default).
    shader.set_int("u_glow_src", glow_src);
    shader.set_vec3("u_glow_rgb", glow_rgb);
    shader.set_float("u_glow_level", glow_level);
```

2. In `render()`, the spot packing loop:

```cpp
        spot_rad[i] = (capture_pass_ && sp.has_capture)
            ? sp.capture_radiance[capture_probe_] : sp.radiance;
```

3. In the sub-pass A `walk_bridge_meshes` lambda, after the material-override lookup:

```cpp
            // Emitter glow: the main bridge view only, never a probe face.
            int glow_src = -1;
            glm::vec3 glow_rgb(0.0f);
            float glow_level = 0.0f;
            if (main_bridge && !capture_pass_ && glow_model_ != 0 && mh == glow_model_) {
                const int mi = static_cast<int>(&mesh - m.meshes.data());
                if (auto it = glow_.find(mi); it != glow_.end()) {
                    glow_src = it->second.src;
                    glow_rgb = it->second.rgb;
                    glow_level = it->second.level;
                }
            }
```

and pass `glow_src, glow_rgb, glow_level` as the last three `draw_mesh` arguments (after `emissive_alert`). The sub-pass B (officer) call is unchanged (defaults).

4. `capture_one` sets the probe index — change its signature and calls:

```cpp
    auto capture_one = [&](BridgeProbe& probe, float scale, int probe_index) {
        Lighting scaled = lighting;
        scaled.ambient *= scale;
        capture_probe_ = probe_index;
        probe.capture(probe_origin_, [&](const scenegraph::Camera& face_cam) {
            ...unchanged...
        });
    };
    capture_one(probe_green_, scale_green_, 0);
    capture_one(probe_yr_, scale_yr_, 1);
```

5. `set_spots`: replace `same_spot` with

```cpp
    auto same_spot = [](const BridgeSpot& a, const BridgeSpot& b) {
        if (!(a.position == b.position && a.direction == b.direction &&
              a.cos_inner == b.cos_inner && a.cos_outer == b.cos_outer &&
              a.range == b.range && a.has_capture == b.has_capture))
            return false;
        // With capture colours the live radiance is per-frame data and never
        // recaptures; without them the radiance IS what the probes hold.
        if (a.has_capture)
            return a.capture_radiance[0] == b.capture_radiance[0] &&
                   a.capture_radiance[1] == b.capture_radiance[1];
        return a.radiance == b.radiance;
    };
```

6. New definitions (beside `set_spots`):

```cpp
void BridgePass::set_glow(unsigned long long model_handle, std::vector<BridgeGlow> glow) {
    glow_.clear();
    for (const auto& g : glow) glow_[g.mesh] = g;
    glow_model_ = glow_.empty() ? 0 : model_handle;
}

void BridgePass::set_spot_radiance(const std::vector<glm::vec3>& radiance) {
    const std::size_t n = std::min(radiance.size(), spots_.size());
    for (std::size_t i = 0; i < n; ++i) {
        const glm::vec3& r = radiance[i];
        spots_[i].radiance = (std::isfinite(r.x) && std::isfinite(r.y) && std::isfinite(r.z))
            ? r : glm::vec3(0.0f);
    }
}
```

`bridge.frag` — replace the `emissive_term` function with the block below, and declare the uniforms beside the emissive ones:

```glsl
// ── Emitter glow (spec 2026-10-08-bridge-emitters §11.2) ───────────────────
// Per shape, pushed every frame: -1 = none (the texture-level _emissive
// default above), 0 = the alert's emissive map, 1 = the albedo (this
// frame's flipbook texel), 2 = flat. Display space, like the default.
uniform int   u_glow_src;
uniform vec3  u_glow_rgb;     // tint x level x wave x scale
uniform float u_glow_level;   // level x wave x scale: the received-light dip

vec3 emissive_term(vec2 uv, vec3 albedo) {
    if (u_debug_view != 0) return vec3(0.0);
    if (u_glow_src < 0) {
        if (u_has_emissive_map == 0) return vec3(0.0);
        return texture(u_emissive_map, uv).rgb * u_emissive_scale;
    }
    vec3 src = vec3(1.0);
    if (u_glow_src == 0)
        src = u_has_emissive_map != 0 ? texture(u_emissive_map, uv).rgb : vec3(0.0);
    else if (u_glow_src == 1)
        src = albedo;
    return src * u_glow_rgb;
}

// The received light a glowing texel keeps (spec §6.1, §11.2): a lit screen
// shows its emission, not emission + room light. m = 1 for albedo / flat,
// the emissive texel's max channel for a map (its black areas stay ordinary
// receivers).
float glow_dip(vec2 uv) {
    if (u_glow_src < 0 || u_debug_view != 0) return 1.0;
    float m = 1.0;
    if (u_glow_src == 0) {
        vec3 e = u_has_emissive_map != 0 ? texture(u_emissive_map, uv).rgb : vec3(0.0);
        m = max(e.r, max(e.g, e.b));
    }
    return 1.0 - m * clamp(u_glow_level, 0.0, 1.0);
}
```

In `main()`, PBR path: immediately after `accumulate_spots(N, V, NdotV, albedo, metal, rough, F0, diffuse, spec);` insert

```glsl
        float dip = glow_dip(base_uv);
        diffuse *= dip;
        spec *= dip;
```

and change `emissive_term(base_uv)` there to `emissive_term(base_uv, base.rgb)`. Legacy path: change
`vec3 received = u_ambient * mix(u_down_bottom, u_down_top, h) * ao;` to
`vec3 received = u_ambient * mix(u_down_bottom, u_down_top, h) * ao * glow_dip(base_uv);`
and its `emissive_term(base_uv)` to `emissive_term(base_uv, base.rgb)`.

- [ ] **Step 4: Build and run all bridge renderer tests**

Run: `cmake --build build -j 2>&1 | tail -2 && ctest --test-dir build -R "Bridge" 2>&1 | tail -4`
Expected: all pass (the new ones and every existing bridge test — the shader compiles at the first GL test).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/renderer/shaders/bridge.frag native/tests/renderer/bridge_pbr_frame_test.cc
git commit -m "feat(bridge): per-mesh emitter glow + received-light dip; spot capture colours split from live colours (spec §11.2, §11.4)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Bindings and host_io — glow, live spot colours, spot captures

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`set_bridge_spots`, new `set_bridge_spot_colours`, new `set_bridge_glow`)
- Modify: `engine/host_io.py` (wrappers + `_BINDINGS` manifest)
- Test: `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: `BridgePass::set_glow`, `clear_glow`, `set_spot_radiance`, `BridgeSpot::has_capture/capture_radiance` (Task 5).
- Produces:
  - `_dauntless_host.set_bridge_spots(spots, captures=None)`: `captures` = `[((r,g,b), (r,g,b))]` per input spot (green, yellow/red), each multiplied by that spot's intensity; a length mismatch ignores `captures`; a non-finite capture drops the spot.
  - `_dauntless_host.set_bridge_spot_colours([(r, g, b)])` — live radiance; no-op before init; never raises.
  - `_dauntless_host.set_bridge_glow(instance_id, [(mesh, src, (r, g, b), level)])` — None / stale id clears; an entry with a non-finite value or `src` outside 0..2 is dropped; never raises.
  - `host_io.set_bridge_spots(spots)` accepts 7- or 9-tuples; `host_io.set_bridge_spot_colours(colours)`; `host_io.set_bridge_glow(instance_id, glow)` — all no-ops headless.

- [ ] **Step 1: Write the failing tests** — append to `tests/host/test_bridge_editor_bindings.py`:

```python
def test_set_bridge_spots_takes_capture_colours(host_module):
    spot = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 100.0, (1.0, 1.0, 1.0), 10.0)
    assert host_module.set_bridge_spots([spot], [((1.0, 1.0, 1.0), (0.0, 0.0, 0.0))]) == 0
    assert host_module.set_bridge_spots([spot], [((float("nan"), 0.0, 0.0), (0.0, 0.0, 0.0))]) == 1
    assert host_module.set_bridge_spots([spot], []) == 0          # mismatch: ignored
    assert host_module.set_bridge_spots([]) == 0


def test_set_bridge_spot_colours_and_glow_never_raise(host_module):
    host_module.set_bridge_spot_colours([(1.0, 2.0, 3.0), (float("inf"), 0.0, 0.0)])
    host_module.set_bridge_spot_colours([])
    host_module.set_bridge_glow(None, [])
    host_module.set_bridge_glow(0xFFFFFFFF, [(0, 2, (1.0, 1.0, 1.0), 1.0)])   # stale id


def test_host_io_bridge_glow_wrappers_are_headless_safe(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_bridge_spots([((0, 0, 0), (0, 0, -1), 30, 60, 100, (1, 1, 1), 1,
                                      (1, 1, 1), (0, 0, 0))]) == 0
    host_io.set_bridge_spot_colours([(1, 1, 1)])
    host_io.set_bridge_glow(None, [(0, 2, (1, 1, 1), 1)])


def test_host_io_set_bridge_spots_splits_captures(monkeypatch):
    from engine import host_io
    calls = []

    class H:
        @staticmethod
        def set_bridge_spots(rows, captures=None):
            calls.append((rows, captures))
            return 0

    monkeypatch.setattr(host_io, "_h", H)
    host_io.set_bridge_spots([((0, 0, 0), (0, 0, -1), 30, 60, 100, (1, 1, 1), 5,
                               (1, 1, 1), (0, 0, 0))])
    rows, caps = calls[-1]
    assert rows == [((0.0, 0.0, 0.0), (0.0, 0.0, -1.0), 30.0, 60.0, 100.0, (1.0, 1.0, 1.0), 5.0)]
    assert caps == [((1.0, 1.0, 1.0), (0.0, 0.0, 0.0))]
    host_io.set_bridge_spots([((0, 0, 0), (0, 0, -1), 30, 60, 100, (1, 1, 1), 5)])
    assert calls[-1][1] is None
```

(If the file's `host_module` fixture is named differently, use its name — it is the fixture the existing `test_set_bridge_spots_returns_dropped_count` uses.)

- [ ] **Step 2: Run, watch fail**

Run: `uv run pytest tests/host/test_bridge_editor_bindings.py -q -k "capture or colours or glow"` — FAIL (`set_bridge_spots()` takes 1 argument; no `set_bridge_spot_colours`).

- [ ] **Step 3: Implement**

`host_bindings.cc`, `set_bridge_spots`: add a second parameter `py::object captures` with `py::arg("captures") = py::none()`. Before the loop:

```cpp
              // Spec §11.4: per-spot probe-capture colours (green, yellow/red),
              // in input order, x that spot's intensity. A length mismatch
              // ignores them (the PBR-step rule: captures = radiance).
              std::vector<std::pair<glm::vec3, glm::vec3>> caps;
              if (!captures.is_none()) {
                  try {
                      for (auto item : captures) {
                          auto pr = item.cast<std::tuple<std::tuple<float, float, float>,
                                                         std::tuple<float, float, float>>>();
                          caps.emplace_back(v3(std::get<0>(pr)), v3(std::get<1>(pr)));
                      }
                  } catch (const py::cast_error&) {
                      caps.clear();
                  }
                  if (caps.size() != spots.size()) caps.clear();
              }
              std::size_t index = 0;
```

Change the loop header to iterate with the index (`for (const auto& s : spots) { const std::size_t i = index++; const auto& [pos, dir, inner_deg, outer_deg, range, rgb, intensity] = s; ...`), add to the validity check
`|| (!caps.empty() && (!finite3(caps[i].first * intensity) || !finite3(caps[i].second * intensity)))`, and after `sp.radiance = v3(rgb) * intensity;`:

```cpp
                  if (!caps.empty()) {
                      sp.has_capture = true;
                      sp.capture_radiance[0] = caps[i].first * intensity;
                      sp.capture_radiance[1] = caps[i].second * intensity;
                  }
```

Extend the docstring with: `"captures (optional): [((r,g,b) green, (r,g,b) yellow/red)] per spot, x its intensity: what each probe capture sees; then the live colour (set_bridge_spot_colours) never recaptures."`

New bindings, after `set_bridge_spots`:

```cpp
    m.def("set_bridge_spot_colours",
          [](const std::vector<std::tuple<float, float, float>>& radiance) {
              if (!g_bridge_pass) return;
              std::vector<glm::vec3> v;
              v.reserve(radiance.size());
              for (const auto& [r, g, b] : radiance) v.emplace_back(r, g, b);
              g_bridge_pass->set_spot_radiance(v);
          },
          py::arg("radiance"),
          "Live LINEAR radiance per bridge spot, in set_bridge_spots order (spec "
          "2026-10-08-bridge-emitters §11.4). Extra entries ignored, missing kept, "
          "non-finite -> 0. Never dirties the probes; no-op before init.");

    m.def("set_bridge_glow",
          [](py::object instance_id,
             const std::vector<std::tuple<int, int, std::tuple<float, float, float>, float>>& glow) {
              if (!g_bridge_pass) return;
              scenegraph::Instance* inst = nullptr;
              if (!instance_id.is_none()) {
                  try {
                      inst = g_world.get(instance_id.cast<scenegraph::InstanceId>());
                  } catch (const py::cast_error&) {
                      inst = nullptr;
                  }
              }
              if (inst == nullptr) { g_bridge_pass->clear_glow(); return; }
              std::vector<renderer::BridgeGlow> v;
              v.reserve(glow.size());
              for (const auto& [mesh, src, rgb, level] : glow) {
                  const glm::vec3 c(std::get<0>(rgb), std::get<1>(rgb), std::get<2>(rgb));
                  if (src < 0 || src > 2 || !std::isfinite(c.x) || !std::isfinite(c.y) ||
                      !std::isfinite(c.z) || !std::isfinite(level))
                      continue;
                  v.push_back({mesh, src, c, level});
              }
              g_bridge_pass->set_glow(inst->model_handle, std::move(v));
          },
          py::arg("instance_id"), py::arg("glow"),
          "Per-mesh emitter glow for the bridge (spec 2026-10-08-bridge-emitters "
          "§11.2): [(mesh, src 0 emissive map / 1 albedo / 2 flat, (r,g,b) display "
          "space, level)]. None or a stale id clears; invalid entries are dropped. "
          "Never dirties the probes; never raises.");
```

`engine/host_io.py`: add `"set_bridge_spot_colours", "set_bridge_glow",` to the `_BINDINGS` manifest set beside `"set_bridge_spots"`, replace `set_bridge_spots` and add the two wrappers:

```python
def set_bridge_spots(spots) -> int:
    """Bridge spot lights (production, not developer-gated): `spots` is
    [(pos3, dir3, inner_deg, outer_deg, range, (r, g, b), intensity
    [, capture_green3, capture_alert3])], the angles HALF-angles from the
    axis. With capture colours (spec 2026-10-08-bridge-emitters §11.4, every
    spot or none) the probes see those and the live colour
    (set_bridge_spot_colours) never recaptures. Returns how many were DROPPED
    (invalid + over the cap). 0 headless."""
    fn = getattr(_h, "set_bridge_spots", None) if _h is not None else None
    if fn is None:
        return 0

    def _v3(v):
        x, y, z = v
        return (float(x), float(y), float(z))

    rows, caps = [], []
    for s in spots:
        p, d, i, o, r, c, k = s[:7]
        rows.append((_v3(p), _v3(d), float(i), float(o), float(r), _v3(c), float(k)))
        if len(s) >= 9:
            caps.append((_v3(s[7]), _v3(s[8])))
    if caps and len(caps) == len(rows):
        return int(fn(rows, caps))
    return int(fn(rows))


def set_bridge_spot_colours(colours) -> None:
    """Live LINEAR radiance per bridge spot, in set_bridge_spots order (spec
    §11.4); never recaptures the probes. No-op headless."""
    fn = getattr(_h, "set_bridge_spot_colours", None) if _h is not None else None
    if fn is not None:
        fn([(float(r), float(g), float(b)) for r, g, b in colours])


def set_bridge_glow(instance_id, glow) -> None:
    """Per-mesh emitter glow for the bridge (spec §11.2): [(mesh, src_code,
    (r, g, b), level)]; None clears. No-op headless."""
    fn = getattr(_h, "set_bridge_glow", None) if _h is not None else None
    if fn is not None:
        fn(instance_id, [(int(m), int(s), (float(c[0]), float(c[1]), float(c[2])), float(lv))
                         for m, s, c, lv in glow])
```

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j 2>&1 | tail -2 && uv run pytest tests/host/test_bridge_editor_bindings.py tests/unit/test_host_io*.py -q`
Expected: pass. (If a manifest test enumerates the binding names, add the two new names to its expected set.)

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc engine/host_io.py tests/host/test_bridge_editor_bindings.py
git commit -m "feat(bridge): bindings for per-mesh glow, live spot colours and spot capture colours

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: BridgeRuntime evaluates every frame; host loop ticks it

**Files:**
- Modify: `engine/bridge_editor/runtime.py`
- Modify: `engine/host_loop.py` (one line after the `on_alert` block, ~line 12410)
- Test: `tests/unit/test_bridge_runtime.py`

**Interfaces:**
- Consumes: `lights.spots(doc, matched)`, `lights.live_colours(...)`, `glow.glow_shapes(...)`, `glow.live(...)`, `profiles.AlertFade` (Tasks 3–4); `io.set_bridge_glow`, `io.set_bridge_spot_colours` (Task 6).
- Produces: `BridgeRuntime.tick(dt)`; `on_alert(level)` now only starts the cross-fade (no spot push); `push(doc, matched)` rebuilds the static spot list and glow table, then pushes live values once.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_bridge_runtime.py` (the `FakeIO` records every call; `INFO`'s mesh 0 is block 3 "floor"):

```python
def _glow_doc(proj):
    d = ld.empty_doc("x")
    d["profiles"]["p"] = {"fade_s": 1.0,
                          "green": {"tint": [1, 1, 1], "level": 1},
                          "red": {"tint": [1, 0, 0], "level": 0.5,
                                  "wave": {"shape": "sine", "period_s": 2.0, "min": 0.0}}}
    ld.shape_entry(d, 3, "floor")["emitter"] = {
        "profile": "p", "glow": {"src": "flat"},
        "light": {"position": [0, 0, 9], "direction": [0, 0, -1], "intensity": 10}}
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")


def last(io, name):
    return [c for c in io.calls if c[0] == name][-1]


def test_attach_pushes_glow_and_live_spot_colours(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    assert last(io, "set_bridge_glow") == ("set_bridge_glow", "iid", [(0, 2, (1.0, 1.0, 1.0), 1.0)])
    assert last(io, "set_bridge_spot_colours") == ("set_bridge_spot_colours", [(10.0, 10.0, 10.0)])
    (spot,) = last(io, "set_bridge_spots")[1]
    assert len(spot) == 9


def test_on_alert_fades_over_fade_s_and_tick_advances_the_clock(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    n_spots = len([c for c in io.calls if c[0] == "set_bridge_spots"])
    rt.on_alert(2)
    assert len([c for c in io.calls if c[0] == "set_bridge_spots"]) == n_spots   # no re-push
    rt.tick(0.5)                               # half way: mix(white 1, red peak... at t=0.5)
    (_, _, rgb, level), = last(io, "set_bridge_glow")[2]
    assert 0.0 < level < 1.0
    rt.tick(10.0)
    (_, _, rgb, level), = last(io, "set_bridge_glow")[2]
    assert rgb[1] == pytest.approx(0.0) and rgb[2] == pytest.approx(0.0)   # settled red


def test_tick_with_zero_dt_keeps_the_same_output(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 2)
    rt.attach("iid")
    rt.tick(0.3)
    a = last(io, "set_bridge_glow")
    rt.tick(0.0)
    assert last(io, "set_bridge_glow") == a


def test_detach_clears_the_glow_and_tick_after_detach_is_a_no_op(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    rt.detach()
    assert ("set_bridge_glow", None, []) in io.calls
    n = len(io.calls)
    rt.tick(1.0)
    assert len(io.calls) == n
```

- [ ] **Step 2: Run, watch fail**

Run: `uv run pytest tests/unit/test_bridge_runtime.py -q` — FAIL (`tick` missing; `lights.spots` signature).

- [ ] **Step 3: Implement** — in `runtime.py`:

Imports: `from engine.bridge_editor import glow, lights, materials, profiles`.

`__init__`: add

```python
        self._meshes = []
        self._glow_shapes = []
        self._fade = profiles.AlertFade(0)
        self._t = 0.0          # the bridge clock (spec §11.3): paused-aware dt
```

`attach`: in the first clearing `try`, add `self._io.set_bridge_glow(None, [])`; reset `self._meshes, self._glow_shapes = [], []`. After `info = ...` store `self._meshes = info.get("meshes", [])`, and before `self.push(doc, matched)` set `self._fade = profiles.AlertFade(self._alert())` (a bridge load shows its state settled, no fade).

`push`: replace the spots block with

```python
            spot_list, warnings = lights.spots(doc, self._matched)
            self._glow_shapes, glow_warnings = glow.glow_shapes(
                doc, self._matched, self._meshes)
            warnings = warnings + glow_warnings
            for w in warnings:
                dev_mode.log_swallowed(
                    "bridge lighting emitters", ld.BridgeLightingError(w))
            dropped = self._io.set_bridge_spots(spot_list)
            ...(the existing dropped-count block, unchanged)...
            self._push_live()
```

Replace `on_alert` and add `tick` / `_push_live`:

```python
    def on_alert(self, level):
        """Start the cross-fade to the new alert state (spec §11.3). The spot
        list is static now -- live colours follow on the next tick() -- so
        nothing is re-pushed and the probes are never recaptured."""
        self._fade.set_alert(level)

    def tick(self, dt):
        """Every frame: advance the bridge clock by the paused-aware player
        dt (0 under pause, so pulses and fades freeze) and push this frame's
        glow and live spot colours."""
        if self._iid is None or self._doc is None:
            return
        dt = max(float(dt), 0.0)
        self._t += dt
        self._fade.advance(dt)
        self._push_live()

    def _push_live(self):
        try:
            self._io.set_bridge_glow(
                self._iid, glow.live(self._glow_shapes, self._fade, self._t))
            self._io.set_bridge_spot_colours(
                lights.live_colours(self._doc, self._matched, self._fade, self._t))
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime live push", e)
```

`detach`: add `self._io.set_bridge_glow(None, [])` beside the other clears, and reset `self._meshes, self._glow_shapes = [], []` in the `finally`.

Update the `push` docstring's mention of on_alert/spots to: "Rebuilds the static spot list (geometry + capture colours) and the glow table; tick() pushes the live values every frame."

`engine/host_loop.py`: directly after the `if _bridge_alert_level != _bridge_probe_alert_last[0]: ... on_alert(...)` block, add:

```python
            # Emitter profiles (spec 2026-10-08-bridge-emitters §11.3): pulses
            # and alert fades on the bridge clock, frozen under pause.
            controller.bridge_runtime.tick(_player_dt)
```

- [ ] **Step 4: Run, pass**

Run: `uv run pytest tests/unit/test_bridge_runtime.py tests/unit/test_bridge_lighting.py tests/unit/test_bridge_emitters_panel.py tests/host/test_bridge_runtime_swap.py -q` — pass. Fix any existing runtime test that asserted the old 7-tuple spot shape or a spot push from `on_alert` (they describe the superseded behaviour; update them to the new contract, never delete coverage).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/runtime.py engine/host_loop.py tests/unit/test_bridge_runtime.py
git commit -m "feat(bridge): BridgeRuntime evaluates glow and lights every frame on the bridge clock (spec §11.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(Add any other test file Step 4 required you to update to the `git add` line.)

---

### Task 8: DBridge test data — alcoves and roof; docs

**Files:**
- Modify: `native/assets/bridge_lighting/dbcdbd4a43dc5a56.json` (via the writer, never by hand)
- Modify: `CLAUDE.md` (the "Bridge editor" row), `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` (§10 log row)

**Interfaces:**
- Consumes: the schema of Task 2; profiles of Task 3.

- [ ] **Step 1: Author the data with the writer** — run from the worktree:

```bash
uv run python - <<'EOF'
import json
from pathlib import Path
from engine.bridge_editor import lighting_doc as ld, lighting_writer as lw
p = Path("native/assets/bridge_lighting/dbcdbd4a43dc5a56.json")
d = ld.validate(json.loads(p.read_text()))
d["profiles"]["alcove"] = {
    "fade_s": 0.5,
    "green": {"tint": [1, 1, 1], "level": 1.0},
    "red": {"tint": [1, 0.12, 0.08], "level": 0.5,
            "wave": {"shape": "sine", "period_s": 2.0, "min": 0.2}},
}
d["profiles"]["roof"] = {
    "fade_s": 0.5,
    "green": {"tint": [1, 1, 1], "level": 1.0},
    "yellow": {"tint": [1, 1, 1], "level": 0.6},
    "red": {"tint": [1, 1, 1], "level": 0.6},
}
# Alcove roofs (Map 19, shared by 22 shapes -> per-shape glow), bridge-local
# spot just under each roof centre, pointing down.
alcoves = {401: (157.0, -135.0, 105.0), 423: (-146.0, -137.0, 105.0),
           441: (-193.0, 156.5, 126.0), 455: (156.5, 156.0, 127.0)}
for block, pos in alcoves.items():
    e = ld.shape_entry(d, block, "")
    e["emitter"] = {"profile": "alcove", "glow": {"src": "texture"},
                    "light": {"position": list(pos), "direction": [0, 0, -1],
                              "inner_deg": 45, "outer_deg": 85, "range": 150,
                              "intensity": 8000}}
# Roof panels on Mark's Map 5 / Map 13 emissive maps.
for block in (76, 81, 84, 87, 90):
    e = ld.shape_entry(d, block, "")
    em = e.setdefault("emitter", {})
    em["profile"] = "roof"
    em["glow"] = {"src": "emissive"}
lw.save(d, p)
print("saved", p)
EOF
```

- [ ] **Step 2: Check it loads, matches and evaluates against the real bridge**

```bash
DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" uv run python - <<'EOF'
import json
from pathlib import Path
from engine.bridge_editor import lighting_doc as ld, lights, glow, profiles
d = ld.validate(json.loads(Path("native/assets/bridge_lighting/dbcdbd4a43dc5a56.json").read_text()))
print(sorted(d["profiles"]))
matched = {k: i for i, k in enumerate(sorted(d["shapes"]))}
spots, w = lights.spots(d, matched)
print(len(spots), "spots", w)
for alert in (0, 1, 2):
    print(alert, lights.live_colours(d, matched, profiles.AlertFade(alert), 0.0)[:2])
EOF
```

Expected: profiles `['alcove', 'roof']`, 7 spots (4 alcoves + Mark's 81/299/319), no warnings, yellow alcove colours 0.

- [ ] **Step 3: Full gate**

Run: `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" scripts/check_tests.sh 2>&1 | tail -6`
Expected: `OK — no new failures`.

- [ ] **Step 4: Docs**

In `CLAUDE.md`, the row starting `| Bridge editor — pick shapes, per-bridge lighting data |`: append to its last cell: ` Emitter glow + profiles (spec §11): per-shape \`emitter.glow\` (\`src\` emissive/texture/flat) and lights driven by per-alert profiles (tint, level, sine/square pulse, \`fade_s\`), evaluated in Python every frame by \`BridgeRuntime.tick\` on the paused-aware bridge clock; live spot colours never recapture the probes. Hand-authored in the JSON until the editor panes land.`

In the spec's §10 log, add after the `G0` row:
`| G1 | 2026-10-10 | Glow slice 1 built (plan 2026-10-10-bridge-emitter-glow-slice-1): per-mesh glow + dip, profiles/waves/fades, spot capture vs live colours, DBridge alcove + roof data | built; awaiting Mark's live check | 11 |`

- [ ] **Step 5: Commit**

```bash
git add native/assets/bridge_lighting/dbcdbd4a43dc5a56.json CLAUDE.md docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md
git commit -m "data(bridge): DBridge alcove + roof emitter profiles (glow slice 1 test cases)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Hand to Mark for the live check** (do not launch the game): give the plain commands

```
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/dbridge-round7
./build/dauntless --developer
```

and what to look for: alcove roofs white at green / dark at yellow / a dim red 2 s pulse at red, the alcove floors following; roof panels glowing in every state, dimmer at yellow and red; 0.5 s fades on each change; everything frozen while paused.
