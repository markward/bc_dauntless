# Transient Impact Feedback (Sparks + Emissive Flicker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two transient, one-shot-per-impact hit-feedback effects — weapon-distinct hull sparks on heavy hits, and a 500ms electrical-stutter flicker of the ship's own glow map on torpedo/disruptor hull hits.

**Architecture:** Two independent paths. **Sparks** extend the existing `hit_vfx` transient-descriptor path and `HitVfxPass`: Python decides whether/how many sparks fire and converts the impact to the ship's body frame (once, at spawn); the renderer resolves a hull-anchored emit origin each frame and flies detached billboard sparks. **Flicker** is a single new term inside `opaque.frag`'s existing damage-decal loop, keyed off the SCORCH decal record's `birth_time`/`weapon_class`/`radius` — no new record, no change to the decal data layout.

**Tech Stack:** Python (`engine/appc/`), C++/pybind11 host bindings (`native/src/host/`), C++ renderer (`native/src/renderer/`), GLSL (`opaque.frag`), pytest + GoogleTest (offscreen llvmpipe).

**Spec:** [`docs/superpowers/specs/2026-06-09-impact-feedback-design.md`](../specs/2026-06-09-impact-feedback-design.md).

**Critical project facts (read before starting):**
- Shader source changes need a **`cmake` reconfigure** (`cmake -B build -S .`), not just `cmake --build` — shaders are embedded at configure time. Every `opaque.frag` iteration in Part B needs this.
- The extension module is **`_dauntless_host`**; the host binary is **`build/dauntless`**. One build tree at `<root>/build/`. Never build from inside `native/`.
- **Do not run the full pytest suite** — it OOMs the machine. Always run focused subsets (exact commands given per task).
- Rotation/units: `inst.world` (renderer instance world matrix) maps **NIF/model units → world game-units** and bakes the uniform `BC_MODEL_SCALE`. `scenegraph::world_to_body(inst.world, p)` returns a **model-unit** body point; `world_dir_to_body` returns a body-frame direction. The renderer resolves back with `inst.world * vec4(body_point, 1)`.
- `WeaponClass` enum (`scenegraph/damage_decals.h`): `HeatGlow = 0` (phaser), `Scorch = 1` (torpedo/disruptor). Python mirrors: `damage_decals.WEAPON_CLASS_HEAT_GLOW = 0`, `WEAPON_CLASS_SCORCH = 1`.

---

## File Structure

**Sparks (Part A):**
- `engine/appc/hit_feedback.py` *(modify)* — spark trigger + count policy; convert impact to body frame via the new binding; pass new fields into `hit_vfx.spawn`.
- `engine/appc/hit_vfx.py` *(modify)* — `spawn(...)` carries `instance_id, body_point, body_normal, weapon_kind, spark_count`.
- `engine/host_loop.py` *(modify)* — `_build_hit_vfx_render_data` forwards the new descriptor fields.
- `native/src/host/host_bindings.cc` *(modify)* — new `world_to_body` binding; extend `set_hit_vfx` ingest; pass `g_world` into the hit-vfx render call.
- `native/src/renderer/include/renderer/frame.h` *(modify)* — extend `HitVfxDescriptor`.
- `native/src/renderer/include/renderer/hit_vfx_pass.h` *(modify)* — `render(...)` gains a `const scenegraph::World&` param.
- `native/src/renderer/hit_vfx_pass.cc` *(modify)* — generalise the CRITICAL-only burst to per-descriptor `spark_count`, weapon-distinct tint/cone, hull-anchored origin, damping; switch spark sprite to `data/rough.tga`.
- Tests: `tests/unit/test_spark_policy.py` *(create)*, `tests/unit/test_hit_vfx_lifecycle.py` *(extend)*, `tests/integration/test_world_to_body_binding.py` *(create)*, `native/tests/renderer/hit_vfx_pass_test.cc` *(create)* + CMake registration.

**Flicker (Part B):**
- `native/src/renderer/shaders/opaque.frag` *(modify)* — flicker constants, `stutter()` helper, glow-modulation term inside `apply_damage_decals`, applied to the glow contribution in `main()`.
- Tests: `native/tests/renderer/frame_test.cc` *(extend)*.

---

# Part A — Sparks

## Task A1: Spark trigger + count policy (pure Python)

