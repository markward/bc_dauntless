# Configuration panel — design

## Purpose

Add a **Configuration** entry to the pause menu that opens a modal with a
left-side vertical tab strip. First iteration ships a single **Graphics**
tab exposing three runtime knobs that take effect immediately:

| Setting              | Type           | Range / values    | Default                |
|---|---|---|---|
| Space Dust           | toggle         | On / Off          | On                     |
| Specular Highlights  | toggle         | On / Off          | On                     |
| Exterior Camera FOV  | integer slider | 55–75° (step 1°)  | Live engine value (70°)|

Saving / persistence is **out of scope for this pass.** Changes apply
immediately to the running engine and are forgotten on shutdown.

## Non-goals

- No on-disk persistence. No config file, no INI write, no
  ConfigMapping plumbing.
- No additional tabs (Audio, Controls, Gameplay) — the tab strip is
  designed to accept them later but only Graphics ships now.
- No "Apply / Cancel" semantics. Edits are live; the **Done** button is
  a closer, not a saver. Closing without committing is not a concept.
- No mouse-drag-to-scrub on the slider visual beyond what a stock
  `<input type=range>` provides.

## Architecture

### Component map

```
PauseMenuModel  ──"Configuration" row──►  on_configuration handler
                                                │
                                                ▼
                                         host_loop:
                                          - panel.open()
                                          - hide pause-menu (existing
                                            mission-picker arbitration)
                                                │
                                                ▼
                            ┌──────────────────────────────────┐
                            │   ConfigurationPanel (Panel)     │
                            │  ─ tabs / focus / settings model │
                            │  ─ render_payload() ─► CEF       │
                            │  ─ dispatch_event()  ◄─ CEF      │
                            └──────────┬────────────┬──────────┘
                                       │            │
                            applier: set_dust   applier: set_specular
                            (renderer)          (renderer, new)
                                       │
                            applier: set_fov_rad (camera director)
```

### New files

- `engine/ui/configuration_panel.py`
- `tests/unit/test_configuration_panel.py`
- `native/assets/ui-cef/js/configuration_panel.js`
- `native/assets/ui-cef/css/configuration_panel.css`

### Modified files

- `engine/ui/pause_menu.py` — `default_pause_menu` gains
  `on_configuration` and inserts a third row.
- `engine/host_loop.py` — construct `ConfigurationPanel`, register on
  `PanelRegistry`, wire pause-menu arbitration, route ESC.
- `engine/renderer.py` — add `set_specular_enabled(bool)` wrapper.
- `native/src/host/host_bindings.cc` — add `specular_set_enabled`
  binding and `g_specular_enabled` flag.
- `native/src/renderer/frame.cc` — read `g_specular_enabled` and set
  new shader uniform on opaque-pass shader bind.
- `native/src/renderer/shaders/opaque.frag` — new
  `uniform int u_specular_enabled;` (defaults treated as enabled);
  spec accumulator short-circuited when 0.
- `native/assets/ui-cef/ship_status.html` — new `<section
  id="configuration-panel">` with tab strip + body + footer, plus
  `<script src="js/configuration_panel.js">` and corresponding
  stylesheet link.
- Tests: extend `tests/unit/test_pause_menu_model.py` and
  `tests/host/test_pause_menu.py`.

## Component design

### `ConfigurationPanel` (Python model + view)

Subclasses `engine.ui.panel.Panel`. Pumped by `PanelRegistry` exactly
like `MissionPicker`.

**Construction:**

```python
ConfigurationPanel(
    tabs=[("graphics", "Graphics")],
    initial_settings=SettingsSnapshot(
        dust_on=True,
        specular_on=True,
        fov_deg=int(round(math.degrees(EXTERIOR_FOV_Y_RAD))),
    ),
    set_dust=renderer.set_dust_enabled,
    set_specular=renderer.set_specular_enabled,
    set_fov_rad=camera_director.set_fov,
)
```

All three appliers are injected — no compile-time import of `renderer`
or `cameras` inside the panel module, mirroring the existing pattern in
`PauseMenuModel`.

**State:**

