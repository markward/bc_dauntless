# SDK-driven UI Positioning + Tutorial Pointer Arrows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SDK the source of truth for the officer menu's on-screen position, and land a real E1M1 tutorial pointer arrow on the actual "Set Course" button in the CEF officer menu.

**Architecture:** A top-down layout resolver over the existing TG-UI widget tree resolves the SDK's relative placement (`SetPosition`/`Move`/`AlignTo`) into absolute **normalized** rects during `Layout()`. `GetScreenOffset` reads those cached rects; the host drives the CEF officer-menu element from the same rects; and `MissionLib.ShowPointerArrow` places a CEF-overlay arrow at the resolved position. Normalized [0,1] flows end to end and becomes `vw`/`vh` at the CEF boundary (no pixel/dsf math). The real E1M1 `ExplainWarp` tutorial is the proof driver.

**Tech Stack:** Python 3 (engine), pytest + ctest (`scripts/check_tests.sh` gate), CEF (HTML/CSS/JS overlay via `cef_execute_javascript`), the running original BC + Dauntless for live verification.

## Global Constraints

- **No SDK edits.** All fixes land in `engine/` / `native/`. SDK scripts are ground truth (`sdk/Build/scripts/` is read-only for this work).
- **Coordinates are normalized 0..1, top-left origin, y-down, NO vertical flip.** CSS/CEF is also top-left/y-down, so reconciliation is a pure scale (normalized → `vw`/`vh`).
- **`GetScreenOffset` returns the widget's top-left corner** (verified from `MissionLib.py:4444-4464` arrow math and `TacticalControlWindow.py:513-536` HUD positions).
- **Fail loud, never silent (0,0).** The old stub returned `(0,0)`; the resolver must raise on an unresolved widget / unhandled `AlignTo` combo instead.
- **Test gate:** `scripts/check_tests.sh` (pytest + ctest, diffed against `tests/known_failures.txt`). Never call a failure "pre-existing" by eyeball.
- **Spec:** `docs/superpowers/specs/2026-07-11-sdk-driven-ui-positioning-and-pointer-arrows-design.md`.
- **POINTER_\* values** (from `MissionLib.py:13-22`): LEFT=0, UL=1, UP=2, UR=3, RIGHT=4, DR=5, DOWN=6, DL=7, UL_CORNER=8, UR_CORNER=9.
- **Reference resolution 1024×768** (`LCARS_1024.py`); geometry is normalized by dividing by `SCREEN_PIXEL_WIDTH/HEIGHT`, so numbers are resolution-agnostic.

---

## Spike gate