**Files:**
- Modify: `engine/appc/hit_feedback.py`
- Test: `tests/unit/test_spark_policy.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_spark_policy.py
"""Spark trigger + count policy — pure, no renderer."""
import pytest
from engine.appc.hit_feedback import (
    Severity, spark_params,
    SPARK_HULL_THRESHOLD, SPARK_KIND_PHASER, SPARK_KIND_TORPEDO,
)


def test_no_spark_below_threshold_non_critical():
    count, kind = spark_params(
        weapon_type="phaser", severity=Severity.HULL,
        absorbed_hull=SPARK_HULL_THRESHOLD - 1.0)
    assert count == 0


def test_spark_at_or_above_threshold():
    count, kind = spark_params(
        weapon_type="torpedo", severity=Severity.HULL,
        absorbed_hull=SPARK_HULL_THRESHOLD)
    assert count > 0
    assert kind == SPARK_KIND_TORPEDO


def test_critical_always_sparks_even_below_threshold():
    count, kind = spark_params(
        weapon_type="phaser", severity=Severity.CRITICAL,
        absorbed_hull=0.0)
    assert count > 0
    assert kind == SPARK_KIND_PHASER


def test_critical_count_exceeds_plain_hull_count():
    hull_count, _ = spark_params(
        weapon_type="torpedo", severity=Severity.HULL,
        absorbed_hull=SPARK_HULL_THRESHOLD * 4)
    crit_count, _ = spark_params(
        weapon_type="torpedo", severity=Severity.CRITICAL,
        absorbed_hull=SPARK_HULL_THRESHOLD * 4)
    assert crit_count > hull_count


def test_phaser_kind_for_phaser_weapon():
    _, kind = spark_params(
        weapon_type="phaser", severity=Severity.CRITICAL, absorbed_hull=0.0)
    assert kind == SPARK_KIND_PHASER


def test_torpedo_kind_for_unknown_weapon_defaults_torpedo():
    _, kind = spark_params(
        weapon_type=None, severity=Severity.CRITICAL, absorbed_hull=0.0)
    assert kind == SPARK_KIND_TORPEDO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_spark_policy.py -q`
Expected: FAIL — `ImportError: cannot import name 'spark_params'`.

- [ ] **Step 3: Add the policy to `hit_feedback.py`**

Add near the top of `engine/appc/hit_feedback.py`, after the `Severity` class:

```python
# ── Spark-burst policy (transient impact VFX) ──────────────────────────────
# Sparks fire on a *heavy direct hit* (absorbed_hull magnitude) OR on any
# CRITICAL subsystem transition. Magnitude-based so a single torpedo clears
# the bar while per-tick phaser dribble does not. Policy lives here; the
# renderer only renders the count it is told.
SPARK_HULL_THRESHOLD = 80.0   # game-units of hull damage in one hit (tune-by-eye)

SPARK_KIND_PHASER = 0    # cool white-blue, fewer, tight cone
SPARK_KIND_TORPEDO = 1   # hot orange, more, wide cone (also disruptor/default)

_SPARK_BASE_COUNT = {SPARK_KIND_PHASER: 6, SPARK_KIND_TORPEDO: 12}
_SPARK_CRITICAL_MULT = 1.5


def _spark_kind_for(weapon_type) -> int:
    return SPARK_KIND_PHASER if weapon_type == "phaser" else SPARK_KIND_TORPEDO


def spark_params(*, weapon_type, severity, absorbed_hull):
    """Return (spark_count, spark_kind). count == 0 means no burst.

    Pure function, tested in isolation. `severity` is a Severity.
    """
    kind = _spark_kind_for(weapon_type)
    fire = (absorbed_hull >= SPARK_HULL_THRESHOLD) or (severity == Severity.CRITICAL)
    if not fire:
        return 0, kind
    count = _SPARK_BASE_COUNT[kind]
    if severity == Severity.CRITICAL:
        count = int(count * _SPARK_CRITICAL_MULT)
    return count, kind
```

Note the test calls `spark_params` positionally in places; change the test calls to keyword OR make params keyword-only consistently. The implementation above is keyword-only (`*`), so update the test calls to use keywords (they already do). Leave as keyword-only.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_spark_policy.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hit_feedback.py tests/unit/test_spark_policy.py
git commit -m "feat(sparks): heavy-hit/CRITICAL spark trigger + count policy"
```

---

## Task A2: Extend `hit_vfx.spawn` to carry spark anchor + kind

**Files:**
- Modify: `engine/appc/hit_vfx.py`
- Test: `tests/unit/test_hit_vfx_lifecycle.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_hit_vfx_lifecycle.py`:

```python
def test_spawn_records_spark_anchor_and_kind():
    hit_vfx._active.clear()
    pos = TGPoint3(1.0, 2.0, 3.0)
    nrm = TGPoint3(0.0, 0.0, 1.0)
    spawn(pos, normal=nrm, severity=Severity.HULL,
          instance_id=7, body_point=(0.5, -0.5, 0.25),
          body_normal=(0.0, 0.0, 1.0), weapon_kind=1, spark_count=12)
    e = snapshot()[0]
    assert e["instance_id"] == 7
    assert e["body_point"] == (0.5, -0.5, 0.25)
    assert e["body_normal"] == (0.0, 0.0, 1.0)
    assert e["weapon_kind"] == 1
    assert e["spark_count"] == 12


