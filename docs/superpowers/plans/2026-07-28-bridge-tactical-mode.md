# Bridge Tactical Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the player opens the Tactical officer's menu on the bridge (F2), show the full tactical HUD plus the Orders/Tactics/Maneuvers command panes, SDK-faithfully and menu-gated, with issued orders visibly changing the ship's AI behavior.

**Architecture:** A per-tick `bridge_tactical_active` flag (bridge view AND the open crew menu's label == "Tactical") relaxes the exterior-only HUD visibility gate to re-show the five existing tactical panels on the bridge. A one-class fix in our shim (`OptimizedFireScript`) removes the `isinstance` TypeError that silently kills every player order except Stop. A new `TacticalOrdersPanel` projects the SDK's Orders/Tactics/Maneuvers widget tree to CEF (mirroring `TargetListView` over `STTargetMenu`), routing clicks back through the SDK's own `ET_MANEUVER` buttons.

**Tech Stack:** Python 3 (engine + SDK shims), CEF (HTML/CSS/JS panels), pytest + ctest. This feature is **pure Python + CEF assets — no native/C++ rebuild** (CEF JS/CSS/HTML load from source at runtime).

## Global Constraints

- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). Never call a failure "pre-existing" by eyeball. `scripts/run_tests.sh` is pytest-only and will not see C++ — do not rely on it as the gate.
- **Shared checkout — NEVER run destructive git.** No `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`/`git add .`. Always stage with an explicit pathspec. To probe-mutate a file, back up with `cp` and restore with `cp` (never git).
- **Commit trailer:** end every commit message with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **host_io façade:** never call `_dauntless_host` directly; in tests patch `host_io._h`.
- **Units:** anything spatial is game units (GU); vars are `*_gu`/`*_gups`. (Not central to this feature, but honor it if you touch ranges.)
- **Branch:** all work lands on `feat/bridge-tactical-mode` (already created; the spec commit is `b031c99f`). Do not branch again; do not merge to main without the gate green.
- **Faithfulness:** the SDK scripts under `sdk/Build/scripts/` are ground truth and must NOT be edited. All fixes live in our shims (`engine/`, root `App.py`) or CEF assets.

---

### Task 1: Bridge-tactical mode flag + HUD visibility gate

Re-show the five existing tactical panels (`target_list_view`, `sensors_panel`, `ship_display_player`, `ship_display_target`, `weapons_display`) on the bridge while the Tactical crew menu is open. Pure Python; no panel changes.

**Files:**
- Modify: `engine/host_loop.py` — `_tactical_hud_visible` (`1993-2000`) and the visibility block (`6494-6503`).
- Test: `tests/unit/test_tactical_hud_visible.py` (create).

**Interfaces:**
- Consumes: `view_mode.is_bridge` / `view_mode.is_exterior` (existing `_ViewModeController`); `crew_menu_panel.open_menu_label()` → `Optional[str]` (returns `"Tactical"` when the Tactical station menu is open, `engine/ui/crew_menu_panel.py:416-423`).
- Produces: `_tactical_hud_visible(*, is_exterior, spv_open, cutscene_active, bridge_tactical_active) -> bool` — a new required keyword `bridge_tactical_active`. Any other caller of `_tactical_hud_visible` must pass it.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tactical_hud_visible.py`:

```python
from engine.host_loop import _tactical_hud_visible


def _v(**kw):
    base = dict(is_exterior=False, spv_open=False,
                cutscene_active=False, bridge_tactical_active=False)
    base.update(kw)
    return _tactical_hud_visible(**base)


def test_exterior_shows_hud():
    assert _v(is_exterior=True) is True


def test_plain_bridge_hides_hud():
    assert _v(is_exterior=False) is False


def test_bridge_tactical_shows_hud_on_bridge():
    # F2 on the bridge with the Tactical menu open.
    assert _v(is_exterior=False, bridge_tactical_active=True) is True


def test_spv_hides_hud_even_in_bridge_tactical():
    assert _v(bridge_tactical_active=True, spv_open=True) is False


