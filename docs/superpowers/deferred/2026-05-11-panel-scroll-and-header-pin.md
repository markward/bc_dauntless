# Deferred: panel scroll behavior & pinned header

**Status:** deferred 2026-05-11. UiPanel works as a fixed-height container with `overflow: hidden` clipping. Scrolling content and pinning the header while only the body scrolls were both attempted and reverted.

## Desired end state

When a `UiPanel` is constructed with `height_vh` and the contained `bc-collapsible` / `bc-button` rows exceed that height:

1. A vertical scrollbar appears.
2. Only the **body** scrolls — the **header** (`bc-panel-header` with title + collapse toggle) stays pinned at the top of the panel.
3. The bc-panel's rounded corners and dark `#1e1e1e` background remain the visual wrapping container regardless of scroll state.

The current implementation gets (3) correct (via `overflow: hidden`) but does not deliver (1) or (2). Content extending past the panel's `55vh` is silently clipped.

## What we tried and why each reverted

### Attempt 1 — `overflow-y: auto` on `bc-panel-body` inside a flex column

`bc-panel { display: flex; flex-direction: column; }` with `bc-panel-header { flex: 0 0 auto; }` and `bc-panel-body { flex: 1 1 auto; overflow-y: auto; min-height: 0dp; }`.

This is the textbook web-CSS approach and would work in a browser. In RmlUi it broke the cross-axis: child rows shrunk to text width instead of stretching to the panel's full width.

### Attempt 2 — adding `align-items: stretch` to the flex container

Explicit `align-items: stretch` on `.bc-panel` did not restore the row widths. Either RmlUi's flex implementation doesn't honor `align-items: stretch` the way CSS specifies, or the property is parsed but ignored, or it's being overridden by something we didn't identify. Diagnosing requires reading RmlUi's `Source/Core/Layout/FlexFormattingContext.cpp` and/or stepping through with the RmlUi debugger to see what RmlUi computes for each flex item's main- and cross-axis sizes.

### Attempt 3 — `overflow-y: auto` on the panel itself (whole-panel scroll, no pin)

Simpler fallback: drop the flex, put `overflow-y: auto` on `.bc-panel`, accept that the header scrolls with the body. This scrolled correctly but the act of reserving scrollbar space caused the absolutely-positioned `.bc-panel-toggle` arrow (anchored `right: 8dp`) to shift visibly, and the `.bc-arrow` glyphs inside collapsible headers also misaligned (likely RmlUi recomputes the content width when the scrollbar appears and absolute children re-anchor to the new edge mid-frame). Reverted on user feedback ("arrows are misaligned").

## Likely paths forward (none tried yet)

### A — Fix or work around RmlUi's flex cross-axis stretch

Most aligned with the intended design. Requires reading the RmlUi flex implementation to confirm whether `align-items: stretch` works correctly for column flex with auto-sized children. If it does work and we just configured it wrong, this is a quick fix.

### B — Absolute positioning with hardcoded header height

```rcss
.bc-panel        { position: relative; ... }
.bc-panel-header { /* natural flow, height ~32dp */ }
.bc-panel-body   { position: absolute; top: 32dp; left: 8dp;
                   right: 8dp; bottom: 8dp; overflow-y: auto; }
```

Pros: avoids flex entirely. Cons: requires hardcoding the header's pixel height — fragile against title font size / padding changes and breaks if a future panel header gains an extra row.

### C — Measure header height from C++ at construction time

`PanelDocument` (which already has access to the live `Rml::Element`) can call `GetClientHeight()` on the header after `doc_->Show()` and set the body's `top` inline style accordingly. More robust than B but couples the layout to a runtime measurement step.

### D — Custom RmlUi event listener that re-sizes the body on header resize

Most general but most code. Probably not worth it unless headers become dynamic (resizable titles, animated chrome).

Recommended order to try: **A** first (quickest to confirm or rule out), then **C** (works regardless of RmlUi flex behavior), then **B** as a last resort.

## Files involved

| File | Relevance |
|---|---|
| [`native/assets/ui/components.rcss`](../../../native/assets/ui/components.rcss) | `.bc-panel`, `.bc-panel-header`, `.bc-panel-body` rules |
| [`engine/ui/panel.py`](../../../engine/ui/panel.py) | `UiPanel` constructor — where the header/body divs are emitted |
| [`native/src/ui/PanelDocument.cc`](../../../native/src/ui/PanelDocument.cc) | Where `doc_` (body) inline styles are set; place to measure header height for path C |
| [`native/src/ui/UiSystem.cc`](../../../native/src/ui/UiSystem.cc) | Registers the RmlUi debugger — useful when actually digging into the flex issue |

## Test plan when implementing

- Pick a panel with `height_vh` smaller than the content height. The current demo panel doesn't exceed 55vh; either shrink the panel to ~30vh or add more rows.
- Verify scrollbar appears.
- Verify scrolling moves only the body, not the header (whichever approach is chosen — if the simpler "whole panel scrolls" is acceptable, that constraint relaxes).
- Verify `bc-panel-toggle` (top-right arrow) stays at a fixed position regardless of scroll.
- Verify clicking individual rows still works after scrolling — the click coordinates feed through `UiSystem::cursor_pos_cb` → RmlUi context, and absolute hit-testing should account for the scroll offset.
