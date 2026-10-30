# Bridge Lottie panels — design

Status: draft, awaiting Mark's approval (2026-10-28). Open questions answered.
Extends: `2026-10-09-bridge-shape-diff-design.md` (§6 fix file `textures`, §11
runbook), `2026-10-08-bridge-emitters-spike-design.md` (§13-14 material
library, five bridge states, emission from `texture`), and the NiFlipController
support in `native/src/assets/src/flip_frame.cc`.

## 1. Intent

Animated LCARS panels on bridges are flipbooks today: N full-resolution frames
on the GPU, one picked per draw. That is nearly free per frame but scales as
frames × resolution, so smooth motion at modern resolution is out of reach (a
2048² MSD with a 30-frame loop would be ~640 MB of GPU memory). Most LCARS
animation is a few vector primitives moving over static artwork: a pulse
travelling along a stroke, a light sliding along a strip, blinking lights,
scrolling numbers.

**Goal:** Mark authors a bridge panel's animation as a **Lottie** file in
Glaxnimate; the engine plays it with **ThorVG** into a live texture that the
bridge pass draws like any other albedo.

Why Lottie + ThorVG (decided with Mark 2026-10-28): Lottie is the animated
vector format with real native players; animated SVG (SMIL/CSS) has none
outside a browser. ThorVG is a small MIT C++ renderer that plays Lottie (Godot
uses it for SVG). Glaxnimate imports SVG (static and SMIL), edits, and exports
Lottie.

### 1.1 Spike evidence (2026-10-28, throwaway, scratchpad only)

A hand-written Lottie of the DBridge running light (block 688, today the
12-frame `running_0..11` 64×32 flipbook at 5 fps) was rendered with ThorVG
(`thorvg-python` bindings, software engine, one thread):
- matched the stock-overlay frames' positions at every 0.2 s step, moving
  sub-pixel in between;
- 2.3 KB minified JSON vs 52 KB of TGAs;
- draw cost incl. pixel readback: 0.05 ms at 256×128, ~0.5 ms at 1024×512,
  ~1.8 ms at 2048×1024 (a 3-shape file; a busy MSD will cost more —
  unmeasured);
- Glaxnimate 0.6 imported it and re-exported Lottie that ThorVG renders
  identically except sub-pixel position rounding on in-between frames.
  Glaxnimate keeps ONE set of gradient stops (colour and opacity share
  offsets), so non-Glaxnimate files with separate opacity stops shift slightly
  on import;
- ThorVG exposes marker segments (`set_marker` / `get_marker`), but
  **Glaxnimate 0.6 does not keep Lottie markers**: a file with two markers
  re-exported with none, and its native `.rawr` save carries no trace of them
  (builder check, 2026-10-28). Per-state animation therefore lives in
  separate files, one per state (§5).

Mark opened it in Glaxnimate and judged it close enough to proceed.

## 2. Goals, non-goals, anti-goals

Goals
- A `<stem>.json` Lottie beside a bridge albedo `<stem>.tga` makes that albedo
  animate in game, for stock textures (overlay) and diff-tool albedos alike.
- Per-state animation, one file per state (§5).
- Glow, bloom and reflections follow the animation through the existing
  material path (emission source `texture`), with no new material concept;
  static `_emissive*` siblings are set aside on animated panels (§4).
- Runtime cost small enough for the 4K bridge (§7 budget).
- A dev reload so Mark can iterate Glaxnimate → game without restarting.

Non-goals (v1)
- Ships, comm sets' own panels beyond what the shared bridge pass draws (§8),
  any non-interior load. Ship loads stay byte-identical.
- Footprint-driven resolution (fixed per-file size in v1, §6).
- dotLottie (`.lottie` zip), Lottie expressions, external image/font assets.
- Authoring UI in the bridge editor.
- A per-frame upload budget (§6): v1 ships one panel, which cannot stack
  uploads onto one frame. Added when a second animated panel is authored.

Anti-goals (fail even if it "works")
- A Lottie panel that hitches the frame when it redraws.
- Any change to production rendering of a bridge with no `.json` siblings.
- A broken or unsupported file that shows garbage instead of the still image.

## 3. Authoring contract (what Mark produces)

Two files with one stem, plus optional per-state files (§5), in the bridge's
texture directory under the replacements overlay (e.g.
`native/assets/replacements/data/Models/Sets/DBridge/High/`):

