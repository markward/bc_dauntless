# SDK info-box rendering — design

**Date:** 2026-06-17
**Status:** Spec draft, awaiting user review.

**Motivation:** Loading E1M1 crashes in `SetupTacticalViewInfoBox` with
`AttributeError: type object 'TGParagraph' has no attribute 'TGPF_READ_ONLY'`.
The immediate cause is missing constants, but the real gap is larger: the SDK's
on-screen **info boxes** — tutorial/help popups built by
`MissionLib.SetupInfoBoxFromParagraph` (tactical-view controls, Scan, Hail,
Orbit, Engineering power, attack orders, … ~15 in E1M1 alone, used across most
missions) — construct a `TGParagraph` text tree that our shim only partially
implements, and which nothing renders. Rather than no-op the missing methods
(smothering the error), this spec implements the info box end-to-end: real
`TGParagraph` content, a CEF-rendered modal, and a working Close button.

It extends the proven two-tier pattern of the
[CEF SDK-UI mirror](2026-06-03-cef-sdk-ui-mirror-design.md) and
[TG widget tree + crew menus](2026-06-12-tg-widget-tree-crew-menus-design.md):
headless Python shims own state, a `Panel` observes and projects into CEF, CEF
clicks route back as real SDK events.

---

## Goals

1. Make `TGParagraph` hold its genuine assembled content (body text + inline
   key-binding glyph children) as an ordered segment stream, so the info-box
   help text is real data, not a discarded string.
2. Render every visible `SetupInfoBoxFromParagraph` info box in the CEF overlay
   as a dauntless-styled modal: title, body text with inline key chips, and a
   Close button.
3. Close the click loop: clicking Close in CEF fires the box's real
   `ET_INPUT_CLOSE_MENU` event, reaching `MissionLib.CloseInfoBox` and the
   mission's own close handler, so the box dismisses and "don't-show-again"
   flags get set exactly as in BC.
4. Unblock mission loading: E1M1 (and the other affected missions) initialize
   without `AttributeError`.

## Non-goals

- **No LCARS recreation / BC font fidelity.** Dauntless re-style, consistent
  with the 2026-06-03 and 2026-06-12 mirror specs. SDK `(x, y)` coords are
  accepted at the shim API and ignored at render time; slot CSS decides layout.
- **No general SDK→Python click router.** Only the info-box Close path is
  wired. The broader click-dispatch effort remains a separate follow-up; this
  spec wires exactly what the Close button needs, reusing
  `STButton.SendActivationEvent` + `g_kEventManager` as the crew-menu panel does.
- **No save/load of info-box state.** SDK rebuilds boxes on mission load; no
  `__getstate__`/`__setstate__`.
- **No keyboard / ESC-to-close in v1.** Close button only. ESC routing can be
  added later.
- **No paragraph text styling beyond key chips.** Font/scale are stored but not
  honoured; each key-glyph child's color is passed to CEF as a hint only.
- **No rendering of non-info-box `_STStylizedWindow` children** beyond what the
  visibility gate naturally includes. The panel renders visible stylized
  windows parented to `TacticalControlWindow`; in practice these are the info
  boxes (crew menus live on the separate `_menus` list, already rendered by
  `crew_menu_panel`).

---

## Architecture

Four units plus one wiring fix. Each unit is independently testable.

### File layout

| File | Status | Purpose |
|---|---|---|
| `engine/appc/tg_ui/widgets.py` | edit | `TGParagraph` segment stream + `TGPF_*` flag constants (flags already added as the crash hotfix); `AppendChar`/`AppendStringW`/`AddChild` build segments |
| `App.py` | edit | Export `WC_*` wide-char constants as real ints |
| `engine/ui/info_box_panel.py` | **new** | `InfoBoxPanel(Panel)` — observes `TacticalControlWindow._children`, serializes visible info boxes, dispatches `close:<id>` |
| `engine/appc/windows.py` | edit | `_STStylizedWindow.ProcessEvent` walks `_handler_registrations` (the wiring fix) |
| `engine/host_loop.py` | edit | Construct `InfoBoxPanel`, register with `PanelRegistry` (always-on, not dev-gated) |
| `native/assets/ui-cef/hello.html` | edit | Add `#sdk-infobox` slot; link new CSS + JS |
| `native/assets/ui-cef/js/info_box.js` | **new** | `setInfoBoxes(payload)` render + Close click → `dauntlessEvent("info-box/close:<id>")` |
| `native/assets/ui-cef/css/info_box.css` | **new** | Modal styling matching mission-picker / config chrome |
| `tests/unit/test_tg_paragraph_segments.py` | **new** | Segment append order, `GetText()` flatten, WC mapping, backward-compat |
| `tests/unit/test_wc_constants.py` | **new** | `App.WC_*` values |
| `tests/unit/test_info_box_panel.py` | **new** | Snapshot shape, visible-only filter, dedup, segment serialization, invalidate |
| `tests/unit/test_st_stylized_window_process_event.py` | **new** | `ProcessEvent` invokes registered handlers; unregistered inert |
| `tests/integration/test_info_box_close_round_trip.py` | **new** | Build box → `close:<id>` → not-visible + close handler ran |

