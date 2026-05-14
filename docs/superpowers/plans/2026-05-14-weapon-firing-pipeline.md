# Weapon Firing Pipeline (PR 2a of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the BC firing chain end-to-end through the SDK input pipeline — mouse click → `g_kInputManager` → `TGKeyboardEvent` → `g_kKeyboardBinding` → `ET_INPUT_FIRE_*` → `TacticalInterfaceHandlers.FireWeapons` → `WeaponSystem.StartFiring` (gated on charge + power) → emitter `Fire()` + audible Start SFX. Alert level RED turns weapons on; GREEN/YELLOW turns them off. AI ships run the same gating logic. Projectiles, beams, collision, and damage are PR 2b.

**Architecture:** Faithful SDK input plumbing (real `TGInputManager` + `KeyboardBinding`, not a shortcut). Existing PR 1 emitter state (`_max_charge`, `_charge_level`, etc.) gains read consumers: `EnergyWeapon.Fire`/`UpdateCharge`, `TorpedoTube.Fire`/`UpdateReload`. `WeaponSystem` gains a round-robin cursor so default-mode phaser banks fire one-at-a-time per click. `LoadTacticalSounds.LoadSounds()` (SDK script) is the canonical source for weapon SFX name → WAV mapping; no hard-coded names in the engine.

**Tech Stack:** Python (engine shim), pytest. C++ (host: GLFW mouse-button polling). No renderer changes.

**Spec:** [docs/superpowers/specs/2026-05-14-weapon-firing-pipeline-design.md](../specs/2026-05-14-weapon-firing-pipeline-design.md)

---

## File map

- Modify [engine/appc/subsystems.py](engine/appc/subsystems.py): `PoweredSubsystem` on/off state; `WeaponSystem` cursor + StartFiring/StopFiring/IsFiring; emitter `Fire`/`CanFire`/`StopFiring`/`UpdateCharge`/`UpdateReload`.
- Modify [engine/appc/ships.py](engine/appc/ships.py): `ShipClass.SetAlertLevel` flips weapon-group power.
- Modify [engine/appc/properties.py](engine/appc/properties.py): `EnergyWeaponProperty.GetFireSound`/`SetFireSound` typed.
- Modify [engine/appc/events.py](engine/appc/events.py): add `TGBoolEvent`, `TGKeyboardEvent`, `ET_KEYBOARD_EVENT` constant.
- Create `engine/appc/input.py`: `TGInputManager`, `KeyboardBinding`, input constants (`WC_*`, `KY_*`, `KS_*`), `register_input_handlers()` wiring helper.
- Create `engine/appc/windows.py`: `TacticalControlWindow` placeholder.
- Modify [App.py](App.py): re-export new classes / singletons / constants.
- Modify [native/src/renderer/include/renderer/window.h](native/src/renderer/include/renderer/window.h) and [native/src/renderer/window.cc](native/src/renderer/window.cc): add mouse-button polling.
- Modify [native/src/host/host_bindings.cc](native/src/host/host_bindings.cc): `mouse_button_pressed`, `mouse_button_released` Python bindings + GLFW button constants.
- Modify [engine/host_loop.py](engine/host_loop.py): bootstrap input pipeline + `LoadTacticalSounds.LoadSounds()`; per-frame mouse poll; per-frame `_advance_weapons` tick.
- Create unit tests:
  - `tests/unit/test_powered_subsystem_on_off.py`
  - `tests/unit/test_ship_alert_powers_weapons.py`
  - `tests/unit/test_weapon_system_sequential_firing.py`
  - `tests/unit/test_energy_weapon_gating.py`
  - `tests/unit/test_energy_weapon_update_charge.py`
  - `tests/unit/test_torpedo_tube_fire.py`
  - `tests/unit/test_torpedo_tube_reload.py`
  - `tests/unit/test_tg_input_manager.py`
  - `tests/unit/test_keyboard_binding.py`
- Create integration tests:
  - `tests/integration/test_fire_secondary_chain.py`
  - `tests/integration/test_fire_primary_continuous.py`
  - `tests/integration/test_fire_gated_by_alert.py`
  - `tests/integration/test_sequential_firing_galaxy.py`

---

## Task 1: `PoweredSubsystem` on/off state + alert-driven power policy

**Files:**
- Modify: `engine/appc/subsystems.py` (`PoweredSubsystem` class ~line 177)
- Modify: `engine/appc/ships.py` (`ShipClass.SetAlertLevel` ~line 98)
- Create: `tests/unit/test_powered_subsystem_on_off.py`
- Create: `tests/unit/test_ship_alert_powers_weapons.py`

### Steps

- [ ] **Step 1: Write failing tests for PoweredSubsystem on/off**

Create `tests/unit/test_powered_subsystem_on_off.py`:

```python
"""PoweredSubsystem.TurnOn/TurnOff/IsOn + Set/GetPowerPercentageWanted.

Mirrors SDK App.py:5705-5708 surface. Used by ShipClass.SetAlertLevel to
flip weapon groups on/off and by WeaponSystem.StartFiring's gating check.
"""
from engine.appc.subsystems import PoweredSubsystem


def test_powered_subsystem_default_state():
    p = PoweredSubsystem("Test")
    assert p.IsOn() == 0
    assert p.GetPowerPercentageWanted() == 0.0


def test_turn_on_then_is_on():
    p = PoweredSubsystem("Test")
    p.TurnOn()
    assert p.IsOn() == 1


def test_turn_off_then_is_off():
    p = PoweredSubsystem("Test")
    p.TurnOn()
    p.TurnOff()
    assert p.IsOn() == 0


def test_power_percentage_wanted_roundtrip():
    p = PoweredSubsystem("Test")
    p.SetPowerPercentageWanted(0.75)
    assert p.GetPowerPercentageWanted() == 0.75


def test_power_percentage_wanted_coerces_to_float():
    p = PoweredSubsystem("Test")
    p.SetPowerPercentageWanted(1)
    assert isinstance(p.GetPowerPercentageWanted(), float)
    assert p.GetPowerPercentageWanted() == 1.0
```

- [ ] **Step 2: Write failing tests for alert-driven power policy**

Create `tests/unit/test_ship_alert_powers_weapons.py`:

```python
"""ShipClass.SetAlertLevel flips weapon groups (phasers/torpedoes/pulse)
on at RED, off at GREEN/YELLOW. Tractor is NOT toggled by alert level —
it stays under manual control (BC behaviour).
"""
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.properties import WeaponSystemProperty


def _add_group(ship, name, wst):
    p = WeaponSystemProperty(name)
    p.SetWeaponSystemType(wst)
    ship.GetPropertySet().AddToSet("Scene Root", p)


def _galaxy_loadout():
    ship = ShipClass_Create("Galaxy")
    _add_group(ship, "Phasers",  WeaponSystemProperty.WST_PHASER)
    _add_group(ship, "Torpedoes",WeaponSystemProperty.WST_TORPEDO)
    _add_group(ship, "Pulse",    WeaponSystemProperty.WST_PULSE)
    _add_group(ship, "Tractors", WeaponSystemProperty.WST_TRACTOR)
    ship.SetupProperties()
    return ship


def test_red_alert_turns_phasers_on():
    ship = _galaxy_loadout()
    assert ship.GetPhaserSystem().IsOn() == 0
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetPhaserSystem().IsOn() == 1
    assert ship.GetPhaserSystem().GetPowerPercentageWanted() == 1.0


def test_red_alert_turns_torpedoes_on():
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetTorpedoSystem().IsOn() == 1


def test_red_alert_turns_pulse_on():
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetPulseWeaponSystem().IsOn() == 1


def test_red_alert_leaves_tractor_untouched():
    """Tractor is operated by a separate UI toggle, not alert level."""
    ship = _galaxy_loadout()
    assert ship.GetTractorBeamSystem().IsOn() == 0
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetTractorBeamSystem().IsOn() == 0


def test_green_alert_turns_phasers_off():
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    assert ship.GetPhaserSystem().IsOn() == 0
    assert ship.GetPhaserSystem().GetPowerPercentageWanted() == 0.0


def test_yellow_alert_keeps_weapons_off():
    """BC convention: yellow alert raises shields but weapons stay cold."""
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    assert ship.GetPhaserSystem().IsOn() == 0
    assert ship.GetTorpedoSystem().IsOn() == 0
    assert ship.GetPulseWeaponSystem().IsOn() == 0


def test_alert_change_no_op_when_group_missing():
    """A ship with no torpedo system must not crash on SetAlertLevel."""
    ship = ShipClass_Create("Bare")
    _add_group(ship, "Phasers", WeaponSystemProperty.WST_PHASER)
    ship.SetupProperties()
    ship.SetAlertLevel(ShipClass.RED_ALERT)  # must not raise
    assert ship.GetPhaserSystem().IsOn() == 1
    assert ship.GetTorpedoSystem() is None
```

- [ ] **Step 3: Run tests to verify they fail**

```
uv run pytest tests/unit/test_powered_subsystem_on_off.py tests/unit/test_ship_alert_powers_weapons.py -v
```

Expected: PoweredSubsystem tests fail with `AttributeError: 'PoweredSubsystem' object has no attribute 'IsOn'` (etc.). Alert tests fail similarly or assert against the default `_is_on = False` state never being flipped.

- [ ] **Step 4: Implement on/off state on `PoweredSubsystem`**

In [engine/appc/subsystems.py](engine/appc/subsystems.py), find `class PoweredSubsystem(ShipSubsystem)` (around line 177). Extend its `__init__` and add the four new methods:

```python
class PoweredSubsystem(ShipSubsystem):
    """Powered subsystem — consumes power, has a target power level."""
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._normal_power = 0.0
        self._current_power = 0.0
        # On/off state — TurnOn/TurnOff drive gating in WeaponSystem.StartFiring
        # and the shield-raise pathway.  Default off matches the SDK; a fresh
        # ship is unpowered until ShipClass.SetAlertLevel(RED) or a mission
        # script explicitly turns systems on.
        self._is_on: bool = False
        self._power_percentage_wanted: float = 0.0

    def GetNormalPowerPerSecond(self) -> float:
        return self._normal_power

    def SetNormalPowerPerSecond(self, value: float) -> None:
        self._normal_power = float(value)

    def GetPowerPerSecond(self) -> float:
        return self._current_power

    def SetPowerPerSecond(self, value: float) -> None:
        self._current_power = float(value)

    def TurnOn(self) -> None:
        self._is_on = True

    def TurnOff(self) -> None:
        self._is_on = False

    def IsOn(self) -> int:
        return 1 if self._is_on else 0

    def SetPowerPercentageWanted(self, pct) -> None:
        self._power_percentage_wanted = float(pct)

    def GetPowerPercentageWanted(self) -> float:
        return self._power_percentage_wanted
```

