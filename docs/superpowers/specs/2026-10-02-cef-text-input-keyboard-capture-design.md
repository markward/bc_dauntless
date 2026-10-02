# In-game keyboard capture for CEF text inputs — Design

**Status:** implemented on feat/cef-text-capture, awaiting live check (§8)
**Date:** 2026-10-02
**Builds on:** `2026-10-01-mod-ships-screen-design.md` §6, which added native
key capture (the `renderer::Window` char/key callbacks, the bounded text-event
queue, `drain_text_events()`, `cef_send_key_event`, `glfw_key_to_windows_vk`).
That work forwards keys only in the pre-boot loop and leaves in-game
forwarding open. This spec closes it.
**Depended on by:** Quick Battle sub-project 2 (the setup screen: renaming
groups, naming presets). That spec relies on the panel contract in §4.4.

## Intent

When an editable element in the in-game CEF page has focus, it owns the
keyboard. Nothing reaches the game as a command key until it lets go: no polled
read, no `ET_KEYBOARD` event, no dev binding. Typed text and editing keys go to
CEF instead. The game can never be left deaf: every way a field can disappear
releases the capture.

This is general infrastructure rather than something owned by Quick Battle.
The first consumer is the Ship Property Viewer: its Move, Rotate and Scale
value rows become typeable (§5). Quick Battle sub-project 2 is the second.

**Success:**

- In the SPV, a value can be typed into a Move, Rotate or Scale row. Typing
  `-` or `=` does not zoom, and Esc reverts the field instead of closing
  anything.
- A headless test shows that, while capture is on, holding W, Space, a fire
  key, `1`, Esc and a dev key changes nothing in the game.
- A structural test fails if any C++ reads key state outside the gate.

## Decisions taken in the brainstorm (2026-10-02)

| # | Question | Decision |
|---|---|---|
| D1 | Who knows focus | **The page reports it, native owns the flag.** A shared `text_capture.js` sends focus and blur events. Python sets a native gate. Native clears the gate itself on page load start and on renderer crash, so it cannot go stale. Rejected: CEF's `OnVirtualKeyboardRequested`, whose macOS OSR behaviour is unverified; per-frame polling of the page, which is laggy and noisy. |
| D2 | Where the gate lives | **Native, at the single key-read function.** All 47 direct `h.key_*` calls and every `host_io` read end at `Window::key_state`, so the gate there cannot be bypassed. Rejected: a Python proxy around `h` plus a gate in `host_io`, which would be two choke points and leaky for future call sites. **Nothing passes through** while captured, F12 and Cmd+R included. Mouse buttons and scroll are untouched. |
| D3 | Held keys | While captured, every key reads up. On release, keys still physically down stay **masked until released**, so the key that ended the edit (Enter, Esc) never becomes a game press on the next frame. |
| D4 | Special keys in a field | **Esc** reverts to the value at focus, then blurs. **Enter** blurs a single-line field, and the DOM `change` event commits. **Tab** stays in the page; moving between fields keeps capture. **Cmd (macOS) / Ctrl + A/C/V/X/Z, and Shift+Z or Y** run native `CefFrame` edit commands, using the system clipboard. |
| D5 | Release guarantees | Five triggers, with no heartbeat: page blur; native reset on load start or renderer crash; owning panel no longer open; mission swap; a left click not routed to CEF. A forced release **abandons** the edit (reverts) rather than committing it. |
| D6 | Testing | A gtest for the pure gate and the edit-command map; a structural guard on raw key reads; Python unit tests for the controller; a host-loop wiring test with a gate-honouring fake host; source-shape tests for the JS. **No JS runtime harness**: a JS bug cannot leak keys past the native gate, and node would be new gate infrastructure for about 40 lines. |
| D7 | Proof case / first consumer | **The SPV's Move, Rotate and Scale rows.** At rest they render exactly as today. Clicking the value swaps the row for an input with ✕ and ✓ buttons (§5). |

## 1. Background: how the game reads keys today

- **Polling dominates.** `key_state(k)` is a level read. `key_pressed(k)` is
  `now && !prev`, where `prev` is a snapshot taken in `frame()` before
  `poll_events()` (`native/src/host/host_bindings.cc:1850-1852`). Reading a
  key does not consume it.
