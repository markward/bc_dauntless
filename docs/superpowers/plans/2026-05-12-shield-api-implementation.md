# Shield API implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the seven shield-related stub-tracker rows by exposing the missing `App.Shield*_Cast` surface, aligning method names with the SDK, and adding per-tick shield regen + a damage hook.

**Architecture:** `ShieldSubsystem` and `ShieldProperty` already exist in `engine/appc/`. This plan wires them to the SDK call sites (Cast factories, SDK-named method aliases), promotes the property's face-indexed accessors from data-bag shims to real methods, adds `Update(dt)` + `ApplyDamage(face, amount)` simulation, and extends the headless game loop to walk live ships and tick their shields each frame.

**Tech Stack:** Python 3, pytest. No native code in this plan.

**Spec:** [docs/superpowers/specs/2026-05-12-shield-api-implementation-design.md](../specs/2026-05-12-shield-api-implementation-design.md)

---

## File map

| File | Action |
|---|---|
| `engine/appc/subsystems.py` | Modify `ShieldSubsystem`: add face constants, `GetSingleShieldPercentage`, `SetCurShields`, `Update`, `ApplyDamage` |
| `engine/appc/properties.py` | Modify `ShieldProperty`: real `GetMaxShields/SetMaxShields/GetShieldChargePerSecond/SetShieldChargePerSecond` methods |
| `engine/appc/ships.py` | Add `GetShields` alias; set property back-ref in `SetupProperties` |
| `engine/appc/ship_iter.py` | Create — extract `iter_set_objects` / `iter_ships` |
| `engine/host_loop.py` | Modify — import from new ship_iter module |
| `engine/core/loop.py` | Modify — per-tick shield update pass |
| `App.py` | Add `ShieldClass_Cast`, `ShieldProperty_Cast`, `ShieldClass = ShieldSubsystem` |
| `tests/unit/test_shield_subsystem.py` | Extend |
| `tests/unit/test_shield_property.py` | Create |
| `tests/unit/test_shield_cast.py` | Create |
| `tests/unit/test_setup_properties_shield.py` | Extend |
| `tests/unit/test_ship_iter.py` | Create |
| `tests/unit/test_gameloop_shield_regen.py` | Create |
| `tests/unit/test_shield_stub_regression.py` | Create |

---

### Task 1: ShieldSubsystem — face constants + SDK-named alias

The class needs `NUM_SHIELDS` and the six face constants exposed directly (today they live only on `ShieldProperty`), plus `SetCurShields` as an SDK-facing alias for `SetCurrentShields`.

**Files:**
- Modify: `engine/appc/subsystems.py:375-410`
- Test: `tests/unit/test_shield_subsystem.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_shield_subsystem.py`:

```python
def test_face_constants_on_subsystem():
    """SDK reads App.ShieldClass.FRONT_SHIELDS / NUM_SHIELDS — the class
    itself must carry them, not just ShieldProperty."""
    assert ShieldSubsystem.NUM_SHIELDS == 6
    assert ShieldSubsystem.FRONT_SHIELDS == 0
    assert ShieldSubsystem.REAR_SHIELDS == 1
    assert ShieldSubsystem.TOP_SHIELDS == 2
    assert ShieldSubsystem.BOTTOM_SHIELDS == 3
    assert ShieldSubsystem.LEFT_SHIELDS == 4
    assert ShieldSubsystem.RIGHT_SHIELDS == 5


def test_set_cur_shields_aliases_set_current_shields():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 3000.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 3000.0
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
uv run pytest tests/unit/test_shield_subsystem.py -v
```

Expected: the two new tests fail with `AttributeError` (no `NUM_SHIELDS` on class, no `SetCurShields`).

- [ ] **Step 3: Implement**

Edit `engine/appc/subsystems.py` `ShieldSubsystem` class. Add face constants at class level (after the docstring, before `__init__`):

```python
    FRONT_SHIELDS  = 0
    REAR_SHIELDS   = 1
    TOP_SHIELDS    = 2
    BOTTOM_SHIELDS = 3
    LEFT_SHIELDS   = 4
    RIGHT_SHIELDS  = 5
    NUM_SHIELDS    = 6
```

Replace the existing `NUM_FACES = 6` line and any `self.NUM_FACES` references with `NUM_SHIELDS`. Update the `__init__` lists that use `self.NUM_FACES` to use `self.NUM_SHIELDS`.