- [ ] **Step 5: Rewrite `ShipClass.SetAlertLevel` with the power policy**

In [engine/appc/ships.py](engine/appc/ships.py), replace the current one-line `SetAlertLevel` (around line 98) with:

```python
    def SetAlertLevel(self, v) -> None:
        """Apply the alert-level → weapon-power policy.

        Red alert powers phasers / torpedoes / pulse weapons on; any other
        level powers them off.  Tractor stays under manual control (mirrors
        BC: tractor is toggled by its own UI, not by alert).  In stock BC
        this side-effect flows through the XO menu after BridgeHandlers.
        SetAlertLevel; we collapse that layer until the bridge menu system
        is wired (see CLAUDE.md "two timer trees" pattern).
        """
        self._alert_level = int(v)
        on = (self._alert_level == ShipClass.RED_ALERT)
        for slot in (self._phaser_system, self._torpedo_system,
                     self._pulse_weapon_system):
            if slot is None:
                continue
            if on:
                slot.TurnOn()
                slot.SetPowerPercentageWanted(1.0)
            else:
                slot.TurnOff()
                slot.SetPowerPercentageWanted(0.0)
```

- [ ] **Step 6: Run tests to verify they pass**

```
uv run pytest tests/unit/test_powered_subsystem_on_off.py tests/unit/test_ship_alert_powers_weapons.py -v
```

Expected: ALL PASS.

- [ ] **Step 7: Full unit suite regression check**

```
uv run pytest tests/unit/ -x
```

Expected: PASS. If `test_ship_alert_level.py` or any existing alert test fails because it expected `SetAlertLevel` to be a bare setter, update those tests — the new behaviour is canonical.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/subsystems.py engine/appc/ships.py \
        tests/unit/test_powered_subsystem_on_off.py \
        tests/unit/test_ship_alert_powers_weapons.py
git commit -m "$(cat <<'EOF'
feat(weapons): PoweredSubsystem on/off + alert-driven power

PoweredSubsystem gains TurnOn/TurnOff/IsOn + Get/SetPowerPercentageWanted
matching the SDK surface.  ShipClass.SetAlertLevel(RED) now turns phasers
torpedoes and pulse weapons on with PowerPercentageWanted=1.0; GREEN and
YELLOW turn them off.  Tractor stays under manual control.  Yellow alert
keeps weapons cold (raises shields elsewhere).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `EnergyWeaponProperty.GetFireSound` typed accessor

**Files:**
- Modify: `engine/appc/properties.py` (`EnergyWeaponProperty` ~line 169-206)
- Add tests to: `tests/unit/test_weapon_property_setters.py`

The `__getattr__` catch-all currently stores `SetFireSound("Galaxy Phaser")` and reads it back from `_data`. Promoting it to a typed accessor with an explicit empty-string default makes the SFX trigger logic cleaner and means consumers can rely on the type. Stays consistent with the typed charge fields PR 1 added.

### Steps

- [ ] **Step 1: Add failing test**

Append to `tests/unit/test_weapon_property_setters.py`:

```python
def test_energy_weapon_fire_sound_default_empty():
    p = EnergyWeaponProperty("Test")
    assert p.GetFireSound() == ""


def test_energy_weapon_fire_sound_roundtrip():
    p = EnergyWeaponProperty("Test")
    p.SetFireSound("Galaxy Phaser")
    assert p.GetFireSound() == "Galaxy Phaser"


def test_phaser_inherits_fire_sound():
    p = PhaserProperty("Dorsal Phaser 1")
    p.SetFireSound("Galaxy Phaser")
    assert p.GetFireSound() == "Galaxy Phaser"
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/unit/test_weapon_property_setters.py -v -k fire_sound
```

Expected: tests fail with `None` returned instead of `""` (because the __getattr__ catch-all returns None for unset values; explicit-default tests fail).

- [ ] **Step 3: Add `_fire_sound` field + accessors to `EnergyWeaponProperty`**

In `engine/appc/properties.py`, find `EnergyWeaponProperty` (around line 169). Add to its `__init__`:

```python
        self._fire_sound: str = ""
```

And add two accessor methods after the existing charge-field accessors:

```python
    def GetFireSound(self) -> str:
        return self._fire_sound

    def SetFireSound(self, v) -> None:
        self._fire_sound = str(v)
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_weapon_property_setters.py -v
```

Expected: all (including the new three) pass.

- [ ] **Step 5: Full unit suite regression check**

```
uv run pytest tests/unit/ -x
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/properties.py tests/unit/test_weapon_property_setters.py
git commit -m "$(cat <<'EOF'
feat(props): typed GetFireSound/SetFireSound on EnergyWeaponProperty

Promotes the FireSound field from the __getattr__ catch-all to a typed
accessor with empty-string default.  PR 2a's SFX trigger reads this via
prop.GetFireSound() + " Start" to look up the WAV name registered by
LoadTacticalSounds.LoadSounds() at audio init.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `WeaponSystem` sequential firing cursor

**Files:**
- Modify: `engine/appc/subsystems.py` (`WeaponSystem` class ~line 197)
- Create: `tests/unit/test_weapon_system_sequential_firing.py`

Replaces the bare `_firing` boolean and `StartFiring/StopFiring` with a round-robin cursor over child emitters. Each `StartFiring` call fires the next eligible emitter and advances the cursor; `StopFiring` halts whatever emitters are currently firing. Matches Galaxy's `SetSingleFire(1)` loadout.

Note: `Weapon.CanFire()` and `Weapon.Fire()` are added in Task 4 (energy) and Task 5 (torpedo). Task 3's tests stub these on a fake emitter; later tasks land the real ones.

### Steps

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_weapon_system_sequential_firing.py`:

```python
"""WeaponSystem cursor-based firing: each StartFiring fires the next
eligible emitter in round-robin order.  StopFiring halts current firers.
No-eligible-emitter case is a silent no-op.

These tests use a minimal stub emitter so Task 3 lands without depending
on energy/torp Fire() semantics (Tasks 4/5).
"""
from engine.appc.subsystems import WeaponSystem, ShipSubsystem


class _StubEmitter(ShipSubsystem):
    """Standalone child fitting the WeaponSystem firing contract."""
    def __init__(self, name, can_fire=True):
        super().__init__(name)
        self._can_fire = can_fire
        self.fire_calls = []
        self.stop_calls = 0
        self._firing = False

    def CanFire(self):
        return 1 if self._can_fire else 0

    def Fire(self, target, offset):
        self._firing = True
        self.fire_calls.append((target, offset))

    def StopFiring(self):
        self._firing = False
        self.stop_calls += 1


def _system_with(emitters):
    ws = WeaponSystem("Group")
    ws.TurnOn()
    for e in emitters:
        ws.AddChildSubsystem(e)
    return ws


def test_start_firing_no_ops_when_off():
    e = _StubEmitter("E0")
    ws = WeaponSystem("Off")
    ws.AddChildSubsystem(e)
    # Off by default; StartFiring should not call Fire.
    ws.StartFiring(target=None, offset=None)
    assert e.fire_calls == []


def test_start_firing_no_ops_when_no_emitters():
    ws = WeaponSystem("Empty")
    ws.TurnOn()
    ws.StartFiring(target=None, offset=None)
    # No emitters; must not raise, IsFiring stays 0.
    assert ws.IsFiring() == 0


def test_start_firing_picks_first_emitter():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    ws = _system_with([a, b])
    ws.StartFiring(target="T", offset="O")
    assert a.fire_calls == [("T", "O")]
    assert b.fire_calls == []
    assert ws.IsFiring() == 1


def test_cursor_advances_after_fire():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    c = _StubEmitter("C")
    ws = _system_with([a, b, c])
    ws.StartFiring(None, None)
    ws.StopFiring()
    ws.StartFiring(None, None)
    assert len(a.fire_calls) == 1
    assert len(b.fire_calls) == 1
    assert len(c.fire_calls) == 0


def test_cursor_wraps_around():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    ws = _system_with([a, b])
    for _ in range(3):
        ws.StartFiring(None, None)
        ws.StopFiring()
    # 3 clicks across 2 emitters → A,B,A
    assert len(a.fire_calls) == 2
    assert len(b.fire_calls) == 1


def test_cursor_skips_ineligible_emitters():
    a = _StubEmitter("A", can_fire=False)
    b = _StubEmitter("B", can_fire=True)
    ws = _system_with([a, b])
    ws.StartFiring(None, None)
    assert a.fire_calls == []
    assert b.fire_calls == [(None, None)]


def test_no_eligible_emitter_silent_no_op():
    a = _StubEmitter("A", can_fire=False)
    b = _StubEmitter("B", can_fire=False)
    ws = _system_with([a, b])
    ws.StartFiring(None, None)
    assert ws.IsFiring() == 0
    assert a.fire_calls == []
    assert b.fire_calls == []


def test_stop_firing_halts_active_emitters():
    a = _StubEmitter("A")
    ws = _system_with([a])
    ws.StartFiring(None, None)
    assert ws.IsFiring() == 1
    ws.StopFiring()
    assert ws.IsFiring() == 0
    assert a.stop_calls == 1


def test_is_firing_when_no_emitters():
    ws = WeaponSystem("Empty")
    assert ws.IsFiring() == 0
```

- [ ] **Step 2: Run to verify failures**

```
uv run pytest tests/unit/test_weapon_system_sequential_firing.py -v
```

Expected: All tests fail. The existing `WeaponSystem.StartFiring` calls `Fire` on no children; `IsFiring` returns the bare `_firing` bool which never matches expectations.

- [ ] **Step 3: Rewrite `WeaponSystem` firing surface**

In `engine/appc/subsystems.py`, find `class WeaponSystem(PoweredSubsystem)` (around line 197). Replace its current `__init__`/`StartFiring`/`StopFiring`/`IsFiring` block with:

```python
class WeaponSystem(PoweredSubsystem):
    """Weapon system — has firing state and an optional target.

    Reparented under PoweredSubsystem because every weapon system in BC
    has a power line.  See sdk/.../App.py:6361 (WeaponSystem inherits
    PoweredSubsystem there).

    Sequential firing (PR 2a): StartFiring picks the next eligible
    emitter in round-robin order, fires it, and advances the cursor.
    Matches Galaxy's SetSingleFire(1) loadout.  Multi-fire / firing-chain
    modes are future work (FiringChainString hardpoint field).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._target = None
        self._weapon_system_type: int = 0
        # Round-robin cursor into child emitters and the set of indices
        # currently firing (for StopFiring to halt the right ones).
        self._next_emitter_index: int = 0
        self._currently_firing: list[int] = []

    def StartFiring(self, target=None, offset=None) -> None:
        if not self.IsOn():
            return
        n = self.GetNumWeapons()
        if n == 0:
            return
        start = self._next_emitter_index % n
        for delta in range(n):
            idx = (start + delta) % n
            emitter = self.GetWeapon(idx)
            if emitter is None:
                continue
            if hasattr(emitter, "CanFire") and emitter.CanFire():
                emitter.Fire(target, offset)
                self._currently_firing.append(idx)
                self._next_emitter_index = (idx + 1) % n
                return
        # No eligible emitter — silent no-op.

    def StopFiring(self, *args) -> None:
        for idx in self._currently_firing:
            emitter = self.GetWeapon(idx)
            if emitter is not None and hasattr(emitter, "StopFiring"):
                emitter.StopFiring()
        self._currently_firing.clear()

    def IsFiring(self) -> int:
        return 1 if self._currently_firing else 0

    def GetTarget(self):
        return self._target

    def SetTarget(self, target) -> None:
        self._target = target

    def GetWeaponSystemType(self) -> int:
        return self._weapon_system_type

    def SetWeaponSystemType(self, v) -> None:
        self._weapon_system_type = int(v)

    # SDK-faithful aliases over the child-subsystem API.
    def GetNumWeapons(self) -> int:
        return self.GetNumChildSubsystems()

    def GetWeapon(self, i: int):
        return self.GetChildSubsystem(i)
```

Remove the old `_firing` attribute initialisation from `WeaponSystem.__init__` — `IsFiring` now derives from `_currently_firing`. Keep `_target`/`_weapon_system_type` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_weapon_system_sequential_firing.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Full unit suite regression check**

```
uv run pytest tests/unit/ -x
```

Expected: PASS. If any existing test asserts `WeaponSystem._firing == True` or `ws.IsFiring() == 1` after a bare `StartFiring()` call, those tests are now stale — Pass 4 emitter children + the cursor model is canonical. Update or remove them.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_weapon_system_sequential_firing.py
git commit -m "$(cat <<'EOF'
feat(weapons): sequential firing cursor on WeaponSystem

StartFiring picks the next eligible child emitter in round-robin
order and advances the cursor.  StopFiring halts whatever's firing.
IsFiring derives from the _currently_firing list, not a bare bool.
No-op when off, when no children exist, or when no child returns
CanFire()=1.  Matches Galaxy hardpoint's SetSingleFire(1) mode.

Multi-fire / firing-chain modes (dual/quad/all) deferred to a
future SDK fidelity PR — FiringChainString hardpoint field is
already accepted by the property catch-all.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `EnergyWeapon` Fire/CanFire/StopFiring/UpdateCharge + SFX

**Files:**
- Modify: `engine/appc/subsystems.py` (`PhaserBank`, `PulseWeapon`, `TractorBeam` ~lines 327-440)
- Create: `tests/unit/test_energy_weapon_gating.py`
- Create: `tests/unit/test_energy_weapon_update_charge.py`

Three energy emitters share gating + tick logic. To keep them DRY, add the new methods on a module-private mixin (`_EnergyWeaponFireMixin`) applied to all three. The existing `_init_energy_weapon_state` helper covers state; the new mixin covers behaviour.

### Steps

- [ ] **Step 1: Write failing tests for gating**

Create `tests/unit/test_energy_weapon_gating.py`:

```python
"""EnergyWeapon.Fire/CanFire/StopFiring — gates on (IsOn AND charge >=
MinFiringCharge).  Records target/offset, flips _firing, calls SFX.
Accepts target=None per spec (PR 2b's projectile fires forward).
"""
from unittest.mock import patch

from engine.appc.subsystems import PhaserBank, PulseWeapon, TractorBeam, PhaserSystem
from engine.appc.properties import PhaserProperty


def _charged_bank():
    bank = PhaserBank("Test")
    # Parent group provides IsOn(); attach to a turned-on system.
    parent = PhaserSystem("Phasers")
    parent.TurnOn()
    parent.AddChildSubsystem(bank)
    bank._max_charge = 5.0
    bank._min_firing_charge = 3.0
    bank._charge_level = 5.0
    return bank


def test_can_fire_true_when_charged_and_on():
    bank = _charged_bank()
    assert bank.CanFire() == 1


def test_can_fire_false_when_undercharged():
    bank = _charged_bank()
    bank._charge_level = 2.0  # below min_firing_charge
    assert bank.CanFire() == 0


def test_can_fire_false_when_parent_off():
    bank = _charged_bank()
    bank.GetParentSubsystem().TurnOff()
    assert bank.CanFire() == 0


def test_fire_sets_firing_flag():
    bank = _charged_bank()
    assert bank.IsFiring() == 0
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 1


def test_fire_records_target_and_offset():
    bank = _charged_bank()
    bank.Fire(target="enemy_ship", offset="hit_point")
    assert bank._target == "enemy_ship"
    assert bank._target_offset == "hit_point"


def test_fire_with_none_target_succeeds():
    """Spec: target=None is allowed; projectile fires along emitter +Y."""
    bank = _charged_bank()
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 1
    assert bank._target is None


def test_fire_no_ops_when_undercharged():
    bank = _charged_bank()
    bank._charge_level = 1.0
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 0


def test_fire_no_ops_when_off():
    bank = _charged_bank()
    bank.GetParentSubsystem().TurnOff()
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 0


def test_stop_firing_clears_flag():
    bank = _charged_bank()
    bank.Fire(target=None, offset=None)
    bank.StopFiring()
    assert bank.IsFiring() == 0


def test_fire_plays_start_sound():
    bank = _charged_bank()
    prop = PhaserProperty("Galaxy Phaser Hardpoint")
    prop.SetFireSound("Galaxy Phaser")
    bank.SetProperty(prop)

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        bank.Fire(target=None, offset=None)
        mock_mgr.return_value.PlaySound.assert_called_once_with("Galaxy Phaser Start")


def test_fire_falls_back_to_bare_name_when_no_start_variant():
    """Tractor uses SetFireSound("Tractor Beam") — LoadTacticalSounds
    registers it without the " Start" suffix.  Spec: try Start first,
    fall back to bare name."""
    beam = TractorBeam("Aft Tractor 1")
    parent = PhaserSystem("TractorParent")  # any WeaponSystem will do for IsOn()
    parent.TurnOn()
    parent.AddChildSubsystem(beam)
    beam._max_charge = 1.0
    beam._min_firing_charge = 0.5
    beam._charge_level = 1.0
    prop = PhaserProperty("Tractor Hardpoint")
    prop.SetFireSound("Tractor Beam")
    beam.SetProperty(prop)

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        # PlaySound returns None for unregistered names; the trigger should
        # try "Tractor Beam Start" first, then fall back to "Tractor Beam".
        def play(name):
            return None if "Start" in name else object()  # bare name "registered"
        mock_mgr.return_value.PlaySound.side_effect = play
        beam.Fire(target=None, offset=None)
        calls = [c.args[0] for c in mock_mgr.return_value.PlaySound.call_args_list]
        assert calls == ["Tractor Beam Start", "Tractor Beam"]


def test_fire_with_empty_fire_sound_no_sfx():
    """Empty FireSound (no hardpoint setter called): no SFX call attempts."""
    bank = _charged_bank()
    prop = PhaserProperty("No-Sound Hardpoint")
    # SetFireSound never called — default empty.
    bank.SetProperty(prop)

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        bank.Fire(target=None, offset=None)
        mock_mgr.return_value.PlaySound.assert_not_called()


def test_pulse_weapon_has_fire_surface():
    """PulseWeapon shares the gating with PhaserBank."""
    pulse = PulseWeapon("Forward Pulse")
    parent = PhaserSystem("PulseSystem")
    parent.TurnOn()
    parent.AddChildSubsystem(pulse)
    pulse._max_charge = 2.0
    pulse._min_firing_charge = 1.0
    pulse._charge_level = 2.0
    assert pulse.CanFire() == 1
    pulse.Fire(None, None)
    assert pulse.IsFiring() == 1
```

- [ ] **Step 2: Write failing tests for charge tick**

Create `tests/unit/test_energy_weapon_update_charge.py`:

```python
"""EnergyWeapon.UpdateCharge(dt): fills at _recharge_rate when on + idle,
drains at _normal_discharge_rate when firing, auto-stops at zero.
"""
from engine.appc.subsystems import PhaserBank, PhaserSystem


def _bank(on=True, charge=5.0, max_charge=5.0, recharge=0.5, discharge=1.0):
    bank = PhaserBank("Test")
    parent = PhaserSystem("Phasers")
    if on:
        parent.TurnOn()
    parent.AddChildSubsystem(bank)
    bank._max_charge = max_charge
    bank._min_firing_charge = 3.0
    bank._charge_level = charge
    bank._recharge_rate = recharge
    bank._normal_discharge_rate = discharge
    return bank


def test_update_charge_fills_when_on_and_idle():
    bank = _bank(on=True, charge=2.0, recharge=0.5)
    bank.UpdateCharge(dt=1.0)
    assert bank.GetChargeLevel() == 2.5


def test_update_charge_caps_at_max():
    bank = _bank(on=True, charge=4.5, recharge=0.5, max_charge=5.0)
    bank.UpdateCharge(dt=2.0)
    assert bank.GetChargeLevel() == 5.0


def test_update_charge_drains_when_firing():
    bank = _bank(on=True, charge=5.0, discharge=1.0)
    bank.Fire(target=None, offset=None)
    bank.UpdateCharge(dt=0.5)
    assert bank.GetChargeLevel() == 4.5


def test_update_charge_auto_stops_when_drained():
    bank = _bank(on=True, charge=1.0, discharge=2.0)
    bank.Fire(target=None, offset=None)
    bank.UpdateCharge(dt=1.0)
    assert bank.GetChargeLevel() == 0.0
    assert bank.IsFiring() == 0


def test_update_charge_holds_when_off_and_idle():
    """Spec: turning weapons off does NOT drain stored charge."""
    bank = _bank(on=False, charge=4.0, recharge=0.5)
    bank.UpdateCharge(dt=10.0)
    assert bank.GetChargeLevel() == 4.0


def test_update_charge_zero_dt_no_op():
    bank = _bank(on=True, charge=3.0)
    bank.UpdateCharge(dt=0.0)
    assert bank.GetChargeLevel() == 3.0
```

- [ ] **Step 3: Run tests to verify failures**

```
uv run pytest tests/unit/test_energy_weapon_gating.py tests/unit/test_energy_weapon_update_charge.py -v
```

Expected: All fail with `AttributeError: 'PhaserBank' object has no attribute 'Fire'` (etc.).

