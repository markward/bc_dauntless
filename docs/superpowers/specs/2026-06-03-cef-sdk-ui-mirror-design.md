# CEF SDK-UI mirror — design

**Date:** 2026-06-03
**Status:** Spec draft, awaiting user review.
**Motivation:** SDK scripts position UI elements (`pTop.AddChild(window, x, y)`, `App.STStylizedWindow_CreateW(...)`, `App.SubtitleWindow_Cast(...)`, `App.TGCreditAction_Create(...)`) that dauntless currently drops on the floor — every `*_NamedStub`-resolved type is a silent no-op. Missions visibly do nothing for any scripted UI: no briefing windows, no mission objectives, no dialogue subtitles. The [TopWindow shim](2026-06-03-top-window-shim-design.md) recently landed `_TopWindow._children` and `_main_windows`, providing the observation surface this spec consumes. This spec mirrors three SDK UI primitives into the existing CEF overlay so scripted UI becomes visible in dauntless's visual language.

---

## Goals

1. Render three SDK UI primitives — `SubtitleWindow`, `STStylizedWindow`, `TGCreditAction` — in the CEF overlay as dauntless-styled elements.
2. Prove the end-to-end loop: SDK script → Python shim → mirror panel snapshot → CEF DOM → visible pixels.
3. Eliminate `STStylizedWindow_CreateW`, `SubtitleWindow_Cast`, and `TGCreditAction_Create` from the top of the `--profile` report.
4. Establish the per-primitive shim pattern + tree-walking mirror panel so follow-up specs (SubtitleAction, SortedRegionMenu, MapWindow, …) drop in by adding one shim + one slot.

## Non-goals

- **No faithful LCARS recreation.** Dauntless re-style chosen over LCARS chrome; SDK pixel coordinates are ignored at render time. SDK callers still pass `(x, y)` to `AddChild` and we still accept them, but the renderer doesn't consult them. The visual departure from BC is intentional and documented.
- **No bitmap assets from `game/data/Models/HUD/`.** Re-style means we don't need them.
- **No BC font fidelity.** CEF default sans-serif. `TGFont`, `TGParagraph_CreateW` text styling not honoured.
- **No SDK→Python click dispatch.** CEF emits `sdk-mirror/click:<id>` events; Python logs them but doesn't route through `_handler_registrations` or `g_kEventManager`. Identity round-trip is a follow-up spec.
- **No dialogue stream actions.** `SubtitleAction_Create`, `CharacterAction_Create` deferred. Only `TGCreditAction` (timed banner text) ships in v1.
- **No additional SDK primitives.** `SortedRegionMenu`, `MapWindow`, `CinematicWindow`, `STText_Create`, `TGIcon_Create`, `TGPane_Create`, `TGParagraph_CreateW` (standalone, not as a credit-action target) are explicitly out of scope.
- **No save-game persistence.** Mirror state is per-process. Shims do not implement `__getstate__`/`__setstate__`.
- **No game-time scaling of TGCreditAction durations.** Wall-clock expiry via `time.monotonic()`. Original BC behaviour for cinematic banners is also wall-clock.
- **No SDK z-order honoured.** Subtitle slot above stylized stack; both above the 3D scene and below the pause menu. Hard-coded slot z-indices.

---

## Architecture

### File layout

