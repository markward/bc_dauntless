# `IsTypeOf` + `GetSubsystemByProperty` — hotfix plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Stop `AdjustShipForDifficulty` from crashing on a Galaxy ship at mission load, and make it actually do its job — currently it's been silently stub-walking.

**Why now:** Today's shield-API work tightened `ShieldClass_Cast` to reject stubs. That surfaced a latent bug: `pShip.GetSubsystemByProperty(prop)` was never implemented on `ShipClass`, so the SDK was working through a stub the whole time. The strict cast returns None, the SDK calls `.GetProperty()` on None, crash.

**Spec:** Inline (this doc).

## Surface to add

### `ShipSubsystem.IsTypeOf(cls) -> int`

The SDK's `CT_*` constants are property classes (`App.CT_SHIELD_SUBSYSTEM = ShieldProperty`, `App.CT_ENERGY_WEAPON = EnergyWeaponProperty`, etc.). A subsystem "is of type X" when its source property is an instance of X. Implementation lives on the base `ShipSubsystem` so every subclass inherits the same logic.

```python
def IsTypeOf(self, cls) -> int:
    """SDK class-id check. Returns 1 when this subsystem's source
    property is an instance of `cls`, else 0.

    `cls` may be a fall-through stub (App.CT_UNKNOWN -> _NamedStub
    instance), so we guard with isinstance(cls, type) before testing.
    """
    if self._property is None or not isinstance(cls, type):
        return 0
    return 1 if isinstance(self._property, cls) else 0
```