def test_cutscene_hides_hud_even_in_bridge_tactical():
    assert _v(bridge_tactical_active=True, cutscene_active=True) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tactical_hud_visible.py -v`
Expected: FAIL — `_tactical_hud_visible() got an unexpected keyword argument 'bridge_tactical_active'` (and the bridge-tactical case would be False under the old logic).

- [ ] **Step 3: Add the keyword to `_tactical_hud_visible`**

In `engine/host_loop.py`, change the signature and return (`1993-2000`):

```python
def _tactical_hud_visible(*, is_exterior: bool, spv_open: bool,
                          cutscene_active: bool,
                          bridge_tactical_active: bool = False) -> bool:
    """Whether the tactical HUD (ship displays, sensors, target list,
    weapons) should show this frame. It is an exterior-view element, but is
    ALSO shown on the bridge while the player is in bridge-tactical mode
    (the Tactical officer's menu is open, BC's g_bIsInBridgeTactical). Hidden
    while the Ship Property Viewer owns the frame, and during a cutscene so the
    letterbox frame stays cinematic (BC hides the tactical UI during
    StartCutscene..EndCutscene)."""
    return (is_exterior or bridge_tactical_active) and not spv_open \
        and not cutscene_active
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tactical_hud_visible.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Compute and pass the flag at the call site**

In `engine/host_loop.py`, at the visibility block (`6494-6503`), compute the flag from `view_mode` + `crew_menu_panel` and thread it in:

```python
                from engine.appc.top_window import TopWindow_GetTopWindow
                _bridge_tactical_active = (
                    view_mode.is_bridge
                    and crew_menu_panel.open_menu_label() == "Tactical")
                _tac_visible = _tactical_hud_visible(
                    is_exterior=view_mode.is_exterior,
                    spv_open=ship_property_viewer.is_open(),
                    cutscene_active=TopWindow_GetTopWindow().IsCutsceneMode(),
                    bridge_tactical_active=_bridge_tactical_active)
                target_list_view.visible    = _tac_visible
                sensors_panel.visible       = _tac_visible
                ship_display_player.visible = _tac_visible
                ship_display_target.visible = _tac_visible
                weapons_display.visible     = _tac_visible
```

(`crew_menu_panel` is already a local in this scope — declared at `~6206`, used at `~6420`. `view_mode` is in scope. No new imports beyond the existing `TopWindow_GetTopWindow`.)

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_tactical_hud_visible.py
git commit -m "feat(bridge): show tactical HUD on bridge in bridge-tactical mode

Relax _tactical_hud_visible's exterior-only gate: the five tactical HUD
panels also show on the bridge while the Tactical officer's menu is open
(bridge_tactical_active = is_bridge AND open crew menu label == 'Tactical'),
matching BC's g_bIsInBridgeTactical. Panels are unchanged (view-independent).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: OptimizedFireScript — unblock player orders

Fix the latent `isinstance(pScript, App.OptimizedFireScript)` TypeError at `sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1861` that silently kills every player order except Stop. Define `OptimizedFireScript` as a real class in our shim so `isinstance` returns a proper bool and `StartAI` proceeds to `SetPlayerAI`.

**Files:**
- Modify: `engine/appc/ai.py` — add the `OptimizedFireScript` class (near the other AI script classes, e.g. after `_AIScriptInstance` ~`:240` or near `ConditionScript` ~`:190`).
- Modify: `App.py` — add `OptimizedFireScript` to the `from engine.appc.ai import (...)` list at `:229-238`.
- Test: `tests/unit/test_optimized_fire_script.py` (create).

**Interfaces:**
- Produces: `engine.appc.ai.OptimizedFireScript` — a class (usable as the 2nd arg of `isinstance`), re-exported as `App.OptimizedFireScript`.

**Background (why a bare class is the correct minimal fix):** `pScript` is the object returned by `PreprocessingAI.GetPreprocessingInstance()`, which is the generic `_AIScriptInstance` data-bag (`engine/appc/ai.py:196`). Once `OptimizedFireScript` is a real class, `isinstance(databag, OptimizedFireScript)` returns `False` without raising, the loop finishes, and `SetPlayerAI` (`TacticalMenuHandlers.py:1872`) installs the AI — so the ship maneuvers per the order. Engaging weapons fire (`CheckFiring`, the `True` branch) requires our fire preprocessor to actually BE an `OptimizedFireScript`; that is the deferred combat-fidelity follow-up (out of scope per the spec) and is left as a `# TODO(combat-fidelity)` marker, not implemented here.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_optimized_fire_script.py`:

```python
import App
import engine.appc.ai as ai


