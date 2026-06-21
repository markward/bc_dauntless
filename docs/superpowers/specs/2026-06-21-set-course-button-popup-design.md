# Set Course → Button + "Setting Course" Popup — Design

**Date:** 2026-06-21
**Status:** Approved, pending implementation
**Branch:** `feat/set-course-button-popup`

## Goal

Override the Helm crew menu's **"Set Course"** item — today a parent menu
(`SortedRegionMenu`) that expands inline into a sorted list of warp-destination
regions — and replace it with a single **button**. Clicking the button opens a
simple popup modal showing the message *"Setting course…"*, reusing the existing
`cp-*` modal component shared by the Configuration and Developer Options panels.

This is the first step toward a real course-setting modal. The popup is
structured so the SDK region list can later be wired into it without
restructuring; for now it is a placeholder that shows a message and an OK button.

> **Note:** A richer set-course implementation exists on the unmerged branch
> `feat/set-course-popup` (system list + warp points). This branch deliberately
> starts fresh from `main` with the minimal placeholder, per direction. The two
> branches are independent; this one uses the panel name `setting-course` to
> avoid any collision with that branch's `set-course` panel.

## Context

- The Set Course menu is built in
  `sdk/Build/scripts/Bridge/HelmMenuHandlers.py:197` as
  `App.SortedRegionMenu_CreateW(...)` and added as a child of the Helm menu.
  In our headless tier it is `engine.appc.tg_ui.st_widgets.SortedRegionMenu`,
  a subclass of `STMenu`. It is the **only** `SortedRegionMenu` in the helm tree.
- The engine projects the SDK menu trees into CEF via
  `engine/ui/crew_menu_panel.py` → `native/assets/ui-cef/js/crew_menus.js`.
  A node of `type:"menu"` renders with a caret and inline accordion expand
  behaviour (firing `crew-menu/expand:<id>`); a node of `type:"button"` renders
  as a caret-less leaf row that fires `crew-menu/click:<id>`.
- The reusable popup is the `cp-*` modal framework defined in
  `native/assets/ui-cef/css/configuration_panel.css`, driven by a `Panel`
  subclass registered in `PanelRegistry`. `engine/ui/developer_options_panel.py`
  is the closest minimal example.

## Decisions

- **Intercept point: engine render layer**, not the SDK source. The SDK
  `HelmMenuHandlers.py` stays byte-untouched; the override lives in
  `crew_menu_panel.py`. Consistent with "SDK drives everything" — the override
  is fully reversible and the SDK ground truth is preserved.
- **Scope: foundation for real course-setting.** The panel is built now as a
  placeholder ("Setting course…") but carries a `destinations` list seam so the
  region tree can be populated later without restructuring.
- Clicking Set Course **closes the open helm menu** as the modal opens.
- The popup is a lightweight modal that **does not freeze the sim** (unlike
  pause-menu modals). Acceptable for the placeholder; real course-setting can
  revisit this when it actually sets a course.

## Components

### 1. Render-layer override — `engine/ui/crew_menu_panel.py`

`_snapshot_node`: add an `isinstance(widget, SortedRegionMenu)` check **before**
the existing `isinstance(widget, STMenu)` branch (`SortedRegionMenu` subclasses
`STMenu`, so order matters). When matched, emit the node as
`type:"button"` — a plain `{id, type, label, enabled, visible}` dict with **no**
`children` and **no** `expanded` key. The CEF renderer then draws it as a leaf
button; `crew_menus.js` is unchanged.

`dispatch_event`, `click:` branch: the resolved widget for Set Course is a
`SortedRegionMenu` (an `STMenu`, *not* an `STButton`), so the existing
button-activation path (`SendActivationEvent` + `ET_ST_BUTTON_CLICKED`) is
skipped by construction. Add a branch: if the clicked widget is a
`SortedRegionMenu`, close the open crew menu (`self._open_menu_id = None`,
`self._expanded_ids.clear()`) and invoke the injected callback
`self._on_set_course(widget)`. The widget is passed through so the future region
list has access to its source tree. **No SDK event is fired** — the placeholder
does not set a course.

`__init__`: add an optional `on_set_course=None` callback parameter, stored as
`self._on_set_course`. Guard the call site so a `None` callback is a silent
no-op (keeps existing tests and any non-wired construction working). This avoids
a hard panel↔panel import; host_loop injects the wiring.

