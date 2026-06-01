# Damage VFX + Bridge-View Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace today's blanket-fire `host.shield_hit` + `hit_vfx.spawn` calls in `_advance_combat` with a single internal dispatcher inside `apply_hit` that classifies every impact into SHIELD / HULL / CRITICAL and fans out to mutually-exclusive VFX, per-tier positional audio, and player-only camera shake. Thread the surface normal returned by `ray_trace_mesh` all the way to the renderer, and extend the existing `HitVfxPass` to render per-tier flashes with a CRITICAL spark burst along the normal.

**Architecture:** Two new pure-Python modules (`engine/appc/hit_feedback.py`, `engine/appc/camera_shake.py`) + one new SDK companion script (`sdk/Build/scripts/LoadDamageHitSounds.py`) + targeted edits to `engine/appc/combat.py`, `engine/appc/hit_vfx.py`, `engine/host_loop.py`, plus a renderer-side extension of `HitVfxDescriptor` / `hit_vfx_pass.cc` / `hit_vfx.frag` / `set_hit_vfx` binding. Tasks 1–6 are pure-Python and merge in a green state without touching the renderer. Task 7 (renderer) is lockstep with the Python-side render-data emission. Task 8 wires the integration. Task 9 verifies cross-cutting + visual smoke.

**Tech Stack:** Python 3 (pytest, enum.IntEnum, math), pybind11 (existing host bindings), C++ (OpenGL via glad, glm), GLSL fragment shader. No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-06-01-damage-vfx-bridge-feedback-design.md`](../specs/2026-06-01-damage-vfx-bridge-feedback-design.md).
**Branch:** `feature/damage-vfx-bridge-feedback` (already created from `main`).
**Build:** `cmake -B build -S . && cmake --build build -j`. **Shader edits** require re-running the configure step (`cmake -B build -S .`), not just `cmake --build`.

## Background facts the implementer needs

- **Column-vector rotation convention.** `R = ship.GetWorldRotation()` stores body axes as columns. `R.GetCol(1)` is the ship-forward axis; `R.GetCol(2)` is the ship-up. Never `GetRow`. See `CLAUDE.md` ↦ "Rotation matrix convention". The plan only touches camera math through `camera_shake.perturb(eye, target, up)`, which works in world frame and does not call `GetCol` directly — but if you find yourself reaching for `GetRow`, stop and reread CLAUDE.md.
- **Audio API.** Positional one-shot is `App.g_kSoundManager.GetSound(name).Play(position=(x,y,z))` (`engine/audio/tg_sound.py:110-122`, used by `engine/audio/engine_rumble.py:52-57`). Headless tests with `App.g_kSoundManager is None` are silent — that is the contract.
- **App shim limitations.** Tests that exercise SDK-imported modules require `tests/conftest.py`'s `_SDKFinder` to be active (already in place). New SDK script (`LoadDamageHitSounds.py`) goes under `sdk/Build/scripts/` and is importable via the same finder.
- **Mesh trace returns `(point, normal, t)` or `None`.** Today the Python side discards `normal` at [`engine/appc/combat.py:87`](../../engine/appc/combat.py#L87). The C++ binding (`host_bindings.cc:ray_trace_mesh`) is unchanged in this project — we just stop dropping the normal.
- **Existing `_FakeHost` in `tests/unit/test_combat_hit_resolution.py:63-70`** is the canonical mock for `ray_trace_mesh`. Reuse its pattern in new tests.
- **`tests/conftest.py` adjusts `sys.path` and injects an `_SDKFinder`** that resolves `App`, `LoadBridge`, and SDK module names. New tests do not need extra setup beyond `import pytest`.
- **`uv run pytest tests/unit/...` is safe.** The full suite OOMs (see memory `feedback_pytest_memory.md`); always specify the file or directory under test.

## File structure

### New files

| Path | Purpose |
|---|---|
| `engine/appc/hit_feedback.py` | `Severity` enum, `classify(...)`, `dispatch(...)` |
| `engine/appc/camera_shake.py` | `apply_kick`, `update`, `perturb`, `reset`, `get_energy` |
| `sdk/Build/scripts/LoadDamageHitSounds.py` | `LoadSounds()`, `g_lsSubsystemCriticals`, `GetRandomSound` rebind |
| `tests/unit/test_hit_feedback_classify.py` | Severity classification table |
| `tests/unit/test_hit_feedback_dispatch.py` | Dispatch fan-out (VFX + audio + camera shake) |
| `tests/unit/test_apply_hit_state_diff.py` | `_subsystem_state_flags` + `_diff_state` |
| `tests/unit/test_camera_shake_decay.py` | Energy decay + perturb math |
| `tests/unit/test_load_damage_hit_sounds.py` | Module shape sanity |
| `tests/integration/test_damage_severity_sequence.py` | Multi-tick continuous-fire scenario (§7.4) |

### Modified files

| Path | Edits |
|---|---|
| `engine/appc/combat.py` | `_resolve_hit_point` returns `(point, normal)`; `apply_hit` widens signature + tracks per-stage absorbed + calls dispatch; `_subsystem_state_flags` + `_diff_state` helpers |
| `engine/appc/hit_vfx.py` | `Severity` enum, `spawn(point, normal=None, severity=...)`, SHIELD early-return, `_LIFETIME = 0.7`, snapshot dict gains `normal` + `severity` |
| `engine/host_loop.py` | Bootstrap `LoadDamageHitSounds.LoadSounds()`; `_advance_combat` unpacks tuple from `_resolve_hit_point`, drops the duplicate `shield_hit`/`hit_vfx.spawn` calls, passes `normal`/`host`/`ship_instances` through `apply_hit` kwargs; `_build_hit_vfx_render_data` emits `normal` + `severity`; `camera_shake.update(dt)` per tick; `camera_shake.perturb(...)` post-`_compute_camera`; `camera_shake.reset()` on view-mode transition |
| `native/src/renderer/include/renderer/frame.h` | `HitVfxDescriptor` gains `glm::vec3 surface_normal` + `int severity` |
| `native/src/renderer/hit_vfx_pass.cc` | Per-tier `kPeakSize` / `kSpawnDur` / `kFadeDur` / `kTotalLife` / tint table; CRITICAL spark loop; `u_tint` uniform set per-draw |
| `native/src/renderer/shaders/hit_vfx.frag` | `uniform vec4 u_tint;` multiplied through texture sample |
| `native/src/host/host_bindings.cc` | `set_hit_vfx` reads `normal` + `severity` from descriptor dict |
| `tests/unit/test_combat_hit_resolution.py` | Update assertions to expect `(point, normal)` tuple |
| `tests/unit/test_apply_hit_routing.py` | Add asserts that dispatch is called with per-stage absorbed amounts |

### Verify-only (must stay green)

- `tests/unit/test_hit_vfx_lifecycle.py` — `spawn(point)` keeps working via defaults
- `tests/unit/test_shield_face_from_hit_point.py` — Project 3 work
- `tests/unit/test_subsystem_pick.py` (if it exists) — Project 2 work
- `tests/integration/test_phaser_damage_applied_through_apply_hit.py` — Project 1+2 work
- `tests/integration/test_mesh_ray_trace.py` — Project 1 work

---

## Task 1: Severity classifier + state-flag helpers

**Files:**
- Create: `engine/appc/hit_feedback.py`
- Create: `tests/unit/test_hit_feedback_classify.py`
- Modify: `engine/appc/combat.py` (add `_subsystem_state_flags` + `_diff_state`)
- Create: `tests/unit/test_apply_hit_state_diff.py`

This task introduces pure functions only — no integration with the rest of the pipeline yet. `classify` is consumed by Task 7's `dispatch`. `_subsystem_state_flags` / `_diff_state` are consumed by Task 3's `apply_hit` extension.

### Step 1.1: Write failing test for `Severity.classify`

- [ ] Create `tests/unit/test_hit_feedback_classify.py`:

```python
"""Severity classifier — pure function, table-driven.

Severity rule (spec §3.1):
- CRITICAL iff sub_transition is not None AND subsystem is not hull.
- SHIELD iff absorbed_shields > 0 AND nothing else absorbed anything.
- HULL otherwise.
"""
import pytest

from engine.appc.hit_feedback import Severity, classify


class _Sub:
    """Marker class for subsystem identity in the classifier."""
    pass


HULL = _Sub()
SENSORS = _Sub()
ENGINES = _Sub()
WEAPONS = _Sub()


@pytest.mark.parametrize(
    "absorbed_shields,absorbed_sub,absorbed_hull,sub_transition,subsystem,expected",
    [
        # (1) Shield-only absorb.
        (50.0, 0.0, 0.0, None, HULL, Severity.SHIELD),
        # (2) Shield + sub spillover.
        (30.0, 20.0, 0.0, None, SENSORS, Severity.HULL),
        # (3) Shield depleted, hull bleed.
        (30.0, 0.0, 20.0, None, HULL, Severity.HULL),
        # (4) Direct hull hit, no shields.
        (0.0, 0.0, 50.0, None, HULL, Severity.HULL),
        # (5) Sub flipped damaged.
        (0.0, 50.0, 0.0, "damaged", ENGINES, Severity.CRITICAL),
        # (6) Sub flipped disabled.
        (0.0, 100.0, 0.0, "disabled", WEAPONS, Severity.CRITICAL),
        # (7) Sub flipped destroyed.
        (0.0, 80.0, 0.0, "destroyed", SENSORS, Severity.CRITICAL),
        # (8) Hull "transition" is ignored — hull is excluded from CRITICAL.
        (0.0, 0.0, 999.0, "damaged", HULL, Severity.HULL),
        # (9) Subsystem == None edge case (no picked sub) → HULL.
        (0.0, 0.0, 50.0, None, None, Severity.HULL),
        # (10) Shield absorbed everything but subsystem is non-hull — still SHIELD.
        #      (Subsystem identity doesn't matter when nothing leaked past shields.)
        (100.0, 0.0, 0.0, None, SENSORS, Severity.SHIELD),
    ],
)
def test_classify_severity_table(absorbed_shields, absorbed_sub,
                                  absorbed_hull, sub_transition,
                                  subsystem, expected):
    assert classify(
        absorbed_shields=absorbed_shields,
        absorbed_subsystem=absorbed_sub,
        absorbed_hull=absorbed_hull,
        sub_transition=sub_transition,
        subsystem=subsystem,
        hull=HULL,
    ) == expected


def test_severity_enum_values():
    """Stable int values — used as a wire-side integer between Python and C++."""
    assert int(Severity.SHIELD) == 0
    assert int(Severity.HULL) == 1
    assert int(Severity.CRITICAL) == 2
```

### Step 1.2: Run test — expect collection failure (module not yet present)

```bash
uv run pytest tests/unit/test_hit_feedback_classify.py -v
```

Expected: `ModuleNotFoundError: No module named 'engine.appc.hit_feedback'`.

### Step 1.3: Create `engine/appc/hit_feedback.py` with `Severity` + `classify`

- [ ] Create `engine/appc/hit_feedback.py`:

```python
"""Damage-impact feedback dispatch.

Called from engine.appc.combat.apply_hit after damage is routed. Classifies
the impact into SHIELD / HULL / CRITICAL based on the per-stage absorbed
amounts and any subsystem state transition this tick, then fans out to the
mutually-exclusive visual (shield_hit OR hit_vfx.spawn), per-tier audio,
and (player-only) camera shake.

Severity rule (spec §3.1):
- CRITICAL iff a non-hull subsystem flipped state this tick.
- SHIELD iff shields absorbed > 0 and nothing else absorbed anything.
- HULL otherwise.

The WeaponHitEvent broadcast in apply_hit is unchanged; dispatch runs
before it, and dispatch failures are swallowed so a renderer-binding
crash never suppresses mission-side event handlers.
"""
from enum import IntEnum


class Severity(IntEnum):
    SHIELD = 0
    HULL = 1
    CRITICAL = 2


def classify(*, absorbed_shields: float, absorbed_subsystem: float,
             absorbed_hull: float, sub_transition,
             subsystem, hull) -> Severity:
    """Pure function. Tested separately from dispatch."""
    if sub_transition is not None and subsystem is not None and subsystem is not hull:
        return Severity.CRITICAL
    if absorbed_shields > 0.0 and absorbed_subsystem == 0.0 and absorbed_hull == 0.0:
        return Severity.SHIELD
    return Severity.HULL


# dispatch(...) is implemented in Task 7. Until then a no-op stub keeps
# apply_hit's call site importable.
def dispatch(*args, **kwargs) -> None:
    """Stub — replaced in Task 7."""
    return None
```

### Step 1.4: Run test — expect PASS

```bash
uv run pytest tests/unit/test_hit_feedback_classify.py -v
```

Expected: all 11 cases pass (10 parametrized + 1 enum check).

### Step 1.5: Write failing test for `_subsystem_state_flags` + `_diff_state`

- [ ] Create `tests/unit/test_apply_hit_state_diff.py`:

```python
"""_subsystem_state_flags + _diff_state.

Worst-new-flag priority: destroyed > disabled > damaged > None.
A flag transitioning False→True counts; True→True does not.
"""
import pytest

from engine.appc.combat import _subsystem_state_flags, _diff_state


class _Sub:
    """Configurable subsystem stub."""
    def __init__(self, damaged=False, disabled=False, destroyed=False):
        self._d = damaged
        self._x = disabled
        self._z = destroyed
    def IsDamaged(self):   return self._d
    def IsDisabled(self):  return self._x
    def IsDestroyed(self): return self._z


def test_flags_reads_all_three_methods():
    sub = _Sub(damaged=True, disabled=False, destroyed=True)
    assert _subsystem_state_flags(sub) == (True, False, True)


