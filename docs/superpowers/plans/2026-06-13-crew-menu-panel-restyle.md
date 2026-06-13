# Crew Menu Panel Restyle + Layout Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The open crew menu renders as a `.bc-panel` (matching ship-display / target-list chrome and row styling) mounted as the first child of `#tactical-target-stack`, with inline accordion submenus whose expand-state is Python-owned.

**Architecture:** Per the spec ([2026-06-13-crew-menu-panel-restyle-design.md](../specs/2026-06-13-crew-menu-panel-restyle-design.md)). Python (`CrewMenuPanel`) gains an `_expanded_ids` set and an `expand:<id>` dispatch branch, mirroring the target list's Python-owned `expanded` flag. The front-end trio (index.html reparent, crew_menus.css rewrite to the salmon LCARS palette + target-list row vocabulary, crew_menus.js rewrite to emit bc-panel structure with recursive accordion rows) lands together since a half-applied state renders broken.

**Tech Stack:** Python shims + pytest focused subsets ONLY (full suite OOMs — >100 GB RAM; use `.venv/bin/python -m pytest <files>` if `uv run` hangs on the lock). CEF assets are read from `native/assets/ui-cef/` at runtime — no rebuild needed for HTML/CSS/JS, just relaunch `./build/dauntless`.

**Branch:** continue on the current `feat/bridge-menu-hotkeys` branch (this is a continuation of the same crew-menu feature, not yet merged). Commit directly to it.

**Key verified facts (do not re-derive):**
- `engine/ui/crew_menu_panel.py` current shape: `__init__` has `_widgets_by_id` and `_open_menu_id` (line 31/33); `render_payload` (39) builds top-level nodes and sets `node["open"]`; `_snapshot_node` (53) sets `{id,type,label,enabled,visible}` and, for `STMenu`, `children`; `dispatch_event` (75) has `toggle:` then `click:` branches then `return False`; `toggle_menu` (118) early-returns on non-STMenu/disabled then flips `_open_menu_id`; `close_open_menu` (132) and `invalidate` (140) reset `_open_menu_id`.
- Leaf `click:` path (102-113) does `SendActivationEvent()` + `ET_ST_BUTTON_CLICKED` — KEEP byte-identical.
- `test_crew_menu_panel.py` has helper `_build_helm_with_button()` (Helm `STTopLevelMenu` + an "All Stop" `STButton` child added to the TCW) and imports `json`, `App`, `TacticalControlWindow`, `CrewMenuPanel`, `ensure_widget_id`, `STTopLevelMenu`/`STButton` (from engine.appc.characters).
- `STMenu.AddChild(child)` appends to `_children`; `STMenu` has `GetLabel/IsEnabled/IsVisible`. A submenu is just an `STMenu` (or `STTopLevelMenu`) added as a child of another menu.
- index.html: `<div id="crew-menu-bar"></div>` sits after the sdk-mirror slots near the bottom; `#tactical-target-stack` (inside `#tactical-left-column`) currently holds `#ship-display-target` then `#target-list-panel`. crew_menus.css/js are linked.
- `.bc-panel__header`/`.bc-panel__body` are global selectors defined in `panels/ship_display/ship_display.css` (loaded before crew_menus.css); palette tokens `--bc-menu1-base` (rgb 216,94,86), `--bc-body-bg`, `--bc-label-text` are in `:root` via target_list.css (loaded before crew_menus.css). Reuse both.

---

### Task 1: Python — accordion expand-state in CrewMenuPanel

**Files:**
- Modify: `engine/ui/crew_menu_panel.py`
- Test: `tests/unit/test_crew_menu_panel.py` (append)

- [ ] **Step 1: Write the failing tests (append; reuse existing imports + `_build_helm_with_button`)**

