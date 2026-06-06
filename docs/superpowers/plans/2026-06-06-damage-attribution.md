# Damage Attribution — Spherical Splash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `engine.appc.combat.apply_hit`'s winner-takes-all subsystem damage model with the spherical-splash multi-subsystem allocation specified in [`docs/superpowers/specs/2026-06-06-damage-attribution-design.md`](../specs/2026-06-06-damage-attribution-design.md).

**Architecture:** Build six small helpers in `engine/appc/combat.py` (splash radius resolver, body→world position transform, candidate iterator, weight function, plus a primary-subsystem picker for VFX dispatch), wire them together in a rewritten `apply_hit`, and delete `pick_target_subsystem`. Extend `WeaponHitEvent` with `normal` and `radius` fields. Update tests that assert winner-takes-all behaviour. Add one integration test that proves multi-subsystem damage on a real Galaxy.

**Tech Stack:** Python 3.12 (engine), pytest + pytest-xdist for tests, `host.ray_trace_mesh` already implemented in `native/src/renderer/ray_trace.cc`, SDK property accessors via the shim `App.py` at the project root.

**Out of scope for this plan:** the live-game instrumentation logger described in spec §6 (verification of the hardpoint-vs-payload DRF combination). That is a separate plan, written when the user is ready to run the original game.

---

## Files touched

| File | Purpose |
|---|---|
| `engine/appc/combat.py` | Add 6 helpers; rewrite `apply_hit`; delete `pick_target_subsystem`. |
| `engine/appc/events.py` | Add `_normal` and `_radius` fields + getters/setters to `WeaponHitEvent`. |
| `tests/unit/test_combat.py` | NEW — unit tests for the new helpers (test_combat_hit_resolution.py and friends already exist; new file collects splash-specific tests). |
| `tests/unit/test_apply_hit_routing.py` | UPDATE — rewrite assertions for splash allocation. |
| `tests/unit/test_weapon_hit_event.py` | UPDATE — assert `radius` and `normal` round-trip. |
| `tests/integration/test_splash_attribution_galaxy.py` | NEW — full-stack test: fire phaser at Galaxy, assert multiple subsystems damaged. |
| `docs/superpowers/specs/2026-06-01-subsystem-damage-propagation-design.md` | Add "superseded" marker to attribution sections. |

Tests in `tests/unit/` that *only* observed shields-→-hull bleed without asserting picker behaviour should remain green without modification. Tests that explicitly assert "picker returned X" need updating; the audit task below catches those.

---

## Task ordering

Tasks 1–6 build helpers, each independently testable. Task 7 wires them into `apply_hit`. Task 8 deletes the old picker. Task 9 audits and updates broken downstream tests. Task 10 is the integration test. Task 11 is the spec marker.

---

### Task 1: `weapon_splash_radius` helper

Resolves `R_hit` from `(hardpoint_weapon, payload_template)` per spec §3.2.

**Files:**
- Modify: `engine/appc/combat.py` (add helper near the top, after `ray_sphere_entry`)
- Create: `tests/unit/test_combat_splash_radius.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_combat_splash_radius.py`:

```python
"""Tests for weapon_splash_radius — the R_hit resolver from spec §3.2."""

from engine.appc.combat import PHASER_DEFAULT_DAMAGE_RADIUS, weapon_splash_radius


class _FakeWeaponProperty:
    def __init__(self, drf):
        self._drf = drf

    def GetDamageRadiusFactor(self):
        return self._drf


class _FakePayloadTemplate:
    def __init__(self, drf):
        self._drf = drf

    def GetDamageRadiusFactor(self):
        return self._drf


def test_hardpoint_drf_overrides_payload_when_set():
    hp = _FakeWeaponProperty(0.20)
    payload = _FakePayloadTemplate(0.13)
    assert weapon_splash_radius(hp, payload) == 0.20


def test_payload_drf_used_when_hardpoint_zero():
    hp = _FakeWeaponProperty(0.0)
    payload = _FakePayloadTemplate(0.13)
    assert weapon_splash_radius(hp, payload) == 0.13


def test_payload_drf_used_when_hardpoint_none():
    payload = _FakePayloadTemplate(0.14)
    assert weapon_splash_radius(None, payload) == 0.14


def test_phaser_default_when_both_absent():
    assert weapon_splash_radius(None, None) == PHASER_DEFAULT_DAMAGE_RADIUS
    assert PHASER_DEFAULT_DAMAGE_RADIUS == 0.15


def test_phaser_default_when_both_zero():
    hp = _FakeWeaponProperty(0.0)
    payload = _FakePayloadTemplate(0.0)
    assert weapon_splash_radius(hp, payload) == PHASER_DEFAULT_DAMAGE_RADIUS


def test_akira_torp_uses_large_hardpoint_value():
    # Akira hardpoint DRF = 0.60, photon payload DRF = 0.13.
    # Override hypothesis: result is 0.60.
    hp = _FakeWeaponProperty(0.60)
    payload = _FakePayloadTemplate(0.13)
    assert weapon_splash_radius(hp, payload) == 0.60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_combat_splash_radius.py -v`
Expected: ImportError on `weapon_splash_radius` / `PHASER_DEFAULT_DAMAGE_RADIUS`.

- [ ] **Step 3: Implement the helper**

Add to `engine/appc/combat.py` (after line 50, before `_resolve_hit_point`):

