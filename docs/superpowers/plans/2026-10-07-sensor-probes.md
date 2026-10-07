# Sensor Probes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make probes a counted resource whose own sensors see for the ship that launched them — listing contacts beyond the ship's range, identifying contacts in their near band — and prove Science "Launch Probe" and E6M4's probe goal end to end.

**Architecture:** `SensorSubsystem` gains BC's probe count and probe-ID list. The one detection rule, `sensor_detection.can_detect`, gains a probe branch after the observer's own range test: any live same-set probe for which `can_detect(probe, target)` holds (not jam-gated, BC order). `IsObjectNear`/`IsObjectFar` and the player's contact sweep consult probes; `in_reach` does too, so the continuity clock covers probe-reached contacts.

**Tech Stack:** Python 3.11, pytest (`uv run pytest`), the headless App shim and the BC SDK scripts. No C++ changes.

**Spec:** `docs/superpowers/specs/2026-10-07-sensor-probes-design.md` (read its Evidence and Rules first). Prior: `docs/superpowers/specs/2026-10-06-sensor-overboost-memory-design.md`.

## Global Constraints

- Work ONLY in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/sensor-overboost-memory`, branch `feat/sensor-probes`. Never commit to main. Never push.
- ⛔ Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths only. To mutate a file temporarily: `cp f /tmp/bak` → edit → test → `cp /tmp/bak f` → `diff f /tmp/bak`.
- Never launch the game (`./build/dauntless`). Never `pkill`/`killall`.
- Probe IDs are resolved with `engine.core.ids.get_object_by_id` (what `App.TGObject_GetTGObjectPtr` uses); an ID that no longer resolves is pruned from the list.
- The probe branch is NOT cancelled by `jammed` (BC: probes precede the jam fallback). It requires the probe and the target in the OBSERVER's set. The observer's power gate (`effective_sensor_range(observer) <= 0` ⇒ False) still precedes everything — dead own sensors ⇒ probes do not help.
- One probe level: a probe's own probes are never walked (reentrancy guard).
- The player's contact sweep treats bands as empty when the player's own range is 0 (BC's sweep bails when the player's sensors are dead).
- Units are GU (1 GU = 175 m). Check `docs/stub_heatmap.md` before claiming an SDK call is a no-op; never decide surface exists by grepping `def <Name>(`.
- Gate: `scripts/check_tests.sh` must exit 0 before the branch is called done. `tests/known_failures.txt` holds no failure entries — fix, never baseline.
- Test command form: `uv run pytest <path> -q`.

## Review Focus

1. **A probe left in another set** after the player warps or hands off must not extend the player's reach (no cross-set leak). Pinned in Task 2 (`test_probe_in_another_set_does_not_reach`).
2. **A destroyed probe** (sensors at 0 condition, object still present as a wreck) must not see; a deleted probe must be pruned from the list without error. Pinned in Tasks 1 and 2 (`test_probes_prunes_a_deleted_probe`, `test_probe_with_offline_sensors_does_not_reach`).
3. **Launching at zero probes** must spawn nothing and leave the count at 0 (no negative count, no name collision). Pinned in Task 4 (`test_launch_with_no_probes_left_spawns_nothing`).
4. **Player sensors dead while a probe is out** — nothing listed via the probe and no FAR/NEAR events from the sweep. Pinned in Tasks 2 and 3 (`test_dead_observer_sensors_ignore_probes`, `test_sweep_posts_nothing_via_probe_when_player_sensors_dead`).
5. **The player's own probe on the list** — it is a contact like any other ship, perceived and targetable; and the probe itself is never "reached via itself" in a way that breaks (a probe as both observer-probe and target). Pinned in Task 2 (`test_own_probe_is_detected_and_not_a_recursion_hazard`).

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `engine/appc/subsystems.py` (`SensorSubsystem`) | count, probe list, `probes()`; bands consult probes | 1, 3 |
| `engine/appc/ships.py` (sensor property branch ~line 1268) | seed `NumProbes` from `MaxProbes` | 1 |
| `engine/appc/sensor_detection.py` | `_probe_reach`, `_probe_in_reach`; wire into `can_detect` tail and `in_reach` | 2 |
| `engine/appc/sensor_contacts.py` (`_sweep`, `_in_near_band`) | bands via the sensors' `IsObjectNear`/`IsObjectFar` | 3 |
| `tests/unit/test_sensor_probes.py` (new) | count, list, reach, bands, sweep, continuity | 1, 2, 3 |
| `tests/integration/test_sensor_probe_launch.py` (new) | real Launch Probe; E6M4 | 4 |
| `tests/unit/test_sensor_reach_bench.py` | probe bench | 5 |
| spec, roadmap, `CLAUDE.md` | As built, status | 5 |

---

### Task 1: Probe count and probe list on `SensorSubsystem`

**Files:**
- Modify: `engine/appc/subsystems.py` (`SensorSubsystem.__init__` and accessors near `GetMaxProbes`)
- Modify: `engine/appc/ships.py` (sensor property branch, after the `(prop.GetMaxProbes, sens.SetMaxProbes)` loop)
- Create: `tests/unit/test_sensor_probes.py`

**Interfaces:**
- Consumes: `engine.core.ids.get_object_by_id(obj_id) -> TGObject | None`.
- Produces: `SensorSubsystem.GetNumProbes() -> int`, `SetNumProbes(n) -> None`, `AddProbe(obj_id) -> None`, `probes() -> list` (live probe objects, prunes dead IDs). Test helpers in `tests/unit/test_sensor_probes.py`: `_probe_at(s, owner_sensors, x, base_range=1000.0) -> ShipClass`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sensor_probes.py`:

```python
"""Sensor-model sub-project 4: probes (2026-10-07-sensor-probes-design.md).

A probe is a ShipClass with its own SensorSubsystem (SDK Hardpoints/probe.py:
1000 GU). The launching ship's sensors hold its object ID (BC AddProbe); its
sensors see for the launcher. Fixtures reuse test_sensor_reach's helpers."""
import pytest

import App
from engine.appc import contact_index
from engine.appc import sensor_detection as sd
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from tests.unit.test_sensor_reach import _observer_in_set, _ship_at, _Neb, _nebulae
from tests.helpers.rocks import occlusion_enabled  # noqa: F401  (fixture)


def _probe_at(s, owner_sensors, x, base_range=1000.0):
    probe = ShipClass_Create("Probe")
    probe.SetTranslateXYZ(float(x), 0.0, 0.0)
    ps = SensorSubsystem("Sensor Array")
    ps._max_condition = 100.0
    ps._condition = 100.0
    ps.SetBaseSensorRange(base_range)
    probe.SetSensorSubsystem(ps)
    s.AddObjectToSet(probe, "Probe %d" % probe.GetObjID())
    owner_sensors.AddProbe(probe.GetObjID())
    return probe


# ── count ───────────────────────────────────────────────────────────────────

def test_num_probes_round_trips():
    sensors = SensorSubsystem("Sensors")
    assert sensors.GetNumProbes() == 0
    sensors.SetNumProbes(7)
    assert sensors.GetNumProbes() == 7


def test_num_probes_is_seeded_from_max_probes_by_setup_properties():
    from engine.appc.properties import SensorProperty
    ship = ShipClass_Create("Galaxy")
    prop = SensorProperty("Sensor Array")
    prop.SetBaseSensorRange(2000.0)
    prop.SetMaxProbes(10)
    prop.SetMaxCondition(8000.0)
    ship.GetPropertySet().AddToSet("Scene Root", prop)
    ship.SetupProperties()
    sensors = ship.GetSensorSubsystem()
    assert sensors.GetMaxProbes() == 10
    assert sensors.GetNumProbes() == 10


def test_repair_ship_fully_refills_probes():
    import Actions.ShipScriptActions as ssa
    from engine.appc.properties import SensorProperty
    ship = ShipClass_Create("Galaxy")
    prop = SensorProperty("Sensor Array")
    prop.SetBaseSensorRange(2000.0)
    prop.SetMaxProbes(10)
    prop.SetMaxCondition(8000.0)
    ship.GetPropertySet().AddToSet("Scene Root", prop)
    ship.SetupProperties()
    sensors = ship.GetSensorSubsystem()
    sensors.SetNumProbes(2)
    ssa.RepairShipFully(None, ship.GetObjID())
    assert sensors.GetNumProbes() == 10


# ── list ────────────────────────────────────────────────────────────────────

def test_add_probe_lists_the_live_probe():
    s, obs, sensors = _observer_in_set()
    probe = _probe_at(s, sensors, 3000.0)
    assert sensors.probes() == [probe]


def test_probes_prunes_a_deleted_probe():
    from engine.core import ids
    s, obs, sensors = _observer_in_set()
    keep = _probe_at(s, sensors, 3000.0)
    gone = _probe_at(s, sensors, 4000.0)
    ids.unregister(gone.GetObjID())
    assert sensors.probes() == [keep]
    assert sensors._probe_ids == [keep.GetObjID()]
```

Notes for the implementer:
- `SensorProperty` lives in `engine/appc/properties.py` (it is a data-bag class; `SetMaxProbes`/`SetBaseSensorRange` go through the generic Get/Set). If `SetupProperties` needs more on the property set to build a `SensorSubsystem` (e.g. a hull), read `tests/unit/test_setup_properties_sensor.py` and copy its construction exactly.
- `Actions.ShipScriptActions` imports through the SDK finder (`tests/conftest.py`). `RepairShipFully` touches hull/shields/power/visible damage; if it raises on the bare ship, build the ship the way `test_setup_properties_sensor.py` does, or report NEEDS_CONTEXT.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_probes.py -q`
Expected: FAIL — `GetNumProbes` returns a `_Stub` (≠ 0), `AttributeError: ... 'probes'`.

- [ ] **Step 3: Implement**

In `SensorSubsystem.__init__` (after `self._max_probes: int = 0`):

```python
        # BC +0xC8 NumProbes (live counter, seeded from MaxProbes) and the
        # +0xAC..+0xBC probe list, which holds OBJECT IDS, not pointers
        # (sensor-subsystem.md; 2026-10-07-sensor-probes-design.md).
        self._num_probes: int = 0
        self._probe_ids: list = []
```

After `SetMaxProbes`:

```python
    def GetNumProbes(self) -> int:                   return self._num_probes
    def SetNumProbes(self, v) -> None:               self._num_probes = int(v)

    def AddProbe(self, obj_id) -> None:
        """BC AddProbe (@0x00567010): remember a launched probe by object ID."""
        self._probe_ids.append(int(obj_id))

    def probes(self) -> list:
        """The live probes, in launch order. An ID that no longer resolves
        (the object was deleted) is dropped, as BC garbage-collects dead
        probes while walking the list."""
        from engine.core.ids import get_object_by_id
        live, keep = [], []
        for oid in self._probe_ids:
            obj = get_object_by_id(oid)
            if obj is not None:
                live.append(obj)
                keep.append(oid)
        self._probe_ids = keep
        return live
```

In `engine/appc/ships.py`, directly after the `for src, setter in (...)` loop in the `SensorProperty` branch (inside `if sens is not None:`):

```python
                    # BC SetProperty seeds NumProbes from MaxProbes.
                    sens.SetNumProbes(sens.GetMaxProbes())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_probes.py tests/unit/test_setup_properties_sensor.py tests/unit/test_sensor_subsystem_identity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py engine/appc/ships.py tests/unit/test_sensor_probes.py
git commit -m "feat(sensors): probe count seeded from MaxProbes, AddProbe and the probe list

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The probe branch in `can_detect` and `in_reach`

**Files:**
- Modify: `engine/appc/sensor_detection.py`
- Modify: `tests/unit/test_sensor_probes.py`

**Interfaces:**
- Consumes: `SensorSubsystem.probes()` (Task 1); `_same_set`, `_beyond_range_reach`, `in_reach`, `effective_sensor_range`, `can_detect` (existing).
- Produces: private `_probe_reach(observer, target) -> bool`, `_probe_in_reach(observer, target) -> bool`; `can_detect` and `in_reach` now include them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sensor_probes.py`:

```python
# ── reach ───────────────────────────────────────────────────────────────────

def test_probe_sees_a_ship_beyond_the_observers_range():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    assert sd.can_detect(obs, far) is False
    _probe_at(s, sensors, 4000.0)                     # 500 GU from the target
    assert sd.can_detect(obs, far) is True


def test_target_beyond_the_probes_range_is_not_reached():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 9000.0)
    _probe_at(s, sensors, 4000.0)                     # 5000 GU away from it
    assert sd.can_detect(obs, far) is False


