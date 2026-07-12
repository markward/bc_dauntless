# SDK-driven UI positioning + tutorial pointer arrows — design

> ## ⚠️ PARTLY SUPERSEDED (2026-07-12)
>
> The **arrow / geometry half of this spec is superseded** by
> `2026-07-12-identifier-centric-ui-attention-design.md`.
>
> **Why:** Chrome draws our UI, not BC's bitmap-font engine. A position-based arrow is
> only correct if the geometry we report matches what *Chrome* laid out — and neither
> source can give us that. Headless, BC's font metrics are `0` (menu resolves to height 0,
> every row reports the same Y). And the planned live probe would have captured BC's
> *bitmap-font metrics at 1024×768*, which don't match Chrome's layout and are
> resolution-bound. Either way the arrow lands **confidently in the wrong place**.
> Attention is therefore re-modelled as **identifier-centric** (style the element Chrome
> already drew), which cannot mis-place and needs no geometry.
>
> **Consequently DROPPED:** Task 1 (original-BC geometry probe) and the whole
> original-BC-machine dependency; the height-0 blocker dissolves.
>
> **STILL VALID and already built:** the **placement** half — the layout resolver
> (Tasks 3/4/5), the officer-menu layout invocation (5b), and the SDK→CEF position push
> channel (8). Mission-driven ad-hoc panels (`ShowInfoBox`, `TextBanner`,
> `EpisodeTitleAction`) genuinely need SDK-driven position; hardcoded CSS cannot serve them.

**Date:** 2026-07-11
**Status:** placement half ACTIVE; arrow/geometry half SUPERSEDED (see banner)
**Proving feature:** the **real E1M1 Set Course tutorial** playing to its `ShowArrow`
beat, with the pointer arrow landing on the actual "Set Course" button in the CEF
officer menu.

## Goal

Make the SDK the source of truth for UI *positioning*, not just data. Today every
CEF panel is positioned by hardcoded CSS (`native/assets/ui-cef/css/global.css`,
`crew_menus.css`), divorced from the SDK. That blocks a whole class of SDK-driven
UI behaviour — most concretely BC's tutorial arrows, which are **position-based**:
`MissionLib.ShowPointerArrow` reads the target widget's live screen position
(`pUIObject.GetScreenOffset(kOffset)`) + `GetWidth/GetHeight` and drops a `TGIcon`
arrow there (`MissionLib.py:4412`). An arrow only lands correctly if the widget's
geometry reflects where it is actually drawn — which requires the CEF UI to be
positioned by the SDK. SDK-driven position and SDK-driven arrows are the same
architecture; position is the prerequisite.

## Scope

**In (this slice):**
- A general SDK layout resolver (`SetPosition`/`Move`/`AlignTo`/`Layout`/
  `GetLeft/Top/Width/Height`/`GetScreenOffset`) over the TG-UI widget tree,
  producing absolute normalized rects.
