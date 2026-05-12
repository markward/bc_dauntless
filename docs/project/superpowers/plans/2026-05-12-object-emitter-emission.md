# Object emitter emission — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `App.ObjectEmitterProperty_Create` a real factory, give `ObjectEmitterProperty` real storage, and install a `LaunchObject` hook that resolves the right emitter, computes the world-frame transform, and records the event via a new `_emission_recorder` singleton. No real Shuttle/Probe/Decoy spawning.

**Architecture:** Three layers — (1) real `ObjectEmitterProperty` data property plus factory and `Cast`, (2) `_EmissionRecorder` singleton on `App`, (3) `Actions.ShipScriptActions.LaunchObject` replaced by an engine wrapper that records instead of spawning. Hook installed once by `tools/mission_harness.setup_sdk()`.

**Tech Stack:** Python 3, pytest. SDK scripts run via `tools/mission_harness._SDKFinder`. Math primitives in `engine/appc/math.py`.

**Spec:** [docs/project/superpowers/specs/2026-05-12-object-emitter-emission-design.md](../specs/2026-05-12-object-emitter-emission-design.md).

---

## Task 1: ObjectEmitterProperty storage + OEP_* constants + accessors

**Files:**
- Modify: [engine/appc/properties.py](../../../engine/appc/properties.py) — replace empty `ObjectEmitterProperty` class
- Test: [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py) — new file

- [ ] **Step 1: Write the failing test**

Create [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py):

```python
from engine.appc.properties import ObjectEmitterProperty
from engine.appc.math import TGPoint3


def test_oep_constants_distinct_integers():
    assert isinstance(ObjectEmitterProperty.OEP_UNKNOWN, int)
    assert isinstance(ObjectEmitterProperty.OEP_SHUTTLE, int)
    assert isinstance(ObjectEmitterProperty.OEP_PROBE, int)
    assert isinstance(ObjectEmitterProperty.OEP_DECOY, int)
    constants = {
        ObjectEmitterProperty.OEP_UNKNOWN,
        ObjectEmitterProperty.OEP_SHUTTLE,
        ObjectEmitterProperty.OEP_PROBE,
        ObjectEmitterProperty.OEP_DECOY,
    }
    assert len(constants) == 4


def test_default_state():
    p = ObjectEmitterProperty("Shuttle Bay")
    assert p.GetName() == "Shuttle Bay"
    assert p.GetEmittedObjectType() == ObjectEmitterProperty.OEP_UNKNOWN
    assert p.GetPosition() is None
    assert p.GetForward() is None
    assert p.GetUp() is None
    assert p.GetRight() is None


def test_set_emitted_object_type_round_trip():
    p = ObjectEmitterProperty("Probe Launcher")
    p.SetEmittedObjectType(ObjectEmitterProperty.OEP_PROBE)
    assert p.GetEmittedObjectType() == ObjectEmitterProperty.OEP_PROBE


def test_set_position_round_trip_and_copy_semantics():
    p = ObjectEmitterProperty("Shuttle Bay")
    src = TGPoint3(1.0, 2.0, 3.0)
    p.SetPosition(src)
    src.SetXYZ(99.0, 99.0, 99.0)  # mutate source after set
    got = p.GetPosition()
    assert (got.x, got.y, got.z) == (1.0, 2.0, 3.0)
    got.SetXYZ(77.0, 77.0, 77.0)  # mutate returned copy
    got2 = p.GetPosition()
    assert (got2.x, got2.y, got2.z) == (1.0, 2.0, 3.0)


def test_set_orientation_round_trip_and_copy_semantics():
    p = ObjectEmitterProperty("Shuttle Bay")
    fwd = TGPoint3(0.0, 1.0, 0.0)
    up  = TGPoint3(0.0, 0.0, 1.0)
    right = TGPoint3(1.0, 0.0, 0.0)
    p.SetOrientation(fwd, up, right)
    fwd.SetXYZ(9.0, 9.0, 9.0)
    up.SetXYZ(9.0, 9.0, 9.0)
    right.SetXYZ(9.0, 9.0, 9.0)
    assert (p.GetForward().x, p.GetForward().y, p.GetForward().z) == (0.0, 1.0, 0.0)
    assert (p.GetUp().x,      p.GetUp().y,      p.GetUp().z)      == (0.0, 0.0, 1.0)
    assert (p.GetRight().x,   p.GetRight().y,   p.GetRight().z)   == (1.0, 0.0, 0.0)
    # Returned values are fresh copies
    got = p.GetForward()
    got.SetXYZ(5.0, 5.0, 5.0)
    assert (p.GetForward().x, p.GetForward().y, p.GetForward().z) == (0.0, 1.0, 0.0)
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
uv run pytest tests/unit/test_object_emitter_property.py -v
```

Expected: 5 tests fail with `AttributeError: type object 'ObjectEmitterProperty' has no attribute 'OEP_UNKNOWN'` (or similar — the class is currently empty).

- [ ] **Step 3: Implement storage + constants + accessors**

Edit [engine/appc/properties.py](../../../engine/appc/properties.py). Replace the existing `ObjectEmitterProperty` block (the one with the stale Phase-1 docstring) with:

```python
class ObjectEmitterProperty(PositionOrientationProperty):
    """Emitter point on a hull (shuttle / probe / decoy launch position).

    SDK hierarchy: ObjectEmitterProperty extends PositionOrientationProperty.
    Hardpoint scripts populate position, orientation, and emitted object type
    via SetPosition / SetOrientation / SetEmittedObjectType; the LaunchObject
    action reads them back to compute world-frame launch transforms.
    """

    OEP_UNKNOWN = 0
    OEP_SHUTTLE = 1
    OEP_PROBE   = 2
    OEP_DECOY   = 3

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._forward = None
        self._up = None
        self._right = None
        self._position = None
        self._emitted_type = self.OEP_UNKNOWN

    def SetOrientation(self, fwd, up, right):
        self._forward = _copy_point(fwd)
        self._up = _copy_point(up)
        self._right = _copy_point(right)

    def GetForward(self):
        return _copy_point(self._forward)

    def GetUp(self):
        return _copy_point(self._up)

    def GetRight(self):
        return _copy_point(self._right)

    def SetPosition(self, p):
        self._position = _copy_point(p)

    def GetPosition(self):
        return _copy_point(self._position)

    def SetEmittedObjectType(self, t):
        self._emitted_type = int(t)

    def GetEmittedObjectType(self):
        return self._emitted_type
```

Add `_copy_point` helper near the top of the file (next to `_hashable_key` at line 54):

```python
def _copy_point(p):
    """Fresh TGPoint3 copy, or None if the source is None.

    Matches SDK semantics where Get*() returns a copy callers can mutate
    (e.g. via MultMatrixLeft) without affecting the template.
    """
    if p is None:
        return None
    from engine.appc.math import TGPoint3
    return TGPoint3(p.x, p.y, p.z)
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
uv run pytest tests/unit/test_object_emitter_property.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_object_emitter_property.py engine/appc/properties.py
git commit -m "feat(appc): real ObjectEmitterProperty storage + OEP_* constants

Replaces the empty Phase-1 placeholder. SetPosition/SetOrientation/
SetEmittedObjectType now round-trip with copy semantics; getters
return fresh TGPoint3 copies callers can transform without mutating
the template.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: ObjectEmitterProperty_Create factory + Cast + App.py wiring

**Files:**
- Modify: [engine/appc/properties.py](../../../engine/appc/properties.py) — add factory and Cast at module level
- Modify: [App.py](../../../App.py) — import factory and Cast
- Test: [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py) — extend with factory/Cast tests

- [ ] **Step 1: Write the failing tests**

Append to [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py):

```python
import App
from engine.appc.properties import ObjectEmitterProperty_Create, ObjectEmitterProperty_Cast
from engine.appc.properties import ShieldProperty


def test_factory_returns_real_instance():
    p = ObjectEmitterProperty_Create("Probe Launcher")
    assert isinstance(p, ObjectEmitterProperty)
    assert p.GetName() == "Probe Launcher"


def test_app_exposes_factory_and_cast():
    p = App.ObjectEmitterProperty_Create("Decoy launcher")
    assert isinstance(p, ObjectEmitterProperty)
    cast_back = App.ObjectEmitterProperty_Cast(p)
    assert cast_back is p


def test_cast_rejects_named_stub():
    stub = App._NamedStub("not-an-emitter")
    assert ObjectEmitterProperty_Cast(stub) is None
    assert App.ObjectEmitterProperty_Cast(stub) is None


def test_cast_rejects_unrelated_property():
    shield = ShieldProperty("Shield")
    assert ObjectEmitterProperty_Cast(shield) is None


def test_cast_passes_none_through():
    assert ObjectEmitterProperty_Cast(None) is None
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
uv run pytest tests/unit/test_object_emitter_property.py -v
```

Expected: 5 new tests fail with `ImportError` (factory/Cast not defined) or `AttributeError` on `App.ObjectEmitterProperty_Create`.

- [ ] **Step 3: Add factory + Cast in properties.py**

Append at the end of [engine/appc/properties.py](../../../engine/appc/properties.py):

```python
def ObjectEmitterProperty_Create(name):
    return ObjectEmitterProperty(name)


def ObjectEmitterProperty_Cast(obj):
    """Lenient pass-through: returns obj if it's an ObjectEmitterProperty, else None.

    Rejects _NamedStub explicitly so undefined-attribute chains don't slip
    through and keep producing stub-tracker hits.
    """
    if obj is None:
        return None
    import App
    if isinstance(obj, App._NamedStub):
        return None
    if isinstance(obj, ObjectEmitterProperty):
        return obj
    return None
```

- [ ] **Step 4: Wire into App.py**

In [App.py](../../../App.py), locate the `from engine.appc.properties import (...)` block at lines 106-133. Add `ObjectEmitterProperty_Create` and `ObjectEmitterProperty_Cast` to the imported names, e.g. after `WeaponSystemProperty_Create,` on line 131:

```python
from engine.appc.properties import (
    ...
    WeaponSystemProperty_Create,
    CloakingSubsystemProperty_Create,
    ObjectEmitterProperty_Create,
    ObjectEmitterProperty_Cast,
)
```

(Keep alphabetical or grouped consistency with the existing block — append to the end of the import is fine.)

- [ ] **Step 5: Run the tests, verify they pass**

```bash
uv run pytest tests/unit/test_object_emitter_property.py -v
```

Expected: all 10 tests pass (5 from Task 1 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_object_emitter_property.py engine/appc/properties.py App.py
git commit -m "feat(appc): ObjectEmitterProperty_Create factory + Cast wired into App

Mirrors the pattern used by sibling properties (ShieldProperty_Create
etc.). Cast rejects _NamedStub so undefined-attribute chains can't
slip through and keep producing stub-tracker hits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Property-manager registration round-trip + stub-tracker regression

**Files:**
- Test: [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py) — extend

No production code changes — Tasks 1+2 should already make these pass.

- [ ] **Step 1: Write the failing tests**

Append to [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py):

```python
def test_register_local_template_findable_by_name():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    emitter = App.ObjectEmitterProperty_Create("Probe Launcher")
    emitter.SetEmittedObjectType(ObjectEmitterProperty.OEP_PROBE)
    App.g_kModelPropertyManager.RegisterLocalTemplate(emitter)
    found = App.g_kModelPropertyManager.FindByName(
        "Probe Launcher", App.TGModelPropertyManager.LOCAL_TEMPLATES
    )
    assert found is emitter
    assert found.GetEmittedObjectType() == ObjectEmitterProperty.OEP_PROBE
    App.g_kModelPropertyManager.ClearLocalTemplates()