- **Two raw reads in all of `native/src`:**
  - `Window::key_state` (`native/src/renderer/window.cc:195-198`), which every
    `key_state` / `key_pressed` binding call goes through;
  - the snapshot loop at `host_bindings.cc:1851`.
- **Python call sites:** 16 go through `host_io` and 47 go to the raw module
  directly. The direct ones are in `engine/host_loop.py` (`_PlayerControl`,
  alert keys, view mode, pause, modal Esc, Controls capture),
  `engine/cameras/chase.py`, `engine/ui/pause_menu.py`,
  `configuration_panel.py`, `developer_options_panel.py` and
  `ship_property_viewer_panel.py`.
- **Evented input is built from polling.** The F-key, fire-key, chord and raw
  pollers (`host_loop.py` around 347-700) derive press and release from
  `host_io.key_state`, then call `TGInputManager.OnKeyDown`/`OnRawKeyDown`/…,
  which produce `ET_KEYBOARD` and `ET_KEYBOARD_EVENT`.
- **What modals block today.** Only `pause.is_open` and `sim_frozen` gate
  keys. Unpaused modals (star map, Quick Battle setup, info box) reroute Esc
  and nothing else.
- **The text queue** (`text_input.{h,cc}`) holds characters and the editing
  keys only, capped at 256 with oldest dropped. Nothing in-game drains it.

Gating at the native read therefore silences every path above at once, with
no Python call site changed.

## 2. Native

### 2.1 `KeyGate`

`native/src/renderer/include/renderer/key_gate.h` and
`native/src/renderer/key_gate.cc` (new). A pure class with no GLFW:

```cpp
namespace renderer {
class KeyGate {
public:
    void capture() noexcept;                         // gate on; clears the mask
    void release(const std::vector<int>& raw_down);  // gate off; mask raw_down
    bool captured() const noexcept;
    bool report(int key, bool raw) noexcept;         // the one filter
};
}
```

- **Captured:** `report` returns `false` for every key.
- **Not captured, key masked:** `report` returns `false`. The first time it
  sees `raw == false`, it unmasks the key, and from then on returns `raw`.
- **Not captured, key not masked:** `report` returns `raw`.
- **Calling `capture()` while already captured** is a no-op. Calling
  `release()` while not captured is also a no-op, and does not re-mask.

Consequences, which the gtests pin down:

- A key held when capture starts reads up on the next poll, so the pollers emit
  their normal key-up.
- A key held through release reads up until it is physically released.
  `prev` and `now` both read `false`, so no edge is produced.
- A key first pressed after release is reported normally.

### 2.2 `Window`

- `Window` owns a `KeyGate gate_`.
- `Window::key_state(k)` returns `gate_.report(k, glfwGetKey(handle_, k) == GLFW_PRESS)`.
  `report` mutates the gate, so `key_state` drops `const`; update the header
  and any callers that relied on it.
- New `Window::set_key_capture(bool on)` and `Window::key_capture_active()`:
  - when `on`, it calls `gate_.capture()`;
  - when off, it reads `glfwGetKey` for every key `key_state` has ever been
    asked about (a `polled_keys_` set that `key_state` records), collects the
    ones that are down, and calls `gate_.release(down)`.
    - Only polled keys matter, because the game reads keys only through
      `key_state`. `polled_keys_` covers every key the game polled before
      release, and the game polls its keys every frame, so a key first
      polled after release is one nobody was reading. (Native `key_pressed`
      reports a held key's first query as an edge — pre-existing, out of
      scope for this spec.)
    - Scanning the full `GLFW_KEY_SPACE..GLFW_KEY_LAST` range instead would
      hit the gaps in GLFW's key codes, which raise `GLFW_INVALID_ENUM`.
- **`Window` becomes the only file in `native/src` that calls `glfwGetKey`,**
  and only inside `key_state` and `set_key_capture`.
- The snapshot loop at `host_bindings.cc:1851` becomes
  `prev = g_window->key_state(k);`.
- `mouse_button_state` and the scroll accumulator are unchanged.

### 2.3 Bindings

In `native/src/host/host_bindings.cc`:

- `set_key_capture(on: bool) -> None`;
- `key_capture_active() -> bool`.

Non-CEF builds get the same two, since they don't depend on CEF. Add them to
`engine/host_io.py` as wrappers that are a no-op or `False` with no host, and
to `_REQUIRED_BINDINGS`.

