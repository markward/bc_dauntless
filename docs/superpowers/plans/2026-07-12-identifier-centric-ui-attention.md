# Identifier-centric UI Attention — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The real E1M1 Set Course tutorial highlights the real "Set Course" submenu row in Kiska's (Helm) CEF menu — by *identifier*, not by geometry.

**Architecture:** `MissionLib.ShowPointerArrow`/`HidePointerArrows` are overridden at boot (SDK file untouched). Instead of placing an LCARS icon at computed coordinates, they add/remove the target widget's **id** in an engine-held highlight set. `CrewMenuPanel`'s existing per-frame snapshot carries a `highlighted` flag per node; `crew_menus.js` adds a CSS class; CSS pulses. **No geometry, no measurement, no new channel.**

**Tech Stack:** Python 3 (engine), pytest + ctest (`scripts/check_tests.sh`), CEF (HTML/CSS/JS).

**Spec:** `docs/superpowers/specs/2026-07-12-identifier-centric-ui-attention-design.md`

## Global Constraints

- **No SDK edits.** `sdk/Build/scripts/` is read-only. We override `MissionLib.ShowPointerArrow`/`HidePointerArrows` **module attributes at boot** — a *renderer substitution*, not a logic fork. The SDK still decides what/when.
- **Persistent, NOT time-boxed.** Highlight on at `ShowPointerArrow`, off at `HidePointerArrows`. BC's arrow persists while the player still hasn't acted; a timed glow would extinguish the hint mid-task.
- **Honour the SDK's own gate:** `ShowPointerArrow` bails when `pUIObject is None` or `IsCompletelyVisible() == 0`. Preserve both.
- **The target is an STMenu (expandable submenu row)**, not a leaf STButton — `pKiskaMenu.GetSubmenuW("Set Course")`. The CSS class must apply to caret/expandable rows too.
- **Identifiers already exist:** `ensure_widget_id(widget)` → `wid`; `CrewMenuPanel._widgets_by_id[wid]`; snapshot nodes carry `{"id": wid}`; CEF rows dispatch `crew-menu/click:<id>`. Reuse this — do not invent a second id scheme.
- **Test gate:** `scripts/check_tests.sh` (pytest + ctest, diffed against `tests/known_failures.txt`).

## Context: what unblocked this

The SP-E MenuUp work on `main` (`522ad8cb` — `AT_MENU_UP`/`AT_MENU_DOWN` dispatch onto `CharacterClass.MenuUp/MenuDown`; `7c87ac07` — crew menus drop on the cutscene-START edge, not per-frame) fixed scripted menu-ups. `ExplainWarp` does Picard-menu-**down** → Kiska-menu-**up** → show arrow, inside a cutscene — so the arrow beat was previously unreachable. It is now reachable. **Rebase this branch onto current `main` before starting.**

---

### Task 1: Rebase onto main; delete the superseded arrow-geometry code

**Files:**
- Delete: `engine/ui/pointer_arrow_overlay.py`, `tests/ui/test_pointer_arrow_overlay.py`
- Delete: `engine/appc/pointer_arrows.py`, `tests/appc/test_pointer_arrows.py`
- Modify: `engine/appc/top_window.py` — remove `_arrow_placements` recording from `PrependChild`/`DeleteChild` (and the `icon._parent` back-ref if unused elsewhere)
- Modify: `engine/host_loop.py` — remove the `ArrowOverlayPusher` construction + per-frame arrow push
- Modify: `native/assets/ui-cef/index.html` — remove `<div id="pointer-arrows">`
- Modify: `native/assets/ui-cef/css/global.css` — remove `#pointer-arrows` + all `.arrow*` rules

**Interfaces:**
- Produces: a branch rebased on `main` with the arrow-geometry path gone. The **resolver + position push channel stay** (`engine/appc/tg_ui/layout.py`, the `TGPane` resolver, `engine/ui/sdk_panel_positions.py`, `resolve_officer_menu_layout`) — they serve SDK-driven *placement*, which is still needed.

- [ ] **Step 1: Rebase onto main**

```bash
git fetch && git rebase main
```
Resolve any conflicts (expect few — the SP-E work touched menus, we touched layout/CEF).

- [ ] **Step 2: Delete the arrow-geometry modules and their tests**

```bash
git rm engine/ui/pointer_arrow_overlay.py tests/ui/test_pointer_arrow_overlay.py \
       engine/appc/pointer_arrows.py tests/appc/test_pointer_arrows.py
```

- [ ] **Step 3: Strip the arrow hooks from `top_window.py`, `host_loop.py`, and the CEF assets**

Remove `_arrow_placements` recording, the `ArrowOverlayPusher` wiring, `#pointer-arrows`, and `.arrow*` CSS. Leave the officer-menu `PositionPusher` and the resolver alone.

