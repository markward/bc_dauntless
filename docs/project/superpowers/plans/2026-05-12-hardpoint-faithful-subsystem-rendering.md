# Hardpoint-Faithful Subsystem Rendering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the targets-panel subsystem list mirror what the hardpoint registered — same set, same names, same parent/child structure. Adds child-emitter storage to `ShipSubsystem`, four new child weapon classes, two new top-level subsystems (Power, Repair), a new `SetupProperties` pass that materialises children, label propagation from hardpoint names, and a UI controller that nests children under their parent.

**Architecture:** Twelve TDD tasks, all Python-only. Engine internals (subsystems.py, ships.py) first, then UI (target_list.py), then an end-to-end integration probe against the drydock hardpoint. Each task lands a coherent slice with a passing test and a commit.

**Tech Stack:** Python 3, pytest. SDK scripts load via `tools/mission_harness._SDKFinder`. No native changes.

**Spec:** [docs/project/superpowers/specs/2026-05-12-hardpoint-faithful-subsystem-rendering-design.md](../specs/2026-05-12-hardpoint-faithful-subsystem-rendering-design.md).

---

## Task 1: ShipSubsystem child storage

**Files:**
- Modify: [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) — replace stubs at lines 138–147 and add `AddChildSubsystem`; add `_children` to `__init__`
- Test: [tests/unit/test_subsystem_children.py](../../../tests/unit/test_subsystem_children.py) — new file

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_subsystem_children.py`:

```python
"""ShipSubsystem child-list storage — replaces the always-0/None stubs.

SDK semantics (App.py:5645+): subsystems form a parent/child tree.
WeaponSystemProperty(WST_TRACTOR) is the parent; each TractorBeamProperty
is a child.  AddChildSubsystem appends and sets the parent back-ref;
GetChildSubsystem(index|name|None) is the SDK-compatible getter.
"""
from engine.appc.subsystems import ShipSubsystem


def test_new_subsystem_has_no_children():
    s = ShipSubsystem("parent")
    assert s.GetNumChildSubsystems() == 0


def test_add_child_appends_and_counts():
    parent = ShipSubsystem("parent")
    a = ShipSubsystem("a")
    b = ShipSubsystem("b")
    parent.AddChildSubsystem(a)
    parent.AddChildSubsystem(b)
    assert parent.GetNumChildSubsystems() == 2


def test_add_child_sets_parent_back_reference():
    parent = ShipSubsystem("parent")
    child = ShipSubsystem("child")
    parent.AddChildSubsystem(child)
    assert child.GetParentSubsystem() is parent


def test_get_child_by_index_returns_child():
    parent = ShipSubsystem("parent")
    a = ShipSubsystem("a")
    b = ShipSubsystem("b")
    parent.AddChildSubsystem(a)
    parent.AddChildSubsystem(b)
    assert parent.GetChildSubsystem(0) is a
    assert parent.GetChildSubsystem(1) is b


def test_get_child_out_of_range_returns_none():
    parent = ShipSubsystem("parent")
    parent.AddChildSubsystem(ShipSubsystem("a"))
    assert parent.GetChildSubsystem(5) is None
    assert parent.GetChildSubsystem(-1) is None


def test_get_child_by_name_returns_matching_child():
    parent = ShipSubsystem("parent")
    a = ShipSubsystem("Aft Tractor 1")
    b = ShipSubsystem("Forward Tractor 1")
    parent.AddChildSubsystem(a)
    parent.AddChildSubsystem(b)
    assert parent.GetChildSubsystem("Forward Tractor 1") is b


def test_get_child_by_name_unknown_returns_none():
    parent = ShipSubsystem("parent")
    parent.AddChildSubsystem(ShipSubsystem("a"))
    assert parent.GetChildSubsystem("unknown") is None


def test_get_child_no_arg_returns_none_for_backwards_compat():
    """The original stub took no arguments and returned None; some SDK
    iterators rely on the zero-arg overload."""
    parent = ShipSubsystem("parent")
    parent.AddChildSubsystem(ShipSubsystem("a"))
    assert parent.GetChildSubsystem() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_subsystem_children.py -v`

Expected: FAIL — `AddChildSubsystem` does not exist, `GetNumChildSubsystems()` returns 0 (passes for the first test) but `GetChildSubsystem(0)` returns `None` not the appended child.

- [ ] **Step 3: Replace stubs in `engine/appc/subsystems.py`**

In `ShipSubsystem.__init__` (around line 22), add `_children` after the other underscored fields:

```python
        self._children: list["ShipSubsystem"] = []
```

Replace the existing block at [engine/appc/subsystems.py:138-147](../../../engine/appc/subsystems.py#L138-L147):

```python
    # ── Child-subsystem walking ──────────────────────────────────────────────
    # SDK consumers iterate child subsystems via GetNumChildSubsystems +
    # GetChildSubsystem(i) (e.g. E2M2 PrepMarauder, E5M2 CreateGeronimo).
    # Hardpoints register TractorBeamProperty etc. as children of the parent
    # WeaponSystemProperty; SetupProperties Pass 4 materialises live children
    # from those property templates.

    def GetNumChildSubsystems(self) -> int:
        return len(self._children)

    def GetChildSubsystem(self, arg=None):
        if arg is None:
            return None
        if isinstance(arg, int):
            if 0 <= arg < len(self._children):
                return self._children[arg]
            return None
        if isinstance(arg, str):
            for c in self._children:
                if c.GetName() == arg:
                    return c
            return None
        return None

    def AddChildSubsystem(self, sub: "ShipSubsystem") -> None:
        sub._parent_subsystem = self
        self._children.append(sub)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_subsystem_children.py -v`

Expected: PASS, 8 tests.

- [ ] **Step 5: Run full unit suite to catch regressions**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit tests/integration -q`

Expected: PASS — the original stubs returned `0`/`None`, and the new implementation returns the same when `_children` is empty (every existing subsystem). No callers should observe a change.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_subsystem_children.py engine/appc/subsystems.py
git commit -m "$(cat <<'EOF'
feat(subsystems): real ShipSubsystem._children storage + AddChildSubsystem

Replaces the always-0/None GetNumChildSubsystems / GetChildSubsystem
stubs with a real list-backed implementation.  AddChildSubsystem sets
the parent back-ref and appends.  Behaviour for empty _children is
identical to the prior stubs — no existing caller observes a change.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Live child weapon classes