Add this method after `SetCurrentShields`:

```python
    def SetCurShields(self, face: int, value: float) -> None:
        """SDK-facing alias of SetCurrentShields (matches Appc method name)."""
        self.SetCurrentShields(face, value)
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
uv run pytest tests/unit/test_shield_subsystem.py -v
```

Expected: all tests in the file pass (the existing four plus the two new ones).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_subsystem.py
git commit -m "feat(shields): expose face constants on ShieldSubsystem + SetCurShields alias"
```

---

### Task 2: ShieldSubsystem.GetSingleShieldPercentage

Compute current/max ratio per face. Returns 0.0 when max==0 (no divide-by-zero — `IsAnyShieldBreached` in MissionLib relies on this).

**Files:**
- Modify: `engine/appc/subsystems.py` `ShieldSubsystem`
- Test: `tests/unit/test_shield_subsystem.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_shield_subsystem.py`:

```python
def test_single_shield_percentage_full():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    # SetMaxShields seeds current to max when current was 0
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 1.0


def test_single_shield_percentage_half():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 0.5


def test_single_shield_percentage_zero_max_returns_zero():
    """A face with max=0 (unshielded ship) reports 0% without raising."""
    s = ShieldSubsystem("Shield Generator")
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_single_shield_percentage_zero_current():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 0.0)
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 0.0
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
uv run pytest tests/unit/test_shield_subsystem.py::test_single_shield_percentage_full -v
```

Expected: `AttributeError: 'ShieldSubsystem' object has no attribute 'GetSingleShieldPercentage'`.

- [ ] **Step 3: Implement**

Add to `ShieldSubsystem` (after `SetCurShields`):

```python
    def GetSingleShieldPercentage(self, face: int) -> float:
        """current/max for the face; 0.0 when max==0 (unshielded face).

        SDK caller MissionLib.IsAnyShieldBreached treats anything <0.05 as
        a breach, so the max==0 case must return 0.0, not raise.
        """
        f = int(face)
        mx = self._max_shields[f]
        if mx == 0.0:
            return 0.0
        return self._current_shields[f] / mx
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
uv run pytest tests/unit/test_shield_subsystem.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_subsystem.py
git commit -m "feat(shields): GetSingleShieldPercentage on ShieldSubsystem"
```

---

### Task 3: ShieldSubsystem.Update — per-tick regen

Each face regenerates by `charge_per_second * dt`, clamped at `max`. Faces with `max==0` stay at 0.

**Files:**
- Modify: `engine/appc/subsystems.py` `ShieldSubsystem`
- Test: `tests/unit/test_shield_subsystem.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_shield_subsystem.py`:

```python
def test_update_regenerates_face():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 10.0)
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 60.0


def test_update_clamps_at_max():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 95.0)
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 100.0


def test_update_zero_charge_rate_noop():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    # charge_per_second defaults to 0
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 50.0


def test_update_skips_unshielded_face():
    """A face with max=0 (e.g. asteroid-like object) stays at 0 even if
    something erroneously set its charge_per_second."""
    s = ShieldSubsystem("Shield Generator")
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_update_independent_per_face():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetMaxShields(ShieldProperty.REAR_SHIELDS, 200.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 0.0)
    s.SetCurShields(ShieldProperty.REAR_SHIELDS, 0.0)
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 10.0)
    s.SetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS, 20.0)
    s.Update(2.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 20.0
    assert s.GetCurrentShields(ShieldProperty.REAR_SHIELDS) == 40.0
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
uv run pytest tests/unit/test_shield_subsystem.py::test_update_regenerates_face -v
```

Expected: `AttributeError: 'ShieldSubsystem' object has no attribute 'Update'`.

- [ ] **Step 3: Implement**

Add to `ShieldSubsystem`:

```python
    def Update(self, dt: float) -> None:
        """Per-tick regen: current += charge_per_second * dt, clamped to max.

        Faces with max==0 are skipped so unshielded faces never accumulate.
        """
        dt = float(dt)
        for f in range(self.NUM_SHIELDS):
            mx = self._max_shields[f]
            if mx == 0.0:
                continue
            new = self._current_shields[f] + self._charge_per_second[f] * dt
            if new > mx:
                new = mx
            self._current_shields[f] = new
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
uv run pytest tests/unit/test_shield_subsystem.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_subsystem.py
git commit -m "feat(shields): ShieldSubsystem.Update regen with per-face clamp"
```

---

### Task 4: ShieldSubsystem.ApplyDamage

Drain `current` toward 0, return overflow so caller can route it to hull.

**Files:**
- Modify: `engine/appc/subsystems.py` `ShieldSubsystem`
- Test: `tests/unit/test_shield_subsystem.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_apply_damage_partial():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 30.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 70.0


def test_apply_damage_exact():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 50.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_apply_damage_overflow():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 20.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 50.0)
    assert overflow == 30.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_apply_damage_other_faces_untouched():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetMaxShields(ShieldProperty.REAR_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.REAR_SHIELDS, 100.0)
    s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 40.0)
    assert s.GetCurrentShields(ShieldProperty.REAR_SHIELDS) == 100.0