| File | Status | Purpose |
|---|---|---|
| `engine/appc/sdk_ui/__init__.py` | new | Package marker; re-exports public factories |
| `engine/appc/sdk_ui/subtitle_window.py` | new | `_SubtitleWindow` class + `SubtitleWindow_Cast` factory; `SM_*` mode constants |
| `engine/appc/sdk_ui/stylized_window.py` | new | `_STStylizedWindow` + `STStylizedWindow_CreateW` factory |
| `engine/appc/sdk_ui/credit_action.py` | new | `_TGCreditAction` + `TGCreditAction_Create` factory |
| `engine/appc/sdk_ui/mirror_panel.py` | new | `SDKMirrorPanel(Panel)` — walks `_TopWindow._main_windows` + `_children`, emits snapshot |
| `engine/appc/top_window.py` | edit | Construct `_SubtitleWindow()` into `_main_windows[MWT_SUBTITLE]` |
| `App.py` | edit | Route `SubtitleWindow_Cast`, `STStylizedWindow_CreateW`, `TGCreditAction_Create` to new factories; export `SubtitleWindow` class with `SM_*` attributes for `App.SubtitleWindow.SM_TACTICAL` access |
| `engine/host_loop.py` | edit | Construct `SDKMirrorPanel`, register with `PanelRegistry` (always-on; not dev-gated) |
| `native/assets/ui-cef/hello.html` | edit | Add `#sdk-subtitle` and `#sdk-stylized-stack` slots; link new CSS + JS |
| `native/assets/ui-cef/css/sdk_mirror.css` | new | Slot styling matching ship-display / sensors aesthetic |
| `native/assets/ui-cef/js/sdk_mirror.js` | new | `setSdkMirror(payload)` routing + click handlers |
| `tests/unit/test_sdk_ui_subtitle_window.py` | new | `_SubtitleWindow` state machine |
| `tests/unit/test_sdk_ui_stylized_window.py` | new | `_STStylizedWindow` construction + visibility |
| `tests/unit/test_sdk_ui_credit_action.py` | new | `_TGCreditAction` text driver |
| `tests/unit/test_sdk_ui_mirror_panel.py` | new | Snapshot / dedup / expiry / invalidate logic |
| `tests/integration/test_sdk_mirror_round_trip.py` | new | TGCreditAction Play → mirror payload assertion (with monkeypatched `time.monotonic`) |

**Mirror Panel ownership rule:** `SDKMirrorPanel` is the *only* consumer of `_TopWindow._children` for rendering. SDK primitives mutate their own state; the panel observes via the children list once per tick. SDK shims never push to CEF directly.

### Visual style decision

CEF renders SDK UI in dauntless's existing visual language (matching the ship-display / sensors / mission-picker chrome). SDK pixel coordinates in `AddChild(x, y)`, `TGCreditAction_Create(fX, fY, ...)` are accepted at the shim API but ignored at render time. Slot CSS decides layout. The visual departure from LCARS is the cost of not shipping BC bitmaps and font tables; mission designers' careful positioning becomes meaningless in dauntless.

---

## Data flow

```
SDK script (mission load)
  │
  ├─ STStylizedWindow_CreateW(title="Mission Briefing", ...)
  │   → _STStylizedWindow(title="Mission Briefing", _id="stylized-7", visible=True)
  │   → pTop.AddChild(window, x=200, y=150)    ← x,y ignored at render time
  │
  ├─ FindMainWindow(MWT_SUBTITLE) → singleton _SubtitleWindow
  │   .SetPositionForMode(SM_TACTICAL)         ← stored as mode flag only
  │   .SetOn()                                  ← visible=True
  │
  └─ TGCreditAction_Create("Disable the Cardassian patrol",
                           subtitle_window, fX, fY, duration=5.0, ...)
      .Play()
      → action calls host._add_text(text, duration)
      → SubtitleWindow appends (text, expires_at=now+duration) to _active_texts

Tick (PanelRegistry.tick):
  SDKMirrorPanel.render_payload()
    sub = _main_windows[MWT_SUBTITLE]
    entries = []
    if sub is not None:
      snap = sub._snapshot(time.monotonic())
      if snap is not None: entries.append(snap)
    for (child, _, _) in _TopWindow._children:
      if hasattr(child, "_snapshot"): entries.append(child._snapshot())
    payload = json.dumps({"entries": entries})
    if payload == self._last_pushed: return None
    self._last_pushed = payload
    return "setSdkMirror(" + payload + ");"
  → cef_execute_javascript

JS (sdk_mirror.js):
  setSdkMirror({entries}):
    for each entry:
      switch entry.type:
        case "subtitle": render lines into #sdk-subtitle
        case "stylized": upsert into #sdk-stylized-stack by entry.id
    remove DOM nodes whose IDs are absent from new payload

User clicks a stylized-window button (v1 only buttons are decorative chrome):
  onclick → dauntlessEvent("sdk-mirror/click:stylized-7/close")
  → OnBeforeBrowse intercepts dauntless://event/…
  → PanelRegistry routes to SDKMirrorPanel.dispatch_event("click:stylized-7/close")
  → Python logs: "sdk-mirror click stylized-7/close (no dispatch — v1)"
  → no SDK invocation
```

