# Oriented Box Glow Regions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a Box glow region a (forward, up) orientation so the Rotate tool can tilt it — persisted via a `SetGlowRegionOrientation` override setter, rendered tilted by the glow shader, previewed tilted in the SPV wireframe. Existing (unrotated) boxes render byte-identically.

**Architecture:** Orientation stored as a forward+up unit basis. Persistence + reading is pure Python (the property auto-records `SetGlowRegion*` via `__getattr__`; `read_indexed_setter_args` reads it back). The C++ side adds orientation to `GlowRegion` + the shader box inside-test (rotate the sample into box-local). Render scope is v1: wireframe-live, glow-on-reload.

**Tech Stack:** Python 3, GLSL (`opaque.frag`), C++/OpenGL, pytest.

## Global Constraints

- **Backward-compatible / production byte-identical.** A box with no orientation (all existing overrides) → default identity basis `forward=(0,1,0)`, `up=(0,0,1)` → shader `R = I` → identical render; `region_spec_to_calls` emits **no** `SetGlowRegionOrientation` for an identity box → zero override churn.
- **Orientation = forward+up unit basis** (right = normalize(forward × up)); re-orthonormalize after every rotate op.
- **v1 render scope:** the SPV wireframe tilts live; the in-scene glow tilts after Save + reload (the ship-glow-controller/baked path carries orientation). No live-glow push during editing.
- **Rotate is shape-aware:** Cylinder → axis (today), **Box → orientation**, Sphere → inert.
- **Persist via the existing light path:** box `orientation` rides `_pending_light[i]` → `region_spec_to_calls` → `set_region` → `hardpoint_overrides.py`. No writer schema change beyond the new indexed setter.
- **Shader change needs a cmake RECONFIGURE** (`cmake -B build -S .`) before `cmake --build`, because `.frag` files are embedded at configure time.
- **Shared checkout.** Explicit pathspecs only. Never `git add -A`/`checkout`/`restore`/`stash`/`reset --hard`/`clean`. Do NOT stage `engine/appc/hardpoint_overrides.py` (it holds Mark's live tunings).
- **Test gate.** `scripts/check_tests.sh` green vs `tests/known_failures.txt` (1 baselined).

## File Structure

- `engine/appc/subsystem_glow.py` — Task 1 (reader + `resolve_baked_region` box op).
- `engine/ui/ship_property_viewer.py` — Task 2 (`region_spec_to_calls` box), Task 3 (rotate helpers if any).
- `engine/appc/hardpoint_override_writer.py` — Task 2 (round-trip; likely no change).
- `engine/ui/ship_property_viewer_panel.py` — Task 3 (rotate box branch).
- `engine/ui/glow_region_overlay.py` — Task 4 (oriented box wireframe).
- `native/src/renderer/shaders/opaque.frag`, `glow_region.{cc,h}`, `frame.cc`, the glow-region push binding — Task 5.
- Tests under `tests/unit/`, `tests/ui/`, `tests/host/`.

---

### Task 1: Box orientation — reader + resolve op

**Files:**
- Modify: `engine/appc/subsystem_glow.py`
- Test: `tests/unit/test_subsystem_glow_box_orientation.py` (create)

**Interfaces:**
- Consumes: `read_indexed_setter_args`, the box branch of `baked_glow_regions` and `resolve_baked_region`.
- Produces: `baked_glow_regions` box entry gains `"orientation": (forward3, up3) | None`; `resolve_baked_region` box op becomes `("box", center, half_extents, forward, up)` (identity default when absent). A helper `_orientation_or_identity(raw) -> (forward, up)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_subsystem_glow_box_orientation.py
"""Box glow regions read + resolve an optional (forward, up) orientation."""
from engine.appc import subsystem_glow as sg


class _Prop:
    def __init__(self, data): self._data = data


def _box_prop(orientation=None):
    # Data-bag as read_indexed_setter_args expects: Set<F>(*args) -> key
    # (F, args[:-1]) = value args[-1].
    data = {
        ("GlowRegionShape", (0,)): "Box",
        ("GlowRegionPosition", (0, 0.0, 0.0)): 0.0,
        ("GlowRegionScale", (0, 0.2, 0.2)): 0.05,
    }
    if orientation is not None:
        (fx, fy, fz), (ux, uy, uz) = orientation
        data[("GlowRegionOrientation", (0, fx, fy, fz, ux, uy))] = uz
    return _Prop(data)


def test_box_without_orientation_reads_none():
    regions = sg.baked_glow_regions(_box_prop())
    assert regions[0]["shape"] == "Box"
    assert regions[0].get("orientation") is None


def test_box_with_orientation_reads_basis():
    ori = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))   # forward=+X, up=+Z
    regions = sg.baked_glow_regions(_box_prop(ori))
    assert regions[0]["orientation"] == ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))


def test_resolve_box_op_carries_identity_by_default():
    op = sg.resolve_baked_region(
        {"shape": "Box", "position": (0.0, 0.0, 0.0), "scale": (0.2, 0.2, 0.05)},
        (0.0, 0.0, 0.0))
    # ("box", center, half_extents, forward, up)
    assert op[0] == "box"
    assert op[3] == (0.0, 1.0, 0.0) and op[4] == (0.0, 0.0, 1.0)


def test_resolve_box_op_carries_orientation():
    op = sg.resolve_baked_region(
        {"shape": "Box", "position": (0.0, 0.0, 0.0), "scale": (0.2, 0.2, 0.05),
         "orientation": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))},
        (0.0, 0.0, 0.0))
    assert op[3] == (1.0, 0.0, 0.0) and op[4] == (0.0, 0.0, 1.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_subsystem_glow_box_orientation.py -v`
Expected: FAIL (`orientation` key absent / box op has no index 3).

- [ ] **Step 3: Implement**

- Add `_orientation_or_identity(raw)`: `raw` is the 6-tuple from `read_indexed_setter_args` (`(fx,fy,fz,ux,uy,uz)`) or None → return `((fx,fy,fz),(ux,uy,uz))` or `((0.0,1.0,0.0),(0.0,0.0,1.0))`.
- In `baked_glow_regions`, for a Box add `"orientation": _pair_or_none(read_indexed_setter_args(prop, "GlowRegionOrientation", i))` where `_pair_or_none` returns `((fx,fy,fz),(ux,uy,uz))` or `None`.
- In `resolve_baked_region`, the box branch returns `("box", center, half_extents, forward, up)` where `(forward, up) = _orientation_or_identity(raw.get("orientation"))` — read `raw["orientation"]` as an already-paired `((f),(u))` or None (from the spec), defaulting to identity.

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/unit/test_subsystem_glow_box_orientation.py tests/unit/test_subsystem_glow.py tests/unit/test_glow_region_overlay.py -v`
Expected: PASS (existing box/glow tests still green — the overlay test may need its box-op unpack widened; if so that's Task 4's consumer, but confirm the resolve change didn't break existing unpacks — if `test_glow_region_overlay` fails on the 5-tuple, note it for Task 4 and DO NOT fix here beyond making resolve return the 5-tuple).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_glow.py tests/unit/test_subsystem_glow_box_orientation.py
git commit -m "feat(glow): box glow regions read + resolve an optional (forward,up) orientation"
```

---

### Task 2: Region spec + override writer

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (`region_spec_to_calls`)
- Modify (only if the round-trip fails): `engine/appc/hardpoint_override_writer.py`
- Test: `tests/ui/test_region_spec_box_orientation.py` (create), `tests/unit/test_hardpoint_override_writer_orientation.py` (create)

**Interfaces:**
- Consumes: `region_spec_to_calls`, the writer's `read_models`/`emit`/`set_region`.
- Produces: box `region_spec_to_calls` appends `SetGlowRegionOrientation(index, fx,fy,fz, ux,uy,uz)` ONLY when the orientation is non-identity; `_is_identity_orientation(ori)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_region_spec_box_orientation.py
from engine.ui.ship_property_viewer import region_spec_to_calls


def _box(orientation=None):
    s = {"shape": "Box", "position": (0.0, 0.0, 0.0), "scale": (0.2, 0.2, 0.05)}
    if orientation is not None:
        s["orientation"] = orientation
    return s


def test_identity_box_emits_no_orientation_call():
    calls = region_spec_to_calls(0, _box())                      # no orientation
    assert not any(c[0] == "SetGlowRegionOrientation" for c in calls)
    calls2 = region_spec_to_calls(0, _box(((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))))  # identity
    assert not any(c[0] == "SetGlowRegionOrientation" for c in calls2)


def test_tilted_box_emits_orientation_call():
    ori = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    calls = region_spec_to_calls(0, _box(ori))
    assert ("SetGlowRegionOrientation", (0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)) in calls
```

```python
# tests/unit/test_hardpoint_override_writer_orientation.py
"""A box SetGlowRegionOrientation override round-trips through the writer."""
import types
from engine.appc import hardpoint_override_writer as w


def _module_with(source):
    m = types.ModuleType("hardpoint_overrides")
    exec(compile(source, "hardpoint_overrides", "exec"), m.__dict__)
    return m


SRC = (
    "def galaxy(find):\n"
    "    p = find('Port Impulse')\n"
    "    p.SetGlowRegionShape(0, 'Box')\n"
    "    p.SetGlowRegionPosition(0, -1.22, -0.2, 0.32)\n"
    "    p.SetGlowRegionScale(0, 0.15, 0.2, 0.05)\n"
    "    p.SetGlowRegionOrientation(0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)\n"
    "OVERRIDES = {'galaxy': galaxy}\n"
)


def test_orientation_is_canonical_fixed_point():
    models = w.read_models(_module_with(SRC))
    text = w.emit(models)
    assert w.emit(w.read_models(_module_with(text))) == text
    assert "SetGlowRegionOrientation(0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_region_spec_box_orientation.py tests/unit/test_hardpoint_override_writer_orientation.py -v`
Expected: `region_spec_to_calls` test FAILS (no orientation call emitted). The writer round-trip may already PASS (the writer handles arbitrary indexed setters) — if it fails, fix in Step 3.

- [ ] **Step 3: Implement**

- In `region_spec_to_calls`, box branch (after the `SetGlowRegionScale` append):
```python
ori = spec.get("orientation")
if ori is not None and not _is_identity_orientation(ori):
    (fx, fy, fz), (ux, uy, uz) = ori
    calls.append(("SetGlowRegionOrientation", (index, fx, fy, fz, ux, uy, uz)))
```
- Add module helper:
```python
def _is_identity_orientation(ori, eps=1e-6):
    (fx, fy, fz), (ux, uy, uz) = ori
    return (abs(fx) < eps and abs(fy - 1.0) < eps and abs(fz) < eps and
            abs(ux) < eps and abs(uy) < eps and abs(uz - 1.0) < eps)
```
- If the writer round-trip test failed: the writer's `read_models`/`emit` handle any `Set<F>` indexed setter generically — a 7-arg `SetGlowRegionOrientation` should already round-trip. Only if it doesn't, make the minimal fix (mirror how `SetGlowRegionScale` is handled). Do not refactor.

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_region_spec_box_orientation.py tests/unit/test_hardpoint_override_writer_orientation.py tests/unit/test_hardpoint_override_writer.py tests/ui/test_glow_region_overlay.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py tests/ui/test_region_spec_box_orientation.py tests/unit/test_hardpoint_override_writer_orientation.py
# add engine/appc/hardpoint_override_writer.py ONLY if you changed it
git commit -m "feat(glow): persist box glow orientation via SetGlowRegionOrientation"
```

---

### Task 3: Rotate tool — box orientation editing

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (a `orthonormalize`/basis helper) + `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel_rotate.py` (extend)

**Interfaces:**
- Consumes: `_rotate_target`, `_rotate_axis`/`_apply_ring_drag_angle`, `rotate_copy`/`paste`/`mirror`, `_effective_light`, `rotate_about_axis`, `_light_region_spec`/`_light_annotation` (so a box light carries a default `orientation`).
- Produces: `_rotate_target()` accepts a Box light; box rotation edits `_pending_light[i]["orientation"]` (forward+up rotated + re-orthonormalized); box Mirror reflects X; Copy/Paste kind = `box_orientation`. A helper `orthonormalize_basis(forward, up)` in ship_property_viewer.py.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/ui/test_ship_property_viewer_panel_rotate.py
def _panel_box_light():
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Port Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": "Box", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.2, 0.2, 0.05),
                         "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))},
    }]
    p.dispatch_event("set_tool:rotate")
    p._selected_light_index = 0
    return p


def test_rotate_target_accepts_box_light():
    p = _panel_box_light()
    assert p._rotate_target() == ("light", 0)
    assert p.rotate_values() is not None


def test_box_rotate_nudge_rotates_orientation():
    p = _panel_box_light()
    # Rotate 90 deg about +Z: forward +Y -> -X, up +Z unchanged.
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 90.0}))
    fwd, up = p._effective_light(0)["orientation"]
    assert fwd == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)
    assert up == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)


def test_box_rotate_mirror_reflects_forward_x():
    p = _panel_box_light()
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 30.0}))
    p.dispatch_event("rotate_mirror")
    fwd, up = p._effective_light(0)["orientation"]
    # forward X flipped; basis stays unit + right-handed (up still ~unit).
    assert abs((fwd[0]**2 + fwd[1]**2 + fwd[2]**2) - 1.0) < 1e-6
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_rotate.py -k "box" -v`
Expected: FAIL (`_rotate_target()` None for a box; no `orientation` edit).

- [ ] **Step 3: Implement**

- Add `orthonormalize_basis(forward, up)` in `ship_property_viewer.py`: normalize forward; `up = normalize(up − (up·f)·f)`; return `(forward, up)` (right derived by consumers as f×u).
- `_light_region_spec`/`_light_annotation`: ensure a Box light's spec carries `"orientation"` (default identity `((0,1,0),(0,0,1))` when the baked region has none) so the descriptor + effective spec always have it.
- `_rotate_target()`: return `("light", i)` when the effective light shape is `"Cylinder"` OR `"Box"` (Sphere still None).
- Rotation application — make it shape-aware:
  - Cylinder → rotate `axis` (unchanged).
  - Box → rotate BOTH forward and up about body axis `k` via `rotate_about_axis`, then `orthonormalize_basis`, store `_pending_light[i]["orientation"] = (forward, up)`. Apply in both `_rotate_axis` (nudge) and `_apply_ring_drag_angle` (drag) — branch on the effective shape.
- `rotate_copy`: store `("cylinder_axis", axis)` for a cylinder, `("box_orientation", (forward, up))` for a box. `rotate_paste`: kind-matched (`can_paste` when clipboard kind matches the current target's kind). `rotate_mirror`: cylinder → negate axis X (today); box → negate the X component of forward AND up, then `orthonormalize_basis` (preserve right-handedness by re-deriving right = f×u), store; zero `_rotate_accum[i]`.
- `rotate_values` `can_paste` becomes kind-aware: true only when the clipboard kind matches the selected target's kind (cylinder vs box).

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_rotate.py tests/ui/test_ship_property_viewer_panel_scale.py tests/ui/test_ship_property_viewer_panel_gizmo.py tests/ui/test_ship_property_viewer_panel.py -v`
Expected: PASS (cylinder rotate + move/scale unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_rotate.py
git commit -m "feat(spv): Rotate edits box glow orientation (forward+up basis)"
```

---

### Task 4: Oriented box wireframe

**Files:**
- Modify: `engine/ui/glow_region_overlay.py`
- Test: `tests/unit/test_glow_region_overlay.py` (extend)

**Interfaces:**
- Consumes: the box op `("box", center, half_extents, forward, up)` from Task 1; `_box(center, ex, ey, ez)`; `_rotate_vec`.
- Produces: the box branch computes edge vectors from the orientation basis: `ex = shipR·(R·(hx,0,0))`, `ey = shipR·(R·(0,hy,0))`, `ez = shipR·(R·(0,0,hz))`, where `R = [right | forward | up]`, `right = normalize(forward × up)`. Identity basis ⇒ current body-aligned edges.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_glow_region_overlay.py
def test_box_wireframe_tilts_with_orientation(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    # forward=+X, up=+Z -> box local Y axis points along world +X.
    monkeypatch.setattr(gro, "baked_region_ops",
        lambda prop, pos, name: [("box", (0.0, 0.0, 0.0), (1.0, 2.0, 3.0),
                                   (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))])
    ship = _BoxShip([_BoxSub("Box Pod", object())])
    _c, boxes = gro.build_glow_region_overlay(ship, show_all=True)
    b = boxes[0]
    # ey carries the hy=2 extent along the forward axis (+X here), not body +Y.
    assert b["ey"] == pytest.approx((2.0, 0.0, 0.0), abs=1e-6)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_glow_region_overlay.py -k "tilt or box" -v`
Expected: FAIL (current code unpacks a 3-field box op and draws body-aligned).

- [ ] **Step 3: Implement**

Update the box branch: unpack `_kind, center, half, forward, up = op`; build `right = _rotate_dir(cross(forward, up))`-style unit vectors and the three edge vectors as above (rotate the half-extent along each box-local axis, then by ship R). Add a small `_basis_from(forward, up)` returning `(right, forward, up)` normalized. Keep the identity path producing the existing body-aligned vectors.

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/unit/test_glow_region_overlay.py -v`
Expected: PASS (existing identity-box test still green).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/glow_region_overlay.py tests/unit/test_glow_region_overlay.py
git commit -m "feat(spv): oriented box glow wireframe"
```

---

### Task 5: Shader + native render (glow-on-reload)

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Modify: `native/src/renderer/glow_region.{cc,h}` (the `GlowRegion` struct + `add_box_region`)
- Modify: `native/src/renderer/frame.cc` (upload the new uniforms)
- Modify: the Python→native glow-region push that feeds box regions (find via the `("box", ...)` op consumer / `add_box_region` binding) so it forwards `forward`/`up`
- Test: `tests/host/test_box_glow_region.py` (extend) or a new host test

**Interfaces:**
- Consumes: `u_glow_region_a..e`, `glow_region_mult`, the box op with orientation (Task 1), the glow push path.
- Produces: `u_glow_region_f`/`u_glow_region_g` (forward/up); the box inside-test rotates the sample into box-local; `GlowRegion.forward/up`; `add_box_region(center, half, forward, up)`; `frame.cc` uploads f/g; the push forwards orientation. Identity basis ⇒ byte-identical.

- [ ] **Step 1: Extend the host test**

Add a test that `add_box_region` accepts forward/up (default identity), and that a box region with identity orientation produces the same in-region result as before (reuse the existing `tests/host/test_box_glow_region.py` harness; assert an identity-oriented box still lights a point inside it — production byte-identical).

- [ ] **Step 2: Build + run to verify current state**

Run: `cmake -B build -S . && cmake --build build -j && uv run pytest tests/host/test_box_glow_region.py -v`
Expected: existing tests PASS; the new orientation-accepting test FAILS until Step 3.

- [ ] **Step 3: Implement**

- `glow_region.h`: `GlowRegion` gains `glm::vec3 forward{0.0f, 1.0f, 0.0f}; glm::vec3 up{0.0f, 0.0f, 1.0f};`.
- `glow_region.cc`: `add_box_region(center, half_extents, forward = {0,1,0}, up = {0,0,1})` sets them; existing 2-arg callers default to identity.
- `frame.cc`: upload `forward`→`u_glow_region_f[i]`, `up`→`u_glow_region_g[i]` for every region (cylinder/sphere carry the identity default, unused by their branches). Add the two `glUniform4fv` (or the existing packed-upload idiom) beside the `u_glow_region_e` upload.
- `opaque.frag`: add `uniform vec4 u_glow_region_f[MAX_GLOW_REGIONS];` and `u_glow_region_g[]`. In the box branch, before `abs(d)`:
  ```glsl
  vec3 fwd = u_glow_region_f[i].xyz;
  vec3 upv = u_glow_region_g[i].xyz;
  vec3 rgt = normalize(cross(fwd, upv));
  mat3 R = mat3(rgt, fwd, upv);       // columns = box-local axes in body space
  d = transpose(R) * d;               // body -> box-local
  ```
  Guard the degenerate case (`length(fwd) < 0.5` ⇒ leave `d` as-is) so an unset region can't NaN. For the identity basis this yields `R = I` ⇒ `d` unchanged ⇒ byte-identical.
  Confirm `MAX_GLOW_REGIONS × 7 vec4` fits the uniform budget (glow regions are few); if not, fall back to a single quaternion uniform.
- The Python→native push (the box-op consumer, e.g. `subsystem_glow._register_baked` / the renderer glow-region call): forward the box op's `forward`/`up` into `add_box_region`.

- [ ] **Step 4: Build + run test + gate**

Run: `cmake -B build -S . && cmake --build build -j && uv run pytest tests/host/test_box_glow_region.py -v && ctest --test-dir build --output-on-failure | tail -5`
Expected: PASS; the scorch/heat-glow baselined `FrameTest`s remain the only ctest failures (per `tests/known_failures.txt`); an identity box renders unchanged.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/src/renderer/glow_region.cc native/src/renderer/glow_region.h native/src/renderer/frame.cc engine/appc/subsystem_glow.py tests/host/test_box_glow_region.py
# add the specific push-path file you edited
git commit -m "feat(glow): shader + GlowRegion draw box glow tilted by (forward,up)"
```

---

## Self-Review

**Spec coverage:** orientation read/resolve (Task 1), persist + writer (Task 2), Rotate box editing (Task 3), live wireframe (Task 4), shader + reload-time glow render (Task 5). Backward-compat (identity ⇒ no emit, R=I ⇒ byte-identical) enforced in Tasks 2 + 5.

**Placeholder scan:** real code for the Python tasks; the shader/native task points at concrete existing structures (`u_glow_region_e` upload, `add_box_region`, the box branch) with the exact GLSL to add.

**Type consistency:** box op `("box", center, half_extents, forward, up)` defined in Task 1, consumed by Task 4 (wireframe) and Task 5 (push); the spec `orientation` field is `((fx,fy,fz),(ux,uy,uz))` everywhere (`region_spec_to_calls`, `resolve_baked_region`, `_effective_light`, the rotate model); `SetGlowRegionOrientation(index, fx,fy,fz,ux,uy,uz)` arg order matches emit (Task 2), read-back (Task 1), and the identity guard.
