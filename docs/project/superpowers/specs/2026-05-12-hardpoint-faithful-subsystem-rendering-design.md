# Hardpoint-Faithful Subsystem Rendering

**Status:** design
**Date:** 2026-05-12

## Problem

The targets panel's subsystem list does not match the hardpoint. Comparing the original game's drydock target row against ours:

| Original "Drydock A" | Ours "Dry Dock3" |
|---|---|
| Shield Generator | _(missing)_ |
| Sensor Array | Sensor Subsystem _(wrong label)_ |
| Power Plant | _(missing)_ |
| ▼ Tractors | Tractor Beam System _(wrong label, no children)_ |
| · Aft Tractor 1 | |
| · Aft Tractor 2 | |
| · Forward Tractor 1 | |
| · Forward Tractor 2 | |

The drydock hardpoint at [sdk/Build/scripts/ships/Hardpoints/drydock.py](../../../sdk/Build/scripts/ships/Hardpoints/drydock.py) registers all of these as properties — `HullProperty`, `ShieldProperty("Shield Generator")`, `SensorProperty("Sensor Array")`, `PowerProperty("Power Plant")`, `WeaponSystemProperty("Tractors", WST_TRACTOR)`, and four `TractorBeamProperty` children. Our engine drops half of them, mislabels the rest, and never materialises child emitters at all.

The same parent→children pattern applies to phaser banks, pulse weapons, and torpedo tubes — every BC weapon system has individual hardpoint emitters. The SDK's UI walks `parent.GetChildSubsystem(i)`; our `populated_subsystems()` is flat.

## Goals

- A ship's targets-panel subsystem list mirrors what its hardpoint registered: same set, same names, same parent/child structure.
- Child weapon emitters (tractor beams, phaser banks, pulse weapons, torpedo tubes) render as nested entries under their parent weapon system.
- Targeting a child subsystem (`player.SetTargetSubsystem(child)`) works exactly like targeting the parent — no new wiring at the targeting layer.
- Existing SDK callers that touch parent slots before SetupProperties runs (e.g. `pShip.GetTorpedoSystem().AddAmmoType(...)`) keep working.

## Non-goals

- Hardpoint *position* fidelity. Properties already carry position; weapons that fire from specific emitter positions are out of scope here — that's a renderer/physics question.
- Per-tube ammo independence. SDK's torpedo-system ammo table is indexed by slot, not by tube reference; the existing flat ammo table stays.
- Damage propagation between parent and children. SDK tracks per-emitter `_condition` but the aggregate flows through the parent; we'll add child storage but not the damage-routing yet.
- Cloak subsystem. `CloakingSubsystemProperty` exists in our properties module but the SDK pattern is the same — wire it in a follow-up if Romulan ships need it.
- Reordering the canonical subsystem list to match the SDK's exact display order. We'll insert Power + Repair in a sensible place; deferring perfect-order matching to a follow-up if the user notices.

## Architecture

Six edits across three files plus a small `properties.py` ordering touch.

| Unit | Where | Role |
|---|---|---|
| `ShipSubsystem._children` *(edit)* | `engine/appc/subsystems.py` | Replace the always-`None`/`0` child stubs with a real list. Add `AddChildSubsystem(sub)`. |
| `PhaserBank`, `PulseWeapon`, `TractorBeam`, `TorpedoTube` *(new)* | `engine/appc/subsystems.py` | Thin live-subsystem classes — one per hardpoint child property type. Subclass `WeaponSystem` (firing state + power line). |
| `PowerSubsystem`, `RepairSubsystem` *(new)* | `engine/appc/subsystems.py` | Power plant and engineering. `PowerSubsystem` subclasses `ShipSubsystem` (matches `PowerProperty: SubsystemProperty`); `RepairSubsystem` subclasses `PoweredSubsystem` (matches `RepairSubsystemProperty: PoweredSubsystemProperty`). Confirmed against [sdk App.py:5710, 6639](../../../sdk/Build/scripts/App.py). |
| `ShipClass._power_subsystem`, `_repair_subsystem` slots *(edit)* | `engine/appc/ships.py` | New slots with the same Get/Set pattern as the existing eight. Pre-allocated in `ShipClass_Create`. |
| `SetupProperties` Pass 4 + label propagation + new slot handlers *(edit)* | `engine/appc/ships.py` | Walk the property set once more after the existing dispatch to instantiate children. Each existing `SetProperty(prop)` branch also calls `receiver.SetName(prop.GetName())`. Add branches for `PowerProperty` and `RepairSubsystemProperty`. |
| `populated_subsystems` + controller *(edit)* | `engine/ui/target_list.py` | Add `Power Plant` and `Engineering` to `_SUBSYSTEM_GETTERS`. Controller's `_add_row` checks `GetNumChildSubsystems()`; if non-zero, renders the subsystem as a nested collapsible inside the ship row instead of a flat button. |