def test_spawn_defaults_have_no_sparks():
    hit_vfx._active.clear()
    spawn(TGPoint3(0, 0, 0))
    e = snapshot()[0]
    assert e["spark_count"] == 0
    assert e["instance_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_hit_vfx_lifecycle.py -q`
Expected: FAIL — `TypeError: spawn() got an unexpected keyword argument 'instance_id'`.

- [ ] **Step 3: Extend `spawn` in `engine/appc/hit_vfx.py`**

Replace the existing `spawn` with:

```python
def spawn(position: TGPoint3, normal=None, severity=Severity.HULL,
          *, instance_id=None, body_point=None, body_normal=None,
          weapon_kind=1, spark_count=0) -> None:
    """Register a new hit VFX at `position` (world space).

    `normal` is a unit TGPoint3 surface normal or None (mesh trace missed).
    `severity` is Severity.SHIELD / HULL / CRITICAL. SHIELD is a no-op —
    the shield_hit renderer pass handles its own splash.

    Spark fields (all optional; spark_count == 0 disables the burst):
      instance_id  — receiving ship's renderer instance id (hull anchor)
      body_point   — impact point in ship body frame (model units, 3-tuple)
      body_normal  — surface normal in ship body frame (3-tuple)
      weapon_kind  — SPARK_KIND_PHASER (0) / SPARK_KIND_TORPEDO (1) tint+cone
      spark_count  — number of sparks to emit
    """
    if severity == Severity.SHIELD:
        return
    _active.append({
        "position":    position,
        "normal":      normal,
        "severity":    int(severity),
        "age":         0.0,
        "instance_id": instance_id,
        "body_point":  body_point,
        "body_normal": body_normal,
        "weapon_kind": int(weapon_kind),
        "spark_count": int(spark_count),
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_hit_vfx_lifecycle.py -q`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hit_vfx.py tests/unit/test_hit_vfx_lifecycle.py
git commit -m "feat(sparks): hit_vfx.spawn carries hull-anchor + weapon kind + spark count"
```

---

## Task A3: `world_to_body` host binding

**Files:**
- Modify: `native/src/host/host_bindings.cc` (add binding near `damage_decal_add`, ~line 1034)
- Test: `tests/integration/test_world_to_body_binding.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_world_to_body_binding.py
"""world_to_body host binding — world hit point -> ship body frame.

Skips when the native module or BC assets are unavailable (matches the
renderer test suite's asset gating).
"""
import math
import pytest

_host = pytest.importorskip("_dauntless_host")


def _load_galaxy_instance():
    """Return (instance_id) for a loaded Galaxy, or skip if unavailable."""
    if not hasattr(_host, "load_model") or not hasattr(_host, "create_instance"):
        pytest.skip("host lacks model-load bindings")
    try:
        handle = _host.load_model("data/models/Galaxy.NIF")
    except Exception:
        pytest.skip("Galaxy NIF not available")
    return _host.create_instance(handle)


def test_world_to_body_round_trips_under_translation():
    iid = _load_galaxy_instance()
    # Identity rotation, translate ship to (100, 0, 0) in world (game units).
    # Column-major 4x4 as a flat 16-list (matches set_world_transform).
    world = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  100, 0, 0, 1]
    _host.set_world_transform(iid, world)

    body_pt, body_nrm = _host.world_to_body(
        instance_id=iid, world_point=(110.0, 0.0, 0.0),
        world_normal=(1.0, 0.0, 0.0))
    # With identity rotation and unit scale, body point = world - translation.
    assert body_pt[0] == pytest.approx(10.0, abs=1e-4)
    assert body_pt[1] == pytest.approx(0.0, abs=1e-4)
    # Direction is translation-invariant and length-normalised.
    n = math.sqrt(sum(c * c for c in body_nrm))
    assert n == pytest.approx(1.0, abs=1e-4)


def test_world_to_body_stale_id_returns_none():
    assert _host.world_to_body(
        instance_id=999999, world_point=(0.0, 0.0, 0.0),
        world_normal=(1.0, 0.0, 0.0)) is None
```

- [ ] **Step 2: Build and run test to verify it fails**

Run:
```bash
cmake --build build -j && uv run pytest tests/integration/test_world_to_body_binding.py -q
```
Expected: FAIL — `AttributeError: module '_dauntless_host' has no attribute 'world_to_body'` (or the importorskip/asset-skip fires; if it skips, temporarily assert the attribute exists to confirm the binding is missing, then proceed).

- [ ] **Step 3: Add the binding**

In `native/src/host/host_bindings.cc`, immediately after the `damage_decal_add` binding block (after its closing `;` near line 1064), add:

```cpp
    m.def("world_to_body",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal)
              -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();  // stale id
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              const glm::vec3 pb = scenegraph::world_to_body(inst->world, pw);
              glm::vec3 nb = scenegraph::world_dir_to_body(inst->world, nw);
              const float len = glm::length(nb);
              if (len > 1e-6f) nb /= len;
              return py::make_tuple(
                  py::make_tuple(pb.x, pb.y, pb.z),
                  py::make_tuple(nb.x, nb.y, nb.z));
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          "Convert a world-space hit point + normal into the ship instance's "
          "body frame (model units). Returns ((bx,by,bz),(nx,ny,nz)) or None "
          "if the instance id is stale.");
```

(`scenegraph::world_to_body` / `world_dir_to_body` are already included via the `damage_decal_add` usage; no new include needed.)

- [ ] **Step 4: Rebuild and run test to verify it passes**

Run:
```bash
cmake --build build -j && uv run pytest tests/integration/test_world_to_body_binding.py -q
```
Expected: PASS (or asset-skip on a machine without the Galaxy NIF — that is an acceptable skip, not a failure; the stale-id test runs regardless).

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc tests/integration/test_world_to_body_binding.py
git commit -m "feat(sparks): world_to_body host binding (world hit -> body frame)"
```

---

