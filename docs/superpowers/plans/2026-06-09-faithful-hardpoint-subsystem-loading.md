# Faithful Hardpoint Subsystem Loading — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build every subsystem a hardpoint registers — engine pods, the bridge, and object emitters — into one BC-faithful subsystem tree, surface them in the Property Viewer and the (now hierarchical) target menu, and keep enemy-AI behavior unchanged.

**Architecture:** Engine pods (`EngineProperty` leaves) attach as plain `ShipSubsystem` children of the impulse/warp aggregators, keyed by engine type; the bridge (2nd `HullProperty`) attaches as a child of the primary hull; object emitters become non-damageable mount markers. The target menu builder recurses into children to render a ship → aggregator → leaf accordion. AI is untouched because `ShipSubsystem.IsTargetable()` is hardcoded to `1`, so the SDK AI loop never recurses into children.

**Tech Stack:** Python 3 (engine), pytest (focused subsets only — the full suite OOMs the host), CEF/JS + CSS for the target-list UI.

**Spec:** `docs/superpowers/specs/2026-06-09-faithful-hardpoint-subsystem-loading-design.md`
**Deferred follow-up (not in this plan):** `docs/superpowers/specs/2026-06-09-subsystem-targetability-fidelity-followup.md`

**Branch:** work on `feat/faithful-hardpoint-subsystems` (already created).

**Test command (always focused):**
```bash
uv run pytest tests/unit/test_xxx.py -v      # never `uv run pytest` with no path
```

---

## Task 1: `EngineProperty` exposes its engine type

The hardpoint calls `PortWarp.SetEngineType(PortWarp.EP_WARP)`, but our `EngineProperty`
has no real `Get/SetEngineType` — the call falls through to a `_NamedStub` and the value is
lost. Add the accessors so the construction pass can route pods to the right aggregator.

**Files:**
- Modify: `engine/appc/properties.py:804-806` (class `EngineProperty`)
- Test: `tests/unit/test_engine_property_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_engine_property_type.py
from engine.appc.properties import EngineProperty


def test_engine_type_round_trips():
    p = EngineProperty("Port Warp")
    p.SetEngineType(EngineProperty.EP_WARP)
    assert p.GetEngineType() == EngineProperty.EP_WARP


def test_engine_type_defaults_to_impulse():
    p = EngineProperty("Center Impulse")
    assert p.GetEngineType() == EngineProperty.EP_IMPULSE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_engine_property_type.py -v`
Expected: FAIL — `GetEngineType()` returns a `_NamedStub`, not `EP_WARP` (and no default).

- [ ] **Step 3: Implement the accessors**

Replace the body of `class EngineProperty(SubsystemProperty):` (currently just the two
class constants) with:

```python
class EngineProperty(SubsystemProperty):
    EP_IMPULSE = 0
    EP_WARP    = 1

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._engine_type = self.EP_IMPULSE

    def SetEngineType(self, t) -> None:
        self._engine_type = int(t)

    def GetEngineType(self) -> int:
        return self._engine_type
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_engine_property_type.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/properties.py tests/unit/test_engine_property_type.py
git commit -m "feat(properties): EngineProperty Get/SetEngineType

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Engine pods attach as children of their aggregators

`EngineProperty` leaves (Port/Star Warp; Port/Star/Center Impulse) currently have no
construction path. Add a pass to `SetupProperties` that builds each as a plain
`ShipSubsystem` and attaches it to the impulse or warp aggregator by `GetEngineType()`.

**Files:**
- Modify: `engine/appc/ships.py` — `SetupProperties`, after the Pass-4 weapon-child loop (ends at line 884)
- Test: `tests/unit/test_setup_properties_engine_pods.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_setup_properties_engine_pods.py
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import EngineProperty
from engine.appc.subsystems import ShipSubsystem


def _impulse_pod(name):
    p = EngineProperty(name)
    p.SetEngineType(EngineProperty.EP_IMPULSE)
    p.SetMaxCondition(2600.0)
    p.SetTargetable(1)
    return p


def _warp_pod(name):
    p = EngineProperty(name)
    p.SetEngineType(EngineProperty.EP_WARP)
    p.SetMaxCondition(5000.0)
    p.SetTargetable(1)
    return p


def test_impulse_pods_attach_to_impulse_aggregator():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    for n in ("Port Impulse", "Star Impulse", "Center Impulse"):
        ps.AddToSet("Scene Root", _impulse_pod(n))
    ship.SetupProperties()

    imp = ship.GetImpulseEngineSubsystem()
    assert imp.GetNumChildSubsystems() == 3
    child = imp.GetChildSubsystem("Port Impulse")
    assert isinstance(child, ShipSubsystem)
    assert child.GetMaxCondition() == 2600.0


def test_warp_pods_attach_to_warp_aggregator():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    for n in ("Port Warp", "Star Warp"):
        ps.AddToSet("Scene Root", _warp_pod(n))
    ship.SetupProperties()

    warp = ship.GetWarpEngineSubsystem()
    assert warp.GetNumChildSubsystems() == 2
    assert warp.GetChildSubsystem("Star Warp") is not None