### Unit 1 — `TGParagraph` content stream

Replace the single `_text: str` with `_segments: list`, where each segment is a
2-tuple:

- `("text", str)` — appended via `AppendStringW(s)` / constructor text / `SetText`
- `("char", int)` — appended via `AppendChar(wc)`; `wc` is a `WC_*` code point
- `("child", TGParagraph)` — appended via `AddChild(child)` (the inline
  key-binding glyph)

`AddChild` continues to satisfy the `TGPane` container contract (the child is a
real widget), but `TGParagraph` records it positionally in the segment stream so
render order is preserved.

API surface:

- `AppendStringW(s)` / `AppendString(s)` — append a `("text", str)` segment.
- `AppendChar(wc)` — append a `("char", int)` segment.
- `AddChild(child, x=0.0, y=0.0, *_)` — append `("child", child)` and store on
  the base `_children` list for `TGPane` compatibility.
- `GetText()` — flatten segments to a plain string: `text` verbatim; `char`
  mapped (`WC_RETURN`/`WC_LINEFEED`→`"\n"`, `WC_SPACE`→`" "`, `WC_TAB`→`"\t"`,
  `WC_CURSOR`→`""`, other → `chr(wc)`); `child` → `child.GetText()`. Preserves
  existing callers that only read flat text.
- `SetText(s)` / `SetStringW(s)` — reset `_segments` to a single text segment
  (matches prior reset semantics).
- `flatten_segments()` — dauntless-internal helper returning the ordered
  renderable stream (text runs coalesced; children surfaced as objects) for the
  panel to serialize. Not an SDK method.

`TGPF_*` flag constants (`TGPF_READ_ONLY=0x01`, `TGPF_INSERT_MODE=0x02`,
`TGPF_WORD_WRAP=0x04`, `TGPF_RECALC_BOUNDS=0x08`, `TGPF_FLAGS_MASK=0x0F`) are
opaque OR-able ints — never decoded. (Landed already as the crash hotfix; listed
here for completeness.)

### Unit 2 — `WC_*` wide-char constants

Real ints at faithful Unicode code points, exported from `App.py` alongside the
existing `ET_*` enums:

| Constant | Value | Note |
|---|---|---|
| `WC_BACKSPACE` | 8 | |
| `WC_TAB` | 9 | |
| `WC_LINEFEED` | 10 | |
| `WC_RETURN` | 13 | |
| `WC_SPACE` | 32 | |
| `WC_CURSOR` | 0xE000 | Unicode Private-Use-Area sentinel; BC's real value is engine-internal and never displayed |

Only the codes actually referenced by the info-box path (and obvious neighbours)
are defined now; more can be added when a script needs them. They are plain
module constants, not flags.

### Unit 3 — `InfoBoxPanel`

A `Panel` subclass, `name = "info-box"`, registered always-on with
`PanelRegistry` (info boxes are gameplay UI, not dev-only).

`render_payload()`:
- Walk `TacticalControlWindow.GetInstance()._children` (each entry is a
  `(child, x, y)` tuple).
- Keep children that are `_STStylizedWindow` **and** `IsVisible()`.
- For each, serialize:
  ```json
  {
    "id": "<box id>",
    "title": "<title>",
    "body": [ {"kind": "text", "text": "..."},
              {"kind": "key",  "text": "W", "color": [r,g,b,a]}, ... ],
    "button": {"id": <stable widget id>, "label": "Close"}   // or null
  }
  ```
  `body` is produced by locating the box's body `TGParagraph` (walk
  box → `TGPane` child → `TGParagraph`) and serializing its segment stream:
  `text`/`char` → `{kind:"text"}` (chars mapped as in `GetText`); `child` →
  `{kind:"key", text: child.GetText(), color: child._color}`.
  The Close button is the box's `STButton` descendant; its id comes from
  `ensure_widget_id` (same helper the crew panel uses for stable CEF ids).
- Dedup against `_last_pushed`; emit `setInfoBoxes(<payload>);` only on change.
- `invalidate()` resets `_last_pushed = None` so a CEF reload re-emits (matches
  the other panels).

`dispatch_event(action)`:
- `"close:<id>"` → resolve the box by id from the last snapshot; find its
  `STButton`; call `button.SendActivationEvent()`. Stale id → log + drop
  (next snapshot repairs the UI). Returns `True` for any `close:` action.
- Anything else → `False`.

### Unit 4 — CEF slot

- `hello.html`: `<div id="sdk-infobox"></div>` slot; `<link>` to
  `css/info_box.css`; `<script>` to `js/info_box.js`.