### Snapshot semantics

The panel emits the *full* tree every time anything changes — no mutation deltas. JS diffs visible DOM against the new payload (matches `MissionPicker` pattern). Cost: payload grows linearly with active SDK windows; harness missions rarely exceed ~5 active windows, so a few hundred bytes per change. Idle missions emit one payload total.

### ID scheme

Each shim instance gets `_id = f"{type_prefix}-{counter}"` from a per-type class-level counter. IDs are stable for the lifetime of the window and round-trip through click events. Counters reset when `_TopWindow.reset_for_tests()` fires (which already runs between harness missions).

`_SubtitleWindow` is the exception: there is exactly one subtitle window per TopWindow, so its `_id` is the constant `"subtitle-0"`. The reset hook drops the old instance and re-seeds `_main_windows[MWT_SUBTITLE]` with a fresh `_SubtitleWindow()` rather than incrementing a counter.

### TGCreditAction expiry

`SDKMirrorPanel.render_payload()` passes `time.monotonic()` to `SubtitleWindow._snapshot(now)`. Expired entries are filtered out before the payload is built. No timer threads; expiry is a pull, not a push. Trade-off: a payload won't emit *purely* because of expiry — it emits because something else changed. In practice the renderer ticks every frame so visible text disappears within one frame of expiry. If the tick stops (game paused), text persists until the next tick — acceptable.

### Subtitle text composition

Multiple `TGCreditAction.Play()` against the same subtitle window stack: later actions are appended below earlier ones, separated by `<br>` in the DOM. Matches BC's cinematic dialogue stacking. Will be refined by the future `SubtitleAction` spec.

---

## Component contracts

### `_SubtitleWindow`

```python
class _SubtitleWindow:
    SM_BRIDGE, SM_TACTICAL, SM_FELIX, SM_NONFELIX = 0, 1, 2, 3
    SM_MAP, SM_CINEMATIC, SM_END_CINEMATIC, SM_SPECIAL_FELIX = 4, 5, 6, 7

    def __init__(self):
        self._id = "subtitle-0"  # singleton
        self._visible = False
        self._mode = self.SM_TACTICAL
        self._active_texts: list[tuple[str, float]] = []  # (text, expires_at)

    def SetOn(self):  self._visible = True
    def SetOff(self): self._visible = False
    def SetVisible(self): self._visible = True   # SDK alias used in MissionLib.TextBanner
    def IsOn(self) -> bool: return self._visible
    def SetPositionForMode(self, mode: int): self._mode = int(mode)

    def _add_text(self, text: str, duration_s: float) -> None:
        self._active_texts.append((text, time.monotonic() + duration_s))

    def _snapshot(self, now: float) -> dict | None:
        self._active_texts = [(t, e) for (t, e) in self._active_texts if e > now]
        if not self._visible and not self._active_texts:
            return None
        return {
            "type": "subtitle",
            "id": self._id,
            "visible": self._visible or bool(self._active_texts),
            "mode": self._mode,
            "lines": [t for (t, _) in self._active_texts],
        }
```

### `_STStylizedWindow`

