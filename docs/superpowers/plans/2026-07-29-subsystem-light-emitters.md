# Subsystem-Attached Light Emitters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add subsystem-attached **light emitters** (point / strip / cone) that cast diffuse+specular onto the hull, flicker/go-offline with subsystem health, and are authored in the Ship Property Viewer (SPV) with the transform/scale/rotate tools + a colour wheel, persisted to `hardpoint_overrides.py`.

**Architecture:** Extend the existing **forward** dynamic-light path (`DynamicLightDescriptor` → `set_dynamic_lights` → `opaque.frag`), which already casts diffuse+specular for point and strip lights. Only cone/spot is new renderer work. A new Python module `engine/appc/light_emitters.py` owns the emitter spec, its persistence round-trip (mirroring `subsystem_glow` glow regions), and its health-state resolution (reusing `subsystem_glow.glow_state`/`impulse_gain`). A per-frame producer feeds emitters into `set_dynamic_lights` alongside torpedoes. The SPV grows an emitter child-node type reusing the gizmo suite.

**Tech Stack:** C++17 renderer (OpenGL, GLSL, pybind11 bindings), Python 3 engine, CEF/HTML/JS for the SPV panel. Build: `cmake -B build -S . && cmake --build build -j`. Gate: `scripts/check_tests.sh`.

## Global Constraints

- **Production render path must stay byte-identical.** A non-cone light (`cos_half_angle < 0`) must short-circuit to spot factor `1.0` *before* any new math, and `u_dyn_light_count == 0` must still skip the dynamic loop entirely. Existing torpedo point lights and all count==0 FrameTests render bit-for-bit unchanged.
- **Rotation is column-vector, right-handed.** World-forward of an object = `GetWorldRotation().GetCol(1)`; body→world direction = `v.MultMatrixLeft(R)` (does `R·v`). Never `GetRow`. Emitter body pos/axis transform to world exactly like glow regions (`world_from_body`).
- **Game units (GU) end-to-end.** All positions/radii/lengths are GU. No `*_m`/`*_mps` names. No display conversion in this feature.
- **Never call `_dauntless_host` directly from engine code** — go through the `host_io._h` façade; tests patch `host_io._h`.
- **`engine/appc/hardpoint_overrides.py` is machine-owned** (holds Mark's hand-tuned data). NEVER stage it in a subagent commit. The controller commits it separately.
- **CEF is mouse-only** — no keyboard→CEF path exists. The colour wheel and intensity slider are pointer drags; steppers are click targets.
- **Shader edits (`.vert`/`.frag`) need `cmake -B build -S .` (reconfigure) before `cmake --build build -j`.** `host_bindings.cc` / native edits need a `dauntless` rebuild. A stale binary shows as `AttributeError: module '_dauntless_host' has no attribute X`.
- **Gate every task with `scripts/check_tests.sh`** (build + pytest + ctest vs `tests/known_failures.txt`). Never call a failure "pre-existing" by eyeball; the only baselined failures are the 7 headless-GL scorch/heat-glow `FrameTest`s.
- Spec: `docs/superpowers/specs/2026-07-29-subsystem-light-emitters-design.md`.

---

## File Structure

**Renderer (C++):**
- `native/src/renderer/include/renderer/frame.h` — extend `DynamicLightDescriptor` (Task 1); add `DebugCone` (Task 8).
- `native/src/renderer/frame.cc` — upload `u_dyn_light_dir` (Task 1).
- `native/src/renderer/shaders/opaque.frag` — cone spot factor (Task 1).
- `native/src/renderer/include/renderer/debug_volume_pass.h`, `debug_volume_pass.cc` — cone wireframe (Task 8).
- `native/src/host/host_bindings.cc` — `set_dynamic_lights` optional keys (Task 1); `set_debug_cones` (Task 8).

**Engine (Python):**
- `engine/appc/light_emitters.py` — NEW. Spec, baked reader, struct conversion (Task 2); state resolution (Task 4).
- `engine/appc/hardpoint_override_writer.py` — second indexed prefix (Task 3).
- `engine/appc/override_routing.py` — route `__emitter__` edits (Task 3).
- `engine/host_loop.py` — producer + per-ship emitter cache (Task 5); overlay feed (Task 9).
- `engine/renderer.py` — `set_debug_cones` wrapper (Task 8).
- `engine/ui/ship_property_viewer.py` — `emitter_spec_to_calls`, emitter annotation, gizmo math reuse (Tasks 6,7,9).
- `engine/ui/ship_property_viewer_panel.py` — emitter state/dispatch/tree/selection (Task 6); gizmo routing (Task 7); save (Task 9).
- `engine/ui/glow_region_overlay.py` — `build_emitter_overlay` (Task 9).

**CEF:**
- `native/assets/ui-cef/index.html` — `#spv-emitter` modal + ctx items (Task 10).
- `native/assets/ui-cef/js/ship_property_viewer.js` — emitter modal + colour wheel + intensity (Task 10).

**Tests:**
- `native/tests/` — cone FrameTest (Task 1), DebugCone (Task 8).
- `tests/appc/test_light_emitters.py` — spec/reader/state (Tasks 2,4).
- `tests/appc/test_hardpoint_override_writer.py` — emitter prefix (Task 3).
- `tests/test_host_loop_emitter_lights.py` — producer (Task 5).
- `tests/ui/test_ship_property_viewer_panel_emitter.py` — panel/gizmo (Tasks 6,7,9).

---

## Emitter spec — the canonical form (used by every task)

A single subsystem carries a **list** of emitter specs (0..N). Each spec is a plain dict in **ship body frame** (same frame as glow-region positions):

```python
{
    "kind": "point" | "strip" | "cone",
    "position": (x, y, z),   # body-frame; point=centre, strip=midpoint, cone=apex
    "axis": (x, y, z),       # body-frame unit dir; strip=segment axis, cone=direction; ignored for point
    "length": float,         # GU; strip=segment length, cone=range; 0 for point
    "radius": float,         # GU; point=range, strip=tube radius, cone=base radius
    "color": (r, g, b),      # linear RGB, 0..1 (from the hue/sat wheel at full value)
    "intensity": float,      # HDR scalar, ~0..8
}
```

Cone half-angle is always **derived**: `atan2(radius, max(length, 1e-6))` — never stored.

---

### Task 1: Renderer — cone/spot dynamic light type

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h:129-137`
- Modify: `native/src/renderer/frame.cc:377-393`
- Modify: `native/src/renderer/shaders/opaque.frag:46-50, 491-518`
- Modify: `native/src/host/host_bindings.cc:2234-2270` (`set_dynamic_lights`)
- Test: `native/tests/` — new `test_cone_light_frame.cc` (or extend the nearest existing dynamic-light/FrameTest harness)

**Interfaces:**
- Consumes: nothing new.
- Produces: `DynamicLightDescriptor` gains `glm::vec3 direction{0.0f}` and `float cos_half_angle = -1.0f`. `set_dynamic_lights` accepts optional dict keys `direction` (3-tuple) and `cos_half_angle` (float). Uniform `u_dyn_light_dir[i] = vec4(dir.xyz, cos_half_angle)`.

- [ ] **Step 1: Extend the struct.** In `frame.h`, add two fields to `DynamicLightDescriptor` (after `intensity`):

```cpp
struct DynamicLightDescriptor {
    glm::vec3 pos_a{0.0f};
    glm::vec3 pos_b{0.0f};
    glm::vec3 color{1.0f};
    float     radius    = 0.0f;
    float     intensity = 1.0f;
    glm::vec3 direction{0.0f};       // cone axis (world, unit); ignored if not a cone
    float     cos_half_angle = -1.0f;// < 0  => not a cone (point/strip). cos(half-angle) for a cone.
};
```

Leave `kMaxDynamicLightsPerFrame`/`kMaxDynamicLightsPerDraw` unchanged. `select_dynamic_lights` and `dynamic_light_attenuation` are unaffected (a cone still culls by its segment/point distance — the apex point — which is conservative; fine for v1).

- [ ] **Step 2: Upload the new uniform.** In `frame.cc`, inside the existing `dyn_light_count > 0` block (after `lc[i] = ...`), add a fourth packed array:

```cpp
            glm::vec4 la[kMaxDynamicLightsPerDraw];
            glm::vec4 lb[kMaxDynamicLightsPerDraw];
            glm::vec3 lc[kMaxDynamicLightsPerDraw];
            glm::vec4 ld[kMaxDynamicLightsPerDraw];   // NEW: dir.xyz, cos_half_angle
            for (int i = 0; i < dyn_light_count; ++i) {
                la[i] = glm::vec4(dyn_lights[i].pos_a, dyn_lights[i].radius);
                lb[i] = glm::vec4(dyn_lights[i].pos_b, 0.0f);
                lc[i] = dyn_lights[i].color * dyn_lights[i].intensity;
                ld[i] = glm::vec4(dyn_lights[i].direction, dyn_lights[i].cos_half_angle);
            }
            prog.set_vec4_array("u_dyn_light_a", la, dyn_light_count);
            prog.set_vec4_array("u_dyn_light_b", lb, dyn_light_count);
            prog.set_vec3_array("u_dyn_light_color", lc, dyn_light_count);
            prog.set_vec4_array("u_dyn_light_dir", ld, dyn_light_count);   // NEW
```

(When `dyn_light_count == 0` nothing here runs — the production path stays byte-identical.)

- [ ] **Step 3: Shader — declare the uniform.** In `opaque.frag`, after line 50 add:

```glsl
uniform vec4 u_dyn_light_dir[MAX_DYN_LIGHTS];    // dir.xyz, cos_half_angle (<0 = not a cone)
```

- [ ] **Step 4: Shader — apply the spot factor.** In the dynamic-light loop, compute a spot factor and fold it into `att` so BOTH diffuse and specular are gated identically. Replace the segment of the loop from the `L`/`nl` computation so it reads:

```glsl
        vec3  L  = (lp - v_position_ws) / max(d, 1e-6);
        float nl = max(dot(n, L), 0.0);

        // Cone/spot gate: cos_half_angle < 0 => not a cone => spot == 1.0
        // (byte-identical to the pre-cone shader for point/strip lights).
        float cha = u_dyn_light_dir[i].w;
        float spot = 1.0;
        if (cha >= 0.0) {
            vec3 cdir = normalize(u_dyn_light_dir[i].xyz);
            // -L points from the light toward the fragment; inside the cone
            // when its angle to the cone axis is <= half-angle.
            float cosf = dot(-L, cdir);
            spot = smoothstep(cha - 0.02, cha, cosf);   // 0.02 = fixed cos-space penumbra
        }
        att *= spot;

        lit_dyn += att * nl * u_dyn_light_color[i];

        if (u_specular_enabled != 0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);
            spec_acc += att * s * u_dyn_light_color[i];
        }