Import `SortedRegionMenu` from `engine.appc.tg_ui.st_widgets`.

### 2. New panel — `engine/ui/setting_course_panel.py`

A `Panel` subclass modeled on `DeveloperOptionsPanel`, reusing the `cp-*` CSS.

- `name` → `"setting-course"`
- `open(course_menu=None)` — sets `_visible = True`, stores
  `self._course_menu = course_menu` for the future region wiring.
- `close()` — `_visible = False`.
- `is_open()` — returns `_visible` (needed by the modal-blocker ladder).
- `render_payload()` — snapshot-cached (mirror DeveloperOptionsPanel's
  `_last_pushed` tuple pattern). When hidden, emit
  `setSettingCoursePanel({"visible": false})`. When visible, emit
  `setSettingCoursePanel({...})` with:
  ```json
  {
    "visible": true,
    "title": "Set Course",
    "message": "Setting course…",
    "destinations": []
  }
  ```
- `dispatch_event(action)` — handle `"cancel"` (close), return `False` otherwise.
- `handle_key_esc()` — close if visible.
- `invalidate()` — reset `_last_pushed` so the panel re-emits after a CEF reload.

**Foundation seam:** `destinations` is empty today, so the JS renders the
`message`. Later, populating `destinations` from `_course_menu`'s region tree
turns this into the real picker; `dispatch_event` grows a `select:<region>`
action at that point. No restructuring required.

### 3. CEF assets

- `native/assets/ui-cef/index.html`: add a `<section id="setting-course-panel">`
  using the `cp-modal` / `cp-header` / `cp-body` / `cp-footer` structure (mirror
  the configuration/developer-options sections). Header text "Set Course",
  body holds the message, footer has an OK button wiring
  `onclick="dauntlessEvent('setting-course/cancel')"`. Add
  `<script src="js/setting_course_panel.js"></script>` alongside the other panel
  scripts.
- `native/assets/ui-cef/js/setting_course_panel.js`: `setSettingCoursePanel(state)`
  — hide the section when `!state.visible`; otherwise show it (`display:flex`),
  set the header to `state.title` and body to `state.message`. If
  `state.destinations` is non-empty (future), render destination rows instead of
  the message; for now the empty list path shows the message.
- CSS: reuse `cp-*` from `configuration_panel.css`. No new stylesheet.

### 4. Host-loop wiring — `engine/host_loop.py`

- Construct `setting_course_panel = SettingCoursePanel()`.
- Pass `on_set_course=setting_course_panel.open` into the `CrewMenuPanel(...)`
  constructor (currently `CrewMenuPanel()`). Ordering: construct the
  setting-course panel before the crew menu panel.
- `registry.register(setting_course_panel)`.
- Add `setting_course_panel` to the `_modal_blockers` list so ESC closes it via
  `_dispatch_modal_esc` and it blocks pause-menu input while open.
- **Not** dev-gated — this is a real gameplay menu, registered unconditionally.

## Testing

Unit tests (pytest, headless — no renderer/CEF required):

1. **`_snapshot_node` emits `SortedRegionMenu` as a childless button.** Build a
   menu tree containing a `SortedRegionMenu` with children; assert the snapshot
   node has `type == "button"`, no `children` key, no `expanded` key, and that a
   sibling plain `STMenu` still snapshots as `type:"menu"` with children.
2. **Click branch invokes `on_set_course` and fires no SDK event.** Wire a spy
   callback, dispatch `click:<id>` for the Set Course widget; assert the spy was
   called once with the `SortedRegionMenu` widget, the open menu was closed, and
   no `ET_ST_BUTTON_CLICKED` event was queued. Also assert a `None` callback is a
   silent no-op.
3. **`SettingCoursePanel` lifecycle.** `open()` → `render_payload()` emits a
   `visible:true` payload with the message; a second `render_payload()` with no
   state change returns `None` (snapshot cache); `dispatch_event("cancel")`
   closes and the next payload is `visible:false`; `handle_key_esc()` closes when
   open; `invalidate()` forces re-emit.

C++/CEF render is verified manually in-game (button appears in place of the
Set Course submenu; clicking it shows the modal; OK/ESC closes it).

## Out of scope

- Actual course-setting / warp-destination selection (the `destinations` seam is
  built but not populated).
- Pausing the sim while the modal is open.
- Any change to `sdk/Build/scripts/Bridge/HelmMenuHandlers.py` or other SDK
  source.
