# Identifier-centric UI attention (+ what survives of SDK-driven placement) — design

**Date:** 2026-07-12
**Status:** design pending approval
**Supersedes:** the *arrow/geometry* half of
`docs/superpowers/specs/2026-07-11-sdk-driven-ui-positioning-and-pointer-arrows-design.md`.
That spec's **placement** half (resolver + SDK→CEF push channel) stands and is already built.

## The pivot

BC's `MissionLib.ShowPointerArrow` is **position-based**: it reads the target widget's
live screen rect (`GetScreenOffset` + `GetWidth/GetHeight`) and drops an LCARS arrow
icon at computed coordinates. We built a faithful resolver for that — and then hit the
wall that makes the whole approach wrong:

**Chrome draws our UI, not BC's bitmap-font engine.** So an arrow is only correct if the
geometry we report matches what *Chrome* laid out. Two ways to get that geometry, both bad:

- **Compute it from the SDK** — headless, BC's font/border metrics come back `0`, so the
  menu resolves to height 0 and every button reports the same Y. The arrow cannot tell
  rows apart.
- **Measure it from original BC** (the planned live probe) — those are *bitmap-font
  metrics at 1024×768*. They don't match what Chrome draws with Antonio 13px, and they're
  resolution-bound — the opposite of the DPI independence we want. The arrow would land
  **confidently in the wrong place.**

The information the SDK is actually conveying is not a coordinate. It is:

> **"draw the player's attention to *this widget*."**

The widget handle is right there in the call. The coordinates were only ever BC's *way of
rendering* that intent with the renderer it had. We have a better renderer.

**So: keep the SDK's decision, substitute the rendering.** Attention becomes
**identifier-centric** — we style the element Chrome already drew. This is the same
relationship as rendering ships with OpenGL instead of Gamebryo: the SDK still decides
*what* and *when*; we own *how it's drawn*.

## Two mechanisms, cleanly divided

| Concern | Model | Why |
|---|---|---|
| **Attention / highlight** (`ShowPointerArrow`) | **Identifier-centric** | Cannot land in the wrong place; needs no geometry; DPI-free |
| **Placement** (`ShowInfoBox`, `TextBanner`, officer menu, HUD panels) | **Position-centric** (SDK → CSS) | You cannot identifier-your-way to "put this box centre-screen". SDK must drive position |

Both are needed. This spec builds the first and preserves the second.

## Mechanism: identifier-centric attention

### Interception point

**`MissionLib.ShowPointerArrow` / `HidePointerArrows`** — the single chokepoint every
caller funnels through. E1M1, E1M2 and E2M0 each wrap it in a mission-local `ShowArrow`
(added by `TGScriptAction_Create(__name__, "ShowArrow", …)`) which also runs a 0.125 s
refresh timer. All three wrappers call `ShowPointerArrow`.

We do **not** fork on the `TGScriptAction_Create` second-argument string (`"ShowArrow"`).
That is a *mission author's local function name* — a heuristic that happens to be
consistent across today's three missions, not a contract. `ShowPointerArrow` is the verb
that actually *means* "draw attention", it is stable SDK API, and it already receives
everything we need:

```python
ShowPointerArrow(pAction, pUIObject, eDirection, fSpacing, kColor)
#                         ^the widget handle      ^intent   ^colour
```

### No SDK edits

`sdk/Build/scripts/` stays read-only. The engine **overrides the two module attributes at
boot** (`MissionLib.ShowPointerArrow = _engine_impl`, same for `HidePointerArrows`) —
the SDK *file* is untouched; only the rendering of the effect changes. Precedent exists
(the project already shadows SDK modules, e.g. the root `App.py`).

### The identifier already exists

This is the key discovery: **the crew menu is already identifier-centric**, because click
dispatch needed exactly the same mapping.

- `engine/ui/crew_menu_panel.py` — `ensure_widget_id(widget)` → a stable `wid`;
  `self._widgets_by_id[wid] = widget`; each snapshot node carries `{"id": wid, …}`.
- `native/assets/ui-cef/js/crew_menus.js` — rows are built from those nodes and dispatch
  `crew-menu/click:<id>` / `crew-menu/expand:<id>`.

So a highlight is **one more piece of per-node state on a payload that already flows every
frame** — exactly like the existing `visible` / `enabled` / `open` / `expanded` fields.
**No new channel. No geometry. No measurement.**

### Implementation shape

1. **Engine holds the highlight set.** `ShowPointerArrow(pUIObject, …)` →
   `highlighted_ids.add(ensure_widget_id(pUIObject))` (honouring the SDK's own
   `IsCompletelyVisible() == 0` bail-out, and recording `kColor` if given).
   `HidePointerArrows()` → `highlighted_ids.clear()` (matches the SDK, which empties
   `g_lPointerArrows` wholesale).
2. **Snapshot carries it.** `CrewMenuPanel._snapshot_node` adds
   `"highlighted": wid in highlighted_ids` (plus an optional `"highlightColor"`).
3. **CEF styles it.** `crew_menus.js` adds a class (e.g. `crew-menu__row--attention`) when
   `node.highlighted`; CSS gives it a pulsing glow. Self-contained (no external assets).

### Lifecycle — persistent, NOT time-boxed

BC's arrow persists until `HidePointerArrows`; it is *refreshed* 8×/sec, not expired.
It stays **while the player still hasn't done the thing.** A fixed "glow for N seconds"
would extinguish the hint while the player is still stuck. So: **highlight on at
`ShowPointerArrow`, off at `HidePointerArrows`.** No duration.