```python
PHASER_DEFAULT_DAMAGE_RADIUS = 0.15
"""Fallback splash radius (game units) used only when neither hardpoint nor
payload defines a SetDamageRadiusFactor. Phaser hardpoints in stock SDK
always write 0.15 explicitly, so this default is reached only by
hand-authored weapons that forget to declare a radius.
"""


def weapon_splash_radius(hardpoint_weapon, payload_template) -> float:
    """Resolve R_hit per spec §3.2.

    hardpoint_weapon: WeaponProperty on the firing ship's hardpoint, or None.
    payload_template: projectile-type template (e.g. PhotonTorpedo), or None
                      for phasers / non-projectile weapons.

    Returns the splash radius in game units. Hardpoint DRF overrides payload
    DRF when both are set and non-zero; falls back to the phaser default
    (0.15 GU) when neither is available.
    """
    if hardpoint_weapon is not None and hasattr(hardpoint_weapon, "GetDamageRadiusFactor"):
        drf = hardpoint_weapon.GetDamageRadiusFactor()
        if drf and drf > 0.0:
            return float(drf)
    if payload_template is not None and hasattr(payload_template, "GetDamageRadiusFactor"):
        drf = payload_template.GetDamageRadiusFactor()
        if drf and drf > 0.0:
            return float(drf)
    return PHASER_DEFAULT_DAMAGE_RADIUS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_combat_splash_radius.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_combat_splash_radius.py
git commit -m "feat(combat): add weapon_splash_radius resolver per spec §3.2"
```

---

### Task 2: Extend `WeaponHitEvent` with `radius` and `normal`

Carry the resolved splash radius and surface normal on the broadcast event so VFX, persistent damage records, and other downstream consumers don't have to re-resolve.

**Files:**
- Modify: `engine/appc/events.py` (class `WeaponHitEvent` around line 89)
- Modify: `tests/unit/test_weapon_hit_event.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_weapon_hit_event.py`:

```python
def test_weapon_hit_event_radius_round_trip():
    from engine.appc.events import WeaponHitEvent
    evt = WeaponHitEvent()
    assert evt.GetRadius() == 0.0
    evt.SetRadius(0.15)
    assert evt.GetRadius() == 0.15


def test_weapon_hit_event_normal_round_trip():
    from engine.appc.events import WeaponHitEvent
    from engine.appc.math import TGPoint3
    evt = WeaponHitEvent()
    assert evt.GetNormal() is None
    n = TGPoint3(0.0, 0.0, 1.0)
    evt.SetNormal(n)
    out = evt.GetNormal()
    assert out is n  # identity, not a copy
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_weapon_hit_event.py::test_weapon_hit_event_radius_round_trip tests/unit/test_weapon_hit_event.py::test_weapon_hit_event_normal_round_trip -v`
Expected: AttributeError on `GetRadius` / `GetNormal`.

- [ ] **Step 3: Extend the class**

In `engine/appc/events.py`, modify `WeaponHitEvent.__init__` and add accessor pairs:

```python
class WeaponHitEvent(TGEvent):
    """Weapon-impact event.  Broadcast by engine.appc.combat.apply_hit
    after damage is routed.  Mission scripts subscribe to ET_WEAPON_HIT
    (per-ship or broadcast) to react — e.g. MissionLib.FriendlyFireHandler
    triggers XO dialogue when the player damages a friendly NPC.

    Inherits TGEvent's _source / Set/GetSource for the firing ship; the
    weapon-specific surface adds target, damage, hit-point, subsystem,
    surface normal, and splash radius (the radius the attribution
    resolver used for this hit, per damage-attribution spec §3.2).
    """
    def __init__(self):
        super().__init__()
        self._event_type = ET_WEAPON_HIT
        self._target = None
        self._damage: float = 0.0
        self._hit_point = None
        self._subsystem = None
        self._normal = None
        self._radius: float = 0.0

    def GetTarget(self):              return self._target
    def SetTarget(self, tgt) -> None: self._target = tgt
    def GetDamage(self) -> float:     return self._damage
    def SetDamage(self, v) -> None:   self._damage = float(v)
    def GetHitPoint(self):            return self._hit_point
    def SetHitPoint(self, p) -> None: self._hit_point = p
    def GetSubsystem(self):           return self._subsystem
    def SetSubsystem(self, s) -> None: self._subsystem = s
    def GetNormal(self):              return self._normal
    def SetNormal(self, n) -> None:   self._normal = n
    def GetRadius(self) -> float:     return self._radius
    def SetRadius(self, r) -> None:   self._radius = float(r)

    def GetFiringObject(self):
        """SDK alias for GetSource() — SelectTarget's DamageEvent
        handler reads via GetFiringObject."""
        return self.GetSource()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_weapon_hit_event.py -v`
Expected: all tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/events.py tests/unit/test_weapon_hit_event.py
git commit -m "feat(events): WeaponHitEvent carries surface normal and splash radius"
```

---

### Task 3: `_iter_subsystems` helper

Walk `ship.GetSubsystems()` plus each weapon-system parent's `_children`. Skips the hull (it's handled unconditionally outside this iterator).

**Files:**
- Modify: `engine/appc/combat.py`
- Create: `tests/unit/test_combat_iter_subsystems.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_combat_iter_subsystems.py`:

```python
"""Tests for combat._iter_subsystems — walks all leaf subsystems of a ship."""

from engine.appc.combat import _iter_subsystems


class _FakeSub:
    def __init__(self, name, children=None):
        self.name = name
        if children is not None:
            self._children = list(children)


class _FakeHull(_FakeSub):
    pass


class _FakeShip:
    def __init__(self, hull, subsystems):
        self._hull = hull
        self._subs = list(subsystems)

    def GetHull(self):
        return self._hull

    def GetSubsystems(self):
        return list(self._subs)


def _names(subs):
    return [s.name for s in subs]


def test_iter_subsystems_yields_top_level_plus_children_skipping_hull():
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")
    phaser_bank_a = _FakeSub("PhaserA")
    phaser_bank_b = _FakeSub("PhaserB")
    weapons = _FakeSub("Weapons", children=[phaser_bank_a, phaser_bank_b])
    ship = _FakeShip(hull=hull, subsystems=[hull, sensors, weapons])

    out = list(_iter_subsystems(ship))

    assert _names(out) == ["Sensors", "Weapons", "PhaserA", "PhaserB"]
    assert hull not in out


def test_iter_subsystems_handles_no_children_attr():
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")  # no _children attribute
    ship = _FakeShip(hull=hull, subsystems=[hull, sensors])

    out = list(_iter_subsystems(ship))

    assert _names(out) == ["Sensors"]


