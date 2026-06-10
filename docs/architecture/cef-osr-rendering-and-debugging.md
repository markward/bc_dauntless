# CEF UI overlay — rendering model & debugging playbook

How the CEF-backed HUD overlay reaches the screen, the pitfalls of CEF's
**software** off-screen rendering (OSR), and the techniques that work for
diagnosing overlay rendering bugs. Written after a long hunt for a HUD
flicker whose root cause was non-obvious (see "Case study" below).

## Rendering model

The overlay is a windowless (OSR) CEF browser composited over the 3D scene
every frame. GPU is disabled (`--disable-gpu`, `--disable-gpu-compositing`
in `cef_app.cc`), so Chromium rasterises the whole page **on the CPU**.

Per host frame (`host_bindings.cc` render → `cef_lifecycle.cc`):

1. 3D scene renders to the backbuffer.
2. `pump()` → `CefDoMessageLoopWork()`. CEF may call `OnPaint` synchronously
   on this thread (single-threaded message loop, `multi_threaded_message_loop
   = false`), delivering a full-view BGRA bitmap into `DauntlessCefClient::bitmap_`.
3. `composite()` → `latest_bitmap()` → `draw_fullscreen()` blits that bitmap
   over the scene with premultiplied-alpha blend.
4. `swap_buffers()`.

Panels are driven from Python: each tick `PanelRegistry.render_all()` returns
JS snippets (`setShipDisplay(...)`, `setTargetList(...)`, …) for panels whose
snapshot changed; the host runs them via `cef_execute_javascript`. A DOM
mutation makes CEF mark that region dirty and repaint it on a later pump.

## The big pitfall: do NOT force a full-view Invalidate

**Rule:** never call `host->Invalidate(PET_VIEW)` on a schedule in `pump()`.

Forcing a full-view invalidate makes the CPU rasteriser re-raster the entire
page (e.g. 2560×1440 on Retina) every tick. It cannot finish in time, so CEF
delivers **partial frames** — panel borders/headers paint but the bodies
don't — for *clusters* of consecutive frames. On screen that is a HUD
flicker, worst on high-refresh / ProMotion displays where the vsync-bound
host loop pumps fastest (120–180 Hz). Rate-limiting the invalidate to 60 Hz
reduces but does **not** eliminate it.

CEF already auto-invalidates the regions our DOM mutations dirty, so panels
update on change without any forced invalidate. If a *targeted* repaint is
ever needed (the original code feared "CEF skips OnPaint after DOM mutation"),
invalidate only the **dirty rect** on frames where JS actually ran — never the
whole view on a timer.

## Debugging playbook

### Getting data out of the browser

- **`console.log` is swallowed.** In this configuration CEF does not surface
  page `console.log`/`console.info` to stdout/stderr, so it is useless for
  diagnostics and gives false negatives ("no output" ≠ "code didn't run").
- **Use the event channel instead.** `dauntlessEvent(name)` emits
  `console.info("dauntless-event:" + name)`, which `OnConsoleMessage` parses
  by prefix and forwards to the Python handler (`PanelRegistry.dispatch`).
  This is the *reliable* JS→Python channel (panel clicks use it). To exfil a
  debug value from JS, push e.g. `dauntlessEvent("dbg:" + ...)` and print it
  from a temporary branch in `dispatch`.
- **Python side** is straightforward to log: `render_payload` runs every tick;
  tally emit-vs-none and the actual values there.

### Localising "a panel vanished": DOM collapse vs compositor drop

A panel can disappear for two very different reasons. Distinguish them before
fixing:

- **DOM collapse** (element actually `hidden`/removed): siblings **reflow** to
  fill the space. Confirm by measuring header Y-positions across frames, or
  log `getComputedStyle(el).display` and `el.offsetHeight` from JS via the
  event channel. If the DOM is stable (`display:block`, non-zero height) it is
  **not** a DOM problem.
- **Compositor drop** (DOM correct, CEF rasterised it wrong): the bitmap is
  wrong while the DOM is provably fine. This is the case the full-view
  invalidate caused.

### Capturing the actual pixels

Two complementary dumps localise the bug to overlay-content vs on-screen
compositing (both were temporary scaffolding — re-add if needed):

- **Overlay buffer** — dump `DauntlessCefClient::latest_bitmap()` (what
  `composite` draws), premultiplied BGRA composited over mid-gray so
  transparent ≠ black and panels stand out.
- **Final framebuffer** — `glReadPixels(GL_BACK)` after `composite()`, before
  swap, gated on a keypress (use a plain letter key like `P`; **macOS eats
  F-keys as media keys** unless Fn is held). glReadPixels origin is bottom-up
  = BMP bottom-up, so no flip. Convert BMP→PNG with `sips -s format png`.

If the **overlay buffer itself** is body-less, the bug is in CEF's
rasterisation (not the GL composite, not the DOM) — which is what pointed at
the forced invalidate.

### A cheap anomaly metric

A stride-sampled scan of the OnPaint buffer for opaque-pixel fraction (and
opaque-near-black fraction) cheaply flags "panels missing" (fraction collapses
vs previous) and "black block appeared" frames. Useful for quantifying how
often partial frames occur and whether a fix reduced them. Note a single
opaque-fraction threshold can't distinguish a single-panel drop from a
legitimate hide — verify against the paired dumps.

## Case study (the flicker that produced this doc)

Symptom: left-column HUD panels flickered during combat on a 120 Hz/ProMotion
display; right-side panels were solid. Dead ends ruled out by falsifiable
tests, each pointing one layer deeper:

1. **Not DOM-driven idempotency** — guarding `img.src`/`innerHTML` rebuilds in
   the panel JS changed nothing.
2. **Not Python/JS visibility** — logs proved `visible` stayed `true`; JS
   never received `visible:false`; DOM stayed `display:block`, `offsetHeight`
   constant.
3. **Not update churn** — quantising the per-frame range/speed didn't reduce
   it (and didn't even reduce emit rate).
4. **Not the overlay-bitmap content** — an OnPaint "reject partial frames"
   mask held bad bitmaps, yet the flicker persisted.
5. **It was CEF rasterisation** — paired overlay/framebuffer dumps showed the
   overlay buffer arriving body-less (borders only) in 4-frame clusters while
   the DOM was stable. Cause: the forced full-view `Invalidate(PET_VIEW)` in
   `pump()`. Fix: remove it (commit `a5411ad`).

Lesson: when the symptom is visual, capture the actual pixels at each boundary
(DOM computed style → overlay buffer → final framebuffer) early, instead of
reasoning forward from a hypothesis about which layer is at fault.