## Task A4: Extend `HitVfxDescriptor` + `set_hit_vfx` ingest + render-data builder

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h` (`HitVfxDescriptor`, ~line 94)
- Modify: `native/src/host/host_bindings.cc` (`set_hit_vfx`, ~line 741)
- Modify: `engine/host_loop.py` (`_build_hit_vfx_render_data`, ~line 407)

- [ ] **Step 1: Extend the descriptor struct**

In `native/src/renderer/include/renderer/frame.h`, replace `HitVfxDescriptor` with:

```cpp
struct HitVfxDescriptor {
    glm::vec3 world_pos;
    glm::vec3 surface_normal{0.0f};   // (0,0,0) sentinel = no normal
    float     age      = 0.0f;
    int       severity = 1;           // 1=HULL, 2=CRITICAL; SHIELD never reaches here
    // Spark burst (hull-anchored, detached). spark_count == 0 => no sparks.
    int       instance_id = -1;       // receiving ship's renderer instance id
    glm::vec3 body_point{0.0f};       // impact in ship body frame (model units)
    glm::vec3 body_normal{0.0f};      // surface normal, body frame
    int       weapon_kind = 1;        // 0=phaser (cool/tight), 1=torpedo (hot/wide)
    int       spark_count = 0;
};
```

- [ ] **Step 2: Extend `set_hit_vfx` ingest**

In `native/src/host/host_bindings.cc`, inside the `set_hit_vfx` lambda loop (after `v.age = d["age"].cast<float>();`), add:

```cpp
                  v.instance_id = d.contains("instance_id") && !d["instance_id"].is_none()
                                  ? d["instance_id"].cast<int>() : -1;
                  v.weapon_kind = d.contains("weapon_kind") ? d["weapon_kind"].cast<int>() : 1;
                  v.spark_count = d.contains("spark_count") ? d["spark_count"].cast<int>() : 0;
                  if (d.contains("body_point") && !d["body_point"].is_none()) {
                      auto bp = d["body_point"].cast<std::tuple<float, float, float>>();
                      v.body_point = {std::get<0>(bp), std::get<1>(bp), std::get<2>(bp)};
                  }
                  if (d.contains("body_normal") && !d["body_normal"].is_none()) {
                      auto bn = d["body_normal"].cast<std::tuple<float, float, float>>();
                      v.body_normal = {std::get<0>(bn), std::get<1>(bn), std::get<2>(bn)};
                  }
```

- [ ] **Step 3: Extend the Python render-data builder**

In `engine/host_loop.py`, replace the body of `_build_hit_vfx_render_data`'s `out.append({...})` with:

```python
        out.append({
            "position":    (pos.x, pos.y, pos.z),
            "normal":      (n.x, n.y, n.z) if n is not None else (0.0, 0.0, 0.0),
            "severity":    entry["severity"],
            "age":         entry["age"],
            "instance_id": entry.get("instance_id"),
            "body_point":  entry.get("body_point"),
            "body_normal": entry.get("body_normal"),
            "weapon_kind": entry.get("weapon_kind", 1),
            "spark_count": entry.get("spark_count", 0),
        })
```

- [ ] **Step 4: Build to verify it compiles**

Run: `cmake --build build -j`
Expected: builds cleanly (no test yet — struct + ingest are exercised by Task A6's render test and the existing hit-vfx path; the dict keys are optional so the existing pipeline still works).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/host/host_bindings.cc engine/host_loop.py
git commit -m "feat(sparks): thread hull-anchor + kind + count through descriptor/binding/builder"
```

---

## Task A5: Wire spark spawn into the dispatch path

**Files:**
- Modify: `engine/appc/hit_feedback.py` (`dispatch`, the `else` visual branch ~line 138)
- Test: `tests/unit/test_hit_feedback_dispatch.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_hit_feedback_dispatch.py` (reuse that file's existing fakes for `ship`/`host`; the snippet below assumes a `make_ship()` / fake-host pattern — match the file's existing helpers):

```python
def test_heavy_hull_hit_spawns_sparks_with_body_anchor(monkeypatch):
    from engine.appc import hit_feedback, hit_vfx
    from engine.appc.hit_feedback import SPARK_HULL_THRESHOLD
    hit_vfx._active.clear()

    # Fake host that converts world->body deterministically.
    class FakeHost:
        def world_to_body(self, *, instance_id, world_point, world_normal):
            return ((1.0, 2.0, 3.0), (0.0, 0.0, 1.0))
    ship = _make_ship()                      # existing helper in this test file
    ship_instances = {ship: 5}

    hit_feedback.dispatch(
        ship=ship, source=None, point=_pt(10, 0, 0), normal=_pt(0, 0, 1),
        damage=200.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=SPARK_HULL_THRESHOLD + 50.0, sub_transition=None,
        host=FakeHost(), ship_instances=ship_instances,
        weapon_type="torpedo", radius=5.0)

    e = hit_vfx.snapshot()[0]
    assert e["spark_count"] > 0
    assert e["instance_id"] == 5
    assert e["body_point"] == (1.0, 2.0, 3.0)
    assert e["weapon_kind"] == hit_feedback.SPARK_KIND_TORPEDO


def test_light_hull_hit_spawns_no_sparks(monkeypatch):
    from engine.appc import hit_feedback, hit_vfx
    from engine.appc.hit_feedback import SPARK_HULL_THRESHOLD
    hit_vfx._active.clear()
    ship = _make_ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=_pt(0, 0, 0), normal=_pt(0, 0, 1),
        damage=5.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=SPARK_HULL_THRESHOLD - 1.0, sub_transition=None,
        host=None, ship_instances=None, weapon_type="phaser", radius=2.0)
    e = hit_vfx.snapshot()[0]
    assert e["spark_count"] == 0
```

