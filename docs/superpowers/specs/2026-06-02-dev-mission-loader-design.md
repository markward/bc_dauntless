# Dev Mission Loader — Design

**Status:** Draft, pre-implementation.
**Sub-project:** A developer-only mission-loading UI surfaced through the
`--developer` pause-menu, allowing in-process swaps to any discoverable
SDK mission via a CEF-rendered modal picker.

## Why this scope

The renderer host currently boots into a single hard-coded mission
(`SHIP_GATE_MISSION`) and offers no way to switch. A prior centred-modal
mission picker existed in [engine/mission_picker.py](engine/mission_picker.py)
(deleted at `912f22d` because it sat on top of the now-removed RmlUi
component layer; functionally the user considered it "great"). The
underlying `engine/missions/` discovery package and the
`HostController.swap_mission(...)` boundary in
[engine/host_loop.py:1701](engine/host_loop.py#L1701) survived the
deletion, leaving the swap machinery operational but unreachable.

The current dev pause-menu section also auto-lists registered dev
keybindings (`— DEVELOPER —` header + `Shield-hit debug (F10)` row).
Those rows are informational only — clicking them does nothing — and
get in the way of real actionable dev entries. The user wants them
gone; F10 should remain a working keypress without occupying menu space.

## Goals

1. Re-introduce a mission picker as a CEF-rendered modal, opened from a
   new "Load Mission…" entry in the dev pause-menu section.
2. Decouple dev keybinding registration from dev pause-menu entry
   registration. Keybindings continue to fire on key press but no
   longer auto-populate the pause menu.
3. Reuse the surviving `engine/missions/` package
   (`MissionRegistry`, `discover`, `tgl_reader`, `name_resolver`) and
   the existing `HostController.swap_mission(mission_name)` swap path.
4. Match the prior picker's structural decisions: two-deep tree
   (family → episode → mission), TGL-derived display names with
   dir-name fallback, the "skip episode level when family has one
   episode named `Episode` or `.`" flattening heuristic, Cancel + ESC
   dismiss.
5. Modal owns its modality relative to the pause menu: opening the
   picker hides the pause menu; closing the picker via Cancel/ESC
   re-opens it; picking a mission closes both and resumes play on the
   new mission.
6. Lazy discovery: walk `sdk/Build/scripts/` only on the first picker
   open. Cache the registry thereafter (game-session-lifetime).

## Non-goals

- Mission preview text, screenshots, difficulty selection — deferred.
- Persistent state (last-picked mission, expanded-section memory).
- A non-dev surface for the picker. The mission loader is strictly
  developer-only; CSS `.dev-only` plus the `dev_mode.is_enabled()`
  registration gate keep it off the normal play surface.
- QuickBattle as a mission target.
- Localising "Load Mission…" / "Cancel" labels.
- Backdrop dim, click-out-to-cancel, input gating outside the picker.
  The pause menu being hidden plus ESC/Cancel are sufficient.
- A keyboard-driven shortcut to open the picker. Pause-menu click is
  the only entry path.

## Architecture

Three changes stacked on the existing `developer-flag` branch:

```
engine/dev_mode.py                 (modified)
    new: register_dev_pause_menu_entry / dev_pause_menu_entries
    unchanged: keybinding registry, is_enabled, dev_only, dispatch_dev_key
    unchanged: keybinding_descriptions  (kept for non-pause-menu introspection)

engine/ui/pause_menu.py            (modified)
    default_pause_menu reads dev_pause_menu_entries() instead of
    keybinding_descriptions(); the auto-listed keybinding rows and the
    "— DEVELOPER —" separator row are removed. Dev rows use unprefixed
    action IDs (e.g. "load-mission") so they fall through PanelRegistry
    to the pause menu's legacy dispatch_event handler — consistent with
    the existing "exit" / "cancel" rows. Slashed action IDs would
    misroute via the panel prefix machinery.

engine/dev_mission_picker.py       (new)
    MissionPicker(Panel) — subclass of engine.ui.panel.Panel. Builds
    tree payload from MissionRegistry. render_payload() returns
    setMissionPicker JS when visibility toggles. dispatch_event(action)
    handles "pick:<module>" and "cancel" routed by PanelRegistry.

engine/host_loop.py                (modified)
    On startup, if dev_mode.is_enabled():
      - cached MissionRegistry getter (closure walks SDK on first call)
      - picker = MissionPicker(registry_getter, on_pick=...)
              # on_pick closure: controller.swap_mission(module); pause.close()
      - panel_registry.register(picker)         # PanelRegistry pump + routing
      - register_dev_pause_menu_entry("Load Mission…", picker.open)
    Existing _apply_pause_menu_side_effects gains picker arg and ANDs
    `not picker.is_open()` into the pause-visibility predicate.
    ESC dispatch in the input switch gets picker-priority:
      if picker.is_open(): picker.handle_key_esc()
      else: (existing pause toggle)

native/assets/ui-cef/hello.html    (modified)
    new <section id="mission-picker" class="dev-only"> with title bar,
    scrollable body, footer Cancel button. Default display: none via
    the existing .dev-only rule + an inline display:none toggled by JS.

native/assets/ui-cef/js/mission_picker.js  (new)
    setMissionPicker({tree, visible}) — re-emits the tree DOM and
    toggles visibility. Mission row onclick fires
    dauntlessEvent('mission-picker/pick:<module>');
    Cancel fires dauntlessEvent('mission-picker/cancel');
    family/episode rows toggle .collapsed on click — purely local.

native/assets/ui-cef/css/hello.css (modified)
    Styling for #mission-picker chrome consistent with .pause-panel.
```

### MissionPicker class shape

`MissionPicker` subclasses `engine.ui.panel.Panel`, fitting the
existing per-tick render pump (`PanelRegistry.render_all()`) and the
slash-prefixed event router (`PanelRegistry.dispatch(...)`).

- `__init__(registry_getter: Callable[[], MissionRegistry], on_pick: Callable[[str], None])`.
  Constructor does **not** call `registry_getter()` — lazy until `open()`.
- `name = "mission-picker"`. Slash-prefixed events
  (`mission-picker/cancel`, `mission-picker/pick:<module>`) route here.
- `open()` flips internal `_visible=True` and lazily resolves the
  registry on first call. Idempotent.
- `close()` flips `_visible=False`. Idempotent.
- `is_open()` returns `_visible`. Read by
  `_apply_pause_menu_side_effects` to gate pause-menu visibility.
- `render_payload() -> Optional[str]` emits
  `setMissionPicker({tree, visible:true})` the first tick after
  opening and `setMissionPicker({visible:false})` the first tick
  after closing. Snapshot-tuple equality check (matches the
  `PauseMenuModel.render_payload` idempotency contract) yields `None`
  between transitions. Tree is built once on first emit and reused.
- `dispatch_event(action: str) -> bool` handles `"cancel"` (calls
  `close()`) and `"pick:<module>"` (calls `on_pick(module)`,
  then `close()`). Returns True iff matched.
- `handle_key_esc()` calls `close()` when `_visible`, else no-op.
  Polled from the host loop's input switch, not from a CEF callback.

No defer queue: CEF console-message dispatch is already off the JS
execution stack, so mutating `_visible` synchronously from
`dispatch_event` is safe.

### Pause-menu / picker arbitration

The picker does NOT call back into the pause controller. Instead,
the host loop's existing `_apply_pause_menu_side_effects(pause, view_mode, _h)`
gains a fourth argument `picker` and ANDs `not picker.is_open()` into
the visibility predicate:

```python
pause_should_show = pause.is_open and not picker.is_open()
```

Consequences:
- `picker.open()` → next tick pause menu hides (the user clicked
  "Load Mission…" so `pause.is_open` is still True, but the new
  conjunct is False).
- `picker.close()` from Cancel/ESC → `pause.is_open` is still True,
  the conjunct flips back; pause menu reappears next tick.
- The host loop's `on_pick(module)` closure calls
  `controller.swap_mission(module)` **then** `pause.close()`. Both
  flags drop; neither overlay shows; game resumes on the new mission.

ESC in the host loop input switch gets a picker-priority clause:
when `picker.is_open()` is True, ESC calls `picker.handle_key_esc()`;
otherwise ESC toggles the pause controller (current behaviour).

### Data flow

```
pause-menu row "Load Mission…" click (dauntlessEvent('load-mission'))
        │
        ▼ PanelRegistry sees no slash → legacy handler → pause_menu.dispatch_event('load-mission') → picker.open()
picker.open()  ── _visible=True; registry_getter() on first call only

host_loop next tick:
    _apply_pause_menu_side_effects(pause, view_mode, _h, picker)
        → pause_should_show = True and not True = False → hide pause menu
    panel_registry.render_all()
        → picker.render_payload() emits setMissionPicker({tree, visible:true})

CEF user clicks mission row
        │
        ▼ dauntlessEvent('mission-picker/pick:Custom.Foo.Bar')
            → console-message → C++ → event handler → registry.dispatch(...)
picker.dispatch_event("pick:Custom.Foo.Bar")
        ├── on_pick("Custom.Foo.Bar")
        │       ├── controller.swap_mission("Custom.Foo.Bar")
        │       └── pause.close()                    (host-loop closure)
        └── self.close()                              ── _visible=False

next tick:
    _apply_pause_menu_side_effects → both flags False → both hidden
    picker.render_payload() emits setMissionPicker({visible:false})
    Game resumes on the new mission.

User presses Cancel button or ESC
        │
        ▼ dauntlessEvent('mission-picker/cancel')   (Cancel button)
            OR host_loop input switch calls picker.handle_key_esc()  (ESC)
picker.close()
        ── _visible=False; pause.is_open is still True

next tick:
    _apply_pause_menu_side_effects → pause_should_show = True → pause menu reappears
    picker.render_payload() emits setMissionPicker({visible:false})
```

## Components

| Component | Lives in | Responsibility |
|---|---|---|
| Dev pause-menu registry | `engine/dev_mode.py` | `register_dev_pause_menu_entry(label, handler)`, `dev_pause_menu_entries() -> list[(str, Callable)]`. Replaces keybinding enumeration as the source of pause-menu rows. |
| Pause-menu construction | `engine/ui/pause_menu.py` | `default_pause_menu` reads the new registry. The hard-coded "— DEVELOPER —" and "Shield-hit debug (F10)" rows are removed. |
| Mission picker (Python) | `engine/dev_mission_picker.py` | `MissionPicker(Panel)` — subclass of `engine.ui.panel.Panel`. Ctor `MissionPicker(registry_getter, on_pick)`. `open()`, `close()`, `is_open()`, `dispatch_event(action)`, `handle_key_esc()`. Owns the JS payload format; emitted via the per-tick `render_payload()` pump (no direct `cef_execute_javascript`). No pause-menu callback — host-loop side-effects function ANDs `not picker.is_open()` into pause visibility. |
| Mission picker (HTML) | `native/assets/ui-cef/hello.html` | Static `<section id="mission-picker" class="dev-only">` carrying title + scrollable body container + footer Cancel button. |
| Mission picker (JS) | `native/assets/ui-cef/js/mission_picker.js` | `setMissionPicker({tree, visible})` renderer; local expand/collapse; event emission via `dauntlessEvent`. |
| Mission picker (CSS) | `native/assets/ui-cef/css/hello.css` | Modal sizing/positioning (centred, ~42vw × 72vh), pane chrome consistent with `.pause-panel`, row hover state, indentation for tree levels. |
| Host-loop wiring | `engine/host_loop.py` | One-shot registration at startup (gated by `dev_mode.is_enabled()`): cached registry-getter closure, `MissionPicker` construction with an `on_pick` closure that calls `controller.swap_mission` then `pause.close`, `panel_registry.register(picker)`, `register_dev_pause_menu_entry("Load Mission…", picker.open)`. `_apply_pause_menu_side_effects` extended to take `picker`. ESC dispatch in the input switch gets picker-priority. |

### Tree payload shape (Python → JS)

```python
{
    "tree": [
        {
            "kind": "family",
            "label": "Tutorial",
            "children": [
                {
                    "kind": "episode",
                    "label": "Episode 1",
                    "children": [
                        {"kind": "mission",
                         "label": "M1Basic",
                         "module": "Custom.Tutorial.Episode.M1Basic.M1Basic"},
                        ...
                    ],
                },
                ...
            ],
        },
        # "skip episode level" flattening: family.children contains
        # mission rows directly (no episode wrapper) when the family had
        # exactly one episode named "Episode" or ".".
        {
            "kind": "family",
            "label": "Multiplayer",
            "children": [
                {"kind": "mission", "label": "...", "module": "..."},
            ],
        },
    ],
    "visible": True,
}
```

JS renders by kind: `family` and `episode` become collapsible rows
(start collapsed); `mission` becomes an actionable button.

### Modality transitions

```
state          ESC behaviour          action that exits
─────          ─────────────          ─────────────────
gameplay       opens pause menu       (handled by existing pause controller)
pause-menu     closes pause menu      click row OR ESC
picker         closes picker,         Cancel button OR ESC OR click mission
               re-opens pause menu    (mission click also closes pause menu)
```

The picker carries no pause-menu callback. Pause-menu visibility is
computed each tick as `pause.is_open and not picker.is_open()` inside
the host loop's `_apply_pause_menu_side_effects`; the pause menu
naturally reappears when the picker closes because `pause.is_open` is
never modified by picker actions. The host loop's `on_pick` closure
calls `pause.close()` alongside `controller.swap_mission(module)` so
that both pause and picker drop on a successful pick.

## Error handling

- **Discovery failure** (missing `sdk/Build/scripts/`, TGL parse error
  on a single file): `engine.missions` already degrades gracefully —
  `name_resolver` falls back to the directory name. A whole-tree
  failure (no `sdk/Build/scripts/` directory at all) yields an empty
  registry; the picker shows an empty body. The user sees no missions
  rather than a crash.
- **swap_mission raises:** Picker has already closed and called the
  callback; the exception propagates through the host loop's existing
  error path. No new error handling is required; this matches today's
  behaviour for hard-coded mission swaps.
- **Stale `.so` / CEF not initialised:** `register_dev_pause_menu_entry`
  is a no-op-safe Python list append. The host-loop wiring is gated by
  `dev_mode.is_enabled()`; CEF JS pushes are inside the
  `_h is not None` guard already present for the pause menu.
- **Dev mode off:** No registration happens. The "Load Mission…" entry
  never appears. The HTML section stays hidden by `.dev-only` CSS.

## Testing

- **Unit (`tests/unit/test_dev_mode.py`)**: extend with three tests for
  the new registry: `register_dev_pause_menu_entry` appends; reading
  via `dev_pause_menu_entries` returns the pairs in registration order;
  the registry is cleared by the existing `reset_dev_mode` fixture
  (extend the fixture to cover the new list).
- **Unit (`tests/unit/test_pause_menu.py` or extend existing)**:
  - When `dev_mode.is_enabled()` is False: `default_pause_menu` items
    are exactly `Exit Program`, `Cancel`. No legacy `— DEVELOPER —` /
    `Shield-hit debug` rows.
  - When `dev_mode.is_enabled()` is True and the registry contains
    `("Foo", handler)`: items are `Exit Program`, `Cancel`, `Foo`.
- **Unit (`tests/unit/test_dev_mission_picker.py`, new)**:
  - Tree payload shape: synthetic `MissionRegistry` → expected
    payload, covering the skip-episode-level flattening case
    (family with one episode named `Episode` or `.`).
  - `dispatch_event("pick:Foo.Bar")` invokes `on_pick("Foo.Bar")`
    then leaves the picker closed (`is_open()` returns False);
    `dispatch_event("cancel")` leaves the picker closed without
    invoking `on_pick`; `handle_key_esc()` closes when open and is
    a no-op when closed.
  - `render_payload()` returns `setMissionPicker({tree, visible:true})`
    JS the first tick after `open()` and
    `setMissionPicker({visible:false})` the first tick after `close()`.
    Returns `None` on subsequent ticks while state is unchanged.
  - `open()` is idempotent: a second `open()` while already open
    does not re-walk the registry getter (call-count assertion on
    a Mock getter).
  - Lazy walk: constructing the `MissionPicker` does not call the
    registry getter; only the first `open()` does.
  - Tests construct `MissionPicker` directly with a Mock
    `on_pick` and a synthetic registry-getter — no CEF, no
    `_dauntless_host`, no host loop needed.
- **Integration (manual)**: launch `./build/dauntless --developer`,
  ESC → click "Load Mission…", confirm the tree renders, click a
  mission, confirm the SDK mission swaps and the game resumes. Cancel
  the picker via ESC and via the Cancel button. Launch without
  `--developer`, confirm the entry is absent.

## Alternatives considered

- **Cascading drill-down inside the pause menu** (rewrite the row list
  on each level): cheapest, no new HTML/JS, but visually awkward for a
  ~3-level navigation and forecloses future preview text. Rejected for
  parity with the prior centred-modal design that the user remembers
  liking.
- **Inline expand-in-place inside the pause menu** (hybrid): adds
  collapsible nested children to pause rows. Awkward CSS to indent
  cleanly; pause rows aren't designed for it. Rejected.
- **Eager discovery at startup**: avoids the small first-open delay
  but adds ~1s to every startup, including non-dev runs (if we
  forgot to gate it). Rejected for laziness.
- **Keep auto-listing keybindings in the pause menu, add picker as a
  third row beside them**: doesn't address the "test options that
  don't do anything" complaint. Rejected.

## Deferred work

- Mission preview pane (text + thumbnail). Out of scope; the tree-only
  view is enough for "jump to mission" usage.
- Remembering expansion state across opens.
- A keyboard shortcut (`F11`?) to open the picker without going through
  the pause menu. Deferred until usage shows the pause-menu path is
  too slow.
- Migrating the F10 shield-debug binding to an explicit dev pause-menu
  entry once we have actionable handlers — for now it remains a
  keypress-only dev tool.
- A `dev_mode.deregister_*` API for tests. The `reset_dev_mode`
  fixture is sufficient until something needs runtime removal.