def test_sovereign_hardpoint_load_no_stub_tracker_rows():
    """Loading the sovereign hardpoint should not produce any
    ObjectEmitterProperty_Create* entries in the stub tracker."""
    import importlib
    import sys
    import tools.mission_harness as mh

    App._stub_tracker.clear()
    App._stub_tracker.set_mission("test")
    try:
        mh.setup_sdk()
        # Force fresh import so the hardpoint module body runs
        sys.modules.pop("ships.Hardpoints.sovereign", None)
        importlib.import_module("ships.Hardpoints.sovereign")
    finally:
        App._stub_tracker.reset_mission()

    names = {row[0] for row in App._stub_tracker.report()}
    leaks = {n for n in names if n.startswith("ObjectEmitterProperty_Create")}
    assert leaks == set(), f"unexpected stub-tracker rows: {sorted(leaks)}"
```

- [ ] **Step 2: Run the tests, verify they pass**

```bash
uv run pytest tests/unit/test_object_emitter_property.py -v
```

Expected: all 12 tests pass (10 from Tasks 1+2 + 2 new). If `test_sovereign_hardpoint_load_no_stub_tracker_rows` fails, it means an emitter call is still falling through to `_NamedStub` — diagnose by printing the leaked names and fixing the missing method on `ObjectEmitterProperty`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_object_emitter_property.py
git commit -m "test(appc): property-manager registration + sovereign hardpoint regression

Locks in that the 451-call ObjectEmitterProperty_Create* stub-tracker
rows are gone for sovereign's four emitters, and that
FindByName(\"Probe Launcher\", LOCAL_TEMPLATES) returns the registered
template (which was always None before because the dict key was a
_NamedStub).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: TGPoint3.MultMatrixLeft in-place transform

**Files:**
- Modify: [engine/appc/math.py](../../../engine/appc/math.py) — add method on `TGPoint3`
- Test: [tests/unit/test_math.py](../../../tests/unit/test_math.py) — extend

Background: the SDK pattern `vec.MultMatrixLeft(matrix)` mutates `vec` to be `matrix * vec` (column-vector convention). Used in [Actions/ShipScriptActions.py:509-514](../../../sdk/Build/scripts/Actions/ShipScriptActions.py) and many other SDK call sites. Missing from `engine/appc/math.py:TGPoint3` today.

- [ ] **Step 1: Write the failing test**

Append to [tests/unit/test_math.py](../../../tests/unit/test_math.py):

```python
def test_tgpoint3_mult_matrix_left_in_place():
    from engine.appc.math import TGPoint3, TGMatrix3
    p = TGPoint3(1.0, 2.0, 3.0)
    R = TGMatrix3()
    # Identity → no change
    p.MultMatrixLeft(R)
    assert (p.x, p.y, p.z) == (1.0, 2.0, 3.0)


def test_tgpoint3_mult_matrix_left_matches_mult_point():
    """vec.MultMatrixLeft(R) must equal R.MultPoint(vec)."""
    from engine.appc.math import TGPoint3, TGMatrix3
    p = TGPoint3(1.0, 2.0, 3.0)
    R = TGMatrix3()
    # Build a non-identity rotation: 90° about z so x→y, y→-x
    R.SetRow(0, TGPoint3(0.0, -1.0, 0.0))
    R.SetRow(1, TGPoint3(1.0,  0.0, 0.0))
    R.SetRow(2, TGPoint3(0.0,  0.0, 1.0))

    expected = R.MultPoint(p)
    p.MultMatrixLeft(R)
    assert abs(p.x - expected.x) < 1e-9
    assert abs(p.y - expected.y) < 1e-9
    assert abs(p.z - expected.z) < 1e-9


def test_tgpoint3_mult_matrix_left_returns_self_for_chaining_optional():
    """Either returns self or returns None; both are fine. Document choice."""
    from engine.appc.math import TGPoint3, TGMatrix3
    p = TGPoint3(1.0, 2.0, 3.0)
    R = TGMatrix3()
    result = p.MultMatrixLeft(R)
    assert result is None or result is p
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
uv run pytest tests/unit/test_math.py -v -k mult_matrix_left
```

Expected: 3 new tests fail with `AttributeError: 'TGPoint3' object has no attribute 'MultMatrixLeft'`.

- [ ] **Step 3: Add MultMatrixLeft to TGPoint3**

In [engine/appc/math.py](../../../engine/appc/math.py), add to the `TGPoint3` class (place it after `Set(self, other)` around line 78):

```python
    def MultMatrixLeft(self, matrix: "TGMatrix3") -> None:
        """In-place transform by matrix: self = matrix · self (column-vector).

        Matches SDK NiPoint3.MultMatrixLeft semantics. Returns None.
        """
        x = matrix._m[0][0] * self.x + matrix._m[0][1] * self.y + matrix._m[0][2] * self.z
        y = matrix._m[1][0] * self.x + matrix._m[1][1] * self.y + matrix._m[1][2] * self.z
        z = matrix._m[2][0] * self.x + matrix._m[2][1] * self.y + matrix._m[2][2] * self.z
        self.x = x
        self.y = y
        self.z = z
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
uv run pytest tests/unit/test_math.py -v -k mult_matrix_left
```

Expected: all 3 new tests pass.

- [ ] **Step 5: Run full math test module to confirm no regression**

```bash
uv run pytest tests/unit/test_math.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_math.py engine/appc/math.py
git commit -m "feat(math): TGPoint3.MultMatrixLeft in-place transform