- `_visible: bool`
- `_selected_tab: str` (default `"graphics"`)
- `_settings: SettingsSnapshot` (dust_on, specular_on, fov_deg)
- `_focused: int` — index into the **focusable list**, which is the
  ordered concatenation of (tab strip rows, then controls in the
  currently selected tab).
  - For Graphics: `[tab:graphics, ctrl:dust, ctrl:specular, ctrl:fov]`
  - `-1` means "no row focused" — first ↑/↓ press lands on index 0 /
    last, matching `PauseMenuModel`.
- `_last_pushed` snapshot tuple for dedup.

**Public surface:**

- `name → "configuration"`
- `is_open() → bool`
- `open()`, `close()`
- `render_payload() → Optional[str]`
- `dispatch_event(action) → bool`
- `handle_key_esc()` — close when visible
- `handle_input(h)` — when visible, process ↑/↓/Space/←/→/Enter via
  the bindings module shape `PauseMenuModel.handle_input` already uses
- `invalidate()` — drop snapshot, called on CEF reload

**Behaviour:**

- Opening seeds nothing extra (settings already current). Initial
  `_focused` is `-1`.
- Each setting mutation calls its applier first, then writes the new
  value into `_settings`. If the applier raises the local state stays
  on the previous value and the exception propagates; for the
  no-persistence first pass this leaves the panel consistent with the
  renderer (the engine state was never flipped) without needing an
  explicit try/except wrapper.
- `dispatch_event` accepts:
  - `"cancel"` → close
  - `"tab:<id>"` → select tab (also rebuilds the focusable list)
  - `"toggle:dust"` → flip + apply
  - `"toggle:specular"` → flip + apply
  - `"fov:<int>"` → clamp 55–75 + apply (`math.radians(deg)`)
- Keyboard input map (active only when visible):
  - `KEY_UP` / `KEY_DOWN` → move focus, wraps; first press from
    unfocused state lands on last / first
  - `KEY_SPACE` (or `KEY_ENTER`) on a toggle row → flip + apply
  - `KEY_SPACE` / `KEY_ENTER` on a tab row → select that tab
  - `KEY_LEFT` / `KEY_RIGHT` on FOV slider → ±1°, clamped, apply
  - `KEY_ESC` → close (also handled via `handle_key_esc`)
- `render_payload` emits:
  ```js
  setConfigurationPanel({
    visible: true,
    tabs: [{id: "graphics", label: "Graphics"}],
    selected_tab: "graphics",
    focused: 2,
    settings: {dust_on: true, specular_on: true, fov_deg: 70}
  });
  ```
  or `{visible: false}` when closing. Dedup against `_last_pushed`.

### Pause-menu integration

`default_pause_menu(*, on_exit, on_configuration, on_cancel)` — gains
the new keyword-only argument and inserts:

```
m.add_item("Exit Program",  "exit",          on_exit)
m.add_item("Configuration", "configuration", on_configuration)
m.add_item("Cancel",        "cancel",        on_cancel)
```

Dev rows continue to append after Cancel.

**Slug collision note:** `_slugify_action_id` already deduplicates
against `used = {"exit", "cancel"}`. Update the seed to
`{"exit", "configuration", "cancel"}` so a dev entry labelled
"Configuration" can't shadow the production row.

### Host-loop wiring

In `engine/host_loop.py` (alongside `MissionPicker` construction):

1. Build `ConfigurationPanel` with appliers wired to
   `renderer.set_dust_enabled`, `renderer.set_specular_enabled`,
   `camera_director.set_fov`.
2. Register on `PanelRegistry`.
3. `on_configuration` handler: `panel.open()` + same pause-menu-hide
   side effect that `_apply_pause_menu_side_effects` performs for the
   mission picker.
4. ESC routing: when the configuration panel is open, ESC closes it
   and shows the pause menu — identical to the mission-picker branch
   already in `handle_key_esc` routing.
5. While the panel is visible, the pause menu's `handle_input` is
   skipped; `ConfigurationPanel.handle_input` runs instead.

### Renderer plumbing — specular toggle

**Python wrapper** (`engine/renderer.py`):
```python
def set_specular_enabled(enabled: bool) -> None:
    """Toggle specular highlights in the opaque pass. Default: on."""
    _h.specular_set_enabled(bool(enabled))
```