def test_engine_pods_idempotent_on_rerun():
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet("Scene Root", _impulse_pod("Port Impulse"))
    ship.SetupProperties()
    ship.SetupProperties()  # must not double-attach
    assert ship.GetImpulseEngineSubsystem().GetNumChildSubsystems() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_setup_properties_engine_pods.py -v`
Expected: FAIL — `GetNumChildSubsystems()` is 0 (pods never built).

- [ ] **Step 3: Add the engine-pod pass**

In `engine/appc/ships.py`, immediately **after** the Pass-4 weapon-child `for prop ...`
loop (the loop ending with the `break` at line 884), insert:

```python
        # Pass 5 — engine pods.  EngineProperty leaves attach to the matching
        # powered aggregator by EngineType (EP_IMPULSE -> impulse, EP_WARP ->
        # warp).  BC uses no dedicated engine-leaf class — pods are plain
        # ShipSubsystems (sdk/.../App.py declares EngineProperty but no
        # EngineSubsystem).  Idempotent: skip a parent already seeded with
        # children on a prior run.
        from engine.appc.properties import EngineProperty
        from engine.appc.subsystems import ShipSubsystem as _ShipSubsystem
        _engine_parent_for = {
            EngineProperty.EP_IMPULSE: self._impulse_engine_subsystem,
            EngineProperty.EP_WARP:    self._warp_engine_subsystem,
        }
        _engine_parents_seeded = {
            id(p) for p in _engine_parent_for.values()
            if p is not None and p.GetNumChildSubsystems() > 0
        }
        for prop in self.GetPropertySet().GetPropertyList():
            if type(prop) is not EngineProperty:
                continue
            parent = _engine_parent_for.get(prop.GetEngineType())
            if parent is None or id(parent) in _engine_parents_seeded:
                continue
            pod = _ShipSubsystem(prop.GetName() or "")
            pod.SetProperty(prop)
            mc = prop.GetMaxCondition()
            if mc is not None:
                pod.SetMaxCondition(mc)
            parent.AddChildSubsystem(pod)
```

Note: `pod.SetProperty(prop)` mirrors `Position` / `Position2D` onto the pod (see
`subsystems.py:462`); `AddChildSubsystem` sets the pod's `_parent_subsystem` so
`_climb_to_ship()` works for viewer placement.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_setup_properties_engine_pods.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_setup_properties_engine_pods.py
git commit -m "feat(ships): build engine pods as aggregator children

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Bridge (2nd hull) attaches as a child of the primary hull

`SetupProperties` keeps only the first `HullProperty` as the primary hull and drops the
rest. Attach the 2nd+ `HullProperty` ("Bridge", `Primary=0`, `Targetable=1`) as a child of
the primary hull. `GetHull()` must still return the primary.

**Files:**
- Modify: `engine/appc/ships.py:674-690` (the `elif isinstance(prop, HullProperty):` branch)
- Test: `tests/unit/test_setup_properties_bridge.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_setup_properties_bridge.py
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import HullProperty
from engine.appc.subsystems import HullSubsystem


def _hull(name, primary, condition):
    p = HullProperty(name)
    p.SetPrimary(primary)
    p.SetTargetable(1)
    p.SetMaxCondition(condition)
    return p


def test_primary_hull_is_first_and_returned_by_get_hull():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _hull("Hull", 1, 15000.0))
    ps.AddToSet("Scene Root", _hull("Bridge", 0, 12000.0))
    ship.SetupProperties()

    assert ship.GetHull().GetName() == "Hull"
    assert ship.GetHull().GetMaxCondition() == 15000.0


def test_bridge_is_a_child_of_the_primary_hull():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _hull("Hull", 1, 15000.0))
    ps.AddToSet("Scene Root", _hull("Bridge", 0, 12000.0))
    ship.SetupProperties()

    hull = ship.GetHull()
    assert hull.GetNumChildSubsystems() == 1
    bridge = hull.GetChildSubsystem("Bridge")
    assert isinstance(bridge, HullSubsystem)
    assert bridge.GetMaxCondition() == 12000.0


def test_bridge_idempotent_on_rerun():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _hull("Hull", 1, 15000.0))
    ps.AddToSet("Scene Root", _hull("Bridge", 0, 12000.0))
    ship.SetupProperties()
    ship.SetupProperties()
    assert ship.GetHull().GetNumChildSubsystems() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_setup_properties_bridge.py -v`
Expected: FAIL — `test_bridge_is_a_child_of_the_primary_hull` finds 0 children
(and the re-run test would otherwise mis-handle the primary on the 2nd pass).

- [ ] **Step 3: Rewrite the HullProperty branch**

Replace the existing branch (`engine/appc/ships.py:674-690`):

```python
            elif isinstance(prop, HullProperty):
                # Only the FIRST HullProperty is the main hull — galaxy.py
                # registers "Hull" first then "Bridge" as a child component.
                # GetHull() must return the primary hull (SDK App.py:5382).
                if self._hull is None:
                    self._hull = HullSubsystem(prop.GetName() or "Hull")
                    self._hull.SetProperty(prop)
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

with:

```python
            elif isinstance(prop, HullProperty):
                # The FIRST HullProperty is the primary hull; GetHull() must
                # return it (SDK App.py:5382). Additional HullProperties (e.g.
                # galaxy.py's non-primary "Bridge") attach as children of the
                # primary hull so they are damageable + viewer-visible. Plain
                # children of a targetable parent stay out of the AI loop.
                if self._hull is not None and self._hull.GetProperty() is prop:
                    pass  # re-run: primary already bound to this property
                else:
                    receiver = None
                    if self._hull is None:
                        self._hull = HullSubsystem(prop.GetName() or "Hull")
                        self._hull.SetProperty(prop)
                        receiver = self._hull
                    elif self._hull.GetChildSubsystem(prop.GetName()) is None:
                        receiver = HullSubsystem(prop.GetName() or "Bridge")
                        receiver.SetProperty(prop)
                        self._hull.AddChildSubsystem(receiver)
                    if receiver is not None:
                        for src, setter in (
                            (prop.GetMaxCondition,        receiver.SetMaxCondition),
                            (prop.GetCritical,            receiver.SetCritical),
                            (prop.GetTargetable,          receiver.SetTargetable),
                            (prop.GetPrimary,             receiver.SetPrimary),
                            (prop.GetRadius,              receiver.SetRadius),
                            (prop.GetDisabledPercentage,  receiver.SetDisabledPercentage),
                        ):
                            v = src()
                            if v is not None: setter(v)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_setup_properties_bridge.py tests/unit/test_setup_properties_hull.py -v`
Expected: PASS (new tests + the existing hull tests still green).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_setup_properties_bridge.py
git commit -m "feat(ships): attach secondary hull (bridge) under primary hull

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Object emitters become mount markers on the ship

`ObjectEmitterProperty` (Shuttle Bay, Probe Launcher) are not subsystems. Create a
lightweight `ObjectEmitter` runtime object, store them on the ship, and populate them in
`SetupProperties`.

**Files:**
- Create: `engine/appc/object_emitter.py`
- Modify: `engine/appc/ships.py:18-40` (`ShipClass.__init__`) — add `self._object_emitters = []`
- Modify: `engine/appc/ships.py` — `SetupProperties`, after the Pass-5 engine-pod loop (Task 2) — populate emitters; add `GetObjectEmitters()` accessor near `GetSubsystems` (line 567)
- Test: `tests/unit/test_object_emitters_built.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_object_emitters_built.py
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ObjectEmitterProperty
from engine.appc.math import TGPoint3
from engine.appc.object_emitter import ObjectEmitter


def _emitter(name, oep_type, x, y, z):
    p = ObjectEmitterProperty(name)
    pos = TGPoint3(); pos.SetXYZ(x, y, z)
    p.SetPosition(pos)
    p.SetEmittedObjectType(oep_type)
    return p


def test_emitters_populated_from_property_set():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root",
                _emitter("Shuttle Bay", ObjectEmitterProperty.OEP_SHUTTLE, 0.0, 0.05, 0.57))
    ps.AddToSet("Scene Root",
                _emitter("Probe Launcher", ObjectEmitterProperty.OEP_PROBE, 0.0, 3.29, 0.27))
    ship.SetupProperties()

    emitters = ship.GetObjectEmitters()
    assert len(emitters) == 2
    names = sorted(e.GetName() for e in emitters)
    assert names == ["Probe Launcher", "Shuttle Bay"]
    assert all(isinstance(e, ObjectEmitter) for e in emitters)
    shuttle = next(e for e in emitters if e.GetName() == "Shuttle Bay")
    assert shuttle.GetEmittedObjectType() == ObjectEmitterProperty.OEP_SHUTTLE
    assert abs(shuttle.GetPosition().y - 0.05) < 1e-6


def test_emitters_idempotent_on_rerun():
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet(
        "Scene Root",
        _emitter("Shuttle Bay", ObjectEmitterProperty.OEP_SHUTTLE, 0.0, 0.05, 0.57))
    ship.SetupProperties()
    ship.SetupProperties()
    assert len(ship.GetObjectEmitters()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_object_emitters_built.py -v`
Expected: FAIL — `engine.appc.object_emitter` does not exist / `GetObjectEmitters` missing.

- [ ] **Step 3a: Create the `ObjectEmitter` runtime class**

```python
# engine/appc/object_emitter.py
"""Runtime mount marker for an ObjectEmitterProperty (shuttle / probe / decoy
launch point). Not a ShipSubsystem: no condition, not targetable, not
damageable. Surfaced by the Ship Property Viewer as an informational mount
pin; excluded from the target list and damage panel.

See docs/superpowers/specs/2026-06-09-faithful-hardpoint-subsystem-loading-design.md
"""
from __future__ import annotations

from engine.appc.math import TGPoint3


class ObjectEmitter:
    def __init__(self, prop=None):
        self._property = prop
        self._name = prop.GetName() if (prop is not None and hasattr(prop, "GetName")) else ""
        self._position = TGPoint3(0.0, 0.0, 0.0)
        self._emitted_type = 0
        self._parent_ship = None
        if prop is not None:
            p = prop.GetPosition() if hasattr(prop, "GetPosition") else None
            if isinstance(p, TGPoint3):
                self._position = TGPoint3(p.x, p.y, p.z)
            if hasattr(prop, "GetEmittedObjectType"):
                t = prop.GetEmittedObjectType()
                if isinstance(t, int):
                    self._emitted_type = t

    def GetName(self) -> str:
        return self._name

    def GetProperty(self):
        return self._property

    def GetPosition(self) -> TGPoint3:
        # Local mount in body frame; the viewer rotates it into world space.
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    def GetEmittedObjectType(self) -> int:
        return self._emitted_type

    def GetParentShip(self):
        return self._parent_ship

    def SetParentShip(self, ship) -> None:
        self._parent_ship = ship
```

- [ ] **Step 3b: Add storage + accessor + population in `ShipClass`**

In `engine/appc/ships.py` `__init__` (near line 28, alongside the other subsystem slots),
add:

```python
        self._object_emitters = []
```