```

The `cha >= 0.0` guard means point/strip (which pass `cos_half_angle = -1`) never enter the `if`, so `spot` stays `1.0` and `att` is unchanged — bit-identical to today for non-cone lights.

- [ ] **Step 5: Binding — accept the optional keys.** In `host_bindings.cc` `set_dynamic_lights`, inside the per-dict loop after `l.intensity = ...`, add:

```cpp
                  l.intensity = d["intensity"].cast<float>();
                  // Optional cone keys (default: not a cone). Point/strip omit both.
                  if (d.contains("direction") && !d["direction"].is_none()) {
                      auto dir = d["direction"].cast<std::tuple<float, float, float>>();
                      l.direction = {std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)};
                  }
                  if (d.contains("cos_half_angle") && !d["cos_half_angle"].is_none()) {
                      l.cos_half_angle = d["cos_half_angle"].cast<float>();
                  }
```

Update the docstring string to mention the two optional cone keys.

- [ ] **Step 6: Reconfigure + build.** Run `cmake -B build -S . && cmake --build build -j` (the shader edit requires the reconfigure).

- [ ] **Step 7: Write the FrameTest.** Add a headless FrameTest that renders a lit plane facing a cone light and asserts the lit region is bounded by the half-angle. Model it on the nearest existing dynamic-light or plane FrameTest in `native/tests/`. Two assertions:
  1. **Cone bounds:** a cone with apex above a plane, `cos_half_angle = cos(30°)`, direction straight down → a fragment on-axis is lit, a fragment well outside the 30° cone is dark (≈ ambient only).
  2. **Non-cone identity:** the same light with `cos_half_angle = -1` lights both fragments (spot factor 1.0), proving the guard.

Register it in the C++ test CMake list next to the other FrameTests.

- [ ] **Step 8: Run the gate.** `scripts/check_tests.sh`. Expected: the new FrameTest passes; no new failures beyond the 7 baselined. If a count==0 FrameTest changed, the byte-identity guard was violated — investigate before proceeding.

- [ ] **Step 9: Commit.**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/frame.cc native/src/renderer/shaders/opaque.frag native/src/host/host_bindings.cc native/tests/
git commit -m "feat(renderer): cone/spot dynamic light type (point/strip byte-identical)"
```

---

### Task 2: Emitter spec module + baked reader

**Files:**
- Create: `engine/appc/light_emitters.py`
- Test: `tests/appc/test_light_emitters.py`

**Interfaces:**
- Consumes: `engine/appc/properties.py:read_indexed_setter_args(prop, field, index)` (returns the recorded arg tuple for a `Set<field>(index, ...)` call, or `None`).
- Produces:
  - `default_emitter_spec(kind: str) -> dict` — a from-scratch spec of that kind.
  - `baked_emitters(prop) -> list[dict]` — reads `SetLightEmitter*` setters back off a subsystem property, index 0..N.
  - `emitter_spec_to_struct(spec: dict) -> dict` — converts a BODY-frame spec to the `set_dynamic_lights` dict keys BEFORE world transform (`position`, optional `position_b`, `color`, `radius`, `intensity`, optional `direction`, optional `cos_half_angle`). Positions/axis remain body-frame; the producer (Task 5) transforms to world.
  - Setter field names (the recorded `SetLightEmitter*` family): `Kind`, `Position`, `Axis`, `Length`, `Radius`, `Color`, `Intensity`.

- [ ] **Step 1: Write the failing test** (`tests/appc/test_light_emitters.py`):

```python
import math
import pytest
from engine.appc.light_emitters import (
    default_emitter_spec, baked_emitters, emitter_spec_to_struct)
from engine.appc.properties import SubsystemProperty


def _prop_with_emitters(specs):
    p = SubsystemProperty()
    from engine.appc.light_emitters import emitter_spec_to_calls  # Task 3 helper
    # Record directly via the setters (mirrors what the writer would emit).
    for j, s in enumerate(specs):
        p.SetLightEmitterKind(j, s["kind"])
        px, py, pz = s["position"]; p.SetLightEmitterPosition(j, px, py, pz)
        ax, ay, az = s["axis"];     p.SetLightEmitterAxis(j, ax, ay, az)
        p.SetLightEmitterLength(j, s["length"])
        p.SetLightEmitterRadius(j, s["radius"])
        r, g, b = s["color"];       p.SetLightEmitterColor(j, r, g, b)
        p.SetLightEmitterIntensity(j, s["intensity"])
    return p


def test_default_specs_have_all_keys():
    for kind in ("point", "strip", "cone"):
        s = default_emitter_spec(kind)
        assert s["kind"] == kind
        assert set(s) == {"kind", "position", "axis", "length", "radius", "color", "intensity"}


def test_baked_emitters_roundtrip():
    specs = [default_emitter_spec("point"), default_emitter_spec("cone")]
    specs[1]["radius"] = 1.0; specs[1]["length"] = 2.0
    p = _prop_with_emitters(specs)
    got = baked_emitters(p)
    assert len(got) == 2
    assert got[0]["kind"] == "point"
    assert got[1]["kind"] == "cone"
    assert got[1]["radius"] == pytest.approx(1.0)


def test_point_struct_is_degenerate_segment():
    d = emitter_spec_to_struct(default_emitter_spec("point"))
    assert "position_b" not in d          # point => pos_b defaults to pos_a native-side
    assert d.get("cos_half_angle", -1.0) < 0.0


def test_strip_struct_has_two_endpoints():
    s = default_emitter_spec("strip")
    s["position"] = (0.0, 0.0, 0.0); s["axis"] = (0.0, 1.0, 0.0); s["length"] = 2.0
    d = emitter_spec_to_struct(s)
    assert d["position"] == pytest.approx((0.0, -1.0, 0.0))
    assert d["position_b"] == pytest.approx((0.0, 1.0, 0.0))


def test_cone_struct_derives_half_angle():
    s = default_emitter_spec("cone")
    s["radius"] = 1.0; s["length"] = 1.0; s["axis"] = (0.0, -1.0, 0.0)
    d = emitter_spec_to_struct(s)
    assert d["direction"] == pytest.approx((0.0, -1.0, 0.0))
    assert d["cos_half_angle"] == pytest.approx(math.cos(math.atan2(1.0, 1.0)))
```

