# Native FreeType font backend behind `TGFontGroup`, proven via a CEF-absent `TGParagraph` render

**Date:** 2026-07-10
**Status:** Design — approved for spec, pending user review of this document
**Sequencing:** Spec 1 of 2 (fonts before icons). Spec 2 (`TGIconGroup` + geometry + full five UI behaviours) is scoped but not yet written.

---

## 1. Motivation

Dauntless's native UI stack (`engine/appc/tg_ui/` — `TGPane`, `TGIcon`, `TGParagraph`,
`TGFontGroup`, `STButton`, …) is a faithful, **render-free** mirror of BC's SDK widget
tree. Every geometry/layout/colour/font call is a silent `_Stub` no-op; the only pixels
in the running game come from CEF (off-screen HTML composited over the 3D scene).

We want to prove a **"keep the SDK interface, swap the backend"** strategy: leave the
Python widget/​font API surface exactly as ported SDK scripts expect it, but give it a
real native rendering backend so the retained tree actually paints — **without CEF in the
launch path**.

This spec is the **first slice**: reimplement the font backend (`TGFontGroup` and its
`TGIconGroup` parent's font-relevant surface) over **FreeType** with a dynamic
glyph-cache atlas, preserving the public method surface, and validate it by rendering a
live `TGParagraph` in a CEF-absent harness window.

Fonts are sequenced before icons deliberately:
- **Licensing forces it.** BC's baked font atlases (`Tahoma.tga`, `Crillee*.tga`) and the
  Crillee typeface are proprietary; we cannot ship them. A runtime font backend that
  loads an OFL font we *can* ship is required regardless.
- **The seam is cleaner.** `TGFontManager` already exposes the full
  `CreateFontGroup`/`GetFontGroup`/`RegisterFont` API; only the backend is fake
  (`TGFontHandle.GetStringWidth` currently returns a synthetic `0.6·size·len`). Swapping
  that backend touches a well-bounded surface.
- **It validates the thesis on the subclass** (`TGFontGroup(TGIconGroup)`) before we
  attempt the same move on the parent `TGIconGroup` (icons/geometry) in Spec 2.

### Non-goal / useful-failure framing

A clean render is the success case. **A crash is also a useful result**: because the
render-free stack leans on silent `_Stub` no-ops, running it with CEF absent today yields
*silence*, not a crash. When we drive a real native paint path and something CEF was
silently providing is missing, we want the failure to name that subsystem, not be worked
around. Capture and report whatever breaks.

---

## 2. Verified current state (ground truth, 2026-07-10)

All confirmed against the working tree. This is what we are building on/around.

### Ownership boundary (decisive)
- **The engine owns the GL context, window, buffer swap, and input pump; CEF is a pure
  off-screen (OSR) guest.**
  - Window + GL 4.1 context: `native/src/renderer/window.cc` (GLFW), created in
    `host_bindings.cc` `init()` — touches no CEF.
  - Present: `glfwSwapBuffers` — `native/src/renderer/window.cc:143`.
  - Input pump: `glfwPollEvents` — `native/src/renderer/window.cc:147` (the one real pump;
    CEF is fed synthesized mouse events and is subordinate).
  - CEF is windowless OSR (`SetAsWindowless(0)`); `OnPaint` produces a BGRA bitmap the
    engine uploads and blends. Every CEF entry point no-ops when uninitialized.
- **Dependency direction is CEF → engine, never the reverse.** Removing CEF removes only
  the HTML overlay; window/present/input remain fully functional.

### Launch path
- `main()` is `native/src/host/host_main.cc:91`. Order: `install_macos_app()` (line 101,
  CEF) → `dispatch_subprocess()` (line 109, loads CEF framework + `CefExecuteProcess`) →
  project-root/PYTHONPATH setup → register `_dauntless_host` → `--developer` scan (line
  126–131) → `Py_InitializeEx` (line 133) → mode dispatch on `argv[1]`
  (`--smoke-check`/`--banner`/default `run_host_loop`).
- GL/window/CEF-*browser* init happen later, inside Python `engine.host_loop.run()`
  (`host_loop.py:4806`): `r.init(1280, 720, …)` (`host_bindings.cc:404`) then
  `r.cef_initialize(...)` (`host_loop.py:4879`). `host_loop.py:4879-4887` already tolerates
  `cef_initialize()` returning `False` and keeps rendering.
- **No runtime flag gates CEF today.** `DAUNTLESS_ENABLE_CEF` is a compile-time CMake
  option (`native/CMakeLists.txt:63`, default ON). `OPEN_STBC_HOST_HEADLESS=1` only hides
  the window; it does not skip CEF.

### Rendering primitives available to copy
- `native/src/renderer/target_reticle_pass.cc` is the model bespoke quad pass: lazy
  VAO/VBO unit quad (`ensure_quad`, `:85`), `glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); glDisable(GL_DEPTH_TEST)` (`:145-151`),
  fragment `tint * texture` with `u_uv_rect` sub-rect sampling. **It is a world-space
  billboard**, so its vertex path is *not* reusable — we write a trivial pixel→NDC vertex
  shader instead.
- Binding pattern: file-scope globals + `m.def("set_…", lambda, …)` setters + a `clear_…`,
  read each `frame()` (e.g. `set_subsystem_pins` `host_bindings.cc:2399`,
  `set_target_reticle` `:2419`). Passes instantiated in `init()` (~`:450`), invoked in
  `frame()`.
- Shaders are embedded at configure time via `embed_shader(...)`
  (`native/src/renderer/CMakeLists.txt:5-12`) and fetched from `Pipeline`
  (`pipeline.cc:44-89`).
- Texture load: `assets::decode_tga` / `assets::upload_image`
  (`native/src/assets/include/assets/texture.h:68`), a **stb_image** wrapper. `Image`
  supports `Format::R8` — usable for an alpha/coverage glyph atlas.

### The font/widget API surface (what we preserve)
- `TGFontManager` (`engine/appc/tg_ui/managers.py:38-69`) — full API present:
  `RegisterFont`, `GetFont`, `SetDefaultFont`, `GetDefaultFont`, `CreateFontGroup`,
  `AddFontGroup`, `GetFontGroup`. Singleton `g_kFontManager` (`:148`). `CreateFontGroup`
  mints a fresh `TGFontGroup`; `AddFontGroup`/`GetFontGroup` cache.
- `TGFontGroup(TGIconGroup)` (`managers.py:25-35`) — stores `_family`, `_size`; name =
  `"%s%d"`. Inherits `TGIconGroup`'s `LoadIconTexture`/`SetIconLocation`/`GetIconLocation`
  (real, store verbatim) and `GetIconScreenWidth/Height(slot)` (**stub → 0.0**).
- `TGFontHandle` (`managers.py:9-22`) — `GetHeight()` → `float(size)`;
  `GetStringWidth(text)` → **synthetic** `0.6·size·len(text)`.
- `TGParagraph` (`widgets.py:176-236`) — **does not hold a font**; `SetFont` is a **no-op**
  (`:235`). Stores an ordered `_segments` content stream of `("text", str) | ("char", int)
  | ("child", TGParagraph)`; `GetText()`/`iter_segments()` expose it; `_scale`/`_color`
  stored but "never consulted".
- `SetHorizontalSpacing` / `SetSpaceWidth` — **absent** everywhere (the SDK `Icons/*.py`
  call them; we will add minimal real versions, see §5).
- The root `App.py` shim re-exports these classes so ported SDK scripts hit the real
  Python methods.

### Libraries — all absent (net-new)
- **FreeType** — 0 matches repo-wide (not vendored/fetched/found).
- **HarfBuzz** — 0 matches (deferred to Spec 1-follow / Spec 2 anyway).
- No first-party glyph-atlas / rect-packer in `native/src/` (only inside the dormant
  `native/third_party/glfw/deps/nuklear.h`, not built). `native/third_party/stb/` contains
  only `stb_image.h`.

### Font asset (already in tree, OFL, shippable)
- `native/assets/ui-cef/fonts/Antonio-Regular.ttf` + license
  `native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt`. Antonio is a condensed
  Helvetica-adjacent face already used for the LCARS look. We load this exact TTF from the
  native path. Minor: relocate/copy to `native/assets/fonts/Antonio-Regular.ttf` so the
  asset is independent of the `ui-cef/` directory we are proving unnecessary.

---

## 3. Decisions (locked with the user)

1. **Render the real tree.** The live `engine/appc` retained tree is the single source of
   truth and genuinely paints. Per-frame traversal + layout live **Python-side** (where the
   objects are), emitting a flat draw-list to a deliberately-dumb native pass. C++ never
   reaches into Python objects per frame.
2. **FreeType-only first.** Ship FreeType rasterization + a dynamic atlas now, using
   FreeType advances + `FT_Get_Kerning` for Latin/LTR layout. **HarfBuzz is deferred** to a
   fast-follow when complex shaping is actually needed.
3. **Launch via a runtime `--no-cef` flag** (not a `-DDAUNTLESS_ENABLE_CEF=OFF` build). CEF
   stays linked but is **provably never constructed** on this path: the flag is parsed early
   and gates the CEF bootstrap + Python `cef_initialize`, with loud guard-prints that fire
   only if CEF is touched. (`-DDAUNTLESS_ENABLE_CEF=OFF` remains available as a
   belt-and-suspenders proof but is out of scope here.)
4. **Bundled font: Antonio.** `CreateFontGroup("Crillee", …)` (and other BC family names)
   resolve to Antonio via a family-name map.
5. **Backend lives native/C++.** It owns the GL glyph-atlas texture. Python `TGFontGroup`/
   `TGFontHandle`/`TGFontManager` keep their exact surface but proxy to native calls.

---

## 4. Architecture

```
engine/ui_harness.py  (throwaway)
    │  builds a real TGParagraph via CreateFontGroup("Crillee", 12.0)
    │  loop: poll → walk paragraph → draw-list → ui_render → swap
    ▼
engine/appc/tg_ui  (interface preserved; backend swapped to native proxy)
    TGFontManager / TGFontGroup / TGFontHandle  → font_create / font_measure
    TGParagraph.SetFont / iter_segments          → text runs
    ▼  (pybind11 bindings, _dauntless_host)
native/src/host/host_bindings.cc
    font_create(family, px) -> handle
    font_measure(handle, text) -> (w, h)
    ui_render(draw_list)      # binds FBO 0, clears, draws runs
    ui_should_close()
    (reuse) poll_events / swap_buffers / cursor_pos / key_state
    ▼
native/src/text/font_service.{h,cc}    (new)   ── FreeType
    FT_Face per (family, size_px)
    dynamic glyph-cache atlas (R8 GL texture + shelf packer)
    shape(text) -> positioned glyph runs (advance + FT_Get_Kerning)
    measure(text) -> (w, h)
native/src/renderer/ui_quad_pass.{h,cc} (new)  ── GL
    screen-space pixel→NDC quad; samples R8 atlas; tint+alpha; FBO 0
    shaders/ui_quad.vert  shaders/ui_quad.frag
native/src/host/host_main.cc  (edited)
    --no-cef flag (early parse) + --ui-harness mode + CEF guard-prints
```

### 4.1 Draw-list contract (Python → native)

The harness walks the paragraph tree and emits an ordered list of **text-run** commands.
For Spec 1 there is exactly one command kind:

```
("text", font_handle:int, x:float, y:float, text:str, rgba:(r,g,b,a))
```

Coordinates are **pixels**, origin top-left (BC convention), resolved by the Python walker
from the paragraph's composed offset. `ui_render(draw_list)` binds FBO 0, sets the viewport
to the framebuffer size, clears to a dark background, and draws each run. (Spec 2 adds
`("rect", …)` and `("icon", …)` kinds to the same list/pass.)

### 4.2 FontService (native, FreeType)

- **Init:** `FT_Init_FreeType` once. Family-name → TTF path map (default `"Crillee"` and
  `"*"` → `Antonio-Regular.ttf`).
- **`font_create(family, size_px) -> handle`:** get-or-create an `FT_Face` sized with
  `FT_Set_Pixel_Sizes`; return an integer handle (index into a vector). Cache by
  `(family, size_px)`.
- **Glyph atlas:** one `GL_R8` texture (start 512×512). A **shelf allocator** packs glyph
  bitmaps on demand; each glyph cached by `(handle, glyph_index)` → `{uv_rect, bearing,
  advance, size}`. On-demand rasterization: `FT_Load_Char(..., FT_LOAD_RENDER)`, upload the
  8-bit coverage bitmap via `glTexSubImage2D`. No eviction (bounded glyph set); if a shelf
  overflows, grow/allocate a second row — atlas-resize is a documented follow-up, not
  required for the harness.
- **Layout (`shape`):** left-to-right; per char, advance the pen by the glyph advance plus
  `FT_Get_Kerning(prev, cur)` when kerning is available; newline resets x and advances y by
  the face line height. Space width from the space glyph's advance, overridable by
  `SetSpaceWidth` (see §5).
- **`measure(text) -> (w, h)`:** run the same layout without drawing; return the bounding
  extent in pixels.

### 4.3 UiQuadPass (native, GL)

- Clone `TargetReticlePass`'s lazy VAO/VBO unit-quad skeleton.
- **Vertex shader** `ui_quad.vert`: uniforms `u_rect_px (x,y,w,h)` and `u_viewport (vw,vh)`;
  emits NDC directly: `ndc.x = (px)/vw*2-1`, `ndc.y = 1-(py)/vh*2`. No camera/projection.
- **Fragment shader** `ui_quad.frag`: samples the R8 atlas as coverage (`a = texture(...).r`),
  outputs `vec4(u_tint.rgb, u_tint.a * a)`; `discard` when `a < 0.01`. (Spec 2 adds a
  `u_textured=0` solid branch for rect/icon fills — left as a uniform hook here.)
- **GL state:** `GL_BLEND` with `GL_SRC_ALPHA/ONE_MINUS_SRC_ALPHA`, `GL_DEPTH_TEST` off,
  `GL_CULL_FACE` off; restore after. Draw target is **FBO 0** (default framebuffer), where
  CEF composites today — crisp, un-tonemapped LDR colour.
- One `glDrawArrays(GL_TRIANGLES, 0, 6)` per glyph quad.

### 4.4 Launch & CEF-absence proof (`host_main.cc`)

- Parse `--no-cef` (and treat `--ui-harness` as implying it) **before** line 101, setting a
  process-global `dauntless::set_cef_disabled(true)` (mirrors the existing
  `set_developer_mode` mechanism in `native/src/host/developer_mode.{h,cc}`).
- When disabled, **skip** `install_macos_app()` and `dispatch_subprocess()` so the CEF
  framework never loads.
- `--ui-harness` mode dispatches like `--smoke-check`: import `engine.ui_harness`, call
  `run()`, return its int as the exit code.
- **Guard-prints** (`print()`, not `logging.*` — the host has no logging handler): at
  `dispatch_subprocess`, `ui_cef::initialize`, and the `cef_initialize` binding, if reached
  while `cef_disabled`, print a loud `!!! CEF CONSTRUCTED ON --no-cef PATH` line. At harness
  startup print the positive `CEF: framework not loaded (--no-cef)`.
- On the Python side, `cef_initialize` is simply not called by the harness (it runs its own
  loop, not `host_loop.run()`); the existing `False`-tolerant path is untouched.

### 4.5 Harness present loop (`engine/ui_harness.py`, throwaway)

```python
def run() -> int:
    r = renderer_facade()
    r.init(1280, 720, "ui-harness")          # window + GL, no CEF
    print("CEF: framework not loaded (--no-cef)")
    group = g_kFontManager.CreateFontGroup("Crillee", 12.0)
    para = TGParagraph("Dauntless native text — CEF absent. 0123456789")
    para.SetFont(group)
    while not r.ui_should_close():
        r.poll_events()
        draw_list = walk_paragraph(para, x0, y0)   # → [("text", handle, x, y, s, rgba)]
        r.ui_render(draw_list)
        r.swap_buffers()
    return 0
```

`walk_paragraph` reconstructs the string from `iter_segments()`, resolves the font handle
from the paragraph's group (or `GetDefaultFont`), and emits one (or more, on newline)
text-run commands. No mouse/focus/teardown in Spec 1 — those need geometry (Spec 2).

---

## 5. Python interface changes (surface preserved, backend swapped)

- `TGFontManager.CreateFontGroup(family, size, …)` / `GetFontGroup` / `GetDefaultFont`:
  return a `TGFontGroup` whose creation also calls `font_create(mapped_family, size_px)` and
  stashes the native handle on the group. Family-name map lives here.
- `TGFontGroup`: gains a `native_handle()`; keeps `GetFontName`/`GetFontSize`; inherited
  `SetIconLocation` becomes a **documented deletable no-op** (the atlas is dynamic now).
- `TGFontHandle.GetHeight()` / `GetStringWidth(text)`: proxy to native `font_measure`
  (replacing the synthetic `0.6·size·len`). `GetIconScreenWidth/Height(slot)` may return real
  glyph extents where a caller needs them; 0.0 otherwise.
- `TGParagraph.SetFont(group)`: **stores** the group (currently discards it); rendering uses
  it, falling back to `g_kFontManager.GetDefaultFont()` when unset. `_segments` stream and
  all append/get APIs are unchanged.
- `SetSpaceWidth(px)` / `SetHorizontalSpacing(px)`: **add** as real setters on
  `TGIconGroup`/`TGFontGroup` that override the FreeType-derived space/advance metrics only
  when called; otherwise FreeType metrics are used. (These are additive — the SDK calls them
  but our tree never defined them.)

Guarding rule: these classes are shared with the running game. Changes must keep every
existing call site working (no signature breaks; new behaviour only when the native backend
is present). When `_dauntless_host` is absent (pytest), the proxies fall back to the current
synthetic metrics so headless tests are unaffected.

---

## 6. Build / dependency plan

- Vendor **FreeType** via CMake `FetchContent` (the established pattern:
  `native/CMakeLists.txt` already fetches pybind11, OpenAL, CEF). Build FreeType **without**
  HarfBuzz/zlib/png/brotli optional deps to keep it self-contained and dodge the
  FreeType↔HarfBuzz build cycle.
- New CMake target `text` (`native/src/text/`) linking FreeType + `glad` + `assets`; linked
  by the host bindings and by a `text_tests` target.
- New shaders `ui_quad.vert/.frag` registered via `embed_shader(...)`; `UiQuadPass`
  constructed in `pipeline.cc`/`init()` per the existing pass pattern.
- Shader edits require `cmake -B build -S .` reconfigure before `cmake --build` (embedded at
  configure time). `host_bindings.cc` edits require a `dauntless` rebuild (module-only
  rebuild leaves `./build/dauntless` stale).
- Font asset copied to `native/assets/fonts/Antonio-Regular.ttf` (+ carry the OFL license).

---

## 7. Testing & verification

- **C++ unit (`text_tests`, ctest):** FontService loads Antonio; `font_create` returns a
  stable handle; `measure("AV")` is non-zero and kerning-adjusted (`< ` sum of raw
  advances where the face has an AV kern pair); atlas packs N distinct glyphs without
  overlap (UV rects disjoint); repeated `measure` of the same string is deterministic.
- **Python unit (pytest):** with `_dauntless_host` absent, `CreateFontGroup`/`SetFont`/
  `GetStringWidth` still work via fallback (no import error, no `_Stub` leakage);
  `walk_paragraph` emits well-formed text-run tuples; `SetFont` actually stores the group;
  `SetSpaceWidth` override changes measured width.
- **Gate:** run `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against
  `tests/known_failures.txt`). No new failures beyond the baselined 7 headless-GL frame
  tests.
- **End-to-end (the real proof, manual):** `./build/dauntless --ui-harness` (or
  `--no-cef --ui-harness`) opens a window showing real Antonio-shaped text; the
  `CEF: framework not loaded` line prints; the `!!! CEF CONSTRUCTED` guard line never
  prints. Verified on Mark's machine (no synthetic desktop interaction; no full-screen
  capture — per standing constraint).
- **Useful-failure protocol:** if the harness crashes or renders nothing, record the exact
  failing subsystem (missing GL state, uninitialized resource, an input/compositor step CEF
  had provided) and report it rather than working around it. That list is a primary
  deliverable.

---

## 8. Success criteria

1. `./build/dauntless --ui-harness` renders a live `TGParagraph` as real shaped Antonio text
   in a window. ✅ = behaviour **1 (Render)** demonstrated for text.
2. CEF is provably never constructed on that path (positive print present, guard print
   absent); `git`-level: CEF still linked, but not initialized.
3. The `TGFontGroup`/`TGFontHandle`/`TGFontManager`/`TGParagraph` public surface is
   unchanged for existing call sites; the running game and pytest suite are unaffected.
4. `scripts/check_tests.sh` is green (baseline failures only).

Behaviours **2 (input)**, **3 (focus)**, **4 (teardown)**, and **5 (event round-trip)** are
intentionally **not** in this spec — they require geometry/clickable widgets and land in
Spec 2.

---

## 9. Out of scope (→ Spec 2: `TGIconGroup` + geometry + full five behaviours)

- HarfBuzz shaping (fast-follow once complex text is needed).
- `TGIconGroup` real backend; `TGIcon_Create` / icon 200 (8×8 white block) tinted-quad
  rendering; `SizeToArtwork` real extents.
- Geometry/layout: `AddChild` offset composition down the tree, `AlignTo` one-shot corner
  snap, `SetPosition` + real `GetWidth`/`GetHeight`, `SCREEN_WIDTH - GetWidth()` anchoring.
- `TGPane` + two `STButton`s + label; mouse hit-testing (route engine-polled clicks to the
  pane); Tab focus traversal (`MoveFocus`, `IsInTrueFocusPath`, real `GotFocus`/`LostFocus`
  on widgets); `KillChildren` + rebuild.
- Glyph-atlas resize/eviction; multiple font weights/styles; sub-pixel/gamma-correct AA.

---

## 10. Open questions / risks

- **FreeType FetchContent build weight** on the target toolchain (macOS + `uv` Python). Risk
  is low (FreeType is highly portable, no required deps when built bare) but is the first
  net-new native dependency added this way besides the big three.
- **Antonio relocation vs reuse:** copying to `native/assets/fonts/` vs loading from
  `native/assets/ui-cef/fonts/`. Reuse is functionally fine; relocation is cleaner for the
  "CEF-independent" story. Chosen: relocate/copy.
- **Coordinate origin:** BC uses top-left, normalized-in-parent offsets. Spec 1 uses pixel
  coordinates in the draw-list for simplicity (single paragraph, no nesting depth that
  matters); Spec 2's `AddChild` composition will formalize the normalized→pixel resolution.
- **`SetSpaceWidth`/`SetHorizontalSpacing` are additive**, not preserved — a small deviation
  from "pure interface preservation" forced by the tree never having defined them.
