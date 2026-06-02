# Target list health bars — design

Status: approved 2026-06-02
Scope: UI consumer fix downstream of the combat damage pipeline arc
(2026-06-01 → 2026-06-02). Sits below Projects 1-5; touches no pipeline
code.

## Problem

The target list panel in `engine/ui/target_list_view.py` renders a hull
bar and a shield bar next to each enemy row, and a bulleted list of
named subsystem children when a row is expanded. Two issues:

1. **Hull and shield bars look empty even on full-health targets**, and
   never visibly change as a target takes damage.
2. **Subsystem children render as a name-only bulleted list** — no
   health indicator.

## Root cause — Issue 1

Both `_query_hull_percentage` and `_query_shield_percentage` round the
return of `GetConditionPercentage()` / `GetShieldPercentage()` to an
integer. Those getters return a ratio in `[0.0, 1.0]`, not a percent in
`[0, 100]`:

- `engine/appc/subsystems.py:526-529` — `GetConditionPercentage`
  returns `self._condition / self._max_condition`.
- Shield getter follows the same ratio convention.

So a full-health hull is rounded to `1`, the JS sets
`--bar-pct: 1%`, and the rendered bar is invisibly thin. Confirmed by
diffing the working ShipDisplay panel: `ship_display_panel.py:_hull_pct`
returns the raw ratio and `ship_display.js` multiplies by 100 at render
time. Target list committed to the "integer percent at Python boundary"
style and just dropped the `* 100`.

## Root cause — Issue 2

`_snapshot` carries each subsystem as a label string only
(`engine/ui/target_list_view.py:114-117`), so the JS at
`native/assets/ui-cef/js/target_list.js:105-118` has no condition data
to render and emits a bullet + name only.

## Fix

### Issue 1 — multiply by 100

`engine/ui/target_list_view.py`:

- Line 40: `int(round(hull.GetConditionPercentage() * 100))`
- Line 70: `int(round(shields.GetShieldPercentage() * 100))`

Defensive zero/exception fallbacks unchanged. The integer-percent
convention stays — Issue 2 reuses it.

### Issue 2 — per-subsystem condition through the snapshot

**Convention chosen:** `GetCombinedConditionPercentage()` with a
`getattr` fallback to `GetConditionPercentage()`. The combined getter
matches stock BC's tactical readout: it rolls up child condition for
parent weapon systems, so a "Weapons" row reflects the aggregate of its
phaser banks. In current `engine/appc/subsystems.py:531-534` the
combined call collapses to `GetConditionPercentage` (no parent
override yet), but once a Project-2 override lands the same code path
surfaces the aggregate without further change.

**Python (`engine/ui/target_list_view.py`):**

In the snapshot loop around line 114-117, resolve each subsystem's
live object via the existing `_resolve_subsystem_by_name(ship, name)`
helper (line 45 — was added for the click-target path) and read its
condition. Subsystems entry becomes a tuple of `(name, condition_pct)`
pairs instead of bare strings:

```python
subsystems = tuple(
    (sub_child.GetLabel(), _query_subsystem_condition(ship, sub_child.GetLabel()))
    for sub_child in child._children
)
```

New helper `_query_subsystem_condition(ship, name) -> int` mirrors the
hull/shield helpers:

- Resolves the subsystem via `_resolve_subsystem_by_name`.
- Calls `GetCombinedConditionPercentage` if present, else
  `GetConditionPercentage`.
- Returns `int(round(value * 100))`.
- Returns `100` on any failure (subsystem missing, getter raises) —
  defensive default that avoids drawing a misleadingly empty bar
  during a transient resolution miss.

JSON serialiser at line 152-163 emits the new shape:

```python
"subsystems": [{"name": s_name, "condition": s_cond} for (s_name, s_cond) in subs],
```

**JS (`native/assets/ui-cef/js/target_list.js`):**

In the `if (expanded)` branch around line 105-118, each subsystem row
gets an extra `target-list__sub-bar` span next to the name with
`style="--bar-pct: <condition>%"`. Defensive fallback
`(typeof sub.condition === 'number') ? sub.condition : 100`, matching
the hull-row pattern at line 74.

Markup shape:

```html
<div class="target-list__sub …" onclick="…">
  <span class="target-list__sub-bullet">•</span>
  <span class="target-list__sub-name">Engineering</span>
  <span class="target-list__sub-bar" style="--bar-pct: 75%"></span>
</div>
```

**CSS (`native/assets/ui-cef/css/target_list.css`):**

New `.target-list__sub-bar` rule mirroring `.target-list__bar`
(`::after` fill, same `--bar-fill: rgb(255, 200, 60)` hull-yellow
token) but scaled smaller — 24 px × 6 px — so it fits the indented
sub-row. The `.target-list__sub-name` keeps `flex: 1 1 auto` so the
bar lands at the right edge of the row, paralleling the layout on
ship rows.

```css
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

## Tests

Added to `tests/unit/test_target_list_view.py`:

1. Hull at 50% condition → snapshot `hull` == `50`.
2. Shields at 100% → snapshot `shields` == `100`.
3. Subsystem at 75% → snapshot subsystem entry `condition` == `75`.
4. Parent weapon system with mixed-condition children →
   snapshot condition equals `GetCombinedConditionPercentage`
   aggregate. Validates the call path; once Project 2's parent
   aggregation override lands the same test asserts the rolled-up
   value.
5. Subsystem-resolution miss (helper returns `None`) → entry still
   rendered with `condition` == `100`, no exception.

## Visual smoke

`cmake -B build -S . && cmake --build build -j && ./build/dauntless`.
Target an enemy ship: hull and shield bars start full, drop visibly
under sustained phaser fire. Expand the row: each subsystem child has
its own bar; sustained fire after shields drop drains the bars of
whichever subsystem absorbs the hit.

## Out of scope

- ShipDisplay panel (no snapshot or style changes).
- Combat damage pipeline (Projects 1-5).
- Restructuring the snapshot to push ratios out + multiply in JS.
- Severity/state colour tinting (red when disabled, flash on hit).
- Shields-per-face bars in the expanded view (goes via ShipDisplay).

## Risks

Snapshot tuple shape changes once (rows now carry `(name, condition)`
pairs instead of bare strings). The existing
`if snapshot == self._last_snapshot` equality check still works because
tuples compare element-wise; first emit after the change is
unconditional, then back to delta-only.