def test_flags_missing_methods_default_false():
    class Bare: pass
    assert _subsystem_state_flags(Bare()) == (False, False, False)


@pytest.mark.parametrize(
    "before,after,expected",
    [
        # No change.
        ((False, False, False), (False, False, False), None),
        ((True,  False, False), (True,  False, False), None),
        # Healthy → damaged.
        ((False, False, False), (True,  False, False), "damaged"),
        # Damaged → disabled (damaged stays True).
        ((True,  False, False), (True,  True,  False), "disabled"),
        # Disabled → destroyed.
        ((True,  True,  False), (True,  True,  True),  "destroyed"),
        # Multiple flags flipping at once — pick the worst NEW one.
        ((False, False, False), (True,  True,  False), "disabled"),
        ((False, False, False), (True,  True,  True),  "destroyed"),
        # Pre-existing damaged, jump straight to destroyed in one tick.
        ((True,  False, False), (True,  True,  True),  "destroyed"),
        # Already destroyed, no further transition possible.
        ((True,  True,  True),  (True,  True,  True),  None),
    ],
)
def test_diff_state_priority(before, after, expected):
    assert _diff_state(before, after) == expected
```

### Step 1.6: Run test — expect failure (helpers not yet present)

```bash
uv run pytest tests/unit/test_apply_hit_state_diff.py -v
```

Expected: `ImportError: cannot import name '_subsystem_state_flags' from 'engine.appc.combat'`.

### Step 1.7: Add the helpers to `engine/appc/combat.py`

- [ ] In `engine/appc/combat.py`, insert these two helpers immediately after the existing `_body_frame_delta` function (around current line 125, before `pick_target_subsystem`):

```python
def _subsystem_state_flags(sub) -> tuple:
    """Snapshot (IsDamaged, IsDisabled, IsDestroyed). Missing methods → False.

    Returned as a 3-tuple of bools so it can be diffed against a later
    snapshot via :func:`_diff_state`.
    """
    return (
        bool(sub.IsDamaged())   if hasattr(sub, "IsDamaged")   else False,
        bool(sub.IsDisabled())  if hasattr(sub, "IsDisabled")  else False,
        bool(sub.IsDestroyed()) if hasattr(sub, "IsDestroyed") else False,
    )


def _diff_state(before: tuple, after: tuple):
    """Worst NEW state-flag, or None if no flag flipped False→True.

    Priority: destroyed > disabled > damaged > None. Pre-existing True
    flags are ignored — only False→True transitions count.
    """
    b_dmg, b_dis, b_des = before
    a_dmg, a_dis, a_des = after
    if a_des and not b_des:
        return "destroyed"
    if a_dis and not b_dis:
        return "disabled"
    if a_dmg and not b_dmg:
        return "damaged"
    return None
```

### Step 1.8: Run test — expect PASS

```bash
uv run pytest tests/unit/test_apply_hit_state_diff.py tests/unit/test_hit_feedback_classify.py -v
```

Expected: all tests pass.

### Step 1.9: Commit

```bash
git add engine/appc/hit_feedback.py engine/appc/combat.py \
        tests/unit/test_hit_feedback_classify.py \
        tests/unit/test_apply_hit_state_diff.py
git commit -m "$(cat <<'EOF'
feat(combat): Severity classifier + subsystem state-diff helpers

Pure-function building blocks for the damage-feedback dispatcher:
- engine.appc.hit_feedback.Severity enum + classify() table-driven rule
- engine.appc.combat._subsystem_state_flags + _diff_state helpers

dispatch() is stubbed; Task 7 wires the fan-out.

Project 4 of the combat damage pipeline roadmap, Task 1 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 2: `_resolve_hit_point` returns `(point, normal)`

**Files:**
- Modify: `engine/appc/combat.py` (`_resolve_hit_point` lines 53-95)
- Modify: `engine/host_loop.py` (`_advance_combat` tuple unpack at lines 302-308 + the beam-clip path at lines 469-477)
- Modify: `tests/unit/test_combat_hit_resolution.py` (update assertions for new return shape)

The signature change is widely visible but mechanical. Both call sites consume only the point today; they keep working by ignoring the second element until Task 3 starts threading the normal.

### Step 2.1: Update tests in `test_combat_hit_resolution.py` to expect the tuple

- [ ] Edit `tests/unit/test_combat_hit_resolution.py`. Every `_resolve_hit_point(...)` call site must be wrapped to unpack `(point, normal)`. There are five test functions touching it: lines 73, 89, 104, 117, 132, 153 (each currently does `p = _resolve_hit_point(...)`).

Replace `test_resolve_returns_mesh_hit_when_trace_succeeds` (current lines 73-86):

```python
def test_resolve_returns_mesh_hit_when_trace_succeeds():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=((1.0, 2.0, 3.0), (0.0, 0.0, -1.0), 5.0))
    p, n = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p.x == pytest.approx(1.0)
    assert p.y == pytest.approx(2.0)
    assert p.z == pytest.approx(3.0)
    # NEW: normal threaded through from the mesh trace.
    assert n is not None
    assert n.x == pytest.approx(0.0)
    assert n.y == pytest.approx(0.0)
    assert n.z == pytest.approx(-1.0)
```

Replace `test_resolve_falls_back_to_sphere_entry_when_trace_misses` (current lines 89-101):

```python
def test_resolve_falls_back_to_sphere_entry_when_trace_misses():
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=None)
    p, n = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    # Sphere of radius 2 at origin; ray enters at z=-2.
    assert p.z == pytest.approx(-2.0)
    # NEW: sphere-entry path has no surface normal.
    assert n is None
```

Replace `test_resolve_returns_fallback_when_host_is_none` (current lines 104-114):

```python
def test_resolve_returns_fallback_when_host_is_none():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    p, n = _resolve_hit_point(
        host=None, ship_instances=None, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback
    assert n is None
```

Replace `test_resolve_returns_fallback_when_ship_instances_missing` (current lines 117-129):

```python
def test_resolve_returns_fallback_when_ship_instances_missing():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=((1.0, 2.0, 3.0), (0.0, 0.0, -1.0), 5.0))
    p, n = _resolve_hit_point(
        host=host, ship_instances={}, ship=ship,  # ship not in map
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback
    assert n is None
    assert host.calls == []  # binding must not be called without an iid
```

Replace `test_resolve_returns_fallback_when_binding_missing` (current lines 132-147):

```python
def test_resolve_returns_fallback_when_binding_missing():
    """If host exists but lacks ray_trace_mesh (older build), fall through."""
    class HostWithoutTrace:
        pass
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    p, n = _resolve_hit_point(
        host=HostWithoutTrace(), ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    # Sphere entry preferred when ray clearly intersects sphere.
    assert p.z == pytest.approx(-2.0)
    assert n is None
```

For the remaining call at line 153 (a similar fallback case), apply the same `p, n = _resolve_hit_point(...)` + `assert n is None` pattern. Read the surrounding context to confirm the test name.

### Step 2.2: Run tests — expect failure (still returns single TGPoint3)

```bash
uv run pytest tests/unit/test_combat_hit_resolution.py -v
```

Expected: tests fail with `TypeError: cannot unpack non-iterable TGPoint3 object` (or similar) on every `p, n = ...` line.

### Step 2.3: Modify `_resolve_hit_point` to return `(point, normal)`

- [ ] Edit `engine/appc/combat.py`. Replace the body of `_resolve_hit_point` (current lines 53-95) with:

```python
def _resolve_hit_point(host, ship_instances, ship,
                       ray_origin, ray_direction,
                       max_dist: float, fallback_point):
    """Three-tier hit-point fallback. Returns ``(point, normal)``.

    ``normal`` is a unit ``TGPoint3`` only when the mesh trace
    succeeded; sphere-entry and fallback paths return ``normal=None``.

    Tiers:
    1. Mesh trace via ``host.ray_trace_mesh`` (requires both host and
       a renderer InstanceId for this ship). Returns the surface point
       and the surface normal.
    2. Bounding-sphere entry. No normal available.
    3. ``fallback_point`` passed by the caller (torpedo position or
       phaser target_pos). No normal.
    """
    if host is None or ray_direction is None:
        return fallback_point, None
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None:
        return fallback_point, None
    if hasattr(host, "ray_trace_mesh"):
        try:
            result = host.ray_trace_mesh(
                iid,
                (ray_origin.x, ray_origin.y, ray_origin.z),
                (ray_direction.x, ray_direction.y, ray_direction.z),
                max_dist,
            )
        except Exception:
            # Native trace errors must not kill a combat tick; degrade to sphere entry.
            result = None
        if result is not None:
            (px, py, pz), (nx, ny, nz), _t = result
            return TGPoint3(px, py, pz), TGPoint3(nx, ny, nz)
    center = ship.GetWorldLocation()
    radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 0.0
    entry = ray_sphere_entry(ray_origin, ray_direction, max_dist,
                             center, radius)
    if entry is not None:
        return entry, None
    return fallback_point, None
```

### Step 2.4: Update both `_advance_combat` call sites in `engine/host_loop.py`

- [ ] At [`engine/host_loop.py:302-308`](engine/host_loop.py#L302-L308), replace:

```python
                impact_point = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=(aim_unit if dist > 1e-6 else None),
                    max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
                    fallback_point=target_pos,
                )
```

with:

```python
                impact_point, impact_normal = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=(aim_unit if dist > 1e-6 else None),
                    max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
                    fallback_point=target_pos,
                )
```

`impact_normal` is consumed by Task 3 (passed through to `apply_hit`). For now, it is bound but unused; Python won't warn.

- [ ] At [`engine/host_loop.py:469-477`](engine/host_loop.py#L469-L477) (the beam-clip path inside `_build_phaser_beam_render_data`), replace:

```python
                clipped = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=aim_unit,
                    max_dist=raw_length * 1.5,
                    fallback_point=beam_end,
                )
                if clipped is not None:
                    beam_end = clipped
```

with:

```python
                clipped, _clipped_normal = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=aim_unit,
                    max_dist=raw_length * 1.5,
                    fallback_point=beam_end,
                )
                if clipped is not None:
                    beam_end = clipped
```

The leading underscore makes it explicit the beam-clip path doesn't need the normal — only the impact path does.

### Step 2.5: Run all combat tests — expect PASS

```bash
uv run pytest tests/unit/test_combat_hit_resolution.py tests/unit/test_apply_hit_routing.py tests/unit/test_shield_face_from_hit_point.py -v
```

Expected: all green. `test_apply_hit_routing.py` and `test_shield_face_from_hit_point.py` don't touch `_resolve_hit_point` so they should be unaffected.

### Step 2.6: Commit

```bash
git add engine/appc/combat.py engine/host_loop.py \
        tests/unit/test_combat_hit_resolution.py
git commit -m "$(cat <<'EOF'
feat(combat): thread surface normal from ray_trace_mesh

_resolve_hit_point now returns (point, normal). Normal is a unit TGPoint3
when the mesh trace succeeds; None on sphere-entry and fallback paths.
Both _advance_combat call sites updated to unpack the tuple.

Sets up Task 3's apply_hit normal kwarg.

Project 4 of the combat damage pipeline roadmap, Task 2 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 3: `apply_hit` records per-stage absorbed + state transition, calls dispatch stub

**Files:**
- Modify: `engine/appc/combat.py` (`apply_hit` lines 206-249)
- Modify: `engine/host_loop.py` (`_advance_combat` torpedo + phaser paths — pass `normal`, `host`, `ship_instances`)
- Modify: `tests/unit/test_apply_hit_routing.py` (add tests asserting dispatch is called with per-stage breakdown)

`hit_feedback.dispatch` is still a stub (Task 1 left it as a no-op). This task wires `apply_hit` to *call* the stub with the right arguments — the actual fan-out lands in Task 7.

### Step 3.1: Inspect existing `test_apply_hit_routing.py` to confirm fixture shape

- [ ] Read `tests/unit/test_apply_hit_routing.py` to learn the existing `_FakeShip` / `_FakeShield` fixtures. The new test cases below assume the existing fixtures exist; if you need to add a fixture (e.g. a `_FakeSubsystem` that returns `_d/_x/_z` flags), put it next to the existing ones.

### Step 3.2: Write failing test for dispatch call with per-stage absorbed

- [ ] Append to `tests/unit/test_apply_hit_routing.py`:

```python
# ── apply_hit calls hit_feedback.dispatch with per-stage breakdown ─────────

class _SpyDispatch:
    """Capture dispatch calls for assertion."""
    def __init__(self):
        self.calls = []
    def __call__(self, *args, **kwargs):
        self.calls.append(kwargs)


def test_apply_hit_calls_dispatch_with_absorbed_shields(monkeypatch):
    """Shield absorbs the entire hit; absorbed_shields=damage, others=0."""
    from engine.appc import combat, hit_feedback
    from engine.appc.math import TGPoint3

    spy = _SpyDispatch()
    monkeypatch.setattr(hit_feedback, "dispatch", spy)

    # Build a ship whose shield face FRONT has 100 charge.
    ship = _make_ship_with_full_shield(face_charge=100.0)   # helper in this file
    combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0, 1, 0),
                     source=None, subsystem=None,
                     normal=TGPoint3(0, -1, 0))

    assert len(spy.calls) == 1
    kw = spy.calls[0]
    assert kw["absorbed_shields"] == pytest.approx(30.0)
    assert kw["absorbed_subsystem"] == pytest.approx(0.0)
    assert kw["absorbed_hull"] == pytest.approx(0.0)
    assert kw["sub_transition"] is None
    assert kw["normal"].y == pytest.approx(-1.0)