- [ ] **Step 2: Run it — expect ImportError** (`emitter_spec_to_calls` is Task 3; import lazily inside `_prop_with_emitters` so the other tests still collect — for THIS task, stub the helper import by defining the setters directly, i.e. delete the `from ... import emitter_spec_to_calls` line and the record loop stays). Run: `uv run pytest tests/appc/test_light_emitters.py -q`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement `engine/appc/light_emitters.py`:**

```python
"""Subsystem-attached light emitters — point / strip / cone dynamic lights.

An emitter is an independent child of a subsystem (0..N per subsystem), stored
in the ship BODY frame (same frame as glow-region positions). Persistence
mirrors glow regions: a Dauntless-invented SetLightEmitter* setter family
recorded via the property data-bag (engine/appc/properties.py) and read back
here. The runtime producer (engine/host_loop.py) transforms body->world and
feeds host_io.set_dynamic_lights; the renderer (opaque.frag) casts the light.

See docs/superpowers/specs/2026-07-29-subsystem-light-emitters-design.md.
"""
import math

from engine.appc.properties import read_indexed_setter_args

_KINDS = ("point", "strip", "cone")


def default_emitter_spec(kind: str) -> dict:
    """A from-scratch emitter of `kind` with sensible default geometry."""
    if kind not in _KINDS:
        kind = "point"
    return {
        "kind": kind,
        "position": (0.0, 0.0, 0.0),
        "axis": (0.0, -1.0, 0.0),
        "length": 2.0,
        "radius": 1.0,
        "color": (1.0, 0.9, 0.7),
        "intensity": 2.0,
    }


def _normalize(v):
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-9:
        return (0.0, -1.0, 0.0)
    return (x / n, y / n, z / n)


def baked_emitters(prop) -> list:
    """Read the recorded SetLightEmitter* setters back into specs, index 0..N.

    Stops at the first index whose Kind is unset (mirrors baked_glow_regions).
    """
    if prop is None:
        return []
    out = []
    i = 0
    while True:
        kind = read_indexed_setter_args(prop, "LightEmitterKind", i)
        if kind is None:
            return out
        pos = read_indexed_setter_args(prop, "LightEmitterPosition", i) or (0.0, 0.0, 0.0)
        axis = read_indexed_setter_args(prop, "LightEmitterAxis", i) or (0.0, -1.0, 0.0)
        length = read_indexed_setter_args(prop, "LightEmitterLength", i)
        radius = read_indexed_setter_args(prop, "LightEmitterRadius", i)
        color = read_indexed_setter_args(prop, "LightEmitterColor", i) or (1.0, 0.9, 0.7)
        intensity = read_indexed_setter_args(prop, "LightEmitterIntensity", i)
        out.append({
            "kind": str(kind[0]),
            "position": tuple(float(c) for c in pos[:3]),
            "axis": tuple(float(c) for c in axis[:3]),
            "length": float(length[0]) if length else 0.0,
            "radius": float(radius[0]) if radius else 1.0,
            "color": tuple(float(c) for c in color[:3]),
            "intensity": float(intensity[0]) if intensity else 1.0,
        })
        i += 1


def emitter_spec_to_struct(spec: dict) -> dict:
    """Convert a BODY-frame emitter spec to set_dynamic_lights dict keys.

    Positions/axis stay body-frame here; the host-loop producer transforms them
    to world. Point => degenerate segment (no position_b, no cone). Strip =>
    two endpoints. Cone => apex + direction + derived cos(half-angle).
    """
    kind = spec.get("kind", "point")
    px, py, pz = spec["position"]
    d = {
        "position": (px, py, pz),
        "color": tuple(spec["color"]),
        "radius": float(spec["radius"]),
        "intensity": float(spec["intensity"]),
    }
    if kind == "point":
        return d
    ax, ay, az = _normalize(spec["axis"])
    length = float(spec["length"])
    if kind == "strip":
        half = length / 2.0
        d["position"] = (px - ax * half, py - ay * half, pz - az * half)
        d["position_b"] = (px + ax * half, py + ay * half, pz + az * half)
        return d
    # cone
    d["direction"] = (ax, ay, az)
    d["cos_half_angle"] = math.cos(math.atan2(float(spec["radius"]), max(length, 1e-6)))
    return d
```

- [ ] **Step 4: Run the tests — expect PASS.** `uv run pytest tests/appc/test_light_emitters.py -q`.

- [ ] **Step 5: Gate + commit.** `scripts/check_tests.sh`, then:

```bash
git add engine/appc/light_emitters.py tests/appc/test_light_emitters.py
git commit -m "feat(emitters): body-frame emitter spec, baked reader, struct conversion"
```

---

### Task 3: Persistence writer — second indexed prefix + `emitter_spec_to_calls`

**Files:**
- Modify: `engine/appc/hardpoint_override_writer.py:27, 61-65, 78-88`
- Modify: `engine/appc/override_routing.py:39-60`
- Modify: `engine/ui/ship_property_viewer.py` (add `emitter_spec_to_calls` next to `region_spec_to_calls:123`)
- Test: `tests/appc/test_hardpoint_override_writer.py` (extend)

**Interfaces:**
- Consumes: existing `read_models`, `emit`, `_replace_key`, `set_region`.
- Produces:
  - `_EMITTER_PREFIX = "SetLightEmitter"` and a shared `_INDEXED_PREFIXES = (_INDEXED_PREFIX, _EMITTER_PREFIX)`.
  - `set_region(models, leaf, subsystem, index, calls, prefix=_INDEXED_PREFIX)` — a `prefix` param so the same full-replace logic serves both glow regions and emitters.
  - `override_routing`: a `(subsystem, "__emitter__", index, calls)` 4-tuple edit routes to `set_region(..., prefix="SetLightEmitter")`.
  - `emitter_spec_to_calls(index, spec) -> list[(setter, args)]` in `ship_property_viewer.py`.

- [ ] **Step 1: Write the failing test** (extend `tests/appc/test_hardpoint_override_writer.py`):

```python
def test_emitter_setters_are_index_keyed_and_full_replace():
    from engine.appc.hardpoint_override_writer import set_region, emit, read_models
    import types
    models = {}
    set_region(models, "galaxy", "Impulse", 0, [
        ("SetLightEmitterKind", (0, "point")),
        ("SetLightEmitterRadius", (0, 1.0)),
    ], prefix="SetLightEmitter")
    # Re-set index 0 => old emitter-0 setters cleared, new ones only.
    set_region(models, "galaxy", "Impulse", 0, [
        ("SetLightEmitterKind", (0, "cone")),
    ], prefix="SetLightEmitter")
    calls = dict((s, a) for (s, a) in models["galaxy"]["Impulse"])
    assert calls["SetLightEmitterKind"] == (0, "cone")
    assert "SetLightEmitterRadius" not in calls   # cleared by full-replace
    # Emit round-trips through ast.parse without error.
    text = emit(models)
    assert "SetLightEmitterKind" in text


def test_emitter_and_glow_prefixes_coexist_on_one_subsystem():
    from engine.appc.hardpoint_override_writer import set_region
    models = {}
    set_region(models, "galaxy", "Impulse", 0, [("SetGlowRegionShape", (0, "Box"))])
    set_region(models, "galaxy", "Impulse", 0, [("SetLightEmitterKind", (0, "point"))],
               prefix="SetLightEmitter")
    keys = set(s for (s, a) in models["galaxy"]["Impulse"])
    assert {"SetGlowRegionShape", "SetLightEmitterKind"} <= keys   # neither clobbers the other
```

- [ ] **Step 2: Run — expect FAIL** (`set_region` has no `prefix` param). `uv run pytest tests/appc/test_hardpoint_override_writer.py -q`.

- [ ] **Step 3: Edit `hardpoint_override_writer.py`.** Add the emitter prefix and generalize:

```python
_INDEXED_PREFIX = "SetGlowRegion"
_EMITTER_PREFIX = "SetLightEmitter"
_INDEXED_PREFIXES = (_INDEXED_PREFIX, _EMITTER_PREFIX)
```

