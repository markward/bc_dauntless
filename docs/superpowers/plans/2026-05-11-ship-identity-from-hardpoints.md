# Ship Identity from Hardpoints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Broaden `loadspacehelper.CreateShip` → `SetupProperties` so every E1M1 ship type ends up with complete identity (genus, species, affiliation, AI string, ship name, full hull/impulse/warp/sensor/shield/weapon-system data) on the live `ShipClass`, plus minimum live state seeding (full hull, full shields, loaded torpedo tubes).

**Architecture:** Extend the existing `isinstance`-dispatch `SetupProperties` walk with explicit per-field getter→setter copies, add a new `ShieldSubsystem`, reparent `WeaponSystem` under `PoweredSubsystem`, and promote four shared identity fields (`_critical / _targetable / _primary / _disabled_percentage`) to the `ShipSubsystem` base. Verified by parametrized integration test across eight ship types whose expected values are cross-checked against the actual `Set*` calls in the SDK hardpoint files at test load time.

**Tech Stack:** Python 3.13, pytest, existing `engine.appc.{ships,subsystems,properties}` modules, SDK `ships/Hardpoints/*.py` files.

**Spec:** [docs/superpowers/specs/2026-05-11-ship-identity-from-hardpoints-design.md](../specs/2026-05-11-ship-identity-from-hardpoints-design.md)

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| [App.py](../../../App.py) | Phase 1 `Appc.dll` shim; defines `AT_*` ammo constants | Modify (add ammo constants) |
| [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) | Subsystem class hierarchy + per-instance state | Modify (new `ShieldSubsystem`, reparent `WeaponSystem`, add identity fields) |
| [engine/appc/ships.py](../../../engine/appc/ships.py) | `ShipClass` + `SetupProperties` template→ship dispatch | Modify (new identity fields, broaden `SetupProperties`) |
| [tests/integration/test_e1m1_ship_identity.py](../../../tests/integration/test_e1m1_ship_identity.py) | Parametrized E1M1 identity assertions | Create |
| [tests/integration/_hardpoint_parser.py](../../../tests/integration/_hardpoint_parser.py) | Helper that extracts `Set*` values from a hardpoint .py for cross-check | Create |

No changes to `engine/appc/properties.py` — its data-bag base class already supports every new getter.

---

## Task 1: Add `AT_*` ammo-type constants to App.py

Background: torpedo tubes in `SetupProperties` Pass 2 call `AddAmmoType(App.AT_ONE)`. Today `App.AT_ONE` returns a `_NamedStub` instance, and `_Stub.__eq__` returns True for *any* two `_NamedStub` instances — so `AT_ONE` is indistinguishable from `AT_TWO`. Real integer constants fix this.