Add an accessor right after `GetSubsystems` (after line 587):

```python
    def GetObjectEmitters(self) -> list:
        """Return the ship's ObjectEmitter mount markers (shuttle/probe/decoy
        launch points). Not subsystems — viewer-only, never targetable."""
        return list(self._object_emitters)
```

In `SetupProperties`, **after** the Pass-5 engine-pod loop added in Task 2, append:

```python
        # Pass 6 — object emitters.  ObjectEmitterProperty templates become
        # ObjectEmitter mount markers (shuttle bay, probe launcher). Not
        # subsystems: no condition, not targetable. Idempotent by name.
        from engine.appc.properties import ObjectEmitterProperty
        from engine.appc.object_emitter import ObjectEmitter
        _existing_emitters = {e.GetName() for e in self._object_emitters}
        for prop in self.GetPropertySet().GetPropertyList():
            if not isinstance(prop, ObjectEmitterProperty):
                continue
            if (prop.GetName() or "") in _existing_emitters:
                continue
            emitter = ObjectEmitter(prop)
            emitter.SetParentShip(self)
            self._object_emitters.append(emitter)
            _existing_emitters.add(prop.GetName() or "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_object_emitters_built.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/object_emitter.py engine/appc/ships.py tests/unit/test_object_emitters_built.py
git commit -m "feat(ships): build ObjectEmitter mount markers from hardpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Tractor system surfaces in the viewer / damage panel

The tractor aggregator already builds with its 4 emitter children (proven by
`tests/integration/test_galaxy_hardpoint_emitters.py`), but `GetTractorBeamSystem` is
missing from `_DAMAGE_SOURCE_GETTERS`, so neither the aggregator nor its emitters appear in
the viewer or damage panel. This task pins that reality, then fixes the getter list.

**Files:**
- Modify: `engine/ui/ship_display_panel.py:423-435` (`_DAMAGE_SOURCE_GETTERS`)
- Test: `tests/unit/test_damage_source_getters_tractor.py` (create)

- [ ] **Step 1: Write the failing test (pins current state, then asserts the fix)**

```python
# tests/unit/test_damage_source_getters_tractor.py
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import WeaponSystemProperty, TractorBeamProperty
from engine.appc.subsystems import TractorBeam
from engine.ui.ship_display_panel import _iter_damage_subsystems


def _build_ship_with_tractors():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    agg = WeaponSystemProperty("Tractors")
    agg.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    ps.AddToSet("Scene Root", agg)
    ps.AddToSet("Scene Root", TractorBeamProperty("Aft Tractor 1"))
    ps.AddToSet("Scene Root", TractorBeamProperty("Forward Tractor 1"))
    ship.SetupProperties()
    return ship


def test_tractor_aggregator_survives_with_children():
    # Records reality: the aggregator + emitters DO build (the finding's
    # "stays None" claim is incorrect).
    ship = _build_ship_with_tractors()
    assert ship.GetTractorBeamSystem() is not None
    assert ship.GetTractorBeamSystem().GetNumChildSubsystems() == 2


def test_tractor_subsystems_appear_in_damage_iteration():
    ship = _build_ship_with_tractors()
    names = {s.GetName() for s in _iter_damage_subsystems(ship)}
    assert "Tractors" in names
    assert "Aft Tractor 1" in names
    assert "Forward Tractor 1" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_damage_source_getters_tractor.py -v`
Expected: `test_tractor_aggregator_survives_with_children` PASSES (reality check);
`test_tractor_subsystems_appear_in_damage_iteration` FAILS (tractors not in the getter list).

- [ ] **Step 3: Add `GetTractorBeamSystem` to the getter list**

In `engine/ui/ship_display_panel.py`, add the tractor getter to `_DAMAGE_SOURCE_GETTERS`
(insert after `"GetPulseWeaponSystem"`, line 434):

```python
_DAMAGE_SOURCE_GETTERS = (
    "GetHull",
    "GetSensorSubsystem",
    "GetShieldSubsystem",
    "GetImpulseEngineSubsystem",
    "GetWarpEngineSubsystem",
    "GetPowerSubsystem",
    "GetRepairSubsystem",
    "GetCloakingSubsystem",
    "GetPhaserSystem",
    "GetTorpedoSystem",
    "GetPulseWeaponSystem",
    "GetTractorBeamSystem",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_damage_source_getters_tractor.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/unit/test_damage_source_getters_tractor.py
git commit -m "fix(viewer): include tractor system in damage-source getters

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Property Viewer shows object emitters as mount pins

Engine pods and the bridge already flow into the viewer via Task 2/3 + the damage iterator
(their parents are in `_DAMAGE_SOURCE_GETTERS`). Object emitters are not subsystems, so add
a dedicated descriptor path for them in the viewer logic core.

**Files:**
- Modify: `engine/ui/ship_property_viewer.py:134-153` (`build_descriptors`)
- Test: `tests/ui/test_ship_property_viewer_emitters.py` (create — viewer tests live in `tests/ui/`)

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_ship_property_viewer_emitters.py
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ObjectEmitterProperty
from engine.appc.math import TGPoint3
from engine.ui.ship_property_viewer import build_descriptors


def _emitter_prop(name, x, y, z):
    p = ObjectEmitterProperty(name)
    pos = TGPoint3(); pos.SetXYZ(x, y, z)
    p.SetPosition(pos)
    p.SetEmittedObjectType(ObjectEmitterProperty.OEP_SHUTTLE)
    return p


def test_emitter_appears_as_mount_descriptor():
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet("Scene Root", _emitter_prop("Shuttle Bay", 0.0, 0.05, 0.57))
    ship.SetupProperties()

    descs = build_descriptors(ship)
    mounts = [d for d in descs if d.get("kind") == "mount"]
    assert len(mounts) == 1
    assert mounts[0]["name"] == "Shuttle Bay"
    assert mounts[0]["state"] == "mount"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer_emitters.py -v`
Expected: FAIL — no descriptor with `kind == "mount"`.

- [ ] **Step 3: Append mount descriptors in `build_descriptors`**

In `engine/ui/ship_property_viewer.py`, at the end of `build_descriptors` (before
`return out`, line 153), add:

```python
    # Object emitters — non-damageable mount markers (shuttle bay, probe
    # launcher). Distinct "mount" kind/state so the pin renderer can style
    # them apart from damageable subsystems; never targetable.
    emitters = ship.GetObjectEmitters() if hasattr(ship, "GetObjectEmitters") else []
    for em in emitters:
        local = em.GetPosition() if hasattr(em, "GetPosition") else None
        if local is None:
            continue
        w = subsystem_world_position(em, ship)
        out.append({
            "name":       em.GetName(),
            "icon_id":    6,            # damage_icons "System" fallback glyph
            "world_pos":  (w.x, w.y, w.z),
            "state":      "mount",
            "kind":       "mount",
            "properties": {"name": em.GetName(),
                           "emitted_type": em.GetEmittedObjectType()},
        })
```

(Leave the existing subsystem descriptor dict untouched so existing viewer tests that
assert its shape stay green — only the new `kind == "mount"` descriptors are added.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ui/test_ship_property_viewer_emitters.py tests/ui/test_ship_property_viewer.py -v`
Expected: PASS (new test + existing viewer tests still green).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py tests/ui/test_ship_property_viewer_emitters.py
git commit -m "feat(viewer): show object emitters as mount pins

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Target-menu builder recurses into child subsystems

Make `STTargetMenu.RebuildShipMenu` recurse into each subsystem's children (the canonical
`MissionLib.HideSubsystem` pattern) so aggregators carry nested child rows. `STMenu` (from
`engine.appc.characters`) already supports children via `AddChild` / `_children` /
`GetLabel` / `KillChildren` — no row-class change needed.

