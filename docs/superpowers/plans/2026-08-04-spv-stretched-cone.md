# Stretched (Elliptical, Oriented) Cone Emitter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the cone light emitter to an **elliptical, oriented** cone (two base radii + an authored roll/up), so it beams like a slit and doesn't wrap around the hull — the cheap, shadow-free alternative to per-light shadows.

**Architecture:** Extend the existing forward dynamic-light path. The cone spot test becomes an **elliptical tangent test** in the cone's oriented frame (aim + up). A circular cone is the special case (equal radii). The `cos_half_angle` descriptor field is repurposed to the major tangent `spot_tan_x` (its `< 0` "not a cone" sentinel preserved, so point/strip stay byte-identical). The SPV cone gains a second scale radius and a Box-style oriented rotate, reusing the oriented-box-glow machinery (`orthonormalize_basis`, `rotate_about_axis`, the `SetGlowRegionOrientation` emit pattern).

**Tech Stack:** C++17 renderer (OpenGL/GLSL, pybind11), Python 3 engine, CEF (no CEF change this feature). Build: `cmake -B build -S . && cmake --build build -j`. Gate: `scripts/check_tests.sh`.

## Global Constraints

- **Point/strip and all non-cone dynamic lights (torpedo glow) stay byte-identical.** The descriptor's cone field (`spot_tan_x`) keeps the `< 0` = "not a cone" sentinel → shader `spot = 1.0` → no change; `u_dyn_light_count == 0` frames unchanged. Prove this in the migrated FrameTest.
- **Existing circular cones render unchanged.** A cone with `radius_y == radius` (and a derived up) is a round beam with the same half-angle boundary (`tan(half) = radius/length`). Legacy saved cones (no `radius_y`/`up` setters) load circular via reader defaults.
- **The ellipse's roll matters only for elliptical cones.** `up` is authored/persisted only when `radius_y != radius`; a circular cone derives up (roll is irrelevant for a circle).
- **Rotation is column-vector, right-handed** (CLAUDE.md): body→world via `MultMatrixLeft` (= `R·v`); `orthonormalize_basis`/`rotate_about_axis` are the shared helpers. Never `GetRow`.
- **Emitter writes use WHOLE-LIST-PER-SUBSYSTEM restage** (`lst = list(self._effective_emitters(i)); lst[j] = spec; self._pending_emitter[i] = lst`) — never a `(i,j)` tuple key, never an index gap (`baked_emitters` stops at the first unset index).
- **Shader edits (`.frag`) require `cmake -B build -S .` reconfigure before build.** Native edits need a `dauntless` rebuild.
- **`engine/appc/hardpoint_overrides.py` is machine-owned** — never staged by a subagent; the controller commits Mark's in-game saves separately.
- **Game units (GU)**; no `*_m` names.
- Gate every task with `scripts/check_tests.sh` (build + pytest + ctest vs `tests/known_failures.txt`; only the baselined failures are acceptable). Run it in the FOREGROUND.
- Spec: `docs/superpowers/specs/2026-08-04-spv-stretched-cone-design.md`.

---

## Canonical shapes (used across tasks)

**Cone emitter spec** (`engine/appc/light_emitters.py`) gains two fields:
```
{ kind:"cone", position, axis, length, radius,   # radius = radius_x (right-axis base radius)
  radius_y,        # NEW: base radius along the up axis; default == radius (circular)
  up,              # NEW: orientation up-vector (3-tuple); forward = normalized axis; default derived
  color, intensity }
```
Derived: `forward = normalize(axis)`, `right = normalize(cross(forward, up))`, `up = cross(right, forward)` (re-orthonormalized). `spot_tan_x = radius/length`, `spot_tan_y = radius_y/length`.

**`DynamicLightDescriptor`** (`frame.h`): rename `cos_half_angle` → `spot_tan_x` (`< 0` sentinel kept), add `glm::vec3 up{0,1,0}` and `float spot_tan_y = -1.0f`.

**Shared up-derivation rule** (Python + C++ must agree for the wireframe/shader of an elliptical cone; irrelevant for circular): `up_ref = (abs(forward.y) < 0.99) ? (0,1,0) : (1,0,0)`, then Gram-Schmidt against forward — the same rule `DebugCone::render` already uses (`debug_volume_pass.cc:346-349`).

