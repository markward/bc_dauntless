# Shield System Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace our strict-cascade shield model with BC's ellipsoid facing selection, pass-through absorption ramp, and power-linked 0.5 s charge cadence.

**Architecture:** Two new pure modules (`shield_geometry`, `shield_absorption`) plus one stateful accumulator (`beam_dwell`); `ShieldSubsystem` gains a power-driven 0.5 s tick; `combat.apply_hit` shrinks to routing and takes a mandatory `segment`.

**Tech Stack:** Python 3 (engine), pytest. No C++ changes except Task 12's read-side wiring.

**Spec:** `docs/superpowers/specs/2026-08-16-shield-system-redesign-design.md`

## Global Constraints

- **Evidence grade.** Every constant traceable to `stbc_reference spec/ShieldFacingDamage.md` is `reviewed-not-tested` — read from the image, never executed. Cite the address in a comment; never promote to "verified".
- **Units.** All spatial values are game units (GU). Never name a variable `*_m` / `*_mps`. See `engine/units.py`.
- **Rotation convention.** `R.GetCol(0/1/2)` = ship right / forward / up. Never `GetRow`.
- **Stub trap.** Use `engine.core.ids.implements(obj, "Name")`, never `hasattr`, to test for engine surface. A missing attribute yields a **truthy** `_Stub`.
- **Shared checkout.** Stage with explicit pathspecs. Never `git add -A`, `git checkout --`, `git stash`, `git restore`, `git clean`, `git reset --hard`.
- **Test gate.** `scripts/check_tests.sh` (both suites). `tests/known_failures.txt` is the baseline — never eyeball "pre-existing".
- **Constants copied verbatim from the spec:** ramp low `0.1` (`0x0088BF28`), ramp high `0.6` (`0x0088CB60`), max pass-through `0.6`, charge quantum divisor `1/6` (`0x0088BACC`), charge efficiency `0.85` (`0x00892FBC`), cadence `0.5` s (`0x008E529C`), axis scale `sqrt(3.0)` (`0x00894338`, stored as a **double**), beam hull-pass ray extension `10.0` (`0x0088C548`).

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/appc/shield_geometry.py` | **new** — ellipsoid value type, construction from a model bound, dominant-axis rule, segment→facing |
| `engine/appc/shield_absorption.py` | **new** — pass-through ramp, absorption arithmetic, the ≤0.1 gate |
| `engine/appc/beam_dwell.py` | **new** — 0.5 s beam pulse accumulator |
| `engine/appc/subsystems.py` | `ShieldSubsystem` charge tick + `ApplyDamage`; `ShieldProperty` weight/scalar split |
| `engine/appc/combat.py` | `apply_hit` mandatory `segment`; delete `_shield_face_from_hit_point` fallback |
| `engine/appc/splash_damage.py` | six-facing splash absorption |
| `engine/appc/projectiles.py` | yield the per-tick segment already computed internally |
| `engine/host_loop.py` | pass real segments; drive `beam_dwell`; ellipsoid caching |

---

## Task 1: Shield ellipsoid + dominant-axis rule

**Files:**
- Create: `engine/appc/shield_geometry.py`
- Test: `tests/unit/test_shield_geometry_ellipsoid.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ELLIPSOID_AXIS_SCALE: float`; `ShieldEllipsoid(centre: tuple[float,float,float], semi_axes: tuple[float,float,float])` (frozen); `ellipsoid_for_bound(centre, half_extents, scale=1.0) -> ShieldEllipsoid | None`; `dominant_signed_axis(v: tuple[float,float,float]) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_shield_geometry_ellipsoid.py
import math
import pytest
from engine.appc.shield_geometry import (
    ELLIPSOID_AXIS_SCALE, ShieldEllipsoid, ellipsoid_for_bound,
    dominant_signed_axis,
)


def test_semi_axes_are_half_extents_times_sqrt3():
    """ComputeShieldEllipsoid 0x005ABAC0: the bound's half-extents scaled by
    sqrt(3.0). The 3.0 is stored as a DOUBLE at 0x00894338 -- reading it as a
    float yields 0.0, which is the trap that silently turns the bubble inside
    out."""
    ell = ellipsoid_for_bound((0.0, 0.0, 0.0), (232.0, 322.0, 70.0))
    k = math.sqrt(3.0)
    assert ell.semi_axes == pytest.approx((232.0 * k, 322.0 * k, 70.0 * k))
    assert ELLIPSOID_AXIS_SCALE == pytest.approx(k)


def test_centre_and_axes_both_scale_with_ship_scale():
    ell = ellipsoid_for_bound((10.0, -20.0, 5.0), (100.0, 200.0, 50.0), scale=2.0)
    k = math.sqrt(3.0)
    assert ell.centre == pytest.approx((20.0, -40.0, 10.0))
    assert ell.semi_axes == pytest.approx((200.0 * k, 400.0 * k, 100.0 * k))


def test_degenerate_bound_returns_none():
    """A zero or negative extent means no usable bubble. Return None so the
    caller routes to hull rather than dividing by zero in a combat tick."""
    assert ellipsoid_for_bound((0.0, 0.0, 0.0), (0.0, 10.0, 10.0)) is None
    assert ellipsoid_for_bound((0.0, 0.0, 0.0), (10.0, -1.0, 10.0)) is None


@pytest.mark.parametrize("vec,expected", [
    ((0.0, 1.0, 0.0), 0),    # +y
    ((0.0, -1.0, 0.0), 1),   # -y
    ((0.0, 0.0, 1.0), 2),    # +z
    ((0.0, 0.0, -1.0), 3),   # -z
    ((-1.0, 0.0, 0.0), 4),   # -x
    ((1.0, 0.0, 0.0), 5),    # +x
])
def test_dominant_axis_maps_each_axis_to_its_facing(vec, expected):
    assert dominant_signed_axis(vec) == expected


def test_ties_resolve_in_bc_scan_order():
    """0x0056A8D0 scans +y, +z, +x, -y, -z, -x with a STRICT compare, so the
    earlier entry wins a tie. +y ties +z -> +y (0); +z ties +x -> +z (2)."""
    assert dominant_signed_axis((0.0, 1.0, 1.0)) == 0
    assert dominant_signed_axis((1.0, 0.0, 1.0)) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_shield_geometry_ellipsoid.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.shield_geometry'`

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/shield_geometry.py
"""Shield ellipsoid geometry — the GAMEPLAY shield surface.

Spec: docs/superpowers/specs/2026-08-16-shield-system-redesign-design.md §4.
Reference: stbc_reference spec/ShieldFacingDamage.md §1-2, graded
reviewed-not-tested (read from the original image, never executed).

Pure maths: no engine imports, no I/O. That is deliberate -- the facing rule
is the part most likely to be wrong, and a pure function is cheap to test
against real hull extents and cheap to correct after a live pass.

NOTE ON SKIN SHIELDING: this module is unconditional. BC has exactly one
shield collision shape and it is always an ellipsoid -- ComputeShieldEllipsoid
reads the model bound with no property branch. Dauntless's SkinShielding is a
RENDER mode only (it does not exist in the SDK at all). Do not make facing
selection mesh-based; see spec §8.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ComputeShieldEllipsoid 0x005ABAC0 multiplies each half-extent by the square
# root of 3.0. The 3.0 is stored as a DOUBLE at 0x00894338 and square-rooted at
# runtime -- read as a float it is 0.0.
ELLIPSOID_AXIS_SCALE: float = math.sqrt(3.0)

# Scan order and mapping from 0x0056A8D0: (component index, sign, facing).
# Scanned in this order with a STRICT compare, so an earlier entry wins a tie.
# The axis->index mapping is measured. The index->NAME convention
# (0 == front, ...) is NOT established anywhere in the binary; probe q19 tests
# it. Nothing here depends on the names.
_AXIS_TO_FACING = (
    (1, 1.0, 0),    # +y -> 0
    (2, 1.0, 2),    # +z -> 2
    (0, 1.0, 5),    # +x -> 5
    (1, -1.0, 1),   # -y -> 1
    (2, -1.0, 3),   # -z -> 3
    (0, -1.0, 4),   # -x -> 4
)


@dataclass(frozen=True)
class ShieldEllipsoid:
    """Body-frame shield bubble at the ship's CURRENT scale."""
    centre: tuple
    semi_axes: tuple


