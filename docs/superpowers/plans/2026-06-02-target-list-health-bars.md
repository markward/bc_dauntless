# Target list health bars — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the empty-looking hull/shield bars on the target list panel and add per-subsystem health bars on expanded rows.

**Architecture:** Pure UI-consumer fix. Python snapshot multiplies condition ratios by 100 at the boundary (existing convention), carries a `(name, condition)` pair per subsystem, and the JS/CSS render a small bar next to each subsystem name. No changes to the combat damage pipeline or ShipDisplay panel.

**Tech Stack:** Python 3 (engine), CEF/Chromium (UI host), vanilla JS, CSS. Tests via `pytest`. Visual smoke via `cmake` + `./build/dauntless`.

**Spec:** `docs/superpowers/specs/2026-06-02-target-list-health-bars-design.md`

---

## Task 1: Feature branch

**Files:** none (git operations only)

- [ ] **Step 1: Confirm clean working tree on main**

Run: `git status`
Expected: `On branch main`, `nothing to commit, working tree clean` (the spec commit `81239fc` is already on main).

- [ ] **Step 2: Create the feature branch**

Run: `git checkout -b feature/target-list-health-bars`
Expected: `Switched to a new branch 'feature/target-list-health-bars'`

Why a feature branch: CLAUDE.md project convention — "New work goes on a feature branch off main." Brief also says: one branch, one merge.

---

## Task 2: Hull percent fix (Issue 1, part 1)

**Files:**
- Modify: `engine/ui/target_list_view.py:40`
- Test: `tests/unit/test_target_list_view.py` (add new case)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_list_view.py`:

```python
# ── Health-bar percent encoding (Issue 1) ────────────────────────────────────