def test_optimized_fire_script_is_a_class():
    # Must be usable as the 2nd argument of isinstance (a type), not a
    # _NamedStub instance — the bug at TacticalMenuHandlers.py:1861.
    assert isinstance(ai.OptimizedFireScript, type)


def test_app_exposes_optimized_fire_script_as_a_type():
    assert isinstance(App.OptimizedFireScript, type)


def test_isinstance_against_app_optimized_fire_script_does_not_raise():
    # Reproduces the crash: before the fix, App.OptimizedFireScript is a
    # _NamedStub *instance*, so this line raised TypeError inside StartAI.
    assert isinstance(object(), App.OptimizedFireScript) is False


def test_generic_ai_script_instance_is_not_a_fire_script():
    # The data-bag GetPreprocessingInstance returns is (correctly) not a
    # fire script — so StartAI's fire branch is skipped, but SetPlayerAI runs.
    databag = ai._AIScriptInstance(ai=None)
    assert isinstance(databag, App.OptimizedFireScript) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_optimized_fire_script.py -v`
Expected: FAIL — `AttributeError: module 'engine.appc.ai' has no attribute 'OptimizedFireScript'`, and the `App.` cases raise `TypeError: isinstance() arg 2 must be a type...`.

- [ ] **Step 3: Define the class in `engine/appc/ai.py`**

Add near the other script classes (e.g. just after `_AIScriptInstance`):

```python
class OptimizedFireScript:
    """Type identity for BC's C++ fire-control preprocessor script.

    BC's Appc exposes an ``OptimizedFireScript`` class; StartAI
    (sdk/.../Bridge/TacticalMenuHandlers.py:1861) does
    ``isinstance(pPreAI.GetPreprocessingInstance(), App.OptimizedFireScript)``
    to decide whether an AI node is a weapons-fire preprocessor and, if so,
    enable firing via CheckFiring. Without a real class here that isinstance
    call raised TypeError (App.OptimizedFireScript resolved to a _NamedStub
    *instance*), aborting StartAI before SetPlayerAI for every order whose AI
    tree contains a PreprocessingAI — i.e. everything except Stop.

    Headless Phase 1 returns the generic _AIScriptInstance data-bag from
    GetPreprocessingInstance, so no node is currently an instance of this
    class: the isinstance check is False, the fire branch is skipped, and the
    AI still installs (the ship maneuvers per the order).

    TODO(combat-fidelity): to make player 'Attack' actually engage weapons,
    have the fire preprocessor's GetPreprocessingInstance return an
    OptimizedFireScript instance so the CheckFiring branch runs. Deferred.
    """
    pass
```

- [ ] **Step 4: Re-export via the App module**

In `App.py`, extend the `from engine.appc.ai import (...)` block (`:229-238`) to include `OptimizedFireScript`, e.g. on the `PreprocessingAI` line:

```python
    PreprocessingAI, PreprocessingAI_Create, PreprocessingAI_Cast,
    OptimizedFireScript,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_optimized_fire_script.py -v`
Expected: PASS (all 4).

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/ai.py App.py tests/unit/test_optimized_fire_script.py
git commit -m "fix(ai): define OptimizedFireScript so player orders install an AI

App.OptimizedFireScript was an undefined _NamedStub instance, so the
isinstance() at TacticalMenuHandlers.py:1861 raised TypeError and aborted
StartAI before SetPlayerAI for every order except Stop (silently swallowed
at the button-click boundary). Defining it as a real class lets isinstance
return a proper bool; the AI now installs and the ship maneuvers per order.
Weapon-fire (CheckFiring) engagement is a tracked combat-fidelity follow-up.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: TacticalOrdersPanel — project Orders/Tactics/Maneuvers to CEF

New CEF panel that projects the SDK's three command panes (built by `CreateOrdersStatusDisplay`, `TacticalMenuHandlers.py:542`) and routes clicks back through the SDK's own `ET_MANEUVER` buttons. Mirrors `TargetListView` (snapshot/render/dispatch) and `CrewMenuPanel` (click → `SendActivationEvent`).

**Files:**
- Create: `engine/ui/tactical_orders_panel.py`
- Create: `native/assets/ui-cef/js/tactical_orders.js`
- Modify: `native/assets/ui-cef/index.html` — add a `#tactical-orders-host` mount in the tactical column; add a `<script src="js/tactical_orders.js">` include.
- Modify: `native/assets/ui-cef/css/` — a `tactical_orders.css` (or append to an existing tactical CSS) for `.bc-panel`-styled panes.
- Modify: `engine/host_loop.py` — construct + register the panel (near the other tactical-panel registrations, `~6197-6231`); set its `.visible` in the visibility block; reset on mission swap where the other panels reset.
- Test: `tests/unit/test_tactical_orders_panel.py` (create).

