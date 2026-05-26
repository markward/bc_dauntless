# Target List Population Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the demo-ship scaffolding with a real target list that auto-populates from the bridge set, shows each ship's subsystems, reflects sensor visibility, displays hull + shield health bars, and lets the player click a row (or a subsystem) to engage targeting.

**Architecture:** Three concerns layer on top of the existing shim + panel framework:
1. **CEF page-load signal** — replace the startup-frames invalidation workaround with a real `OnLoadEnd` callback so panels re-emit exactly once when the page is ready.
2. **Set-event subscribers** — `SetClass` gains a tiny subscriber API; the engine subscribes the target-menu singleton to the `bridge` set so add/remove events drive `RebuildShipMenu` and row removal automatically. This deletes the demo-ship block.
3. **State-payload extensions** — the `TargetListView` snapshot grows nested subsystem rows, hull/shield percentages, and a `selected_subsystem` field; the JS render mirrors the new shape and the click dispatcher routes `target/<ship>/<subsystem>` actions to `SetTargetSubsystem`.

Sensor visibility uses the existing `STSubsystemMenu.SetVisible()` mechanism — the `TargetListView` already filters by it, so we just need the sensor subsystem to drive the flag.

**Tech Stack:** C++ (CEF lifecycle), Python 3 (engine + tests), vanilla JS + CSS, pytest.

**Explicitly deferred (out of scope, follow-up plans):**
- **Persistent target save/load** — the engine does not yet support save/load at all; restoring the last clicked target across saves becomes relevant once save/load lands. `STTargetMenu.GetPersistentTarget` / `SetPersistentTarget` are already in the shim and can be wired then.
- **Reticule rendering in the 3D scene** — parked separately.
- **Pause menu refactor onto Panel base** — the legacy fallback path is fine.
- **Real localized display names for ships** — we use `ship.GetName()` as the row label. If/when a mission exposes a separate localized hull-class name distinct from the internal name, a later plan can plumb it through. Subsystem labels come from `SubsystemProperty.GetName()` which is already user-readable.

**Spec references:**
- Existing target-list infrastructure: `docs/superpowers/plans/2026-05-25-target-list-shim.md`
- SDK callsites: `Bridge/TacticalMenuHandlers.py`, `TacticalInterfaceHandlers.py`, `MissionLib.py` (HideSubsystems/ShowSubsystems calling `RebuildShipMenu`)
- Existing CEF lifecycle: `native/src/ui_cef/cef_lifecycle.h:25-58`
- Existing event channel: JS `console.info('dauntless-event:<name>')` → C++ `OnConsoleMessage` → Python callback registered via `cef_set_event_handler`
- Shim accessors used by this plan: `ShipClass.StartGetSubsystemMatch`, `ShipSubsystem.GetName`, `ShieldSubsystem.GetShieldPercentage`, `HullSubsystem.GetConditionPercentage`, `SensorSubsystem` (range queries TBD per task), `ShipClass.SetTargetSubsystem`

---

## File Structure

**New files**
- `engine/ui/cef_load_signal.py` — module-level registry for "browser page loaded" callbacks; lets Python subscribers fire once the CEF page is ready. ~30 lines.
- `tests/unit/test_cef_load_signal.py` — unit tests.
- `tests/unit/test_set_subscribers.py` — unit tests for the new `SetClass` subscriber API.
- `tests/unit/test_target_menu_bridge_subscription.py` — tests that target-menu rows track bridge-set add/remove.
- `tests/integration/test_target_list_subsystems.py` — integration test that loads `Bridge.TacticalMenuHandlers.CreateTargetList`, populates real ships with subsystems, and asserts the rendered payload includes nested subsystems with hull/shield bars.

**Modified files**
- `native/src/ui_cef/cef_client.h`, `cef_client.cc` — implement `CefLoadHandler::OnLoadEnd` and route to a `std::function<void()>` callback.
- `native/src/ui_cef/cef_lifecycle.h`, `cef_lifecycle.cc` — add `set_load_end_handler(std::function<void()>)`.
- `native/src/host/host_bindings.cc` — Python binding `cef_set_load_end_handler(callback)`.
- `engine/ui/panel_registry.py` — add `invalidate_all()` method and an abstract `invalidate()` hook on the `Panel` base.
- `engine/ui/panel.py` — add `invalidate()` to `Panel` ABC (default no-op).
- `engine/ui/target_list_view.py` — extend `_snapshot` and `render_payload` for subsystem nesting + health bars + selected_subsystem; extend `dispatch_event` to parse `ship/subsystem` actions.
- `engine/appc/sets.py` — `SetClass.subscribe(callback)` / `unsubscribe`; `AddObjectToSet` and `RemoveObjectFromSet` fire notifications.
- `engine/appc/target_menu.py` — `wire_to_bridge_set()` helper that subscribes the singleton to a given set.
- `engine/appc/ships.py` — add `CT_SHIP_SUBSYSTEM` dispatch to `StartGetSubsystemMatch`.
- `engine/appc/subsystems.py` — `SensorSubsystem.update_target_list_visibility(target_menu, ships)` method that flips `STSubsystemMenu.SetVisible/SetNotVisible` based on range.
- `engine/host_loop.py` — replace the startup-frames hack with a load-end callback that calls `registry.invalidate_all()`; replace the demo-ship block with `wire_to_bridge_set` invocation; call sensor visibility update each tick.
- `native/assets/ui-cef/js/target_list.js` — render nested subsystem rows, hull/shield bars, selected-subsystem highlighting.
- `native/assets/ui-cef/css/target_list.css` — nested-row indentation + bar styling.

---

## Task 1: CEF `OnLoadEnd` C++ hook

**Files:**
- Modify: `native/src/ui_cef/cef_client.h`
- Modify: `native/src/ui_cef/cef_client.cc`

The CEF browser process already implements `CefDisplayHandler::OnConsoleMessage` for JS→Python events. We need to also implement `CefLoadHandler::OnLoadEnd` so we know when `hello.html` finishes loading.

- [ ] **Step 1: Read the current cef_client.h to find where the handler interfaces are listed**

Run: `grep -n "CefDisplayHandler\|CefLoadHandler\|GetDisplayHandler\|GetLoadHandler\|set_event_handler" native/src/ui_cef/cef_client.h native/src/ui_cef/cef_client.cc`

This shows where to add the new handler. The pattern from `set_event_handler` is exactly what to mirror.

- [ ] **Step 2: Edit `cef_client.h` to declare LoadHandler + setter**

In `native/src/ui_cef/cef_client.h`, find the existing `set_event_handler` declaration (around line 72) and add directly after it:

```cpp
    // Load-end handler injection. cef_lifecycle::set_load_end_handler
    // routes here. Fired once when the main frame finishes loading
    // hello.html; panels use this to invalidate their snapshot caches
    // so the first state-push lands AFTER the page is ready.
    void set_load_end_handler(std::function<void()> handler);
```

In the same file, the class lists which CEF interfaces it implements via `IMPLEMENT_REFCOUNTING` and which handler getters it overrides. Find the existing `CefRefPtr<CefDisplayHandler> GetDisplayHandler() override`. Add immediately after:

```cpp
    CefRefPtr<CefLoadHandler> GetLoadHandler() override { return this; }
```

Then make the class inherit `CefLoadHandler` — find the class declaration line (likely `class DauntlessCefClient : public CefClient, public CefDisplayHandler, ...`) and append `, public CefLoadHandler` to the inheritance list.

Add the `OnLoadEnd` override in the public methods section:

```cpp
    // CefLoadHandler — fired when the main frame finishes loading.
    void OnLoadEnd(CefRefPtr<CefBrowser> browser,
                   CefRefPtr<CefFrame> frame,
                   int httpStatusCode) override;
```

And the storage member alongside `_event_handler`:

```cpp
    std::function<void()> _load_end_handler;
```

- [ ] **Step 3: Implement in `cef_client.cc`**

In `native/src/ui_cef/cef_client.cc`, add the setter (mirror the existing `set_event_handler`):

```cpp
void DauntlessCefClient::set_load_end_handler(std::function<void()> handler) {
    _load_end_handler = std::move(handler);
}
```

Implement `OnLoadEnd`. It should only fire for the *main* frame (sub-frames like iframes would re-fire it; we want a single signal per page-load):