def test_apply_hit_calls_dispatch_with_hull_bleed(monkeypatch):
    """Shields drained, hull absorbs the overflow."""
    from engine.appc import combat, hit_feedback
    from engine.appc.math import TGPoint3

    spy = _SpyDispatch()
    monkeypatch.setattr(hit_feedback, "dispatch", spy)

    ship = _make_ship_with_full_shield(face_charge=10.0)
    combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0, 1, 0),
                     source=None, subsystem=None,
                     normal=None)

    kw = spy.calls[0]
    assert kw["absorbed_shields"] == pytest.approx(10.0)
    # subsystem=None → no sub absorb in this branch; pick_target_subsystem
    # may return the hull, in which case absorbed_subsystem stays 0 and
    # the 20 spills to hull.
    assert kw["absorbed_subsystem"] == pytest.approx(0.0)
    assert kw["absorbed_hull"] == pytest.approx(20.0)


def test_apply_hit_dispatch_captures_subsystem_transition(monkeypatch):
    """A subsystem that flips disabled this tick produces sub_transition='disabled'."""
    from engine.appc import combat, hit_feedback
    from engine.appc.math import TGPoint3

    spy = _SpyDispatch()
    monkeypatch.setattr(hit_feedback, "dispatch", spy)

    # Use a subsystem whose IsDisabled flips False→True after DamageSystem.
    ship = _make_ship_with_flipping_sub(initial_dmg=False,
                                          initial_dis=False,
                                          final_dmg=True,
                                          final_dis=True)
    combat.apply_hit(ship, damage=50.0, hit_point=TGPoint3(0, 1, 0),
                     source=None, subsystem=ship._flipping_sub,
                     normal=None)

    kw = spy.calls[0]
    assert kw["sub_transition"] == "disabled"


def _make_ship_with_full_shield(*, face_charge):
    """Ship with FRONT shield charged to `face_charge`, no children.
    pick_target_subsystem returns hull (no candidate children pass the
    proximity gate)."""
    shields = _FakeShields(current=face_charge)
    hull = _FakeSubsystem("Hull", max_cond=1000.0)
    return _FakeShip(shields=shields, hull=hull, children=[])


class _FlippingSub(_FakeSubsystem):
    """Subsystem whose IsDamaged/IsDisabled return initial_* until
    DamageSystem is called once, then final_*."""
    def __init__(self, *, initial_dmg, initial_dis,
                 final_dmg, final_dis,
                 position=None, radius=2.0):
        super().__init__("Flipping", max_cond=100.0,
                         position=position or TGPoint3(0, 5, 0),
                         radius=radius)
        self._initial = (initial_dmg, initial_dis, False)
        self._final = (final_dmg, final_dis, False)
        self._damaged_called = False
    def IsDamaged(self):
        return (self._final if self._damaged_called else self._initial)[0]
    def IsDisabled(self):
        return (self._final if self._damaged_called else self._initial)[1]
    def IsDestroyed(self):
        return False
    def SetCondition(self, v):
        super().SetCondition(v)
        self._damaged_called = True


def _make_ship_with_flipping_sub(*, initial_dmg, initial_dis,
                                   final_dmg, final_dis):
    """Ship with one _FlippingSub as a child, no shields. Caller passes
    ship._flipping_sub explicitly to apply_hit's `subsystem` kwarg."""
    shields = _FakeShields(current=0.0)
    hull = _FakeSubsystem("Hull", max_cond=1000.0)
    flipping = _FlippingSub(
        initial_dmg=initial_dmg, initial_dis=initial_dis,
        final_dmg=final_dmg, final_dis=final_dis,
        position=TGPoint3(0, 1, 0), radius=10.0,
    )
    ship = _FakeShip(shields=shields, hull=hull, children=[flipping])
    ship._flipping_sub = flipping
    return ship
```

**Note to implementer:** the two `_make_ship_*` helpers must be implemented against the existing fixtures in the file. Read `tests/unit/test_apply_hit_routing.py` first to pick the right base classes; do not introduce parallel fixture hierarchies. If the existing fixtures don't compose this way, add a minimal `_FlippingSub` class with two-stage `IsDisabled()` semantics (a counter or `_called_damage_system` flag toggled by `DamageSystem`).

### Step 3.3: Run tests — expect failure (apply_hit doesn't accept `normal` kwarg, doesn't call dispatch)

```bash
uv run pytest tests/unit/test_apply_hit_routing.py -v
```

Expected: TypeError on the `normal=...` kwarg, or AssertionError that `spy.calls` is empty.

### Step 3.4: Rewrite `apply_hit` body in `engine/appc/combat.py`

- [ ] Replace `apply_hit` (current lines 206-249) with:

```python
def apply_hit(ship, damage: float, hit_point, source, subsystem=None,
              *, normal=None, host=None, ship_instances=None) -> None:
    """Route `damage` to `ship`: shields face first → picked subsystem
    → hull bleed.  Then call hit_feedback.dispatch with the per-stage
    absorbed breakdown + subsystem state transition + surface normal,
    then broadcast WeaponHitEvent so per-ship and broadcast handlers
    (MissionLib.FriendlyFireHandler) react.

    New kwargs:
        normal — TGPoint3 surface normal at hit_point, or None if the
                 mesh trace missed. Threaded to hit_feedback.dispatch.
        host, ship_instances — passed through to dispatch so it can
                 fire host.shield_hit (the shield-bubble splash on
                 SHIELD severity).

    Dispatch is wrapped in try/except so a renderer or audio crash
    cannot suppress the WeaponHitEvent broadcast.
    """
    from engine.appc.events import WeaponHitEvent
    from engine.appc import hit_feedback
    import App

    if subsystem is None:
        subsystem = pick_target_subsystem(ship, hit_point)

    remaining = float(damage)
    absorbed_shields = 0.0
    absorbed_subsystem = 0.0
    absorbed_hull = 0.0
    sub_transition = None
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None

    # 1. Shields take it first.
    shields = ship.GetShields() if hasattr(ship, "GetShields") else None
    if shields is not None and hasattr(shields, "ApplyDamage"):
        face = _shield_face_from_hit_point(ship, hit_point)
        before_shields = remaining
        remaining = shields.ApplyDamage(face, remaining)
        absorbed_shields = before_shields - remaining

    # 2. Bleed remainder to picked subsystem (skip if subsystem is the hull —
    #    the hull-bleed branch below handles that).
    if remaining > 0.0 and subsystem is not None and subsystem is not hull \
            and hasattr(ship, "DamageSystem"):
        before_flags = _subsystem_state_flags(subsystem)
        current = subsystem.GetCondition() if hasattr(subsystem, "GetCondition") else remaining
        absorb = min(remaining, current)
        ship.DamageSystem(subsystem, absorb)
        absorbed_subsystem = absorb
        remaining -= absorb
        after_flags = _subsystem_state_flags(subsystem)
        sub_transition = _diff_state(before_flags, after_flags)

    # 3. Bleed final remainder to hull.
    if remaining > 0.0 and hull is not None and hasattr(ship, "DamageSystem"):
        ship.DamageSystem(hull, remaining)
        absorbed_hull = remaining
        remaining = 0.0

    # 4. Fan out VFX + audio + camera shake. Errors swallowed so the
    #    downstream WeaponHitEvent broadcast always runs.
    try:
        hit_feedback.dispatch(
            ship=ship, source=source, point=hit_point, normal=normal,
            damage=damage, subsystem=subsystem,
            absorbed_shields=absorbed_shields,
            absorbed_subsystem=absorbed_subsystem,
            absorbed_hull=absorbed_hull,
            sub_transition=sub_transition,
            host=host, ship_instances=ship_instances,
        )
    except Exception:
        # Dispatch failures must not suppress mission handlers below.
        pass

    # 5. Broadcast WeaponHitEvent.
    evt = WeaponHitEvent()
    evt.SetSource(source)
    evt.SetTarget(ship)
    evt.SetDamage(damage)
    evt.SetHitPoint(hit_point)
    evt.SetSubsystem(subsystem)
    if isinstance(ship, App.TGEventHandlerObject):
        evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)
```

### Step 3.5: Update `_advance_combat` to pass new kwargs through

- [ ] In `engine/host_loop.py`, edit the torpedo branch ([lines 232-249](engine/host_loop.py#L232-L249)). The current code reads:

```python
    for torpedo, ship, subsystem, hit_point in hits:
        apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship, subsystem=subsystem)
        hit_vfx.spawn(hit_point)
        if (host is not None
                and ship_instances is not None
                and hasattr(host, "shield_hit")):
            iid = ship_instances.get(ship)
            if iid is not None:
                host.shield_hit(
                    instance_id=iid,
                    point=(hit_point.x, hit_point.y, hit_point.z),
                    rgba=(0.0, 0.0, 0.0, 0.0),
                    intensity=1.0,
                )
```

`hits` doesn't currently carry a normal — torpedo hits go through `projectiles.update_all` which reports `(torpedo, ship, subsystem, hit_point)` 4-tuples. Two routes forward:

**Route A (preferred, simpler):** thread `normal=None` for torpedoes in this task. Torpedoes don't get a mesh-trace normal in v1; they use the bounding-sphere swept check. Sentinel handling in the renderer covers it (§6.3 of the spec).

**Route B:** call `_resolve_hit_point` with the torpedo's per-tick motion ray to *try* to get a normal. Extra work; deferred to a polish pass.

Route A is the chosen scope. Replace the torpedo branch with:

```python
    for torpedo, ship, subsystem, hit_point in hits:
        apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship, subsystem=subsystem,
                  normal=None, host=host, ship_instances=ship_instances)
        # NOTE: hit_vfx.spawn + host.shield_hit moved into
        # hit_feedback.dispatch (Task 7). Do not call them here.
```

- [ ] Edit the phaser branch ([lines 295-321](engine/host_loop.py#L295-L321)). Replace:

```python
            damage = _phaser_damage_for_tick(...)
            if damage > 0:
                impact_point, impact_normal = _resolve_hit_point(...)
                apply_hit(target, damage, impact_point,
                          source=ship, subsystem=target_sub)
                if (host is not None
                        and ship_instances is not None
                        and hasattr(host, "shield_hit")):
                    iid = ship_instances.get(target)
                    if iid is not None:
                        host.shield_hit(
                            instance_id=iid,
                            point=(impact_point.x, impact_point.y, impact_point.z),
                            rgba=(0.0, 0.0, 0.0, 0.0),
                            intensity=1.0,
                        )
```

(Note: the `impact_point, impact_normal = _resolve_hit_point(...)` was added in Task 2.) Now also drop the trailing `host.shield_hit` block:

```python
            damage = _phaser_damage_for_tick(
                max_damage=bank.GetMaxDamage(),
                max_damage_distance=bank.GetMaxDamageDistance(),
                dist=dist,
                dt=dt,
            )
            if damage > 0:
                impact_point, impact_normal = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=(aim_unit if dist > 1e-6 else None),
                    max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
                    fallback_point=target_pos,
                )
                apply_hit(target, damage, impact_point,
                          source=ship, subsystem=target_sub,
                          normal=impact_normal,
                          host=host, ship_instances=ship_instances)
                # NOTE: host.shield_hit moved into hit_feedback.dispatch
                # (Task 7). Do not call it here.
```

### Step 3.6: Run tests — expect PASS for the new dispatch-spy tests; existing tests still green

```bash
uv run pytest tests/unit/test_apply_hit_routing.py tests/unit/test_combat_hit_resolution.py -v
```

Expected: all green.

### Step 3.7: Run the broader combat + integration suite to confirm nothing regressed

```bash
uv run pytest tests/unit/test_apply_hit_routing.py \
              tests/unit/test_combat_hit_resolution.py \
              tests/unit/test_hit_feedback_classify.py \
              tests/unit/test_apply_hit_state_diff.py \
              tests/unit/test_hit_vfx_lifecycle.py \
              tests/unit/test_shield_face_from_hit_point.py \
              tests/integration/test_phaser_damage_applied_through_apply_hit.py -v
```

Expected: all green. Dispatch stub is a no-op so the existing damage-routing assertions are unaffected.

### Step 3.8: Commit

```bash
git add engine/appc/combat.py engine/host_loop.py tests/unit/test_apply_hit_routing.py
git commit -m "$(cat <<'EOF'
feat(combat): apply_hit records per-stage absorbed + calls dispatch stub

apply_hit now tracks absorbed_shields / absorbed_subsystem / absorbed_hull
during routing and snapshots the picked subsystem's state flags before
and after DamageSystem to detect a tick-local transition. Calls
hit_feedback.dispatch(...) with the breakdown + normal + host hooks
before broadcasting WeaponHitEvent. Dispatch failures are swallowed so
mission-side handlers always see the event.

_advance_combat drops its own host.shield_hit + hit_vfx.spawn calls —
both move into dispatch in Task 7. apply_hit gains normal=, host=,
ship_instances= kwargs.

Project 4 of the combat damage pipeline roadmap, Task 3 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 4: `hit_vfx` extends with `Severity` + normal + per-tier life

**Files:**
- Modify: `engine/appc/hit_vfx.py`
- Verify-only: `tests/unit/test_hit_vfx_lifecycle.py` (must stay green via defaults)
- New test: append to `tests/unit/test_hit_vfx_lifecycle.py`

`Severity` needs to be importable from both `hit_feedback` and `hit_vfx`. We define it in `hit_feedback.py` (Task 1) and re-export it from `hit_vfx.py` so call sites that already import from `hit_vfx` don't need to learn the new module name.

