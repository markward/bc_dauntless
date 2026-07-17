# Faithful `IsCompletelyVisible` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `IsCompletelyVisible()` as a faithful inherited widget method so BC's power-display auto-rebalance (`AdjustPower`) runs only while the engineering display is on screen, instead of every tick.

**Architecture:** Add the RE's "self AND every ancestor visible" chain-walk to the `TGPane` base class (a `_parent` back-reference plus the method). Drive only the `EngPowerDisplay` leaf visibility, via a module-level `is_engineering_open` hook in `eng_power.py` that `IsCompletelyVisible` consults — registered once from the host loop using the same signal the CEF Engineering panel already uses. The engine-side power economy (`PowerSubsystem` conduit/battery draw) is untouched.

**Tech Stack:** Python 3 (headless `Appc` shim), pytest with the real SDK loader (`tests/conftest.py`), `scripts/check_tests.sh` gate.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-17-iscompletelyvisible-faithful-design.md`.
- `IsCompletelyVisible()` returns an **`int`** (`1`/`0`) — SDK callers compare `== 0` / `== 1` and use it in `or`/`not` tests.
- Do **not** change `_Stub` numeric/bool behavior — only its docstring.
- Do **not** change `PowerSubsystem` or any conduit/battery draw code.
- Capability tests use `isinstance(x, TGPane)`, **never** `hasattr`/`getattr` on engine objects — `TGObject.__getattr__` vends a truthy `_Stub` for missing names (see the `AddChild` comment at `widgets.py:76-83`).
- Shared checkout: stage commits with explicit pathspecs only; never `git add -A`/`.`.
- Full gate before done: `scripts/check_tests.sh` (pytest + ctest, diffs vs `tests/known_failures.txt`).

---

### Task 1: Faithful `IsCompletelyVisible` chain-walk on `TGPane`

**Files:**
- Modify: `engine/appc/tg_ui/widgets.py` (`TGPane.__init__`, `AddChild`, `InsertChild`, `DeleteChild`, `KillChildren`; add `IsCompletelyVisible`)
- Modify: `App.py:1998-2001` (`_Stub` docstring only)
- Test: `tests/unit/test_tg_pane_completely_visible.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TGPane._parent: Optional[TGPane]` — back-reference to the pane this was last added to (or `None`).
  - `TGPane.IsCompletelyVisible() -> int` — `1` iff own `_visible` is true AND, when a `TGPane` `_parent` exists, that parent is also completely visible; degrades to own `_visible` when `_parent` is `None` or not a `TGPane`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tg_pane_completely_visible.py`:

```python
"""TGPane.IsCompletelyVisible() — RE-faithful 'self AND ancestor chain' visibility.

See docs/superpowers/specs/2026-07-17-iscompletelyvisible-faithful-design.md.
"""
from engine.appc.tg_ui.widgets import TGPane


def test_lone_visible_pane_is_completely_visible():
    p = TGPane()
    assert p.IsCompletelyVisible() == 1


def test_lone_hidden_pane_is_not_completely_visible():
    p = TGPane()
    p.SetNotVisible()
    assert p.IsCompletelyVisible() == 0


def test_hidden_ancestor_hides_visible_child():
    parent = TGPane()
    child = TGPane()
    parent.AddChild(child)
    assert child.IsCompletelyVisible() == 1
    parent.SetNotVisible()
    assert child.IsCompletelyVisible() == 0        # ancestor hidden


def test_visible_chain_is_completely_visible():
    grand = TGPane()
    parent = TGPane()
    child = TGPane()
    grand.AddChild(parent)
    parent.AddChild(child)
    assert child.IsCompletelyVisible() == 1


def test_deletechild_clears_parent_backref():
    parent = TGPane()
    child = TGPane()
    parent.AddChild(child)
    parent.SetNotVisible()
    parent.DeleteChild(child)
    # Orphaned child no longer inherits the hidden parent's state.
    assert child.IsCompletelyVisible() == 1


def test_returns_int_not_bool():
    p = TGPane()
    assert type(p.IsCompletelyVisible()) is int
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_pane_completely_visible.py -v`
Expected: FAIL — `IsCompletelyVisible` currently resolves to a truthy `_Stub` via `TGObject.__getattr__` (e.g. `assert <_Stub> == 1` fails; `type(...) is int` fails).