**Files:**
- Modify: [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) — add classes below `TractorBeamSystem`
- Test: [tests/unit/test_child_weapon_classes.py](../../../tests/unit/test_child_weapon_classes.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""PhaserBank, PulseWeapon, TractorBeam, TorpedoTube — live child classes.

Each one is a per-hardpoint weapon emitter that hangs under the matching
parent WeaponSystem.  All subclass WeaponSystem so they inherit firing
state, target, and the SetProperty back-ref; fields will be added as
SDK callers demand.
"""
from engine.appc.subsystems import (
    WeaponSystem, PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
)


def test_phaser_bank_is_weapon_system():
    bank = PhaserBank("Forward Phaser 1")
    assert isinstance(bank, WeaponSystem)
    assert bank.GetName() == "Forward Phaser 1"


def test_pulse_weapon_is_weapon_system():
    pw = PulseWeapon("Forward Pulse")
    assert isinstance(pw, WeaponSystem)
    assert pw.GetName() == "Forward Pulse"


def test_tractor_beam_is_weapon_system():
    tb = TractorBeam("Aft Tractor 1")
    assert isinstance(tb, WeaponSystem)
    assert tb.GetName() == "Aft Tractor 1"


def test_torpedo_tube_is_weapon_system():
    tt = TorpedoTube("Forward Torpedo 1")
    assert isinstance(tt, WeaponSystem)
    assert tt.GetName() == "Forward Torpedo 1"


def test_child_weapon_inherits_property_back_reference():
    from engine.appc.properties import TractorBeamProperty
    tb = TractorBeam("Aft Tractor 1")
    p = TractorBeamProperty("Aft Tractor 1")
    tb.SetProperty(p)
    assert tb.GetProperty() is p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_child_weapon_classes.py -v`

Expected: FAIL — `ImportError: cannot import name 'PhaserBank'`.

- [ ] **Step 3: Add the four classes**

Append to `engine/appc/subsystems.py` after the existing `TractorBeamSystem` class (around line 306):

```python
class PhaserBank(WeaponSystem):
    """Individual phaser emitter.  Hangs under a parent PhaserSystem
    (WeaponSystemProperty WST_PHASER).  SDK App.py: EnergyWeapon subclass.

    Fields are inherited from WeaponSystem; per-bank specialisation is
    added when SDK callers prove they need it.
    """
    pass


class PulseWeapon(WeaponSystem):
    """Individual pulse-weapon emitter under a parent PulseWeaponSystem
    (WeaponSystemProperty WST_PULSE)."""
    pass


class TractorBeam(WeaponSystem):
    """Individual tractor-beam emitter under a parent TractorBeamSystem
    (WeaponSystemProperty WST_TRACTOR)."""
    pass


class TorpedoTube(WeaponSystem):
    """Individual launcher under a parent TorpedoSystem.  Ammo tracking
    lives on the parent's slot table (SDK-compatible: SetAmmoType(slot, type)
    indexes by integer, not by tube reference)."""
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_child_weapon_classes.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_child_weapon_classes.py engine/appc/subsystems.py
git commit -m "$(cat <<'EOF'
feat(subsystems): PhaserBank / PulseWeapon / TractorBeam / TorpedoTube

Four live child-weapon classes.  Each subclasses WeaponSystem so it
inherits firing state, target, and SetProperty back-ref.  They hang
under the matching parent WeaponSystem* slot via AddChildSubsystem in
Pass 4 of SetupProperties (separate commit).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: PowerSubsystem and RepairSubsystem live classes

**Files:**
- Modify: [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) — add classes below `ShieldSubsystem`
- Test: [tests/unit/test_power_repair_subsystems.py](../../../tests/unit/test_power_repair_subsystems.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""PowerSubsystem + RepairSubsystem — top-level subsystems missing from
the panel today because SetupProperties had no handler for their property
templates.  Inheritance matches SDK App.py:5710 (PowerSubsystem :
ShipSubsystem — not powered) and SDK App.py:6639 (RepairSubsystem :
PoweredSubsystem)."""
from engine.appc.subsystems import (
    ShipSubsystem, PoweredSubsystem, PowerSubsystem, RepairSubsystem,
)


def test_power_subsystem_inherits_ship_subsystem():
    p = PowerSubsystem("Power Plant")
    assert isinstance(p, ShipSubsystem)
    # NOT a PoweredSubsystem — it generates power rather than consuming it.
    assert not isinstance(p, PoweredSubsystem)
    assert p.GetName() == "Power Plant"


def test_repair_subsystem_inherits_powered_subsystem():
    r = RepairSubsystem("Engineering")
    assert isinstance(r, PoweredSubsystem)
    assert r.GetName() == "Engineering"


def test_power_subsystem_property_back_reference():
    from engine.appc.properties import PowerProperty
    p = PowerSubsystem("Power Plant")
    pp = PowerProperty("Power Plant")
    p.SetProperty(pp)
    assert p.GetProperty() is pp


def test_repair_subsystem_property_back_reference():
    from engine.appc.properties import RepairSubsystemProperty
    r = RepairSubsystem("Engineering")
    rp = RepairSubsystemProperty("Engineering")
    r.SetProperty(rp)
    assert r.GetProperty() is rp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_power_repair_subsystems.py -v`

Expected: FAIL — `ImportError: cannot import name 'PowerSubsystem'`.

- [ ] **Step 3: Add the two classes**

Append to `engine/appc/subsystems.py` after `ShieldSubsystem` (around line 475, before the module-level warp helpers):

```python
class PowerSubsystem(ShipSubsystem):
    """Power plant — drives the ship's energy budget.

    Inherits ShipSubsystem (not PoweredSubsystem) to match SDK
    App.py:5710 where PowerSubsystem inherits ShipSubsystem directly.
    It generates power rather than consuming it.
    """
    pass


class RepairSubsystem(PoweredSubsystem):
    """Engineering / damage-control subsystem.  SDK App.py:6639 has
    RepairSubsystem(PoweredSubsystem) with internal repair-allocation
    state; Phase 1 ships only need the slot + property back-ref so the
    targets panel reflects the hardpoint."""
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_power_repair_subsystems.py -v`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_power_repair_subsystems.py engine/appc/subsystems.py
git commit -m "$(cat <<'EOF'
feat(subsystems): PowerSubsystem + RepairSubsystem live classes

Two top-level subsystems the drydock hardpoint registers
(PowerProperty 'Power Plant', RepairSubsystemProperty 'Engineering')
that SetupProperties currently drops on the floor.  Inheritance matches
SDK App.py:5710 / 6639: Power is ShipSubsystem, Repair is
PoweredSubsystem.  Slot wiring + SetupProperties handlers land in
subsequent tasks.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ShipClass slots for Power + Repair

**Files:**
- Modify: [engine/appc/ships.py](../../../engine/appc/ships.py) — add slot fields, accessors, ShipClass_Create preallocation, Pass 3 enumeration
- Test: [tests/unit/test_ship_power_repair_slots.py](../../../tests/unit/test_ship_power_repair_slots.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""ShipClass exposes _power_subsystem and _repair_subsystem slots
with the same Get/Set + pre-allocation + Pass 3 scrub pattern as the
existing eight."""
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (
    PowerSubsystem, RepairSubsystem,
)


def test_ship_class_create_preallocates_power():
    ship = ShipClass_Create("blank")
    assert isinstance(ship.GetPowerSubsystem(), PowerSubsystem)
    assert ship.GetPowerSubsystem().GetName() == "Power Plant"


def test_ship_class_create_preallocates_repair():
    ship = ShipClass_Create("blank")
    assert isinstance(ship.GetRepairSubsystem(), RepairSubsystem)
    assert ship.GetRepairSubsystem().GetName() == "Engineering"


def test_set_get_power_round_trip():
    ship = ShipClass()
    p = PowerSubsystem("X")
    ship.SetPowerSubsystem(p)
    assert ship.GetPowerSubsystem() is p


def test_set_get_repair_round_trip():
    ship = ShipClass()
    r = RepairSubsystem("X")
    ship.SetRepairSubsystem(r)
    assert ship.GetRepairSubsystem() is r


def test_setup_properties_scrubs_power_when_no_property():
    """Pass 3 must clear _power_subsystem when no PowerProperty is in
    the property set (mirrors the existing scrub for sensor/impulse/etc)."""
    ship = ShipClass_Create("blank")
    ship.SetupProperties()  # empty property set
    assert ship.GetPowerSubsystem() is None
    assert ship.GetRepairSubsystem() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_ship_power_repair_slots.py -v`