Tasks 1 and 2 are **investigation spikes** run against live games; their deliverable is a findings document, not a passing test. Task 2's output defines Task 11's concrete steps — **do not write Task 11 until Task 2 is complete.** If Task 2 surfaces a blocker that is itself a large subsystem, STOP and re-scope with Mark (per the spec's guard) rather than absorbing it.

Tasks 3–10 (resolver, arrows, channel, CEF) do **not** depend on the spikes' outcomes except Task 6, which consumes Task 1's captured geometry. They may proceed in parallel with scheduling the spikes.

---

### Task 1: Spike — officer-menu geometry probe (running ORIGINAL game)

**Files:**
- Create: `docs/instrumented_experiments/2026-07-11-officer-menu-geometry.md` (runbook + captured results)

**Interfaces:**
- Produces: ground-truth normalized rects consumed by Task 6 — `WINDOW_RECT = (left, top, width, height)` and `SETTING_COURSE_BUTTON_RECT = (left, top, width, height)` at 1024×768, plus `BORDER = (bw, bh)`.

- [ ] **Step 1: Write the probe runbook**

Following the `docs/instrumented_experiments/` convention (console probes, NOT an `App.py` snippet). The experiment, to run in a live original-BC mission with Picard's menu open:

```python
# In-game console (Python 1.5), officer menu ("Picard"/Commander) open:
import App, MissionLib
pTCW = App.TacticalControlWindow_GetTacticalControlWindow()
pDB  = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
pMenu = pTCW.FindMenu(pDB.GetString("Commander"))
pWin  = pMenu.GetContainingWindow()
kOff = App.NiPoint2(0.0, 0.0); pWin.GetScreenOffset(kOff)
# record: pWin screen offset, GetWidth/GetHeight, GetBorderWidth/GetBorderHeight
pBtn = pMenu.GetButtonW(pDB.GetString("SettingCourse"))
kB = App.NiPoint2(0.0, 0.0); pBtn.GetScreenOffset(kB)
# record: pBtn screen offset, GetWidth/GetHeight
# Write results to BCTickLog.cfg via g_kConfigMapping (the only working write path).
```

- [ ] **Step 2: Mark runs the probe at 1024×768 and records values**

Expected: numeric normalized rects for window + button + border. (Window offset expected ≈ (0.0, 0.0) per the traced placement; button offset ≈ border + row index × row height.)

- [ ] **Step 3: Record results in the runbook and commit**

```bash
git add docs/instrumented_experiments/2026-07-11-officer-menu-geometry.md
git commit -m "docs(instr): officer-menu geometry ground truth from original BC"
```

Deliverable: the four rects above, filled in. These become the tolerance target in Task 6.

---

### Task 2: Spike — E1M1 tutorial-chain blocker enumeration (running Dauntless)

**Files:**
- Create: `docs/superpowers/plans/2026-07-11-e1m1-set-course-tutorial-blockers.md` (findings)

**Interfaces:**
- Produces: an ordered list of concrete engine-side blockers preventing the E1M1 `SettingCourse` tutorial from reaching its `ShowArrow` beat. Consumed by Task 11 (re-plan).

- [ ] **Step 1: Run E1M1 in Dauntless and drive toward the SettingCourse beat**

```bash
./build/dauntless --developer   # load E1M1 via the dev mission picker
```

Progress the mission; observe whether Picard's menu becomes enabled with a `SettingCourse` button and whether clicking it triggers `ExplainWarp`.

- [ ] **Step 2: For each dependency in the ExplainWarp sequence, record status**

Check, in order (`E1M1.py:3513-3534`): `PreloadSequenceLines`, `StartCutscene`, `ChangeToBridge`, `SetTutorialFlag`, Picard `AT_MENU_DOWN`, Kiska `AT_MENU_UP`, `SetCharWindowLock`, `ReturnControl`, `ShowInfoBox`, and whether mission progression even enables Picard's menu at this beat. Note each as WORKS / BROKEN (with the error) / UNREACHED.

- [ ] **Step 3: Write findings + go/no-go and commit**

If any blocker is a large subsystem, mark **STOP — re-scope** and raise with Mark. Otherwise list the fixes for Task 11.

```bash
git add docs/superpowers/plans/2026-07-11-e1m1-set-course-tutorial-blockers.md
git commit -m "docs(plan): E1M1 Set Course tutorial blocker enumeration"
```

---

### Task 3: Rect, anchor mapping, and normalized→viewport reconciliation

**Files:**
- Create: `engine/appc/tg_ui/layout.py`
- Test: `tests/appc/tg_ui/test_layout_rect.py`

**Interfaces:**
- Produces:
  - `Rect(left, top, width, height)` with `.right`, `.bottom` properties.
  - `ANCHOR_FRACTIONS: dict[int, tuple[float, float]]` mapping each `ALIGN_*` sentinel to `(fx, fy)` in `{0.0, 0.5, 1.0}`.
  - `anchor_point(rect: Rect, anchor: int) -> tuple[float, float]` — the (x,y) of `anchor` on `rect`.
  - `norm_to_vhvw(left, top, width, height) -> dict` — `{"left","top","width","height"}` as CSS `vw`/`vh` strings (the single documented normalized→CEF boundary).

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/tg_ui/test_layout_rect.py
from engine.appc.tg_ui.layout import (
    Rect, ANCHOR_FRACTIONS, anchor_point, norm_to_vhvw,
    ALIGN_UL, ALIGN_UR, ALIGN_BL, ALIGN_BR, ALIGN_UC,
)

def test_rect_edges():
    r = Rect(0.1, 0.2, 0.3, 0.4)
    assert r.right == 0.4
    assert abs(r.bottom - 0.6) < 1e-9

def test_anchor_points_top_left_ydown():
    r = Rect(0.1, 0.2, 0.4, 0.4)
    assert anchor_point(r, ALIGN_UL) == (0.1, 0.2)          # upper-left
    assert anchor_point(r, ALIGN_UR) == (0.5, 0.2)          # upper-right
    assert anchor_point(r, ALIGN_BL) == (0.1, 0.6)          # bottom-left (y down)
    assert anchor_point(r, ALIGN_BR) == (0.5, 0.6)
    assert anchor_point(r, ALIGN_UC) == (0.3, 0.2)          # upper-centre

def test_anchor_fractions_distinct():
    # every ALIGN_* sentinel is distinct and mapped
    assert len(set(ANCHOR_FRACTIONS.keys())) == len(ANCHOR_FRACTIONS)

def test_norm_to_vhvw():
    css = norm_to_vhvw(0.0, 0.0, 0.143, 0.326)
    assert css["left"] == "0.0vw"
    assert css["top"] == "0.0vh"
    assert css["width"] == "14.3vw"
    assert css["height"] == "32.6vh"
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/appc/tg_ui/test_layout_rect.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `layout.py`**

```python
# engine/appc/tg_ui/layout.py
"""SDK UI layout primitives: normalized (0..1, top-left, y-down) rects, the
ALIGN_* anchor mapping, and the single normalized→CEF (vw/vh) boundary.

These sentinels are our own; the SDK references App.TGUIObject.ALIGN_* which
must resolve to these same values (wired in Task 4)."""

# Anchor sentinels (halign, valign codes). Values are internal but must be the
# ones App.TGUIObject.ALIGN_* expose so SDK comparisons match (Task 4 wires them).
ALIGN_UL = 0   # (0.0, 0.0)
ALIGN_UC = 1   # (0.5, 0.0)
ALIGN_UR = 2   # (1.0, 0.0)
ALIGN_CL = 3   # (0.0, 0.5)
ALIGN_CC = 4   # (0.5, 0.5)
ALIGN_CR = 5   # (1.0, 0.5)
ALIGN_BL = 6   # (0.0, 1.0)
ALIGN_BC = 7   # (0.5, 1.0)
ALIGN_BR = 8   # (1.0, 1.0)

ANCHOR_FRACTIONS = {
    ALIGN_UL: (0.0, 0.0), ALIGN_UC: (0.5, 0.0), ALIGN_UR: (1.0, 0.0),
    ALIGN_CL: (0.0, 0.5), ALIGN_CC: (0.5, 0.5), ALIGN_CR: (1.0, 0.5),
    ALIGN_BL: (0.0, 1.0), ALIGN_BC: (0.5, 1.0), ALIGN_BR: (1.0, 1.0),
}


class Rect:
    __slots__ = ("left", "top", "width", "height")

    def __init__(self, left=0.0, top=0.0, width=0.0, height=0.0):
        self.left = float(left)
        self.top = float(top)
        self.width = float(width)
        self.height = float(height)

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height


def anchor_point(rect, anchor):
    fx, fy = ANCHOR_FRACTIONS[anchor]
    return (rect.left + fx * rect.width, rect.top + fy * rect.height)


def _fmt(value, unit):
    # Normalized fraction → viewport-percent string, trimmed to 1 decimal.
    return "%svw" % round(value * 100.0, 1) if unit == "vw" else "%svh" % round(value * 100.0, 1)


def norm_to_vhvw(left, top, width, height):
    """The one documented normalized→CEF boundary: fraction-of-screen → vw/vh.
    x/width use vw (fraction of viewport width); y/height use vh. No y-flip."""
    return {
        "left": _fmt(left, "vw"),
        "top": _fmt(top, "vh"),
        "width": _fmt(width, "vw"),
        "height": _fmt(height, "vh"),
    }
```

- [ ] **Step 4: Run it — expect pass**

Run: `uv run pytest tests/appc/tg_ui/test_layout_rect.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/tg_ui/layout.py tests/appc/tg_ui/test_layout_rect.py
git commit -m "feat(ui): normalized Rect + anchor mapping + vw/vh reconciliation"
```

---

### Task 4: Resolver core — local placement + top-down Layout + GetScreenOffset

**Files:**
- Modify: `engine/appc/tg_ui/widgets.py` (the `TGPane` base, lines 64-150)
- Test: `tests/appc/tg_ui/test_layout_resolver.py`

**Interfaces:**
- Consumes: `Rect` from Task 3.
- Produces, on every `TGPane`:
  - local placement state via `SetPosition(x, y, *_)`, `Move(dx, dy, *_)` (accumulates), seeded by `AddChild(child, x, y)`.
  - `Layout()` performs a **top-down** pass caching `child._abs_rect` (a `Rect`) = parent origin + child local (AlignTo added in Task 5).
  - `GetLeft()/GetTop()` return resolved absolute values (from `_abs_rect`), `GetScreenOffset(out)` fills `out.x/out.y` with the resolved top-left.
  - `_abs_rect` is `None` until the widget is laid out; `GetScreenOffset` on an un-laid-out widget **raises `LayoutNotResolved`** (fail-loud), never returns `(0,0)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/tg_ui/test_layout_resolver.py
import pytest
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.tg_ui.layout import LayoutNotResolved

class _Pt:
    def __init__(self): self.x = 0.0; self.y = 0.0

def test_setposition_then_layout_resolves_absolute():
    root = TGPane(1.0, 1.0)
    child = TGPane(0.2, 0.1)
    root.AddChild(child, 0.0, 0.0)
    child.SetPosition(0.3, 0.4, 0)
    root.Layout()
    off = _Pt(); child.GetScreenOffset(off)
    assert abs(off.x - 0.3) < 1e-9
    assert abs(off.y - 0.4) < 1e-9
    assert abs(child.GetLeft() - 0.3) < 1e-9

def test_nested_offsets_accumulate():
    root = TGPane(1.0, 1.0)
    mid = TGPane(0.5, 0.5); leaf = TGPane(0.1, 0.1)
    root.AddChild(mid, 0.1, 0.2)
    mid.AddChild(leaf, 0.05, 0.05)
    root.Layout()
    off = _Pt(); leaf.GetScreenOffset(off)
    assert abs(off.x - 0.15) < 1e-9
    assert abs(off.y - 0.25) < 1e-9

def test_move_accumulates():
    root = TGPane(1.0, 1.0); child = TGPane(0.1, 0.1)
    root.AddChild(child, 0.0, 0.0)
    child.SetPosition(0.1, 0.1, 0); child.Move(0.05, 0.0, 0)
    root.Layout()
    off = _Pt(); child.GetScreenOffset(off)
    assert abs(off.x - 0.15) < 1e-9

def test_unresolved_raises_not_zero():
    orphan = TGPane(0.1, 0.1)
    with pytest.raises(LayoutNotResolved):
        orphan.GetScreenOffset(_Pt())
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/appc/tg_ui/test_layout_resolver.py -v`
Expected: FAIL (`LayoutNotResolved` undefined; offsets 0.0).

- [ ] **Step 3: Add `LayoutNotResolved` to `layout.py`**

```python
# append to engine/appc/tg_ui/layout.py
class LayoutNotResolved(RuntimeError):
    """Raised when GetScreenOffset/GetLeft is called on a widget the resolver
    has not placed. Replaces the old silent (0,0) stub so unimplemented panels
    are loud, not plausibly-wrong."""
```

- [ ] **Step 4: Refactor `TGPane` placement + Layout in `widgets.py`**

Replace the stub methods (lines 135-150 region) with:

```python
    # ── Layout resolver state (Task 4/5) ─────────────────────────────────────
    #   _local_left/_top : this widget's position relative to its parent origin
    #   _abs_rect        : resolved absolute Rect (None until Layout runs)
    #   _align_spec      : optional (other, my_anchor, other_anchor) for AlignTo
    def _ensure_layout_state(self):
        if not hasattr(self, "_local_left"):
            self._local_left = 0.0
            self._local_top = 0.0
            self._abs_rect = None
            self._align_spec = None

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))
        child._ensure_layout_state()
        child._local_left = float(x)
        child._local_top = float(y)

    def SetPosition(self, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._ensure_layout_state()
        self._local_left = float(x)
        self._local_top = float(y)
        self._align_spec = None

    def Move(self, dx: float = 0.0, dy: float = 0.0, *_extra) -> None:
        self._ensure_layout_state()
        self._local_left += float(dx)
        self._local_top += float(dy)

    def Layout(self, *args) -> None:
        from engine.appc.tg_ui.layout import Rect
        self._ensure_layout_state()
        if self._abs_rect is None:            # root: place at its own local
            self._abs_rect = Rect(self._local_left, self._local_top,
                                  self._width, self._height)
        self._layout_children()

    def _layout_children(self):
        from engine.appc.tg_ui.layout import Rect
        origin_l = self._abs_rect.left
        origin_t = self._abs_rect.top
        for child, _x, _y in self._children:
            child._ensure_layout_state()
            child._abs_rect = self._resolve_child_rect(child, origin_l, origin_t)
            child._layout_children()

    def _resolve_child_rect(self, child, origin_l, origin_t):
        from engine.appc.tg_ui.layout import Rect
        # AlignTo handled in Task 5; here: parent origin + child local.
        return Rect(origin_l + child._local_left,
                    origin_t + child._local_top,
                    child._width, child._height)

    def GetLeft(self) -> float:
        self._ensure_layout_state()
        if self._abs_rect is None:
            from engine.appc.tg_ui.layout import LayoutNotResolved
            raise LayoutNotResolved("GetLeft before Layout")
        return self._abs_rect.left

    def GetTop(self) -> float:
        self._ensure_layout_state()
        if self._abs_rect is None:
            from engine.appc.tg_ui.layout import LayoutNotResolved
            raise LayoutNotResolved("GetTop before Layout")
        return self._abs_rect.top

    def GetScreenOffset(self, out=None):
        self._ensure_layout_state()
        if self._abs_rect is None:
            from engine.appc.tg_ui.layout import LayoutNotResolved
            raise LayoutNotResolved("GetScreenOffset before Layout")
        if out is not None:
            if hasattr(out, "x"): out.x = self._abs_rect.left
            if hasattr(out, "y"): out.y = self._abs_rect.top
            return out
        from engine.appc.math import TGPoint3
        return TGPoint3(self._abs_rect.left, self._abs_rect.top, 0.0)
```

Remove the old `def GetLeft`, `def GetTop`, `def AlignTo`, `def SetPosition`, `def Layout` stubs (they are now defined above). Keep `AlignTo` as a temporary no-op **only** until Task 5 replaces it — add `def AlignTo(self, *a): self._ensure_layout_state()` if needed for import safety.

- [ ] **Step 5: Run tests — expect pass**

Run: `uv run pytest tests/appc/tg_ui/test_layout_resolver.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full gate to catch fallout from changing the base widget**

Run: `scripts/check_tests.sh`
Expected: no new failures vs `tests/known_failures.txt`. (Many shims subclass `TGPane`; if a caller relied on `GetLeft()==0.0`, fix that caller in this task.)

- [ ] **Step 7: Commit**

```bash
git add engine/appc/tg_ui/widgets.py engine/appc/tg_ui/layout.py tests/appc/tg_ui/test_layout_resolver.py
git commit -m "feat(ui): top-down layout resolver with fail-loud GetScreenOffset"
```

---

### Task 5: AlignTo resolution

**Files:**
- Modify: `engine/appc/tg_ui/widgets.py` (`AlignTo`, `_resolve_child_rect`)
- Test: `tests/appc/tg_ui/test_layout_alignto.py`

**Interfaces:**
- Consumes: `anchor_point`, `ANCHOR_FRACTIONS` from Task 3; resolver from Task 4.
- Produces: `AlignTo(other, my_anchor, other_anchor, *_)` records an alignment spec resolved at Layout so `my_anchor` point coincides with `other_anchor` point of `other` (both already-resolved). Raises `LayoutNotResolved` if `other` is not yet resolved when this child is laid out.

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/tg_ui/test_layout_alignto.py
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.tg_ui.layout import ALIGN_BL, ALIGN_UL

class _Pt:
    def __init__(self): self.x = 0.0; self.y = 0.0

def test_alignto_bl_to_ul_stacks_below():
    # Child B's upper-left aligns to sibling A's bottom-left -> B sits under A.
    root = TGPane(1.0, 1.0)
    a = TGPane(0.2, 0.1); b = TGPane(0.2, 0.1)
    root.AddChild(a, 0.05, 0.05)
    root.AddChild(b, 0.0, 0.0)
    b.AlignTo(a, ALIGN_UL, ALIGN_BL, 0)   # my UL to A's BL
    root.Layout()
    off = _Pt(); b.GetScreenOffset(off)
    assert abs(off.x - 0.05) < 1e-9        # same left as A
    assert abs(off.y - 0.15) < 1e-9        # A.top(0.05) + A.height(0.1)
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/appc/tg_ui/test_layout_alignto.py -v`
Expected: FAIL (AlignTo is a no-op; offset wrong).

- [ ] **Step 3: Implement AlignTo + alignment resolution**

```python
    def AlignTo(self, other, my_anchor, other_anchor, *_extra) -> None:
        self._ensure_layout_state()
        self._align_spec = (other, int(my_anchor), int(other_anchor))
        self._local_left = 0.0
        self._local_top = 0.0
```

Update `_resolve_child_rect` to honor the spec:

```python
    def _resolve_child_rect(self, child, origin_l, origin_t):
        from engine.appc.tg_ui.layout import (
            Rect, anchor_point, ANCHOR_FRACTIONS, LayoutNotResolved,
        )
        if child._align_spec is not None:
            other, my_anchor, other_anchor = child._align_spec
            if getattr(other, "_abs_rect", None) is None:
                raise LayoutNotResolved("AlignTo target not yet resolved")
            ox, oy = anchor_point(other._abs_rect, other_anchor)
            mfx, mfy = ANCHOR_FRACTIONS[my_anchor]
            return Rect(ox - mfx * child._width, oy - mfy * child._height,
                        child._width, child._height)
        return Rect(origin_l + child._local_left,
                    origin_t + child._local_top,
                    child._width, child._height)
```

Note: `AlignTo` targets a resolved sibling, so siblings must resolve in child order; the test's A-before-B ordering matches `RepositionUI`'s ordering. If a future panel aligns to a later sibling, the `LayoutNotResolved` raise makes it loud (handle in a follow-on, not here).

- [ ] **Step 4: Run it — expect pass**

Run: `uv run pytest tests/appc/tg_ui/test_layout_alignto.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/tg_ui/widgets.py tests/appc/tg_ui/test_layout_alignto.py
git commit -m "feat(ui): AlignTo anchor resolution in the layout resolver"
```

---

### Task 6: Officer-menu geometry — wire the menu + button, assert BC ground truth

**Files:**
- Modify: `engine/appc/characters.py` (the `CharacterMenu` button `GetScreenOffset`, lines 87-100)
- Test: `tests/appc/test_officer_menu_geometry.py`

**Interfaces:**
- Consumes: resolver (Tasks 4-5); Task 1's `WINDOW_RECT`, `SETTING_COURSE_BUTTON_RECT`, `BORDER`.
- Produces: the officer-menu window resolves to `(0,0)`; each button's `GetScreenOffset` = border + row index × row height, matching Task 1 within tolerance.

- [ ] **Step 1: Delete the stub `GetScreenOffset`/`GetWidth`/`GetHeight` in `characters.py`**

Remove lines 86-100 (the "Layout placeholders" block returning `(0,0)`). The class must inherit the resolver's `GetScreenOffset` (make the menu-button class subclass `TGPane`, or delegate to a resolver-backed pane). If it cannot subclass `TGPane` directly, give it `_ensure_layout_state`/`_abs_rect` and reuse `TGPane.GetScreenOffset` via composition.

- [ ] **Step 2: Write the failing test using Task 1's captured values**

```python
# tests/appc/test_officer_menu_geometry.py
# Ground truth captured in docs/instrumented_experiments/2026-07-11-officer-menu-geometry.md
# Fill BORDER/ROW_H from that runbook before running.
from engine.appc.tg_ui.widgets import TGPane

BORDER = (0.0, 0.0)      # TODO: replace with captured GetBorderWidth/Height
ROW_H = 0.0              # TODO: replace with captured button row height
SETTING_COURSE_TOP = 0.0 # TODO: replace with captured button top (row index 2)

class _Pt:
    def __init__(self): self.x = 0.0; self.y = 0.0

def _build_officer_menu():
    # Mirror the SDK: window at (0,0), buttons stacked from border by ROW_H.
    window = TGPane(0.143, 0.326)
    window.SetPosition(0.0, 0.0, 0)
    labels = ["CrewSelect", "Objectives", "SettingCourse"]
    buttons = {}
    for i, name in enumerate(labels):
        b = TGPane(0.143 - 2 * BORDER[0], ROW_H)
        window.AddChild(b, BORDER[0], BORDER[1] + i * ROW_H)
        buttons[name] = b
    return window, buttons

def test_setting_course_button_matches_bc_ground_truth():
    window, buttons = _build_officer_menu()
    window.Layout()
    off = _Pt(); buttons["SettingCourse"].GetScreenOffset(off)
    assert abs(off.x - BORDER[0]) < 0.01
    assert abs(off.y - SETTING_COURSE_TOP) < 0.01
```

(This test encodes the resolver's fidelity to BC; once real menu construction is wired in Task 11's mission run, the live arrow is the ultimate check.)

- [ ] **Step 3: Run it — expect failure until values filled / class wired**

Run: `uv run pytest tests/appc/test_officer_menu_geometry.py -v`
Expected: FAIL until `characters.py` inherits the resolver and BORDER/ROW_H are filled from Task 1.

- [ ] **Step 4: Wire `CharacterMenu` button to the resolver; fill values; pass**

Run: `uv run pytest tests/appc/test_officer_menu_geometry.py -v`
Expected: PASS.

- [ ] **Step 5: Run the gate**

Run: `scripts/check_tests.sh`
Expected: no new failures (the `characters.py` change removes a stub used by many bridge flows — verify no regressions).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/characters.py tests/appc/test_officer_menu_geometry.py
git commit -m "feat(ui): officer-menu buttons report resolver-backed GetScreenOffset"
```

---

### Task 7: Pointer-arrow surface — ShowPointerArrow emission + g_lPointerArrows

**Files:**
- Create: `engine/appc/pointer_arrows.py`
- Modify: `engine/appc/top_window.py` (the `TopWindow` `PrependChild` to record arrow placements)
- Test: `tests/appc/test_pointer_arrows.py`

**Interfaces:**
- Consumes: resolver `GetScreenOffset`; `POINTER_*` constants (from `MissionLib`, values 0-9).
- Produces:
  - `TopWindow.PrependChild(icon, x, y, *_)` records `(icon, x, y)` (normalized) into `TopWindow._arrow_placements`.
  - `emitted_arrows() -> list[dict]` on the host bridge: `[{"x","y","dir"}...]` from live `g_lPointerArrows`.
  - `HidePointerArrows` clears both `g_lPointerArrows` and `TopWindow._arrow_placements`.
- Note: `MissionLib.ShowPointerArrow` is the SDK's own code and already runs; this task only makes the Appc calls it uses (`TGIcon_Create`, `TopWindow.PrependChild`, `GetScreenOffset`) resolve to real placements. Verify by porting the MissionLib arrow-position formula into an assertion.

- [ ] **Step 1: Write the failing test (port the MissionLib formula)**

```python
# tests/appc/test_pointer_arrows.py
# Ports MissionLib.ShowPointerArrow math (MissionLib.py:4444-4464) for POINTER_LEFT:
#   arrow x = offset.x + width + iconW*spacing ; y = offset.y + h/2 - iconH/2
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.top_window import TopWindow_GetTopWindow

def test_prependchild_records_normalized_placement():
    top = TopWindow_GetTopWindow()
    top._arrow_placements = []
    icon = TGPane(0.02, 0.02)
    top.PrependChild(icon, 0.30, 0.40, 0)
    assert top._arrow_placements[-1][1] == 0.30
    assert top._arrow_placements[-1][2] == 0.40

def test_show_pointer_arrow_left_lands_right_of_widget():
    import App, MissionLib
    from engine.appc.tg_ui.widgets import TGPane
    top = TopWindow_GetTopWindow(); top._arrow_placements = []
    MissionLib.g_lPointerArrows = []
    widget = TGPane(0.143, 0.030)
    # place + resolve the widget at a known offset
    root = TGPane(1.0, 1.0); root.AddChild(widget, 0.0, 0.10); root.Layout()
    MissionLib.ShowPointerArrow(None, widget, MissionLib.POINTER_LEFT, 0.0, None)
    icon, x, y = top._arrow_placements[-1]
    assert abs(x - (0.0 + 0.143)) < 1e-6           # right edge of widget
    assert abs(y - (0.10 + 0.015 - icon.GetHeight() / 2.0)) < 1e-6
    assert len(MissionLib.g_lPointerArrows) == 1

def test_hide_pointer_arrows_clears():
    import MissionLib
    from engine.appc.top_window import TopWindow_GetTopWindow
    top = TopWindow_GetTopWindow()
    MissionLib.HidePointerArrows()
    assert MissionLib.g_lPointerArrows == []
    assert top._arrow_placements == []
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/appc/test_pointer_arrows.py -v`
Expected: FAIL (`PrependChild` no-op; `_arrow_placements` absent).

- [ ] **Step 3: Implement `TopWindow.PrependChild` arrow recording**

In `engine/appc/top_window.py`, on the `TopWindow` class:

```python
    def PrependChild(self, child, x=0.0, y=0.0, *_extra):
        # Arrow icons from MissionLib.ShowPointerArrow land here as (icon, x, y)
        # in normalized TopWindow coords. Record for the host arrow-overlay pass.
        if not hasattr(self, "_arrow_placements"):
            self._arrow_placements = []
        self._arrow_placements.append((child, float(x), float(y)))

    def DeleteChild(self, child) -> None:
        if hasattr(self, "_arrow_placements"):
            self._arrow_placements = [
                p for p in self._arrow_placements if p[0] is not child
            ]
```

- [ ] **Step 4: Implement `engine/appc/pointer_arrows.py` (host-facing collector)**

```python
# engine/appc/pointer_arrows.py
"""Host-facing collector for MissionLib pointer arrows. MissionLib owns the
placement math; this exposes the resulting normalized placements + direction so
the host can emit a CEF overlay (Task 9). POINTER_* live in MissionLib."""

from engine.appc.top_window import TopWindow_GetTopWindow


def emitted_arrows():
    top = TopWindow_GetTopWindow()
    placements = getattr(top, "_arrow_placements", [])
    out = []
    for icon, x, y in placements:
        out.append({
            "x": x, "y": y,
            "w": icon.GetWidth(), "h": icon.GetHeight(),
            "dir": getattr(icon, "_pointer_dir", None),
        })
    return out
```

Ensure `MissionLib.HidePointerArrows` clears `TopWindow._arrow_placements`: the SDK's `HidePointerArrows` deletes each icon via its parent (`pIcon.GetParent().DeleteChild(pIcon)`). Confirm `TGIcon.GetParent()` returns the TopWindow so `DeleteChild` above runs; if `GetParent()` is `None` (current stub), set `icon._parent = top` in `PrependChild` and make `GetParent` return it, OR clear `_arrow_placements` directly in a thin `HidePointerArrows` wrapper registered in the engine. Pick the approach that keeps MissionLib unedited.

- [ ] **Step 5: Run tests — expect pass**

Run: `uv run pytest tests/appc/test_pointer_arrows.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/pointer_arrows.py engine/appc/top_window.py tests/appc/test_pointer_arrows.py
git commit -m "feat(ui): pointer-arrow placement recording + host collector"
```

---

### Task 8: Host → CEF position channel + SDK-positioned panel registry

**Files:**
- Create: `engine/ui/sdk_panel_positions.py`
- Modify: `engine/host_loop.py` (call the channel after the tactical layout pass)
- Test: `tests/ui/test_sdk_panel_positions.py`

**Interfaces:**
- Consumes: resolver rects; `norm_to_vhvw` (Task 3); `cef_execute_javascript`.
- Produces:
  - `SDK_POSITIONED_PANELS: dict[str, str]` mapping `panelId → DOM selector` (start: `{"officer-menu": "#crew-menu-host"}`).
  - `build_position_script(panel_id, rect) -> str | None` — JS that sets the element's inline `position:fixed` + vw/vh; `None` if unchanged since last call (dirty-flag).
  - `push_positions(cef_execute_javascript, rects: dict[str, Rect])` — emits scripts only for changed rects.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_sdk_panel_positions.py
from engine.appc.tg_ui.layout import Rect
from engine.ui.sdk_panel_positions import (
    build_position_script, PositionPusher, SDK_POSITIONED_PANELS,
)

def test_officer_menu_registered():
    assert SDK_POSITIONED_PANELS["officer-menu"] == "#crew-menu-host"

def test_script_sets_fixed_vwvh():
    js = build_position_script("officer-menu", Rect(0.0, 0.0, 0.143, 0.326))
    assert "#crew-menu-host" in js
    assert "position" in js and "fixed" in js
    assert "14.3vw" in js and "32.6vh" in js

def test_pusher_is_dirty_flagged():
    calls = []
    pusher = PositionPusher(lambda s: calls.append(s))
    r = Rect(0.0, 0.0, 0.143, 0.326)
    pusher.push({"officer-menu": r})
    pusher.push({"officer-menu": r})       # unchanged -> no second emit
    assert len(calls) == 1
    pusher.push({"officer-menu": Rect(0.0, 0.0, 0.2, 0.326)})  # changed -> emit
    assert len(calls) == 2
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/ui/test_sdk_panel_positions.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `engine/ui/sdk_panel_positions.py`**

```python
# engine/ui/sdk_panel_positions.py
"""Drives CEF panel position from SDK-resolved rects. Only panels the SDK
defines are listed here; Dauntless-invented panels stay CSS-positioned and are
never touched by this channel."""

from engine.appc.tg_ui.layout import norm_to_vhvw

SDK_POSITIONED_PANELS = {
    "officer-menu": "#crew-menu-host",
    # follow-on: "target-list": "#...", "ship-display": "#...", ...
}


def build_position_script(panel_id, rect):
    selector = SDK_POSITIONED_PANELS[panel_id]
    css = norm_to_vhvw(rect.left, rect.top, rect.width, rect.height)
    return (
        "(function(){var e=document.querySelector('%s');if(!e)return;"
        "e.style.position='fixed';e.style.left='%s';e.style.top='%s';"
        "e.style.width='%s';e.style.height='%s';})();"
        % (selector, css["left"], css["top"], css["width"], css["height"])
    )


class PositionPusher:
    """Emits a position script only when a panel's rect changes (dirty-flag)."""

    def __init__(self, cef_execute_javascript):
        self._exec = cef_execute_javascript
        self._last = {}

    def push(self, rects):
        for panel_id, rect in rects.items():
            key = (round(rect.left, 4), round(rect.top, 4),
                   round(rect.width, 4), round(rect.height, 4))
            if self._last.get(panel_id) == key:
                continue
            self._last[panel_id] = key
            self._exec(build_position_script(panel_id, rect))
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/ui/test_sdk_panel_positions.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire into `host_loop.py`**

After the tactical layout / `RepositionUI` pass runs (near the existing CEF panel push at `host_loop.py:5720`), construct a module-level `PositionPusher(_h.cef_execute_javascript)` once and call `pusher.push({"officer-menu": officer_menu_window._abs_rect})` each frame the officer menu is up. Guard with `hasattr(window, "_abs_rect") and window._abs_rect is not None`.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/sdk_panel_positions.py engine/host_loop.py tests/ui/test_sdk_panel_positions.py
git commit -m "feat(ui): SDK-resolved rect drives officer-menu CEF position (dirty-flagged)"
```

---

### Task 9: Host → CEF arrow-overlay emission

**Files:**
- Create: `engine/ui/pointer_arrow_overlay.py`
- Modify: `engine/host_loop.py` (emit arrows each frame)
- Test: `tests/ui/test_pointer_arrow_overlay.py`

**Interfaces:**
- Consumes: `emitted_arrows()` (Task 7); `norm_to_vhvw` (Task 3).
- Produces: `build_arrows_script(arrows: list[dict]) -> str` — replaces `#pointer-arrows` children with one positioned element per arrow (class `arrow arrow--<dir>` at vw/vh). Empty list → clears the layer.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_pointer_arrow_overlay.py
from engine.ui.pointer_arrow_overlay import build_arrows_script

def test_empty_clears_layer():
    js = build_arrows_script([])
    assert "#pointer-arrows" in js
    assert "innerHTML=''" in js.replace('"', "'").replace(" ", "")

def test_one_arrow_positioned_vwvh():
    js = build_arrows_script([{"x": 0.30, "y": 0.40, "w": 0.02, "h": 0.02, "dir": 0}])
    assert "30.0vw" in js and "40.0vh" in js
    assert "arrow--0" in js
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/ui/test_pointer_arrow_overlay.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `engine/ui/pointer_arrow_overlay.py`**

```python
# engine/ui/pointer_arrow_overlay.py
"""Renders MissionLib pointer arrows as a CEF overlay layer (#pointer-arrows).
Arrow (x,y) are normalized TopWindow coords -> vw/vh. Direction 0-9 maps to a
CSS class the stylesheet rotates/points."""

from engine.appc.tg_ui.layout import norm_to_vhvw


def build_arrows_script(arrows):
    parts = []
    for a in arrows:
        css = norm_to_vhvw(a["x"], a["y"], a.get("w", 0.0), a.get("h", 0.0))
        parts.append(
            "<div class='arrow arrow--%s' style=\"left:%s;top:%s\"></div>"
            % (a.get("dir"), css["left"], css["top"])
        )
    html = "".join(parts).replace("\\", "\\\\").replace("'", "\\'")
    return (
        "(function(){var e=document.querySelector('#pointer-arrows');"
        "if(!e)return;e.innerHTML='%s';})();" % html
    )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/ui/test_pointer_arrow_overlay.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into `host_loop.py`**

Each frame after the position push, call `build_arrows_script(pointer_arrows.emitted_arrows())` and pass to `_h.cef_execute_javascript`. Only emit when the arrow set changed (dirty-flag on the arrow list, same pattern as `PositionPusher`).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/pointer_arrow_overlay.py engine/host_loop.py tests/ui/test_pointer_arrow_overlay.py
git commit -m "feat(ui): CEF pointer-arrow overlay emission from resolved placements"
```

---

### Task 10: CEF assets — officer-menu SDK-driven position + arrow overlay layer

**Files:**
- Modify: `native/assets/ui-cef/css/crew_menus.css` (remove CSS-flow placement dependence)
- Modify: `native/assets/ui-cef/css/global.css` (add `#pointer-arrows` + `.arrow*` styles)
- Modify: `native/assets/ui-cef/hello.html` (add `<div id="pointer-arrows"></div>` overlay root)
- Test: manual/live (CEF assets have no unit harness); verified in Task 12.

**Interfaces:**
- Consumes: inline styles from Task 8 (`#crew-menu-host` gets `position:fixed` + vw/vh) and Task 9 (`#pointer-arrows` children).

- [ ] **Step 1: Add the arrow overlay root to `hello.html`**

```html
<!-- top-level overlay, above panels, ignores pointer events -->
<div id="pointer-arrows"></div>
```

- [ ] **Step 2: Style the overlay + arrows in `global.css`**

```css
#pointer-arrows {
  position: fixed; inset: 0; pointer-events: none; z-index: 9000;
}
#pointer-arrows .arrow {
  position: fixed; width: 2vw; height: 2vw;
  background: no-repeat center/contain;
  /* LCARS-white triangle; rotated per direction */
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><path d='M0 5 L10 0 L10 10 Z' fill='white'/></svg>");
}
#pointer-arrows .arrow--0 { transform: rotate(0deg); }    /* LEFT  (points left) */
#pointer-arrows .arrow--2 { transform: rotate(90deg); }   /* UP */
#pointer-arrows .arrow--4 { transform: rotate(180deg); }  /* RIGHT */
#pointer-arrows .arrow--6 { transform: rotate(270deg); }  /* DOWN */
#pointer-arrows .arrow--1, #pointer-arrows .arrow--8 { transform: rotate(45deg); }
#pointer-arrows .arrow--3, #pointer-arrows .arrow--9 { transform: rotate(135deg); }
#pointer-arrows .arrow--5 { transform: rotate(225deg); }
#pointer-arrows .arrow--7 { transform: rotate(315deg); }
```

- [ ] **Step 3: Neutralize the officer-menu CSS-flow placement in `crew_menus.css`**

`#crew-menu-host` now receives `position:fixed` + vw/vh inline from Task 8. Ensure the host is no longer laid out by the tactical-stack flow: remove/override any `#tactical-target-stack`-driven sizing on `#crew-menu-host` so the inline SDK position wins. Keep the inner `.crew-menu` chrome untouched.

- [ ] **Step 4: Rebuild is not required for CEF asset changes; reload the app**

CEF assets are read at runtime. (No cmake needed for HTML/CSS.)

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/hello.html native/assets/ui-cef/css/global.css native/assets/ui-cef/css/crew_menus.css
git commit -m "feat(ui): CEF officer-menu SDK-position hook + pointer-arrow overlay layer"
```

---

### Task 11: E1M1 Set Course tutorial trigger fixes  — **SPIKE-GATED**

**Do not implement until Task 2 is complete.** Task 2's findings define the concrete blockers and therefore the steps here. After Task 2, return to the writing-plans skill and expand this task into TDD steps per blocker (engine-side only, no SDK edits). If Task 2 found no blockers (tutorial already reaches `ShowArrow`), this task is a no-op and Task 12 proceeds directly.

**Files:** determined by Task 2 (likely `engine/` mission-progression / cutscene / info-box wiring).

**Deliverable:** the real E1M1 `SettingCourse` tutorial reaches its `ShowArrow(pSetCourseMenu, POINTER_UR_CORNER)` call in Dauntless.

---

### Task 12: End-to-end live acceptance (Mark-run)

**Files:** none (verification).

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no new failures vs `tests/known_failures.txt`.

- [ ] **Step 2: Live-run the real E1M1 Set Course tutorial**

```bash
./build/dauntless --developer   # load E1M1
```

Progress to the point Picard's menu enables `SettingCourse`; click it; confirm `ExplainWarp` plays and the pointer arrow appears **on the actual "Set Course" button** in the CEF officer menu (UR_CORNER), and that it tracks the button on the 0.125 s refresh.

- [ ] **Step 3: Confirm no production-path regression**

With `--developer` **off**, confirm the officer menu still renders correctly (SDK-driven position must not regress the normal HUD) and no arrows appear.

- [ ] **Step 4: Record verification in the spec status and commit**

```bash
git commit --allow-empty -m "test(ui): E1M1 Set Course pointer arrow lands on real button (live-verified)"
```

---

## Self-Review

**Spec coverage:**
- Layout resolver (`SetPosition`/`Move`/`AlignTo`/`Layout`/`GetLeft/Top/Width/Height`/`GetScreenOffset`) → Tasks 3-5. ✓
- Normalized/top-left/y-down/no-flip contract → Task 3 + constraints. ✓
- Officer menu SDK-positioned → Tasks 6, 8, 10. ✓
- `ShowPointerArrow`/`HidePointerArrows`/`g_lPointerArrows`/`POINTER_*` → Task 7. ✓
- Arrow as CEF overlay → Tasks 9, 10. ✓
- SDK→CEF position channel + dirty-flag → Task 8. ✓
- Coexistence registry (invented panels untouched) → Task 8 (`SDK_POSITIONED_PANELS`). ✓
- Fail-loud degradation → Tasks 3-4 (`LayoutNotResolved`). ✓
- Instrumentation ground truth → Task 1. ✓
- Real E1M1 tutorial trigger (Option B) → Tasks 2, 11, 12. ✓
- Coordinate reconciliation single boundary → Task 3 (`norm_to_vhvw`). ✓

**Placeholder scan:** Task 11 is intentionally spike-gated (Task 2 defines it) — flagged explicitly, not a hidden TODO. Task 6's test has captured-value placeholders that Task 1 fills — flagged inline. All other tasks contain complete code.

**Type consistency:** `Rect`, `anchor_point`, `norm_to_vhvw`, `LayoutNotResolved`, `_abs_rect`, `emitted_arrows()`, `PositionPusher.push`, `build_position_script`, `build_arrows_script`, `SDK_POSITIONED_PANELS` are used with consistent signatures across tasks. ✓

---

### Task 5b (INSERTED 2026-07-11 during execution): Officer-menu SDK layout invocation

**Why inserted:** the spec assumed `host_loop.py:run_tactical_layout` runs the SDK
tactical constructor; that exists only on the parked `feat/native_xo_menu_ui` branch.
On this branch the SDK menus are built + projected to CEF, but nothing runs
`ResizeUI`/`RepositionUI` + `Layout()` on the TCW, so the officer-menu window never
resolves a rect. Without this, Tasks 6/8/9/10 have no rect to read. Re-derived fresh
(no code copied from the parked branch; Mark's decision). Full brief:
`.superpowers/sdd/task-5b-brief.md`. Dependency: after Tasks 4-5; before Tasks 6/8/9/10.
