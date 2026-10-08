# Sensor Debts (sensor model sub-project 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ForceObjectIdentified` player-only, give sensor-less observers a 2000 GU dial instead of 30000 GU, cap the cloak bubble with a 30 GU dial, and correct the docs.

**Architecture:** Two new dials in `engine/appc/sensor_dials.py`, read at use by `engine/appc/sensor_detection.py` (`effective_sensor_range` and `can_detect`'s cloak term). One gate line in `engine/appc/subsystems.py`. The test helper `tests/helpers/cloak_geometry.py` keeps deriving the bubble from live values, now including the cap.

**Tech Stack:** Python 3 engine shim, pytest. No C++ change.

**Spec:** `docs/superpowers/specs/2026-10-08-sensor-debts-design.md`

## Global Constraints

- Worktree: `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/sensor-debts`, branch `feat/sensor-debts`. Run every command from there. Never commit to main; never push.
- **Banned git:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths only. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` to prove it.
- Units are GU (1 GU = 175 m). Never name a variable `*_m`.
- `sensorless_range_gu`: default 2000.0, step 250.0, min 250.0, no max.
- `cloak_bubble_cap_gu`: default 30.0, step 1.0, min 1.0, no max.
- **Never restate a cloak bubble size in prose** (comments, docstrings, messages). Compute it in tests from `CLOAK_DETECTION_BASE_GU`, `CLOAK_RANGE_FACTOR` and the dials via `tests.helpers.cloak_geometry`.
- `FALLBACK_RANGE_GU` is deleted, not aliased. Nothing may reference it afterwards (`grep -rn FALLBACK_RANGE_GU engine tests` must be empty at the end of Task 2).
- Dials are read at use (`sensor_dials.get(name)`), never captured at import.
- Tests set a dial with `monkeypatch.setitem(sensor_dials._dials, "<name>", value)`; conftest's autouse reset calls `sensor_dials.reset()`.
- Python test runs: `uv run pytest <path> -q`. Full gate: `scripts/check_tests.sh` (must exit 0; `tests/known_failures.txt` holds no failures and none may be added).

## Review Focus

1. A `ForceObjectIdentified` on sensors whose owner cannot be resolved while no game/player exists: `None is None` must NOT count as "is the player". Expected: no-op, no raise. (Task 1)
2. An over-boosted observer (NormalPowerPercentage > 1.0) with high base range seeing a cloaked target: expected capped at `cloak_bubble_cap_gu`, never above. (Task 3)
3. A cloaked target near an observer whose sensors are offline: expected not detected, even inside the cap (the `r <= 0.0` guard precedes the cap). (Task 3)
4. Live dial change: stepping `sensorless_range_gu` or `cloak_bubble_cap_gu` mid-run changes the next `can_detect` answer with no restart. (Tasks 2 and 3)
5. A ship that HAS a sensor subsystem with `BaseSensorRange` 0 gets the dial, same as a ship with none. (Task 2)

---

### Task 1: `ForceObjectIdentified` is player-only

**Files:**
- Modify: `engine/appc/subsystems.py` (`SensorSubsystem.ForceObjectIdentified`, ~line 1481)
- Modify: `engine/appc/sensor_identification.py:69-72` (comment cites "AI-side ForceObjectIdentified")
- Test: `tests/unit/test_sensor_identification.py`

**Interfaces:**
- Consumes: `engine.appc.sensor_contacts.current_player()` (returns the current Game's player ship or None); `SensorSubsystem._owner_ship()`.
- Produces: nothing new; behaviour change only.

- [ ] **Step 1: Replace the NPC test and add the orphan test**

In `tests/unit/test_sensor_identification.py`, replace the whole of `test_npc_force_identify_does_not_release_the_players_placeholder` with the two tests below. The old test pinned the opposite behaviour (an NPC's sensors identifying), which the spec's Rule 1 removes. Its placeholder assertion still holds, so keep it.

```python
def test_npc_force_identify_is_a_no_op():
    """BC's contact manager is player-only: every entry point is gated on
    GetParentShip() == GetPlayerShip() (sensor-subsystem.md, "The Global
    Contact Manager"; ForceObjectIdentified @0x005678B0). On an NPC's own
    sensors it marks nothing known, fires no ET_SENSORS_SHIP_IDENTIFIED and
    leaves the player's "Unknown N" placeholder allocated. All four SDK
    callers pass the PLAYER's sensors (spec, Evidence)."""
    _subscribe()
    s, player, sensors = _player_in_set()
    from engine.appc import unknown_labels
    unknown_labels.reset()

    npc = ShipClass_Create("Galaxy")
    npc_sensors = SensorSubsystem("Sensors")
    npc.SetSensorSubsystem(npc_sensors)
    s.AddObjectToSet(npc, "npc")

    target = ShipClass_Create("BirdOfPrey")
    s.AddObjectToSet(target, "Bird")
    placeholder = unknown_labels.placeholder(target)

    npc_sensors.ForceObjectIdentified(target)

    assert npc_sensors.IsObjectKnown(target) == 0
    assert sensors.IsObjectKnown(target) == 0
    assert target not in _identified
    assert unknown_labels.current(target) == placeholder


def test_force_identify_with_no_player_is_a_no_op():
    """Orphan sensors and no current game: the owner and the player are both
    None, and None-is-None must not pass the player gate."""
    _subscribe()
    _set_current_game(None)
    orphan = SensorSubsystem("Sensors")
    target = ShipClass_Create("BirdOfPrey")

    orphan.ForceObjectIdentified(target)   # must not raise

    assert orphan.IsObjectKnown(target) == 0
    assert _identified == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_identification.py -q -k "npc_force_identify_is_a_no_op or no_player_is_a_no_op"`
Expected: `test_npc_force_identify_is_a_no_op` FAILS (`IsObjectKnown` returns 1). `test_force_identify_with_no_player_is_a_no_op` may pass or fail depending on whether `_identify_one` tolerates an orphan; record which.

- [ ] **Step 3: Gate the method**

Replace the body and docstring of `ForceObjectIdentified` in `engine/appc/subsystems.py`:

```python
    def ForceObjectIdentified(self, pTarget) -> None:
        """Immediate identification (BC @0x005678B0), bypassing the dwell.
        SDK ``HelmMenuHandlers.SetupOrbitMenuFromSet`` uses it so orbitable
        planets are targetable; MissionLib.IdentifyObjects, E3M4 and E4M4 use
        it on mission ships. Player-only, like BC's contact manager (every
        entry point gated on GetParentShip() == GetPlayerShip()): a no-op on
        any other ship's sensors, and when there is no player. All four SDK
        callers pass the player's sensors. None-safe and de-duped (a no-op if
        *pTarget* is None or already known)."""
        from engine.appc import sensor_contacts, sensor_identification
        owner = self._owner_ship()
        if owner is None or owner is not sensor_contacts.current_player():
            return
        sensor_identification._identify_one(self, pTarget)
```

- [ ] **Step 4: Fix the stale comment**

In `engine/appc/sensor_identification.py`, the comment around lines 69-72 says `_identify_one` "also commits identification for an NPC's own sensors (e.g. AI-side ForceObjectIdentified)". Reword the comment so it no longer names `ForceObjectIdentified` as an NPC path. Keep the guard itself unchanged as defence in depth:

```python
    # Player-only: the Scan Object menu and the "Unknown N" placeholder are
    # both the PLAYER's UI. Every public way in (dwell, scan,
    # ForceObjectIdentified) is already player-gated, as BC's contact manager
    # is; this guard is defence in depth so an NPC-owned sensors object can
    # never rename/release the number the PLAYER's target list is showing.
```

- [ ] **Step 5: Run the identification tests plus the SDK-caller integration tests**

Run: `uv run pytest tests/unit/test_sensor_identification.py tests/unit/test_sensor_scan_dwell.py tests/integration/test_sensor_memory_missions.py tests/integration/test_science_scan_unknown_labels.py tests/integration/test_sensor_continuity_missions.py -q`
Expected: all PASS. If an integration test fails, read it: it must be calling through an NPC's sensors or with no game player. Report it as BLOCKED with the evidence; do not loosen the gate.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py engine/appc/sensor_identification.py tests/unit/test_sensor_identification.py
git commit -m "fix(sensors): ForceObjectIdentified is player-only, like BC's contact manager"
```

---

### Task 2: Sensor-less observers see the `sensorless_range_gu` dial (default 2000 GU)

**Files:**
- Modify: `engine/appc/sensor_dials.py` (DEFAULTS, `_STEP`, `_MIN`, docstring)
- Modify: `engine/appc/sensor_detection.py` (delete `FALLBACK_RANGE_GU` at line ~34-37; `effective_sensor_range` reads the dial; its docstring)
- Modify: `engine/cameras/dof.py:155` (comment naming `FALLBACK_RANGE_GU (30000 GU)`)
- Modify: `engine/appc/ai_sensor_gate.py:64-72` (only the sentence on "18 of 52 ... FALLBACK_RANGE_GU (30000), the largest bubble"; Task 3 rewrites the rest of that note)
- Modify: `tests/helpers/cloak_geometry.py`
- Test: `tests/unit/test_sensor_dials.py`, `tests/unit/test_sensor_detection.py`
- Update (measured fallout, see below): `tests/unit/test_cloak_subsystem_suppression.py`, `tests/unit/test_cloak_target_visibility.py`, `tests/unit/test_concealment_latch_lifetime.py`, `tests/unit/test_select_target_drops_cloaked.py`, `tests/unit/test_select_target_forceupdate_drops_cloaked.py`, `tests/unit/test_dof_focus.py`, plus docstrings in `test_sensors_disabled_blanks_target_ui.py`, `test_cloak_detection_contest.py`, `test_nebula_concealment.py`, `test_ai_acquires_close_cloaked.py`, `test_phaser_cloaked_target_no_fire.py`, `test_nebula_hides_contacts_from_ui.py`, `test_sensor_visibility.py`, `test_perceived_by.py`

**Interfaces:**
- Produces: dial `"sensorless_range_gu"` (read `sensor_dials.get("sensorless_range_gu")`); helper `tests.helpers.cloak_geometry.sensorless_gu() -> float` (replaces the `FALLBACK_SENSOR_GU` constant, read at call time).
- Removes: `engine.appc.sensor_detection.FALLBACK_RANGE_GU`, `tests.helpers.cloak_geometry.FALLBACK_SENSOR_GU`.

**Measured fallout:** setting the old constant to 2000.0 on this branch's base (`0910936f`) failed exactly these 15 tests. Every one of them must pass again at the end of this task, through a deliberate change, never by restoring a large range just to make it green:
- `test_cloak_subsystem_suppression.py`: all 7 tests (`..._inside_bubble_lists_ship_with_no_subsystems`, `test_uncloaked_contact_at_same_distance_still_carries_subsystems`, `test_subsystem_lock_drops_to_ship_level_when_target_cloaks`, `test_subsystem_lock_drops_when_target_cloaks_outside_the_bubble`, `test_dispatch_event_subsystem_click_rechecks_cloak_flag`, `test_enhanced_sensor_contest_off_cloaked_ship_undetected_untouched`, `test_cached_subsystem_rows_survive_cloak_then_decloak_without_rebuild`)
- `test_cloak_target_visibility.py`: 6 tests (`test_cloaked_ship_marked_not_visible_for_radar`, `test_cloaked_ship_stays_on_radar_inside_the_bubble`, `test_cloaked_ship_dropped_from_target_list_view`, `test_cloaked_ship_stays_in_target_list_view_inside_the_bubble`, `test_player_lock_drops_cloaked_target`, `test_player_lock_survives_close_cloak_but_drops_beyond_the_bubble`)
- `test_concealment_latch_lifetime.py`: `test_a_fresh_pair_in_the_band_is_detected`, `test_a_recycled_id_cannot_inherit_a_stale_latch`

Deleting the constant also breaks every importer of `FALLBACK_RANGE_GU` / `FALLBACK_SENSOR_GU` (collection errors). Find them all with `grep -rn "FALLBACK_RANGE_GU\|FALLBACK_SENSOR_GU" engine tests`.

- [ ] **Step 1: Write the failing dial and range tests**

Append to `tests/unit/test_sensor_dials.py`:

```python
def test_sensorless_range_dial_default_step_and_floor():
    sensor_dials.reset()
    assert sensor_dials.get("sensorless_range_gu") == 2000.0
    d = dict(sensor_dials.DEFAULTS)
    assert sensor_dials.step(d, "sensorless_range_gu", +1)["sensorless_range_gu"] == 2250.0
    low = dict(d, sensorless_range_gu=250.0)
    assert sensor_dials.step(low, "sensorless_range_gu", -1)["sensorless_range_gu"] == 250.0
```

In `tests/unit/test_sensor_detection.py`: drop `FALLBACK_RANGE_GU` from the import at line 13, add `from engine.appc import sensor_dials`, and replace the three `== FALLBACK_RANGE_GU` assertions (lines ~55, ~77, ~82) with `== sensor_dials.get("sensorless_range_gu")`. Update the docstring at ~line 66 to say "the `sensorless_range_gu` dial" instead of `FALLBACK_RANGE_GU`. Then add:

```python
def test_sensorless_range_is_the_dial_read_at_use(monkeypatch):
    """Rule 2 (spec 2026-10-08-sensor-debts-design.md): a ship with no sensor
    subsystem, and one with BaseSensorRange 0, both see the live dial."""
    class _NoSensorShip:
        def GetSensorSubsystem(self):
            return None
    zero_ship, _ = _ship_with_sensor(0.0)
    assert effective_sensor_range(_NoSensorShip()) == 2000.0
    assert effective_sensor_range(zero_ship) == 2000.0
    monkeypatch.setitem(sensor_dials._dials, "sensorless_range_gu", 750.0)
    assert effective_sensor_range(_NoSensorShip()) == 750.0
    assert effective_sensor_range(zero_ship) == 750.0


def test_a_sensorless_observer_no_longer_sees_past_the_dial():
    """The old 30000 GU fallback made sensor-less observers (CommArray,
    CommLight stations) see farther than any authored sensor."""
    observer = ShipClass_Create("CommArray")
    assert observer.GetSensorSubsystem() is None   # the case under test
    observer.SetTranslateXYZ(0.0, 0.0, 0.0)
    near = ShipClass_Create("BirdOfPrey")
    far = ShipClass_Create("BirdOfPrey")
    near.SetTranslateXYZ(1500.0, 0.0, 0.0)
    far.SetTranslateXYZ(2500.0, 0.0, 0.0)
    assert can_detect(observer, near) is True
    assert can_detect(observer, far) is False
```

`ShipClass_Create` builds no subsystems from a hardpoint, so the in-test assert is the guard that this really is a sensor-less observer.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_dials.py tests/unit/test_sensor_detection.py -q`
Expected: FAIL (`KeyError: 'sensorless_range_gu'`, and 30000 != 2000).

- [ ] **Step 3: Add the dial**

In `engine/appc/sensor_dials.py`, add to `DEFAULTS` after `overboost_threshold`:

```python
    # Sub-project 5 (2026-10-08-sensor-debts-design.md) -- Mark's rulings,
    # play-test values, not recovered BC numbers.
    "sensorless_range_gu": 2000.0,    # range for an observer with no sensor subsystem / no BaseSensorRange
```

Add `"sensorless_range_gu": 250.0` to both `_STEP` and `_MIN`. Add a sentence to the module docstring: "`sensorless_range_gu` (sub-project 5) is Mark's play-test ruling, not a recovered BC value."

Update `test_continuity_and_occlusion_dials_defaults_and_order` in `tests/unit/test_sensor_dials.py`: its `set(DIAL_ORDER[3:])` assertion must now include `"sensorless_range_gu"`.

- [ ] **Step 4: Delete the constant and read the dial**

In `engine/appc/sensor_detection.py`, delete the comment and the line `FALLBACK_RANGE_GU = 30000.0` (lines ~34-37). In `effective_sensor_range`, replace both `return FALLBACK_RANGE_GU` with `return _sensorless_range()`, and add this above the function:

```python
def _sensorless_range() -> float:
    """Range for an observer that models no sensor subsystem or carries no
    BaseSensorRange: the `sensorless_range_gu` dial (Mark's ruling,
    2026-10-08). Only CommArray and CommLight (plus rocks, which never
    observe) author no sensors; the 7 other stock hardpoints without a
    SetBaseSensorRange inherit their parent's."""
    from engine.appc import sensor_dials
    return sensor_dials.get("sensorless_range_gu")
```

In the `effective_sensor_range` docstring, replace "Returns FALLBACK_RANGE_GU" and "the documented fallback" wording with "the `sensorless_range_gu` dial".

- [ ] **Step 5: Run the new tests**

Run: `uv run pytest tests/unit/test_sensor_dials.py tests/unit/test_sensor_detection.py -q`
Expected: PASS.

- [ ] **Step 6: Update the cloak geometry helper**

In `tests/helpers/cloak_geometry.py`:
- Delete `FALLBACK_SENSOR_GU = sd.FALLBACK_RANGE_GU` and its comment, and add:

```python
def sensorless_gu():
    """What `effective_sensor_range` returns for an observer with NO sensor
    subsystem: the live `sensorless_range_gu` dial, read at call time."""
    from engine.appc import sensor_dials
    return sensor_dials.get("sensorless_range_gu")
```

- In the module docstring, replace both `FALLBACK_SENSOR_GU` examples with `sensorless_gu()`, and drop the claim that `inside_gu(...)` of the sensor-less range is "far beyond a phaser's 60 GU reach" (no longer true); keep the point that a derived distance can silently violate a second constraint.
- Remove the "18 of 52 hardpoint files" comment.

- [ ] **Step 7: Fix every importer and the 15 measured failures**

Run `grep -rn "FALLBACK_RANGE_GU\|FALLBACK_SENSOR_GU" engine tests` and handle each hit:

1. **Tests that place a cloaked target "inside the sensor-less bubble" at a literal 50 GU** (`test_cloak_subsystem_suppression.py` ~line 56-60, `test_cloak_target_visibility.py` ~line 62-66, and the tests in those files that depend on that layout). Under the new default the sensor-less bubble is smaller than 50 GU, so `assert_inside(50.0, ...)` fails. Re-pick the distance; don't relax the assertion. If the 50 GU has no second constraint, derive it: use `inside_gu(sensorless_gu())`. If it does (e.g. a weapon range), keep a literal that satisfies both and assert it with `assert_inside(<literal>, sensorless_gu())`. Every "outside the bubble" probe in these files uses `outside_gu(sensorless_gu())`. Rewrite the module docstrings (lines ~12-13 and ~20) without "30000", "the game's largest bubble", or any bubble size.
2. **`test_concealment_latch_lifetime.py::_scene`**: the observer sits 3000 GU from the nebula core, beyond the new range. The scene's own docstring says "range is never the reason a detection fails here". Move the observer closer, e.g. `(0.0, 0.0, 1500.0)`, only if that point is still in clear space: add `assert sd.concealment_at(observer) == 0.0` inside `_scene`. If no closer clear point exists, give the observer a real sensor subsystem with a base range that covers the layout instead. Update the docstring to name the `sensorless_range_gu` dial.
3. **`test_select_target_drops_cloaked.py` and `test_select_target_forceupdate_drops_cloaked.py`**: replace `FALLBACK_SENSOR_GU` with `sensorless_gu()` in the imports and the `inside_gu(...)` / `outside_gu(...)` calls; fix the module docstrings (~line 21, ~line 14) so they no longer say the sensor-less bubble is the largest.
4. **`test_dof_focus.py` ~lines 181-189**: that test is about a far focus distance staying under `MAX_FOCUS_GU`, not about sensors. Replace `sensor_detection.FALLBACK_RANGE_GU` with a local `FAR_FOCUS_GU = 30000.0` named for what it is, and update the docstring to say the old sensor fallback was this distance. Keep the assertion `FAR_FOCUS_GU < dof.MAX_FOCUS_GU`.
5. **Docstring-only mentions** (`test_sensors_disabled_blanks_target_ui.py:110`, `test_cloak_detection_contest.py:17,170`, `test_nebula_concealment.py:7,62`, `test_ai_acquires_close_cloaked.py:56`, `test_phaser_cloaked_target_no_fire.py:138`, `test_nebula_hides_contacts_from_ui.py:53`, `test_sensor_visibility.py:11`, `test_perceived_by.py:16`): rewrite each so it names the `sensorless_range_gu` dial and states no number. Where a docstring claims a contact is "well within 30000 range", check the actual distance against 2000 GU; if the test still passes, it's within range, so just fix the words.
6. **`engine/cameras/dof.py:155`**: rewrite the clause to "sensor_detection's old 30000 GU sensor-less fallback -- which USED to sit six times past the far plane -- would now be well inside it". A history note is fine; there's no live constant to name.
7. **`engine/appc/ai_sensor_gate.py:66-68`**: replace "while the 18 of 52 hardpoint files that author no SetBaseSensorRange fall back to FALLBACK_RANGE_GU (30000), the largest bubble in the game" with "and the two stock hardpoints with no sensors at all (commarray, commlight) use the `sensorless_range_gu` dial". Task 3 rewrites the rest of the note.

- [ ] **Step 8: Prove the 15 pass and nothing references the constant**

Run: `grep -rn "FALLBACK_RANGE_GU\|FALLBACK_SENSOR_GU" engine tests` → no output.
Run: `uv run pytest tests/unit/test_cloak_subsystem_suppression.py tests/unit/test_cloak_target_visibility.py tests/unit/test_concealment_latch_lifetime.py tests/unit/test_select_target_drops_cloaked.py tests/unit/test_select_target_forceupdate_drops_cloaked.py tests/unit/test_dof_focus.py tests/unit/test_sensor_detection.py tests/unit/test_sensor_dials.py -q` → all PASS.
Then run the full pytest suite: `scripts/run_tests.sh -q`. Expected: 0 failures, 0 errors.

- [ ] **Step 9: Commit**

Stage every file you changed, by explicit path (list them with `git status --short`), then:

```bash
git commit -m "feat(sensors): sensor-less observers see the sensorless_range_gu dial (2000 GU), not 30000"
```

---

### Task 3: Cap the cloak bubble with `cloak_bubble_cap_gu` (default 30 GU)

**Files:**
- Modify: `engine/appc/sensor_dials.py`
- Modify: `engine/appc/sensor_detection.py` (`can_detect` cloak term, ~line 210; the `ENHANCED_SENSOR_CONTEST` comment block item (1) and the `CLOAK_DETECTION_BASE_GU` comment so both mention the cap; no sizes)
- Modify: `engine/appc/ai_sensor_gate.py:56-74` (the ⚠️ note)
- Modify: `tests/helpers/cloak_geometry.py` (`bubble_gu`)
- Test: `tests/unit/test_cloak_detection_contest.py`, `tests/unit/test_sensor_dials.py`

**Interfaces:**
- Consumes: Task 2's `sensorless_gu()` helper and dial pattern.
- Produces: dial `"cloak_bubble_cap_gu"`; `cloak_geometry.bubble_gu(effective_range_gu)` now returns `min(cap, BASE + r × FACTOR)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sensor_dials.py`:

```python
def test_cloak_bubble_cap_dial_default_step_and_floor():
    sensor_dials.reset()
    assert sensor_dials.get("cloak_bubble_cap_gu") == 30.0
    d = dict(sensor_dials.DEFAULTS)
    assert sensor_dials.step(d, "cloak_bubble_cap_gu", -1)["cloak_bubble_cap_gu"] == 29.0
    low = dict(d, cloak_bubble_cap_gu=1.0)
    assert sensor_dials.step(low, "cloak_bubble_cap_gu", -1)["cloak_bubble_cap_gu"] == 1.0
```

And update the `set(DIAL_ORDER[3:])` assertion to include `"cloak_bubble_cap_gu"`.

Append a "CAP" section to `tests/unit/test_cloak_detection_contest.py`. The file's helpers are `_observer(base_range=2000.0, condition=100.0)` (Galaxy at the origin with a real `SensorSubsystem`) and `_target(x, cloaked=False, mid_cloak=False)`. First extend `_observer` with a `power=1.0` keyword that sets `sensors._power_factor = power` (the idiom `tests/unit/test_sensor_reach.py:131` uses), and fix its docstring so it no longer says "FALLBACK_RANGE_GU (30000), fifteen times a Galaxy's real reach" (say "the `sensorless_range_gu` dial"). Keep every distance derived from the constants and the dial:

```python
# ── CAP (sub-project 5, Mark's ruling B 2026-10-08) ──────────────────────────
# A station must not out-reach your phasers: the bubble never exceeds the
# cloak_bubble_cap_gu dial, for any observer, at any power.
from engine.appc import sensor_dials as _sd_dials

_STATION_GU = 12000.0   # fedstarbase's authored BaseSensorRange


def _uncapped(r):
    return sd.CLOAK_DETECTION_BASE_GU + r * sd.CLOAK_RANGE_FACTOR


def test_the_station_case_really_exceeds_the_cap():
    """Anti-vacuity: without the cap this observer's bubble is bigger."""
    assert _uncapped(_STATION_GU) > _sd_dials.get("cloak_bubble_cap_gu")


def test_a_high_range_observer_is_capped():
    cap = _sd_dials.get("cloak_bubble_cap_gu")
    obs = _observer(_STATION_GU)
    assert sd.can_detect(obs, _target(cap * 0.9, cloaked=True)) is True
    between = (cap + _uncapped(_STATION_GU)) / 2.0
    assert sd.can_detect(obs, _target(between, cloaked=True)) is False


def test_over_boost_cannot_push_past_the_cap():
    cap = _sd_dials.get("cloak_bubble_cap_gu")
    obs = _observer(_STATION_GU, power=1.25)
    assert sd.can_detect(obs, _target(cap * 1.1, cloaked=True)) is False


def test_offline_sensors_see_no_cloaked_ship_even_inside_the_cap():
    cap = _sd_dials.get("cloak_bubble_cap_gu")
    obs = _observer(_STATION_GU, condition=0.0)
    assert sd.can_detect(obs, _target(cap * 0.1, cloaked=True)) is False


def test_the_cap_is_read_at_use(monkeypatch):
    obs = _observer(_STATION_GU)
    t = _target(20.0, cloaked=True)
    monkeypatch.setitem(_sd_dials._dials, "cloak_bubble_cap_gu", 25.0)
    assert sd.can_detect(obs, t) is True
    monkeypatch.setitem(_sd_dials._dials, "cloak_bubble_cap_gu", 15.0)
    assert sd.can_detect(obs, t) is False


def test_a_galaxy_is_below_the_cap():
    """The cap bites only observers whose uncapped bubble exceeds it; a
    Galaxy's bubble is unchanged."""
    assert _uncapped(2000.0) < _sd_dials.get("cloak_bubble_cap_gu")
```

Also add, near the existing "AI ACQUISITION" tests in the same file:

```python
def test_a_station_does_not_acquire_a_cloaked_contact_beyond_the_cap():
    cap = _sd_dials.get("cloak_bubble_cap_gu")
    between = (cap + _uncapped(_STATION_GU)) / 2.0
    cloaked = _target(between, cloaked=True)
    assert _candidates(_observer(_STATION_GU), [cloaked]) == ()
```

If a "power=1.25" observer would also trip the over-boost reach (`overboost_threshold` 1.2): over-boost never reaches a fully cloaked target (`_beyond_range_reach` returns False when `cloaked`), so the assertion still tests the cap. Leave a one-line comment saying so.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_dials.py tests/unit/test_cloak_detection_contest.py -q`
Expected: the cap tests FAIL (KeyError, or detected beyond the cap); `test_the_station_case_really_exceeds_the_cap` and `test_a_galaxy_is_below_the_cap` fail only on the KeyError.

- [ ] **Step 3: Add the dial**

In `engine/appc/sensor_dials.py` `DEFAULTS`, after `sensorless_range_gu`:

```python
    "cloak_bubble_cap_gu": 30.0,      # the cloak bubble never exceeds this, for any observer
```

Add `"cloak_bubble_cap_gu": 1.0` to `_STEP` and `_MIN`. Extend the docstring sentence from Task 2 to cover both dials.

- [ ] **Step 4: Apply the cap in `can_detect`**

In `engine/appc/sensor_detection.py`, change

```python
    if cloaked:
        r = CLOAK_DETECTION_BASE_GU + r * CLOAK_RANGE_FACTOR
```

to

```python
    if cloaked:
        # Capped (sub-project 5, Mark's ruling 2026-10-08): a station must
        # not out-reach your phasers. Applied after condition/power scaling,
        # so over-boost cannot exceed it either.
        from engine.appc import sensor_dials
        r = min(sensor_dials.get("cloak_bubble_cap_gu"),
                CLOAK_DETECTION_BASE_GU + r * CLOAK_RANGE_FACTOR)
```

In the `ENHANCED_SENSOR_CONTEST` block, item (1): after the bubble formula line add `capped at the cloak_bubble_cap_gu dial (sensor_dials) so no observer -- in practice the big stations -- out-reaches a phaser.`. Replace the sentence about "cutting the factor is the lever that shrinks the oversized station bubbles" with "the cap is what bounds the station bubbles". In the `CLOAK_DETECTION_BASE_GU` comment, change the "Compute it:" formula line to `bubble = min(cap, BASE + effective_sensor_range * FACTOR)`. State no sizes.

- [ ] **Step 5: Update the helper**

In `tests/helpers/cloak_geometry.py` `bubble_gu`:

```python
def bubble_gu(effective_range_gu=GALAXY_SENSOR_GU):
    """Cloak bubble radius in GU for an observer with *effective_range_gu*.

    Mirrors `can_detect`'s cloak term exactly, including the
    `cloak_bubble_cap_gu` dial. The argument is EFFECTIVE range (post sensor
    condition and power), not the authored base range -- at full condition
    they coincide."""
    from engine.appc import sensor_dials
    return min(sensor_dials.get("cloak_bubble_cap_gu"),
               sd.CLOAK_DETECTION_BASE_GU
               + effective_range_gu * sd.CLOAK_RANGE_FACTOR)
```

Update the module docstring's formula line the same way.

- [ ] **Step 6: Rewrite the ⚠️ note in `ai_sensor_gate.py`**

Keep the first part (the two publishers differ about cloak; StarbaseAttack has no skip, so stations do acquire cloaked ships inside their bubble). Replace everything from "The bubble is CLOAK_DETECTION_BASE_GU plus..." through "deliberately NOT clamped here." with:

```python
# only. The bubble is CLOAK_DETECTION_BASE_GU plus CLOAK_RANGE_FACTOR of the
# observer's effective range, capped by the cloak_bubble_cap_gu dial
# (sensor_dials; Mark's ruling 2026-10-08) so a station never out-reaches a
# phaser. Only the biggest stations (fedstarbase, fedoutpost, cardfacility)
# reach the cap at normal power. Compute figures from the constants and the
# dial; they are deliberately NOT restated here.
```

Also update the matching paragraph in `tests/unit/test_cloak_detection_contest.py` (~lines 160-173): drop the "18 of 52 ... 30000" clause and "Whether they are right is a TUNING question", and say the cap now bounds them (Mark, 2026-10-08).

- [ ] **Step 7: Run the cloak and sensor suites, then the full pytest suite**

Run: `uv run pytest tests/unit -q -k "cloak or sensor or perceiv or select_target or phaser or torpedo"` → all PASS.
Run: `scripts/run_tests.sh -q` → 0 failures, 0 errors.
If a test now fails because its observer has a high range and it probes a derived "outside" distance that lies past the cap: it already reads `bubble_gu`, so it should follow automatically. If it hard-codes a distance, apply Task 2's pattern (derive, or keep the literal and `assert_inside`/`assert_outside`).

- [ ] **Step 8: Commit**

Stage the changed files by explicit path, then:

```bash
git commit -m "feat(sensors): cap the cloak bubble with the cloak_bubble_cap_gu dial (30 GU)"
```

---

### Task 4: Docs and the gate

**Files:**
- Modify: `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md`
- Modify: `CLAUDE.md` ("Sensor tiers" row, line ~70)
- Modify: `docs/superpowers/specs/2026-10-08-sensor-debts-design.md` (append "As built")

- [ ] **Step 1: Roadmap**

In "Later / parked", replace the bullet's first item `` `FALLBACK_RANGE_GU = 30000` (18 of 52 hardpoints author no sensor range); station cloak bubbles; `` with `` ~~`FALLBACK_RANGE_GU = 30000`~~ and ~~station cloak bubbles~~ — paid by sub-project 5 (only 10 stock hardpoints author no sensors: 8 rocks plus commarray and commlight; 7 more author no `SetBaseSensorRange` but inherit a parent's); ``. Keep the nebula clamp item. In the Sub-projects table, row 5: Status → `built on feat/sensor-debts, not merged — spec: 2026-10-08-sensor-debts-design.md`.

- [ ] **Step 2: CLAUDE.md**

In the "Sensor tiers" row, after the `SP3/SP4: ...` sentence, add: `SP5: \`ForceObjectIdentified\` is player-only; sensor-less observers (CommArray/CommLight) see the \`sensorless_range_gu\` dial (2000 GU), and the cloak bubble is capped by \`cloak_bubble_cap_gu\` (30 GU) — spec \`2026-10-08-sensor-debts-design.md\`.` Name no bubble sizes.

- [ ] **Step 3: Spec "As built"**

Append an `## As built` section to the spec listing the commits from Tasks 1-3 (`git log --oneline main..HEAD`) and any deviation from this plan, with the reason. If there was none, write "No deviations."

- [ ] **Step 4: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. If it names a failure, reproduce it on local main in the main checkout before calling it unrelated; never add a line to `tests/known_failures.txt`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md CLAUDE.md docs/superpowers/specs/2026-10-08-sensor-debts-design.md
git commit -m "docs(sensors): sub-project 5 roadmap, CLAUDE.md and as-built"
```