(Adjust `_make_ship` / `_pt` to the helpers already defined in `test_hit_feedback_dispatch.py`. If the file builds ships differently, follow its established fixture.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_hit_feedback_dispatch.py -q -k spark`
Expected: FAIL — sparks not yet wired (`spark_count` is 0 / key missing).

- [ ] **Step 3: Wire the spawn call**

In `engine/appc/hit_feedback.py`, replace the `else:` visual branch (currently `hit_vfx.spawn(point, normal=normal, severity=severity)`) with:

```python
    else:
        # HULL or CRITICAL — hit_vfx.spawn handles both, filtered by severity.
        # Spark policy + hull anchor (sparks are independent of decals).
        spark_count, weapon_kind = spark_params(
            weapon_type=weapon_type, severity=severity,
            absorbed_hull=absorbed_hull)
        body_point = body_normal = None
        instance_id = None
        if (spark_count > 0 and host is not None and ship_instances is not None
                and normal is not None and hasattr(host, "world_to_body")):
            instance_id = ship_instances.get(ship)
            if instance_id is not None:
                conv = host.world_to_body(
                    instance_id=instance_id,
                    world_point=(point.x, point.y, point.z),
                    world_normal=(normal.x, normal.y, normal.z))
                if conv is not None:
                    body_point, body_normal = conv
                else:
                    instance_id = None  # stale id; render flash only, no sparks
        hit_vfx.spawn(
            point, normal=normal, severity=severity,
            instance_id=instance_id, body_point=body_point,
            body_normal=body_normal, weapon_kind=weapon_kind,
            spark_count=(spark_count if body_point is not None else 0))
```

Note: `spark_count` is forced to 0 when there is no body anchor (headless/stale), so the renderer never tries to anchor a burst it cannot place; the main impact-flash billboard still renders from `world_pos`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_hit_feedback_dispatch.py -q -k spark`
Expected: PASS. Then run the whole dispatch file to check no regression: `uv run pytest tests/unit/test_hit_feedback_dispatch.py -q`.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hit_feedback.py tests/unit/test_hit_feedback_dispatch.py
git commit -m "feat(sparks): spawn hull-anchored spark burst from dispatch on heavy/CRITICAL hits"
```

---

## Task A6: Render the hull-anchored, weapon-distinct spark burst

**Files:**
- Modify: `native/src/renderer/include/renderer/hit_vfx_pass.h` (`render` signature)
- Modify: `native/src/renderer/hit_vfx_pass.cc`
- Modify: `native/src/host/host_bindings.cc` (the `g_hit_vfx_pass->render(...)` call, line ~343)
- Test: `native/tests/renderer/hit_vfx_pass_test.cc` (create) + `native/tests/renderer/CMakeLists.txt`

- [ ] **Step 1: Add `World&` to the render signature (header)**

In `native/src/renderer/include/renderer/hit_vfx_pass.h`:
- Add `namespace scenegraph { class World; }` next to the existing `struct Camera;` forward declaration.
- Change the `render` declaration to:

```cpp
    void render(const std::vector<HitVfxDescriptor>& vfx,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);
```

- [ ] **Step 2: Update the call site**

In `native/src/host/host_bindings.cc` line ~343, change:

```cpp
        if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx, g_world, g_camera, *g_pipeline);
```

- [ ] **Step 3: Update spark constants + sprite + cone parametrisation in `hit_vfx_pass.cc`**

Add `#include <scenegraph/world.h>` and `#include <scenegraph/instance.h>` to the includes. Replace the spark constants block with weapon-distinct values, and switch the spark sprite. Near the top constants:

```cpp
// Weapon-distinct spark tints + cone half-angles (spec §3.4). weapon_kind:
// 0 = phaser (cool white-blue, tight), 1 = torpedo/disruptor (hot orange, wide).
constexpr glm::vec4 kSparkTint[2] = {
    {0.78f, 0.86f, 1.00f, 1.0f},   // phaser — cool white-blue
    {1.00f, 0.55f, 0.18f, 1.0f},   // torpedo — hot orange
};
constexpr float kSparkConeDegByKind[2] = {40.0f, 120.0f};  // phaser tight, torpedo wide
constexpr float kSparkSpeed     = 4.0f;    // wu/s initial speed
constexpr float kSparkSizeMult  = 0.6f;    // multiplier on tier peak_size
constexpr float kSparkDamping   = 1.4f;    // velocity damping rate (SDK SetDamping analogue)
```

Delete the old `kSparkCount`, `kSparkConeDeg`, and keep `hash3`. Change `rotate_jitter` to take a cone half-angle parameter:

```cpp
glm::vec3 rotate_jitter(const glm::vec3& base, const glm::vec3& cam_up,
                          const glm::vec3& cam_right, glm::vec2 jitter,
                          float cone_deg) {
    const float k = cone_deg * 3.14159265f / 180.0f;
    glm::vec3 v = base + cam_right * std::sin(jitter.x * k)
                       + cam_up    * std::sin(jitter.y * k);
    float len = glm::length(v);
    if (len > 1e-6f) v /= len;
    return v;
}
```