```python
def _build_helm_with_submenu():
    """Helm top-level menu with a 'Set Course' submenu that has one child."""
    from engine.appc.characters import STTopLevelMenu, STMenu, STButton
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    setcourse = STMenu("Set Course")
    setcourse.AddChild(STButton("Sol System"))
    helm.AddChild(setcourse)
    tcw.AddMenuToList(helm)
    return helm, setcourse


def test_expand_toggles_node_and_flag():
    helm, setcourse = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)               # open Helm
    panel.render_payload()                # build _widgets_by_id
    sc_id = ensure_widget_id(setcourse)

    assert panel.dispatch_event(f"expand:{sc_id}") is True
    data = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    setcourse_node = data["menus"][0]["children"][0]
    assert setcourse_node["expanded"] is True
    assert setcourse_node["children"][0]["label"] == "Sol System"

    assert panel.dispatch_event(f"expand:{sc_id}") is True   # collapse
    data = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    assert data["menus"][0]["children"][0]["expanded"] is False


def test_expand_stale_and_malformed_dropped():
    helm, _ = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)
    panel.render_payload()
    assert panel.dispatch_event("expand:999999") is True   # stale
    assert panel.dispatch_event("expand:nope") is True      # malformed


def test_closing_menu_clears_expanded():
    helm, setcourse = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)
    panel.render_payload()
    panel.dispatch_event(f"expand:{ensure_widget_id(setcourse)}")
    assert panel._expanded_ids
    panel.toggle_menu(helm)               # close → expansion resets
    assert not panel._expanded_ids


def test_invalidate_clears_expanded():
    helm, setcourse = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)
    panel.render_payload()
    panel.dispatch_event(f"expand:{ensure_widget_id(setcourse)}")
    panel.invalidate()
    assert not panel._expanded_ids
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -k "expand or clears_expanded" -v`
Expected: FAIL — `_expanded_ids` attribute missing / `expand:` returns False / no `expanded` key.

- [ ] **Step 3: Implement in `engine/ui/crew_menu_panel.py`**

(a) In `__init__`, after `self._open_menu_id: Optional[int] = None`:

```python
        # Inline accordion expand-state for submenu rows — Python-owned,
        # mirroring TargetListView's per-row `expanded` flag. Cleared
        # whenever the open menu changes (a reopened menu starts collapsed,
        # matching BC).
        self._expanded_ids: set[int] = set()
```

(b) In `_snapshot_node`, inside the `if isinstance(widget, STMenu):` block, add the `expanded` flag alongside `children`:

```python
        if isinstance(widget, STMenu):
            node["expanded"] = wid in self._expanded_ids
            children = [self._snapshot_node(c) for c in widget._children]
            node["children"] = [c for c in children if c is not None]
        return node
```

(c) In `dispatch_event`, add an `expand:` branch **before** the `toggle:` branch:

```python
    def dispatch_event(self, action: str) -> bool:
        if action.startswith("expand:"):
            try:
                wid = int(action[len("expand:"):])
            except ValueError:
                _logger.info("crew-menu: malformed expand action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                _logger.info("crew-menu: stale expand id %d dropped", wid)
                return True
            if isinstance(widget, STMenu):
                if wid in self._expanded_ids:
                    self._expanded_ids.discard(wid)
                else:
                    self._expanded_ids.add(wid)
            return True
        if action.startswith("toggle:"):
            ... existing toggle body unchanged ...
```

(d) In `toggle_menu`, after the `_open_menu_id` reassignment line, clear expansion:

```python
        wid = ensure_widget_id(menu)
        self._open_menu_id = None if self._open_menu_id == wid else wid
        # Open menu changed (toggle always closes or switches) — a reopened
        # menu starts with all submenus collapsed.
        self._expanded_ids.clear()
```

(e) In `close_open_menu`, before `return True`, add `self._expanded_ids.clear()`.

(f) In `invalidate`, after `self._open_menu_id = None`, add `self._expanded_ids.clear()`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -v`
Expected: all PASS (existing 17 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_panel.py tests/unit/test_crew_menu_panel.py
git commit -m "feat(crew-menu): Python-owned submenu accordion expand-state"
```

---

### Task 2: Front-end — reparent, panel chrome, accordion rows

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Rewrite: `native/assets/ui-cef/css/crew_menus.css`
- Modify: `native/assets/ui-cef/js/crew_menus.js`

No Python test (HTML/CSS/JS); guarded by Task 1's tests staying green and the Task 3 visual check. These three land in one commit — a half-applied state renders broken.

- [ ] **Step 1: index.html — remove the old mount, add the new one**