Expected: FAIL — `AttributeError: ShipClass has no attribute 'GetPowerSubsystem'`.

- [ ] **Step 3: Add slots, accessors, and pre-allocation**

In [engine/appc/ships.py](../../../engine/appc/ships.py) `ShipClass.__init__` (after line 28 `self._shield_subsystem = None`), add:

```python
        self._power_subsystem = None
        self._repair_subsystem = None
```

Add accessors after the existing shield accessor block (after line 105):

```python
    def GetPowerSubsystem(self):                  return self._power_subsystem
    def SetPowerSubsystem(self, s) -> None:       self._power_subsystem = s
    def GetRepairSubsystem(self):                 return self._repair_subsystem
    def SetRepairSubsystem(self, s) -> None:      self._repair_subsystem = s
```

Add the slots to `GetSubsystemByProperty`'s scan tuple (line 119):

```python
        for sub in (
            self._sensor_subsystem,
            self._impulse_engine_subsystem,
            self._warp_engine_subsystem,
            self._torpedo_system,
            self._phaser_system,
            self._pulse_weapon_system,
            self._tractor_beam_system,
            self._shield_subsystem,
            self._power_subsystem,
            self._repair_subsystem,
            self._hull,
        ):
```

In Pass 3 (the loop added by today's earlier commit at engine/appc/ships.py:262-270), extend the attr tuple:

```python
        for attr in (
            "_sensor_subsystem", "_impulse_engine_subsystem",
            "_warp_engine_subsystem", "_torpedo_system",
            "_phaser_system", "_pulse_weapon_system",
            "_tractor_beam_system", "_shield_subsystem",
            "_power_subsystem", "_repair_subsystem",
        ):
```

Update `ShipClass_Create` (around line 303) — add imports and pre-allocation:

```python
def ShipClass_Create(class_name: str = "") -> ShipClass:
    from engine.appc.subsystems import (
        TorpedoSystem, PhaserSystem, PulseWeaponSystem, TractorBeamSystem,
        SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
        ShieldSubsystem, PowerSubsystem, RepairSubsystem,
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
    ship.SetPowerSubsystem(PowerSubsystem("Power Plant"))
    ship.SetRepairSubsystem(RepairSubsystem("Engineering"))
    return ship
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_ship_power_repair_slots.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Update the `no-op` regression in test_ship_setup_properties.py**

Today's earlier commit added a test that enumerates all post-scrub slots. Append to its assertions:

In [tests/unit/test_ship_setup_properties.py](../../../tests/unit/test_ship_setup_properties.py) around line 165 (`test_setup_properties_no_op_when_property_set_empty`), add inside the function body:

```python
    assert ship.GetPowerSubsystem() is None
    assert ship.GetRepairSubsystem() is None
```

- [ ] **Step 6: Run full unit suite**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit tests/integration -q`

Expected: PASS. Pass-3 scrub already iterates the attr tuple we just extended; behaviour for empty property sets is "all property-less slots become None".

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_ship_power_repair_slots.py tests/unit/test_ship_setup_properties.py engine/appc/ships.py
git commit -m "$(cat <<'EOF'
feat(ships): _power_subsystem and _repair_subsystem slots

Two new ShipClass slots mirroring the existing eight: Get/Set
accessors, pre-allocation in ShipClass_Create, included in
GetSubsystemByProperty scan and Pass 3 scrub.  Pass 1 dispatch
(PowerProperty / RepairSubsystemProperty handlers) lands in the
next task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: SetupProperties handlers for PowerProperty + RepairSubsystemProperty

**Files:**
- Modify: [engine/appc/ships.py](../../../engine/appc/ships.py) — add two branches inside `SetupProperties`
- Test: [tests/unit/test_setup_properties_power_repair.py](../../../tests/unit/test_setup_properties_power_repair.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""SetupProperties dispatches PowerProperty -> _power_subsystem and
RepairSubsystemProperty -> _repair_subsystem, copying MaxCondition
through and setting the property back-reference."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import PowerProperty, RepairSubsystemProperty


def test_setup_properties_wires_power_plant():
    ship = ShipClass_Create("DryDock")
    p = PowerProperty("Power Plant")
    p.SetMaxCondition(2000.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()

    power = ship.GetPowerSubsystem()
    assert power is not None
    assert power.GetProperty() is p
    assert power.GetMaxCondition() == 2000.0


def test_setup_properties_wires_engineering():
    ship = ShipClass_Create("DryDock")
    r = RepairSubsystemProperty("Engineering")
    r.SetMaxCondition(1500.0)
    r.SetNormalPowerPerSecond(40.0)
    ship.GetPropertySet().AddToSet("Scene Root", r)
    ship.SetupProperties()

    repair = ship.GetRepairSubsystem()
    assert repair is not None
    assert repair.GetProperty() is r
    assert repair.GetMaxCondition() == 1500.0
    # RepairSubsystem inherits PoweredSubsystem -> picks up power line.
    assert repair.GetNormalPowerPerSecond() == 40.0


def test_setup_properties_power_repair_survive_scrub_only_when_property_set():
    """Pass 3 only scrubs slots whose GetProperty() is None.  When
    PowerProperty is in the set, the slot survives."""
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", PowerProperty("Power Plant"))
    ship.SetupProperties()
    assert ship.GetPowerSubsystem() is not None
    assert ship.GetRepairSubsystem() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_setup_properties_power_repair.py -v`

Expected: FAIL — `assert ship.GetPowerSubsystem() is not None` because the property is in the set but no handler exists, so Pass 3 scrubs the slot.

- [ ] **Step 3: Add the two branches**

In [engine/appc/ships.py:143](../../../engine/appc/ships.py#L143) `SetupProperties`, extend the imports tuple:

```python
        from engine.appc.properties import (
            ShipProperty, ImpulseEngineProperty, WarpEngineProperty,
            HullProperty, SensorProperty, ShieldProperty,
            WeaponSystemProperty, TorpedoTubeProperty,
            PowerProperty, RepairSubsystemProperty,
        )
```

Inside the `for prop in self.GetPropertySet().GetPropertyList()` loop, between the `WeaponSystemProperty` branch and the loop end (around line 242), add:

```python
            elif isinstance(prop, PowerProperty):
                ps = self._power_subsystem
                if ps is not None:
                    ps.SetProperty(prop)
                    mc = prop.GetMaxCondition()
                    if mc is not None: ps.SetMaxCondition(mc)
            elif isinstance(prop, RepairSubsystemProperty):
                rs = self._repair_subsystem
                if rs is not None:
                    self._copy_powered_subsystem_fields(prop, rs)
                    rs.SetProperty(prop)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_setup_properties_power_repair.py -v`

Expected: PASS, 3 tests.

- [ ] **Step 5: Run full unit suite**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit tests/integration -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_setup_properties_power_repair.py engine/appc/ships.py
git commit -m "$(cat <<'EOF'
feat(ships): SetupProperties dispatches PowerProperty + RepairSubsystemProperty

Two new dispatch branches in SetupProperties Pass 1.  PowerProperty ->
_power_subsystem (ShipSubsystem-based, no power line of its own).
RepairSubsystemProperty -> _repair_subsystem with the standard
PoweredSubsystem field copy.  Drydock targets panel now surfaces
'Power Plant' and 'Engineering' once the UI getters land in a later
task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Label propagation across SetupProperties branches

**Files:**
- Modify: [engine/appc/ships.py](../../../engine/appc/ships.py) — add `SetName` call to each `SetProperty`-setting branch
- Test: [tests/unit/test_setup_properties_label_propagation.py](../../../tests/unit/test_setup_properties_label_propagation.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""SetupProperties copies the hardpoint name onto the live subsystem.

ShipClass_Create pre-allocates with canonical fallback names
('Tractor Beam System', 'Sensor Subsystem').  When the hardpoint
registers a WeaponSystemProperty('Tractors'), the targets panel must
show 'Tractors' not the fallback.
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    SensorProperty, ImpulseEngineProperty, WarpEngineProperty,
    HullProperty, ShieldProperty, WeaponSystemProperty,
    PowerProperty, RepairSubsystemProperty,
)


def test_sensor_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", SensorProperty("Sensor Array"))
    ship.SetupProperties()
    assert ship.GetSensorSubsystem().GetName() == "Sensor Array"


def test_impulse_label_copied_from_hardpoint():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", ImpulseEngineProperty("Impulse Drive"))
    ship.SetupProperties()
    assert ship.GetImpulseEngineSubsystem().GetName() == "Impulse Drive"


def test_warp_label_copied_from_hardpoint():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", WarpEngineProperty("Warp Nacelles"))
    ship.SetupProperties()
    assert ship.GetWarpEngineSubsystem().GetName() == "Warp Nacelles"


def test_shield_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", ShieldProperty("Shield Generator"))
    ship.SetupProperties()
    assert ship.GetShieldSubsystem().GetName() == "Shield Generator"


def test_tractor_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    p = WeaponSystemProperty("Tractors")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    assert ship.GetTractorBeamSystem().GetName() == "Tractors"


def test_phaser_label_copied_from_hardpoint():
    ship = ShipClass_Create("Galaxy")
    p = WeaponSystemProperty("Phasers")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    assert ship.GetPhaserSystem().GetName() == "Phasers"


def test_power_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", PowerProperty("Power Plant"))
    ship.SetupProperties()
    assert ship.GetPowerSubsystem().GetName() == "Power Plant"


def test_repair_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", RepairSubsystemProperty("Engineering"))
    ship.SetupProperties()
    assert ship.GetRepairSubsystem().GetName() == "Engineering"


def test_hull_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", HullProperty("Primary Hull"))
    ship.SetupProperties()
    assert ship.GetHull().GetName() == "Primary Hull"


def test_empty_hardpoint_name_keeps_canonical_fallback():
    """A property with an empty name leaves the receiver's canonical
    fallback name alone (Phase 1 hardpoints always name; defensive)."""
    ship = ShipClass_Create("Galaxy")
    p = SensorProperty("")  # explicitly empty
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    # The canonical fallback 'Sensor Subsystem' from ShipClass_Create persists.
    assert ship.GetSensorSubsystem().GetName() == "Sensor Subsystem"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_setup_properties_label_propagation.py -v`

Expected: FAIL — every assertion fails except `test_empty_hardpoint_name_keeps_canonical_fallback` (the canonical name stays today because nothing copies anything). `Sensor Subsystem` is returned for every label expectation.

- [ ] **Step 3: Add label-copy line to every SetupProperties branch**

Add a helper at the top of `SetupProperties` (after the imports, before the property loop):

```python
        def _copy_name(prop, receiver):
            if receiver is None: return
            n = prop.GetName()
            if n: receiver.SetName(n)
```

Then in each branch that wires a subsystem, call `_copy_name(prop, receiver)` after the `SetProperty` call:

```python
            if isinstance(prop, ShipProperty):
                # ShipProperty maps to the ship itself; no SetName equivalent.
                for src, setter in (...): ...
            elif isinstance(prop, ImpulseEngineProperty):
                ies = self._impulse_engine_subsystem
                if ies is not None:
                    _copy_name(prop, ies)
                    ies.SetProperty(prop)
                    ...
            elif isinstance(prop, WarpEngineProperty):
                wes = self._warp_engine_subsystem
                if wes is not None:
                    _copy_name(prop, wes)
                    wes.SetProperty(prop)
                ...
            elif isinstance(prop, HullProperty):
                if self._hull is None:
                    self._hull = HullSubsystem(prop.GetName() or "Hull")
                    # Constructor already used the name; no _copy_name call needed.
                    ...
            elif isinstance(prop, SensorProperty):
                sens = self._sensor_subsystem
                if sens is not None:
                    _copy_name(prop, sens)
                    sens.SetProperty(prop)
                    ...
            elif isinstance(prop, ShieldProperty):
                ss = self._shield_subsystem
                if ss is not None:
                    _copy_name(prop, ss)
                    ss.SetProperty(prop)
                    ...
            elif isinstance(prop, WeaponSystemProperty):
                wst = prop.GetWeaponSystemType()
                receiver = {...}.get(wst)
                if receiver is not None:
                    _copy_name(prop, receiver)
                    self._copy_powered_subsystem_fields(prop, receiver)
                    receiver.SetProperty(prop)
                    ...
            elif isinstance(prop, PowerProperty):
                ps = self._power_subsystem
                if ps is not None:
                    _copy_name(prop, ps)
                    ps.SetProperty(prop)
                    ...
            elif isinstance(prop, RepairSubsystemProperty):
                rs = self._repair_subsystem
                if rs is not None:
                    _copy_name(prop, rs)
                    self._copy_powered_subsystem_fields(prop, rs)
                    rs.SetProperty(prop)
```

(The full `SetupProperties` already exists; this task just inserts `_copy_name(prop, receiver)` lines after the existing `receiver is not None:` guard in each branch.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_setup_properties_label_propagation.py -v`

Expected: PASS, 10 tests.

- [ ] **Step 5: Run full unit + integration suite**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit tests/integration -q`

Expected: PASS. The Galaxy hardpoint registers `WeaponSystemProperty("Phasers")` so the existing `test_target_panel_subsystems` integration test will now see "Phasers" instead of "Phaser System" — if the test asserts the exact label set, expect to update it as part of Task 8.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_setup_properties_label_propagation.py engine/appc/ships.py
git commit -m "$(cat <<'EOF'
feat(ships): SetupProperties copies hardpoint name onto subsystem

ShipClass_Create pre-allocates with canonical fallback names
('Tractor Beam System', 'Sensor Subsystem') so SDK callers can chain
methods before SetupProperties runs.  After the hardpoint registers
WeaponSystemProperty('Tractors'), the live subsystem keeps the
fallback name — the targets panel shows 'Tractor Beam System' instead
of 'Tractors'.

Adds a _copy_name(prop, receiver) helper in SetupProperties that
overwrites the receiver's name when the hardpoint provides one
(non-empty GetName()).  Empty/None hardpoint names leave the
canonical fallback alone.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: SetupProperties Pass 4 — child instantiation

**Files:**
- Modify: [engine/appc/ships.py](../../../engine/appc/ships.py) — add Pass 4 at the end of `SetupProperties`
- Test: [tests/unit/test_setup_properties_pass4_children.py](../../../tests/unit/test_setup_properties_pass4_children.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""Pass 4 instantiates one live child subsystem per child WeaponProperty,
attaching it under the matching parent slot via AddChildSubsystem.

Property type -> child slot mapping:
    PhaserProperty       -> _phaser_system._children   (PhaserBank)
    PulseWeaponProperty  -> _pulse_weapon_system       (PulseWeapon)
    TractorBeamProperty  -> _tractor_beam_system       (TractorBeam)
    TorpedoTubeProperty  -> _torpedo_system            (TorpedoTube)
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PhaserProperty, PulseWeaponProperty,
    TractorBeamProperty, TorpedoTubeProperty,
)
from engine.appc.subsystems import (
    PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
)


def _tractor_parent():
    p = WeaponSystemProperty("Tractors")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    return p


def _phaser_parent():
    p = WeaponSystemProperty("Phasers")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    return p


def _pulse_parent():
    p = WeaponSystemProperty("Pulse")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PULSE)
    return p


def _torpedo_parent():
    p = WeaponSystemProperty("Torpedoes")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TORPEDO)
    return p


def test_tractor_children_attached_to_parent():
    ship = ShipClass_Create("DryDock")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _tractor_parent())
    for n in ("Aft Tractor 1", "Aft Tractor 2",
              "Forward Tractor 1", "Forward Tractor 2"):
        ps.AddToSet("Scene Root", TractorBeamProperty(n))
    ship.SetupProperties()

    parent = ship.GetTractorBeamSystem()
    assert parent is not None
    assert parent.GetNumChildSubsystems() == 4
    for i, expected in enumerate([
        "Aft Tractor 1", "Aft Tractor 2",
        "Forward Tractor 1", "Forward Tractor 2",
    ]):
        c = parent.GetChildSubsystem(i)
        assert isinstance(c, TractorBeam)
        assert c.GetName() == expected
        assert c.GetParentSubsystem() is parent


def test_phaser_children_attached_to_parent():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _phaser_parent())
    ps.AddToSet("Scene Root", PhaserProperty("Fore Phaser"))
    ps.AddToSet("Scene Root", PhaserProperty("Aft Phaser"))
    ship.SetupProperties()

    parent = ship.GetPhaserSystem()
    assert parent.GetNumChildSubsystems() == 2
    assert all(isinstance(parent.GetChildSubsystem(i), PhaserBank) for i in range(2))


