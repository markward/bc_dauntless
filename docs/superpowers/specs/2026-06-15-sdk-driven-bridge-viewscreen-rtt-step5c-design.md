# SDK-driven bridge init — Step 5c: viewscreen render-to-texture

**Date:** 2026-06-15
**Project:** SDK-driven bridge initialization (see
`docs/superpowers/specs/2026-06-15-sdk-driven-bridge-init-design.md`)
**Predecessors:** step 5b (viewscreen mesh, merged `39a7aac`)
**Status:** design approved, ready for implementation plan

## Context

Step 5b realized the viewscreen mesh (`DBridgeViewScreen.nif`, a single
"room screen" trishape) as a bridge-pass render instance that draws a blank
panel — the NIF has no authored base texture because the screen surface is the
render-to-texture *target*. Step 5c renders the live forward view of space into
that surface, so the bridge's main screen shows what's outside the ship. This is
deferred-work item #26 and unblocks item #25 (stripping the wasted space pass in
bridge mode).

### Renderer facts that shape the design (verified)

- **The space passes already run every bridge frame.** In bridge view,
  `host_bindings.cc::frame()` still runs the full space scene (backdrops, sun,
  opaque ships, shield, dust, lens-flares, torpedoes, phasers, hit-VFX) into the
  main HDR FBO, then the bridge pass `glClear()`s it away. A standing comment in
  `frame()` (~lines 379-381) explicitly preserved this so the RTT could "swap the
  space pass's target from main framebuffer to viewscreen texture without adding
  a render-space-here path that didn't exist before."
- **Every space pass takes its camera by `const scenegraph::Camera&` and renders
  to whatever FBO is bound** — no globals read inside the passes. Redirecting
  them to an offscreen target with a different camera is a call-site change in
  `frame()`, not a pass rewrite.
- **The bridge-mode camera is already the forward remote-cam.**
  `host_loop._compute_camera` (lines 2008-2014), bridge branch, returns
  `eye = ship world-loc`, `target = loc + ship-forward (rot.GetCol(1))`,
  `up = ship-up (rot.GetCol(2))`, and the host sends it to `r.set_camera(...)`
  (line 3085). So in bridge mode the renderer's space camera `g_camera` is
  *already* the forward-from-ship view. **No new camera, no new camera binding.**
  (The separate `g_bridge_camera` is the captain's-chair first-person view used
  by the bridge pass.)
- **The viewscreen is its own single-trishape instance** with a unique model
  handle (the host holds it from `_realize_viewscreen`'s `load_model`). So the
  feed texture is swapped per-**instance** by matching `inst.model_handle` — no
  per-mesh hunt inside a shared model.
- **Existing FBO infrastructure:** `HdrTarget` (RGBA16F color + depth24) with
  `resize()/bind()/color_texture()/fbo()`. Reusable verbatim for the RTT target.
- **`bridge.frag`** computes `FragColor = base.rgb * lm * max(ambient, emissive)`.
  BC treats console screens as `emissive=(1,1,1)`, so a full-bright draw of the
  viewscreen gives `FragColor = base` (the raw feed) regardless of bridge
  ambient. `draw_mesh` already sets `u_emissive` per material.

## Goal & scope

In bridge view, render the forward space scene into an offscreen HDR texture and
map it onto the viewscreen instance, so the bridge's main screen shows a live
picture-in-picture view of what's ahead. Honor on/off (`SetIsOn`), default-on at
realize.

**Why RTT is unavoidable:** the viewscreen is picture-in-picture — the bridge
interior and the screen are visible in the *same frame*. That is two renders to
two different targets per frame; the forward view must land in an offscreen
texture to be sampled by the screen surface. Camera-mode switching alone cannot
produce a picture-in-picture.

**In scope:**
- One offscreen HDR target; in bridge view the already-running space passes
  target it (using the existing `g_camera`).
- Per-instance texture override so the viewscreen instance samples that texture,
  drawn full-bright so the feed isn't dimmed by bridge ambient.
- Hide the player-ship instance while in bridge view (avoids the forward cam —
  which sits at the ship center — clipping through its own hull, and keeps the
  ship off its own screen).
- Honor on/off: feed when `vs.IsOn()`, else the 5b blank panel. Default-on at
  realize. (`GetRemoteCam`/`SetRemoteCam` stay as stored 5b state but are not the
  5c gate — the feed camera is the implicit reuse of `g_camera`, so there is no
  real remote-cam object headless to gate on.)

**Out of scope (deferred, genuinely-expensive content surface):**
- Comm/hail faces, static-texture variations, viewscreen menus, ViewOn/ViewOff
  sfx, viewscreen flicker — all need new asset/render paths.
- A viewscreen camera decoupled from the ship-forward axis (e.g. target-locked).
  YAGNI; reuse `g_camera`.
- Stripping the space pass in non-RTT cases / deferred item #25 (this step
  *enables* it but does not do it).

