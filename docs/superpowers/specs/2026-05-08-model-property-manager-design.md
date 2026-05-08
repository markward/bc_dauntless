# Model Property Manager — Design Spec

**Date:** 2026-05-08  
**Status:** Approved  
**Phase:** 1

## Context

`g_kModelPropertyManager.FindByName` is the hottest stub in the harness profile — 6,756 calls across 30 missions. The full property manager cluster (FindByName + RegisterLocalTemplate + TGModelPropertySet.AddToSet + property factory calls) dominates the top-50 profile entries and currently flows entirely through `_NamedStub`, meaning configured property values (shield max, weapon damage, charge rates, etc.) are silently discarded. Phase 1 mission logic queries these values to drive branching decisions, so they must be real.

## Goal

Replace `g_kModelPropertyManager` and the `TGModelProperty` hierarchy with a real implementation so that:

1. `RegisterLocalTemplate(prop)` persists the property by name.
2. `FindByName(name, scope)` retrieves it.
3. All `Set*(...)` / `Get*(...)` calls store and return values correctly.
4. `ClearLocalTemplates()` between ship loads works correctly.
5. The harness still passes 35/35 after the change.

## Non-goals

- Renderer-layer methods: `RegisterFilter`, `AddFilter`, `ApplyFilters`, `ClearRegisteredFilters`, `ClearCurrentFilters`, `RemoveFilter` — these are Phase 2 concerns and stay as `_NamedStub` fallbacks.
- Game-logic within properties (e.g. actual shield absorption, weapon firing) — properties are data containers only in Phase 1.

## Architecture

### New module: `engine/appc/properties.py`

Follows the existing `engine/appc/` convention (one module per subsystem). App.py imports from it and exposes the public names.

### `TGModelProperty` — data-bag base

```python
class TGModelProperty:
    def __init__(self, name: str):
        self._name = name
        self._data: dict = {}

    def GetName(self) -> str:  return self._name
    def SetName(self, v: str): self._name = v
    def __bool__(self):        return True
    def __repr__(self):        return f"<{type(self).__name__} {self._name!r}>"

    def __getattr__(self, attr):
        if attr.startswith("Set"):
            field = attr[3:]
            def setter(*args):
                self._data[(field, args[:-1])] = args[-1]
            return setter
        if attr.startswith("Get"):
            field = attr[3:]
            def getter(*args):
                return self._data.get((field, args), None)
            return getter
        raise AttributeError(attr)
```

Key design point: `SetMaxShields(face, value)` stores `("MaxShields", (face,)) → value`. `GetMaxShields(face)` looks up `("MaxShields", (face,))`. Zero-arg setters like `SetMaxCondition(5000)` store `("MaxCondition", ()) → 5000`. This handles the full SDK surface without per-method boilerplate.

`Ptr` wrapper classes from the original SWIG binding are not reproduced — factory functions return the concrete subclass directly.

### Property subclass hierarchy

Subclasses are thin — they only add class-level constants. All setter/getter behaviour is inherited from the base.

```
TGModelProperty
├── PositionOrientationProperty
├── EngineGlowProperty
└── SubsystemProperty
    ├── HullProperty
    ├── PowerProperty
    ├── WeaponProperty
    │   ├── TorpedoTubeProperty
    │   └── EnergyWeaponProperty
    │       ├── PhaserProperty
    │       ├── PulseWeaponProperty
    │       └── TractorBeamProperty
    └── PoweredSubsystemProperty
        ├── ShieldProperty       # FRONT/REAR/TOP/BOTTOM/LEFT/RIGHT/NUM_SHIELDS = 0..6
        ├── SensorProperty
        ├── RepairSubsystemProperty
        └── WeaponSystemProperty  # WST_UNKNOWN/PHASER/TORPEDO/PULSE/TRACTOR = 0..4
            └── TorpedoSystemProperty
```

**Shield face constants** (used as `ShieldGenerator.FRONT_SHIELDS` in hardpoints):
```python
FRONT_SHIELDS = 0; REAR_SHIELDS = 1; TOP_SHIELDS = 2
BOTTOM_SHIELDS = 3; LEFT_SHIELDS = 4; RIGHT_SHIELDS = 5; NUM_SHIELDS = 6
```

**WeaponSystemProperty type constants:**
```python
WST_UNKNOWN = 0; WST_PHASER = 1; WST_TORPEDO = 2; WST_PULSE = 3; WST_TRACTOR = 4
```

### Factory functions

Each property type gets a `XxxProperty_Create(name)` factory that simply returns `XxxProperty(name)`. These mirror the SDK's `Appc.new_XxxProperty` pattern. Named `_Create` (not `__init__`) to match SDK call sites: `App.ShieldProperty_Create("Shield Generator")`.

### `TGModelPropertyManager`