SDK pattern vec.MultMatrixLeft(R) mutates vec to R*vec (column-vector
convention). Needed by the upcoming LaunchObject emission hook and
already called from many SDK scripts (MissionLib, AI/Preprocessors,
mission scripts).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: _EmissionRecorder singleton on App

**Files:**
- Modify: [App.py](../../../App.py) — add class + singleton next to `_stub_tracker`
- Test: [tests/unit/test_emission_recorder.py](../../../tests/unit/test_emission_recorder.py) — new file

- [ ] **Step 1: Write the failing tests**

Create [tests/unit/test_emission_recorder.py](../../../tests/unit/test_emission_recorder.py):

```python
import App


def _reset_recorder():
    App._emission_recorder.disable()
    App._emission_recorder.reset_mission()
    App._emission_recorder.clear()


def test_recorder_disabled_by_default():
    _reset_recorder()
    assert App._emission_recorder.is_enabled() is False


def test_record_is_noop_when_disabled():
    _reset_recorder()
    from engine.appc.math import TGPoint3
    p = TGPoint3(1.0, 2.0, 3.0)
    fwd = TGPoint3(0.0, 1.0, 0.0)
    up = TGPoint3(0.0, 0.0, 1.0)
    App._emission_recorder.record(123, "Shuttle Bay", 1, p, fwd, up)
    assert App._emission_recorder.events() == []


def test_record_when_enabled_captures_event():
    _reset_recorder()
    App._emission_recorder.enable()
    App._emission_recorder.set_mission("mission.M1")
    from engine.appc.math import TGPoint3
    p = TGPoint3(1.0, 2.0, 3.0)
    fwd = TGPoint3(0.0, 1.0, 0.0)
    up = TGPoint3(0.0, 0.0, 1.0)
    App._emission_recorder.record(123, "Shuttle Bay", 1, p, fwd, up)
    events = App._emission_recorder.events()
    assert len(events) == 1
    e = events[0]
    assert e["mission"] == "mission.M1"
    assert e["ship_id"] == 123
    assert e["emitter_name"] == "Shuttle Bay"
    assert e["emitter_type"] == 1
    assert e["world_position"] == (1.0, 2.0, 3.0)
    assert e["world_forward"] == (0.0, 1.0, 0.0)
    assert e["world_up"] == (0.0, 0.0, 1.0)
    _reset_recorder()


def test_events_returns_a_copy():
    _reset_recorder()
    App._emission_recorder.enable()
    from engine.appc.math import TGPoint3
    App._emission_recorder.record(1, "n", 1, TGPoint3(), TGPoint3(), TGPoint3())
    snapshot = App._emission_recorder.events()
    App._emission_recorder.record(2, "n2", 2, TGPoint3(), TGPoint3(), TGPoint3())
    # Original snapshot must not have grown
    assert len(snapshot) == 1
    _reset_recorder()


def test_clear_empties_events():
    _reset_recorder()
    App._emission_recorder.enable()
    from engine.appc.math import TGPoint3
    App._emission_recorder.record(1, "n", 1, TGPoint3(), TGPoint3(), TGPoint3())
    assert len(App._emission_recorder.events()) == 1
    App._emission_recorder.clear()
    assert App._emission_recorder.events() == []
    _reset_recorder()
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
uv run pytest tests/unit/test_emission_recorder.py -v
```

Expected: 5 tests fail with `AttributeError: module 'App' has no attribute '_emission_recorder'`.

- [ ] **Step 3: Add _EmissionRecorder to App.py**

In [App.py](../../../App.py), locate the `_color_consumer_tracker = _ColorConsumerTracker()` line (around line 615) and add immediately after it:

```python
# ── Emission recorder ─────────────────────────────────────────────────────────
# Captures shuttle / probe / decoy launch events when the
# Actions.ShipScriptActions.LaunchObject hook (engine/appc/emission.py) is
# installed. Off by default; tests and the harness opt in.
class _EmissionRecorder:
    def __init__(self):
        self._enabled = False
        self._mission = None
        self._events = []

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def is_enabled(self):
        return self._enabled

    def set_mission(self, name):
        self._mission = name

    def reset_mission(self):
        self._mission = None

    def record(self, ship_id, emitter_name, emitter_type,
               world_position, world_forward, world_up):
        if not self._enabled:
            return
        self._events.append({
            "mission": self._mission,
            "ship_id": ship_id,
            "emitter_name": emitter_name,
            "emitter_type": emitter_type,
            "world_position": (world_position.x, world_position.y, world_position.z),
            "world_forward":  (world_forward.x,  world_forward.y,  world_forward.z),
            "world_up":       (world_up.x,       world_up.y,       world_up.z),
        })

    def events(self):
        return list(self._events)

    def clear(self):
        self._events = []


_emission_recorder = _EmissionRecorder()
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
uv run pytest tests/unit/test_emission_recorder.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_emission_recorder.py App.py
git commit -m "feat(app): _EmissionRecorder singleton on App

Captures shuttle / probe / decoy launch events. Off by default.
Mirrors _stub_tracker mission-tagging pattern; values are stored as
plain tuples so events survive per-mission cleanup. The persistent
App module is the natural owner since the recorder needs to outlive
mission resets.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: engine/appc/emission.py — _launch_object wrapper + install hook

**Files:**
- Create: [engine/appc/emission.py](../../../engine/appc/emission.py) — new module
- Test: [tests/unit/test_emission_hook.py](../../../tests/unit/test_emission_hook.py) — new file (idempotence)
- Test: [tests/integration/test_emission_hook.py](../../../tests/integration/test_emission_hook.py) — new file (full hook flow)

- [ ] **Step 1: Write the failing unit test (idempotence)**

Create [tests/unit/test_emission_hook.py](../../../tests/unit/test_emission_hook.py):

```python
import tools.mission_harness as mh