```python
class _STStylizedWindow:
    _counter = 0

    def __init__(self, title: str = ""):
        type(self)._counter += 1
        self._id = f"stylized-{self._counter}"
        self._title = _to_str(title)
        self._visible = True
        self._children: list = []

    def AddChild(self, child, x=0.0, y=0.0, *_): self._children.append(child)
    def SetVisible(self):    self._visible = True
    def SetNotVisible(self): self._visible = False
    def GetObjID(self) -> int: return id(self)  # SDK identity hook (profile shows hit)

    def _snapshot(self) -> dict:
        return {
            "type": "stylized",
            "id": self._id,
            "visible": self._visible,
            "title": self._title,
        }
```

Children are recorded so `GetNumChildren` works, but v1 does not recurse into them for rendering — the title is the only content. Recursion is a follow-up when `STText` / `TGIcon` / `TGParagraph_CreateW` ship.

### `_TGCreditAction`

```python
class _TGCreditAction:
    def __init__(self, text, host_window, fX=0.0, fY=0.0,
                 duration=3.0, fade_in=0.25, fade_out=0.5,
                 size=16, justify_x=0, justify_y=0):
        self._text = _to_str(text)
        self._host = host_window
        self._duration = float(duration)
        self._played = False

    def Play(self) -> None:
        if self._played: return
        self._played = True
        if hasattr(self._host, "_add_text"):
            self._host._add_text(self._text, self._duration)
```

`fX`, `fY`, `fade_in`, `fade_out`, `size`, `justify_x`, `justify_y` are accepted and ignored. The dauntless subtitle slot has its own layout. Visual departure intentional.

`_to_str` is a small helper (likely already needed elsewhere) that handles `str`, BC's wide-string objects, and `DBString` objects that come out of database lookups. Implementation lives in `engine/appc/sdk_ui/__init__.py`.

### `SDKMirrorPanel`

```python
class SDKMirrorPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = None

    @property
    def name(self) -> str: return "sdk-mirror"

    def render_payload(self) -> Optional[str]:
        now = time.monotonic()
        entries = []
        tw = top_window.TopWindow_GetTopWindow()

        sub = tw._main_windows.get(top_window.MWT_SUBTITLE)
        if sub is not None:
            snap = sub._snapshot(now)
            if snap is not None: entries.append(snap)

        for (child, _x, _y) in tw._children:
            if hasattr(child, "_snapshot"):
                entries.append(child._snapshot())
            else:
                self._log_unrecognised_once(type(child).__name__)
            # Children without _snapshot are logged once per unique type
            # then skipped; follow-up primitive specs add the method and
            # slot together.

        payload = json.dumps({"entries": entries})
        if payload == self._last_pushed: return None
        self._last_pushed = payload
        return "setSdkMirror(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("click:"):
            _logger.info("sdk-mirror click %s (no dispatch — v1)", action[6:])
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None

    def _log_unrecognised_once(self, type_name: str) -> None:
        if type_name in self._logged_unrecognised: return
        self._logged_unrecognised.add(type_name)
        _logger.info("sdk-mirror: skipping unrecognised child type %s", type_name)
```

`__init__` also sets `self._logged_unrecognised: set[str] = set()`.

### CEF slots (`hello.html`)

```html
<!-- Bottom-anchored subtitle strip; one line per active credit-action text. -->
<div id="sdk-subtitle" class="sdk-mirror" hidden></div>

<!-- Centred modal stack for STStylizedWindow instances. -->
<div id="sdk-stylized-stack" class="sdk-mirror"></div>
```

`sdk_mirror.js` exposes `setSdkMirror({entries})`, routes each entry by `entry.type` into the right slot, upserts DOM by `entry.id`, and removes DOM nodes whose IDs are absent from the new payload.

### TopWindow seeding

```python
# engine/appc/top_window.py — inside _TopWindow.__init__
from engine.appc.sdk_ui.subtitle_window import _SubtitleWindow
self._main_windows[MWT_SUBTITLE] = _SubtitleWindow()
```

