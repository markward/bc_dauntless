# Remove RmlUi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip every trace of RmlUi from the main branch — build no longer fetches/links it, runtime has no UI surface — while keeping the 3D scene, audio, inputs, bridge view, and throttle/turn controls working.

**Architecture:** Pure deletion across three layers: Python (`engine/ui/`, `engine/mission_picker.py`, the UI block of `engine/host_loop.py`), C++ bindings (UI-shaped `m.def` entries + globals in `host_bindings.cc`), and the native `ui` library / RmlUi FetchContent / `native/assets/ui/` assets. Order matters: peel callers first so each commit leaves the build green.

**Tech Stack:** CMake, CPython 3.11, pybind11, GLFW, RmlUi (departing).

**Source spec:** [docs/superpowers/specs/2026-05-24-remove-rmlui-design.md](../specs/2026-05-24-remove-rmlui-design.md).

---

## File Inventory

**Files deleted (whole):**
- `engine/ui/__init__.py`, `_dom.py`, `bindings.py`, `button.py`, `collapsible.py`, `panel.py`, `stat_row.py`, `target_list.py`, `theme.py`
- `engine/mission_picker.py`
- `native/src/ui/CMakeLists.txt`, `UiSystem.cc/h`, `PanelDocument.cc/h`, `HudDocument.cc/h`
- `native/assets/ui/components.rcss`, `hud.rcss`, `hud.rml`, `panel.rml`, `fonts/` (whole subtree)
- `tests/ui/` (whole directory)
- `tests/test_mission_picker.py`
- `tests/host/test_target_panel_integration.py`
- `tests/host/test_target_panel_subsystems.py`
- `tests/host/test_panel_overflow.py`

**Files modified:**
- `engine/host_loop.py` — drop UI block, picker, F7/F8/F9, `_cursor_over_panel`, `bridge_hud`, stat updates, OPEN_STBC_HOST_MISSION env path; add `_update_ui_for_tick` stub.
- `engine/renderer.py` — drop `ui_assets_root` param on `init`, delete `set_hud_state` wrapper.
- `native/src/host/host_bindings.cc` — drop UI includes, globals, `ui_assets_root` ctor arg, shutdown reset, frame render, all UI `m.def` entries.
- `native/src/host/CMakeLists.txt` — drop `ui` from both `target_link_libraries` lists.
- `native/CMakeLists.txt` — drop RmlUi `FetchContent` block + the three `RMLUI_*` cache vars + `add_subdirectory(src/ui)`.
- `CLAUDE.md` — drop the UI-components row from "Key reference material".

**Files audited (touched only if grep finds coupling):**
- `tests/host/test_bindings_smoke.py` — already uses `init(w, h, title)` signature; no change expected.
- `tests/audio/test_engine_rumble.py` — verify no `engine.ui` import.

---

## Task 0: Baseline snapshot

**Goal:** Confirm we're starting from green so any regression later is attributable to this PR.

- [ ] **Step 1: Configure + build the project**

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: build succeeds, `build/dauntless` and `build/python/_dauntless_host.cpython-*.so` exist.

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest -q
```

Expected: all tests pass (note the count, e.g. "N passed"). If any test is already failing on `main`, record it — it's pre-existing and not our problem to fix here.

- [ ] **Step 3: Save the baseline counts to a scratch note**

Just keep them in your head / in the conversation. We'll compare in Task 8.

---

## Task 1: Delete UI-only test files

**Why first:** the about-to-be-deleted Python and C++ symbols still exist, so these tests still pass right now. Deleting them up front means the test suite stays green as we strip code in the next tasks.

**Files:**
- Delete: `tests/ui/` (whole directory)
- Delete: `tests/test_mission_picker.py`
- Delete: `tests/host/test_target_panel_integration.py`
- Delete: `tests/host/test_target_panel_subsystems.py`
- Delete: `tests/host/test_panel_overflow.py`

- [ ] **Step 1: Audit `tests/audio/test_engine_rumble.py` for UI coupling**

```bash
grep -n "engine\.ui\|UiPanel\|mission_picker" tests/audio/test_engine_rumble.py
```

Expected: no matches. (The file appeared in a prior `engine.ui` grep but only via a shared import chain.) If matches appear, note them — we'll fix that test in Task 3 alongside `host_loop.py`.

- [ ] **Step 2: Audit `tests/host/test_bindings_smoke.py`**

```bash
grep -n "create_panel\|set_hud_state\|toggle_ui\|panel_root\|set_ui_scale" tests/host/test_bindings_smoke.py
```

Expected: no matches. (The current file only checks `init`/`shutdown`/`should_close`/`frame`.) If matches appear, we'll prune in Task 6.

- [ ] **Step 3: Delete the test files**

```bash
rm -rf tests/ui/
rm tests/test_mission_picker.py
rm tests/host/test_target_panel_integration.py
rm tests/host/test_target_panel_subsystems.py
rm tests/host/test_panel_overflow.py
```

- [ ] **Step 4: Verify tests still collect and pass**

```bash
uv run pytest -q
```

Expected: all remaining tests pass. Test count is lower than baseline by ~30-40 tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: drop UI-only test suites ahead of RmlUi removal"
```

