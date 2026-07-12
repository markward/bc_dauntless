# TorpedoTube Recreation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `App.TorpedoTube` faithful to the original BC engine — correct base class, world-space firing direction (fixes AI dumb-fire), the decompiled per-slot reload model on game time, and removal of the phantom charge probes that top the stub heatmap.

**Architecture:** Introduce a `Weapon(ShipSubsystem)` leaf-emitter base (BC's real hierarchy) and re-parent `TorpedoTube` onto it, dropping the bogus `PoweredSubsystem` surface it inherits today. Rewrite the tube's reload state to the model recovered from `stbc.exe` (per-slot timer array, game-clock compare, `ImmediateDelay` refire gate). Wire `ET_TORPEDO_RELOAD`, harden `events.py` against stub-typed event keys, and delete the two `hasattr` probes that ask a tube for an `EnergyWeapon` API it cannot have.

**Tech Stack:** Python 3.11, pytest, existing `engine/appc/` shim layer.

**Spec:** `docs/superpowers/specs/2026-07-12-torpedo-tube-recreation-design.md`

## Global Constraints

- **Test gate is `scripts/check_tests.sh`**, NOT `scripts/run_tests.sh` (which is pytest-only and cannot see C++ regressions). It diffs failures against `tests/known_failures.txt` (only the 7 headless-GL `FrameTest`s). Any failure not in that list is a regression this branch introduced. **Never call a failure "pre-existing" by eyeball.**
- **No C++ changes in this plan.** Nothing here touches `native/`, so no rebuild is required.
- **`TGObject.__getattr__` returns a truthy, callable `_Stub` for ANY missing attribute** (`engine/core/ids.py:125`). Consequences that shape every task:
  - `hasattr(x, "anything")` is **vacuously True** on any subsystem. Never use `hasattr` to test a subsystem's surface — use `isinstance` or walk the MRO.
  - A method we accidentally drop **will not raise**; it silently returns a truthy stub (`int()` → 0, `float()` → 0.0). Losing a method fails *silently*.
- **Rotation convention:** `TGMatrix3` is column-vector, right-handed (det=+1). World-forward is `GetCol(1)`, world-up `GetCol(2)`, world-right `GetCol(0)`. Body→world is `v.MultMatrixLeft(R)`. See `CLAUDE.md`.
- **Game clock is `App.g_kUtopiaModule.GetGameTime()`**, reached via a deferred `import App` *inside* the method (the established idiom — `weapon_subsystems.py:1727`, `damage_decals.py:62`). It is pause-frozen and frame-rate independent. **Never `time.monotonic()`.**
- **Do NOT convert reload to dt-integration.** `_advance_weapons` runs once per *render frame* with a constant `TICK_DT = 1/60` (`host_loop.py:6054`, `:5525`) — it is not inside the fixed-timestep sim loop. Integrating `dt` there would make reload frame-rate dependent (a Galaxy tube would reload in 20 s on a 120 Hz display).
- **`ET_TORPEDO_FIRED` is OUT OF SCOPE** — blocked on probe q12. Do not define or post it. `Episode7.TorpedoFired` destroys the event's `GetDestination()` subsystem on a 10% roll; a wrong Destination destroys the wrong subsystem.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `engine/appc/weapon_subsystems.py` | `Weapon` base, `_emitter_world_direction` helper, rewritten `TorpedoTube` | Modify |
| `engine/appc/subsystems.py:2421` | `_WEAPON_EXPORTS` façade allowlist | Modify (add `"Weapon"`) |
| `engine/appc/ships.py:1123-1129` | `_copy_torpedo_tube_fields` — size the reload-slot array | Modify |
| `engine/appc/events.py` | `ET_TORPEDO_RELOAD` const; stub-key hardening; `RemoveBroadcastHandler` fix | Modify |
| `App.py` | re-export `ET_TORPEDO_RELOAD` | Modify |
| `engine/host_loop.py:487-490` | `_advance_weapons` — `isinstance` dispatch, not `hasattr` | Modify |
| `engine/ui/weapons_display_panel.py:222-238` | `_has_charge_model` — `isinstance`, not `hasattr` | Modify |
| `tests/unit/test_torpedo_tube_weapon_base.py` | Task 1 tests | Create |
| `tests/unit/test_torpedo_tube_direction.py` | Task 2 tests | Create |
| `tests/unit/test_torpedo_tube_reload.py` | Task 3 — **rewrite** (hard-codes `monotonic()`) | Modify |
| `tests/unit/test_torpedo_reload_event.py` | Task 4 tests | Create |
| `tests/unit/test_event_stub_key_hardening.py` | Task 5 tests | Create |
| `tests/unit/test_no_phantom_charge_probe.py` | Task 6 tests | Create |
| `tests/unit/test_child_weapon_classes.py:30-33` | asserts `isinstance(tt, WeaponSystem)` — now false | Modify |
| `tests/unit/test_weapon_power_factor.py:141-215` | 5 torpedo cases seed `monotonic()` | Modify |
| `tests/unit/test_torpedo_tube_fire_dumb.py:22-33` | asserts model-space direction | Modify |

---

## Task 1: `Weapon` base class + re-parent `TorpedoTube`

BC's hierarchy is `TorpedoTube → Weapon → ShipSubsystem` (`sdk/.../App.py:5758,5988`). `Weapon` is a leaf emitter and is **not** a `PoweredSubsystem` — no power, no `IsOn`, no charge. Ours is `TorpedoTube → WeaponSystem → PoweredSubsystem`, which is why `host_loop` felt entitled to ask a tube for `UpdateCharge`.

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (add `Weapon`; change `class TorpedoTube(WeaponSystem)` → `class TorpedoTube(Weapon)` at line 1625)
- Modify: `engine/appc/subsystems.py:2421` (`_WEAPON_EXPORTS`)
- Modify: `tests/unit/test_child_weapon_classes.py:30-33`
- Test: `tests/unit/test_torpedo_tube_weapon_base.py` (create)

**Interfaces:**
- Produces: `class Weapon(ShipSubsystem)` with `__init__(name="")` setting `_firing`/`_target`/`_target_offset`; methods `Fire(target=None, offset=None, **kwargs)`, `CanFire() -> int`, `StopFiring() -> None`, `IsFiring() -> int`, `FireDumb(iReserved=0, iForce=1) -> None`, `CalculateRoughDirection() -> TGPoint3`, `CalculateWeaponAppeal() -> float`. Tasks 2 and 3 extend this class and `TorpedoTube`.
- Consumes: `ShipSubsystem`, `TGPoint3` (already imported at `weapon_subsystems.py:18-24`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_torpedo_tube_weapon_base.py`:

```python
"""TorpedoTube is a BC leaf Weapon, not a powered WeaponSystem.

sdk/Build/scripts/App.py:5758  class Weapon(ShipSubsystem)
sdk/Build/scripts/App.py:5988  class TorpedoTube(Weapon)

NOTE: every assertion here walks the MRO rather than using hasattr().
TGObject.__getattr__ (engine/core/ids.py:125) returns a truthy _Stub for ANY
missing attribute, so hasattr() is vacuously True on every subsystem and would
make these tests pass even if the re-parent had not happened.
"""
from engine.appc.subsystems import (
    Weapon, WeaponSystem, PoweredSubsystem, ShipSubsystem, TorpedoTube,
)


def _mro_has(cls, name: str) -> bool:
    """True only if `name` is a REAL attribute on some class in the MRO.
    Bypasses TGObject.__getattr__'s _Stub catch-all."""
    return any(name in klass.__dict__ for klass in cls.__mro__)


def test_weapon_is_a_shipsubsystem_not_a_powered_subsystem():
    assert issubclass(Weapon, ShipSubsystem)
    assert not issubclass(Weapon, PoweredSubsystem)


def test_torpedo_tube_is_a_weapon_not_a_weapon_system():
    assert issubclass(TorpedoTube, Weapon)
    assert not issubclass(TorpedoTube, WeaponSystem)


def test_torpedo_tube_keeps_the_sdk_demanded_leaf_surface():
    # Every one of these has a real SDK call site on a tube.
    for name in ("Fire", "FireDumb", "CanFire", "StopFiring", "IsFiring",
                 "CalculateRoughDirection", "CalculateWeaponAppeal"):
        assert _mro_has(TorpedoTube, name), name


def test_torpedo_tube_drops_the_powered_aggregate_surface():
    # These are WeaponSystem/PoweredSubsystem-only. No SDK site calls any of
    # them on a tube; carrying them is what let host_loop probe for UpdateCharge.
    for name in ("StartFiring", "StopFiringAtTarget", "GetNumWeapons",
                 "GetWeapon", "IsOn", "TurnOn", "TurnOff",
                 "GetNormalPowerPercentage", "UpdateCharge", "GetMaxCharge"):
        assert not _mro_has(TorpedoTube, name), name


def test_fresh_tube_is_not_firing():
    # Weapon.__init__ must seed _firing; otherwise IsFiring() returns a truthy
    # _Stub instead of 0 and nothing raises.
    assert TorpedoTube("Forward Torpedo 1").IsFiring() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_torpedo_tube_weapon_base.py -v`
Expected: FAIL — `ImportError: cannot import name 'Weapon' from 'engine.appc.subsystems'`

- [ ] **Step 3: Add the `Weapon` base class**

In `engine/appc/weapon_subsystems.py`, insert **immediately before** `class WeaponSystem(PoweredSubsystem):` (line 508):

```python
class Weapon(ShipSubsystem):
    """BC leaf emitter — sdk/Build/scripts/App.py:5758 `class Weapon(ShipSubsystem)`.

    Deliberately NOT a PoweredSubsystem: in BC a weapon has no power, no IsOn
    and no charge.  Power lives on the parent WeaponSystem; charge lives on
    EnergyWeapon (App.py:6426-6440), which torpedo tubes do not inherit.

    Only the surface the SDK actually calls on a leaf weapon.  DELIBERATELY
    ABSENT (verified zero SDK call sites on a tube): SetFiring,
    IsMemberOfGroup, GetTargetID, IsDumbFire, GetOverallConditionPercentage,
    IsInArc, CanHit, SetSkewFire, IsSkewFire.  IsInArc/CanHit are additionally
    unspecifiable — their BC signatures cannot be recovered from the SDK.

    GetProperty/SetProperty are inherited from ShipSubsystem (subsystems.py:273).
    """

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Seeded here, not in the subclass: IsFiring() must return a real 0 on a
        # fresh weapon.  Without this, __getattr__ hands back a truthy _Stub.
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def Fire(self, target=None, offset=None, **kwargs) -> None:
        """Discrete shot.  Subclasses implement — the payload differs per weapon
        (TorpedoTube.Fire additionally takes spread_unit/homing_delay for
        Dual/Quad spread volleys; see TorpedoSystem.StartFiring)."""
        raise NotImplementedError

    def CanFire(self) -> int:
        return 0

    def StopFiring(self) -> None:
        self._firing = False

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def FireDumb(self, iReserved=0, iForce=1) -> None:
        """SDK AI/Preprocessors.py:458 — `pTube.FireDumb(0, 1)`.  Unguided shot,
        no target.  The AI never checks CanFire() first, so this must be a silent
        no-op when the weapon is not ready."""
        self.Fire(target=None, offset=None)

    def CalculateRoughDirection(self) -> TGPoint3:
        """WORLD-space mount direction.  Implemented in Task 2."""
        raise NotImplementedError

    def CalculateWeaponAppeal(self) -> float:
        """SDK AI/PlainAI/IntelligentCircleObject.py:238.  The AI sums appeal
        across weapons facing a candidate heading and picks the best facing.

        BC's exact formula is not recoverable from the SDK, so this is an
        APPROXIMATION, not a reproduction: 1.0 for a functional weapon, 0.0 for
        a disabled one.  That yields "face the direction with the most working
        weapons", which matches the caller's intent.
        """
        return 0.0 if self.IsDisabled() else 1.0
```

- [ ] **Step 4: Re-parent `TorpedoTube` and move its firing state up**

In `engine/appc/weapon_subsystems.py:1625`, change the class statement:

```python
class TorpedoTube(Weapon):
```

Then in `TorpedoTube.__init__`, **delete** these three lines (now set by `Weapon.__init__`):

```python
        self._firing: bool = False
        self._target = None
        self._target_offset = None
```

Leave the rest of `__init__` alone — Task 3 rewrites the reload state.

- [ ] **Step 5: Export `Weapon` through the façade**

`engine/appc/subsystems.py:2421` — add `"Weapon"` to `_WEAPON_EXPORTS`:

```python
_WEAPON_EXPORTS = frozenset({
    "Weapon",
    "WeaponSystem",
    "TorpedoAmmoType",
```

This is a PEP-562 `__getattr__` allowlist; ~30 sites import weapon classes through it, and an omission is an `AttributeError` at import — not a stub.

- [ ] **Step 6: Update the test that encodes the old hierarchy**

`tests/unit/test_child_weapon_classes.py:30-33` currently asserts `isinstance(tt, WeaponSystem)`. Replace that test with:

```python
def test_torpedo_tube_is_a_weapon_not_a_weapon_system():
    """BC: TorpedoTube derives from Weapon (a leaf), not WeaponSystem (a powered
    aggregate).  See sdk/Build/scripts/App.py:5988 and
    docs/superpowers/specs/2026-07-12-torpedo-tube-recreation-design.md."""
    tt = TorpedoTube("Forward Torpedo 1")
    assert isinstance(tt, Weapon)
    assert not isinstance(tt, WeaponSystem)
```

Add `Weapon` to that file's imports, and update its module docstring (lines 1-7), which claims "All subclass WeaponSystem".

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_torpedo_tube_weapon_base.py tests/unit/test_child_weapon_classes.py -v`
Expected: PASS (all)

- [ ] **Step 8: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`.

If a *different* torpedo test fails here, it is telling you a method was silently lost to `_Stub` — read the failure, do not paper over it.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/weapon_subsystems.py engine/appc/subsystems.py \
        tests/unit/test_torpedo_tube_weapon_base.py tests/unit/test_child_weapon_classes.py
git commit -m "refactor(weapons): add BC Weapon leaf base; re-parent TorpedoTube off WeaponSystem

BC's TorpedoTube derives from Weapon (a leaf emitter under ShipSubsystem), not
from WeaponSystem (a PoweredSubsystem aggregate). Carrying the powered-aggregate
surface is what let host_loop probe a tube for UpdateCharge.

Weapon carries only the SDK-demanded leaf surface. Deliberately absent (zero SDK
call sites on a tube): SetFiring, IsMemberOfGroup, GetTargetID, IsDumbFire,
GetOverallConditionPercentage, IsInArc, CanHit, SetSkewFire, IsSkewFire."
```

---

## Task 2: World-space `CalculateRoughDirection` — the AI dumb-fire fix

`CalculateRoughDirection` currently returns `App.TGPoint3_GetModelForward()` for **every** tube (`weapon_subsystems.py:1722`) — the same vector regardless of which way the tube points, and never rotated into world space.

`AI/Preprocessors.py:447-456` builds `vToTarget` as a **world-space** delta and dots it against `CalculateRoughDirection()` to decide which tubes may dumb-fire. `AI/PlainAI/IntelligentCircleObject.py:204,234` is decisive: it takes the result and explicitly converts it **world→model** (`mWorldToModel`, comment *"Change it to model space"*).

So today every tube reads as ship-forward: **aft tubes dumb-fire at targets ahead, and nothing fires at targets behind.**

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (add `_emitter_world_direction`; refactor `_emitter_in_arc:113-118`; implement `Weapon.CalculateRoughDirection`; delete `TorpedoTube.CalculateRoughDirection:1722`)
- Modify: `tests/unit/test_torpedo_tube_fire_dumb.py:22-33`
- Test: `tests/unit/test_torpedo_tube_direction.py` (create)

**Interfaces:**
- Consumes: `Weapon` (Task 1).
- Produces: `_emitter_world_direction(emitter, ship) -> TGPoint3` — module-level helper in `weapon_subsystems.py`.

**Two things that must be right:**

1. **`GetDirection()` stays MODEL space and is NOT touched.** It is dotted against a *model-space* restriction vector at `ConditionTorpsReady.py:128`. `GetDirection` (model) and `CalculateRoughDirection` (world) are different vectors for different callers. Conflating them breaks the condition.
2. **Resolve the ship with `_climb_to_ship()`, NOT `GetParentShip()`.** `ShipClass._attach_subsystem` (`ships.py:690-700`) calls `SetParentShip` only on **top-level** subsystems. Tubes are added as children under `TorpedoSystem`, so `tube._parent_ship` is `None` on every real tube — `GetParentShip()` would silently return `None` and fall back.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_torpedo_tube_direction.py`:

```python
"""CalculateRoughDirection is WORLD space; GetDirection stays MODEL space.

Evidence that CalculateRoughDirection is world-space:
  AI/Preprocessors.py:447-456          dots it against a world-space target delta
  AI/PlainAI/IntelligentCircleObject.py:204,234
                                       converts the result world->model explicitly
                                       ("Change it to model space")

Evidence that GetDirection is model-space:
  Conditions/ConditionTorpsReady.py:128  dots it against a model-space vector
"""
import math

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


def _tube_on_ship(local_dir: TGPoint3, yaw_rad: float) -> tuple:
    """A tube pointing `local_dir` in body space, on a ship yawed by `yaw_rad`."""
    ship = ShipClass("Galaxy")
    rot = TGMatrix3()
    rot.MakeZRotation(yaw_rad)          # yaw about body-up (col 2)
    ship.SetWorldRotation(rot)

    system = TorpedoSystem("Torpedoes")
    tube = TorpedoTube("Aft Torpedo 1")
    tube.SetDirection(local_dir)
    system.AddChildSubsystem(tube)
    ship._attach_subsystem(system)      # sets _parent_ship on the SYSTEM only
    return ship, tube


def test_aft_tube_points_backwards_in_world_space_when_ship_is_unrotated():
    """The core dumb-fire bug: an AFT tube must NOT read as ship-forward."""
    _ship, tube = _tube_on_ship(TGPoint3(0.0, -1.0, 0.0), 0.0)
    world = tube.CalculateRoughDirection()
    assert world.y < -0.99          # points aft, i.e. -Y in world

    # AI/Preprocessors.py:456 gates dumb-fire on this dot being > 0.
    target_ahead = TGPoint3(0.0, 1.0, 0.0)
    dot = world.x * target_ahead.x + world.y * target_ahead.y + world.z * target_ahead.z
    assert dot < 0.0, "aft tube must not dumb-fire at a target dead ahead"


def test_forward_tube_rotates_with_the_ship():
    """World space means the ship's rotation is applied."""
    _ship, tube = _tube_on_ship(TGPoint3(0.0, 1.0, 0.0), math.radians(90.0))
    world = tube.CalculateRoughDirection()
    # Body +Y yawed 90 deg about body-up lands on world -X (column-vector,
    # right-handed; see CLAUDE.md).
    assert abs(world.x - (-1.0)) < 1e-6
    assert abs(world.y) < 1e-6


def test_get_direction_stays_model_space():
    """GetDirection must NOT be rotated -- ConditionTorpsReady.py:128 dots it
    against a model-space restriction vector."""
    _ship, tube = _tube_on_ship(TGPoint3(0.0, -1.0, 0.0), math.radians(90.0))
    local = tube.GetDirection()
    assert abs(local.y - (-1.0)) < 1e-6   # unchanged by the ship's rotation
    assert abs(local.x) < 1e-6


def test_orphaned_tube_falls_back_to_its_body_direction():
    """No parent ship -- return the un-rotated mount direction, not a crash."""
    tube = TorpedoTube("Orphan")
    tube.SetDirection(TGPoint3(0.0, 1.0, 0.0))
    world = tube.CalculateRoughDirection()
    assert abs(world.y - 1.0) < 1e-6
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_torpedo_tube_direction.py -v`
Expected: FAIL — `test_aft_tube_points_backwards...` fails because the current implementation returns model-forward `(0,1,0)` for every tube, so `world.y` is `+1.0`, not `< -0.99`. **This failure IS the AI dumb-fire bug.**

- [ ] **Step 3: Add the `_emitter_world_direction` helper**

In `engine/appc/weapon_subsystems.py`, insert **immediately before** `def _emitter_in_arc(...)` (line 96):

```python
def _emitter_world_direction(emitter, ship) -> TGPoint3:
    """The emitter's mount direction rotated into WORLD space.

    This is what BC's Weapon::CalculateRoughDirection returns.  Evidence:
    AI/Preprocessors.py:447-456 dots the result against a world-space target
    delta, and AI/PlainAI/IntelligentCircleObject.py:204,234 converts it
    world->model explicitly ("Change it to model space").

    DISTINCT from GetDirection(), which stays MODEL space — ConditionTorpsReady
    .py:128 dots that against a model-space restriction vector.  Do not conflate.

    Orphaned emitter (no owning ship): return the un-rotated body direction.
    """
    local = emitter.GetDirection() if isinstance(emitter, ShipSubsystem) else None
    if not isinstance(local, TGPoint3):
        local = TGPoint3(0.0, 1.0, 0.0)     # BC model-forward default
    world = TGPoint3(local.x, local.y, local.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world.MultMatrixLeft(rot)       # v_world = R . v_body (column-vector)
    return world
```

- [ ] **Step 4: Reuse the helper inside `_emitter_in_arc`**

`_emitter_in_arc` (line 96) duplicates this rotation at lines 113-118. Replace this block:

```python
    if not hasattr(emitter, "GetDirection"):
        return True
    try:
        local_dir = emitter.GetDirection()
    except Exception:
        return True
    if not isinstance(local_dir, TGPoint3):
        return True
    # Rotate emitter direction into world space.
    world_dir = TGPoint3(local_dir.x, local_dir.y, local_dir.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world_dir.MultMatrixLeft(rot)
```

with:

```python
    world_dir = _emitter_world_direction(emitter, ship)
```

Leave the rest of `_emitter_in_arc` (the arc-bounds branch, from the `use_arc_check` line down) exactly as it is.

- [ ] **Step 5: Implement `Weapon.CalculateRoughDirection`, delete the tube's override**

In `Weapon` (added in Task 1), replace the `raise NotImplementedError` body:

```python
    def CalculateRoughDirection(self) -> TGPoint3:
        """WORLD-space mount direction.  SDK AI/Preprocessors.py:456 and
        AI/PlainAI/IntelligentCircleObject.py:234.

        _climb_to_ship() — NOT GetParentShip().  ShipClass._attach_subsystem
        (ships.py:690-700) sets _parent_ship only on TOP-LEVEL subsystems.  A
        torpedo tube is a CHILD of the TorpedoSystem, so its _parent_ship is
        None and GetParentShip() would silently return None on every real tube.
        """
        return _emitter_world_direction(self, self._climb_to_ship())
```

Then **delete** `TorpedoTube.CalculateRoughDirection` entirely (`weapon_subsystems.py:1722-1728`) — the base now does it correctly. Its docstring's "per-tube arcs deferred to Slice D" note is what this task closes.

- [ ] **Step 6: Update the stale dumb-fire test**

`tests/unit/test_torpedo_tube_fire_dumb.py:22-33` — `test_calculate_rough_direction_returns_ship_forward_when_attached` sets `tube._parent_ship = ship` directly and asserts model-forward. Rewrite it:

```python
def test_calculate_rough_direction_is_world_space_when_attached():
    """Was: asserted model-forward for every tube. That WAS the dumb-fire bug --
    see tests/unit/test_torpedo_tube_direction.py for the real coverage."""
    ship = ShipClass("Galaxy")
    system = TorpedoSystem("Torpedoes")
    tube = TorpedoTube("Forward Torpedo 1")
    tube.SetDirection(TGPoint3(0.0, 1.0, 0.0))
    system.AddChildSubsystem(tube)
    ship._attach_subsystem(system)

    world = tube.CalculateRoughDirection()
    assert abs(world.y - 1.0) < 1e-6      # identity rotation -> body == world
```

The orphaned-tube test in that file (lines 36-43) passes unchanged.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_torpedo_tube_direction.py tests/unit/test_torpedo_tube_fire_dumb.py -v`
Expected: PASS (all)

- [ ] **Step 8: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`. Pay attention to phaser/pulse arc tests — `_emitter_in_arc` was refactored and they exercise it.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/weapon_subsystems.py tests/unit/test_torpedo_tube_direction.py \
        tests/unit/test_torpedo_tube_fire_dumb.py
git commit -m "fix(weapons): CalculateRoughDirection returns WORLD space — unbreaks AI dumb-fire

It returned model-forward for EVERY tube, so aft tubes dumb-fired at targets
ahead and nothing fired at targets behind. AI/Preprocessors.py:456 dots the
result against a world-space delta; IntelligentCircleObject.py:234 converts it
world->model explicitly.

GetDirection stays MODEL space (ConditionTorpsReady.py:128 needs it that way) —
the two are different vectors for different callers.

Ship resolved via _climb_to_ship(), not GetParentShip(): tubes are children of
the TorpedoSystem, so their _parent_ship is None."
```

---

## Task 3: Decompiled reload model — game clock, per-slot timers, `ImmediateDelay` gate

Rewrite the tube's reload state to the model recovered from `stbc.exe`
(`docs/original_game_reference/gameplay/combat-and-damage.md:740-830`).

Three defects being fixed:
1. **Wall-clock stamp.** `_last_fire_time` is `time.monotonic()` (`:1668`). Wall time runs while the sim is frozen, so after a 40 s pause (or alt-tab, or a long mission load) **every tube instantly reloads**.
2. **`ImmediateDelay` is loaded and never used.** It is a **`CanFire` refire gate** (`gameTime - last_fire_time >= ImmediateDelay`, `combat-and-damage.md:824`) — *not* "delay from fire request to launch", which is what the current docstring at `:1629` claims while citing `galaxy.py:28-30` (bare setter calls that say no such thing). Values reach **5.0 s** across hardpoints, not a uniform 0.25.
3. **`MaxReady > 1` cannot be represented.** Four hardpoint families ship `MaxReady=2` (`keldon.py:30`, `galor.py:30`, `kessokmine.py:164`, `warbird.py:30,393`). A single scalar cannot model two independently-reloading slots.

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`TorpedoTube.__init__`, `CanFire`, `Fire`, `UpdateReload`; add `_game_time`, `_resize_slots`, `_start_slot_cooldown`)
- Modify: `engine/appc/ships.py:1123-1129` (`_copy_torpedo_tube_fields`)
- Modify: `tests/unit/test_torpedo_tube_reload.py` (**rewrite** — hard-codes `monotonic()`)
- Modify: `tests/unit/test_weapon_power_factor.py:141-215` (5 torpedo cases seed `monotonic()`)

**Interfaces:**
- Consumes: `TorpedoTube(Weapon)` (Task 1).
- Produces: `_game_time() -> float` (module-level); `TorpedoTube._reload_timers: list[float]`, `_SLOT_LOADED = -1.0`, `TorpedoTube._resize_slots()`. Task 4 calls `ReloadTorpedo()`.

- [ ] **Step 1: Write the failing test**

**Rewrite** `tests/unit/test_torpedo_tube_reload.py` entirely (its docstring line 2 says "Time source is time.monotonic()", and lines 29/36/46/55 seed it):

```python
"""Torpedo reload runs on GAME time, with one timer slot per MaxReady.

Model recovered from stbc.exe --
docs/original_game_reference/gameplay/combat-and-damage.md:740-830:

    last_fire_time   float, GAME time, init -1000.0
    reload_timers    float[], ONE SLOT PER MaxReady;  -1.0 == loaded
    CanFire          num_ready > 0  AND  gameTime - last_fire_time >= ImmediateDelay
    Fire             stamp last_fire_time = gameTime; num_ready--; start a slot cooling
    ReloadTorpedo    num_ready++; oldest cooling slot -> loaded

NOT time.monotonic(): wall time advances while the sim is paused, which made
every tube instantly reload on unpause.

NOT dt-integration: _advance_weapons runs once per RENDER frame with a constant
TICK_DT (host_loop.py:6054, :5525), so integrating dt would make reload
frame-rate dependent -- a Galaxy tube would reload in 20s on a 120Hz display.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


@pytest.fixture
def clock():
    """Drive the game clock directly.  App.g_kUtopiaModule.GetGameTime() reads
    g_kTimerManager._time (App.py:1052), a pure accumulator."""
    App.g_kTimerManager._time = 0.0

    def _set(t: float) -> None:
        App.g_kTimerManager._time = float(t)

    yield _set
    App.g_kTimerManager._time = 0.0


def _tube(max_ready: int = 1, reload_delay: float = 40.0,
          immediate_delay: float = 0.25) -> TorpedoTube:
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = reload_delay
    tube._immediate_delay = immediate_delay
    tube._max_ready = max_ready
    tube._num_ready = max_ready
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


def test_last_fire_time_inits_to_minus_1000(clock):
    """BC init value (combat-and-damage.md:757).  NOT -inf: -inf poisons any
    subtraction a caller might do."""
    assert _tube().GetLastFireTime() == -1000.0


def test_fresh_tube_can_fire_immediately(clock):
    """-1000.0 init means the ImmediateDelay gate is already satisfied at t=0."""
    clock(0.0)
    assert _tube().CanFire() == 1


def test_immediate_delay_gates_a_refire(clock):
    """gameTime - last_fire_time >= ImmediateDelay (combat-and-damage.md:824)."""
    tube = _tube(max_ready=2, immediate_delay=2.0)
    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 1           # still has a round chambered

    clock(101.0)                             # only 1.0s elapsed, gate is 2.0s
    assert tube.CanFire() == 0

    clock(102.0)                             # gate satisfied
    assert tube.CanFire() == 1


def test_reload_completes_after_reload_delay_of_game_time(clock):
    tube = _tube(reload_delay=40.0)
    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 0

    clock(139.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 0           # 39s -- not yet

    clock(140.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # 40s -- reloaded


def test_pause_does_not_advance_reload(clock):
    """The bug this replaces: with time.monotonic(), pausing for 40s of WALL
    time instantly reloaded every tube.  Game time does not advance while
    paused, so a frozen clock must make no progress."""
    tube = _tube(reload_delay=40.0)
    clock(100.0)
    tube.Fire()

    for _ in range(100):                     # 100 frames, clock frozen (paused)
        tube.UpdateReload(1.0 / 60.0)
    assert tube.GetNumReady() == 0


def test_max_ready_two_reloads_slots_independently(clock):
    """warbird/keldon/galor/kessokmine ship MaxReady=2.  A single scalar
    last_fire_time cannot represent two slots cooling out of phase."""
    tube = _tube(max_ready=2, reload_delay=40.0, immediate_delay=0.25)
    clock(100.0)
    tube.Fire()                              # slot A starts cooling at t=100
    clock(110.0)
    tube.Fire()                              # slot B starts cooling at t=110
    assert tube.GetNumReady() == 0

    clock(140.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # A done (40s), B has 10s to go

    clock(149.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # B still not done

    clock(150.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 2           # B done


def test_reload_never_exceeds_max_ready(clock):
    tube = _tube(max_ready=1)
    clock(1000.0)
    for _ in range(5):
        tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_torpedo_tube_reload.py -v`
Expected: FAIL — `AttributeError`-free but wrong: `test_last_fire_time_inits_to_minus_1000` fails (`-inf != -1000.0`), and `_resize_slots` does not exist (it resolves to a `_Stub` and silently does nothing, so the `MaxReady=2` test fails on the assertion, not on an exception — a reminder that missing methods do *not* raise here).

- [ ] **Step 3: Add the game-clock helper and the slot constant**

In `engine/appc/weapon_subsystems.py`, add near the top-level helpers (after `_SPREAD_DELAY`, ~line 34):

```python
# ── Torpedo reload slots ───────────────────────────────────────────────────
# BC stores one float per MaxReady at TorpedoTube+0xAC
# (docs/original_game_reference/gameplay/combat-and-damage.md:748).  We store the
# GAME TIME at which each slot began cooling; _SLOT_LOADED means "ready".
_SLOT_LOADED = -1.0


def _game_time() -> float:
    """The game clock — pause-frozen and frame-rate independent.

    NEVER time.monotonic(): wall time advances while the sim is frozen, which
    made every tube instantly reload on unpause.  Deferred import is the
    established idiom in this module (see _spawn_torpedo)."""
    import App
    try:
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception:
        return 0.0
```

- [ ] **Step 4: Rewrite `TorpedoTube.__init__` and the reload methods**

Replace `TorpedoTube.__init__` (`weapon_subsystems.py:1634-1643`) — keep the class docstring but **replace its reload paragraph**, which is unsourced:

```python
    def __init__(self, name: str = ""):
        super().__init__(name)          # Weapon.__init__ seeds _firing/_target
        self._num_ready: int = 0
        # GAME time. BC inits to -1000.0 (combat-and-damage.md:757) so a fresh
        # tube already satisfies the ImmediateDelay gate. NOT -inf: -inf poisons
        # any subtraction a caller might do on GetLastFireTime().
        self._last_fire_time: float = -1000.0
        self._immediate_delay: float = 0.0
        self._reload_delay: float = 0.0
        self._max_ready: int = 0
        # One slot per MaxReady. Value = game time cooling began; _SLOT_LOADED = ready.
        self._reload_timers: list[float] = []

    def _resize_slots(self) -> None:
        """(Re)build the per-slot reload array to MaxReady, all slots loaded.
        Called by ships.py after the hardpoint property is copied in."""
        self._reload_timers = [_SLOT_LOADED] * max(0, int(self._max_ready))

    def _start_slot_cooldown(self, now: float) -> None:
        """Put one loaded slot into cooldown, stamped at `now`."""
        for i in range(len(self._reload_timers)):
            if self._reload_timers[i] == _SLOT_LOADED:
                self._reload_timers[i] = now
                return
```

Replace `CanFire` (`:1654-1657`):

```python
    def CanFire(self) -> int:
        """BC torpedo CanFire (combat-and-damage.md:822-826):
        powered AND num_ready > 0 AND the ImmediateDelay refire gate has expired.

        ImmediateDelay is a REFIRE GATE, not a fire->launch latency: it prevents
        rapid double-fires. Hardpoint values run 0.25s (galaxy) to 5.0s.
        The ammo reserve gate lives on the parent TorpedoSystem.StartFiring.
        """
        parent = self.GetParentSubsystem()
        if parent is None or not parent.IsOn():
            return 0
        if self._num_ready <= 0:
            return 0
        if _game_time() - self._last_fire_time < self._immediate_delay:
            return 0
        return 1
```

In `Fire` (`:1659-1677`), replace the timestamp block. Was:

```python
        self._num_ready -= 1
        import time as _time
        self._last_fire_time = _time.monotonic()
```

Now:

```python
        now = _game_time()
        self._num_ready -= 1
        self._last_fire_time = now
        self._start_slot_cooldown(now)
```

Replace `UpdateReload` (`:1733-1745`) wholesale:

```python
    def UpdateReload(self, dt: float = 0.0) -> None:
        """Poll each cooling slot; reload one when ReloadDelay of GAME time has passed.

        `dt` is accepted for call-site compatibility (host_loop._advance_weapons)
        and DELIBERATELY IGNORED. _advance_weapons runs once per RENDER frame with
        a constant TICK_DT = 1/60 (host_loop.py:6054, :5525) — it is NOT inside the
        fixed-timestep sim loop. Integrating dt there would make reload frame-rate
        dependent: a Galaxy tube would reload in 20s on a 120Hz display. BC compares
        against the game clock instead (combat-and-damage.md:812-815).

        Power throttles the reload: a half-powered torpedo system reloads at half
        rate (existing behaviour, preserved).
        """
        if self._num_ready >= self._max_ready:
            return
        parent = self.GetParentSubsystem()
        factor = (parent.GetNormalPowerPercentage()
                  if parent is not None else 1.0)
        if factor <= 0.0:
            return
        delay = self._reload_delay / factor
        now = _game_time()
        for slot in self._reload_timers:
            if slot != _SLOT_LOADED and now - slot >= delay:
                self.ReloadTorpedo()      # loads the OLDEST cooling slot
                return                    # one round per tick, as BC does

    def ReloadTorpedo(self) -> None:
        """Load one round into the oldest cooling slot. BC FUN_0057D8A0
        (combat-and-damage.md:786-793).

        BC says "find slot with greatest timer". Its timers count UP while
        cooling, so the greatest timer is the slot cooling LONGEST. We store
        cooldown START stamps, so the equivalent is the SMALLEST stamp.

        DIVERGENCE (deliberate, documented): BC decrements the magazine here
        ("total_ammo_consumed++"). We already debit ammo at FIRE time, in
        TorpedoSystem.StartFiring. Debiting again here would double-count.
        Aligning the debit point with BC is a follow-up; it touches TorpedoSystem.
        """
        if self._num_ready >= self._max_ready:
            return
        oldest_i, oldest_t = -1, None
        for i in range(len(self._reload_timers)):
            t = self._reload_timers[i]
            if t == _SLOT_LOADED:
                continue
            if oldest_t is None or t < oldest_t:
                oldest_i, oldest_t = i, t
        if oldest_i < 0:
            return
        self._reload_timers[oldest_i] = _SLOT_LOADED
        self._num_ready += 1

    def UnloadTorpedo(self) -> None:
        """Remove one ready round; its slot goes back into cooldown.
        BC FUN_0057D9A0 — used by SetAmmoType(type, immediate=1), which unloads
        every tube on an ammo-type switch (combat-and-damage.md:833-838)."""
        if self._num_ready <= 0:
            return
        self._num_ready -= 1
        self._start_slot_cooldown(_game_time())
```

- [ ] **Step 5: Size the slot array at construction**

`engine/appc/ships.py:1123-1129`, in `_copy_torpedo_tube_fields`, append one line after `tube._num_ready = tube._max_ready`:

```python
        def _copy_torpedo_tube_fields(tube, prop):
            """Copy reload constants, then preload tubes to MaxReady."""
            v = prop.GetImmediateDelay()
            if v is not None: tube._immediate_delay = float(v)
            v = prop.GetReloadDelay()
            if v is not None: tube._reload_delay = float(v)
            v = prop.GetMaxReady()
            if v is not None: tube._max_ready = int(v)
            tube._num_ready = tube._max_ready
            tube._resize_slots()     # one reload slot per MaxReady, all loaded
```

- [ ] **Step 6: Update `test_weapon_power_factor.py`**

`tests/unit/test_weapon_power_factor.py:141-215` — the 5 torpedo cases seed `_last_fire_time` from `time.monotonic()` (lines 154, 170, 184, 197, 209). Replace each `import time; tube._last_fire_time = time.monotonic() - N` with a game-clock drive, using the same `clock` fixture pattern as `test_torpedo_tube_reload.py`:

```python
    App.g_kTimerManager._time = 100.0
    tube.Fire()
    App.g_kTimerManager._time = 100.0 + elapsed
    tube.UpdateReload(0.0)
```

Add `tube._resize_slots()` wherever a torpedo tube is constructed by hand in that file, after `_max_ready` is set. Reset `App.g_kTimerManager._time = 0.0` in teardown.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_torpedo_tube_reload.py tests/unit/test_weapon_power_factor.py tests/unit/test_torpedo_tube_fire.py -v`
Expected: PASS (all)

- [ ] **Step 8: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`. Watch the torpedo integration tests (`test_fire_secondary_chain`, `test_sequential_firing_galaxy`, `test_torpedo_spread_volley`) — they fire tubes and now run on the game clock.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/weapon_subsystems.py engine/appc/ships.py \
        tests/unit/test_torpedo_tube_reload.py tests/unit/test_weapon_power_factor.py
git commit -m "fix(weapons): decompiled torpedo reload model — game clock, per-slot timers, ImmediateDelay gate

From the RE'd stbc.exe internals (combat-and-damage.md:740-830):

- last_fire_time is GAME time, init -1000.0. It was time.monotonic(), so wall
  time spent paused counted as reload progress: pause 40s, unpause, and every
  tube was instantly full.
- reload_timers is an array with ONE SLOT PER MaxReady. Four hardpoint families
  ship MaxReady=2 (keldon, galor, kessokmine, warbird) and a single scalar
  cannot represent two slots cooling out of phase.
- ImmediateDelay is a CanFire REFIRE GATE (gameTime - last_fire_time >=
  ImmediateDelay), not a fire->launch latency. It was loaded from the hardpoint
  and then ignored. Values run 0.25s to 5.0s.

Deliberately NOT dt-integration: _advance_weapons runs once per render frame with
a constant TICK_DT, so integrating dt would make reload frame-rate dependent."
```

---

## Task 4: `ET_TORPEDO_RELOAD` — define and broadcast

`ConditionTorpsReady.py:140,169` registers a broadcast handler for `ET_TORPEDO_RELOAD` **with the tube as Destination**. We have never defined the constant nor posted the event, so the handler is dead.

**Scope note:** `ET_TORPEDO_FIRED` is **NOT** part of this task — it is blocked on probe q12. Do not define or post it.

**Files:**
- Modify: `engine/appc/events.py` (add `ET_TORPEDO_RELOAD`)
- Modify: `App.py` (re-export it)
- Modify: `engine/appc/weapon_subsystems.py` (`TorpedoTube.ReloadTorpedo` posts the event)
- Test: `tests/unit/test_torpedo_reload_event.py` (create)

**Interfaces:**
- Consumes: `TorpedoTube.ReloadTorpedo()` (Task 3).
- Produces: `engine.appc.events.ET_TORPEDO_RELOAD: int = 0x1322`, re-exported as `App.ET_TORPEDO_RELOAD`.

**Value choice:** `0x1322` — the next free integer in our private block (current high is `ET_ADD_TO_REPAIR_LIST = 0x1321`, `App.py:1010`). We do **not** need BC's real integer: `App.py:762` declares our event values *"arbitrary but stable"*, and nothing interoperates with BC's numbering. Do **not** use `0x65`/`0x66` — they collide with `ET_ACTION_COMPLETED = 101` and `ET_MISSION_START = 102`.

**Source choice:** the tube's parent `TorpedoSystem`. This is a **choice, not a finding** — no SDK script reads `GetSource()` on a reload event, and the decompile does not say. Probe q12 will confirm or correct it.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_torpedo_reload_event.py`:

```python
"""ReloadTorpedo broadcasts ET_TORPEDO_RELOAD with the TUBE as Destination.

Conditions/ConditionTorpsReady.py:140  registers a broadcast handler filtered on
                                       the tube (4th arg = destination filter)
Conditions/ConditionTorpsReady.py:169  reads App.TorpedoTube_Cast(pEvent.GetDestination())

ET_TORPEDO_FIRED is deliberately NOT covered here -- it is blocked on probe q12.
Episode7.TorpedoFired destroys the event's GetDestination() subsystem on a 10%
roll, so a wrong Destination destroys the wrong subsystem.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


@pytest.fixture
def clock():
    App.g_kTimerManager._time = 0.0
    yield lambda t: setattr(App.g_kTimerManager, "_time", float(t))
    App.g_kTimerManager._time = 0.0


def test_et_torpedo_reload_is_a_real_int_not_a_stub():
    """An undefined App.ET_* falls through App's module __getattr__ to a
    _NamedStub, which is minted fresh on every access -- so a handler registered
    under it is unreachable forever."""
    assert isinstance(App.ET_TORPEDO_RELOAD, int)


def test_reload_broadcasts_with_the_tube_as_destination(clock):
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.25
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    system.AddChildSubsystem(tube)

    seen = []
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_TORPEDO_RELOAD, tube, __name__ + "._on_reload")
    globals()["_on_reload"] = lambda _obj, evt: seen.append(evt)

    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 0
    assert seen == []                     # nothing yet

    clock(140.0)
    tube.UpdateReload(0.0)

    assert tube.GetNumReady() == 1
    assert len(seen) == 1
    assert seen[0].GetDestination() is tube          # THE load-bearing assertion
    assert seen[0].GetSource() is system
    assert seen[0].GetEventType() == App.ET_TORPEDO_RELOAD
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_torpedo_reload_event.py -v`
Expected: FAIL — `test_et_torpedo_reload_is_a_real_int_not_a_stub` fails because `App.ET_TORPEDO_RELOAD` is an `App._NamedStub`, not an `int`.

- [ ] **Step 3: Define the constant**

`engine/appc/events.py`, after `ET_WARP_BUTTON_PRESSED` (line ~10):

```python
# Torpedo tube reloaded one round.  Destination = the TUBE
# (Conditions/ConditionTorpsReady.py:140,169).  Value is from our own private
# block -- App.py:762 declares our event ids "arbitrary but stable" and nothing
# interoperates with BC's numbering.  0x1321 is the current high water mark.
#
# NOTE: ET_TORPEDO_FIRED is deliberately NOT defined here.  It is blocked on
# probe q12 (docs/instrumented_experiments/2026-07-12-torpedo-event-probe.md):
# Episode7.TorpedoFired destroys the event's GetDestination() subsystem on a 10%
# roll, and nobody has RE'd the torpedo projectile path that posts it.
ET_TORPEDO_RELOAD: int = 0x1322
```

- [ ] **Step 4: Re-export it from `App.py`**

`App.py:2-10`, add `ET_TORPEDO_RELOAD` to the `from engine.appc.events import (...)` list:

```python
from engine.appc.events import (
    TGEvent, TGEvent_Create,
    TGBoolEvent, TGBoolEvent_Create,
    TGKeyboardEvent, ET_KEYBOARD_EVENT,
    WeaponHitEvent, ET_WEAPON_HIT, ET_WARP_BUTTON_PRESSED,
    ET_TORPEDO_RELOAD,
    ObjectExplodingEvent, ObjectExplodingEvent_Create,
    TGEventHandlerObject, TGEventManager,
    TGPythonInstanceWrapper,
    ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
```

- [ ] **Step 5: Post the event from `ReloadTorpedo`**

In `engine/appc/weapon_subsystems.py`, add the broadcast helper to `TorpedoTube` and call it at the end of `ReloadTorpedo` (written in Task 3):

```python
    def _broadcast_reload(self) -> None:
        """Post ET_TORPEDO_RELOAD with the TUBE as Destination.

        Destination is load-bearing: ConditionTorpsReady.py:140 registers with a
        tube destination-filter, and :169 casts GetDestination() to a TorpedoTube.

        Source = the parent TorpedoSystem. This is a CHOICE, not a finding -- no
        SDK script reads GetSource() on a reload event and the decompile does not
        say. Probe q12 will confirm or correct it.
        """
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_RELOAD)
            evt.SetDestination(self)
            evt.SetSource(self.GetParentSubsystem())
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_RELOAD broadcast", _e)
```

Then, in `ReloadTorpedo`, after `self._num_ready += 1`:

```python
        self._num_ready += 1
        self._broadcast_reload()
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_torpedo_reload_event.py tests/unit/test_torpedo_tube_reload.py -v`
Expected: PASS (all)

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/events.py App.py engine/appc/weapon_subsystems.py \
        tests/unit/test_torpedo_reload_event.py
git commit -m "feat(weapons): define and broadcast ET_TORPEDO_RELOAD (tube as destination)

ConditionTorpsReady.py:140,169 registers a broadcast handler filtered on the tube
and casts GetDestination() to a TorpedoTube. We never defined the constant nor
posted the event, so the handler was dead.

Value 0x1322 from our own private block -- App.py:762 declares our event ids
'arbitrary but stable'. NOT 0x65/0x66, which collide with ET_ACTION_COMPLETED
and ET_MISSION_START.

ET_TORPEDO_FIRED remains UNDEFINED: blocked on probe q12. Episode7.TorpedoFired
destroys the event's GetDestination() subsystem on a 10% roll, and the torpedo
projectile path that posts it has never been reverse-engineered."
```

---

## Task 5: `events.py` hardening — record stub keys, fix wrong-handler removal

Two real defects, both rooted in `_Stub`:

1. **Stub-typed event keys create silently dead handlers.** An `ET_*` name absent from our `App.py` falls through the module `__getattr__` (`App.py:1935-1946`) to a `_NamedStub`. `events.py` uses the event type as a **raw dict key** with no `int()` coercion (`:318`, `:329`, `:384`), `_Stub.__hash__` is `id(self)`, and `__getattr__` does **not** memoize `ET_*` — so **every access mints a fresh key**. Each registration lands in its own private, permanently unreachable slot. **89 distinct stub `ET_` names across ~270 SDK registration sites are dead this way.**

2. **`RemoveBroadcastHandler` can remove the WRONG handler.** It uses `entry in list` / `list.remove(entry)` (`:344-353`), which compares tuples element-wise with `==`. `_Stub.__eq__` is **type**-based, so *any* all-stub tuple compares equal to any other. Only the first tuple element needs to be a stub to trigger this.

**CRITICAL — record and warn, NEVER refuse.** `Tactical/Interface/CinematicInterfaceHandlers.py:15` holds a module-level stub as a **live same-object dispatch key** (registered at `:229`, fired at `:275` through that same global). Refusing stub-typed registrations would break it.

**Files:**
- Modify: `engine/appc/events.py` (`TGEventManager`)
- Test: `tests/unit/test_event_stub_key_hardening.py` (create)

**Interfaces:**
- Consumes: `engine.core.stub_telemetry.record_attr(owner_type: str, attr_name: str)`.
- Produces: module-level `_validate_event_type(event_type, where: str) -> bool` in `engine/appc/events.py`. **Module-level, not a method** — there are four registrars across three different classes (`TGEventHandlerObject`, `TGPythonInstanceWrapper`, `TGEventManager`), and a shared free function is the only way all four reach it without a fake-`self` hack.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_event_stub_key_hardening.py`:

```python
"""Stub-typed event keys are recorded, not silently dead. And removal is by identity.

An ET_* name absent from our App.py resolves through App's module __getattr__
(App.py:1935) to a _NamedStub. events.py keys handlers on the raw object;
_Stub.__hash__ is id(self) and __getattr__ does not memoize, so EVERY access
mints a fresh key -- the handler is unreachable forever. 89 distinct stub ET_
names across ~270 SDK registration sites are dead this way.

We RECORD (so it surfaces in docs/stub_heatmap.md) and WARN. We must NOT refuse:
Tactical/Interface/CinematicInterfaceHandlers.py:15 keeps a module-level stub as
a LIVE same-object dispatch key (registered :229, fired :275 through that same
global), and refusing would break it.
"""
import App
from engine.appc.events import TGEventManager
from engine.core import stub_telemetry


def test_stub_event_type_is_recorded_to_telemetry(monkeypatch):
    recorded = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: recorded.append((owner, attr)))

    mgr = TGEventManager()
    mgr.AddBroadcastPythonFuncHandler(
        App.ET_SOME_UNDEFINED_EVENT, object(), "mod.Func")

    assert recorded, "a stub-typed event key must be recorded, not silently dead"
    assert any("ET_SOME_UNDEFINED_EVENT" in str(attr) for _owner, attr in recorded)


def test_stub_event_type_registration_is_not_refused(monkeypatch):
    """CinematicInterfaceHandlers.py:15 relies on a live stub key. Refusing would
    break it -- we record and warn, then register anyway."""
    monkeypatch.setattr(stub_telemetry, "ENABLED", False)
    mgr = TGEventManager()
    key = App.ET_ANOTHER_UNDEFINED_EVENT      # capture ONE stub object

    mgr.AddBroadcastPythonFuncHandler(key, object(), "mod.Func")

    # Same-object lookup must still find it (that is the Cinematic pattern).
    assert mgr._broadcast_handlers.get(key), "registration must not be refused"


def test_remove_broadcast_handler_removes_the_correct_handler():
    """_Stub.__eq__ is TYPE-based, so any all-stub tuple == any other. With
    list.remove(), removing B's handler would delete A's."""
    mgr = TGEventManager()
    key = App.ET_YET_ANOTHER_UNDEFINED       # one stub, reused as the key
    dest_a = App.ET_STUB_A                   # two DIFFERENT stub "objects"
    dest_b = App.ET_STUB_B

    mgr.AddBroadcastPythonFuncHandler(key, dest_a, "Handler")
    mgr.AddBroadcastPythonFuncHandler(key, dest_b, "Handler")
    assert len(mgr._broadcast_handlers[key]) == 2

    mgr.RemoveBroadcastHandler(key, dest_b, "Handler")

    remaining = mgr._broadcast_handlers[key]
    assert len(remaining) == 1
    assert remaining[0][0] is dest_a, "removed the WRONG handler"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_event_stub_key_hardening.py -v`
Expected: FAIL — `test_stub_event_type_is_recorded_to_telemetry` fails (nothing recorded), and `test_remove_broadcast_handler_removes_the_correct_handler` fails (`remaining[0][0] is dest_b`, i.e. it deleted A).

- [ ] **Step 3: Add the validator**

`engine/appc/events.py` — add the import at the top (line 3):

```python
from engine.core.ids import TGObject
from engine.core import stub_telemetry
```

Then add this **module-level** function, above `class TGEventHandlerObject` (~line 190). It must be module-level, not a method: four registrars across three different classes need it, and a free function is the only way all four reach it without passing a fake `self`.

```python
# Undefined event-type names already warned about, so a per-frame registration
# cannot spam the log.
_warned_event_types: set[str] = set()


def _validate_event_type(event_type, where: str) -> bool:
    """False if `event_type` is not a usable dict key.

    An ET_* constant absent from our App.py resolves through App's module
    __getattr__ (App.py:1935) to a _NamedStub. We key handlers on the raw
    object; _Stub.__hash__ is id(self) and __getattr__ does NOT memoize ET_*
    names, so every access mints a FRESH key -- the handler becomes unreachable
    forever. 89 stub ET_ names across ~270 SDK sites are dead this way.

    We RECORD (surfacing it in docs/stub_heatmap.md) and warn once per name. We
    do NOT refuse: Tactical/Interface/CinematicInterfaceHandlers.py:15 keeps a
    module-level stub as a LIVE same-object dispatch key (registered :229, fired
    :275 through that same global), so refusing would break it.

    Test `not isinstance(x, int)` -- NOT isinstance(x, App._NamedStub). There are
    two unrelated _Stub hierarchies (App._Stub and engine.core.ids._Stub) and a
    class check would miss one.
    """
    if isinstance(event_type, int):
        return True
    name = str(getattr(event_type, "_name", None) or repr(event_type))
    stub_telemetry.record_attr("EventType", name)
    if name not in _warned_event_types:
        _warned_event_types.add(name)
        print(
            "WARNING: %s registered on undefined event type %s -- this handler "
            "can never fire. Define it in engine/appc/events.py."
            % (where, name),
            file=sys.stderr,
        )
    return False
```

- [ ] **Step 4: Call it from every registration entry point**

There are **four** registrars. Add the call as the first line of each. The return value is deliberately ignored — we record, we do not refuse.

`TGEventManager.AddBroadcastPythonFuncHandler` (`:315`):

```python
    def AddBroadcastPythonFuncHandler(
        self, event_type: int, dest: "TGEventHandlerObject", qualified_name: str, *extra
    ) -> None:
        _validate_event_type(event_type, "AddBroadcastPythonFuncHandler(%s)" % qualified_name)
        self._broadcast_handlers.setdefault(event_type, []).append((dest, qualified_name))
```

`TGEventManager.AddBroadcastPythonMethodHandler` (`:320`) — first line after the docstring:

```python
        _validate_event_type(event_type, "AddBroadcastPythonMethodHandler(%s)" % method_name)
        self._method_handlers.setdefault(event_type, []).append(
            (wrapper, method_name, target)
        )
```

`TGEventHandlerObject.AddPythonFuncHandlerForInstance` (`:198`) — first line:

```python
        _validate_event_type(event_type, "AddPythonFuncHandlerForInstance(%s)" % qualified_name)
```

`TGPythonInstanceWrapper.AddPythonMethodHandlerForInstance` (`:284`) — first line:

```python
        _validate_event_type(event_type, "AddPythonMethodHandlerForInstance(%s)" % method_name)
```

**These last two matter most.** They are the instance-level registrars, and they are where the bulk of SDK handler registrations actually land — hardening only the manager would miss them.

- [ ] **Step 5: Fix `RemoveBroadcastHandler` to remove by identity**

Replace the body (`:344-353`):

```python
        # Func handlers: (dest, qualified_name).  Identity-compare the object.
        # `entry in list` / list.remove() compare with ==, and _Stub.__eq__ is
        # TYPE-based -- any all-stub tuple equals any other, so == would delete
        # the WRONG handler. Only the first element needs to be a stub.
        func_handlers = self._broadcast_handlers.get(event_type, [])
        for i, (d, q) in enumerate(func_handlers):
            if d is dest_or_wrapper and q == qualified_name_or_method:
                del func_handlers[i]
                return
        # Method handlers: (wrapper, method_name, target).
        method_handlers = self._method_handlers.get(event_type, [])
        for i, (w, m, t) in enumerate(method_handlers):
            if w is dest_or_wrapper and m == qualified_name_or_method and t is target:
                del method_handlers[i]
                return
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_event_stub_key_hardening.py -v`
Expected: PASS (all)

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`.

Note: the new warning will now print for the 89 stub `ET_` names during any run that loads SDK scripts. That is the point — but confirm it is once-per-name and not per-frame.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/events.py tests/unit/test_event_stub_key_hardening.py
git commit -m "fix(events): record stub-typed event keys; remove handlers by identity

Two defects rooted in _Stub:

1. An ET_* absent from our App.py resolves to a _NamedStub. events.py keys
   handlers on the raw object; _Stub.__hash__ is id(self) and App's __getattr__
   does not memoize ET_*, so every access mints a FRESH key and the handler is
   unreachable forever. 89 stub ET_ names / ~270 SDK registration sites are dead
   this way. Now recorded to stub_telemetry (surfacing in docs/stub_heatmap.md)
   and warned once per name.

   We RECORD, we do NOT REFUSE: CinematicInterfaceHandlers.py:15 keeps a
   module-level stub as a LIVE same-object dispatch key.

2. RemoveBroadcastHandler used list.remove(), which compares with ==. _Stub.__eq__
   is TYPE-based, so any all-stub tuple equals any other and it could delete the
   WRONG handler. Now removes by identity."
```

---

## Task 6: Delete the phantom `UpdateCharge` / `GetMaxCharge` probes

`UpdateCharge` and `GetMaxCharge` are **not part of BC's `TorpedoTube` API and never were** — they are bound exclusively on `EnergyWeapon` (`sdk/.../App.py:6426-6440`), and `TorpedoTubeProperty` carries no charge fields. `Actions/ShipScriptActions.py:355-400` restores *charge* for energy weapons, then switches to a completely different mechanism (`LoadAmmoType`/`FillAmmoType`) for torpedoes.

**Ranks 1 and 2 of `docs/stub_heatmap.md` — 4.5M hits — come entirely from our own code** probing tubes for an API they cannot have. `hasattr` is always `True` (the `_Stub` catch-all), so `host_loop` then *calls* the stub on every tube every frame.

After Task 1's re-parent this is enforced structurally: a `Weapon` has no charge API to probe for.

**Files:**
- Modify: `engine/host_loop.py:487-490`
- Modify: `engine/ui/weapons_display_panel.py:222-238`

**Interfaces:**
- Consumes: `TorpedoTube` (Task 1), `_EnergyWeaponFireMixin` (existing, `weapon_subsystems.py:335`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_no_phantom_charge_probe.py`. The key assertion is behavioural, not structural: **run `_advance_weapons` and assert it records no stub hit for `TorpedoTube.UpdateCharge`.** The `hasattr` probe triggers `TGObject.__getattr__`, which records telemetry — so this test is genuinely RED today and GREEN after the fix.

```python
"""_advance_weapons must not probe a torpedo tube for an EnergyWeapon API.

UpdateCharge/GetMaxCharge are bound exclusively on EnergyWeapon
(sdk/Build/scripts/App.py:6426-6440). BC's TorpedoTube never had them. But
host_loop.py:487 guarded with `hasattr(emitter, "UpdateCharge")`, and hasattr is
VACUOUSLY TRUE on every subsystem -- TGObject.__getattr__ (engine/core/ids.py:125)
returns a truthy _Stub for any missing attribute. So host_loop CALLED that stub on
every tube, every frame: 3.3M hits, rank 1 of docs/stub_heatmap.md.

This test asserts the probe is gone by watching stub_telemetry, which is what the
hasattr() lookup trips.
"""
from engine.appc.subsystems import TorpedoSystem, TorpedoTube, _EnergyWeaponFireMixin
from engine.core import stub_telemetry
from engine.host_loop import _advance_weapons


def _mro_has(cls, name: str) -> bool:
    return any(name in klass.__dict__ for klass in cls.__mro__)


def test_hasattr_is_vacuously_true_here(monkeypatch):
    """Guard-rail documenting WHY isinstance is required. If this ever fails,
    _Stub's catch-all changed and the dispatch rule can be revisited."""
    tube = TorpedoTube("Forward Torpedo 1")
    assert hasattr(tube, "UpdateCharge")          # !!! true, and it is a _Stub
    assert hasattr(tube, "TotallyMadeUpMethod")   # !!! also true


def test_torpedo_tube_has_no_charge_api_in_its_mro():
    assert not _mro_has(TorpedoTube, "UpdateCharge")
    assert not _mro_has(TorpedoTube, "GetMaxCharge")
    assert not isinstance(TorpedoTube("t"), _EnergyWeaponFireMixin)


def test_advance_weapons_never_probes_a_tube_for_updatecharge(monkeypatch):
    """THE regression test. Ranks 1 and 2 of the heatmap, 4.5M hits."""
    hits = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: hits.append((owner, attr)))

    class _Ship:
        def __init__(self, system):
            self._system = system
        def GetTorpedoSystem(self):     return self._system
        def GetPhaserSystem(self):      return None
        def GetPulseWeaponSystem(self): return None
        def GetTractorBeamSystem(self): return None

    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    system.AddChildSubsystem(tube)

    _advance_weapons([_Ship(system)], 1.0 / 60.0)

    charge_probes = [h for h in hits if h[1] in ("UpdateCharge", "GetMaxCharge")]
    assert charge_probes == [], (
        "_advance_weapons still probes a tube for an EnergyWeapon API: %r"
        % (charge_probes,))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_no_phantom_charge_probe.py -v`
Expected: FAIL on `test_advance_weapons_never_probes_a_tube_for_updatecharge` — `hasattr(emitter, "UpdateCharge")` at `host_loop.py:487` trips `TGObject.__getattr__`, which records `("TorpedoTube", "UpdateCharge")`. **That recorded hit IS rank 1 of the heatmap.** The other two tests pass already (Task 1 made them structurally true) and serve as guard-rails.

- [ ] **Step 3: Fix `_advance_weapons`**

`engine/host_loop.py:487-490`. Replace:

```python
                if hasattr(emitter, "UpdateCharge"):
                    emitter.UpdateCharge(dt)
                if isinstance(emitter, TorpedoTube):
                    emitter.UpdateReload(dt)
```

with:

```python
                # isinstance, NOT hasattr: TGObject.__getattr__ returns a truthy
                # _Stub for any missing attribute, so hasattr() is vacuously True
                # on every subsystem. The old hasattr(emitter, "UpdateCharge")
                # guard therefore CALLED a no-op stub on every torpedo tube, every
                # frame -- ranks 1 and 2 of docs/stub_heatmap.md, 4.5M hits.
                # Charge is an EnergyWeapon concept (App.py:6426-6440); a
                # TorpedoTube cannot have it.
                if isinstance(emitter, TorpedoTube):
                    emitter.UpdateReload(dt)
                elif isinstance(emitter, _EnergyWeaponFireMixin):
                    emitter.UpdateCharge(dt)
```

Add `_EnergyWeaponFireMixin` to the `engine.appc.subsystems` import block at `host_loop.py:81` (which already imports `TorpedoTube`).

- [ ] **Step 4: Fix `_has_charge_model`**

`engine/ui/weapons_display_panel.py:222-238`. Replace the whole function — **its docstring is factually wrong**: it claims a tube has a zero `_max_charge`, but there is no `_max_charge` on a tube at all; the zero came from `_Stub.__float__`.

```python
def _has_charge_model(mount) -> bool:
    """True when the mount carries an energy-weapon charge reservoir.

    isinstance, NOT hasattr: TGObject.__getattr__ returns a truthy _Stub for any
    missing attribute, so `hasattr(mount, "GetMaxCharge")` is True even for a
    torpedo tube -- which is where rank 2 of docs/stub_heatmap.md (1.2M hits)
    came from.

    Charge is an EnergyWeapon concept (sdk/.../App.py:6426-6440): PhaserBank,
    PulseWeapon and TractorBeam have it; TorpedoTube does not and never did. A
    tube's readiness is discrete ammo + a reload timer -- see _has_reload_model.
    """
    from engine.appc.subsystems import _EnergyWeaponFireMixin
    if not isinstance(mount, _EnergyWeaponFireMixin):
        return False
    try:
        return float(mount.GetMaxCharge()) > 0.0
    except Exception:
        return False
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_no_phantom_charge_probe.py tests/unit/test_torpedo_tube_weapon_base.py tests/host/test_weapons_display_panel.py -v`
Expected: PASS (all)

- [ ] **Step 6: Verify the heatmap claim empirically**

This is the whole point of the task — prove `TorpedoTube` leaves the rankings.

```bash
DAUNTLESS_STUB_TELEMETRY=1 uv run pytest tests/integration/test_sequential_firing_galaxy.py -v
```

Then inspect the emitted report: there must be **no `TorpedoTube` / `UpdateCharge` or `TorpedoTube` / `GetMaxCharge` rows**. If either still appears, a `hasattr` probe survives somewhere — grep for it rather than assuming.

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py engine/ui/weapons_display_panel.py \
        tests/unit/test_no_phantom_charge_probe.py
git commit -m "fix(weapons): delete phantom UpdateCharge/GetMaxCharge probes on torpedo tubes

Ranks 1 and 2 of docs/stub_heatmap.md -- 4.5M hits -- were entirely self-inflicted.
UpdateCharge and GetMaxCharge are bound exclusively on EnergyWeapon
(sdk/.../App.py:6426-6440); BC's TorpedoTube never had them. Our own code was
asking a tube for an API it cannot have:

  host_loop.py:487            hasattr(emitter, 'UpdateCharge')
  weapons_display_panel.py:233 hasattr(mount, 'GetMaxCharge')

hasattr() is VACUOUSLY TRUE on every subsystem -- TGObject.__getattr__ returns a
truthy _Stub -- so host_loop then CALLED the stub on every tube, every frame.
Now dispatched on isinstance. After the Weapon re-parent this is structural: a
Weapon has no charge API to probe for.

Also corrects weapons_display_panel's docstring, which claimed a tube has a zero
_max_charge. It has no _max_charge at all; the zero came from _Stub.__float__."
```

---

## Out of scope (recorded in the spec, do NOT do here)

1. **`EnergyWeapon(Weapon)`** — migrate `PhaserBank`/`PulseWeapon`/`TractorBeam` off `WeaponSystem`. **The agreed immediate follow-up project.**
2. **`_advance_weapons` runs once per render frame with a constant `TICK_DT`** (`host_loop.py:6054`), so `UpdateCharge` — phaser/pulse/tractor recharge — **is frame-rate dependent today**. Real bug, pre-existing. This plan sidesteps it for torpedoes by using the game clock.
3. **`ET_TORPEDO_FIRED`** — blocked on probe q12.
4. **Ammo debit point** — BC debits the magazine in `ReloadTorpedo`; we debit at `Fire`. Documented divergence in Task 3.
5. **`sensor_detection.py:63`** calls a non-existent `g_kTimerManager.GetGameTime()` and silently returns 0.0 forever.
6. **`ET_CLOAKED_COLLISION` and `ET_POWER_FRACTION_CHANGED` are both `1075`** (`App.py:913`, `:941`).

## Live sign-off (after q12 unblocks `ET_TORPEDO_FIRED`)

E7M1 — fire phased-plasma torpedoes; a tube should occasionally be destroyed with the correct Felix/Saffi/Brex dialogue and the correct forward/aft branch.