| File | Role |
|---|---|
| `<stem>.json` | Lottie (Bodymovin JSON) exported from Glaxnimate. What the game plays by default. Required. |
| `<stem>_y.json`, `<stem>_r.json`, `<stem>_s.json` | Optional: what the game plays at yellow alert, red alert and the special state (§5). |
| `<stem>.tga` | A still of the same panel. What Blender shows, what the diff tool checks, and the in-game fallback. |

- **Blender / diff tool: unchanged.** Point the object's Base Color at
  `<stem>.tga`, UV the faces onto it (the Lottie canvas covers the same 0-1 UV
  square), run the diff as usual. The fix's `textures` op splices the albedo
  into the NIF before `build_model` (`AssetCache::load`), so the loader's
  sibling probe (§4) sees it like a stock texture.
- **Stock textures:** dropping `Map 7.json` beside the overlay's `Map 7.tga`
  animates that stock panel with no Blender round trip.
- **Replace or overlay — both work.** The live texture is the still, scaled
  to the live size, with the Lottie drawn over it. A Lottie with an opaque
  background (like the spike's black panel) therefore replaces the panel
  entirely; a Lottie with a transparent canvas adds motion over the existing
  raster artwork (e.g. a few blinking lights over a stock `Map 7.tga`). Output
  alpha is the still's alpha composited under the Lottie's, so a material
  with an `NiAlphaProperty` alpha-tests as it does with the still alone.
- Canvas aspect should match the UV region's aspect (and the still's);
  canvas units are arbitrary (the spike used 640×320 for a 64×32 texture).
- Self-contained files only: shapes, fills, strokes, gradients, transforms,
  trim paths, masks. Markers are ignored (Glaxnimate drops them anyway). Text converted to shapes; no image layers, no
  expressions. Glow is NOT painted into the Lottie: it comes from the bridge
  editor material (emission source `texture`) and bloom.
- Stem rules are the albedo rules (no reserved suffix: `_glow`, `_spec(ular)`,
  `_norm(al)`, `_emissive*`, `_rough`, `_metal`).

## 4. Loader

`native/src/assets/src/model_build.cc`, in the existing sibling-map probe
(`SiblingMapProbe`, `interior_sibling_policy`):

1. On **interior loads only**, for each external albedo image that is not a
   derived map, probe `<stem>.json` through the same `sibling_dirs_for`
   directory set as the other interior siblings, and beside it the state
   files `<stem>_y.json`, `<stem>_r.json`, `<stem>_s.json` (§5). Ship loads
   probe nothing new. State files with no `<stem>.json` warn once and are
   ignored.
2. Found → **always** create the live slot (steps 3-4), whether or not the
   file is valid, so the dev reload (§10) can recover a file that was broken
   at load. Parse it with ThorVG: it must load as a Lottie animation with
   non-zero size and total frames; anything else warns once per file
   (`[lottie] <path>: <reason>; using the still`) and the slot shows the
   still until a reload succeeds.
3. Create a **live texture**: a `Texture` of the v1 size (§6), initialised
   with the still composited under frame 0 (§3), appended to
   `Model::textures`. The material's Base slot points at it. The decoded
   `.tga` is kept CPU-side as the composite base and the fallback.
4. Record a `LottieTexture` entry: live texture index, source path, the
   ThorVG animation for the default file and for each state file found (or
   none for any that is invalid; an invalid state file warns once and that
   state falls back as if the file were absent, §5), canvas size, and each
   animation's frame rate. Cached models are
   `shared_ptr<const Model>` (`cache.cc:28-29`), so the mutable playback
   state (current state file, its start time, last drawn frame, worker job)
   lives OUTSIDE the model, in a renderer-side store keyed by (model, live
   texture index). The model holds only the immutable description.
5. **Static emissive siblings are set aside** on a material whose albedo has a
   live slot: the loader does not bind its `_emissive*` maps (one warning per
   file names the skipped siblings), so its glow can only come from the
   animated image via a bridge editor material with emission source
   `texture`. `engine/bridge_editor/glow.py:29` currently prefers an
   `_emissive` file whenever one exists on disk; it must apply the same rule
   (no `_emissive` preference when `<stem>.json` exists beside the albedo).
   Without an editor material the panel does not glow, exactly as a panel with
   no emissive map today.