def test_apply_damage_zero_amount_noop():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 75.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 0.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 75.0
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
uv run pytest tests/unit/test_shield_subsystem.py::test_apply_damage_partial -v
```

Expected: `AttributeError: 'ShieldSubsystem' object has no attribute 'ApplyDamage'`.

- [ ] **Step 3: Implement**

Add to `ShieldSubsystem`:

```python
    def ApplyDamage(self, face: int, amount: float) -> float:
        """Drain current shields on the face; return damage overflow.

        Caller routes the returned overflow to hull. Does not trigger
        regen, fire events, or mutate any other face.
        """
        f = int(face)
        amt = float(amount)
        cur = self._current_shields[f]
        if amt <= cur:
            self._current_shields[f] = cur - amt
            return 0.0
        self._current_shields[f] = 0.0
        return amt - cur
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
uv run pytest tests/unit/test_shield_subsystem.py -v
```

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_subsystem.py
git commit -m "feat(shields): ShieldSubsystem.ApplyDamage with overflow return"
```

---

### Task 5: ShieldProperty — real per-face accessors

Promote `GetMaxShields/SetMaxShields/GetShieldChargePerSecond/SetShieldChargePerSecond` from the data-bag shim to real methods. Existing tests use these names via the shim — they must keep passing.

**Files:**
- Modify: `engine/appc/properties.py` `ShieldProperty`
- Create: `tests/unit/test_shield_property.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_shield_property.py`:

```python
"""ShieldProperty: real per-face accessors (not data-bag shims)."""
from engine.appc.properties import ShieldProperty


def test_max_shields_defaults_zero():
    p = ShieldProperty("Shield Generator")
    for face in range(ShieldProperty.NUM_SHIELDS):
        assert p.GetMaxShields(face) == 0.0


def test_max_shields_round_trip_per_face():
    p = ShieldProperty("Shield Generator")
    p.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    p.SetMaxShields(ShieldProperty.REAR_SHIELDS,  4000.0)
    assert p.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert p.GetMaxShields(ShieldProperty.REAR_SHIELDS) == 4000.0
    assert p.GetMaxShields(ShieldProperty.TOP_SHIELDS) == 0.0


def test_charge_per_second_round_trip_per_face():
    p = ShieldProperty("Shield Generator")
    p.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 10.0)
    p.SetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS,  20.0)
    assert p.GetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS) == 10.0
    assert p.GetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS) == 20.0
    assert p.GetShieldChargePerSecond(ShieldProperty.TOP_SHIELDS) == 0.0


def test_methods_are_real_not_databag_shim():
    """The methods must exist on the class itself, not be synthesized by
    TGModelProperty.__getattr__.  Without this, the SDK call sites would
    keep round-tripping through the data-bag and the accessors would
    return None for unset faces (vs. 0.0)."""
    assert "GetMaxShields" in vars(ShieldProperty)
    assert "SetMaxShields" in vars(ShieldProperty)
    assert "GetShieldChargePerSecond" in vars(ShieldProperty)
    assert "SetShieldChargePerSecond" in vars(ShieldProperty)
    # A real bound method has __self__; a __getattr__-synthesized closure
    # is a plain function without it.
    p = ShieldProperty("X")
    assert p.GetMaxShields.__self__ is p
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
uv run pytest tests/unit/test_shield_property.py -v
```

Expected: defaults and the "real method" test fail. The round-trip tests may pass (they go through the data-bag shim today).

- [ ] **Step 3: Implement**

Edit `engine/appc/properties.py` `ShieldProperty`. Replace the existing body with:

```python
class ShieldProperty(PoweredSubsystemProperty):
    FRONT_SHIELDS  = 0
    REAR_SHIELDS   = 1
    TOP_SHIELDS    = 2
    BOTTOM_SHIELDS = 3
    LEFT_SHIELDS   = 4
    RIGHT_SHIELDS  = 5
    NUM_SHIELDS    = 6

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_shields = [0.0] * self.NUM_SHIELDS
        self._charge_per_second = [0.0] * self.NUM_SHIELDS

    def GetMaxShields(self, face):
        return self._max_shields[int(face)]

    def SetMaxShields(self, face, value):
        f = int(face)
        v = float(value)
        self._max_shields[f] = v
        # Transition dual-write: existing data-bag readers keep working
        # until Task 10 removes this line.
        self._data[("MaxShields", (f,))] = v

    def GetShieldChargePerSecond(self, face):
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face, value):
        f = int(face)
        v = float(value)
        self._charge_per_second[f] = v
        self._data[("ShieldChargePerSecond", (f,))] = v
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
uv run pytest tests/unit/test_shield_property.py tests/unit/test_setup_properties_shield.py tests/unit/test_shield_property_skin.py -v
```

Expected: all pass. (The `setup_properties_shield` test uses these methods to populate a property — must keep working.)

- [ ] **Step 5: Run the full unit test suite to catch any regressions**

```bash
uv run pytest tests/unit -q
```

Expected: same pass count as before, plus the new tests.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/properties.py tests/unit/test_shield_property.py
git commit -m "feat(shields): real per-face accessors on ShieldProperty"
```

---

### Task 6: ShipClass — GetShields alias + property back-ref

SDK uses `pShip.GetShields()`; engine has `GetShieldSubsystem()`. Add the alias. Also, set the subsystem's `_property` back-ref in `SetupProperties` so `GetProperty()` (inherited from `ShipSubsystem`) returns the source `ShieldProperty`.

**Files:**
- Modify: `engine/appc/ships.py:104-105` (alias) and `engine/appc/ships.py:184-192` (back-ref)
- Modify: `tests/unit/test_setup_properties_shield.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_setup_properties_shield.py`:

```python
def test_get_shields_aliases_get_shield_subsystem():
    """SDK uses pShip.GetShields(); engine has GetShieldSubsystem.
    Both names must return the same object."""
    ship = ShipClass_Create("Galaxy")
    assert ship.GetShields() is ship.GetShieldSubsystem()


def test_setup_properties_sets_shield_property_back_ref():
    """After SetupProperties copies a ShieldProperty onto the subsystem,
    the subsystem's GetProperty() returns the source property.
    loadspacehelper.py:246 reads pShields.GetProperty()."""
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    assert ship.GetShields().GetProperty() is sp
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
uv run pytest tests/unit/test_setup_properties_shield.py -v
```

Expected: `AttributeError: 'ShipClass' object has no attribute 'GetShields'`, and the back-ref assertion fails.

- [ ] **Step 3: Implement**

In `engine/appc/ships.py`, after the `SetShieldSubsystem` line (around line 105), add:

```python
    # SDK-facing alias — pShip.GetShields() in mission scripts and SDK helpers.
    def GetShields(self):                         return self._shield_subsystem
```

In the same file, in `SetupProperties` at the `elif isinstance(prop, ShieldProperty):` branch (around line 184), set the back-ref:

```python
            elif isinstance(prop, ShieldProperty):
                self._copy_powered_subsystem_fields(prop, self._shield_subsystem)
                ss = self._shield_subsystem
                if ss is not None:
                    ss.SetProperty(prop)
                    for face in range(ShieldProperty.NUM_SHIELDS):
                        mx = prop.GetMaxShields(face)
                        if mx is not None: ss.SetMaxShields(face, mx)
                        cr = prop.GetShieldChargePerSecond(face)
                        if cr is not None: ss.SetShieldChargePerSecond(face, cr)
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
uv run pytest tests/unit/test_setup_properties_shield.py tests/unit/test_ship_shield_slot.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_setup_properties_shield.py
git commit -m "feat(shields): ShipClass.GetShields alias + property back-ref in SetupProperties"
```

---

### Task 7: App.ShieldClass_Cast / ShieldProperty_Cast / ShieldClass re-export

Cast factories return the object when the type matches, `None` otherwise. Must reject `_NamedStub` instances. Re-exporting `ShieldSubsystem` as `App.ShieldClass` lets SDK code read `App.ShieldClass.NUM_SHIELDS`.

**Files:**
- Modify: `App.py`
- Create: `tests/unit/test_shield_cast.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_shield_cast.py`:

```python
"""App.ShieldClass_Cast / ShieldProperty_Cast / ShieldClass surface."""
import App
from engine.appc.subsystems import ShieldSubsystem, ImpulseEngineSubsystem
from engine.appc.properties import ShieldProperty, SensorProperty