**Needs a full `dauntless` rebuild** (C++ + host_bindings.cc). `engine/appc/`
stays headless.

## Design

### 1. Offscreen target & frame() flow

Add one renderer global `g_viewscreen_hdr` — a second `HdrTarget` instance
(reuse the class verbatim) at a fixed resolution, named constants
`kViewscreenRttW = 640`, `kViewscreenRttH = 360` (16:9). Created in `init()`,
destroyed in `shutdown()`.

**Extract a helper** to avoid duplicating the space-pass list across the main
and RTT call sites:

```cpp
// Renders the space scene from `camera` into the currently-bound FBO.
// for_viewscreen=true skips cockpit/screen-space effects (see §2).
void render_space_scene(const scenegraph::Camera& camera, bool for_viewscreen);
```

`frame()` bridge-view branch becomes:

```
if (bridge view && viewscreen on) {
    g_viewscreen_hdr->resize(kViewscreenRttW, kViewscreenRttH);
    g_viewscreen_hdr->bind();                       // sets viewport to RTT size
    glClear(COLOR|DEPTH);
    render_space_scene(g_camera, /*for_viewscreen=*/true);   // forward feed
    g_bridge_pass->set_viewscreen_texture(g_viewscreen_hdr->color_texture());
} else {
    g_bridge_pass->set_viewscreen_texture(0);       // off -> blank 5b panel
}

g_hdr_target->bind();                                // restore main target
... (existing hologram/reticle) ...
glClear(COLOR|DEPTH);                                // existing bridge clear
g_bridge_pass->render(...);                          // viewscreen samples the feed
```

Non-bridge view: unchanged — `render_space_scene(g_camera, false)` into the main
HDR target exactly as today (the extracted helper wraps the existing pass list).
The RTT path is fully gated on bridge-view + on, so space/exterior rendering is
byte-identical.

### 2. Which passes feed the screen

`render_space_scene(camera, for_viewscreen)` runs, in order:
backdrops → sun → opaque(`Pass::Space`) ships → shield → torpedoes → phasers →
hit-VFX. When `for_viewscreen` is **false** it additionally runs dust →
lens-flares → particles (the current full list, unchanged for the main view).

The viewscreen feed **skips** dust (a camera-anchored cockpit smear that carries
cross-frame `prev_eye_` state — rendering it from a second camera would corrupt
that state and it makes no sense on a viewscreen), lens-flares (screen-space,
sized to the main framebuffer), and particles (cost; first cut). The result is
"the 3D world + weapons fire," tonemapped once by the main post-process.

### 3. Exposure — feed HDR directly

The viewscreen instance samples `g_viewscreen_hdr`'s **HDR** color texture as its
base; the bridge pass writes it into the main HDR target, and the single main
tonemap (resolve/bloom/FXAA) exposes it once. Feeding LDR instead would
double-tonemap (the feed would come out dark/desaturated). No intermediate
resolve/bloom pass for the RTT.

To stop bridge ambient from dimming the feed, the viewscreen draw forces
`u_emissive = (1,1,1)` (and binds the RTT texture as `u_base_color`), so
`FragColor = feed` — matching BC's `emissive=(1,1,1)` console-screen convention.

### 4. Per-instance texture override in `BridgePass`

`BridgePass` gains two members + a setter:

```cpp
ModelHandle viewscreen_model_handle_ = 0;   // set once by host at realize
GLuint      viewscreen_tex_          = 0;   // set per frame by frame(); 0 = off
void set_viewscreen_model(ModelHandle h);
void set_viewscreen_texture(GLuint tex);
```

In `walk_bridge_meshes` / `draw_mesh`, when the current instance's
`model_handle == viewscreen_model_handle_` **and** `viewscreen_tex_ != 0`, bind
`viewscreen_tex_` as `u_base_color` (texture unit 0) instead of the material's
base texture and set `u_emissive = (1,1,1)`. Otherwise the existing path runs
unchanged (→ 5b blank panel when off). Identifying by **model handle** (unique to
the loaded viewscreen NIF) avoids needing the InstanceId inside the pass.

GL types (`GLuint`) stay in the renderer layer (`BridgePass`); the scenegraph
`Instance` is untouched.

### 5. Host wiring + on/off

- **`engine/renderer.py`** — thin wrappers: `set_viewscreen_model(handle)`,
  `set_viewscreen_enabled(on)` (the renderer maps these to
  `BridgePass::set_viewscreen_model` and the frame()-internal texture wiring).