---

## File Structure

- **Renderer (Task 1):** `native/src/renderer/include/renderer/frame.h`, `frame.cc`, `shaders/opaque.frag`, `native/src/host/host_bindings.cc`, `native/src/renderer/include/renderer/debug_volume_pass.h`, `debug_volume_pass.cc`, `native/tests/renderer/test_cone_light_frame.cc`.
- **Data/persistence/producer (Task 2):** `engine/appc/light_emitters.py`, `engine/ui/ship_property_viewer.py` (`emitter_spec_to_calls`), `engine/host_loop.py` (`_build_emitter_light_render_data`), tests.
- **SPV scale+rotate (Task 3):** `engine/ui/ship_property_viewer_panel.py`, tests.
- **Overlay (Task 4):** `engine/ui/glow_region_overlay.py`, `engine/renderer.py` (docstring), tests.

---

### Task 1: Renderer — elliptical oriented cone (spot test + up + elliptical DebugCone + FrameTest)

**Files:** `frame.h`, `frame.cc`, `opaque.frag`, `host_bindings.cc`, `debug_volume_pass.{h,cc}`, `test_cone_light_frame.cc`.

**Interfaces produced:**
- `DynamicLightDescriptor`: `spot_tan_x` (was `cos_half_angle`; `< 0` = not a cone), `up` (vec3), `spot_tan_y` (float).
- `set_dynamic_lights` dict keys: `direction`, `up` (3-tuples), `spot_tan_x`, `spot_tan_y` (floats). All optional; absent ⇒ not a cone.
- `DebugCone`: gains `radius_y` + `up`; `set_debug_cones` dict gains `radius_y`, `up`.

- [ ] **Step 1: Struct.** In `frame.h:129-137`, rename `cos_half_angle`→`spot_tan_x` and add fields:
```cpp
struct DynamicLightDescriptor {
    glm::vec3 pos_a{0.0f};
    glm::vec3 pos_b{0.0f};
    glm::vec3 color{1.0f};
    float     radius    = 0.0f;
    float     intensity = 1.0f;
    glm::vec3 direction{0.0f};       // cone forward axis (world, unit); ignored if not a cone
    float     spot_tan_x = -1.0f;    // < 0 => not a cone. tan(half-angle) along `right` (= radius/length).
    glm::vec3 up{0.0f, 1.0f, 0.0f};  // cone up axis (world, unit) — orients the ellipse
    float     spot_tan_y = -1.0f;    // tan(half-angle) along `up` (= radius_y/length)
};
```

- [ ] **Step 2: Upload.** In `frame.cc:376-393`, pack `ld` with `spot_tan_x` and add a `le` array → `u_dyn_light_up`:
```cpp
            glm::vec4 ld[kMaxDynamicLightsPerDraw];   // dir.xyz, spot_tan_x
            glm::vec4 le[kMaxDynamicLightsPerDraw];   // up.xyz,  spot_tan_y
            for (int i = 0; i < dyn_light_count; ++i) {
                ...
                ld[i] = glm::vec4(dyn_lights[i].direction, dyn_lights[i].spot_tan_x);
                le[i] = glm::vec4(dyn_lights[i].up,        dyn_lights[i].spot_tan_y);
            }
            ...
            prog.set_vec4_array("u_dyn_light_dir", ld, dyn_light_count);
            prog.set_vec4_array("u_dyn_light_up",  le, dyn_light_count);
```