### 2.4 Native capture reset

- `ui_cef` gains `set_capture_reset_handler(std::function<void()>)`, stored on
  `DauntlessCefClient`.
- It fires:
  - from `OnLoadStart`, for the main frame of our browser, under the same
    DevTools guard as the existing `page_loaded_` reset;
  - from a new `OnRenderProcessTerminated`. The client gains
    `CefRequestHandler` and a `GetRequestHandler()` override; it implements
    only that callback.
- `host_bindings` wires the handler at CEF init to
  `g_window->set_key_capture(false)`. No Python runs. Python learns of the
  reset through `key_capture_active()` (§4.2, step 1).

### 2.5 Edit commands (clipboard and undo)

In macOS OSR, Cmd shortcuts arrive through the application's Edit menu, so CEF
never acts on them as key events. Run them directly instead.

- `text_input.h` gains `kTextEventEdit = 2` and
  `enum class EditCommand { None, SelectAll, Copy, Paste, Cut, Undo, Redo }`.
- It also gains a pure function
  `EditCommand edit_command_for(char letter, int mods) noexcept`:
  - the primary modifier is `GLFW_MOD_SUPER` on macOS and `GLFW_MOD_CONTROL`
    elsewhere, chosen at compile time;
  - with the primary modifier: `a` → SelectAll, `c` → Copy, `v` → Paste,
    `x` → Cut, `z` → Undo, `y` → Redo;
  - with the primary modifier and Shift: `z` → Redo;
  - anything else → None, including no modifier, the wrong modifier, or
    Alt held.
- **The key callback,** before the editing-keys filter, does this on
  PRESS/REPEAT when a primary modifier is held:
  - resolve the layout letter with `glfwGetKeyName(key, scancode)`, so non-QWERTY
    layouts work;
  - if `edit_command_for` gives a command, push
    `{kTextEventEdit, (int)cmd, scancode, action, mods}` and return.
- **`cef_send_key_event`** routes kind 2 to a new
  `ui_cef::edit_command(int cmd)`. That calls the focused frame's
  `SelectAll()`/`Copy()`/`Paste()`/`Cut()`/`Undo()`/`Redo()`, and is a no-op
  with no browser.
- **Pre-boot gets this for free,** because its loop forwards every queued event.

### 2.6 Unchanged

The queue's capacity and drop-oldest policy, the char and editing-key events,
`glfw_key_to_windows_vk`, and the pre-boot loop all stay as they are.

### 2.7 Superseded 2026-10-02: `TextEventTranslator` (arrows moving twice, typed characters dropped)

A live trace found CEF's macOS key translator
(`CefBrowserPlatformDelegateNativeMac::TranslateWebKeyEvent`) treats
`character == 0 && unmodified_character == 0` as `NSEventTypeFlagsChanged` and
**ignores the `KEYEVENT` type entirely** — so sending an editing key's press
*and* release with `character = 0` (as §2.3/§2.5 originally did, one
`cef_send_key_event` call per queued event) made both arrive in Blink as a
key-down. One Right-arrow tap moved the caret twice. Typed characters, sent as
bare `CHAR` events with `native_key_code = 0` and no preceding key-down, are
not what a real keyboard produces either — the first one after a handled
key-down was silently dropped.

This supersedes §2.3's `cef_send_key_event` and the "queue every editing key"
half of §2.2/the original §3.0 queue description:

- **The key callback now queues every key** (`window.cc`), not just the
  editing-key subset `glfw_key_to_windows_vk` recognizes. The edit-command
  branch (§2.5) still short-circuits first and unchanged.
- **`renderer::TextEventTranslator`** (`text_input.h`/`.cc`) is a pure,
  stateful class that turns one frame's drained queue into CEF's own
  KEYDOWN+CHAR / KEYUP sequence, with a non-zero character on every event it
  emits on Apple — mirroring CEF's reference macOS OSR client
  (`tests/cefclient/browser/text_input_client_osr_mac.mm`), which sends one
  `KEYEVENT_KEYDOWN` and then the same event as `KEYEVENT_CHAR` per press,
  and a `KEYEVENT_KEYUP` with the same character fields on release. It
  remembers, per held key, the character to replay on that key's eventual
  KEYUP (`held_`); `reset()` forgets everything, for a capture boundary.