def test_install_hook_is_idempotent():
    """Calling install_launch_object_hook() twice replaces the same slot,
    never composes."""
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook, _launch_object
    install_launch_object_hook()
    install_launch_object_hook()
    import Actions.ShipScriptActions as ssa
    assert ssa.LaunchObject is _launch_object
```

- [ ] **Step 2: Run the unit test, verify it fails**

```bash
uv run pytest tests/unit/test_emission_hook.py -v
```

Expected: fails with `ModuleNotFoundError: No module named 'engine.appc.emission'`.

- [ ] **Step 3: Write the failing integration test**

Create [tests/integration/test_emission_hook.py](../../../tests/integration/test_emission_hook.py):

```python
"""Integration tests for the LaunchObject emission hook.

Builds a synthetic ship-like object whose PropertySet exposes a single
ObjectEmitterProperty per launch type. Verifies the hook resolves the
correct emitter, computes the world-frame transform, and records the
event in App._emission_recorder.
"""
import pytest

import App
import tools.mission_harness as mh
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import (
    ObjectEmitterProperty,
    TGModelPropertyManager,
    TGModelPropertySet,
)


@pytest.fixture(autouse=True)
def reset_recorder():
    App._emission_recorder.disable()
    App._emission_recorder.clear()
    yield
    App._emission_recorder.disable()
    App._emission_recorder.clear()


def _make_emitter(name, local_pos, fwd, up, right, kind):
    e = App.ObjectEmitterProperty_Create(name)
    e.SetPosition(local_pos)
    e.SetOrientation(fwd, up, right)
    e.SetEmittedObjectType(kind)
    return e


def _make_synthetic_ship(emitters, world_loc, world_rot, obj_id, monkeypatch):
    """Return a stand-in for a ShipClass: implements the calls
    Actions.ShipScriptActions.LaunchObject needs, no more. Registers itself
    in engine.core.ids._registry so App.TGObject_GetTGObjectPtr resolves it,
    and monkeypatches App.ShipClass_Cast to accept the synthetic ship."""

    class _Set:
        def GetPropertiesByType(self, type_cls):
            # The engine wraps templates in TGModelPropertyInstance via the
            # standard TGModelPropertySet machinery. Reuse it.
            tps = TGModelPropertySet()
            for e in emitters:
                tps.AddProperty(e)
            return tps.GetPropertiesByType(type_cls)

    class _Ship:
        def GetPropertySet(self): return _Set()
        def GetWorldRotation(self): return world_rot
        def GetWorldLocation(self): return TGPoint3(world_loc.x, world_loc.y, world_loc.z)
        def GetObjID(self): return obj_id

    ship = _Ship()
    # App.TGObject_GetTGObjectPtr looks up engine.core.ids._registry
    from engine.core.ids import _registry as _ID_REGISTRY
    _ID_REGISTRY[obj_id] = ship
    # App.ShipClass_Cast checks isinstance(obj, ShipClass); for a synthetic
    # ship we shortcut it to a pass-through for the duration of the test.
    monkeypatch.setattr(App, "ShipClass_Cast", lambda obj: obj)
    return ship