def test_pulse_children_attached_to_parent():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _pulse_parent())
    ps.AddToSet("Scene Root", PulseWeaponProperty("Forward Pulse"))
    ship.SetupProperties()

    parent = ship.GetPulseWeaponSystem()
    assert parent.GetNumChildSubsystems() == 1
    assert isinstance(parent.GetChildSubsystem(0), PulseWeapon)


def test_torpedo_tubes_attached_as_children():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _torpedo_parent())
    ps.AddToSet("Scene Root", TorpedoTubeProperty("Forward Torpedo 1"))
    ps.AddToSet("Scene Root", TorpedoTubeProperty("Forward Torpedo 2"))
    ship.SetupProperties()

    parent = ship.GetTorpedoSystem()
    assert parent.GetNumChildSubsystems() == 2
    assert all(isinstance(parent.GetChildSubsystem(i), TorpedoTube) for i in range(2))


def test_pass4_skips_children_when_parent_scrubbed():
    """A TractorBeamProperty without a parent WST_TRACTOR -> Pass 3
    scrubs the parent slot, Pass 4 finds no parent to attach to and
    silently skips."""
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet("Scene Root", TractorBeamProperty("Orphan"))
    ship.SetupProperties()  # must not raise

    assert ship.GetTractorBeamSystem() is None
    # No exception, no half-attached state.


