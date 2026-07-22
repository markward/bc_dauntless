# CharacterClass reimplementation — SP4: StatusMap + PositionZoomTable + MenuState

> **Sub-project 4 of 4** of the faithful `CharacterClass` reimplementation (SP1 state model,
> SP2 AnimationQueue, SP3 SpeakQueue+PhonemeMap+jaw — all merged to local `main`). Driven by the
> tier-0 `docs/engine/characterclass-reference.md` (§4.4 position-zoom, §4.6 status, §4.12 context
> menu; struct offsets `+0xd4`/`+0xd8` status, `+0xa8`/`+0xac` position-zoom, `+0x14c` menu-state).
> Architecture is unchanged from SP2/SP3: **own + consolidate** — `CharacterClass` owns small
> sub-objects mirroring BC's struct; existing live-verified infra stays as the execution backends.

## 1. Problem & scope

SP1 left three owner slots stubbed:

- **`SetStatus`** collapses BC's status **key 0..5** into ONE `_status["text"]` slot (SP1 shortcut).
  The SDK uses distinct keys (`BridgeHandlers.py:1397/1404/1417` → `SetStatus(str, 1/2/3)`).
  `_status["text"]` has **no reader** anywhere in `engine/` — it is a write-only sink today.
- **`AddPositionZoom`/`GetPositionZoom`/`GetPositionLookAtName`** fall through to the `__getattr__`
  data-bag (single-slot, last-write-wins — broken for a per-name table). No reader anywhere.
- **`_menu`** is an informal handle in the `_data` dict; there is no owned `MenuState`.

**Key evidence finding (drives the scope):** both the status *render* and the position-zoom *read*
are **native BC subsystems with zero Python consumers**:

- The `*UpdateToolTip(pCharacter)` handlers (which write status keys 1-3) are **never called from
  Python** — BC dispatches them natively on hover. The status box itself is a native widget built
  lazily by `Bridge.BridgeMenus.CreateCharacterTooltipBox(self)`. Dauntless has never built either.
- `GetPositionZoom`/`GetPositionLookAtName` have **no Python caller in the entire SDK** (only the
  `App.py` binding) — the bridge camera native-reads them to zoom to an officer's station on focus.

So SP4 is not "wire existing data" — it is "build the faithful data model **and** reconstruct the
two absent native surfaces." Mark chose the full-visibility path for both (2026-07-22):

- **StatusMap → Full tooltip box:** faithful keyed model + a CEF crew tooltip box + a Python
  reimplementation of the native `UpdateToolTip` dispatch.
- **PositionZoomTable → Table + camera zoom on MenuUp:** faithful table + wire the bridge camera to
  zoom to an officer's station when their menu opens.
- **MenuState:** pure consolidation of `_menu` into an owned sub-object.

### Out of scope (YAGNI)
- `MorphBody` / `GetHeadHeight` (0 SDK call sites — already excluded in the parent memory).
- Pixel-exact LCARS layout of the tooltip box; literal BC memory layout.
- Rebuilding `ZoomCameraObjectClass`'s stubbed zoom geometry — we drive the existing `_BridgeCamera`.

## 2. Architecture

