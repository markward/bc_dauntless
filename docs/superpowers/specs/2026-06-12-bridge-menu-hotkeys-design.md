# Bridge menu hotkeys (F1–F5) — design

**Date:** 2026-06-12
**Status:** Spec draft, awaiting user review.
**Motivation:** Stock BC opens the bridge crew menus with F1–F5; in dauntless the
keys do nothing. The SDK side of the chain already runs at host startup
(`KeyConfig.MapScancodes()` registers the keys, `DefaultKeyboardBinding.Initialize()`
binds `WC_F1..F5 → ET_INPUT_TALK_TO_{HELM,TACTICAL,XO,SCIENCE,ENGINEERING}` with
the TacticalControlWindow as destination — sdk/Build/scripts/DefaultKeyboardBinding.py:121-125)
but three gaps break it: GLFW F1–F5 are not exposed by `host_bindings.cc`, no code
forwards host keyboard edges into `g_kInputManager` (only mouse buttons are
forwarded), and `WC_F1..`/`KY_F1..` are `_NamedStub`s (so the SDK bound key code 0).
Additionally, the stock effect (`BridgeHandlers.TalkTo*` opens a bridge *character*
menu) dead-ends headless: the bridge set has no characters, so
`CharacterClass_GetObject(pBridge, "Helm")` is None and the handler no-ops.

---

## Goals

1. **F1–F5 toggle the five bridge menus** in the CEF crew-menu bar with stock
   mapping: F1 Helm, F2 Tactical, F3 XO, F4 Science, F5 Engineering. Same key
   again closes; opening one closes the others; ESC closes any open menu
   (consuming the press so the pause menu does not also open).
2. **The SDK binding table stays authoritative.** Key→event routing flows
   through `g_kInputManager` → `g_kKeyboardBinding` → `ET_INPUT_TALK_TO_*`, so a
   future Options screen rebinding keys via the SDK table works untouched.
3. **One source of truth for dropdown open-state**, owned by `CrewMenuPanel`
   (Python), shared by hotkeys and mouse clicks, headless-testable.

## Non-goals

- **No bridge characters / character menus.** The stock `BridgeHandlers.TalkTo*`
  effect (crew speech, character menu interaction) needs the character system;
  our handler opens the corresponding CEF menu instead — a documented deviation
  in the same spirit as the CEF re-style.
- **No F6 (guest) / Shift-modified bindings.** Stock binds more keys; only
  F1–F5 are in scope.
- **No general keyboard forwarding.** Only the five function keys are polled;
  a full host→SDK keyboard bridge is its own future spec.
- **No rebinding UI.**

---

## Design

### Input chain (host → SDK pipeline)

- `native/src/host/host_bindings.cc`: expose `KEY_F1..KEY_F5` GLFW constants
  next to the existing `KEY_F7..KEY_F12`.
- `engine/appc/input.py`: real int constants `WC_F1..WC_F5` and `KY_F1..KY_F5`
  in the existing WC_/KY_ constant ranges (values stable, no collisions with
  the mouse-button codes already defined there); exported through `App.py`.
- `engine/host_loop.py`: `_poll_function_keys(host)` beside
  `_poll_mouse_buttons`, called from the same per-frame site. For each
  `(host.keys.KEY_Fn, App.WC_Fn)` pair: `key_pressed` →
  `App.g_kInputManager.OnKeyDown(wc)`; `key_released` → `OnKeyUp(wc)`. No-op
  when the host lacks the poll methods (headless tests), matching
  `_poll_mouse_buttons`.

From `OnKeyDown` onward the existing SDK pipeline produces
`ET_INPUT_TALK_TO_*` events with the TCW destination — our code adds no
key→event mapping of its own.

### Menu-open effect (`engine/ui/crew_menu_hotkeys.py`)

`wire(tcw, panel)` registers instance handlers on the TacticalControlWindow
for the five `ET_INPUT_TALK_TO_*` event types. Each handler resolves its menu
with the same TGL lookup the LoadBridge epilogue uses
(`g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")` →
`GetString("Helm")` → `tcw.FindMenu(label)`; database loaded once per wire,
labels cached) and calls `panel.toggle_menu(menu)`. Missing menu (handler
failed to build, or pre-activation) → drop with one log line.

Lifecycle: the handlers are *instance* handlers on the TCW object, so they die
when `reset_sdk_globals` nulls the singleton. The module keeps the wired panel
in a module-level `_wired_panel`; `wire(tcw, panel)` stores it (called from
host_loop where the panel is constructed), and `rewire()` re-registers on the
current `TacticalControlWindow.GetInstance()` using the stored panel.
`reset_sdk_globals` calls `crew_menu_hotkeys.rewire()` right after the
keyboard-destination re-point, in the same best-effort try-block (no-op when
nothing was ever wired, e.g. headless tests).

### Open-state ownership (`engine/ui/crew_menu_panel.py`)

- `_open_menu_id: int | None` — at most one open menu (matches the JS
  single-open invariant).
- `toggle_menu(menu)` — same menu → close; different/None-open → open it
  (closing any other).
- `close_open_menu() -> bool` — True if something was open and is now closed.
- Snapshot top-level nodes gain `"open": <bool>` (children unchanged).
- `dispatch_event` handles `"toggle:<id>"` — resolve via `_widgets_by_id`,
  call `toggle_menu`; stale/malformed ids drop with a log, return True.
- Open-state changes alter the payload, so the existing diff re-emits on the
  next tick — no extra push mechanism.

### CEF side (`native/assets/ui-cef/js/crew_menus.js`)

Remove `crewMenuOpenId` and local class toggling. Top-level `.crew-menu` gets
the `open` class from the payload's `"open"` flag. The title click handler
becomes `dauntlessEvent("crew-menu/toggle:" + menu.id)`.

### ESC ordering (`engine/host_loop.py`)

At the existing ESC-handling site, before the pause-menu toggle:
`if crew_menu_panel.close_open_menu(): <consume the press>` — the menu closes
and the pause menu does not open on that press. Pause-menu ESC behaviour is
otherwise unchanged.

## Error handling

- Stale/malformed `toggle:` ids and missing menus: logged, dropped, never
  raised into the tick (same rules as click dispatch).
- `_poll_function_keys` is best-effort and absent-host-safe.
- `crew_menu_hotkeys.wire` failures must not block host startup (wrap the
  call site like the other SDK init steps).

## Testing

Focused subsets only; `.venv/bin/python -m pytest` if the uv lock is contended.

- **Unit (panel):** toggle semantics (open / switch / close / single-open),
  payload `"open"` flags, `close_open_menu` return values, stale `toggle:` id.
- **Unit (hotkeys):** `wire` + synthetic `ET_INPUT_TALK_TO_*` event through
  `g_kEventManager` toggles the right menu; missing-menu drop.
- **Unit (poll):** fake host object with scripted pressed/released edges →
  `OnKeyDown`/`OnKeyUp` calls with the right WC codes; absent-host no-op.
- **Integration:** real five menus built (existing activation path), then
  `App.g_kInputManager.OnKeyDown(App.WC_F1)` end-to-end → next payload marks
  Helm `"open": true`; F1 again → closed; F1 then F2 → Tactical open, Helm
  closed. ESC path: `close_open_menu()` True-then-False.
- **Regression:** crew-menu panel suite, activation suite, host-loop suite.

## Follow-ups unlocked

General host→SDK keyboard bridge (all bound keys, not just F1–F5); F6/guest
and Shift-modified bindings; Options-screen rebinding UI.