- **`_realize_viewscreen`** (step 5b) — after creating the instance, call
  `r.set_viewscreen_model(handle)` so the bridge pass knows which instance is the
  screen. (`handle` is already in scope.)
- **Per bridge frame** in `host_loop.run`'s render block — compute
  `on = bool(vs.IsOn())` for the realized viewscreen object and call
  `r.set_viewscreen_enabled(on)`. The renderer feeds the RTT texture when on, 0
  when off.
- **Default-on at realize:** `_realize_viewscreen` calls `vs.SetIsOn(1)` after
  creating the instance, so the feed shows on a fresh `LoadBridge.Load` (the SDK
  doesn't call `SetIsOn` on first load — see step 5b). Subsequent `SetIsOn(0)`
  from SDK/mission code blanks it for real.
- **Hide the player ship in bridge view:** in the render block, while
  `view_mode.is_bridge`, set the player ship instance invisible
  (`r.set_visible(player_iid, False)`); restore on return to exterior. The player
  ship is never shown in bridge mode anyway (the bridge pass draws only
  bridge-tagged instances), so this only affects the RTT feed — removing the
  ship from its own screen and avoiding near-plane hull clipping by the
  center-mounted forward cam. Mirrors the existing SPV hide/restore pattern.

## Testing

Focused files only. **Never** run the full suite (>100 GB RAM, freezes macOS) —
warn subagents.

GL/visual correctness is Mark's live-verify; the automatable surface is the host
wiring and the headless smoke path:

- **`tests/unit/test_viewscreen_rtt_host.py`** (new) — fake-renderer asserts:
  `_realize_viewscreen` calls `set_viewscreen_model(handle)` with the realized
  handle; default-on leaves the viewscreen object `IsOn()==1` after realize; the
  per-frame on/off computation calls `set_viewscreen_enabled(True)` when
  `vs.IsOn()`, `False` after `vs.SetIsOn(0)`; entering bridge view hides the
  player instance and exiting restores it.
- **Existing `tests/unit/test_realize_viewscreen.py`** (update) — extend the
  fake renderer with `set_viewscreen_model` and assert it's called once with the
  harvested handle (idempotency matrix unchanged otherwise).
- **Headless smoke (C++):** if a headless GL harness exists
  (`OPEN_STBC_HOST_HEADLESS=1`), a test that runs one `frame()` with the bridge
  pass enabled and a viewscreen model set does not crash and produces no GL
  error. If no such harness is practical, document the manual smoke step instead
  (do not fabricate a passing test).

## Verification, risks, rollback

- **Live verify (Mark drives):** `cmake -B build -S . && cmake --build build -j`
  (full rebuild — C++ + host_bindings.cc; a shader change would also need the
  `-B` reconfigure, but this step adds none). Run `./build/dauntless`, enter
  bridge view: the front screen shows a live forward view of space (stars, sun,
  any ships/weapons fire ahead); your own ship is absent; turning the viewscreen
  off (if a mission does) blanks it. Exterior view + space rendering unchanged.
  No synthetic desktop input / full-screen capture.
- **Risks:**
  - (a) The "room screen" UVs may not map 0..1 across the surface, distorting or
    cropping the feed — a NIF-coordinate finding to record, tuned by the fixed
    RTT aspect, not by inventing UVs.
  - (b) The forward cam at the ship center may still clip nearby geometry
    even with the player ship hidden (e.g. a docked ship); accepted for the first
    cut.
  - (c) RTT cost: the space scene now renders at `kViewscreenRtt*` every bridge
    frame — but it was already rendering (and being discarded) at full
    framebuffer size, so this is net-neutral-to-cheaper. Tune the constant if
    needed.
  - (d) If the viewscreen material is *not* authored `emissive=(1,1,1)`, forcing
    `u_emissive=(1,1,1)` for that draw guarantees the feed is full-bright
    regardless — intended.
- **No regression** to the SP1/SP2 renderer, the space/exterior path (gated), or
  steps 1-5b: the RTT path only runs in bridge view with the viewscreen on.
- **Rollback:** revert the branch; the FBO, helper, bridge-pass members, and host
  wiring are additive and gated. Rebuild.

## Follow-ups (not this step)

- **#25** — strip the space pass when bridge view is active *and the viewscreen
  is off* (now that a "render space here" path exists, the wasted-work case is
  removable).
- Rich viewscreen content: comm/hail faces, static, menus, ViewOn/ViewOff sfx,
  red-alert flicker.
- **5a** — SDK `ZoomCameraObjectClass` as the captain's-camera source of truth
  (the last bridge-load stub).