### Step 4.1: Write failing test for new spawn signature

- [ ] Append to `tests/unit/test_hit_vfx_lifecycle.py`:

```python
# ── extended spawn signature: normal + severity ────────────────────────────

def test_spawn_with_normal_and_severity_records_both():
    from engine.appc import hit_vfx
    from engine.appc.hit_vfx import Severity
    from engine.appc.math import TGPoint3

    hit_vfx._active.clear()

    pos = TGPoint3(1.0, 2.0, 3.0)
    n = TGPoint3(0.0, 0.0, -1.0)
    hit_vfx.spawn(pos, normal=n, severity=Severity.HULL)

    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    entry = snap[0]
    assert entry["position"].x == 1.0
    assert entry["normal"].z == -1.0
    assert entry["severity"] == int(Severity.HULL)


def test_spawn_shield_severity_is_noop():
    """SHIELD severity is filtered at the Python side — the shield_hit
    pass on the renderer handles the bubble splash separately."""
    from engine.appc import hit_vfx
    from engine.appc.hit_vfx import Severity
    from engine.appc.math import TGPoint3

    hit_vfx._active.clear()
    hit_vfx.spawn(TGPoint3(0, 0, 0), severity=Severity.SHIELD)
    assert hit_vfx.snapshot() == []


def test_spawn_legacy_call_defaults_to_hull():
    """Old call sites that pass only the point still work; severity
    defaults to HULL and normal defaults to None."""
    from engine.appc import hit_vfx
    from engine.appc.hit_vfx import Severity
    from engine.appc.math import TGPoint3

    hit_vfx._active.clear()
    hit_vfx.spawn(TGPoint3(0, 0, 0))
    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    assert snap[0]["severity"] == int(Severity.HULL)
    assert snap[0]["normal"] is None


def test_lifetime_widens_to_cover_critical_tail():
    """_LIFETIME must be at least 0.7s — CRITICAL kTotalLife in the renderer."""
    from engine.appc import hit_vfx
    assert hit_vfx._LIFETIME >= 0.7
```

### Step 4.2: Run tests — expect failure (Severity not present, spawn signature wrong)

```bash
uv run pytest tests/unit/test_hit_vfx_lifecycle.py -v
```

Expected: ImportError on `Severity` and/or TypeError on `severity=` kwarg.

### Step 4.3: Rewrite `engine/appc/hit_vfx.py`

- [ ] Replace the file contents with:

```python
"""Transient impact-VFX registry.

Per-impact descriptors are pushed via spawn(...); the renderer reads them
via snapshot() each frame. SHIELD severity is filtered here — the shield
bubble splash is handled by the renderer's shield_hit pass directly and
should not also appear as a hit_vfx descriptor.

_LIFETIME is widened from 0.5s to 0.7s to cover the CRITICAL spark burst
tail. Renderer-side fade timing is per-tier (see native/.../hit_vfx_pass.cc).
"""
from engine.appc.hit_feedback import Severity
from engine.appc.math import TGPoint3


_LIFETIME = 0.7  # seconds — must cover renderer's longest kTotalLife (CRITICAL = 0.65s).


_active: list[dict] = []


def spawn(position: TGPoint3, normal=None, severity=Severity.HULL) -> None:
    """Register a new hit VFX at `position`.

    `normal` is a unit TGPoint3 surface normal or None (mesh trace missed).
    `severity` is Severity.SHIELD / HULL / CRITICAL. SHIELD is a no-op —
    the shield_hit renderer pass handles its own splash.
    """
    if severity == Severity.SHIELD:
        return
    _active.append({
        "position": position,
        "normal":   normal,
        "severity": int(severity),
        "age":      0.0,
    })


def update_ages(dt: float) -> None:
    """Increment ages by dt; prune entries past _LIFETIME."""
    dt = float(dt)
    survivors = []
    for entry in _active:
        new_age = entry["age"] + dt
        if new_age < _LIFETIME:
            entry["age"] = new_age
            survivors.append(entry)
    _active.clear()
    _active.extend(survivors)


def snapshot() -> list[dict]:
    """Return a shallow copy of active VFX for renderer push."""
    return list(_active)
```

### Step 4.4: Run tests — expect PASS

```bash
uv run pytest tests/unit/test_hit_vfx_lifecycle.py -v
```

Expected: all tests pass.

### Step 4.5: Commit

```bash
git add engine/appc/hit_vfx.py tests/unit/test_hit_vfx_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(hit_vfx): spawn takes normal + severity; SHIELD is filtered

hit_vfx.spawn(point, normal=None, severity=Severity.HULL) — Severity is
re-exported from engine.appc.hit_feedback. SHIELD severity early-returns
so the shield bubble splash (handled by the C++ shield_hit pass) is the
only visual that fires on shield-absorbed hits.

_LIFETIME widens to 0.7s to cover the renderer's CRITICAL spark burst
tail. snapshot() entries gain 'normal' (TGPoint3 or None) and 'severity'
(int) keys; '_build_hit_vfx_render_data' will emit them in Task 8.

Project 4 of the combat damage pipeline roadmap, Task 4 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 5: `LoadDamageHitSounds.py` SDK companion + bootstrap wire-up

**Files:**
- Create: `sdk/Build/scripts/LoadDamageHitSounds.py`
- Create: `tests/unit/test_load_damage_hit_sounds.py`
- Modify: `engine/host_loop.py` (bootstrap call at lines 127-132)

### Step 5.1: Write failing test for `LoadDamageHitSounds` module shape

- [ ] Create `tests/unit/test_load_damage_hit_sounds.py`:

```python
"""LoadDamageHitSounds module shape: pool tuple non-empty, names unique,
GetRandomSound is bound at LoadSounds() time."""
import pytest


def test_module_imports():
    import LoadDamageHitSounds
    assert hasattr(LoadDamageHitSounds, "LoadSounds")
    assert callable(LoadDamageHitSounds.LoadSounds)


def test_critical_pool_non_empty_and_unique():
    import LoadDamageHitSounds
    pool = LoadDamageHitSounds.g_lsSubsystemCriticals
    assert len(pool) >= 4, "need at least 4 entries for GetRandomSound rotation"
    assert len(set(pool)) == len(pool), "pool entries must be unique"
    for name in pool:
        assert isinstance(name, str)
        assert name.startswith("Subsystem Critical")


def test_get_random_sound_bound_after_loadsounds(monkeypatch):
    """LoadSounds() rebinds GetRandomSound to LoadTacticalSounds.GetRandomSound
    so callers don't need a separate import."""
    import LoadDamageHitSounds
    # Reset to unbound state to verify rebind is idempotent.
    LoadDamageHitSounds.GetRandomSound = None

    # Stub out App.Game_GetCurrentGame().LoadSound so LoadSounds doesn't
    # need a real audio backend.
    import App
    class _StubGame:
        def LoadSound(self, path, name, loadspec):
            class _Snd:
                def SetVolume(self, *_a): return self
            return _Snd()
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _StubGame())

    LoadDamageHitSounds.LoadSounds()
    assert LoadDamageHitSounds.GetRandomSound is not None
    # Sanity: invoking it returns one of the pool entries.
    pick = LoadDamageHitSounds.GetRandomSound(LoadDamageHitSounds.g_lsSubsystemCriticals)
    assert pick in LoadDamageHitSounds.g_lsSubsystemCriticals
```

### Step 5.2: Run test — expect ModuleNotFoundError

```bash
uv run pytest tests/unit/test_load_damage_hit_sounds.py -v
```

Expected: `ModuleNotFoundError: No module named 'LoadDamageHitSounds'`.

### Step 5.3: Create `sdk/Build/scripts/LoadDamageHitSounds.py`

- [ ] Create the file:

```python
"""LoadDamageHitSounds — companion to LoadTacticalSounds.

Registers damage-impact audio names not in stock BC:
- "Shield Hit"               — single name, softer existing WAV.
- "Subsystem Critical 1-8"   — pool re-pointing the existing
                               explo_large_NN.WAV files under new names
                               so the existing g_lsBigDeathExplosions
                               registrations (used for station deaths)
                               are not overloaded.

Hull-tier audio uses the orphaned g_lsWeaponExplosions pool already
declared in LoadTacticalSounds; no entries needed here for HULL.

Called once at host bootstrap alongside LoadTacticalSounds.LoadSounds().
"""
import App


g_lsSubsystemCriticals = (
    "Subsystem Critical 1",
    "Subsystem Critical 2",
    "Subsystem Critical 3",
    "Subsystem Critical 4",
    "Subsystem Critical 5",
    "Subsystem Critical 6",
    "Subsystem Critical 7",
    "Subsystem Critical 8",
)


# Rebound by LoadSounds() so callers can use a single
# LoadDamageHitSounds.GetRandomSound(pool) call without importing
# LoadTacticalSounds. Initial value is None so the test in
# tests/unit/test_load_damage_hit_sounds.py can verify the rebind.
GetRandomSound = None


def LoadSounds():
    """Register the new sound names with TGSoundManager."""
    global GetRandomSound
    pGame = App.Game_GetCurrentGame()

    # SHIELD tier — softer existing WAV, volume reduced.
    snd = pGame.LoadSound("sfx/Explosions/explo15.WAV",
                           "Shield Hit", App.TGSound.LS_3D)
    if snd is not None:
        snd.SetVolume(0.6)

    # CRITICAL tier pool — explo_large_NN.WAV under new names.
    pGame.LoadSound("sfx/Explosions/explo_large_01.WAV",
                     "Subsystem Critical 1", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_02.WAV",
                     "Subsystem Critical 2", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_03.WAV",
                     "Subsystem Critical 3", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_04.WAV",
                     "Subsystem Critical 4", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_05.WAV",
                     "Subsystem Critical 5", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_06.WAV",
                     "Subsystem Critical 6", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_07.WAV",
                     "Subsystem Critical 7", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_08.WAV",
                     "Subsystem Critical 8", App.TGSound.LS_3D)

    # Rebind GetRandomSound to LoadTacticalSounds' implementation so
    # callers have a single picker entry point.
    import LoadTacticalSounds
    GetRandomSound = LoadTacticalSounds.GetRandomSound
```

### Step 5.4: Run test — expect PASS

```bash
uv run pytest tests/unit/test_load_damage_hit_sounds.py -v
```

Expected: all green.

### Step 5.5: Wire bootstrap call in `engine/host_loop.py`

- [ ] At `engine/host_loop.py` lines 127-132, replace:

```python
    try:
        import LoadTacticalSounds
        LoadTacticalSounds.LoadSounds()
    except Exception as _e:
        print(f"[host_loop] WARNING: LoadTacticalSounds.LoadSounds() failed: {_e}",
              flush=True)
```

with:

```python
    try:
        import LoadTacticalSounds
        LoadTacticalSounds.LoadSounds()
    except Exception as _e:
        print(f"[host_loop] WARNING: LoadTacticalSounds.LoadSounds() failed: {_e}",
              flush=True)

    # Damage-impact sounds — Shield Hit + Subsystem Critical pool.
    # Depends on LoadTacticalSounds having loaded first (rebinds
    # GetRandomSound from there).
    try:
        import LoadDamageHitSounds
        LoadDamageHitSounds.LoadSounds()
    except Exception as _e:
        print(f"[host_loop] WARNING: LoadDamageHitSounds.LoadSounds() failed: {_e}",
              flush=True)
```

### Step 5.6: Commit

```bash
git add sdk/Build/scripts/LoadDamageHitSounds.py \
        tests/unit/test_load_damage_hit_sounds.py \
        engine/host_loop.py
git commit -m "$(cat <<'EOF'
feat(audio): register damage-impact sound names via SDK companion

LoadDamageHitSounds.LoadSounds() registers 'Shield Hit' (softer
explo15.WAV at volume 0.6) and 'Subsystem Critical 1-8' (re-pointing
explo_large_NN.WAV). Avoids overloading the existing
g_lsBigDeathExplosions registration used for station deaths.

Bootstrap call wired next to LoadTacticalSounds.LoadSounds() in
host_loop. GetRandomSound rebound from LoadTacticalSounds at LoadSounds()
time so consumers have a single picker entry point.

Project 4 of the combat damage pipeline roadmap, Task 5 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 6: `camera_shake` module

**Files:**
- Create: `engine/appc/camera_shake.py`
- Create: `tests/unit/test_camera_shake_decay.py`

Pure Python, no `App` import, no host. Fully testable in isolation. Wired into `host_loop` in Task 9.

### Step 6.1: Write failing tests

- [ ] Create `tests/unit/test_camera_shake_decay.py`:

```python
"""camera_shake — energy decay + perturbation math.

API:
    apply_kick(damage: float) -> None
    update(dt: float) -> None
    perturb(eye, target, up) -> (eye, target, up)
    reset() -> None
    get_energy() -> float
"""
import math

import pytest


# ── energy decay ───────────────────────────────────────────────────────────

def test_apply_kick_increases_energy():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    assert camera_shake.get_energy() == pytest.approx(2.0)   # 100 / DAMAGE_PER_UNIT_ENERGY=50


def test_apply_kick_clamped_to_max_kick_energy():
    """A single 10000-damage hit injects at most MAX_KICK_ENERGY = 4.0."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(10000.0)
    assert camera_shake.get_energy() == pytest.approx(4.0)


def test_zero_damage_apply_kick_is_noop():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(0.0)
    assert camera_shake.get_energy() == 0.0


def test_energy_decays_monotonically():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    last = camera_shake.get_energy()
    for _ in range(60):
        camera_shake.update(1.0 / 60.0)
        cur = camera_shake.get_energy()
        assert cur <= last + 1e-9
        last = cur


def test_energy_decays_to_one_percent_in_half_a_second():
    """TAU=0.15s → exp(-0.5/0.15) ≈ 0.036 → crosses 1% near t ≈ 0.69s.
    Test bound: under 1% within [0.45s, 0.80s] to cover both float drift
    and the spec's '~0.5s' target."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    peak = camera_shake.get_energy()
    one_pct = 0.01 * peak
    t = 0.0
    dt = 1.0 / 240.0
    while camera_shake.get_energy() > one_pct and t < 1.0:
        camera_shake.update(dt)
        t += dt
    assert 0.45 <= t <= 0.80


def test_sustained_fire_clamped_to_max_energy():
    from engine.appc import camera_shake
    camera_shake.reset()
    for _ in range(100):
        camera_shake.apply_kick(1000.0)   # each kick clamps to 4.0
    assert camera_shake.get_energy() <= 8.0 + 1e-9   # MAX_ENERGY


# ── perturbation math ──────────────────────────────────────────────────────

def test_perturb_identity_when_energy_zero():
    from engine.appc import camera_shake
    camera_shake.reset()
    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)
    e2, t2, u2 = camera_shake.perturb(eye, target, up)
    assert e2 == pytest.approx(eye)
    assert t2 == pytest.approx(target)
    assert u2 == pytest.approx(up)


def test_perturb_keeps_up_vector_unchanged():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)
    _, _, u2 = camera_shake.perturb(eye, target, up)
    assert u2 == pytest.approx(up)


def test_perturb_peak_yaw_within_expected_range():
    """Peak yaw over a 30-tick window after a 100-damage kick is between
    1.0° and 2.0° (calibration target from spec §3.5)."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)

    peak_yaw_deg = 0.0
    for _ in range(30):
        e2, t2, _ = camera_shake.perturb(eye, target, up)
        # Yaw angle = angle of (target' - eye') projected onto XZ plane,
        # relative to the original view direction (-Z).
        vx = t2[0] - e2[0]
        vz = t2[2] - e2[2]
        yaw_rad = math.atan2(vx, -vz)   # 0 when looking down -Z.
        peak_yaw_deg = max(peak_yaw_deg, abs(math.degrees(yaw_rad)))
        camera_shake.update(1.0 / 60.0)
    assert 1.0 <= peak_yaw_deg <= 2.5


def test_perturb_is_deterministic_across_resets():
    """Two identical kick sequences after reset produce identical perturb outputs."""
    from engine.appc import camera_shake

    def _run():
        camera_shake.reset()
        camera_shake.apply_kick(50.0)
        outs = []
        for _ in range(30):
            outs.append(camera_shake.perturb((0.0, 0.0, 100.0),
                                              (0.0, 0.0, 0.0),
                                              (0.0, 1.0, 0.0)))
            camera_shake.update(1.0 / 60.0)
        return outs

    a = _run()
    b = _run()
    assert a == b


def test_yaw_crosses_zero_multiple_times_in_decay_window():
    """The decaying-noise design should oscillate, not drift. Yaw flips
    sign at least 4 times during the first 0.3s after a kick."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)

    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)

    prev_sign = 0
    crossings = 0
    for _ in range(18):    # 0.3s @ 60Hz
        e2, t2, _ = camera_shake.perturb(eye, target, up)
        vx = t2[0] - e2[0]
        sign = 1 if vx > 1e-6 else (-1 if vx < -1e-6 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            crossings += 1
        if sign != 0:
            prev_sign = sign
        camera_shake.update(1.0 / 60.0)
    assert crossings >= 4
```

### Step 6.2: Run tests — expect ModuleNotFoundError

```bash
uv run pytest tests/unit/test_camera_shake_decay.py -v
```

Expected: `ModuleNotFoundError: No module named 'engine.appc.camera_shake'`.

### Step 6.3: Create `engine/appc/camera_shake.py`

- [ ] Create the file:

```python
"""Camera shake — energy pool + decaying-noise perturbation.

Energy accumulates via apply_kick(damage), decays each tick via
update(dt), and produces a per-tick (yaw, pitch, lateral) perturbation
via perturb(eye, target, up). Up vector is left unchanged to keep the
horizon stable.

Waveform: sum of two incommensurate sinusoids per axis. Deterministic
(no RNG), reset()-able.

Tuning constants (spec §5.2):
    DAMAGE_PER_UNIT_ENERGY = 50.0     100 damage → 2.0 energy
    MAX_KICK_ENERGY        = 4.0      single-hit ceiling
    MAX_ENERGY             = 8.0      sustained-fire ceiling
    TAU                    = 0.15s    decay time constant
    ANGULAR_GAIN           = 0.013    rad per energy unit (~0.75°)
    LATERAL_GAIN           = 0.03     world units per energy unit
"""
import math


DAMAGE_PER_UNIT_ENERGY = 50.0
MAX_KICK_ENERGY        = 4.0
MAX_ENERGY             = 8.0
TAU                    = 0.15
ANGULAR_GAIN           = 0.013
LATERAL_GAIN           = 0.03


_energy: float = 0.0
_phase:  float = 0.0


def reset() -> None:
    """Zero the energy pool and the phase accumulator. Called by tests
    and by host_loop on view-mode transitions."""
    global _energy, _phase
    _energy = 0.0
    _phase = 0.0


def get_energy() -> float:
    """Introspection for tests."""
    return _energy


def apply_kick(damage: float) -> None:
    """Inject energy proportional to `damage`. Clamped per-hit to
    MAX_KICK_ENERGY; cumulative energy clamped to MAX_ENERGY."""
    global _energy
    if damage <= 0.0:
        return
    delta = min(damage / DAMAGE_PER_UNIT_ENERGY, MAX_KICK_ENERGY)
    _energy = min(_energy + delta, MAX_ENERGY)


def update(dt: float) -> None:
    """Exponential decay of energy; advance phase by dt."""
    global _energy, _phase
    if dt <= 0.0:
        return
    _energy *= math.exp(-dt / TAU)
    _phase += dt


def perturb(eye, target, up):
    """Apply yaw + pitch rotation to (target - eye) and a small lateral
    eye-translation along the camera-right axis. `up` is returned
    unchanged.

    Returns a fresh (eye, target, up) tuple-of-tuples.

    No-op when _energy == 0.0 (within float precision).
    """
    if _energy <= 1e-9:
        return eye, target, up

    amp = ANGULAR_GAIN * _energy
    yaw   = amp * (math.sin(_phase * 47.1)         + 0.5 * math.sin(_phase * 113.7 + 1.3))
    pitch = amp * (math.sin(_phase * 59.3 + 0.7)   + 0.5 * math.sin(_phase *  91.1 + 2.1))
    lateral_offset = LATERAL_GAIN * _energy * math.sin(_phase * 31.5)

    # Build basis: forward = normalize(target - eye), right = normalize(forward × up).
    fx = target[0] - eye[0]
    fy = target[1] - eye[1]
    fz = target[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    if flen < 1e-9:
        return eye, target, up
    fx, fy, fz = fx / flen, fy / flen, fz / flen
    # right = forward × up
    rx = fy * up[2] - fz * up[1]
    ry = fz * up[0] - fx * up[2]
    rz = fx * up[1] - fy * up[0]
    rlen = math.sqrt(rx*rx + ry*ry + rz*rz)
    if rlen < 1e-9:
        return eye, target, up
    rx, ry, rz = rx / rlen, ry / rlen, rz / rlen

    # Rotate forward vector by yaw around up, then by pitch around right.
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    # Yaw rotation around up axis.
    f2x = fx * cy + rx * sy
    f2y = fy * cy + ry * sy
    f2z = fz * cy + rz * sy
    # Pitch rotation around right axis (use the post-yaw right, which equals
    # right rotated by yaw around up; for small angles this is approximately
    # the same right vector, which is what we want).
    # Apply pitch: forward' = forward * cos(pitch) + up * sin(pitch)
    f3x = f2x * cp + up[0] * sp
    f3y = f2y * cp + up[1] * sp
    f3z = f2z * cp + up[2] * sp

    # Restore length (rotation is length-preserving in theory; numerical
    # cleanup so callers don't accumulate drift).
    new_target = (
        eye[0] + f3x * flen,
        eye[1] + f3y * flen,
        eye[2] + f3z * flen,
    )
    new_eye = (
        eye[0] + rx * lateral_offset,
        eye[1] + ry * lateral_offset,
        eye[2] + rz * lateral_offset,
    )
    # Shift target by same lateral offset so the look direction stays roughly fixed
    # relative to the lateral rumble (otherwise we'd swing wildly).
    new_target = (
        new_target[0] + rx * lateral_offset,
        new_target[1] + ry * lateral_offset,
        new_target[2] + rz * lateral_offset,
    )
    return new_eye, new_target, up
```

### Step 6.4: Run tests — expect PASS

```bash
uv run pytest tests/unit/test_camera_shake_decay.py -v
```

Expected: all green. If `test_perturb_peak_yaw_within_expected_range` fails because the actual peak is slightly outside `[1.0, 2.5]`, adjust `ANGULAR_GAIN` toward 0.013 ± 0.002 until the test passes; the constant is a tuning knob, not a derived value. Do NOT widen the test bound — that masks future regressions.

### Step 6.5: Commit

```bash
git add engine/appc/camera_shake.py tests/unit/test_camera_shake_decay.py
git commit -m "$(cat <<'EOF'
feat(camera_shake): energy pool + decaying-noise perturbation

Pure-Python module. apply_kick(damage) injects energy; update(dt) decays
exponentially with TAU=0.15s; perturb(eye, target, up) returns a yaw +
pitch rotated camera with a small lateral rumble. Up vector untouched
so the horizon stays stable.

Deterministic waveform (sum of two incommensurate sinusoids per axis,
no RNG), reset()-able for tests and view-mode transitions. Calibrated
so a 100-damage hit produces ~1.5° peak yaw, decays under 1% in ~0.5s.

Wired into host_loop in Task 9.

Project 4 of the combat damage pipeline roadmap, Task 6 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 7: `hit_feedback.dispatch` full fan-out

**Files:**
- Modify: `engine/appc/hit_feedback.py` (replace dispatch stub with real implementation)
- Create: `tests/unit/test_hit_feedback_dispatch.py`

Wires together Tasks 1–6. After this task, `apply_hit` produces the full mutually-exclusive feedback for every impact (renderer-side still operates on old descriptor shape until Task 8).

### Step 7.1: Write failing tests for dispatch fan-out

- [ ] Create `tests/unit/test_hit_feedback_dispatch.py`:

```python
"""dispatch — severity routing + mutual exclusivity + player gate.

Mocks host.shield_hit, hit_vfx.spawn, audio, camera shake; asserts each
fires for the right severity and only for the right severity.
"""
import pytest

from engine.appc import hit_feedback, hit_vfx, camera_shake
from engine.appc.hit_feedback import Severity
from engine.appc.math import TGPoint3


# ── fixtures ───────────────────────────────────────────────────────────────


class _HullMarker: pass


class _Sub:
    def __init__(self, name): self.name = name
    def __repr__(self): return f"_Sub({self.name!r})"


class _Ship:
    def __init__(self, hull):
        self._hull = hull
    def GetHull(self): return self._hull


class _FakeHost:
    def __init__(self):
        self.shield_hit_calls = []
    def shield_hit(self, *, instance_id, point, rgba, intensity):
        self.shield_hit_calls.append({
            "instance_id": instance_id, "point": point,
            "rgba": rgba, "intensity": intensity,
        })


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    hit_vfx._active.clear()
    camera_shake.reset()


@pytest.fixture
def spy(monkeypatch):
    """Capture audio.Play(position=) + camera_shake.apply_kick calls."""

    audio_calls = []
    kick_calls = []

    class _StubSnd:
        def Play(self, position=None):
            audio_calls.append({"position": position})
            return None

    class _StubMgr:
        def __init__(self):
            self.last_lookup = None
        def GetSound(self, name):
            self.last_lookup = name
            return _StubSnd()

    mgr = _StubMgr()
    import App
    monkeypatch.setattr(App, "g_kSoundManager", mgr, raising=False)

    # Patch GetRandomSound on both audio modules so dispatch's name
    # pick is deterministic.
    import LoadTacticalSounds, LoadDamageHitSounds
    monkeypatch.setattr(LoadTacticalSounds, "GetRandomSound",
                          lambda pool: pool[0])
    monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound",
                          lambda pool: pool[0])

    def _kick(damage):
        kick_calls.append({"damage": damage})
    monkeypatch.setattr(camera_shake, "apply_kick", _kick)

    return {"audio": audio_calls, "kicks": kick_calls,
            "mgr": mgr}


# ── SHIELD ──────────────────────────────────────────────────────────────────

def test_shield_severity_fires_shield_hit_not_hit_vfx(spy):
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}
    point = TGPoint3(1.0, 2.0, 3.0)

    hit_feedback.dispatch(
        ship=ship, source=None, point=point, normal=None,
        damage=30.0, subsystem=hull,
        absorbed_shields=30.0, absorbed_subsystem=0.0, absorbed_hull=0.0,
        sub_transition=None,
        host=host, ship_instances=ship_instances,
    )

    assert len(host.shield_hit_calls) == 1
    call = host.shield_hit_calls[0]
    assert call["instance_id"] == 42
    assert call["point"] == (1.0, 2.0, 3.0)
    # No hit_vfx descriptor pushed.
    assert hit_vfx.snapshot() == []
    # Audio: Shield Hit name picked.
    assert spy["mgr"].last_lookup == "Shield Hit"
    assert spy["audio"][0]["position"] == (1.0, 2.0, 3.0)