Subtitle is the only seeded main window in v1. Other `MWT_*` keys remain unmapped (`FindMainWindow(MWT_CINEMATIC)` etc. continue to return `None`).

### `_STStylizedWindow._counter` reset

`reset_for_tests` in `top_window.py` resets `_STStylizedWindow._counter = 0` so stylized IDs don't accumulate across harness missions. Same hook re-seeds `_main_windows[MWT_SUBTITLE]` with a fresh `_SubtitleWindow()`.

---

## CSS / JS sketch

### `css/sdk_mirror.css`

```css
#sdk-subtitle {
  position: absolute;
  left: 50%;
  bottom: 12vh;
  transform: translateX(-50%);
  max-width: 60vw;
  padding: 12px 20px;
  background: rgba(20, 40, 80, 0.85);
  border: 1px solid #3a6bb8;
  border-radius: 4px;
  color: #e8f0ff;
  font-family: sans-serif;
  font-size: 14px;
  text-align: center;
  z-index: 50;
}

#sdk-stylized-stack {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 16px;
  pointer-events: none;
  z-index: 40;
}

#sdk-stylized-stack .sdk-stylized-window {
  pointer-events: auto;
  min-width: 360px;
  max-width: 60vw;
  background: rgba(10, 20, 40, 0.92);
  border: 1px solid #3a6bb8;
  border-radius: 6px;
}

#sdk-stylized-stack .sdk-stylized-window__header {
  padding: 10px 16px;
  color: #7fa8d8;
  font-size: 11px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  border-bottom: 1px solid #2a4a80;
}
```

### `js/sdk_mirror.js`

```javascript
function setSdkMirror(payload) {
  const entries = payload.entries || [];
  const subtitle = entries.find(e => e.type === "subtitle");
  renderSubtitle(subtitle);
  renderStylizedStack(entries.filter(e => e.type === "stylized"));
}

function renderSubtitle(entry) {
  const el = document.getElementById("sdk-subtitle");
  if (!entry || !entry.visible || entry.lines.length === 0) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  el.innerHTML = entry.lines.map(escapeHtml).join("<br>");
}

function renderStylizedStack(entries) {
  const stack = document.getElementById("sdk-stylized-stack");
  const seen = new Set();
  for (const entry of entries) {
    seen.add(entry.id);
    if (!entry.visible) continue;
    let node = document.getElementById("sdk-stylized-" + entry.id);
    if (!node) {
      node = document.createElement("div");
      node.id = "sdk-stylized-" + entry.id;
      node.className = "sdk-stylized-window";
      node.onclick = () => dauntlessEvent("sdk-mirror/click:" + entry.id);
      stack.appendChild(node);
    }
    node.innerHTML = `<div class="sdk-stylized-window__header">${escapeHtml(entry.title)}</div>`;
  }
  // Prune nodes for IDs no longer in payload, or marked invisible.
  for (const child of [...stack.children]) {
    const id = child.id.replace(/^sdk-stylized-/, "");
    const entry = entries.find(e => e.id === id);
    if (!entry || !entry.visible) stack.removeChild(child);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
```

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Subtitle text reaches the window via a fourth path I haven't traced (e.g. `STText_AppendCharW` directly on a SubtitleWindow child), so v1 ships invisible | Medium | The post-landing `--profile` will show the next missing primitive. Accept the risk that "first visible subtitle" may need a fast follow-up |
| `_TopWindow._children` contains entries other than `_STStylizedWindow` once SDK starts `AddChild`-ing other types; panel's `hasattr(child, "_snapshot")` skips them silently | Medium | Panel logs once per unique unrecognised type, so the next missing primitive is visible in stderr without rebuilding the panel |
| Snapshot payload churns if a mission animates a stylized window each tick | Low | Snapshot only re-emits on JSON change. If a future primitive includes a per-tick counter that legitimately changes, that primitive's spec will need to negotiate a stable representation |
| `time.monotonic()` expiry diverges from game time when `--game-time-scale` is non-1 | Low | Documented. Original BC cinematic banners are also wall-clock. If a future use-case needs game-time expiry, `SubtitleAction` will introduce a separate timing source |
| `STStylizedWindow._counter` is a class attribute — survives test fixture teardown that doesn't import `top_window.reset_for_tests()` | Low | Same `reset_for_tests` chain is already called from `host_loop.reset_sdk_globals` and the integration test setup helper. Unit tests reset the counter explicitly in a fixture |
| Click events fire `dauntlessEvent` even though v1 doesn't dispatch them — visible no-op confuses playtesters | Low | Stylized windows in v1 have no visible click affordances (no buttons rendered, no cursor change). The whole-window click handler exists only to prove the IPC channel; document in playtest notes |