def test_pass4_idempotent_against_re_run():
    """Re-running SetupProperties must not double-attach children."""
    ship = ShipClass_Create("DryDock")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _tractor_parent())
    ps.AddToSet("Scene Root", TractorBeamProperty("Aft Tractor 1"))

    ship.SetupProperties()
    ship.SetupProperties()  # second call should detect existing children
    assert ship.GetTractorBeamSystem().GetNumChildSubsystems() == 1


def test_pass4_copies_child_property_back_reference():
    ship = ShipClass_Create("DryDock")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _tractor_parent())
    tbp = TractorBeamProperty("Aft Tractor 1")
    ps.AddToSet("Scene Root", tbp)
    ship.SetupProperties()

    child = ship.GetTractorBeamSystem().GetChildSubsystem(0)
    assert child.GetProperty() is tbp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_setup_properties_pass4_children.py -v`

Expected: FAIL — `GetNumChildSubsystems() == 4` returns 0 because Pass 4 doesn't exist yet.

- [ ] **Step 3: Implement Pass 4**

In [engine/appc/ships.py](../../../engine/appc/ships.py) `SetupProperties`, after Pass 3 (the slot-scrub loop), add Pass 4:

```python
        # Pass 4 — child weapons.  For each child WeaponProperty in the set,
        # instantiate the matching live subsystem and attach it under the
        # parent WeaponSystem slot via AddChildSubsystem.  Skip when the
        # parent slot was scrubbed in Pass 3 (orphan hardpoint).
        #
        # Idempotent — if the parent already has children, this pass is a
        # no-op for the corresponding property type.
        from engine.appc.properties import (
            PhaserProperty, PulseWeaponProperty,
            TractorBeamProperty as _TBP, TorpedoTubeProperty as _TTP,
        )
        from engine.appc.subsystems import (
            PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
        )
        _CHILD_DISPATCH = (
            (PhaserProperty,      "_phaser_system",        PhaserBank),
            (PulseWeaponProperty, "_pulse_weapon_system",  PulseWeapon),
            (_TBP,                "_tractor_beam_system",  TractorBeam),
            (_TTP,                "_torpedo_system",       TorpedoTube),
        )
        # Build a "parent already populated" guard so re-runs are no-ops.
        _parents_with_children = set()
        for _, attr, _ in _CHILD_DISPATCH:
            p = getattr(self, attr)
            if p is not None and p.GetNumChildSubsystems() > 0:
                _parents_with_children.add(attr)

        for prop in self.GetPropertySet().GetPropertyList():
            # Use type(prop) not isinstance — we want the leaf classes only.
            for prop_cls, parent_attr, child_cls in _CHILD_DISPATCH:
                if type(prop) is not prop_cls:
                    continue
                if parent_attr in _parents_with_children:
                    break
                parent = getattr(self, parent_attr)
                if parent is None:
                    break  # parent scrubbed; orphan property
                child = child_cls(prop.GetName() or "")
                child.SetProperty(prop)
                mc = prop.GetMaxCondition()
                if mc is not None: child.SetMaxCondition(mc)
                parent.AddChildSubsystem(child)
                break
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit/test_setup_properties_pass4_children.py -v`

Expected: PASS, 7 tests.

- [ ] **Step 5: Run full suite**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit tests/integration -q`