# ── HULL ────────────────────────────────────────────────────────────────────

def test_hull_severity_fires_hit_vfx_not_shield_hit(spy):
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}
    point = TGPoint3(0.0, 0.0, 0.0)
    normal = TGPoint3(0.0, 0.0, -1.0)

    hit_feedback.dispatch(
        ship=ship, source=None, point=point, normal=normal,
        damage=30.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=30.0,
        sub_transition=None,
        host=host, ship_instances=ship_instances,
    )

    assert host.shield_hit_calls == []
    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    assert snap[0]["severity"] == int(Severity.HULL)
    assert snap[0]["normal"].z == -1.0
    # Audio: HULL pool — first name (per stubbed GetRandomSound).
    import LoadTacticalSounds
    assert spy["mgr"].last_lookup == LoadTacticalSounds.g_lsWeaponExplosions[0]


# ── CRITICAL ───────────────────────────────────────────────────────────────

def test_critical_severity_fires_hit_vfx_critical(spy):
    hull = _HullMarker()
    sensors = _Sub("sensors")
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}
    point = TGPoint3(0.0, 0.0, 0.0)
    normal = TGPoint3(1.0, 0.0, 0.0)

    hit_feedback.dispatch(
        ship=ship, source=None, point=point, normal=normal,
        damage=80.0, subsystem=sensors,
        absorbed_shields=0.0, absorbed_subsystem=80.0, absorbed_hull=0.0,
        sub_transition="disabled",
        host=host, ship_instances=ship_instances,
    )

    assert host.shield_hit_calls == []
    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    assert snap[0]["severity"] == int(Severity.CRITICAL)
    # Audio: CRITICAL pool.
    import LoadDamageHitSounds
    assert spy["mgr"].last_lookup == LoadDamageHitSounds.g_lsSubsystemCriticals[0]


# ── Player gate ────────────────────────────────────────────────────────────

def test_camera_shake_fires_when_ship_is_player(spy, monkeypatch):
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}

    # Make Game_GetCurrentGame().GetPlayer() return our ship.
    import App
    class _Game:
        def GetPlayer(self): return ship
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)

    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=50.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=50.0,
        sub_transition=None,
        host=host, ship_instances=ship_instances,
    )

    assert len(spy["kicks"]) == 1
    assert spy["kicks"][0]["damage"] == pytest.approx(50.0)


def test_camera_shake_does_not_fire_for_non_player_target(spy, monkeypatch):
    hull = _HullMarker()
    ship = _Ship(hull)
    other_player = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}

    import App
    class _Game:
        def GetPlayer(self): return other_player
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)

    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=50.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=50.0,
        sub_transition=None,
        host=host, ship_instances=ship_instances,
    )

    assert spy["kicks"] == []


# ── Headless robustness ───────────────────────────────────────────────────

def test_dispatch_with_none_host_does_not_call_shield_hit(spy):
    """host=None means no renderer; dispatch must not raise."""
    hull = _HullMarker()
    ship = _Ship(hull)
    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=30.0, subsystem=hull,
        absorbed_shields=30.0, absorbed_subsystem=0.0, absorbed_hull=0.0,
        sub_transition=None,
        host=None, ship_instances=None,
    )
    # No exception; SHIELD severity tried to fire shield_hit but no host
    # to call it on. hit_vfx still empty (SHIELD never spawns hit_vfx).
    assert hit_vfx.snapshot() == []


def test_dispatch_with_no_sound_manager_is_silent(spy, monkeypatch):
    """App.g_kSoundManager = None — audio path falls through silently."""
    import App
    monkeypatch.setattr(App, "g_kSoundManager", None, raising=False)

    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=30.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=30.0,
        sub_transition=None,
        host=host, ship_instances={ship: 42},
    )
    # Audio silently dropped — no exception.
    # hit_vfx still pushed.
    assert len(hit_vfx.snapshot()) == 1
```

### Step 7.2: Run tests — expect failure (dispatch is a stub)

```bash
uv run pytest tests/unit/test_hit_feedback_dispatch.py -v
```

Expected: assertions fail because dispatch is the no-op stub from Task 1.

### Step 7.3: Replace stub with real `dispatch` in `engine/appc/hit_feedback.py`

- [ ] Edit `engine/appc/hit_feedback.py`. Replace the `def dispatch(*args, **kwargs)` stub with:

```python
def dispatch(*, ship, source, point, normal, damage, subsystem,
             absorbed_shields: float, absorbed_subsystem: float,
             absorbed_hull: float, sub_transition,
             host=None, ship_instances=None) -> None:
    """Per-impact fan-out: VFX + audio + camera shake.

    Severity is computed via classify(...). Exactly one visual fires per
    impact (shield_hit for SHIELD, hit_vfx.spawn for HULL/CRITICAL).
    Audio fires for every severity. Camera shake fires only when
    ship == Game_GetCurrentGame().GetPlayer().

    Headless-safe: host=None silently skips shield_hit;
    App.g_kSoundManager=None silently skips audio.
    """
    from engine.appc import hit_vfx, camera_shake

    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    severity = classify(
        absorbed_shields=absorbed_shields,
        absorbed_subsystem=absorbed_subsystem,
        absorbed_hull=absorbed_hull,
        sub_transition=sub_transition,
        subsystem=subsystem,
        hull=hull,
    )

    # 1. Visual — mutually exclusive.
    if severity == Severity.SHIELD:
        if host is not None and ship_instances is not None \
                and hasattr(host, "shield_hit"):
            iid = ship_instances.get(ship)
            if iid is not None:
                host.shield_hit(
                    instance_id=iid,
                    point=(point.x, point.y, point.z),
                    rgba=(0.0, 0.0, 0.0, 0.0),
                    intensity=1.0,
                )
    else:
        # HULL or CRITICAL — hit_vfx.spawn handles both, filtered by severity.
        hit_vfx.spawn(point, normal=normal, severity=severity)

    # 2. Audio.
    _play_audio(severity, point)

    # 3. Camera shake — player only.
    try:
        import App
        game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
    except Exception:
        player = None
    if player is not None and ship is player:
        camera_shake.apply_kick(float(damage))


def _play_audio(severity: Severity, point) -> None:
    """Look up the tier's sound name and play positionally. Silent on
    missing sound manager or missing sound name."""
    import App
    mgr = getattr(App, "g_kSoundManager", None)
    if mgr is None:
        return

    if severity == Severity.SHIELD:
        name = "Shield Hit"
    elif severity == Severity.HULL:
        try:
            import LoadTacticalSounds
            name = LoadTacticalSounds.GetRandomSound(
                LoadTacticalSounds.g_lsWeaponExplosions)
        except Exception:
            return
    else:  # CRITICAL
        try:
            import LoadDamageHitSounds
            picker = LoadDamageHitSounds.GetRandomSound
            if picker is None:
                # LoadSounds() hasn't run yet — fall back to first entry.
                name = LoadDamageHitSounds.g_lsSubsystemCriticals[0]
            else:
                name = picker(LoadDamageHitSounds.g_lsSubsystemCriticals)
        except Exception:
            return

    snd = mgr.GetSound(name)
    if snd is None:
        return
    snd.Play(position=(point.x, point.y, point.z))
```

### Step 7.4: Run tests — expect PASS

```bash
uv run pytest tests/unit/test_hit_feedback_dispatch.py tests/unit/test_hit_feedback_classify.py -v
```

Expected: all green.

### Step 7.5: Confirm wider Python suite still green

```bash
uv run pytest tests/unit/test_apply_hit_routing.py \
              tests/unit/test_combat_hit_resolution.py \
              tests/unit/test_hit_vfx_lifecycle.py \
              tests/unit/test_camera_shake_decay.py \
              tests/unit/test_hit_feedback_dispatch.py \
              tests/unit/test_hit_feedback_classify.py \
              tests/unit/test_apply_hit_state_diff.py \
              tests/unit/test_load_damage_hit_sounds.py \
              tests/unit/test_shield_face_from_hit_point.py \
              tests/integration/test_phaser_damage_applied_through_apply_hit.py -v
```

Expected: all green.

### Step 7.6: Commit

```bash
git add engine/appc/hit_feedback.py tests/unit/test_hit_feedback_dispatch.py
git commit -m "$(cat <<'EOF'
feat(hit_feedback): real dispatch — VFX + audio + camera shake fan-out

dispatch() classifies severity from per-stage absorbed amounts +
subsystem transition, then fires exactly one visual per impact:
host.shield_hit (SHIELD) or hit_vfx.spawn (HULL/CRITICAL). Audio fires
via App.g_kSoundManager.GetSound(name).Play(position=...). Camera shake
fires only when ship == Game_GetCurrentGame().GetPlayer().

Headless-safe: host=None skips shield_hit; g_kSoundManager=None skips
audio; missing GetPlayer skips camera shake.

Project 4 of the combat damage pipeline roadmap, Task 7 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 8: Renderer C++ extension (descriptor, binding, tier constants, sparks, shader)

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h` (`HitVfxDescriptor`)
- Modify: `native/src/renderer/hit_vfx_pass.cc` (per-tier constants, tint, sparks)
- Modify: `native/src/renderer/shaders/hit_vfx.frag` (`u_tint` uniform)
- Modify: `native/src/host/host_bindings.cc` (`set_hit_vfx` reads new keys)
- Modify: `engine/host_loop.py` (`_build_hit_vfx_render_data` emits `normal` + `severity`)

This task is lockstep: the Python side and the C++ side must change together because `set_hit_vfx` will fail-cast if the dict is missing the new keys. **Shader edits require re-running `cmake -B build -S .`**, not just `cmake --build`.

### Step 8.1: Update `_build_hit_vfx_render_data` to emit `normal` + `severity`

- [ ] Edit `engine/host_loop.py` lines 386-395:

```python
def _build_hit_vfx_render_data():
    from engine.appc import hit_vfx
    out = []
    for entry in hit_vfx.snapshot():
        pos = entry["position"]
        n = entry["normal"]
        out.append({
            "position": (pos.x, pos.y, pos.z),
            "normal":   (n.x, n.y, n.z) if n is not None else (0.0, 0.0, 0.0),
            "severity": entry["severity"],
            "age":      entry["age"],
        })
    return out
```

### Step 8.2: Find `HitVfxDescriptor` in the C++ side

```bash
grep -rn "struct HitVfxDescriptor" native/src/
```

Expected: a hit in `native/src/renderer/include/renderer/frame.h` (or similar).

### Step 8.3: Extend `HitVfxDescriptor`

- [ ] Edit the descriptor struct (typically in `native/src/renderer/include/renderer/frame.h`):

```cpp
struct HitVfxDescriptor {
    glm::vec3 world_pos;
    glm::vec3 surface_normal{0.0f};   // NEW: (0,0,0) sentinel = no normal
    float     age;
    int       severity{1};            // NEW: 1=HULL, 2=CRITICAL; SHIELD never reaches here
};
```

### Step 8.4: Extend `set_hit_vfx` binding in `host_bindings.cc`

- [ ] In `native/src/host/host_bindings.cc` at lines 575-588, replace:

```cpp
    m.def("set_hit_vfx",
          [](const std::vector<py::dict>& descs) {
              g_hit_vfx.clear();
              g_hit_vfx.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::HitVfxDescriptor v;
                  auto pos = d["position"].cast<std::tuple<float, float, float>>();
                  v.world_pos = {std::get<0>(pos), std::get<1>(pos), std::get<2>(pos)};
                  v.age = d["age"].cast<float>();
                  g_hit_vfx.push_back(std::move(v));
              }
          },
          py::arg("vfx"),
          "Set the active hit-VFX list (position + age), applied each frame().");
```

with:

```cpp
    m.def("set_hit_vfx",
          [](const std::vector<py::dict>& descs) {
              g_hit_vfx.clear();
              g_hit_vfx.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::HitVfxDescriptor v;
                  auto pos = d["position"].cast<std::tuple<float, float, float>>();
                  v.world_pos = {std::get<0>(pos), std::get<1>(pos), std::get<2>(pos)};
                  auto n = d["normal"].cast<std::tuple<float, float, float>>();
                  v.surface_normal = {std::get<0>(n), std::get<1>(n), std::get<2>(n)};
                  v.severity = d["severity"].cast<int>();
                  v.age = d["age"].cast<float>();
                  g_hit_vfx.push_back(std::move(v));
              }
          },
          py::arg("vfx"),
          "Set the active hit-VFX list (position + normal + severity + age), "
          "applied each frame().");
```

### Step 8.5: Rewrite `hit_vfx_pass.cc` with per-tier constants + sparks

- [ ] Edit `native/src/renderer/hit_vfx_pass.cc`. Replace the contents of the anonymous namespace `kPeakSize` / `kSpawnDur` / `kFadeDur` constants with a per-tier table, and rewrite `render()` to dispatch per descriptor. Full new file body:

```cpp
// native/src/renderer/hit_vfx_pass.cc
#include "renderer/hit_vfx_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/type_ptr.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>