def test_shield_class_cast_returns_subsystem_unchanged():
    s = ShieldSubsystem("Shield Generator")
    assert App.ShieldClass_Cast(s) is s


def test_shield_class_cast_rejects_other_subsystem():
    other = ImpulseEngineSubsystem("Impulse")
    assert App.ShieldClass_Cast(other) is None


def test_shield_class_cast_rejects_none():
    assert App.ShieldClass_Cast(None) is None


def test_shield_class_cast_rejects_named_stub():
    """Without this, every undefined attribute access keeps producing
    stub-tracker hits via __getattr__."""
    stub = App.SomeUndefinedThing
    assert isinstance(stub, App._NamedStub)
    assert App.ShieldClass_Cast(stub) is None


def test_shield_property_cast_returns_property_unchanged():
    p = ShieldProperty("Shield Generator")
    assert App.ShieldProperty_Cast(p) is p


def test_shield_property_cast_rejects_other_property():
    other = SensorProperty("Sensors")
    assert App.ShieldProperty_Cast(other) is None


def test_shield_property_cast_rejects_named_stub():
    stub = App.SomethingElse
    assert App.ShieldProperty_Cast(stub) is None


def test_app_shield_class_is_subsystem():
    """SDK reads App.ShieldClass.NUM_SHIELDS, .FRONT_SHIELDS, etc."""
    assert App.ShieldClass is ShieldSubsystem
    assert App.ShieldClass.NUM_SHIELDS == 6
    assert App.ShieldClass.FRONT_SHIELDS == 0
```

- [ ] **Step 2: Run tests, confirm fail**

```bash
uv run pytest tests/unit/test_shield_cast.py -v
```

Expected: tests fail. `App.ShieldClass_Cast(s)` returns a `_NamedStub` (not `s`), so `is s` is False; `App.ShieldClass` is `ImpulseEngineSubsystem`... actually, `App.ShieldClass` returns a `_NamedStub` too, so `App.ShieldClass is ShieldSubsystem` is False.

- [ ] **Step 3: Implement**

Edit `App.py`. Locate the imports block that already pulls in `ShieldProperty` (around line 117) and extend it to import `ShieldSubsystem` too. From `engine.appc.subsystems`:

```python
from engine.appc.subsystems import (
    # ... existing imports
    ShieldSubsystem,
)
```

(Find the existing subsystem imports and add `ShieldSubsystem` to the list. If there isn't one yet, add a new `from engine.appc.subsystems import ShieldSubsystem` line near the property imports.)

Then add, alongside the existing module-level re-exports (look for `CT_SHIELD_SUBSYSTEM` around line 167 as a landmark):

```python
# SDK calls App.ShieldClass.NUM_SHIELDS / .FRONT_SHIELDS etc.  Map the class
# name onto the engine's ShieldSubsystem.
ShieldClass = ShieldSubsystem


def ShieldClass_Cast(obj):
    """Lenient pass-through: returns obj if it's a ShieldSubsystem, else None.

    Rejects _NamedStub explicitly so undefined-attribute chains don't slip
    through and keep producing stub-tracker hits."""
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, ShieldSubsystem):
        return obj
    return None


def ShieldProperty_Cast(obj):
    """Lenient pass-through: returns obj if it's a ShieldProperty, else None."""
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, ShieldProperty):
        return obj
    return None
```

Place these BEFORE the module-level `__getattr__` definition at the bottom of the file (lines 653-654) — otherwise `__getattr__` never gets to defer to the real names, but in this case it would still work because real module attributes take precedence. Putting them with the other stable re-exports keeps `App.py` organized.

`_NamedStub` is defined later in the same file (line 628) but module-level definitions don't execute in order at lookup time, so the forward reference is fine.

- [ ] **Step 4: Run tests, confirm pass**

```bash
uv run pytest tests/unit/test_shield_cast.py -v
```

Expected: all pass.

- [ ] **Step 5: Run full unit suite**

```bash
uv run pytest tests/unit -q
```

Expected: same baseline pass count plus the new tests.

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_shield_cast.py
git commit -m "feat(shields): App.ShieldClass_Cast / ShieldProperty_Cast / ShieldClass export"
```