6. **A Lottie wins over a NiFlipController** on the same material: the
   material's `animation_index` is cleared so `animated_base_texture` returns
   the live texture. (Today's `running_0..11` flipbook on b0688 is replaced by
   pointing its Base Color at `running.tga` and regenerating the fix; a
   `running_0.json` would also work under this rule.) Builder: log once when
   this happens.

The head-graft composition path (`model_compose.cc:250-253`) DROPS a grafted
head's flipbook (`animation_index = -1`); it drops a head's `LottieTexture`
the same way. Heads are characters, not bridge panels, so nothing is lost.

## 5. Bridge states → files

One Lottie file per state (Mark, 2026-10-28), named like the per-state
emissive maps (`_emissive`, `_emissive_y`, `_emissive_r`, `_emissive_s`):

| State | File played | Falls back to |
|---|---|---|
| green | `<stem>.json` | — |
| yellow | `<stem>_y.json` | `<stem>.json` |
| red | `<stem>_r.json` | `<stem>_y.json`, then `<stem>.json` |
| special | `<stem>_s.json` | `<stem>.json` |
| offline | `<stem>.json` | — |

The fallbacks are `bridge_emissive_texture`'s (`bridge_pass.cc:40`), so a
panel's artwork and its glow change state together. The renderer already
knows the state (`kBridgeState*`, the `emissive_alert` value in
`bridge_pass.cc`).

- Each file loops its whole timeline. Each is a complete animation: shared
  artwork is copied between files in Glaxnimate (the accepted cost of this
  choice).
- Every file is drawn at the live texture's size, set from `<stem>.json`'s
  canvas (§6). A state file whose canvas aspect differs warns once and is
  stretched to fit.
- Suffix letters are case-insensitive, like the emissive ones. Probing is per
  albedo: for `running.tga`, `running_y.json` is its yellow file. Avoid
  albedo stems that themselves end in `_y`, `_r` or `_s`.
- **Comm sets** always draw with state green (`bridge_pass.cc:336-337`), and
  their panels play `<stem>.json` accordingly.
- **On a state change the new file starts from its first frame** (Mark-
  delegated call, 2026-10-28). The bridge editor's Transition modifier still
  fades emission across the change; the artwork itself cuts.
- The bridge editor's State and Animation modifiers multiply on top as for any
  material, so a panel can dim or pulse per state without a state file.
- Offline keeps its existing emission behaviour (`bridge_pass.cc:256`); the
  albedo plays `<stem>.json`. (No offline file, as there is no offline
  emissive; added if Mark wants one.)

## 6. Resolution and redraw

- **Size:** the canvas aspect, longest edge capped by Bridge Quality
  (`renderer/bridge_quality.h`): Low 512, Medium 1024, High 2048, and also by
  the canvas itself: no more than **2× the canvas's long edge**, never below
  512 (`lottie::panel_edge_cap`). Recomputed when Bridge Quality changes
  (texture reallocated). A 640×320 strip is therefore 1024×512 at Medium and
  1280×640 at High; a 512×512 trace is 1024×1024 at Medium and High. (The cap
  was added after the conn/ops measurement, 2026-10-28: High drew that 512²
  canvas at 2048², ~45 ms per raster.)
- **One panel per file:** images naming the same resolved albedo share one
  panel (one raster, one upload). A mesh fix's per-shape albedo op gives each
  shape its own NiImage, which made DBridge's two conn/ops tops two panels.
- **Mipmaps:** panels keep a full mip chain (they are seen at grazing
  angles), built on the worker -- a rounded 2×2 box filter over only what a
  change reaches -- and uploaded with each result. The render thread never
  calls `glGenerateMipmap`: live on this Mac it cost 5-10 ms a call
  (perf-register SIG-150).