```cpp
void DauntlessCefClient::OnLoadEnd(CefRefPtr<CefBrowser> browser,
                                   CefRefPtr<CefFrame> frame,
                                   int httpStatusCode) {
    if (frame && frame->IsMain() && _load_end_handler) {
        _load_end_handler();
    }
}
```

- [ ] **Step 4: Verify build**

Run:
```bash
cmake --build build -j 2>&1 | tail -5
```

Expected: clean build (existing OpenAL/macOS warnings only).

If the build complains about CefLoadHandler not being declared, add `#include "include/cef_load_handler.h"` near the existing CefDisplayHandler include in `cef_client.h`.

- [ ] **Step 5: Commit**

```bash
git add native/src/ui_cef/cef_client.h native/src/ui_cef/cef_client.cc
git commit -m "$(cat <<'EOF'
ui_cef: implement CefLoadHandler::OnLoadEnd on the client

Routes main-frame load-end events to a std::function callback. The
panel layer subscribes via cef_lifecycle::set_load_end_handler (next
commit) so it can invalidate snapshot caches once the page is ready,
replacing the per-frame invalidation workaround currently in
host_loop.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: CEF lifecycle public API for load-end

**Files:**
- Modify: `native/src/ui_cef/cef_lifecycle.h`
- Modify: `native/src/ui_cef/cef_lifecycle.cc`

Expose `set_load_end_handler` at the `dauntless::ui_cef` namespace level so host_bindings.cc can wire it without touching the internal client.

- [ ] **Step 1: Edit `cef_lifecycle.h`**

In `native/src/ui_cef/cef_lifecycle.h`, find the existing `set_event_handler` declaration (line 58). Add directly after it:

```cpp
// Load-end handler injection. Invoked once when the main frame finishes
// loading hello.html (or after Cmd+R reload). Used by the panel layer
// to invalidate per-tick snapshot caches so the first post-load tick
// re-emits state. Pass an empty function to disable.
void set_load_end_handler(std::function<void()> handler);
```

- [ ] **Step 2: Implement in `cef_lifecycle.cc`**

In `native/src/ui_cef/cef_lifecycle.cc`, find the existing `set_event_handler` implementation (around line 218). Add directly after it:

```cpp
void set_load_end_handler(std::function<void()> handler) {
    if (g_client) {
        g_client->set_load_end_handler(std::move(handler));
    }
}
```

- [ ] **Step 3: Verify build**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add native/src/ui_cef/cef_lifecycle.h native/src/ui_cef/cef_lifecycle.cc
git commit -m "$(cat <<'EOF'
ui_cef: expose set_load_end_handler in cef_lifecycle namespace

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Python binding `cef_set_load_end_handler`

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Find the existing `cef_set_event_handler` binding**

Run: `grep -n "cef_set_event_handler" native/src/host/host_bindings.cc`

Confirm two definitions exist (line ~927 for real builds, line ~962 for the no-op fallback when bindings aren't built).

- [ ] **Step 2: Add the new binding alongside both**

In `native/src/host/host_bindings.cc`, around the existing `m.def("cef_set_event_handler", ...)` (line ~927), add immediately after that block:

```cpp
    m.def("cef_set_load_end_handler",
          [](py::function fn) {
              // Hold a strong ref so the callback survives across CEF callbacks.
              auto fn_ptr = std::make_shared<py::function>(std::move(fn));
              dauntless::ui_cef::set_load_end_handler(
                  [fn_ptr]() {
                      py::gil_scoped_acquire gil;
                      try {
                          (*fn_ptr)();
                      } catch (const std::exception& e) {
                          fprintf(stderr,
                                  "cef_set_load_end_handler: python callback raised: %s\n",
                                  e.what());
                      }
                  });
          });
```

In the fallback block at line ~962 (the `#else` path for when CEF isn't available), add the matching no-op:

```cpp
    m.def("cef_set_load_end_handler", [](py::function) {});
```

- [ ] **Step 3: Verify build**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: clean build, `_dauntless_host` rebuilt.

- [ ] **Step 4: Verify the binding is importable**

Run:
```bash
uv run python -c "import sys; sys.path.insert(0, 'build/python'); import _dauntless_host; print(hasattr(_dauntless_host, 'cef_set_load_end_handler'))"
```

Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "$(cat <<'EOF'
host_bindings: expose cef_set_load_end_handler to Python

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Panel base `invalidate()` + `PanelRegistry.invalidate_all`

**Files:**
- Modify: `engine/ui/panel.py`
- Modify: `engine/ui/panel_registry.py`
- Modify: `tests/unit/test_panel.py`
- Modify: `tests/unit/test_panel_registry.py`