Expected: PASS. The existing tube-seeding test (`test_setup_properties_torpedo_tubes.py`) still passes because Pass 2 ran before Pass 4 and the `AddAmmoType` calls are independent of child subsystems.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_setup_properties_pass4_children.py engine/appc/ships.py
git commit -m "$(cat <<'EOF'
feat(ships): SetupProperties Pass 4 — materialise child weapons

For each PhaserProperty / PulseWeaponProperty / TractorBeamProperty /
TorpedoTubeProperty in the property set, instantiate the matching live
child subsystem and attach under the parent WeaponSystem slot.
Idempotent: re-runs are no-ops when the parent already has children.
Orphan child properties (no matching parent slot) skip silently.

The drydock's four TractorBeamProperty entries now surface as four
TractorBeam children under the Tractors parent — visible to the
targets panel once the UI nesting lands in a later task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Targets-panel getter list — add Power + Repair

**Files:**
- Modify: [engine/ui/target_list.py](../../../engine/ui/target_list.py) — extend `_SUBSYSTEM_GETTERS`
- Modify: [tests/host/test_target_panel_subsystems.py](../../../tests/host/test_target_panel_subsystems.py) — update Galaxy expected count
- Modify: [tests/integration/test_e1m1_ship_identity.py](../../../tests/integration/test_e1m1_ship_identity.py) — may need updates for new slots
- Test: [tests/ui/test_populated_subsystems_power_repair.py](../../../tests/ui/test_populated_subsystems_power_repair.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""populated_subsystems includes Power + Repair entries in canonical order."""
from engine.ui.target_list import populated_subsystems, _SUBSYSTEM_GETTERS


def test_power_and_repair_are_in_getter_list():
    labels = [label for label, _ in _SUBSYSTEM_GETTERS]
    assert "Power Plant" in labels
    assert "Engineering" in labels


def test_canonical_order_places_defensive_before_offensive():
    """Roughly: hull -> shield -> sensor -> power -> engineering ->
    impulse -> warp -> phaser -> pulse -> torpedo -> tractor."""
    labels = [label for label, _ in _SUBSYSTEM_GETTERS]
    # Use index comparisons rather than asserting the full order so
    # later canonical-order tweaks don't churn this test.
    assert labels.index("Hull")               < labels.index("Shield Generator")
    assert labels.index("Shield Generator")   < labels.index("Sensor Subsystem")
    assert labels.index("Sensor Subsystem")   < labels.index("Power Plant")
    assert labels.index("Power Plant")        < labels.index("Engineering")
    assert labels.index("Engineering")        < labels.index("Impulse Engines")
    assert labels.index("Phaser System")      < labels.index("Tractor Beam System")


class _ShipWithPowerAndRepair:
    class _Sub:
        def __init__(self, n): self._n = n
        def GetName(self): return self._n
    def GetHull(self):              return None
    def GetSensorSubsystem(self):   return None
    def GetImpulseEngineSubsystem(self): return None
    def GetWarpEngineSubsystem(self):    return None
    def GetPhaserSystem(self):           return None
    def GetPulseWeaponSystem(self):      return None
    def GetTorpedoSystem(self):          return None
    def GetTractorBeamSystem(self):      return None
    def GetShieldSubsystem(self):        return None
    def GetPowerSubsystem(self):         return self._Sub("Power Plant")
    def GetRepairSubsystem(self):        return self._Sub("Engineering")


def test_populated_includes_power_and_repair_when_present():
    rows = populated_subsystems(_ShipWithPowerAndRepair())
    labels = [label for label, _ in rows]
    assert labels == ["Power Plant", "Engineering"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/ui/test_populated_subsystems_power_repair.py -v`

Expected: FAIL — Power Plant / Engineering not in `_SUBSYSTEM_GETTERS`.

- [ ] **Step 3: Update `_SUBSYSTEM_GETTERS`**

Replace the tuple at [engine/ui/target_list.py:13-22](../../../engine/ui/target_list.py#L13-L22):

```python
_SUBSYSTEM_GETTERS = (
    ("Hull",                "GetHull"),
    ("Shield Generator",    "GetShieldSubsystem"),
    ("Sensor Subsystem",    "GetSensorSubsystem"),
    ("Power Plant",         "GetPowerSubsystem"),
    ("Engineering",         "GetRepairSubsystem"),
    ("Impulse Engines",     "GetImpulseEngineSubsystem"),
    ("Warp Engines",        "GetWarpEngineSubsystem"),
    ("Phaser System",       "GetPhaserSystem"),
    ("Pulse Weapon System", "GetPulseWeaponSystem"),
    ("Torpedo System",      "GetTorpedoSystem"),
    ("Tractor Beam System", "GetTractorBeamSystem"),
)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/ui/test_populated_subsystems_power_repair.py -v`

Expected: PASS, 3 tests.

- [ ] **Step 5: Update existing Galaxy assertions**

In [tests/host/test_target_panel_subsystems.py:48-53](../../../tests/host/test_target_panel_subsystems.py#L48-L53), the comment says "Galaxy hardpoint registers 7 subsystem-bearing templates". With Power + Repair added, check whether Galaxy actually registers them. Run a probe:

```bash
PYTHONPATH=build/python:$PYTHONPATH uv run python -c "
from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
from engine.appc import ship_lifecycle
from engine.ui.target_list import populated_subsystems
_setup_sdk(); _init_mission(SHIP_GATE_MISSION)
import App
player = App.Game_GetCurrentPlayer()
for ship in ship_lifecycle.snapshot():
    if ship is player: continue
    print(ship.GetName(), [l for l,_ in populated_subsystems(ship)])
"
```

Look at the output. Update the assertion in test_target_panel_subsystems.py to match — either `== 7`, `== 8`, or `== 9` depending on what Galaxy's hardpoint actually registers. If you see new labels appear (e.g. "Power Plant" was always in galaxy.py and now surfaces), set the expected count to match the actual list and update the comment accordingly.

If the e1m1 identity table in `tests/integration/test_e1m1_ship_identity.py` asserts subsystem counts/labels, update those too — same probe-and-adjust pattern.

- [ ] **Step 6: Run full suite**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit tests/integration tests/ui tests/host/test_target_panel_subsystems.py tests/host/test_target_panel_integration.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/ui/test_populated_subsystems_power_repair.py engine/ui/target_list.py tests/host/test_target_panel_subsystems.py
# Plus any of e1m1 / other tests you needed to adjust
git commit -m "$(cat <<'EOF'
feat(ui): targets panel surfaces Power Plant + Engineering

Extends _SUBSYSTEM_GETTERS with the two new ShipClass slots in
canonical defensive-then-input-then-propulsion-then-offensive order.
Galaxy + drydock hardpoints' PowerProperty / RepairSubsystemProperty
templates were silently dropped before; they now drive real targets-
panel rows.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Targets-panel controller nests children under parent

**Files:**
- Modify: [engine/ui/target_list.py](../../../engine/ui/target_list.py) — extend `_add_row` to recurse one level
- Test: [tests/ui/test_target_list_subsystem_children.py](../../../tests/ui/test_target_list_subsystem_children.py) — new file

- [ ] **Step 1: Write the failing test**

```python
"""When a top-level subsystem has children, the controller renders it as
a nested collapsible under the ship row instead of a flat button.
Clicking either the parent collapsible header or a child button routes
to player.SetTargetSubsystem(<that subsystem>)."""
import pytest

from engine.appc import ship_lifecycle
from engine.ui import UiPanel, bindings as bindings_module
from engine.ui._dom import FakeDom
from engine.ui.target_list import TargetListController


@pytest.fixture
def fake_dom(monkeypatch) -> FakeDom:
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


class _Child:
    def __init__(self, name): self._name = name
    def GetName(self): return self._name


class _Parent:
    def __init__(self, name, children):
        self._name = name
        self._children = [_Child(n) for n in children]
    def GetName(self): return self._name
    def GetNumChildSubsystems(self): return len(self._children)
    def GetChildSubsystem(self, i):
        if isinstance(i, int) and 0 <= i < len(self._children):
            return self._children[i]
        return None


class _Ship:
    def __init__(self):
        self._tractor = _Parent("Tractors", [
            "Aft Tractor 1", "Forward Tractor 1",
        ])
        self.target_subsystem = None
    def GetName(self):                   return "Dry Dock"
    def GetHull(self):                   return None
    def GetShieldSubsystem(self):        return None
    def GetSensorSubsystem(self):        return None
    def GetPowerSubsystem(self):         return None
    def GetRepairSubsystem(self):        return None
    def GetImpulseEngineSubsystem(self): return None
    def GetWarpEngineSubsystem(self):    return None
    def GetPhaserSystem(self):           return None
    def GetPulseWeaponSystem(self):      return None
    def GetTorpedoSystem(self):          return None
    def GetTractorBeamSystem(self):      return self._tractor
    def SetTarget(self, t): pass
    def SetTargetSubsystem(self, s): self.target_subsystem = s


def test_parent_with_children_renders_as_nested_collapsible(fake_dom):
    ship = _Ship()
    ship_lifecycle.publish_added(ship)
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: None,
        show_subsystems=True,
    )
    ctrl.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    ship_wrapper = fake_dom.children(body_id)[0]
    ship_children_container = fake_dom.children(ship_wrapper)[1]

    # The ship row's body should contain a nested collapsible (the
    # Tractors parent) — recognisable by having its own children > 0.
    nested_wrappers = fake_dom.children(ship_children_container)
    assert len(nested_wrappers) == 1
    nested_wrapper = nested_wrappers[0]
    # A nested collapsible has the header+body two-child shape.
    nested_children_container = fake_dom.children(nested_wrapper)[1]
    button_ids = fake_dom.children(nested_children_container)
    assert len(button_ids) == 2  # Aft Tractor 1, Forward Tractor 1


def test_click_on_child_subsystem_button_routes_to_set_target(fake_dom):
    """Firing click on a nested child button calls player.SetTargetSubsystem
    with that exact child instance."""
    target_subsystem_holder = {"value": None}

    class _Player:
        def SetTargetSubsystem(self, s):
            target_subsystem_holder["value"] = s

    player = _Player()
    ship = _Ship()
    ship_lifecycle.publish_added(ship)
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: player,
        show_subsystems=True,
    )
    ctrl.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    ship_wrapper = fake_dom.children(body_id)[0]
    ship_children_container = fake_dom.children(ship_wrapper)[1]
    nested_wrapper = fake_dom.children(ship_children_container)[0]
    nested_children_container = fake_dom.children(nested_wrapper)[1]
    first_child_button = fake_dom.children(nested_children_container)[0]
    fake_dom.fire_click(first_child_button)

    assert target_subsystem_holder["value"] is not None
    assert target_subsystem_holder["value"].GetName() == "Aft Tractor 1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/ui/test_target_list_subsystem_children.py -v`

Expected: FAIL — the current controller renders a flat button for every populated subsystem; the nested-collapsible assertion fails.

- [ ] **Step 3: Update controller `_add_row`**

Replace [engine/ui/target_list.py:92-104](../../../engine/ui/target_list.py#L92-L104):

```python
    def _add_row(self, ship) -> None:
        if ship is self._get_player():
            return
        affiliation = _ship_affiliation(ship)
        row = self._panel.collapsible(
            label=ship.GetName(),
            affiliation=affiliation,
            expanded=False,
            on_click=lambda s=ship: self._select(s),
        )
        if not self._show_subsystems:
            return
        for label, sub in populated_subsystems(ship):
            num_children = 0
            if hasattr(sub, "GetNumChildSubsystems"):
                num_children = sub.GetNumChildSubsystems()
            if num_children == 0:
                row.button(label, on_click=lambda s=sub: self._select_subsystem(s))
            else:
                child_collapsible = row.collapsible(
                    label=label,
                    expanded=False,
                    on_click=lambda s=sub: self._select_subsystem(s),
                )
                for i in range(num_children):
                    child = sub.GetChildSubsystem(i)
                    if child is None: continue
                    cl = child.GetName() if hasattr(child, "GetName") else label
                    child_collapsible.button(
                        cl,
                        on_click=lambda s=child: self._select_subsystem(s),
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/ui/test_target_list_subsystem_children.py -v`

Expected: PASS, 2 tests.

If `row.collapsible(...)` doesn't accept `affiliation=None` or omits a default, inspect [engine/ui/panel.py](../../../engine/ui/panel.py) — the `collapsible` factory should already support nested calls (Stage 1 spec confirmed it returns a `Collapsible` that supports `.button(...)` and `.collapsible(...)`).

- [ ] **Step 5: Update existing target-panel tests for the new nested DOM shape**

The existing `test_target_panel_subsystems.py::test_subsystem_buttons_render_for_each_ship` now sees the Galaxy's child weapons as nested collapsibles (PhaserBank × N inside Phasers; TractorBeam × N inside Tractors; TorpedoTube × N inside Torpedoes). Probe what the live shape is:

```bash
PYTHONPATH=build/python:$PYTHONPATH uv run python -c "
from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
from engine.appc import ship_lifecycle
from engine.ui.target_list import populated_subsystems
_setup_sdk(); _init_mission(SHIP_GATE_MISSION)
import App
player = App.Game_GetCurrentPlayer()
for ship in ship_lifecycle.snapshot():
    if ship is player: continue
    print(ship.GetName())
    for label, sub in populated_subsystems(ship):
        n = sub.GetNumChildSubsystems() if hasattr(sub, 'GetNumChildSubsystems') else 0
        if n:
            kids = [sub.GetChildSubsystem(i).GetName() for i in range(n)]
            print(f'  {label} (parent) ->', kids)
        else:
            print(f'  {label} (leaf)')
"
```

Update the assertion accordingly. The existing `assert len(button_ids) == 7` will likely need to become a structured check that distinguishes top-level rows from nested ones; the test_target_list_subsystem_children.py shape is the template.

- [ ] **Step 6: Run full suite**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/unit tests/integration tests/ui tests/host -q`

If `tests/host` hangs (some host tests are slow), narrow to `tests/host/test_target_panel_subsystems.py tests/host/test_target_panel_integration.py`.

Expected: PASS across all affected files.

- [ ] **Step 7: Commit**

```bash
git add tests/ui/test_target_list_subsystem_children.py engine/ui/target_list.py tests/host/test_target_panel_subsystems.py
git commit -m "$(cat <<'EOF'
feat(ui): targets panel nests child weapons under parent collapsible

Parent weapon systems (phasers, pulse, torpedoes, tractors) with at
least one child render as a nested collapsible inside the ship row.
Each child button targets the individual hardpoint emitter via
player.SetTargetSubsystem.  Parent header click still routes to
SetTargetSubsystem(parent) — same UX as before for clicking the
weapon-system row.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: End-to-end drydock probe

**Files:**
- Test: [tests/integration/test_drydock_subsystem_tree.py](../../../tests/integration/test_drydock_subsystem_tree.py) — new file

- [ ] **Step 1: Write the integration test**

```python
"""End-to-end: loading the drydock hardpoint via loadspacehelper produces
the targets-panel subsystem tree the original game shows.  Pins all
behaviour the spec promises: labels from hardpoint, child emitters
under Tractors parent, Power Plant + Engineering surfaced."""
import importlib
import sys

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    HullSubsystem, ShieldSubsystem, SensorSubsystem,
    PowerSubsystem, RepairSubsystem, TractorBeamSystem, TractorBeam,
)


def _build_drydock():
    """Mirror loadspacehelper.CreateShip for ships.Hardpoints.drydock."""
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    mod = importlib.import_module("ships.Hardpoints.drydock")
    ship = ShipClass_Create("DryDock")
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    return ship


def test_drydock_hull_present_and_named():
    ship = _build_drydock()
    hull = ship.GetHull()
    assert isinstance(hull, HullSubsystem)
    assert hull.GetName() == "Hull"


def test_drydock_shield_generator_present_and_named():
    ship = _build_drydock()
    ss = ship.GetShieldSubsystem()
    assert isinstance(ss, ShieldSubsystem)
    assert ss.GetName() == "Shield Generator"


def test_drydock_sensor_array_named_from_hardpoint():
    ship = _build_drydock()
    sens = ship.GetSensorSubsystem()
    assert isinstance(sens, SensorSubsystem)
    assert sens.GetName() == "Sensor Array"


def test_drydock_power_plant_surfaced():
    ship = _build_drydock()
    pwr = ship.GetPowerSubsystem()
    assert isinstance(pwr, PowerSubsystem)
    assert pwr.GetName() == "Power Plant"


def test_drydock_engineering_surfaced():
    ship = _build_drydock()
    eng = ship.GetRepairSubsystem()
    assert isinstance(eng, RepairSubsystem)
    assert eng.GetName() == "Engineering"


def test_drydock_tractor_parent_named_tractors():
    ship = _build_drydock()
    parent = ship.GetTractorBeamSystem()
    assert isinstance(parent, TractorBeamSystem)
    assert parent.GetName() == "Tractors"


def test_drydock_tractor_has_four_named_children():
    ship = _build_drydock()
    parent = ship.GetTractorBeamSystem()
    assert parent.GetNumChildSubsystems() == 4
    names = sorted(parent.GetChildSubsystem(i).GetName() for i in range(4))
    assert names == sorted([
        "Aft Tractor 1", "Aft Tractor 2",
        "Forward Tractor 1", "Forward Tractor 2",
    ])
    for i in range(4):
        assert isinstance(parent.GetChildSubsystem(i), TractorBeam)


def test_drydock_has_no_phasers_no_torpedoes_no_pulse():
    """Drydock hardpoint registers no phasers/torps/pulse; Pass 3
    scrubs those slots and Pass 4 has nothing to attach."""
    ship = _build_drydock()
    assert ship.GetPhaserSystem() is None
    assert ship.GetTorpedoSystem() is None
    assert ship.GetPulseWeaponSystem() is None
```

- [ ] **Step 2: Run test to verify it passes (already implemented through prior tasks)**

Run: `PYTHONPATH=build/python:$PYTHONPATH uv run pytest tests/integration/test_drydock_subsystem_tree.py -v`

Expected: PASS, 8 tests. (This test is the validation harness for everything Tasks 1–9 built; if any individual assertion fails, fix the underlying task before moving on.)

- [ ] **Step 3: Run the mission harness probe one last time**

```bash
PYTHONPATH=build/python:$PYTHONPATH uv run python -c "
import importlib, sys
for k in list(sys.modules):
    if k == 'ships' or k.startswith('ships.'):
        del sys.modules[k]
mod = importlib.import_module('ships.Hardpoints.drydock')
from engine.appc.ships import ShipClass_Create
ship = ShipClass_Create('DryDock')
mod.LoadPropertySet(ship.GetPropertySet())
ship.SetupProperties()

print('Drydock subsystem tree:')
def show(sub, indent=0):
    if sub is None: return
    n_kids = sub.GetNumChildSubsystems() if hasattr(sub, 'GetNumChildSubsystems') else 0
    print('  '*indent + '- ' + sub.GetName() + (' (' + str(n_kids) + ' children)' if n_kids else ''))
    for i in range(n_kids):
        show(sub.GetChildSubsystem(i), indent+1)

from engine.ui.target_list import populated_subsystems
for label, sub in populated_subsystems(ship):
    show(sub)
"
```

Expected output:

```
Drydock subsystem tree:
  - Hull
  - Shield Generator
  - Sensor Array
  - Power Plant
  - Engineering
  - Tractors (4 children)
    - Aft Tractor 1
    - Aft Tractor 2
    - Forward Tractor 1
    - Forward Tractor 2
```

That matches the original game's targets panel for Drydock A.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_drydock_subsystem_tree.py
git commit -m "$(cat <<'EOF'
test(integration): end-to-end drydock subsystem tree probe

Locks in the targets-panel structure for the drydock hardpoint:
Hull + Shield Generator + Sensor Array + Power Plant + Engineering
+ Tractors parent with four named TractorBeam children.  Matches the
original game's Drydock A row exactly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist

After running through all tasks, confirm:

- [ ] Each spec section is covered by at least one task:
  - A.1 Child storage → Task 1
  - A.2 Live child classes → Task 2
  - A.3 New top-level classes → Task 3
  - A.4 New ShipClass slots → Task 4
  - A.5 SetupProperties handlers → Task 5
  - A.6 Label propagation → Task 6
  - A.7 Pass 4 child instantiation → Task 7
  - UI getters → Task 8
  - UI nested rendering → Task 9
  - End-to-end probe → Task 10
- [ ] No "TBD" / "TODO" / "fill in details" markers.
- [ ] Property class names match between tasks (`TractorBeamProperty`, `PowerProperty`, etc — leaf types, not `EnergyWeaponProperty`).
- [ ] Slot attribute names match (`_power_subsystem`, `_repair_subsystem`) across Tasks 4–9.
- [ ] Test files use the convention `test_<thing>.py` and live alongside their kind (`tests/unit`, `tests/integration`, `tests/ui`).
- [ ] No task assumes UI internals that the test fixtures don't reach (`FakeDom.children`, `panel_root`, `fire_click` are all real APIs in `engine/ui/_dom.py`).
- [ ] Empty / orphan property cases covered — Task 4 (empty), Task 7 (orphan child).
- [ ] Idempotency covered — Task 7 has `test_pass4_idempotent_against_re_run`.