- [ ] **Step 3: Shader — declare + elliptical test.** In `opaque.frag`, after line 51 add `uniform vec4 u_dyn_light_up[MAX_DYN_LIGHTS];   // up.xyz, spot_tan_y`. Replace the circular gate (lines 513-524) with:
```glsl
        // Cone/spot gate: spot_tan_x < 0 => not a cone => spot == 1.0
        // (byte-identical to the pre-cone shader for point/strip lights).
        float tx = u_dyn_light_dir[i].w;
        float spot = 1.0;
        if (tx >= 0.0) {
            vec3 fwd = normalize(u_dyn_light_dir[i].xyz);
            vec3 upv = normalize(u_dyn_light_up[i].xyz);
            vec3 rgt = cross(fwd, upv);
            if (dot(rgt, rgt) > 1e-6) {          // guard degenerate up
                rgt = normalize(rgt);
                upv = cross(rgt, fwd);
                float ty = u_dyn_light_up[i].w;
                vec3  dld = normalize(-L);        // light -> fragment
                float fz  = dot(dld, fwd);
                if (fz > 1e-4) {
                    float ex = dot(dld, rgt) / (fz * tx);
                    float ey = dot(dld, upv) / (fz * ty);
                    float e  = ex*ex + ey*ey;     // <= 1 inside the elliptical cone
                    spot = 1.0 - smoothstep(1.0 - 0.15, 1.0, e);  // soft edge
                } else {
                    spot = 0.0;                   // behind the aim
                }
            }
        }
        att *= spot;
```
(`tx < 0` short-circuits before any new math ⇒ point/strip byte-identical. Circular cone: `tx == ty` ⇒ round beam. The `0.15` e-space penumbra is the tunable softness.)

