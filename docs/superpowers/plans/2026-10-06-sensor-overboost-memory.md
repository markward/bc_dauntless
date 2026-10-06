# Sensor Over-boost and Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `sensor_detection.can_detect` BC's two out-of-range ways in — sensor memory (a known contact stays detected) and over-boost (sensors above 1.2 normal power see the whole set) — both cancelled by a nebula jam, and make `SensorSubsystem.IsObjectVisible` give the same answer.

**Architecture:** `can_detect` keeps every gate it has. When its final range test fails it asks a new private `_beyond_range_reach(observer, target, cloaked)`: same set ∧ not fully cloaked ∧ (boosted ∨ known) ∧ not `jammed`. `jammed` is BC's yes/no "observer or target inside any MetaNebula in the set". `in_reach` (reach ignoring the hide gates) feeds the continuity clock. `IsObjectVisible` keeps BC's set gate and then delegates.

**Tech Stack:** Python 3.11, pytest (`uv run pytest`), the headless App shim. No C++ changes.

**Spec:** `docs/superpowers/specs/2026-10-06-sensor-overboost-memory-design.md` (read it first; its Evidence table is the RE basis for every rule here). Roadmap: `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md`.

## Global Constraints

- Work ONLY in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/sensor-overboost-memory`, branch `feat/sensor-overboost-memory`. Never commit to main. Never push.
- ⛔ Banned git (shared checkout): `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths only. To mutate a file temporarily: `cp f /tmp/bak` → edit → test → `cp /tmp/bak f` → `diff f /tmp/bak`.
- Never launch the game (`./build/dauntless`). Never `pkill`/`killall`.
- Over-boost threshold: **strictly greater than** `overboost_threshold`, default **1.2** (RE'd constant `0x0089054c`), compared against `GetNormalPowerPercentage()` — NEVER `GetPowerPercentage()`.
- Jam = observer OR target inside any `MetaNebula` in the observer's set (`contact_index.nebulae_in` + `IsObjectInNebula`). Not `concealment_at`. The radial system-profile nebula never jams.
- The new branches require same set AND target not fully cloaked (`IsCloaked()`). The existing range branch is byte-identical (cross-set `dist_sq_gu` callers unchanged).
- `ENHANCED_SENSOR_CONTEST` / `apply_concealment` do NOT switch the new branches off.
- Every tunable is a dial in `engine/appc/sensor_dials.py` (the "sensors" group on the shared / L O keys).
- Units are GU. Check `docs/stub_heatmap.md` before claiming any SDK call is a no-op; never decide surface exists by grepping `def <Name>(`.
- Gate: `scripts/check_tests.sh` must exit 0 before the branch is called done. `tests/known_failures.txt` holds no failure entries — fix, never baseline.
- Test command form: `uv run pytest <path> -q`.

## Review Focus

1. **Cross-set target at nearby coordinates** — a known (or boosted-on) target in ANOTHER set, close by, must not be detected through the new branches; the cross-set torpedo `dist_sq_gu` path must still answer by range only. Pinned in Task 3 (`test_known_target_in_another_set_is_not_reached`, `test_cross_set_dist_sq_path_is_range_only`).
2. **Sensors die, then recover** — a remembered far contact vanishes when the player's sensors go offline and comes back (memory not wiped) when they recover. Pinned in Task 3 (`test_memory_drops_with_dead_sensors_and_returns_on_repair`).
3. **Boost reached through the real slider, under-fed** — 125% wanted with a full grid crosses 1.2; 125% wanted with a grid supplying ≤ 1.2× normal does not. Pinned in Task 3 (`test_boost_through_the_real_power_path`).
4. **Lock on a remembered far target** — `clear_undetectable_player_lock` keeps the player's lock on a known contact that leaves range, and drops it when the contact is jammed. Pinned in Task 6 (`test_lock_survives_range_and_drops_when_jammed`).
5. **Player leaves the set and returns** — memory does not resurrect a far ship after a set change (identity is wiped on leaving, existing behaviour). Pinned in Task 6 (`test_set_change_wipes_memory_so_far_ships_stay_unlisted`).

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `engine/appc/sensor_dials.py` | add `overboost_threshold` dial | 2 |
| `engine/appc/sensor_detection.py` | `jammed`, `_same_set`, `_beyond_range_reach`, `in_reach`; `can_detect` tail | 2, 3 |
| `engine/appc/subsystems.py` (`SensorSubsystem.IsObjectVisible`) | delegate to `can_detect` after BC's set gate | 4 |
| `engine/appc/sensor_contacts.py` (`is_concealed`) | use `in_reach` instead of a raw range test | 5 |
| `tests/unit/test_sensor_reach.py` (new) | jam, memory, boost, in_reach matrix | 2, 3 |
| `tests/unit/test_sensor_dials.py` | dial set/min updates | 2 |
| `tests/unit/test_sensor_bands_and_visibility.py` | cloak test rewrite, delegation equivalence | 4 |
| `tests/unit/test_sensor_continuity.py` | rewrite leaving-range test, add memory/jam clock tests | 5 |
| `tests/integration/test_sensor_memory_missions.py` (new) | E2M1 end-to-end memory / jam / boost; lock; set change | 6 |
| `tests/unit/test_sensor_reach_bench.py` (new) | CPU budget for the new branch | 6 |
| spec, roadmap, `CLAUDE.md` | audit findings, As built, row status | 1, 7 |

---

### Task 1: Audit consumers that assume "out of range ⇒ off the list"

Read-only investigation. No production code changes. Output is a findings section appended to the spec. If any finding is UNSAFE (a mission or handler that misbehaves when a remembered contact stays listed, or an over-boosted Unknown appears), STOP and report BLOCKED with the evidence — do not invent a guard.

**Files:**
- Modify: `docs/superpowers/specs/2026-10-06-sensor-overboost-memory-design.md` (append `## Audit findings (Task 1)`)

**Interfaces:**
- Consumes: nothing.
- Produces: a findings table later tasks may cite; no code.

- [ ] **Step 1: Locate the SDK root**

Run: `uv run python -c "from engine import paths; print(paths.sdk_scripts())"`
Use the printed path as `$SDK` below.

- [ ] **Step 2: Science scan-button removal**

Read `$SDK/Bridge/ScienceMenuHandlers.py` — every function reached from `ET_TARGET_LIST_OBJECT_REMOVED` (grep that name). Record: what it removes, and whether anything breaks if the event simply never fires for a remembered out-of-range contact (expected: the contact keeps its Scan button — acceptable, BC behaviour).

Run: `grep -rn "ET_TARGET_LIST_OBJECT_REMOVED" "$SDK" engine/ --include=*.py`

- [ ] **Step 3: Engine consumers of perceivability**

Run: `grep -rn "perceivable\|perceived_by(\|clear_undetectable_player_lock\|IsObjectVisible" engine/ --include=*.py`
For each production reader, record one line: does it assume a contact beyond `effective_sensor_range` is absent? (e.g. a radar disc clip is fine — it clips by its own display range.)

- [ ] **Step 4: Mission beats**

Read these call sites and record whether each still behaves (they read power or identity, not the list):
- `$SDK/Maelstrom/Episode2/E2M2/E2M2.py` around `:1934` and `:2012` (`IsBoosted(pSensors, 1.2)` — eavesdrop), and its unidentified-ships beat (grep `IdentifyObject\|IsObjectKnown\|ET_SENSORS_SHIP_IDENTIFIED` in E2M2.py).
- `$SDK/Maelstrom/Episode7/E7M6/E7M6.py` `:607`, `:865`, `:2158`, `:2518`.
- `$SDK/Maelstrom/Episode8/E8M1/E8M1.py` `:2699`.
- `$SDK/MissionLib.py` `IsBoosted` (`:2315`).

- [ ] **Step 5: AI memory exposure**

Run: `grep -rn "ForceObjectIdentified\|AddKnownObject" "$SDK" engine/ --include=*.py | grep -v "^tests/"`
Record whether any path adds known objects to a NON-player ship's sensors (which would give that AI ship memory). `IdentifyObject` is already player-only (`subsystems.py` `IdentifyObject`); `ForceObjectIdentified` is not gated.

- [ ] **Step 6: Write findings and commit**

Append to the spec:

```markdown
## Audit findings (Task 1)

| Consumer | Assumes out-of-range ⇒ absent? | Verdict |
|---|---|---|
| <one row per item from Steps 2–5> | yes/no + file:line | safe / UNSAFE (why) |
```

```bash
git add docs/superpowers/specs/2026-10-06-sensor-overboost-memory-design.md
git commit -m "docs(sensors): SP3 audit of out-of-range consumers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `overboost_threshold` dial and the `jammed` predicate

**Files:**
- Modify: `engine/appc/sensor_dials.py`
- Modify: `engine/appc/sensor_detection.py` (add `_same_set`, `jammed` after `is_hidden_by_cloak`)
- Modify: `tests/unit/test_sensor_dials.py`
- Create: `tests/unit/test_sensor_reach.py`

**Interfaces:**
- Consumes: `contact_index.nebulae_in(pSet) -> tuple`, `MetaNebula.IsObjectInNebula(obj) -> int`, `engine.core.ids.implements`.
- Produces: `sensor_dials.get("overboost_threshold") -> float` (default 1.2); `sensor_detection.jammed(observer, target) -> bool`; `sensor_detection._same_set(observer, target) -> bool`.

- [ ] **Step 1: Write the failing dial tests**

In `tests/unit/test_sensor_dials.py`:

1. In `test_step_is_pure_additive_and_clamped`, add `overboost_threshold=0.5` to the `low = dict(d, ...)` call (it is now a dial at its minimum too), and after the `high` assertion add:

```python
    top = dict(d, overboost_threshold=2.0)
    assert sensor_dials.step(top, "overboost_threshold", +1)["overboost_threshold"] == 2.0
```

2. In `test_continuity_and_occlusion_dials_defaults_and_order`, change the final set to include the new dial:

```python
    assert set(sensor_dials.DIAL_ORDER[3:]) == {
        "continuity_window_s", "min_blocker_radius_gu",
        "field_unknown_threshold", "nebula_unknown_threshold",
        "overboost_threshold"}
```

3. Append:

```python
def test_overboost_threshold_is_bcs_recovered_value_and_steps_by_a_hundredth():
    sensor_dials.reset()
    assert sensor_dials.get("overboost_threshold") == 1.2
    d = dict(sensor_dials.DEFAULTS)
    assert sensor_dials.step(d, "overboost_threshold", +1)["overboost_threshold"] == 1.21
    assert sensor_dials.step(d, "overboost_threshold", -1)["overboost_threshold"] == 1.19
```

- [ ] **Step 2: Write the failing jam tests**

Create `tests/unit/test_sensor_reach.py`:

```python
"""Sensor-model sub-project 3: BC's out-of-range ways in -- sensor memory and
over-boost -- and the nebula jam that cancels both
(2026-10-06-sensor-overboost-memory-design.md). Nebulae are fakes fed through
contact_index.nebulae_in, as tests/unit/test_sensor_bands_and_visibility.py
does: a real MetaNebula also adds density (concealment_at), which would let the
dense-core gate answer instead of the jam and hide what these tests pin."""
import pytest

from engine.appc import contact_index, sensor_dials
from engine.appc import sensor_detection as sd
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem, CloakingSubsystem


def _observer_in_set(base_range=2000.0):
    s = SetClass()
    obs = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    obs.SetSensorSubsystem(sensors)
    s.AddObjectToSet(obs, "observer")
    return s, obs, sensors


def _ship_at(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


class _Neb:
    """A nebula that contains exactly the objects it is given."""
    def __init__(self, *inside):
        self._inside = inside

    def IsObjectInNebula(self, obj):
        return 1 if any(obj is o for o in self._inside) else 0


def _nebulae(monkeypatch, *nebs):
    monkeypatch.setattr(contact_index, "nebulae_in", lambda pSet: tuple(nebs))


# ── jammed ──────────────────────────────────────────────────────────────────

def test_jammed_when_the_target_is_in_a_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    _nebulae(monkeypatch, _Neb(tgt))
    assert sd.jammed(obs, tgt) is True


def test_jammed_when_the_observer_is_in_a_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    _nebulae(monkeypatch, _Neb(obs))
    assert sd.jammed(obs, tgt) is True


def test_not_jammed_when_neither_is_in_any_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    other = _ship_at(s, "o", 9000.0)
    _nebulae(monkeypatch, _Neb(other))
    assert sd.jammed(obs, tgt) is False


def test_not_jammed_with_no_nebulae_even_inside_profile_concealment(monkeypatch):
    # The radial system-profile nebula is density, not a MetaNebula: never a jam.
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    monkeypatch.setattr(sd, "concealment_at", lambda ship: 0.19)
    assert sd.jammed(obs, tgt) is False


def test_jammed_never_raises_on_a_broken_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)

    class _Broken:
        def IsObjectInNebula(self, obj):
            raise RuntimeError("boom")

    _nebulae(monkeypatch, _Broken())
    assert sd.jammed(obs, tgt) is False


def test_jammed_is_false_for_an_observer_in_no_set():
    obs = ShipClass_Create("Galaxy")
    tgt = ShipClass_Create("BirdOfPrey")
    assert sd.jammed(obs, tgt) is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_dials.py tests/unit/test_sensor_reach.py -q`
Expected: FAIL — `KeyError: 'overboost_threshold'` and `AttributeError: module 'engine.appc.sensor_detection' has no attribute 'jammed'`.

- [ ] **Step 4: Add the dial**

In `engine/appc/sensor_dials.py`:
- Extend the module docstring's last paragraph-before-"Read at use" with: `"overboost_threshold" is BC's recovered over-boost constant (1.2f at 0x0089054c, compared strictly-greater against NormalPowerPercentage in IsObjectVisible @0x005671D0; sub-project 3, 2026-10-06-sensor-overboost-memory-design.md). RE tier, not tested.`
- Add to `DEFAULTS` after `nebula_unknown_threshold`:

```python
    # Sub-project 3 (2026-10-06-sensor-overboost-memory-design.md) -- BC's
    # recovered constant (0x0089054c), RE tier.
    "overboost_threshold": 1.2,       # NormalPowerPercentage strictly above this sees the set
```

- Add `"overboost_threshold": 0.01` to `_STEP`, `"overboost_threshold": 0.5` to `_MIN`, `"overboost_threshold": 2.0` to `_MAX`.

- [ ] **Step 5: Add `_same_set` and `jammed`**

In `engine/appc/sensor_detection.py`, directly after `is_hidden_by_cloak`:

```python
def _same_set(observer, target) -> bool:
    """BC's set gate (IsObjectVisible: owner +0x20 == target +0x20)."""
    oset = observer.GetContainingSet() if implements(observer, "GetContainingSet") else None
    tset = target.GetContainingSet() if implements(target, "GetContainingSet") else None
    return oset is not None and oset is tset


def jammed(observer, target) -> bool:
    """BC's nebula-interference flag (IsObjectVisible @0x005671D0, disassembly
    0x00567245-0x00567282): True iff *observer* OR *target* is inside any
    MetaNebula in the observer's set. A yes/no membership test, distinct from
    the density `concealment_at`: the radial system-profile nebula is not a
    MetaNebula and never jams. It cancels only the two out-of-range ways in
    (`_beyond_range_reach`); the range test never consults it. Never raises --
    a nebula that fails answers "not in it" and is logged once."""
    pset = observer.GetContainingSet() if implements(observer, "GetContainingSet") else None
    if pset is None:
        return False
    from engine.appc import contact_index
    for neb in contact_index.nebulae_in(pset):
        try:
            if neb.IsObjectInNebula(observer) or neb.IsObjectInNebula(target):
                return True
        except Exception as e:
            import engine.dev_mode as dev_mode
            dev_mode.log_swallowed("sensor_detection.jammed", e)
    return False
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_dials.py tests/unit/test_sensor_reach.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/sensor_dials.py engine/appc/sensor_detection.py tests/unit/test_sensor_dials.py tests/unit/test_sensor_reach.py
git commit -m "feat(sensors): overboost_threshold dial and BC's nebula jam predicate

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Memory and over-boost in `can_detect`; `in_reach`

**Files:**
- Modify: `engine/appc/sensor_detection.py` (`can_detect` tail; new `_beyond_range_reach`, `in_reach`; module docstring)
- Modify: `tests/unit/test_sensor_reach.py`

**Interfaces:**
- Consumes: `jammed`, `_same_set` (Task 2); `sensor_dials.get("overboost_threshold")`; `SensorSubsystem.GetNormalPowerPercentage()`, `.IsObjectKnown(obj) -> int`; `effective_sensor_range`, `is_hidden_by_cloak`, `_get_xyz`.
- Produces: `can_detect(...)` with the new branches (signature unchanged); `sensor_detection.in_reach(observer, target) -> bool`; private `_beyond_range_reach(observer, target, cloaked: bool) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sensor_reach.py`:

```python
# ── memory ──────────────────────────────────────────────────────────────────

def test_known_contact_beyond_range_is_detected():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.can_detect(obs, far) is False
    sensors.AddKnownObject(far)
    assert sd.can_detect(obs, far) is True


def test_unknown_contact_beyond_range_is_not_detected():
    s, obs, _ = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.can_detect(obs, far) is False


@pytest.mark.parametrize("who", ["target", "observer"])
def test_jam_cancels_memory(monkeypatch, who):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    sensors.AddKnownObject(far)
    _nebulae(monkeypatch, _Neb(far if who == "target" else obs))
    assert sd.can_detect(obs, far) is False


def test_known_target_in_another_set_is_not_reached():
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(5000.0, 0.0, 0.0)
    other.AddObjectToSet(ship, "elsewhere")
    sensors.AddKnownObject(ship)
    sensors._power_factor = 1.25
    assert sd.can_detect(obs, ship) is False


def test_cross_set_dist_sq_path_is_range_only():
    # projectiles.py hands a cross-set offset in via dist_sq_gu; that path must
    # keep answering by range alone.
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    other.AddObjectToSet(ship, "elsewhere")
    sensors.AddKnownObject(ship)
    assert sd.can_detect(obs, ship, dist_sq_gu=1000.0 ** 2) is True
    assert sd.can_detect(obs, ship, dist_sq_gu=5000.0 ** 2) is False


def test_memory_never_reveals_a_fully_cloaked_target():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    far.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    far.GetCloakingSubsystem().InstantCloak()
    sensors.AddKnownObject(far)
    assert sd.can_detect(obs, far) is False


def test_memory_drops_with_dead_sensors_and_returns_on_repair():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    sensors.AddKnownObject(far)
    sensors._condition = 10.0             # below the 25% disabled threshold
    assert sd.can_detect(obs, far) is False
    sensors._condition = 100.0
    assert sd.can_detect(obs, far) is True   # memory itself was never wiped


def test_memory_respects_occlusion(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    sensors.AddKnownObject(far)
    make_major_rock(s, "Rock", at=(2500.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is False


def test_ai_observer_never_reaches_by_memory():
    # AI has no identification tier: a fresh AI ship's sensors know nothing.
    s, ai, _ = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.can_detect(ai, far) is False


# ── over-boost ──────────────────────────────────────────────────────────────

def test_boost_above_threshold_sees_the_whole_set():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.2 + 1e-6
    assert sd.can_detect(obs, far) is True


def test_boost_exactly_at_threshold_does_not():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.2
    assert sd.can_detect(obs, far) is False


def test_boost_threshold_is_the_dial(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.1
    assert sd.can_detect(obs, far) is False
    monkeypatch.setitem(sensor_dials._dials, "overboost_threshold", 1.05)
    assert sd.can_detect(obs, far) is True


@pytest.mark.parametrize("who", ["target", "observer"])
def test_jam_cancels_boost(monkeypatch, who):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.25
    _nebulae(monkeypatch, _Neb(far if who == "target" else obs))
    assert sd.can_detect(obs, far) is False


def test_boost_never_reveals_a_fully_cloaked_target():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    far.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    far.GetCloakingSubsystem().InstantCloak()
    sensors._power_factor = 1.25
    assert sd.can_detect(obs, far) is False


def test_boost_does_not_identify():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.25
    assert sd.can_detect(obs, far) is True
    assert sensors.IsObjectKnown(far) == 0


def test_boost_through_the_real_power_path():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._normal_power = 1.0

    class _Grid:
        def __init__(self, cap):
            self.cap = cap

        def _draw(self, wanted, mode):
            return min(wanted, self.cap)

    sensors.SetPowerPercentageWanted(1.25)
    sensors._update_power(1.0, _Grid(cap=10.0))           # fully fed: 1.25
    assert sensors.GetNormalPowerPercentage() == pytest.approx(1.25)
    assert sd.can_detect(obs, far) is True
    sensors._update_power(1.0, _Grid(cap=1.2))            # under-fed: exactly 1.2
    assert sensors.GetNormalPowerPercentage() == pytest.approx(1.2)
    assert sd.can_detect(obs, far) is False


# ── in_reach (for the continuity clock) ────────────────────────────────────

def test_in_reach_ignores_occlusion(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    near = _ship_at(s, "near", 500.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, near) is False
    assert sd.in_reach(obs, near) is True


def test_in_reach_uses_the_unshrunk_range(monkeypatch):
    # A ship in the dense nebula core is hidden, but still in reach.
    s, obs, _ = _observer_in_set(2000.0)
    tgt = _ship_at(s, "t", 1500.0)
    monkeypatch.setattr(sd, "concealment_at", lambda ship: 0.9)
    assert sd.can_detect(obs, tgt) is False
    assert sd.in_reach(obs, tgt) is True


def test_in_reach_includes_memory_and_respects_the_jam(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.in_reach(obs, far) is False
    sensors.AddKnownObject(far)
    assert sd.in_reach(obs, far) is True
    _nebulae(monkeypatch, _Neb(far))
    assert sd.in_reach(obs, far) is False


def test_in_reach_is_false_with_dead_sensors():
    s, obs, sensors = _observer_in_set(2000.0)
    near = _ship_at(s, "near", 10.0)
    sensors._condition = 10.0
    assert sd.in_reach(obs, near) is False
```

Also add at the top of the file, under the imports:

```python
from tests.helpers.rocks import occlusion_enabled  # noqa: F401  (fixture)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_reach.py -q`
Expected: the memory/boost "is True" tests FAIL (`assert False is True`), `in_reach` tests FAIL with `AttributeError: ... has no attribute 'in_reach'`. The "is False" tests may already pass — that is expected.

- [ ] **Step 3: Implement**

In `engine/appc/sensor_detection.py`:

1. Replace the last line of `can_detect` (`return dist_sq_gu <= (r * r)`) with:

```python
    if dist_sq_gu <= (r * r):
        return True
    # ── Beyond range (sub-project 3): BC's memory and over-boost ──────────
    return _beyond_range_reach(observer, target, cloaked)
```

2. Add after `can_detect`:

```python
def _beyond_range_reach(observer, target, cloaked) -> bool:
    """BC's two out-of-range ways in (IsObjectVisible @0x005671D0;
    2026-10-06-sensor-overboost-memory-design.md): OVER-BOOST -- the
    observer's NormalPowerPercentage strictly above the `overboost_threshold`
    dial (BC 1.2f @0x0089054c) sees the whole set -- and MEMORY -- a contact
    the observer's sensors already know (IsObjectKnown). Both need the same
    set and a target that is not fully cloaked (BC's set and absolute-cloak
    gates precede them), and both are cancelled by `jammed`. Neither
    identifies anything. Not part of the stage-4 contest: the
    ENHANCED_SENSOR_CONTEST / apply_concealment switches leave it on.
    AI has no identification tier, so memory never applies to an AI observer
    in practice, and AI never raises sensor power above 1.0."""
    if cloaked or not _same_set(observer, target):
        return False
    sensors = (observer.GetSensorSubsystem()
               if implements(observer, "GetSensorSubsystem") else None)
    if sensors is None:
        return False
    from engine.appc import sensor_dials
    boosted = (sensors.GetNormalPowerPercentage()
               > sensor_dials.get("overboost_threshold"))
    if not boosted:
        known = (implements(sensors, "IsObjectKnown")
                 and bool(sensors.IsObjectKnown(target)))
        if not known:
            return False
    return not jammed(observer, target)


def in_reach(observer, target) -> bool:
    """Would *observer* reach *target* if nothing hid it? The continuity
    clock's "in reach" (sensor_contacts.is_concealed): the UNSHRUNK effective
    range -- no density sample, no latch mutation, so a ship in the dense
    nebula core still counts -- or `_beyond_range_reach`. Ignores rock
    occlusion and the nebula core on purpose: those are what conceal."""
    r = effective_sensor_range(observer)
    if r <= 0.0:
        return False
    ox, oy, oz = _get_xyz(observer)
    tx, ty, tz = _get_xyz(target)
    dx, dy, dz = tx - ox, ty - oy, tz - oz
    if dx * dx + dy * dy + dz * dz <= r * r:
        return True
    return _beyond_range_reach(observer, target, is_hidden_by_cloak(target))
```

3. In the `can_detect` docstring, after the occlusion paragraph, add:

```
    Beyond range, BC's sensor MEMORY and OVER-BOOST still reach the target
    (``_beyond_range_reach``; sub-project 3): a known contact, or any contact
    when sensors run above ``overboost_threshold`` normal power -- same set,
    not fully cloaked, and not ``jammed``.
```

4. In the module docstring's first paragraph, after the occlusion sentence, add: `Beyond range, a known contact (BC's sensor memory) or any contact while sensors are over-boosted is still detected unless a nebula jams it (`jammed`; sub-project 3).`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_reach.py tests/unit/test_sensor_detection.py tests/unit/test_cloak_detection_contest.py tests/unit/test_nebula_hides_contacts_from_ui.py tests/unit/test_ai_sensor_gate.py tests/unit/test_player_lock_sensor_gate.py -q`
Expected: PASS. If an existing test fails because it placed a KNOWN or BOOSTED contact out of range and expected "not detected", that test encoded overturned decision 2: report it to the controller with the test name and the line — do not edit it silently.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_detection.py tests/unit/test_sensor_reach.py
git commit -m "feat(sensors): BC sensor memory and over-boost in can_detect; in_reach

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `IsObjectVisible` delegates to `can_detect`

**Files:**
- Modify: `engine/appc/subsystems.py` (`SensorSubsystem.IsObjectVisible`)
- Modify: `tests/unit/test_sensor_bands_and_visibility.py`

**Interfaces:**
- Consumes: `sensor_detection.can_detect(observer, target)` (Task 3).
- Produces: `SensorSubsystem.IsObjectVisible(obj) -> int` (0/1), equal to `can_detect(owner, obj)` for same-set objects, 0 otherwise.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_sensor_bands_and_visibility.py`:

1. Change the module docstring's last clause `IsObjectVisible's ordered gates, probes omitted).` to `IsObjectVisible = BC's set gate, then the one rule sensor_detection.can_detect -- sub-project 3).`

2. Replace `test_fully_cloaked_is_never_visible` with:

```python
def test_fully_cloaked_follows_the_cloak_contest():
    """IsObjectVisible gives the list's answer: a fully cloaked ship inside
    the cloak bubble is visible (BC: never -- our stage-4 contest), outside it
    is not, and neither memory nor over-boost reveals it."""
    from engine.appc.sensor_detection import (CLOAK_DETECTION_BASE_GU,
                                              CLOAK_RANGE_FACTOR)
    s, player, sensors = _player_in_set(2000.0)
    bubble = CLOAK_DETECTION_BASE_GU + 2000.0 * CLOAK_RANGE_FACTOR
    inside = _ship_at(s, "inside", bubble * 0.5)
    outside = _ship_at(s, "outside", bubble * 3.0)
    for ship in (inside, outside):
        ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        ship.GetCloakingSubsystem().InstantCloak()
        sensors.AddKnownObject(ship)
    assert sensors.IsObjectVisible(inside) == 1
    assert sensors.IsObjectVisible(outside) == 0
    sensors._power_factor = 1.25
    assert sensors.IsObjectVisible(outside) == 0
```

3. Append:

```python
def test_is_object_visible_matches_can_detect(monkeypatch):
    from engine.appc import contact_index
    from engine.appc.sensor_detection import can_detect
    s, player, sensors = _player_in_set(2000.0)
    ships = [_ship_at(s, "n%d" % i, x)
             for i, x in enumerate((10.0, 1500.0, 2500.0, 50000.0))]
    sensors.AddKnownObject(ships[2])

    class _Neb:
        def IsObjectInNebula(self, obj):
            return 1 if obj is ships[3] else 0

    for power in (1.0, 1.25):
        sensors._power_factor = power
        for jam in (False, True):
            monkeypatch.setattr(contact_index, "nebulae_in",
                                (lambda pSet: (_Neb(),)) if jam else (lambda pSet: ()))
            for ship in ships:
                assert sensors.IsObjectVisible(ship) == (1 if can_detect(player, ship) else 0), (
                    power, jam, ship.GetName())


def test_is_object_visible_keeps_bcs_set_gate():
    # can_detect's range branch has no set check (cross-set torpedoes); the
    # SDK surface must still refuse another set's object at close range.
    s, player, sensors = _player_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(10.0, 0.0, 0.0)
    other.AddObjectToSet(ship, "elsewhere")
    assert sensors.IsObjectVisible(ship) == 0


def test_is_object_visible_gets_occlusion(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, player, sensors = _player_in_set(2000.0)
    near = _ship_at(s, "near", 500.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    assert sensors.IsObjectVisible(near) == 0
```

And add under the imports: `from tests.helpers.rocks import occlusion_enabled  # noqa: F401  (fixture)`

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_bands_and_visibility.py -q`
Expected: FAIL — `test_fully_cloaked_follows_the_cloak_contest` (inside-bubble ship answers 0) and `test_is_object_visible_gets_occlusion` (answers 1).

- [ ] **Step 3: Implement**

Replace the body and docstring of `SensorSubsystem.IsObjectVisible` in `engine/appc/subsystems.py` with:

```python
    def IsObjectVisible(self, obj) -> int:
        """BC's IsObjectVisible (@0x005671D0): BC's same-set gate, then the
        one rule, sensor_detection.can_detect -- which carries BC's power,
        cloak, nebula-jam, over-boost, range and memory steps (probes:
        sensor-model sub-project 4) plus our occlusion, nebula-core and
        cloak-contest extensions. BC's target list and radar call this same
        function (RE xrefs 0x00538D86, 0x005443D7), so the SDK's direct
        callers and our list agree by construction
        (2026-10-06-sensor-overboost-memory-design.md). The set gate stays
        here because can_detect's range branch has none: cross-set torpedo
        guidance hands it an offset distance."""
        ship = self._owner_ship()
        if ship is None or obj is None:
            return 0
        pset = ship.GetContainingSet()
        if pset is None or obj.GetContainingSet() is not pset:
            return 0
        from engine.appc.sensor_detection import can_detect
        return 1 if can_detect(ship, obj) else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_bands_and_visibility.py tests/unit/test_sensor_reach.py -q`
Then: `uv run pytest tests -q -k "IsObjectVisible or visib or E3M2 or E1M2 or tactical" -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_sensor_bands_and_visibility.py
git commit -m "feat(sensors): IsObjectVisible delegates to can_detect after BC's set gate

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The continuity clock uses `in_reach`

**Files:**
- Modify: `engine/appc/sensor_contacts.py` (`is_concealed`)
- Modify: `tests/unit/test_sensor_continuity.py`

**Interfaces:**
- Consumes: `sensor_detection.in_reach(observer, target) -> bool` (Task 3).
- Produces: `sensor_contacts.is_concealed(player, obj) -> bool` — True iff ShipClass, same set, `in_reach`, not fully cloaked, `not can_detect`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_sensor_continuity.py`, replace `test_leaving_range_while_hidden_stops_the_clock` with the three tests below (the old one pinned roadmap decision 2, overturned by sub-project 3: memory keeps a known contact in reach beyond range):

```python
def test_known_ship_hidden_beyond_range_keeps_running_the_clock(helm):
    """Sub-project 3: memory keeps a known contact in reach beyond range, so a
    rock that hides it there still loses the track after the window."""
    s, player, sensors, bird, rock = _known_bird_behind_rock()
    sensor_contacts.tick(player, 0.0)
    bird.SetTranslateXYZ(9000.0, 0.0, 0.0)            # beyond 2000 GU, rock still on the line
    for t in (1.0, 2.0, 3.0, 4.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.is_concealed(player, bird) is True, t
    sensor_contacts.tick(player, 5.0)
    assert sensors.IsObjectKnown(bird) == 0
    sensor_contacts.tick(player, 6.0)
    assert helm == [bird]


def test_hidden_known_ship_that_goes_jammed_beyond_range_stops_the_clock(monkeypatch, helm):
    """Beyond range AND jammed is out of reach: not concealment, identity kept
    (roadmap decision 3)."""
    from engine.appc import contact_index
    s, player, sensors, bird, rock = _known_bird_behind_rock()
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.tick(player, 1.0)
    assert sensor_contacts.concealed_since(bird) == 0.0
    bird.SetTranslateXYZ(9000.0, 0.0, 0.0)

    class _Neb:
        def IsObjectInNebula(self, obj):
            return 1 if obj is bird else 0

    monkeypatch.setattr(contact_index, "nebulae_in", lambda pSet: (_Neb(),))
    for t in (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.concealed_since(bird) is None, t
    assert sensor_contacts.is_concealed(player, bird) is False
    assert helm == []


def test_unknown_ship_beyond_range_behind_a_rock_is_not_concealed(helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 9000.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_contacts.is_concealed(player, bird) is False


def test_boosted_player_concealment_counts_beyond_range(helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 9000.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    sensors._power_factor = 1.25
    assert sensor_contacts.is_concealed(player, bird) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_continuity.py -q`
Expected: FAIL — `test_known_ship_hidden_beyond_range_keeps_running_the_clock` (`is_concealed` False beyond range) and `test_boosted_player_concealment_counts_beyond_range`.

- [ ] **Step 3: Implement**

In `engine/appc/sensor_contacts.py` `is_concealed`, replace:

```python
        from engine.appc.sensor_detection import (can_detect, effective_sensor_range,
                                                  is_hidden_by_cloak)
        r = effective_sensor_range(player)
        if r <= 0.0 or _dist(player, obj) > r:
            return False
```

with:

```python
        from engine.appc.sensor_detection import (can_detect, in_reach,
                                                  is_hidden_by_cloak)
        if not in_reach(player, obj):
            return False
```

and change its docstring's first sentence to: `Does *obj* run the lost-track clock? In the player's set, IN REACH (sensor_detection.in_reach: unshrunk range, or BC's memory / over-boost unless jammed -- sub-project 3), HIDDEN (`not can_detect`) and not fully cloaked.` and replace `leaving range is never concealment.` with `leaving REACH is never concealment.`

If `_dist` is now unused anywhere in the module (`grep -n "_dist(" engine/appc/sensor_contacts.py`), leave it — other functions use it; only delete it if the grep shows no caller.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_continuity.py tests/unit/test_sensor_contacts.py tests/unit/test_sensor_identification.py tests/unit/test_sensor_scan.py tests/unit/test_sensor_scan_dwell.py tests/integration/test_sensor_continuity_missions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_contacts.py tests/unit/test_sensor_continuity.py
git commit -m "feat(sensors): continuity clock runs over memory/boost reach (in_reach)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: End-to-end on E2M1, lock, set change, and the CPU budget

**Files:**
- Create: `tests/integration/test_sensor_memory_missions.py`
- Create: `tests/unit/test_sensor_reach_bench.py`

**Interfaces:**
- Consumes: everything above; `perception.perceived_by(observer) -> tuple[Contact]` (`Contact.ship`, `.perceivable`, `.identified`); `sensor_detection.clear_undetectable_player_lock(player)`; the E2M1 harness pattern from `tests/integration/test_sensor_continuity_missions.py` (`host_loop._init_mission`, `_fresh_world`).
- Produces: tests only.

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_sensor_memory_missions.py`:

```python
"""Sensor-model sub-project 3 end to end on the REAL E2M1 (same harness as
tests/integration/test_sensor_continuity_missions.py): a known Karoon stays on
the player's perceived list by name beyond sensor range, a nebula around the
PLAYER alone jams it off (the Karoon sits in clear space, so only the jam can
explain it), over-boost lists an unknown Karoon far away without identifying
it, the lock survives range and drops on jam, and a set change wipes memory.

Occlusion is switched off here: these tests prove memory and boost, and Beol4's
own asteroids could otherwise sit on the line and answer instead."""
import App
import MissionLib
import pytest

from engine import host_loop
from engine.appc import perception, sensor_occlusion
from engine.appc.sensor_detection import (can_detect, clear_undetectable_player_lock,
                                          effective_sensor_range)
from tests.integration.test_sdk_bridge_load import _fresh_world

E2M1_MODULE = "Maelstrom.Episode2.E2M1.E2M1"


@pytest.fixture
def beol4_with_karoon():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E2M1_MODULE)
    beol4 = App.g_kSetManager.GetSet("Beol4")
    if beol4.GetObject("Karoon") is None:
        mod.CreateBeolShips()
    karoon = App.ShipClass_GetObject(beol4, "Karoon")
    player = MissionLib.GetPlayer()
    player.GetContainingSet().RemoveObjectFromSet("player")
    beol4.AddObjectToSet(player, "player")
    sensor_occlusion.set_enabled(False)
    loc = karoon.GetWorldLocation()
    r = effective_sensor_range(player)
    assert r > 0.0
    player.SetTranslateXYZ(loc.x + 1.5 * r, loc.y, loc.z)   # Karoon is 1.5 ranges away
    return beol4, player, karoon


def _contact(player, ship):
    for c in perception.perceived_by(player):
        if c.ship is ship:
            return c
    return None


def test_known_karoon_stays_listed_by_name_beyond_range(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    sensors = player.GetSensorSubsystem()
    c = _contact(player, karoon)
    assert c is None or c.perceivable is False         # unknown and out of range
    sensors.ForceObjectIdentified(karoon)
    c = _contact(player, karoon)
    assert c is not None and c.perceivable is True and c.identified is True


def test_a_nebula_around_the_player_alone_jams_memory(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    player.GetSensorSubsystem().ForceObjectIdentified(karoon)
    assert can_detect(player, karoon) is True
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "", "")
    p = player.GetWorldLocation()
    neb.AddNebulaSphere(p.x, p.y, p.z, 50.0)
    beol4.AddObjectToSet(neb, "JamNebula")
    assert can_detect(player, karoon) is False


def test_boost_lists_an_unknown_karoon_far_away(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    sensors = player.GetSensorSubsystem()
    sensors._power_factor = 1.25
    c = _contact(player, karoon)
    assert c is not None and c.perceivable is True and c.identified is False
    assert sensors.IsObjectKnown(karoon) == 0


def test_lock_survives_range_and_drops_when_jammed(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    player.GetSensorSubsystem().ForceObjectIdentified(karoon)
    player.SetTarget(karoon)
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is karoon
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "", "")
    p = player.GetWorldLocation()
    neb.AddNebulaSphere(p.x, p.y, p.z, 50.0)
    beol4.AddObjectToSet(neb, "JamNebula")
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None


def test_set_change_wipes_memory_so_far_ships_stay_unlisted(beol4_with_karoon):
    from engine.appc import sensor_contacts
    beol4, player, karoon = beol4_with_karoon
    sensors = player.GetSensorSubsystem()
    sensors.ForceObjectIdentified(karoon)
    assert can_detect(player, karoon) is True
    vesuvi = App.g_kSetManager.GetSet("Vesuvi6")
    beol4.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")
    sensor_contacts.tick(player, 1.0)
    vesuvi.RemoveObjectFromSet("player")
    beol4.AddObjectToSet(player, "player")
    sensor_contacts.tick(player, 2.0)
    assert sensors.IsObjectKnown(karoon) == 0
    assert can_detect(player, karoon) is False
```

Notes for the implementer:
- Read `tests/integration/test_sensor_continuity_missions.py` first; reuse its idioms exactly. If `SetTarget`/`GetTarget` are not the player-target accessors this engine uses, read `clear_undetectable_player_lock`'s body for the real ones and use those.
- If `test_set_change_wipes_memory_so_far_ships_stay_unlisted` FAILS because leaving the set does not wipe known objects in the engine, that is a real gap against roadmap decision 3 ("the player leaving wipes everything"): STOP and report it with the evidence — do not weaken the test.
- `App.MetaNebula_Create`'s argument list: check `engine/appc/nebula.py:103` and match it.

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/integration/test_sensor_memory_missions.py -q`
Expected: PASS (Tasks 2–5 already built the behaviour). If one fails, diagnose against the spec before changing anything; any production change goes back through a failing test first.

- [ ] **Step 3: Write the CPU budget test**

Create `tests/unit/test_sensor_reach_bench.py`:

```python
"""CPU budget for sub-project 3's beyond-range branch (spec: Performance).

Measures can_detect for out-of-range KNOWN contacts (the new branch, worst
case: set compare + power read + IsObjectKnown + jam scan over 3 nebulae)
against in-range contacts (the old path) with time.process_time, as
test_sensor_occlusion_bench.py does -- wall clock is too noisy on a shared
machine. Budget: the new branch costs at most 3x the in-range call."""
import time

from engine.appc import contact_index
from engine.appc import sensor_detection as sd
from tests.unit.test_sensor_reach import _observer_in_set, _ship_at


class _FarNeb:
    def IsObjectInNebula(self, obj):
        return 0


def _per_call(obs, ships, reps):
    t0 = time.process_time()
    for _ in range(reps):
        for s in ships:
            sd.can_detect(obs, s)
    return (time.process_time() - t0) / (reps * len(ships))


def test_beyond_range_branch_stays_within_budget(monkeypatch):
    monkeypatch.setattr(contact_index, "nebulae_in",
                        lambda pSet: (_FarNeb(), _FarNeb(), _FarNeb()))
    s, obs, sensors = _observer_in_set(2000.0)
    near = [_ship_at(s, "n%d" % i, 100.0 + i) for i in range(40)]
    far = [_ship_at(s, "f%d" % i, 5000.0 + i) for i in range(40)]
    for ship in far:
        sensors.AddKnownObject(ship)
    assert all(sd.can_detect(obs, x) for x in far)
    _per_call(obs, near + far, 20)                    # warm caches
    in_range = min(_per_call(obs, near, 200) for _ in range(3))
    beyond = min(_per_call(obs, far, 200) for _ in range(3))
    assert beyond <= 3.0 * in_range, (beyond, in_range)
```

- [ ] **Step 4: Run it**

Run: `uv run pytest tests/unit/test_sensor_reach_bench.py -q`
Expected: PASS. If it fails, report the measured ratio to the controller; do not raise the budget without a ruling.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_sensor_memory_missions.py tests/unit/test_sensor_reach_bench.py
git commit -m "test(sensors): E2M1 end-to-end memory/jam/boost, lock, set change; reach CPU budget

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Docs and the gate

**Files:**
- Modify: `docs/superpowers/specs/2026-10-06-sensor-overboost-memory-design.md` (append `## As built`)
- Modify: `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md` (SP3 row status)
- Modify: `CLAUDE.md` ("Sensor tiers" row)

**Interfaces:**
- Consumes: the branch as built.
- Produces: docs only.

- [ ] **Step 1: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure it names is a regression from this branch — fix it via a failing test first. Do not edit `tests/known_failures.txt`.

- [ ] **Step 2: Write "As built" in the spec**

Append `## As built` to the spec: one bullet per deviation from the spec or ruling taken during execution (from the SDD ledger), the audit verdicts in one line, and the measured bench ratio from Task 6.

- [ ] **Step 3: Roadmap row**

In the roadmap's sub-project table, change row 3's status cell to `built, unmerged (feat/sensor-overboost-memory) — spec: \`2026-10-06-sensor-overboost-memory-design.md\``.

- [ ] **Step 4: CLAUDE.md**

In the "Sensor tiers — detected vs identified" row of `CLAUDE.md`, append before the final sentence about occlusion: `Sub-project 3: \`can_detect\` keeps BC's sensor MEMORY (a known contact stays listed beyond range) and OVER-BOOST (NormalPowerPercentage > \`overboost_threshold\` 1.2 lists the whole set as Unknown), both cancelled by \`sensor_detection.jammed\` (either ship in a MetaNebula) and never for a cloaked or other-set target; \`IsObjectVisible\` = set gate + \`can_detect\` (BC's list and radar call it — RE xrefs).`

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-10-06-sensor-overboost-memory-design.md docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md CLAUDE.md
git commit -m "docs(sensors): SP3 as built; roadmap and CLAUDE.md sensor row

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Re-run the gate on the final commit**

Run: `scripts/check_tests.sh`
Expected: exit 0.