**Interfaces:**
- Consumes: the three SDK module globals on `Bridge.TacticalMenuHandlers` — `g_pOrdersStatusUI`, `g_pTacticsStatusUIMenu`, `g_pManeuversStatusUIMenu` (set by `CreateOrdersStatusDisplay`; may be absent/None before a bridge load). Each is a widget whose children expose `GetLabel()`/`GetName()`, `IsChosen()`, `IsDisabled()` (or `IsEnabled()`), and `SendActivationEvent()` (the `STButton`/`STMenu` surface in `engine/appc/characters.py`). Also `crew_menu_panel.open_menu_label()` for visibility.
- Produces: `TacticalOrdersPanel(Panel)` with `name == "tactical-orders"`; JS entrypoint `setTacticalOrders({...})`; click event `tactical-orders/click:<row-id>`.

**Sub-step 3a — verify SDK widget construction (Fallback B gate):** Before writing the panel, confirm `CreateOrdersStatusDisplay` runs clean against our shims and the three globals are populated. Run this probe:

```bash
uv run python -c "
import tests.conftest  # installs the SDK finder
import App, Bridge.TacticalMenuHandlers as T
# Minimal: ensure the module imports and the builder's widget deps resolve.
print('STButton_CreateW:', hasattr(App, 'STButton_CreateW'))
print('STCharacterMenu_CreateW:', hasattr(App, 'STCharacterMenu_CreateW'))
print('STSubPane_Create:', hasattr(App, 'STSubPane_Create'))
print('STStylizedWindow_CreateW:', hasattr(App, 'STStylizedWindow_CreateW'))
"
```

If any widget factory is a stub (a `_NamedStub`, i.e. `hasattr` True but calling it returns a stub), the panel projection will see empty/garbage children. In that case implement the missing widget in `engine/appc/characters.py`/`engine/appc/windows.py` to the minimal surface the panel reads (`GetLabel`, `IsChosen`, `IsDisabled`, `SendActivationEvent`, child iteration) — mirroring the existing `STTargetMenu`/`STButton` implementations — and add a focused unit test for it, BEFORE proceeding. Record what you found in the commit message.

- [ ] **Step 1: Write the failing test (panel snapshot + click)**

Create `tests/unit/test_tactical_orders_panel.py`. Use lightweight fakes for the three panes (the panel must not require a full bridge load):

