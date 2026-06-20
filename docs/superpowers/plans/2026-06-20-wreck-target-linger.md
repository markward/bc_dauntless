# Selectable Wreck Linger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a destroyed ship selectable in the HUD target list as a wreck for 10 s (5 s death throes + 5 s linger) so the player can catch and watch the breach, then remove it.

**Architecture:** Split `ship_death`'s single-shot `_finish` into a two-phase sequence — a death-marker at the end of the 5 s throes (`SetDead` + `ET_OBJECT_DESTROYED`, hull stays in its set) and a final removal after a new 5 s linger (clear locks + remove from set). Expose `is_targetable_wreck(ship)`; the target-list view's filter keeps such ships listed.

**Tech Stack:** Python 3 (engine + UI layers), pytest. No native/C++ changes.

## Global Constraints

Copied verbatim from the spec — every task's requirements implicitly include these:

- **Engine/UI layers are modern Python 3** (the Python-1.5 constraint applies only to `tools/`).
- `THROES_DURATION` stays **5.0** (unchanged). New `WRECK_LINGER_DURATION = 5.0`.
- `ET_OBJECT_DESTROYED` and `ship_lifecycle.publish_destroyed` (fired by `SetDead`) must STILL occur at the **end of the throes (5 s)** — mission timing must not move.
- At final removal, `_clear_target_locks` must run **immediately before** `RemoveObjectFromSet` (both now at 10 s), so locks release while the handle is still in the set.
- This applies to **every** ship death, not only warp-core breaches.
- Run tests with `uv run pytest <path> -v`.

**Spec:** `docs/superpowers/specs/2026-06-20-wreck-target-linger-design.md`

---

### Task 1: Two-phase ship death + `is_targetable_wreck`

**Files:**
- Modify: `engine/appc/ship_death.py` (constant near line 16; `begin` line 52; replace `advance`+`_finish` lines 75–106; add `is_targetable_wreck`)
- Test: `tests/unit/test_ship_death.py` (update two existing tests, add new ones)

**Interfaces:**
- Produces: `ship_death.WRECK_LINGER_DURATION = 5.0`; `ship_death.is_targetable_wreck(ship) -> bool` (True while the ship is in the active death/linger registry). `begin`/`advance`/`reset` keep their existing signatures.
- The death-marker (`SetDead` + `ET_OBJECT_DESTROYED`) fires at `THROES_DURATION`; removal (`_clear_target_locks` + `RemoveObjectFromSet`) fires at `THROES_DURATION + WRECK_LINGER_DURATION`.

- [ ] **Step 1: Update the two existing tests that assume single-shot removal, and add the new behavior tests**

In `tests/unit/test_ship_death.py`, REPLACE the existing test `test_advance_transitions_to_dead_and_removes_after_throes` with the version below, REPLACE `test_entry_pruned_after_death` with the version below, and ADD the four new tests. (The `FakeShip`/`FakeSet` fixtures and the `_clean_registry` autouse fixture already exist in this file — reuse them.)

```python
def test_advance_marks_dead_at_throes_but_keeps_wreck_in_set():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)   # throes expire
    # Death-marker fired, but the wreck lingers — NOT removed yet.
    assert ship.IsDead() == 1
    assert s.removed == []
    assert ship_death.is_targetable_wreck(ship) is True


def test_advance_removes_wreck_after_throes_plus_linger():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)        # -> linger
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)  # linger expires
    assert s.removed == ["Doomed"]
    assert ship_death.is_targetable_wreck(ship) is False


def test_wreck_entry_pruned_after_final_removal():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)  # removed once
    s.removed.clear()
    ship_death.advance(1.0)   # entry pruned -> no second removal
    assert s.removed == []


def test_is_targetable_wreck_false_for_untracked_ship():
    ship = FakeShip()
    assert ship_death.is_targetable_wreck(ship) is False


def test_locks_clear_only_at_final_removal(monkeypatch):
    cleared = []
    monkeypatch.setattr(ship_death, "_clear_target_locks",
                        lambda s: cleared.append(s))
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)
    assert cleared == []                 # not cleared at throes end
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)
    assert cleared == [ship]             # cleared only at linger end


def test_destroyed_event_fires_at_throes_not_linger():
    import App
    seen = []
    orig = App.g_kEventManager.AddEvent

    def capture(evt):
        seen.append(evt.GetEventType())
        return orig(evt)
    App.g_kEventManager.AddEvent = capture
    try:
        ship = FakeShip()
        ship_death.begin(ship)
        ship_death.advance(ship_death.THROES_DURATION)
        assert App.ET_OBJECT_DESTROYED in seen   # fired at the 5s mark
        assert ship.IsDead() == 1
        assert ship._set.removed == []           # still in set (lingering)
    finally:
        App.g_kEventManager.AddEvent = orig
```