- [ ] **Step 4: Binding.** In `host_bindings.cc:2269-2276`, replace the `direction`/`cos_half_angle` parse with `direction`, `up`, `spot_tan_x`, `spot_tan_y` (all optional; `spot_tan_x`/`spot_tan_y` default to the struct's `-1.0f`, `up` to `{0,1,0}`):
```cpp
                  if (d.contains("direction") && !d["direction"].is_none()) { /* -> l.direction */ }
                  if (d.contains("up") && !d["up"].is_none()) { /* -> l.up */ }
                  if (d.contains("spot_tan_x") && !d["spot_tan_x"].is_none()) l.spot_tan_x = d["spot_tan_x"].cast<float>();
                  if (d.contains("spot_tan_y") && !d["spot_tan_y"].is_none()) l.spot_tan_y = d["spot_tan_y"].cast<float>();
```
Update the docstring (2281-2286) to the new cone keys.

- [ ] **Step 5: DebugCone elliptical.** In `debug_volume_pass.h:45-51` add `float radius_y = 1.0f;` and `glm::vec3 up{0.0f, 1.0f, 0.0f};` to `DebugCone`. In `debug_volume_pass.cc:336-360` change the model-matrix build so `M[0] = right·radius`, `M[1] = up·radius_y`, `M[2] = forward·length`, using the **authored up** (Gram-Schmidt fallback when `up` is degenerate/parallel — keep the existing `abs(w.y)<0.99` rule as the fallback path). Keep the zero-axis guard (line 340). In `host_bindings.cc:2531-2557` (`set_debug_cones`) parse optional `radius_y` (default = `radius`) and `up`.

- [ ] **Step 6: Migrate the FrameTest.** In `test_cone_light_frame.cc`: change the cone construction (line 141) from `light.cos_half_angle = std::cos(glm::radians(30.0f))` to `light.spot_tan_x = std::tan(glm::radians(30.0f)); light.spot_tan_y = std::tan(glm::radians(30.0f)); light.up = glm::vec3(0,1,0);`. The `NegativeCosHalfAngleActsAsNonConeIdentity` test (line 195) sets `light.spot_tan_x = -1.0f` (rename it to `NegativeSpotTanActsAsNonConeIdentity`). Update header/inline comments (lines 6-13, 128-134, 173-178). **Add a 3rd test `EllipticalConeBoundsToEllipse`:** a cone with `spot_tan_x = tan(45°)` (wide) and `spot_tan_y = tan(10°)` (narrow), `up=(0,1,0)`, aim `-Z` — assert a fragment offset along the wide (x) axis inside 45° is lit, and a fragment offset the same angle along the narrow (y) axis is dark. Keep the on-axis-lit + circular assertions.

- [ ] **Step 7: Reconfigure + build + gate.** `cmake -B build -S . && cmake --build build -j`, then `scripts/check_tests.sh`. Expected: the 3 cone FrameTests pass; no new failures. Byte-identity: any count==0 FrameTest unchanged.

- [ ] **Step 8: Commit** (explicit pathspec of the 6 files).

---

### Task 2: Data model + persistence + producer (elliptical cone spec, setters, tangents, up transform)

**Files:** `engine/appc/light_emitters.py`, `engine/ui/ship_property_viewer.py`, `engine/host_loop.py`, tests (`tests/appc/test_light_emitters.py`, and the producer test `tests/test_host_loop_emitter_lights.py`).

**Interfaces:**
- Consumes Task 1's dict keys (`up`, `spot_tan_x`, `spot_tan_y`).
- Produces: cone spec `radius_y`/`up`; setters `SetLightEmitterRadiusY`, `SetLightEmitterUp`; `emitter_spec_to_struct` cone output.

- [ ] **Step 1: Write failing tests** (`test_light_emitters.py`): (a) `default_emitter_spec("cone")` has `radius_y == radius` and an `up`; (b) an elliptical cone (`radius_y != radius`, explicit up) round-trips through `emitter_spec_to_calls` → recorded setters → `baked_emitters` (RadiusY + Up preserved); (c) a **legacy** cone (only Kind/Position/Axis/Length/Radius/Color/Intensity setters, no RadiusY/Up) loads with `radius_y == radius` and a derived `up` (circular); (d) `emitter_spec_to_struct` for an elliptical cone outputs `spot_tan_x = radius/length`, `spot_tan_y = radius_y/length`, and a unit `up`, and NO `cos_half_angle`; (e) a circular cone's `emitter_spec_to_struct` has `spot_tan_x == spot_tan_y`; (f) `emitter_spec_to_calls` emits RadiusY+Up ONLY when `radius_y != radius`.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: `light_emitters.py`.**
  - `default_emitter_spec` cone: add `"radius_y": 1.0` (== radius) and `"up": (0.0, 0.0, 1.0)` (a canonical perpendicular to the default axis `(0,-1,0)`). *(Add these keys for ALL kinds or gate on cone — simplest: add to the returned dict unconditionally; point/strip ignore them.)*
  - Add `_derive_up(axis)`: the shared Gram-Schmidt rule (`up_ref = (abs(fy)<0.99)?(0,1,0):(1,0,0)`; return `normalize(up_ref - dot(up_ref, f)*f)` where `f = _normalize(axis)`).
  - `baked_emitters`: read `radius_y = read_indexed_setter_args(prop,"LightEmitterRadiusY",i)` (default = the read `radius`) and `up = read_indexed_setter_args(prop,"LightEmitterUp",i)` (default = `_derive_up(axis)`); include both in every emitter dict (harmless for point/strip).
  - `emitter_spec_to_struct` cone branch: replace the `cos_half_angle` line with:
    ```python
    f = _normalize(spec["axis"]); length = max(float(spec["length"]), 1e-6)
    up = spec.get("up"); up = up if up else _derive_up(f)
    d["direction"] = f
    d["up"] = _orthonormalized_up(f, up)   # up made perpendicular to f
    d["spot_tan_x"] = float(spec["radius"]) / length
    d["spot_tan_y"] = float(spec.get("radius_y", spec["radius"])) / length
    ```
    (`_orthonormalized_up` = Gram-Schmidt up vs f, normalized — or import `orthonormalize_basis` and take the up.)

- [ ] **Step 4: `emitter_spec_to_calls`** (`ship_property_viewer.py:148-165`) — for a cone, after the shared calls, append RadiusY + Up **only when the cone is elliptical** (mirrors the Box `_is_identity_orientation` skip):
    ```python
    if kind == "cone":
        ry = float(spec.get("radius_y", spec["radius"]))
        if abs(ry - float(spec["radius"])) > 1e-9:
            calls.append(("SetLightEmitterRadiusY", (index, ry)))
            ux, uy, uz = spec.get("up") or (0.0, 0.0, 1.0)
            calls.append(("SetLightEmitterUp", (index, ux, uy, uz)))
    ```

- [ ] **Step 5: Producer up transform** (`host_loop.py:1010-1024`) — after the `direction` world-transform, add:
    ```python
    if "up" in d:
        d["up"] = _rotate_body(R, d["up"])
    ```
  Add a producer test (`test_host_loop_emitter_lights.py`): an elliptical cone on a rotated ship → the emitted dict's `direction` AND `up` are both `R·body` (rotation-only), `spot_tan_x`/`spot_tan_y` pass through.

- [ ] **Step 6: Run tests green, gate, commit.**

---

### Task 3: SPV — cone 3-field scale + oriented cone rotate

**Files:** `engine/ui/ship_property_viewer_panel.py`, `tests/ui/test_ship_property_viewer_panel_emitter.py`.

This mirrors the existing **Box light** orientation path (verbatim in `_apply_ring_drag_angle`/`_rotate_axis`/`_set_orientation_absolute`/`region`-copy) onto the **cone emitter**. Key idea: a cone emitter now carries a `(forward=axis, up)` orientation like a Box, but is still keyed by the `("emitter", i, j)` target and restaged whole-list.

**Interfaces:** cone scale kind `"radius_xy_length"` (3 fields: Radius X / Radius Y / Length); cone rotate clipboard kind `"cone_orientation"`.

- [ ] **Step 1: Write failing tests** — for a CONE emitter: (a) `_scale_kind_and_fields` returns `("radius_xy_length", [RadiusX, RadiusY, Length])`; (b) each of the 3 scale handles/fields writes the right one (`radius`, `radius_y`, `length`) via `_set_scale_field`, whole-list restaged, sibling untouched; (c) `_begin_scale_drag` maps the forward-aligned handle → Length, and the two perpendicular handles → RadiusX vs RadiusY distinctly (by alignment with the cone's `right` vs `up`); (d) cone rotate rotates BOTH `axis` and `up` and re-orthonormalizes (`_apply_ring_drag_angle` + `_rotate_axis`); (e) `rotate_copy`→`rotate_paste` round-trips the cone's `(axis, up)`; `rotate_mirror` negates X of both; (f) a strip emitter still rotates single-axis (unchanged); (g) point emitter scale still radius-only.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: `_scale_kind_and_fields`** (`:530-549`) cone arm — replace the strip/cone shared `"radius_length"` return with a cone-specific 3-field kind:
```python
        if kind == "point":
            return "radius", [{"label": "Radius", "value": float(spec["radius"])}]
        if kind == "cone":
            return "radius_xy_length", [
                {"label": "Radius X", "value": float(spec["radius"])},
                {"label": "Radius Y", "value": float(spec.get("radius_y", spec["radius"]))},
                {"label": "Length",   "value": float(spec["length"])}]
        # strip
        return "radius_length", [
            {"label": "Radius", "value": float(spec["radius"])},
            {"label": "Length", "value": float(spec["length"])}]
```

- [ ] **Step 4: `_set_scale_field`** (`:590-620`) emitter arm — field 0 → `radius`, field 1 → `radius_y` (for a cone) / `length` (for a strip), field 2 → `length` (cone). Branch on the emitter's kind:
```python
        if t[0] == "emitter":
            _, i, j = t
            lst = list(self._effective_emitters(i)); ...
            spec = dict(lst[j])
            if spec.get("kind") == "cone":
                spec[("radius", "radius_y", "length")[index]] = value
            else:  # strip / point
                spec["radius" if index == 0 else "length"] = value
            lst[j] = spec; self._pending_emitter[i] = lst; self._last_pushed = None
            return
```

- [ ] **Step 5: `_begin_scale_drag`** (`:939-970`) — for a cone (`radius_xy_length`), map the gizmo handle to a field by alignment with the cone's oriented frame: the handle aligned with `forward` (dominant component of `axis`) → field 2 (Length); of the remaining two, the one aligned with `right = cross(forward, up)` → field 0 (Radius X), the other (`up`) → field 1 (Radius Y). Compute `right`/`up` from `spec["axis"]` + `spec["up"]` (derive up if absent). Keep the existing `radius_length`/`xyz`/uniform branches.

- [ ] **Step 6: Oriented cone rotate.** Give the cone the Box path in the four rotate sites (mirror the verbatim Box branches):
  - `_rotate_clipboard_kind` (`:704-714`): `if target[0]=="emitter"`: return `"cone_orientation"` if the emitter is a cone else `"cylinder_axis"`.
  - `_apply_ring_drag_angle` (`:1019-1060`) emitter arm: if the emitter is a **cone**, rotate `spec["axis"]` (forward) AND `spec["up"]` via `rotate_about_axis`, then `spec["up"] = orthonormalize_basis(new_forward, new_up)[1]` and `spec["axis"] = new_forward` (store both); else (strip) single-axis as today. Restage whole-list; keep the accum bookkeeping.
  - `_rotate_axis` (`:716-758`) emitter arm: same cone (forward+up) vs strip (axis) split (this is the nudge sibling).
  - Add an emitter arm to `_set_orientation_absolute` (`:789-800`) that takes `("emitter", i, j)` and writes `spec["axis"]`(=forward) + `spec["up"]` via whole-list restage (mirror `_set_axis_absolute`'s emitter arm).
  - `rotate_copy`/`rotate_paste`/`rotate_mirror` (`:1999-2056`) cone arms: copy `("cone_orientation", (axis, up))`; paste via `_set_orientation_absolute(target, axis, up)`; mirror negates X of both axis and up then `_set_orientation_absolute`. (Kind-match already gates paste; `cone_orientation` only matches a cone emitter.)
  - `_begin_ring_drag` already grabs `_ring_grab_orientation` — for a cone, seed it from `(spec["axis"], spec["up"])` so the ring drag rotates from the grab-start orientation (add a cone case where it reads the emitter's axis+up into `_ring_grab_orientation`).

- [ ] **Step 7: Run tests green, gate, commit.**

---

### Task 4: Overlay — elliptical/rolled cone wireframe

**Files:** `engine/ui/glow_region_overlay.py`, `engine/renderer.py` (docstring only), `tests/unit/test_glow_region_overlay.py`.

- [ ] **Step 1: Write failing test** — `build_emitter_overlay` for a selected ELLIPTICAL cone returns a `cones` dict carrying `radius_y` and a world-space `up` (rotation-only transform of `spec["up"]`), plus `radius` (X) and `length`; a circular cone (no explicit up / `radius_y == radius`) still returns a valid cone dict (radius_y defaults to radius).

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: `build_emitter_overlay`** (`:110-147`) cone branch — add `radius_y` + world `up`:
```python
    else:  # cone
        upv = spec.get("up") or (0.0, 0.0, 1.0)
        cones.append({"apex": center, "axis": _world_dir(ship, spec["axis"]),
                      "radius": float(spec["radius"]),
                      "radius_y": float(spec.get("radius_y", spec["radius"])),
                      "up": _world_dir(ship, upv),
                      "length": float(spec["length"]), "color": color})
```
(`_world_dir` already normalizes + guards zero — reuse for `up`.)

- [ ] **Step 4:** Update `engine/renderer.py:set_debug_cones` docstring to list the new `radius_y`, `up` keys.

- [ ] **Step 5: Run test green, gate, commit.**

---

## Self-Review (author)

- **Spec coverage:** elliptical spot test + up (A); radius_y/up spec + setters + tangents + producer transform (B); 3-field cone scale + oriented cone rotate + copy/paste/mirror (C); wireframe (D). Byte-identity (A step 6/7), backward-compat legacy cone (B step 1c), whole-list dense invariant (C tests) all covered.
- **Type consistency:** the cone spec keys `radius`(X)/`radius_y`/`up` are used identically in B, C, D; the descriptor fields `spot_tan_x`/`spot_tan_y`/`up` and dict keys match between A (shader/binding) and B (`emitter_spec_to_struct`); scale-kind `"radius_xy_length"` field order (0=RadiusX,1=RadiusY,2=Length) matches between `_scale_kind_and_fields` and `_set_scale_field` (C).
- **Cross-task ordering note:** between Task 1 (renderer expects `spot_tan_*`/`up`) and Task 2 (producer sends them), an in-game emitter cone renders as non-cone (the binding defaults `spot_tan_x` to `-1`) — transient, no automated test asserts the producer→cone visual, so the gate stays green each task. Feature is end-to-end after B (given A). This is expected for sequential SDD; the branch isn't shippable mid-tasks.
- **No placeholders:** every step has concrete code or a precise mirror-instruction citing the verbatim current line range.