**Files:**
- Modify: `engine/appc/target_menu.py:130-162` — `RebuildShipMenu` (a method of `STTargetMenu`, the top-level menu; `GetObjectEntry` is also on `STTargetMenu`)
- Test: `tests/unit/test_target_menu_nested.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_target_menu_nested.py
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PhaserProperty, EngineProperty,
)
from engine.appc.target_menu import STTargetMenu


def _build_ship():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    phasers = WeaponSystemProperty("Phasers")
    phasers.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ps.AddToSet("Scene Root", phasers)
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 1"))
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 2"))
    imp = EngineProperty("Port Impulse")
    imp.SetEngineType(EngineProperty.EP_IMPULSE)
    ps.AddToSet("Scene Root", imp)
    ship.SetupProperties()
    return ship


def test_phaser_row_has_two_child_rows():
    menu = STTargetMenu("targets")
    ship = _build_ship()
    menu.RebuildShipMenu(ship)
    row = menu.GetObjectEntry(ship)        # the per-ship STSubsystemMenu
    labels = [c.GetLabel() for c in row._children]
    assert "Phasers" in labels
    phaser_row = next(c for c in row._children if c.GetLabel() == "Phasers")
    child_labels = sorted(gc.GetLabel() for gc in phaser_row._children)
    assert child_labels == ["Dorsal Phaser 1", "Dorsal Phaser 2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_nested.py -v`
Expected: FAIL — `phaser_row._children` is empty (builder is flat).

- [ ] **Step 3: Recurse in `RebuildShipMenu`**

Replace the iteration body of `RebuildShipMenu` (`engine/appc/target_menu.py:155-162`):

```python
        row.KillChildren()
        kIter = ship.StartGetSubsystemMatch(_App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(kIter)
        while sub is not None:
            label = sub.GetName() if hasattr(sub, "GetName") else ""
            row.AddChild(STMenu(label))
            sub = ship.GetNextSubsystemMatch(kIter)
        ship.EndGetSubsystemMatch(kIter)
```

with a version that recurses into children (mirrors `MissionLib.HideSubsystem:2172`):

```python
        row.KillChildren()
        kIter = ship.StartGetSubsystemMatch(_App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(kIter)
        while sub is not None:
            self._add_subsystem_row(row, sub)
            sub = ship.GetNextSubsystemMatch(kIter)
        ship.EndGetSubsystemMatch(kIter)

    def _add_subsystem_row(self, parent_row, sub):
        """Add a row for `sub` under `parent_row`, then recurse into its
        child subsystems so aggregators (Phasers, Impulse Engines, Tractors,
        ...) become expandable parents of their leaves."""
        label = sub.GetName() if hasattr(sub, "GetName") else ""
        sub_row = STMenu(label)
        parent_row.AddChild(sub_row)
        n = sub.GetNumChildSubsystems() if hasattr(sub, "GetNumChildSubsystems") else 0
        for i in range(n):
            child = sub.GetChildSubsystem(i)
            if child is not None:
                self._add_subsystem_row(sub_row, child)
```