def test_hook_resolves_shuttle_emitter_and_records(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    shuttle = _make_emitter(
        "Shuttle Bay",
        local_pos=TGPoint3(0.0, -2.0, -0.17),
        fwd=TGPoint3(0.0, -1.0, 0.0),
        up=TGPoint3(0.0, 0.0, 1.0),
        right=TGPoint3(-1.0, 0.0, 0.0),
        kind=ObjectEmitterProperty.OEP_SHUTTLE,
    )

    # Identity rotation; world location at origin
    R = TGMatrix3()
    ship = _make_synthetic_ship([shuttle], TGPoint3(0, 0, 0), R, obj_id=4242, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    rc = ssa.LaunchObject(None, 4242, "test-shuttle", ObjectEmitterProperty.OEP_SHUTTLE)
    assert rc == 0

    events = App._emission_recorder.events()
    assert len(events) == 1
    e = events[0]
    assert e["ship_id"] == 4242
    assert e["emitter_name"] == "Shuttle Bay"
    assert e["emitter_type"] == ObjectEmitterProperty.OEP_SHUTTLE
    # Identity rotation, origin world location → world position == local position
    assert abs(e["world_position"][0] - 0.0)   < 1e-9
    assert abs(e["world_position"][1] - (-2.0)) < 1e-9
    assert abs(e["world_position"][2] - (-0.17)) < 1e-9


def test_hook_picks_correct_emitter_by_type(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    shuttle = _make_emitter("Shuttle Bay", TGPoint3(0,-2,0), TGPoint3(0,-1,0),
                            TGPoint3(0,0,1), TGPoint3(-1,0,0), ObjectEmitterProperty.OEP_SHUTTLE)
    probe = _make_emitter("Probe Launcher", TGPoint3(0,3.35,0), TGPoint3(0,1,0),
                          TGPoint3(0,0,1), TGPoint3(1,0,0), ObjectEmitterProperty.OEP_PROBE)
    decoy = _make_emitter("Decoy launcher", TGPoint3(0,0,1), TGPoint3(0,1,0),
                          TGPoint3(0,0,1), TGPoint3(1,0,0), ObjectEmitterProperty.OEP_DECOY)

    R = TGMatrix3()
    ship = _make_synthetic_ship([shuttle, probe, decoy], TGPoint3(0,0,0), R, obj_id=4243, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    ssa.LaunchObject(None, 4243, "p", ObjectEmitterProperty.OEP_PROBE)
    ssa.LaunchObject(None, 4243, "d", ObjectEmitterProperty.OEP_DECOY)
    ssa.LaunchObject(None, 4243, "s", ObjectEmitterProperty.OEP_SHUTTLE)

    events = App._emission_recorder.events()
    assert [e["emitter_name"] for e in events] == ["Probe Launcher", "Decoy launcher", "Shuttle Bay"]
    assert [e["emitter_type"] for e in events] == [
        ObjectEmitterProperty.OEP_PROBE,
        ObjectEmitterProperty.OEP_DECOY,
        ObjectEmitterProperty.OEP_SHUTTLE,
    ]


def test_hook_no_match_records_nothing(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    shuttle = _make_emitter("Shuttle Bay", TGPoint3(0,-2,0), TGPoint3(0,-1,0),
                            TGPoint3(0,0,1), TGPoint3(-1,0,0), ObjectEmitterProperty.OEP_SHUTTLE)
    R = TGMatrix3()
    _make_synthetic_ship([shuttle], TGPoint3(0,0,0), R, obj_id=4244, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    rc = ssa.LaunchObject(None, 4244, "phantom-probe", ObjectEmitterProperty.OEP_PROBE)
    assert rc == 0
    assert App._emission_recorder.events() == []


def test_hook_applies_world_rotation_and_translation(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    # Local-frame emitter at +Y=3.35 (probe launcher offset on sovereign)
    probe = _make_emitter("Probe Launcher",
                          TGPoint3(0.0, 3.35, 0.0),
                          TGPoint3(0.0, 1.0, 0.0),
                          TGPoint3(0.0, 0.0, 1.0),
                          TGPoint3(1.0, 0.0, 0.0),
                          ObjectEmitterProperty.OEP_PROBE)
    # 90° rotation about z: x→y, y→-x (column-vector convention)
    R = TGMatrix3()
    R.SetRow(0, TGPoint3(0.0, -1.0, 0.0))
    R.SetRow(1, TGPoint3(1.0,  0.0, 0.0))
    R.SetRow(2, TGPoint3(0.0,  0.0, 1.0))
    world_loc = TGPoint3(10.0, 20.0, 30.0)
    _make_synthetic_ship([probe], world_loc, R, obj_id=4245, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    ssa.LaunchObject(None, 4245, "p", ObjectEmitterProperty.OEP_PROBE)

    e = App._emission_recorder.events()[0]
    # Expected world position: R · (0, 3.35, 0) + (10, 20, 30)
    #   R · (0, 3.35, 0) = (-3.35, 0, 0)
    #   + (10, 20, 30) = (6.65, 20, 30)
    assert abs(e["world_position"][0] - 6.65) < 1e-9
    assert abs(e["world_position"][1] - 20.0) < 1e-9
    assert abs(e["world_position"][2] - 30.0) < 1e-9
    # Expected world_forward: R · (0,1,0) = (-1, 0, 0)
    assert abs(e["world_forward"][0] - (-1.0)) < 1e-9
    assert abs(e["world_forward"][1] -   0.0)  < 1e-9
    assert abs(e["world_forward"][2] -   0.0)  < 1e-9
    # Expected world_up: R · (0,0,1) = (0, 0, 1)
    assert abs(e["world_up"][0] - 0.0) < 1e-9
    assert abs(e["world_up"][1] - 0.0) < 1e-9
    assert abs(e["world_up"][2] - 1.0) < 1e-9


def test_hook_records_nothing_when_recorder_disabled(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.disable()  # explicit

    shuttle = _make_emitter("Shuttle Bay", TGPoint3(0,-2,0), TGPoint3(0,-1,0),
                            TGPoint3(0,0,1), TGPoint3(-1,0,0), ObjectEmitterProperty.OEP_SHUTTLE)
    R = TGMatrix3()
    _make_synthetic_ship([shuttle], TGPoint3(0,0,0), R, obj_id=4246, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    rc = ssa.LaunchObject(None, 4246, "s", ObjectEmitterProperty.OEP_SHUTTLE)
    assert rc == 0
    assert App._emission_recorder.events() == []
```

Note on the synthetic ship fixture: `App.TGObject_GetTGObjectPtr(id)` resolves via `engine.core.ids.get_object_by_id`, which reads `engine.core.ids._registry`. The fixture writes directly into that dict to make the synthetic ship findable. `App.ShipClass_Cast` would normally reject a non-`ShipClass` object, so the fixture monkeypatches it to a pass-through for the test's duration only.

- [ ] **Step 4: Run the integration tests, verify they fail**

```bash
uv run pytest tests/integration/test_emission_hook.py -v
```

Expected: 5 tests fail with `ModuleNotFoundError: No module named 'engine.appc.emission'`.

- [ ] **Step 5: Implement engine/appc/emission.py**

Create [engine/appc/emission.py](../../../engine/appc/emission.py):

```python
"""LaunchObject hook for shuttle / probe / decoy emission.

Replaces Actions.ShipScriptActions.LaunchObject with a wrapper that
resolves the right emitter on the ship's PropertySet, computes the
world-frame position and orientation, and records the event in
App._emission_recorder. No real spawning — Layer 3 of the emission
design (see docs/project/superpowers/specs/2026-05-12-object-emitter-emission-design.md).

Install once at harness setup:
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()

Idempotent: calling twice replaces the same slot, never composes.
"""


def _launch_object(pAction, iShipID, pcName, iType):
    import App

    pShip = App.ShipClass_Cast(App.TGObject_GetTGObjectPtr(iShipID))
    if pShip is None:
        return 0

    pPropSet = pShip.GetPropertySet()
    pEmitterInstanceList = pPropSet.GetPropertiesByType(App.CT_OBJECT_EMITTER_PROPERTY)

    pEmitterInstanceList.TGBeginIteration()
    iNumItems = pEmitterInstanceList.TGGetNumItems()

    pLaunchProperty = None
    for _ in range(iNumItems):
        pInstance = pEmitterInstanceList.TGGetNext()
        pProperty = App.ObjectEmitterProperty_Cast(pInstance.GetProperty())
        if pProperty is not None and pProperty.GetEmittedObjectType() == iType:
            pLaunchProperty = pProperty
            break

    pEmitterInstanceList.TGDoneIterating()
    pEmitterInstanceList.TGDestroy()

    if pLaunchProperty is None:
        return 0

    pRotation = pShip.GetWorldRotation()

    pPosition = pLaunchProperty.GetPosition()
    pPosition.MultMatrixLeft(pRotation)
    pPosition.Add(pShip.GetWorldLocation())

    pFwd = pLaunchProperty.GetForward()
    pUp = pLaunchProperty.GetUp()
    pFwd.MultMatrixLeft(pRotation)
    pUp.MultMatrixLeft(pRotation)

    App._emission_recorder.record(
        iShipID,
        pLaunchProperty.GetName(),
        iType,
        pPosition, pFwd, pUp,
    )
    return 0


def install_launch_object_hook():
    """Replace Actions.ShipScriptActions.LaunchObject with the engine wrapper.

    Idempotent — calling twice replaces the same slot.
    Requires tools.mission_harness.setup_sdk() to have run first so the
    Actions.ShipScriptActions module is importable through the SDK finder.
    """
    import Actions.ShipScriptActions as _ssa
    _ssa.LaunchObject = _launch_object
```

- [ ] **Step 6: Run the unit + integration tests, verify they pass**

```bash
uv run pytest tests/unit/test_emission_hook.py tests/integration/test_emission_hook.py -v
```

Expected: 1 unit test + 5 integration tests pass (6 total).

If the integration tests fail with `ImportError`, double-check that `engine.core.ids` still exposes `_registry` and `get_object_by_id`. The fixture deliberately uses the same store `App.TGObject_GetTGObjectPtr` consults; if that internal name changes, update the fixture, not production.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_emission_hook.py tests/integration/test_emission_hook.py engine/appc/emission.py
git commit -m "feat(emission): LaunchObject hook for shuttle/probe/decoy

Replaces Actions.ShipScriptActions.LaunchObject with an engine wrapper
that resolves the right emitter on the ship's PropertySet, computes
the world-frame transform (position via R·local + world_loc, fwd/up
via R·local), and records the event in App._emission_recorder. No
real spawning. Idempotent install.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Wire install_launch_object_hook() into setup_sdk()

**Files:**
- Modify: [tools/mission_harness.py](../../../tools/mission_harness.py) — call hook installer at end of `setup_sdk()`
- Test: [tests/unit/test_emission_hook.py](../../../tests/unit/test_emission_hook.py) — add setup_sdk wiring test

- [ ] **Step 1: Write the failing test**

Append to [tests/unit/test_emission_hook.py](../../../tests/unit/test_emission_hook.py):

```python
def test_setup_sdk_installs_hook():
    """tools.mission_harness.setup_sdk() should install the hook so the
    gameloop harness gets it automatically."""
    import importlib
    import sys
    import tools.mission_harness as mh

    # Force Actions.ShipScriptActions to be re-imported fresh so we can
    # observe whether setup_sdk re-installs the hook.
    sys.modules.pop("Actions.ShipScriptActions", None)
    sys.modules.pop("Actions", None)

    mh.setup_sdk()
    from engine.appc.emission import _launch_object
    import Actions.ShipScriptActions as ssa
    assert ssa.LaunchObject is _launch_object
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
uv run pytest tests/unit/test_emission_hook.py::test_setup_sdk_installs_hook -v
```

Expected: fails because `setup_sdk` doesn't install the hook yet — `ssa.LaunchObject` is the SDK version, not `_launch_object`.

- [ ] **Step 3: Wire into setup_sdk**

In [tools/mission_harness.py](../../../tools/mission_harness.py), the `setup_sdk()` function (around line 364). At the end of the function body, add:

```python
    # Install the LaunchObject emission hook so any TGScriptAction that
    # routes through Actions.ShipScriptActions.LaunchObject lands in the
    # engine wrapper (which records via App._emission_recorder instead
    # of spawning real ships). Idempotent — safe to call repeatedly.
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
```

(Place it after the `_BASELINE_MODULES = set(sys.modules)` line if there is one near the end, or as the final statement of `setup_sdk()` otherwise — read the function and pick the position that runs after SDK pathing is established.)

- [ ] **Step 4: Run the test, verify it passes**

```bash
uv run pytest tests/unit/test_emission_hook.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Run the broader emission test suite as a regression check**

```bash
uv run pytest tests/unit/test_emission_hook.py tests/integration/test_emission_hook.py tests/unit/test_emission_recorder.py tests/unit/test_object_emitter_property.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_emission_hook.py tools/mission_harness.py
git commit -m "feat(harness): setup_sdk installs LaunchObject emission hook

Wires the engine wrapper in once per harness setup so every mission
that fires TGScriptAction_Create(\"Actions.ShipScriptActions\",
\"LaunchObject\", ...) lands in the recorder path instead of spawning
real ships through SDK LoadSpaceHelper.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Gameloop harness regression — no ObjectEmitterProperty_Create rows

**Files:**
- Modify: [tests/integration/test_gameloop_harness.py](../../../tests/integration/test_gameloop_harness.py) — add regression assertion

- [ ] **Step 1: Read the existing test to find an insertion point**

```bash
sed -n '1,80p' tests/integration/test_gameloop_harness.py
```

Identify the existing test that runs the harness with `profile=True` (or add one). The goal is to call `tools.gameloop_harness.main(...)` (or `run_mission_with_loop` per mission) with profiling on and inspect `App._stub_tracker.report()` afterwards.

- [ ] **Step 2: Write the failing test**

Append to [tests/integration/test_gameloop_harness.py](../../../tests/integration/test_gameloop_harness.py):

```python
def test_no_object_emitter_property_create_stub_rows(monkeypatch):
    """After Task 1-7 land, sovereign / galaxy / nebula / etc. hardpoint
    loads should not produce any ObjectEmitterProperty_Create* stub-tracker
    rows during a real harness run across all discovered missions. Catches
    future regressions where someone removes the factory or the Cast.
    """
    import App
    import tools.mission_harness as mh
    from tools.gameloop_harness import run_mission_with_loop

    App._stub_tracker.clear()
    mh.setup_sdk()
    missions = mh.discover_missions()
    # Hardpoint loads happen during mission Initialize(), before the tick
    # loop. n_ticks=1 keeps the test fast (~few seconds) while still
    # exercising every mission's setup path.
    for name in missions:
        run_mission_with_loop(name, n_ticks=1, profile=True)

    leaks = [
        row for row in App._stub_tracker.report()
        if row[0].startswith("ObjectEmitterProperty_Create")
    ]
    assert leaks == [], f"ObjectEmitterProperty_Create* still in stub tracker: {leaks[:10]}"
```

- [ ] **Step 3: Run the test, verify it passes**

```bash
uv run pytest tests/integration/test_gameloop_harness.py::test_no_object_emitter_property_create_stub_rows -v
```

Expected: PASS. If it fails, the leak list tells you which method on `ObjectEmitterProperty` is still missing.

- [ ] **Step 4: Run the full integration suite to confirm no regression**

```bash
uv run pytest tests/integration/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_gameloop_harness.py
git commit -m "test(harness): regression — no ObjectEmitterProperty_Create stub rows

Locks in across the first 30 missions (which cover all emitter-bearing
ship hardpoints) that the factory + Cast + storage work end-to-end.
Catches future regressions where someone removes the factory or the
Cast and the calls silently fall back to _NamedStub.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the full test suite**

```bash
uv run pytest
```

Expected: all tests pass (no regressions in any pre-existing test).

- [ ] **Sanity-check the profile by hand**

```bash
uv run python tools/gameloop_harness.py --ticks 600 --profile 2>&1 | grep -i "ObjectEmitterProperty"
```

Expected: no output (no rows). Confirms the original 5-row profile gap is closed end-to-end through the harness.

- [ ] **Document a known limitation in the spec follow-up section**

If `LoadSpaceHelper.CreateShip("Shuttle"/"Probe"/"Decoy", ...)` paths are later wired, this hook will need to be revisited (the wrapper short-circuits before that call). That's expected and explicitly out of scope for this plan.

---

## Self-review notes

**Spec coverage:**
- Goal 1 (eliminate 5 stub rows) → Task 3 unit regression + Task 8 harness regression.
- Goal 2 (`FindByNameAndType` returns the template) → Task 3 unit test `test_register_local_template_findable_by_name`.
- Goal 3 (`LaunchObject` resolves emitter + computes world transform + records) → Task 6 integration tests 1-4.
- Goal 4 (unit + integration + harness tests) → Tasks 1-3, 5-8.
- Layer 1 (real property) → Tasks 1-3.
- Layer 2 (recorder) → Task 5.
- Layer 3 (hook) → Tasks 4 (math infra), 6 (hook), 7 (wire into setup_sdk).
- Non-goals (real spawning, sensor probe, collision-disable, renderer) → explicitly skipped; the wrapper short-circuits before those calls.

**Placeholder scan:** none. Every step has either code, a specific command, or a specific assertion.

**Type consistency:** `_emission_recorder` (lowercase, leading underscore) used consistently. `OEP_*` constants match spec. `_launch_object` (lowercase, leading underscore) is the internal function; `install_launch_object_hook()` is the public installer. `_copy_point` helper used consistently in property class.

**Discovered during plan-write that the spec missed:** `TGPoint3.MultMatrixLeft` does not exist on the engine's `TGPoint3` today (only `TGMatrix3` has it). Task 4 adds it. This is small generally-useful math infrastructure — SDK code in `MissionLib`, `AI/Preprocessors`, and several mission scripts calls the same pattern, so adding it pays for itself beyond this plan.