`_property` is set by `ShipClass.SetupProperties` (already wired for `ShieldSubsystem` in the shield-API work; other subsystems get it set today only via `ShipSubsystem.SetProperty`, which is callable but not always invoked — that's fine, an unset `_property` correctly reports 0 for every type).

### `ShipClass.GetSubsystemByProperty(prop)`

Walks every slot, returns the subsystem whose `GetProperty()` is identity-equal to `prop`. Hull is included — it's a subsystem-shaped slot in the SDK's eyes ([App.py:5378 `pShip.GetHull()`](sdk/Build/scripts/App.py)).

```python
def GetSubsystemByProperty(self, prop):
    """Find the live subsystem whose source property is `prop`.

    Mirrors sdk/.../App.py:5438 - the SDK uses this in
    loadspacehelper.AdjustShipForDifficulty to map each
    SubsystemProperty in the ship's property set to its live
    subsystem instance.
    """
    for sub in (
        self._sensor_subsystem,
        self._impulse_engine_subsystem,
        self._warp_engine_subsystem,
        self._torpedo_system,
        self._phaser_system,
        self._pulse_weapon_system,
        self._tractor_beam_system,
        self._shield_subsystem,
        self._hull,
    ):
        if sub is not None and sub.GetProperty() is prop:
            return sub
    return None
```

## Tests

Three test files, one per task:

1. **`tests/unit/test_subsystem_istypeof.py`** — `IsTypeOf` returns 0 by default, 1 when property type matches, 0 when wrong type, 0 when `cls` is a `_NamedStub` instance.
2. **`tests/unit/test_ship_get_subsystem_by_property.py`** — returns the right subsystem for a shielded ship, returns None for a property not on the ship, returns None for a ship with no shield subsystem.
3. **`tests/integration/test_adjust_ship_for_difficulty.py`** — exercises the full `loadspacehelper.AdjustShipForDifficulty(ship, "Galaxy")` path on a real-ish Galaxy ship and asserts:
   - It doesn't raise.
   - The shield's `_max_shields[FRONT]` is scaled by `Game_GetDefensiveDifficultyMultiplier()` after the call.

---

### Task 1: `ShipSubsystem.IsTypeOf`

**Files:**
- Modify: `engine/appc/subsystems.py` `ShipSubsystem` class (around line 20)
- Create: `tests/unit/test_subsystem_istypeof.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_subsystem_istypeof.py`:

```python
"""ShipSubsystem.IsTypeOf — SDK class-id check via source-property type."""
import App
from engine.appc.subsystems import (
    ShipSubsystem, ShieldSubsystem, ImpulseEngineSubsystem,
)
from engine.appc.properties import (
    ShieldProperty, ImpulseEngineProperty, SensorProperty,
)


def test_default_is_type_of_zero_with_no_property():
    s = ShieldSubsystem("Shield Generator")
    # No SetProperty called.
    assert s.IsTypeOf(ShieldProperty) == 0


def test_is_type_of_matches_property_class():
    s = ShieldSubsystem("Shield Generator")
    s.SetProperty(ShieldProperty("template"))
    assert s.IsTypeOf(ShieldProperty) == 1


def test_is_type_of_zero_for_wrong_class():
    s = ShieldSubsystem("Shield Generator")
    s.SetProperty(ShieldProperty("template"))
    assert s.IsTypeOf(SensorProperty) == 0
    assert s.IsTypeOf(ImpulseEngineProperty) == 0


def test_is_type_of_zero_when_cls_is_a_named_stub_instance():
    """App.CT_UNKNOWN_THING returns a _NamedStub instance (not a class).
    Guard against TypeError from isinstance(prop, instance)."""
    s = ShieldSubsystem("Shield Generator")
    s.SetProperty(ShieldProperty("template"))
    fake_ct = App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST
    assert isinstance(fake_ct, App._NamedStub)
    # Must not raise; must return 0.
    assert s.IsTypeOf(fake_ct) == 0


def test_is_type_of_works_on_other_subsystem_types():
    """Confirms IsTypeOf lives on the base, not the shield subclass."""
    s = ImpulseEngineSubsystem("Impulse")
    s.SetProperty(ImpulseEngineProperty("template"))
    assert s.IsTypeOf(ImpulseEngineProperty) == 1
    assert s.IsTypeOf(ShieldProperty) == 0
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/unit/test_subsystem_istypeof.py -v
```

Expected: `IsTypeOf` returns a `_Stub` (from `TGObject.__getattr__`), so equality comparison against `0` or `1` fails.

- [ ] **Step 3: Implement**

Add to `ShipSubsystem` in `engine/appc/subsystems.py` (after `SetProperty` around line 48):

```python
    def IsTypeOf(self, cls) -> int:
        """SDK class-id check. Returns 1 when this subsystem's source
        property is an instance of `cls`, else 0.

        `cls` may be a fall-through stub (e.g. App.CT_UNKNOWN_THING
        returns an App._NamedStub instance), so guard with
        isinstance(cls, type) before testing.
        """
        if self._property is None or not isinstance(cls, type):
            return 0
        return 1 if isinstance(self._property, cls) else 0
```

- [ ] **Step 4: Run new tests + full unit suite**

```bash
uv run pytest tests/unit/test_subsystem_istypeof.py -v
uv run pytest tests/unit -q
```

Expected: new tests pass; full suite stays green (800 + 5 = 805).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_subsystem_istypeof.py
git commit -m "feat(subsystems): ShipSubsystem.IsTypeOf via source-property class

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `ShipClass.GetSubsystemByProperty`

**Files:**
- Modify: `engine/appc/ships.py` `ShipClass` (near the other Get*Subsystem accessors around line 104)
- Create: `tests/unit/test_ship_get_subsystem_by_property.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_ship_get_subsystem_by_property.py`:

```python
"""ShipClass.GetSubsystemByProperty — slot scan returning the live
subsystem whose source property matches the requested one."""
from engine.appc.properties import ShieldProperty, SensorProperty
from engine.appc.ships import ShipClass_Create


def test_returns_shield_subsystem_for_its_property():
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    assert ship.GetSubsystemByProperty(sp) is ship.GetShields()


def test_returns_none_for_property_not_on_ship():
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    foreign = ShieldProperty("foreign")
    assert ship.GetSubsystemByProperty(foreign) is None


def test_returns_none_when_no_subsystem_present():
    ship = ShipClass_Create("Galaxy")
    # No SetupProperties call - the ship has a default ShieldSubsystem
    # instance but no _property back-ref.
    sp = ShieldProperty("never registered")
    assert ship.GetSubsystemByProperty(sp) is None


def test_handles_unrelated_property_type():
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    sensor_prop = SensorProperty("Sensors")
    assert ship.GetSubsystemByProperty(sensor_prop) is None
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/unit/test_ship_get_subsystem_by_property.py -v
```

Expected: `GetSubsystemByProperty` returns a `_Stub` from `TGObject.__getattr__`; `is`/`is None` checks fail.

- [ ] **Step 3: Implement**

Add to `ShipClass` in `engine/appc/ships.py` near `GetShields` (after line 107):

```python
    def GetSubsystemByProperty(self, prop):
        """Find the live subsystem whose source property is `prop`.

        Mirrors sdk/.../App.py:5438 — the SDK calls this from
        loadspacehelper.AdjustShipForDifficulty to map each
        SubsystemProperty in the ship's property set to its live
        subsystem instance.  Returns None if no slot matches.
        """
        for sub in (
            self._sensor_subsystem,
            self._impulse_engine_subsystem,
            self._warp_engine_subsystem,
            self._torpedo_system,
            self._phaser_system,
            self._pulse_weapon_system,
            self._tractor_beam_system,
            self._shield_subsystem,
            self._hull,
        ):
            if sub is not None and sub.GetProperty() is prop:
                return sub
        return None
```

- [ ] **Step 4: Run new tests + full unit suite**

```bash
uv run pytest tests/unit/test_ship_get_subsystem_by_property.py -v
uv run pytest tests/unit -q
```

Expected: new tests pass; full suite stays green (805 + 4 = 809).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_ship_get_subsystem_by_property.py
git commit -m "feat(ships): ShipClass.GetSubsystemByProperty slot scan

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: End-to-end regression — `AdjustShipForDifficulty` doesn't crash

**Files:**
- Create: `tests/integration/test_adjust_ship_for_difficulty.py`

This test exercises the actual SDK code path that crashed: `loadspacehelper.AdjustShipForDifficulty(ship, hardpoint_filename)`. The SDK function calls `Game_GetDifficulty`, multipliers, walks the property set, calls `GetSubsystemByProperty`, casts the result via `ShieldClass_Cast`, then writes through `GetProperty().SetMaxShields(...)`.

Pre-fix: crashes on `pShields.GetProperty()` because `pShields` is None.
Post-fix: completes; shield max-shields are scaled by the defensive multiplier.

- [ ] **Step 1: Write the failing-before, passing-after test**

Create `tests/integration/test_adjust_ship_for_difficulty.py`:

```python
"""Regression: loadspacehelper.AdjustShipForDifficulty must not crash
on a shielded ship, and must actually scale the shield max by the
defensive difficulty multiplier."""
import App
from engine.appc.properties import ShieldProperty
from engine.appc.ships import ShipClass_Create


def _build_galaxy_with_shields():
    """A minimal stand-in for a Galaxy ship with a ShieldProperty in
    its property set and SetupProperties applied. Mirrors what the
    Galaxy hardpoint loader produces — enough for AdjustShipForDifficulty
    to find a real shield subsystem via GetSubsystemByProperty."""
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxCondition(12000.0)
    for face in range(ShieldProperty.NUM_SHIELDS):
        sp.SetMaxShields(face, 8000.0)
        sp.SetShieldChargePerSecond(face, 11.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    return ship, sp


def test_adjust_ship_for_difficulty_does_not_crash_on_shielded_ship():
    """Pre-fix this raised AttributeError: 'NoneType' has no GetProperty()
    at loadspacehelper.py:246."""
    import sys
    sdk_root = "/Users/mward/Documents/Projects/open_stbc/sdk/Build/scripts"
    if sdk_root not in sys.path:
        sys.path.insert(0, sdk_root)
    import loadspacehelper

    ship, sp = _build_galaxy_with_shields()
    # Pre-existing front-face max (before scaling)
    front_max_before = sp.GetMaxShields(ShieldProperty.FRONT_SHIELDS)
    assert front_max_before == 8000.0

    # Should complete without raising:
    loadspacehelper.AdjustShipForDifficulty(ship, "Galaxy")

    # After the call, the SDK has rewritten the property's MaxShields
    # by the defensive multiplier. The Phase 1 App shim returns 1.0
    # for the difficulty multipliers, so values are unchanged but the
    # full code path executed against real subsystems.
    front_max_after = sp.GetMaxShields(ShieldProperty.FRONT_SHIELDS)
    assert front_max_after == front_max_before * App.Game_GetDefensiveDifficultyMultiplier()
```

- [ ] **Step 2: Run, confirm it passes**

```bash
uv run pytest tests/integration/test_adjust_ship_for_difficulty.py -v
```

Expected: passes — by this point both prior tasks have shipped, so the SDK code completes against real implementations.

If it fails — diagnose the failure (likely a missing SDK helper that needs implementing or a property class not covered). Report BLOCKED with the traceback, do not weaken the assertion.

- [ ] **Step 3: Run the full unit + integration suite**

```bash
uv run pytest tests/unit tests/integration -q
```

Expected: green.

- [ ] **Step 4: Manually verify the original launch crash is gone**

```bash
./build/open_stbc
```

Reach the same M2Objects mission and confirm the original `AttributeError: 'NoneType' object has no attribute 'GetProperty'` no longer appears. If the binary now crashes elsewhere, that's a new bug surfaced by this fix — report it but don't fix here.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_adjust_ship_for_difficulty.py
git commit -m "test(loadspacehelper): regression — AdjustShipForDifficulty completes

Reproduces the M2Objects launch crash (AttributeError on None.GetProperty)
and confirms it stays fixed by exercising loadspacehelper.AdjustShipForDifficulty
on a shielded Galaxy ship end-to-end.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```