`STMenu` is already imported in `target_menu.py` (line 12:
`from engine.appc.characters import STMenu, STTopLevelMenu`) and already has `AddChild` /
`_children` / `GetLabel` / `KillChildren`, so no row-class change is needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_nested.py tests/unit/test_target_menu_shim.py tests/unit/test_target_menu_bridge_subscription.py -v`
Expected: PASS (new test + existing target-menu tests still green).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/target_menu.py tests/unit/test_target_menu_nested.py
git commit -m "feat(target-menu): recurse into child subsystems

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `_resolve_subsystem_by_name` also searches children

A click on a nested leaf row sends its name; the resolver must find leaf subsystems, not
just top-level ones, to lock the subsystem target.

**Files:**
- Modify: `engine/ui/target_list_view.py:45-59` (`_resolve_subsystem_by_name`)
- Test: `tests/unit/test_resolve_subsystem_by_name.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_resolve_subsystem_by_name.py
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import WeaponSystemProperty, PhaserProperty
from engine.ui.target_list_view import _resolve_subsystem_by_name


def _ship():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ph = WeaponSystemProperty("Phasers")
    ph.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ps.AddToSet("Scene Root", ph)
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 1"))
    ship.SetupProperties()
    return ship


def test_resolves_top_level_subsystem():
    ship = _ship()
    assert _resolve_subsystem_by_name(ship, "Phasers") is not None


def test_resolves_child_leaf_subsystem():
    ship = _ship()
    leaf = _resolve_subsystem_by_name(ship, "Dorsal Phaser 1")
    assert leaf is not None
    assert leaf.GetName() == "Dorsal Phaser 1"


def test_unknown_name_returns_none():
    assert _resolve_subsystem_by_name(_ship(), "No Such System") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resolve_subsystem_by_name.py -v`
Expected: FAIL — `test_resolves_child_leaf_subsystem` returns None (resolver is top-level only).

- [ ] **Step 3: Recurse in the resolver**

Replace `_resolve_subsystem_by_name` (`engine/ui/target_list_view.py:45-59`):

```python
def _resolve_subsystem_by_name(ship, name: str):
    """Walk the ship's subsystems (and their children) and return the first
    whose GetName() matches. Returns None if no match — caller treats that
    as 'clear subsystem lock'."""
    import App

    def _search(sub):
        if hasattr(sub, "GetName") and sub.GetName() == name:
            return sub
        n = sub.GetNumChildSubsystems() if hasattr(sub, "GetNumChildSubsystems") else 0
        for i in range(n):
            child = sub.GetChildSubsystem(i)
            if child is not None:
                hit = _search(child)
                if hit is not None:
                    return hit
        return None

    it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
    try:
        sub = ship.GetNextSubsystemMatch(it)
        while sub is not None:
            hit = _search(sub)
            if hit is not None:
                return hit
            sub = ship.GetNextSubsystemMatch(it)
    finally:
        ship.EndGetSubsystemMatch(it)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resolve_subsystem_by_name.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/target_list_view.py tests/unit/test_resolve_subsystem_by_name.py
git commit -m "feat(target-list): resolve nested child subsystems by name

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: `TargetListView` snapshot carries nested children + per-subsystem expansion

Extend the panel snapshot so each subsystem row may carry `children` and an `expanded`
flag, and add a subsystem-level toggle action.

**Files:**
- Modify: `engine/ui/target_list_view.py` — `_snapshot` (lines 118-169), `render_payload` (171-195), `dispatch_event` (197-238); add `self._expanded_subsystems: set` in `__init__` (lines 108-116)
- Test: `tests/unit/test_target_list_view_nested.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_target_list_view_nested.py
from engine.ui.target_list_view import TargetListView


def test_subsystem_toggle_action_tracks_expansion():
    view = TargetListView()
    # Subsystem-level toggle: target/<ship>/<subsystem>/__toggle__
    handled = view.dispatch_event_subsystem_toggle("Enterprise", "Phasers")
    assert handled is True
    assert "Enterprise/Phasers" in view._expanded_subsystems
    # Toggling again collapses it.
    view.dispatch_event_subsystem_toggle("Enterprise", "Phasers")
    assert "Enterprise/Phasers" not in view._expanded_subsystems
```