---

## Task 2: Strip the UI block from `engine/host_loop.py`

**Why:** removes every caller of `engine.ui`, `engine.mission_picker`, and the to-be-deleted host bindings. After this task, the next task can delete the Python UI package without orphaning references.

**Files:**
- Modify: `engine/host_loop.py`

Apply these edits in order. Run pytest after the final edit.

- [ ] **Step 1: Remove `_cursor_over_panel` helper**

Delete lines `engine/host_loop.py:1676-1688` (the whole `def _cursor_over_panel` function and its docstring). Verify the function is gone:

```bash
grep -n "_cursor_over_panel" engine/host_loop.py
```

Expected: only the call site at line ~2053 remains (we'll delete that in Step 4).

- [ ] **Step 2: Trim `run()` mission-resolution preamble**

Replace this block (around `engine/host_loop.py:1820-1850` in the original):

```python
def run(mission_name: Optional[str] = None,
        max_ticks: Optional[int] = None) -> int:
    """Boot the renderer, init the named mission, run until the window closes
    or max_ticks is reached. Returns 0 on clean exit.

    Mission resolution: ``mission_name`` argument wins; otherwise the
    ``OPEN_STBC_HOST_MISSION`` env var; otherwise ``SHIP_GATE_MISSION`` (the
    default M2Objects ship-gate mission). The env-var path lets
    ``./build/dauntless`` swap missions without recompiling, while
    preserving the existing default for the ship-gate tests.

    Debug knobs (env vars):
      OPEN_STBC_HOST_HEADLESS=1     — hide the window (used by tests).
      OPEN_STBC_HOST_VERBOSE=1      — print loaded ships, player position,
                                      camera state on the first tick.
      OPEN_STBC_HOST_FIXED_CAMERA=1 — ignore third-person follow; use a
                                      fixed camera at (0, 0, 150) looking
                                      at the world origin.
      OPEN_STBC_HOST_MISSION=<dotted> — override the loaded mission.
    """
    import os as _os
    verbose = _os.environ.get("OPEN_STBC_HOST_VERBOSE") == "1"
    fixed_camera = _os.environ.get("OPEN_STBC_HOST_FIXED_CAMERA") == "1"
    if mission_name is None:
        mission_name = _os.environ.get(
            "OPEN_STBC_HOST_MISSION", SHIP_GATE_MISSION)
```

with:

```python
def run(mission_name: Optional[str] = None,
        max_ticks: Optional[int] = None) -> int:
    """Boot the renderer, init the named mission, run until the window closes
    or max_ticks is reached. Returns 0 on clean exit.

    Mission resolution: ``mission_name`` argument wins; otherwise
    ``SHIP_GATE_MISSION`` (the default M2Objects ship-gate mission).

    Debug knobs (env vars):
      OPEN_STBC_HOST_HEADLESS=1     — hide the window (used by tests).
      OPEN_STBC_HOST_VERBOSE=1      — print loaded ships, player position,
                                      camera state on the first tick.
      OPEN_STBC_HOST_FIXED_CAMERA=1 — ignore third-person follow; use a
                                      fixed camera at (0, 0, 150) looking
                                      at the world origin.
    """
    import os as _os
    verbose = _os.environ.get("OPEN_STBC_HOST_VERBOSE") == "1"
    fixed_camera = _os.environ.get("OPEN_STBC_HOST_FIXED_CAMERA") == "1"
    if mission_name is None:
        mission_name = SHIP_GATE_MISSION
```

- [ ] **Step 3: Update `r.init(...)` call and drop UI/picker setup**

Replace this block (around `engine/host_loop.py:1855-1959`):

```python
    r.init(1280, 720, "open_stbc",
           str(PROJECT_ROOT / "native" / "assets" / "ui"))
    try:
        from engine import ui
        from engine.ui.target_list import TargetListController
        ui.init()

        # Target list panel — mirrors live ships from ship_lifecycle.
        # Stage 1: ship names + affiliation only. Flip show_subsystems=True
        # to add populated subsystem buttons per row (stage 2).
        target_panel = ui.UiPanel(id="targets", anchor="top-left",
                                  width_vw=18.0, height_vh=55.0,
                                  title="Targets")
        target_list = TargetListController(
            target_panel,
            player_provider=lambda: App.Game_GetCurrentPlayer(),
            show_subsystems=True,
        )

        # Debug stat panel, top-right. Replaces the old hud.rml document.
        # Height accommodates the title + 5 stat rows + the "Load Mission"
        # button at the bottom without clipping (the panel has overflow:
        # hidden so under-tall heights silently cut the button off).
        debug_panel = ui.UiPanel(id="debug", anchor="top-right",
                                 width_vw=18.0, height_vh=28.0,
                                 title="Debug", collapsible=True)
        stat_ship   = debug_panel.stat("Ship",   "---")
        stat_system = debug_panel.stat("System", "---")
        stat_pos    = debug_panel.stat("Pos",    "0 0 0")
        stat_rot    = debug_panel.stat("Rot",    "Y0\xb0 P0\xb0 R0\xb0")
        stat_alert  = debug_panel.stat("Alert",  "---")

        # Bridge view marker — visible only when KEY_SPACE has toggled
        # _ViewModeController into bridge mode. PoC: text-only, no
        # bridge geometry yet.
        bridge_hud = ui.UiPanel(id="bridge_hud", anchor="top",
                                width_vw=20.0, height_vh=6.0,
                                title="BRIDGE VIEW")
        bridge_hud.set_visible(False)

        # Controller owns the renderer, the nif-handle cache, and the
        # current mission session. _MissionLoader.load() runs the
        # mission init + scene build; HostController.swap_mission()
        # queues a deferred swap that drains at the next tick.
        controller = HostController()
        controller.renderer = r
        controller.loader = _MissionLoader(controller, verbose=verbose)
        controller.post_load_hook = target_list.rebuild_from_snapshot
```

with:

```python
    r.init(1280, 720, "open_stbc")
    try:
        # Controller owns the renderer, the nif-handle cache, and the
        # current mission session. _MissionLoader.load() runs the
        # mission init + scene build; HostController.swap_mission()
        # queues a deferred swap that drains at the next tick.
        controller = HostController()
        controller.renderer = r
        controller.loader = _MissionLoader(controller, verbose=verbose)
```

(`post_load_hook` stays defined on `HostController` — the controller is shared with `_drain_pending_swap`, which still checks `if self.post_load_hook is not None`. Just don't assign it.)

- [ ] **Step 4: Drop `target_list.rebuild_from_snapshot()` line**

Find and delete the line:

```python
        target_list.rebuild_from_snapshot()    # filter player after Game.SetPlayer
```

(Approximately at `engine/host_loop.py:1931` post-edit positions will have shifted; locate by grep.)

- [ ] **Step 5: Drop the mission-picker block**

Replace this block (around `engine/host_loop.py:1941-1952`):

```python
        # Mission picker — scans the SDK script tree and offers an
        # in-process swap via controller.swap_mission().
        from engine.missions import discover as discover_missions
        from engine.mission_picker import MissionPicker

        registry = discover_missions(PROJECT_ROOT / "sdk" / "Build" / "scripts")
        picker = MissionPicker(
            registry=registry,
            on_load=controller.swap_mission,
            on_cancel=lambda: None,
        )
        debug_panel.button("Load Mission", on_click=picker.open, radio=False)
```

with: (nothing — delete the whole block including the blank line above it.)

- [ ] **Step 6: Drop the `target_list.on_target_change` assignment**

Delete the three lines:

```python
        # Selecting a ship in the target panel snaps the chase orbit back
        # to defaults and engages target lock — overrides any manual
        # orbit the player had set. C key reverses (resets + unlocks).
        target_list.on_target_change = lambda _ship: cam_control.lock_to_target()
```

- [ ] **Step 7: Drop the `picker.drain()` per-tick call**

Locate (around `engine/host_loop.py:1985` originally):

```python
            # Drain deferred picker actions (close + on_load/on_cancel)
            # first — picker click handlers fire inside RmlUi's dispatch
            # so they queue rather than tear panels down synchronously.
            # Then drain any queued mission swap before scene work.
            picker.drain()
            had_pending_swap = controller.pending_swap is not None
```

Replace with:

```python
            had_pending_swap = controller.pending_swap is not None
```

- [ ] **Step 8: Drop F7/F8/F9 handlers and `_dust_enabled` local**

Locate the comment + handlers (around lines `2007-2014`):

```python
            # F7 toggles space dust; F8 toggles the RmlUi debugger
            # overlay; F9 toggles whole-UI visibility; ESC dismisses the
            # mission picker (no-op when it isn't open).
            if _h is not None and _h.key_pressed(_h.keys.KEY_F7):
                _dust_enabled = not _dust_enabled
                _h.dust_set_enabled(_dust_enabled)
            if _h is not None and _h.key_pressed(_h.keys.KEY_F8):
                _h.toggle_ui_debugger()
            if _h is not None and _h.key_pressed(_h.keys.KEY_F9):
                _h.toggle_ui_visibility()
```

Replace with:

```python
            # F10 (debug shield hit) is handled below. ESC exits
            # bridge view, handled below.
```

Also delete the `_dust_enabled = True   # mirrors DustPass default` line earlier in `run()` (around line 1981 originally) — the local is now unused.

- [ ] **Step 9: Simplify ESC handler — drop picker arm**

Find:

```python
            if _h is not None and _h.key_pressed(_h.keys.KEY_ESCAPE):
                # Order: exit bridge mode first, then dismiss any open
                # picker. If both apply, ESC handles both.
                _handle_esc_for_view_mode(view_mode)
                picker.handle_key_esc()
```

Replace with:

```python
            if _h is not None and _h.key_pressed(_h.keys.KEY_ESCAPE):
                _handle_esc_for_view_mode(view_mode)
```

- [ ] **Step 10: Drop panel scroll routing**

Find:

```python
            # Route scroll: cursor over the targets panel -> list scroll.
            # Otherwise camera zoom (the existing path).
            if scroll_y != 0.0 and _h is not None:
                if _cursor_over_panel(_h, target_panel.panel_id):
                    target_list.scroll(-int(round(scroll_y)))
                    scroll_y = 0.0  # consumed by panel; camera gets nothing
```

Delete the whole block (scroll already flows into `_apply_input` for camera zoom).

- [ ] **Step 11: Drop `bridge_hud.set_visible` per-tick line**

Find (around line 2129):

```python
            bridge_hud.set_visible(view_mode.is_bridge)
```

Delete the line.

- [ ] **Step 12: Drop per-tick stat updates**

Find this block (around lines 2131-2152):

```python
            if player is not None:
                _R = player.GetWorldRotation()
                _p = player.GetWorldLocation()
                _yaw, _pitch, _roll = _extract_ypr(_R)
                _set_name = next(
                    (n for n, s in App.g_kSetManager._sets.items()
                     if s is active_set),
                    ""
                ) if active_set is not None else ""
                try:
                    _raw_script = player.GetScript() or ""
                except Exception:
                    _raw_script = ""
                _ship_display = _raw_script.split(".")[-1] if _raw_script else "---"
                stat_ship.set_value(_ship_display)
                stat_system.set_value(_set_name or "---")
                stat_pos.set_value("%.1f %.1f %.1f" % (_p.x, _p.y, _p.z))
                stat_rot.set_value(
                    "Y%.0f\xb0 P%.0f\xb0 R%.0f\xb0" % (_yaw, _pitch, _roll))
                stat_alert.set_value(_format_alert_level(player.GetAlertLevel()))
```

Replace the whole block with a stub call:

```python
            _update_ui_for_tick(player, view_mode, session, active_set)
```

- [ ] **Step 13: Add the `_update_ui_for_tick` stub function**

Add at module scope, near the other helper functions (just before `def run(...)` is a good spot):

```python
def _update_ui_for_tick(player, view_mode, session, active_set) -> None:
    """CEF integration hook — Stage 2 wires this up. Currently a no-op."""
    return
```

- [ ] **Step 14: Confirm no orphaned references remain**

```bash
grep -nE "ui\.UiPanel|target_panel|debug_panel|bridge_hud|target_list|picker|stat_ship|stat_system|stat_pos|stat_rot|stat_alert|_cursor_over_panel|MissionPicker|engine\.mission_picker|engine\.ui|TargetListController|discover_missions|_dust_enabled|OPEN_STBC_HOST_MISSION" engine/host_loop.py
```

Expected: no matches. If any appear, fix before moving on.

- [ ] **Step 15: Run the test suite**

```bash
uv run pytest -q
```

Expected: all tests still pass. (The C++ bindings and Python `engine.ui` package still exist; nothing imports them now from host_loop.)

- [ ] **Step 16: Commit**

```bash
git add engine/host_loop.py
git commit -m "refactor(host_loop): strip RmlUi panel/picker/stat block, add _update_ui_for_tick stub"
```

---

## Task 3: Delete `engine/ui/`, `engine/mission_picker.py`, trim `engine/renderer.py`

**Files:**
- Delete: `engine/ui/` (whole directory)
- Delete: `engine/mission_picker.py`
- Modify: `engine/renderer.py` (drop `ui_assets_root` param, drop `set_hud_state` wrapper)

- [ ] **Step 1: Confirm nothing outside the deletion zone still imports them**

```bash
grep -rn "from engine import ui\|from engine\.ui\|import engine\.ui\|from engine\.mission_picker\|import engine\.mission_picker" engine/ tests/ --include="*.py"
```

Expected: no matches. (If matches appear, Task 2 missed a spot — go back and fix.)

- [ ] **Step 2: Delete the Python UI package and mission_picker**

```bash
rm -rf engine/ui/
rm engine/mission_picker.py
```

- [ ] **Step 3: Edit `engine/renderer.py` — drop `ui_assets_root` from `init`**

Replace lines 13-14:

```python
def init(width: int, height: int, title: str, ui_assets_root: str = "") -> None:
    _h.init(width, height, title, ui_assets_root)
```

with:

```python
def init(width: int, height: int, title: str) -> None:
    _h.init(width, height, title)
```

- [ ] **Step 4: Edit `engine/renderer.py` — delete `set_hud_state` wrapper**

Delete lines 121-126:

```python
def set_hud_state(state: dict) -> None:
    """Push per-tick HUD data (pos, yaw/pitch/roll deg, system, ship) to the overlay.

    No-op if the UI system was not initialized (headless runs, empty ui_assets_root).
    """
    _h.set_hud_state(state)
```

- [ ] **Step 5: Run pytest**

```bash
uv run pytest -q
```

Expected: all tests pass. (Bindings still exist; just no Python wrappers around them now.)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete engine/ui package, engine/mission_picker, set_hud_state wrapper"
```

---

## Task 4: Strip UI from `host_bindings.cc` + host CMake

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `native/src/host/CMakeLists.txt`

- [ ] **Step 1: Remove UI includes**

Delete these two lines from `host_bindings.cc` (around lines 33-34):

```cpp
#include <ui/UiSystem.h>
#include <ui/PanelDocument.h>
```

- [ ] **Step 2: Remove UI globals**

Delete these two lines (around lines 93-94):

```cpp
std::unique_ptr<ui::UiSystem> g_ui_system;
ui::HudState                  g_hud_state;
```

- [ ] **Step 3: Trim `init()` — drop `ui_assets_root` parameter and UiSystem construction**

Locate the `init` function (starts around line 145). The signature includes `const std::string& ui_assets_root = ""` — drop it. Inside, remove the block:

```cpp
    if (!ui_assets_root.empty()) {
        g_ui_system = std::make_unique<ui::UiSystem>(
            g_window->glfw(),
            std::filesystem::path(ui_assets_root));
    }
```

(Also remove any `if (g_ui_system) g_hud_state = ui::HudState{};` reset line — see Step 4.)

- [ ] **Step 4: Trim `shutdown()` — drop UiSystem reset**

Find lines (around 185-187):

```cpp
    // UI system must be destroyed before g_window — RmlUi shutdown calls into
    // ...
    g_ui_system.reset();
```

Delete both the comment and the line.

Also remove (around line 222):

```cpp
    g_hud_state = ui::HudState{};
```

- [ ] **Step 5: Trim `frame()` — drop UiSystem update/render**

Find (around lines 292-294):

```cpp
    if (g_ui_system) {
        g_ui_system->update_hud(g_hud_state);
        g_ui_system->render(fw, fh);
    }
```

Delete the whole block.

- [ ] **Step 6: Update the `m.def("init", ...)` registration**

Find (around line 316):

```cpp
    m.def("init", &init,
          py::arg("width"), py::arg("height"), py::arg("title"),
          py::arg("ui_assets_root") = "",
          "Open a window and initialise the renderer. ui_assets_root points to "
          "the directory holding panel.rml + components.rcss + fonts/.");
```

Replace with:

```cpp
    m.def("init", &init,
          py::arg("width"), py::arg("height"), py::arg("title"),
          "Open a window and initialise the renderer.");
```

- [ ] **Step 7: Delete all UI-shaped `m.def` entries**

In the bindings registration block, delete every `m.def(...)` for these names. Find by searching `m.def("<name>"`:

- `set_hud_state`
- `set_ui_scale`
- `toggle_ui_debugger`
- `toggle_ui_visibility`
- `create_panel`
- `destroy_panel`
- `clear_panel`
- `set_panel_visible`
- `panel_root`
- `set_panel_css_var`
- `panel_bounds`
- `append_div`
- `remove_element`
- `set_class`
- `set_text`
- `set_element_property`
- `on_click`
- `on_dblclick`
- The **element-id variant** of `set_visible` (the one in the UI section, around line 1005, that iterates `g_ui_system->panels_for_bindings()`). The instance-id variant at line 350 STAYS — that's `g_world.set_visible`, not UI.

After this step, confirm no `g_ui_system` references remain:

```bash
grep -n "g_ui_system\|g_hud_state\|ui::" native/src/host/host_bindings.cc
```

Expected: no matches.

- [ ] **Step 8: Trim `native/src/host/CMakeLists.txt`**

Find this block:

```cmake
target_link_libraries(_dauntless_host PRIVATE renderer ui scenegraph assets dauntless_audio)
```

Replace with:

```cmake
target_link_libraries(_dauntless_host PRIVATE renderer scenegraph assets dauntless_audio)
```

And find:

```cmake
target_link_libraries(dauntless
    PRIVATE
        Python3::Python
        pybind11::embed
        renderer
        ui
        scenegraph
        assets
        dauntless_audio
)
```

Replace with:

```cmake
target_link_libraries(dauntless
    PRIVATE
        Python3::Python
        pybind11::embed
        renderer
        scenegraph
        assets
        dauntless_audio
)
```

- [ ] **Step 9: Rebuild**

```bash
cmake --build build -j
```

Expected: build succeeds. (The `ui` library and its sources still exist on disk — `native/CMakeLists.txt` still has `add_subdirectory(src/ui)` — but neither host target links it anymore. That's intentional and we clean up in Task 5.)

- [ ] **Step 10: Run pytest**

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/host/CMakeLists.txt
git commit -m "refactor(host): drop UI globals, bindings, and ui_assets_root from host_bindings"
```

---

## Task 5: Delete `native/src/ui/` and drop RmlUi from `native/CMakeLists.txt`

**Files:**
- Delete: `native/src/ui/` (whole directory)
- Modify: `native/CMakeLists.txt`

- [ ] **Step 1: Delete the UI library source tree**

```bash
rm -rf native/src/ui/
```

- [ ] **Step 2: Trim `native/CMakeLists.txt` — remove `add_subdirectory(src/ui)`**

Find:

```cmake
# UI library (RmlUi integration + HUD).
add_subdirectory(src/ui)
```

Delete both lines.

- [ ] **Step 3: Trim `native/CMakeLists.txt` — remove RmlUi FetchContent**

Find the block (around lines 37-49):

```cmake
# RmlUi — HTML/CSS UI framework. Samples/tests off so RmlUi only builds RmlCore;
# we compile the GLFW+GL3 backends ourselves in native/src/ui so they pick up
# our existing glad + glfw targets rather than any system copies.
FetchContent_Declare(
    RmlUi
    GIT_REPOSITORY https://github.com/mikke89/RmlUi.git
    GIT_TAG        6.0
)
set(RMLUI_SAMPLES       OFF   CACHE BOOL   "" FORCE)
set(RMLUI_TESTS         OFF   CACHE BOOL   "" FORCE)
set(RMLUI_LOTTIE_PLUGIN OFF   CACHE BOOL   "" FORCE)
FetchContent_MakeAvailable(RmlUi)
```

Delete the whole block.

- [ ] **Step 4: Re-configure from scratch (FetchContent cache cleanup)**

```bash
rm -rf build
cmake -B build -S . && cmake --build build -j
```

Expected: configure does NOT mention RmlUi; build succeeds; `build/_deps/` no longer contains an `rmlui-src` directory.

- [ ] **Step 5: Confirm no RmlUi symbols in the final binary**

```bash
nm build/dauntless 2>/dev/null | grep -i rml | head
```

Expected: empty output.

```bash
find build -name '*Rml*' -o -name '*rmlui*' 2>/dev/null
```

Expected: empty output.

- [ ] **Step 6: Run pytest**

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "build: drop RmlUi FetchContent + native/src/ui library"
```

---

## Task 6: Delete `native/assets/ui/` and clean up audit items

**Files:**
- Delete: `native/assets/ui/` (whole directory)
- Audit: `tests/host/test_bindings_smoke.py` (no edit expected)
- Audit: `tests/audio/test_engine_rumble.py` (no edit expected)

- [ ] **Step 1: Delete the UI assets directory**

```bash
rm -rf native/assets/ui/
```

- [ ] **Step 2: Confirm nothing references the deleted paths**

```bash
grep -rn "native/assets/ui\|panel\.rml\|hud\.rml\|components\.rcss\|hud\.rcss\|Antonio-Regular\|NotoSansSymbols2" engine/ native/ tests/ docs/ 2>/dev/null
```

Expected: no matches in `engine/`, `native/`, or `tests/`. (Docs may still mention the old paths; that's fine.)

- [ ] **Step 3: Re-audit `tests/host/test_bindings_smoke.py`**

```bash
grep -n "create_panel\|set_hud_state\|toggle_ui\|panel_root\|set_ui_scale\|ui_assets" tests/host/test_bindings_smoke.py
```

Expected: no matches. If any appear, delete those assertions and re-run pytest.

- [ ] **Step 4: Re-audit `tests/audio/test_engine_rumble.py`**

```bash
grep -n "engine\.ui\|UiPanel\|mission_picker" tests/audio/test_engine_rumble.py
```

Expected: no matches. If any appear, fix and re-run pytest.

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "build: drop native/assets/ui directory"
```

---

## Task 7: Touch up `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Remove the UI-components row from the reference table**

Find the row in the "Key reference material" table (in `CLAUDE.md`):

```markdown
| UI components | `engine/ui/`, `docs/project/superpowers/specs/2026-05-11-ui-components-design.md` | Reusable Button + CollapsibleList; theme registries mirror LoadInterface.py |
```

Delete the entire row.

- [ ] **Step 2: Confirm no other CLAUDE.md sections mention RmlUi-specific concepts**

```bash
grep -n -i "rmlui\|panel\.rml\|hud\.rml\|UiPanel\|UiButton\|engine/ui\|engine\.ui\|mission_picker" CLAUDE.md
```

Expected: no matches. If a stray mention appears, remove it.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: drop UI-components row from CLAUDE.md reference table"
```

---

## Task 8: Final verification gate

Runs the four checks listed in the spec's verification gate.

- [ ] **Step 1: Fresh build from a clean tree**

```bash
rm -rf build
cmake -B build -S . && cmake --build build -j
```

Expected: configure + build succeed. No RmlUi text in the configure output.

- [ ] **Step 2: Confirm no RmlUi in linked binary**

```bash
nm build/dauntless 2>/dev/null | grep -i rml
echo "---"
find build -name '*Rml*' -o -name '*rmlui*' 2>/dev/null
```

Expected: both empty.

- [ ] **Step 3: Pytest green**

```bash
uv run pytest -q
```

Expected: all tests pass (count = baseline minus the ~30-40 UI tests deleted in Task 1).

- [ ] **Step 4: Manual smoke — launch the game**

```bash
./build/dauntless
```

In the running window, verify:
1. The SHIP_GATE_MISSION scene renders (sun, dust, player ship visible).
2. No UI overlay (no Targets panel, no Debug panel, no HUD text).
3. WASD / throttle digits visibly move the player ship.
4. SPACE enters bridge view (interior visible, camera responds to mouse motion).
5. ESC exits bridge view (back to exterior orbit camera).
6. F10 triggers a debug shield hit (shield bubble flash on the player ship).
7. Window-X closes cleanly with no console error.

If any check fails, stop and fix in this PR.

- [ ] **Step 5: Final commit (only if any verification produced changes)**

If steps 1-4 all passed without edits, skip. Otherwise:

```bash
git add -A
git commit -m "fix: address findings from RmlUi-removal verification"
```

- [ ] **Step 6: Summarise the PR**

State, for hand-off:
- Files deleted: count of removed files.
- LOC removed (rough): `git diff --stat main..HEAD | tail -1`.
- Verification: build clean / pytest N passed / manual smoke ✓.

---

## Self-review notes

Cross-check against [the spec](../specs/2026-05-24-remove-rmlui-design.md):

- ✓ Build-system removals (Task 5 covers `native/CMakeLists.txt`; Task 4 covers `native/src/host/CMakeLists.txt`).
- ✓ `native/src/ui/` deletion (Task 5) and `native/assets/ui/` deletion (Task 6).
- ✓ All `host_bindings.cc` deletions enumerated in Task 4 Step 7.
- ✓ Python: `engine/ui/`, `engine/mission_picker.py`, `engine/renderer.py` edits (Task 3).
- ✓ `engine/host_loop.py` block (Task 2 covers all 14 sub-edits: imports, panels, picker, F-keys, `_cursor_over_panel`, scroll routing, ESC arm, stat updates, env-var drop, `_update_ui_for_tick` stub).
- ✓ Test deletions enumerated (Task 1) plus audits (Task 6).
- ✓ Docs touch-ups (Task 7).
- ✓ Verification gate (Task 8) matches the spec's four checks.
- ✓ Key bindings: F7/F8/F9 removed (Task 2 Step 8); F10 kept (untouched in Task 2); SPACE + ESC bridge view paths kept (only the picker arm removed from ESC in Task 2 Step 9).
- ✓ No placeholders — every code edit shows the exact before/after, every shell command shows expected output.