Change the spark sprite path constant:

```cpp
constexpr const char* kImpactTexturePath = "data/rough.tga";
```

(If `data/rough.tga` is absent at runtime the existing `ensure_texture` fallback logs and renders nothing — acceptable; tests gate on assets.)

- [ ] **Step 4: Rewrite the spark sub-block in `render`**

Replace the `// ── CRITICAL spark burst ──` block (the `if (sev == 2) { ... }`) with a hull-anchored, per-descriptor burst. Insert after the main billboard `glDrawArrays`:

```cpp
        // ── Spark burst (hull-anchored, detached, weapon-distinct) ──
        if (v.spark_count > 0 && v.instance_id >= 0) {
            const scenegraph::Instance* inst = world.get(v.instance_id);
            if (inst != nullptr) {
                // Resolve the emit frame through the ship's CURRENT world
                // matrix so the origin tracks the hull as the ship moves.
                const glm::vec3 origin =
                    glm::vec3(inst->world * glm::vec4(v.body_point, 1.0f));
                glm::vec3 base = glm::mat3(inst->world) * v.body_normal;
                float blen = glm::length(base);
                base = (blen > 1e-6f) ? base / blen : cam_right;

                const int kind = (v.weapon_kind == 0) ? 0 : 1;
                shader.set_vec4("u_tint", kSparkTint[kind]);
                const float cone = kSparkConeDegByKind[kind];
                // Damped ballistic travel: x(t) = (v0/c)(1 - e^{-c t}).
                const float travel =
                    (kSparkSpeed / kSparkDamping) * (1.0f - std::exp(-kSparkDamping * age));
                const float life_t = age / tier.total_life;
                for (int i = 0; i < v.spark_count; ++i) {
                    const glm::vec2 jitter = hash3(origin, i);
                    const glm::vec3 dir =
                        rotate_jitter(base, cam_up, cam_right, jitter, cone);
                    const glm::vec3 pos = origin + dir * travel;
                    const float spark_size =
                        kSparkSizeMult * tier.peak_size * (1.0f - life_t);
                    const float spark_alpha = 1.0f - life_t;
                    shader.set_vec3 ("u_world_position", pos);
                    shader.set_float("u_size",           spark_size);
                    shader.set_float("u_alpha",          spark_alpha);
                    glDrawArrays(GL_TRIANGLES, 0, 6);
                }
            }
        }
```

(`sev` is still used by the main billboard above; leave that. The spark burst no longer depends on `sev == 2` — count + kind come from the descriptor.)

- [ ] **Step 5: Write the failing render test**