- The **officer menu** (Picard's Commander/Helm/Tactical menu) positioned on
  screen from its SDK-resolved rect, replacing its CSS-flow placement.
- `MissionLib.ShowPointerArrow` / `HidePointerArrows` / `g_lPointerArrows` +
  `POINTER_*` constants, rendering arrows as a CEF overlay layer.
- **Driving the real E1M1 Set Course tutorial** (`ExplainWarp`) to its `ShowArrow`
  beat: fixing whatever currently blocks that tutorial sequence from playing end
  to end in Dauntless (integration of already-existing pieces; see Component 7).
- End-to-end proof: the real tutorial plays, the arrow lands on the "Set Course"
  button, and tracks it on the 0.125 s refresh.

**Out (follow-on, reuses the same resolver):**
- The rest of the tactical HUD (target list, ship/enemy display, weapons, radar,
  gauges — the E1M2 arrows).
- Any change to Dauntless-invented panels (engineering power grid, configuration,
  developer options, QuickBattle setup, pause menu) — they stay CSS-positioned.

**Non-goals:**
- Not replacing CEF with the native renderer. The arrow is a CEF overlay; no new
  native GL pass. (See the "Native UI is a DEAD END" project memory.)
- Not re-authoring BC-authentic geometry for panels beyond the officer menu in
  this slice.

## Key facts established during design

### Coordinate system — normalized 0..1, top-left origin, y-down

All SDK UI coordinates are **normalized fractions of the screen**:
`LCARS_1024.py` sets `SCREEN_WIDTH = SCREEN_HEIGHT = 1.0`, and pixel quantities are
written `146 / SCREEN_PIXEL_WIDTH` (reference `SCREEN_PIXEL_WIDTH = 1024`,
`SCREEN_PIXEL_HEIGHT = 768`).

`GetScreenOffset` returns the widget's **top-left corner**, y increasing
**downward**. Verified two ways:
- `ShowPointerArrow` math (`MissionLib.py:4444-4464`): `POINTER_LEFT` uses
  `x = kOffset.x + GetWidth()` (→ right edge, so `kOffset.x` = left);
  `POINTER_UP` uses `y = kOffset.y + GetHeight()` (→ bottom edge, so `kOffset.y` =
  top and y grows down); `POINTER_DOWN` subtracts to go above.
- `RepositionUI` real HUD positions (`TacticalControlWindow.py:513-536`): radar
  `SetPosition(0, H-height)` = bottom-left; weapons `(W-width, H-height)` =
  bottom-right; orders `(W-width, 0)` = top-right — all matching BC's actual HUD.

**Consequence:** CSS/CEF is *also* top-left origin, y-down, so reconciliation is a
pure scale by view dimensions — **no vertical flip**. This is a hard contract of
the resolver; nobody may reintroduce a flip.

`AlignTo(other, myAnchor, otherAnchor)` anchors (`ALIGN_UL/BL/UR/BR/UC/...`) are a
*separate* concern: they feed layout resolution but do not change what
`GetScreenOffset` reports (always top-left).

### Officer-menu placement — traced

- `TacticalControlWindow` is added to the bridge/tactical main window at
  `AddChild(pTacCtrlWindow, 0.0, 0.0)` (`TacticalControlWindow.py:338/345`) →
  TCW origin = screen (0,0).
- Officer-menu **window** = `InterfacePane.GetNthChild(TACTICAL_MENU=0)`, an
  `STStylizedWindow` (`pMenu.GetConceptualParent()` / `GetContainingWindow()`).
- `RepositionUI` sets `pTacticalMenuPane.SetPosition(0.0, 0.0)`
  (`TacticalControlWindow.py:489`) → officer menu window at screen **top-left
  (0,0)**.
- Size: `SetMaximumSize(TACTICAL_MENU_WIDTH + borderWidth,
  TACTICAL_MENU_HEIGHT + borderHeight)` (`:179`), where
  `TACTICAL_MENU_WIDTH = 146/1024 ≈ 0.143`,
  `TACTICAL_MENU_HEIGHT = 250/768 ≈ 0.326`, plus LCARS border.
- Buttons stack vertically inside the interior (window minus border).
- Therefore `GetScreenOffset(button) = (0,0) + borderInset + rowIndex·rowHeight`.

The `borderInset` and `rowHeight` are C++-delegated (`GetBorderWidth/Height`,
menu row layout) — captured from the running original game as ground truth (see
Verification).

## Architecture

```
SDK relative-layout tree (SetPosition / Move / AlignTo)
        │  Layout() / RepositionUI   ← already runs in our engine
        ▼
Layout resolver → absolute NORMALIZED rects (0..1, top-left, y-down)
        ├──▶ GetScreenOffset(widget)  → normalized top-left
        ├──▶ CEF panel position       → element placed at rect
        └──▶ Pointer arrow position   → arrow placed at rect ± spacing
```

Everything stays normalized [0,1] end-to-end. Pixels appear at exactly one
boundary — the CEF handoff — via a single reconciliation helper
`normalized → CEF view px → framebuffer px` (the inverse of the content-scale math
already in `host_loop.py:_compute_cef_resize` / `_forward_mouse_to_cef`).

The arrow and the CEF panel both read from the **same resolver**, so they are
consistent by construction — that is the whole point.

## Components

### 1. Layout resolver

A small 2D box-layout engine attached to the existing TG-UI widget shims
(`engine/appc/tg_ui/st_widgets.py`, the `CharacterMenu` in
`engine/appc/characters.py`, `TGPane`).

- `Rect(left, top, width, height)` in normalized coords.
- Per-widget local placement state: `SetPosition(x,y)`, `Move(dx,dy)`
  (accumulating delta), `AlignTo(other, myAnchor, otherAnchor)`.
- Anchor enum: `ALIGN_UL/UC/UR/BL/BC/BR/...` (implement the combinations the
  officer-menu chain uses; see Degradation).
- `Layout()` propagates parent → child: each child's absolute rect resolves
  against its parent origin and already-resolved siblings (for `AlignTo`).
- `GetLeft/GetTop/GetWidth/GetHeight` return resolved values.
- `GetScreenOffset(out)` fills `out` (an `NiPoint2`-like) with the resolved
  absolute top-left; returns a `TGPoint3` when called with no arg (matching the
  current stub's dual signature).

This is the general Approach-1 engine, but validated first on only the
officer-menu chain.

### 2. Officer-menu SDK-driven position

- Resolve the officer-menu window (`TACTICAL_MENU` pane) to its BC-authentic rect:
  top-left `(0,0)`, size ~`0.143 × 0.326` + border.
- The current CSS-flow placement of `#crew-menu-host` (inside
  `#tactical-target-stack`) is **replaced** by an SDK-driven inline position on
  the menu's own container.

### 3. SDK → CEF position channel

- After each `Layout()`/`RepositionUI`, the host reads each **SDK-positioned**
  panel's resolved rect and, **only on change** (dirty flag), pushes
  `{panelId, rect:{l,t,w,h}}` to CEF over the existing host→CEF event path
  (the `dauntlessEvent`/resize plumbing near `host_loop.py:5575`).
- JS applies it as inline `position:fixed; left/top/width/height = rect × viewPx`.

### 4. Pointer-arrow overlay

The SDK's `MissionLib.ShowPointerArrow`/`HidePointerArrows`/`g_lPointerArrows`
already run; they need the Appc surface they call:
- `TGIcon_Create`, `GraphicsModeInfo.GetLcarsString`,
  `TopWindow.PrependChild(icon, x, y)`, `icon.GetWidth/GetHeight/Layout`,
  `NiColorA_WHITE`, and the `POINTER_*` constants.
- `TopWindow.PrependChild` for arrow icons **emits to a CEF arrow-overlay layer**:
  a dedicated absolutely-positioned `#pointer-arrows` container; each arrow is one
  element (LCARS arrow glyph / CSS triangle) at `(x,y) × viewPx`, in 8 directions
  + 2 corners (`POINTER_LEFT/UL/UP/UR/RIGHT/DR/DOWN/DL` + `UL_CORNER/UR_CORNER`).
- The 0.125 s refresh timer is SDK-driven already; each refresh re-reads
  `GetScreenOffset` (now real) and re-emits, so arrows track the panel if it
  moves. `HidePointerArrows` clears the overlay + `g_lPointerArrows`.

### 5. Coordinate reconciliation

A single helper `normalized[0,1] → view px → framebuffer px`, mirroring the
content-scale inverse of `_compute_cef_resize`. Documented at the one boundary;
no y-flip.

### 6. Coexistence of invented panels

A panel is either **SDK-positioned** or **CSS-positioned**, tracked by an explicit
registry/flag:
- *SDK-positioned* (driven by the position channel): officer menu now; target
  list / ship displays / weapons / radar / gauges later.
- *CSS-positioned* (untouched): engineering power grid, configuration, developer
  options, QuickBattle setup, pause menu.

They occupy different DOM containers, so there is no collision: the position
channel only writes SDK-positioned panels' containers; invented panels keep their
`global.css` fixed positions. The registry is the single place that declares
"this panelId is SDK-driven," which also documents the scope boundary in code.

### 7. E1M1 Set Course tutorial trigger (the proof driver)

The arrow architecture is inert without something calling `ShowArrow`. For this
slice the driver is the **real E1M1 Set Course tutorial**, not a dev harness.

Trigger chain (traced):
- E1M1 builds Picard's menu with a `SettingCourse` button wired to
  `ET_SET_COURSE_TUTORIAL → ExplainWarp`, then disables the menu
  (`SetMenuEnabled(0)`) until the mission enables it (`E1M1.py:700/708/712`).
- Player clicks `SettingCourse` in the CEF officer menu → SDK activation event
  dispatches → `ExplainWarp` builds and plays a `TGSequence`:
  `PreloadSequenceLines → StartCutscene → ChangeToBridge → SetTutorialFlag →
  Picard AT_MENU_DOWN → Kiska AT_MENU_UP → SetCharWindowLock → ReturnControl →
  ShowInfoBox → ShowArrow(pSetCourseMenu, POINTER_UR_CORNER)`
  (`E1M1.py:3513-3534`).

Status of each dependency in Dauntless (to confirm in the spike):
- CEF menu button click → SDK activation dispatch — **exists** (crew-menu CEF
  activation is merged).
- `StartCutscene` / cutscene mode — exists (cutscene camera work).
- `ChangeToBridge` / view switch — exists (view-sync pull model).
- `AT_MENU_DOWN` / `AT_MENU_UP` — exists (bridge character animation / menus).
- `SetCharWindowLock` / `ReturnControl` — exists (char-window / control gating).
- `ShowInfoBox` — engine `info_box_panel.py` exists.
- `ShowArrow` / `ShowPointerArrow` — this spec (Components 1–5).
- **Mission progression enabling Picard's menu at the SettingCourse beat** —
  unverified; the spike determines whether E1M1 reaches this state and what (if
  anything) blocks it.

This is **integration of existing pieces**, not net-new subsystems — but the only
way to know the chain plays cleanly is live. Therefore the implementation plan
**front-loads a spike** (task 1) that runs E1M1, drives it toward the SettingCourse
beat, and enumerates the concrete blockers before any resolver code is written.
If the spike surfaces a blocker that is itself a large subsystem, we stop and
re-scope with Mark rather than absorbing it silently.

## Data flow

```
SDK ShowArrow action ─▶ MissionLib.ShowPointerArrow
                          ├─ GetScreenOffset(button)  ◀─ resolver (Layout resolved)
                          └─ PrependChild(icon, x,y)  ─▶ host ─▶ CEF #pointer-arrows @ px
RepositionUI/Layout ──▶ resolver rects ──▶ (dirty) host ─▶ CEF panel inline position @ px
```

## Degradation contract

The current `GetScreenOffset` stub silently returns `(0,0)` — an arrow on an
unhandled widget would land in the top-left corner and look "plausible but wrong."
The resolver must instead **fail loudly** on an `AlignTo` anchor combination or
widget-chain it does not yet handle (assert / raise, surfaced via
`dev_mode.log_swallowed` or an explicit error), never silently return `(0,0)`.
This keeps unimplemented panels honest and debuggable as the HUD is converted.

## Verification

### Instrumentation against the running original game (mandated)

Per the project's instrumentation convention, capture ground truth via the
`docs/instrumented_experiments/` runbook + in-game console probes (**not** an
`App.py` snippet). Experiment: open Picard's menu in a running mission, then probe
the live widgets at a known resolution:
- `pMenu.GetContainingWindow().GetScreenOffset(kOffset)` → window top-left
- `pWindow.GetBorderWidth()`, `GetBorderHeight()`
- `pButton = pMenu.GetButtonW("SettingCourse")`; `pButton.GetScreenOffset(kOffset)`,
  `GetWidth()`, `GetHeight()`

These normalized rects are the fidelity target; the resolver must reproduce them
within pixel tolerance for the same resolution. (`GetScreenOffset` is
C++-delegated, so static SDK reading alone cannot give the resolved absolute — the
probe is the ground truth.)

### End-to-end acceptance (Mark-run)

Play the **real E1M1 Set Course tutorial**: progress the mission until Picard's
menu enables the `SettingCourse` button, click it, and confirm `ExplainWarp` plays
its sequence to the `ShowArrow` call, with the arrow landing on the actual "Set
Course" button in the CEF officer menu and tracking it on the 0.125 s refresh.

## Testing (TDD; both suites via `scripts/check_tests.sh`)

- **Resolver unit tests:** `SetPosition`/`Move`/`AlignTo` across anchor
  combinations resolve to expected normalized rects; nested pane chains accumulate;
  `GetScreenOffset` returns top-left, y-down, no flip; `GetLeft/Top/Width/Height`
  agree; unhandled anchor/chain raises rather than returning `(0,0)`.
- **Reconciliation unit test:** normalized → view px → framebuffer px matches the
  content-scale inverse of `_compute_cef_resize`.
- **Arrow-math unit test:** given a known widget rect, each `POINTER_*` direction
  produces the arrow px the MissionLib formula dictates (port the formula into an
  assertion); `HidePointerArrows` empties `g_lPointerArrows`.
- **Integration test:** the officer-menu resolved rect produces the expected CEF
  position payload; a `ShowArrow` action emits one arrow overlay at the button's
  resolved position.
- **Live verification:** the E1M1 arrow beat (above).

## Risks

1. **`borderInset` / `rowHeight` exact values** — C++-delegated. *Mitigation:* the
   instrumentation probe captures them; the resolver reproduces `(0,0) + border +
   rowIndex·rowHeight`.
2. **`AlignTo` completeness** — the resolver must handle every anchor combo the
   officer-menu chain uses and degrade loudly elsewhere. *Mitigation:* implement
   on-demand for the chain in scope; assert-fail on unhandled combos.
3. **Bridge chatter** — dirty-flag rects so pushes happen only on change.
4. **Resolution independence** — LCARS numbers are per-resolution modules
   (`LCARS_1024/1280/1600/...`). *Mitigation:* resolver reads the current LCARS
   module (as the SDK does) and works in normalized coords, so it is
   resolution-agnostic; the probe is captured at one resolution and normalized.
5. **E1M1 tutorial chain plays cleanly** — the proof depends on the real
   `ExplainWarp` sequence and mission progression to the SettingCourse beat. The
   pieces mostly exist, but integration is unverified. *Mitigation:* the plan's
   task 1 is a live spike that enumerates concrete blockers before resolver work;
   a large blocker triggers a re-scope conversation, not silent absorption.

## Files (anticipated)

- `engine/appc/tg_ui/layout.py` (new) — `Rect`, anchors, resolver.
- `engine/appc/tg_ui/st_widgets.py`, `engine/appc/characters.py`,
  `engine/appc/windows.py` — wire widgets to the resolver.
- `engine/appc/pointer_arrows.py` (new) — `ShowPointerArrow`/`HidePointerArrows`
  Appc surface + `TopWindow.PrependChild` arrow emission (or extend the existing
  MissionLib-supporting shims).
- `engine/host_loop.py` — SDK→CEF position channel; arrow-overlay emission;
  reconciliation helper.
- `native/assets/ui-cef/js/*`, `native/assets/ui-cef/css/*` — officer-menu
  SDK-driven inline position; `#pointer-arrows` overlay layer; remove officer-menu
  CSS-flow placement.
- `docs/instrumented_experiments/` — the officer-menu geometry probe runbook.
- E1M1 tutorial trigger: engine-side gaps surfaced by the task-1 spike (mission
  progression to the SettingCourse beat, any broken `ExplainWarp` sequence
  action). Specific files unknown until the spike; **no SDK edits** — fixes land
  in `engine/` per "SDK drives everything."
- Tests alongside each of the above.
```