- **Clock:** the bridge pass's `wall_time_`, which `host_loop.py` feeds from
  `GetGameTime()`, so panels freeze under pause exactly like today's
  flipbooks. Local time = (t − time the current state's file started) mod that
  file's length.
- **Redraw only when needed:** a live texture redraws when (a) its file-
  local frame number has changed since the last draw, at the file's own frame
  rate **capped at 30 Hz** (Glaxnimate files are often 60 fps; LCARS motion
  reads the same at 30), AND (b) its model was drawn by any `BridgePass` draw
  last frame (main view or a comm set seen in the viewscreen feed). Panels on
  a hidden bridge (exterior view) cost nothing. Per-panel visibility culling
  is the builder's call (nice-to-have, not required).
- **Partial uploads (instead of an upload cap):** the worker keeps each
  panel's last composite and returns only the rectangle that changed since
  its previous result, or nothing when the frame is identical (a held
  keyframe). The render thread `glTexSubImage2D`s just that rectangle. A
  result that is not uploaded (texture reallocated, entry not playing) makes
  the next job ask for the whole frame, so the texture never falls behind.
- **Never write a texture the GPU may still read (added 2026-10-30, after
  the back-wall panel):** each panel rotates through three textures. An
  upload writes the next in turn, and only once a GPU fence says every frame
  that drew it has finished; otherwise the result waits a frame (never a
  blocking wait, and the poll never forces a flush -- that alone cost 9-34 ms
  a frame live, SIG-153; the frame's swap sends the fence). The job carries what that texture lacks (`also`), and the
  others fall behind only by what changed. Uploads go straight from client
  memory: through a pixel-unpack buffer the same uploads stalled 20-37 ms a
  frame at 4K (SIG-151).
- **Threading (v1, not later):** ThorVG rasterises on a worker thread into a
  CPU buffer for the NEXT frame; the render thread only uploads
  (`glTexSubImage2D` of each level) at the start of the bridge pass. One
  frame of animation latency is accepted. A worker that has not finished keeps
  the previous image (never blocks the render thread). The existing
  `std::async` job patterns (`rock_speck.cc`, `structure_parts_cache.cc`) are
  the model; ThorVG's own task-scheduler thread count is the builder's call.
- Reflection probes capture whatever image is current, as with flipbooks.

## 7. Cost budget and measurement

- Target: the render thread's added cost on a bridge with all of Mark's v1
  panels animating is **≤ 0.3 ms per frame**; worker time is reported
  separately. This is a target, not a merge gate: a miss is recorded as a
  perf-register signal and brought to Mark with the numbers.
- New frame-profiler scope `bridge_lottie` around the uploads; worker
  raster time accumulated into a stderr line on the existing 120-frame report
  cadence.
- Measured once on Mark's DBridge with the running light (Debug build, compare
  like with like; `docs/reference/engine/perf-register.md` conventions), and
  recorded as a signal there.

## 8. Where it applies

- Every model loaded with `interior=True` and drawn by `BridgePass`: the
  bridge sets (DBridge, EBridge, mod bridges).
- Comm/viewscreen-feed sets load with `interior=True` but no
  `sibling_overlay_dirs` (`engine/host_loop.py:8812`), so `sibling_dirs_for`
  (`model_build.cc:139-148`) probes only beside an albedo that itself
  resolved into the overlay. A comm panel therefore animates only when its
  `<stem>.tga` is also in the overlay. That is accepted: §3 already requires
  the still beside the `.json`. Nothing is added for comm sets.
- Ships: not in v1 (Mark, 2026-10-28). The probe is behind
  `interior_sibling_policy`, so ship loads are untouched.

## 9. Dependency

- Vendor ThorVG sources into `native/third_party/thorvg/` with our own
  `CMakeLists.txt` (upstream builds with Meson only; Godot vendors it the same
  way). Build only the software raster engine and the Lottie loader; no SVG
  loader, no GL/WebGPU engines, no savers, no threads beyond what §6 needs.
- Pin a released version (the spike used the PyPI `thorvg-python` wheel's
  `libthorvg-1`); record it in the vendored directory's README.
- Licence: MIT. Add to `THIRD_PARTY_NOTICES.md` and the packaged notices the
  README audit set up.
- Must build on macOS, Linux and Windows like the other `third_party/`
  libraries.

## 10. Developer tooling

- Developer Options → Lighting → **Reload Bridge Panels**: re-reads every
  live slot's `.json` files (default and state files) from disk (keeping the texture), including slots whose
  file was invalid at load, so Mark can save in Glaxnimate and see it in
  game. A file that no longer loads reverts that panel to its still and warns
  once. It also re-probes the loaded bridge models' interior albedos for
  `.json` siblings **added since load** and creates slots for them (and sets
  aside their emissive siblings, §4 step 5). A `.json` deleted since load
  reverts its panel to the still; a state file added or deleted since load is
  picked up or dropped the same way.
- Python surface: one binding to trigger the reload; nothing else is exposed
  in v1.

## 11. Testing

Focused tests only (CLAUDE.md test gate). Fixtures are small Lottie files we
author (no BC content in the repo, shape-diff §6.2).

- Loader (`native/tests/assets/cpu/`): `.json` beside an albedo on an interior
  load → live slot + `LottieTexture`; same files on a ship load → nothing;
  invalid JSON / non-Lottie JSON → slot created, warns once, shows the still;
  Lottie + flipbook on one material → Lottie wins; emissive siblings beside a
  Lottie albedo are not bound (and `glow.py` agrees, Python test).
- Compositing: a transparent-canvas fixture over a still shows the still
  where the Lottie is empty; an opaque-background fixture hides it; output
  alpha = still alpha under Lottie alpha.
- States: state → file selection, including red → yellow → default and
  special → default; offline and comm sets → default; restart on state change;
  case-insensitive suffixes; an invalid state file falls back; a state file
  with no default file is ignored; a different-aspect state file warns once.
- Redraw scheduling: no redraw when the (≤30 Hz) frame number is unchanged or
  the model wasn't drawn; paused clock → no redraws.
- Reload: an invalid-at-load file fixed on disk recovers; a newly added
  `.json` gets a slot; a deleted one reverts to the still.
- Raster determinism: a fixture rendered at frame k matches a stored expected
  image within a tolerance (CPU, no GL).
- Headless GL: the live texture's contents change between two frame times and
  the render thread never waits on the worker.
- Python: the reload binding.

## 12. Acceptance

1. Mark replaces the DBridge running light (b0688) with `running.json` +
   `running.tga` and checks it in game against the flipbook. This is the only
   panel in v1 (Mark, 2026-10-28). A state file (e.g. a red `running_r.json`)
   is checked too if Mark authors one; otherwise state switching is covered
   by the tests alone.
2. §7 measurement recorded.
3. A bridge with no `.json` siblings renders byte-identically (existing bridge
   render tests stay green).

## 13. Decisions log

| Date | Decision | By |
|---|---|---|
| 2026-10-28 | Lottie authored in Glaxnimate, played with ThorVG, over animated SVG / CEF / a custom vector renderer | Mark |
| 2026-10-28 | Bridges only for v1 | Mark |
| 2026-10-28 | ~~Alert states via markers in one file~~ — dropped: Glaxnimate drops markers (§1.1) | Mark (on recommendation), superseded below |
| 2026-10-28 | Alert states as one Lottie file per state (`<stem>_y/_r/_s.json`) | Mark |
| 2026-10-28 | v1 is the DBridge running light only | Mark |
| 2026-10-28 | Upload budget deferred until a second panel exists | Claude |
| 2026-10-28 | State-file fallbacks copy the emissive maps' (red → yellow → default, special → default); no offline file | Claude |
| 2026-10-28 | Lottie drawn over the scaled still: opaque background replaces, transparent canvas overlays | Claude (builder check Q1) |
| 2026-10-28 | Static `_emissive*` siblings set aside on animated panels; glow only via emission source `texture` | Claude (builder check Q2) |
| 2026-10-28 | Redraw ≤ 30 Hz; 0.3 ms is a target, not a gate | Claude (builder check Q4) |
| 2026-10-28 | Slot always created when a `.json` exists; reload recovers, adds and removes | Claude (builder check Q5) |
| 2026-10-28 | Comm sets play green; redraw when their model was drawn in any bridge pass | Claude (builder check Q6) |
| 2026-10-28 | `<stem>.json` beside `<stem>.tga` at texture load, not a diff-tool field | Claude (Mark asked whether the convention works; not explicitly ruled) |
| 2026-10-28 | Restart from the first frame on state change | Claude (Mark delegated) |
| 2026-10-28 | Worker-thread raster in v1; Bridge Quality caps size; Lottie beats flipbook | Claude |
| 2026-10-28 | Vendor ThorVG with our own CMake | Claude |
| 2026-10-28 | One panel per resolved albedo; only changed rectangles uploaded; size capped at 2× the canvas (floor 512) — after the conn/ops measurement | Mark approved the three fixes; cap rule (2×, floor 512) is Claude's |
| 2026-10-30 | Worker-built mips; three-texture rotation behind GPU fences; no pixel-unpack buffer — after the back-wall panel took the bridge to ~23 fps live | Mark: "fix it"; the rotation and dropping the buffer are Claude's, from measurement |