### Live subsystem hierarchy

```
ShipClass
├── _hull              HullSubsystem            (from HullProperty)
├── _sensor_subsystem  SensorSubsystem          (from SensorProperty)
├── _power_subsystem   PowerSubsystem  *new*    (from PowerProperty)
├── _repair_subsystem  RepairSubsystem *new*    (from RepairSubsystemProperty)
├── _impulse_engine_subsystem  ImpulseEngineSubsystem
├── _warp_engine_subsystem     WarpEngineSubsystem
├── _phaser_system     PhaserSystem             (from WeaponSystemProperty WST_PHASER)
│   └── _children      [PhaserBank, ...]        (from each PhaserProperty)
├── _pulse_weapon_system  PulseWeaponSystem
│   └── _children      [PulseWeapon, ...]       (from each PulseWeaponProperty)
├── _torpedo_system    TorpedoSystem
│   └── _children      [TorpedoTube, ...]       (from each TorpedoTubeProperty)
├── _tractor_beam_system  TractorBeamSystem
│   └── _children      [TractorBeam, ...]       (from each TractorBeamProperty)
└── _shield_subsystem  ShieldSubsystem          (from ShieldProperty)
```

### SetupProperties pass map

The existing two passes stay. Two new passes follow.

| Pass | Walks | Action |
|---|---|---|
| 1 *(existing)* | property set | Match each property to its slot. `SetProperty(slot, prop)` on matched slots. |
| 2 *(existing)* | torpedo tubes | Count `TorpedoTubeProperty` instances; seed `AddAmmoType(AT_ONE)` per tube. |
| 3 *(existing)* | every slot | Scrub slots whose `GetProperty()` is `None`. |
| **4** *(new)* | property set | For each `PhaserProperty` / `PulseWeaponProperty` / `TractorBeamProperty` / `TorpedoTubeProperty`, instantiate the matching live child and append to the parent slot's `_children`. Skip if the parent slot was scrubbed in Pass 3. |

Pass 4 runs after Pass 3 so children attach only to surviving parents. A ship that has phaser hardpoints but no parent `WeaponSystemProperty(WST_PHASER)` is malformed; Pass 4 logs and skips rather than auto-creating a parent.

### Pass 1 label propagation

Each `elif isinstance(prop, X)` branch in `SetupProperties` already calls `receiver.SetProperty(prop)`. Add `receiver.SetName(prop.GetName())` in the same branch when `prop.GetName()` is non-empty. This is a one-line edit per branch (seven branches: sensor, impulse, warp, hull, shield, weapon, plus the two new branches). The hardpoint name ("Tractors", "Sensor Array", "Power Plant") replaces the canonical fallback name ("Tractor Beam System", "Sensor Subsystem", etc.).

### Targeting child subsystems

The controller's `_add_row` recurses one level:

```python
def _add_row(self, ship) -> None:
    if ship is self._get_player(): return
    row = self._panel.collapsible(label=ship.GetName(), affiliation=affiliation, ...)
    if not self._show_subsystems: return
    for label, sub in populated_subsystems(ship):
        if sub.GetNumChildSubsystems() == 0:
            row.button(label, on_click=lambda s=sub: self._select_subsystem(s))
        else:
            child_row = row.collapsible(label=label, on_click=lambda s=sub: self._select_subsystem(s))
            for i in range(sub.GetNumChildSubsystems()):
                ch = sub.GetChildSubsystem(i)
                child_row.button(ch.GetName(), on_click=lambda s=ch: self._select_subsystem(s))
```

`UiPanel.collapsible` already returns an object that supports `.button(...)` and `.collapsible(...)` factories — the nested case reuses the existing API. Targeting the parent (`on_click` on the parent collapsible header) routes to `SetTargetSubsystem(parent)`; targeting a child routes the same call with the child instance.

## Data flow