Delete this block near the bottom (after the sdk-mirror slots):

```html
    <!-- Crew-menu bar — top-left menu strip driven by CrewMenuPanel.
         Receives setCrewMenus({menus:[...]}) from Python; button clicks
         fire dauntlessEvent("crew-menu/click:<id>"). -->
    <div id="crew-menu-bar"></div>
```

Insert as the **first child** of `#tactical-target-stack`, immediately before
`<section class="bc-panel ship-display" id="ship-display-target" ...>`:

```html
        <!-- Crew-menu panel — officer/tactical menus summoned by F1-F5
             (CrewMenuPanel). Empty until a menu is open; renders one
             .bc-panel matching the target panels below it. Spec:
             docs/superpowers/specs/2026-06-13-crew-menu-panel-restyle-design.md -->
        <div id="crew-menu-host"></div>
```

- [ ] **Step 2: crew_menus.css — full rewrite**

Replace the entire file with:

```css
/* Crew menu panel — officer/tactical menus (F1-F5), rendered by
   CrewMenuPanel into #crew-menu-host (first child of #tactical-target-stack).
   Matches the shared tactical panel chrome: .bc-panel header/body (salmon
   LCARS gradient, near-opaque body, Antonio font) plus target-list row
   styling. Only the open menu renders; the host collapses to zero height
   when nothing is open. Spec:
   docs/superpowers/specs/2026-06-13-crew-menu-panel-restyle-design.md */

#crew-menu-host {
  width: 100%;
  font-family: "Antonio", "Antonio-Regular", sans-serif;
  font-weight: 600;
  color: var(--bc-label-text);
  -webkit-font-smoothing: antialiased;
}

/* .crew-menu is a .bc-panel — header/body chrome inherited from the
   global bc-panel classes (panels/ship_display/ship_display.css). */
.crew-menu { width: 100%; }

/* Body rows mirror target-list row styling (.target-list__row / __sub /
   __leaf). Crew rows carry no affiliation colour, so hover uses a neutral
   tint of --bc-menu1-base. */
.crew-menu__row {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
  letter-spacing: 0.04em;
}

.crew-menu__row:hover { background: rgba(216, 94, 86, 0.18); }

.crew-menu__row[data-depth="1"] { padding-left: 28px; }
.crew-menu__row[data-depth="2"] { padding-left: 44px; }

.crew-menu__row.disabled { opacity: 0.4; cursor: default; }
.crew-menu__row.disabled:hover { background: transparent; }

/* Caret matches .target-list__caret — neutral white, glyph swapped in JS
   (no CSS rotate; rotation promotes the caret to its own GPU layer in CEF
   and blurs adjacent text). */
.crew-menu__caret {
  flex: 0 0 auto;
  width: 14px;
  text-align: center;
  margin-right: 8px;
  line-height: 1;
  color: white;
}

/* Leaf rows have no caret — pad the label to align with carried rows. */
.crew-menu__row--leaf .crew-menu__label { margin-left: 22px; }

.crew-menu__label { flex: 1 1 auto; }
```

- [ ] **Step 3: crew_menus.js — rewrite render fns**

Replace the entire file with:

```javascript
// CrewMenuPanel renderer — officer/tactical menus (F1-F5).
// Payload: {menus:[{id,type,label,enabled,visible,open,expanded,children:[...]}]}
// Invoked by the C++ CEF host as setCrewMenus(payload) (payload is a JS
// object, matching the setSdkMirror convention).
//
// Only the OPEN menu renders, as one .bc-panel mounted in #crew-menu-host
// (first child of #tactical-target-stack). No persistent bar: the host is
// empty until a menu is summoned. Submenus expand inline as indented
// accordion rows; expand-state is Python-owned (crew-menu/expand:<id>).
// Leaf buttons fire crew-menu/click:<id>. The payload carries every menu so
// widget ids stay stable for dispatch.

function setCrewMenus(payload) {
  const host = document.getElementById("crew-menu-host");
  if (!host) return;
  host.innerHTML = "";
  for (const menu of payload.menus) {
    if (!menu.open) continue;
    host.appendChild(renderCrewMenu(menu));
  }
}

function renderCrewMenu(menu) {
  const panel = document.createElement("section");
  panel.className = "bc-panel crew-menu";

  const header = document.createElement("header");
  header.className = "bc-panel__header";
  const title = document.createElement("span");
  title.className = "bc-panel__title";
  title.textContent = menu.label;
  header.appendChild(title);
  panel.appendChild(header);

  const body = document.createElement("div");
  body.className = "bc-panel__body";
  appendCrewRows(body, menu.children || [], 0);
  panel.appendChild(body);
  return panel;
}

// Append rows for `nodes` at `depth`, recursing into expanded submenus.
function appendCrewRows(body, nodes, depth) {
  for (const node of nodes) {
    if (node.visible === false) continue;
    const hasChildren = node.type === "menu" && (node.children || []).length > 0;

    const row = document.createElement("div");
    row.className = "crew-menu__row" + (node.enabled ? "" : " disabled") +
                    (hasChildren ? "" : " crew-menu__row--leaf");
    row.setAttribute("data-depth", String(Math.min(depth, 2)));

    if (hasChildren) {
      const caret = document.createElement("span");
      caret.className = "crew-menu__caret";
      caret.textContent = node.expanded ? "▾" : "▸";   // ▾ / ▸
      row.appendChild(caret);
    }

    const label = document.createElement("span");
    label.className = "crew-menu__label";
    label.textContent = node.label;
    row.appendChild(label);

    if (node.enabled) {
      if (hasChildren) {
        row.onclick = () => dauntlessEvent("crew-menu/expand:" + node.id);
      } else if (node.type === "button") {
        row.onclick = () => dauntlessEvent("crew-menu/click:" + node.id);
      }
    }
    body.appendChild(row);

    if (hasChildren && node.expanded) {
      appendCrewRows(body, node.children, depth + 1);
    }
  }
}
```

- [ ] **Step 4: Verify Python side still green + no stale references**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -q`
Expected: all pass (JS/CSS/HTML untouched by Python tests).

Run: `grep -n "crew-menu-bar\|crew-menu-title\|crew-menu-drop\|crew-menu-sub\|crewMenuOpenId" native/assets/ui-cef/index.html native/assets/ui-cef/css/crew_menus.css native/assets/ui-cef/js/crew_menus.js`
Expected: NO output (all old identifiers gone).

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/css/crew_menus.css native/assets/ui-cef/js/crew_menus.js
git commit -m "feat(crew-menu): bc-panel chrome + accordion rows in the left column"
```

---

### Task 3: Regression sweep + visual verification + finishing

**Files:** none (verification only)

- [ ] **Step 1: Feature-wide regression sweep**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py tests/unit/test_crew_menu_hotkeys.py tests/unit/test_fkey_input_chain.py tests/unit/test_fkey_poll.py tests/unit/test_reset_sdk_globals_menus.py tests/integration/test_bridge_menu_hotkeys.py tests/integration/test_bridge_menu_activation.py tests/integration/test_crew_menu_round_trip.py tests/host/test_host_loop_unit.py -q`
Expected: ALL pass. The payload still carries every menu and widget ids are
stable, so the hotkey/activation/round-trip suites are unaffected by the
render change.

- [ ] **Step 2: Visual verification (no rebuild — assets read from disk)**

```bash
./build/dauntless > /tmp/dauntless_restyle.log 2>&1 &
```

Wait for `first OnPaint` in the log, then confirm `grep -c "CreateMenus failed\|crew-menu" /tmp/dauntless_restyle.log` shows no errors.

⚠️ HARD RULE (memory: no-desktop-interaction-during-verification): do NOT
synthesize key/mouse events. Ask Mark to press F1–F5 and report, or rely on
the log + tests. Evidence = log lines; delete any screen capture that catches
non-dauntless windows. Expected when Mark presses F1: the Helm panel appears
as the top item in the left column (above the target list when one is shown),
in identical salmon-LCARS chrome; a submenu row expands inline indented on
click; ESC/F1 closes it and the column collapses back.

- [ ] **Step 3: Use superpowers:finishing-a-development-branch**

This completes the whole crew-menu feature line (widget tree → activation →
hotkeys → restyle) accumulated on `feat/bridge-menu-hotkeys`.