### The refresh-flicker trap (and why it doesn't bite)

The mission's `RefreshArrows` timer calls `HidePointerArrows()` **then** re-issues
`ShowPointerArrow` for every entry — 8× a second. A naive implementation would clear and
re-add the CSS class 8×/sec, restarting the pulse animation and rendering it broken.

It doesn't bite, **provided the panel push is change-gated**: the whole hide→show cycle
happens inside a single Python tick, so by the time the next snapshot is taken the
highlight set is *identical* to the previous frame's. Same payload → no re-render → the CSS
animation runs smoothly.

**This must be verified, not assumed** — `crew_menus.js` rebuilds `host.innerHTML`, so if
the panel re-pushes an unchanged payload every frame the animation restarts every frame.
Confirm `PanelRegistry`/`Panel` only re-renders on payload change; if it doesn't, add a
dirty-flag (same pattern as the existing `PositionPusher`).

### What we deliberately give up

The arrow's **direction** (`POINTER_LEFT`/`UL_CORNER`/…) and **spacing** become
meaningless under a glow. The *information* was only ever "look here"; direction was a
placement detail of BC's arrow art. We **do** keep `kColor` → the glow colour, which is
cheap fidelity.

This is a visible departure from BC's look. It is consistent with the CEF-modern direction
the UI has already taken (the crew menu is Antonio/salmon-LCARS, not a pixel-clone), but it
is a **choice**, recorded here.

### Coverage

Highlighting works for any widget **projected into CEF with an id**. Today that's the
officer/crew menus ✓. The tutorials also point at the target list, weapons display, ship
displays and power gauges — those need the same id-carrying projection. That requirement is
identical under *any* approach: we cannot highlight what we do not render.

## What this deletes

- `native/assets/ui-cef/` — the `#pointer-arrows` overlay root + all `.arrow*` CSS.
- `engine/ui/pointer_arrow_overlay.py` (`build_arrows_script`, `ArrowOverlayPusher`).
- `engine/appc/pointer_arrows.py` (`emitted_arrows`) and the arrow-placement recording in
  `TopWindow.PrependChild` / `DeleteChild` (dead once `ShowPointerArrow` is overridden).
- **The live geometry probe (old Task 1) is DROPPED.** With it dies the whole
  original-BC-machine dependency.
- **The height-0 blocker DISSOLVES.** Nothing needs BC's font metrics any more.

## What survives (already built, reviewed, gate-green)

The **placement** half stands unchanged and is still justified — mission-driven ad-hoc
panels (`ShowInfoBox` 34 calls, `HideInfoBox` 25, `EpisodeTitleAction` 8, `TextBanner` 2)
must be positioned by the SDK, not hardcoded CSS:

- The layout resolver — `Rect`/anchors/`AlignTo`, top-down `Layout()` (Tasks 3/4/5).
- The officer-menu SDK layout invocation (Task 5b).
- The SDK→CEF position push channel + panel registry (Task 8).
- The `App.TGUIObject.ALIGN_*` binding fix.

### Scope line on placement

- **Absolute placement (`SetPosition` / `Move`) ships now.** It needs **no** text metrics —
  the officer-menu window is `SetPosition(0,0)` + an LCARS width constant. This is what the
  ad-hoc mission panels need.
- **`AlignTo`-driven HUD *reflow* is DEFERRED.** Resolving an `AlignTo` chain requires the
  *measured sizes* of the widgets being aligned to, which are 0 headless. That is the **only**
  thing that would need a Chrome→host measurement channel, and **nothing currently depends on
  it**. If/when we want BC's HUD to reflow as menus open, that channel is a clean future
  addition — not a blocker now.

## Proving feature

**The real E1M1 Set Course beat highlights the real "Set Course" button.** The tutorial
trigger (old Tasks 2/11 — driving `ExplainWarp` to its `ShowArrow` call) remains in scope
per Mark's earlier decision.

Crucially, the **highlight mechanism is now independently verifiable without the tutorial
and without the BC machine**: open the officer menu in Dauntless, call
`MissionLib.ShowPointerArrow` on the real Set Course button, and watch it glow. The
mechanism no longer has a live-original-game dependency at all.

## Testing

- **Unit:** `ShowPointerArrow` adds the widget's id to the highlight set and honours the
  `IsCompletelyVisible() == 0` bail-out; `HidePointerArrows` clears it; re-issuing an
  identical set is idempotent.
- **Unit:** `_snapshot_node` emits `highlighted: true` for a highlighted widget and `false`
  otherwise; `kColor` maps to `highlightColor`.
- **Unit (the flicker trap):** a `Hide` → `Show` cycle within one tick leaves the snapshot
  payload byte-identical to the previous frame (so no re-render, so no animation restart).
- **Live (Mark):** the officer menu's Set Course row glows on `ShowPointerArrow` and stops
  on `HidePointerArrows`; production path (no tutorial) is visually unchanged.
- Gate: `scripts/check_tests.sh`.

## Risks

1. **Panel re-render churn** — if the crew-menu payload is re-pushed unchanged each frame,
   the CSS pulse restarts and looks broken. *Mitigation:* verify/add change-gating (above);
   it has a unit test.
2. **Overriding an SDK function** is a behavioural fork of two functions. *Mitigation:* it is
   a **renderer substitution**, not a logic change — the SDK still decides what/when; scope
   it to exactly `ShowPointerArrow`/`HidePointerArrows` and document it loudly.
3. **Widgets we don't project** can't be highlighted (target list, gauges). *Mitigation:*
   out of scope here; same constraint under any approach.
