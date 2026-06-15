# Remove RmlUi — Stage 1 of RmlUi → CEF Migration

**Status:** Approved 2026-05-24
**Scope:** Mechanical removal. No replacement UI in this stage; CEF arrives in a follow-up.

## Goal

Strip every trace of RmlUi from the main branch so the build no longer fetches/links it and the running game has no UI surface. The 3D scene, audio, inputs, bridge view, and throttle/turn controls must continue to work after the cut. This produces a clean baseline for the CEF integration that follows.

## Non-goals

- Introducing CEF. That is a separate stage; this PR only deletes.
- Refactoring renderer, audio, scene-graph, NIF, or SDK shim code beyond what is required to compile after the UI is gone.
- Preserving any UI state, mission-picker UX, or in-game debug overlays. They will be reintroduced on top of CEF later if needed.

## What gets removed

### Build system

- `native/CMakeLists.txt`:
  - Drop the `FetchContent_Declare(RmlUi …)` block and `FetchContent_MakeAvailable(RmlUi)`.
  - Drop the three `set(RMLUI_… OFF CACHE BOOL "" FORCE)` lines.
  - Drop `add_subdirectory(src/ui)`.
- `native/src/host/CMakeLists.txt`:
  - Drop `ui` from the `target_link_libraries(_dauntless_host …)` and `target_link_libraries(dauntless …)` lists.
- `native/src/ui/` — whole directory deleted (CMakeLists.txt, UiSystem.cc/.h, PanelDocument.cc/.h, HudDocument.cc/.h).
- `native/assets/ui/` — whole directory deleted (panel.rml, hud.rml, components.rcss, hud.rcss, fonts/).

### Native host bindings — `native/src/host/host_bindings.cc`

Remove:
- Includes: `#include <ui/UiSystem.h>`, `#include <ui/PanelDocument.h>`.
- Globals: `g_ui_system`, `g_hud_state`.
- `init()` parameter `ui_assets_root` and the UiSystem construction branch that consumes it.
- `shutdown()` — the `g_ui_system.reset()` call. The "destroy UI before window" ordering comment goes with it.
- `frame()` — the `if (g_ui_system) { update_hud; render }` block.
- The `m.def(...)` entries: `set_hud_state`, `set_ui_scale`, `toggle_ui_debugger`, `toggle_ui_visibility`, `create_panel`, `destroy_panel`, `clear_panel`, `set_panel_visible`, `panel_root`, `set_panel_css_var`, `panel_bounds`, `append_div`, `remove_element`, `set_class`, `set_text`, `set_element_property`, `on_click`, `on_dblclick`, and the **element-id-variant** of `set_visible`. The instance-id `set_visible` (renderer visibility for ship/planet instances) **stays**.

Keep:
- `init` signature is now `init(width, height, title)`. The `py::arg("ui_assets_root") = ""` default goes with it.

### Python engine

- `engine/ui/` — whole package deleted (`__init__.py`, `_dom.py`, `bindings.py`, `button.py`, `collapsible.py`, `panel.py`, `stat_row.py`, `target_list.py`, `theme.py`).
- `engine/mission_picker.py` — deleted.
- `engine/renderer.py`:
  - `init(width, height, title, ui_assets_root="")` becomes `init(width, height, title)`. Forward the trimmed signature to `_h.init`.
- `engine/host_loop.py`:
  - Remove imports: `from engine import ui`, `from engine.ui.target_list import TargetListController`, `from engine.missions import discover as discover_missions`, `from engine.mission_picker import MissionPicker`.
  - Remove `ui.init()` and all `UiPanel`/`stat_*`/`bridge_hud` setup (the block beginning "Target list panel" through "bridge_hud.set_visible(False)").
  - Remove the `MissionPicker` construction and `debug_panel.button("Load Mission", …)`.
  - Remove `picker.drain()` and `picker.handle_key_esc()` per-tick calls.
  - Remove `_cursor_over_panel(...)` helper function and its call site (the scroll-routing-to-panel branch). Scroll passes through unchanged to the camera.
  - Remove `target_list.on_target_change`, `target_list.rebuild_from_snapshot`, `controller.post_load_hook` assignments tied to the target list.
  - Remove the F7 (`dust_set_enabled`), F8 (`toggle_ui_debugger`), F9 (`toggle_ui_visibility`) handlers. Keep the F10 (debug shield hit) handler.
  - Remove `bridge_hud.set_visible(view_mode.is_bridge)` per-tick line.
  - Remove the per-tick stat updates (`stat_ship.set_value(...)`, etc.) and the surrounding `if player is not None` block that only existed to feed them.
  - Drop `_dust_enabled` local (no longer toggled by F7) — `dust_set_enabled` still exists as a binding but isn't called from host_loop.
  - Adjust ESC handling: remove the picker dismissal arm; keep `_handle_esc_for_view_mode(view_mode)`.
  - Collapse whatever remains of the per-tick UI work into a `_update_ui_for_tick(...)` stub function that takes whatever context CEF will need (player, view_mode, session). For Stage 1 the body is `pass` plus a one-line `# CEF integration hook — Stage 2 wires this up.` comment.
  - Mission selection: drop the `_os.environ.get("OPEN_STBC_HOST_MISSION", SHIP_GATE_MISSION)` branch. `mission_name` is `SHIP_GATE_MISSION` unconditionally when callers don't pass one. `OPEN_STBC_HOST_VERBOSE` and `OPEN_STBC_HOST_FIXED_CAMERA` stay — they aren't UI.