(`dispatch_event_subsystem_toggle` is a small helper the real `dispatch_event` delegates to;
testing it directly avoids needing a live `Game`/`STTargetMenu`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_list_view_nested.py -v`
Expected: FAIL — `dispatch_event_subsystem_toggle` / `_expanded_subsystems` do not exist.

- [ ] **Step 3a: Track expanded subsystems in `__init__`**

In `TargetListView.__init__` (after `self._expanded_ships: set = set()`, line 116):

```python
        # Keys are "<ship-name>/<subsystem-name>" for subsystem rows whose
        # child leaves are expanded in the panel (second accordion level).
        self._expanded_subsystems: set = set()
```

- [ ] **Step 3b: Add the toggle helper + wire it into `dispatch_event`**

Add the helper method to `TargetListView`:

```python
    def dispatch_event_subsystem_toggle(self, ship_name: str, subsystem_name: str) -> bool:
        """Toggle the expansion of a subsystem (aggregator) row. Pure UI
        state, no target change."""
        key = ship_name + "/" + subsystem_name
        if key in self._expanded_subsystems:
            self._expanded_subsystems.discard(key)
        else:
            self._expanded_subsystems.add(key)
        return True
```

In `dispatch_event`, after the `ship_name, suffix` split (line 211-214), handle the
subsystem-level toggle. The action shape is `target/<ship>/<subsystem>/__toggle__`, which
arrives here (the registry strips the `target/` prefix) as `ship_name="<ship>"`,
`suffix="<subsystem>/__toggle__"`. Add, immediately after the existing ship-level
`if suffix == self._TOGGLE_ACTION:` block (line 217-222):

```python
        # Subsystem-level accordion toggle: "<subsystem>/__toggle__".
        if suffix is not None and suffix.endswith("/" + self._TOGGLE_ACTION):
            subsystem_name = suffix[: -(len(self._TOGGLE_ACTION) + 1)]
            return self.dispatch_event_subsystem_toggle(ship_name, subsystem_name)
```

- [ ] **Step 3c: Emit nested children in the snapshot + payload**

In `_snapshot` (line 144-149), replace the flat `subsystems` comprehension with one that
walks the nested menu rows and attaches children + expansion state. Replace:

```python
                    subsystems = tuple(
                        (sub_child.GetLabel(),
                         _query_subsystem_condition(ship, sub_child.GetLabel()))
                        for sub_child in child._children
                    )
```

with:

```python
                    ship_name_for_keys = ship.GetName()
                    def _sub_entry(sub_child):
                        label = sub_child.GetLabel()
                        cond = _query_subsystem_condition(ship, label)
                        kids = tuple(
                            (gc.GetLabel(), _query_subsystem_condition(ship, gc.GetLabel()))
                            for gc in getattr(sub_child, "_children", ())
                        )
                        expanded = (ship_name_for_keys + "/" + label) in self._expanded_subsystems
                        return (label, cond, kids, expanded)
                    subsystems = tuple(_sub_entry(sub_child) for sub_child in child._children)
```

In `render_payload` (line 186-188), replace the `subsystems` serialization to carry the
new fields:

```python
                    "subsystems": [
                        {"name": s_name, "condition": s_cond,
                         "expanded": s_expanded,
                         "children": [{"name": c_name, "condition": c_cond}
                                      for (c_name, c_cond) in s_kids]}
                        for (s_name, s_cond, s_kids, s_expanded) in subs
                    ],
```

(The `subs` tuples now have four fields; the row-unpacking at line 191
`for (name, aff, is_vis, hull, shields, subs, expanded) in rows` is unchanged — only the
shape of each `subs` element changed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_list_view_nested.py tests/unit/test_target_list_view.py -v`
(Find the existing view test filename with `ls tests/unit | grep target_list`.)
Expected: PASS (new test + existing view tests still green).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/target_list_view.py tests/unit/test_target_list_view_nested.py
git commit -m "feat(target-list): nested subsystem children + expansion state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Render nested subsystem children in the CEF target list

Update `target_list.js` to render child rows (with their own caret + toggle) under an
expanded subsystem row, and add a nested-indent CSS style. This is verified manually in the
running app (no pytest).

**Files:**
- Modify: `native/assets/ui-cef/js/target_list.js:103-122` (subsystem render loop)
- Modify: target-list CSS — find with `grep -rln "target-list__sub" native/assets/ui-cef/css/`

- [ ] **Step 1: Render subsystem-level caret + nested children**

In `target_list.js`, replace the subsystem render block (lines 105-122, the
`if (expanded) { ... }` body) with one that renders a caret for subsystems that have
children, a subsystem toggle, and nested child rows when the subsystem is expanded:

```javascript
        if (expanded) {
            const subs = row.subsystems || [];
            for (let j = 0; j < subs.length; j++) {
                const sub = subs[j];
                const subName = String(sub.name || '');
                const subCondition = (typeof sub.condition === 'number') ? sub.condition : 100;
                const subExpanded = !!sub.expanded;
                const subChildren = sub.children || [];
                const hasChildren = subChildren.length > 0;
                const subChosen = (selected === name && selectedSub === subName)
                    ? ' target-list__sub--chosen' : '';
                const subAttr = clickAttr('target/' + name + '/' + subName);
                const subToggleAttr = clickAttr('target/' + name + '/' + subName + '/__toggle__');
                const subCaret = hasChildren
                    ? '<span class="target-list__sub-caret"'
                      + ' onclick="event.stopPropagation();' + subToggleAttr + '">'
                      + (subExpanded ? '&#9662;' : '&#9656;') + '</span>'
                    : '<span class="target-list__sub-bullet">&#8226;</span>';
                html += '<div class="target-list__sub target-list__sub--' + aff + subChosen + '"'
                      +   ' onclick="' + subAttr + '">'
                      +   subCaret
                      +   '<span class="target-list__sub-name">' + escapeHtml(subName) + '</span>'
                      +   '<span class="target-list__sub-bar"'
                      +   ' style="--bar-pct:' + subCondition + '%"></span>'
                      + '</div>';

                // Nested leaf rows (banks / tubes / pods / nacelles / emitters).
                if (subExpanded && hasChildren) {
                    for (let k = 0; k < subChildren.length; k++) {
                        const leaf = subChildren[k];
                        const leafName = String(leaf.name || '');
                        const leafCond = (typeof leaf.condition === 'number') ? leaf.condition : 100;
                        const leafChosen = (selected === name && selectedSub === leafName)
                            ? ' target-list__leaf--chosen' : '';
                        const leafAttr = clickAttr('target/' + name + '/' + leafName);
                        html += '<div class="target-list__leaf target-list__leaf--' + aff + leafChosen + '"'
                              +   ' onclick="' + leafAttr + '">'
                              +   '<span class="target-list__leaf-bullet">&#8226;</span>'
                              +   '<span class="target-list__leaf-name">' + escapeHtml(leafName) + '</span>'
                              +   '<span class="target-list__leaf-bar"'
                              +   ' style="--bar-pct:' + leafCond + '%"></span>'
                              + '</div>';
                    }
                }
            }
        }
```

- [ ] **Step 2: Add nested-indent CSS**

In the target-list CSS file (located in Step 1's grep), add a `.target-list__leaf` block
that indents one level deeper than `.target-list__sub` (copy the `.target-list__sub`
rule's padding-left and increase it; copy `--bar` styling for `.target-list__leaf-bar`).
Match the existing indentation/colour variables used by `.target-list__sub`.

- [ ] **Step 3: Build and run the app to verify manually**

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```

Load a mission with the Galaxy, open the target list, expand the player/enemy ship, then
expand an aggregator row (e.g. "Phasers", "Impulse Engines", "Tractors"). Verify:
- Aggregators with children show a caret; expanding reveals the leaves.
- Clicking a leaf (e.g. "Port Warp") locks it as the subsystem target.
- Leaf condition bars render and indent one level deeper than the aggregator.

(Per the project memory, shader edits need a `cmake` reconfigure; JS/CSS assets do not — a
re-run of `./build/dauntless` picks them up.)

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/js/target_list.js native/assets/ui-cef/css/
git commit -m "feat(target-list): render nested subsystem children in CEF

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: End-to-end integration assertions on the real Galaxy hardpoint

Extend the canonical Galaxy integration fixture so the full faithful-loading contract is
proven against the real hardpoint data, not just synthetic property sets.

**Files:**
- Modify: `tests/integration/test_galaxy_hardpoint_emitters.py` (append tests; reuse the existing `galaxy_ship` fixture)

- [ ] **Step 1: Append the failing integration tests**

```python
# append to tests/integration/test_galaxy_hardpoint_emitters.py
from engine.appc.subsystems import ShipSubsystem, HullSubsystem
from engine.appc.object_emitter import ObjectEmitter


def test_galaxy_impulse_aggregator_has_three_pods(galaxy_ship):
    imp = galaxy_ship.GetImpulseEngineSubsystem()
    names = sorted(imp.GetChildSubsystem(i).GetName()
                   for i in range(imp.GetNumChildSubsystems()))
    assert names == ["Center Impulse", "Port Impulse", "Star Impulse"]


def test_galaxy_warp_aggregator_has_two_nacelles(galaxy_ship):
    warp = galaxy_ship.GetWarpEngineSubsystem()
    names = sorted(warp.GetChildSubsystem(i).GetName()
                   for i in range(warp.GetNumChildSubsystems()))
    assert names == ["Port Warp", "Star Warp"]


def test_galaxy_port_warp_condition_matches_hardpoint(galaxy_ship):
    warp = galaxy_ship.GetWarpEngineSubsystem()
    port = warp.GetChildSubsystem("Port Warp")
    assert isinstance(port, ShipSubsystem)
    assert port.GetMaxCondition() == 5000.0  # galaxy.py:909


def test_galaxy_bridge_is_child_of_hull(galaxy_ship):
    hull = galaxy_ship.GetHull()
    assert hull.GetName() == "Hull"
    bridge = hull.GetChildSubsystem("Bridge")
    assert isinstance(bridge, HullSubsystem)
    assert bridge.GetMaxCondition() == 12000.0  # galaxy.py:1108


def test_galaxy_has_two_object_emitters(galaxy_ship):
    names = sorted(e.GetName() for e in galaxy_ship.GetObjectEmitters())
    assert names == ["Probe Launcher", "Shuttle Bay"]
    assert all(isinstance(e, ObjectEmitter) for e in galaxy_ship.GetObjectEmitters())
```

- [ ] **Step 2: Run the integration file to verify pass**

Run: `uv run pytest tests/integration/test_galaxy_hardpoint_emitters.py -v`
Expected: PASS (existing + new). If any fail, the failure pinpoints which construction pass
regressed against real data.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_galaxy_hardpoint_emitters.py
git commit -m "test(galaxy): integration coverage for pods, bridge, emitters

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the focused suites touched by this work together:

```bash
uv run pytest \
  tests/unit/test_engine_property_type.py \
  tests/unit/test_setup_properties_engine_pods.py \
  tests/unit/test_setup_properties_bridge.py \
  tests/unit/test_setup_properties_hull.py \
  tests/unit/test_object_emitters_built.py \
  tests/unit/test_damage_source_getters_tractor.py \
  tests/ui/test_ship_property_viewer_emitters.py \
  tests/unit/test_target_menu_nested.py \
  tests/unit/test_resolve_subsystem_by_name.py \
  tests/unit/test_target_list_view_nested.py \
  tests/integration/test_galaxy_hardpoint_emitters.py \
  -v
```

Expected: all PASS. **Do not run the full suite** — it OOMs the host.

- [ ] Manual app check (from Task 10) confirms pods/nacelles/bridge appear in the Property
  Viewer and the hierarchical target menu, and emitters appear as mount pins.

- [ ] Confirm the deferred follow-up doc
  (`docs/superpowers/specs/2026-06-09-subsystem-targetability-fidelity-followup.md`) is
  still accurate and unaddressed (AI targeting intentionally unchanged).