Update `_replace_key` to index-key BOTH prefixes:

```python
def _replace_key(setter, args):
    if setter.startswith(_INDEXED_PREFIXES) and args:
        return (setter, args[0])      # same setter AND same index
    return (setter,)
```

Add a `prefix` param to `set_region` (default keeps glow behaviour):

```python
def set_region(models, leaf, subsystem, index, calls, prefix=_INDEXED_PREFIX) -> None:
    """Replace all <prefix>*(index, ...) calls for a subsystem with `calls`.
    Other setters and other indices of the same prefix are left intact."""
    per_sub = models.setdefault(leaf, {})
    existing = per_sub.setdefault(subsystem, [])
    kept = [(s, a) for (s, a) in existing
            if not (s.startswith(prefix) and a and a[0] == index)]
    kept.extend((s, tuple(a)) for (s, a) in calls)
    per_sub[subsystem] = kept
```

(`emit`/`_emit_function` already drop empty blocks — no change; a cleared emitter list → `[]` → block dropped.)

- [ ] **Step 4: Edit `override_routing.py`** — route the `__emitter__` tag. In `HardpointOverridesFileTarget.write`, where it dispatches edit tuples, add an `__emitter__` arm alongside `__region__`:

```python
        for edit in edits:
            if len(edit) == 4 and edit[1] == "__region__":
                _, _, index, calls = edit
                set_region(models, leaf, edit[0], index, calls)
            elif len(edit) == 4 and edit[1] == "__emitter__":
                _, _, index, calls = edit
                set_region(models, leaf, edit[0], index, calls, prefix="SetLightEmitter")
            else:
                set_setter(models, leaf, edit[0], edit[1], edit[2])
```

(Match the existing dispatch shape at `override_routing.py:49-56`; only the `__emitter__` branch is new.)

- [ ] **Step 5: Add `emitter_spec_to_calls`** in `ship_property_viewer.py` (next to `region_spec_to_calls`):

```python
def emitter_spec_to_calls(index, spec):
    """Full ordered SetLightEmitter* call list for one emitter spec (Task 3).
    Point omits axis/length; strip/cone include them; all carry colour+intensity."""
    kind = spec["kind"]
    px, py, pz = spec["position"]
    r, g, b = spec["color"]
    calls = [
        ("SetLightEmitterKind", (index, kind)),
        ("SetLightEmitterPosition", (index, px, py, pz)),
        ("SetLightEmitterRadius", (index, float(spec["radius"]))),
        ("SetLightEmitterColor", (index, float(r), float(g), float(b))),
        ("SetLightEmitterIntensity", (index, float(spec["intensity"]))),
    ]
    if kind in ("strip", "cone"):
        ax, ay, az = spec["axis"]
        calls.append(("SetLightEmitterAxis", (index, ax, ay, az)))
        calls.append(("SetLightEmitterLength", (index, float(spec["length"]))))
    return calls
```

- [ ] **Step 6: Run the tests — expect PASS**, then gate.

- [ ] **Step 7: Commit.**

```bash
git add engine/appc/hardpoint_override_writer.py engine/appc/override_routing.py engine/ui/ship_property_viewer.py tests/appc/test_hardpoint_override_writer.py
git commit -m "feat(emitters): persist SetLightEmitter* via a second indexed prefix"
```

---

### Task 4: Emitter health-state resolution (flicker / offline / impulse)

**Files:**
- Modify: `engine/appc/light_emitters.py` (add `resolve_emitter_intensity`)
- Test: `tests/appc/test_light_emitters.py` (extend)

**Interfaces:**
- Consumes: `engine/appc/subsystem_glow.py:glow_state(sub)` (returns `HEALTHY`/`DISABLED`/`DESTROYED`), `impulse_gain(frac, now, powered)`.
- Produces: `resolve_emitter_intensity(spec, sub, now, throttle_frac=0.0, is_impulse=False, powered=True) -> float | None` — the per-frame intensity MULTIPLIER-applied scalar (returns `None` when the emitter is fully off, so the producer emits no light that frame). Also `emitter_flicker(now, phase) -> float`.

- [ ] **Step 1: Write the failing test** (extend `test_light_emitters.py`):

```python
from engine.appc.light_emitters import resolve_emitter_intensity
from engine.appc.subsystem_glow import HEALTHY, DISABLED, DESTROYED


class _Sub:
    def __init__(self, destroyed=False, disabled=False):
        self._d, self._x = destroyed, disabled
    def IsDestroyed(self): return self._d
    def IsDisabled(self): return self._x


def test_healthy_emitter_is_full_intensity():
    s = default_emitter_spec("point"); s["intensity"] = 3.0
    assert resolve_emitter_intensity(s, _Sub(), now=0.0) == pytest.approx(3.0)


def test_destroyed_emitter_is_off():
    s = default_emitter_spec("point")
    assert resolve_emitter_intensity(s, _Sub(destroyed=True), now=0.0) is None


def test_disabled_emitter_flickers_over_time():
    s = default_emitter_spec("point"); s["intensity"] = 4.0
    vals = [resolve_emitter_intensity(s, _Sub(disabled=True), now=t * 0.05)
            for t in range(40)]
    assert all(v is None or v <= 4.0 + 1e-6 for v in vals)
    present = [v for v in vals if v is not None]
    assert len(set(round(v, 3) for v in present)) > 1   # not a single steady value


def test_impulse_emitter_scales_with_throttle():
    s = default_emitter_spec("point"); s["intensity"] = 1.0
    lo = resolve_emitter_intensity(s, _Sub(), now=0.0, throttle_frac=0.0,
                                   is_impulse=True, powered=True)
    hi = resolve_emitter_intensity(s, _Sub(), now=0.0, throttle_frac=1.0,
                                   is_impulse=True, powered=True)
    assert hi > lo
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** in `light_emitters.py`:

```python
from engine.appc import subsystem_glow

# Disabled-state flicker: a sputtering waveform in [0, 1], deterministic in
# game time (no Math.random) with a per-emitter phase so neighbours desync.
# Tunable like subsystem_glow.PULSE_AMP — not an authored field.
_FLICKER_FLOOR = 0.05


def emitter_flicker(now: float, phase: float) -> float:
    a = math.sin(now * 37.0 + phase)
    b = math.sin(now * 11.3 + phase * 2.0)
    v = 0.35 + 0.65 * max(0.0, a * b)
    return _FLICKER_FLOOR + (1.0 - _FLICKER_FLOOR) * max(0.0, min(1.0, v))


def resolve_emitter_intensity(spec, sub, now, throttle_frac=0.0,
                              is_impulse=False, powered=True, phase=0.0):
    """Per-frame emitter intensity scalar, or None when fully off.

    HEALTHY -> base intensity; DISABLED -> base * flicker(now); DESTROYED -> off.
    Impulse-parented emitters additionally scale by subsystem_glow.impulse_gain
    so they brighten with commanded throttle exactly like the impulse glow.
    """
    base = float(spec["intensity"])
    state = subsystem_glow.glow_state(sub)
    if state == subsystem_glow.DESTROYED:
        return None
    out = base
    if state == subsystem_glow.DISABLED:
        out = base * emitter_flicker(now, phase)
    if is_impulse:
        out *= subsystem_glow.impulse_gain(throttle_frac, now, powered)
    if out <= 0.0:
        return None
    return out