---

### Task 8: Extract iter_ships into engine/appc/ship_iter.py

The headless gameloop needs to walk ships per tick without importing `engine/host_loop.py` (which carries renderer/native dependencies). Pull the existing `_iter_set_objects` and `_iter_ships` helpers into their own module.

**Critical:** Preserve the `_objects.values()` workaround verbatim. Don't refactor to `GetFirstObject/GetNextObject` — the comment block at `host_loop.py:629-637` explains why, and that constraint still applies.

**Files:**
- Create: `engine/appc/ship_iter.py`
- Modify: `engine/host_loop.py` (use the new module)
- Create: `tests/unit/test_ship_iter.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_ship_iter.py`:

```python
"""ship_iter: walk every ship in every active set."""
import App
from engine.appc.sets import SetClass
from engine.appc.ship_iter import iter_ships, iter_set_objects
from engine.appc.ships import ShipClass_Create


def test_iter_ships_empty_when_no_sets():
    """Fresh App.g_kSetManager has no sets — iter yields nothing."""
    App.g_kSetManager._sets.clear()
    assert list(iter_ships()) == []


def test_iter_ships_yields_ships_with_scripts():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    ship.SetScript("test_script")
    pSet.AddObjectToSet(ship, "ship_1")
    found = list(iter_ships())
    assert ship in found


def test_iter_set_objects_yields_via_values():
    """Confirms we still walk _objects.values() rather than GetFirstObject
    — see the comment block in the helper for why."""
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    pSet.AddObjectToSet(ship, "ship_1")
    found = list(iter_set_objects(pSet))
    assert ship in found
```

- [ ] **Step 2: Run test, confirm fail**

```bash
uv run pytest tests/unit/test_ship_iter.py -v
```

Expected: `ModuleNotFoundError: No module named 'engine.appc.ship_iter'`.

- [ ] **Step 3: Create the new module**

Create `engine/appc/ship_iter.py`:

```python
"""Walk live ships / set objects.

Extracted from engine/host_loop.py so the headless gameloop can drive
per-tick subsystem updates without pulling in the renderer-host module.

Iteration intentionally uses `pSet._objects.values()` rather than BC's
`GetFirstObject + GetNextObject` API: the latter is unreliable in the
presence of stub objects.  Any object whose `GetObjID()` returns an
`App._NamedStub` causes `SetClass.GetNextObject(stub).int(stub) -> 0`
to find no match and return None, terminating iteration prematurely.
The `_objects` private attribute is already inspected elsewhere
(set-membership checks, verbose logging), so the implementation
coupling is consistent.
"""
from typing import Iterable

import App


def iter_set_objects(pSet) -> Iterable:
    """Walk every object in a set exactly once via _objects.values()."""
    for obj in getattr(pSet, "_objects", {}).values():
        yield obj


def iter_ships(*, verbose: bool = False) -> Iterable:
    """Walk every ShipClass-like object in every active set."""
    for set_name, pSet in App.g_kSetManager._sets.items():
        if verbose:
            count = len(getattr(pSet, "_objects", {}))
            obj_keys = list(getattr(pSet, "_objects", {}).keys())
            print(f"[ship_iter] set {set_name!r}: {count} object(s), keys={obj_keys}", flush=True)
        for obj in iter_set_objects(pSet):
            # ShipClass exposes GetScript; non-ship objects (waypoints,
            # characters) typically don't have a non-empty script string.
            if hasattr(obj, "GetScript"):
                yield obj
```

- [ ] **Step 4: Update host_loop.py to use the new module**

In `engine/host_loop.py`, find and remove the existing `_iter_set_objects` (around line 627) and `_iter_ships` (around line 643) function definitions.

At the top of the file (with the other imports), add:

```python
from engine.appc.ship_iter import iter_set_objects as _iter_set_objects, iter_ships as _iter_ships
```