namespace renderer {

namespace {

// Per-tier visual constants (spec §6.1).
struct TierConfig {
    float peak_size;     // world-units half-size at peak expansion
    float spawn_dur;     // seconds, size eases 0→peak
    float fade_dur;      // seconds, alpha fades 1→0
    float total_life;    // seconds, descriptor pruned at this age (renderer side)
    glm::vec4 tint;
};

// Indexed by severity: 0=SHIELD (unused — never reaches renderer), 1=HULL, 2=CRITICAL.
constexpr TierConfig kTiers[3] = {
    {0.0f, 0.0f, 0.0f, 0.0f, {1.0f, 1.0f, 1.0f, 1.0f}},   // SHIELD — never used.
    {3.0f, 0.08f, 0.25f, 0.33f, {1.00f, 0.55f, 0.20f, 1.0f}},  // HULL
    {7.0f, 0.10f, 0.55f, 0.65f, {1.00f, 0.92f, 0.80f, 1.0f}},  // CRITICAL
};

constexpr int   kSparkCount     = 6;
constexpr float kSparkSpeed     = 4.0f;    // wu/s
constexpr float kSparkSizeMult  = 0.6f;    // multiplier on tier peak_size
constexpr float kSparkConeDeg   = 30.0f;   // half-angle of spark cone around the normal

constexpr const char* kImpactTexturePath = "data/Textures/Tactical/TorpedoFlares.tga";

constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,
    +1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, +1.0f,
};

// Deterministic 2-float hash from (world_pos, i). xorshift on float bit
// reinterprets — cheap, no allocation, repeatable for a given descriptor.
inline glm::vec2 hash3(const glm::vec3& p, int i) {
    auto bits = [](float f) -> std::uint32_t {
        std::uint32_t u;
        std::memcpy(&u, &f, sizeof(u));
        return u;
    };
    std::uint32_t h = bits(p.x) ^ (bits(p.y) * 0x9E3779B9u)
                    ^ (bits(p.z) * 0x85EBCA6Bu) ^ (std::uint32_t(i) * 0xC2B2AE35u);
    h ^= h << 13; h ^= h >> 17; h ^= h << 5;
    std::uint32_t h2 = h * 0x1B873593u;
    h2 ^= h2 << 13; h2 ^= h2 >> 17; h2 ^= h2 << 5;
    // Map to [-1, 1] floats.
    auto to_unit = [](std::uint32_t x) {
        return (float(x & 0xFFFFFF) / float(0xFFFFFF)) * 2.0f - 1.0f;
    };
    return glm::vec2{to_unit(h), to_unit(h2)};
}

// Rotate `base` toward `+kSparkConeDeg` along two perpendicular axes,
// jittered by `jitter` ∈ [-1, 1]^2.
glm::vec3 rotate_jitter(const glm::vec3& base, const glm::vec3& cam_up,
                          const glm::vec3& cam_right, glm::vec2 jitter) {
    const float ang_h = jitter.x * (kSparkConeDeg * 3.14159265f / 180.0f);
    const float ang_v = jitter.y * (kSparkConeDeg * 3.14159265f / 180.0f);
    glm::vec3 v = base + cam_right * std::sin(ang_h) + cam_up * std::sin(ang_v);
    float len = glm::length(v);
    if (len > 1e-6f) v /= len;
    return v;
}

}  // namespace

HitVfxPass::HitVfxPass() = default;

HitVfxPass::~HitVfxPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void HitVfxPass::ensure_quad_mesh() {
    if (quad_vao_ != 0) return;
    glGenVertexArrays(1, &quad_vao_);
    glBindVertexArray(quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuadCorners), kQuadCorners,
                 GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glBindVertexArray(0);
}

void HitVfxPass::ensure_texture() {
    if (texture_) return;
    std::ifstream in(kImpactTexturePath, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[hit_vfx_pass] failed to open '%s'\n",
                     kImpactTexturePath);
        texture_ = std::make_unique<assets::Texture>();
        return;
    }
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        texture_ = std::make_unique<assets::Texture>(std::move(tex));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[hit_vfx_pass] failed to decode '%s': %s\n",
                     kImpactTexturePath, e.what());
        texture_ = std::make_unique<assets::Texture>();
    }
}