Add a `invalidate()` hook to the `Panel` ABC (default no-op so existing subclasses don't break). `PanelRegistry.invalidate_all()` calls it on every registered panel.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_panel.py`:

```python
def test_panel_invalidate_is_a_noop_by_default():
    """Base implementation lets subclasses opt in to invalidation
    without forcing every Panel to override the hook."""
    from engine.ui.panel import Panel

    class Minimal(Panel):
        @property
        def name(self):
            return "minimal"
        def render_payload(self):
            return None
        def dispatch_event(self, action):
            return False

    p = Minimal()
    p.invalidate()  # must not raise
```

Append to `tests/unit/test_panel_registry.py`:

```python
def test_registry_invalidate_all_calls_invalidate_on_every_panel():
    """invalidate_all is the CEF page-load hook entry point — every
    panel's snapshot cache gets cleared so the next render_all
    re-emits even if state didn't change."""
    invalidated = []

    class _Recording(Panel):
        def __init__(self, name):
            super().__init__()
            self._name = name
        @property
        def name(self):
            return self._name
        def render_payload(self):
            return None
        def dispatch_event(self, action):
            return False
        def invalidate(self):
            invalidated.append(self._name)

    reg = PanelRegistry()
    reg.register(_Recording("a"))
    reg.register(_Recording("b"))

    reg.invalidate_all()

    assert invalidated == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_panel.py tests/unit/test_panel_registry.py -v`
Expected:
- `test_panel_invalidate_is_a_noop_by_default` — FAIL (`AttributeError: 'Minimal' object has no attribute 'invalidate'`)
- `test_registry_invalidate_all_calls_invalidate_on_every_panel` — FAIL (`AttributeError: 'PanelRegistry' object has no attribute 'invalidate_all'`)

- [ ] **Step 3: Implement the hooks**

In `engine/ui/panel.py`, add to the `Panel` class (after `dispatch_event`):

```python
    def invalidate(self) -> None:
        """Drop any cached state so the next render_payload re-emits.

        Default no-op — subclasses with snapshot caches (e.g.
        TargetListView) override this. Wired by PanelRegistry.invalidate_all,
        which the host loop calls when the CEF page finishes loading
        so the first post-load emit is guaranteed to land.
        """
        pass
```

In `engine/ui/panel_registry.py`, add to the `PanelRegistry` class (after `dispatch`):

```python
    def invalidate_all(self) -> None:
        """Call ``panel.invalidate()`` on every registered panel.

        Used by the host loop as a CEF load-end callback so that all
        panel snapshot caches drop their last-pushed state. The next
        ``render_all()`` then re-emits regardless of whether Python-side
        state has changed since the last tick.
        """
        for p in self._panels:
            p.invalidate()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_panel.py tests/unit/test_panel_registry.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/panel.py engine/ui/panel_registry.py tests/unit/test_panel.py tests/unit/test_panel_registry.py
git commit -m "$(cat <<'EOF'
ui: Panel.invalidate hook + PanelRegistry.invalidate_all

CEF page-load callback (next commit) calls invalidate_all to clear
panel snapshot caches, so the first post-load tick re-emits state.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Replace startup-frames hack with the OnLoadEnd hook

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Find the current startup-frames hack**

Run: `grep -n "ticks < 240\|target_list_view.invalidate\|cef_set_load_end_handler\|cef_set_event_handler" engine/host_loop.py`

Confirm the hack at the pump block (currently around line 2113-2117) and the existing `_cef_set_event_handler` wiring (around line 2000).

- [ ] **Step 2: Wire the load-end callback at startup**

In `engine/host_loop.py`, near the existing CEF capability lookups (where `_cef_set_event_handler` is fetched and wired, around line 1994-2001), add similar lookup + wiring for the new load-end binding.

Find the existing block:

```python
        _cef_set_event_handler = getattr(_h, "cef_set_event_handler", None) if _h else None
        if _cef_set_event_handler is not None:
            _cef_set_event_handler(registry.dispatch)
```

Add immediately after:

```python
        _cef_set_load_end = getattr(_h, "cef_set_load_end_handler", None) if _h else None
        if _cef_set_load_end is not None:
            # Drop snapshot caches when CEF finishes loading hello.html
            # so the next tick re-emits state. Handles both initial load
            # and Cmd+R reloads.
            _cef_set_load_end(registry.invalidate_all)
```

- [ ] **Step 3: Remove the startup-frames hack from the pump block**

Find:

```python
                target_list_view.visible = view_mode.is_exterior

                if ticks < 240:  # ~4 sec at 60 Hz
                    target_list_view.invalidate()
                _scripts = registry.render_all()
```

Replace with:

```python
                target_list_view.visible = view_mode.is_exterior

                _scripts = registry.render_all()
```

- [ ] **Step 4: Build + smoke-test**

```bash
cmake --build build -j 2>&1 | tail -3
timeout 5 ./build/dauntless 2>&1 | tee /tmp/dauntless-loadend.log
grep -i "load-end\|target-list\|setTargetList\|cef" /tmp/dauntless-loadend.log | head -20
```

Visual verification needed: launch the binary, press SPACE to enter tactical view, confirm the target list panel appears with the three demo rows (demo block is still in place until Task 9).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "$(cat <<'EOF'
host_loop: replace startup-frames invalidate with OnLoadEnd callback

CEF's main-frame load-end now drives PanelRegistry.invalidate_all once
per page load (initial or Cmd+R reload), so panels re-emit on the next
tick instead of relying on a 4-second blind retry.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `SetClass` subscriber API

**Files:**
- Modify: `engine/appc/sets.py`
- Create: `tests/unit/test_set_subscribers.py`

Add `subscribe(callback)` / `unsubscribe(callback)` to `SetClass`. `AddObjectToSet` and `RemoveObjectFromSet` fire all subscribers with `(event, obj, identifier)` where event is the string `"added"` or `"removed"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_set_subscribers.py`:

```python
"""Unit tests for SetClass subscribe/unsubscribe + add/remove notifications."""
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass(); s.SetName(name); return s


def test_subscriber_receives_added_event():
    s = SetClass()
    received = []
    s.subscribe(lambda event, obj, identifier: received.append((event, identifier)))
    ship = _ship("A")

    s.AddObjectToSet(ship, "A")

    assert received == [("added", "A")]


def test_subscriber_receives_removed_event():
    s = SetClass()
    ship = _ship("A")
    s.AddObjectToSet(ship, "A")

    received = []
    s.subscribe(lambda event, obj, identifier: received.append((event, identifier)))
    s.RemoveObjectFromSet("A")

    assert received == [("removed", "A")]


def test_unsubscribe_stops_notifications():
    s = SetClass()
    received = []
    cb = lambda event, obj, identifier: received.append(event)
    s.subscribe(cb)
    s.unsubscribe(cb)

    s.AddObjectToSet(_ship("A"), "A")

    assert received == []


def test_multiple_subscribers_all_fire():
    s = SetClass()
    a_calls, b_calls = [], []
    s.subscribe(lambda *args: a_calls.append(args[0]))
    s.subscribe(lambda *args: b_calls.append(args[0]))

    s.AddObjectToSet(_ship("X"), "X")

    assert a_calls == ["added"]
    assert b_calls == ["added"]


def test_subscriber_exceptions_do_not_stop_other_subscribers():
    """A broken subscriber must not break the rest of the chain."""
    s = SetClass()
    received_b = []
    def bad(*args): raise RuntimeError("subscriber bug")
    def good(*args): received_b.append(args[0])
    s.subscribe(bad)
    s.subscribe(good)

    s.AddObjectToSet(_ship("X"), "X")

    assert received_b == ["added"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_set_subscribers.py -v`
Expected: FAIL — `AttributeError: 'SetClass' object has no attribute 'subscribe'`.

- [ ] **Step 3: Implement subscribe + notify**

In `engine/appc/sets.py`, find the `SetClass` `__init__` method. Add `self._subscribers: list = []` to the existing attribute init block.

Add methods to `SetClass`:

```python
    def subscribe(self, callback) -> None:
        """Register a callback notified on every AddObjectToSet /
        RemoveObjectFromSet / DeleteObjectFromSet. Callback signature:
        ``callback(event: str, obj, identifier: str)`` where event is
        ``"added"`` or ``"removed"``.

        Used by the target-menu layer to track ship comings-and-goings
        without polling.
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _fire(self, event: str, obj, identifier: str) -> None:
        # Snapshot the subscriber list so a callback that unsubscribes
        # during dispatch doesn't disturb the iteration.
        for cb in list(self._subscribers):
            try:
                cb(event, obj, identifier)
            except Exception:
                # One broken subscriber must not break the chain. Real
                # production reporting could log this; for the headless
                # shim we swallow and continue.
                pass
```

Modify `AddObjectToSet` to fire `_fire("added", obj, identifier)` after successful add. Modify `RemoveObjectFromSet` and `DeleteObjectFromSet` to fire `_fire("removed", obj, name)` before the removal completes (so subscribers can still query the object).

The exact edits depend on the current bodies of those methods; preserve their existing return values and side-effects, just add the `self._fire(...)` line at the right point.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_set_subscribers.py -v`
Expected: 5 passed.

Also run the full sets test suite to confirm no regression:
```bash
uv run pytest tests/unit/test_sets.py tests/unit/test_set_subscribers.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sets.py tests/unit/test_set_subscribers.py
git commit -m "$(cat <<'EOF'
appc/sets: subscribe/unsubscribe + add/remove notifications

SetClass now exposes a tiny subscriber API; AddObjectToSet and
RemoveObjectFromSet fire ("added"|"removed", obj, identifier) to every
subscriber. Used by the target-menu layer (next commit) to track
bridge-set membership without polling.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `wire_to_bridge_set` — auto-populate target menu

**Files:**
- Modify: `engine/appc/target_menu.py`
- Create: `tests/unit/test_target_menu_bridge_subscription.py`

A helper that subscribes the target-menu singleton to a `SetClass` (typically the `bridge` set). On `"added"`, calls `RebuildShipMenu(ship)` then `ResetAffiliationColors()`. On `"removed"`, removes the row.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_target_menu_bridge_subscription.py`:

```python
"""wire_to_bridge_set hooks the target-menu singleton to a bridge set."""
import App
from engine.appc.ships import ShipClass
from engine.appc.sets import SetClass


def _ship(name):
    s = ShipClass(); s.SetName(name); return s


def _setup_game_with_groups(friendly=(), enemy=()):
    """Required because ResetAffiliationColors consults the current
    game's mission for group lookups."""
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    for n in friendly:
        mission.GetFriendlyGroup().AddName(n)
    for n in enemy:
        mission.GetEnemyGroup().AddName(n)
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    _set_current_game(game)
    return game


def test_wire_to_bridge_set_adds_row_when_ship_enters():
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = SetClass()
    _setup_game_with_groups(friendly=["Dauntless"])
    try:
        wire_to_bridge_set(bridge)
        ship = _ship("Dauntless")
        bridge.AddObjectToSet(ship, "Dauntless")

        row = target_menu.GetObjectEntry(ship)
        assert row is not None
        assert row.GetAffiliation() == "FRIENDLY"
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_wire_to_bridge_set_removes_row_when_ship_leaves():
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = SetClass()
    _setup_game_with_groups(enemy=["Kor"])
    try:
        wire_to_bridge_set(bridge)
        ship = _ship("Kor")
        bridge.AddObjectToSet(ship, "Kor")
        assert target_menu.GetObjectEntry(ship) is not None

        bridge.RemoveObjectFromSet("Kor")
        assert target_menu.GetObjectEntry(ship) is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_wire_to_bridge_set_is_idempotent_for_singleton():
    """Calling wire_to_bridge_set twice on the same set must not produce
    duplicate rows on subsequent add events."""
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = SetClass()
    _setup_game_with_groups(friendly=["Dauntless"])
    try:
        wire_to_bridge_set(bridge)
        wire_to_bridge_set(bridge)  # second call
        ship = _ship("Dauntless")
        bridge.AddObjectToSet(ship, "Dauntless")

        rows = [c for c in target_menu._children]
        assert len(rows) == 1
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_target_menu_bridge_subscription.py -v`
Expected: FAIL — `ImportError: cannot import name 'wire_to_bridge_set'`.

- [ ] **Step 3: Implement `wire_to_bridge_set`**

Append to `engine/appc/target_menu.py`:

```python
# ── Bridge-set integration ───────────────────────────────────────────────────

def _on_bridge_set_event(event: str, obj, identifier: str) -> None:
    """SetClass subscriber callback — drives target-menu rows from
    bridge-set add/remove events."""
    menu = STTargetMenu_GetTargetMenu()
    if menu is None:
        return
    if event == "added":
        if hasattr(obj, "StartGetSubsystemMatch"):
            menu.RebuildShipMenu(obj)
            menu.ResetAffiliationColors()
    elif event == "removed":
        row = menu.GetObjectEntry(obj)
        if row is not None:
            menu.DeleteChild(row)


def wire_to_bridge_set(bridge_set) -> None:
    """Subscribe the target-menu singleton to a bridge set.

    Idempotent — subscribing the same callback twice is a no-op (the
    SetClass.subscribe API enforces uniqueness).
    """
    bridge_set.subscribe(_on_bridge_set_event)


def unwire_from_bridge_set(bridge_set) -> None:
    """Counterpart to wire_to_bridge_set. Used by reset_sdk_globals
    so mission swaps don't leak the subscription."""
    bridge_set.unsubscribe(_on_bridge_set_event)
```

Expose `wire_to_bridge_set` via `App.py` re-export — find the existing `from engine.appc.target_menu import (...)` block and add `wire_to_bridge_set` and `unwire_from_bridge_set` to it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_menu_bridge_subscription.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/target_menu.py App.py tests/unit/test_target_menu_bridge_subscription.py
git commit -m "$(cat <<'EOF'
target_menu: wire_to_bridge_set auto-populates rows from set events

Subscribes the target-menu singleton to a SetClass; add events call
RebuildShipMenu + ResetAffiliationColors, remove events drop the row.
Idempotent. Used in host_loop to replace the demo-ship block.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `reset_sdk_globals` unsubscribes from bridge

**Files:**
- Modify: `engine/host_loop.py`
- Modify: `tests/unit/test_target_menu_bridge_subscription.py`

`reset_sdk_globals` already clears the target-menu singleton (Task 13 fix from the previous plan). Now it also needs to unhook the subscriber so a mission swap doesn't accumulate stale subscriptions on a recreated bridge set.

- [ ] **Step 1: Append a test for the cleanup**

Append to `tests/unit/test_target_menu_bridge_subscription.py`:

```python
def test_reset_sdk_globals_unwires_from_bridge_set():
    """After reset_sdk_globals, the subscriber callback must not fire
    on subsequent bridge-set events (the singleton has been cleared)."""
    from engine.host_loop import reset_sdk_globals
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        from engine.appc.sets import SetClass
        bridge = SetClass()
        App.g_kSetManager.AddSet(bridge, "bridge")
    wire_to_bridge_set(bridge)

    reset_sdk_globals()

    # After reset the singleton is gone; adding to the bridge set must
    # not raise (the subscriber callback handles None gracefully).
    ship = ShipClass(); ship.SetName("Late")
    bridge.AddObjectToSet(ship, "Late")  # must not raise
```

- [ ] **Step 2: Run tests to verify the new test currently passes-or-fails**

Run: `uv run pytest tests/unit/test_target_menu_bridge_subscription.py::test_reset_sdk_globals_unwires_from_bridge_set -v`

The test should pass already because `_on_bridge_set_event` early-returns when the singleton is None. Even so, this test locks in the behaviour.

- [ ] **Step 3: Commit (cleanup-coverage test)**

```bash
git add tests/unit/test_target_menu_bridge_subscription.py
git commit -m "$(cat <<'EOF'
test: lock-in that bridge subscriber is safe after singleton reset

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Replace demo-ship block with `wire_to_bridge_set`

**Files:**
- Modify: `engine/host_loop.py`

The demo block currently constructs its own Mission/Episode/Game and seeds three fake ships into the bridge set. Replace it with a call to `wire_to_bridge_set(bridge_set)` so real mission ships flow into the menu automatically. The mission's existing call to `CreatePlayerShip` and any `AddObjectToSet` calls then drive the panel.

- [ ] **Step 1: Find the demo block**

Run: `grep -n "Demo ships for Phase 1\|_run_demo\|_demo_player\|_demo_bridge" engine/host_loop.py`

This points at the block to delete (currently around lines 1987-2028).

- [ ] **Step 2: Replace the block**

In `engine/host_loop.py`, delete the entire block from the `# ── Demo ships for Phase 1 of the target list ─────────────────` comment header down to and including the `_demo_game.SetPlayer(_demo_player)` line.

In its place insert:

```python
        # Wire the target-menu singleton to the bridge set so real
        # ships flow into the panel as the mission loads them. The
        # SDK's CreateTargetList is the one that constructs the
        # singleton — but Bridge/TacticalMenuHandlers is not yet
        # loaded by the host loop, so we construct it ourselves and
        # subscribe. Once a Bridge.Initialize equivalent runs in this
        # codepath, the explicit construction here can drop and the
        # SDK call site will own it.
        import App as _App
        if _App.STTargetMenu_GetTargetMenu() is None:
            _App.STTargetMenu_CreateW("Targets")
        _bridge_set = _App.g_kSetManager.GetSet("bridge")
        if _bridge_set is not None:
            from engine.appc.target_menu import wire_to_bridge_set
            wire_to_bridge_set(_bridge_set)
            # Rebuild rows for any ships the mission already added before
            # we subscribed (mission Initialize runs above this line).
            _App.STTargetMenu_GetTargetMenu().RebuildShipMenus()
            _App.STTargetMenu_GetTargetMenu().ResetAffiliationColors()
```

- [ ] **Step 3: Build + smoke test**

```bash
cmake --build build -j 2>&1 | tail -3
uv run pytest -q
timeout 5 ./build/dauntless 2>&1 | tee /tmp/dauntless-real.log
grep -i "setTargetList\|target-list" /tmp/dauntless-real.log | head -5
```

Expected:
- Tests still pass.
- Launching with the default M2Objects mission populates the bridge set; the target-menu singleton subscribes; the panel should now show *real ship names* (USS Galaxy and whatever M2Objects spawns) instead of the demo trio. **Visual verification needed**: press SPACE → tactical view → confirm real ship names appear.

If the panel is empty after this change, the most likely cause is that `RebuildShipMenus()` is being called before any ships exist (mission loaded later). Check the order of operations: `controller.loader.load(mission_name)` must run before this block, and that load must actually add ships to the bridge set.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "$(cat <<'EOF'
host_loop: replace demo-ship block with wire_to_bridge_set

The panel now populates from the real bridge set as the mission's
ships register. Demo scaffolding gone; panel is empty until a real
mission adds ships (and subsystems will appear in Task 10-11).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `CT_SHIP_SUBSYSTEM` dispatch in `StartGetSubsystemMatch`

**Files:**
- Modify: `engine/appc/ships.py`
- Modify: `tests/unit/test_target_menu_shim.py`

`RebuildShipMenu` already calls `ship.StartGetSubsystemMatch()` with no argument (returns empty). We want it to iterate ALL of the ship's subsystems. The SDK uses `CT_SHIP_SUBSYSTEM` (= `ShipSubsystem` base class) for that.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_menu_shim.py`:

```python
def test_rebuild_ship_menu_populates_subsystem_rows():
    """Phase-2: RebuildShipMenu walks all targetable subsystems and
    creates a child row per subsystem under the ship's STSubsystemMenu.

    A ShipClass_Create()'d ship has the default subsystem set installed,
    so the row should now have several children (sensor, impulse,
    weapons, shields, hull etc.)."""
    from engine.appc.ships import ShipClass_Create

    target_menu = App.STTargetMenu("Targets")
    ship = ShipClass_Create("Test")
    ship.SetName("Test Ship")

    target_menu.RebuildShipMenu(ship)
    row = target_menu.GetObjectEntry(ship)

    # Should now have at least one subsystem child.
    assert len(row._children) > 0, (
        f"Expected subsystem rows, got {len(row._children)} children. "
        "Did CT_SHIP_SUBSYSTEM dispatch get added to StartGetSubsystemMatch?"
    )
```

This will also flip the existing `test_rebuild_ship_menu_leaves_subsystem_children_empty_in_phase1` from passing to failing — that test asserted Phase-1 deferral. Update it to reflect Phase 2:

```python
def test_rebuild_ship_menu_populates_subsystem_children_in_phase2():
    """Phase-2 update: previously this test asserted empty children
    (Phase 1 deferral). With CT_SHIP_SUBSYSTEM dispatch added,
    subsystem rows now populate."""
    target_menu = App.STTargetMenu("Targets")
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Test")
    ship.SetName("Dauntless")
    target_menu.RebuildShipMenu(ship)
    row = target_menu.GetObjectEntry(ship)
    assert row is not None
    assert len(row._children) > 0
```

Delete the original `test_rebuild_ship_menu_leaves_subsystem_children_empty_in_phase1` test body, or replace it with the new test above.

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: the new `test_rebuild_ship_menu_populates_subsystem_rows` and `test_rebuild_ship_menu_populates_subsystem_children_in_phase2` both fail.

- [ ] **Step 3: Add `CT_SHIP_SUBSYSTEM` dispatch**

In `engine/appc/ships.py`, find the dispatch chain inside `StartGetSubsystemMatch` (around lines 888-899). Locate the final `elif match_type is App.CT_HULL_SUBSYSTEM:` branch and add a new branch *above* the `else: return iter(())` clause:

```python
        elif match_type is App.CT_SHIP_SUBSYSTEM:
            # ShipSubsystem is the base class — every subsystem matches.
            target_class = ShipSubsystem
```

Also import `ShipSubsystem` from `engine.appc.subsystems` at the top of the function (alongside the existing imports inside `StartGetSubsystemMatch`).

Then update `RebuildShipMenu` in `engine/appc/target_menu.py` to actually pass `App.CT_SHIP_SUBSYSTEM`. Find:

```python
        kIter = ship.StartGetSubsystemMatch()
```

Replace with:

```python
        import App as _App
        kIter = ship.StartGetSubsystemMatch(_App.CT_SHIP_SUBSYSTEM)
```

Update the docstring in `RebuildShipMenu`: the "Phase 1 deferral" paragraph should be removed (Phase 2 now populates).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_menu_shim.py tests/integration/test_target_list_sdk_integration.py -v`
Expected: all pass. The existing integration tests should still work because they construct ships with `ShipClass()` (no subsystems) and the iteration returns empty for those.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ships.py engine/appc/target_menu.py tests/unit/test_target_menu_shim.py
git commit -m "$(cat <<'EOF'
ships: add CT_SHIP_SUBSYSTEM dispatch + populate subsystem rows

StartGetSubsystemMatch now accepts CT_SHIP_SUBSYSTEM (ShipSubsystem
base class) for iterating every subsystem. RebuildShipMenu uses it
so each ship row gets child rows for sensor, weapons, shields, hull
etc.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Extend `TargetListView` snapshot with subsystems + hull/shield

**Files:**
- Modify: `engine/ui/target_list_view.py`
- Modify: `tests/unit/test_target_list_view.py`

Snapshot grows from `(visible, selected, rows)` to include per-row subsystem children and hull/shield percentages. Payload JSON shape:

```json
{
  "visible": true,
  "selected": "USS Galaxy",
  "selected_subsystem": "Phaser Bank Alpha",
  "rows": [
    {
      "name": "USS Galaxy",
      "affiliation": "FRIENDLY",
      "hull": 85,
      "shields": 92,
      "subsystems": [
        {"name": "Sensor Array"},
        {"name": "Phaser Bank Alpha"}
      ]
    }
  ]
}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_target_list_view.py`:

```python
def test_view_payload_includes_subsystems_and_health():
    """Each row carries hull%, shield%, and a flat list of subsystem
    names. selected_subsystem mirrors player.GetTargetSubsystem()."""
    import json
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("USS Galaxy")
        target_menu.RebuildShipMenu(ship)
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            from engine.appc.sets import SetClass
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "USS Galaxy")
        player.SetTarget("USS Galaxy")
        # Pick the first subsystem as the targeted subsystem.
        first_sub = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        first_sub_obj = ship.GetNextSubsystemMatch(first_sub)
        ship.EndGetSubsystemMatch(first_sub)
        player.SetTargetSubsystem(first_sub_obj)

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)

        assert state["selected"] == "USS Galaxy"
        assert state["selected_subsystem"] == first_sub_obj.GetName()
        row = state["rows"][0]
        assert "hull" in row and 0 <= row["hull"] <= 100
        assert "shields" in row and 0 <= row["shields"] <= 100
        assert isinstance(row["subsystems"], list)
        assert len(row["subsystems"]) > 0
        assert row["subsystems"][0]["name"]  # non-empty string
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_list_view.py::test_view_payload_includes_subsystems_and_health -v`
Expected: FAIL.

- [ ] **Step 3: Extend `_snapshot` and `render_payload`**

In `engine/ui/target_list_view.py`, replace `_snapshot`:

```python
    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        import App
        target_menu = App.STTargetMenu_GetTargetMenu()
        if target_menu is None:
            return (self._visible, None, None, ())
        from engine.appc.target_menu import STSubsystemMenu
        rows = []
        child = target_menu.GetFirstChild()
        while child is not None:
            if isinstance(child, STSubsystemMenu):
                ship = child.GetShip()
                # Hull % via the ship's hull subsystem if present.
                hull_pct = _query_hull_percentage(ship)
                shield_pct = _query_shield_percentage(ship)
                # Subsystem child rows — names only, ordering preserved.
                subsystems = tuple(
                    sub_child.GetLabel()
                    for sub_child in child._children
                )
                rows.append((
                    ship.GetName(),
                    child.GetAffiliation(),
                    child.IsVisible(),
                    hull_pct,
                    shield_pct,
                    subsystems,
                ))
            child = target_menu.GetNextChild(child)

        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        selected = None
        selected_subsystem = None
        if game is not None:
            player = game.GetPlayer()
            if player is not None:
                target = player.GetTarget()
                if target is not None:
                    selected = target.GetName()
                target_sub = player.GetTargetSubsystem()
                if target_sub is not None and hasattr(target_sub, "GetName"):
                    selected_subsystem = target_sub.GetName()
        return (self._visible, selected, selected_subsystem, tuple(rows))