**Files:**
- Modify: [App.py](../../../App.py)
- Test: [tests/unit/test_app_ammo_constants.py](../../../tests/unit/test_app_ammo_constants.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_app_ammo_constants.py`:

```python
"""AT_* ammo-type constants on the App shim."""
import App


def test_at_one_is_int():
    assert isinstance(App.AT_ONE, int)


def test_at_constants_are_distinct():
    constants = [App.AT_ONE, App.AT_TWO, App.AT_THREE, App.AT_FOUR, App.AT_FIVE]
    assert len(set(constants)) == 5, f"AT_* constants must be distinct: {constants}"


def test_at_one_equals_at_one():
    # Sanity: same constant referenced twice compares equal.
    assert App.AT_ONE == App.AT_ONE
    # And differs from AT_TWO.
    assert App.AT_ONE != App.AT_TWO
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_app_ammo_constants.py -v
```

Expected: `test_at_one_is_int` fails with `AssertionError: assert False` (because `App.AT_ONE` is a `_NamedStub`).

- [ ] **Step 3: Add the constants**

In [App.py](../../../App.py), find a good location (e.g. right after the `CT_*` constants block near line 161). Add:

```python
# ── App.AT_* ammo-type constants ─────────────────────────────────────────────
# SDK code uses these as ints in TorpedoSystem.SetAmmoType / AddAmmoType
# (e.g. E2M0.py: pTorps.SetAmmoType(App.AT_TWO, 0)).  Values are arbitrary
# distinct ints — Phase 1 never round-trips them to a real engine.
AT_ONE   = 0
AT_TWO   = 1
AT_THREE = 2
AT_FOUR  = 3
AT_FIVE  = 4
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_app_ammo_constants.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Confirm no regressions in existing tests**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_app_ammo_constants.py
git commit -m "$(cat <<'EOF'
feat(app): AT_* ammo-type constants as real ints

Replace _NamedStub fallback for App.AT_ONE/AT_TWO/etc. so tests can
distinguish ammo loadouts. Used by upcoming torpedo-tube seeding work.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Promote shared identity fields to `ShipSubsystem` base

Add `_critical`, `_targetable`, `_primary`, `_disabled_percentage` to the base `ShipSubsystem`. Replaces the hard-coded `GetDisabledPercentage() == 0.25` with a real backing field that the upcoming `SetupProperties` extension can write into.

**Files:**
- Modify: [engine/appc/subsystems.py:20-133](../../../engine/appc/subsystems.py#L20-L133)
- Test: [tests/unit/test_subsystem_identity_fields.py](../../../tests/unit/test_subsystem_identity_fields.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_subsystem_identity_fields.py`:

```python
"""ShipSubsystem base identity fields: critical/targetable/primary/disabled."""
from engine.appc.subsystems import ShipSubsystem


def test_defaults():
    s = ShipSubsystem("Test")
    assert s.GetCritical() == 0
    assert s.GetTargetable() == 0
    assert s.GetPrimary() == 0
    assert s.GetDisabledPercentage() == 0.25


def test_setters_persist():
    s = ShipSubsystem("Test")
    s.SetCritical(1)
    s.SetTargetable(1)
    s.SetPrimary(1)
    s.SetDisabledPercentage(0.5)
    assert s.GetCritical() == 1
    assert s.GetTargetable() == 1
    assert s.GetPrimary() == 1
    assert s.GetDisabledPercentage() == 0.5


def test_disabled_percentage_is_field_not_constant():
    """Two instances should hold independent values."""
    a = ShipSubsystem("A")
    b = ShipSubsystem("B")
    a.SetDisabledPercentage(0.75)
    assert b.GetDisabledPercentage() == 0.25  # untouched
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_subsystem_identity_fields.py -v
```

Expected: fails (GetCritical/SetCritical don't exist; GetDisabledPercentage is the hardcoded 0.25 method, not field-backed).

- [ ] **Step 3: Modify `ShipSubsystem.__init__` and replace `GetDisabledPercentage`**

In [engine/appc/subsystems.py:20-34](../../../engine/appc/subsystems.py#L20-L34), extend `__init__`:

```python
class ShipSubsystem(TGEventHandlerObject):
    def __init__(self, name: str = ""):
        super().__init__()
        self._name = name
        self._property = None
        self._parent_ship = None
        self._parent_subsystem = None
        self._child_subsystem = None
        self._condition = 1.0
        self._max_condition = 1.0
        self._radius = 0.0
        self._position = TGPoint3(0.0, 0.0, 0.0)
        # Shared identity fields populated by SetupProperties.
        self._critical: int = 0
        self._targetable: int = 0
        self._primary: int = 0
        self._disabled_percentage: float = 0.25
```

Then find and **delete** the existing `GetDisabledPercentage` method (currently at [engine/appc/subsystems.py:129-133](../../../engine/appc/subsystems.py#L129-L133)) — it's a hardcoded `return 0.25`. Replace with field-backed accessors at the end of the class body:

```python
    def GetCritical(self) -> int:                       return self._critical
    def SetCritical(self, v) -> None:                   self._critical = int(v)
    def GetTargetable(self) -> int:                     return self._targetable
    def SetTargetable(self, v) -> None:                 self._targetable = int(v)
    def GetPrimary(self) -> int:                        return self._primary
    def SetPrimary(self, v) -> None:                    self._primary = int(v)
    def GetDisabledPercentage(self) -> float:           return self._disabled_percentage
    def SetDisabledPercentage(self, v) -> None:         self._disabled_percentage = float(v)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_subsystem_identity_fields.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_subsystem_identity_fields.py
git commit -m "$(cat <<'EOF'
feat(subsystems): promote critical/targetable/primary/disabled to base

Replaces hardcoded GetDisabledPercentage()==0.25 with a real field so
upcoming SetupProperties extension can write per-subsystem values.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Reparent `WeaponSystem` under `PoweredSubsystem`

`WeaponSystemProperty` extends `PoweredSubsystemProperty`, so every concrete weapon system in BC has a power line. The current `WeaponSystem(ShipSubsystem)` leaves `SetNormalPowerPerSecond` unimplemented on PhaserSystem/TorpedoSystem/PulseWeaponSystem/TractorBeamSystem.

**Files:**
- Modify: [engine/appc/subsystems.py:156-161](../../../engine/appc/subsystems.py#L156-L161)
- Test: [tests/unit/test_weapon_system_powered.py](../../../tests/unit/test_weapon_system_powered.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_weapon_system_powered.py`:

```python
"""WeaponSystem subclasses should expose PoweredSubsystem's power API."""
from engine.appc.subsystems import (
    PoweredSubsystem, WeaponSystem,
    PhaserSystem, TorpedoSystem, PulseWeaponSystem, TractorBeamSystem,
)


def test_weapon_system_is_powered():
    assert issubclass(WeaponSystem, PoweredSubsystem)


def test_phaser_has_power_accessors():
    p = PhaserSystem("Phaser System")
    p.SetNormalPowerPerSecond(300.0)
    assert p.GetNormalPowerPerSecond() == 300.0


def test_torpedo_has_power_accessors():
    t = TorpedoSystem("Torpedo System")
    t.SetNormalPowerPerSecond(50.0)
    assert t.GetNormalPowerPerSecond() == 50.0


def test_pulse_and_tractor_have_power_accessors():
    PulseWeaponSystem("Pulse").SetNormalPowerPerSecond(100.0)
    TractorBeamSystem("Tractor").SetNormalPowerPerSecond(75.0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_weapon_system_powered.py -v
```

Expected: `test_weapon_system_is_powered` fails.

- [ ] **Step 3: Reparent `WeaponSystem`**

In [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) change the class declaration:

```python
class WeaponSystem(PoweredSubsystem):
    """Weapon system — has firing state and an optional target.

    Reparented under PoweredSubsystem because every weapon system in BC
    has a power line.  See sdk/.../App.py:6361 (WeaponSystem inherits
    PoweredSubsystem there).
    """
```

(was: `class WeaponSystem(ShipSubsystem):`)

Keep the existing `__init__` body; `super().__init__(name)` already chains correctly.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_weapon_system_powered.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Confirm no regressions in existing tests**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass. (No existing tests `isinstance`-check `WeaponSystem` against `ShipSubsystem` directly — only against the concrete classes.)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_weapon_system_powered.py
git commit -m "$(cat <<'EOF'
feat(subsystems): reparent WeaponSystem under PoweredSubsystem

Every concrete weapon system in BC has a power line. Lets PhaserSystem /
TorpedoSystem / PulseWeaponSystem / TractorBeamSystem inherit
SetNormalPowerPerSecond / GetNormalPowerPerSecond.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add identity fields to `SensorSubsystem`

`SensorProperty` carries `BaseSensorRange` and `MaxProbes`; the live `SensorSubsystem` currently has neither.

**Files:**
- Modify: [engine/appc/subsystems.py:258-259](../../../engine/appc/subsystems.py#L258-L259)
- Test: [tests/unit/test_sensor_subsystem_identity.py](../../../tests/unit/test_sensor_subsystem_identity.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sensor_subsystem_identity.py`:

```python
"""SensorSubsystem identity fields: BaseSensorRange + MaxProbes."""
from engine.appc.subsystems import SensorSubsystem


def test_defaults():
    s = SensorSubsystem("Sensor Array")
    assert s.GetBaseSensorRange() == 0.0
    assert s.GetMaxProbes() == 0


def test_setters_persist():
    s = SensorSubsystem("Sensor Array")
    s.SetBaseSensorRange(2000.0)
    s.SetMaxProbes(10)
    assert s.GetBaseSensorRange() == 2000.0
    assert s.GetMaxProbes() == 10
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_sensor_subsystem_identity.py -v
```

Expected: fails (GetBaseSensorRange does not exist).

- [ ] **Step 3: Replace the `pass` body of `SensorSubsystem`**

In [engine/appc/subsystems.py:258-259](../../../engine/appc/subsystems.py#L258-L259):

```python
class SensorSubsystem(PoweredSubsystem):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._base_sensor_range: float = 0.0
        self._max_probes: int = 0

    def GetBaseSensorRange(self) -> float:           return self._base_sensor_range
    def SetBaseSensorRange(self, v) -> None:         self._base_sensor_range = float(v)
    def GetMaxProbes(self) -> int:                   return self._max_probes
    def SetMaxProbes(self, v) -> None:               self._max_probes = int(v)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_sensor_subsystem_identity.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_sensor_subsystem_identity.py
git commit -m "$(cat <<'EOF'
feat(subsystems): SensorSubsystem identity (BaseSensorRange, MaxProbes)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add identity fields to `PhaserSystem`

`WeaponSystemProperty(WST_PHASER)` carries `WeaponSystemType`, `SingleFire`, `AimedWeapon`. PhaserSystem already has `PowerLevel`; add the three identity fields.

**Files:**
- Modify: [engine/appc/subsystems.py:208-221](../../../engine/appc/subsystems.py#L208-L221)
- Test: [tests/unit/test_phaser_system_identity.py](../../../tests/unit/test_phaser_system_identity.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_phaser_system_identity.py`:

```python
"""PhaserSystem identity fields: weapon-system type, single-fire, aimed."""
from engine.appc.subsystems import PhaserSystem


def test_defaults():
    p = PhaserSystem("Phaser System")
    assert p.GetWeaponSystemType() == 0
    assert p.GetSingleFire() == 0
    assert p.GetAimedWeapon() == 0


def test_setters_persist():
    p = PhaserSystem("Phaser System")
    p.SetWeaponSystemType(1)
    p.SetSingleFire(1)
    p.SetAimedWeapon(0)
    assert p.GetWeaponSystemType() == 1
    assert p.GetSingleFire() == 1
    assert p.GetAimedWeapon() == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_phaser_system_identity.py -v
```

Expected: fails (GetWeaponSystemType does not exist).

- [ ] **Step 3: Extend `PhaserSystem.__init__` and accessors**

In [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) modify `PhaserSystem`:

```python
class PhaserSystem(WeaponSystem):
    # Power-level constants from sdk/.../App.py:6444-6446.
    PP_LOW = 0
    PP_HIGH = 1

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._power_level = self.PP_HIGH
        self._weapon_system_type: int = 0
        self._single_fire: int = 0
        self._aimed_weapon: int = 0

    def SetPowerLevel(self, level) -> None:
        self._power_level = int(level)

    def GetPowerLevel(self) -> int:
        return self._power_level

    def GetWeaponSystemType(self) -> int:           return self._weapon_system_type
    def SetWeaponSystemType(self, v) -> None:       self._weapon_system_type = int(v)
    def GetSingleFire(self) -> int:                 return self._single_fire
    def SetSingleFire(self, v) -> None:             self._single_fire = int(v)
    def GetAimedWeapon(self) -> int:                return self._aimed_weapon
    def SetAimedWeapon(self, v) -> None:            self._aimed_weapon = int(v)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_phaser_system_identity.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_phaser_system_identity.py
git commit -m "$(cat <<'EOF'
feat(subsystems): PhaserSystem identity (weapon-system type, single fire, aimed)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Create `ShieldSubsystem` class

Six face slots indexed by `ShieldProperty.FRONT_SHIELDS`..`RIGHT_SHIELDS`. Setting a max seeds current to that max when current was 0 (mirrors `HullSubsystem.SetMaxCondition` seeding).

**Files:**
- Modify: [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) (append new class)
- Test: [tests/unit/test_shield_subsystem.py](../../../tests/unit/test_shield_subsystem.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_shield_subsystem.py`:

```python
"""ShieldSubsystem: six-face shield slots with seed-on-max behavior."""
from engine.appc.subsystems import ShieldSubsystem, PoweredSubsystem
from engine.appc.properties import ShieldProperty


def test_is_powered_subsystem():
    assert issubclass(ShieldSubsystem, PoweredSubsystem)


def test_defaults_zero_per_face():
    s = ShieldSubsystem("Shield Generator")
    for face in range(ShieldProperty.NUM_SHIELDS):
        assert s.GetMaxShields(face) == 0.0
        assert s.GetCurrentShields(face) == 0.0
        assert s.GetShieldChargePerSecond(face) == 0.0


def test_set_max_seeds_current_when_current_zero():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    assert s.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 8000.0


def test_set_max_does_not_overwrite_nonzero_current():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    s.SetCurrentShields(ShieldProperty.FRONT_SHIELDS, 3000.0)  # take damage
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 10000.0)     # repair upgrade
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 3000.0  # unchanged


def test_charge_per_second():
    s = ShieldSubsystem("Shield Generator")
    s.SetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS, 11.0)
    assert s.GetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS) == 11.0


def test_faces_are_independent():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    s.SetMaxShields(ShieldProperty.REAR_SHIELDS, 4000.0)
    assert s.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert s.GetMaxShields(ShieldProperty.REAR_SHIELDS) == 4000.0
    assert s.GetMaxShields(ShieldProperty.TOP_SHIELDS) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_shield_subsystem.py -v
```

Expected: ImportError on `ShieldSubsystem`.

- [ ] **Step 3: Append `ShieldSubsystem` to subsystems.py**

In [engine/appc/subsystems.py](../../../engine/appc/subsystems.py), add after `WarpEngineSubsystem` (before the module-level `_warp_effect_time_default`):

```python
class ShieldSubsystem(PoweredSubsystem):
    """Six-face shield generator.

    Faces indexed by ShieldProperty.FRONT_SHIELDS..RIGHT_SHIELDS (0..5).
    SetMaxShields seeds current to that max when current was 0 — mirrors
    HullSubsystem.SetMaxCondition so freshly-loaded ships start fully shielded.
    """
    NUM_FACES = 6

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_shields:       list[float] = [0.0] * self.NUM_FACES
        self._current_shields:   list[float] = [0.0] * self.NUM_FACES
        self._charge_per_second: list[float] = [0.0] * self.NUM_FACES

    def GetMaxShields(self, face: int) -> float:
        return self._max_shields[int(face)]

    def SetMaxShields(self, face: int, value: float) -> None:
        f = int(face)
        v = float(value)
        if self._current_shields[f] == 0.0:
            self._current_shields[f] = v
        self._max_shields[f] = v

    def GetCurrentShields(self, face: int) -> float:
        return self._current_shields[int(face)]

    def SetCurrentShields(self, face: int, value: float) -> None:
        self._current_shields[int(face)] = float(value)

    def GetShieldChargePerSecond(self, face: int) -> float:
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face: int, value: float) -> None:
        self._charge_per_second[int(face)] = float(value)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_shield_subsystem.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_subsystem.py
git commit -m "$(cat <<'EOF'
feat(subsystems): ShieldSubsystem with six-face shield state

Each face tracks max/current/charge-rate independently. SetMaxShields
seeds current to max when current was 0 so freshly-loaded ships start
fully shielded.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Wire `ShieldSubsystem` into `ShipClass`

Add `_shield_subsystem` slot, accessors, and instantiation in `ShipClass_Create`.

**Files:**
- Modify: [engine/appc/ships.py:14-42](../../../engine/appc/ships.py#L14-L42) (`ShipClass.__init__` + accessors)
- Modify: [engine/appc/ships.py:170-193](../../../engine/appc/ships.py#L170-L193) (`ShipClass_Create`)
- Test: [tests/unit/test_ship_shield_slot.py](../../../tests/unit/test_ship_shield_slot.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ship_shield_slot.py`:

```python
"""ShipClass exposes a ShieldSubsystem slot."""
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import ShieldSubsystem


def test_default_ship_has_none():
    """A bare ShipClass() has no shield until ShipClass_Create or a setter wires one."""
    s = ShipClass()
    assert s.GetShieldSubsystem() is None


def test_shipclass_create_installs_shield():
    s = ShipClass_Create("Galaxy")
    assert isinstance(s.GetShieldSubsystem(), ShieldSubsystem)


def test_set_shield_subsystem():
    s = ShipClass()
    shield = ShieldSubsystem("Shield Generator")
    s.SetShieldSubsystem(shield)
    assert s.GetShieldSubsystem() is shield
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_ship_shield_slot.py -v
```

Expected: fails on `GetShieldSubsystem`.

- [ ] **Step 3: Add `_shield_subsystem` slot + accessors to ShipClass**

In [engine/appc/ships.py:20-28](../../../engine/appc/ships.py#L20-L28), extend `ShipClass.__init__` adding the slot beside the others:

```python
        self._sensor_subsystem = None
        self._impulse_engine_subsystem = None
        self._warp_engine_subsystem = None
        self._torpedo_system = None
        self._phaser_system = None
        self._pulse_weapon_system = None
        self._tractor_beam_system = None
        self._shield_subsystem = None
```

In the accessor block around [engine/appc/ships.py:59-74](../../../engine/appc/ships.py#L59-L74), add the matching pair just before `def GetHull`:

```python
    def GetShieldSubsystem(self):                 return self._shield_subsystem
    def SetShieldSubsystem(self, s) -> None:      self._shield_subsystem = s
```

- [ ] **Step 4: Update `ShipClass_Create` to install a `ShieldSubsystem`**

In [engine/appc/ships.py:170-193](../../../engine/appc/ships.py#L170-L193):

```python
def ShipClass_Create(class_name: str = "") -> ShipClass:
    """Construct a ShipClass with default empty subsystem instances. ..."""
    from engine.appc.subsystems import (
        TorpedoSystem, PhaserSystem, PulseWeaponSystem, TractorBeamSystem,
        SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
        ShieldSubsystem,
    )
    ship = ShipClass()
    ship.SetName(class_name)
    ship.SetTorpedoSystem(TorpedoSystem("Torpedo System"))
    ship.SetPhaserSystem(PhaserSystem("Phaser System"))
    ship.SetPulseWeaponSystem(PulseWeaponSystem("Pulse Weapon System"))
    ship.SetTractorBeamSystem(TractorBeamSystem("Tractor Beam System"))
    ship.SetSensorSubsystem(SensorSubsystem("Sensor Subsystem"))
    ship.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("Impulse Engines"))
    ship.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    ship.SetShieldSubsystem(ShieldSubsystem("Shield Generator"))
    return ship
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_ship_shield_slot.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_ship_shield_slot.py
git commit -m "$(cat <<'EOF'
feat(ships): wire ShieldSubsystem into ShipClass + factory

ShipClass_Create installs a default ShieldSubsystem so freshly-created
ships have a queryable shield surface before SetupProperties runs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Add ship-level identity fields to `ShipClass`

Nine new fields: genus, species, affiliation, ship-name, AI-string, damage-resolution, model-filename, stationary, death-explosion-sound. All None-safe; defaults sensible for a default-constructed ship.

**Files:**
- Modify: [engine/appc/ships.py:14-42](../../../engine/appc/ships.py#L14-L42)
- Test: [tests/unit/test_ship_identity_fields.py](../../../tests/unit/test_ship_identity_fields.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ship_identity_fields.py`:

```python
"""ShipClass ship-level identity fields populated by SetupProperties."""
from engine.appc.ships import ShipClass


def test_defaults():
    s = ShipClass()
    assert s.GetGenus() == 0
    assert s.GetSpecies() == 0
    assert s.GetAffiliation() == 0
    assert s.GetShipName() == ""
    assert s.GetAIString() == ""
    assert s.GetDamageResolution() == 0.0
    assert s.GetModelFilename() == ""
    assert s.IsStationary() == 0
    assert s.GetDeathExplosionSound() == ""


def test_setters_persist():
    s = ShipClass()
    s.SetGenus(1)
    s.SetSpecies(101)
    s.SetAffiliation(2)
    s.SetShipName("Dauntless")
    s.SetAIString("FedAttack")
    s.SetDamageResolution(10.0)
    s.SetModelFilename("data/Models/Ships/Galaxy/Galaxy.nif")
    s.SetStationary(1)
    s.SetDeathExplosionSound("g_lsDeathExplosions")
    assert s.GetGenus() == 1
    assert s.GetSpecies() == 101
    assert s.GetAffiliation() == 2
    assert s.GetShipName() == "Dauntless"
    assert s.GetAIString() == "FedAttack"
    assert s.GetDamageResolution() == 10.0
    assert s.GetModelFilename() == "data/Models/Ships/Galaxy/Galaxy.nif"
    assert s.IsStationary() == 1
    assert s.GetDeathExplosionSound() == "g_lsDeathExplosions"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_ship_identity_fields.py -v
```

Expected: fails on `GetGenus`.

- [ ] **Step 3: Add fields + accessors to `ShipClass`**

In [engine/appc/ships.py:14-42](../../../engine/appc/ships.py#L14-L42), extend `__init__` after the existing subsystem slots and before `_target`:

```python
        # Lifecycle flags — IsDocked/IsDying/IsDead drive cutscene + game-over
        # branching in MissionLib and per-mission scripts.  Defaults are
        # the "alive, undocked, not dying" state that a freshly-spawned ship
        # has at mission start.
        self._docked = False
        self._dying = False
        self._dead = False
        # Ship-level identity populated by SetupProperties from ShipProperty.
        self._genus: int = 0
        self._species: int = 0
        self._affiliation: int = 0
        self._ship_name: str = ""
        self._ai_string: str = ""
        self._damage_resolution: float = 0.0
        self._model_filename: str = ""
        self._stationary: int = 0
        self._death_explosion_sound: str = ""
```

Then add an accessor block. Insert immediately after the existing `SetNetType / GetNetType` pair (around [engine/appc/ships.py:49-53](../../../engine/appc/ships.py#L49-L53)):

```python
    # ── Ship-level identity ──────────────────────────────────────────────────
    def GetGenus(self) -> int:                          return self._genus
    def SetGenus(self, v) -> None:                      self._genus = int(v)
    def GetSpecies(self) -> int:                        return self._species
    def SetSpecies(self, v) -> None:                    self._species = int(v)
    def GetAffiliation(self) -> int:                    return self._affiliation
    def SetAffiliation(self, v) -> None:                self._affiliation = int(v)
    def GetShipName(self) -> str:                       return self._ship_name
    def SetShipName(self, v) -> None:                   self._ship_name = str(v)
    def GetAIString(self) -> str:                       return self._ai_string
    def SetAIString(self, v) -> None:                   self._ai_string = str(v)
    def GetDamageResolution(self) -> float:             return self._damage_resolution
    def SetDamageResolution(self, v) -> None:           self._damage_resolution = float(v)
    def GetModelFilename(self) -> str:                  return self._model_filename
    def SetModelFilename(self, v) -> None:              self._model_filename = str(v)
    def IsStationary(self) -> int:                      return self._stationary
    def SetStationary(self, v) -> None:                 self._stationary = int(v)
    def GetDeathExplosionSound(self) -> str:            return self._death_explosion_sound
    def SetDeathExplosionSound(self, v) -> None:        self._death_explosion_sound = str(v)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_ship_identity_fields.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_ship_identity_fields.py
git commit -m "$(cat <<'EOF'
feat(ships): ShipClass identity fields (genus/species/affiliation/AI/name/...)

Nine ship-level fields with field-backed accessors. Defaults match a
default-constructed ship before any property template loads.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Broaden `SetupProperties` — `ShipProperty` block

Extend the existing `ShipProperty` branch in `SetupProperties` to propagate the nine new identity fields plus the existing mass/inertia.

**Files:**
- Modify: [engine/appc/ships.py:85-119](../../../engine/appc/ships.py#L85-L119)
- Test: [tests/unit/test_setup_properties_ship.py](../../../tests/unit/test_setup_properties_ship.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_setup_properties_ship.py`:

```python
"""SetupProperties copies all ShipProperty identity fields onto the ship."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ShipProperty


def test_ship_property_propagation():
    ship = ShipClass_Create("Galaxy")
    sp = ShipProperty("Galaxy")
    sp.SetGenus(1)
    sp.SetSpecies(101)
    sp.SetMass(120.0)
    sp.SetRotationalInertia(15000.0)
    sp.SetShipName("Dauntless")
    sp.SetDamageResolution(10.0)
    sp.SetAffiliation(0)
    sp.SetStationary(0)
    sp.SetAIString("FedAttack")
    sp.SetDeathExplosionSound("g_lsDeathExplosions")
    sp.SetModelFilename("")

    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    assert ship.GetGenus() == 1
    assert ship.GetSpecies() == 101
    assert ship.GetMass() == 120.0
    assert ship.GetRotationalInertia() == 15000.0
    assert ship.GetShipName() == "Dauntless"
    assert ship.GetDamageResolution() == 10.0
    assert ship.GetAffiliation() == 0
    assert ship.IsStationary() == 0
    assert ship.GetAIString() == "FedAttack"
    assert ship.GetDeathExplosionSound() == "g_lsDeathExplosions"
    assert ship.GetModelFilename() == ""


def test_none_fields_are_skipped():
    """Unset ShipProperty fields don't clobber defaults."""
    ship = ShipClass_Create("X")
    ship.SetAIString("PrevAI")        # pre-set
    sp = ShipProperty("X")
    sp.SetMass(50.0)                   # only mass is set
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    assert ship.GetMass() == 50.0
    assert ship.GetAIString() == "PrevAI"   # not clobbered by None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_setup_properties_ship.py -v
```

Expected: fails (only mass/inertia propagate today).

- [ ] **Step 3: Extend the `ShipProperty` branch in `SetupProperties`**

In [engine/appc/ships.py:85-119](../../../engine/appc/ships.py#L85-L119), replace the `if isinstance(prop, ShipProperty):` block with:

```python
            if isinstance(prop, ShipProperty):
                for src, setter in (
                    (prop.GetMass,                 self.SetMass),
                    (prop.GetRotationalInertia,    self.SetRotationalInertia),
                    (prop.GetGenus,                self.SetGenus),
                    (prop.GetSpecies,              self.SetSpecies),
                    (prop.GetAffiliation,          self.SetAffiliation),
                    (prop.GetShipName,             self.SetShipName),
                    (prop.GetAIString,             self.SetAIString),
                    (prop.GetDamageResolution,     self.SetDamageResolution),
                    (prop.GetModelFilename,        self.SetModelFilename),
                    (prop.GetStationary,           self.SetStationary),
                    (prop.GetDeathExplosionSound,  self.SetDeathExplosionSound),
                ):
                    v = src()
                    if v is not None: setter(v)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_setup_properties_ship.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_setup_properties_ship.py
git commit -m "$(cat <<'EOF'
feat(setup-properties): copy all ShipProperty identity fields

Broadens the ShipProperty branch of SetupProperties from mass/inertia
to the full set: genus/species/affiliation/AI-string/ship-name/
damage-resolution/model-filename/stationary/death-explosion-sound.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Broaden `SetupProperties` — `HullProperty` block

Already populates the primary hull's MaxCondition. Add Critical/Targetable/Primary/Radius/DisabledPercentage propagation.

**Files:**
- Modify: [engine/appc/ships.py:112-119](../../../engine/appc/ships.py#L112-L119)
- Test: [tests/unit/test_setup_properties_hull.py](../../../tests/unit/test_setup_properties_hull.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_setup_properties_hull.py`:

```python
"""SetupProperties copies HullProperty identity fields onto the primary hull."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import HullProperty


def test_hull_property_propagation():
    ship = ShipClass_Create("Galaxy")
    h = HullProperty("Hull")
    h.SetMaxCondition(11000.0)
    h.SetCritical(0)
    h.SetTargetable(1)
    h.SetPrimary(1)
    h.SetRadius(1.0)
    h.SetDisabledPercentage(0.0)

    ship.GetPropertySet().AddToSet("Scene Root", h)
    ship.SetupProperties()

    hull = ship.GetHull()
    assert hull is not None
    assert hull.GetMaxCondition() == 11000.0
    assert hull.GetCondition() == 11000.0  # seeded full
    assert hull.GetCritical() == 0
    assert hull.GetTargetable() == 1
    assert hull.GetPrimary() == 1
    assert hull.GetDisabledPercentage() == 0.0


def test_first_hull_wins():
    """Galaxy registers Hull then Bridge (both HullProperty). Primary hull
    should remain the first one."""
    ship = ShipClass_Create("Galaxy")
    primary = HullProperty("Hull")
    primary.SetMaxCondition(11000.0)
    secondary = HullProperty("Bridge")
    secondary.SetMaxCondition(500.0)

    ship.GetPropertySet().AddToSet("Scene Root", primary)
    ship.GetPropertySet().AddToSet("Scene Root", secondary)
    ship.SetupProperties()

    assert ship.GetHull().GetName() == "Hull"
    assert ship.GetHull().GetMaxCondition() == 11000.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_setup_properties_hull.py -v
```

Expected: fails on hull.GetCritical (hull never got Critical propagated).

- [ ] **Step 3: Add `SetRadius` to `ShipSubsystem` base**

`ShipSubsystem` exposes `GetRadius` but no public setter. The `HullProperty` branch below writes radius, so add the setter first.

In [engine/appc/subsystems.py](../../../engine/appc/subsystems.py), add to the base `ShipSubsystem` class accessor block (next to `GetRadius`):

```python
    def SetRadius(self, value: float) -> None:
        self._radius = float(value)
```

- [ ] **Step 4: Extend the `HullProperty` branch in `SetupProperties`**

In [engine/appc/ships.py:112-119](../../../engine/appc/ships.py#L112-L119) replace:

```python
            elif isinstance(prop, HullProperty):
                # Only the FIRST HullProperty is the main hull — galaxy.py
                # registers "Hull" first then "Bridge" as a child component.
                # GetHull() must return the primary hull (SDK App.py:5382).
                if self._hull is None:
                    self._hull = HullSubsystem(prop.GetName() or "Hull")
                    for src, setter in (
                        (prop.GetMaxCondition,        self._hull.SetMaxCondition),
                        (prop.GetCritical,            self._hull.SetCritical),
                        (prop.GetTargetable,          self._hull.SetTargetable),
                        (prop.GetPrimary,             self._hull.SetPrimary),
                        (prop.GetRadius,              self._hull.SetRadius),
                        (prop.GetDisabledPercentage,  self._hull.SetDisabledPercentage),
                    ):
                        v = src()
                        if v is not None: setter(v)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_setup_properties_hull.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/ships.py engine/appc/subsystems.py tests/unit/test_setup_properties_hull.py
git commit -m "$(cat <<'EOF'
feat(setup-properties): broaden HullProperty propagation + SetRadius

Hull gains Critical/Targetable/Primary/Radius/DisabledPercentage in
addition to MaxCondition. Base ShipSubsystem gains SetRadius (was
get-only).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Broaden `SetupProperties` — `SensorProperty` block

New branch that pulls MaxCondition, NormalPowerPerSecond, BaseSensorRange, MaxProbes onto the ship's `SensorSubsystem`.

**Files:**
- Modify: [engine/appc/ships.py:85-119](../../../engine/appc/ships.py#L85-L119)
- Test: [tests/unit/test_setup_properties_sensor.py](../../../tests/unit/test_setup_properties_sensor.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_setup_properties_sensor.py`:

```python
"""SetupProperties copies SensorProperty fields onto the SensorSubsystem."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import SensorProperty


def test_sensor_property_propagation():
    ship = ShipClass_Create("Galaxy")
    sp = SensorProperty("Sensor Array")
    sp.SetMaxCondition(8000.0)
    sp.SetNormalPowerPerSecond(100.0)
    sp.SetBaseSensorRange(2000.0)
    sp.SetMaxProbes(10)

    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    sensor = ship.GetSensorSubsystem()
    assert sensor is not None
    assert sensor.GetMaxCondition() == 8000.0
    assert sensor.GetNormalPowerPerSecond() == 100.0
    assert sensor.GetBaseSensorRange() == 2000.0
    assert sensor.GetMaxProbes() == 10
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_setup_properties_sensor.py -v
```

Expected: fails (no branch for SensorProperty).

- [ ] **Step 3: Add the SensorProperty branch**

In [engine/appc/ships.py](../../../engine/appc/ships.py), in the import block at the top of `SetupProperties`:

```python
    def SetupProperties(self) -> None:
        from engine.appc.properties import (
            ShipProperty, ImpulseEngineProperty, WarpEngineProperty,
            HullProperty, SensorProperty,
        )
        from engine.appc.subsystems import HullSubsystem
```

In the `if/elif` chain inside the `for prop in ...` loop, add this elif (anywhere between the `HullProperty` and end of the loop):

```python
            elif isinstance(prop, SensorProperty):
                self._copy_powered_subsystem_fields(prop, self._sensor_subsystem)
                sens = self._sensor_subsystem
                if sens is not None:
                    for src, setter in (
                        (prop.GetBaseSensorRange, sens.SetBaseSensorRange),
                        (prop.GetMaxProbes,       sens.SetMaxProbes),
                    ):
                        v = src()
                        if v is not None: setter(v)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_setup_properties_sensor.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_setup_properties_sensor.py
git commit -m "$(cat <<'EOF'
feat(setup-properties): propagate SensorProperty to SensorSubsystem

Adds MaxCondition + NormalPowerPerSecond + BaseSensorRange + MaxProbes
propagation when a SensorProperty appears in the property set.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Broaden `SetupProperties` — `ShieldProperty` block

New branch. Six face maxes (`MaxShields[face]`) and six charge rates (`ShieldChargePerSecond[face]`) propagate onto the new `ShieldSubsystem`. Setting max also seeds current (logic already in `ShieldSubsystem.SetMaxShields`).

**Files:**
- Modify: [engine/appc/ships.py:85-119](../../../engine/appc/ships.py#L85-L119)
- Test: [tests/unit/test_setup_properties_shield.py](../../../tests/unit/test_setup_properties_shield.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_setup_properties_shield.py`:

```python
"""SetupProperties copies ShieldProperty fields onto the ShieldSubsystem."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ShieldProperty


def test_shield_property_propagation():
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxCondition(12000.0)
    sp.SetNormalPowerPerSecond(400.0)
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS,  8000.0)
    sp.SetMaxShields(ShieldProperty.REAR_SHIELDS,   4000.0)
    sp.SetMaxShields(ShieldProperty.TOP_SHIELDS,    4000.0)
    sp.SetMaxShields(ShieldProperty.BOTTOM_SHIELDS, 4000.0)
    sp.SetMaxShields(ShieldProperty.LEFT_SHIELDS,   4000.0)
    sp.SetMaxShields(ShieldProperty.RIGHT_SHIELDS,  4000.0)
    for face in range(ShieldProperty.NUM_SHIELDS):
        sp.SetShieldChargePerSecond(face, 11.0)

    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    shield = ship.GetShieldSubsystem()
    assert shield is not None
    assert shield.GetMaxCondition() == 12000.0
    assert shield.GetNormalPowerPerSecond() == 400.0
    assert shield.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert shield.GetMaxShields(ShieldProperty.REAR_SHIELDS) == 4000.0
    # Current seeded equal to max:
    for face in range(ShieldProperty.NUM_SHIELDS):
        assert shield.GetCurrentShields(face) == shield.GetMaxShields(face)
        assert shield.GetShieldChargePerSecond(face) == 11.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_setup_properties_shield.py -v
```

Expected: fails (no branch for ShieldProperty).

- [ ] **Step 3: Add the ShieldProperty branch**

In [engine/appc/ships.py](../../../engine/appc/ships.py), update the import in `SetupProperties`:

```python
        from engine.appc.properties import (
            ShipProperty, ImpulseEngineProperty, WarpEngineProperty,
            HullProperty, SensorProperty, ShieldProperty,
        )
```

Then add the elif branch:

```python
            elif isinstance(prop, ShieldProperty):
                self._copy_powered_subsystem_fields(prop, self._shield_subsystem)
                ss = self._shield_subsystem
                if ss is not None:
                    for face in range(ShieldProperty.NUM_SHIELDS):
                        mx = prop.GetMaxShields(face)
                        if mx is not None: ss.SetMaxShields(face, mx)
                        cr = prop.GetShieldChargePerSecond(face)
                        if cr is not None: ss.SetShieldChargePerSecond(face, cr)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_setup_properties_shield.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_setup_properties_shield.py
git commit -m "$(cat <<'EOF'
feat(setup-properties): propagate ShieldProperty (6 face maxes + charge rates)

Per-face shield maxes and charge rates copy onto the new ShieldSubsystem.
SetMaxShields seeds current, so freshly-loaded ships start fully shielded.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Broaden `SetupProperties` — `WeaponSystemProperty` block (WST_* dispatch)

`WeaponSystemProperty` instances appear once per weapon family on a ship: Phasers, Torpedoes, Pulse, Tractors. Dispatch by `GetWeaponSystemType()` to the matching ship subsystem.

**Files:**
- Modify: [engine/appc/ships.py:85-119](../../../engine/appc/ships.py#L85-L119)
- Test: [tests/unit/test_setup_properties_weapon_systems.py](../../../tests/unit/test_setup_properties_weapon_systems.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_setup_properties_weapon_systems.py`:

```python
"""SetupProperties dispatches WeaponSystemProperty by WST_* to the right slot."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import WeaponSystemProperty


def _make_ws(name, wst_type, max_c=4000.0, power=300.0, single_fire=1, aimed=0):
    p = WeaponSystemProperty(name)
    p.SetMaxCondition(max_c)
    p.SetNormalPowerPerSecond(power)
    p.SetWeaponSystemType(wst_type)
    p.SetSingleFire(single_fire)
    p.SetAimedWeapon(aimed)
    return p


def test_phaser_dispatch():
    ship = ShipClass_Create("Galaxy")
    p = _make_ws("Phasers", WeaponSystemProperty.WST_PHASER)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()

    phaser = ship.GetPhaserSystem()
    assert phaser.GetMaxCondition() == 4000.0
    assert phaser.GetNormalPowerPerSecond() == 300.0
    assert phaser.GetWeaponSystemType() == WeaponSystemProperty.WST_PHASER
    assert phaser.GetSingleFire() == 1


def test_torpedo_dispatch():
    ship = ShipClass_Create("Galaxy")
    p = _make_ws("Torpedoes", WeaponSystemProperty.WST_TORPEDO, max_c=2400.0, power=50.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    torp = ship.GetTorpedoSystem()
    assert torp.GetMaxCondition() == 2400.0
    assert torp.GetWeaponSystemType() == WeaponSystemProperty.WST_TORPEDO


def test_pulse_and_tractor_dispatch():
    ship = ShipClass_Create("X")
    p = _make_ws("Pulse",   WeaponSystemProperty.WST_PULSE,   power=100.0)
    t = _make_ws("Tractor", WeaponSystemProperty.WST_TRACTOR, power=75.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.GetPropertySet().AddToSet("Scene Root", t)
    ship.SetupProperties()

    assert ship.GetPulseWeaponSystem().GetNormalPowerPerSecond() == 100.0
    assert ship.GetTractorBeamSystem().GetNormalPowerPerSecond() == 75.0
```

Note: `TorpedoSystem` doesn't currently have `GetWeaponSystemType` or `SetWeaponSystemType` — they're inherited via `WeaponSystem(PoweredSubsystem)` after Task 3. The torpedo test calls `torp.GetWeaponSystemType()` which doesn't exist yet. Add `_weapon_system_type` to the base `WeaponSystem` class.

- [ ] **Step 2: Add `_weapon_system_type` to base `WeaponSystem`**

In [engine/appc/subsystems.py](../../../engine/appc/subsystems.py), update `WeaponSystem.__init__`:

```python
class WeaponSystem(PoweredSubsystem):
    """Weapon system — has firing state and an optional target.

    Reparented under PoweredSubsystem because every weapon system in BC
    has a power line. See sdk/.../App.py:6361.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._firing = False
        self._target = None
        self._weapon_system_type: int = 0

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def StartFiring(self, *args) -> None:
        self._firing = True

    def StopFiring(self, *args) -> None:
        self._firing = False

    def GetTarget(self):
        return self._target

    def SetTarget(self, target) -> None:
        self._target = target

    def GetWeaponSystemType(self) -> int:           return self._weapon_system_type
    def SetWeaponSystemType(self, v) -> None:       self._weapon_system_type = int(v)
```

Then **remove** the `GetWeaponSystemType / SetWeaponSystemType` from `PhaserSystem` (added in Task 5) since they're now on the base. Keep `SingleFire` and `AimedWeapon` on `PhaserSystem` since they're phaser-specific.

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_setup_properties_weapon_systems.py -v
```

Expected: fails (no branch for WeaponSystemProperty).

- [ ] **Step 4: Add the `WeaponSystemProperty` branch with WST_* dispatch**

In [engine/appc/ships.py](../../../engine/appc/ships.py), update the import in `SetupProperties`:

```python
        from engine.appc.properties import (
            ShipProperty, ImpulseEngineProperty, WarpEngineProperty,
            HullProperty, SensorProperty, ShieldProperty,
            WeaponSystemProperty,
        )
```

Add the elif branch:

```python
            elif isinstance(prop, WeaponSystemProperty):
                wst = prop.GetWeaponSystemType()
                receiver = {
                    WeaponSystemProperty.WST_PHASER:  self._phaser_system,
                    WeaponSystemProperty.WST_TORPEDO: self._torpedo_system,
                    WeaponSystemProperty.WST_PULSE:   self._pulse_weapon_system,
                    WeaponSystemProperty.WST_TRACTOR: self._tractor_beam_system,
                }.get(wst)
                if receiver is not None:
                    self._copy_powered_subsystem_fields(prop, receiver)
                    if wst is not None: receiver.SetWeaponSystemType(wst)
                    # Phaser-only extras (no-op for other receivers).
                    if wst == WeaponSystemProperty.WST_PHASER:
                        sf = prop.GetSingleFire()
                        if sf is not None: receiver.SetSingleFire(sf)
                        aw = prop.GetAimedWeapon()
                        if aw is not None: receiver.SetAimedWeapon(aw)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_setup_properties_weapon_systems.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/ships.py engine/appc/subsystems.py tests/unit/test_setup_properties_weapon_systems.py
git commit -m "$(cat <<'EOF'
feat(setup-properties): WeaponSystemProperty WST_* dispatch

Routes WeaponSystemProperty entries to phaser/torpedo/pulse/tractor
slots based on WeaponSystemType. WeaponSystem base owns the type field;
PhaserSystem-only fields (SingleFire, AimedWeapon) handled inline.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Two-pass torpedo tube seeding

After Pass 1, walk the property list again; count `TorpedoTubeProperty` entries; for each, call `AddAmmoType(App.AT_ONE)` on the ship's `TorpedoSystem`. Guard: only seed if `_ammo_by_slot` is currently empty (idempotent re-runs).

**Files:**
- Modify: [engine/appc/ships.py:85-119](../../../engine/appc/ships.py#L85-L119)
- Test: [tests/unit/test_setup_properties_torpedo_tubes.py](../../../tests/unit/test_setup_properties_torpedo_tubes.py)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_setup_properties_torpedo_tubes.py`:

```python
"""SetupProperties Pass 2: count TorpedoTubeProperty + seed AT_ONE per tube."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import TorpedoTubeProperty, WeaponSystemProperty


def _make_tube(name):
    p = TorpedoTubeProperty(name)
    p.SetMaxCondition(2400.0)
    return p


def test_six_tubes_seed_six_ammo_slots():
    ship = ShipClass_Create("Galaxy")
    # Add 6 tubes (Galaxy: ForwardTorpedo1..4 + AftTorpedo1..2)
    for i in range(6):
        ship.GetPropertySet().AddToSet("Scene Root", _make_tube(f"Torpedo {i}"))
    # Plus the system entry (so dispatch works)
    sys_prop = WeaponSystemProperty("Torpedoes")
    sys_prop.SetWeaponSystemType(WeaponSystemProperty.WST_TORPEDO)
    ship.GetPropertySet().AddToSet("Scene Root", sys_prop)

    ship.SetupProperties()

    ts = ship.GetTorpedoSystem()
    assert ts.GetNumAmmoTypes() == 6
    for i in range(6):
        assert ts.GetAmmoType(i) == App.AT_ONE


def test_no_tubes_no_seeding():
    ship = ShipClass_Create("FedStarbase")
    ship.SetupProperties()
    assert ship.GetTorpedoSystem().GetNumAmmoTypes() == 0


def test_idempotent_against_re_run():
    ship = ShipClass_Create("Galaxy")
    for i in range(2):
        ship.GetPropertySet().AddToSet("Scene Root", _make_tube(f"Torpedo {i}"))

    ship.SetupProperties()
    assert ship.GetTorpedoSystem().GetNumAmmoTypes() == 2
    # Re-run: should not double-seed.
    ship.SetupProperties()
    assert ship.GetTorpedoSystem().GetNumAmmoTypes() == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_setup_properties_torpedo_tubes.py -v
```

Expected: fails on the count (tubes are not seeded today).

- [ ] **Step 3: Add Pass 2 after the existing loop**

In [engine/appc/ships.py](../../../engine/appc/ships.py), update the imports in `SetupProperties`:

```python
        from engine.appc.properties import (
            ShipProperty, ImpulseEngineProperty, WarpEngineProperty,
            HullProperty, SensorProperty, ShieldProperty,
            WeaponSystemProperty, TorpedoTubeProperty,
        )
        from engine.appc.subsystems import HullSubsystem
        import App
```

After the existing `for prop in self.GetPropertySet().GetPropertyList():` loop closes, add the second pass:

```python
        # Pass 2 — seed torpedo tubes (idempotent).
        ts = self._torpedo_system
        if ts is not None and ts.GetNumAmmoTypes() == 0:
            tube_count = sum(
                1
                for prop in self.GetPropertySet().GetPropertyList()
                if isinstance(prop, TorpedoTubeProperty)
            )
            for _ in range(tube_count):
                ts.AddAmmoType(App.AT_ONE)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_setup_properties_torpedo_tubes.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_setup_properties_torpedo_tubes.py
git commit -m "$(cat <<'EOF'
feat(setup-properties): Pass 2 seeds AT_ONE per TorpedoTubeProperty

Counts TorpedoTubeProperty entries in the property set and seeds one
AT_ONE ammo type per tube on the ship's TorpedoSystem. Guarded so
re-running SetupProperties does not double-seed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Hardpoint expectation extractor

Helper that parses a hardpoint .py file and extracts `Set*` call values, used by the parametrized E1M1 test to cross-check hand-coded expectations against SDK truth. Uses a regex; not a full Python parser.

**Files:**
- Create: [tests/integration/_hardpoint_parser.py](../../../tests/integration/_hardpoint_parser.py)
- Test: [tests/integration/test_hardpoint_parser.py](../../../tests/integration/test_hardpoint_parser.py)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_hardpoint_parser.py`:

```python
"""Hardpoint expectation extractor unit tests."""
from pathlib import Path

import pytest

from tests.integration._hardpoint_parser import extract_setters


SDK_HARDPOINTS = Path(__file__).resolve().parents[2] / "sdk" / "Build" / "scripts" / "ships" / "Hardpoints"


def test_extract_galaxy_ship_mass():
    setters = extract_setters(SDK_HARDPOINTS / "galaxy.py", "Galaxy")
    assert setters["Mass"] == 120.0
    assert setters["RotationalInertia"] == 15000.0
    assert setters["ShipName"] == "Dauntless"
    assert setters["AIString"] == "FedAttack"
    assert setters["Affiliation"] == 0
    assert setters["Stationary"] == 0


def test_extract_galaxy_hull_max_condition():
    setters = extract_setters(SDK_HARDPOINTS / "galaxy.py", "Hull")
    assert setters["MaxCondition"] > 0


def test_extract_galaxy_impulse():
    setters = extract_setters(SDK_HARDPOINTS / "galaxy.py", "ImpulseEngines")
    assert setters["MaxSpeed"] == 6.3
    assert setters["MaxAccel"] == 1.5
    assert setters["MaxAngularVelocity"] == 0.28
    assert setters["MaxAngularAccel"] == 0.12


def test_extract_missing_template_raises():
    with pytest.raises(KeyError):
        extract_setters(SDK_HARDPOINTS / "galaxy.py", "NotPresent")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_hardpoint_parser.py -v
```

Expected: ImportError on `_hardpoint_parser`.

- [ ] **Step 3: Write the extractor**

Create `tests/integration/_hardpoint_parser.py`:

```python
"""Tiny regex-based extractor for ships/Hardpoints/<name>.py.

Each hardpoint file is a sequence of `Template = Property_Create("Name")`
followed by a block of `Template.SetFoo(value)` lines. This extractor
finds a named template and returns a dict of setter-name -> Python value.

Values are parsed as int / float / quoted-string. Non-literal call
arguments (e.g. `Hardpoint.SetDirection(kDirection)`) are recorded as
the raw string; tests usually only care about scalar fields.
"""
from __future__ import annotations

import re
from pathlib import Path


_TEMPLATE_RE = re.compile(r"^(\w+)\s*=\s*App\.\w+_Create\(")
_SETTER_RE = re.compile(r"^(\w+)\.Set(\w+)\(([^)]*)\)")


def _parse_value(raw: str):
    s = raw.strip()
    if not s:
        return None
    # Try int
    try:
        return int(s)
    except ValueError:
        pass
    # Try float (covers "120.000000")
    try:
        return float(s)
    except ValueError:
        pass
    # Quoted string?
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    # Fallback: raw text (likely a variable reference)
    return s


def extract_setters(path: Path, template_name: str) -> dict:
    """Return {setter_name: value} for all `template_name.SetX(...)` lines.

    Raises KeyError if template_name is never declared in the file.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    declared = False
    setters: dict = {}
    for line in text.splitlines():
        m = _TEMPLATE_RE.match(line.strip())
        if m and m.group(1) == template_name:
            declared = True
        m2 = _SETTER_RE.match(line.strip())
        if m2 and m2.group(1) == template_name:
            name, args = m2.group(2), m2.group(3)
            # Single-arg setter: store directly. Multi-arg (e.g.
            # SetMaxShields(face, value), SetShieldChargePerSecond(face, value))
            # store as list of (key, value) tuples accumulated under the name.
            parts = [_parse_value(p) for p in args.split(",")]
            if len(parts) == 1:
                setters[name] = parts[0]
            else:
                setters.setdefault(name, []).append(tuple(parts))
    if not declared:
        raise KeyError(f"Template {template_name!r} not declared in {path}")
    return setters
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_hardpoint_parser.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/_hardpoint_parser.py tests/integration/test_hardpoint_parser.py
git commit -m "$(cat <<'EOF'
test(hardpoint-parser): extractor for ships/Hardpoints/<name>.py

Tiny regex-based reader returning {SetterName: value} for a named
template inside a hardpoint file. Used by upcoming parametrized E1M1
identity test to cross-check expectations against SDK truth.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Parametrized E1M1 ship identity integration test

The capstone test. Parametrized over E1M1's eight ship types. For each: calls `loadspacehelper.CreateShip`, then asserts identity fields. Expectations are hand-coded for clarity, but cross-checked at module load against the actual hardpoint file via `_hardpoint_parser.extract_setters` — drift fails loudly with a useful diff.

**Files:**
- Create: [tests/integration/test_e1m1_ship_identity.py](../../../tests/integration/test_e1m1_ship_identity.py)

- [ ] **Step 1: Write the test**

Create `tests/integration/test_e1m1_ship_identity.py`:

```python
"""Parametrized identity check for every E1M1 ship type.

Verifies that loadspacehelper.CreateShip returns a ShipClass whose
ship-level + hull + propulsion + sensor + shield + weapon-system
identity fields match the SDK hardpoint definition. Expected values
are hand-coded for clarity, and cross-checked at module load against
the actual ships/Hardpoints/<name>.py file via _hardpoint_parser.
"""
from pathlib import Path

import pytest

import App
from engine.appc.properties import ShieldProperty
from tests.integration._hardpoint_parser import extract_setters


SDK_HARDPOINTS = Path(__file__).resolve().parents[2] / "sdk" / "Build" / "scripts" / "ships" / "Hardpoints"


# ── Per-ship expectations ────────────────────────────────────────────────────

GALAXY = {
    "script": "Galaxy",
    "hardpoint_file": "galaxy.py",
    "ship_template": "Galaxy",
    "hull_template": "Hull",
    "genus": 1, "species": 101, "affiliation": 0,
    "mass": 120.0, "rotational_inertia": 15000.0,
    "ship_name": "Dauntless", "ai_string": "FedAttack", "stationary": 0,
    "has_impulse": True,
    "impulse_template": "ImpulseEngines",
    "impulse_max_speed": 6.3, "impulse_max_accel": 1.5,
    "impulse_max_angular_velocity": 0.28, "impulse_max_angular_accel": 0.12,
    "has_warp": True,
    "has_sensor": True,
    "sensor_template": "SensorArray",
    "sensor_base_range": 2000.0, "sensor_max_probes": 10,
    "has_shields": True,
    "shield_template": "ShieldGenerator",
    "shield_max_front": 8000.0, "shield_max_rear": 4000.0,
    "shield_charge_front": 11.0,
    "has_phasers": True,
    "phaser_template": "Phasers",
    "has_torpedoes": True, "torpedo_tube_count": 6,
}

DRYDOCK = {
    "script": "DryDock",
    "hardpoint_file": "drydock.py",
    "ship_template": "DryDock",
    "hull_template": "Hull",
    "genus": None,  # set from extracted value
    "species": None,
    "affiliation": 0,
    "mass": 300.0, "rotational_inertia": None,
    "ship_name": "Dry Dock", "ai_string": "StarbaseAttack", "stationary": 1,
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": False,  # drydock.py has no WeaponSystemProperty
    "has_torpedoes": False,
    "torpedo_tube_count": 0,
}

FEDSTARBASE = {
    "script": "FedStarbase",
    "hardpoint_file": "fedstarbase.py",
    "ship_template": "FederationStarbase",
    "hull_template": "Hull",
    "affiliation": 0, "stationary": 1,
    "ship_name": "Federation Starbase",
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": False,
    "torpedo_tube_count": 0,
}

SHUTTLE = {
    "script": "Shuttle",
    "hardpoint_file": "shuttle.py",
    "ship_template": "Shuttle",
    "hull_template": "Hull",
    "mass": 15.0, "affiliation": 0, "stationary": 0,
    "has_impulse": True, "impulse_template": "ImpulseEngines",
    "has_warp": True,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": False,
    "has_torpedoes": False,
    "torpedo_tube_count": 0,
}

SPACEFACILITY = {
    "script": "SpaceFacility",
    "hardpoint_file": "spacefacility.py",
    "ship_template": "Spacefacility",
    "hull_template": "Hull",
    "mass": 500.0, "stationary": 0, "ai_string": "StarbaseAttack",
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": False, "has_torpedoes": False, "torpedo_tube_count": 0,
}

NEBULA = {
    "script": "Nebula",
    "hardpoint_file": "nebula.py",
    "ship_template": "Nebula",
    "hull_template": "Hull",
    "mass": 100.0, "stationary": 0, "ai_string": "FedAttack",
    "has_impulse": True, "impulse_template": "ImpulseEngines",
    "has_warp": True,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": True, "torpedo_tube_count": 4,
}

AKIRA = {
    "script": "Akira",
    "hardpoint_file": "akira.py",
    "ship_template": "Akira",
    "hull_template": "Hull",
    "mass": 70.0, "stationary": 0,
    "has_impulse": True, "impulse_template": "ImpulseEngines",
    "has_warp": True,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": True, "torpedo_tube_count": 4,
}

FEDOUTPOST = {
    "script": "FedOutpost",
    "hardpoint_file": "fedoutpost.py",
    "ship_template": "FedOutpost",
    "hull_template": "Hull",
    "mass": 400.0, "stationary": 0, "ai_string": "StarbaseAttack",
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": False, "torpedo_tube_count": 0,
}

E1M1_EXPECTATIONS = [GALAXY, DRYDOCK, FEDSTARBASE, SHUTTLE,
                     SPACEFACILITY, NEBULA, AKIRA, FEDOUTPOST]


# ── Cross-check expectations against SDK files at module load ─────────────────

def _verify_expectations_against_sdk():
    """Read each hardpoint file and verify the hand-coded ship-level values."""
    for exp in E1M1_EXPECTATIONS:
        path = SDK_HARDPOINTS / exp["hardpoint_file"]
        ship_setters = extract_setters(path, exp["ship_template"])
        for key in ("mass", "affiliation", "stationary", "ship_name", "ai_string"):
            expected = exp.get(key)
            if expected is None:
                continue
            sdk_key = {
                "mass": "Mass",
                "affiliation": "Affiliation",
                "stationary": "Stationary",
                "ship_name": "ShipName",
                "ai_string": "AIString",
            }[key]
            actual = ship_setters.get(sdk_key)
            assert expected == actual, (
                f"{exp['script']}: expected {key}={expected!r} but SDK has "
                f"{sdk_key}={actual!r} in {exp['hardpoint_file']}"
            )


_verify_expectations_against_sdk()


# ── Fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def sdk_setup():
    from tools.mission_harness import setup_sdk
    setup_sdk()


@pytest.fixture(autouse=True)
def clean_state():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    App.g_kSetManager._sets.clear()
    yield
    App.g_kModelPropertyManager.ClearLocalTemplates()
    App.g_kSetManager._sets.clear()


# ── The actual test ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("expected", E1M1_EXPECTATIONS, ids=lambda e: e["script"])
def test_e1m1_ship_identity(sdk_setup, clean_state, expected):
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test_set")

    import loadspacehelper
    ship = loadspacehelper.CreateShip(
        expected["script"], pSet, expected["script"] + "_test", None
    )
    assert ship is not None, f"CreateShip({expected['script']!r}) returned None"

    # ── Ship-level identity ──
    if expected.get("mass") is not None:
        assert ship.GetMass() == expected["mass"]
    if expected.get("affiliation") is not None:
        assert ship.GetAffiliation() == expected["affiliation"]
    if expected.get("ship_name") is not None:
        assert ship.GetShipName() == expected["ship_name"]
    if expected.get("ai_string") is not None:
        assert ship.GetAIString() == expected["ai_string"]
    if expected.get("stationary") is not None:
        assert ship.IsStationary() == expected["stationary"]

    # ── Hull (every E1M1 ship has one) ──
    hull = ship.GetHull()
    assert hull is not None, f"{expected['script']} has no hull"
    assert hull.GetMaxCondition() > 0
    assert hull.GetCondition() == hull.GetMaxCondition(), "hull current must seed full"

    # ── Impulse (conditional) ──
    if expected.get("has_impulse"):
        ies = ship.GetImpulseEngineSubsystem()
        assert ies.GetMaxSpeed() > 0, f"{expected['script']} impulse MaxSpeed must be > 0"
        if "impulse_max_speed" in expected:
            assert ies.GetMaxSpeed() == expected["impulse_max_speed"]
        if "impulse_max_accel" in expected:
            assert ies.GetMaxAccel() == expected["impulse_max_accel"]

    # ── Sensor (conditional) ──
    if expected.get("has_sensor"):
        sens = ship.GetSensorSubsystem()
        assert sens.GetBaseSensorRange() > 0, f"{expected['script']} sensor must have a range"

    # ── Shields (conditional) ──
    if expected.get("has_shields"):
        ss = ship.GetShieldSubsystem()
        for face in range(ShieldProperty.NUM_SHIELDS):
            mx = ss.GetMaxShields(face)
            cur = ss.GetCurrentShields(face)
            assert mx > 0, f"{expected['script']} shield face {face} must have max > 0"
            assert cur == mx, f"{expected['script']} shield face {face} not seeded full"
        if "shield_max_front" in expected:
            assert ss.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == expected["shield_max_front"]
        if "shield_max_rear" in expected:
            assert ss.GetMaxShields(ShieldProperty.REAR_SHIELDS) == expected["shield_max_rear"]

    # ── Phasers (conditional) ──
    if expected.get("has_phasers"):
        ps = ship.GetPhaserSystem()
        assert ps.GetMaxCondition() > 0

    # ── Torpedoes (conditional) ──
    if expected.get("has_torpedoes"):
        ts = ship.GetTorpedoSystem()
        assert ts.GetNumAmmoTypes() == expected["torpedo_tube_count"]
        for i in range(expected["torpedo_tube_count"]):
            assert ts.GetAmmoType(i) == App.AT_ONE
    else:
        # Even ships without torpedoes have a TorpedoSystem (default-installed
        # by ShipClass_Create); it should have no ammo loaded.
        assert ship.GetTorpedoSystem().GetNumAmmoTypes() == 0
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_e1m1_ship_identity.py -v
```

Expected: 8 passed.

If any ship fails, the assertion message identifies which ship and which field. Diagnose by:
1. If the expected value is wrong, read the hardpoint file (`sdk/Build/scripts/ships/Hardpoints/<name>.py`), find the relevant `Set*` call, update the expectation dict. The module-load cross-check will catch the simple ship-level mismatches automatically.
2. If `SetupProperties` isn't propagating a field correctly, revisit the relevant `Task 9–14` branch.

- [ ] **Step 3: Confirm no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_e1m1_ship_identity.py
git commit -m "$(cat <<'EOF'
test(integration): parametrized identity check for E1M1 ship types

Eight ship types (Galaxy, DryDock, FedStarbase, Shuttle, SpaceFacility,
Nebula, Akira, FedOutpost) verified end-to-end through
loadspacehelper.CreateShip. Expectations cross-checked at module load
against the actual hardpoint files via _hardpoint_parser, so SDK drift
fails loudly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (post-write)

- **Spec coverage.** Tasks 9–14 cover every property type in the spec's coverage table. Task 8 covers the `ShipClass` identity surface. Task 6+7 add `ShieldSubsystem`. Task 3 reparents `WeaponSystem`. Task 2 promotes shared identity fields. Task 14 covers the two-pass torpedo seeding. Task 16 covers the parametrized integration test for all eight E1M1 ship types. Task 1 adds the `AT_*` constants needed for the torpedo assertions to be meaningful.
- **Placeholders.** No `TBD` / `TODO` / "fill in" wording. Every code block is complete. Every step has explicit run commands and expected output.
- **Type consistency.** `GetCritical/SetCritical`, `GetTargetable/SetTargetable`, `GetPrimary/SetPrimary`, `GetDisabledPercentage/SetDisabledPercentage`, `GetShipName/SetShipName`, `GetAIString/SetAIString`, `IsStationary/SetStationary`, `GetMaxShields/SetMaxShields(face, value)`, `GetBaseSensorRange/SetBaseSensorRange`, `GetWeaponSystemType/SetWeaponSystemType` — names used in Tasks 2–8 match references in Tasks 9–14 and 16.

If `loadspacehelper.CreateShip` resolves to the SDK file rather than a project shim, no host-loop change is needed for these tests — the SDK importer is already installed by `tools.mission_harness.setup_sdk`. If the live host (`build/open_stbc`) shows new behavior after this work lands, that's a side-effect of `SetupProperties` becoming correct; nothing in this plan touches the renderer.