def test_probe_in_another_set_does_not_reach():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    other = SetClass()
    probe = ShipClass_Create("Probe")
    probe.SetTranslateXYZ(4400.0, 0.0, 0.0)
    ps = SensorSubsystem("Sensor Array")
    ps._max_condition = 100.0
    ps._condition = 100.0
    ps.SetBaseSensorRange(1000.0)
    probe.SetSensorSubsystem(ps)
    other.AddObjectToSet(probe, "Probe 1")
    sensors.AddProbe(probe.GetObjID())
    assert sd.can_detect(obs, far) is False


def test_probe_with_offline_sensors_does_not_reach():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    probe = _probe_at(s, sensors, 4000.0)
    probe.GetSensorSubsystem()._condition = 0.0
    assert sd.can_detect(obs, far) is False


def test_dead_observer_sensors_ignore_probes():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    sensors._condition = 10.0                         # below the disabled threshold
    assert sd.can_detect(obs, far) is False


def test_rock_between_probe_and_target_hides_it(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    make_major_rock(s, "Rock", at=(4250.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is False


def test_jam_does_not_cancel_the_probe_branch(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    _nebulae(monkeypatch, _Neb(far, obs))
    assert sd.jammed(obs, far) is True
    assert sd.can_detect(obs, far) is True


def test_dense_core_still_hides_from_the_probe(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    monkeypatch.setattr(sd, "concealment_at", lambda ship: 0.9)
    assert sd.can_detect(obs, far) is False


def test_probe_branch_does_not_identify():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    assert sd.can_detect(obs, far) is True
    assert sensors.IsObjectKnown(far) == 0


def test_own_probe_is_detected_and_not_a_recursion_hazard():
    s, obs, sensors = _observer_in_set(2000.0)
    probe = _probe_at(s, sensors, 2500.0)             # beyond own range
    probe.GetSensorSubsystem().AddProbe(obs.GetObjID())   # pathological cycle
    assert sd.can_detect(obs, probe) is True          # its own sensors see itself at 0 GU
    near = _probe_at(s, sensors, 500.0)
    assert sd.can_detect(obs, near) is True


def test_cross_set_dist_sq_path_ignores_probes():
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    other.AddObjectToSet(ship, "elsewhere")
    _probe_at(s, sensors, 0.0)
    assert sd.can_detect(obs, ship, dist_sq_gu=5000.0 ** 2) is False


# ── in_reach ────────────────────────────────────────────────────────────────

def test_in_reach_includes_probes_and_ignores_rocks(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    assert sd.in_reach(obs, far) is False
    _probe_at(s, sensors, 4000.0)
    make_major_rock(s, "Rock", at=(4250.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is False
    assert sd.in_reach(obs, far) is True


def test_in_reach_via_probe_needs_live_observer_sensors():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    sensors._condition = 10.0
    assert sd.in_reach(obs, far) is False
```

Note: `test_own_probe_is_detected_and_not_a_recursion_hazard` — `can_detect(probe, probe)` (distance 0) is True, which is how the observer reaches its own far probe; the deliberately added cycle (`probe` listing `obs`) must not recurse without bound.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_probes.py -q`
Expected: the "is True" reach tests and `test_in_reach_includes_probes_and_ignores_rocks` FAIL; "is False" tests may already pass.

- [ ] **Step 3: Implement**

In `engine/appc/sensor_detection.py`:

1. Add a module-level guard near the other module state (after `ENHANCED_SENSOR_CONTEST`'s constants block is fine):

```python
# One probe level (2026-10-07-sensor-probes-design.md, Rule 3): while a probe's
# own sensors are being asked, its probe list is not walked. Also guards a
# pathological AddProbe cycle.
_walking_probes = False
```

2. Add after `_beyond_range_reach`:

```python
def _live_probes(observer) -> list:
    sensors = (observer.GetSensorSubsystem()
               if implements(observer, "GetSensorSubsystem") else None)
    if sensors is None or not implements(sensors, "probes"):
        return []
    return sensors.probes()


def _probe_reach(observer, target) -> bool:
    """BC's probe walk (IsObjectVisible @0x005671D0, step 7): a live probe of
    the observer, in the observer's set, whose own sensors detect the target
    (the one rule, from the probe's position -- rocks, cloak bubble, nebula
    core, the probe's power and condition all apply). Runs after the range
    test and is NOT cancelled by `jammed` (BC's probe walk precedes the jam
    fallback). One level only: `_walking_probes`."""
    global _walking_probes
    if _walking_probes or not _same_set(observer, target):
        return False
    probes = _live_probes(observer)
    if not probes:
        return False
    oset = observer.GetContainingSet()
    _walking_probes = True
    try:
        for probe in probes:
            if (implements(probe, "GetContainingSet")
                    and probe.GetContainingSet() is oset
                    and can_detect(probe, target)):
                return True
        return False
    finally:
        _walking_probes = False


def _probe_in_reach(observer, target) -> bool:
    """`in_reach` through a probe: a live same-set probe whose own reach
    (unshrunk range, ignoring the hide gates) covers the target."""
    global _walking_probes
    if _walking_probes or not _same_set(observer, target):
        return False
    probes = _live_probes(observer)
    if not probes:
        return False
    oset = observer.GetContainingSet()
    _walking_probes = True
    try:
        for probe in probes:
            if (implements(probe, "GetContainingSet")
                    and probe.GetContainingSet() is oset
                    and in_reach(probe, target)):
                return True
        return False
    finally:
        _walking_probes = False
```

3. In `can_detect`, change the tail:

```python
    # ── Beyond range (sub-project 3): BC's memory and over-boost ──────────
    return _beyond_range_reach(observer, target, cloaked)
```

to

```python
    # ── Beyond range: BC's memory and over-boost (sub-project 3), then the
    # probe walk (sub-project 4) ─────────────────────────────────────────
    return (_beyond_range_reach(observer, target, cloaked)
            or _probe_reach(observer, target))
```

4. In `in_reach`, change its last line `return _beyond_range_reach(observer, target, is_hidden_by_cloak(target))` to:

```python
    return (_beyond_range_reach(observer, target, is_hidden_by_cloak(target))
            or _probe_in_reach(observer, target))
```

5. Update `can_detect`'s docstring paragraph about beyond-range reach to add: `…; or, failing those, a live same-set probe of the observer whose own sensors detect it (``_probe_reach``; sub-project 4, not jam-gated).` Update `in_reach`'s docstring: `…or `_beyond_range_reach`, or a probe's own reach (`_probe_in_reach`).`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_probes.py tests/unit/test_sensor_reach.py tests/unit/test_sensor_detection.py tests/unit/test_cloak_detection_contest.py tests/unit/test_ai_sensor_gate.py tests/unit/test_sensor_bands_and_visibility.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_detection.py tests/unit/test_sensor_probes.py
git commit -m "feat(sensors): probes see for their launcher in can_detect and in_reach

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Bands and the player's sweep consult probes

**Files:**
- Modify: `engine/appc/subsystems.py` (`SensorSubsystem.IsObjectNear` / `IsObjectFar`)
- Modify: `engine/appc/sensor_contacts.py` (`_sweep`, `_in_near_band`)
- Modify: `tests/unit/test_sensor_probes.py`

**Interfaces:**
- Consumes: `SensorSubsystem.probes()` (Task 1); `sensor_dials.get("near_fraction")`.
- Produces: `IsObjectNear(obj)` / `IsObjectFar(obj)` = owner's own band OR any live probe (in the owner's set) whose own band (half / full of the PROBE's range) covers obj. Private `_own_band(obj, fraction) -> bool` on `SensorSubsystem`. The sweep's `near`/`far` booleans and `_in_near_band` come from these, and are False when the player's own effective range is 0.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sensor_probes.py`:

```python
# ── bands ───────────────────────────────────────────────────────────────────

def test_bands_include_the_probes_bands():
    s, obs, sensors = _observer_in_set(2000.0)
    probe = _probe_at(s, sensors, 4000.0)
    in_near = _ship_at(s, "near_probe", 4400.0)   # 400 from probe (< 500)
    in_far = _ship_at(s, "far_probe", 4800.0)     # 800 from probe (< 1000)
    out = _ship_at(s, "out", 6000.0)
    assert (sensors.IsObjectNear(in_near), sensors.IsObjectFar(in_near)) == (1, 1)
    assert (sensors.IsObjectNear(in_far), sensors.IsObjectFar(in_far)) == (0, 1)
    assert (sensors.IsObjectNear(out), sensors.IsObjectFar(out)) == (0, 0)


def test_probe_bands_need_the_probe_in_the_owners_set():
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    tgt = ShipClass_Create("BirdOfPrey")
    tgt.SetTranslateXYZ(4400.0, 0.0, 0.0)
    other.AddObjectToSet(tgt, "elsewhere")
    _probe_at(s, sensors, 4000.0)
    assert sensors.IsObjectNear(tgt) == 0 and sensors.IsObjectFar(tgt) == 0


# ── the player's sweep ──────────────────────────────────────────────────────

def _player_world(base_range=2000.0):
    from engine.core.game import Game, _set_current_game
    s, player, sensors = _observer_in_set(base_range)
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors


@pytest.fixture
def _no_game():
    yield
    from engine.core.game import _set_current_game
    _set_current_game(None)


def test_sweep_identifies_a_contact_in_the_probes_near_band(_no_game):
    from engine.appc import sensor_contacts
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4400.0)
    _probe_at(s, sensors, 4000.0)
    sensor_contacts.tick(player, 0.0)
    assert sensors.IsObjectKnown(bird) == 0
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        sensor_contacts.tick(player, t)
    assert sensors.IsObjectKnown(bird) == 1


def test_sweep_posts_far_and_near_via_probe(_no_game, monkeypatch):
    from engine.appc import sensor_contacts
    posted = []
    monkeypatch.setattr(sensor_contacts, "_post",
                        lambda et, obj, entered, sensors: posted.append((et, obj, entered)))
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4400.0)
    _probe_at(s, sensors, 4000.0)
    sensor_contacts.tick(player, 0.0)
    assert (App.ET_SENSORS_SHIP_FAR_PROXIMITY, bird, True) in posted
    assert (App.ET_SENSORS_SHIP_NEAR_PROXIMITY, bird, True) in posted


def test_sweep_posts_nothing_via_probe_when_player_sensors_dead(_no_game, monkeypatch):
    from engine.appc import sensor_contacts
    posted = []
    monkeypatch.setattr(sensor_contacts, "_post",
                        lambda et, obj, entered, sensors: posted.append((et, obj, entered)))
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4400.0)
    _probe_at(s, sensors, 4000.0)
    sensors._condition = 10.0
    sensor_contacts.tick(player, 0.0)
    assert [p for p in posted if p[1] is bird] == []


def test_continuity_runs_for_a_known_probe_reached_contact_behind_a_rock(_no_game, occlusion_enabled, monkeypatch):
    from engine.appc import sensor_contacts
    from tests.helpers.rocks import make_major_rock
    monkeypatch.setattr(sensor_contacts, "_helm_exited_set", lambda obj: None)
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4500.0)
    _probe_at(s, sensors, 4000.0)
    # unknown to the player on purpose: memory cannot be why it is in reach
    make_major_rock(s, "Rock", at=(4250.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_contacts.is_concealed(player, bird) is True
```

Notes for the implementer:
- Read `sensor_contacts._post`'s real signature first and match the monkeypatch lambda to it; if the posting goes elsewhere, assert on the real recording seam the existing `tests/unit/test_sensor_contacts.py` uses.
- `test_continuity_runs_for_a_known_probe_reached_contact_behind_a_rock` asserts `is_concealed` (which uses `in_reach`, Task 2); it is unknown to the player on purpose so memory cannot be the reason it is in reach. If `is_concealed` rejects unknown contacts by design, change the assertion target to `sd.in_reach(player, bird) is True and sd.can_detect(player, bird) is False` and say so in the report.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_probes.py -q`
Expected: band and sweep tests FAIL.

- [ ] **Step 3: Implement**

In `SensorSubsystem` (`engine/appc/subsystems.py`), replace `IsObjectNear` and `IsObjectFar` with:

```python
    def _own_band(self, obj, fraction) -> bool:
        """Owner-only band test: centre distance within *fraction* of this
        subsystem's own effective range, same set."""
        d = self._band_distance(obj)
        r = self.GetSensorRange()
        return d is not None and r > 0.0 and d <= r * fraction

    def _probe_band(self, obj, fraction) -> bool:
        """Any live probe, in the owner's set, whose own band covers obj
        (BC: IsObjectNear/IsObjectFar fall back to walking the probe list)."""
        ship = self._owner_ship()
        pset = ship.GetContainingSet() if ship is not None else None
        if pset is None or obj is None or obj.GetContainingSet() is not pset:
            return False
        for probe in self.probes():
            ps = probe.GetSensorSubsystem() if hasattr(type(probe), "GetSensorSubsystem") else None
            if (ps is not None and probe.GetContainingSet() is pset
                    and ps._own_band(obj, fraction)):
                return True
        return False

    def IsObjectNear(self, obj) -> int:
        """Within near_fraction (BC: half) of sensor range -- the owner's or
        a live probe's own (sub-project 4). Pure distance."""
        from engine.appc import sensor_dials
        nf = sensor_dials.get("near_fraction")
        return 1 if (self._own_band(obj, nf) or self._probe_band(obj, nf)) else 0

    def IsObjectFar(self, obj) -> int:
        """Within full sensor range -- the owner's or a live probe's own."""
        return 1 if (self._own_band(obj, 1.0) or self._probe_band(obj, 1.0)) else 0
```

(Use `engine.core.ids.implements(probe, "GetSensorSubsystem")` instead of the `hasattr(type(...))` probe if `implements` is already imported in `subsystems.py`; never plain `hasattr` on a TGObject — it is vacuously True.)

In `engine/appc/sensor_contacts.py`:

`_in_near_band`:

```python
def _in_near_band(player, obj) -> bool:
    from engine.appc.sensor_detection import effective_sensor_range
    if effective_sensor_range(player) <= 0.0:
        return False
    sensors = player.GetSensorSubsystem()
    return sensors is not None and bool(sensors.IsObjectNear(obj))
```

`_sweep`: replace

```python
    r = effective_sensor_range(player)
    nf = sensor_dials.get("near_fraction")
```

with

```python
    alive = effective_sensor_range(player) > 0.0   # BC's sweep bails on dead sensors
```

and inside the loop replace

```python
        d = _dist(player, obj)
        far = r > 0.0 and d <= r
        near = r > 0.0 and d <= r * nf
```

with

```python
        far = alive and bool(sensors.IsObjectFar(obj))
        near = alive and bool(sensors.IsObjectNear(obj))
```

Keep the `dwell = …` line. If `_dist` or `sensor_dials` become unused in `sensor_contacts.py`, check with grep before removing an import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_probes.py tests/unit/test_sensor_contacts.py tests/unit/test_sensor_continuity.py tests/unit/test_sensor_bands_and_visibility.py tests/unit/test_sensor_identification.py tests/unit/test_sensor_scan.py tests/unit/test_sensor_scan_dwell.py tests/integration/test_sensor_continuity_missions.py tests/integration/test_sensor_memory_missions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py engine/appc/sensor_contacts.py tests/unit/test_sensor_probes.py
git commit -m "feat(sensors): near/far bands and the player's sweep count probes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Launch Probe end to end, and E6M4

**Files:**
- Create: `tests/integration/test_sensor_probe_launch.py`
- (Production code only if a test exposes a real gap — then a failing test first, and report it.)

**Interfaces:**
- Consumes: Tasks 1–3; `tests/helpers/headless_mission.load(name)` and `tick(seconds)`; SDK `Bridge.ScienceMenuHandlers.LaunchProbe(pObject, pEvent)` / `MakeLaunchProbeAction(pAction, iShipID)`; `Actions.ShipScriptActions.LaunchObject`.
- Produces: tests only.

- [ ] **Step 1: Investigate (record findings in the report before writing tests)**

1. Pick the harness mission: E6M4 (`Maelstrom.Episode6.E6M4.E6M4`) via `headless_mission.load`. Confirm the player is a Galaxy-class (or Sovereign) ship with an `OEP_PROBE` ObjectEmitterProperty (grep the hardpoint) and that `GetNumProbes()` is seeded (10).
2. Confirm the mission harness's emission RECORDER is not installed in this path (`engine/appc/emission.py` is installed only by `tools/mission_harness.py` `setup_sdk`). If it is, find how to run the real `ShipScriptActions.LaunchObject` (do not monkeypatch production code to fake a spawn).
3. Find how to fire the launch: call `ScienceMenuHandlers.LaunchProbe(None, evt)` the way the menu does, or play `MakeLaunchProbeAction(None, player.GetObjID())` directly; then advance time with `headless_mission.tick(1.0)` so the 0.5 s delayed action and the probe event run. Read `tests/integration/test_e1m2_scan_area.py` for how an SDK menu handler is dispatched headlessly.
4. For E6M4: find what puts the player in set "Tezle1" (the mission's own set creation / warp), how `ProbeLaunched` is registered (`E6M4.py:562`), and which flags `ProbeLaunched` checks (`g_bProbeReachedPlanet`, the set name). Find "Tezle 1"'s radius and the inner check radius (radius + 5).

- [ ] **Step 2: Write the tests**

Create `tests/integration/test_sensor_probe_launch.py` with these tests (adapt the setup lines to what Step 1 found; keep every assertion):

```python
"""Sensor-model sub-project 4 end to end: the REAL Science Launch Probe path
(SDK ScienceMenuHandlers -> ShipScriptActions.LaunchObject, no emission
recorder) spawns a probe that the player's sensors count and see through; and
E6M4's probe goal registers the launched probe and fires its planet proximity
check (2026-10-07-sensor-probes-design.md)."""
import App
import MissionLib
import pytest

from engine.appc import sensor_occlusion
from engine.appc.sensor_detection import can_detect, effective_sensor_range
from tests.helpers import headless_mission

E6M4 = "Maelstrom.Episode6.E6M4.E6M4"


def _launch(player):
    """Fire the real launch and let its 0.5 s delayed action run."""
    import Bridge.ScienceMenuHandlers as smh
    seq = smh.MakeLaunchProbeAction(None, player.GetObjID())
    if seq is not None and hasattr(seq, "Play"):
        seq.Play()
    headless_mission.tick(1.0)


@pytest.fixture
def e6m4_player():
    mission, episode, game, mod = headless_mission.load(E6M4)
    player = MissionLib.GetPlayer()
    assert player is not None
    sensor_occlusion.set_enabled(False)
    return mod, player


def test_launch_spawns_a_counted_listed_probe(e6m4_player):
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    pSet = player.GetContainingSet()
    before = sensors.GetNumProbes()
    assert before > 0
    sensors.SetNumProbes(before - 1)         # LaunchProbe decrements before the action
    _launch(player)
    probes = sensors.probes()
    assert len(probes) == 1
    probe = probes[0]
    assert probe.GetContainingSet() is pSet
    assert probe.GetName().startswith("Probe ")
    v = probe.GetVelocityTG()
    assert (v.x * v.x + v.y * v.y + v.z * v.z) > 0.0
    assert can_detect(player, probe) is True


def test_launch_probe_handler_decrements_the_count(e6m4_player):
    import Bridge.ScienceMenuHandlers as smh
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    before = sensors.GetNumProbes()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_LAUNCH_PROBE)
    smh.LaunchProbe(None, evt)
    headless_mission.tick(1.0)
    assert sensors.GetNumProbes() == before - 1
    assert len(sensors.probes()) == 1


def test_launch_with_no_probes_left_spawns_nothing(e6m4_player):
    import Bridge.ScienceMenuHandlers as smh
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    sensors.SetNumProbes(0)
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_LAUNCH_PROBE)
    smh.LaunchProbe(None, evt)
    headless_mission.tick(1.0)
    assert sensors.GetNumProbes() == 0
    assert sensors.probes() == []


def test_launched_probe_sees_a_ship_beyond_player_range(e6m4_player):
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    sensors.SetNumProbes(sensors.GetNumProbes() - 1)
    _launch(player)
    probe = sensors.probes()[0]
    r = effective_sensor_range(player)
    p = probe.GetWorldLocation()
    q = player.GetWorldLocation()
    # A ship placed on the far side of the probe: beyond player range, 300 GU from the probe.
    dx, dy, dz = p.x - q.x, p.y - q.y, p.z - q.z
    n = (dx * dx + dy * dy + dz * dz) ** 0.5 or 1.0
    from engine.appc.ships import ShipClass_Create
    far = ShipClass_Create("BirdOfPrey")
    far.SetTranslateXYZ(q.x + dx / n * (r + 300.0), q.y + dy / n * (r + 300.0), q.z + dz / n * (r + 300.0))
    probe.SetTranslateXYZ(q.x + dx / n * r, q.y + dy / n * r, q.z + dz / n * r)
    player.GetContainingSet().AddObjectToSet(far, "FarBird")
    assert can_detect(player, far) is True
    probe.GetContainingSet().RemoveObjectFromSet(probe.GetName())
    assert can_detect(player, far) is False


def test_e6m4_registers_the_probe_and_reaches_tezle_1(e6m4_player):
    """Drive E6M4's own ProbeLaunched handler with a real launch in Tezle1.
    If the Intercept AI cannot bring the probe within radius+5 headlessly,
    keep the registration half and record why in the test docstring
    (spec: Testing)."""
    mod, player = e6m4_player
    # Setup per Step 1 findings: get the player into Tezle1 the way the mission does.
    ...
```

Fill in `test_e6m4_registers_the_probe_and_reaches_tezle_1` from your Step 1 findings: get the player into the `Tezle1` set by the mission's own path, launch for real, assert `mod.g_lProbeNames` contains the probe's name (registration), then `headless_mission.tick(...)` in bounded steps (≤ 300 s game time) and assert `mod.g_bProbeReachedPlanet` is true. If the reach half cannot pass headlessly, assert the registration half, mark nothing xfail, and write the reason (with the measured closest approach) in the docstring and the report.

Notes:
- `App.TGEvent_Create` / `SetEventType` names: check `engine/appc/events.py` for the real constructor; use whatever the existing menu-dispatch test uses.
- `RemoveObjectFromSet` takes the object's name in this engine (see `tests/integration/test_sensor_continuity_missions.py`).
- If any of these fail because production behaviour is wrong (not because of harness setup), write the minimal failing test, fix production code, and report it as DONE_WITH_CONCERNS with the evidence.

- [ ] **Step 3: Run them**

Run: `uv run pytest tests/integration/test_sensor_probe_launch.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_sensor_probe_launch.py
git commit -m "test(sensors): real Launch Probe end to end and E6M4's probe goal

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Probe bench, docs and the gate

**Files:**
- Modify: `tests/unit/test_sensor_reach_bench.py`
- Modify: `docs/superpowers/specs/2026-10-07-sensor-probes-design.md` (append `## As built`)
- Modify: `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md` (row 4 status)
- Modify: `CLAUDE.md` ("Sensor tiers" row — ≤ 1200 chars, `tests/docs/test_doc_consistency.py`)

**Interfaces:**
- Consumes: the branch as built.
- Produces: a bench test and docs.

- [ ] **Step 1: Bench test**

Append to `tests/unit/test_sensor_reach_bench.py`:

```python
def test_probe_branch_stays_within_budget(monkeypatch):
    from tests.unit.test_sensor_probes import _probe_at
    monkeypatch.setattr(contact_index, "nebulae_in", lambda pSet: ())
    s, obs, sensors = _observer_in_set(2000.0)
    for x in (3000.0, 6000.0, 9000.0):
        _probe_at(s, sensors, x)
    near = [_ship_at(s, "n%d" % i, 100.0 + i) for i in range(40)]
    far = [_ship_at(s, "f%d" % i, 9300.0 + i) for i in range(40)]  # reached by the 3rd probe only
    assert all(sd.can_detect(obs, x) for x in far)
    _per_call(obs, near + far, 20)
    in_range = min(_per_call(obs, near, 200) for _ in range(3))
    via_probe = min(_per_call(obs, far, 200) for _ in range(3))
    assert via_probe <= 5.0 * in_range, (via_probe, in_range)
```

(Budget 5× here, not 3×: three probes each run one full `can_detect`. If it fails, report the measured ratio; do not raise the budget without a ruling.)

Run: `uv run pytest tests/unit/test_sensor_reach_bench.py -q` — expected PASS.

- [ ] **Step 2: Run the gate**

Run: `scripts/check_tests.sh` (slow — run in the background and poll its log). Expected: exit 0. A failure caused by this branch is fixed through a failing test; never edit `tests/known_failures.txt`.

- [ ] **Step 3: Docs**

- Spec: append `## As built` — every deviation or ruling from the SDD ledger, the E6M4 outcome (reach half passed, or why only registration is pinned), the bench ratio.
- Roadmap row 4: status → `built, unmerged (feat/sensor-probes) — spec: \`2026-10-07-sensor-probes-design.md\``.
- CLAUDE.md "Sensor tiers" row: add `SP4: probes (\`AddProbe\`, count from MaxProbes) see for their launcher in \`can_detect\` and the near/far bands (not jam-gated).` — keep every existing fact; if the row would exceed 1200 chars, shorten the SP3/SP4 clauses, never the SP1/SP2 facts. Run `uv run pytest tests/docs/test_doc_consistency.py -q`.

- [ ] **Step 4: Commit and re-run the gate**

```bash
git add tests/unit/test_sensor_reach_bench.py docs/superpowers/specs/2026-10-07-sensor-probes-design.md docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md CLAUDE.md
git commit -m "docs(sensors): SP4 as built; probe bench; roadmap and CLAUDE.md row

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Run `scripts/check_tests.sh` again on the final commit. Expected: exit 0.