**C++ binding** (`native/src/host/host_bindings.cc`):
```cpp
m.def("specular_set_enabled",
      [](bool enabled){ renderer::set_specular_enabled(enabled); },
      py::arg("enabled"),
      "Toggle specular contribution in the opaque pass. Default: on.");
```

**Renderer state:** a `std::atomic<bool> g_specular_enabled{true}` in
the renderer module, with `renderer::set_specular_enabled` /
`renderer::specular_enabled()` accessors. `frame.cc`'s opaque-pass
shader-bind block reads the flag and emits:

```cpp
shader.set_int("u_specular_enabled", renderer::specular_enabled() ? 1 : 0);
```

**Shader** (`native/src/renderer/shaders/opaque.frag`): add
`uniform int u_specular_enabled;`. Wrap the existing per-light
`s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);` and
the final `spec = spec_acc * u_specular_color * ...` so the
contribution is zero when the uniform is 0. Reminder: per project
memory, shader edits require a `cmake -B build -S .` reconfigure
before the next build picks them up.

### CEF view

**HTML** (`native/assets/ui-cef/ship_status.html`) — new section,
matching the mission-picker pattern but production-visible:

```html
<!-- Configuration overlay (production).
     setConfigurationPanel({...}) drives state; clicks fire
     dauntlessEvent('configuration/<verb>:<arg>'). ESC and the Done
     button both fire 'configuration/cancel'.
     Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md -->
<section id="configuration-panel">
  <div class="cp-modal">
    <div class="cp-header">Configuration</div>
    <div class="cp-content">
      <nav class="cp-tabstrip" id="cp-tabstrip"></nav>
      <div class="cp-body" id="cp-body"></div>
    </div>
    <div class="cp-footer">
      <button class="cp-done-button"
              onclick="dauntlessEvent('configuration/cancel')">
        Done
      </button>
    </div>
  </div>
</section>
```

**CSS** (`native/assets/ui-cef/css/configuration_panel.css`):

- `#configuration-panel`: full-screen flex centred overlay,
  `display:none` by default (JS toggles to `flex`).
- `.cp-modal`: ~600×400 px, flex column.
- `.cp-content`: flex row, tab strip (`flex: 0 0 140px`) + body
  (`flex: 1`).
- `.cp-tabstrip` rows: vertical list, hover highlight, `.cp-tab--active`
  for selected, `.cp-focused` for keyboard focus.
- `.cp-row`: one settings row, flex row with label + control,
  `.cp-focused` outline when keyboard-focused.
- `.cp-slider`: native `<input type=range>` + degree readout span.
- Visual palette consistent with the existing pause-menu / mission-picker
  CSS conventions.

**JS** (`native/assets/ui-cef/js/configuration_panel.js`):

- `setConfigurationPanel(state)` — root-level entry. Hides/shows the
  section; rebuilds tab strip and body each call (small DOM, no
  diffing).
- Tab rows: `dauntlessEvent('configuration/tab:' + id)`.
- Toggle rows: clicking the row or its checkbox fires
  `dauntlessEvent('configuration/toggle:dust')` /
  `'configuration/toggle:specular'`.
- Slider: on `change` (not `input`, to avoid event spam mid-drag) fires
  `dauntlessEvent('configuration/fov:' + value)`.
- Focus class applied based on `state.focused` index into the same
  ordered focusable list the Python side builds.

## Data flow per interaction

**Toggle Space Dust off (mouse):**

1. Click on dust row → `dauntlessEvent('configuration/toggle:dust')`.
2. C++ `OnBeforeBrowse` routes `configuration/toggle:dust` to
   `PanelRegistry.dispatch("configuration", "toggle:dust")`.
3. Panel flips `_settings.dust_on` and calls `set_dust(False)` →
   `renderer.set_dust_enabled(False)` → `_h.dust_set_enabled(False)`.
4. Next tick, `render_payload` emits the new state; JS re-paints with
   the dust row's checkbox unchecked.

**Adjust FOV via slider (mouse):**

1. User drags slider, releases at 62 → `change` fires
   `'configuration/fov:62'`.
2. Panel clamps 62 to [55,75] (no-op), stores `_settings.fov_deg = 62`,
   calls `set_fov_rad(math.radians(62))` →
   `_camera_director.set_fov(...)` updates director + tracking FOV.