- `info_box.js`: `setInfoBoxes(payload)` rebuilds the slot — one modal per
  entry: title bar, body (text runs as spans, `kind:"key"` segments as
  `<span class="key-chip">` with the color hint applied inline), and a Close
  button whose click calls `dauntlessEvent("info-box/close:" + entry.button.id)`.
  Empty `entries` clears the slot.
- `info_box.css`: centred modal stack, dauntless chrome (reuse mission-picker /
  config variables), `.key-chip` bordered inline style. z-index above the 3D
  scene, below the pause menu (consistent with the existing mirror slots).

### Wiring fix — `_STStylizedWindow.ProcessEvent`

`_STStylizedWindow` overrides `AddPythonFuncHandlerForInstance` to append
`(event_type, "module.func")` to its own `_handler_registrations` list, but the
inherited `ProcessEvent` never consults that list, so registered handlers never
fire. Implement `_STStylizedWindow.ProcessEvent(event)`:

- Read `event.GetEventType()`.
- For each `(etype, qualified_name)` in `_handler_registrations` matching the
  type, resolve `qualified_name` (`"module.func"`: import module, get attr) and
  call `func(self, event)`.
- Resolution failures are logged once and skipped (never crash the tick).

This is the minimal, faithful path: the Close button created in
`SetupInfoBoxFromParagraph` holds a `TGEvent` with
`type = ET_INPUT_CLOSE_MENU`, `destination = box`; `SendActivationEvent` pushes
it to `g_kEventManager`, which calls `box.ProcessEvent`, which now dispatches to
`MissionLib.CloseInfoBox` and the mission's `TacticalInfoBoxClosed`.

---

## Data flow

### Render (per tick, read-only)

```
SetupInfoBoxFromParagraph():
  _STStylizedWindow(title) ──AddChild──▶ TGPane ──AddChild──▶ TGParagraph (segments)
                                               └─AddChild──▶ STButton("Close", event=pEvent)
  TacticalControlWindow.AddChild(box)        # box → _children
  box.SetNotVisible()                         # hidden until opened
  ...open event flips box.SetVisible()

PanelRegistry → InfoBoxPanel.render_payload():
  walk TacticalControlWindow._children → visible _STStylizedWindow boxes
  serialize {id, title, body[segments], button}
  dedup → emit setInfoBoxes(...) on change
```

### Close (CEF → SDK)

```
CEF Close click → dauntlessEvent("info-box/close:<boxId>")
  → PanelRegistry.dispatch → InfoBoxPanel.dispatch_event("close:<boxId>")
     → resolve box → STButton.SendActivationEvent()
        → g_kEventManager.AddEvent(button._event)         # type=ET_INPUT_CLOSE_MENU, dest=box
           → box.ProcessEvent(event)                       # wiring fix
              → MissionLib.CloseInfoBox(box, event)         # SetNotVisible + cleanup
              → mission TacticalInfoBoxClosed(box, event)   # sets don't-show flag
  → next tick: box not visible → InfoBoxPanel emits updated payload → modal removed
```

### Error / edge handling

- **Stale ids:** `dispatch_event` drops actions for boxes absent from the last
  snapshot; the next snapshot repairs the DOM. Same contract as `crew_menu_panel`.
- **Handler resolution failure:** logged once, skipped; tick continues.
- **No body paragraph / no Close button:** serialize what exists
  (`button: null` → CEF renders no close affordance); never crash.
- **Multiple visible boxes:** rendered as a stack; each closes independently.

---

## Testing

TDD. All headless except the CEF asset layer.

- `test_tg_paragraph_segments.py` — append order across text/char/child;
  `GetText()` flatten with WC mapping; `SetText` reset; child segments preserved;
  backward-compat for existing flat-text callers.
- `test_wc_constants.py` — `App.WC_*` equal the specified ints; plain constants.
- `test_info_box_panel.py` — snapshot shape; visible-only filter; dedup vs
  `_last_pushed`; key-chip segment serialization incl. color; `invalidate()`
  re-emit; `dispatch_event` stale-id drop.
- `test_st_stylized_window_process_event.py` — registered `module.func` handler
  is invoked with `(box, event)` for the matching event type; non-matching and
  unregistered types are inert; resolution failure does not raise.
- `test_info_box_close_round_trip.py` (integration) — build a box via
  `SetupInfoBoxFromParagraph`, assert it serializes; `close:<id>` →
  box `IsVisible()` is false and the mission close handler ran.
- CEF JS/CSS: no automated test (consistent with existing mirror panels);
  manual verification via `./build/dauntless --developer` loading E1M1 — the
  tactical-view help modal appears, Close dismisses it.

---

## Open questions

None blocking. Future extensions (separate specs): ESC-to-close, the general
SDK→Python click router, and honouring SDK pixel coordinates if dauntless ever
adopts an LCARS-faithful render mode.