Create `native/tests/renderer/hit_vfx_pass_test.cc`. Model it on `frame_test.cc` (offscreen `renderer::Window(..., visible=false)` under llvmpipe; `GTEST_SKIP()` if a GL context can't be created). It does not need BC assets — it can create a `World`, a stub instance with a set world matrix, and assert the burst origin resolves to `world * body_point`:

```cpp
// native/tests/renderer/hit_vfx_pass_test.cc
#include <gtest/gtest.h>
#include <scenegraph/world.h>
#include <scenegraph/instance.h>
#include <glm/glm.hpp>

// Pure-math regression for the hull-anchor resolve used by HitVfxPass.
// (The full GL draw is covered by frame_test-style smoke; here we lock the
// transform contract that makes sparks track a moving/rotating hull.)
TEST(HitVfxSparkAnchor, OriginTracksWorldMatrix) {
    glm::mat4 world(1.0f);
    world[3] = glm::vec4(100.0f, 0.0f, 0.0f, 1.0f);   // translate +X
    const glm::vec3 body_point(1.0f, 2.0f, 3.0f);
    const glm::vec3 origin = glm::vec3(world * glm::vec4(body_point, 1.0f));
    EXPECT_FLOAT_EQ(origin.x, 101.0f);
    EXPECT_FLOAT_EQ(origin.y, 2.0f);
    EXPECT_FLOAT_EQ(origin.z, 3.0f);

    // Re-place the ship; origin must follow.
    world[3] = glm::vec4(0.0f, 50.0f, 0.0f, 1.0f);
    const glm::vec3 origin2 = glm::vec3(world * glm::vec4(body_point, 1.0f));
    EXPECT_FLOAT_EQ(origin2.x, 1.0f);
    EXPECT_FLOAT_EQ(origin2.y, 52.0f);
}
```

Register it in `native/tests/renderer/CMakeLists.txt` by adding `hit_vfx_pass_test.cc` to the existing test-sources list next to `frame_test.cc`.

- [ ] **Step 6: Reconfigure, build, run**

Run:
```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R HitVfx --output-on-failure
```
Expected: `HitVfxSparkAnchor.OriginTracksWorldMatrix` PASS. (cmake reconfigure required — sprite path is a source change.)

- [ ] **Step 7: Manual smoke (optional but recommended)**

Run `./build/dauntless`, trigger a heavy torpedo hit, confirm an orange wide spark spray erupts from the hull and tracks the ship as it moves; a phaser critical shows a tighter cool-white burst. No crash, no GL error spew.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/hit_vfx_pass.h native/src/renderer/hit_vfx_pass.cc \
        native/src/host/host_bindings.cc native/tests/renderer/hit_vfx_pass_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(sparks): hull-anchored weapon-distinct spark burst in HitVfxPass"
```

---

# Part B — Emissive Flicker (torpedo/disruptor glow-map stutter)

> Builds on the shipped damage-decal Phase-2 shader. No Python or binding changes — every input (`u_decal_a/b/c`, `u_decal_time`, `u_ship_world_inv`, the glow map) already exists. A SCORCH decal is already created on every hull-penetrating torpedo/disruptor hit; the flicker is a term keyed off it.

## Task B1: Add the glow-stutter term to `opaque.frag`

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`

- [ ] **Step 1: Add flicker constants + `stutter` helper**

In `native/src/renderer/shaders/opaque.frag`, near the other decal constants (after `NOISE_SCALE`, ~line 56), add:

```glsl
// ── Torpedo/disruptor power-disruption flicker (spec §3.5) ──────────────────
// A ~500ms electrical stutter of the ship's OWN glow map within a SCORCH
// decal's radius. Signed multiplier on the sampled glow (above and below
// baseline). Distinct from the blackbody ember (deposited heat) on the same
// record. Phaser (HeatGlow) decals never flicker.
const float FLICKER_DURATION  = 0.5;    // seconds (game time)
const float STUTTER_GAIN      = 1.6;    // peak signed swing of the glow multiplier
const float FLICKER_TIGHTNESS = 4.0;    // radial falloff (normalised r)
const float STUTTER_FREQ      = 60.0;   // ~ rad/s base; gives ~8-12 flickers / window

float stutter(float age) {
    // Deterministic, all fragments of one decal share `age` so the patch
    // flickers together (electrical-disruption read). Mixes a fast sine with
    // a hashed irregular term, both in [-1, 1].
    float s1 = sin(age * STUTTER_FREQ);
    float s2 = sin(age * STUTTER_FREQ * 2.37 + 1.7);
    return clamp(0.6 * s1 + 0.4 * s2, -1.0, 1.0);
}
```

- [ ] **Step 2: Add a `glow_flicker` accumulator to `apply_damage_decals`**

Change the `apply_damage_decals` signature to add an `inout float glow_flicker`:

```glsl
void apply_damage_decals(vec3 p_body, vec3 n_body,
                         inout vec3 base_lit, inout vec3 emissive,
                         inout float glow_flicker) {
```

Inside the per-decal loop, in the SCORCH branch (the `weapon_class == 1` path — where the ember is computed), add the flicker accumulation. After the existing ember `emissive += ...` line, add:

```glsl
            // Power-disruption flicker: modulate the ship's own glow map for
            // ~500ms. Reuses wn (normal-aware) + the decal radius.
            float fl_age = u_decal_time - birth;          // `birth` = u_decal_c[i].x, already read above
            if (fl_age >= 0.0 && fl_age < FLICKER_DURATION) {
                float env  = 1.0 - (fl_age / FLICKER_DURATION);
                float fall = exp(-r * r * FLICKER_TIGHTNESS);
                glow_flicker += STUTTER_GAIN * env * stutter(fl_age) * fall * wn;
            }
```

(Confirm the local variable names `birth`, `r`, `wn` match those already in the function — the Phase-2 shader computes `r = length(p_body - point) / radius`, `wn` from the normal smoothstep, and reads `birth` from `u_decal_c[i].x`. Reuse them; do not recompute.)

- [ ] **Step 3: Apply the multiplier to the glow contribution in `main()`**

In `main()`, initialise the accumulator, pass it in, and fold it into the glow term:

```glsl
    vec3 decal_emissive = vec3(0.0);
    float glow_flicker = 1.0;
    if (u_decal_count > 0) {
        apply_damage_decals(p_body, n_body, lit, decal_emissive, glow_flicker);
    }

    vec4 glow = texture(u_glow_map, v_uv);
    // ... (spec/rim unchanged) ...
    float gf = max(glow_flicker, 0.0);   // clamp; dropout cannot go negative
    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a * gf
                      + spec + rim + decal_emissive, 1.0);
```

(Only the `glow.rgb * glow.a` term gains the `* gf` factor; everything else in the final sum is unchanged.)

- [ ] **Step 4: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds; shader compiles (watch stderr for GLSL compile errors on first `./build/dauntless` or in the render test below).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag
git commit -m "feat(flicker): 500ms glow-map electrical stutter on SCORCH decals"
```

---

## Task B2: Render tests for the flicker

**Files:**
- Modify: `native/tests/renderer/frame_test.cc` (extend — it already loads the Galaxy + decal-seeding helpers)

- [ ] **Step 1: Write the failing tests**

Add to `native/tests/renderer/frame_test.cc`, following its existing pattern (offscreen llvmpipe, load Galaxy, seed `inst.decals.add(...)`, render opaque, `glReadPixels`; `GTEST_SKIP()` without assets). Use a SCORCH decal placed over a glow-bearing region of the Galaxy (e.g. a saucer/window area — reuse whatever body point the existing decal tests use, choosing one where the baseline glow is non-zero):

```cpp
// Flicker present near birth, gone after the window, ember unaffected.
TEST_F(FrameTest, TorpedoFlickerModulatesGlowThenSettles) {
    if (!assets_available()) GTEST_SKIP();
    auto iid = load_galaxy_instance();              // existing helper
    const glm::vec3 body_pt = glow_bearing_body_point();   // see note below
    seed_scorch_decal(iid, body_pt, /*birth_time=*/10.0f); // existing-style helper

    // t just after birth: glow region modulated vs an undamaged baseline.
    const auto undamaged = render_and_sample_region(/*decals=*/false, body_pt);
    const auto fresh     = render_and_sample_region_at_time(body_pt, 10.02f);
    EXPECT_NE(luminance(fresh), luminance(undamaged));   // modulation present

    // t past the window: flicker gone (glow back to ~baseline), but the
    // ~10s ember is still present, so sample the GLOW band specifically.
    const auto settled = render_and_sample_region_at_time(body_pt, 10.0f + 0.6f);
    EXPECT_NEAR(glow_only(settled), glow_only(undamaged), kGlowTol);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Phaser (HeatGlow) decals never trigger the flicker.
TEST_F(FrameTest, PhaserDecalDoesNotFlickerGlow) {
    if (!assets_available()) GTEST_SKIP();
    auto iid = load_galaxy_instance();
    const glm::vec3 body_pt = glow_bearing_body_point();
    seed_heatglow_decal(iid, body_pt, /*birth_time=*/10.0f);
    const auto undamaged = render_and_sample_region(/*decals=*/false, body_pt);
    const auto fresh     = render_and_sample_region_at_time(body_pt, 10.02f);
    EXPECT_NEAR(glow_only(fresh), glow_only(undamaged), kGlowTol);
}

// Undamaged ship is byte-identical to the pre-flicker baseline.
TEST_F(FrameTest, UndamagedGlowUnchangedByFlickerCode) {
    if (!assets_available()) GTEST_SKIP();
    auto iid = load_galaxy_instance();
    const auto a = render_full_frame();              // empty ring
    const auto b = render_full_frame_baseline();     // captured reference
    EXPECT_TRUE(images_within_tolerance(a, b, /*tol=*/0));
}
```

Implementation notes for the executor:
- Reuse the seeding/sampling helpers already present in `frame_test.cc` for the Phase-2 decal tests. If a `render_*_at_time` variant doesn't exist, add a thin one that sets the decal-time uniform path the same way the host does (`u_decal_time`); the Phase-2 tests already drive `u_decal_time`, so follow that.
- `glow_bearing_body_point()`: pick a body point whose screen projection samples a non-zero glow texel on the Galaxy (the Phase-2 tests already identify hull regions; choose one over the engine/windows). If no glow-bearing region is convenient, assert on the **total** emissive change instead and document it — the contract is "fresh ≠ baseline, settled ≈ baseline."
- `kGlowTol`: small luminance tolerance consistent with the existing decal tests' tolerances.

- [ ] **Step 2: Reconfigure, build, run**

Run:
```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R Frame --output-on-failure
```
Expected: the three flicker tests PASS (or `GTEST_SKIP` without BC assets). Existing `FrameTest` cases still green.

- [ ] **Step 3: Commit**

```bash
git add native/tests/renderer/frame_test.cc
git commit -m "test(flicker): glow-stutter present near birth, settles after window, phaser exempt"
```

---

## Final verification

- [ ] **Run the focused Python suites:**

```bash
uv run pytest tests/unit/test_spark_policy.py tests/unit/test_hit_vfx_lifecycle.py \
              tests/unit/test_hit_feedback_dispatch.py \
              tests/integration/test_world_to_body_binding.py -q
```
Expected: all pass (binding test may asset-skip).

- [ ] **Run the focused renderer suites:**

```bash
ctest --test-dir build -R "HitVfx|Frame" --output-on-failure
```
Expected: all pass or asset-skip; no GL errors.

- [ ] **Manual smoke in `./build/dauntless`:** heavy torpedo hit → wide orange sparks tracking the hull + a brief windows/glow stutter near the impact; phaser critical → tighter cool-white sparks, no glow stutter; light phaser fire → no sparks. No crash.

---

## Self-Review (completed during planning)

- **Spec coverage:** §3.2 trigger → A1; §3.3 hull-anchor → A3/A4/A6; §3.4 weapon-distinct look → A1(kind)+A6(tint/cone/sprite); §3.5 flicker term → B1; §3.6 flash-unchanged → A6 keeps the `world_pos` billboard untouched; §3.7 differentiation/extent/fields → B1 (multiplier on sampled glow, no new fields, radius reused); §5 testing → tests in every task. All spec sections map to a task.
- **No new decal fields / no layout change:** B1 reads only existing `u_decal_*` uniforms — confirmed against `frame.cc` packing and `opaque.frag`. ✓
- **Type/name consistency:** `spark_params` (kw-only), `SPARK_KIND_{PHASER,TORPEDO}`, descriptor fields `instance_id/body_point/body_normal/weapon_kind/spark_count`, binding `world_to_body`, `g_world.get(id)->world`, `scenegraph::world_to_body/world_dir_to_body` — all used identically across tasks. ✓
- **Headless safety:** dispatch forces `spark_count = 0` when host/instance/normal absent, so Python-only tests and headless runs never require the renderer. ✓
```