3. Next frame `r.set_camera` uses the new value.

**FOV adjust via keyboard (focused on slider):**

1. `KEY_RIGHT` → `_settings.fov_deg = min(75, fov_deg + 1)`; applier
   fires; render payload emits.

**ESC while panel is open:**

1. ESC handler in host loop sees `panel.is_open()`; calls
   `panel.close()` and re-shows the pause menu (existing arbitration).
2. Next tick, `render_payload` emits `{visible: false}`; JS hides the
   overlay. Pause menu reappears via its own dirty re-render.

## Error / edge cases

- **Applier raises:** the mutation never lands (applier is invoked
  before the local state write); the exception propagates so a
  misconfigured wiring is visible at test time.
- **Unknown event name:** `dispatch_event` returns `False`; the
  `PanelRegistry` logs and ignores (existing pattern).
- **Pause menu opened while panel is open** (paranoia — host loop
  should prevent this): pause-menu input is skipped while
  `panel.is_open()`. The host loop already does this for mission
  picker.
- **CEF reload (Cmd+R) while panel is visible:** `invalidate()` drops
  the snapshot so the next tick re-emits the visible payload, mirroring
  `MissionPicker.invalidate`.
- **`fov_deg` clamping:** values outside [55,75] from any source (event
  string, keyboard repeat overshoot) are clamped silently.

## Testing strategy

**Unit — `tests/unit/test_configuration_panel.py`:**

- Construction seeds `fov_deg` from the injected initial snapshot.
- `dispatch_event("toggle:dust")` flips state and calls the dust
  applier with `False`.
- `dispatch_event("toggle:specular")` flips state and calls the
  specular applier.
- `dispatch_event("fov:62")` updates state and calls `set_fov_rad`
  with `radians(62)`.
- `dispatch_event("fov:42")` clamps to 55 and applies `radians(55)`.
- `dispatch_event("fov:100")` clamps to 75 and applies `radians(75)`.
- `dispatch_event("tab:graphics")` is a no-op for state but allowed;
  unknown `"tab:audio"` returns `False`.
- `dispatch_event("cancel")` closes.
- Focus navigation: ↑ from `-1` lands on the last focusable; ↓ from
  `-1` lands on the first; wraps both directions.
- Space on toggle row triggers applier; ←/→ on FOV row adjusts and
  clamps; Space on tab row selects.
- `render_payload` returns a script on first emit; returns `None` when
  state hasn't changed; re-emits after `invalidate()`.

**Unit — extend `tests/unit/test_pause_menu_model.py`:**

- `default_pause_menu` produces rows in order
  `[exit, configuration, cancel]` plus dev rows after.
- Activating the Configuration row calls `on_configuration`.
- Dev entry labelled "Configuration" gets a disambiguated action id
  (e.g. `"configuration-2"`), not `"configuration"`.

**Host — extend `tests/host/test_pause_menu.py`:**

- Selecting Configuration via Enter opens the panel and hides the
  pause menu.
- ESC while panel is open closes the panel and re-shows the pause
  menu.
- A renderer fake records calls; toggling dust and specular through
  the panel records the expected applier calls.

## Risks and considerations

- **Shader rebuild:** `opaque.frag` edits require a cmake reconfigure
  per project memory. Build instructions in the plan must call this
  out so the first build after the shader edit isn't silently stale.
- **No persistence today.** Re-opening the panel after a launch shows
  defaults again. Acceptable per the brief; flagged here so it's
  obvious when adding persistence later that the panel's
  `initial_settings` is the integration point.
- **Tab-strip-with-one-tab visual.** The strip is shown even for a
  single tab to lock in the layout future tabs will use. If this looks
  awkward in practice, the CSS hook `cp-tabstrip--single` can hide it
  without touching Python.
- **`<input type=range>` event spam.** We listen on `change` (released)
  not `input` (every pixel) so dragging the slider doesn't flood the
  CEF event channel.
- **Default FOV mismatch.** The brief specified 65° default; the
  codebase currently uses 70°. Decision recorded: keep 70°, slider
  seed reads the live engine value. If the global default later
  changes, the panel follows automatically.