- [ ] **Step 4: Run the gate — nothing should break**

Run: `scripts/check_tests.sh`
Expected: green (compare failures to `tests/known_failures.txt`). Deleting dead code must not regress anything.

- [ ] **Step 5: Commit**

```bash
git add -u && git commit -m "refactor(ui): drop position-based pointer arrows (superseded by identifier-centric attention)"
```

---

### Task 2: Engine — the highlight registry + SDK override

**Files:**
- Create: `engine/ui/ui_attention.py`
- Test: `tests/ui/test_ui_attention.py`
- Modify: wherever engine boot installs SDK overrides (find where `MissionLib` is first imported/patched; if no such seam exists, install lazily on first use and document it)

**Interfaces:**
- Produces:
  - `highlighted_ids() -> set[int]` — the currently-highlighted widget ids.
  - `show_pointer_arrow(pAction, pUIObject, eDirection=0, fSpacing=0.0, kColor=None) -> int` — the `MissionLib.ShowPointerArrow` replacement. Bails (returns 0) if `pUIObject is None` or `pUIObject.IsCompletelyVisible() == 0`. Otherwise adds `ensure_widget_id(pUIObject)` to the set (recording `kColor` if given) and returns 0.
  - `hide_pointer_arrows(pAction=None) -> None` — clears the set (matches the SDK, which empties `g_lPointerArrows` wholesale).
  - `install()` — overrides `MissionLib.ShowPointerArrow` / `MissionLib.HidePointerArrows` module attributes.
  - `highlight_color(wid) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_ui_attention.py
from engine.ui import ui_attention
from engine.appc.tg_ui.widgets import ensure_widget_id, TGPane

class _Widget(TGPane):
    def __init__(self, visible=True):
        super().__init__()
        self._vis = visible
    def IsCompletelyVisible(self):
        return 1 if self._vis else 0

def setup_function(_):
    ui_attention.hide_pointer_arrows()

def test_show_adds_widget_id():
    w = _Widget()
    ui_attention.show_pointer_arrow(None, w, 0, 0.0, None)
    assert ensure_widget_id(w) in ui_attention.highlighted_ids()

def test_show_bails_on_none_and_invisible():
    ui_attention.show_pointer_arrow(None, None, 0, 0.0, None)
    assert ui_attention.highlighted_ids() == set()
    hidden = _Widget(visible=False)
    ui_attention.show_pointer_arrow(None, hidden, 0, 0.0, None)
    assert ui_attention.highlighted_ids() == set()

def test_hide_clears_all():
    a, b = _Widget(), _Widget()
    ui_attention.show_pointer_arrow(None, a, 0, 0.0, None)
    ui_attention.show_pointer_arrow(None, b, 0, 0.0, None)
    ui_attention.hide_pointer_arrows()
    assert ui_attention.highlighted_ids() == set()

def test_reissuing_same_set_is_idempotent():
    w = _Widget()
    ui_attention.show_pointer_arrow(None, w, 0, 0.0, None)
    first = set(ui_attention.highlighted_ids())
    ui_attention.show_pointer_arrow(None, w, 0, 0.0, None)
    assert ui_attention.highlighted_ids() == first

def test_install_overrides_missionlib():
    import MissionLib
    ui_attention.install()
    assert MissionLib.ShowPointerArrow is ui_attention.show_pointer_arrow
    assert MissionLib.HidePointerArrows is ui_attention.hide_pointer_arrows
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/ui/test_ui_attention.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `engine/ui/ui_attention.py`**

```python
# engine/ui/ui_attention.py
"""Identifier-centric UI attention.

BC's MissionLib.ShowPointerArrow is POSITION-based: it reads the target widget's
screen rect and drops an LCARS arrow icon at computed coordinates. Chrome draws our
UI, so those coordinates can never be made reliably correct (headless SDK font
metrics are 0; BC's real metrics are 1024x768 bitmap values that don't match Chrome's
layout). The information the SDK is conveying is not a coordinate — it is "draw the
player's attention to THIS widget".

So we override the two SDK functions (the sdk/ file is untouched — this is a RENDERER
substitution, not a logic fork; the SDK still decides what and when) and record the
target's widget id. CrewMenuPanel's existing snapshot carries the flag; CEF styles the
element Chrome already drew. Cannot mis-place, needs no geometry.

Spec: docs/superpowers/specs/2026-07-12-identifier-centric-ui-attention-design.md
"""

from engine.appc.tg_ui.widgets import ensure_widget_id

_highlighted: set = set()
_colors: dict = {}


def highlighted_ids() -> set:
    return _highlighted


def highlight_color(wid):
    return _colors.get(wid)