```

(Confirm `subsystem_glow` exports `HEALTHY`/`DISABLED`/`DESTROYED` constants and `glow_state`/`impulse_gain`; they do — `subsystem_glow.py:94,78`.)

- [ ] **Step 4: Run — expect PASS**, gate, commit.

```bash
git add engine/appc/light_emitters.py tests/appc/test_light_emitters.py
git commit -m "feat(emitters): health-driven intensity (flicker/offline/impulse gain)"
```

---

### Task 5: Runtime producer + per-ship emitter cache

**Files:**
- Modify: `engine/host_loop.py:782` (the `set_dynamic_lights` call site) and `:882-908` (add a producer next to `_build_dynamic_light_render_data`); add a build-time cache next to the `ShipGlowController` construction (`host_loop.py:3849-3850` and `4404-4406`).
- Test: `tests/test_host_loop_emitter_lights.py` (NEW)

**Interfaces:**
- Consumes: `light_emitters.baked_emitters`, `emitter_spec_to_struct`, `resolve_emitter_intensity`; `subsystem_glow.commanded_impulse_frac`; the ship's world loc/rotation; `world_from_body`-equivalent transform.
- Produces: `_build_emitter_light_render_data(session) -> list[dict]` returning `set_dynamic_lights` dicts with WORLD positions. Wired so `set_dynamic_lights` receives `torpedoes + emitters` (clamped to 64 native-side).

- [ ] **Step 1: Write the failing test** (`tests/test_host_loop_emitter_lights.py`) — a headless unit test that patches the pieces and asserts a world-transformed, health-gated emitter light is produced. Model the fixture on existing `host_loop` producer tests (search `tests/` for `_build_dynamic_light_render_data` / `_build_hit_vfx_render_data` usage). Assert:
  - a HEALTHY point emitter on a ship at world origin with identity rotation → one light dict at the emitter's body position, with `color`/`radius`/`intensity` from the spec;
  - a DESTROYED parent → no light for that emitter;
  - a body-frame position on a rotated/translated ship → the light's `position` equals `ship_loc + R·body_pos` (column-vector `R·v`).

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Build the per-ship emitter cache at spawn.** Where `ShipGlowController` is constructed (both sites, `host_loop.py:3850` and `:4405`), add a best-effort emitter-cache build guarded the same way (never block spawn). Cache shape: `session.ship_emitters[iid] = [(sub, is_impulse, phase, spec), ...]` built by walking the ship's subsystems (reuse the same subsystem enumeration `ShipGlowController.__init__` uses — warp pods, impulse engines, sensor, and any other subsystem carrying baked emitters) and calling `baked_emitters(sub.GetProperty()...)` per subsystem. Assign each emitter a stable `phase` (e.g. `j * 1.7 + subsystem_index`). Mark `is_impulse` when the subsystem is one of the impulse engines.

Add `session.ship_emitters = {}` initialization next to `session.ship_glow_controllers`.

- [ ] **Step 4: Write the producer** in `host_loop.py` (next to `_build_dynamic_light_render_data`):

```python
def _build_emitter_light_render_data(session):
    """World-space dynamic lights from subsystem-attached emitters.

    Body-frame emitter specs (cached at spawn) are transformed to world via the
    ship's world loc + rotation (column-vector R.v), health-gated through
    light_emitters.resolve_emitter_intensity (flicker/offline), and impulse
    emitters brighten with commanded throttle. Mirror point for the torpedo
    producer above: both feed the same 64-light host list (native clamps)."""
    from engine.appc import light_emitters
    from engine.appc.subsystem_glow import commanded_impulse_frac
    out = []
    now = session.game_time if hasattr(session, "game_time") else 0.0
    for iid, entries in getattr(session, "ship_emitters", {}).items():
        ship = session.ship_of_instance(iid)      # or the existing iid->ship lookup
        if ship is None:
            continue
        loc = ship.GetWorldLocation()
        R = ship.GetWorldRotation()
        frac = commanded_impulse_frac(ship)
        for (sub, is_impulse, phase, spec) in entries:
            inten = light_emitters.resolve_emitter_intensity(
                spec, sub, now, throttle_frac=frac, is_impulse=is_impulse,
                powered=True, phase=phase)
            if inten is None:
                continue
            d = light_emitters.emitter_spec_to_struct(spec)
            d["intensity"] = inten
            d["position"] = _world_from_body(loc, R, d["position"])
            if "position_b" in d:
                d["position_b"] = _world_from_body(loc, R, d["position_b"])
            if "direction" in d:
                d["direction"] = _rotate_body(R, d["direction"])
            out.append(d)
    return out
```

Add small helpers `_world_from_body(loc, R, p)` (= `loc + R·p`, column-vector) and `_rotate_body(R, v)` (= `R·v`, no translation) using the existing `TGPoint3.MultMatrixLeft` / matrix-column convention (mirror `world_from_body` in `ship_property_viewer.py`). Use the ship→iid lookup that the surrounding code already uses (e.g. `session.ship_instances` inverse or the existing helper); match the local idiom rather than inventing a new map.

- [ ] **Step 5: Wire the call site.** At `host_loop.py:782` change:

```python
    host_io.set_dynamic_lights(
        _build_dynamic_light_render_data() + _build_emitter_light_render_data(session))
```

(Use whatever `session`/context object is in scope at that call — match the surrounding signature.)

- [ ] **Step 6: Run the tests — expect PASS**, gate, commit.

```bash
git add engine/host_loop.py tests/test_host_loop_emitter_lights.py
git commit -m "feat(emitters): per-frame producer feeds subsystem emitters to set_dynamic_lights"
```

---

### Task 6: SPV panel — emitter data model, dispatch, tree nodes, selection

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` (state, dispatch handlers, `_subsystem_rows`, selection, render payload)
- Modify: `engine/ui/ship_property_viewer.py` (`build_descriptors` emitter annotation)
- Test: `tests/ui/test_ship_property_viewer_panel_emitter.py` (NEW)

**Interfaces:**
- Consumes: `light_emitters.default_emitter_spec`, `baked_emitters`.
- Produces panel API (mirrors the light-volume API but keyed by `(subsystem_index, emitter_index)`):
  - `_pending_emitter: dict[(i, j), spec|None]`, `_saved_emitter: dict`, `_selected_emitter: tuple|None`.
  - `_descriptors[i]["emitters"]: list[spec]` (baked).
  - `_effective_emitters(i) -> list[spec]` (baked + pending/saved overrides, dropping None).
  - dispatch: `add_emitter:{i, kind}`, `set_emitter:{i, j, kind, color, intensity}`, `select_emitter:{i, j}`, `remove_emitter:{i, j}`.
  - tree: one `{"kind":"emitter", "name":"Light Emitter", "emitter_of": i, "emitter_index": j, ...}` child row per emitter.
  - selection: `_active_transform_target()` returns `("emitter", i, j)` when an emitter is selected (highest priority), mutually exclusive with subsystem/light.

- [ ] **Step 1: Write the failing tests** (`tests/ui/test_ship_property_viewer_panel_emitter.py`) — mirror `tests/ui/test_ship_property_viewer_panel_light_modal.py`'s `_panel_with_light` fixture but with an emitter. Cover:
  - `add_emitter:{i:0,kind:"point"}` on a subsystem → `_effective_emitters(0)` has one point spec; `_selected_emitter == (0, 0)`; `selected_index`/`_selected_light_index` cleared.
  - a second `add_emitter` → two emitters, selected `(0,1)`.
  - `set_emitter:{i:0,j:0,kind:"cone",color:[1,0,0],intensity:3.0}` → spec kind/color/intensity updated, geometry preserved.
  - `remove_emitter:{i:0,j:0}` → that emitter gone (None sentinel), selection cleared.
  - `_subsystem_rows()` emits an `"emitter"` child row per emitter under the subsystem.
  - render payload carries `selected_emitter`.

Use the `dispatch_event('<action>:' + json.dumps({...}))` pattern and assert return bool + state, exactly like the light-modal tests.

- [ ] **Step 2: Run — expect FAIL** (handlers missing).

- [ ] **Step 3: Add panel state** (constructor, next to `_pending_light`):

```python
        self._selected_emitter: Optional[tuple] = None   # (subsystem_idx, emitter_idx)
        self._pending_emitter: dict = {}                 # (i, j) -> spec | None (removed)
        self._saved_emitter: dict = {}
```

Reset all three to `None`/`{}` in `open()` and `close()` (alongside the light resets).

- [ ] **Step 4: Add effective-emitter resolution:**

```python
    def _baked_emitters(self, i):
        d = self._descriptors[i]
        return list(d.get("emitters") or [])

    def _effective_emitters(self, i):
        """Baked emitters for subsystem i with pending/saved (i,j) overrides
        applied; a None override drops that emitter."""
        out = list(self._baked_emitters(i))
        for source in (self._saved_emitter, self._pending_emitter):
            for (si, j), spec in source.items():
                if si != i:
                    continue
                if spec is None:
                    if 0 <= j < len(out):
                        out[j] = None
                elif j < len(out):
                    out[j] = spec
                else:
                    out.append(spec)
        return [s for s in out if s is not None]

    def _effective_emitter(self, i, j):
        if (i, j) in self._pending_emitter:
            return self._pending_emitter[(i, j)]
        if (i, j) in self._saved_emitter:
            return self._saved_emitter[(i, j)]
        baked = self._baked_emitters(i)
        return baked[j] if 0 <= j < len(baked) else None
```