```
hardpoint.py LoadPropertySet(pSet)
    └─ pSet.AddToSet("Scene Root", TractorBeamProperty("Aft Tractor 1"))
       pSet.AddToSet("Scene Root", WeaponSystemProperty("Tractors", WST_TRACTOR))
       …

pShip.SetupProperties()
    ├─ Pass 1: each property → matched slot, SetProperty + SetName
    ├─ Pass 2: count TorpedoTubeProperty → seed ammo
    ├─ Pass 3: scrub property-less slots
    └─ Pass 4: each child property → parent.AddChildSubsystem(new live child)

target_list.TargetListController.rebuild_from_snapshot()
    └─ for each ship:
       for label, sub in populated_subsystems(ship):
           if sub has children → render nested collapsible
           else                → render flat button
```

## Per-unit detail

### `ShipSubsystem` child storage

```python
def __init__(self, name=""):
    ...
    self._children: list["ShipSubsystem"] = []

def GetNumChildSubsystems(self) -> int:
    return len(self._children)

def GetChildSubsystem(self, arg=None):
    if arg is None: return None        # zero-arg backward compat — SDK uses this in flowed iter
    if isinstance(arg, int):
        if 0 <= arg < len(self._children): return self._children[arg]
        return None
    if isinstance(arg, str):
        for c in self._children:
            if c.GetName() == arg: return c
        return None
    return None

def AddChildSubsystem(self, sub: "ShipSubsystem") -> None:
    sub._parent_subsystem = self
    self._children.append(sub)
```

### Live child classes

```python
class PhaserBank(WeaponSystem):     pass   # placeholder — fields added as SDK callers demand
class PulseWeapon(WeaponSystem):    pass
class TractorBeam(WeaponSystem):    pass
class TorpedoTube(WeaponSystem):
    """Individual launcher; ammo-type tracking lives on the parent TorpedoSystem."""
    pass
```

Tests will lock in the inheritance + presence of `GetName`/`GetProperty`. Field expansion is incremental.

### Pass 4 implementation sketch

```python
CHILD_DISPATCH: dict[type, tuple[str, type]] = {
    PhaserProperty:      ("_phaser_system",       PhaserBank),
    PulseWeaponProperty: ("_pulse_weapon_system", PulseWeapon),
    TractorBeamProperty: ("_tractor_beam_system", TractorBeam),
    TorpedoTubeProperty: ("_torpedo_system",      TorpedoTube),
}

for prop in self.GetPropertySet().GetPropertyList():
    entry = CHILD_DISPATCH.get(type(prop))
    if entry is None: continue
    parent_attr, child_cls = entry
    parent = getattr(self, parent_attr)
    if parent is None: continue   # parent scrubbed in Pass 3
    child = child_cls(prop.GetName() or "")
    child.SetProperty(prop)
    mc = prop.GetMaxCondition()
    if mc is not None: child.SetMaxCondition(mc)
    parent.AddChildSubsystem(child)
```

`type(prop)` rather than `isinstance` because `PhaserProperty` inherits from `EnergyWeaponProperty`, which inherits from `WeaponProperty`, which inherits from `SubsystemProperty` — and we only want the leaf types. (Verify class hierarchy when implementing.)

### New `PowerSubsystem` / `RepairSubsystem`

```python
class PowerSubsystem(ShipSubsystem):
    """Power plant — drives the ship's energy budget.

    Inherits from ShipSubsystem (not PoweredSubsystem) to match SDK
    App.py:5710 where PowerSubsystem inherits ShipSubsystem directly.
    """
    pass

class RepairSubsystem(PoweredSubsystem):
    """Engineering / damage-control subsystem. SDK App.py:6639."""
    pass
```

Same minimal pattern as the new weapon children. Fields added when SDK callers prove they're needed (consistent with how the rest of the subsystem module evolved).

### `ShipClass` slot additions

`ShipClass.__init__`, `ShipClass_Create`, and the slot enumeration in Pass 3 all grow by two entries. `_SUBSYSTEM_GETTERS` in `target_list.py` grows by two entries (`"Power Plant"` and `"Engineering"` paired with `GetPowerSubsystem` / `GetRepairSubsystem`).

Canonical order in `_SUBSYSTEM_GETTERS` (matches original screenshot ordering roughly: defensive → input → propulsion → offensive):

1. Hull
2. Shield Generator
3. Sensor Subsystem
4. Power Plant
5. Engineering
6. Impulse Engines
7. Warp Engines
8. Phaser System
9. Pulse Weapon System
10. Torpedo System
11. Tractor Beam System