def _make_targeted_ship(name="USS Galaxy"):
    """Build a ShipClass via ShipClass_Create, register it as the player's
    target, and return it. Caller is responsible for tearing the game
    down via _set_current_game(None)."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.sets import SetClass
    ship = ShipClass_Create("Galaxy")
    ship.SetName(name)
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        bridge = SetClass()
        App.g_kSetManager.AddSet(bridge, "bridge")
    bridge.AddObjectToSet(ship, name)
    return ship


def test_view_payload_hull_pct_is_integer_percent_not_ratio():
    """A hull at 50% condition must report hull == 50 (not 0 or 1).
    Regression test for the missing * 100 — GetConditionPercentage
    returns [0.0, 1.0]."""
    from engine.ui.target_list_view import TargetListView

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("Half-hull")
        hull = ship.GetHull()
        hull.SetMaxCondition(1000.0)
        hull.SetCondition(500.0)
        target_menu.RebuildShipMenu(ship)

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        row = next(r for r in state["rows"] if r["name"] == "Half-hull")
        assert row["hull"] == 50
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_view_payload_hull_pct_is_integer_percent_not_ratio -v`
Expected: FAIL with `assert 1 == 50` (current code rounds 0.5 to 0 or 1.0 to 1; here 0.5 rounds to 0 — either way it's not 50).

⚠️ Important: never run `uv run pytest` against the whole suite — it OOMs the host at >100 GB RAM. Always scope to the file.

- [ ] **Step 3: Fix the helper**

In [engine/ui/target_list_view.py:40](engine/ui/target_list_view.py#L40), change:

```python
        return int(round(hull.GetConditionPercentage()))
```

to:

```python
        return int(round(hull.GetConditionPercentage() * 100))
```

- [ ] **Step 4: Re-run, confirm pass**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_view_payload_hull_pct_is_integer_percent_not_ratio -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_target_list_view.py engine/ui/target_list_view.py
git commit -m "$(cat <<'EOF'
fix(target_list): hull bar shows real percent, not raw ratio

GetConditionPercentage returns [0.0, 1.0]. The helper was rounding
that to 0 or 1 and emitting --bar-pct: 1%, producing an invisible
bar even at full health. Multiply by 100 to match the integer-percent
convention the JS expects.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Shield percent fix (Issue 1, part 2)

**Files:**
- Modify: `engine/ui/target_list_view.py:70`
- Test: `tests/unit/test_target_list_view.py` (add new case)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_list_view.py`:

```python
def test_view_payload_shield_pct_is_integer_percent_not_ratio():
    """A fully-shielded ship must report shields == 100 (not 1).
    Regression test for the missing * 100."""
    from engine.ui.target_list_view import TargetListView
    from engine.appc.subsystems import ShieldSubsystem

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("Full-shields")
        shields = ship.GetShields()
        # Seed all six faces; SetMaxShields seeds current when current==0.
        for face in range(ShieldSubsystem.NUM_SHIELDS):
            shields.SetMaxShields(face, 1000.0)
        target_menu.RebuildShipMenu(ship)

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        row = next(r for r in state["rows"] if r["name"] == "Full-shields")
        assert row["shields"] == 100
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_view_payload_shield_pct_is_integer_percent_not_ratio -v`
Expected: FAIL with `assert 1 == 100`.

- [ ] **Step 3: Fix the helper**

In [engine/ui/target_list_view.py:70](engine/ui/target_list_view.py#L70), change:

```python
        return int(round(shields.GetShieldPercentage()))
```

to:

```python
        return int(round(shields.GetShieldPercentage() * 100))
```

- [ ] **Step 4: Re-run, confirm pass**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_view_payload_shield_pct_is_integer_percent_not_ratio -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_target_list_view.py engine/ui/target_list_view.py
git commit -m "$(cat <<'EOF'
fix(target_list): shield bar shows real percent, not raw ratio

Same bug as the hull-bar fix in the previous commit — multiply by
100 at the Python boundary so --bar-pct lands in the [0, 100] range
the CSS expects.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Per-subsystem condition helper + snapshot extension

**Files:**
- Modify: `engine/ui/target_list_view.py` (add `_query_subsystem_condition`, extend snapshot tuple + JSON)
- Test: `tests/unit/test_target_list_view.py` (add new case)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_list_view.py`:

```python
# ── Per-subsystem condition (Issue 2) ────────────────────────────────────────

def test_view_payload_subsystems_carry_condition_pct():
    """Each subsystem entry in the snapshot includes a `condition`
    integer percent reflecting its live condition."""
    from engine.ui.target_list_view import TargetListView

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("USS Galaxy")
        # Drop the first subsystem on the ship to 75% condition.
        it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        first_sub = ship.GetNextSubsystemMatch(it)
        ship.EndGetSubsystemMatch(it)
        first_sub.SetMaxCondition(400.0)
        first_sub.SetCondition(300.0)
        damaged_name = first_sub.GetName()

        target_menu.RebuildShipMenu(ship)
        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)

        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")
        damaged_entry = next(s for s in row["subsystems"] if s["name"] == damaged_name)
        assert damaged_entry["condition"] == 75
        # Untouched subsystems stay at 100%.
        for entry in row["subsystems"]:
            assert "condition" in entry
            assert 0 <= entry["condition"] <= 100
            if entry["name"] != damaged_name:
                assert entry["condition"] == 100
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_view_payload_subsystems_carry_condition_pct -v`
Expected: FAIL — `KeyError: 'condition'` (current payload emits only `{"name": ...}`).

- [ ] **Step 3: Add the helper**

In `engine/ui/target_list_view.py`, add this function immediately after `_query_shield_percentage` (after the current line 72, before the `class TargetListView` declaration):

```python
def _query_subsystem_condition(ship, name: str) -> int:
    """Return the named subsystem's condition as an integer percentage
    0-100. Prefers GetCombinedConditionPercentage so parent weapon
    systems reflect aggregated child condition; falls back to
    GetConditionPercentage when the combined variant is absent.

    Defaults to 100 on any failure (subsystem missing, getter raises)
    so a transient resolution miss draws a full bar rather than an
    empty one."""
    if ship is None or not name:
        return 100
    sub = _resolve_subsystem_by_name(ship, name)
    if sub is None:
        return 100
    getter = getattr(sub, "GetCombinedConditionPercentage", None)
    if getter is None:
        getter = getattr(sub, "GetConditionPercentage", None)
    if getter is None:
        return 100
    try:
        return int(round(getter() * 100))
    except Exception:
        return 100
```

- [ ] **Step 4: Extend the snapshot loop**

In `engine/ui/target_list_view.py`, find the snapshot loop (currently lines 114-117):

```python
                    subsystems = tuple(
                        sub_child.GetLabel()
                        for sub_child in child._children
                    )
```

Replace with:

```python
                    subsystems = tuple(
                        (sub_child.GetLabel(),
                         _query_subsystem_condition(ship, sub_child.GetLabel()))
                        for sub_child in child._children
                    )
```

- [ ] **Step 5: Update the JSON serialiser**

In `engine/ui/target_list_view.py`, find the JSON building list comprehension (currently line 157):

```python
                    "subsystems": [{"name": s} for s in subs],
```

Replace with:

```python
                    "subsystems": [{"name": s_name, "condition": s_cond}
                                   for (s_name, s_cond) in subs],
```

- [ ] **Step 6: Run the new test, confirm pass**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_view_payload_subsystems_carry_condition_pct -v`
Expected: 1 passed.

- [ ] **Step 7: Run the full target-list test file, confirm all pass**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: all tests pass, including the pre-existing
`test_view_payload_includes_subsystems_and_health` (it only checks the `name` key, so it stays green).

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_target_list_view.py engine/ui/target_list_view.py
git commit -m "$(cat <<'EOF'
feat(target_list): carry per-subsystem condition in the snapshot

Each subsystem entry now serialises as {name, condition}. The new
_query_subsystem_condition helper prefers GetCombinedConditionPercentage
so parent weapon systems reflect aggregated child condition once the
Project-2 override lands; falls back to GetConditionPercentage today.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Combined-condition preference + resolution-miss fallback

**Files:**
- Test only: `tests/unit/test_target_list_view.py`

These test the contract of `_query_subsystem_condition` directly so the helper's behaviour is locked even if no parent-aggregating subsystem exists in current code.

- [ ] **Step 1: Add the combined-preference test**

Append to `tests/unit/test_target_list_view.py`:

```python
def test_query_subsystem_condition_prefers_combined_over_individual():
    """When a subsystem exposes GetCombinedConditionPercentage, the
    helper uses it (so future parent-weapon aggregation surfaces in
    the panel). When only GetConditionPercentage exists, it falls back."""
    from engine.ui.target_list_view import _query_subsystem_condition

    class FakeWeapons:
        def GetName(self): return "Weapons"
        def GetConditionPercentage(self): return 1.0
        def GetCombinedConditionPercentage(self): return 0.4  # aggregate with damaged children

    class FakeShip:
        def __init__(self, sub): self._sub = sub
        def StartGetSubsystemMatch(self, _ct): return iter([self._sub])
        def GetNextSubsystemMatch(self, it):
            try: return next(it)
            except StopIteration: return None
        def EndGetSubsystemMatch(self, _it): pass

    aggregated = FakeWeapons()
    assert _query_subsystem_condition(FakeShip(aggregated), "Weapons") == 40

    class FakeImpulse:
        def GetName(self): return "Impulse"
        def GetConditionPercentage(self): return 0.6
        # no GetCombinedConditionPercentage

    flat = FakeImpulse()
    assert _query_subsystem_condition(FakeShip(flat), "Impulse") == 60


def test_query_subsystem_condition_defaults_to_100_when_resolution_misses():
    """If the subsystem can't be found on the ship, default to 100 so
    the bar renders full rather than misleadingly empty."""
    from engine.ui.target_list_view import _query_subsystem_condition

    class EmptyShip:
        def StartGetSubsystemMatch(self, _ct): return iter([])
        def GetNextSubsystemMatch(self, it):
            try: return next(it)
            except StopIteration: return None
        def EndGetSubsystemMatch(self, _it): pass

    assert _query_subsystem_condition(EmptyShip(), "Phantom") == 100
    assert _query_subsystem_condition(None, "Anything") == 100
    assert _query_subsystem_condition(EmptyShip(), "") == 100
```

- [ ] **Step 2: Run both tests, confirm pass**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_query_subsystem_condition_prefers_combined_over_individual tests/unit/test_target_list_view.py::test_query_subsystem_condition_defaults_to_100_when_resolution_misses -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_target_list_view.py
git commit -m "$(cat <<'EOF'
test(target_list): lock combined-vs-individual preference and miss fallback

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Render subsystem bars in JS

**Files:**
- Modify: `native/assets/ui-cef/js/target_list.js:103-119`

Tests for the JS layer are visual-smoke only — this is a markup change inside a CEF-rendered panel.

- [ ] **Step 1: Update the subsystem-row builder**

In `native/assets/ui-cef/js/target_list.js`, find the `if (expanded)` block (currently lines 105-119):

```javascript
        if (expanded) {
            const subs = row.subsystems || [];
            for (let j = 0; j < subs.length; j++) {
                const sub = subs[j];
                const subName = String(sub.name || '');
                const subChosen = (selected === name && selectedSub === subName)
                    ? ' target-list__sub--chosen' : '';
                const subAttr = clickAttr('target/' + name + '/' + subName);
                html += '<div class="target-list__sub target-list__sub--' + aff + subChosen + '"'
                      +   ' onclick="' + subAttr + '">'
                      +   '<span class="target-list__sub-bullet">&#8226;</span>'
                      +   '<span class="target-list__sub-name">' + escapeHtml(subName) + '</span>'
                      + '</div>';
            }
        }
```

Replace with:

```javascript
        if (expanded) {
            const subs = row.subsystems || [];
            for (let j = 0; j < subs.length; j++) {
                const sub = subs[j];
                const subName = String(sub.name || '');
                const subCondition = (typeof sub.condition === 'number') ? sub.condition : 100;
                const subChosen = (selected === name && selectedSub === subName)
                    ? ' target-list__sub--chosen' : '';
                const subAttr = clickAttr('target/' + name + '/' + subName);
                html += '<div class="target-list__sub target-list__sub--' + aff + subChosen + '"'
                      +   ' onclick="' + subAttr + '">'
                      +   '<span class="target-list__sub-bullet">&#8226;</span>'
                      +   '<span class="target-list__sub-name">' + escapeHtml(subName) + '</span>'
                      +   '<span class="target-list__sub-bar"'
                      +   ' style="--bar-pct:' + subCondition + '%"></span>'
                      + '</div>';
            }
        }
```

- [ ] **Step 2: Commit**

```bash
git add native/assets/ui-cef/js/target_list.js
git commit -m "$(cat <<'EOF'
feat(target_list): render per-subsystem health bar in expanded rows

Each subsystem now emits a target-list__sub-bar span next to the name,
driven by the condition value carried in the snapshot. Defensive
fallback to 100% when the value is absent or non-numeric.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Subsystem bar styling

**Files:**
- Modify: `native/assets/ui-cef/css/target_list.css` (append new rule)

- [ ] **Step 1: Add the `.target-list__sub-bar` rule**

Append to `native/assets/ui-cef/css/target_list.css`:

```css
/* ── Subsystem health bar (small) ─────────────────────────────────── */
.target-list__sub-bar {
    --bar-pct: 0%;
    --bar-fill: rgb(255, 200, 60);
    width: 24px;
    height: 6px;
    background: rgba(40, 40, 40, 0.6);
    position: relative;
    margin-left: 6px;
}

.target-list__sub-bar::after {
    content: "";
    display: block;
    height: 100%;
    width: var(--bar-pct);
    background: var(--bar-fill);
    transition: width 120ms linear;
}
```

Mirror of `.target-list__bar` scaled down (24×6 vs 32×8) so it fits the indented sub-row. Same hull-yellow `rgb(255, 200, 60)` token; only one bar (condition only — no shield equivalent at the subsystem level).

- [ ] **Step 2: Commit**

```bash
git add native/assets/ui-cef/css/target_list.css
git commit -m "$(cat <<'EOF'
style(target_list): add .target-list__sub-bar rule for subsystem health

Scaled-down mirror of .target-list__bar (24x6 instead of 32x8) with
the same hull-yellow fill, sitting at the right edge of each
indented sub-row.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Full target-list test sweep + targeted neighbours

**Files:** none — verification only

- [ ] **Step 1: Run the full target_list_view test file**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: all tests pass (the four pre-existing tests + the five new ones from Tasks 2-5).

- [ ] **Step 2: Run nearby test files that exercise the same code paths**

Run: `uv run pytest tests/unit/test_target_menu_shim.py tests/unit/test_target_menu_bridge_subscription.py tests/unit/test_sensors_disabled_blanks_target_ui.py -v`
Expected: all pass — these touch `STSubsystemMenu` / `TargetListView` adjacent code and would catch any unintended snapshot regressions.

⚠️ Do NOT run `uv run pytest` against the whole project — it OOMs the host. Only run the listed files.

- [ ] **Step 3: If anything fails, stop and fix before continuing**

Common failure mode: a pre-existing test that asserts on the old subsystem entry shape (`{"name": s}` only). The replacement is compatible — `"name"` still exists — but if any test asserts the dict's `len == 1` or compares against `{"name": "X"}` exactly, update it to check the `name` key only.

---

## Task 9: Visual smoke

**Files:** none — build + run the game and observe

- [ ] **Step 1: Reconfigure + build**

Run from project root:

```bash
cmake -B build -S . && cmake --build build -j
```

Why reconfigure first: per memory `feedback_shader_rebuild.md`, shader/asset path changes are not picked up by `cmake --build` alone. CSS/JS in `native/assets/ui-cef/` are copied into the build by the configure step; reconfigure to be safe.

Expected: build completes with `[100%] Built target dauntless`.

- [ ] **Step 2: Launch the game**

Run: `./build/dauntless`
Expected: game launches into the default mission. If it crashes on launch, stop — that's a regression from the build, not the UI change.

- [ ] **Step 3: Verify ship-row bars**

Target an enemy ship (default tutorial mission or whichever loads). Observe:
- The hull bar on each row is **visibly filled** (yellow) and reflects the target's condition.
- The shield bar is **visibly filled** (purple) and reflects shield strength.

Open fire on the target with sustained phaser fire. Observe:
- The shield bar **drops first**, visibly shrinking.
- Once shields collapse, the hull bar starts draining.

- [ ] **Step 4: Verify per-subsystem bars**

Click the caret on a damaged enemy row to expand. Observe:
- Each subsystem child has a **small bar** at the right edge of its row.
- Bars start full (yellow) on an undamaged subsystem.
- After sustained fire with shields down, subsystem bars on the absorbing systems visibly shrink.

- [ ] **Step 5: Take a screenshot for the merge record**

Capture the panel with at least one row expanded and visibly damaged subsystems. Save it to your scratch directory (don't commit screenshots — they're not part of the working tree).

- [ ] **Step 6: If anything looks wrong**

If bars don't render or look broken, common causes:
- Stale CEF cache. Restart the game; CEF aggressively caches CSS.
- `--bar-pct` not applied. Inspect the DOM via the CEF dev tools (if exposed in this build) or check the JS via `grep "sub-bar" build/`-tree CSS to confirm the new asset shipped.
- Build picked up the wrong CSS. Confirm there's no parallel `native/build/` tree (per CLAUDE.md, that is forbidden — delete it if found and rebuild from `build/`).

Do not "fix" the issue by changing the damage pipeline or ShipDisplay. Those are out of scope. If the UI doesn't show what it should, the bug is in this branch's diff.

---

## Task 10: Merge to main

**Files:** none — git operations

- [ ] **Step 1: Confirm clean state**

Run: `git status`
Expected: `working tree clean` on `feature/target-list-health-bars`.

- [ ] **Step 2: Re-run the focused test file one more time before merge**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: all pass.

- [ ] **Step 3: Switch to main and merge**

```bash
git checkout main
git merge --no-ff feature/target-list-health-bars
```

`--no-ff` preserves the feature-branch boundary in the history — matches the project pattern from recent commits like `76580cb Merge feature/subsystem-failure-consequences into main`.

Pause here and confirm with the user before pushing or deleting the branch. Merge to main is shared-state; the brief asks the human to drive that step.