```

Add the helpers at module scope (above the class):

```python
def _query_hull_percentage(ship) -> int:
    """Return hull condition as an integer percentage 0-100, or 100 if
    the ship has no hull subsystem (defensive — shouldn't happen on
    real ships)."""
    if ship is None or not hasattr(ship, "GetHull"):
        return 100
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    if hull is None:
        return 100
    if not hasattr(hull, "GetConditionPercentage"):
        return 100
    try:
        return int(round(hull.GetConditionPercentage()))
    except Exception:
        return 100


def _query_shield_percentage(ship) -> int:
    """Return shield strength as an integer percentage 0-100."""
    if ship is None or not hasattr(ship, "GetShields"):
        return 0
    shields = ship.GetShields()
    if shields is None or not hasattr(shields, "GetShieldPercentage"):
        return 0
    try:
        return int(round(shields.GetShieldPercentage()))
    except Exception:
        return 0
```

Replace `render_payload`:

```python
    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, selected, selected_subsystem, rows = snapshot
        payload = {
            "visible": visible,
            "selected": selected,
            "selected_subsystem": selected_subsystem,
            "rows": [
                {
                    "name": name,
                    "affiliation": aff,
                    "hull": hull,
                    "shields": shields,
                    "subsystems": [{"name": s} for s in subs],
                }
                for (name, aff, is_vis, hull, shields, subs) in rows
                if is_vis
            ],
        }
        return "setTargetList(" + json.dumps(payload) + ");"