- [ ] **Step 2: Run the updated tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: the new/updated tests FAIL — `AttributeError: module 'engine.appc.ship_death' has no attribute 'WRECK_LINGER_DURATION'` (and `is_targetable_wreck`). The pre-existing unchanged tests still pass.

- [ ] **Step 3: Add the constant**

In `engine/appc/ship_death.py`, immediately after the `THROES_DURATION` line (line 16), add:

```python
WRECK_LINGER_DURATION = 5.0   # seconds a dead hull lingers, selectable in the
                              # target list, after the throes before removal
```

- [ ] **Step 4: Tag the registry entry with a phase in `begin`**

In `engine/appc/ship_death.py`, change the `_active.append(...)` line inside `begin` (line 52) from:

```python
    _active.append({"ship": ship, "time_left": THROES_DURATION})
```

to:

```python
    _active.append({"ship": ship, "phase": "throes", "time_left": THROES_DURATION})
```

- [ ] **Step 5: Replace `advance` and `_finish` with the two-phase version**

In `engine/appc/ship_death.py`, replace the entire `advance` function AND the entire `_finish` function (lines 75–106) with the following four functions:

```python
def advance(dt: float) -> None:
    """Tick every in-progress death sequence. A 'throes' entry that expires
    becomes a dead, still-selectable wreck (the death-marker fires, but the
    hull stays in its set and keeps its locks); a 'linger' entry that expires
    is finally removed. Only fully-removed entries are pruned."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        entry["time_left"] -= dt
        if entry["time_left"] > 0.0:
            survivors.append(entry)
            continue
        if entry["phase"] == "throes":
            _mark_dead(entry["ship"])
            entry["phase"] = "linger"
            entry["time_left"] = WRECK_LINGER_DURATION
            survivors.append(entry)          # wreck lingers, still selectable
        else:  # "linger"
            _remove(entry["ship"])           # pruned (not re-appended)
    _active[:] = survivors


def _mark_dead(ship) -> None:
    """End of throes: mark the ship dead and broadcast ET_OBJECT_DESTROYED so
    mission logic and ship_lifecycle.publish_destroyed (fired by SetDead) run
    on schedule. The hull stays in its set and keeps its target locks — it
    lingers as a selectable wreck for WRECK_LINGER_DURATION."""
    if hasattr(ship, "SetDead"):
        ship.SetDead()
    _broadcast_destroyed(ship)


def _remove(ship) -> None:
    """End of linger: release every lock held on the wreck, then remove it from
    its set. Order matters — locks clear while the handle is still in the set
    so firing ships drop their target pointers against a valid object."""
    _clear_target_locks(ship)
    try:
        pSet = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        if pSet is not None and hasattr(ship, "GetName"):
            pSet.RemoveObjectFromSet(ship.GetName())
    except Exception as _e:
        dev_mode.log_swallowed("remove dead ship from set", _e)


def is_targetable_wreck(ship) -> bool:
    """True while `ship` is in an in-progress death/linger sequence (dying or a
    dead wreck not yet removed). The HUD target list uses this to keep a
    destroyed ship selectable through the throes + linger window. Identity
    match against the active registry; no engine calls, so it is safe to call
    on any object."""
    return any(entry["ship"] is ship for entry in _active)
```