Three new pure-Python sub-objects, each in its own file (mirrors SP3's `speak_queue.py`/`phoneme_map.py`):

| Sub-object | File | BC offset | Backend / render seam ("the hands") |
|---|---|---|---|
| `StatusMap` | `engine/appc/character_status_map.py` | `+0xd4` m_pStatusUI, `+0xd8` hash 0..5 | new CEF `CharacterTooltipPanel` + host-loop `UpdateToolTip` dispatcher |
| `PositionZoomTable` | `engine/appc/character_position_zoom.py` | `+0xa8/+0xac` (0x18-byte records) | `_BridgeCamera` zoom machine + `bridge_camera_watch` framing |
| `MenuState` | `engine/appc/character_menu_state.py` | `+0x14c` (id + `+0x28` ready-flag) | existing `crew_menu_panel` (unchanged) |

`CharacterClass` constructs all three in `__init__` (replacing the `_position_zoom = None` /
`_menu_state = None` slots and the `_status` dict), and its public methods delegate to them. The
class stays renderer-free; visibility lives in the host loop / CEF, reached through seams exactly as
`bridge_character_anim` and `crew_menu_panel` are today.

## 3. Workstream 1 — StatusMap + tooltip box

### 3.1 Data model (`StatusMap`, pure — tier-0 §4.6)

State: `dict[int, value]` for keys `0..5`, plus a `dirty` flag for the render seam.

- `set_status(value, key=0)` — **`key > 5` returns (no-op)** (BC `0x00669D10`: `key>5 → return`).
  Store `value` at `key`; mark dirty. `key` defaults to `0` (the SDK's 1-arg `SetStatus("Waiting")`).
- `get_status(key)` → the stored value, else `0` (BC `0x00669CC0`: hash miss → `0`).
- `clear_status(key)` — remove that key's row; mark dirty (BC `0x00669F70`: keys `0..5`,
  unlink+destroy+refresh). No-arg / out-of-range clear is a no-op.
- `rows()` → the non-empty keys in ascending key order, as `[(key, value)]`, for the renderer.

`CharacterClass.SetStatus/GetStatus/ClearStatus` become thin delegators. `GetStatusText` (SP1's
interim reader) is removed; nothing else reads it. Values are BC `TGString`/`str` display strings —
stored opaquely and `str()`-rendered.

### 3.2 Current-tooltip-owner (BC statics)

BC tracks ONE visible tooltip via `CharacterClass_GetCurrentToolTipOwner()` /
`SetCurrentToolTipOwner(pChar)`. SP4 adds these as module-level statics in `characters.py` (single
global owner slot). `DropCharacterToolTips()` (already referenced by `DropMenusTurnBack`) hides the
owner's box and clears the slot.

**Owner selection (the one deliberate deviation, Mark-approved):** BC shows the tooltip on **hover**
(native pick), independent of the menu. Dauntless already computes the aimed officer each frame via
`engine/ui/bridge_officer_picking.pick(h, r, bridge_camera)`. SP4 sets the tooltip owner to the
**aimed officer** (hover) when the bridge view is up; the open-menu officer also counts as focused.
This unifies BC's separate hover-vs-menu triggers onto Dauntless's single "focused officer" signal.
When the aimed officer changes (or focus is lost), the owner updates and the box show/hides.

### 3.3 CEF tooltip box (`CharacterTooltipPanel`)

A `Panel` subclass (like `CrewMenuPanel`), rendering into a new host element, mirroring
`Bridge.BridgeMenus.CreateCharacterTooltipBox`:

- **Title** = character display name (`CharacterStatus.tgl` lookup, key = `GetCharacterName()`;
  headless/miss falls back to the raw name).
- **Body** = the StatusMap's non-empty rows `0..5`, stacked in key order (one text line each).
- **Visibility** = driven by the current-tooltip-owner: renders `{visible:false}` when this panel's
  character is not the owner or has no rows; top-centre of the bridge view (BC attaches the box to
  the bridge window at `(width - TOOL_TIP_WIDTH)/2, 0.05`).

**Visual language (Mark, 2026-07-22 — "in line with the rest of the UI even if not polished"):**
reuse the shared **`.bc-panel`** header/body chrome (salmon `--bc-*` tokens in `global.css`), the
same chrome the crew menus use (`crew_menus.css`) — the tooltip is the same officer-focus context.
New CSS file `native/assets/ui-cef/css/character_tooltip.css` styles only layout (top-centre
placement, stacked rows); all color/typography inherits from `.bc-panel`. No new palette.

### 3.4 UpdateToolTip dispatcher (reconstruct the native dispatch)

BC natively calls `<Name>UpdateToolTip(pCharacter)` on a cadence while a tooltip is up; those SDK
functions (`BridgeHandlers.HelmUpdateToolTip` writing keys 1-3, `XOUpdateToolTip` key 1, etc.) call
`pChar.SetStatus(str, key)`. SP4 adds a **host-loop tick** that, for the **current tooltip owner
only**, resolves and calls its `BridgeHandlers.<Name>UpdateToolTip` on a throttle (e.g. a few Hz).
This runs the **real SDK handlers** — not a reimplementation of their text.

- **Character → handler map:** by station name, exactly as BC's native registry
  (`Helm→HelmUpdateToolTip`, `Tactical→TacticalUpdateToolTip`, `XO→XOUpdateToolTip`,
  `Science→ScienceUpdateToolTip`, `Engineer→EngineerUpdateToolTip`, plus Picard/Data/Saalek/Korbus).
  Resolved via `getattr(BridgeHandlers, name + "UpdateToolTip", None)`.
- Characters with no `*UpdateToolTip` show only their **key-0** status (the direct
  `SetStatus("Waiting"/"Attacking"/…)` calls from the `*CharacterHandlers`/`*MenuHandlers`).
- **Stub-list note:** if the dispatcher needs `BridgeHandlers` (and its `MissionLib`/localization
  deps) importable at runtime, verify against the **twin** SDK stub lists — `tools/mission_harness.py`
  AND `tests/conftest.py` — and never unstub a whole module to reach one function.

### 3.5 Status key semantics (evidence, for the tests)

Keys are per-station stacked slots, not global meanings:

| Key | Writer(s) | Meaning |
|---|---|---|
| 0 | `*CharacterHandlers` init, Tactical/Helm menu handlers | general status: `Waiting`/`Attacking`/`Disabling`/`Defending`/`Intercepting` |
| 1 | `HelmUpdateToolTip` / `XOUpdateToolTip` | Helm `"{imp} : {vel} kph"` **or** XO `"Red/Yellow/Green Alert"` |
| 2 | `HelmUpdateToolTip` | `"Current Location : <set>"` |
| 3 | `HelmUpdateToolTip` (or `ClearStatus(3)`) | `"Destination : <wp>"` |
| 4–5 | unused in shipped SDK | supported by the widget (0..5) |

## 4. Workstream 2 — PositionZoomTable + camera zoom on MenuUp

### 4.1 Data model (`PositionZoomTable`, pure — tier-0 §4.4)

Ordered list of records `(name, value: float, look_at: str|None)`.

- `add_position_zoom(name, value, zoom_name="")` — **append only if `name` not already present**
  (BC `0x0066C530`: dedupe via `GetPositionZoom == sentinel`); store `(name, float(value), zoom_name
  or None)`.
- `get_position_zoom(name)` — linear search → `value`, else the **default sentinel**.
- `get_position_look_at_name(name)` — linear search → `look_at` or `None`.

**Sentinel:** BC returns `*0x00888EB4` (a float const) on miss. SP4 uses a named module constant
`POSITION_ZOOM_SENTINEL` and attempts to recover the real value via the constants/BCS-preamble
route; if unrecoverable it documents a fallback of `1.0` (= "no zoom") and the callers treat sentinel
as "no focus zoom for this station." (Exact value tracked as a spec follow-up if RE lookup fails.)

`CharacterClass.AddPositionZoom/GetPositionZoom/GetPositionLookAtName` delegate here, replacing the
`__getattr__` data-bag fallthrough.

### 4.2 Camera zoom on MenuUp (wire the dormant gap)

**Key composition (evidence):** BC native-reads `GetPositionZoom(pChar.GetLocation())` —
`GetLocation()` returns the station name (`"DBTactical"`, `"DBHelm"`, …), exactly the
`AddPositionZoom` key (`Kiska.AddPositionZoom("DBHelm", 0.45, "Helm")`).

**Hook = MenuUp / MenuDown** (the crew_menu_panel already tracks the open officer):

- On **MenuUp** (officer menu opens): resolve
  `zoom = officer.GetPositionZoom(officer.GetLocation())` and
  `look_at = officer.GetPositionLookAtName(officer.GetLocation())`; if `zoom` is not the sentinel,
  drive `_BridgeCamera` to that zoom factor (its existing FOV-factor + ease state machine) and frame
  the officer via `bridge_camera_watch.watch(officer)`.
- On **MenuDown** / `DropMenusTurnBack`: restore the default zoom and `bridge_camera_watch.clear()`.

**No new camera math.** The zoom *value* (0.45/0.5/0.8) becomes the target zoom factor consumed by
`_BridgeCamera`; framing reuses `bridge_camera_watch`'s head-centre resolve. `ZoomCameraObjectClass`'s
stubbed `ToggleZoom`/`IsZoomed` remain stubs — we drive the real `_BridgeCamera`. The MenuUp/MenuDown
methods reach the camera through a seam (a small module-level hook, `None`-guarded headless), never
importing the host loop at module load.

## 5. Workstream 3 — MenuState consolidation (low-risk, tier-0 §4.12)

`MenuState` holds **menu id** + **ready-flag** (BC `+0x14c`; ready-flag at `+0x28` bit 0x1).

- `CharacterClass._menu_state` owns it. `SetMenu(menu)` stores the `STTopLevelMenu` handle (unchanged)
  and stamps the derived id + ready-flag into `MenuState`; `GetMenu()` unchanged (still returns the
  handle / `_NULL_MENU`).
- **MenuUp gate consolidation:** formalize BC's `0x0066CDF0` gate set —
  menu-state present, `CS_UI_DISABLED` (0x8) **not** set, `m_bMenuEnabled` set, ready-flag set —
  reading from `MenuState` instead of the `_data` dict. `MenuUp`/`MenuDown`/CEF-panel behavior stays
  **byte-identical**; this is bookkeeping consolidation, not a behavior change.
- `GetCharacterFromMenu(menuId)` static (§4.12) — search the "bridge" set, first character whose
  menu id matches. Currently absent; implement faithfully (used by BC's menu-event routing).

## 6. Testing & verification

**Unit (pytest, pure — patch `host_io._h`, never call `_dauntless_host`):**
- `StatusMap`: keys 0..5 store/read/clear; `key>5` rejected; miss → `0`; `rows()` ascending order.
- `PositionZoomTable`: append-if-absent (dup name ignored); linear lookup; miss → sentinel;
  look-at resolution + `None` default.
- `MenuState`: id + ready-flag; MenuUp gate matrix (each gate blocks independently).

**Integration (pytest):**
- Run real `BridgeHandlers.HelmUpdateToolTip(pHelm)` → StatusMap keys 1-3 reflect speed/loc/dest;
  `XOUpdateToolTip` → key 1 alert.
- `Kiska.AddPositionZoom(...)` round-trip; MenuUp zoom hook resolves a zoom from `GetLocation()`.
- Tooltip owner: aimed-officer change updates the owner; `DropCharacterToolTips` clears it.

**Process:**
- Check the **stub heatmap** before asserting any `SetStatus`/zoom-read no-op.
- Gate on `scripts/check_tests.sh` (pytest + ctest) — NOT `run_tests.sh`. One baselined emitters
  flake in `known_failures.txt` is pre-existing/unrelated.
- Shared checkout: explicit-pathspec commits only; never `git add -A`/checkout/restore/stash/reset.

**Live pass by Mark (REQUIRED — StatusMap tooltips + camera zoom are player-visible; green tests
cannot see them, per `feedback_green_tests_cannot_see_asset_paths`):**
- Tooltip box appears on officer focus, `.bc-panel` styling, correct stacked rows (Helm
  speed/loc/dest; XO alert; "Waiting"/"Attacking"), hides on defocus.
- Camera zooms to the officer's station on menu open and back out on close.
- **Not** claimed done until Mark has seen it run in-game.

## 7. Delivery

- Fresh branch off `main`: `feat/characterclass-sp4-status-zoom-menu`.
- Subagent-driven (small tasks, review each, ledger in `.superpowers/sdd/progress.md`).
- Whole-branch code review → Mark's live pass → merge decision (local `main`, per SP1-SP3 pattern;
  push to origin is Mark's call).