- [ ] **Step 4: Add the firing mixin + apply to energy emitters**

In `engine/appc/subsystems.py`, add a module-private helper near the existing `_init_energy_weapon_state` (around line 18):

```python
def _resolve_fire_sound(prop) -> str:
    """Returns the FireSound name (typed accessor) or empty string."""
    if prop is None or not hasattr(prop, "GetFireSound"):
        return ""
    return prop.GetFireSound() or ""


class _EnergyWeaponFireMixin:
    """Shared Fire/CanFire/StopFiring/UpdateCharge for PhaserBank / PulseWeapon
    / TractorBeam.  Per-emitter state initialised by _init_energy_weapon_state.
    Each class also has _firing (False at init), _target/_target_offset (None).

    SFX trigger looks up the property's FireSound name and asks TGSoundManager
    to play it.  Tries "<name> Start" first (phaser convention), falls back to
    bare "<name>" (tractor convention).  Names map to WAV assets via
    sdk/Build/scripts/LoadTacticalSounds.py invoked at audio init.
    """

    def CanFire(self) -> int:
        parent = self.GetParentSubsystem()
        on = parent is not None and parent.IsOn()
        charged = self._charge_level >= self._min_firing_charge
        return 1 if (on and charged) else 0

    def Fire(self, target=None, offset=None) -> None:
        if not self.CanFire():
            return
        self._firing = True
        self._target = target
        self._target_offset = offset
        self._play_fire_sfx()

    def StopFiring(self) -> None:
        self._firing = False

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def UpdateCharge(self, dt: float) -> None:
        if self._firing:
            self._charge_level = max(
                0.0, self._charge_level - self._normal_discharge_rate * dt
            )
            if self._charge_level <= 0.0:
                self._firing = False
        else:
            parent = self.GetParentSubsystem()
            if parent is not None and parent.IsOn():
                self._charge_level = min(
                    self._max_charge,
                    self._charge_level + self._recharge_rate * dt,
                )

    def _play_fire_sfx(self) -> None:
        name = _resolve_fire_sound(self.GetProperty())
        if not name:
            return
        from engine.audio.tg_sound import TGSoundManager
        mgr = TGSoundManager.instance()
        played = mgr.PlaySound(name + " Start")
        if played is None:
            mgr.PlaySound(name)
```

Then update each energy emitter class to use the mixin. Modify `PhaserBank` (around line 327):

```python
class PhaserBank(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual phaser emitter under a parent PhaserSystem
    (WeaponSystemProperty WST_PHASER).  Charge fields populated by Pass 4
    from the parent PhaserProperty (galaxy.py:209-214 for typical values).
    Inherits Fire/CanFire/StopFiring/UpdateCharge from the mixin.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def GetMaxCharge(self) -> float: return self._max_charge
    def GetMinFiringCharge(self) -> float: return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float: return self._normal_discharge_rate
    def GetRechargeRate(self) -> float: return self._recharge_rate
    def GetChargeLevel(self) -> float: return self._charge_level

    def GetChargePercentage(self) -> float:
        if self._max_charge <= 0.0:
            return 0.0
        return self._charge_level / self._max_charge

    def SetChargeLevel(self, v) -> None:
        v = float(v)
        if v < 0.0:                self._charge_level = 0.0
        elif v > self._max_charge: self._charge_level = self._max_charge
        else:                      self._charge_level = v
```

Apply the same mixin-first base-class pattern to `PulseWeapon` (around line 337) and `TractorBeam` (around line 343). For each, add the same `_firing/_target/_target_offset` init lines. Keep existing typed getters (`GetMaxCharge` etc.) — they're still needed for the property read-back tests from PR 1.

For `PulseWeapon`, keep its existing `_cooldown_time` field and `GetCooldownTime` getter.

- [ ] **Step 5: Run tests to verify pass**

```
uv run pytest tests/unit/test_energy_weapon_gating.py tests/unit/test_energy_weapon_update_charge.py -v
```

Expected: ALL PASS.

- [ ] **Step 6: Full unit suite regression check**

```
uv run pytest tests/unit/ -x
```

Expected: PASS. The sequential-firing tests from Task 3 still pass — the new `Fire`/`CanFire` on emitters satisfy the cursor logic's expectations.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_energy_weapon_gating.py tests/unit/test_energy_weapon_update_charge.py
git commit -m "$(cat <<'EOF'
feat(weapons): energy emitter Fire / CanFire / UpdateCharge

PhaserBank / PulseWeapon / TractorBeam share Fire / CanFire / StopFiring
/ UpdateCharge via _EnergyWeaponFireMixin.  CanFire gates on (parent on
AND charge >= MinFiringCharge); Fire flips _firing + records target +
plays SFX; UpdateCharge fills at _recharge_rate when idle and on, drains
at _normal_discharge_rate when firing, auto-stops at zero.

SFX trigger tries "<FireSound> Start" first (phaser registration in
LoadTacticalSounds), falls back to bare "<FireSound>" (tractor case).
Empty FireSound is a silent no-op.  Fire(target=None) is allowed — the
projectile renderer in PR 2b handles the no-target case by firing along
the emitter's local +Y in world space.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `TorpedoTube` Fire/CanFire/StopFiring/UpdateReload

**Files:**
- Modify: `engine/appc/subsystems.py` (`TorpedoTube` class ~line 349)
- Create: `tests/unit/test_torpedo_tube_fire.py`
- Create: `tests/unit/test_torpedo_tube_reload.py`

Torpedoes are discrete-shot: each `Fire` decrements `_num_ready` and immediately auto-stops (no continuous firing). Reload advances `_num_ready` after `_reload_delay` elapses since `_last_fire_time`. No SFX in PR 2a (deferred to PR 2b — needs `TorpedoAmmoType.GetLaunchSound()` modelling).

### Steps

- [ ] **Step 1: Write failing tests for Fire/CanFire**

Create `tests/unit/test_torpedo_tube_fire.py`:

```python
"""TorpedoTube.Fire — discrete shot. Decrements _num_ready, stamps
_last_fire_time, auto-stops _firing.  Gated on (parent on AND _num_ready > 0).
"""
from engine.appc.subsystems import TorpedoTube, TorpedoSystem


def _loaded_tube(num_ready=1, max_ready=1):
    tube = TorpedoTube("Forward Torpedo 1")
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent.AddChildSubsystem(tube)
    tube._max_ready = max_ready
    tube._num_ready = num_ready
    tube._reload_delay = 40.0
    return tube


def test_can_fire_true_when_loaded_and_on():
    tube = _loaded_tube()
    assert tube.CanFire() == 1


def test_can_fire_false_when_empty():
    tube = _loaded_tube(num_ready=0)
    assert tube.CanFire() == 0


def test_can_fire_false_when_parent_off():
    tube = _loaded_tube()
    tube.GetParentSubsystem().TurnOff()
    assert tube.CanFire() == 0


def test_fire_decrements_num_ready():
    tube = _loaded_tube(num_ready=1)
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0


def test_fire_records_target():
    tube = _loaded_tube()
    tube.Fire(target="enemy_ship", offset="hit_point")
    assert tube._target == "enemy_ship"
    assert tube._target_offset == "hit_point"


def test_fire_with_none_target_succeeds():
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0


def test_fire_auto_stops_firing():
    """Torpedoes are discrete-shot — _firing flips False immediately after
    the launch.  WeaponSystem.IsFiring() derives from _currently_firing
    which stays populated until StopFiring."""
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)
    assert tube.IsFiring() == 0


def test_fire_stamps_last_fire_time():
    import math
    tube = _loaded_tube()
    assert tube.GetLastFireTime() == -math.inf
    tube.Fire(target=None, offset=None)
    assert tube.GetLastFireTime() > -math.inf


def test_fire_no_ops_when_empty():
    tube = _loaded_tube(num_ready=0)
    import math
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0  # no underflow
    assert tube.GetLastFireTime() == -math.inf  # no fire-time update


def test_fire_no_sfx_in_pr2a():
    """Torpedo SFX deferred to PR 2b (needs TorpedoAmmoType.GetLaunchSound).
    PR 2a Fire must not crash even with no SFX path wired."""
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)  # must not raise
    assert tube.GetNumReady() == 0
```

- [ ] **Step 2: Write failing tests for UpdateReload**

Create `tests/unit/test_torpedo_tube_reload.py`:

```python
"""TorpedoTube.UpdateReload — advances _num_ready when reload elapses.
Caps at _max_ready.  Time source is time.monotonic().
"""
import time

from engine.appc.subsystems import TorpedoTube, TorpedoSystem


def _tube(num_ready=0, max_ready=1, reload_delay=40.0):
    tube = TorpedoTube("Forward Torpedo 1")
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent.AddChildSubsystem(tube)
    tube._max_ready = max_ready
    tube._num_ready = num_ready
    tube._reload_delay = reload_delay
    return tube


def test_update_reload_caps_at_max_ready():
    tube = _tube(num_ready=1, max_ready=1)
    tube.UpdateReload(dt=100.0)
    assert tube.GetNumReady() == 1


def test_update_reload_no_change_before_delay():
    tube = _tube(num_ready=0, max_ready=1, reload_delay=40.0)
    # Simulate firing now, then ask for an update at dt=0 (should not advance).
    tube._last_fire_time = time.monotonic()
    tube.UpdateReload(dt=0.1)
    assert tube.GetNumReady() == 0


def test_update_reload_advances_after_delay():
    tube = _tube(num_ready=0, max_ready=1, reload_delay=0.001)  # tiny delay for test
    tube._last_fire_time = time.monotonic() - 1.0  # >> reload_delay ago
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 1


def test_update_reload_resets_timer_after_each_increment():
    """A tube with multiple ready slots reloads them one at a time, each
    waiting reload_delay from the previous reload."""
    tube = _tube(num_ready=0, max_ready=2, reload_delay=0.001)
    # First reload triggers.
    tube._last_fire_time = time.monotonic() - 1.0
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 1
    first_reload_time = tube.GetLastFireTime()
    # Immediate second call — last_fire_time was just updated, not enough
    # has elapsed for the next slot.
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 1
    # Manually rewind last_fire_time to simulate another reload_delay passing.
    tube._last_fire_time = first_reload_time - 1.0
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 2
```

- [ ] **Step 3: Run tests to verify failures**

```
uv run pytest tests/unit/test_torpedo_tube_fire.py tests/unit/test_torpedo_tube_reload.py -v
```

Expected: All fail with `AttributeError: 'TorpedoTube' object has no attribute 'Fire'` (etc.).

- [ ] **Step 4: Add Fire / CanFire / StopFiring / UpdateReload to `TorpedoTube`**