```

If `ShipClass` lacks `GetHull` (only `GetHullSubsystem` exists), adjust `_query_hull_percentage` to use the correct accessor — run `grep -n "def GetHull\|def Get.*Hull" engine/appc/ships.py` to find the right one. Likely it's `GetHull` if the SDK uses that name, otherwise `GetHullSubsystem`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: all pass (the new test + existing idempotency/dispatch tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/target_list_view.py tests/unit/test_target_list_view.py
git commit -m "$(cat <<'EOF'
target_list_view: snapshot includes subsystems + hull/shield + selected_subsystem

Payload now nests subsystem rows under each ship and exposes hull and
shield percentages. selected_subsystem mirrors player.GetTargetSubsystem
so the JS can highlight the locked subsystem.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: JS render for nested subsystems + health bars

**Files:**
- Modify: `native/assets/ui-cef/js/target_list.js`

Update `setTargetList` to consume the new payload shape and emit nested subsystem rows + hull/shield bars.

- [ ] **Step 1: Replace `setTargetList` body**

In `native/assets/ui-cef/js/target_list.js`, replace the existing `setTargetList` function with:

```js
function setTargetList(state) {
    const panel = document.getElementById('target-list-panel');
    if (!panel) return;
    if (!state || !state.visible) {
        panel.classList.add('target-list--hidden');
        return;
    }
    panel.classList.remove('target-list--hidden');

    const body = document.getElementById('target-list-body');
    if (!body) return;

    const rows = state.rows || [];
    const selected = state.selected || null;
    const selectedSub = state.selected_subsystem || null;

    let html = '';
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const name = String(row.name || '');
        const aff = String(row.affiliation || 'UNKNOWN');
        const chosen = (selected === name) ? ' target-list__row--chosen' : '';
        const hull = (typeof row.hull === 'number') ? row.hull : 100;
        const shields = (typeof row.shields === 'number') ? row.shields : 0;
        const safe = name.replace(/'/g, "\\'");

        // Ship row — caret, name, hull bar, shield bar.
        html += '<div class="target-list__row target-list__row--' + aff + chosen + '"'
              +   ' onclick="dauntlessEvent(\'target/' + safe + '\')">'
              +   '<span class="target-list__caret">&#9656;</span>'
              +   '<span class="target-list__name">' + name + '</span>'
              +   '<span class="target-list__bars">'
              +     '<span class="target-list__bar target-list__bar--hull"'
              +     ' style="--bar-pct:' + hull + '%"></span>'
              +     '<span class="target-list__bar target-list__bar--shields"'
              +     ' style="--bar-pct:' + shields + '%"></span>'
              +   '</span>'
              + '</div>';

        // Subsystem child rows — nested under the ship row.
        const subs = row.subsystems || [];
        for (let j = 0; j < subs.length; j++) {
            const sub = subs[j];
            const subName = String(sub.name || '');
            const subSafe = subName.replace(/'/g, "\\'");
            const subChosen = (selected === name && selectedSub === subName)
                ? ' target-list__sub--chosen' : '';
            html += '<div class="target-list__sub target-list__sub--' + aff + subChosen + '"'
                  +   ' onclick="dauntlessEvent(\'target/' + safe + '/' + subSafe + '\')">'
                  +   '<span class="target-list__sub-bullet">&#8226;</span>'
                  +   '<span class="target-list__sub-name">' + subName + '</span>'
                  + '</div>';
        }
    }
    body.innerHTML = html;
}
```

- [ ] **Step 2: Commit (JS only; CSS in Task 13)**

```bash
git add native/assets/ui-cef/js/target_list.js
git commit -m "$(cat <<'EOF'
ui-cef: render subsystem rows + hull/shield bars

setTargetList consumes the extended payload: each ship row gets a
caret + name + two health bars, with subsystem rows nested
underneath. Subsystem click dispatches target/<ship>/<subsystem>.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: CSS for nested subsystems + health bars

**Files:**
- Modify: `native/assets/ui-cef/css/target_list.css`

Adds:
- `.target-list__bars` — flex container for the two bars, pushed to the right edge of the ship row.
- `.target-list__bar` — generic bar with a percent-driven fill via CSS custom property.
- `.target-list__bar--hull` + `.target-list__bar--shields` — variant tints.
- `.target-list__sub` — nested subsystem row (indented, smaller text).
- `.target-list__sub--chosen` — bumped tint for the active subsystem.

- [ ] **Step 1: Append the new rules**

Append to `native/assets/ui-cef/css/target_list.css`:

```css

/* ── Health bars ─────────────────────────────────────────────────── */
.target-list__row {
    /* Make the bars block sit at the right edge of each ship row. */
    justify-content: flex-start;
}

.target-list__name {
    flex: 1 1 auto;
}

.target-list__bars {
    display: flex;
    gap: 4px;
    align-items: center;
}

.target-list__bar {
    --bar-pct: 0%;
    width: 32px;
    height: 8px;
    background: rgba(40, 40, 40, 0.6);
    position: relative;
}

.target-list__bar::after {
    content: "";
    display: block;
    height: 100%;
    width: var(--bar-pct);
    background: var(--bar-fill, white);
    transition: width 120ms linear;
}

.target-list__bar--hull    { --bar-fill: rgb(255, 200, 60); }
.target-list__bar--shields { --bar-fill: rgb(150, 129, 222); }

/* ── Nested subsystem rows ────────────────────────────────────────── */
.target-list__sub {
    display: flex;
    align-items: center;
    padding: 3px 12px 3px 28px;   /* indent past the ship row caret */
    cursor: pointer;
    font-size: 12px;
    color: rgba(235, 225, 255, 0.75);
}

.target-list__sub-bullet {
    margin-right: 8px;
    color: white;
}

.target-list__sub-name {
    flex: 1 1 auto;
}

/* Subsystem hover: same affiliation tint as the parent row, lower
 * baseline alpha. */
.target-list__sub--FRIENDLY:hover { background: rgba( 80, 112, 230, 0.15); }
.target-list__sub--ENEMY:hover    { background: rgba(216,  43,  43, 0.15); }
.target-list__sub--NEUTRAL:hover  { background: rgba(255, 255, 175, 0.10); }
.target-list__sub--UNKNOWN:hover  { background: rgba(128, 128, 128, 0.15); }

/* Chosen subsystem: a tick brighter than hover so the locked subsystem
 * reads clearly. */
.target-list__sub--FRIENDLY.target-list__sub--chosen { background: rgba( 80, 112, 230, 0.30); color: rgb(235, 225, 255); }
.target-list__sub--ENEMY.target-list__sub--chosen    { background: rgba(216,  43,  43, 0.30); color: rgb(235, 225, 255); }
.target-list__sub--NEUTRAL.target-list__sub--chosen  { background: rgba(255, 255, 175, 0.25); color: rgb(235, 225, 255); }
.target-list__sub--UNKNOWN.target-list__sub--chosen  { background: rgba(128, 128, 128, 0.30); color: rgb(235, 225, 255); }
```

- [ ] **Step 2: Visually verify**

CSS is loaded from disk by CEF at runtime — relaunch (no rebuild needed):

```bash
./build/dauntless
```

Visual check (SPACE → tactical view):
- Each ship row shows two small bars at the right: yellow (hull) and purple (shields).
- Bars are partially filled based on the current values.
- Subsystem rows are nested under each ship, indented, with a `•` bullet in white.
- Clicking a subsystem highlights it.

- [ ] **Step 3: Commit**

```bash
git add native/assets/ui-cef/css/target_list.css
git commit -m "$(cat <<'EOF'
ui-cef: CSS for nested subsystem rows + hull/shield bars

Subsystem rows indent 28px with a smaller white bullet and dimmer
text. Hull/shield bars sit at the right edge of each ship row, filled
via a --bar-pct custom property and tinted by --bar-fill.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: `dispatch_event` routes subsystem clicks

**Files:**
- Modify: `engine/ui/target_list_view.py`
- Modify: `tests/unit/test_target_list_view.py`

When the user clicks a subsystem row the JS emits `target/<ship>/<subsystem>`. The registry strips the `target/` prefix and passes `<ship>/<subsystem>` as `action` to `TargetListView.dispatch_event`. Parse the slash and call both `SetTarget(ship)` and `SetTargetSubsystem(subsystem-instance)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_list_view.py`:

```python
def test_dispatch_event_subsystem_click_sets_both_target_and_subsystem():
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("USS Galaxy")
        target_menu.RebuildShipMenu(ship)
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            from engine.appc.sets import SetClass
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "USS Galaxy")
        # Find a real subsystem name to click.
        it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(it)
        ship.EndGetSubsystemMatch(it)
        assert sub is not None
        sub_name = sub.GetName()

        view = TargetListView()
        handled = view.dispatch_event(f"USS Galaxy/{sub_name}")

        assert handled is True
        assert player.GetTarget() is ship
        assert player.GetTargetSubsystem() is sub
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_dispatch_event_ship_only_click_clears_subsystem():
    """Clicking the ship row (no subsystem) sets the target ship and
    clears any previously selected subsystem."""
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("USS Galaxy")
        target_menu.RebuildShipMenu(ship)
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            from engine.appc.sets import SetClass
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "USS Galaxy")
        it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(it)
        ship.EndGetSubsystemMatch(it)
        player.SetTargetSubsystem(sub)
        assert player.GetTargetSubsystem() is sub

        view = TargetListView()
        view.dispatch_event("USS Galaxy")

        assert player.GetTarget() is ship
        assert player.GetTargetSubsystem() is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: both new tests FAIL (current dispatch_event doesn't parse the slash).

- [ ] **Step 3: Update `dispatch_event`**

In `engine/ui/target_list_view.py`, replace `dispatch_event`:

```python
    def dispatch_event(self, action: str) -> bool:
        """Action format: ``<ship>`` or ``<ship>/<subsystem>``.

        Ship-only clicks set the target and clear any previously-selected
        subsystem. Subsystem clicks set both the target and the
        subsystem in one go.
        """
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        if game is None:
            return False
        player = game.GetPlayer()
        if player is None:
            return False

        if "/" in action:
            ship_name, subsystem_name = action.split("/", 1)
        else:
            ship_name, subsystem_name = action, None

        player.SetTarget(ship_name)

        if subsystem_name is None:
            # Ship-only click — clear any subsystem lock.
            player.SetTargetSubsystem(None)
            return True

        # Subsystem click — find the subsystem instance on the now-targeted
        # ship and lock it.
        target_ship = player.GetTarget()
        if target_ship is None:
            return True  # ship resolution failed, but the SetTarget call already happened
        sub = _resolve_subsystem_by_name(target_ship, subsystem_name)
        player.SetTargetSubsystem(sub)
        return True
```

Add the helper at module scope:

```python
def _resolve_subsystem_by_name(ship, name: str):
    """Walk the ship's subsystems and return the first whose GetName()
    matches. Returns None if no match — caller treats that as "clear
    subsystem lock"."""
    import App
    it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
    try:
        sub = ship.GetNextSubsystemMatch(it)
        while sub is not None:
            if hasattr(sub, "GetName") and sub.GetName() == name:
                return sub
            sub = ship.GetNextSubsystemMatch(it)
    finally:
        ship.EndGetSubsystemMatch(it)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/target_list_view.py tests/unit/test_target_list_view.py
git commit -m "$(cat <<'EOF'
target_list_view: dispatch_event routes subsystem clicks

Action 'ship/subsystem' resolves the subsystem by name on the
targeted ship and calls SetTargetSubsystem. Ship-only clicks clear
any prior subsystem lock.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Sensor visibility filtering

**Files:**
- Modify: `engine/appc/subsystems.py`
- Modify: `engine/host_loop.py`
- Create: `tests/unit/test_sensor_visibility.py`

The `STSubsystemMenu.SetVisible/SetNotVisible` flag is already filtered by `TargetListView` — when `IsVisible()` returns 0, the row is omitted from the payload. We need a helper that the host loop calls each tick to flip the flag based on sensor range.

- [ ] **Step 1: Decide what "in range" means**

For this iteration, "in range" = sensor subsystem range from the player ship. If `SensorSubsystem` exposes a range query (`GetRange()`, `GetMaxRange()`, etc.), use it. If not, use a fixed default (e.g. 30000 game units) and flag in deferred work that the real sensor distance comes from `SensorProperty.GetMaxRange`.

Run: `grep -n "def GetRange\|def GetMaxRange\|SensorRange\|_range\|GetSensorRange" engine/appc/subsystems.py engine/appc/properties.py 2>/dev/null | head -10`

If a range query exists, use that. Otherwise fall back to `30000.0`.

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_sensor_visibility.py`:

```python
"""Tests for the sensor-visibility update path that drives
STSubsystemMenu.SetVisible/SetNotVisible based on range from the player."""
import App
from engine.appc.ships import ShipClass, ShipClass_Create


def _ship(name, x=0.0, y=0.0, z=0.0):
    s = ShipClass_Create("test")
    s.SetName(name)
    s.SetTranslation(x, y, z)
    return s


def _setup_game_with_player():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = _ship("Player", 0.0, 0.0, 0.0)
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def test_in_range_ship_remains_visible():
    from engine.appc.subsystems import update_target_list_visibility

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        nearby = _ship("Nearby", 1000.0, 0.0, 0.0)
        target_menu.RebuildShipMenu(nearby)

        update_target_list_visibility(target_menu, [nearby], player, range_units=30000.0)

        assert target_menu.GetObjectEntry(nearby).IsVisible() == 1
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_out_of_range_ship_becomes_invisible():
    from engine.appc.subsystems import update_target_list_visibility

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        far = _ship("Far", 100000.0, 0.0, 0.0)
        target_menu.RebuildShipMenu(far)

        update_target_list_visibility(target_menu, [far], player, range_units=30000.0)

        assert target_menu.GetObjectEntry(far).IsVisible() == 0
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_ship_pops_back_when_back_in_range():
    """Out → in transition flips visibility back to 1."""
    from engine.appc.subsystems import update_target_list_visibility

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        wanderer = _ship("Wanderer", 100000.0, 0.0, 0.0)
        target_menu.RebuildShipMenu(wanderer)
        update_target_list_visibility(target_menu, [wanderer], player, range_units=30000.0)
        assert target_menu.GetObjectEntry(wanderer).IsVisible() == 0

        wanderer.SetTranslation(500.0, 0.0, 0.0)
        update_target_list_visibility(target_menu, [wanderer], player, range_units=30000.0)
        assert target_menu.GetObjectEntry(wanderer).IsVisible() == 1
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_visibility.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_target_list_visibility'`.

- [ ] **Step 4: Implement `update_target_list_visibility`**

If `ShipClass` exposes `GetTranslation()` or similar — verify via `grep -n "def GetTranslation\|def GetPosition\|def SetTranslation" engine/appc/ships.py`. Use whichever exists.

Append to `engine/appc/subsystems.py`:

```python
def update_target_list_visibility(target_menu, ships, player, range_units: float = 30000.0) -> None:
    """Flip STSubsystemMenu.SetVisible/SetNotVisible on each row based
    on the ship's distance from the player.

    Args:
        target_menu: the STTargetMenu singleton (or any object exposing
            GetObjectEntry).
        ships: iterable of ship objects expected to be in the menu.
        player: the player ship (for distance computation).
        range_units: maximum range to consider visible. Default 30000
            game units; replace with SensorProperty.GetMaxRange once
            the sensor data is plumbed.

    Real Appc filters by sensor subsystem state (charged, undamaged,
    not jammed). Phase-2 takes only range into account; the property
    chain will be wired in a later iteration.
    """
    from engine.appc.target_menu import STSubsystemMenu
    if player is None:
        return
    px, py, pz = _get_xyz(player)
    range_sq = range_units * range_units
    for ship in ships:
        row = target_menu.GetObjectEntry(ship)
        if row is None or not isinstance(row, STSubsystemMenu):
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - px, sy - py, sz - pz
        if dx * dx + dy * dy + dz * dz <= range_sq:
            row.SetVisible()
        else:
            row.SetNotVisible()


def _get_xyz(ship) -> tuple:
    """Read a ship's world-space position as a tuple of floats. Tries
    GetTranslation, then GetPosition, then falls back to (0, 0, 0) —
    the fallback makes the function safe to call against a ship that
    hasn't been positioned yet (e.g. just spawned)."""
    for name in ("GetTranslation", "GetPosition"):
        if hasattr(ship, name):
            try:
                t = getattr(ship, name)()
                if isinstance(t, (tuple, list)) and len(t) == 3:
                    return (float(t[0]), float(t[1]), float(t[2]))
            except Exception:
                pass
    return (0.0, 0.0, 0.0)
```

If `SetTranslation` exists with `(x, y, z)` signature, the tests above work. If `SetTranslation` expects a vector type, adjust the test fixture in `_ship(...)` accordingly — likely it accepts three floats; verify with `grep -n "def SetTranslation\|def SetPosition" engine/appc/ships.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_visibility.py -v`
Expected: 3 passed.

- [ ] **Step 6: Hook into host_loop's per-tick block**

In `engine/host_loop.py`, find the panel pump block (where `registry.render_all()` is called). Add the visibility update right before `render_all`:

```python
                # Sensor-visibility update — flip per-row IsVisible
                # based on range from the player. TargetListView
                # filters rows where IsVisible() == 0.
                import App as _App_sv  # local alias; module-level App is also fine
                _menu = _App_sv.STTargetMenu_GetTargetMenu()
                _bridge = _App_sv.g_kSetManager.GetSet("bridge")
                if _menu is not None and _bridge is not None:
                    from engine.appc.subsystems import update_target_list_visibility
                    from engine.core.game import Game_GetCurrentGame
                    _game = Game_GetCurrentGame()
                    _player = _game.GetPlayer() if _game is not None else None
                    if _player is not None:
                        update_target_list_visibility(
                            _menu, _bridge.GetObjectList(), _player
                        )
```

- [ ] **Step 7: Build + smoke test**

```bash
cmake --build build -j 2>&1 | tail -3
uv run pytest -q
./build/dauntless
```

Visual check: in tactical view, ships closer than 30000 units appear in the list; farther ships are omitted. (The default M2Objects mission likely has most ships within range; you can verify the cutoff by inspecting position via the JS console payload preview.)

- [ ] **Step 8: Commit**

```bash
git add engine/appc/subsystems.py engine/host_loop.py tests/unit/test_sensor_visibility.py
git commit -m "$(cat <<'EOF'
subsystems: update_target_list_visibility flips row visibility by range

Phase 2 sensor visibility — uses a fixed 30000-unit range for now;
real SensorProperty.GetMaxRange wiring is a follow-up. TargetListView
already filters by STSubsystemMenu.IsVisible, so out-of-range ships
disappear from the payload (and back when they re-enter).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Final integration test + verification pass

**Files:**
- Create: `tests/integration/test_target_list_subsystems.py`

End-to-end check that the whole pipeline works against the real SDK and a populated ship.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_target_list_subsystems.py`:

```python
"""End-to-end: load Bridge.TacticalMenuHandlers.CreateTargetList,
populate a real ship with subsystems via the bridge set, and verify
the rendered payload contains nested subsystems + health bars."""
import json
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.sets import SetClass


def test_full_pipeline_real_sdk_real_ship_real_subsystems():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.target_menu import wire_to_bridge_set
    from engine.ui.target_list_view import TargetListView

    App._reset_target_menu_singleton()

    # Construct the menu via the real SDK call.
    import Bridge.TacticalMenuHandlers as TMH
    pTacticalWindow = App.TacticalControlWindow_GetTacticalControlWindow()
    TMH.CreateTargetList(pTacticalWindow)

    # Set up game + bridge set.
    mission = Mission()
    mission.GetEnemyGroup().AddName("Kor")
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    try:
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        wire_to_bridge_set(bridge)

        # Spawn a real ship with default subsystems.
        kor = ShipClass_Create("Kor")
        kor.SetName("Kor")
        bridge.AddObjectToSet(kor, "Kor")  # fires the subscriber → RebuildShipMenu

        # Verify the row landed in the singleton with subsystems.
        menu = App.STTargetMenu_GetTargetMenu()
        row = menu.GetObjectEntry(kor)
        assert row is not None
        assert row.GetAffiliation() == "ENEMY"
        assert len(row._children) > 0  # subsystems populated

        # Render the view payload and verify the shape.
        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        kor_row = next(r for r in state["rows"] if r["name"] == "Kor")
        assert kor_row["affiliation"] == "ENEMY"
        assert "hull" in kor_row and 0 <= kor_row["hull"] <= 100
        assert "shields" in kor_row and 0 <= kor_row["shields"] <= 100
        assert isinstance(kor_row["subsystems"], list)
        assert len(kor_row["subsystems"]) > 0
        subsystem_names = [s["name"] for s in kor_row["subsystems"]]
        # All names are non-empty strings.
        for n in subsystem_names:
            assert isinstance(n, str) and n
    finally:
        _set_current_game(None)
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/integration/test_target_list_subsystems.py -v`
Expected: PASS.

If FAIL: read the traceback. Common gaps:
- A specific subsystem accessor (`GetName`, etc.) returns None → check `engine/appc/subsystems.py` for the missing override.
- Hull or shield percentage clamping → verify the property exposes 0-100; if it exposes a 0-1 scale, multiply by 100 in `_query_*_percentage`.

- [ ] **Step 3: Final visual verification**

```bash
cmake --build build -j 2>&1 | tail -3
./build/dauntless
```

Press SPACE → tactical view. Confirm:
- Real ship names visible (USS Galaxy and whatever M2Objects spawns).
- Each row has a yellow hull bar and a purple shield bar on the right.
- Each row has nested subsystem rows under it (sensor, weapons, shields, hull, etc.) with smaller text and a `•` bullet.
- Clicking a ship row highlights it with the +0.20 affiliation tint.
- Clicking a subsystem row highlights it AND (the ship row remains highlighted, since both ship + subsystem are now the target).
- Pressing SPACE again hides the whole panel.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_target_list_subsystems.py
git commit -m "$(cat <<'EOF'
target_list: end-to-end integration test for subsystem rendering

Loads the real SDK CreateTargetList, populates a real ship with
default subsystems through the bridge set, and verifies the full
payload shape (affiliation, hull%, shields%, nested subsystems).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes (for the executor)

Final sanity pass after Task 16:

```bash
uv run pytest -q                  # full suite green
cmake --build build -j            # native build clean
./build/dauntless                 # visual verification
```

The one pre-existing failure in `test_fire_script_choose_subsystem.py` is the dict-iteration flake — not related to this work.

A quick incremental test command for any task in this plan:
```bash
uv run pytest tests/unit/test_panel.py tests/unit/test_panel_registry.py \
              tests/unit/test_set_subscribers.py \
              tests/unit/test_target_menu_bridge_subscription.py \
              tests/unit/test_target_menu_shim.py \
              tests/unit/test_target_list_view.py \
              tests/unit/test_sensor_visibility.py \
              tests/integration/test_target_list_sdk_integration.py \
              tests/integration/test_target_list_subsystems.py -v
```

## What's deferred to follow-up plans

These are explicitly out of scope here; surface them when this plan is done:

1. **Save/load + persistent target restore.** The engine does not support save/load at all yet. Once it does, the persistent-target hint (`STTargetMenu.GetPersistentTarget` / `SetPersistentTarget`) needs to be serialised and restored — the shim is already in place; only the save/load plumbing is missing.
2. **Real sensor distance.** This plan uses a fixed 30000-unit range. Replace with `SensorProperty.GetMaxRange()` reading from the player's sensor subsystem; also gate on sensor health (`disabled` ships shouldn't see anything).
3. **Sensor identification (`ShowUnknownName`/`ShowRealName`).** Out-of-range or unidentified ships should display a generic "Unknown Contact" label instead of the real name. The shim methods are no-ops; engine integration is a follow-up.
4. **Subsystem health bars.** Each subsystem row currently shows only the name. A future plan could add a small bar per subsystem showing condition.
5. **Localized ship display names.** If a mission exposes a separate display name (TGL-localized hull class) distinct from the internal `ship.GetName()` identifier, plumb that through. Today the row label is the raw `GetName()`.
6. **Pause-menu refactor onto Panel base.** The legacy fallback works; the refactor is purely tidy-up.
7. **Reticule rendering in the 3D scene.** Parked by user decision; revisit when subsystem targeting is solid and we can draw the active-subsystem marker.