def show_pointer_arrow(pAction=None, pUIObject=None, eDirection=0,
                       fSpacing=0.0, kColor=None) -> int:
    # Preserve the SDK's own gates (MissionLib.py:4413-4416).
    if pUIObject is None:
        return 0
    try:
        if pUIObject.IsCompletelyVisible() == 0:
            return 0
    except AttributeError:
        return 0
    wid = ensure_widget_id(pUIObject)
    _highlighted.add(wid)
    if kColor is not None:
        _colors[wid] = kColor
    # eDirection / fSpacing are BC arrow-art placement details with no meaning
    # under a glow; deliberately discarded (see spec).
    return 0


def hide_pointer_arrows(pAction=None):
    # SDK semantics: HidePointerArrows empties g_lPointerArrows wholesale.
    _highlighted.clear()
    _colors.clear()
    if pAction is not None:
        return 0


def install() -> None:
    """Override the SDK's two attention functions. The SDK file is untouched."""
    import MissionLib
    MissionLib.ShowPointerArrow = show_pointer_arrow
    MissionLib.HidePointerArrows = hide_pointer_arrows
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/ui/test_ui_attention.py -v` → PASS (5 tests).

- [ ] **Step 5: Call `install()` at engine boot**

Find where the engine sets up SDK-facing state at boot (grep `host_loop.py` for existing SDK module patching / `reset_sdk_globals`). Call `ui_attention.install()` there. **Note `reset_sdk_globals` re-imports/reloads SDK modules on mission swap** — if it does, `install()` must be re-run after each swap or the override is lost (cf. the "TCW recreated on every mission swap" gotcha). Verify and handle; add a test if a swap seam exists.

- [ ] **Step 6: Gate + commit**

```bash
scripts/check_tests.sh
git add engine/ui/ui_attention.py tests/ui/test_ui_attention.py engine/host_loop.py
git commit -m "feat(ui): identifier-centric attention — override ShowPointerArrow to a highlight set"
```

---

### Task 3: Snapshot carries the highlight (+ the flicker trap)

**Files:**
- Modify: `engine/ui/crew_menu_panel.py` (`_snapshot_node`)
- Test: `tests/ui/test_crew_menu_highlight.py`

**Interfaces:**
- Consumes: `ui_attention.highlighted_ids()`, `highlight_color()`.
- Produces: each snapshot node gains `"highlighted": bool` and (when set) `"highlightColor"`. Applies to **STMenu (submenu) nodes as well as STButton leaves** — the E1M1 target is a submenu row.

- [ ] **Step 1: Write the failing test — including the flicker trap**

```python
# tests/ui/test_crew_menu_highlight.py
from engine.ui import ui_attention

def test_snapshot_marks_highlighted_node(crew_panel_with_helm_menu):
    panel, set_course_submenu = crew_panel_with_helm_menu
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, set_course_submenu, 0, 0.0, None)
    payload = panel.snapshot()
    node = _find(payload, set_course_submenu)
    assert node["highlighted"] is True

def test_snapshot_unhighlighted_by_default(crew_panel_with_helm_menu):
    panel, set_course_submenu = crew_panel_with_helm_menu
    ui_attention.hide_pointer_arrows()
    node = _find(panel.snapshot(), set_course_submenu)
    assert node["highlighted"] is False

def test_refresh_cycle_leaves_payload_identical(crew_panel_with_helm_menu):
    """THE FLICKER TRAP. The mission's RefreshArrows timer calls HidePointerArrows()
    then re-issues ShowPointerArrow 8x/sec. Both happen inside ONE tick, so the next
    snapshot must be byte-identical to the previous one — otherwise CEF re-renders and
    restarts the CSS pulse animation 8x/sec, which looks broken."""
    panel, target = crew_panel_with_helm_menu
    ui_attention.show_pointer_arrow(None, target, 0, 0.0, None)
    before = panel.snapshot()
    ui_attention.hide_pointer_arrows()                       # what RefreshArrows does...
    ui_attention.show_pointer_arrow(None, target, 0, 0.0, None)  # ...then re-shows
    after = panel.snapshot()
    assert after == before
```

Build the `crew_panel_with_helm_menu` fixture from the real SDK Helm menu if a bridge fixture exists; otherwise construct an `STMenu` with a `GetSubmenuW("Set Course")` child and register it on a `CrewMenuPanel`. `_find` walks the payload tree matching `node["id"] == ensure_widget_id(widget)`.

- [ ] **Step 2: Run — expect failure** (`highlighted` key absent).

- [ ] **Step 3: Add the flag in `_snapshot_node`**

```python
        wid = ensure_widget_id(widget)
        self._widgets_by_id[wid] = widget
        ...
        node["highlighted"] = wid in ui_attention.highlighted_ids()
        _color = ui_attention.highlight_color(wid)
        if _color is not None:
            node["highlightColor"] = _color