In `engine/appc/subsystems.py`, find `class TorpedoTube(WeaponSystem)` (around line 349). Add to its `__init__`:

```python
        self._firing: bool = False
        self._target = None
        self._target_offset = None
```

And add these methods after the existing accessors:

```python
    def CanFire(self) -> int:
        parent = self.GetParentSubsystem()
        on = parent is not None and parent.IsOn()
        return 1 if (on and self._num_ready > 0) else 0

    def Fire(self, target=None, offset=None) -> None:
        if not self.CanFire():
            return
        self._firing = True
        self._target = target
        self._target_offset = offset
        self._num_ready -= 1
        import time as _time
        self._last_fire_time = _time.monotonic()
        # Discrete-shot — auto-stop after launch.  WeaponSystem's
        # _currently_firing list still tracks us until StopFiring is called.
        self._firing = False

    def StopFiring(self) -> None:
        self._firing = False

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def UpdateReload(self, dt: float) -> None:
        if self._num_ready >= self._max_ready:
            return
        import time as _time
        if _time.monotonic() - self._last_fire_time >= self._reload_delay:
            self._num_ready += 1
            self._last_fire_time = _time.monotonic()
```

- [ ] **Step 5: Run tests to verify pass**

```
uv run pytest tests/unit/test_torpedo_tube_fire.py tests/unit/test_torpedo_tube_reload.py -v
```

Expected: ALL PASS.

- [ ] **Step 6: Full unit suite regression check**

```
uv run pytest tests/unit/ -x
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_torpedo_tube_fire.py tests/unit/test_torpedo_tube_reload.py
git commit -m "$(cat <<'EOF'
feat(weapons): TorpedoTube discrete-shot Fire + UpdateReload

Fire decrements _num_ready, stamps _last_fire_time, auto-stops _firing
(torpedoes are one-shot per click — WeaponSystem.IsFiring derives from
_currently_firing which the parent's StopFiring clears).  Gated on
(parent on AND _num_ready > 0).  Target=None allowed; projectile
direction is PR 2b's problem.

UpdateReload advances _num_ready when reload_delay has elapsed since
_last_fire_time, then resets the timer so the next slot waits another
reload_delay.  Caps at _max_ready.

Torpedo SFX deferred to PR 2b — needs TorpedoAmmoType.GetLaunchSound()
which our ammo-type model doesn't yet support.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Input pipeline classes (TGBoolEvent + TGKeyboardEvent + TGInputManager + KeyboardBinding + TacticalControlWindow)

**Files:**
- Modify: `engine/appc/events.py` (add `TGBoolEvent`, `TGKeyboardEvent`, `ET_KEYBOARD_EVENT`)
- Create: `engine/appc/input.py` (`TGInputManager`, `KeyboardBinding`, constants, `register_input_handlers`)
- Create: `engine/appc/windows.py` (`TacticalControlWindow`)
- Modify: `App.py` (re-export new singletons/classes/constants)
- Create: `tests/unit/test_tg_input_manager.py`
- Create: `tests/unit/test_keyboard_binding.py`

### Steps

- [ ] **Step 1: Write failing tests for TGInputManager**

Create `tests/unit/test_tg_input_manager.py`:

```python
"""TGInputManager.RegisterUnicodeKey + OnKeyDown/OnKeyUp emit
TGKeyboardEvent into g_kEventManager.
"""
from engine.appc.events import TGEventManager
from engine.appc.input import (
    TGInputManager, WC_RBUTTON, KY_RBUTTON, KS_KEYDOWN, KS_KEYUP,
)


def _fresh_manager():
    em = TGEventManager()
    im = TGInputManager(em)
    return im, em


def test_register_unicode_key_records_mapping():
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_RBUTTON, KY_RBUTTON, None, "RButton")
    assert WC_RBUTTON in im._registered


def test_on_key_down_emits_event_for_registered_key():
    im, em = _fresh_manager()
    im.RegisterUnicodeKey(WC_RBUTTON, KY_RBUTTON, None, "RButton")
    received = []
    em.AddBroadcastPythonFuncHandler(
        em.ET_KEYBOARD_EVENT if hasattr(em, "ET_KEYBOARD_EVENT") else 1000,  # see Step 4
        None, "tests.unit.test_tg_input_manager._capture",
    )
    # Workaround: subscribe via a module-global since AddBroadcastPythonFuncHandler
    # resolves a string qualified name.
    global _CAPTURED
    _CAPTURED = received
    im.OnKeyDown(WC_RBUTTON)
    assert len(received) == 1
    evt = received[0]
    assert evt.GetUnicodeKey() == WC_RBUTTON
    assert evt.GetKeyState() == KS_KEYDOWN


def test_on_key_down_no_op_for_unregistered():
    im, em = _fresh_manager()
    received = []
    global _CAPTURED
    _CAPTURED = received
    em.AddBroadcastPythonFuncHandler(
        1000, None, "tests.unit.test_tg_input_manager._capture",
    )
    im.OnKeyDown(WC_RBUTTON)  # not registered
    assert received == []


def test_on_key_up_emits_keyup_event():
    im, em = _fresh_manager()
    im.RegisterUnicodeKey(WC_RBUTTON, KY_RBUTTON, None, "RButton")
    received = []
    global _CAPTURED
    _CAPTURED = received
    em.AddBroadcastPythonFuncHandler(
        1000, None, "tests.unit.test_tg_input_manager._capture",
    )
    im.OnKeyUp(WC_RBUTTON)
    assert received[0].GetKeyState() == KS_KEYUP


_CAPTURED: list = []


def _capture(_obj, evt):
    _CAPTURED.append(evt)
```

(Note: The capture-via-broadcast pattern routes through `g_kEventManager`'s string-resolution mechanism. The `ET_KEYBOARD_EVENT` constant value `1000` is a placeholder; Step 4 replaces it with the actual constant.)

- [ ] **Step 2: Write failing tests for KeyboardBinding**

Create `tests/unit/test_keyboard_binding.py`:

```python
"""KeyboardBinding.BindKey + OnKeyboardEvent — translate
(WC, KS) → (ET_*, value) and post the bound event via g_kEventManager.
"""
from engine.appc.events import TGEventManager, TGEventHandlerObject
from engine.appc.input import (
    KeyboardBinding, TGInputManager, TGKeyboardEvent,
    WC_RBUTTON, KS_KEYDOWN, KS_KEYUP,
)


# ET_INPUT_FIRE_SECONDARY value from sdk/Build/scripts/App.py constants
# (the integer value doesn't matter as long as the binding records it
# consistently; here we pick a recognisable test value).
_ET_INPUT_FIRE_SECONDARY = 2001


class _Dest(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self.received = []

    def ProcessEvent(self, evt):
        self.received.append(evt)


def test_bind_key_records_mapping():
    kb = KeyboardBinding(TGEventManager())
    kb.BindKey(WC_RBUTTON, KS_KEYDOWN, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 1)
    assert (WC_RBUTTON, KS_KEYDOWN) in kb._bindings


def test_on_keyboard_event_dispatches_bound_event():
    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)

    kb.BindKey(WC_RBUTTON, KS_KEYDOWN, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 1)

    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(WC_RBUTTON)
    evt.SetKeyState(KS_KEYDOWN)
    kb.OnKeyboardEvent(None, evt)

    assert len(dest.received) == 1
    out = dest.received[0]
    assert out.GetEventType() == _ET_INPUT_FIRE_SECONDARY
    assert out.GetBool() == 1  # GET_BOOL_EVENT with value=1


def test_keyup_routes_to_separate_binding():
    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)

    # DefaultKeyboardBinding pattern: KEYDOWN bool=1, KEYUP bool=0
    kb.BindKey(WC_RBUTTON, KS_KEYDOWN, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 1)
    kb.BindKey(WC_RBUTTON, KS_KEYUP, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 0)

    e1 = TGKeyboardEvent(); e1.SetUnicodeKey(WC_RBUTTON); e1.SetKeyState(KS_KEYDOWN)
    kb.OnKeyboardEvent(None, e1)
    e2 = TGKeyboardEvent(); e2.SetUnicodeKey(WC_RBUTTON); e2.SetKeyState(KS_KEYUP)
    kb.OnKeyboardEvent(None, e2)

    assert len(dest.received) == 2
    assert dest.received[0].GetBool() == 1
    assert dest.received[1].GetBool() == 0


def test_unbound_key_state_no_op():
    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)
    # No BindKey calls.
    evt = TGKeyboardEvent(); evt.SetUnicodeKey(WC_RBUTTON); evt.SetKeyState(KS_KEYDOWN)
    kb.OnKeyboardEvent(None, evt)
    assert dest.received == []
```

- [ ] **Step 3: Run tests to verify failures**

```
uv run pytest tests/unit/test_tg_input_manager.py tests/unit/test_keyboard_binding.py -v
```

Expected: ALL FAIL with `ModuleNotFoundError: No module named 'engine.appc.input'`.

- [ ] **Step 4: Add `TGBoolEvent` and `TGKeyboardEvent` to events.py**

In `engine/appc/events.py`, add this constant near the top:

```python
# Event type IDs.  SDK uses int constants in App.py; here we pick a stable
# value that won't collide with the SDK's ET_INPUT_FIRE_* range (those are
# Appc-side constants exposed via App.py:13834+).
ET_KEYBOARD_EVENT: int = 0x1000
```

Then add these classes after the existing `TGEvent` definition (around line 32):

```python
class TGBoolEvent(TGEvent):
    """Boolean-carrying event subclass.  Used by ET_INPUT_FIRE_* events to
    signal bFiring=1 (start) / bFiring=0 (stop).  See sdk/Build/scripts/
    TacticalInterfaceHandlers.py:391 — FireWeapons reads pEvent.GetBool()."""
    def __init__(self):
        super().__init__()
        self._value: int = 0

    def SetBool(self, v) -> None:
        self._value = 1 if v else 0

    def GetBool(self) -> int:
        return self._value


def TGBoolEvent_Create() -> TGBoolEvent:
    return TGBoolEvent()


class TGKeyboardEvent(TGEvent):
    """Carries a unicode key code + key state (KS_KEYDOWN / KS_KEYUP).
    Generated by g_kInputManager when a registered key transitions; consumed
    by g_kKeyboardBinding which translates it into ET_INPUT_FIRE_* events.
    """
    KS_KEYDOWN   = 0
    KS_KEYUP     = 1
    KS_KEYREPEAT = 2

    def __init__(self):
        super().__init__()
        self._event_type = ET_KEYBOARD_EVENT
        self._unicode_key: int = 0
        self._key_state: int = 0

    def SetUnicodeKey(self, k) -> None:
        self._unicode_key = int(k)

    def GetUnicodeKey(self) -> int:
        return self._unicode_key

    def SetKeyState(self, s) -> None:
        self._key_state = int(s)

    def GetKeyState(self) -> int:
        return self._key_state