```python
import json
from engine.ui.tactical_orders_panel import TacticalOrdersPanel


class _FakeButton:
    def __init__(self, label, chosen=False, disabled=False):
        self._label, self._chosen, self._disabled = label, chosen, disabled
        self.activated = 0

    def GetLabel(self):     return self._label
    def IsChosen(self):     return self._chosen
    def IsDisabled(self):   return self._disabled
    def SendActivationEvent(self): self.activated += 1


class _FakePane:
    def __init__(self, buttons): self._buttons = buttons
    def _iter_buttons(self):     return list(self._buttons)


def _panel_with(orders, tactics, maneuvers):
    p = TacticalOrdersPanel()
    p._resolve_panes = lambda: (_FakePane(orders),
                                _FakePane(tactics),
                                _FakePane(maneuvers))
    return p


def test_snapshot_projects_all_three_groups():
    stop = _FakeButton("OrderStop", chosen=True)
    destroy = _FakeButton("OrderDestroy")
    atwill = _FakeButton("TacticAtWill", chosen=True)
    left = _FakeButton("TacticLeft", disabled=True)
    m_atwill = _FakeButton("ManeuverAtWill", chosen=True)
    p = _panel_with([destroy, stop], [atwill, left], [m_atwill])
    p.visible = True
    js = p.render_payload()
    assert js is not None and js.startswith("setTacticalOrders(")
    payload = json.loads(js[len("setTacticalOrders("):-2])
    assert payload["visible"] is True
    labels = [r["label"] for r in payload["orders"]]
    assert labels == ["OrderDestroy", "OrderStop"]
    assert payload["orders"][1]["chosen"] is True          # Stop chosen
    assert payload["tactics"][1]["enabled"] is False        # TacticLeft disabled
    assert [r["label"] for r in payload["maneuvers"]] == ["ManeuverAtWill"]


def test_render_is_idempotent():
    p = _panel_with([_FakeButton("OrderStop", chosen=True)], [], [])
    p.visible = True
    assert p.render_payload() is not None
    assert p.render_payload() is None  # unchanged snapshot -> no re-emit


def test_click_activates_the_matching_button():
    destroy = _FakeButton("OrderDestroy")
    p = _panel_with([destroy], [], [])
    assert p.dispatch_event("click:OrderDestroy") is True
    assert destroy.activated == 1


def test_invisible_snapshot_emits_no_rows():
    p = _panel_with([_FakeButton("OrderStop")], [], [])
    p.visible = False
    js = p.render_payload()
    payload = json.loads(js[len("setTacticalOrders("):-2])
    assert payload["visible"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tactical_orders_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.ui.tactical_orders_panel`.

- [ ] **Step 3: Implement the panel**

Create `engine/ui/tactical_orders_panel.py`, mirroring `TargetListView`:

```python
"""CEF view for the tactical Orders/Tactics/Maneuvers command panes.

Projects the three SDK widgets built by Bridge.TacticalMenuHandlers
(CreateOrdersStatusDisplay): g_pOrdersStatusUI, g_pTacticsStatusUIMenu,
g_pManeuversStatusUIMenu. Reads label/chosen/enabled per button each tick and
emits setTacticalOrders({...}); a click resolves the matching SDK button and
calls SendActivationEvent(), which fires the SDK's own ET_MANEUVER event.

Availability (which tactics/maneuvers are enabled) is computed by the SDK's
UpdateOrderMenus from the g_dAIs table and reflected in each button's
IsDisabled()/IsChosen() — we only read it.

Spec:  docs/superpowers/specs/2026-07-28-bridge-tactical-mode-f2-hud-design.md
Plan:  docs/superpowers/plans/2026-07-28-bridge-tactical-mode.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel


class TacticalOrdersPanel(Panel):
    @property
    def name(self) -> str:
        return "tactical-orders"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None

    def _resolve_panes(self):
        """Return (orders_pane, tactics_pane, maneuvers_pane), any of which
        may be None before a bridge load. Overridden in tests."""
        try:
            import Bridge.TacticalMenuHandlers as T
        except Exception:
            return (None, None, None)
        return (getattr(T, "g_pOrdersStatusUI", None),
                getattr(T, "g_pTacticsStatusUIMenu", None),
                getattr(T, "g_pManeuversStatusUIMenu", None))

    @staticmethod
    def _iter_buttons(pane):
        """Yield the clickable child buttons of a pane, tolerant of the
        widget surface. Prefers a helper _iter_buttons (test fakes / future
        widget), else walks GetFirstChild/GetNextChild."""
        if pane is None:
            return []
        if hasattr(pane, "_iter_buttons"):
            return list(pane._iter_buttons())
        out = []
        if hasattr(pane, "GetFirstChild"):
            child = pane.GetFirstChild()
            while child is not None:
                out.append(child)
                child = pane.GetNextChild(child)
        return out

    @staticmethod
    def _row(button) -> dict:
        label = button.GetLabel() if hasattr(button, "GetLabel") else ""
        chosen = bool(button.IsChosen()) if hasattr(button, "IsChosen") else False
        if hasattr(button, "IsDisabled"):
            enabled = not bool(button.IsDisabled())
        elif hasattr(button, "IsEnabled"):
            enabled = bool(button.IsEnabled())
        else:
            enabled = True
        return {"label": label, "id": label, "chosen": chosen, "enabled": enabled}

    def _snapshot(self):
        orders_pane, tactics_pane, maneuvers_pane = self._resolve_panes()
        orders = tuple(self._row(b) for b in self._iter_buttons(orders_pane))
        tactics = tuple(self._row(b) for b in self._iter_buttons(tactics_pane))
        maneuvers = tuple(self._row(b) for b in self._iter_buttons(maneuvers_pane))
        return (self._visible,
                tuple(tuple(sorted(r.items())) for r in orders),
                tuple(tuple(sorted(r.items())) for r in tactics),
                tuple(tuple(sorted(r.items())) for r in maneuvers))

    def render_payload(self) -> Optional[str]:
        orders_pane, tactics_pane, maneuvers_pane = self._resolve_panes()
        orders = [self._row(b) for b in self._iter_buttons(orders_pane)]
        tactics = [self._row(b) for b in self._iter_buttons(tactics_pane)]
        maneuvers = [self._row(b) for b in self._iter_buttons(maneuvers_pane)]
        snap = (self._visible,
                tuple(tuple(sorted(r.items())) for r in orders),
                tuple(tuple(sorted(r.items())) for r in tactics),
                tuple(tuple(sorted(r.items())) for r in maneuvers))
        if snap == self._last_snapshot:
            return None
        self._last_snapshot = snap
        payload = {"visible": self._visible, "orders": orders,
                   "tactics": tactics, "maneuvers": maneuvers}
        return "setTacticalOrders(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if not action.startswith("click:"):
            return False
        label = action[len("click:"):]
        for pane in self._resolve_panes():
            for button in self._iter_buttons(pane):
                if hasattr(button, "GetLabel") and button.GetLabel() == label:
                    if hasattr(button, "SendActivationEvent"):
                        button.SendActivationEvent()
                    return True
        return False

    def invalidate(self) -> None:
        self._last_snapshot = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tactical_orders_panel.py -v`