- [ ] **Step 3: Add the `_parent` back-reference and the method**

In `engine/appc/tg_ui/widgets.py`, `TGPane.__init__` (after `self._enabled = True`, ~line 73), add:

```python
        self._parent = None   # set by a parent's AddChild/InsertChild
```

In `AddChild`, inside the existing `if isinstance(child, TGPane):` block (~line 83, alongside `_ensure_layout_state()`), add:

```python
            child._parent = self
```

In `InsertChild` (currently only does `self._children.insert(...)`), append after the insert:

```python
        if isinstance(child, TGPane):
            child._parent = self
```

In `DeleteChild`, after rebuilding `self._children`, clear the removed child's back-ref. Replace the body with:

```python
    def DeleteChild(self, child) -> None:
        if isinstance(child, TGPane) and child._parent is self:
            child._parent = None
        self._children = [(c, x, y) for (c, x, y) in self._children if c is not child]
```

In `KillChildren`, clear each child's back-ref before dropping them. Replace the body with:

```python
    def KillChildren(self) -> None:
        for c, _x, _y in self._children:
            if isinstance(c, TGPane) and c._parent is self:
                c._parent = None
        self._children.clear()
```

Add the method next to `IsVisible` (~line 140):

```python
    def IsCompletelyVisible(self) -> int:
        """RE-faithful: this pane AND every ancestor visible (bit 10 in BC).

        Degrades to own visibility when there is no tracked TGPane parent —
        correct for our headless tree, where ancestors above SDK widgets are
        either synthetic-always-visible or absent.
        """
        if not self._visible:
            return 0
        parent = self._parent
        if isinstance(parent, TGPane):
            return parent.IsCompletelyVisible()
        return 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tg_pane_completely_visible.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Fix the stale `_Stub` docstring**

In `App.py`, replace the `_Stub` docstring (lines 1998-2001):

```python
    """Returned for any App attribute not yet implemented.

    Falsy so that `if pShip:` guards behave correctly when the object
    hasn't been set up — surfaces missing implementations rather than
    silently proceeding with stub data.
    """
```

with:

```python
    """Returned for any App attribute not yet implemented.

    TRUTHY (``__bool__`` returns True) and has no ``__eq__``, so ``x == 0``
    is False and ``if x:`` passes — an undefined name sails through guards
    rather than reading as absent. That is the truthiness trap the stub
    telemetry records; it is NOT falsy. Numeric coercion (`int()`/`float()`)
    collapses to 0. See docs/stub_heatmap.md.
    """
```

- [ ] **Step 6: Verify no regression across the widget/UI suites**

Run: `uv run pytest tests/unit/test_tg_ui_power_widgets.py tests/unit/test_tg_pane_completely_visible.py tests/ui -q`
Expected: PASS (no failures introduced by the `_parent`/method change).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/tg_ui/widgets.py App.py tests/unit/test_tg_pane_completely_visible.py
git commit -m "feat(ui): faithful TGPane.IsCompletelyVisible chain-walk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Drive `EngPowerDisplay` visibility from the engineering-open signal

**Files:**
- Modify: `engine/appc/tg_ui/eng_power.py` (module-level hook + `EngPowerDisplay.IsCompletelyVisible` override)
- Modify: `engine/host_loop.py:5965-5970` (register the hook next to the CEF panel)
- Modify: `tests/conftest.py` (clear the hook in the autouse leak-reset)
- Test: `tests/unit/test_power_display_visibility_gate.py` (create)

**Interfaces:**
- Consumes: `TGPane.IsCompletelyVisible` (Task 1).
- Produces:
  - `eng_power.set_engineering_open_check(fn: Optional[Callable[[], bool]]) -> None` — register/clear the module-level signal.
  - `EngPowerDisplay.IsCompletelyVisible() -> int` — `1` iff the registered check returns truthy; falls back to `TGPane.IsCompletelyVisible()` when no check is registered.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_power_display_visibility_gate.py`:

```python
"""EngPowerDisplay visibility gates Bridge.PowerDisplay.Update -> AdjustPower.

The engine-side conduit draw is the real power governor; AdjustPower is BC's
UI-side auto-rebalance and must run only while the engineering display is up
(or on a forced Update(1)).  See the 2026-07-17 spec.
"""
import App
import Bridge.PowerDisplay as PD
from engine.appc.subsystems import PowerSubsystem
from engine.appc.properties import PowerProperty
from engine.appc.tg_ui import eng_power
from engine.appc.tg_ui.eng_power import EngPowerDisplay


def _player():
    ship = App.ShipClass_Create("GateShip")
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(250000.0)
    prop.SetBackupBatteryLimit(80000.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    for s in (ship.GetImpulseEngineSubsystem(), ship.GetPhaserSystem(),
              ship.GetTorpedoSystem(), ship.GetPulseWeaponSystem()):
        if s:
            s.SetNormalPowerPerSecond(50.0)
            s.TurnOn()
    return ship


def _wired_display():
    ship = _player()
    App.Game_SetCurrentPlayer(ship)
    pd = EngPowerDisplay(400.0, 200.0)
    PD.Init(pd)                      # builds children (needs a current player)
    PD.g_idPowerDisplay = pd.GetObjID()
    return pd


def test_completely_visible_true_when_engineering_open(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: True)
    assert pd.IsCompletelyVisible() == 1


def test_completely_visible_false_when_engineering_closed(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: False)
    assert pd.IsCompletelyVisible() == 0


def test_update_skips_adjustpower_when_closed(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: False)
    calls = []
    monkeypatch.setattr(PD, "AdjustPower", lambda systems: calls.append(1))
    PD.Update()                      # unforced
    assert calls == []               # visibility gate fired


def test_update_runs_adjustpower_when_open(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: True)
    calls = []
    monkeypatch.setattr(PD, "AdjustPower", lambda systems: calls.append(1))
    PD.Update()
    assert calls == [1]              # gate open -> rebalance runs


def test_forced_update_runs_adjustpower_even_when_closed(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: False)
    calls = []
    monkeypatch.setattr(PD, "AdjustPower", lambda systems: calls.append(1))
    PD.Update(1)                     # bForce punches through
    assert calls == [1]


def test_no_check_falls_back_to_base_visibility(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(None)
    # Fallback = TGPane chain-walk; the display's own _visible defaults True.
    assert pd.IsCompletelyVisible() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_power_display_visibility_gate.py -v`
Expected: FAIL — `eng_power.set_engineering_open_check` does not exist (`AttributeError`), and `IsCompletelyVisible()` currently returns a truthy `_Stub` for the closed case.

- [ ] **Step 3: Add the module-level hook and the override**

In `engine/appc/tg_ui/eng_power.py`, add near the singletons block (after `_power_display_singleton = None`, ~line 37):

```python
# Host-registered signal: True while the Engineering crew menu is the open
# top-level station menu.  EngPowerDisplay.IsCompletelyVisible() consults it so
# BC's per-tick AdjustPower runs only while the display is on screen.  Module
# level (not per-instance) because the SDK recreates the display singleton on
# every bridge load, while the host registers this once at boot.
_engineering_open_check = None


def set_engineering_open_check(fn) -> None:
    """Register (or clear with None) the engineering-menu-open predicate."""
    global _engineering_open_check
    _engineering_open_check = fn
```

Extend `_reset_eng_power_singletons` — leave the check ALONE there (it is a boot-registered host hook, not per-mission state; clearing it on a bridge reload would let AdjustPower run every tick again). Add a clarifying comment only:

```python
def _reset_eng_power_singletons() -> None:
    global _power_ctrl_singleton, _power_display_singleton
    _power_ctrl_singleton = None
    _power_display_singleton = None
    # NOTE: _engineering_open_check is intentionally NOT reset here — it is a
    # boot-time host registration that must survive bridge reloads.
```

Add the override to `EngPowerDisplay` (after `GetConceptualParent`, ~line 110):