```

- [ ] **Step 5: Create `engine/appc/input.py`**

Create the file with the input pipeline:

```python
"""SDK-faithful input pipeline shim.

Lays the g_kInputManager → TGKeyboardEvent → g_kKeyboardBinding → ET_*
chain that BC's input system uses.  Mission scripts that call
g_kKeyboardBinding.BindKey(...) (e.g. DefaultKeyboardBinding.py) work
unmodified once these classes are alive.
"""
from engine.core.ids import TGObject
from engine.appc.events import (
    TGBoolEvent, TGEvent, TGEventManager, TGKeyboardEvent, ET_KEYBOARD_EVENT,
)


# ── Constants — mirror SDK App.py keyboard constants ────────────────────────
WC_LBUTTON: int = 0x01
WC_RBUTTON: int = 0x02
WC_MBUTTON: int = 0x04
KY_LBUTTON: int = 0x01
KY_RBUTTON: int = 0x02
KY_MBUTTON: int = 0x04
KS_KEYDOWN   = TGKeyboardEvent.KS_KEYDOWN
KS_KEYUP     = TGKeyboardEvent.KS_KEYUP
KS_KEYREPEAT = TGKeyboardEvent.KS_KEYREPEAT


class TGInputManager(TGObject):
    """Receives host-side key/button events and emits TGKeyboardEvents
    into the event manager.  Registration table is populated by mission
    scripts (e.g. DefaultKeyboardBinding.RegisterUnicodeKeys)."""

    def __init__(self, event_manager: TGEventManager):
        super().__init__()
        self._event_manager = event_manager
        # {WC_code: (KY_code, database_ref, name)}
        self._registered: dict[int, tuple[int, object, str]] = {}

    def RegisterUnicodeKey(self, wc_code, ky_code, database, name) -> None:
        self._registered[int(wc_code)] = (int(ky_code), database, str(name))

    def OnKeyDown(self, wc_code: int) -> None:
        self._emit(int(wc_code), KS_KEYDOWN)

    def OnKeyUp(self, wc_code: int) -> None:
        self._emit(int(wc_code), KS_KEYUP)

    def _emit(self, wc_code: int, key_state: int) -> None:
        if wc_code not in self._registered:
            return
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(wc_code)
        evt.SetKeyState(key_state)
        self._event_manager.AddEvent(evt)


class KeyboardBinding(TGObject):
    """Translates (unicode_key, key_state) → (event_type, value) per
    registered bindings.  Posts the resulting event to the event manager
    with destination = the default destination (TacticalControlWindow)."""

    GET_BOOL_EVENT  = 1
    GET_INT_EVENT   = 2
    GET_FLOAT_EVENT = 3

    def __init__(self, event_manager: TGEventManager):
        super().__init__()
        self._event_manager = event_manager
        # {(wc_code, key_state): (event_type, flags, value)}
        self._bindings: dict[tuple[int, int], tuple[int, int, object]] = {}
        self._default_destination = None

    def SetDefaultDestination(self, dest) -> None:
        self._default_destination = dest

    def BindKey(self, wc_code, key_state, event_type, flags, value) -> None:
        self._bindings[(int(wc_code), int(key_state))] = (int(event_type), int(flags), value)

    def OnKeyboardEvent(self, _obj, evt: TGKeyboardEvent) -> None:
        key = (evt.GetUnicodeKey(), evt.GetKeyState())
        binding = self._bindings.get(key)
        if binding is None:
            return
        event_type, flags, value = binding
        out = self._build_event(event_type, flags, value)
        if self._default_destination is not None:
            out.SetDestination(self._default_destination)
        self._event_manager.AddEvent(out)

    def _build_event(self, event_type: int, flags: int, value) -> TGEvent:
        if flags == self.GET_BOOL_EVENT:
            ev = TGBoolEvent()
            ev.SetBool(value)
        else:
            # GET_INT_EVENT / GET_FLOAT_EVENT not used by ET_INPUT_FIRE_*;
            # add when a real consumer needs them.
            ev = TGEvent()
        ev.SetEventType(event_type)
        return ev


# ── Module-level singletons ─────────────────────────────────────────────────
g_kInputManager:    TGInputManager   | None = None
g_kKeyboardBinding: KeyboardBinding  | None = None


def register_input_handlers(event_manager: TGEventManager) -> None:
    """Wire KeyboardBinding.OnKeyboardEvent into the broadcast handler list.

    Must run AFTER g_kKeyboardBinding is initialised and AFTER App.py has
    re-exported g_kInputManager / g_kKeyboardBinding so qualified-name
    resolution works.
    """
    if g_kKeyboardBinding is None:
        return
    event_manager.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT,
        g_kKeyboardBinding,
        "engine.appc.input._OnKeyboardEvent_Dispatch",
    )


def _OnKeyboardEvent_Dispatch(obj, evt):
    """Trampoline so AddBroadcastPythonFuncHandler can resolve a qualified
    name and reach the singleton's bound method."""
    if g_kKeyboardBinding is not None:
        g_kKeyboardBinding.OnKeyboardEvent(obj, evt)


def init_input_pipeline(event_manager: TGEventManager) -> tuple[TGInputManager, KeyboardBinding]:
    """Initialise the singletons.  Called from host_loop bootstrap."""
    global g_kInputManager, g_kKeyboardBinding
    g_kInputManager   = TGInputManager(event_manager)
    g_kKeyboardBinding = KeyboardBinding(event_manager)
    return g_kInputManager, g_kKeyboardBinding
```

- [ ] **Step 6: Create `engine/appc/windows.py`**

Create:

```python
"""TacticalControlWindow placeholder.

Real BC TCW is a full window with menus / layout / focus.  PR 2a only
needs the event-handler-object surface so TacticalInterfaceHandlers.
RegisterHandlers(pTCW) can install fire-event handlers on it.  Future
PRs will replace this with the real window when the menu system lands.
"""
from engine.appc.events import TGEventHandlerObject


class TacticalControlWindow(TGEventHandlerObject):
    _instance: "TacticalControlWindow | None" = None

    @classmethod
    def GetInstance(cls) -> "TacticalControlWindow":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def CallNextHandler(self, _evt) -> None:
        """SDK handlers call pObject.CallNextHandler(pEvent) for chain
        propagation.  Without a parent window chain we no-op."""
        return None
```

- [ ] **Step 7: Re-export new symbols from App.py**

In project-root [App.py](App.py), add imports and module-level singletons. Find the existing imports from `engine.appc.*` (around line 8) and extend; then add singleton setup near where `g_kEventManager` is wired (around line 292).

```python
# Add to top imports:
from engine.appc.events import (
    TGBoolEvent, TGBoolEvent_Create,
    TGKeyboardEvent, ET_KEYBOARD_EVENT,
)
from engine.appc.input import (
    TGInputManager, KeyboardBinding,
    WC_LBUTTON, WC_RBUTTON, WC_MBUTTON,
    KY_LBUTTON, KY_RBUTTON, KY_MBUTTON,
    KS_KEYDOWN, KS_KEYUP, KS_KEYREPEAT,
    init_input_pipeline, register_input_handlers,
)
from engine.appc.windows import TacticalControlWindow

# Add to module body (after g_kEventManager = TGEventManager()):
g_kInputManager, g_kKeyboardBinding = init_input_pipeline(g_kEventManager)
register_input_handlers(g_kEventManager)

def TacticalControlWindow_GetTacticalControlWindow():
    return TacticalControlWindow.GetInstance()
```

- [ ] **Step 8: Run tests to verify pass**

```
uv run pytest tests/unit/test_tg_input_manager.py tests/unit/test_keyboard_binding.py -v
```

Expected: ALL PASS. If the broadcast-handler dispatch breaks due to qualified-name resolution, double-check that `engine.appc.input._OnKeyboardEvent_Dispatch` is reachable as a module attribute.

- [ ] **Step 9: Full unit suite regression check**

```
uv run pytest tests/unit/ -x
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add engine/appc/events.py engine/appc/input.py engine/appc/windows.py App.py \
        tests/unit/test_tg_input_manager.py tests/unit/test_keyboard_binding.py
git commit -m "$(cat <<'EOF'
feat(input): SDK-faithful input pipeline shim

TGKeyboardEvent + TGBoolEvent join the engine.appc.events hierarchy
(ET_KEYBOARD_EVENT=0x1000 reserved).  TGInputManager translates host
key/button events into TGKeyboardEvents; KeyboardBinding routes
(WC, KS) pairs to ET_INPUT_FIRE_* events with TGBoolEvent payloads.
TacticalControlWindow is a TGEventHandlerObject placeholder so
TacticalInterfaceHandlers.RegisterHandlers(pTCW) can install fire-
event handlers on it.

Mission scripts that call g_kKeyboardBinding.BindKey(...) (e.g.
DefaultKeyboardBinding.py) work unmodified once these classes are
alive — no shortcut, no input-system bypass.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Host mouse-button polling

**Files:**
- Modify: `native/src/renderer/include/renderer/window.h`
- Modify: `native/src/renderer/window.cc`
- Modify: `native/src/host/host_bindings.cc`

Add `Window::mouse_button_state(button)` mirroring `Window::key_state(key)`; expose `mouse_button_pressed(button)` / `mouse_button_released(button)` from the Python host with rising-edge / falling-edge detection. Plus `MOUSE_BUTTON_LEFT/RIGHT/MIDDLE` constants.

### Steps

- [ ] **Step 1: Add `mouse_button_state` to `Window` header**

In `native/src/renderer/include/renderer/window.h`, after the `key_state` declaration (around line 33), add:

```cpp
    /// Cached state of a GLFW mouse button (GLFW_MOUSE_BUTTON_*). Returns
    /// true while the button is held. State is updated by poll_events().
    bool mouse_button_state(int glfw_button) const noexcept;
```

- [ ] **Step 2: Implement in `window.cc`**

In `native/src/renderer/window.cc`, add the implementation (just after `key_state`):

```cpp
bool Window::mouse_button_state(int glfw_button) const noexcept {
    if (!handle_) return false;
    return glfwGetMouseButton(handle_, glfw_button) == GLFW_PRESS;
}
```

- [ ] **Step 3: Add Python bindings + GLFW constants**

In `native/src/host/host_bindings.cc`, after the existing `key_pressed` definition (around line 663):