def test_iter_subsystems_handles_none_entries():
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")
    ship = _FakeShip(hull=hull, subsystems=[hull, None, sensors])

    out = list(_iter_subsystems(ship))

    assert _names(out) == ["Sensors"]


def test_iter_subsystems_legacy_fallback_via_child_subsystem_index():
    """Stub ships that predate GetSubsystems still get walked via the
    legacy GetNumChildSubsystems / GetChildSubsystem path. Hull is still
    excluded.
    """
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")
    weapons = _FakeSub("Weapons")

    class _LegacyShip:
        def GetHull(self):
            return hull

        def GetNumChildSubsystems(self):
            return 3

        def GetChildSubsystem(self, i):
            return [hull, sensors, weapons][i]

    out = list(_iter_subsystems(_LegacyShip()))

    assert _names(out) == ["Sensors", "Weapons"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_combat_iter_subsystems.py -v`
Expected: ImportError on `_iter_subsystems`.

- [ ] **Step 3: Implement the helper**

Add to `engine/appc/combat.py` (after `_diff_state`):

```python
def _iter_subsystems(ship):
    """Yield every leaf subsystem on `ship`, excluding the hull.

    Walks `ship.GetSubsystems()` and for each top-level subsystem also
    yields the entries of its `_children` list (weapon-system parents
    expose hardpoint children there). Falls back to the legacy
    `GetNumChildSubsystems` / `GetChildSubsystem(i)` API for stub ships
    that predate `GetSubsystems`.

    Hull is excluded because the attribution resolver damages it
    unconditionally outside the iteration loop.
    """
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None

    if hasattr(ship, "GetSubsystems"):
        for s in ship.GetSubsystems():
            if s is None or s is hull:
                continue
            yield s
            children = getattr(s, "_children", None)
            if children:
                for c in children:
                    if c is not None and c is not hull:
                        yield c
        return

    n = ship.GetNumChildSubsystems() if hasattr(ship, "GetNumChildSubsystems") else 0
    for i in range(n):
        s = ship.GetChildSubsystem(i)
        if s is not None and s is not hull:
            yield s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_combat_iter_subsystems.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_combat_iter_subsystems.py
git commit -m "feat(combat): add _iter_subsystems helper for splash candidate walk"
```

---

### Task 4: `_subsystem_world_position` helper

Transform a subsystem's body-frame position to world space via the column-vector rotation convention.

**Files:**
- Modify: `engine/appc/combat.py`
- Create: `tests/unit/test_combat_subsystem_world_position.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_combat_subsystem_world_position.py`:

```python
"""Tests for combat._subsystem_world_position — body→world via column R."""

from engine.appc.combat import _subsystem_world_position
from engine.appc.math import TGMatrix3, TGPoint3


class _FakeSub:
    def __init__(self, pos):
        self._pos = pos

    def GetPosition(self):
        return self._pos


class _FakeShip:
    def __init__(self, location, rotation=None):
        self._loc = location
        self._rot = rotation

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


def test_identity_rotation_passes_position_through_plus_ship_origin():
    ship = _FakeShip(location=TGPoint3(10.0, 20.0, 30.0),
                     rotation=TGMatrix3())  # identity
    sub = _FakeSub(TGPoint3(1.0, 2.0, 3.0))

    p = _subsystem_world_position(ship, sub)

    assert p.x == 11.0
    assert p.y == 22.0
    assert p.z == 33.0


def test_y_rotation_90deg_maps_body_x_to_world_minus_z():
    """Column-vector convention: R · v_body = v_world.
    MakeYRotation(+pi/2) rotates body-X onto world-(-Z).
    """
    import math
    R = TGMatrix3()
    R.MakeYRotation(math.pi / 2.0)
    ship = _FakeShip(location=TGPoint3(0.0, 0.0, 0.0), rotation=R)
    sub = _FakeSub(TGPoint3(1.0, 0.0, 0.0))

    p = _subsystem_world_position(ship, sub)

    assert abs(p.x - 0.0) < 1e-6
    assert abs(p.y - 0.0) < 1e-6
    assert abs(p.z - (-1.0)) < 1e-6


def test_no_rotation_attribute_treats_R_as_identity():
    """Legacy fakes without GetWorldRotation: body == world."""
    class _NoRotShip:
        def GetWorldLocation(self):
            return TGPoint3(5.0, 5.0, 5.0)

    sub = _FakeSub(TGPoint3(1.0, 1.0, 1.0))
    p = _subsystem_world_position(_NoRotShip(), sub)

    assert p.x == 6.0
    assert p.y == 6.0
    assert p.z == 6.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_combat_subsystem_world_position.py -v`
Expected: ImportError on `_subsystem_world_position`.

- [ ] **Step 3: Implement the helper**

Add to `engine/appc/combat.py` (after `_body_frame_delta`):

```python
def _subsystem_world_position(ship, subsystem):
    """Return the world-space position of `subsystem` on `ship`.

    Per CLAUDE.md's column-vector convention, body→world is
    `v_world = R · v_body`. SDK `TGPoint3.MultMatrixLeft(R)` already
    computes that in place. We construct a fresh point to avoid
    mutating the subsystem's stored position.

    Legacy fakes without `GetWorldRotation` get identity R, so
    `world_pos = ship_pos + body_pos`.
    """
    ship_pos = ship.GetWorldLocation()
    body_pos = subsystem.GetPosition()
    if not hasattr(ship, "GetWorldRotation"):
        return TGPoint3(
            ship_pos.x + body_pos.x,
            ship_pos.y + body_pos.y,
            ship_pos.z + body_pos.z,
        )
    R = ship.GetWorldRotation()
    p = TGPoint3(body_pos.x, body_pos.y, body_pos.z)
    p.MultMatrixLeft(R)
    p.x += ship_pos.x
    p.y += ship_pos.y
    p.z += ship_pos.z
    return p
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_combat_subsystem_world_position.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_combat_subsystem_world_position.py
git commit -m "feat(combat): add _subsystem_world_position body->world helper"
```

---

### Task 5: `_splash_weight` helper

Linear falloff weight per spec §3.4: `w = clamp((R_sub + R_hit − d) / R_hit, 0, 1)`.

**Files:**
- Modify: `engine/appc/combat.py`
- Create: `tests/unit/test_combat_splash_weight.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_combat_splash_weight.py`:

```python
"""Tests for combat._splash_weight — linear falloff per spec §3.4."""

from engine.appc.combat import _splash_weight


def test_impact_at_subsystem_centre_yields_full_weight():
    # d=0, R_sub=0.3, R_hit=0.15 → (0.3+0.15-0)/0.15 = 3.0 → clamped to 1.0
    assert _splash_weight(r_sub=0.3, r_hit=0.15, d=0.0) == 1.0


def test_impact_at_subsystem_surface_still_full_weight():
    # d=R_sub, formula yields R_hit/R_hit = 1.0 exactly
    assert _splash_weight(r_sub=0.3, r_hit=0.15, d=0.3) == 1.0


def test_impact_just_outside_subsystem_surface_starts_falloff():
    # d = R_sub + half R_hit, weight = 0.5
    w = _splash_weight(r_sub=0.3, r_hit=0.15, d=0.3 + 0.075)
    assert abs(w - 0.5) < 1e-9


def test_impact_at_splash_edge_yields_zero():
    # d = R_sub + R_hit
    assert _splash_weight(r_sub=0.3, r_hit=0.15, d=0.45) == 0.0


def test_impact_beyond_splash_edge_yields_zero():
    assert _splash_weight(r_sub=0.3, r_hit=0.15, d=1.0) == 0.0


def test_zero_radius_subsystem_only_hit_when_d_inside_r_hit():
    # R_sub=0: w = (0 + 0.15 - d) / 0.15
    assert _splash_weight(r_sub=0.0, r_hit=0.15, d=0.0) == 1.0
    assert abs(_splash_weight(r_sub=0.0, r_hit=0.15, d=0.075) - 0.5) < 1e-9
    assert _splash_weight(r_sub=0.0, r_hit=0.15, d=0.15) == 0.0


def test_r_hit_zero_safe_no_division_by_zero():
    # R_hit=0 is a degenerate weapon; guard returns 0.0 rather than divide.
    assert _splash_weight(r_sub=0.3, r_hit=0.0, d=0.0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_combat_splash_weight.py -v`
Expected: ImportError on `_splash_weight`.

- [ ] **Step 3: Implement the helper**

Add to `engine/appc/combat.py` (after `_subsystem_world_position`):

```python
def _splash_weight(r_sub: float, r_hit: float, d: float) -> float:
    """Linear falloff weight for splash damage attribution per spec §3.4.

    `r_sub`  — subsystem catchment radius (from `subsystem.GetRadius()`)
    `r_hit`  — weapon splash radius (from `weapon_splash_radius()`)
    `d`      — distance from impact point to subsystem world position

    Returns 1.0 when the impact is inside (or on the surface of) the
    subsystem sphere, decays linearly to 0 at the combined-sphere edge,
    and is exactly 0 at or beyond. A zero `r_hit` degenerate weapon
    returns 0.0 with no division by zero.
    """
    if r_hit <= 0.0:
        return 0.0
    raw = (r_sub + r_hit - d) / r_hit
    if raw <= 0.0:
        return 0.0
    if raw >= 1.0:
        return 1.0
    return raw
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_combat_splash_weight.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_combat_splash_weight.py
git commit -m "feat(combat): add _splash_weight linear falloff helper"
```

---

### Task 6: `_pick_primary_subsystem_for_dispatch` helper

`hit_feedback.dispatch` expects a single "subsystem" arg + a single transition. In the splash model we can damage many. Define "primary" as the candidate with the highest weight (ties broken by iteration order — first wins). This preserves the dispatch contract without altering severity classification.

**Files:**
- Modify: `engine/appc/combat.py`
- Create: `tests/unit/test_combat_primary_for_dispatch.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_combat_primary_for_dispatch.py`:

```python
"""Tests for combat._pick_primary_subsystem_for_dispatch.

Used to give hit_feedback.dispatch a single subsystem + transition even
though splash allocation damages many subsystems per hit.
"""

from engine.appc.combat import _pick_primary_subsystem_for_dispatch


def test_returns_highest_weight_candidate():
    allocations = [("sensors", 0.3), ("warp_core", 0.9), ("impulse", 0.5)]
    assert _pick_primary_subsystem_for_dispatch(allocations) == "warp_core"


def test_ties_resolved_by_first_in_list():
    allocations = [("sensors", 0.7), ("warp_core", 0.7)]
    assert _pick_primary_subsystem_for_dispatch(allocations) == "sensors"


def test_empty_allocations_returns_none():
    assert _pick_primary_subsystem_for_dispatch([]) is None


def test_all_zero_weights_returns_none():
    allocations = [("sensors", 0.0), ("warp_core", 0.0)]
    assert _pick_primary_subsystem_for_dispatch(allocations) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_combat_primary_for_dispatch.py -v`
Expected: ImportError on `_pick_primary_subsystem_for_dispatch`.

- [ ] **Step 3: Implement the helper**

Add to `engine/appc/combat.py` (after `_splash_weight`):

```python
def _pick_primary_subsystem_for_dispatch(allocations):
    """Return the subsystem with the highest splash weight in
    `allocations`, ties broken by first appearance, or None if the list
    is empty or every weight is zero.

    `allocations` is an iterable of `(subsystem, weight)` tuples
    produced by the apply_hit resolver loop. The hit_feedback.dispatch
    consumer wants a single subsystem so the per-stage severity
    classifier (shield-only / hull-pen / critical-fail) can decide
    which subsystem's state transition to report.
    """
    primary = None
    best = 0.0
    for sub, w in allocations:
        if w > best:
            best = w
            primary = sub
    return primary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_combat_primary_for_dispatch.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_combat_primary_for_dispatch.py
git commit -m "feat(combat): add _pick_primary_subsystem_for_dispatch helper"
```

---

### Task 7: Rewrite `apply_hit` to use splash allocation

Replace the picker → single subsystem → hull-bleed path with the splash model. Hull always takes full post-shield damage. Subsystems take `D · w_i` independently.

**Files:**
- Modify: `engine/appc/combat.py` (`apply_hit` function around line 242)
- Create: `tests/unit/test_apply_hit_splash.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_apply_hit_splash.py`:

```python
"""Tests for the rewritten apply_hit — splash allocation per spec.

These tests use minimal fakes to keep the focus on attribution. They
cover:
- hull always damaged when post-shield > 0
- multiple subsystems damaged when their spheres overlap the splash
- weight falloff produces proportional damage
- shield-only hit (no bleed-through) leaves hull and subsystems untouched
- WeaponHitEvent carries the radius and normal
"""

import pytest

from engine.appc.combat import apply_hit
from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGMatrix3, TGPoint3
import App


class _FakeSub:
    def __init__(self, name, pos, radius, max_condition=1000.0):
        self.name = name
        self._pos = pos
        self._radius = radius
        self._max = max_condition
        self._condition = max_condition

    def GetPosition(self):  return self._pos
    def GetRadius(self):    return self._radius
    def GetCondition(self): return self._condition
    def GetMaxCondition(self): return self._max
    def IsDamaged(self):    return self._condition < self._max
    def IsDisabled(self):   return False
    def IsDestroyed(self):  return False


class _FakeHull(_FakeSub):
    pass


class _FakeShip(App.TGEventHandlerObject):
    def __init__(self, hull, subsystems, location=None, rotation=None):
        super().__init__()
        self._hull = hull
        self._subs = list(subsystems)
        self._loc = location or TGPoint3(0.0, 0.0, 0.0)
        self._rot = rotation or TGMatrix3()
        self.damage_log = []

    def GetHull(self):          return self._hull
    def GetSubsystems(self):    return list(self._subs)
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetShields(self):       return None  # shields off for these tests

    def DamageSystem(self, sub, amount):
        self.damage_log.append((sub.name, amount))
        sub._condition = max(0.0, sub._condition - amount)


def _captured_event(holder):
    """Patch App.g_kEventManager.AddEvent to capture the broadcast event."""
    orig = App.g_kEventManager.AddEvent
    def capture(evt):
        holder.append(evt)
        return orig(evt)
    App.g_kEventManager.AddEvent = capture
    return orig


@pytest.fixture
def restore_event_manager():
    orig = App.g_kEventManager.AddEvent
    yield
    App.g_kEventManager.AddEvent = orig


def test_hull_always_takes_full_post_shield_damage(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    far_sub = _FakeSub("FarSub", TGPoint3(10.0, 0, 0), radius=0.1)
    ship = _FakeShip(hull=hull, subsystems=[hull, far_sub])

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=100.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=None)

    names = [e[0] for e in ship.damage_log]
    assert "Hull" in names
    hull_amount = next(amt for n, amt in ship.damage_log if n == "Hull")
    assert hull_amount == 100.0
    # FarSub well outside splash, no damage to it.
    assert "FarSub" not in names


def test_subsystem_inside_splash_takes_weighted_damage(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    # Sensor at (0.3, 0, 0), R=0.28; hit at (0.3, 0, 0) → centre, w=1.0
    sensor = _FakeSub("Sensors", TGPoint3(0.3, 0, 0), radius=0.28)
    ship = _FakeShip(hull=hull, subsystems=[hull, sensor])

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=100.0, hit_point=TGPoint3(0.3, 0.0, 0.0),
              source=None, normal=None)

    sensor_amount = next(amt for n, amt in ship.damage_log if n == "Sensors")
    assert sensor_amount == pytest.approx(100.0)


def test_subsystem_outside_splash_takes_no_damage(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    # Sensor at (0.3, 0, 0), R=0.28; hit at (5.0, 0, 0) → far outside.
    sensor = _FakeSub("Sensors", TGPoint3(0.3, 0, 0), radius=0.28)
    ship = _FakeShip(hull=hull, subsystems=[hull, sensor])

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=100.0, hit_point=TGPoint3(5.0, 0.0, 0.0),
              source=None, normal=None)

    names = [e[0] for e in ship.damage_log]
    assert "Sensors" not in names
    assert "Hull" in names  # hull always damaged


def test_multiple_overlapping_subsystems_each_take_damage_independently(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    a = _FakeSub("A", TGPoint3(0.2, 0, 0), radius=0.3)
    b = _FakeSub("B", TGPoint3(-0.2, 0, 0), radius=0.3)
    ship = _FakeShip(hull=hull, subsystems=[hull, a, b])

    holder = []
    _captured_event(holder)

    # Hit at origin: 0.2 from A's centre (inside R_A=0.3 → w=1.0)
    # and 0.2 from B's centre (inside R_B=0.3 → w=1.0). Both take full.
    apply_hit(ship, damage=50.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=None)

    a_amount = next(amt for n, amt in ship.damage_log if n == "A")
    b_amount = next(amt for n, amt in ship.damage_log if n == "B")
    hull_amount = next(amt for n, amt in ship.damage_log if n == "Hull")

    assert a_amount == pytest.approx(50.0)
    assert b_amount == pytest.approx(50.0)
    assert hull_amount == pytest.approx(50.0)
    # Total applied (150) exceeds incoming (50) — by design (independent allocation).


def test_weapon_hit_event_carries_radius_and_normal(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    ship = _FakeShip(hull=hull, subsystems=[hull])

    holder = []
    _captured_event(holder)
    normal = TGPoint3(1.0, 0.0, 0.0)

    apply_hit(ship, damage=10.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=normal)

    assert len(holder) == 1
    evt = holder[0]
    # No hardpoint or payload passed → phaser default 0.15
    assert evt.GetRadius() == 0.15
    assert evt.GetNormal() is normal


def test_apply_hit_accepts_optional_hardpoint_and_payload(restore_event_manager):
    """apply_hit signature gains hardpoint_weapon= and payload_template=
    kwargs so callers (phaser firing, projectile collision) can supply
    the DRF resolver inputs."""
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    ship = _FakeShip(hull=hull, subsystems=[hull])

    class _Hp:
        def GetDamageRadiusFactor(self): return 0.20

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=10.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=None, hardpoint_weapon=_Hp())

    assert holder[0].GetRadius() == 0.20
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_apply_hit_splash.py -v`
Expected: Mix of failures — old signature lacks `hardpoint_weapon=`, hull damage path is bleed-only, etc.

- [ ] **Step 3: Rewrite `apply_hit`**

Replace the body of `apply_hit` in `engine/appc/combat.py` (lines 242–346) with:

```python
def apply_hit(ship, damage: float, hit_point, source, *,
              normal=None, host=None, ship_instances=None,
              weapon_type: str | None = None,
              hardpoint_weapon=None, payload_template=None) -> None:
    """Apply `damage` to `ship` per the spherical-splash attribution
    model in docs/superpowers/specs/2026-06-06-damage-attribution-design.md.

    Flow:
    1. Resolve splash radius `R_hit` from (hardpoint_weapon, payload_template).
    2. Apply shield attenuation on the impact-direction face.
    3. Damage the hull at full post-shield damage (unconditional).
    4. Walk every non-hull subsystem; for each whose damage sphere
       intersects the splash sphere, apply `D · w_i` independently.
    5. Dispatch hit_feedback with shield / subsystem / hull totals and
       the highest-weight subsystem as the "primary" for severity
       classification.
    6. Broadcast WeaponHitEvent carrying hit point, normal, splash
       radius, and primary subsystem.

    Kwargs:
        normal              — TGPoint3 surface normal at hit_point (mesh
                              trace), or None.
        host, ship_instances — passed to hit_feedback.dispatch.
        weapon_type         — "phaser" / "torpedo" / None. Used by dispatch
                              for audio routing.
        hardpoint_weapon    — WeaponProperty on the firing ship's hardpoint
                              (used to resolve R_hit). None for legacy callers.
        payload_template    — projectile-type template (used to resolve R_hit
                              when hardpoint DRF is not set). None for phasers.
    """
    from engine.appc.events import WeaponHitEvent
    from engine.appc import hit_feedback
    import App

    r_hit = weapon_splash_radius(hardpoint_weapon, payload_template)

    # 1. Shields take the first bite. Identical to the pre-splash flow.
    remaining = float(damage)
    absorbed_shields = 0.0
    shields = ship.GetShields() if hasattr(ship, "GetShields") else None
    shields_on = bool(getattr(shields, "IsOn", lambda: 1)()) if shields is not None else False
    shields_disabled = bool(getattr(shields, "IsDisabled", lambda: 0)()) if shields is not None else False
    shields_destroyed = bool(getattr(shields, "IsDestroyed", lambda: 0)()) if shields is not None else False
    shields_online = (shields is not None and shields_on
                      and not shields_disabled and not shields_destroyed)
    if shields_online and hasattr(shields, "ApplyDamage"):
        face = _shield_face_from_hit_point(ship, hit_point)
        before = remaining
        remaining = shields.ApplyDamage(face, remaining)
        absorbed_shields = before - remaining

    post_shield = remaining
    absorbed_hull = 0.0
    absorbed_subsystem_total = 0.0
    allocations: list = []  # (subsystem, weight) for primary picking
    primary_transition = None

    hull = ship.GetHull() if hasattr(ship, "GetHull") else None

    if post_shield > 0.0:
        # 2. Hull always takes full post-shield damage.
        if hull is not None and hasattr(ship, "DamageSystem"):
            ship.DamageSystem(hull, post_shield)
            absorbed_hull = post_shield

        # 3. Each non-hull subsystem within the splash sphere takes a
        #    weighted share independently. Total can exceed post_shield.
        for sub in _iter_subsystems(ship):
            pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
            if pos is None:
                continue
            r_sub = sub.GetRadius() if hasattr(sub, "GetRadius") else 0.0
            h_world = _subsystem_world_position(ship, sub)
            dx = hit_point.x - h_world.x
            dy = hit_point.y - h_world.y
            dz = hit_point.z - h_world.z
            d = (dx * dx + dy * dy + dz * dz) ** 0.5
            if d >= r_sub + r_hit:
                continue
            w = _splash_weight(r_sub, r_hit, d)
            if w <= 0.0:
                continue
            allocations.append((sub, w))
            amount = post_shield * w
            if hasattr(ship, "DamageSystem"):
                before_flags = _subsystem_state_flags(sub)
                ship.DamageSystem(sub, amount)
                absorbed_subsystem_total += amount
                after_flags = _subsystem_state_flags(sub)
                transition = _diff_state(before_flags, after_flags)
                if transition is not None and primary_transition is None:
                    primary_transition = transition

    primary_subsystem = _pick_primary_subsystem_for_dispatch(allocations)

    # 4. Fan out VFX + audio + camera shake. Errors swallowed so the
    #    downstream WeaponHitEvent broadcast always runs.
    try:
        hit_feedback.dispatch(
            ship=ship, source=source, point=hit_point, normal=normal,
            damage=damage, subsystem=primary_subsystem,
            absorbed_shields=absorbed_shields,
            absorbed_subsystem=absorbed_subsystem_total,
            absorbed_hull=absorbed_hull,
            sub_transition=primary_transition,
            host=host, ship_instances=ship_instances,
            weapon_type=weapon_type,
        )
    except Exception:
        pass

    # 5. Broadcast WeaponHitEvent.
    evt = WeaponHitEvent()
    evt.SetSource(source)
    evt.SetTarget(ship)
    evt.SetDamage(damage)
    evt.SetHitPoint(hit_point)
    evt.SetNormal(normal)
    evt.SetRadius(r_hit)
    evt.SetSubsystem(primary_subsystem)
    if isinstance(ship, App.TGEventHandlerObject):
        evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `uv run pytest tests/unit/test_apply_hit_splash.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_apply_hit_splash.py
git commit -m "feat(combat): rewrite apply_hit using spherical splash attribution"
```

---

### Task 8: Delete `pick_target_subsystem`

The new `apply_hit` does not call it and no production code should depend on it. Verify, then delete.

**Files:**
- Modify: `engine/appc/combat.py` (remove `pick_target_subsystem`, lines 164–219)

- [ ] **Step 1: Audit non-test callers**

Run: `grep -rn "pick_target_subsystem" engine/ native/ tests/ tools/ --include="*.py"`
Expected: only `tests/` matches. If `engine/` or `native/` references appear, STOP and surface them — the plan is wrong.

- [ ] **Step 2: Remove the function**

Delete the entire `def pick_target_subsystem(...)` block in `engine/appc/combat.py` (the function and its docstring, plus the blank line above and below).

- [ ] **Step 3: Run the whole combat unit test directory**

Run: `uv run pytest tests/unit/test_combat_splash_radius.py tests/unit/test_combat_iter_subsystems.py tests/unit/test_combat_subsystem_world_position.py tests/unit/test_combat_splash_weight.py tests/unit/test_combat_primary_for_dispatch.py tests/unit/test_apply_hit_splash.py tests/unit/test_weapon_hit_event.py tests/unit/test_combat_hit_resolution.py tests/unit/test_shield_face_from_hit_point.py tests/unit/test_sphere_hit.py -v`
Expected: all pass. (Existing test files may have one or two pre-existing failures unrelated to this work; flag any failure whose stack mentions splash / pick_target_subsystem.)

- [ ] **Step 4: Commit**

```bash
git add engine/appc/combat.py
git commit -m "refactor(combat): delete pick_target_subsystem (superseded by splash)"
```

---

### Task 9: Audit and update tests that depended on winner-takes-all

Some legacy tests likely assert `subsystem=X` round-tripped through `apply_hit` and ended up taking all the damage. Those need updating.

**Files:**
- Modify (likely): `tests/unit/test_apply_hit_routing.py`
- Modify (likely): `tests/unit/test_apply_hit_state_diff.py`
- Modify (likely): `tests/unit/test_phaser_damage_falloff.py`
- Modify (possibly): `tests/integration/test_phaser_damage_applied_through_apply_hit.py`
- Modify (possibly): `tests/integration/test_torpedo_hit_point_on_mesh.py`

- [ ] **Step 1: Find broken tests**

Run: `uv run pytest tests/unit/ tests/integration/ -k "combat or hit or damage or phaser or torp" -x --no-header 2>&1 | head -80`
Expected: a list of failing tests with assertions about subsystem damage that no longer match.

- [ ] **Step 2: Triage each failure**

For each failing test:

1. **If the test asserts "subsystem X took damage Y"** under the old winner-takes-all model: rewrite the assertion using the splash model. For a hit at `subsystem.GetPosition()` with weight 1.0 the subsystem still takes full damage `D`; for off-centre hits compute the expected weight by hand.
2. **If the test asserts "subsystem X took ALL the damage and nothing else did"**: this assumption is gone. Either narrow the assertion to "subsystem X took damage > 0" or set up the fixture so other candidates are out of range.
3. **If the test was specifically testing `pick_target_subsystem`**: delete it. The picker is gone.
4. **If the test asserts the `subsystem=` keyword argument to `apply_hit`**: remove the keyword. `apply_hit` no longer accepts `subsystem=` (verify by reading the new signature in Task 7's step 3). Update any callsite using that kwarg.

- [ ] **Step 3: Apply fixes one test file at a time**

For each test file: open, fix all failures within it, re-run just that file, then move to the next. Smaller deltas → cleaner diffs.

After each file:

```bash
uv run pytest tests/unit/<file>.py -v
```

Expected: all pass.

- [ ] **Step 4: Run the full focused suite**

Run: `uv run pytest tests/unit/ tests/integration/ -k "combat or hit or damage or phaser or torp" --no-header`
Expected: all pass.

**Memory caution:** per the CLAUDE memory, do NOT run the full `uv run pytest` against everything — it OOMs. Stick to filtered selections.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test(combat): update legacy tests for splash attribution"
```

---

### Task 10: Integration test — phaser at Galaxy damages multiple subsystems

End-to-end proof that a single phaser hit lands damage on hull + at least one non-hull subsystem when the impact point is near a known hardpoint position.

**Files:**
- Create: `tests/integration/test_splash_attribution_galaxy.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_splash_attribution_galaxy.py`:

```python
"""End-to-end: a phaser hit on the Galaxy applies damage to the hull and
to any subsystem whose hardpoint position is within the splash sphere of
the impact point.

This is the production-fidelity proof of the splash attribution model.
Loads the real Galaxy ship via loadspacehelper, fires a synthesized
phaser hit at the world-space position of the Sensors subsystem, and
asserts both hull and sensors took damage.
"""

import pytest

from engine.appc.combat import _subsystem_world_position, apply_hit
from engine.appc.math import TGPoint3


@pytest.fixture
def galaxy_ship(headless_app):
    """Construct a Galaxy via the real SDK helper, headless."""
    import loadspacehelper
    set_ = headless_app.g_kSetManager.GetSet("bridge")
    galaxy = loadspacehelper.CreateShip("Galaxy", set_)
    galaxy.SetPosition(0.0, 0.0, 0.0)
    yield galaxy


def _subsystem_named(ship, name):
    for s in ship.GetSubsystems():
        if hasattr(s, "GetName") and s.GetName() == name:
            return s
        for child in getattr(s, "_children", []) or []:
            if hasattr(child, "GetName") and child.GetName() == name:
                return child
    return None


def test_phaser_at_sensor_array_damages_hull_and_sensors(galaxy_ship):
    sensors = _subsystem_named(galaxy_ship, "Sensor Array")
    assert sensors is not None, "Galaxy SDK should declare a Sensor Array subsystem"

    hull = galaxy_ship.GetHull()
    hull_before = hull.GetCondition()
    sensors_before = sensors.GetCondition()

    # Fire at the sensors' world-space position; weight should be ~1.0
    hit_point = _subsystem_world_position(galaxy_ship, sensors)

    apply_hit(galaxy_ship, damage=100.0, hit_point=hit_point,
              source=None, normal=TGPoint3(0.0, 1.0, 0.0))

    hull_after = hull.GetCondition()
    sensors_after = sensors.GetCondition()

    assert hull_after < hull_before, "hull should always take damage on a bleed-through hit"
    assert sensors_after < sensors_before, "sensors should take damage when impact is at its centre"
    # Hull takes the full damage; sensors takes the same.
    assert pytest.approx(hull_before - hull_after, rel=0.01) == 100.0
    assert pytest.approx(sensors_before - sensors_after, rel=0.01) == 100.0


def test_phaser_far_from_any_subsystem_only_damages_hull(galaxy_ship):
    hull = galaxy_ship.GetHull()
    hull_before = hull.GetCondition()

    # 1000 GU offset along world-X — way outside any subsystem catchment.
    # The point isn't physically on the hull either, but apply_hit doesn't
    # validate that — it trusts the caller's impact point.
    hit_point = TGPoint3(1000.0, 0.0, 0.0)

    subsystem_conditions_before = {}
    for s in galaxy_ship.GetSubsystems():
        if s is hull:
            continue
        if hasattr(s, "GetCondition"):
            subsystem_conditions_before[id(s)] = s.GetCondition()

    apply_hit(galaxy_ship, damage=50.0, hit_point=hit_point,
              source=None, normal=None)

    assert hull.GetCondition() < hull_before  # hull always damaged
    # No non-hull subsystem should have taken damage.
    for s in galaxy_ship.GetSubsystems():
        if s is hull:
            continue
        if hasattr(s, "GetCondition") and id(s) in subsystem_conditions_before:
            assert s.GetCondition() == subsystem_conditions_before[id(s)], \
                f"{getattr(s, 'GetName', lambda: '?')()} should not be damaged by a far hit"
```

- [ ] **Step 2: Inspect existing test infrastructure**

If `headless_app` fixture isn't named that in this project, find the right one. Run: `grep -rn "headless_app\|@pytest.fixture" tests/conftest.py tests/integration/conftest.py 2>/dev/null | head -20`

Adjust the fixture name and import in the new test file to match what the project already exposes.

- [ ] **Step 3: Run the integration test**

Run: `uv run pytest tests/integration/test_splash_attribution_galaxy.py -v`
Expected: 2 passed. If `_subsystem_named` returns None for "Sensor Array", inspect Galaxy's hardpoint file: `head -40 sdk/Build/scripts/ships/Hardpoints/galaxy.py` and adjust the name (it might be "Sensors" or another label).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_splash_attribution_galaxy.py
git commit -m "test(combat): integration proof of splash attribution on Galaxy"
```

---

### Task 11: Mark the propagation spec superseded

The propagation spec's attribution sections are replaced by this work. Its parent-aggregation rules stay valid.

**Files:**
- Modify: `docs/superpowers/specs/2026-06-01-subsystem-damage-propagation-design.md`

- [ ] **Step 1: Add the superseded marker**

Add a banner near the top of `docs/superpowers/specs/2026-06-01-subsystem-damage-propagation-design.md` (right after the H1 / status block):

```markdown
> **Attribution-decision section superseded by [2026-06-06-damage-attribution-design.md](./2026-06-06-damage-attribution-design.md).** The "closest within 2× radius" rule described in this doc is no longer authoritative — spherical-splash with multi-subsystem weighted allocation replaces it. The parent-aggregator predicates (`IsDamaged`, `IsDisabled`, `IsDestroyed` derived from children) defined here remain valid and continue to apply.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-01-subsystem-damage-propagation-design.md
git commit -m "docs(combat): mark propagation spec attribution sections superseded"
```

---

## Self-review notes

- **Spec §3.1 (mesh-accurate hit point):** assumed already implemented — verified in survey, `_resolve_hit_point` at combat.py:53 already uses `host.ray_trace_mesh`. No task needed.
- **Spec §3.2 (R_hit resolver):** Task 1.
- **Spec §3.3 (candidate set):** Task 3 (`_iter_subsystems`) + Task 4 (`_subsystem_world_position`) + Task 7 (apply_hit's candidate loop).
- **Spec §3.4 (linear falloff):** Task 5.
- **Spec §3.5 (independent allocation):** Task 7's apply_hit loop; integration test in Task 10 verifies hull + subsystem each take full damage on a centred hit.
- **Spec §3.6 (shield face):** unchanged, already in `_shield_face_from_hit_point`.
- **Spec §3.7 (targeting biases aim only):** Task 7 removes the `subsystem=` parameter from `apply_hit`'s public signature, so callers cannot bias allocation. The plan is silent on the firing-math side (aim biasing) because that lives in `engine/appc/projectiles.py` and the phaser fire path, both already aim at the targeted subsystem's position without this plan needing to touch them.
- **Spec §4.1 edge cases:** "no candidates" → hull still damaged (Task 7's `if post_shield > 0.0` branch); "shield absorbs all" → no hull or subsystem damage (Task 7 fixes for `post_shield > 0.0`); "impact inside multiple subsystems" → Task 7's loop applies each weight independently (covered by Task 7 test); "weapon with no DRF anywhere" → Task 1's phaser default; "subsystem with R=0" → Task 5 test covers this.
- **Spec §4 pseudocode broadcast:** Task 7's `evt.SetNormal(normal); evt.SetRadius(r_hit)`.
- **Spec §5 integration with roadmap:** Task 11 marks propagation spec; this plan is the Project 2 + Project 4 attribution-side work.
- **Spec §6 verification plan:** out of scope for this plan, separate plan when user is ready.
- **Spec §7 non-goals:** observed; nothing in this plan touches manual targeting, falloff curves, armour, multi-victim splash, or save/load.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-06-damage-attribution.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