---

## Verification plan

| Layer | What | How |
|---|---|---|
| Unit — `test_sdk_ui_subtitle_window.py` | State machine | `SetOn/SetOff` flip `_visible`; `SetPositionForMode` stores int mode; `_add_text` appends with correct expiry; `_snapshot` returns `None` when hidden + empty, dict when visible or text active; expired entries pruned |
| Unit — `test_sdk_ui_stylized_window.py` | Construction + visibility | `STStylizedWindow_CreateW("Title")` returns instance with stable `_id`, monotonic counter; `SetVisible/SetNotVisible` flip flag; `AddChild` records but doesn't render; `GetObjID` returns int |
| Unit — `test_sdk_ui_credit_action.py` | Text driver | `Create(...).Play()` calls host `_add_text(text, duration)`; second `Play()` is no-op; wide-string and `DBString` inputs unwrap via `_to_str` |
| Unit — `test_sdk_ui_mirror_panel.py` | Snapshot logic | Empty children + hidden subtitle → `render_payload()` returns `None`; add a stylized window → returns `setSdkMirror(...)` once, then `None` until state changes; child without `_snapshot` skipped silently; `invalidate()` forces re-emit |
| Integration — `test_sdk_mirror_round_trip.py` | End-to-end | Construct TopWindow + mirror panel; call `TGCreditAction_Create(...).Play()` against the singleton subtitle window; tick once; assert payload contains the text; advance `time.monotonic` past duration via monkeypatch; tick; assert text absent |
| Harness profile | Stub removal | `uv run python tools/gameloop_harness.py --profile` after change. Confirm `STStylizedWindow_CreateW`, `SubtitleWindow_Cast`, `TGCreditAction_Create` (and their `.Create()/.Play()/.AddChild` sub-rows) drop out of the top 50 |
| Manual playtest | Visible loop | `cmake --build build -j` then `./build/dauntless`. Load a mission with an early `TextBanner` / `SubtitledLine` (the tutorial M1Basic fires text within ~15s of mission start). Confirm a dauntless-style strip appears at the bottom with the mission text. Load a mission that opens an STStylizedWindow on init (Maelstrom E1M1 opens one). Confirm a centred dauntless panel appears with the title |

---

## Follow-up specs (out of scope for this one, in expected order)

1. **`SubtitleAction` / `CharacterAction` dialogue stream** — proper streamed dialogue with `AddCompletedEvent` callbacks. Will refine subtitle text composition rules.
2. **SDK→Python click dispatch** — wire `_handler_registrations` through `g_kEventManager`, design `(object_id ↔ window-id)` round-trip, map DOM events to `ET_*` event types.
3. **`SortedRegionMenu_Cast`** — the warp-targets menu. 31 missions, the highest-leverage interactive primitive. Needs full click round-trip from #2 first.
4. **`STText_Create` / `TGIcon_Create` / `TGParagraph_CreateW` / `TGPane_Create`** — content children of stylized windows. When these land, the mirror panel starts recursing into stylized window `_children`.
5. **`MapWindow` / `CinematicWindow`** — additional main windows; each gets its own `MWT_*` seed and slot.
6. **Font fidelity** — if and when we decide BC typography matters. Likely never.