```python
    def IsCompletelyVisible(self) -> int:
        """On screen iff the Engineering crew menu is open.

        The engineering-open signal encodes this widget's ancestor context
        (the display lives inside the Engineering pane, visible only when that
        menu is up), so it stands in for the base chain-walk.  Falls back to
        TGPane's own-visibility walk when no host check is registered (bare
        unit contexts).
        """
        if _engineering_open_check is not None:
            return 1 if _engineering_open_check() else 0
        return super().IsCompletelyVisible()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_power_display_visibility_gate.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Register the hook from the host loop**

In `engine/host_loop.py`, immediately after the panel construction block (currently lines 5965-5970, right after `registry.register(engineering_power_panel)`), add:

```python
        # Gate BC's per-tick power-display auto-rebalance on the SAME signal the
        # CEF panel uses: AdjustPower runs only while Engineering is the open
        # station menu (docs/superpowers/specs/2026-07-17-iscompletelyvisible-faithful-design.md).
        from engine.appc.tg_ui import eng_power as _eng_power
        _eng_power.set_engineering_open_check(_engpower_is_engineering_open)
```

- [ ] **Step 6: Clear the hook in the conftest leak-reset**

In `tests/conftest.py`, inside the autouse `_reset_leakable_engine_globals` fixture, add (near the other UI-singleton resets):

```python
    try:
        from engine.appc.tg_ui import eng_power as _eng_power
        _eng_power.set_engineering_open_check(None)
    except Exception:
        pass
```

- [ ] **Step 7: Re-run the gate test in isolation to confirm no cross-test leak**

Run: `uv run pytest tests/unit/test_power_display_visibility_gate.py tests/unit/test_engineering_power_panel.py tests/unit/test_tg_ui_power_widgets.py -q`
Expected: PASS (the conftest reset keeps `_engineering_open_check` from leaking between tests).

- [ ] **Step 8: Commit**

```bash
git add engine/appc/tg_ui/eng_power.py engine/host_loop.py tests/conftest.py tests/unit/test_power_display_visibility_gate.py
git commit -m "feat(power): gate PowerDisplay auto-rebalance on engineering-open

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Full gate + heatmap regression note

**Files:**
- Modify: `docs/stub_heatmap.md` (annotate the resolved entry, if the doc's format has a notes column)

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: nothing (verification + doc).

- [ ] **Step 1: Run the full machine-checked gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. Any failure it names that is not in `tests/known_failures.txt` (the 7 headless-GL scorch/heat-glow `FrameTest`s) is a regression this change introduced — fix it before proceeding. Do NOT hand-wave a failure as "pre-existing"; the gate is the arbiter.

- [ ] **Step 2: Annotate the heatmap entry**

In `docs/stub_heatmap.md`, the `EngPowerDisplay | IsCompletelyVisible` row (rank ~4) now has a real implementation. Add a note in its trailing notes cell (the empty `|  |` at the end of that row):

```
| 4 | EngPowerDisplay | IsCompletelyVisible | 4997 | 24/47 | 2026-07-16 06:01 UTC | RESOLVED 2026-07-17: faithful TGPane chain-walk + engineering-open gate (spec 2026-07-17-iscompletelyvisible-faithful) |
```

(The heatmap is regenerated by `tools/stub_heatmap.py`; this hand-note is a breadcrumb, not the source of truth — the hit count drops once telemetry is re-collected because the name resolves to a real method instead of `_Stub`.)

- [ ] **Step 3: Commit**

```bash
git add docs/stub_heatmap.md
git commit -m "docs(heatmap): note IsCompletelyVisible resolved

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand off for live verification**

Report to Mark that the change is code-complete and gated, and that he verifies live himself. The observable delta (from the spec): with Engineering **closed**, subsystems keep their full *requested* power percentage under a bandwidth deficit (the conduit draw starves them at the grid); with Engineering **open**, `AdjustPower` rebalances the requested percentages downward. The real power economy — battery/conduit depletion, ship speed, weapon starvation — should look identical either way.

---

## Self-Review Notes

- **Spec coverage:** §1 mechanism → Task 1; §2 blast-radius (unchanged callers) → covered by Task 1's int-return + Task 3 gate (the six other callers exercised by their existing suites); §3 pull-model state driving → Task 2; §4 `_Stub` docstring → Task 1 Step 5; Testing → Tasks 1-2 tests; Live verification → Task 3 Step 4.
- **Type consistency:** `IsCompletelyVisible` returns `int` in both `TGPane` (Task 1) and the `EngPowerDisplay` override (Task 2); `set_engineering_open_check` name identical in eng_power (Step 3), host_loop (Step 5), and conftest (Step 6).
- **No placeholders:** every code step shows the exact code; every run step names the command and expected result.