### Tests

Delete:
- `tests/ui/` — whole directory.
- `tests/test_mission_picker.py`.
- `tests/host/test_target_panel_integration.py`.
- `tests/host/test_target_panel_subsystems.py`.
- `tests/host/test_panel_overflow.py`.

Audit (do not delete blindly):
- `tests/host/test_bindings_smoke.py` — strip any assertions on removed binding names (`create_panel`, `set_hud_state`, etc.). Keep the rest.
- `tests/audio/test_engine_rumble.py` — appeared in the `engine.ui` grep. Verify whether it imports the UI package (likely incidental) and patch the import out if so.

Anything else that fails to import after deletion is in scope to fix as part of this PR. Do not introduce new tests.

### Documentation touch-ups

- `CLAUDE.md` "Key reference material" table — remove the row for `engine/ui/` + `docs/superpowers/specs/2026-05-11-ui-components-design.md`. The space-dust row stays (dust_pass is renderer code, not UI).
- `THIRD_PARTY_NOTICES.md` — remove the RmlUi entry if present.

## What stays untouched

- Window + GL + GLFW initialisation.
- Scene graph and every render pass (sun, dust, bridge, shield, torpedo, phaser, hit_vfx, lens_flare, backdrop).
- Input bindings: `key_pressed`, `key_state`, `consume_scroll_y`, `consume_mouse_delta`, `cursor_pos`, `set_cursor_locked`, `mouse_button_pressed`, `mouse_button_released`, the GLFW key-code submodule.
- Bridge view: `SPACE` toggle, `ESC` exit, `_BridgeCamera`, `_ViewModeController`, `_apply_view_mode_side_effects`, `set_bridge_camera`, `set_bridge_lighting`, `create_bridge_instance`, `bridge_pass_set_enabled`. `LoadBridge.py` shim.
- Player controls: `_PlayerControl` (throttle, alert keys, turn, fire), `_CameraControl` (orbit/zoom), `_apply_input`, `_apply_alert_keys`, `_poll_mouse_buttons`.
- Audio (`init_audio`, `tick_audio`, `shutdown_audio`, alert audio, engine rumble, tg_sound).
- Mission system (`engine/missions/`, `MissionSession`, `_MissionLoader`, `HostController`, `_drain_pending_swap`, `swap_mission`).
- SDK shims (`App.py`, `LoadBridge.py`).
- NIF loader, assets cache, scenegraph world/camera.
- Renderer-side `dust_set_enabled`, `read_pixel`, `framebuffer_size` bindings — kept available even though host_loop no longer drives them.

## Key bindings after the cut

| Key       | Behavior            | Status |
|-----------|---------------------|--------|
| WASD / throttle digits | Player ship motion | keep   |
| Shift + 1/2/3 | Alert levels      | keep   |
| Mouse buttons | Fire/select         | keep   |
| Scroll wheel  | Camera zoom         | keep (no more panel route) |
| SPACE     | Bridge view toggle  | keep   |
| ESC       | Exit bridge view    | keep (picker arm removed) |
| F7        | Dust toggle         | **removed** |
| F8        | RmlUi debugger      | **removed** |
| F9        | UI visibility       | **removed** |
| F10       | Debug shield hit    | keep   |

## Verification gate

The work is not complete until all four pass:

1. **Build clean.** `cmake -B build -S . && cmake --build build -j` succeeds. `nm build/dauntless | grep -i rml` is empty. `find build -name '*Rml*'` is empty (apart from the FetchContent cache, which should not be referenced from the linked binary).
2. **Runtime green.** `./build/dauntless` opens a window, draws the SHIP_GATE_MISSION scene with sun, dust, ship, no UI overlay, no console errors. Closes cleanly on window-X.
3. **Pytest green.** `uv run pytest` passes with no skips beyond pre-existing ones.
4. **Manual smoke.** With the binary running:
   - WASD / throttle keys move the player ship visibly.
   - SPACE enters bridge view (interior visible, camera orientation responds to mouse).
   - ESC exits bridge view (back to exterior orbit camera).
   - F10 triggers a debug shield hit (shield bubble flash on the player ship).

If any verification fails, fix in this PR — do not defer.

## Out of scope (deliberately)

- Restoring an in-game mission picker. CLI/env mission selection are also gone; the binary boots `SHIP_GATE_MISSION` and nothing else until CEF lands.
- Restoring stat overlays or any HUD text.
- Touching the `.claude/worktrees/sdk-ui-shim/` worktree where prior CEF work lives — that is the playground for Stage 2 and not part of this cleanup.
- Removing `glfw`, `glad`, or any other library RmlUi happened to share with the renderer.