## Error handling

- Child property whose parent slot was scrubbed: silently skip (already happens via the `if parent is None: continue` guard). Logged once at WARN if the property carries a non-empty name, since this indicates a malformed hardpoint.
- `prop.GetName()` returning `None` or `""`: child gets a placeholder name (`f"{child_cls.__name__} {index}"`). Real hardpoints always name their emitters; defensive only.
- `SetMaxCondition(None)`: existing `_copy_powered_subsystem_fields` already None-checks; same pattern in the new code.

## Testing

| Test | File | Asserts |
|---|---|---|
| Pass 4 creates one TractorBeam child per TractorBeamProperty | `tests/unit/test_setup_properties_children.py` *(new)* | After SetupProperties on a property set with one WST_TRACTOR parent + 4 TractorBeamProperties, `parent.GetNumChildSubsystems() == 4` and each child is a `TractorBeam` instance with the property name. |
| Pass 4 skips children when parent is scrubbed | same | Property set with TractorBeamProperty but no WST_TRACTOR parent → no children created, no exception. |
| Label propagation copies hardpoint name | `tests/unit/test_setup_properties_label_propagation.py` *(new)* | After SetupProperties with `WeaponSystemProperty("Tractors", WST_TRACTOR)`, `ship.GetTractorBeamSystem().GetName() == "Tractors"`. Same for sensor, shield, hull, impulse, warp. |
| New Power / Engineering slots populate from hardpoint | `tests/unit/test_setup_properties_power_repair.py` *(new)* | `PowerProperty("Power Plant")` + `RepairSubsystemProperty("Engineering")` → `ship.GetPowerSubsystem()` / `GetRepairSubsystem()` non-None with correct names. |
| Power/Engineering scrubbed when absent | same | Empty property set → both getters return `None` after SetupProperties (Pass 3 still works for the new slots). |
| UI nests children under parent | `tests/ui/test_target_list_subsystem_children.py` *(new)* | Stub ship with a tractor-beam-system whose `GetNumChildSubsystems()` returns 4 → controller renders a nested collapsible with 4 buttons, not a flat button. |
| Click on child subsystem routes to SetTargetSubsystem | same | Firing click on the nested child button calls `player.SetTargetSubsystem(child)`. |
| Live drydock probe | `tests/integration/test_drydock_subsystem_tree.py` *(new)* | Load drydock hardpoint via `loadspacehelper.CreateShip("DryDock", ...)`; assert `GetTractorBeamSystem()` has 4 children with the expected names; assert `GetPowerSubsystem().GetName() == "Power Plant"`. |

Existing tests that relied on the wrong label or missing slots are updated as side-effects of the implementation, the same way today's commit updated `test_target_panel_subsystems.py` and `test_e1m1_ship_identity.py`.

## Migration

No data migration. Save/load (SDK pickle of ShipClass) is not affected — child subsystems are recreated from the property set at load-time the same way the parent slots already are.

## Risk and mitigation

| Risk | Mitigation |
|---|---|
| New child types break SDK code that does `isinstance(sub, WeaponSystem)` and assumes a parent. | All four new child classes subclass `WeaponSystem`, so `isinstance` still passes. Callers that distinguish "parent vs. child" use the property-class check, which we don't break. |
| `type(prop)` exact-match in Pass 4 misses a subclass. | Test fixture covers `PhaserProperty` (which inherits multiple layers). If the SDK ever adds a `PhaserProperty` subclass, the test will catch the omission. |
| Existing target-list integration tests count subsystems exactly. | They'll need updating to include Power + Engineering; this is mechanical (same pattern as today's commit). |
| Damage scaling (`AdjustShipForDifficulty`) silently skips new children. | Already covered by the existing back-reference test pattern — Pass 4 sets `_property` on each child, so `GetSubsystemByProperty` walks find them. Add a regression test that includes child weapon properties in the difficulty walk. |

## Out of scope, deferred

- Cloak (`CloakingSubsystemProperty`) — same pattern as Power/Repair; add when a Romulan/Klingon ship needs it.
- Per-emitter firing arcs / hardpoint positions on the renderer side. The property already carries position; rendering the muzzle flash from the right hardpoint is a Phase 2 visual-effects task.
- Reading the SDK's exact subsystem display order. Current ordering is plausible; revisit if the user reports rows in the "wrong" order.
- Damage propagation between child and parent condition aggregates.