```
Ensure this runs for **every** node type that gets an id (STMenu/submenu AND STButton), not just leaves.

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: VERIFY the panel push is change-gated**

`crew_menus.js` rebuilds `host.innerHTML`, so an unchanged payload re-pushed every frame would restart the CSS animation continuously. Confirm `Panel`/`PanelRegistry` only pushes when the payload **changes**. If it does not, add a dirty-flag (same pattern as `PositionPusher` in `engine/ui/sdk_panel_positions.py`) and cover it with a test. **Do not assume — check.**

- [ ] **Step 6: Gate + commit**

```bash
scripts/check_tests.sh
git commit -m "feat(ui): crew-menu snapshot carries the highlight flag (refresh-cycle stable)"
```

---

### Task 4: CEF — style the highlighted row

**Files:**
- Modify: `native/assets/ui-cef/js/crew_menus.js`
- Modify: `native/assets/ui-cef/css/crew_menus.css`
- Test: manual/live (CEF assets have no unit harness) — verified in Task 5.

- [ ] **Step 1: Apply the class in `crew_menus.js`**

Where the row element is built (it already sets `data-depth` and the click handlers), add:

```js
    if (node.highlighted) {
      row.classList.add("crew-menu__row--attention");
      if (node.highlightColor) {
        row.style.setProperty("--attention-color", node.highlightColor);
      }
    }
```
This must apply to **expandable submenu rows** as well as leaf rows — the E1M1 target ("Set Course") is a caret row.

- [ ] **Step 2: Style it in `crew_menus.css`**

Self-contained, no external assets. A pulsing glow/outline, defaulting to an LCARS-ish colour, overridable by `--attention-color`:

```css
/* Tutorial attention: BC drew an LCARS arrow beside the widget; we glow the row
   itself (identifier-centric — cannot mis-place). Persists until HidePointerArrows;
   deliberately NOT time-boxed. */
.crew-menu__row--attention {
  --attention-color: rgb(255, 208, 112);
  position: relative;
  animation: crew-attention-pulse 1.2s ease-in-out infinite;
  box-shadow: inset 0 0 0 2px var(--attention-color);
}
@keyframes crew-attention-pulse {
  0%, 100% { box-shadow: inset 0 0 0 2px var(--attention-color); }
  50%      { box-shadow: inset 0 0 0 2px var(--attention-color),
                         0 0 12px 2px var(--attention-color); }
}
@media (prefers-reduced-motion: reduce) {
  .crew-menu__row--attention { animation: none; }
}
```

- [ ] **Step 3: Gate (assets don't affect the suites) + commit**

```bash
scripts/check_tests.sh
git commit -m "feat(ui): CEF pulses the highlighted crew-menu row"
```

---

### Task 5: Live acceptance (Mark-run)

**Files:** none.

- [ ] **Step 1: Full gate**

Run: `scripts/check_tests.sh` → green vs `tests/known_failures.txt`.

- [ ] **Step 2: Drive the real E1M1 Set Course tutorial**

```bash
./build/dauntless --developer   # load E1M1
```
Progress until **Picard's** menu offers "Setting Course"; click it. `ExplainWarp` should now play (Picard menu **down** → Kiska/Helm menu **up**, inside the cutscene — this is what the SP-E MenuUp work unblocked), then:

**Confirm: the "Set Course" submenu row in Kiska's Helm menu pulses.** It should keep pulsing (not time out) and stop when the tutorial hides it.

- [ ] **Step 3: Confirm no production regression**

Without the tutorial, no row ever pulses; the crew menu is visually unchanged.

- [ ] **Step 4: Record and commit**

```bash
git commit --allow-empty -m "test(ui): E1M1 Set Course highlights the real Helm submenu row (live-verified)"
```

---

## Self-Review

**Spec coverage:** override at `ShowPointerArrow` chokepoint (T2 ✓); no SDK edits (T2 ✓); identifier reuse via `ensure_widget_id` (T2/T3 ✓); persistent-not-timed (T2 `hide` clears only on `HidePointerArrows` ✓); SDK visibility gate preserved (T2 ✓); `kColor` → glow colour (T2/T3/T4 ✓); snapshot flag on the existing channel (T3 ✓); **flicker trap tested** (T3 ✓); submenu rows highlightable (T3/T4 ✓); arrow-geometry deleted + Task 1 probe dropped (T1 ✓); resolver/push channel preserved (T1 explicitly ✓); live proof (T5 ✓).

**Deferred (not in this plan, nothing depends on them):** `AlignTo`-driven HUD reflow (needs a Chrome→host measurement channel); highlighting widgets we don't yet project with ids (target list, gauges).

**Placeholders:** none. The one "verify, don't assume" is Task 3 Step 5 (panel change-gating), which is flagged as a required check with a test, not a TODO.