The leading underscore aliases preserve the private-name convention used internally in `host_loop.py`. All existing call sites (`_iter_planets`, `_iter_suns`, the AI walker) continue to work unchanged.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_ship_iter.py tests/unit -q
```

Expected: new tests pass; full unit suite still passes (no regressions in host_loop usage).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ship_iter.py engine/host_loop.py tests/unit/test_ship_iter.py
git commit -m "refactor(engine): extract iter_ships into engine/appc/ship_iter"
```

---

### Task 9: GameLoop.tick — per-tick shield update pass

Wire the regen into the headless game loop. Order: timers, then shield subsystems.

**Files:**
- Modify: `engine/core/loop.py`
- Create: `tests/unit/test_gameloop_shield_regen.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_gameloop_shield_regen.py`:

```python
"""GameLoop.tick drives shield regen on registered ships."""
import App
from engine.appc.properties import ShieldProperty
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.core.loop import GameLoop, TICK_RATE


def test_tick_regens_shields_on_set_managed_ship():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")

    ship = ShipClass_Create("Galaxy")
    ship.SetScript("test_script")  # makes iter_ships find it
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    sp.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 60.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    # Drain so regen has somewhere to go
    ship.GetShields().SetCurShields(ShieldProperty.FRONT_SHIELDS, 0.0)

    pSet.AddObjectToSet(ship, "ship_1")

    loop = GameLoop()
    # 60 ticks @ 60 Hz = 1.0s of game time; charge 60/s -> +60
    loop.advance(TICK_RATE)
    assert ship.GetShields().GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 60.0


def test_tick_skips_ship_with_no_shield_subsystem():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    ship.SetScript("test_script")
    ship.SetShieldSubsystem(None)  # explicitly no shields (e.g. shuttlecraft)
    pSet.AddObjectToSet(ship, "ship_1")

    loop = GameLoop()
    loop.tick()  # must not raise
```

- [ ] **Step 2: Run test, confirm fail**

```bash
uv run pytest tests/unit/test_gameloop_shield_regen.py -v
```

Expected: regen test fails (current stays 0.0 — no shield update happens).

- [ ] **Step 3: Implement**

Replace `engine/core/loop.py` with:

```python
import App

from engine.appc.ship_iter import iter_ships

TICK_RATE = 60
TICK_DELTA = 1.0 / TICK_RATE


class GameLoop:
    """Drives App.g_kTimerManager, App.g_kRealtimeTimerManager, and live-ship
    subsystem updates at 60 Hz.

    Phase 1: both timer managers advance at the same fixed rate.
    Subsystem updates run after timers, mirroring the instrumented
    AI/Python-first-then-physics-then-render ordering (Q2).
    """

    def tick(self) -> None:
        App.g_kTimerManager.tick(TICK_DELTA)
        App.g_kRealtimeTimerManager.tick(TICK_DELTA)
        for ship in iter_ships():
            ss = ship.GetShieldSubsystem()
            if ss is not None:
                ss.Update(TICK_DELTA)

    def advance(self, n: int) -> None:
        for _ in range(n):
            self.tick()

    @property
    def game_time(self) -> float:
        return App.g_kTimerManager.get_time()
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_gameloop_shield_regen.py tests/unit -q
```

Expected: new tests pass, full unit suite passes.

- [ ] **Step 5: Commit**

```bash
git add engine/core/loop.py tests/unit/test_gameloop_shield_regen.py
git commit -m "feat(loop): per-tick shield regen pass"
```

---

### Task 10: Stub-tracker regression test

Reproduce the difficulty-scaling code path from `loadspacehelper.py:241-258` and assert no shield-related entries appear in the stub-tracker's report.

**Files:**
- Create: `tests/unit/test_shield_stub_regression.py`

- [ ] **Step 1: Write the regression test**

Create `tests/unit/test_shield_stub_regression.py`:

```python
"""After the shield API is wired up, the seven SDK shield-call rows must
not appear in App._stub_tracker.report()."""
import App
from engine.appc.properties import ShieldProperty
from engine.appc.ships import ShipClass_Create


SHIELD_STUB_NAMES = {
    "ShieldClass_Cast",
    "ShieldProperty_Cast",
    # Methods that previously chained off the _NamedStub Cast return:
    "GetMaxShields",
    "SetMaxShields",
    "SetCurShields",
    "GetSingleShieldPercentage",
    "GetShieldChargePerSecond",
    "SetShieldChargePerSecond",
    "GetProperty",
}


def test_difficulty_scale_path_records_no_shield_stubs():
    """Exercise the SDK-style loadspacehelper.SetDifficulty path that the
    stub profile flagged: ShieldClass_Cast(sub).GetProperty().SetMaxShields,
    etc.  After Tasks 1-9 these should all hit real implementations."""
    App._stub_tracker.clear()
    App._stub_tracker.set_mission("regression")

    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    for face in range(ShieldProperty.NUM_SHIELDS):
        sp.SetMaxShields(face, 1000.0)
        sp.SetShieldChargePerSecond(face, 10.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    pSubsystem = ship.GetShields()
    pNewProperty = sp
    fDFactor = 2.0

    # Mirrors loadspacehelper.py:243-258 verbatim:
    pShields = App.ShieldClass_Cast(pSubsystem)
    pShieldProperty = App.ShieldProperty_Cast(pNewProperty)
    assert pShields is not None
    assert pShieldProperty is not None

    pCurrentProperty = pShields.GetProperty()
    facings = [
        App.ShieldClass.FRONT_SHIELDS,
        App.ShieldClass.REAR_SHIELDS,
        App.ShieldClass.TOP_SHIELDS,
        App.ShieldClass.BOTTOM_SHIELDS,
        App.ShieldClass.LEFT_SHIELDS,
        App.ShieldClass.RIGHT_SHIELDS,
    ]
    for kFacing in facings:
        fPct = pShields.GetSingleShieldPercentage(kFacing)
        pCurrentProperty.SetMaxShields(
            kFacing, pShieldProperty.GetMaxShields(kFacing) * fDFactor)
        pShields.SetCurShields(
            kFacing, pShields.GetMaxShields(kFacing) * fPct)
        pCurrentProperty.SetShieldChargePerSecond(
            kFacing, pShieldProperty.GetShieldChargePerSecond(kFacing) * fDFactor)

    App._stub_tracker.reset_mission()
    leaked = {name for (name, _, _) in App._stub_tracker.report()
              if any(stub in name for stub in SHIELD_STUB_NAMES)}
    assert leaked == set(), (
        "Shield SDK calls still hit _NamedStub: " + repr(leaked))
```

- [ ] **Step 2: Run test, confirm pass**

```bash
uv run pytest tests/unit/test_shield_stub_regression.py -v
```

Expected: pass on the first run (the prior tasks already wired everything up).

If this test FAILS at this point, do not edit the test to make it pass — diagnose which call site is still hitting a stub and fix it in the appropriate prior-task file.

- [ ] **Step 3: Run the full suite**

```bash
uv run pytest tests/unit -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_shield_stub_regression.py
git commit -m "test(shields): regression — difficulty-scale path produces no stub hits"
```

---

### Task 11: Drop the ShieldProperty data-bag dual-write

Task 5 wrote into both `self._max_shields[f]` AND `self._data[("MaxShields", (f,))]` to keep any data-bag reader working. If no reader uses those keys, drop the dual-write.

**Files:**
- Modify: `engine/appc/properties.py` `ShieldProperty`

- [ ] **Step 1: Search for data-bag readers**

```bash
grep -rn '"MaxShields"\|"ShieldChargePerSecond"\|_data\[.*MaxShields\|_data\[.*ShieldChargePerSecond' \
  /Users/mward/Documents/Projects/open_stbc/engine \
  /Users/mward/Documents/Projects/open_stbc/native \
  /Users/mward/Documents/Projects/open_stbc/tests
```

Expected: only the writes in `properties.py` itself, no readers.

If you find any reader, STOP and leave the dual-write in place; document the reader in this task's notes and skip to the commit (commit a no-op message saying the dual-write is retained because of reader X).

- [ ] **Step 2: Remove the two `self._data[...]` lines**

In `engine/appc/properties.py` `ShieldProperty.SetMaxShields` and `SetShieldChargePerSecond`, delete the `self._data[...] = v` lines added in Task 5.

- [ ] **Step 3: Run the full suite**

```bash
uv run pytest tests/unit -q
```

Expected: all tests still pass.

- [ ] **Step 4: Commit**

```bash
git add engine/appc/properties.py
git commit -m "refactor(shields): drop ShieldProperty data-bag dual-write"
```

---

## Verification — final state

Run the full test suite and confirm:

```bash
uv run pytest tests/unit -v
```

All tests pass, including the new shield tests and the stub-tracker regression test. The seven shield-related rows from the stub-call profile are eliminated.