- [ ] **Step 5: Add the dispatch handlers** (mirror `add_light`/`set_light`/`select_light`/`remove_light`). Key detail: the new emitter index on add = current effective length.

```python
        if action.startswith("add_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); kind = str(arg["kind"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= i < len(self._descriptors)) or kind not in ("point", "strip", "cone"):
                return False
            from engine.appc.light_emitters import default_emitter_spec
            j = len(self._effective_emitters(i))
            self._pending_emitter[(i, j)] = default_emitter_spec(kind)
            self._selected_emitter = (i, j)
            self.selected_index = None
            self._selected_light_index = None
            self._expanded_groups.add(self._descriptors[i].get("name", ""))
            self._last_pushed = None
            return True

        if action.startswith("set_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); j = int(arg["j"]); kind = str(arg["kind"])
            except (ValueError, KeyError, TypeError):
                return False
            if kind not in ("point", "strip", "cone"):
                return False
            base = dict(self._effective_emitter(i, j) or {})
            if not base:
                return False
            base["kind"] = kind
            if "color" in arg:
                base["color"] = tuple(float(c) for c in arg["color"])
            if "intensity" in arg:
                base["intensity"] = float(arg["intensity"])
            self._pending_emitter[(i, j)] = base
            self._last_pushed = None
            return True

        if action.startswith("select_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); j = int(arg["j"])
            except (ValueError, KeyError, TypeError):
                return False
            if self._effective_emitter(i, j) is None:
                return False
            self._selected_emitter = (i, j)
            self.selected_index = None
            self._selected_light_index = None
            self._expanded_groups.add(self._descriptors[i].get("name", ""))
            self._last_pushed = None
            return True

        if action.startswith("remove_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); j = int(arg["j"])
            except (ValueError, KeyError, TypeError):
                return False
            self._pending_emitter[(i, j)] = None
            if self._selected_emitter == (i, j):
                self._selected_emitter = None
            self._last_pushed = None
            return True
```

Also clear `_selected_emitter` in the `select_pin`/`select_light`/`deselect` handlers (add `self._selected_emitter = None` everywhere those clear `_selected_light_index`).

- [ ] **Step 6: Emit emitter child rows** in `_subsystem_rows()` (next to the Light-Volume child loop):

```python
        for i in range(len(self._descriptors)):
            for j, spec in enumerate(self._effective_emitters(i)):
                by_index[i]["children"].append({
                    "kind": "emitter",
                    "name": "Light Emitter",
                    "emitter_of": i,
                    "emitter_index": j,
                    "emitter_kind": spec["kind"],
                    "emitter_spec": spec,
                    "dirty": ((i, j) in self._pending_emitter),
                })
```

- [ ] **Step 7: Wire selection + payload.** In `_active_transform_target()` add the emitter arm FIRST (highest priority):

```python
        if self._selected_emitter is not None:
            return ("emitter",) + self._selected_emitter   # ("emitter", i, j)
        if self._selected_light_index is not None:
            return ("light", self._selected_light_index)
        if self.selected_index is not None:
            return ("subsystem", self.selected_index)
        return None
```

Include `self._selected_emitter` in the render-payload snapshot key and emit `"selected_emitter": list(self._selected_emitter) if self._selected_emitter else None`. In `subsystem_pins()`, when an emitter is selected show only its parent subsystem pin (mirror the `_selected_light_index` branch, using `self._selected_emitter[0]`).

- [ ] **Step 8: Annotate descriptors with baked emitters** in `ship_property_viewer.py:build_descriptors` (next to the `light`/`light_region` annotation ~215-227):

```python
        try:
            from engine.appc.light_emitters import baked_emitters
            out[di]["emitters"] = baked_emitters(_subsystem_property(sub))
        except Exception:
            out[di]["emitters"] = []
```

Use the same property accessor `build_descriptors` already uses to read glow regions (mirror how `light_region` is sourced).

- [ ] **Step 9: Run the tests — expect PASS**, gate, commit.

```bash
git add engine/ui/ship_property_viewer_panel.py engine/ui/ship_property_viewer.py tests/ui/test_ship_property_viewer_panel_emitter.py
git commit -m "feat(spv): emitter child nodes — data model, dispatch, tree, selection"
```

---

### Task 7: SPV gizmo routing for emitters (transform / scale / rotate)

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` (gizmo target arms)
- Test: `tests/ui/test_ship_property_viewer_panel_emitter.py` (extend, reuse `_begin_axis_drag_for_test`)

**Interfaces:**
- Consumes: the gizmo helpers in `ship_property_viewer.py` (`world_from_body`, `pick_gizmo_axis`, `axis_drag_param`, `rotate_about_axis`, etc.) — unchanged.
- Produces: transform/scale/rotate now act on an `("emitter", i, j)` target. Scale kinds: **point → `radius`**, **strip → `radius_length`**, **cone → `radius_length_angle`** (axial handle = Length/range, perpendicular handles = Radius/base-radius; the cone half-angle is derived, so no separate field). Rotate: strip → rotate `axis`; cone → rotate `axis`; point → inert.

- [ ] **Step 1: Write the failing tests** (extend the emitter test file), reusing the drag harness:
  - transform: select an emitter, `_begin_axis_drag_for_test(axis=0, grab_param=0.0)`, `_apply_axis_drag(1.5)` → `_effective_emitter(i,j)["position"]` X moved by 1.5.
  - scale (strip): axial handle scales `length`, perpendicular scales `radius`.
  - scale (cone): perpendicular handle grows `radius` (→ wider derived angle); axial grows `length`.
  - rotate (cone): a ring drag rotates `axis`.
  - point rotate inert: `_rotate_target()` returns None for a point emitter.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Add a position read/write arm.** Add `set_emitter_position(i, j, body_pos)` (writes `spec["position"]` into `_pending_emitter[(i,j)]`) and route `_begin_axis_drag`/`_apply_axis_drag` to it when the target kind is `"emitter"` (mirror `set_light_position` at panel `364-371` and the light branch in `_apply_axis_drag`).

- [ ] **Step 4: Extend `transform_gizmo()`/`scale_gizmo()`/`rotate_gizmo()`** to compute their origin from `_effective_emitter(i,j)["position"]` via `world_from_body(ship, pos)` when the target is `("emitter", i, j)` (mirror the light origin branch).

- [ ] **Step 5: Extend `_scale_kind_and_fields(target)`** with an emitter arm:

```python
        if kt == "emitter":
            _, i, j = target
            spec = self._effective_emitter(i, j)
            if not spec:
                return "radius", [{"label": "Radius", "value": 0.0}]
            kind = spec.get("kind", "point")
            if kind == "point":
                return "radius", [{"label": "Radius", "value": float(spec["radius"])}]
            # strip and cone both expose Radius + Length; cone's angle is derived.
            return "radius_length", [
                {"label": "Radius", "value": float(spec["radius"])},
                {"label": "Length", "value": float(spec["length"])}]
```

(Unpack `kt, *rest = target` at the top of the method so both the 2-tuple light/subsystem targets and the 3-tuple emitter target work. Cone reuses `radius_length`; no new gizmo kind is needed because the perpendicular handle already maps to Radius, which IS the angle driver.)

- [ ] **Step 6: Extend `_set_scale_field(index, value)`** with an emitter arm writing scalar `radius`/`length` (simpler than the glow tuple form):

```python
        if kt == "emitter":
            _, i, j = t
            spec = dict(self._effective_emitter(i, j) or {})
            if not spec:
                return
            if index == 0:               # Radius / base-radius
                spec["radius"] = value
            else:                        # Length / range
                spec["length"] = value
            self._pending_emitter[(i, j)] = spec
            self._last_pushed = None
            return
```

Ensure `_begin_scale_drag` maps the axial (axis-aligned-with-emitter-`axis`) handle to field 1 (Length) and the two perpendicular handles to field 0 (Radius) for emitters — reuse the same dominant-body-axis logic the cylinder uses, reading `spec["axis"]` for emitters.

- [ ] **Step 7: Extend `_rotate_target()` and `_apply_ring_drag_angle()`** for emitters:

```python
        # in _rotate_target(), after unpacking the target:
        if kt == "emitter":
            _, i, j = t
            spec = self._effective_emitter(i, j)
            if not spec or spec.get("kind") not in ("strip", "cone"):
                return None
            return ("emitter", i, j)