def ellipsoid_for_bound(centre, half_extents, scale: float = 1.0):
    """Build the bubble from a model bound. Returns None if degenerate."""
    try:
        hx, hy, hz = (float(v) for v in half_extents)
        cx, cy, cz = (float(v) for v in centre)
    except (TypeError, ValueError):
        return None
    if hx <= 0.0 or hy <= 0.0 or hz <= 0.0:
        return None
    s = float(scale)
    k = ELLIPSOID_AXIS_SCALE * s
    return ShieldEllipsoid((cx * s, cy * s, cz * s), (hx * k, hy * k, hz * k))


def dominant_signed_axis(v) -> int:
    """Signed dominant axis of `v` -> facing index (0x0056A8D0)."""
    best_facing = _AXIS_TO_FACING[0][2]
    best_value = None
    for comp, sign, facing in _AXIS_TO_FACING:
        value = float(v[comp]) * sign
        if best_value is None or value > best_value:
            best_value = value
            best_facing = facing
    return best_facing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_shield_geometry_ellipsoid.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/shield_geometry.py tests/unit/test_shield_geometry_ellipsoid.py
git commit -m "feat(shields): ellipsoid geometry + BC's dominant-axis facing rule"
```

---

## Task 2: Facing from a segment

**Files:**
- Modify: `engine/appc/shield_geometry.py`
- Test: `tests/unit/test_shield_geometry_facing.py`

**Interfaces:**
- Consumes: `ShieldEllipsoid`, `dominant_signed_axis` (Task 1).
- Produces: `FacingHit(facing: int, entry_body: tuple, normal_body: tuple)` (frozen); `facing_for_segment(ell, start_body, end_body) -> FacingHit | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_shield_geometry_facing.py
import math
import pytest
from engine.appc.shield_geometry import (
    ellipsoid_for_bound, facing_for_segment, dominant_signed_axis,
)

# Real hulls, from model_aabb (see CLAUDE.md "Shield face + impact splash").
GALAXY = ((0.0, 0.0, 0.0), (232.0, 322.0, 70.0))
SOVEREIGN = ((0.0, 0.0, -6.98), (115.0, 350.0, 41.0))


def _ell(bound):
    return ellipsoid_for_bound(bound[0], bound[1])


def test_bow_on_shot_selects_the_forward_facing():
    ell = _ell(GALAXY)
    hit = facing_for_segment(ell, (0.0, 5000.0, 0.0), (0.0, 0.0, 0.0))
    assert hit is not None
    assert hit.facing == 0


def test_dorsal_shot_selects_the_up_facing_on_a_flat_hull():
    """A Galaxy is 4.6x longer than it is tall. The normalisation by semi-axes
    is what makes a dorsal hit read as dorsal; a raw-component compare bills
    most of the dorsal surface to fore/aft."""
    ell = _ell(GALAXY)
    hit = facing_for_segment(ell, (0.0, 0.0, 5000.0), (0.0, 0.0, 0.0))
    assert hit is not None
    assert hit.facing == 2


def test_segment_starting_inside_the_bubble_returns_none():
    """TestHit 0x005AE730 step 5: a shooter already inside the bubble gets the
    hull test, not a facing."""
    ell = _ell(GALAXY)
    assert facing_for_segment(ell, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)) is None


def test_segment_that_misses_returns_none():
    ell = _ell(GALAXY)
    assert facing_for_segment(
        ell, (100000.0, 5000.0, 0.0), (100000.0, -5000.0, 0.0)) is None


def test_segment_too_short_to_reach_the_bubble_returns_none():
    """The intersection must lie within the segment, not on its infinite line."""
    ell = _ell(GALAXY)
    assert facing_for_segment(ell, (0.0, 5000.0, 0.0), (0.0, 4900.0, 0.0)) is None


def test_entry_point_lies_on_the_ellipsoid():
    ell = _ell(SOVEREIGN)
    hit = facing_for_segment(ell, (4000.0, 3000.0, 500.0), (0.0, 0.0, 0.0))
    assert hit is not None
    ax, ay, az = ell.semi_axes
    cx, cy, cz = ell.centre
    ex, ey, ez = hit.entry_body
    r = ((ex - cx) / ax) ** 2 + ((ey - cy) / ay) ** 2 + ((ez - cz) / az) ** 2
    assert r == pytest.approx(1.0, abs=1e-9)


def test_normal_is_the_ellipsoid_normal_not_the_sphere_normal():
    """CORRECTED DEFECT 2 (spec §7). BC writes the unit-sphere position as the
    normal; the true ellipsoid normal is grad(F) ~ h / semi_axes. On an
    anisotropic hull these differ, and only the sphere one is wrong."""
    ell = _ell(GALAXY)
    hit = facing_for_segment(ell, (3000.0, 3000.0, 0.0), (0.0, 0.0, 0.0))
    assert hit is not None
    nx, ny, nz = hit.normal_body
    assert nx * nx + ny * ny + nz * nz == pytest.approx(1.0)
    # The sphere normal would point along the (equal) normalised components;
    # the ellipsoid normal must be pulled toward the SHORT axis (x on a Galaxy).
    assert abs(nx) > abs(ny)


def test_entry_point_and_impact_point_can_select_different_facings():
    """THE regression test for spec §4.4 -- the divergence this redesign fixes.

    A shot that grazes the bow and travels aft ENTERS the bubble forward, but
    its recorded impact lies further aft. BC bills the facing where the segment
    entered; our old point-based rule billed where it landed.
    """
    ell = _ell(GALAXY)
    start = (0.0, 4000.0, 60.0)
    end = (0.0, -4000.0, 60.0)
    hit = facing_for_segment(ell, start, end)
    assert hit is not None
    ax, ay, az = ell.semi_axes
    cx, cy, cz = ell.centre
    impact_axis = dominant_signed_axis(
        ((end[0] - cx) / ax, (end[1] - cy) / ay, (end[2] - cz) / az))
    assert hit.facing != impact_axis, (
        "fixture no longer exercises the divergence -- pick a grazing segment "
        "whose entry and endpoint disagree")
    assert hit.facing == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_shield_geometry_facing.py -q`
Expected: FAIL — `ImportError: cannot import name 'facing_for_segment'`

- [ ] **Step 3: Write the implementation**

Append to `engine/appc/shield_geometry.py`:

```python
@dataclass(frozen=True)
class FacingHit:
    """A resolved shield impact. All vectors are body-frame."""
    facing: int
    entry_body: tuple
    normal_body: tuple


def _segment_unit_sphere_near(p0, p1):
    """Near intersection of segment p0->p1 with the unit sphere at the origin,
    or None. Mirrors the ray/sphere helper 0x004570D0 (centre 0x009A2878,
    radius 1.0 at 0x00888860)."""
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    a = dx * dx + dy * dy + dz * dz
    if a <= 1e-18:
        return None
    b = 2.0 * (p0[0] * dx + p0[1] * dy + p0[2] * dz)
    c = p0[0] * p0[0] + p0[1] * p0[1] + p0[2] * p0[2] - 1.0
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    t = (-b - math.sqrt(disc)) / (2.0 * a)
    if t < 0.0 or t > 1.0:
        return None
    return (p0[0] + dx * t, p0[1] + dy * t, p0[2] + dz * t)