Expected: PASS (all 4).

- [ ] **Step 5: Add the CEF renderer (JS + mount + CSS)**

Create `native/assets/ui-cef/js/tactical_orders.js`, mirroring `js/crew_menus.js` (label/chosen/enabled → `.bc-panel` rows, click → `dauntlessEvent`):

```javascript
// Renders the tactical Orders / Tactics / Maneuvers command panes.
// Payload: { visible, orders[], tactics[], maneuvers[] }, each row
// { label, id, chosen, enabled }. Mounts into #tactical-orders-host.
function setTacticalOrders(payload) {
  var host = document.getElementById("tactical-orders-host");
  if (!host) return;
  if (!payload || !payload.visible) { host.innerHTML = ""; return; }
  host.innerHTML = "";
  var groups = [["Orders", payload.orders],
                ["Maneuvers", payload.maneuvers],
                ["Tactics", payload.tactics]];
  groups.forEach(function (g) {
    var title = g[0], rows = g[1] || [];
    if (!rows.length) return;
    var section = document.createElement("section");
    section.className = "bc-panel tactical-orders";
    var head = document.createElement("div");
    head.className = "bc-panel__header";
    head.innerHTML = '<span class="bc-panel__title">' + title + "</span>";
    section.appendChild(head);
    var body = document.createElement("div");
    body.className = "bc-panel__body";
    rows.forEach(function (r) {
      var el = document.createElement("div");
      el.className = "tactical-orders__row"
        + (r.chosen ? " is-chosen" : "")
        + (r.enabled ? "" : " is-disabled");
      el.textContent = r.label;
      if (r.enabled) {
        el.addEventListener("click", function () {
          dauntlessEvent("tactical-orders/click:" + r.id);
        });
      }
      body.appendChild(el);
    });
    section.appendChild(body);
    host.appendChild(section);
  });
}
```

In `native/assets/ui-cef/index.html`, add the mount inside the tactical column (near `#tactical-target-stack`) and the script include (near the other panel scripts):