- **`cef_lifecycle` gains `send_key_intent`** (replacing `send_key_event`),
  taking one already-paired `renderer::CefKeyIntent`. `renderer::CefKeyType`'s
  four values are defined to equal `cef_key_event_type_t`'s, so the type cast
  is exact.
- **The binding is now a batch:** `cef_send_text_events(events)` replaces
  per-event `cef_send_key_event`. It walks one frame's whole drained list,
  via `renderer::build_text_event_steps`, into an ordered sequence of steps
  — a run of kind-0/1 events translated together (pairing depends on seeing
  a key and its immediately-following char event in the same run) or one
  kind-2 edit command — and executes each step in the batch's **original
  order**. This matters: a naive two-pass split (every edit command first,
  every translated key intent after, which is what an earlier revision of
  this binding did) reorders a frame that holds both — a frame of `['-'
  press, '-' char, Cmd+V]` would paste before the `-` was inserted, and a
  typed character immediately followed by Cmd+Z would undo the wrong thing.
  `build_text_event_steps` shares ONE process-wide, host-owned
  `TextEventTranslator` across the whole batch (so pairing/held-key state
  still carries correctly across edit commands in between), and
  `cef_reset_text_translator()` is the new binding for `reset()`.
- **Non-BMP codepoints are dropped, not truncated.** CEF's `character`/
  `unmodified_character` fields are `char16_t`; a codepoint above `0xFFFF`
  (e.g. an emoji) does not fit, and a naive `static_cast<char16_t>` would
  wrap it to some other, wrong 16-bit value — which on macOS risks landing
  back on `0` and retriggering the flags-changed trap this whole translator
  exists to dodge. `TextEventTranslator::translate` drops any such char
  event instead (lone or paired with a key): no intent emitted, and a
  paired key is not remembered, so its later release is a no-op too.
- **`engine/ui/text_capture.py`** sends the whole frame's queue in one
  `host_io.cef_send_text_events(events)` call instead of per-event sends, and
  calls `host_io.cef_reset_text_translator()` on every capture-boundary
  transition (focus gained, blur, forced release, and the native-reset path)
  so a key held across the boundary cannot replay a stale KEYUP into a field
  that never saw its KEYDOWN.
- **Off-Apple is unverified** (no reference client to check against there):
  the key-down type becomes `RawKeyDown` rather than `KeyDown` (CEF's own
  Windows path sends `RAWKEYDOWN`), and the CHAR half is skipped whenever the
  platform character is 0 (arrows/Home/End/Delete carry no character off-
  Apple; `windows_key_code` carries the key instead there, and the character
  ==0 flags-changed rule that motivates all of this is macOS-only).

See `native/src/renderer/include/renderer/text_input.h`'s `TextEventTranslator`
doc comment for the exact rule set, and `native/tests/renderer/text_input_test.cc`
for the gtest coverage (`TextEventTranslator.*`).

## 3. The page: `text_capture.js`

`native/assets/ui-cef/js/text_capture.js` (new), loaded once by `index.html`
ahead of the panel scripts. It is kept thin: focus and blur reporting, plus three
keys. All other logic stays in Python.

**Editable** means one of:

- `textarea`;
- an element with `contenteditable`, unless the value is `"false"`;
- `input` whose `type` is `text`, `search`, `number`, `email`, `url`,
  `password` or `tel`.

Checkboxes, ranges and buttons never capture.

**The owner** is the nearest ancestor carrying `data-panel`. Its value is the
panel's registry `name`.