```cpp
    // Mouse-button rising-edge detection.  Mirrors key_pressed pattern;
    // separate previous-state map keyed by GLFW button code.
    static std::unordered_map<int, bool> g_prev_mouse_state;

    m.def("mouse_button_pressed",
          [](int button) {
              if (!g_window) {
                  throw std::runtime_error("mouse_button_pressed: init must be called first");
              }
              const bool now = g_window->mouse_button_state(button);
              auto it = g_prev_mouse_state.find(button);
              const bool prev = (it != g_prev_mouse_state.end()) && it->second;
              if (it == g_prev_mouse_state.end()) {
                  g_prev_mouse_state[button] = now;
              }
              return now && !prev;
          },
          py::arg("button"),
          "Returns true on the first frame the mouse button is pressed (rising edge).");

    m.def("mouse_button_released",
          [](int button) {
              if (!g_window) {
                  throw std::runtime_error("mouse_button_released: init must be called first");
              }
              const bool now = g_window->mouse_button_state(button);
              auto it = g_prev_mouse_state.find(button);
              const bool prev = (it != g_prev_mouse_state.end()) && it->second;
              if (it == g_prev_mouse_state.end()) {
                  g_prev_mouse_state[button] = now;
              }
              return prev && !now;
          },
          py::arg("button"),
          "Returns true on the first frame the mouse button is released (falling edge).");
```

Then update the frame() pre-poll snapshot loop (around line 266) to also snapshot mouse buttons:

```cpp
    for (auto& [k, prev] : g_prev_key_state) {
        prev = (glfwGetKey(g_window->native_handle(), k) == GLFW_PRESS);
    }
    for (auto& [b, prev] : g_prev_mouse_state) {
        prev = (glfwGetMouseButton(g_window->native_handle(), b) == GLFW_PRESS);
    }
```

Add the GLFW constants near the existing `keys.attr("KEY_RIGHT")` block (around line 597):

```cpp
    keys.attr("MOUSE_BUTTON_LEFT")   = GLFW_MOUSE_BUTTON_LEFT;
    keys.attr("MOUSE_BUTTON_RIGHT")  = GLFW_MOUSE_BUTTON_RIGHT;
    keys.attr("MOUSE_BUTTON_MIDDLE") = GLFW_MOUSE_BUTTON_MIDDLE;
```

- [ ] **Step 4: Rebuild**

```
cmake -B build -S . && cmake --build build -j
```

Expected: build succeeds, `_open_stbc_host.so` re-links.

- [ ] **Step 5: Smoke-test the binding is reachable**

```
uv run python -c "
import open_stbc_host as h
print('mouse_button_pressed' in dir(h))
print('MOUSE_BUTTON_RIGHT' in dir(h.keys))
"
```

(Adjust import path to match how host bindings are exposed in this project — likely `from build.python import _open_stbc_host` or similar.)

Expected: `True` `True`.

If smoke import fails, check the build's `.so` is at `build/python/_open_stbc_host.cpython-*.so` per CLAUDE.md.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/window.h \
        native/src/renderer/window.cc \
        native/src/host/host_bindings.cc
git commit -m "$(cat <<'EOF'
feat(host): mouse_button_pressed / mouse_button_released bindings

Window.mouse_button_state(button) mirrors Window.key_state(key); host
exposes mouse_button_pressed(button) / mouse_button_released(button)
with rising-edge / falling-edge detection via a separate per-button
previous-state map.  GLFW_MOUSE_BUTTON_LEFT/RIGHT/MIDDLE constants
exposed alongside the existing KEY_* enum.

PR 2a's host_loop polls these each frame and forwards the events into
g_kInputManager.OnKeyDown / OnKeyUp.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: host_loop bootstrap + per-frame poll + per-frame weapon tick

**Files:**
- Modify: `engine/host_loop.py`

Wires the input pipeline at startup, polls mouse buttons each frame, and walks every ship's weapon emitters to advance charge / reload state.

### Steps

- [ ] **Step 1: Add the bootstrap block after init_audio**

In `engine/host_loop.py`, find the call to `init_audio()` (around line 1417). Immediately after, add the bootstrap:

```python
            init_audio()
            _bootstrap_firing_pipeline()
```

Then define `_bootstrap_firing_pipeline` near the top-level of the file (just below `init_audio`):

```python
def _bootstrap_firing_pipeline() -> None:
    """Bring up the SDK-faithful input chain and tactical-control window
    after audio is alive.  Registers the default keybindings + installs
    the TacticalInterfaceHandlers on the TCW + loads weapon SFX names.

    Idempotent: safe to call from a second mission load — DefaultKeyboard-
    Binding internally short-circuits when the input manager already has
    the keys registered.
    """
    import App

    # Default destination for fire events.
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)

    # Register the canonical key + binding tables.
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.RegisterUnicodeKeys()
    DefaultKeyboardBinding.RegisterBindings()

    # Wire TacticalInterfaceHandlers' fire-event handlers onto the TCW so
    # ET_INPUT_FIRE_PRIMARY / SECONDARY / TERTIARY route to FireWeapons.
    import TacticalInterfaceHandlers
    TacticalInterfaceHandlers.RegisterHandlers(tcw)

    # Load weapon SFX via the SDK's canonical sound script — no hard-coded
    # names anywhere in the engine.  "Galaxy Phaser Start"/"Loop", "Photon
    # Torpedo", "Tractor Beam", etc. all get registered with the file paths
    # the SDK script encodes.
    import LoadTacticalSounds
    LoadTacticalSounds.LoadSounds()
```

- [ ] **Step 2: Add per-frame mouse polling**

In the existing frame loop (find where keyboard polling lives — likely around the `_apply_alert_keys` call near line 1448), add the mouse-button forwarding:

```python
                _poll_mouse_buttons(_h)
```

And define `_poll_mouse_buttons`:

```python
def _poll_mouse_buttons(host) -> None:
    """Forward host-side mouse rising/falling edges into g_kInputManager.

    `host` is the bound _open_stbc_host module (or the equivalent _h handle
    used elsewhere in host_loop).  No-op when host doesn't expose the
    button-poll methods (e.g. headless test setup).
    """
    if host is None or not hasattr(host, "mouse_button_pressed"):
        return
    import App
    for glfw_btn, wc in (
        (host.keys.MOUSE_BUTTON_LEFT,   App.WC_LBUTTON),
        (host.keys.MOUSE_BUTTON_RIGHT,  App.WC_RBUTTON),
        (host.keys.MOUSE_BUTTON_MIDDLE, App.WC_MBUTTON),
    ):
        if host.mouse_button_pressed(glfw_btn):
            App.g_kInputManager.OnKeyDown(wc)
        if host.mouse_button_released(glfw_btn):
            App.g_kInputManager.OnKeyUp(wc)
```

(Adjust `host.keys.MOUSE_BUTTON_*` access if the host module exposes the constants differently — check what works in the rebuilt binding from Task 7.)

- [ ] **Step 3: Add per-frame weapon tick**

Define `_advance_weapons` at module scope:

```python
def _advance_weapons(ships, dt: float) -> None:
    """Per-frame charge / reload advancement for every weapon emitter.

    Walks all ships × all four weapon groups × all child emitters and
    calls UpdateCharge (energy) or UpdateReload (torpedo).  AI ships are
    included — their AI scripts call StartFiring expecting charged
    emitters, same as the player.
    """
    from engine.appc.subsystems import TorpedoTube
    for ship in ships:
        for group in (
            ship.GetPhaserSystem(),
            ship.GetPulseWeaponSystem(),
            ship.GetTractorBeamSystem(),
            ship.GetTorpedoSystem(),
        ):
            if group is None:
                continue
            for i in range(group.GetNumWeapons()):
                emitter = group.GetWeapon(i)
                if emitter is None:
                    continue
                if hasattr(emitter, "UpdateCharge"):
                    emitter.UpdateCharge(dt)
                if isinstance(emitter, TorpedoTube):
                    emitter.UpdateReload(dt)
```

Wire it into the frame loop just after physics/AI but before render (find the existing per-frame loop, look for where ship physics updates run). The call:

```python
                _advance_weapons(_all_ships_for_tick(), dt)
```

Define `_all_ships_for_tick`:

```python
def _all_ships_for_tick():
    """Iterator over every ship the per-frame weapon tick should advance.

    Mirrors the iteration pattern engine_rumble uses (see
    engine.audio.engine_rumble.update_positions) — walks the active Sets
    via App.g_kSetManager.
    """
    import App
    sm = getattr(App, "g_kSetManager", None)
    if sm is None:
        return iter(())
    # Use the same enumeration that engine_rumble relies on; fall back to
    # the player set if that's all that's wired in headless tests.
    try:
        return iter(sm.GetAllShips())
    except AttributeError:
        # Headless setups may not expose GetAllShips — find by walking the
        # current mission's known sets.
        pset = sm.GetSet("bridge") if hasattr(sm, "GetSet") else None
        if pset is None:
            return iter(())
        return iter([pset])
```