```

In `_apply_ring_drag_angle`, add an emitter branch that rotates `spec["axis"]` via `rotate_about_axis(self._ring_grab_axis, k, d_body)` and writes `_pending_emitter[(i,j)]` (mirror the cylinder/light `axis` branch; strip and cone both rotate their single axis — no orientation basis needed).

- [ ] **Step 8: Run the tests — expect PASS**, gate, commit.

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_emitter.py
git commit -m "feat(spv): transform/scale/rotate routing for emitters (point/strip/cone)"
```

---

### Task 8: Cone wireframe primitive (`DebugCone`)

**Files:**
- Modify: `native/src/renderer/include/renderer/debug_volume_pass.h` (add `DebugCone` struct + a `render` overload + `ensure_cone_resources` + VAO/VBO/count members)
- Modify: `native/src/renderer/debug_volume_pass.cc` (mesh build + render, cloning the `DebugSphere` triple at `:188-265`)
- Modify: `native/src/host/host_bindings.cc` (`set_debug_cones`/`g_debug_cones`/`clear_debug_cones` cloning `set_debug_spheres:2491-2515`; frame-draw wiring at `:923-924`; pass reset)
- Modify: `engine/renderer.py` (`set_debug_cones` wrapper cloning `set_debug_spheres:981`)
- Test: extend the debug-volume ctest if one exists, else a smoke FrameTest that a cone primitive renders without GL error.

**Interfaces:**
- Produces: `renderer.set_debug_cones(list)` where each item is `{"apex":(x,y,z), "axis":(x,y,z), "radius":r, "length":L, "color":(r,g,b)}` (angle is implied by radius/length — the base ring sits at `apex + axis*length` with radius `radius`).

- [ ] **Step 1: Add `DebugCone` struct** in `debug_volume_pass.h` (clone `DebugSphere`, the smallest primitive):

```cpp
struct DebugCone {
    glm::vec3 apex{0.0f};
    glm::vec3 axis{0.0f, -1.0f, 0.0f};   // unit, apex -> base
    float     radius = 1.0f;             // base radius
    float     length = 1.0f;             // apex -> base distance
    glm::vec3 color{1.0f, 0.55f, 0.1f};
};
```

Add a `render(const std::vector<DebugCone>&, const Camera&)` overload, an `ensure_cone_resources()`, and `cone_vao_/cone_vbo_/cone_vertex_count_` members (mirror the sphere members).

- [ ] **Step 2: Build the cone mesh** in `ensure_cone_resources()` — a unit cone (apex at origin, base ring of `kSeg=24` verts at `+Z`, radius 1, length 1): side triangles (apex→ring[i]→ring[i+1]) + base fan. Store as a `GL_TRIANGLES` vertex list, drawn in `GL_LINE` polygon mode (the existing pass sets line mode + `u_alpha=0.5`). Mirror `ensure_sphere_resources:188-230`.

- [ ] **Step 3: Implement the `render(DebugCone...)` overload** (clone the sphere render at `:232-265`): per cone build a model matrix that maps unit-`+Z` to `axis`, scales `+Z` by `length` and X/Y by `radius`, translates to `apex`; upload color + `u_alpha`; `glDrawArrays`. Build the axis→matrix with any stable up (e.g. Gram-Schmidt against world-up, fall back to world-X when parallel).

- [ ] **Step 4: Host binding** — add `g_debug_cones`, `set_debug_cones` (parse `apex`/`axis`/`radius`/`length`/`color`), `clear_debug_cones`, and the frame-draw line `if (viewer_mode && g_debug_volume_pass && !g_debug_cones.empty()) g_debug_volume_pass->render(g_debug_cones, g_camera);` next to the sphere draw (`:923-924`). Clear `g_debug_cones` where the other debug lists reset.

- [ ] **Step 5: Python wrapper** — `engine/renderer.py:set_debug_cones(self, cones)` cloning `set_debug_spheres`; hasattr-guard the underlying `_h` call so a stale binary no-ops instead of crashing (the established `r.<binding>` pattern).

- [ ] **Step 6: Reconfigure + build** (`cmake -B build -S . && cmake --build build -j`), then a smoke check that `set_debug_cones` exists on the module and renders without error.

- [ ] **Step 7: Gate + commit.**

```bash
git add native/src/renderer/include/renderer/debug_volume_pass.h native/src/renderer/debug_volume_pass.cc native/src/host/host_bindings.cc engine/renderer.py native/tests/
git commit -m "feat(renderer): DebugCone wireframe primitive for emitter overlay"
```

---

### Task 9: Emitter overlay feed + panel save routing

**Files:**
- Modify: `engine/ui/glow_region_overlay.py` (add `build_emitter_overlay`)
- Modify: `engine/host_loop.py` (feed `set_debug_cones` + reuse sphere/cylinder for point/strip in the SPV overlay block ~`:7378-7391`)
- Modify: `engine/ui/ship_property_viewer_panel.py` (save handler: route `_pending_emitter` via `emitter_spec_to_calls` + `__emitter__` edits)
- Test: `tests/ui/test_ship_property_viewer_panel_emitter.py` (extend — save produces `__emitter__` edits)

**Interfaces:**
- Consumes: `emitter_spec_to_calls` (Task 3), `set_debug_cones` (Task 8), existing `set_debug_spheres`/`set_debug_cylinders`.
- Produces: `build_emitter_overlay(ship, panel) -> (spheres, cylinders, cones)` returning wireframe dicts for the SELECTED emitter only (selection-scoped, mirroring `build_glow_region_overlay`); the panel save writes `(name, "__emitter__", j, emitter_spec_to_calls(j, spec) if spec is not None else [])` edits.

- [ ] **Step 1: Write the failing test** — after staging two emitters and removing one, the panel's save-edit list (factor the edit-building into a testable `_emitter_save_edits()` helper, mirroring how the light save builds edits) contains an `__emitter__` 4-tuple per pending `(i, j)`, with `[]` for the removed one (drives the writer's drop-empty path). Assert the edit tuples' shape and that `emitter_spec_to_calls` output is present for the kept one.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Extend the panel save handler.** Where `_pending_light` becomes `__region__` edits, add `_pending_emitter` → `__emitter__` edits:

```python
        edits += [(self._descriptors[i]["name"], "__emitter__", j,
                   emitter_spec_to_calls(j, spec) if spec is not None else [])
                  for (i, j), spec in sorted(self._pending_emitter.items())]
```

On save success also `self._saved_emitter.update(self._pending_emitter); self._pending_emitter = {}` (mirror the light save at panel `:1705-1706`). Import `emitter_spec_to_calls` next to `region_spec_to_calls`.

- [ ] **Step 4: Add `build_emitter_overlay`** in `glow_region_overlay.py`:

```python
def build_emitter_overlay(ship, panel):
    """Wireframes for the currently-selected emitter only (selection-scoped).
    Returns (spheres, cylinders, cones) of overlay dicts in WORLD space."""
    from engine.ui.ship_property_viewer import world_from_body
    spheres, cylinders, cones = [], [], []
    sel = getattr(panel, "_selected_emitter", None)
    if sel is None:
        return spheres, cylinders, cones
    i, j = sel
    spec = panel._effective_emitter(i, j)
    if not spec:
        return spheres, cylinders, cones
    center = world_from_body(ship, spec["position"])
    color = tuple(spec["color"])
    kind = spec["kind"]
    if kind == "point":
        spheres.append({"center": center, "radius": spec["radius"], "color": color})
    elif kind == "strip":
        cylinders.append({"center": center, "axis": _world_dir(ship, spec["axis"]),
                          "radius": spec["radius"], "length": spec["length"], "color": color})
    else:  # cone
        cones.append({"apex": center, "axis": _world_dir(ship, spec["axis"]),
                      "radius": spec["radius"], "length": spec["length"], "color": color})
    return spheres, cylinders, cones
```

Add a small `_world_dir(ship, body_axis)` helper (= `R·axis`, no translation) mirroring the rotation-only transform used elsewhere in this file.