def facing_for_segment(ell: ShieldEllipsoid, start_body, end_body):
    """Facing struck by the segment, or None for 'no facing -> hull'.

    BC (TestHit 0x005AE730) takes the dominant axis of the point where the
    segment ENTERS the ellipsoid -- not of the impact point. They agree on the
    bubble surface and diverge on grazing and long-step shots.
    """
    ax, ay, az = ell.semi_axes
    cx, cy, cz = ell.centre
    n0 = ((start_body[0] - cx) / ax,
          (start_body[1] - cy) / ay,
          (start_body[2] - cz) / az)
    # Shooter already inside the bubble -> hull test (TestHit step 5).
    if n0[0] * n0[0] + n0[1] * n0[1] + n0[2] * n0[2] <= 1.0:
        return None
    n1 = ((end_body[0] - cx) / ax,
          (end_body[1] - cy) / ay,
          (end_body[2] - cz) / az)
    h = _segment_unit_sphere_near(n0, n1)
    if h is None:
        return None
    # CORRECTED DEFECT 2: the true ellipsoid normal is grad(F) ~ h / semi_axes.
    # BC writes h itself, which is the SPHERE's normal (spec §7).
    gx, gy, gz = h[0] / ax, h[1] / ay, h[2] / az
    length = math.sqrt(gx * gx + gy * gy + gz * gz)
    if length <= 1e-12:
        return None
    return FacingHit(
        dominant_signed_axis(h),
        (h[0] * ax + cx, h[1] * ay + cy, h[2] * az + cz),
        (gx / length, gy / length, gz / length),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_shield_geometry_facing.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/shield_geometry.py tests/unit/test_shield_geometry_facing.py
git commit -m "feat(shields): facing from the segment's ellipsoid entry point"
```

---

## Task 3: The absorption ramp

**Files:**
- Create: `engine/appc/shield_absorption.py`
- Test: `tests/unit/test_shield_absorption.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RAMP_LOW = 0.1`, `RAMP_HIGH = 0.6`, `MAX_PASSTHROUGH = 0.6`; `passthrough_fraction(fraction) -> float`; `facing_stops_shot(fraction) -> bool`; `Absorption(absorbed: float, passthrough: float, new_charge: float)` (frozen); `absorb(fraction, charge, damage) -> Absorption`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_shield_absorption.py
import pytest
from engine.appc.shield_absorption import (
    RAMP_LOW, RAMP_HIGH, MAX_PASSTHROUGH,
    passthrough_fraction, facing_stops_shot, absorb,
)


@pytest.mark.parametrize("fraction,expected", [
    (1.00, 0.0), (0.60, 0.0), (0.35, 0.30),
    (0.10, 0.6), (0.00, 0.6),
])
def test_ramp_values(fraction, expected):
    assert passthrough_fraction(fraction) == pytest.approx(expected)


def test_ramp_is_continuous_at_both_breakpoints():
    eps = 1e-9
    assert passthrough_fraction(RAMP_LOW + eps) == pytest.approx(MAX_PASSTHROUGH, abs=1e-6)
    assert passthrough_fraction(RAMP_HIGH - eps) == pytest.approx(0.0, abs=1e-6)


def test_full_facing_absorbs_everything():
    """THE TESTED ANCHOR (spec §11). Probe q04 measured EXACTLY 0.0 hull damage
    with all facings full. f = 1.0 -> b = 0, so pass-through must be exactly
    zero -- not approximately. This is the one assertion here backed by
    measured evidence rather than read evidence."""
    result = absorb(fraction=1.0, charge=1000.0, damage=250.0)
    assert result.passthrough == 0.0
    assert result.absorbed == 250.0
    assert result.new_charge == 750.0


def test_weakened_facing_bleeds_through():
    """At f = 0.35 the ramp passes 30%: the facing absorbs 70."""
    result = absorb(fraction=0.35, charge=1000.0, damage=100.0)
    assert result.passthrough == pytest.approx(30.0)
    assert result.absorbed == pytest.approx(70.0)
    assert result.new_charge == pytest.approx(930.0)


def test_overdraw_adds_the_shortfall_on_top_of_the_bleed():
    """ApplyWeaponHit step 5: when the facing is driven negative the overdraw
    is ADDED to the bleed, and the charge clamps at zero."""
    result = absorb(fraction=0.35, charge=35.0, damage=100.0)
    # absorbing component = (1 - 0.3) * 100 = 70; charge 35 -> shortfall 35.
    assert result.new_charge == 0.0
    assert result.passthrough == pytest.approx(30.0 + 35.0)
    assert result.absorbed == pytest.approx(35.0)


def test_gate_is_strictly_above_the_low_breakpoint():
    """TestHit step 9: 'not greater than 0.1' means the facing does not stop
    the shot at all."""
    assert facing_stops_shot(0.11) is True
    assert facing_stops_shot(0.10) is False
    assert facing_stops_shot(0.0) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_shield_absorption.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.shield_absorption'`

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/shield_absorption.py
"""Shield absorption — BC's pass-through ramp.

Spec: docs/superpowers/specs/2026-08-16-shield-system-redesign-design.md §5.
Reference: stbc_reference spec/ShieldFacingDamage.md §3.3, graded
reviewed-not-tested.

This is NOT a strict cascade. A facing above 60% charge absorbs everything; as
charge falls, an increasing fraction of every shot passes through, reaching 60%
at 10% charge. Our probe q04 measured "no bleed-through" only because it tested
full facings, where the ramp is identically zero.
"""
from __future__ import annotations

from dataclasses import dataclass

RAMP_LOW: float = 0.1          # 0x0088BF28
RAMP_HIGH: float = 0.6         # 0x0088CB60
MAX_PASSTHROUGH: float = 0.6   # 0x0088CB60


def passthrough_fraction(fraction: float) -> float:
    """Fraction of an incoming shot that passes THROUGH the facing.

    Continuous: 0.6 at RAMP_LOW, falling linearly to 0.0 at RAMP_HIGH.

    The `f <= RAMP_LOW` branch is unreachable while `facing_stops_shot` gates
    the caller AND the fraction is live (spec §5). It is kept because BC's own
    curve defines it and because the branch becomes live again the moment the
    gate moves. Do not delete it as dead code.
    """
    f = float(fraction)
    if f >= RAMP_HIGH:
        return 0.0
    if f <= RAMP_LOW:
        return MAX_PASSTHROUGH
    return (1.0 - 2.0 * (f - RAMP_LOW)) * MAX_PASSTHROUGH


def facing_stops_shot(fraction: float) -> bool:
    """Whether the facing stops the shot at all (TestHit 0x005AE730 step 9).

    Below this the hit routes to hull with no facing, exactly as if the segment
    had missed the bubble. Kept separate from absorption because in BC this
    gate lives in the geometry pass, not the damage pass.
    """
    return float(fraction) > RAMP_LOW


@dataclass(frozen=True)
class Absorption:
    absorbed: float
    passthrough: float
    new_charge: float


def absorb(fraction: float, charge: float, damage: float) -> Absorption:
    """Apply `damage` to one facing. Caller clamps new_charge to the cap."""
    d = float(damage)
    b = passthrough_fraction(fraction)
    new_charge = float(charge) - (1.0 - b) * d
    if new_charge >= 0.0:
        passthrough = b * d
    else:
        passthrough = b * d + (-new_charge)
        new_charge = 0.0
    return Absorption(d - passthrough, passthrough, new_charge)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_shield_absorption.py -q`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/shield_absorption.py tests/unit/test_shield_absorption.py
git commit -m "feat(shields): BC's pass-through absorption ramp as a pure unit"
```

---

## Task 4: Separate the per-facing weight from the scalar rate

**Files:**
- Modify: `engine/appc/subsystems.py` (`ShieldSubsystem.__init__`, new accessors)
- Test: `tests/unit/test_shield_charge_rate_fields.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ShieldSubsystem.GetShieldChargeRateScalar() -> float`; `ShieldSubsystem.SetShieldChargeRateScalar(value) -> None`; existing `GetShieldChargePerSecond(face)` / `SetShieldChargePerSecond(face, value)` retained, now documented as the per-facing WEIGHT.

**Design note (ours, not BC's):** BC's scalar lives at `ShieldProperty +0x48` and its authored values are not in the image. We default the scalar to the subsystem's `GetNormalPowerWanted()`, so that at 100 % power delivery the effective regen equals the authored per-facing rate — preserving existing ship balance while making power the lever. At full power, regen is `0.85 ×` the authored rate because BC's efficiency factor is kept explicit; check that against the measured ~6.7 pts/s on a Galaxy during the live pass.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_shield_charge_rate_fields.py
from engine.appc.subsystems import ShieldSubsystem


def test_weight_and_scalar_are_distinct_fields():
    """NAMING TRAP (spec §6.1): GetShieldChargePerSecond returns the per-facing
    WEIGHT (ShieldProperty +0x78 + 4i). The scalar the charge tick divides by is
    a DIFFERENT field (+0x48). The published name describes the weight, not the
    resulting rate. Collapsing them silently changes every ship's regen."""
    s = ShieldSubsystem("shields")
    s.SetShieldChargePerSecond(0, 12.0)
    s.SetShieldChargeRateScalar(100.0)
    assert s.GetShieldChargePerSecond(0) == 12.0
    assert s.GetShieldChargeRateScalar() == 100.0


def test_scalar_defaults_to_normal_power_wanted():
    """Our calibration, not BC's: at full power delivery the effective regen
    equals the authored per-facing rate."""
    s = ShieldSubsystem("shields")
    s.SetNormalPowerWanted(80.0)
    assert s.GetShieldChargeRateScalar() == 80.0


def test_explicit_scalar_overrides_the_default():
    s = ShieldSubsystem("shields")
    s.SetNormalPowerWanted(80.0)
    s.SetShieldChargeRateScalar(40.0)
    assert s.GetShieldChargeRateScalar() == 40.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_shield_charge_rate_fields.py -q`
Expected: FAIL — `AttributeError: 'ShieldSubsystem' object has no attribute 'SetShieldChargeRateScalar'`

**`SetNormalPowerWanted` does not exist yet** — `PoweredSubsystem` has only the getter. Add the setter beside it in this task:

```python
    def SetNormalPowerWanted(self, v) -> None:            self._normal_power = float(v)
```

- [ ] **Step 3: Write the implementation**

In `ShieldSubsystem.__init__`, after `self._charge_per_second`:

```python
        # BC ShieldProperty +0x48: the SCALAR the charge tick divides by. This
        # is NOT the same field as _charge_per_second, which is the per-facing
        # WEIGHT (+0x78 + 4i) that GetShieldChargePerSecond publishes. Keeping
        # them distinct is load-bearing -- see spec §6.1's naming trap.
        # None means "not authored": fall back to normal power wanted, so that
        # at 100% power delivery the effective regen equals the authored
        # per-facing rate. That calibration is OURS; BC's authored values for
        # +0x48 are not in the image.
        self._charge_rate_scalar: "float | None" = None
```

Add methods on `ShieldSubsystem`:

```python
    def GetShieldChargeRateScalar(self) -> float:
        """The scalar divisor in the charge tick (BC ShieldProperty +0x48)."""
        if self._charge_rate_scalar is not None:
            return float(self._charge_rate_scalar)
        return float(self.GetNormalPowerWanted())

    def SetShieldChargeRateScalar(self, value) -> None:
        self._charge_rate_scalar = float(value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_shield_charge_rate_fields.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_charge_rate_fields.py
git commit -m "feat(shields): split the per-facing charge weight from the scalar rate"
```

---

## Task 5: Power-linked 0.5 s charge tick

**Files:**
- Modify: `engine/appc/subsystems.py` (`ShieldSubsystem.__init__`, `ShieldSubsystem.Update`)
- Test: `tests/unit/test_shield_charge_tick.py`

**Interfaces:**
- Consumes: `GetShieldChargeRateScalar` (Task 4).
- Produces: `ShieldSubsystem.CHARGE_TICK_SECONDS = 0.5`, `ShieldSubsystem.CHARGE_QUANTUM_DIVISOR = 6.0`, `ShieldSubsystem.CHARGE_EFFICIENCY = 0.85`; `Update(dt)` becomes power-driven and quantised.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_shield_charge_tick.py
import pytest
from engine.appc.subsystems import ShieldSubsystem


def _shields(power_received=100.0, max_per_face=1000.0, weight=10.0):
    s = ShieldSubsystem("shields")
    s.TurnOn()
    s.SetNormalPowerWanted(100.0)
    for i in range(ShieldSubsystem.NUM_SHIELDS):
        s.SetMaxShields(i, max_per_face)
        s.SetCurrentShields(i, 0.0)
        s.SetShieldChargePerSecond(i, weight)
    s._power_received = power_received
    return s


def test_no_charge_before_the_half_second_boundary():
    """Cadence is 0.5s of accumulated time (0x008E529C), not per frame."""
    s = _shields()
    for _ in range(29):            # 29 * 1/60 = 0.483s
        s.Update(1.0 / 60.0)
    assert s.GetCurrentShields(0) == 0.0


def test_charge_lands_at_the_boundary():
    s = _shields()
    for _ in range(30):            # 0.5s
        s.Update(1.0 / 60.0)
    assert s.GetCurrentShields(0) > 0.0


def test_zero_delivered_power_means_zero_regen():
    """THE headline gameplay assertion. Power management is now a direct lever
    on shield recovery; with nothing delivered, nothing charges."""
    s = _shields(power_received=0.0)
    for _ in range(120):           # 2s
        s.Update(1.0 / 60.0)
    assert s.GetCurrentShields(0) == 0.0


def test_regen_scales_linearly_with_delivered_power():
    lo = _shields(power_received=50.0)
    hi = _shields(power_received=100.0)
    for _ in range(30):
        lo.Update(1.0 / 60.0)
        hi.Update(1.0 / 60.0)
    assert hi.GetCurrentShields(0) == pytest.approx(2.0 * lo.GetCurrentShields(0))


def test_charge_uses_weight_over_scalar_with_the_efficiency_factor():
    """added = weight * accumulated_power / scalar, times 0.85 (0x00892FBC).
    The two 1/6 factors cancel; both are kept in the code to match the
    original's shape."""
    s = _shields(power_received=100.0, weight=10.0)
    s.SetShieldChargeRateScalar(100.0)
    for _ in range(30):
        s.Update(1.0 / 60.0)
    # accumulated power over 0.5s = 100 * 0.5 = 50
    expected = 10.0 * 50.0 / 100.0 * ShieldSubsystem.CHARGE_EFFICIENCY
    assert s.GetCurrentShields(0) == pytest.approx(expected, rel=1e-6)


def test_charge_clamps_to_the_face_maximum():
    s = _shields(power_received=1e6)
    for _ in range(30):
        s.Update(1.0 / 60.0)
    assert s.GetCurrentShields(0) == 1000.0


def test_fraction_is_refreshed_on_the_tick():
    s = _shields()
    for _ in range(30):
        s.Update(1.0 / 60.0)
    assert s.GetShieldFraction(0) == pytest.approx(
        s.GetCurrentShields(0) / 1000.0)


def test_powered_down_generator_bleeds_charge():
    """BC's tick drains a facing whose generator is off, rather than merely
    failing to add (spec §6.1 consequence 2). We drained only on the
    SetAlertLevel transition before."""
    s = _shields()
    for i in range(ShieldSubsystem.NUM_SHIELDS):
        s.SetCurrentShields(i, 500.0)
    s.TurnOff()
    for _ in range(30):
        s.Update(1.0 / 60.0)
    assert s.GetCurrentShields(0) < 500.0
    assert s.GetShieldFraction(0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_shield_charge_tick.py -q`
Expected: FAIL — `AttributeError: type object 'ShieldSubsystem' has no attribute 'CHARGE_EFFICIENCY'`

- [ ] **Step 3: Write the implementation**

Add class constants and accumulators to `ShieldSubsystem`:

```python
    # Charge cadence (stbc_reference spec/ShieldFacingDamage.md §6.1,
    # reviewed-not-tested).
    CHARGE_TICK_SECONDS = 0.5     # 0x008E529C
    CHARGE_QUANTUM_DIVISOR = 6.0  # 0x0088BACC
    CHARGE_EFFICIENCY = 0.85      # 0x00892FBC
    OFF_DRAIN_PER_TICK = 0.25     # fraction of remaining charge bled per tick
```

In `__init__`:

```python
        self._charge_time_accum: float = 0.0    # BC +0x154
        self._charge_power_accum: float = 0.0   # BC +0x158
        self._fractions: list[float] = [0.0] * self.NUM_SHIELDS
```

Replace `ShieldSubsystem.Update` with:

```python
    def Update(self, dt: float) -> None:
        """Power-driven charge tick, quantised to 0.5s (BC 0x0056A230).

        Regen is a function of DELIVERED POWER, not a fixed rate: diverting
        power away from shields directly slows recovery. A generator that is
        off or disabled BLEEDS charge rather than holding it.
        """
        self._charge_time_accum += float(dt)
        self._charge_power_accum += float(self.GetPowerReceived()) * float(dt)
        if self._charge_time_accum < self.CHARGE_TICK_SECONDS:
            return

        quantum = self._charge_power_accum / self.CHARGE_QUANTUM_DIVISOR
        self._charge_time_accum = 0.0

        if _is_offline(self) or not self.IsOn():
            for i in range(self.NUM_SHIELDS):
                self._current_shields[i] *= (1.0 - self.OFF_DRAIN_PER_TICK)
                self._fractions[i] = 0.0
        else:
            quantum *= self.CHARGE_EFFICIENCY
            scalar = self.GetShieldChargeRateScalar()
            rate = scalar / self.CHARGE_QUANTUM_DIVISOR
            for i in range(self.NUM_SHIELDS):
                cap = self._max_shields[i]
                if cap <= 0.0:
                    self._fractions[i] = 0.0
                    continue
                if rate > 0.0:
                    added = self._charge_per_second[i] * quantum / rate
                    self._current_shields[i] = min(
                        self._current_shields[i] + added, cap)
                self._fractions[i] = self._current_shields[i] / cap
        self._charge_power_accum = 0.0
        self._refresh_watchers()

    def GetShieldFraction(self, face: int) -> float:
        """Live normalised charge on a facing. Refreshed on every charge
        change, not only on the tick -- CORRECTED DEFECT 3 (spec §7)."""
        return float(self._fractions[int(face)])

    def _refresh_watchers(self) -> None:
        """Step every facing watcher, then the combined one.

        `FloatRangeWatcher._update(new_value)` is the mutator -- it fires any
        range checks the SDK registered (ConditionSingleShieldBelow et al.).
        There is no `SetValue`.
        """
        for i in range(self.NUM_SHIELDS):
            self._shield_watchers[i]._update(self._fractions[i])
        self._shield_watchers[self.NUM_SHIELDS]._update(
            self.GetShieldPercentage())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_shield_charge_tick.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_charge_tick.py
git commit -m "feat(shields): power-linked 0.5s charge tick; off generators bleed"
```

---

## Task 6: `ApplyDamage` uses the ramp; fraction stays live

**Files:**
- Modify: `engine/appc/subsystems.py` (`ShieldSubsystem.ApplyDamage`, `SetCurrentShields`)
- Test: `tests/unit/test_shield_apply_damage_ramp.py`
- Modify: any existing test asserting strict cascade (find with the grep in Step 1)

**Interfaces:**
- Consumes: `absorb` (Task 3), `_fractions` + `GetShieldFraction` (Task 5).
- Produces: `ApplyDamage(face, amount) -> float` — unchanged signature, returns pass-through; `SetCurrentShields` refreshes the fraction.

- [ ] **Step 1: Find the tests that encode the old model**

Run: `grep -rln "ApplyDamage" tests/`
Every assertion of the form "facing absorbs everything until empty" encodes the model being replaced. Rewrite them in this task — **do not delete them**.

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_shield_apply_damage_ramp.py
import pytest
from engine.appc.subsystems import ShieldSubsystem


def _shields(charge, cap=1000.0):
    s = ShieldSubsystem("shields")
    s.TurnOn()
    for i in range(ShieldSubsystem.NUM_SHIELDS):
        s.SetMaxShields(i, cap)
        s.SetCurrentShields(i, charge)
    return s


def test_full_facing_passes_nothing_through():
    """The tested anchor again, at subsystem level (probe q04)."""
    s = _shields(1000.0)
    assert s.ApplyDamage(0, 250.0) == 0.0
    assert s.GetCurrentShields(0) == 750.0


def test_weakened_facing_passes_damage_through():
    """f = 0.35 -> 30% bleeds. The old strict cascade returned 0.0 here."""
    s = _shields(350.0)
    through = s.ApplyDamage(0, 100.0)
    assert through == pytest.approx(30.0)
    assert s.GetCurrentShields(0) == pytest.approx(280.0)


def test_damage_does_not_touch_other_facings():
    s = _shields(350.0)
    s.ApplyDamage(0, 100.0)
    assert s.GetCurrentShields(1) == 350.0


def test_fraction_is_live_not_stale():
    """CORRECTED DEFECT 3: BC refreshes the fraction only on the 0.5s charge
    tick, so a burst inside one window all sees a stale value. Ours updates on
    every charge change, so the second shot in a burst sees the real number."""
    s = _shields(1000.0)
    s.ApplyDamage(0, 500.0)
    assert s.GetShieldFraction(0) == pytest.approx(0.5)


def test_facing_below_the_gate_is_left_for_the_caller():
    """ApplyDamage does not apply the gate -- facing_stops_shot does, in the
    caller, because in BC that decision lives in the geometry pass."""
    s = _shields(50.0)          # f = 0.05
    through = s.ApplyDamage(0, 100.0)
    assert through > 0.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_shield_apply_damage_ramp.py -q`
Expected: FAIL — `test_weakened_facing_passes_damage_through` asserts 30.0, gets 0.0

- [ ] **Step 4: Write the implementation**

```python
    def ApplyDamage(self, face: int, amount: float) -> float:
        """Apply damage to one facing; return the pass-through.

        BC's ApplyWeaponHit shield branch (spec §3.3): NOT a strict cascade.
        The facing absorbs the complement of a charge-dependent pass-through
        fraction, and any overdraw is added on top of that bleed.
        """
        from engine.appc.shield_absorption import absorb
        f = int(face)
        cap = self._max_shields[f]
        result = absorb(self.GetShieldFraction(f), self._current_shields[f],
                        float(amount))
        self.SetCurrentShields(f, min(result.new_charge, cap) if cap > 0.0
                               else 0.0)
        return result.passthrough
```

And make `SetCurrentShields` refresh the fraction (corrected defect 3) — inside its existing body, after the charge is stored:

```python
        cap = self._max_shields[f]
        self._fractions[f] = (self._current_shields[f] / cap) if cap > 0.0 else 0.0
```

- [ ] **Step 5: Run the full unit suite**

Run: `uv run pytest tests/unit -q`
Expected: PASS. Any failure asserting strict cascade must be **rewritten** to the ramp, in this commit.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/
git commit -m "feat(shields): ApplyDamage uses the pass-through ramp; fraction stays live"
```

---

## Task 7: `apply_hit` takes a mandatory segment

**Files:**
- Modify: `engine/appc/combat.py` (`apply_hit` signature, shield branch; delete `_shield_face_from_hit_point`)
- Modify: all `apply_hit` callers in `engine/` and `tests/` (67 call sites in tests)
- Test: `tests/unit/test_apply_hit_segment.py`

**Interfaces:**
- Consumes: `facing_for_segment`, `ellipsoid_for_bound` (Tasks 1–2); `facing_stops_shot`, `GetShieldFraction` (Tasks 3, 5).
- Produces: `apply_hit(ship, damage, hit_point, source, *, segment, ...)` — `segment` is **required**, typed `tuple[start_world, end_world] | None`; `combat._shield_ellipsoid_for(ship) -> ShieldEllipsoid | None`; `combat._resolve_facing(ship, segment) -> int | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_apply_hit_segment.py
import pytest
from engine.appc import combat


def test_segment_is_required():
    """No default, no fallback. A caller must state whether its path selects a
    facing; omitting it is a TypeError, not a silent approximation."""
    with pytest.raises(TypeError):
        combat.apply_hit(object(), 10.0, None, None)


def test_segment_none_routes_to_hull(shielded_ship_at_origin):
    """None is an explicit, meaningful value: 'this path selects no facing'.
    That is exactly BC's semantics for collision, AddDamage and splash, which
    reach the hull branch with facing -1."""
    ship = shielded_ship_at_origin
    before = ship.GetShields().GetCurrentShields(0)
    combat.apply_hit(ship, 100.0, _point(0.0, 400.0, 0.0), source=None,
                     segment=None)
    assert ship.GetShields().GetCurrentShields(0) == before
    assert ship.GetHull().GetCondition() < 1000.0
```

Use this fixture (mirrors `tests/unit/test_apply_hit_bypass_shields.py`, which is the canonical shielded-ship construction in this suite):

```python
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _point(x, y, z):
    return TGPoint3(x, y, z)


@pytest.fixture
def shielded_ship_at_origin(hull_max=1000.0, face_max=1000.0):
    """Yellow alert so the generator is IsOn(); shields seeded full."""
    ship = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    ship._shield_hull_box = ((0.0, 0.0, 0.0), (232.0, 322.0, 70.0))
    return ship
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_apply_hit_segment.py -q`
Expected: FAIL — `apply_hit` accepts the call without `segment`

- [ ] **Step 3: Change the signature and the shield branch**

In `apply_hit`, add `segment` as a required keyword-only parameter, and replace the facing resolution:

```python
    if shields_online and implements(shields, "ApplyDamage"):
        face = _resolve_facing(ship, segment)
        if face is None or not facing_stops_shot(
                shields.GetShieldFraction(face)):
            pass                      # no facing -> hull branch, BC's -1
        else:
            before = remaining
            ...existing commit / god-mode branch, using `face`...
```

Add both helpers — `_shield_ellipsoid_for` is introduced **here**, not in Task 12:

```python
def _shield_ellipsoid_for(ship):
    """The ship's shield bubble at its CURRENT scale, or None.

    `ship._shield_hull_box` is cached at spawn in world units at
    GetScale() == 1; the live scale is applied here so a rescaled ship keeps
    bubble and instance matrix in step.
    """
    from engine.appc.shield_geometry import ellipsoid_for_bound
    box = getattr(ship, "_shield_hull_box", None)
    if box is None:
        return None
    try:
        centre, half = box
    except (TypeError, ValueError):
        return None
    scale = 1.0
    if implements(ship, "GetScale"):
        try:
            scale = float(ship.GetScale()) or 1.0
        except (TypeError, ValueError):
            scale = 1.0
    return ellipsoid_for_bound(centre, half, scale)


def _resolve_facing(ship, segment):
    """Facing index for this hit, or None for 'route to hull'.

    `segment is None` means the caller's path selects no facing at all --
    collision, AddDamage and splash. That is not a degraded case; it is BC's
    behaviour for those paths.
    """
    if segment is None:
        return None
    ell = _shield_ellipsoid_for(ship)
    if ell is None:
        return None
    hit = facing_for_segment(ell,
                             _body_frame_delta(ship, segment[0]),
                             _body_frame_delta(ship, segment[1]))
    return None if hit is None else hit.facing
```

Delete `_shield_face_from_hit_point` and its point-based fallback entirely.

- [ ] **Step 4: Update every caller**

Run: `grep -rn "apply_hit(" engine/ tests/ | grep -v "def apply_hit"`

Add `segment=None` to `collisions.py` (2 sites), `objects.py`, and `splash_damage.py` — all bypass or skip facing selection. Add `segment=None` to every test call site that is not specifically testing facing selection. Tasks 8 and 10 supply real segments for the torpedo and phaser paths.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add engine/appc/combat.py engine/appc/collisions.py engine/appc/objects.py engine/appc/splash_damage.py tests/
git commit -m "refactor(shields): apply_hit takes a mandatory segment; drop the point-based facing"
```

---

## Task 8: Real segments for torpedoes and phasers

**Files:**
- Modify: `engine/appc/projectiles.py` (`update_all` yields the segment it already computes)
- Modify: `engine/host_loop.py:845-851` (torpedo), `:955-960` (phaser)
- Test: `tests/integration/test_hit_segments.py`

**Interfaces:**
- Consumes: `apply_hit(..., segment=...)` (Task 7).
- Produces: `projectiles.update_all` yields `(torpedo, ship, hit_point, hit_normal, prev_pos)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_hit_segments.py
def test_torpedo_hits_carry_the_travel_segment():
    """projectiles.update_all already computes prev_pos before advancing
    (projectiles.py:304). It just never yielded it -- so the facing was chosen
    from the impact point instead of the segment BC uses."""
    from engine.appc import projectiles
    hits = _fire_one_torpedo_into_a_target()
    assert hits, "fixture fired no torpedo"
    for hit in hits:
        assert len(hit) == 5, "update_all must yield prev_pos as the 5th value"
        prev = hit[4]
        assert prev is not None
```

Build `_fire_one_torpedo_into_a_target` from the existing torpedo fixtures — read `tests/unit/test_torpedo_decal_emission.py` and reuse its construction.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_hit_segments.py -q`
Expected: FAIL — tuple has 4 elements

- [ ] **Step 3: Yield the segment and pass it**

In `projectiles.update_all`, include `prev_pos` in the appended hit tuple. In `host_loop`:

```python
    for torpedo, ship, hit_point, hit_normal, prev_pos in hits:
        combat.apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship,
                  normal=hit_normal, ship_instances=ship_instances,
                  weapon_type="torpedo",
                  hardpoint_weapon=torpedo,
                  segment=(prev_pos, torpedo._position))
```

For the phaser site, the beam segment is muzzle to impact — `emitter_pos` and `impact_point` are both already in scope:

```python
                combat.apply_hit(target, damage, impact_point,
                          source=ship,
                          normal=impact_normal,
                          ship_instances=ship_instances,
                          weapon_type="phaser",
                          hardpoint_weapon=bank,
                          damage_hull=damage_hull,
                          segment=(emitter_pos, impact_point))
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_hit_segments.py tests/unit -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/appc/projectiles.py engine/host_loop.py tests/integration/test_hit_segments.py
git commit -m "feat(shields): torpedo and phaser hits carry a real travel segment"
```

---

## Task 9: Beam dwell accumulator

**Files:**
- Create: `engine/appc/beam_dwell.py`
- Test: `tests/unit/test_beam_dwell.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PULSE_SECONDS = 0.5`; `BeamDwell()` with `accumulate(weapon_key, target, dt) -> float | None` (returns dwell to flush, or None), `on_target_lost(weapon_key) -> float | None`, `reset(weapon_key) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_beam_dwell.py
import pytest
from engine.appc.beam_dwell import BeamDwell, PULSE_SECONDS


def test_no_flush_before_the_pulse_boundary():
    d = BeamDwell()
    for _ in range(29):
        assert d.accumulate("bank1", "targetA", 1.0 / 60.0) is None


def test_flush_at_the_pulse_boundary_returns_the_dwell():
    d = BeamDwell()
    out = None
    for _ in range(30):
        out = d.accumulate("bank1", "targetA", 1.0 / 60.0) or out
    assert out == pytest.approx(PULSE_SECONDS, abs=1e-6)


def test_dwell_resets_after_a_flush():
    d = BeamDwell()
    for _ in range(30):
        d.accumulate("bank1", "targetA", 1.0 / 60.0)
    assert d.accumulate("bank1", "targetA", 1.0 / 60.0) is None


def test_target_change_flushes_the_partial_pulse():
    d = BeamDwell()
    for _ in range(10):
        d.accumulate("bank1", "targetA", 1.0 / 60.0)
    partial = d.accumulate("bank1", "targetB", 1.0 / 60.0)
    assert partial == pytest.approx(10.0 / 60.0, abs=1e-6)


def test_losing_the_target_flushes_the_partial_pulse():
    d = BeamDwell()
    for _ in range(10):
        d.accumulate("bank1", "targetA", 1.0 / 60.0)
    assert d.on_target_lost("bank1") == pytest.approx(10.0 / 60.0, abs=1e-6)


def test_losing_a_target_we_never_had_flushes_nothing():
    """CORRECTED DEFECT 1 (spec §7). BC's flush runs on the target-lost path
    with a stale facing of -1 and dumps full damage on the HULL at full
    shields. We drop the pulse instead."""
    d = BeamDwell()
    assert d.on_target_lost("bank1") is None


def test_banks_accumulate_independently():
    d = BeamDwell()
    for _ in range(30):
        d.accumulate("bank1", "targetA", 1.0 / 60.0)
    assert d.accumulate("bank2", "targetA", 1.0 / 60.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_beam_dwell.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.beam_dwell'`

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/beam_dwell.py
"""Beam pulse accumulator — BC applies beam damage in 0.5s pulses.

Spec: docs/superpowers/specs/2026-08-16-shield-system-redesign-design.md §6.2.
Reference: stbc_reference spec/ShieldFacingDamage.md §12.2-12.3
(reviewed-not-tested).

A beam does NOT damage continuously. Dwell accumulates while it is held on a
target; at 0.5s the accumulated dwell is flushed as one hit, and damage scales
linearly with it. The cadence matches the shield charge tick by construction.
"""
from __future__ import annotations

PULSE_SECONDS: float = 0.5   # 0x008E53E0


class BeamDwell:
    """Per-weapon dwell accumulators. Keys are caller-chosen and opaque."""

    def __init__(self) -> None:
        self._dwell: dict = {}
        self._target: dict = {}

    def accumulate(self, weapon_key, target, dt: float):
        """Add `dt` of dwell. Returns dwell to flush, or None.

        A target change flushes the partial pulse for the OLD target before
        starting the new one -- BC fires beam-off/beam-on and resets the
        accumulator on the same edge.
        """
        previous = self._target.get(weapon_key)
        if previous is not None and previous != target:
            partial = self._dwell.get(weapon_key, 0.0)
            self._dwell[weapon_key] = float(dt)
            self._target[weapon_key] = target
            return partial if partial > 0.0 else None

        self._target[weapon_key] = target
        total = self._dwell.get(weapon_key, 0.0) + float(dt)
        if total >= PULSE_SECONDS:
            self._dwell[weapon_key] = 0.0
            return total
        self._dwell[weapon_key] = total
        return None

    def on_target_lost(self, weapon_key):
        """Flush the partial pulse when the beam stops.

        CORRECTED DEFECT 1: BC flushes here with a stale facing of -1, which
        takes the HULL branch regardless of shield charge. Returning None when
        there is nothing accumulated is how we decline to reproduce that.
        """
        partial = self._dwell.pop(weapon_key, 0.0)
        self._target.pop(weapon_key, None)
        return partial if partial > 0.0 else None

    def reset(self, weapon_key) -> None:
        self._dwell.pop(weapon_key, None)
        self._target.pop(weapon_key, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_beam_dwell.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/beam_dwell.py tests/unit/test_beam_dwell.py
git commit -m "feat(shields): 0.5s beam dwell accumulator"
```

---

## Task 10: Drive the phaser path from `beam_dwell`

**Files:**
- Modify: `engine/host_loop.py` (phaser firing block around `:938-960`)
- Test: `tests/integration/test_beam_pulse_damage.py`

**Interfaces:**
- Consumes: `BeamDwell` (Task 9), `apply_hit(..., segment=...)` (Tasks 7–8).
- Produces: module-level `_beam_dwell = BeamDwell()` in `host_loop`, reset on mission swap.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_beam_pulse_damage.py
def test_beam_damage_arrives_in_pulses_not_every_tick(monkeypatch):
    """BC applies beam damage in 0.5s pulses (spec §6.2). Held for 1s at 60Hz,
    a beam must land 2 hits, not 60."""
    hits = []
    from engine.appc import combat
    monkeypatch.setattr(combat, "apply_hit",
                        lambda *a, **k: hits.append((a, k)))
    _hold_beam_on_target_for(seconds=1.0, dt=1.0 / 60.0)
    assert len(hits) == 2


def test_pulse_damage_scales_with_dwell():
    """Damage is linear in dwell, so a full pulse and two half pulses deliver
    the same total."""
    full = _beam_damage_over(seconds=1.0)
    halves = _beam_damage_over(seconds=0.5) * 2
    assert full == pytest.approx(halves, rel=1e-6)
```

Build `_hold_beam_on_target_for` and `_beam_damage_over` from the existing phaser fixtures — read `tests/integration/test_fire_secondary_chain.py` and reuse its ship/target construction.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_beam_pulse_damage.py -q`
Expected: FAIL — 60 hits, not 2

- [ ] **Step 3: Route the phaser block through the accumulator**

Near the top of `host_loop.py`:

```python
from engine.appc.beam_dwell import BeamDwell

_beam_dwell = BeamDwell()
```

In the phaser block, replace the direct `apply_hit` with:

```python
            if damage > 0:
                dwell = _beam_dwell.accumulate((id(ship), id(bank)),
                                               id(target), dt)
                if dwell is not None:
                    impact_point, impact_normal = combat._resolve_hit_point(...)
                    combat.apply_hit(target, damage * dwell, impact_point,
                              source=ship, normal=impact_normal,
                              ship_instances=ship_instances,
                              weapon_type="phaser", hardpoint_weapon=bank,
                              damage_hull=damage_hull,
                              segment=(emitter_pos, impact_point))
```

`damage` from `_phaser_damage_for_tick` is currently `rate * dt`; change that call to pass `dt=1.0` so it yields a per-second rate, and let the dwell supply the time. Add `_beam_dwell.reset(...)` to the mission-swap block beside the other per-mission resets.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_beam_pulse_damage.py tests/unit -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/integration/test_beam_pulse_damage.py
git commit -m "feat(shields): phaser damage lands in 0.5s pulses"
```

---

## Task 11: Six-facing splash absorption

**Files:**
- Modify: `engine/appc/splash_damage.py`
- Test: `tests/unit/test_splash_six_facing.py`

**Interfaces:**
- Consumes: `ShieldSubsystem.ApplyDamage` is **not** used here — splash has its own simpler rule.
- Produces: `absorb_splash(shields, damage) -> float` (remainder) in `splash_damage.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_splash_six_facing.py
import pytest
from engine.appc.splash_damage import absorb_splash
from engine.appc.subsystems import ShieldSubsystem


def _shields(charge, cap=1000.0):
    s = ShieldSubsystem("shields")
    s.TurnOn()
    for i in range(ShieldSubsystem.NUM_SHIELDS):
        s.SetMaxShields(i, cap)
        s.SetCurrentShields(i, charge)
    return s


def test_each_facing_absorbs_up_to_one_sixth():
    """Splash 0x00593C10: no geometry, no facing choice, no ramp -- every
    facing absorbs up to 1/6 (0x0088BACC), capped at what it holds."""
    s = _shields(1000.0)
    assert absorb_splash(s, 600.0) == pytest.approx(0.0)
    for i in range(6):
        assert s.GetCurrentShields(i) == pytest.approx(900.0)


def test_remainder_survives_when_facings_cannot_cover_their_share():
    s = _shields(10.0)
    remainder = absorb_splash(s, 600.0)
    assert remainder == pytest.approx(600.0 - 60.0)
    for i in range(6):
        assert s.GetCurrentShields(i) == 0.0


def test_offline_shields_absorb_nothing():
    s = _shields(1000.0)
    s.TurnOff()
    assert absorb_splash(s, 600.0) == pytest.approx(600.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_splash_six_facing.py -q`
Expected: FAIL — `ImportError: cannot import name 'absorb_splash'`

- [ ] **Step 3: Write the implementation**

```python
SPLASH_SHARE = 1.0 / 6.0     # 0x0088BACC


def absorb_splash(shields, damage: float) -> float:
    """Splash absorption: each facing takes up to 1/6, capped at its charge.

    BC 0x00593C10. Deliberately NOT the pass-through ramp -- splash has no
    geometry and selects no facing, so there is no fraction to ramp on.
    Returns the damage that survives all six facings.
    """
    from engine.core.ids import implements
    if shields is None or not implements(shields, "ApplyDamage"):
        return float(damage)
    if not shields.IsOn() or shields.IsDisabled() or shields.IsDestroyed():
        return float(damage)
    remaining = float(damage)
    share = float(damage) * SPLASH_SHARE
    for i in range(shields.NUM_SHIELDS):
        take = min(share, shields.GetCurrentShields(i))
        if take <= 0.0:
            continue
        shields.SetCurrentShields(i, shields.GetCurrentShields(i) - take)
        remaining -= take
    return max(0.0, remaining)
```

Call it from the splash path before routing the remainder into `apply_hit(..., segment=None)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_splash_six_facing.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/splash_damage.py tests/unit/test_splash_six_facing.py
git commit -m "feat(shields): splash absorbs one sixth per facing"
```

---

## Task 12: One source of truth for the shield shape

**Files:**
- Modify: `engine/host_loop.py` (`_cache_shield_hull_box` → cache a `ShieldEllipsoid`)
- Modify: `engine/appc/combat.py` (`_shield_ellipsoid_for` reads the cache)
- Modify: `engine/shields.py` (`register_ship_shield` derives its half-extents from the same ellipsoid)
- Test: `tests/unit/test_shield_shape_single_source.py`

**Interfaces:**
- Consumes: `ellipsoid_for_bound` (Task 1), `combat._shield_ellipsoid_for` (Task 7 — already defined there; this task does **not** introduce it).
- Produces: `engine/shields.py:register_ship_shield` derives its extents from `ellipsoid_for_bound`, so the drawn bubble and the gameplay bubble are one surface.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_shield_shape_single_source.py
import math
import pytest
from engine.appc import combat
from engine.appc.shield_geometry import ELLIPSOID_AXIS_SCALE


def test_gameplay_and_render_shapes_come_from_one_definition():
    """The sqrt(3) used to live in the renderer (kShieldEllipsoidAxisScale)
    while the box lived in host_loop -- two half-definitions of one surface.
    Both now derive from shield_geometry."""
    assert ELLIPSOID_AXIS_SCALE == pytest.approx(math.sqrt(3.0))


def test_ellipsoid_tracks_the_ships_live_scale():
    ship = _ship_with_bound(centre=(0.0, 0.0, 0.0),
                            half_extents=(100.0, 200.0, 50.0))
    ship.SetScale(2.0)
    ell = combat._shield_ellipsoid_for(ship)
    assert ell.semi_axes[0] == pytest.approx(
        100.0 * ELLIPSOID_AXIS_SCALE * 2.0)
```

Build `_ship_with_bound` by mirroring how `tests/` currently seeds `_shield_hull_box`; grep for it and reuse that construction.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_shield_shape_single_source.py -q`
Expected: FAIL — `AttributeError: module 'engine.appc.combat' has no attribute '_shield_ellipsoid_for'`

- [ ] **Step 3: Implement**

`combat._shield_ellipsoid_for` already exists from Task 7 — do not redefine it. This task unifies the **render** side.

In `engine/shields.py:register_ship_shield`, replace the raw AABB half-extents with the ellipsoid's semi-axes so the native pass no longer re-applies √3 of its own:

```python
    from engine.appc.shield_geometry import ellipsoid_for_bound
    ell = ellipsoid_for_bound(aabb_center, aabb_half_extents)
    if ell is None:
        return
    host.shield_register(
        instance_id=instance_id,
        mode=mode,
        decay_seconds=float(decay),
        default_color=color,
        aabb_center=ell.centre,
        aabb_half_extents=ell.semi_axes,
        ...
    )
```

Then remove the axis scaling on the native side so it is applied exactly once. Grep `kShieldEllipsoidAxisScale` in `native/src/renderer/` and delete its multiplication at the point of use, leaving the constant only if something else reads it.

⚠️ Shader or `.cc` edits need `cmake -B build -S .` before `cmake --build build -j` — see CLAUDE.md.

- [ ] **Step 4: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures.` Any failure not in `tests/known_failures.txt` is a regression from this change.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/combat.py engine/host_loop.py engine/shields.py tests/unit/test_shield_shape_single_source.py
git commit -m "refactor(shields): one definition of the shield shape for gameplay and render"
```

---

## Final verification

- [ ] Run `scripts/check_tests.sh` — both suites, diffed against `tests/known_failures.txt`.
- [ ] Confirm the tested anchor holds end to end: full facings ⇒ **exactly** 0.0 hull damage.
- [ ] Hand to Mark for the live pass. The three things most likely to surprise: overall time-to-kill (a weakened facing now leaks up to 60 %), shield recovery under power diversion, and beam damage arriving in visible 0.5 s steps.
- [ ] Open items deliberately left: quantum threading (spec §6.1), facing names (probe q19), hull/subsystem distribution, the mode multiplier table.