(If `g_kSetManager.GetAllShips` doesn't exist in our shim, look at what `engine.audio.engine_rumble.update_positions` actually uses to walk ships, and copy that pattern. The key requirement: every ship that has weapon groups gets its emitters ticked.)

- [ ] **Step 4: Run existing unit suite**

```
uv run pytest tests/unit/ -x
```

Expected: PASS — no new tests yet, but the host_loop module must still import cleanly. If `import LoadTacticalSounds` fails in a headless test environment (no `_h.LoadSound` callable), guard the bootstrap call behind `if _h is not None:` or similar.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "$(cat <<'EOF'
feat(host_loop): bootstrap firing pipeline + per-frame weapon tick

After init_audio(), call _bootstrap_firing_pipeline() to register the
DefaultKeyboardBinding key + binding tables, install TacticalInterface-
Handlers on TacticalControlWindow, and invoke LoadTacticalSounds.
LoadSounds() so weapon SFX names resolve.

Per frame: _poll_mouse_buttons() forwards rising/falling edges via
g_kInputManager.OnKeyDown / OnKeyUp.  _advance_weapons() walks every
ship × every weapon group × every emitter and calls UpdateCharge /
UpdateReload.  AI ships included — they fire on the same gating.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: End-to-end integration tests

**Files:**
- Create: `tests/integration/test_fire_secondary_chain.py`
- Create: `tests/integration/test_fire_primary_continuous.py`
- Create: `tests/integration/test_fire_gated_by_alert.py`
- Create: `tests/integration/test_sequential_firing_galaxy.py`

These exercise the entire chain from `OnKeyDown(WC_RBUTTON)` to the runtime emitter flipping `_firing = True` (with mocked TGSoundManager so SFX assertions don't depend on audio).

### Steps

- [ ] **Step 1: Write test_fire_secondary_chain.py**

Create `tests/integration/test_fire_secondary_chain.py`:

```python
"""End-to-end: post OnKeyDown(WC_RBUTTON) via g_kInputManager and assert
the entire chain runs through to one Galaxy torpedo tube firing.

Mocks TGSoundManager so the test doesn't depend on a live audio engine.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create


@pytest.fixture
def galaxy_in_red_alert():
    """Load Galaxy hardpoint, wire input pipeline if it isn't already,
    return a ship at RED alert."""
    ship = ShipClass_Create("Galaxy")

    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()

    # Set this ship as the current player so FireWeapons can find it.
    App.Game_GetCurrentPlayer = lambda: ship
    # Register tactical handlers on the TCW (idempotent — host_loop bootstrap
    # would normally do this, but tests start cold).
    import TacticalInterfaceHandlers
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    TacticalInterfaceHandlers.RegisterHandlers(tcw)
    # Register the binding so WC_RBUTTON keydown maps to ET_INPUT_FIRE_SECONDARY.
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.RegisterUnicodeKeys()
    DefaultKeyboardBinding.RegisterBindings()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)

    ship.SetAlertLevel(ShipClass.RED_ALERT)

    yield ship

    # Teardown — keep the property manager / module cache clean.
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def test_right_click_fires_torpedo(galaxy_in_red_alert):
    ship = galaxy_in_red_alert
    torps = ship.GetTorpedoSystem()
    initial_ready = sum(
        torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())
    )

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    # Exactly one torpedo was fired.
    final_ready = sum(
        torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())
    )
    assert final_ready == initial_ready - 1


def test_right_click_at_green_alert_does_nothing(galaxy_in_red_alert):
    ship = galaxy_in_red_alert
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    torps = ship.GetTorpedoSystem()
    initial = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    final = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]
    assert final == initial
```

- [ ] **Step 2: Write test_fire_primary_continuous.py**

Create `tests/integration/test_fire_primary_continuous.py`:

```python
"""End-to-end continuous fire: hold LBUTTON, run the tick loop, assert
the active phaser bank's charge drains.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.host_loop import _advance_weapons


@pytest.fixture
def galaxy_in_red_alert():
    """Same setup as test_fire_secondary_chain."""
    ship = ShipClass_Create("Galaxy")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()

    App.Game_GetCurrentPlayer = lambda: ship
    import TacticalInterfaceHandlers
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    TacticalInterfaceHandlers.RegisterHandlers(tcw)
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.RegisterUnicodeKeys()
    DefaultKeyboardBinding.RegisterBindings()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    ship.SetAlertLevel(ShipClass.RED_ALERT)

    yield ship
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def test_holding_left_button_drains_phaser_charge(galaxy_in_red_alert):
    ship = galaxy_in_red_alert
    phasers = ship.GetPhaserSystem()

    # All banks start at MaxCharge=5.0.
    starting = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    assert all(c == 5.0 for c in starting)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        # Simulate 10 frames at dt=0.1 each (NormalDischargeRate=1.0).
        for _ in range(10):
            _advance_weapons([ship], dt=0.1)

    # One bank should have drained noticeably.
    after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    drained = [i for i, c in enumerate(after) if c < 5.0]
    assert len(drained) == 1
    # Drained by ~1.0 charge (1.0/s × 1.0s total).  Allow for the recharge
    # offset that triggers when _firing is True but charge=0 auto-stops.
    assert 3.5 < after[drained[0]] < 4.5


def test_release_left_button_stops_phaser(galaxy_in_red_alert):
    ship = galaxy_in_red_alert
    phasers = ship.GetPhaserSystem()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        for _ in range(5):
            _advance_weapons([ship], dt=0.1)
        # Snapshot mid-fire charge.
        mid = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
        App.g_kInputManager.OnKeyUp(App.WC_LBUTTON)
        # Now run more frames — charge should recover, not drain.
        for _ in range(5):
            _advance_weapons([ship], dt=0.1)
        after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
        # The previously-firing bank should now be recharging (higher than mid).
        firing_bank_idx = next(i for i in range(len(mid)) if mid[i] < 5.0)
        assert after[firing_bank_idx] >= mid[firing_bank_idx]
```

- [ ] **Step 3: Write test_fire_gated_by_alert.py**

Create `tests/integration/test_fire_gated_by_alert.py`:

```python
"""End-to-end gating: same Galaxy + LBUTTON sequence at GREEN alert
should not drain any charge, not flip any bank to firing, not call SFX.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.host_loop import _advance_weapons


@pytest.fixture
def galaxy_at_green_alert():
    ship = ShipClass_Create("Galaxy")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()

    App.Game_GetCurrentPlayer = lambda: ship
    import TacticalInterfaceHandlers
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    TacticalInterfaceHandlers.RegisterHandlers(tcw)
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.RegisterUnicodeKeys()
    DefaultKeyboardBinding.RegisterBindings()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    yield ship
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def test_left_click_at_green_does_not_drain_charge(galaxy_at_green_alert):
    ship = galaxy_at_green_alert
    phasers = ship.GetPhaserSystem()
    starting = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        for _ in range(10):
            _advance_weapons([ship], dt=0.1)
        mock_mgr.return_value.PlaySound.assert_not_called()

    after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    assert after == starting  # no change


def test_right_click_at_green_does_not_decrement_torpedoes(galaxy_at_green_alert):
    ship = galaxy_at_green_alert
    torps = ship.GetTorpedoSystem()
    starting = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]
    assert after == starting
```

- [ ] **Step 4: Write test_sequential_firing_galaxy.py**

Create `tests/integration/test_sequential_firing_galaxy.py`:

```python
"""End-to-end sequential firing: 6 right-clicks at RED → each fires from
a different tube; 7th click cycles back to tube 0.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create


@pytest.fixture
def galaxy_red():
    ship = ShipClass_Create("Galaxy")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()

    App.Game_GetCurrentPlayer = lambda: ship
    import TacticalInterfaceHandlers
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    TacticalInterfaceHandlers.RegisterHandlers(tcw)
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.RegisterUnicodeKeys()
    DefaultKeyboardBinding.RegisterBindings()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    ship.SetAlertLevel(ShipClass.RED_ALERT)

    yield ship
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def test_six_right_clicks_fire_six_tubes(galaxy_red):
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    assert torps.GetNumWeapons() == 6
    initial = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert all(n == 1 for n in initial)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(6):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert after == [0, 0, 0, 0, 0, 0]


def test_seventh_click_wraps_cursor(galaxy_red):
    """Seventh right-click at RED alert tries to fire from tube 0 which is
    now empty.  Since no tube is reloaded yet, the WeaponSystem cursor
    looks for any eligible tube and finds none → silent no-op."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(6):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        after_6 = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
        # 7th click — all tubes empty.
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        after_7 = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert after_6 == after_7  # no change — silent no-op
```

- [ ] **Step 5: Run the integration suite**

```
uv run pytest tests/integration/ -v
```

Expected: ALL PASS. Watch for chain-breaks: if any step in the chain (input manager, binding, TCW, FireWeapons handler) silently no-ops, the assertion at the end of the test will fail and the traceback won't pin the bad link. Add `print()` statements at suspicious link points if debugging is needed; remove before committing.

- [ ] **Step 6: Full suite regression check**

```
uv run pytest tests/ -x
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_fire_secondary_chain.py \
        tests/integration/test_fire_primary_continuous.py \
        tests/integration/test_fire_gated_by_alert.py \
        tests/integration/test_sequential_firing_galaxy.py
git commit -m "$(cat <<'EOF'
test(weapons): end-to-end firing chain integration tests

Posts OnKeyDown via g_kInputManager and asserts the entire chain
(InputManager → KeyboardBinding → ET_INPUT_FIRE_* → TCW → Tactical-
InterfaceHandlers → FireWeapons → group.StartFiring → emitter.Fire)
fires exactly one torpedo / drains exactly one phaser bank's charge
and respects alert-level gating.

Sequential firing verified: 6 right-clicks empty all 6 Galaxy tubes
in turn; 7th click is a silent no-op (no eligible emitter).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| PoweredSubsystem TurnOn/TurnOff/IsOn + percent-wanted | Task 1 |
| ShipClass.SetAlertLevel → power policy | Task 1 |
| EnergyWeaponProperty.GetFireSound typed | Task 2 |
| WeaponSystem sequential cursor | Task 3 |
| EnergyWeapon Fire/CanFire/StopFiring + UpdateCharge | Task 4 |
| TorpedoTube Fire/CanFire/StopFiring + UpdateReload | Task 5 |
| SFX trigger (Start + fallback) | Task 4 |
| TorpedoTube no-SFX (deferred) | Task 5 commit note |
| TGBoolEvent + TGKeyboardEvent + ET_KEYBOARD_EVENT | Task 6 |
| TGInputManager | Task 6 |
| KeyboardBinding | Task 6 |
| TacticalControlWindow placeholder | Task 6 |
| Input constants (WC/KY/KS) | Task 6 |
| Host mouse-button polling | Task 7 |
| Host_loop bootstrap (DefaultKeyboardBinding + RegisterHandlers + LoadTacticalSounds) | Task 8 |
| Host_loop per-frame mouse poll | Task 8 |
| Host_loop per-frame `_advance_weapons` tick | Task 8 |
| End-to-end Galaxy + RED + right-click | Task 9 |
| Gating by alert | Task 9 |
| Sequential firing exhaustion | Task 9 |
| Manual verification | Not a task — spec describes; user runs after merge |

No gaps.

**Placeholder scan:** No TBD/TODO/FIXME in code blocks. Some narrative comments reference future PR work ("PR 2b adds Loop transition") — those are forward references, not placeholders.

**Type consistency:**
- `_max_charge` / `_charge_level` / `_min_firing_charge` etc. — Task 4 reads, Task 1 (via Pass 4 from PR 1) sets. Names match across files.
- `_num_ready` / `_max_ready` / `_last_fire_time` — Task 5 reads, PR 1's Pass 4 sets. Names match.
- `IsOn()` / `TurnOn()` / `TurnOff()` — defined on PoweredSubsystem (Task 1), called from WeaponSystem.StartFiring (Task 3) and emitter.CanFire (Task 4/5). Signatures match.
- `Fire(target, offset)` / `StopFiring()` / `CanFire() -> int` — same signature across Tasks 3-5.
- `OnKeyDown(wc_code)` / `OnKeyUp(wc_code)` — same signature in Task 6 (definition) and Task 8 (caller).
- `App.WC_LBUTTON` / `App.WC_RBUTTON` etc. — exported in Task 6, consumed in Task 8 + integration tests.
- `App.g_kInputManager` / `App.g_kKeyboardBinding` / `App.TacticalControlWindow_GetTacticalControlWindow()` — exported in Task 6, consumed in Task 8 + integration tests.

Names and signatures consistent across the plan.
