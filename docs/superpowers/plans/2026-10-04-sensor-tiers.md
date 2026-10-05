# Sensor Tiers (sub-project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split "listed" from "identified" the way BC does: contacts in sensor range list as grey "Unknown N" with restricted information until they sit in the near band (half range) for the 4.0 s identification dwell, or a scan identifies them; FAR/NEAR proximity events, `GetIdentificationTime` and `IsObjectNear/Far/Visible` become real.

**Architecture:** A new player-only contact manager (`engine/appc/sensor_contacts.py`) ticks every sim frame, sweeps the player's set on a 1 s game-time cadence, tracks near/far band membership, posts proximity events and arms deferred identifications that commit through the existing single commit point `sensor_identification._identify_one`. Display is derived: `perception.Contact` gains `identified`, the target-menu row shows a placeholder caption from `engine/appc/unknown_labels.py`, and a thin wrapper keeps Science's Scan Object buttons from leaking real names. Tunables live in a "sensors" dial group.

**Tech Stack:** Python 3 engine shim (`engine/appc/`), pytest, CEF JS panel (`native/assets/ui-cef/js/target_list.js`).

**Spec:** `docs/superpowers/specs/2026-10-03-sensor-tiers-design.md` (read with the roadmap `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md`).

## Global Constraints

- Work ONLY in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/sensor-tiers` on branch `feat/sensor-tiers`. Never commit to main; never push.
- BANNED git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths only. To mutate a file temporarily, back it up with `cp`, restore with `cp`, prove with `diff`.
- NEVER `pkill`/`killall`; kill only a PID you started. NEVER launch the game (`./build/dauntless`).
- Run Python tests with `uv run pytest <path> -q` from the worktree root.
- Defaults (RE'd, BC): identification time **4.0 s**, near band **0.5** of sensor range, sweep period **1.0 s**. Every one is a dial; never hard-code them outside `engine/appc/sensor_dials.py`.
- Units are GU. Bands are **pure centre distance** (no nebula, no cloak). Identification (passive) additionally requires `sensor_detection.can_detect(player, obj)`.
- Proximity events: `TGBoolEvent`, bool = 1 entered / 0 left, **source = the contact**, destination = the player's sensor subsystem. Identify event: destination = the contact (unchanged).
- The contact manager is **player-only**. AI behaviour must not change.
- `STSubsystemMenu.GetLabel()` must keep returning the REAL display name (`STTargetMenu.GetSubmenuW` resolves rows by it for E2M0/E1M2 tutorial arrows). The placeholder is exposed only via the new `GetCaption()`.
- Never put a game-state mutation in a panel's `render_payload`.
- Check `docs/stub_heatmap.md` before claiming an SDK call is or isn't a no-op; never decide surface exists by grepping `def <Name>(`.
- A changed call becoming a no-op can leave old tests passing vacuously: when you delete or replace a function, grep every test that named it and confirm each still fails without your code (mutation check: back up, delete the line, watch the test fail, restore by `cp`, `diff`).

## Review Focus

1. **A contact identified while targeted** — the lock and target must not change when an Unknown row turns into its real name; subsystem rows simply appear. (Task 6 test `test_identifying_a_targeted_contact_keeps_the_lock`.)
2. **Two unknown ships with the same display name** (e.g. two "Galor") — they must get distinct placeholders and distinct Science buttons. (Task 3 `test_two_contacts_never_share_a_number`, Task 7 `test_two_unknowns_get_two_buttons`.)
3. **A contact that leaves the set mid-dwell** — no identification event may arrive later for it. (Task 4 `test_exit_set_mid_dwell_never_identifies`.)
4. **Sensors destroyed mid-dwell** — the passive identification must abort, not complete. (Task 4 `test_sensors_lost_mid_dwell_aborts`.)
5. **`ForceObjectIdentified` while an identification is pending** — exactly one `ET_SENSORS_SHIP_IDENTIFIED`. (Task 5 `test_force_identify_while_pending_fires_once`.)

---

## File structure

| File | Responsibility |
|---|---|
| `engine/appc/sensor_dials.py` (new) | The three sensor dials, their stepping, and "sensors" dial-group registration |
| `engine/appc/unknown_labels.py` (new) | The "Unknown N" placeholder per unidentified contact |
| `engine/appc/sensor_contacts.py` (new) | Player-only contact manager: bands, proximity events, pending identifications, set-exit purge |
| `engine/appc/science_scan_labels.py` (new) | Wrapper keeping Science Scan Object buttons on the placeholder until identification |
| `engine/appc/subsystems.py` | `SensorSubsystem` surface: `GetIdentificationTime`, `GetSensorRange`, `IsObjectNear/Far/Visible`, deferred `IdentifyObject`, spaced `ScanAllObjects` |
| `engine/appc/sensor_identification.py` | `_identify_one` (commit point, now renames the placeholder button and releases the label first); delete `identify_contacts`/`identify_all_in_set` |
| `engine/appc/sets.py` | Call `sensor_contacts.on_exited_set` after the exit broadcast |
| `engine/appc/perception.py` | `Contact.identified`; `subsystems_targetable` folds it in |
| `engine/appc/target_menu.py` | Real `ShowUnknownName`/`ShowRealName`, `GetCaption`, UNKNOWN affiliation while unknown; `set_contacts` drives them |
| `engine/ui/target_list_view.py`, `native/assets/ui-cef/js/target_list.js` | `label` in the payload, displayed by JS |
| `engine/ui/ship_display_panel.py` | SDK `IsObjectKnown` gate on the target role |
| `App.py` | Real `g_kRadar{Friendly,Enemy,Neutral,Unknown}Color` |
| `engine/host_loop.py` | Tick the manager; reset on mission swap; install the Science wrapper; register the dial group |
| `tests/conftest.py` | Autouse reset of the new module state |
| `tests/helpers/sensor_time.py` (new) | `settle_identification(player)` for fixtures that need contacts identified |

---

### Task 1: Sensor dials

**Files:**
- Create: `engine/appc/sensor_dials.py`
- Modify: `engine/appc/subsystems.py` (`SensorSubsystem`, after `SetMaxProbes` ~line 1379)
- Modify: `engine/host_loop.py:~9949-9953` (boot dial registration block, after `_far_dials.register()`)
- Modify: `tests/conftest.py` (autouse `_reset_leakable_engine_globals`, beside `reset_concealment_state` ~line 1443)
- Test: `tests/unit/test_sensor_dials.py`

**Interfaces:**
- Produces: `sensor_dials.get(name: str) -> float`; `sensor_dials.current() -> dict`; `sensor_dials.step(dials: dict, name: str, direction: int) -> dict` (pure); `sensor_dials.reset() -> None`; `sensor_dials.register() -> None`; `DEFAULTS`, `DIAL_ORDER`. `SensorSubsystem.GetIdentificationTime() -> float`.

- [ ] **Step 1: Write the failing test**

```python
"""Sensor dials: identification time, near band, sweep period (RE'd defaults)."""
from engine.appc import sensor_dials
from engine import dev_dial_groups
from engine.appc.subsystems import SensorSubsystem


def test_defaults_are_bcs_recovered_values():
    sensor_dials.reset()
    assert sensor_dials.get("identification_time_s") == 4.0
    assert sensor_dials.get("near_fraction") == 0.5
    assert sensor_dials.get("sweep_period_s") == 1.0
    assert sensor_dials.DIAL_ORDER == (
        "identification_time_s", "near_fraction", "sweep_period_s")


def test_step_is_pure_additive_and_clamped():
    d = dict(sensor_dials.DEFAULTS)
    up = sensor_dials.step(d, "identification_time_s", +1)
    assert up["identification_time_s"] == 4.5
    assert d["identification_time_s"] == 4.0          # pure
    assert sensor_dials.step(d, "near_fraction", +1)["near_fraction"] == 0.55
    low = dict(d, identification_time_s=0.5, near_fraction=0.05,
               sweep_period_s=0.25)
    for name in sensor_dials.DIAL_ORDER:
        assert sensor_dials.step(low, name, -1)[name] == low[name]
    high = dict(d, near_fraction=1.0)
    assert sensor_dials.step(high, "near_fraction", +1)["near_fraction"] == 1.0


def test_registered_group_steps_the_live_dial():
    dev_dial_groups.reset()
    sensor_dials.reset()
    sensor_dials.register()
    assert "sensors" in dev_dial_groups.groups()
    assert dev_dial_groups.set_active("sensors") is True
    dev_dial_groups.push(+1)       # selected dial is the first: identification time
    assert sensor_dials.get("identification_time_s") == 4.5


def test_sensor_subsystem_reports_the_dial():
    sensor_dials.reset()
    assert SensorSubsystem("Sensors").GetIdentificationTime() == 4.0
    sensor_dials._dials["identification_time_s"] = 2.5
    assert SensorSubsystem("Sensors").GetIdentificationTime() == 2.5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_sensor_dials.py -q`
Expected: FAIL — `ModuleNotFoundError: engine.appc.sensor_dials`.

- [ ] **Step 3: Implement**

`engine/appc/sensor_dials.py`:

```python
"""The sensor model's tunables (sensor-tiers spec §7).

Defaults are BC's own, recovered by reverse engineering
(STBC-Reverse-Engineering-1/docs/gameplay/sensor-subsystem.md): a hard-coded
4.0 s identification dwell (GetIdentificationTime @0x005671C0), the near band at
half sensor range (IsObjectNear @0x00567440) and a 1.0 s periodic sweep
(interval at 0x008E50F4). RE tier, not tested.

Read at use. Not persisted; tuned live through the shared / L O keys once
Developer Options -> Lighting -> "Dial keys" selects "sensors"
(engine/dev_dial_groups.py).
"""
DEFAULTS: dict = {
    "identification_time_s": 4.0,
    "near_fraction": 0.5,
    "sweep_period_s": 1.0,
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"identification_time_s": 0.5, "near_fraction": 0.05,
         "sweep_period_s": 0.25}
_MIN = {"identification_time_s": 0.5, "near_fraction": 0.05,
        "sweep_period_s": 0.25}
_MAX = {"near_fraction": 1.0}

_dials: dict = dict(DEFAULTS)


def reset() -> None:
    global _dials
    _dials = dict(DEFAULTS)


def get(name: str) -> float:
    return float(_dials[name])


def current() -> dict:
    return dict(_dials)


def step(dials: dict, name: str, direction: int) -> dict:
    """Pure: one additive step, clamped to [_MIN, _MAX]."""
    out = dict(dials)
    v = round(out[name] + (_STEP[name] if direction > 0 else -_STEP[name]), 4)
    v = max(_MIN[name], v)
    if name in _MAX:
        v = min(_MAX[name], v)
    out[name] = v
    return out


def _step(name: str, direction: int) -> None:
    global _dials
    _dials = step(_dials, name, direction)


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("sensors", DIAL_ORDER, current, _step)
```

In `SensorSubsystem` (`engine/appc/subsystems.py`), after `SetMaxProbes`:

```python
    def GetIdentificationTime(self) -> float:
        """BC's identification dwell (RE'd: a hard-coded 4.0 s, no setter);
        here the live `identification_time_s` dial."""
        from engine.appc import sensor_dials
        return sensor_dials.get("identification_time_s")
```

In `engine/host_loop.py`, in the boot dial-registration block, directly after `_far_dials.register()` (~line 9953), add:

```python
                from engine.appc import sensor_dials as _sensor_dials
                _sensor_dials.register()
```

In `tests/conftest.py` `_reset_leakable_engine_globals`, beside the `reset_concealment_state` block:

```python
    try:
        from engine.appc import sensor_dials
        sensor_dials.reset()
    except Exception:
        pass
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_sensor_dials.py tests/unit/test_dev_dial_groups.py -q`
Expected: PASS. Also run `uv run pytest tests/ -q -k "dev_key_collisions or dial"` — PASS (no new keys are bound; the group shares / L O).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_dials.py engine/appc/subsystems.py engine/host_loop.py tests/conftest.py tests/unit/test_sensor_dials.py
git commit -m "feat(sensors): sensor dial group with BC's identification time, near band, sweep period"
```

---

### Task 2: SensorSubsystem range bands and IsObjectVisible

**Files:**
- Modify: `engine/appc/subsystems.py` (`SensorSubsystem`)
- Test: `tests/unit/test_sensor_bands_and_visibility.py`

**Interfaces:**
- Consumes: `sensor_dials.get("near_fraction")` (Task 1); `sensor_detection.effective_sensor_range(ship)`, `sensor_detection.is_hidden_by_cloak(obj)`; `contact_index.nebulae_in(pSet)`; `Nebula.IsObjectInNebula(obj) -> int`.
- Produces: `SensorSubsystem.GetSensorRange() -> float`, `IsObjectNear(obj) -> int`, `IsObjectFar(obj) -> int`, `IsObjectVisible(obj) -> int`, private `_owner_ship()`.

- [ ] **Step 1: Write the failing test**

```python
"""SensorSubsystem bands + IsObjectVisible, per BC's RE'd algorithm
(sensor-subsystem.md: IsObjectNear = half range, IsObjectFar = full range,
pure distance; IsObjectVisible's ordered gates, probes omitted)."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem, CloakingSubsystem
from engine.appc.sets import SetClass


def _player_in_set(base_range=2000.0):
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    return s, player, sensors


def _ship_at(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


def test_get_sensor_range_is_the_one_rule():
    from engine.appc.sensor_detection import effective_sensor_range
    s, player, sensors = _player_in_set(2000.0)
    assert sensors.GetSensorRange() == effective_sensor_range(player) == 2000.0


def test_near_is_half_range_far_is_full_range():
    s, player, sensors = _player_in_set(2000.0)
    near = _ship_at(s, "near", 999.0)
    mid = _ship_at(s, "mid", 1500.0)
    out = _ship_at(s, "out", 2001.0)
    assert (sensors.IsObjectNear(near), sensors.IsObjectFar(near)) == (1, 1)
    assert (sensors.IsObjectNear(mid), sensors.IsObjectFar(mid)) == (0, 1)
    assert (sensors.IsObjectNear(out), sensors.IsObjectFar(out)) == (0, 0)


def test_bands_follow_the_near_fraction_dial():
    from engine.appc import sensor_dials
    s, player, sensors = _player_in_set(2000.0)
    mid = _ship_at(s, "mid", 1500.0)
    sensor_dials._dials["near_fraction"] = 0.8
    assert sensors.IsObjectNear(mid) == 1


def test_other_set_is_neither_near_nor_far():
    s, player, sensors = _player_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    other.AddObjectToSet(ship, "elsewhere")
    assert sensors.IsObjectNear(ship) == 0 and sensors.IsObjectFar(ship) == 0


def test_visible_in_range_invisible_beyond_unless_known():
    s, player, sensors = _player_in_set(2000.0)
    inside = _ship_at(s, "in", 1500.0)
    beyond = _ship_at(s, "beyond", 5000.0)
    assert sensors.IsObjectVisible(inside) == 1
    assert sensors.IsObjectVisible(beyond) == 0
    sensors.AddKnownObject(beyond)          # BC sensor memory
    assert sensors.IsObjectVisible(beyond) == 1


def test_fully_cloaked_is_never_visible():
    s, player, sensors = _player_in_set(2000.0)
    ship = _ship_at(s, "cloaked", 10.0)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    ship.GetCloakingSubsystem().InstantCloak()
    sensors.AddKnownObject(ship)
    assert sensors.IsObjectVisible(ship) == 0


def test_over_boost_sees_the_whole_set():
    s, player, sensors = _player_in_set(2000.0)
    beyond = _ship_at(s, "beyond", 50000.0)
    sensors._power_factor = 1.25
    assert sensors.IsObjectVisible(beyond) == 1


def test_offline_sensors_see_nothing():
    s, player, sensors = _player_in_set(2000.0)
    inside = _ship_at(s, "in", 10.0)
    sensors.AddKnownObject(inside)
    sensors._power_factor = 0.0
    assert sensors.GetSensorRange() == 0.0
    assert sensors.IsObjectVisible(inside) == 0


def test_nebula_jam_cancels_memory_and_boost(monkeypatch):
    from engine.appc import contact_index
    s, player, sensors = _player_in_set(2000.0)
    beyond = _ship_at(s, "beyond", 50000.0)
    sensors.AddKnownObject(beyond)

    class _Neb:
        def IsObjectInNebula(self, obj):
            return 1 if obj is beyond else 0

    monkeypatch.setattr(contact_index, "nebulae_in", lambda pSet: (_Neb(),))
    assert sensors.IsObjectVisible(beyond) == 0      # memory blocked
    sensors._power_factor = 1.25
    assert sensors.IsObjectVisible(beyond) == 0      # boost blocked
    near = _ship_at(s, "near", 100.0)
    assert sensors.IsObjectVisible(near) == 1        # range test still applies
```

Note: `_power_factor` is the backing field of `GetNormalPowerPercentage()` (`subsystems.py:1252`). If a test fixture's `GetNormalPowerPercentage` reads something else, use the real setter instead and say so in your report.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_sensor_bands_and_visibility.py -q`
Expected: FAIL — `GetSensorRange` / `IsObjectNear` resolve to `_Stub` (truthy) so equality assertions fail.

- [ ] **Step 3: Implement** — add to `SensorSubsystem`:

```python
    # ── Range bands + visibility (BC RE'd: sensor-subsystem.md) ───────────
    def _owner_ship(self):
        ship = self.GetParentShip()
        if ship is None and hasattr(self, "_climb_to_ship"):
            ship = self._climb_to_ship()
        return ship

    def GetSensorRange(self) -> float:
        """BC's GetSensorRange: base x normal-power% x condition%, 0 when
        offline. Delegates to the one rule, sensor_detection.effective_sensor_range."""
        ship = self._owner_ship()
        if ship is None:
            return 0.0
        from engine.appc.sensor_detection import effective_sensor_range
        return float(effective_sensor_range(ship))

    def _band_distance(self, obj):
        """Centre distance owner->obj in GU, or None when not in the same set."""
        ship = self._owner_ship()
        if ship is None or obj is None:
            return None
        pset = ship.GetContainingSet()
        if pset is None or obj.GetContainingSet() is not pset:
            return None
        ox, oy, oz = _get_xyz(ship)
        tx, ty, tz = _get_xyz(obj)
        return ((tx - ox) ** 2 + (ty - oy) ** 2 + (tz - oz) ** 2) ** 0.5

    def IsObjectNear(self, obj) -> int:
        """Within near_fraction (BC: half) of sensor range. Pure distance."""
        from engine.appc import sensor_dials
        d = self._band_distance(obj)
        r = self.GetSensorRange()
        return 1 if (d is not None and r > 0.0
                     and d <= r * sensor_dials.get("near_fraction")) else 0

    def IsObjectFar(self, obj) -> int:
        """Within full sensor range. Pure distance."""
        d = self._band_distance(obj)
        r = self.GetSensorRange()
        return 1 if (d is not None and r > 0.0 and d <= r) else 0

    def IsObjectVisible(self, obj) -> int:
        """BC's IsObjectVisible (@0x005671D0), probes omitted. NOT the target
        list's gate (that is sensor_detection.can_detect) — only SDK callers
        that ask this directly use it. Order is BC's: power, absolute cloak,
        same set, nebula jam, over-boost, range, (jam) , memory."""
        ship = self._owner_ship()
        if ship is None or obj is None:
            return 0
        if self.GetSensorRange() <= 0.0:
            return 0
        from engine.appc.sensor_detection import is_hidden_by_cloak
        if is_hidden_by_cloak(obj):
            return 0
        pset = ship.GetContainingSet()
        if pset is None or obj.GetContainingSet() is not pset:
            return 0
        from engine.appc import contact_index
        jammed = any(n.IsObjectInNebula(ship) or n.IsObjectInNebula(obj)
                     for n in contact_index.nebulae_in(pset))
        if not jammed and self.GetNormalPowerPercentage() > 1.2:
            return 1
        if self.IsObjectFar(obj):
            return 1
        if jammed:
            return 0
        return self.IsObjectKnown(obj)
```

(`_get_xyz` is already defined in `engine/appc/subsystems.py`.)

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_sensor_bands_and_visibility.py tests/unit/test_sensor_visibility.py tests/unit/test_sensor_subsystem_identity.py -q`
Expected: PASS. If `test_sensor_visibility.py` asserted the old stub behaviour of a method you just made real, read it, confirm what it pinned, and update it to the RE'd behaviour with a comment citing the RE doc.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_sensor_bands_and_visibility.py
git commit -m "feat(sensors): SensorSubsystem range bands and BC's IsObjectVisible"
```

---

### Task 3: Unknown labels

**Files:**
- Create: `engine/appc/unknown_labels.py`
- Modify: `tests/conftest.py` (autouse reset)
- Test: `tests/unit/test_unknown_labels.py`

**Interfaces:**
- Produces: `unknown_labels.placeholder(obj) -> str` (allocates, idempotent per obj); `unknown_labels.current(obj) -> str | None` (no allocation); `unknown_labels.release(obj) -> None`; `unknown_labels.reset() -> None`.

- [ ] **Step 1: Write the failing test**

```python
from engine.appc import unknown_labels


class _Obj:
    pass


def test_placeholders_count_up_and_are_stable():
    unknown_labels.reset()
    a, b = _Obj(), _Obj()
    assert unknown_labels.placeholder(a) == "Unknown 1"
    assert unknown_labels.placeholder(b) == "Unknown 2"
    assert unknown_labels.placeholder(a) == "Unknown 1"


def test_two_contacts_never_share_a_number():
    unknown_labels.reset()
    objs = [_Obj() for _ in range(5)]
    labels = [unknown_labels.placeholder(o) for o in objs]
    assert len(set(labels)) == 5


def test_release_frees_the_lowest_number_for_reuse():
    unknown_labels.reset()
    a, b, c = _Obj(), _Obj(), _Obj()
    unknown_labels.placeholder(a)
    unknown_labels.placeholder(b)
    unknown_labels.release(a)
    assert unknown_labels.current(a) is None
    assert unknown_labels.placeholder(c) == "Unknown 1"
    assert unknown_labels.current(b) == "Unknown 2"


def test_current_never_allocates():
    unknown_labels.reset()
    a = _Obj()
    assert unknown_labels.current(a) is None
    assert unknown_labels.placeholder(_Obj()) == "Unknown 1"
```

- [ ] **Step 2: Run it** — `uv run pytest tests/unit/test_unknown_labels.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** `engine/appc/unknown_labels.py`:

```python
"""The placeholder an unidentified contact shows: "Unknown N".

Roadmap decision 4: N is held per contact until it is identified or leaves the
set, so the SDK's label-keyed button de-duplication (Science CreateScanButton's
GetButtonW) never merges two unknowns. BC's own "Unknown ..." wording is not
recovered (ShowUnknownName's body is unreconstructed) — Mark's call.

Weak-keyed: a contact that goes away releases its number with it.
"""
import weakref

_numbers: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def placeholder(obj) -> str:
    n = _numbers.get(obj)
    if n is None:
        used = set(_numbers.values())
        n = 1
        while n in used:
            n += 1
        _numbers[obj] = n
    return "Unknown %d" % n


def current(obj):
    n = _numbers.get(obj)
    return None if n is None else "Unknown %d" % n


def release(obj) -> None:
    _numbers.pop(obj, None)


def reset() -> None:
    _numbers.clear()
```

Add to `tests/conftest.py` autouse reset (same try/except shape as Task 1):

```python
    try:
        from engine.appc import unknown_labels
        unknown_labels.reset()
    except Exception:
        pass
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_unknown_labels.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/unknown_labels.py tests/conftest.py tests/unit/test_unknown_labels.py
git commit -m "feat(sensors): Unknown N placeholder allocation"
```

---

### Task 4: Contact manager — bands, proximity events, passive dwell, set exit

**Files:**
- Create: `engine/appc/sensor_contacts.py`
- Modify: `engine/appc/sets.py:248-262` (after each `self._broadcast_set_transition(obj, entered=False)`)
- Modify: `tests/conftest.py` (autouse reset)
- Create: `tests/helpers/sensor_time.py`
- Test: `tests/unit/test_sensor_contacts.py`

**Interfaces:**
- Consumes: `sensor_dials.get` (Task 1); `SensorSubsystem.IsObjectKnown/AddKnownObject/RemoveKnownObject`; `sensor_detection.can_detect`, `effective_sensor_range`; `sensor_identification._identify_one(sensors, obj) -> bool`; `unknown_labels.release` (Task 3).
- Produces: `sensor_contacts.tick(player, now_gt: float) -> None`; `sensor_contacts.schedule_scan(obj, delay_s: float, now_gt: float | None = None) -> None`; `sensor_contacts.on_exited_set(pSet, obj) -> None`; `sensor_contacts.player_knows(obj) -> bool`; `sensor_contacts.current_player()` (the game's player or None); `sensor_contacts.reset() -> None`; `sensor_contacts.is_pending(obj) -> bool`. Test helper `tests/helpers/sensor_time.settle_identification(player, start_gt: float = 0.0) -> float` (returns the game time it ended at).

- [ ] **Step 1: Write the failing test**

```python
"""Player-only contact manager (sensor-tiers spec §1)."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import sensor_contacts

_events: list = []


def _on_any(dest, event):
    _events.append((event.GetEventType(), event.GetSource(),
                    getattr(event, "GetBool", lambda: None)(),
                    event.GetDestination()))


def _subscribe():
    _events.clear()
    for et in (App.ET_SENSORS_SHIP_FAR_PROXIMITY,
               App.ET_SENSORS_SHIP_NEAR_PROXIMITY,
               App.ET_SENSORS_SHIP_IDENTIFIED):
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            et, None, __name__ + "._on_any")


def _world(base_range=2000.0):
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    return s, player, sensors


def _ship(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


def _of(et):
    return [e for e in _events if e[0] == et]


def test_far_band_entry_posts_far_with_source_ship_and_no_identify():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)          # far, not near
    sensor_contacts.tick(player, 0.0)
    far = _of(App.ET_SENSORS_SHIP_FAR_PROXIMITY)
    assert len(far) == 1
    assert far[0][1] is bird and far[0][2] == 1
    assert far[0][3] is sensors
    assert _of(App.ET_SENSORS_SHIP_NEAR_PROXIMITY) == []
    sensor_contacts.tick(player, 10.0)
    assert sensors.IsObjectKnown(bird) == 0   # never near => never identified


def test_near_band_identifies_after_the_dwell_not_before():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    near = _of(App.ET_SENSORS_SHIP_NEAR_PROXIMITY)
    assert len(near) == 1 and near[0][1] is bird and near[0][2] == 1
    sensor_contacts.tick(player, 3.9)
    assert sensors.IsObjectKnown(bird) == 0
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 1
    assert [e[3] for e in _of(App.ET_SENSORS_SHIP_IDENTIFIED)] == [bird]


def test_entry_order_is_far_then_near_and_exit_near_then_far():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    kinds = [e[0] for e in _events]
    assert kinds == [App.ET_SENSORS_SHIP_FAR_PROXIMITY,
                     App.ET_SENSORS_SHIP_NEAR_PROXIMITY]
    _events.clear()
    bird.SetTranslateXYZ(9000.0, 0.0, 0.0)
    sensor_contacts.tick(player, 1.0)
    assert [(e[0], e[2]) for e in _events] == [
        (App.ET_SENSORS_SHIP_NEAR_PROXIMITY, 0),
        (App.ET_SENSORS_SHIP_FAR_PROXIMITY, 0)]


def test_sweep_runs_on_its_period_not_every_tick():
    _subscribe()
    s, player, sensors = _world()
    sensor_contacts.tick(player, 0.0)
    bird = _ship(s, "Bird", 1500.0)
    sensor_contacts.tick(player, 0.5)
    assert _of(App.ET_SENSORS_SHIP_FAR_PROXIMITY) == []
    sensor_contacts.tick(player, 1.0)
    assert len(_of(App.ET_SENSORS_SHIP_FAR_PROXIMITY)) == 1


def test_leaving_the_near_band_mid_dwell_aborts():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    bird.SetTranslateXYZ(1500.0, 0.0, 0.0)
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 0


def test_sensors_lost_mid_dwell_aborts():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    sensors._power_factor = 0.0
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 0


def test_identity_survives_leaving_range():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.tick(player, 4.0)
    bird.SetTranslateXYZ(9000.0, 0.0, 0.0)
    sensor_contacts.tick(player, 5.0)
    assert sensors.IsObjectKnown(bird) == 1


def test_exit_set_mid_dwell_never_identifies():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    s.RemoveObjectFromSet("Bird")
    assert sensor_contacts.is_pending(bird) is False
    s.AddObjectToSet(bird, "Bird")            # back, but the old dwell is gone
    sensor_contacts.tick(player, 4.0)
    assert _of(App.ET_SENSORS_SHIP_IDENTIFIED) == []


def test_exit_set_forgets_a_known_contact():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    s.RemoveObjectFromSet("Bird")
    assert sensors.IsObjectKnown(bird) == 0


def test_player_leaving_its_set_wipes_everything():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    sensor_contacts.tick(player, 0.0)
    s.RemoveObjectFromSet("player")
    assert sensors.IsObjectKnown(bird) == 0
    assert sensor_contacts.is_pending(bird) is False


def test_a_new_player_starts_with_a_clean_manager():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)
    sensor_contacts.tick(player, 0.0)
    other = ShipClass_Create("Galaxy")
    sensors2 = SensorSubsystem("Sensors")
    sensors2._max_condition = 100.0
    sensors2._condition = 100.0
    sensors2.SetBaseSensorRange(2000.0)
    other.SetSensorSubsystem(sensors2)
    s.AddObjectToSet(other, "other")
    _events.clear()
    sensor_contacts.tick(other, 5.0)
    # bird is re-reported as entering the new player's far band
    assert any(e[0] == App.ET_SENSORS_SHIP_FAR_PROXIMITY and e[1] is bird
               for e in _events)


def test_reset_clears_pending():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.reset()
    sensor_contacts.tick(player, 4.0)        # sweeps again at 4.0, commit at 8.0
    assert sensors.IsObjectKnown(bird) == 0


def test_planets_are_identified_too():
    from engine.appc.planet import Planet_Create
    s, player, sensors = _world()
    planet = Planet_Create(10.0, "data/models/environment/planet.nif")
    planet.SetTranslateXYZ(500.0, 0.0, 0.0)
    s.AddObjectToSet(planet, "Haven")
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(planet) == 1
```

Check `Planet_Create`'s real signature in `engine/appc/planet.py` (and how `tests/unit/test_sensor_identification.py` builds a planet) before relying on the call above; match it.

- [ ] **Step 2: Run it** — `uv run pytest tests/unit/test_sensor_contacts.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** `engine/appc/sensor_contacts.py`:

```python
"""For the player's sensors: which contacts are in which band, and which are
on their way to being identified (sensor-tiers spec §1).

BC keeps this on a player-only singleton (RE'd: the global contact manager
@0x0098C000, every entry point gated on GetParentShip() == GetPlayerShip()), so
this module is player-only too. AI ships never identify.

- A sweep every `sweep_period_s` (BC: 1.0 s) walks the player's set and diffs
  near (`near_fraction` x range, BC: half) and far (full range) membership.
  Bands are PURE DISTANCE, as BC's are: E8M1 relies on FAR firing for a ship
  inside a nebula before it can be seen.
- Crossings post ET_SENSORS_SHIP_FAR/NEAR_PROXIMITY as a TGBoolEvent
  (1 entered / 0 left), source = the contact (the SDK handlers read
  GetSource()), destination = the player's sensors.
- A contact in the near band that can_detect passes and is not known gets a
  pending identification at now + identification_time_s (BC: 4.0 s). A passive
  entry re-checks near band + can_detect when it falls due; a scan entry
  (schedule_scan) commits unconditionally. Commit = _identify_one.
- Identity survives leaving range. A contact leaving the set is purged and
  forgotten; the player leaving its set wipes the lot (BC HandleExitSet).

Ticked every sim frame from host_loop (sim-gated). Never call from
render_payload.
"""
import weakref

import App
from engine.appc import sensor_dials
from engine.core.ids import implements

_near: "weakref.WeakSet" = weakref.WeakSet()
_far: "weakref.WeakSet" = weakref.WeakSet()
_pending: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_next_sweep_gt = None
_player_ref = None


def reset() -> None:
    global _next_sweep_gt, _player_ref
    _near.clear()
    _far.clear()
    _pending.clear()
    _next_sweep_gt = None
    _player_ref = None


def is_pending(obj) -> bool:
    return obj in _pending


def _now() -> float:
    try:
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception:
        return 0.0


def current_player():
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetPlayer() if game is not None else None
    except Exception:
        return None


def _sensors_of(ship):
    if ship is None or not implements(ship, "GetSensorSubsystem"):
        return None
    return ship.GetSensorSubsystem()


def player_knows(obj) -> bool:
    """True iff the current player's sensors have identified *obj*."""
    sensors = _sensors_of(current_player())
    if sensors is None or obj is None:
        return False
    try:
        return bool(sensors.IsObjectKnown(obj))
    except Exception:
        return False


def _contacts(player):
    """Ships and planets in the player's set, minus the player — exactly the
    filter the old passive sweep used (contact_index buckets ships only, and
    planets must still be identifiable). RockClass asteroids are ShipClass and
    are included, as they were before; rock-field scenery rocks are not set
    objects and never appear here."""
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet
    pset = player.GetContainingSet() if implements(player, "GetContainingSet") else None
    if pset is None or not hasattr(pset, "GetObjectList"):
        return ()
    return tuple(o for o in pset.GetObjectList()
                 if o is not None and o is not player
                 and isinstance(o, (ShipClass, Planet)))


def _dist(a, b) -> float:
    from engine.appc.subsystems import _get_xyz
    ax, ay, az = _get_xyz(a)
    bx, by, bz = _get_xyz(b)
    return ((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2) ** 0.5


def _post(event_type, obj, entered: bool, sensors) -> None:
    evt = App.TGBoolEvent_Create()
    evt.SetEventType(event_type)
    evt.SetBool(1 if entered else 0)
    evt.SetSource(obj)
    evt.SetDestination(sensors)
    App.g_kEventManager.AddEvent(evt)


def _sync_player(player) -> None:
    """A different player ship starts a clean manager (BC HandleSetPlayer)."""
    global _player_ref, _next_sweep_gt
    current = _player_ref() if _player_ref is not None else None
    if current is player:
        return
    _near.clear()
    _far.clear()
    _pending.clear()
    _next_sweep_gt = None
    _player_ref = weakref.ref(player) if player is not None else None


def _in_near_band(player, obj) -> bool:
    from engine.appc.sensor_detection import effective_sensor_range
    r = effective_sensor_range(player)
    return r > 0.0 and _dist(player, obj) <= r * sensor_dials.get("near_fraction")


def _commit_due(player, sensors, now_gt) -> None:
    from engine.appc.sensor_detection import can_detect
    from engine.appc.sensor_identification import _identify_one
    for obj, (due, by_scan) in list(_pending.items()):
        if now_gt < due:
            continue
        _pending.pop(obj, None)
        if sensors.IsObjectKnown(obj):
            continue
        if by_scan or (_in_near_band(player, obj) and can_detect(player, obj)):
            _identify_one(sensors, obj)


def _sweep(player, sensors, now_gt) -> None:
    from engine.appc.sensor_detection import can_detect, effective_sensor_range
    r = effective_sensor_range(player)
    nf = sensor_dials.get("near_fraction")
    dwell = sensor_dials.get("identification_time_s")
    for obj in _contacts(player):
        d = _dist(player, obj)
        far = r > 0.0 and d <= r
        near = r > 0.0 and d <= r * nf
        was_far, was_near = obj in _far, obj in _near
        if far and not was_far:
            _far.add(obj)
            _post(App.ET_SENSORS_SHIP_FAR_PROXIMITY, obj, True, sensors)
        if near and not was_near:
            _near.add(obj)
            _post(App.ET_SENSORS_SHIP_NEAR_PROXIMITY, obj, True, sensors)
        if was_near and not near:
            _near.discard(obj)
            _post(App.ET_SENSORS_SHIP_NEAR_PROXIMITY, obj, False, sensors)
        if was_far and not far:
            _far.discard(obj)
            _post(App.ET_SENSORS_SHIP_FAR_PROXIMITY, obj, False, sensors)
        if (near and obj not in _pending and not sensors.IsObjectKnown(obj)
                and can_detect(player, obj)):
            _pending[obj] = (now_gt + dwell, False)


def tick(player, now_gt: float) -> None:
    global _next_sweep_gt
    _sync_player(player)
    sensors = _sensors_of(player)
    if sensors is None:
        return
    _commit_due(player, sensors, now_gt)
    if _next_sweep_gt is None or now_gt >= _next_sweep_gt:
        _next_sweep_gt = now_gt + sensor_dials.get("sweep_period_s")
        _sweep(player, sensors, now_gt)


def schedule_scan(obj, delay_s: float, now_gt=None) -> None:
    """Arm a scan identification of *obj* (IdentifyObject / ScanAllObjects).
    Commits unconditionally when due. Keeps the earlier due time if one is
    already pending. No-op if the player already knows *obj*."""
    if obj is None or player_knows(obj):
        return
    t = (_now() if now_gt is None else float(now_gt)) + float(delay_s)
    prior = _pending.get(obj)
    if prior is not None:
        t = min(t, prior[0])
    _pending[obj] = (t, True)


def on_exited_set(pSet, obj) -> None:
    """Called by SetClass after the ET_EXITED_SET broadcast (so Science's
    ExitedSet has already found the placeholder button)."""
    from engine.appc import unknown_labels
    _near.discard(obj)
    _far.discard(obj)
    _pending.pop(obj, None)
    unknown_labels.release(obj)
    player = current_player()
    sensors = _sensors_of(player)
    if obj is player:
        reset()
        unknown_labels.reset()
        if sensors is not None:
            sensors._known_objects.clear()
        return
    if sensors is not None:
        sensors.RemoveKnownObject(obj)
```

`player_knows`, `on_exited_set` read the *current game player*. The unit tests above build a set without a `Game`; if `Game_GetCurrentGame()` returns None in that fixture, `test_exit_set_forgets_a_known_contact` and `test_player_leaving_its_set_wipes_everything` need a player. Look at how existing unit tests set a current player (grep `SetPlayer(` under `tests/unit/`) and add the same setup to `_world()`; do not weaken the assertions.

In `engine/appc/sets.py`, after each `self._broadcast_set_transition(obj, entered=False)` (two sites, ~lines 250 and 262), add:

```python
            from engine.appc import sensor_contacts
            sensor_contacts.on_exited_set(self, obj)
```

`tests/conftest.py` autouse reset:

```python
    try:
        from engine.appc import sensor_contacts
        sensor_contacts.reset()
    except Exception:
        pass
```

`tests/helpers/sensor_time.py`:

```python
"""Drive the player-only contact manager to identification in a fixture."""
from engine.appc import sensor_contacts, sensor_dials


def settle_identification(player, start_gt: float = 0.0) -> float:
    """One sweep, then one tick a full dwell later: every contact that was in
    the near band and detectable at start_gt is identified. Returns the end
    game time."""
    sensor_contacts.tick(player, start_gt)
    end = start_gt + sensor_dials.get("identification_time_s")
    sensor_contacts.tick(player, end)
    return end
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_sensor_contacts.py -q` → PASS. Then `uv run pytest tests/unit -q -k "set or contact or sensor"` → no new failures.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_contacts.py engine/appc/sets.py tests/conftest.py tests/helpers/sensor_time.py tests/unit/test_sensor_contacts.py
git commit -m "feat(sensors): player-only contact manager with bands, proximity events and identification dwell"
```

---

### Task 5: Scan paths, host-loop wiring, delete the full-range sweep

**Files:**
- Modify: `engine/appc/subsystems.py` (`SensorSubsystem.IdentifyObject`, `ScanAllObjects`)
- Modify: `engine/appc/sensor_identification.py` (delete `identify_contacts`, `identify_all_in_set`; `ScanAllObjectsAction` schedules; update module docstring)
- Modify: `engine/host_loop.py` — the identification block (~lines 11100-11112), `_reset_sensor_state` (~4450-4475), the `_last_identify_gt` global (~4767)
- Modify: `tests/unit/test_sensor_identification.py`, `tests/unit/test_sensor_scan.py`, `tests/integration/test_hail_button_population.py:213`, `tests/integration/test_e1m2_scan_area.py`
- Test: `tests/unit/test_sensor_scan_dwell.py`

**Interfaces:**
- Consumes: `sensor_contacts.tick`, `schedule_scan`, `reset`, `player_knows` (Task 4); `settle_identification` (Task 4).
- Produces: `sensor_identification.schedule_area_scan(player) -> int` (number scheduled); `IdentifyObject` deferred; `ScanAllObjects()` → `TGSequence` whose action calls `ScanAllObjectsAction`.

- [ ] **Step 1: Write the failing test** `tests/unit/test_sensor_scan_dwell.py`:

```python
"""Scans take BC's dwell: IdentifyObject is deferred, Scan Area spaces its
identifications one dwell apart (RE'd: ScanAllObjects spaces actions by
GetIdentificationTime). ForceObjectIdentified stays immediate."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import sensor_contacts

_ids: list = []


def _on_id(dest, event):
    _ids.append(event.GetDestination())


def _world():
    from engine.core.game import Game_GetCurrentGame
    _ids.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SENSORS_SHIP_IDENTIFIED, None, __name__ + "._on_id")
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    Game_GetCurrentGame().SetPlayer(player)   # adjust to the fixture idiom found in Task 4
    return s, player, sensors


def _ship(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


def test_identify_object_is_deferred_by_the_dwell(monkeypatch):
    s, player, sensors = _world()
    far_away = _ship(s, "Far", 50000.0)       # beyond range: scans reach anyway
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 10.0)
    sensors.IdentifyObject(far_away)
    assert sensors.IsObjectKnown(far_away) == 0
    sensor_contacts.tick(player, 13.9)
    assert sensors.IsObjectKnown(far_away) == 0
    sensor_contacts.tick(player, 14.0)
    assert sensors.IsObjectKnown(far_away) == 1


def test_area_scan_spaces_identifications_one_dwell_apart(monkeypatch):
    s, player, sensors = _world()
    a = _ship(s, "A", 30000.0)
    b = _ship(s, "B", 40000.0)
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 0.0)
    seq = sensors.ScanAllObjects()
    assert isinstance(seq, App.TGSequence)
    seq.Play()
    sensor_contacts.tick(player, 4.0)
    assert len(_ids) == 1
    sensor_contacts.tick(player, 8.0)
    assert set(_ids) == {a, b}


def test_force_identify_is_immediate():
    s, player, sensors = _world()
    a = _ship(s, "A", 30000.0)
    sensors.ForceObjectIdentified(a)
    assert sensors.IsObjectKnown(a) == 1
    assert _ids == [a]


def test_force_identify_while_pending_fires_once(monkeypatch):
    s, player, sensors = _world()
    a = _ship(s, "A", 500.0)
    sensor_contacts.tick(player, 0.0)         # passive dwell pending
    sensors.ForceObjectIdentified(a)
    sensor_contacts.tick(player, 4.0)
    assert _ids == [a]


def test_identify_object_on_a_non_player_ship_is_a_no_op(monkeypatch):
    s, player, sensors = _world()
    npc = _ship(s, "NPC", 100.0)
    npc_sensors = SensorSubsystem("Sensors")
    npc.SetSensorSubsystem(npc_sensors)
    target = _ship(s, "T", 200.0)
    npc_sensors.IdentifyObject(target)
    sensor_contacts.tick(player, 100.0)
    assert npc_sensors.IsObjectKnown(target) == 0
```

- [ ] **Step 2: Run it** — `uv run pytest tests/unit/test_sensor_scan_dwell.py -q` → FAIL (`IdentifyObject` identifies at once; Scan Area identifies all at once).

- [ ] **Step 3: Implement**

`SensorSubsystem.IdentifyObject` becomes:

```python
    def IdentifyObject(self, pTarget) -> None:
        """Single-target scan (Science "Scan Object" via
        Actions.ShipScriptActions.ScanObject). BC (RE'd) schedules a DEFERRED
        identification on its player-only contact manager, so this arms one
        identification-time later. Player-only, like BC's; no-op otherwise."""
        from engine.appc import sensor_contacts
        if self._owner_ship() is not sensor_contacts.current_player():
            return
        sensor_contacts.schedule_scan(pTarget, self.GetIdentificationTime())
```

`ScanAllObjects` keeps building one `TGScriptAction` calling `ScanAllObjectsAction` (unchanged). In `sensor_identification.py`, delete `identify_contacts` and `identify_all_in_set`, keep `_identify_one` and `_resolve_sensors_and_set`, and replace `ScanAllObjectsAction` with:

```python
def schedule_area_scan(player) -> int:
    """Active area scan: arm a scan identification for every unknown ship /
    station / planet in *player*'s set, ignoring range, one identification
    time apart (BC's ScanAllObjects spaces its scan actions by
    GetIdentificationTime). Returns how many were armed."""
    sensors, pSet = _resolve_sensors_and_set(player)
    if sensors is None:
        return 0
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet
    from engine.appc import sensor_contacts
    dwell = sensors.GetIdentificationTime()
    n = 0
    for obj in pSet.GetObjectList():
        if obj is None or obj is player or not isinstance(obj, (ShipClass, Planet)):
            continue
        if sensors.IsObjectKnown(obj):
            continue
        n += 1
        sensor_contacts.schedule_scan(obj, dwell * n)
    return n


def ScanAllObjectsAction(pAction, iShipID) -> int:
    """TGScriptAction entry played by the ScanAllObjects sequence. Re-looks up
    the scanning ship by id (SDK idiom) and arms the area scan. Returns 0 so
    TGScriptAction.Play auto-completes."""
    try:
        ship = App.TGObject_GetTGObjectPtr(iShipID)
        if ship is not None:
            schedule_area_scan(ship)
    except Exception as _e:
        dev_mode.log_swallowed("ScanAllObjectsAction", _e)
    return 0
```

Rewrite the module docstring's "Each tick the player's sensors identify newly-detectable contacts …" paragraph: identification now happens through `engine.appc.sensor_contacts` (passive dwell) and scans; `_identify_one` is the single commit point.

`engine/host_loop.py`: replace the identification block (the `if player is not None:` that reads `_last_identify_gt` and calls `identify_contacts`) with:

```python
                # Player-only contact manager: bands, proximity events and the
                # identification dwell (engine/appc/sensor_contacts.py). Sim-gated
                # by the enclosing `not pause.sim_frozen`; it runs its own 1 s
                # sweep cadence internally.
                if player is not None:
                    import App  # deferred: matches host-loop convention
                    from engine.appc import sensor_contacts
                    sensor_contacts.tick(player, App.g_kUtopiaModule.GetGameTime())
```

In `_reset_sensor_state`, remove `_last_identify_gt` from the `global` line and the `_last_identify_gt = None` assignment, and add:

```python
    from engine.appc import sensor_contacts, unknown_labels
    sensor_contacts.reset()
    unknown_labels.reset()
```

Delete the module-level `_last_identify_gt = None  # float | None` (~line 4767) and its docstring mention ("the identification clock") — grep `_last_identify_gt` afterwards: zero hits.

Update existing tests:
- `tests/unit/test_sensor_identification.py`: every `sensor_identification.identify_contacts(player)` becomes `settle_identification(player)` (from `tests.helpers.sensor_time`), and fixtures must set the current game player as in Task 4. The "in range" test's contact at 1000 GU is exactly half of 2000 — the near test is `<=`, so it still identifies; leave a comment saying so. Rename the test module docstring to describe the passive dwell. Keep the cloak tests (cloak bubble distances are well inside half range).
- `tests/unit/test_sensor_scan.py`: area-scan tests now need `sensor_contacts.tick(player, n * 4.0)` after `Play()` before asserting known; single-target scan tests tick one dwell.
- `tests/integration/test_hail_button_population.py:213`: replace `identify_contacts(player)` with `settle_identification(player)`.
- `tests/integration/test_e1m2_scan_area.py::test_area_scan_advances_mission`: keep its assertions; add after them a tick loop `for k in range(1, 40): sensor_contacts.tick(player, k * 1.0)` with `player = MissionLib.GetPlayer()` and assert at least one previously unknown ship in the player's set is now known. If E1M2's `ScanComplete` beat depends on identification being instant, report it — do not change the mission.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_sensor_scan_dwell.py tests/unit/test_sensor_identification.py tests/unit/test_sensor_scan.py tests/integration/test_hail_button_population.py tests/integration/test_e1m2_scan_area.py -q`
Expected: PASS. Then `grep -rn "identify_contacts\|identify_all_in_set\|_last_identify_gt" engine tests` → no hits.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py engine/appc/sensor_identification.py engine/host_loop.py tests/unit/test_sensor_scan_dwell.py tests/unit/test_sensor_identification.py tests/unit/test_sensor_scan.py tests/integration/test_hail_button_population.py tests/integration/test_e1m2_scan_area.py
git commit -m "feat(sensors): scans take the identification dwell; host loop ticks the contact manager"
```

---

### Task 6: Unknown display — Contact.identified, row caption, list payload

**Files:**
- Modify: `engine/appc/perception.py` (`Contact`, `perceived_by`)
- Modify: `engine/appc/target_menu.py` (`STSubsystemMenu`, `STTargetMenu.set_contacts`, module docstring)
- Modify: `engine/ui/target_list_view.py` (row tuple + payload `label`)
- Modify: `native/assets/ui-cef/js/target_list.js` (display `label`)
- Test: `tests/unit/test_unknown_contact_display.py`

**Interfaces:**
- Consumes: `unknown_labels.placeholder`, `current` (Task 3); `settle_identification` (Task 4).
- Produces: `Contact.identified: bool = True`; `STSubsystemMenu.ShowUnknownName(caption=None)`, `ShowRealName()`, `IsShowingUnknownName() -> bool`, `GetCaption() -> str`; `GetAffiliation()` returns `"UNKNOWN"` while showing unknown. Payload rows gain `"label"`.

- [ ] **Step 1: Write the failing test**

```python
"""Unknown contacts: listed and targetable, but captioned "Unknown N", grey
(UNKNOWN affiliation) and without subsystem rows until identified."""
import json
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import perception
from engine.appc.target_menu import STSubsystemMenu, STTargetMenu_CreateW
from tests.helpers.sensor_time import settle_identification


def _world():
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    bird = ShipClass_Create("BirdOfPrey")
    bird.SetTranslateXYZ(500.0, 0.0, 0.0)
    s.AddObjectToSet(bird, "Bird")
    return s, player, sensors, bird


def _contact(player, ship):
    return next(c for c in perception.perceived_by(player) if c.ship is ship)


def test_contact_reports_identified_and_restricts_subsystems():
    s, player, sensors, bird = _world()
    c = _contact(player, bird)
    assert c.perceivable and c.targetable
    assert c.identified is False
    assert c.subsystems_targetable is False
    sensors.AddKnownObject(bird)
    c = _contact(player, bird)
    assert c.identified is True and c.subsystems_targetable is True


def test_row_caption_and_affiliation_while_unknown():
    row = STSubsystemMenu(None, "IKS Korvat")
    row.SetAffiliation("ENEMY")
    row.ShowUnknownName("Unknown 3")
    assert row.GetCaption() == "Unknown 3"
    assert row.GetLabel() == "IKS Korvat"         # SDK lookups keep the real name
    assert row.GetAffiliation() == "UNKNOWN"
    row.ShowRealName()
    assert row.GetCaption() == "IKS Korvat"
    assert row.GetAffiliation() == "ENEMY"


def test_set_contacts_drives_the_caption():
    s, player, sensors, bird = _world()
    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(perception.perceived_by(player))
    row = menu.GetObjectEntry(bird)
    assert row.GetCaption().startswith("Unknown ")
    sensors.AddKnownObject(bird)
    menu.set_contacts(perception.perceived_by(player))
    assert row.GetCaption() == bird.GetDisplayName()


def test_reset_affiliation_colors_keeps_unknown_rows_unknown():
    s, player, sensors, bird = _world()
    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(perception.perceived_by(player))
    menu.ResetAffiliationColors()
    assert menu.GetObjectEntry(bird).GetAffiliation() == "UNKNOWN"


def test_identifying_a_targeted_contact_keeps_the_lock():
    s, player, sensors, bird = _world()
    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(perception.perceived_by(player))
    player.SetTarget(bird)
    sensors.AddKnownObject(bird)
    menu.set_contacts(perception.perceived_by(player))
    assert player.GetTarget() is bird
```

Add a view-level test in the same file that builds the target-list panel the way `tests/unit/test_target_list_view.py` does (copy its fixture idiom exactly), and asserts the payload row for an unknown contact has `"label": "Unknown 1"` and `"name": "<the ship's GetName()>"`, and that after `AddKnownObject` + a re-push `"label"` equals the display name. Name it `test_payload_carries_label_and_keeps_name_as_key`.

- [ ] **Step 2: Run it** — `uv run pytest tests/unit/test_unknown_contact_display.py -q` → FAIL (`Contact` has no `identified`; `GetCaption` missing).

- [ ] **Step 3: Implement**

`perception.Contact`: add after `subsystems_targetable`:

```python
    # True when the OBSERVER's sensors have identified this contact
    # (IsObjectKnown). Defaults True so synthetic constructions (tests, the
    # bulk RebuildShipMenus synthesiser) keep "identified" behaviour. Records
    # are only built for the player; AI never reads them.
    identified: bool = True
```

In `perceived_by`, before the loop: `observer_sensors = observer.GetSensorSubsystem() if implements(observer, "GetSensorSubsystem") else None`. In the loop:

```python
        identified = bool(observer_sensors is not None
                          and observer_sensors.IsObjectKnown(ship))
        out.append(Contact(
            ship=ship,
            surface_gu=_surface_gu(dist_sq, ship),
            perceivable=perceivable,
            targetable=perceivable and alive_or_wreck and bool(ship.IsTargetable()),
            subsystems_targetable=identified and not sd.is_hidden_by_cloak(ship),
            identified=identified,
        ))
```

Update the `subsystems_targetable` field comment: unidentified contacts are now its second producer.

`STSubsystemMenu` (replace the two no-ops; add the caption state in `__init__`):

```python
        self._unknown_caption = None    # set while the contact is unidentified

    def GetAffiliation(self) -> str:
        return "UNKNOWN" if self._unknown_caption is not None else self._affiliation

    def ShowUnknownName(self, caption=None) -> None:
        """Show the row as an unidentified contact. BC's body is
        unreconstructed (RE'd at 0x535800); the engine drives it from
        Contact.identified. GetLabel() keeps the REAL name because
        STTargetMenu.GetSubmenuW resolves rows by it (E2M0/E1M2 arrows)."""
        self._unknown_caption = str(caption) if caption else "Unknown"

    def ShowRealName(self, *args) -> None:
        self._unknown_caption = None

    def IsShowingUnknownName(self) -> bool:
        return self._unknown_caption is not None

    def GetCaption(self) -> str:
        """What the panel draws: the placeholder while unknown, else the label."""
        return self._unknown_caption if self._unknown_caption is not None else self.GetLabel()
```

Update the `target_menu.py` module docstring sentence "(ShowUnknownName / ShowRealName) are no-ops" accordingly.

`STTargetMenu.set_contacts`, inside the loop after `row.SetVisible()`:

```python
            if c.identified:
                row.ShowRealName()
            else:
                from engine.appc import unknown_labels
                row.ShowUnknownName(unknown_labels.placeholder(c.ship))
```

`engine/ui/target_list_view.py`: in `_snapshot`, take `caption = child.GetCaption()` alongside `name` and add it to the row tuple; in `render_payload` emit `"label": caption`. Keep `name` as `ship.GetName()`. Update the tuple unpacking in both places.

`native/assets/ui-cef/js/target_list.js` (~line 71): keep `name` for keys and click actions; display the label:

```js
        const name = String(row.name || '');
        const label = String(row.label || row.name || '');
```

and use `escapeHtml(label)` where `nameHtml` is built (`const nameHtml = escapeHtml(label);`). Leave every `clickAttr('target/' + name ...)` on `name`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_unknown_contact_display.py tests/unit/test_perceived_by.py tests/unit/test_target_list_view.py tests/unit/test_target_menu_visibility_derived.py -q`
Expected: the new tests PASS. Existing tests that assert subsystem rows / `subsystems_targetable=True` for an uncloaked contact now fail because the contact is unidentified: fix the FIXTURE (identify the contact with `sensors.AddKnownObject(ship)` or `settle_identification`), never the assertion. Then run `uv run pytest tests/unit tests/integration -q` and fix every fixture failure of that same shape; list each file you touched in your report.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/perception.py engine/appc/target_menu.py engine/ui/target_list_view.py native/assets/ui-cef/js/target_list.js tests/unit/test_unknown_contact_display.py
git add <each fixture file you fixed, explicitly>
git commit -m "feat(sensors): unidentified contacts list as grey Unknown N without subsystems"
```

---

### Task 7: Science Scan Object button — no name leak

**Files:**
- Create: `engine/appc/science_scan_labels.py`
- Modify: `engine/appc/sensor_identification.py` (`_identify_one`: rename + release before posting)
- Modify: `engine/host_loop.py:~281` (install beside `install_ai_sensor_gate()`) and `_reset_sensor_state` (re-install, idempotent)
- Test: `tests/integration/test_science_scan_unknown_labels.py`

**Interfaces:**
- Consumes: `unknown_labels.placeholder/current/release`; `sensor_contacts.player_knows`.
- Produces: `science_scan_labels.install() -> None` (idempotent); `science_scan_labels.rename_on_identify(obj) -> None`.

- [ ] **Step 1: Write the failing test**

Base the fixture on `tests/integration/test_science_scan_menu_removal.py` (read it first — it already builds the bridge menus and drives Science's handlers). Tests:

```python
def test_unknown_contact_gets_a_placeholder_scan_button():
    # world from the removal test's fixture; player's sensors do NOT know bird
    # post ET_TARGET_LIST_OBJECT_ADDED (destination=bird) as the target list does
    # assert the Scan Object submenu has a button "Unknown 1" and none named
    # bird.GetDisplayName()


def test_identification_renames_the_button_without_a_duplicate():
    # as above, then sensors.ForceObjectIdentified(bird)
    # assert exactly one button for bird, labelled bird.GetDisplayName(),
    # and no "Unknown 1"


def test_exit_set_removes_the_placeholder_button():
    # as the first test, then remove bird from its set
    # assert no "Unknown 1" button remains


def test_two_unknowns_get_two_buttons():
    # two unknown ships with the SAME display name
    # assert two buttons "Unknown 1" and "Unknown 2"


def test_known_contact_uses_its_real_name():
    # sensors.AddKnownObject(bird) BEFORE the ADDED event
    # assert the button is labelled bird.GetDisplayName()
```

Write each body with real code using the removal test's idioms (`MissionLib.GetCharacterSubmenu("Science", "Scan Object")`, `GetButtonW(label)`), and call `science_scan_labels.install()` in the fixture. Every assertion above must be concrete.

- [ ] **Step 2: Run it** — FAIL (module missing; real name used).

- [ ] **Step 3: Implement** `engine/appc/science_scan_labels.py`:

```python
"""Keep Science's Scan Object buttons on the "Unknown N" placeholder until the
contact is identified (sensor-tiers spec §6, roadmap decision 5).

Science adds a button labelled GetDisplayName() on ET_TARGET_LIST_OBJECT_ADDED
as well as on identification (Bridge/ScienceMenuHandlers.py:91-94), which
would leak an unknown ship's real name. Two SDK functions are wrapped, by
module attribute — handlers resolve by name at dispatch
(engine/appc/events.py:_resolve_handler), so the wrap reaches live events:

  * CreateScanButton — sees the placeholder as the object's display name, so
    its GetButtonW de-dupe and STButton_CreateW label both use it.
  * ExitedSet — removes by the placeholder while the object is unknown.

On identification `_identify_one` calls rename_on_identify BEFORE posting
ET_SENSORS_SHIP_IDENTIFIED; otherwise ShipIdentified's de-dupe (by the real
name) would miss the placeholder button and add a duplicate.
"""
from contextlib import contextmanager

import App
from engine.appc import unknown_labels


@contextmanager
def _display_name_as(obj, label):
    """Temporarily make obj.GetDisplayName() answer *label* (instance attr)."""
    obj.GetDisplayName = lambda: label
    try:
        yield
    finally:
        try:
            del obj.GetDisplayName
        except AttributeError:
            pass


def _unknown_label(obj):
    from engine.appc import sensor_contacts
    if obj is None or sensor_contacts.player_knows(obj):
        return None
    return unknown_labels.placeholder(obj)


def _wrap_create(orig):
    def CreateScanButton(pObject):
        obj = App.ObjectClass_Cast(pObject)
        label = _unknown_label(obj)
        if label is None:
            return orig(pObject)
        with _display_name_as(obj, label):
            return orig(pObject)
    CreateScanButton._unknown_labelled = True
    return CreateScanButton


def _wrap_exited(orig):
    def ExitedSet(pObject, pEvent=None):
        obj = App.ObjectClass_Cast(pEvent.GetDestination() if pEvent else pObject)
        label = unknown_labels.current(obj) if obj is not None else None
        if label is None:
            return orig(pObject, pEvent)
        with _display_name_as(obj, label):
            return orig(pObject, pEvent)
    ExitedSet._unknown_labelled = True
    return ExitedSet


def install() -> None:
    try:
        import Bridge.ScienceMenuHandlers as smh
    except ImportError:
        return
    if not getattr(smh.CreateScanButton, "_unknown_labelled", False):
        smh.CreateScanButton = _wrap_create(smh.CreateScanButton)
    if not getattr(smh.ExitedSet, "_unknown_labelled", False):
        smh.ExitedSet = _wrap_exited(smh.ExitedSet)


def rename_on_identify(obj) -> None:
    label = unknown_labels.current(obj)
    if label is None:
        return
    try:
        import MissionLib
        menu = MissionLib.GetCharacterSubmenu("Science", "Scan Object")
    except Exception:
        return
    if menu is None:
        return
    button = menu.GetButtonW(label)
    if button is not None:
        button.SetLabel(obj.GetDisplayName())
```

If instance assignment of `GetDisplayName` does not take effect on `ShipClass` (e.g. a `__setattr__` override or `__slots__`), report it and use a thread-free module-level override instead — do not copy the SDK body.

`_identify_one` (in `sensor_identification.py`), between `sensors.AddKnownObject(obj)` and building the event:

```python
    # Before the event: Science's ShipIdentified de-dupes by the REAL name,
    # so the placeholder button must already carry it (spec §6).
    try:
        from engine.appc import science_scan_labels, unknown_labels
        science_scan_labels.rename_on_identify(obj)
        unknown_labels.release(obj)
    except Exception as _e:
        dev_mode.log_swallowed("identify unknown-label rename", _e)
```

`engine/host_loop.py` beside `install_ai_sensor_gate()` (~line 281):

```python
    from engine.appc import science_scan_labels
    science_scan_labels.install()
```

and the same two lines at the end of `_reset_sensor_state` (the SDK module may be re-imported across a mission swap; `install` is idempotent). Add a test asserting the wrap is present after `host_loop._init_mission("Maelstrom.Episode1.E1M2.E1M2")` (use `tests/integration/test_e1m2_scan_area.py`'s `_init_e1m2` idiom).

- [ ] **Step 4: Run** — `uv run pytest tests/integration/test_science_scan_unknown_labels.py tests/integration/test_science_scan_menu_removal.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/science_scan_labels.py engine/appc/sensor_identification.py engine/host_loop.py tests/integration/test_science_scan_unknown_labels.py
git commit -m "feat(sensors): Science scan buttons show Unknown N until identification"
```

---

### Task 8: Target panel gate and radar colour constants

**Files:**
- Modify: `engine/ui/ship_display_panel.py` (`_resolve_ship_for_role`, ~line 320-346; its docstring)
- Modify: `App.py` (beside `g_kSTMenu2NormalBase`, ~line 1357)
- Test: `tests/unit/test_unknown_target_panel_and_colours.py`

**Interfaces:**
- Produces: target role resolves to None for an unidentified target; `App.g_kRadarFriendlyColor`, `g_kRadarEnemyColor`, `g_kRadarNeutralColor`, `g_kRadarUnknownColor` are real `NiColorA`.

- [ ] **Step 1: Write the failing test**

```python
import App


def test_radar_colours_are_real_and_unknown_is_mid_grey():
    for name in ("g_kRadarFriendlyColor", "g_kRadarEnemyColor",
                 "g_kRadarNeutralColor", "g_kRadarUnknownColor"):
        assert isinstance(getattr(App, name), App.NiColorA), name
    c = App.g_kRadarUnknownColor
    assert abs(c.r - 127.5 / 255.0) < 1e-6
    assert abs(c.g - 127.5 / 255.0) < 1e-6
    assert abs(c.b - 127.5 / 255.0) < 1e-6
```

Check `TGColorA`'s attribute names in `App.py:1309` (`r/g/b/a` or otherwise) and match them.

Add a panel test copying the fixture idiom of `tests/unit/test_sensors_disabled_blanks_target_ui.py` (read it): player targets an unidentified ship → the target-role resolver returns None; after `sensors.AddKnownObject(target)` → it returns the ship. Name it `test_unknown_target_blanks_the_target_panel`.

- [ ] **Step 2: Run it** — FAIL (colours are stubs; resolver ignores `IsObjectKnown`).

- [ ] **Step 3: Implement**

`App.py`, after the `g_kSTMenu2*` block:

```python
# ── Radar affiliation colours (LoadInterface.py:135-140 sets these through
# SetupColor; real objects so SetupColor and readers never meet a _Stub).
# Values are the SDK's own. g_kRadarUnknownColor was a live undefined-constant
# stub (docs/stub_heatmap.md rank 182).
g_kRadarFriendlyColor = NiColorA(80.0 / 255.0, 112.0 / 255.0, 230.0 / 255.0, 1.0)
g_kRadarEnemyColor    = NiColorA(216.0 / 255.0, 43.0 / 255.0, 43.0 / 255.0, 1.0)
g_kRadarNeutralColor  = NiColorA(1.0, 1.0, 0.68627, 1.0)
g_kRadarUnknownColor  = NiColorA(127.5 / 255.0, 127.5 / 255.0, 127.5 / 255.0, 1.0)
```

`ship_display_panel._resolve_ship_for_role`, replace the final return:

```python
    from engine.appc.ships import ShipClass_Cast
    ship = ShipClass_Cast(target)
    # The SDK gate (ShieldsDisplay.SetShipIcon, ShieldsDisplay.py:329-338):
    # an unidentified target shows no data. Contacts are now identified by the
    # contact manager, so the gate is applied (sensor-tiers spec §5).
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    if ship is not None and sensors is not None and not sensors.IsObjectKnown(ship):
        return None
    return ship
```

and rewrite the docstring paragraph that says the gate is skipped.

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_unknown_target_panel_and_colours.py tests/unit -q -k "ship_display or target_panel or colour or color"` → new tests PASS; fix any fixture that now targets an unidentified ship by identifying it (fixture, not assertion).

- [ ] **Step 5: Commit**

```bash
git add App.py engine/ui/ship_display_panel.py tests/unit/test_unknown_target_panel_and_colours.py
git add <each fixture file you fixed, explicitly>
git commit -m "feat(sensors): target panel honours IsObjectKnown; real radar colour constants"
```

---

### Task 9: Mission integration and the gate

**Files:**
- Test: `tests/integration/test_sensor_tiers_missions.py`
- Modify: `docs/stub_heatmap.md` only if `tools/stub_heatmap.py` is the documented way to refresh it (do not hand-edit generated tables)
- Modify: `CLAUDE.md` — add one reference-table row for the sensor model (pointer only)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the integration tests**

Use `host_loop._init_mission(<module>)` after `tests.integration.test_sdk_bridge_load._fresh_world()` exactly as `tests/integration/test_e1m2_scan_area.py::_init_e1m2` does.

```python
"""Missions that depend on the two tiers (sensor-tiers spec, Testing)."""
import App
import MissionLib
from engine import host_loop
from engine.appc import sensor_contacts
from tests.integration.test_sdk_bridge_load import _fresh_world


def _init(module):
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(module)
    return mod


def _ship_in_player_set(name, offset_gu):
    player = MissionLib.GetPlayer()
    loc = player.GetWorldLocation()
    import loadspacehelper
    ship = loadspacehelper.CreateShip("Galor", player.GetContainingSet(), name, None)
    ship.SetTranslateXYZ(loc.x + offset_gu, loc.y, loc.z)
    return player, ship


def test_e2m2_ships_on_sensors_comes_from_far_proximity_not_identify():
    mod = _init("Maelstrom.Episode2.E2M2.E2M2")
    name = mod.g_lShipNames[0]
    player, ship = _ship_in_player_set(name, 0.0)
    r = player.GetSensorSubsystem().GetSensorRange()
    ship.SetTranslateXYZ(player.GetWorldLocation().x + r * 0.75,
                         player.GetWorldLocation().y, player.GetWorldLocation().z)
    mod.g_bShipsOnSensors = 0
    sensor_contacts.tick(player, 1000.0)
    assert mod.g_bShipsOnSensors == 1
    assert player.GetSensorSubsystem().IsObjectKnown(ship) == 0


def test_contact_identified_only_after_dwell_in_mission():
    mod = _init("Maelstrom.Episode1.E1M2.E1M2")
    player, ship = _ship_in_player_set("Test Contact", 50.0)
    sensors = player.GetSensorSubsystem()
    sensor_contacts.tick(player, 1000.0)
    assert sensors.IsObjectKnown(ship) == 0
    sensor_contacts.tick(player, 1000.0 + sensors.GetIdentificationTime())
    assert sensors.IsObjectKnown(ship) == 1
```

Read E2M2 first: confirm `g_lShipNames` and `g_bShipsOnSensors` exist as module globals and that `ShipInSensorRange` is registered at mission load (E2M2.py:565). Confirm the `loadspacehelper.CreateShip` signature and a valid ship script name (grep its other uses in `tests/`). If `ShipInSensorRange` only registers after the player reaches Serris 2, drive the mission state the way `tests/integration/test_campaign_warp_transitions.py` does, or STOP and report BLOCKED with what you found — do not weaken the assertion.

Add one E8M1 test if (and only if) `DetectingObject`'s registration and its `Belaruz1` set can be reached headlessly: a `KessokHeavy` in the player's set inside far range, beyond near range → `sensor_contacts.tick` → the handler ran (it removes itself: assert the handler is no longer registered, or assert its documented side effect, player targets the Kessok). Otherwise list it under "live check" in your report.

- [ ] **Step 2: Run** — `uv run pytest tests/integration/test_sensor_tiers_missions.py -q` → PASS.

- [ ] **Step 3: Full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression from this branch — fix it (fixture fixes must identify contacts; never weaken an assertion). Never call a failure pre-existing by eyeball.

- [ ] **Step 4: Docs**

Add a CLAUDE.md reference-table row:

```markdown
| Sensor tiers — detected vs identified | `engine/appc/sensor_contacts.py`, `engine/appc/unknown_labels.py`, `engine/appc/science_scan_labels.py`, `engine/appc/sensor_dials.py`, `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md` | BC's two tiers, RE'd: contacts in range list as grey **"Unknown N"** (no subsystems, Hail button or target panel) until they sit in the **near band (half range)** for the **4.0 s** dwell, or a scan identifies them. Player-only 1 s sweep posts `FAR/NEAR_PROXIMITY` (source = the ship). `_identify_one` is the single commit point. ⚠️ `STSubsystemMenu.GetLabel()` stays the REAL name (tutorial arrows resolve rows by it); the placeholder is `GetCaption()`. Dials: "sensors" group on / L O. Sub-project 2 (continuity + occlusion) is in the roadmap. |
```

Add a "As built" section at the end of the spec listing anything that differed from the spec during execution.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_sensor_tiers_missions.py CLAUDE.md docs/superpowers/specs/2026-10-03-sensor-tiers-design.md
git commit -m "test(sensors): mission integration for the two tiers; docs"
```
