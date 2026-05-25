# Bridge-default view + ESC pause menu

## Goal

Reframe modality so the **bridge** is the player's home view rather than a menu
they opt into. SPACE becomes a pure bridge↔tactical toggle. ESC is removed from
view-mode dispatch and reserved for UI — its first job is bringing up a
placeholder pause menu that fully freezes the game.

## Current behavior

- `_ViewModeController` starts in `EXTERIOR`. SPACE toggles to `BRIDGE`. ESC
  also returns to `EXTERIOR` via `_handle_esc_for_view_mode`
  ([engine/host_loop.py:984-1045](../../../../engine/host_loop.py#L984-L1045),
  call site [host_loop.py:1983-1984](../../../../engine/host_loop.py#L1983-L1984)).
- Bridge side-effects (cursor lock, bridge_pass enable, engine-rumble mute,
  bridge ambient) sync through `_apply_view_mode_side_effects` — edge-triggered
  on mode change, with `_last_synced_is_bridge` as the latch.
- No pause-menu surface exists. CEF Python surface is `cef_initialize`,
  `cef_pump`, `cef_composite`, `cef_shutdown`, `cef_toggle_devtools`,
  `cef_reload` ([native/src/host/host_bindings.cc:876-912](../../../../native/src/host/host_bindings.cc#L876-L912)) —
  no primitive for executing JS in the embedded browser.

## New behavior

1. **Bridge is the default.** A fresh session opens already inside the bridge:
   cursor locked, bridge geometry rendering, bridge ambient hum playing. No new
   "first-tick" code is required — `_apply_view_mode_side_effects` already
   syncs on first call because `_last_synced_is_bridge` starts as `None`.

2. **SPACE is a pure bridge↔tactical toggle.** Unchanged from today's
   `_ViewModeController.apply` once the default flips.

3. **ESC is removed from view-mode dispatch.** SPACE is the only key that
   changes view mode.

4. **ESC opens / closes a placeholder pause menu.** While the menu is open, the
   game is fully paused: AI, physics, weapons, combat, ship/camera input, and
   audio tick all skip. The world keeps rendering (frozen) and CEF keeps
   pumping so the menu paints. ESC again closes the menu and resumes ticking.

## Architecture

### `_PauseMenuController` (new, in `engine/host_loop.py`)

Mirrors `_ViewModeController`'s shape so future readers can pattern-match.

```python
class _PauseMenuController:
    def __init__(self):
        self._open = False

    @property
    def is_open(self) -> bool: return self._open

    def toggle(self) -> None:
        self._open = not self._open

    def apply(self, h) -> None:
        """Edge-triggered on KEY_ESCAPE."""
        if h.key_pressed(h.keys.KEY_ESCAPE):
            self.toggle()
```

`apply` runs every tick (regardless of pause state) so ESC always works.

### Pause menu side-effects sync

```python
def _apply_pause_menu_side_effects(pause: "_PauseMenuController", h) -> None:
    target = pause.is_open
    last = getattr(pause, "_last_synced_is_open", None)
    if last == target:
        return
    h.cef_execute_javascript(
        "document.getElementById('pause-menu').style.display = "
        + ("'flex';" if target else "'none';")
    )
    pause._last_synced_is_open = target
```

Same idempotent latch pattern as `_apply_view_mode_side_effects`. `flex` (not
`block`) because the placeholder CSS uses flexbox centering.

### Tick gating

The pause check sits at the top of the loop body, after view-mode +
pause-controller `apply()` and their side-effect syncs:

```
loop body:
  view_mode.apply(_h)              # SPACE toggle (gated below if paused)
  pause.apply(_h)                  # ESC toggle — always live
  _apply_pause_menu_side_effects(pause, _h)

  if pause.is_open:
      # Render the frozen world + CEF overlay, then continue.
      _render_frozen_frame(...)    # camera/lighting from last tick, r.frame()
      continue

  _apply_view_mode_side_effects(view_mode, _h)
  ... rest of tick ...
```

**SPACE while paused must not change mode.** `view_mode.apply` is called
before the pause check so the modality is technically toggled, but
`_apply_view_mode_side_effects` runs *after* the pause-gate, meaning the
side-effects don't fire until the player unpauses. That's confusing
state-vs-render skew. Cleaner: guard `view_mode.apply` itself.

Final layout:

```
pause.apply(_h)
_apply_pause_menu_side_effects(pause, _h)

if not pause.is_open:
    view_mode.apply(_h)
    _apply_view_mode_side_effects(view_mode, _h)

if pause.is_open:
    _render_frozen_frame(...)
    continue

... rest of tick ...
```

### Frozen-frame render path

Goal: while paused, the world stays painted (last camera, last instance
transforms, last lighting) and the CEF overlay composites over it. The
existing tick body already does all of that *after* the pause-able systems
have advanced. The simplest implementation is to gate the *systems* but keep
the *render* section running.

Concretely, when `pause.is_open`:

- **Skip:** `loop.tick()`, `_apply_alert_keys`, `_apply_input`,
  `_poll_mouse_buttons`, `_advance_weapons`, `_advance_combat`, the per-tick
  transform sync over `session.ship_instances` / `planet_instances`,
  `tick_audio`, `_update_ui_for_tick`.
- **Keep:** camera reads (`_compute_camera`), `r.set_camera`,
  `r.set_lighting`, `r.set_bridge_lighting`, `r.set_backdrops`, `r.set_suns`,
  `r.set_lens_flares`, `r.frame()`. These all read state without advancing
  it, so calling them repeatedly produces the same frozen view.

Implementation choice: wrap the pause-able block in `if not pause.is_open:`
rather than splitting the loop into two functions. The blocks are
sequential and well-marked; splitting them into helpers would scatter the
read order without adding clarity.

`cef_pump` already runs as part of `r.frame()` (see [native/src/host/host_bindings.cc:268](../../../../native/src/host/host_bindings.cc#L268)
and surrounding) so no extra wiring is needed for the overlay to update while
paused.

### CEF JS-eval primitive

Add to [native/src/host/host_bindings.cc](../../../../native/src/host/host_bindings.cc):

```cpp
m.def("cef_execute_javascript",
      [](const std::string& script) {
          dauntless::ui_cef::execute_javascript(script);
      },
      "Execute JavaScript in the main frame of the CEF overlay.");
```

And the no-CEF stub branch:

```cpp
m.def("cef_execute_javascript", [](const std::string&) {});
```

The implementation lives in `native/src/ui_cef/cef_lifecycle.{h,cc}` (the same
module that owns the browser handle today):

```cpp
void execute_javascript(const std::string& script) {
    auto browser = current_browser();   // existing accessor used by reload
    if (!browser) return;
    auto frame = browser->GetMainFrame();
    if (!frame) return;
    frame->ExecuteJavaScript(script, frame->GetURL(), 0);
}
```

(If `current_browser()` doesn't exist by that name today, follow whatever
accessor `cef_reload` uses — they need the same handle.)

### HTML / CSS

Extend [native/assets/ui-cef/hello.html](../../../../native/assets/ui-cef/hello.html):

```html
<body>
    <div class="hello">Hello world</div>
    <div id="pause-menu">placeholder - pause menu</div>
</body>
```

Extend [native/assets/ui-cef/css/hello.css](../../../../native/assets/ui-cef/css/hello.css)
with a centered-overlay rule:

```css
#pause-menu {
    display: none;                    /* toggled to 'flex' by Python */
    position: fixed;
    inset: 0;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 32px;
    background: rgba(0, 0, 0, 0.5);   /* dim the world behind */
    z-index: 100;
}
```

## Code changes (concrete sites)

| Change | Location |
|---|---|
| Default mode → BRIDGE | `_ViewModeController.__init__` ([engine/host_loop.py:998-999](../../../../engine/host_loop.py#L998-L999)) |
| Delete `_handle_esc_for_view_mode` | [engine/host_loop.py:1040-1045](../../../../engine/host_loop.py#L1040-L1045) |
| Delete ESC view-mode call site | [engine/host_loop.py:1983-1984](../../../../engine/host_loop.py#L1983-L1984) |
| Add `_PauseMenuController` + sync helper | new, alongside view-mode controller |
| Instantiate `pause = _PauseMenuController()` | near `view_mode = _ViewModeController()` ([host_loop.py:1910](../../../../engine/host_loop.py#L1910)) |
| Tick-body gating | around the SPACE-poll block ([host_loop.py:1938-2065](../../../../engine/host_loop.py#L1938-L2065)) |
| Add `cef_execute_javascript` binding + stub | [native/src/host/host_bindings.cc:876-912](../../../../native/src/host/host_bindings.cc#L876-L912) |
| Add `execute_javascript` impl | `native/src/ui_cef/cef_lifecycle.{h,cc}` |
| Pause-menu HTML element | [native/assets/ui-cef/hello.html](../../../../native/assets/ui-cef/hello.html) |
| Pause-menu CSS | [native/assets/ui-cef/css/hello.css](../../../../native/assets/ui-cef/css/hello.css) |

## Tests

### Updates to existing [tests/host/test_view_mode.py](../../../../tests/host/test_view_mode.py)

- `test_view_mode_starts_exterior` → rename to `test_view_mode_starts_in_bridge`,
  flip assertions.
- `test_esc_in_bridge_mode_returns_to_exterior` → **delete** (ESC no longer
  toggles view mode).
- `test_esc_in_exterior_mode_is_a_noop` → **delete** (same reason).
- `test_view_mode_toggle_on_space_pressed` — update initial-state assertions
  (starts in bridge, first SPACE goes exterior, second goes bridge).
- `test_apply_input_*` — adjust the `_ViewModeController()` construction in
  fixtures that need exterior mode to call `vm.toggle()` once after
  construction (the controller now starts in bridge).

### New tests for `_PauseMenuController`

In a new file `tests/host/test_pause_menu.py`:

- `test_pause_menu_starts_closed` — `_PauseMenuController().is_open is False`.
- `test_pause_menu_toggle_on_escape_pressed` — fake reader, ESC pressed once
  flips to open, ESC pressed again flips closed (edge-triggered, not held).
- `test_pause_menu_side_effects_show_uses_flex` — recording fake exposing
  `cef_execute_javascript`; opening fires a single call whose script contains
  `"'flex'"` and references `pause-menu` by id.
- `test_pause_menu_side_effects_hide_uses_none` — closing fires a single call
  with `"'none'"`.
- `test_pause_menu_side_effects_idempotent_within_a_state` — two calls in a
  row without toggling produce at most one script execution.

### Integration: tick-body gating

Pure tick-body gating (the `if not pause.is_open:` blocks) is verified by
inspection — adding a unit test that drives the full host loop is out of scope
for this spec. The unit tests above lock down the controller and the
sync helper; the gating is a small, reviewable diff over the existing tick
body.

## Out of scope

- Real pause-menu UI (buttons, resume / options / quit). The placeholder text
  is intentional; the menu logic comes later.
- Anti-cheat / save-game interactions with pause state.
- Hooking ESC inside the CEF overlay itself for nested menus. Today the menu
  is text only.
- A general "game paused" event other systems might want to observe. The
  current pause is purely a host-loop tick gate; nothing else needs to know.

## Decisions deferred

- **Where the `cef_execute_javascript` binding ultimately lives** (a thin
  `ui_cef::execute_javascript` free function vs. a method on whatever class
  owns the browser handle). Choose whichever pattern matches `cef_reload`'s
  existing structure — they need the same browser pointer.