```python
class TGModelPropertyManager:
    LOCAL_TEMPLATES  = 0
    GLOBAL_TEMPLATES = 1

    def __init__(self):
        self._local:  dict[str, TGModelProperty] = {}
        self._global: dict[str, TGModelProperty] = {}

    def RegisterLocalTemplate(self, prop):  self._local[prop.GetName()]  = prop
    def RegisterGlobalTemplate(self, prop): self._global[prop.GetName()] = prop
    def ClearLocalTemplates(self):          self._local.clear()
    def ClearGlobalTemplates(self):         self._global.clear()

    def FindByName(self, name, scope):
        store = self._local if scope == self.LOCAL_TEMPLATES else self._global
        return store.get(name)

    def FindByNameAndType(self, name, type_cls, scope):
        prop = self.FindByName(name, scope)
        return prop if isinstance(prop, type_cls) else None

    def IsLocalTemplate(self, prop):  return prop in self._local.values()
    def IsGlobalTemplate(self, prop): return prop in self._global.values()

    def RemoveTemplate(self, prop):
        self._local  = {k: v for k, v in self._local.items()  if v is not prop}
        self._global = {k: v for k, v in self._global.items() if v is not prop}
```

Important: `loadspacehelper.py:90` calls `ClearLocalTemplates()` between ship loads, so the manager is genuinely stateful across hardpoint imports. The singleton `g_kModelPropertyManager` must survive the mission lifetime — it is a module-level object in App.py, so this is automatic.

Renderer-only methods (`RegisterFilter`, `AddFilter`, `ApplyFilters`, `ClearRegisteredFilters`, `ClearCurrentFilters`, `RemoveFilter`) are **not implemented** here. They are accessed via App.py's module-level `__getattr__` fallback and return `_NamedStub`.

### `TGModelPropertySet`

Used in `loadspacehelper.py` to construct a set of properties for a ship. Also used directly in hardpoint `LoadPropertySet` functions.

```python
class TGModelPropertySet:
    def __init__(self):
        self._entries: list[tuple[str, TGModelProperty]] = []

    def AddToSet(self, node_name: str, prop: TGModelProperty):
        self._entries.append((node_name, prop))

    def GetPropertyList(self):           return _PropertyListIter(self._entries)
    def GetPropertiesByType(self, cls):  return _PropertyListIter(
        [(n, p) for n, p in self._entries if isinstance(p, cls)]
    )
```

`_PropertyListIter` is a minimal iterable wrapper exposing `TGBeginIteration` / `TGGetNext` / `TGDoneIterating` / `TGGetNumItems` to match the SDK iterator pattern used in SDK scripts that walk a ship's property list.

### App.py changes

```python
from engine.appc.properties import (
    TGModelProperty,
    TGModelPropertyManager, TGModelPropertySet,
    PositionOrientationProperty, PositionOrientationProperty_Create,
    SubsystemProperty, HullProperty, HullProperty_Create,
    PowerProperty, PowerProperty_Create,
    WeaponProperty, EnergyWeaponProperty,
    PhaserProperty, PhaserProperty_Create,
    PulseWeaponProperty, PulseWeaponProperty_Create,
    TractorBeamProperty, TractorBeamProperty_Create,
    TorpedoTubeProperty, TorpedoTubeProperty_Create,
    PoweredSubsystemProperty,
    ShieldProperty, ShieldProperty_Create,
    SensorProperty, SensorProperty_Create,
    RepairSubsystemProperty, RepairSubsystemProperty_Create,
    WeaponSystemProperty, TorpedoSystemProperty, TorpedoSystemProperty_Create,
    EngineGlowProperty,
)

g_kModelPropertyManager = TGModelPropertyManager()
```

Because these are explicit module-level names, Python's attribute lookup finds them before falling through to `__getattr__`. No changes to `__getattr__` are needed.

## Testing

New `tests/unit/test_properties.py`:

- Register/FindByName round-trip (local scope)
- Register/FindByName round-trip (global scope)
- `FindByName` returns `None` for unknown name
- `ClearLocalTemplates` empties local; global unaffected
- `ClearGlobalTemplates` empties global; local unaffected
- Data bag: single-arg setter/getter (`SetMaxCondition` / `GetMaxCondition`)
- Data bag: multi-arg setter/getter (`SetMaxShields(face, v)` / `GetMaxShields(face)`)
- `FindByNameAndType` returns property on type match, `None` on mismatch
- `IsLocalTemplate` / `IsGlobalTemplate` correctness
- `TGModelPropertySet.AddToSet` and `GetPropertyList` iteration
- `TGModelPropertySet.GetPropertiesByType` filters by subclass
- `ShieldProperty.FRONT_SHIELDS` constant value is 0
- `WeaponSystemProperty.WST_TORPEDO` constant value is 2

Integration: harness run with `--ticks 60` must still pass 35/35.