Leave `_broadcast_destroyed`, `_clear_target_locks`, `_spawn_explosion`, `begin`, `reset`, and `_out_of_action` otherwise unchanged. (The module docstring's mention of `_finish` is now stale but harmless; optionally update it.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: all tests PASS (the updated two, the four new, and every pre-existing unchanged test).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/ship_death.py tests/unit/test_ship_death.py
git commit -m "feat(death): two-phase death with selectable wreck linger

After the 5s throes the ship is marked dead + ET_OBJECT_DESTROYED fires (mission
timing unchanged) but the hull lingers in its set as a selectable wreck for
WRECK_LINGER_DURATION (5s) before locks clear and it is removed. Add
is_targetable_wreck() for the target-list filter.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Keep wrecks in the HUD target list

**Files:**
- Modify: `engine/ui/target_list_view.py:192,200-201` (`_snapshot` import + filter)
- Test: `tests/unit/test_target_list_view.py` (add one test)

**Interfaces:**
- Consumes: `ship_death.is_targetable_wreck(ship)` and `ship_death._out_of_action(ship)` (Task 1 / existing).
- Produces: nothing new — `_snapshot` now includes ships that are out of action but are still targetable wrecks.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_target_list_view.py`, add this test (reuses the existing `_setup_game_with_player` helper and `App` import already in the file):

```python
def test_destroyed_ship_lingers_in_list_then_drops_after_removal():
    """A ship in its death/linger window stays selectable in the target list;
    once ship_death finally removes it, it drops off."""
    import json
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass
    from engine.appc import ship_death

    ship_death.reset()
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        wreck = ShipClass(); wreck.SetName("Doomed")
        target_menu.RebuildShipMenu(wreck)

        # Enter the death sequence: now dying (out of action) but a wreck.
        ship_death.begin(wreck)
        view = TargetListView()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert "Doomed" in [r["name"] for r in state["rows"]]   # listed as a wreck

        # Run out the throes + linger -> final removal -> no longer a wreck.
        ship_death.advance(ship_death.THROES_DURATION)
        ship_death.advance(ship_death.WRECK_LINGER_DURATION)
        assert ship_death.is_targetable_wreck(wreck) is False
        state2 = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert "Doomed" not in [r["name"] for r in state2["rows"]]
    finally:
        ship_death.reset()
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_destroyed_ship_lingers_in_list_then_drops_after_removal -v`
Expected: FAIL on the first assertion — the current filter drops the dying ship, so `"Doomed"` is NOT in the rows.

- [ ] **Step 3: Update the filter to keep targetable wrecks**

In `engine/ui/target_list_view.py`, change the import line (currently line 192):

```python
        from engine.appc.ship_death import _out_of_action
```

to:

```python
        from engine.appc.ship_death import _out_of_action, is_targetable_wreck
```

Then change the filter condition (currently lines 200–201):

```python
                if ship is not None and ship is not player \
                        and not _out_of_action(ship):
```

to:

```python
                if ship is not None and ship is not player \
                        and (not _out_of_action(ship) or is_targetable_wreck(ship)):
```

Also update the comment immediately above it (lines 198–199) to:

```python
                # A living ship, or a destroyed ship still inside its wreck
                # linger window, is a valid target; a ship past final removal
                # is dropped.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_destroyed_ship_lingers_in_list_then_drops_after_removal -v`
Expected: PASS.

- [ ] **Step 5: Run the full target-list + ship-death test files**

Run: `uv run pytest tests/unit/test_target_list_view.py tests/unit/test_target_list_view_nested.py tests/unit/test_ship_death.py -v`
Expected: all PASS (no regression in the existing target-list behavior — living ships still listed, the player still excluded).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/target_list_view.py tests/unit/test_target_list_view.py
git commit -m "feat(hud): keep destroyed ships selectable as wrecks in the target list

The target-list filter now keeps a ship listed while it is a targetable wreck
(ship_death.is_targetable_wreck), so a destroyed ship stays selectable through
the throes + linger window instead of dropping off the instant it dies.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Selectable from moment of death through throes + 5 s linger (10 s) → Task 1 two-phase `advance` + Task 2 filter. ✓
- Death VFX/coast/throes unchanged (5 s) → `begin`/`THROES_DURATION`/`_spawn_explosion` untouched. ✓
- `ET_OBJECT_DESTROYED` + `publish_destroyed` still at 5 s → `_mark_dead` (via `SetDead`) at throes end; `test_destroyed_event_fires_at_throes_not_linger`. ✓
- Locks clear only at final removal (10 s), before set-removal → `_remove`; `test_locks_clear_only_at_final_removal`. ✓
- `is_targetable_wreck` predicate → Task 1; consumed in Task 2. ✓
- Filter keeps wrecks listed, drops after final removal → Task 2 + its test. ✓
- Applies to every death → the two-phase change is in the shared `advance` path, not breach-specific. ✓
- Wreck stays rendered (in set 10 s) → no renderer change needed; confirmed in spec. ✓
- Re-trigger safety (idempotent `begin`) → `begin`'s `_out_of_action` guard is unchanged. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". All steps carry complete code. ✓

**3. Type consistency:** `WRECK_LINGER_DURATION` and `is_targetable_wreck(ship) -> bool` are named identically in Task 1 (definition), Task 1 tests, and Task 2 (import + filter + test). `_mark_dead`/`_remove` are internal to Task 1 and referenced only by the `advance` defined in the same step. The entry dict gains `"phase"` in `begin` (Task 1 Step 4) and is read in `advance` (Task 1 Step 5) — consistent. Filter expression `not _out_of_action(ship) or is_targetable_wreck(ship)` matches the predicate's boolean return. ✓

**Note on a single large `advance(dt)`:** a `dt` overshooting both phases in one call advances only one phase per tick (linger restarts at its full duration). This is acceptable — production `dt` is ~1/60 s and the tests step phase-by-phase — and avoids modeling fractional carryover. No task depends on single-call double-transition.