- **An untagged field** sends `kbd/focus:` with an empty owner. In game, Python
  refuses it with a logged warning and pushes a blur, so a panel missing its
  tag fails visibly (the field won't hold focus) rather than leaking keys.
- **Pre-boot** is unaffected: its event handler routes only its own panel's
  prefix and drops `kbd/` events. The Mods screen's untagged fields still get
  the Esc and Enter behaviour below, which applies to every editable element.

**Document listeners (capture phase):**

- **`focusin` on an editable element:** remember its current value (a `WeakMap`
  keyed by element; `textContent` for contenteditable), then call
  `dauntlessEvent('kbd/focus:' + owner)`.
- **`blur` from an editable element (capture phase, not `focusout` — a panel may remove the field in its own blur handler, and a detached field's focusout never reaches the document):** if `relatedTarget` is editable, do
  nothing. Otherwise call `dauntlessEvent('kbd/blur')`.
- **`keydown` on an editable element:**
  - **Esc:** restore the remembered value, `blur()`, `preventDefault()` and
    `stopPropagation()`. Because the value is restored before the blur, no
    `change` event fires and nothing commits.
  - **Enter, except in `textarea`:** `blur()` and `preventDefault()`. The
    browser's `change` event then fires, and that is the commit.

**`window.__dauntlessBlurText()`:** if the active element is editable,
restore its remembered value, then `blur()` it. Python calls this for a forced
release. It abandons the edit.

**Panel-side cancel and commit helpers,** for in-panel ✕/✓ buttons (§5):

- `window.__dauntlessTextCancel(el)` is the same as Esc on `el`;
- `window.__dauntlessTextCommit(el)` calls `el.blur()`.

## 4. Python

### 4.1 `TextCaptureController`

`engine/ui/text_capture.py` (new). A `Panel` named `kbd`, registered once in
`run()`, so `PanelRegistry` routes `kbd/...` to it. It holds a registry
reference, `owner: Optional[str]` and `_blur_pending: bool`.

`PanelRegistry` gains `find(name) -> Optional[Panel]`.

**Events (`dispatch_event`):**

- **`focus:<name>`:**
  - if `registry.find(name)` exists and is open, set `owner = name` and call
    `host_io.set_key_capture(True)`;
  - otherwise, refuse: leave capture off and set `_blur_pending`, which also
    clears a field focused on a panel that is closing. An empty or unknown
    name also logs a warning naming it, since that means a panel is missing
    its `data-panel` tag.
- **`blur`:** `owner = None` and `host_io.set_key_capture(False)`. Idempotent.
  It does not set `_blur_pending`; the page has already blurred.

**Open** means `panel.is_open()` when the panel defines it, otherwise
`panel.visible`.

**`render_payload()`** returns `"window.__dauntlessBlurText&&window.__dauntlessBlurText()"`
once when `_blur_pending` is set, clears the flag, and otherwise returns `None`.
That reuses the registry's existing JS path, which is already gated on page
load.

**`release()`** (forced release, triggers 3-5):

- if `owner` is not `None`, set `owner = None`, call `set_key_capture(False)`
  and set `_blur_pending`;
- if `owner` is `None`, do nothing.

The page's resulting `blur` sends `kbd/blur`, which is then a harmless
no-op.

### 4.2 `tick()`: once per frame, top of the input block

`tick()` runs before `_dispatch_modal_esc` and the Controls-capture branch, in
both paused and unpaused frames. It takes three steps:

1. **Native reset.** If `owner` is set and `host_io.key_capture_active()` is
   `False`, set `owner = None`. No JS is sent, because the page that had focus
   is gone.
2. **Owner gone (trigger 3).** If `owner` is set and that panel is no longer
   open, call `release()`.
3. **Drain the queue.** Call `host_io.drain_text_events()` every frame. When
   `owner` is set, forward each event with `host_io.cef_send_key_event(*ev)`.
   Otherwise, discard them. Draining every frame keeps stale gameplay
   keystrokes from reaching a field when it gains focus.

### 4.3 Host-loop wiring (`engine/host_loop.py`, `run()`)

- **Construction and calls:**
  - construct `TextCaptureController(registry)` and register it with the other
    panels;
  - call `text_capture.tick()` at the top of the per-frame input block.
- **Mission swap (trigger 4):**
  `controller.pre_swap_hooks.append(text_capture.release)`, beside the SPV's
  existing hook at about `host_loop.py:9905`.
- **Unrouted click (trigger 5):** in the unpaused click router (around
  `host_loop.py:10667`), when the left button is pressed and
  `_cursor_in_panel` is false, call `text_capture.release()`. In paused
  frames every click already goes to CEF, so the page blurs on its own, and
  the edit commits as it would from clicking any other page control.
- **Nothing else changes:**
  - no key call site, no `_modal_blockers` entry and no Esc routing;
  - Esc cannot reach `_dispatch_modal_esc` while captured, because
    `key_pressed(KEY_ESCAPE)` reads `False`;
  - after the field blurs, the Esc that blurred it stays masked until it is
    released (D3), so it does not open the pause menu.

### 4.4 The panel contract (what consumers do)

A panel that hosts a text field must:

1. put `data-panel="<its registry name>"` on its root element;
2. commit on the field's DOM `change` event by sending
   `dauntlessEvent('<name>/<action>:' + value)`, validated in Python as usual;
3. expect an edit to be abandoned (reverted, no `change`) on Esc, on panel
   close, on mission swap, and on clicking the game world in an unpaused frame.

Capture is automatic. No consumer calls `set_key_capture`.

## 5. First consumer: SPV Move, Rotate and Scale rows

### 5.1 Behaviour

- **At rest, nothing changes.** Each row looks exactly as it does today:
  `axis  [−big][−small]  value  [+small][+big]`. The only visible difference is
  that the value span shows a text cursor on hover.
- **Clicking the value** swaps that row's steppers and value for:
  `axis  [ input ]  [✕][✓]`.
  - The axis label stays.
  - The input fills the space the steppers and value used.
  - It is pre-filled with the value at full precision, focused, and its text
    selected.
- **Commit:** Enter, ✓, or clicking or tabbing elsewhere in the page.
  - The text is trimmed and a decimal comma becomes a point (`1,5` → `1.5`).
    It is then parsed with `Number(...)`.
  - If the text is empty, or the result is not finite, the row reverts and
    nothing is sent. Empty must be checked explicitly: `Number('')` is `0`, so
    a cleared field would otherwise move the target to zero.
  - Otherwise the event in §5.2 is sent and the row swaps back. The new value
    arrives with Python's refresh.
- **Abandon:** Esc, ✕, or a forced release (§4.1). The row swaps back showing
  the old value, and nothing is sent.
- **How the row tells them apart.** The row listens for the input's `blur`
  rather than `change`, because it must swap back on *every* exit. On blur:
  - if the text equals the pre-filled text, it swaps back and sends nothing;
  - otherwise it parses and commits.

  Esc, ✕ and a forced release all restore the pre-filled text before
  blurring, so they land in the first branch. That means no cancel flag is
  needed, which matters because `text_capture.js`'s capture-phase Esc handler
  stops propagation, so the row never sees the Esc keydown.
- **✕ and ✓** call `preventDefault()` on `mousedown`, so pressing them does
  not blur the input before their `click` runs. Otherwise blur would commit
  before ✕ could abandon. Their clicks call
  `__dauntlessTextCancel(input)` / `__dauntlessTextCommit(input)`.
- **One row edits at a time.** While a row in a panel is in edit mode,
  `spvShowPanel` skips rebuilding that panel's rows, so a payload refresh or a
  gizmo push cannot destroy the input. The panel rebuilds normally as soon as
  the row swaps back.
- **Panel root:** `#spv-root` gets `data-panel="ship-property-viewer"`.
- **Stale comments:** the "mouse-only steppers (no keyboard→CEF forwarding)"
  comments in `index.html` and `ship_property_viewer.js` are corrected.

### 5.2 Events and Python actions

All three are added to `ShipPropertyViewerPanel.dispatch_event`. Each is
validated like its `*_nudge` sibling (JSON parse, index range, finite float)
and goes through the existing `EditTarget` adapters, so every editable kind
gets them with no kind-specific branch.

| Event | Payload | Action |
|---|---|---|
| `coord_set` | `{"axis": i, "value": v}` | `p = list(t.position()); p[i] = v; t.set_position(tuple(p))` |
| `scale_set` | `{"index": i, "value": v}` | `t.set_scale_field(i, v)`, on `_scale_edit_target()` |
| `rotate_set` | `{"axis": i, "value": v}` | `t.rotate_nudge(i, v - shown)`, where `shown` is the row's current accumulator readout (`t.rotate_spec()["fields"][i]["value"]`) |

**Rotate sets by difference** because the Rotate rows show a per-target
*accumulator* of degrees nudged, not an absolute angle. Typing 30 into X does
exactly what clicking the steppers until the readout says 30 would do.

**The lock applies to typed edits too.** `coord_set:`, `scale_set:` and
`rotate_set:` all join `_MOUNT_GIZMO_PREFIXES`. That tuple is the
locked-mount gate (`_is_locked_mount_action`). Without these entries, a typed
value would edit a mount that the steppers and gizmo refuse to touch. A test in
§7.7 pins this.

## 6. Units

| Unit | Job |
|---|---|
| `native/src/renderer/{include/renderer/key_gate.h,key_gate.cc}` (new) | Pure gate and mask (§2.1) |
| `native/src/renderer/window.{h,cc}` | Own the gate; `key_state` filtered; `set_key_capture` / `key_capture_active`; edit-command push in the key callback; queues EVERY key (§2.7), not just editing keys |
| `native/src/renderer/{include/renderer/text_input.h,text_input.cc}` | `kTextEventEdit`, `EditCommand`, `edit_command_for`; `CefKeyType`, `CefKeyIntent`, `TextEventTranslator`; `TextEventStep`, `build_text_event_steps` (order-preserving split around edit commands) (§2.7) |
| `native/src/ui_cef/` (`cef_client.{h,cc}`, `cef_lifecycle.cc`, public header) | Capture-reset handler on `OnLoadStart` + `OnRenderProcessTerminated`; `edit_command(cmd)`; `send_key_intent` (§2.7, supersedes `send_key_event`) |
| `native/src/host/host_bindings.cc` | Snapshot via `key_state`; `set_key_capture`, `key_capture_active`; `cef_send_text_events` batch binding, built on `build_text_event_steps` + the process's one `TextEventTranslator`, `cef_reset_text_translator` (§2.7, supersedes per-event `cef_send_key_event`) |
| `engine/host_io.py` | Wrappers and `_REQUIRED_BINDINGS`; `cef_send_text_events`/`cef_reset_text_translator` (§2.7) |
| `native/assets/ui-cef/js/text_capture.js` (new), `index.html` | §3 |
| `engine/ui/text_capture.py` (new) | `TextCaptureController` (§4.1-4.2) |
| `engine/ui/panel_registry.py` | `find(name)` |
| `engine/host_loop.py` | Construct, register, tick, swap hook, unrouted-click release (§4.3) |
| `native/assets/ui-cef/js/ship_property_viewer.js`, `index.html`, CSS | Click-to-edit rows (§5.1) |
| `engine/ui/ship_property_viewer_panel.py` | `coord_set`, `scale_set`, `rotate_set` (§5.2) |

## 7. Testing

All of it runs under `scripts/check_tests.sh`.

1. **gtest `KeyGate`** (`native/tests/`):
   - captured ⇒ every key `false`;
   - held across release ⇒ `false` until a raw-`false` sample, then tracks raw;
   - a key pressed after release is not masked;
   - release with nothing down ⇒ no mask;
   - a second `capture()` and a stray `release()` are no-ops.
2. **gtest `edit_command_for`:**
   - the platform modifier with each of `a c v x z y`;
   - Shift+`z` → Redo;
   - no modifier, the wrong modifier, or Alt held ⇒ None.
3. **Structural guard** (`tests/tools/test_raw_key_reads.py`). Every `glfwGetKey`
   in `native/src` must sit inside `Window::key_state` or
   `Window::set_key_capture` in `window.cc`. The test finds the enclosing
   function by parsing brace structure, not by matching lines. Any new raw read
   fails the gate.
4. **`TextCaptureController` unit tests** (`tests/ui/test_text_capture.py`) cover:
   - focus with an open owner ⇒ capture on;
   - unknown or closed owner ⇒ refused, with one blur payload;
   - blur ⇒ capture off, with no payload;
   - owner closes ⇒ release and exactly one blur payload;
   - native reset ⇒ owner dropped, with no payload;
   - `release()` from the swap hook and the unrouted click;
   - `release()` with no owner does nothing;
   - the queue is forwarded only while an owner is set, and discarded
     otherwise.
5. **Host-loop wiring test** (`tests/host/test_text_capture_wiring.py`). It
   uses a fake `h` that implements the gate contract:
   - `key_state` and `key_pressed` report up while captured;
   - masking on release follows §2.1.

   With capture on and W, Space, a fire key, `1`, Esc and a registered dev key
   held, one frame of the real input path shows:
   - no throttle change, no fire, no raw or `ET_KEYBOARD` dispatch;
   - no alert change, no dev handler call, no pause toggle and no
     `handle_key_esc`.

   After a `kbd/blur` with Esc still held, the next frame does not toggle pause.
   Once Esc is released and pressed again, it does.
6. **JS source-shape tests** (`tests/ui/test_text_capture_js.py`,
   `tests/ui/test_spv_value_edit_js.py`) check:
   - the editable selector excludes checkbox and range;
   - Esc restores before blurring;
   - the capture-phase blur listener checks `relatedTarget`;
   - `__dauntlessBlurText` restores before blurring;
   - `index.html` loads `text_capture.js` and `#spv-root` carries `data-panel`;
   - the SPV ✕ and ✓ buttons call `preventDefault` on mousedown;
   - `spvShowPanel` has the edit-mode guard.
7. **SPV action tests** (`tests/ui/`):
   - `coord_set`, `scale_set` and `rotate_set` across the mount, light, emitter
     and part-node adapters;
   - malformed JSON, a bad index or a non-finite value ⇒ rejected;
   - `rotate_set` applies `v - accumulator`;
   - on a locked mount, all three are refused, as the `*_nudge` actions are.
8. **gtest `TextEventTranslator`** (`native/tests/renderer/text_input_test.cc`,
   §2.7), Apple-guarded where the expected character is platform-specific:
   - an arrow tap (press then release across two `translate()` calls) emits
     exactly `[KeyDown, Char]` then `[KeyUp]`, never a KEYUP with character 0;
   - a printable key's press+char pairs into `[KeyDown, Char]`, with
     `native_key_code` the key event's scancode, not 0; three presses of the
     same key each produce their own pair and their own KEYUP;
   - a REPEAT produces another `[KeyDown, Char]` pair; still one KEYUP at
     release;
   - a modifier alone (Shift) emits nothing and is not remembered;
   - a char with no preceding key emits `[KeyDown, Char]` with
     `native_key_code` 0 and no KEYUP;
   - a release with nothing held emits nothing; `reset()` forgets a held key;
   - Backspace/Enter/Escape carry their control characters;
   - a kind-2 event is never translated (the caller routes it to
     `ui_cef::edit_command` instead);
   - press+char+release all passed in a SINGLE `translate()` call still
     pairs and releases correctly;
   - Shift held alone emits nothing, and a Shift-modified letter (Shift
     press, letter press+char, letter release, Shift release) emits only
     the letter's KeyDown/Char/KeyUp;
   - a printable key pressed with no following char, then released, emits
     nothing for either;
   - a char codepoint above `0xFFFF` emits nothing, whether lone or paired
     with a key (and a paired key is not remembered: its later release is
     also a no-op).
9. **gtest `BuildTextEventSteps`** (`native/tests/renderer/text_input_test.cc`,
   §2.7) — the ordering-regression guard:
   - a batch of `['-' press, '-' char, Cmd+V edit, '1' press, '1' char]`
     produces exactly three steps in that order: the `-` intents, then the
     Paste edit command, then the `1` intents — proving the binding no
     longer runs every edit command before every key intent;
   - a batch with no edit commands produces exactly one key step;
   - two adjacent edit commands each get their own step, with no empty key
     step wedged between them.

## 8. Live check (Mark)

Open the SPV from the pause menu, select a mount and choose the Move tool.

1. Click the X value. The row becomes an input with ✕ and ✓, and the value is
   selected.
2. Type `-1.5` and press Enter. The mount moves to X = −1.5 and the view does
   **not** zoom.
3. Click a value and type `=`. The view does not zoom.
4. Type something, then press Esc. The row reverts and the SPV stays as it was.
5. Press Esc again. The SPV does what Esc normally does.
6. Edit a value and press ✕. The row reverts. Edit again and press ✓. It
   commits.
7. Use Cmd+A, Cmd+C, and Cmd+V into another row.
8. Repeat steps 1-2 with the Rotate and Scale tools.
9. Close the SPV while a row is in edit mode, then resume flight. W and Space
   work.

The SPV pauses the sim, so this check cannot show flight keys staying silent
while typing. The wiring test (§7.5) covers that.

## Not in scope

- IME composition (CJK input) and dead-key accents beyond what GLFW's char
  callback already delivers.
- Multi-line `textarea` behaviour beyond "Enter inserts a newline".
- Other text fields: the SPV radius stepper, Quick Battle names. Each adopts
  the §4.4 contract in its own work.
- A JS runtime test harness.
- Pre-boot changes beyond receiving edit commands for free.