```html
<div id="tactical-orders-host"></div>
...
<script src="js/tactical_orders.js"></script>
```

Add `native/assets/ui-cef/css/tactical_orders.css` (and link it in `index.html`) styling `.tactical-orders`, `.tactical-orders__row`, `.is-chosen`, `.is-disabled` — reuse the `.bc-panel` / `.target-list__row` idiom from `css/crew_menus.css` and `css/global.css`.

- [ ] **Step 6: Register + gate visibility in the host loop**

In `engine/host_loop.py`, construct and register the panel alongside the other tactical panels (`~6197-6231`):

```python
                from engine.ui.tactical_orders_panel import TacticalOrdersPanel
                tactical_orders_panel = TacticalOrdersPanel()
                panel_registry.register(tactical_orders_panel)
```

In the visibility block (Task 1 edit site), set its visibility — shown whenever the Tactical menu is open, in EITHER view (matches SetupBridgeTactical + SetupTacticalTactical), still hidden under SPV/cutscene:

```python
                _tactical_menu_open = crew_menu_panel.open_menu_label() == "Tactical"
                tactical_orders_panel.visible = (
                    _tactical_menu_open
                    and not ship_property_viewer.is_open()
                    and not TopWindow_GetTopWindow().IsCutsceneMode())
```

Reset it where the other tactical panels reset on mission swap (find the block that nulls/rebuilds `target_list_view` et al. and add `tactical_orders_panel.invalidate()` there).

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failures outside `tests/known_failures.txt`.

- [ ] **Step 8: Commit**

```bash
git add engine/ui/tactical_orders_panel.py native/assets/ui-cef/js/tactical_orders.js native/assets/ui-cef/index.html native/assets/ui-cef/css/tactical_orders.css engine/host_loop.py tests/unit/test_tactical_orders_panel.py
git commit -m "feat(bridge): Orders/Tactics/Maneuvers panel projected from SDK widgets

New TacticalOrdersPanel projects Bridge.TacticalMenuHandlers' three command
panes (g_pOrdersStatusUI/g_pTacticsStatusUIMenu/g_pManeuversStatusUIMenu) to
CEF, reading label/chosen/enabled per button (g_dAIs-driven availability comes
free from UpdateOrderMenus) and routing clicks back through the SDK button's
SendActivationEvent (ET_MANEUVER). Shown whenever the Tactical menu is open.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (after all three tasks, on the live app)

Green tests cannot see panel visibility or CEF asset paths. Confirm on the live build (`--developer` → mission picker → a combat mission):

1. On the bridge, press **F2** → the Tactical drop-down raises AND the tactical HUD (radar/target list, player + target shields, weapons) appears, plus the **Orders | Maneuvers | Tactics** panes.
2. Close the menu (ESC / re-press F2 / talk to another officer) → HUD + command panes disappear; clean bridge restored.
3. Select a hostile target, click **Attack/Destroy** → the ship's AI changes (it maneuvers toward/engages the target); **Stop** halts it. (Weapon-fire tuning is a separate follow-up.)
4. With no target, Tactics/Maneuvers rows render disabled; Orders still shown.

## Self-Review

- **Spec coverage:** Component 1 → Task 1; Component 2 → Task 2; Component 3 → Task 3 (incl. Fallback-B widget verification at 3a). Visibility rules (HUD = `is_exterior OR bridge_tactical_active`; Orders panel = Tactical-menu-open, either view) implemented in Task 1 Step 5 and Task 3 Step 6. Edge cases (no target, SPV/cutscene, multiplayer via SDK button state, unknown widget) covered by reading SDK button state + the gate.
- **Type consistency:** `_tactical_hud_visible(..., bridge_tactical_active)` keyword consistent between Task 1 Steps 3 and 5. `open_menu_label() == "Tactical"` used consistently. Panel `name == "tactical-orders"`, event `tactical-orders/click:<id>`, JS `setTacticalOrders` consistent across Task 3.
- **Note for implementer:** the JS in Step 5 builds `header` then `body` per group; the three groups render in Orders → Maneuvers → Tactics order (BC's left-to-right). Style with the shared `.bc-panel` idiom.