- [ ] **Step 5: Feed the overlay** in `host_loop.py` where the glow overlay is pushed (`:7378-7391`): call `build_emitter_overlay(ship, panel)` and merge its spheres/cylinders into the existing `set_debug_spheres`/`set_debug_cylinders` payloads (or push additively) and push cones via `set_debug_cones`. Keep it selection-scoped so only the selected emitter draws.

- [ ] **Step 6: Run the tests — expect PASS**, gate, commit.

```bash
git add engine/ui/glow_region_overlay.py engine/host_loop.py engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_emitter.py
git commit -m "feat(spv): emitter wireframe overlay + save routing to hardpoint_overrides"
```

---

### Task 10: CEF modal — type picker + colour wheel + intensity slider

**Files:**
- Modify: `native/assets/ui-cef/index.html` (`#spv-emitter` modal + ctx menu items)
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js` (emitter modal handlers, colour wheel, intensity slider, ctx wiring, row menu for emitter nodes)

**Interfaces:**
- Consumes: the panel dispatch actions from Task 6 (`add_emitter:`, `set_emitter:`, `select_emitter:`, `remove_emitter:`) via the existing `dauntlessEvent('ship-property-viewer/<action>')` bridge.
- Produces: an emitter modal that fires `add_emitter:{i,kind}` / `set_emitter:{i,j,kind,color,intensity}`; a canvas hue/sat colour wheel (pointer drag) + an HDR intensity slider (pointer drag). Mouse-only.

This task is verified in-game (CEF DOM has no automated test); the dispatch behaviour it drives is already covered by the Task 6/7/9 pytest.

- [ ] **Step 1: Add the ctx menu items** in `index.html` (next to the light items at `:350-355`):

```html
        <div id="spv-ctx-addemitter" class="spv-ctxmenu__item" style="display:none;" onclick="shipPropertyViewerCtxAddEmitter()">Add Light Emitter…</div>
        <div id="spv-ctx-editemitter" class="spv-ctxmenu__item" style="display:none;" onclick="shipPropertyViewerCtxEditEmitter()">Edit Emitter…</div>
        <div id="spv-ctx-removeemitter" class="spv-ctxmenu__item" style="display:none;" onclick="shipPropertyViewerCtxRemoveEmitter()">Remove Light Emitter</div>
```

- [ ] **Step 2: Add the `#spv-emitter` modal** in `index.html` (clone `#spv-light` at `:374-390`): a title, a type-button row (Point/Strip/Cone → `shipPropertyViewerEmitterKind(...)`), a `<canvas id="spv-emitter-wheel" width="160" height="160">` for hue/sat, an intensity slider row (a track `<div>` + fill, pointer-drag; plus `−/value/+` steppers referencing `spv-em-intensity`), and Cancel/Apply buttons calling `shipPropertyViewerEmitterCancel()` / `shipPropertyViewerEmitterApply()`.

- [ ] **Step 3: JS state + kind/colour/intensity handlers** (`ship_property_viewer.js`, next to the light modal state ~`:210-219`):

```javascript
var spvEmitterMode = 'add';         // 'add' | 'edit'
var spvEmitterTarget = null;        // {i, j} for edit, {i} for add
var spvEmitter = null;              // {kind, hue, sat, intensity}

function spvEmitterDefaults() { return {kind: 'point', hue: 40, sat: 0.3, intensity: 2.0}; }

window.shipPropertyViewerEmitterKind = function (kind) {
    spvEmitter.kind = kind;
    ['point', 'strip', 'cone'].forEach(function (k) {
        var b = document.getElementById('spv-emkind-' + k);
        if (b) b.classList.toggle('active', k === kind);
    });
};
```

Add `spvHsToRgb(hue, sat)` (HSV with V=1 → linear-ish RGB triple 0..1), a `spvDrawWheel()` that paints the hue/sat disc onto the canvas once, and pointer handlers on the canvas that set `spvEmitter.hue/sat` from the click radius/angle and redraw a selection marker. Add pointer-drag handlers on the intensity track mapping x → `spvEmitter.intensity` in `[0, 8]`, plus the stepper `+/−` (clamp `>= 0`).

- [ ] **Step 4: Context openers + Apply.**

```javascript
window.shipPropertyViewerCtxAddEmitter = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    spvEmitterMode = 'add';
    spvEmitterTarget = {i: spvCtxIndex};
    spvEmitter = spvEmitterDefaults();
    document.getElementById('spv-emitter-title').textContent = 'Add Light Emitter';
    shipPropertyViewerEmitterKind(spvEmitter.kind);
    spvDrawWheel();
    document.getElementById('spv-emitter').style.display = 'flex';
};

window.shipPropertyViewerEmitterApply = function () {
    var rgb = spvHsToRgb(spvEmitter.hue, spvEmitter.sat);
    var payload;
    if (spvEmitterMode === 'add') {
        payload = {i: spvEmitterTarget.i, kind: spvEmitter.kind};
        dauntlessEvent('ship-property-viewer/add_emitter:' + JSON.stringify(payload));
        // colour/intensity applied via a follow-up set_emitter on the new (last) index:
        // the panel selects the new emitter; send set_emitter with its index.
    } else {
        payload = {i: spvEmitterTarget.i, j: spvEmitterTarget.j, kind: spvEmitter.kind,
                   color: rgb, intensity: spvEmitter.intensity};
        dauntlessEvent('ship-property-viewer/set_emitter:' + JSON.stringify(payload));
    }
    spvHideOverlays();
};
```

For **add**, colour/intensity are applied by having the panel echo the new emitter's `(i, j)` back in the render payload (`selected_emitter`); the JS, on the next `setShipPropertyViewer`, sends a `set_emitter:{i,j,kind,color,intensity}` to stamp colour+intensity onto the just-added emitter. (Simpler alternative if the echo is awkward: extend the panel `add_emitter` handler to also accept optional `color`/`intensity` in its payload and seed the default spec with them — pick whichever the implementer finds cleaner; if seeding on add, update the Task 6 `add_emitter` handler and its test accordingly.)

- [ ] **Step 5: Edit opener + remove + row menu.** `shipPropertyViewerCtxEditEmitter` seeds `spvEmitter` from the selected emitter row's `emitter_spec` (kind + colour→hue/sat + intensity), sets mode `'edit'` + `spvEmitterTarget={i,j}`, opens the modal. `shipPropertyViewerCtxRemoveEmitter` fires `remove_emitter:{i,j}`. In `spvRowHtml`, render `kind==='emitter'` rows (label "Light Emitter", a right-click menu `shipPropertyViewerEmitterMenu(event, emitter_of, emitter_index)` that shows edit/remove; the subsystem row menu also shows `addemitter:true`). Cache each emitter row's spec (`spvRowEmitter[i+'/'+j] = row.emitter_spec`) in `spvSeedRow`.

- [ ] **Step 6: Build (CEF assets load from source — a rebuild copies them; confirm the modal opens).** Manual in-game verification by Mark: add each emitter kind, pick a colour + intensity, see the wireframe; save; reload; confirm persistence and in-mission cast light + damage flicker.

- [ ] **Step 7: Gate + commit** (pytest/ctest unaffected; the gate confirms no regressions).

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js
git commit -m "feat(spv): emitter CEF modal — type picker, colour wheel, HDR intensity"
```

---

## Self-review notes (author)

- **Spec coverage:** point/strip/cone (Tasks 1,2,7,8,10); health flicker/offline + impulse gain (Task 4/5); colour wheel + HDR intensity (Task 10); independent subsystem-child data model (Task 6); transform/scale/rotate reuse (Task 7); persistence to `hardpoint_overrides.py` (Tasks 3,9); wireframe-now/light-in-game (Tasks 8,9 overlay vs Task 5 producer). All spec sections map to a task.
- **Byte-identity:** guarded in Task 1 (Steps 4/8) — the only production-render change, gated by the count==0 FrameTests and the `cos_half_angle < 0` short-circuit.
- **Type consistency:** the emitter spec dict shape is fixed once at the top and used verbatim in every task; setter field names (`LightEmitter{Kind,Position,Axis,Length,Radius,Color,Intensity}`) are identical across Tasks 2/3; scale-field indices (0=Radius, 1=Length) match between Task 7's `_scale_kind_and_fields` and `_set_scale_field`.
- **Open implementer choice flagged:** Task 10 Step 4 offers two equivalent ways to apply colour/intensity on *add* (echo-then-set vs seed-on-add); if the implementer seeds on add, Task 6's handler+test update in lockstep.
```