void HitVfxPass::render(const std::vector<HitVfxDescriptor>& vfx,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline) {
    if (vfx.empty()) return;
    ensure_quad_mesh();
    ensure_texture();
    if (!texture_ || texture_->id() == 0) return;

    auto& shader = pipeline.hit_vfx_shader();
    shader.use();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    const glm::mat4 view = camera.view_matrix();
    const glm::vec3 cam_right = glm::vec3(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up    = glm::vec3(view[0][1], view[1][1], view[2][1]);

    shader.set_mat4("u_view_proj",    vp);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_texture",      0);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, texture_->id());

    for (const auto& v : vfx) {
        // Clamp severity to [1, 2]; index 0 (SHIELD) should never reach
        // the renderer but guard regardless.
        const int sev = std::max(1, std::min(2, v.severity));
        const TierConfig& tier = kTiers[sev];

        const float age = std::max(0.0f, v.age);
        if (age >= tier.total_life) continue;

        // ── Main billboard ──
        const float size_t  = std::min(1.0f, age / tier.spawn_dur);
        const float fade_t  = std::max(0.0f, std::min(1.0f,
                                  (age - tier.spawn_dur) / tier.fade_dur));
        const float size    = tier.peak_size * size_t;
        const float alpha   = 1.0f - fade_t;

        shader.set_vec4 ("u_tint",           tier.tint);
        shader.set_vec3 ("u_world_position", v.world_pos);
        shader.set_float("u_size",           size);
        shader.set_float("u_alpha",          alpha);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // ── CRITICAL spark burst ──
        if (sev == 2) {
            const bool has_normal = glm::length(v.surface_normal) > 1e-3f;
            const glm::vec3 base = has_normal ? glm::normalize(v.surface_normal)
                                              : cam_right;
            for (int i = 0; i < kSparkCount; ++i) {
                const glm::vec2 jitter = hash3(v.world_pos, i);
                const glm::vec3 dir = rotate_jitter(base, cam_up, cam_right, jitter);
                const glm::vec3 pos = v.world_pos + dir * (kSparkSpeed * age);
                const float life_t = age / tier.total_life;
                const float spark_size = kSparkSizeMult * tier.peak_size * (1.0f - life_t);
                const float spark_alpha = 1.0f - life_t;
                shader.set_vec3 ("u_world_position", pos);
                shader.set_float("u_size",           spark_size);
                shader.set_float("u_alpha",          spark_alpha);
                glDrawArrays(GL_TRIANGLES, 0, 6);
            }
        }
    }

    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
```

### Step 8.6: Add `u_tint` to the fragment shader

- [ ] Find the fragment shader:

```bash
ls native/src/renderer/shaders/hit_vfx.frag native/assets/shaders/hit_vfx.frag 2>/dev/null
```

Edit whichever exists. Add `uniform vec4 u_tint;` to the uniform block and multiply the output:

```glsl
#version 330 core

in vec2 v_uv;
out vec4 out_color;

uniform sampler2D u_texture;
uniform float u_alpha;
uniform vec4 u_tint;

void main() {
    vec4 tex_sample = texture(u_texture, v_uv);
    out_color = tex_sample * u_tint * vec4(1.0, 1.0, 1.0, u_alpha);
}
```

(Adapt the existing shader's I/O variable names; only the `uniform vec4 u_tint;` declaration and the multiplication in `out_color` are new. Do not blindly overwrite — read the existing shader first.)

### Step 8.7: Reconfigure + build

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: clean build. If you see "shader has no uniform u_tint" warnings, the shader bind cache may need clearing — re-run the cmake configure step. Per CLAUDE.md memory: **shader changes require the configure step, not just the build step.**

### Step 8.8: Verify the binary loads and runs without crashing (smoke)

```bash
./build/dauntless &
sleep 4
kill %1 2>/dev/null || true
```

If it crashes immediately with a `set_hit_vfx` cast error, the descriptor schema and the binding are out of sync. Re-read Step 8.1 + 8.4.

### Step 8.9: Run the Python suite — must still be green

```bash
uv run pytest tests/unit/test_hit_vfx_lifecycle.py \
              tests/unit/test_hit_feedback_dispatch.py \
              tests/unit/test_apply_hit_routing.py \
              tests/unit/test_combat_hit_resolution.py \
              tests/integration/test_phaser_damage_applied_through_apply_hit.py -v
```

Expected: all green. The Python tests don't touch the renderer; they exercise `_build_hit_vfx_render_data` only via the format of the dict it emits. The new keys are present per Step 8.1.

### Step 8.10: Commit

```bash
git add native/src/renderer/include/renderer/frame.h \
        native/src/renderer/hit_vfx_pass.cc \
        native/src/renderer/shaders/hit_vfx.frag \
        native/src/host/host_bindings.cc \
        engine/host_loop.py
git commit -m "$(cat <<'EOF'
feat(renderer): per-tier hit VFX with surface-normal spark burst

HitVfxDescriptor gains surface_normal (vec3) + severity (int).
hit_vfx_pass.cc:
  - per-tier kPeakSize / kSpawnDur / kFadeDur / kTotalLife / tint table
    (HULL = orange-amber 3wu / 0.33s; CRITICAL = white-hot 7wu / 0.65s)
  - CRITICAL severity emits 6 sparks ejected along the surface normal
    over the descriptor lifetime, deterministic per-descriptor jitter
    via xorshift on float bit reinterprets
  - sentinel-normal fallback (no mesh trace) uses cam_right as the
    spark spread basis
hit_vfx.frag gains uniform vec4 u_tint multiplied through the texture
sample. set_hit_vfx binding reads the new descriptor keys.
_build_hit_vfx_render_data emits 'normal' + 'severity' fields.

Project 4 of the combat damage pipeline roadmap, Task 8 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 9: `host_loop` wiring for camera shake + view-mode reset

**Files:**
- Modify: `engine/host_loop.py` (camera shake update + perturb + reset)

### Step 9.1: Wire `camera_shake.update(dt)` next to `hit_vfx.update_ages(dt)`

- [ ] In `engine/host_loop.py`, find the `_advance_combat` function. At [line 251](engine/host_loop.py#L251) (after the torpedo loop, where `hit_vfx.update_ages(dt)` is called), add the camera shake update:

```python
    hit_vfx.update_ages(dt)
    from engine.appc import camera_shake
    camera_shake.update(dt)
```

### Step 9.2: Wire `camera_shake.perturb(...)` post-`_compute_camera`

- [ ] At [line 2425](engine/host_loop.py#L2425) (after `eye, target, up_vec = _compute_camera(...)`), insert the perturb call. The current code is:

```python
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, cam_control,
                    player=player, dt=TICK_DT)
                if view_mode.is_bridge:
                    mouse_dx, mouse_dy = _h.consume_mouse_delta() if _h else (0.0, 0.0)
                    ...
```

Change to:

```python
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, cam_control,
                    player=player, dt=TICK_DT)
                # Camera shake — perturbs both exterior and bridge views uniformly.
                from engine.appc import camera_shake
                eye, target, up_vec = camera_shake.perturb(eye, target, up_vec)
                if view_mode.is_bridge:
                    mouse_dx, mouse_dy = _h.consume_mouse_delta() if _h else (0.0, 0.0)
                    ...
```

Note: the bridge view passes `b_eye, b_target, b_up` (a separately-computed bridge camera) into `r.set_bridge_camera`, **not** the perturbed `eye/target/up`. So the bridge view will *not* receive camera shake on its primary camera through this path.

Re-check this against the spec — §5.5 says "both exterior and bridge views get the same perturbation". Two options:

**Option A:** Perturb `b_eye, b_target, b_up` too, just before `r.set_bridge_camera`. This is the spec-correct path.

**Option B:** Accept that the bridge first-person camera doesn't shake. Spec gets amended.

Going with Option A. After the existing `b_eye, b_target, b_up = bridge_camera.compute_camera()` line at [line 2434](engine/host_loop.py#L2434), insert:

```python
                    b_eye, b_target, b_up = bridge_camera.compute_camera()
                    b_eye, b_target, b_up = camera_shake.perturb(b_eye, b_target, b_up)
                    r.set_bridge_camera(
                        eye=b_eye, target=b_target, up=b_up,
                        ...
                    )
```

(The `camera_shake` import is already in scope from a few lines above; if Python's scoping rule for the local import bothers you, move the `from engine.appc import camera_shake` import to the top of the file with the other `engine.appc` imports.)

### Step 9.3: Wire `camera_shake.reset()` on view-mode transition

- [ ] Inspect `_apply_view_mode_side_effects` ([line 1127](engine/host_loop.py#L1127)). It already detects view-mode transitions via `_last_synced_is_bridge`. Add `camera_shake.reset()` inside the transition branch.

Read the function body to see the transition trigger, then add:

```python
def _apply_view_mode_side_effects(view_mode, h) -> None:
    ...
    target = view_mode.is_bridge
    last = getattr(view_mode, "_last_synced_is_bridge", None)
    if target != last:
        # ... existing transition handling ...
        from engine.appc import camera_shake
        camera_shake.reset()
    view_mode._last_synced_is_bridge = target
    ...
```

The exact insertion point depends on the function's body — read [lines 1127-1150](engine/host_loop.py#L1127-L1150) and place the `reset()` call alongside `cam_control.reset_smoothing()` if that's there, otherwise inside the `if target != last:` branch.

### Step 9.4: Manual smoke — launch the binary

```bash
cmake --build build -j
./build/dauntless &
HOSTPID=$!
sleep 8
kill $HOSTPID 2>/dev/null || true
```

Expected: no crash. The binary should run with the current default mission. Camera shake is a no-op until something fires on the player, so this smoke is purely "does the wiring not crash at startup".

### Step 9.5: Run the Python suite — must still be green

```bash
uv run pytest tests/unit/test_camera_shake_decay.py \
              tests/unit/test_hit_feedback_dispatch.py \
              tests/integration/test_phaser_damage_applied_through_apply_hit.py -v
```

Expected: all green.

### Step 9.6: Commit

```bash
git add engine/host_loop.py
git commit -m "$(cat <<'EOF'
feat(host_loop): wire camera_shake update + perturb + view-mode reset

camera_shake.update(dt) runs once per tick alongside
hit_vfx.update_ages(dt). camera_shake.perturb(eye, target, up) is
applied to the result of _compute_camera before being handed to
r.set_camera AND to the bridge first-person camera before
r.set_bridge_camera — both views get the same perturbation per spec
§5.5. camera_shake.reset() fires inside _apply_view_mode_side_effects
on view-mode transitions to prevent stale energy leaking across
exterior↔bridge swaps.

Project 4 of the combat damage pipeline roadmap, Task 9 of the
damage-vfx-bridge-feedback implementation plan.
EOF
)"
```

---

## Task 10: Integration test + cross-cutting verification + visual smoke

**Files:**
- Create: `tests/integration/test_damage_severity_sequence.py`
- Verify: no leftover `shield_hit` / `hit_vfx.spawn` calls outside `hit_feedback.dispatch`
- Manual: visual smoke procedure per spec §7.6

### Step 10.1: Write integration test for the severity transition sequence

- [ ] Create `tests/integration/test_damage_severity_sequence.py`:

```python
"""Integration test for the full damage pipeline:
shields → hull bleed → subsystem flip → severity stream
SHIELD → HULL → CRITICAL → HULL.

Mocks the renderer and audio; asserts mutual-exclusivity (no tick has
both a shield_hit call and a hit_vfx descriptor pushed for the same
impact) and asserts the severity sequence.
"""
import pytest

from engine.appc import combat, hit_feedback, hit_vfx, camera_shake
from engine.appc.hit_feedback import Severity
from engine.appc.math import TGPoint3


# ── fixtures ───────────────────────────────────────────────────────────────


class _HullMarker:
    def GetCondition(self): return 1000.0


class _Shield:
    """6-face shield with FRONT (index 0) charged to `front_charge`.
    ApplyDamage on FRONT subtracts up to front_charge, returns overflow."""
    def __init__(self, front_charge):
        self._charges = [0.0] * 6
        self._charges[0] = float(front_charge)
    def ApplyDamage(self, face, dmg):
        absorb = min(self._charges[face], dmg)
        self._charges[face] -= absorb
        return dmg - absorb


class _Sensors:
    """Subsystem with MaxCondition=100, DisabledPercentage=0.5. IsDisabled
    flips True once condition <= 50; IsDestroyed flips True once
    condition <= 0."""
    def __init__(self):
        self.condition = 100.0
        self._max = 100.0
    def GetCondition(self): return self.condition
    def GetMaxCondition(self): return self._max
    def IsDamaged(self): return self.condition < self._max
    def IsDisabled(self): return self.condition <= 0.5 * self._max
    def IsDestroyed(self): return self.condition <= 0.0
    def GetPosition(self):
        return TGPoint3(0.0, 0.0, 0.0)
    def GetRadius(self):
        return 1000.0   # huge so pick_target_subsystem always picks it


class _Ship:
    def __init__(self, hull, shields, sensors):
        self._hull = hull
        self._shields = shields
        self._sensors = sensors
        self._loc = TGPoint3(0.0, 0.0, 0.0)
    def GetHull(self): return self._hull
    def GetShields(self): return self._shields
    def GetWorldLocation(self): return self._loc
    def GetSubsystems(self):
        return [self._sensors]
    def DamageSystem(self, sub, amount):
        if isinstance(sub, _Sensors):
            sub.condition = max(0.0, sub.condition - float(amount))
        # Hull DamageSystem is a no-op for this test (we only care about
        # the routing, not the hull condition).


class _FakeHost:
    def __init__(self):
        self.shield_hit_calls = []
    def shield_hit(self, *, instance_id, point, rgba, intensity):
        self.shield_hit_calls.append({"point": point, "instance_id": instance_id})


@pytest.fixture
def setup(monkeypatch):
    """Build ship + host + capture audio + camera-shake calls."""
    hit_vfx._active.clear()
    camera_shake.reset()

    hull = _HullMarker()
    shields = _Shield(front_charge=100.0)
    sensors = _Sensors()
    ship = _Ship(hull, shields, sensors)
    host = _FakeHost()
    ship_instances = {ship: 42}

    audio = []
    class _StubSnd:
        def Play(self, position=None):
            audio.append({"position": position})
            return None
    class _StubMgr:
        def GetSound(self, _name):
            return _StubSnd()
    import App
    monkeypatch.setattr(App, "g_kSoundManager", _StubMgr(), raising=False)

    # Player gate: ship IS the player.
    class _Game:
        def GetPlayer(self): return ship
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)

    import LoadTacticalSounds, LoadDamageHitSounds
    monkeypatch.setattr(LoadTacticalSounds, "GetRandomSound",
                          lambda pool: pool[0])
    monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound",
                          lambda pool: pool[0])

    return {"ship": ship, "host": host, "ship_instances": ship_instances,
            "sensors": sensors, "shields": shields, "audio": audio}


# ── test ───────────────────────────────────────────────────────────────────


def _severity_for_last_push(host_before_count, host, snapshot_before, snapshot_after):
    """Decide what severity this tick produced by looking at how the
    captured state changed."""
    new_shield_hit = len(host.shield_hit_calls) > host_before_count
    new_descriptor = len(snapshot_after) > len(snapshot_before)
    # Mutual exclusivity invariant — exactly one fires per impact.
    assert not (new_shield_hit and new_descriptor), \
        "shield_hit and hit_vfx fired together — mutual exclusivity broken"
    if new_shield_hit:
        return Severity.SHIELD
    if new_descriptor:
        return Severity(snapshot_after[-1]["severity"])
    raise AssertionError("neither shield_hit nor hit_vfx fired")


def test_severity_sequence_shield_then_hull_then_critical(setup):
    """10 ticks of 30 damage each, fire on FRONT face of a ship with:
    - FRONT shield charge 100
    - sensors MaxCondition 100, DisabledPercentage 0.5

    Expected stream (each tick = one apply_hit call):
       1: SHIELD  (shield 70 / sensors 100)
       2: SHIELD  (shield 40 / sensors 100)
       3: SHIELD  (shield 10 / sensors 100)
       4: HULL    (shield 0, sensors 80; no transition)
       5: CRITICAL (sensors 50, IsDisabled flips True)
       6: HULL    (sensors 20)
       7: CRITICAL (sensors 0, IsDestroyed flips True)
       8-10: HULL (sensors stays destroyed, no further transition)
    """
    ship = setup["ship"]
    host = setup["host"]
    ship_instances = setup["ship_instances"]

    expected = [
        Severity.SHIELD, Severity.SHIELD, Severity.SHIELD,
        Severity.HULL,
        Severity.CRITICAL,
        Severity.HULL,
        Severity.CRITICAL,
        Severity.HULL, Severity.HULL, Severity.HULL,
    ]
    actual = []

    point = TGPoint3(0.0, 1.0, 0.0)   # FRONT face — body +Y.
    for tick in range(10):
        host_before = len(host.shield_hit_calls)
        snap_before = hit_vfx.snapshot()
        combat.apply_hit(ship, damage=30.0, hit_point=point,
                          source=None, subsystem=setup["sensors"],
                          normal=TGPoint3(0.0, 1.0, 0.0),
                          host=host, ship_instances=ship_instances)
        snap_after = hit_vfx.snapshot()
        actual.append(_severity_for_last_push(host_before, host,
                                                snap_before, snap_after))

    assert actual == expected, f"got {actual}, expected {expected}"


def test_camera_shake_fires_only_when_target_is_player(setup, monkeypatch):
    ship = setup["ship"]
    host = setup["host"]
    ship_instances = setup["ship_instances"]

    # Re-confirm ship IS player → energy should accumulate.
    camera_shake.reset()
    for _ in range(5):
        combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0,1,0),
                          source=None, subsystem=setup["sensors"],
                          normal=None,
                          host=host, ship_instances=ship_instances)
    energy_when_player = camera_shake.get_energy()
    assert energy_when_player > 0.0

    # Now point player to someone else.
    other = _Ship(setup["ship"]._hull, setup["shields"], setup["sensors"])
    import App
    class _Game2:
        def GetPlayer(self): return other
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game2(), raising=False)

    camera_shake.reset()
    for _ in range(5):
        combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0,1,0),
                          source=None, subsystem=setup["sensors"],
                          normal=None,
                          host=host, ship_instances=ship_instances)
    assert camera_shake.get_energy() == 0.0
```

### Step 10.2: Run the integration test

```bash
uv run pytest tests/integration/test_damage_severity_sequence.py -v
```

Expected: both tests pass. If the severity sequence is off by one (e.g. CRITICAL appears at tick 4 instead of 5), inspect the `_Sensors.IsDisabled` flipping logic and confirm the shield only drains to zero exactly when expected.

### Step 10.3: Cross-cutting grep audit for stale `shield_hit` / `hit_vfx.spawn` calls

```bash
grep -rn 'shield_hit\|hit_vfx.spawn' engine/
```

Expected matches:
- `engine/appc/hit_feedback.py` — `host.shield_hit(...)` inside dispatch (the only legitimate call site for shield_hit on the renderer)
- `engine/appc/hit_vfx.py` — the `spawn` definition itself
- `engine/host_loop.py` — only the renderer-batch `host.set_hit_vfx(...)` call, NOT `host.shield_hit(...)` and NOT `hit_vfx.spawn(...)` (both must be gone from `_advance_combat` after Task 3 and Task 7).

If `_advance_combat` still has either call, this is a regression — remove it.

### Step 10.4: Run the full focused suite

```bash
uv run pytest tests/unit/test_apply_hit_routing.py \
              tests/unit/test_apply_hit_state_diff.py \
              tests/unit/test_camera_shake_decay.py \
              tests/unit/test_combat_hit_resolution.py \
              tests/unit/test_hit_feedback_classify.py \
              tests/unit/test_hit_feedback_dispatch.py \
              tests/unit/test_hit_vfx_lifecycle.py \
              tests/unit/test_load_damage_hit_sounds.py \
              tests/unit/test_shield_face_from_hit_point.py \
              tests/integration/test_phaser_damage_applied_through_apply_hit.py \
              tests/integration/test_damage_severity_sequence.py \
              tests/integration/test_mesh_ray_trace.py -v
```

Expected: all green.

### Step 10.5: Visual smoke (manual, gated on a working dev binary)

Per spec §7.6:

1. `cmake -B build -S . && cmake --build build -j && ./build/dauntless`
2. Default mission (M2Objects). Approach a Warbird.
3. Fire phasers continuously on the Warbird front. Confirm:
   - Shield bubble splashes for ~first 3 seconds, no hull billboard, no sparks.
   - Audio: `"Shield Hit"`.
4. Shields exhaust on front face. Confirm:
   - Bubble splashes stop, tinted hull billboard appears at the impact point.
   - Audio switches to `g_lsWeaponExplosions` pool (one of `"Explosion 1..19"`).
5. Target Sensors with `T`. Continue firing. Confirm:
   - On the tick the Sensors row on the ShipDisplay panel flips, one frame produces a larger flash + 6 sparks ejected along the hull surface.
   - Audio: one of the `g_lsSubsystemCriticals` names plays.
6. Have an NPC fire on the player. Confirm:
   - Camera rocks ~1–2° on hits, decays within ~0.5s.
   - Test in both exterior and bridge views.

Record observed behaviour. If any step fails, file as a deferred polish issue with the constants involved (e.g. "CRITICAL spark cone too wide — kSparkConeDeg 30° looked like a starburst, dial to 15°").

### Step 10.6: Final commit

```bash
git add tests/integration/test_damage_severity_sequence.py
git commit -m "$(cat <<'EOF'
test(integration): severity transition sequence + player-gate camera shake

Integration coverage for the full damage pipeline:
- 10-tick continuous fire on a target with FRONT shield 100, sensors
  MaxCondition 100, DisabledPercentage 0.5
- Asserts severity stream SHIELD×3 → HULL → CRITICAL (sensors disabled)
  → HULL → CRITICAL (sensors destroyed) → HULL×3
- Mutual-exclusivity invariant: no tick fires both shield_hit and
  hit_vfx.spawn for the same impact
- Camera shake fires only when target is App.Game_GetCurrentGame().GetPlayer()

Project 4 of the combat damage pipeline roadmap, Task 10 of the
damage-vfx-bridge-feedback implementation plan. Closes Project 4.
EOF
)"
```

---

## Definition of done (mirrors spec §10)

- [ ] All three severity tiers fire correctly from `apply_hit`. Mutual exclusivity invariant verified by `tests/integration/test_damage_severity_sequence.py`.
- [ ] Surface normal threaded from `ray_trace_mesh` through to the renderer for HULL + CRITICAL descriptors. Verified by `tests/unit/test_combat_hit_resolution.py::test_resolve_returns_mesh_hit_when_trace_succeeds` and the C++ rebuild succeeding.
- [ ] Per-tier audio plays via `App.g_kSoundManager.GetSound(name).Play(position=...)`. Verified by `tests/unit/test_hit_feedback_dispatch.py`.
- [ ] Player camera shake fires on player-targeted hits in both exterior and bridge views, decays smoothly within ~0.5s. Verified by `tests/unit/test_camera_shake_decay.py` and visual smoke step 6.
- [ ] All §7.5 existing tests still pass.
- [ ] Visual smoke procedure (§7.6 / Step 10.5) reproduces the expected sequence on M2Objects.
- [ ] No stale `shield_hit` / `hit_vfx.spawn` calls outside `engine/appc/hit_feedback.py` (Step 10.3 grep audit).
