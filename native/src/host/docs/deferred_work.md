# Renderer Host — Deferred Work

This file mirrors the "Deferred / future work" section of the design spec at
[`docs/superpowers/specs/2026-05-09-renderer-host-design.md`](../../../../docs/superpowers/specs/2026-05-09-renderer-host-design.md).

The spec is the authoritative source. Update both when items move on or off
the list.

## Spec items

1. **Skybox path lookup from mission/system config.** ✅ Implemented
   2026-05-10 as a multi-layer backdrop system rather than a single-NIF
   skybox slot. See
   [`docs/superpowers/specs/2026-05-10-skybox-backdrops-design.md`](../../../../docs/superpowers/specs/2026-05-10-skybox-backdrops-design.md).

   - Phase-1 shim (`engine/appc/backdrops.py`) materialises BC's
     `App.StarSphere_Create()` / `App.BackdropSphere_Create()` /
     `pSet.AddBackdropToSet(obj, name)` calls into `SetClass._backdrops`
     (insertion order = draw order).
   - `engine/host_loop.run` resolves the active set each tick via
     `_resolve_active_set` (shared with lighting), aggregates backdrops
     into a flat descriptor list, calls `r.set_backdrops(...)`.
   - `BackdropPass` (`native/src/renderer/backdrop_pass.{h,cc}`) draws
     the list with depth-write off, depth-LEQUAL, view-translation
     stripped (camera-anchored position, world-locked orientation);
     per-backdrop blend mode (opaque for StarSphere,
     `GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA` for BackdropSphere); shared
     procedural UV-sphere mesh cache + per-texture cache.
   - **NIF-skybox parsing was deliberately NOT part of this work** — BC
     ships no skybox NIFs (`tools/pick_default_skybox.py` only matched
     starbase NIFs by name; tool removed by this commit).

   Follow-up backlog:

   - **Lens-flare rendering.** Used by
     `Tactical.LensFlares.YellowLensFlare(pSet, pSun)`; scoped into
     sub-project #3 (sun + planet rendering).
   - **Backdrop animation.** No stock content uses rotating nebulae;
     cosmetic future option.
   - **Cubemap path.** Higher-detail starfields via cubemaps; mod
     territory.
2. **BC light data interpretation.** ✅ Implemented 2026-05-10.
   See [`docs/superpowers/specs/2026-05-10-bc-light-data-design.md`](../../../../docs/superpowers/specs/2026-05-10-bc-light-data-design.md).

   - Phase-1 shim (`engine/appc/lights.py`) materialises BC's
     `LightPlacement` / `Config*Light` / `pSet.Create*Light` calls into
     `SetClass._lights`.
   - `engine/host_loop.run` resolves the active set
     (`g_kSetManager.GetRenderedSet()` → player's set → None) each tick,
     aggregates 1 ambient + up to 4 directionals, calls
     `r.set_lighting(...)`.
   - `opaque.frag` consumes the ambient + directional array.

   **NIF-block light parsing is intentionally not part of this work** — a
   binary survey of all 93 NIFs in the repo (`game/data/` + `sdk/Art/`)
   found zero `NiAmbient*` / `NiDirectional*` blocks. Stock BC stores no
   lighting in scene NIFs.

   Follow-up backlog:

   - **Bridge & cinematic light rendering.** ✅ Resolved 2026-05-15 by
     the [bridge-lighting-materials work](../../../../docs/superpowers/specs/2026-05-15-bridge-lighting-materials-design.md).
     `BridgePass` + `bridge.{vert,frag}` / `lightmap.{vert,frag}` ship
     the visual; `engine/appc/lights.py:aggregate_bridge_for_renderer`
     plumbs bridge-set ambient through `r.set_bridge_lighting`. The
     `CreateAmbientLight` 4th-arg was decided as a dimmer **clamped to
     [0, 1]** — see new follow-up item below.
   - **`AddIlluminatedObject` per-object filtering.** Phase 1 ignores
     it; lights affect every object in the set. Becomes relevant when
     characters render.
   - **Save/load coverage of `Light` and `SetClass._lights`.** Tracked
     under "Save/load coverage of render state" (existing item #15).
   - **Point/spot light support.** No stock content uses them. The NIF
     parser already understands `NiPointLight` / `NiSpotLight` block
     types for forward compatibility.
   - **Per-set lighting persistence across set transitions.** The
     pull-each-tick model re-aggregates every frame; cache by `_lights`
     identity if profiling later shows it matters.
3. **Sun rendering.** ✅ Implemented 2026-05-10.
   See [`docs/superpowers/specs/2026-05-10-sun-rendering-design.md`](../../../../docs/superpowers/specs/2026-05-10-sun-rendering-design.md).

   - `aggregate_suns_for_renderer` (`engine/appc/planet.py`) collects `Sun`
     objects from all sets into descriptor dicts (position, radius,
     base_texture_path, corona_radius).
   - `engine/host_loop.run` calls `_aggregate_suns()` + `r.set_suns(...)` each
     tick, between `set_backdrops` and `frame()`.
   - `SunPass` (`native/src/renderer/sun_pass.{h,cc}`) draws each sun as an
     opaque UV-sphere (unlit, full MVP, scaled to radius) followed by an
     additive corona shell when `corona_radius > radius`.

   Follow-up backlog:

   - **Lens-flare rendering.** `Tactical.LensFlares.YellowLensFlare(pSet, pSun)`
     needs a screen-space sprite pass. Already noted under backdrop sub-project.
   - **Sun as a light source.** BC's directional lights come from
     `LightPlacement` objects, not the `Sun` object. Wiring Sun position into
     a directional is a future quality-of-life improvement.
   - **Animated / dedicated corona texture.** The corona currently reuses the
     body texture with a latitude fade. The `_flare_texture` arg from
     `Sun_Create` is already stored on the instance for when this is revisited.

4. **Animation playback.** Evaluate `AnimationClip` data already present
   in `Model` (asset pipeline produces it; renderer ignores it).
5. **Skinned-mesh rendering.** Bone palette uniform, vertex skinning in
   the vertex shader, evaluation against `Skeleton` data already in
   `Model`. The opaque shader currently has the bone_indices /
   bone_weights vertex inputs but ignores them.
6. **LOD selection.** Depends on asset pipeline populating
   `Mesh::lod_chain` first (asset pipeline deferred-work item #1). v1 uses
   `FilenameHigh` for every ship.
7. **Frustum culling.** Sphere-in-frustum test once scene-instance count
   grows beyond a few dozen. Requires the asset pipeline to produce
   per-`Model` bounding volumes; cross-cutting work into the asset
   pipeline. The `Camera::view_matrix` / `proj_matrix` infrastructure in
   v1 is already sufficient to derive frustum planes when needed.
8. **Decoupled render thread / interpolation.** Off-table for v1,
   available if profiling later shows headroom problems.
9. **Render targets / framebuffers / post-processing.** Required for
   bloom, motion blur, etc.; none of these are v1 surface.
10. **Debug fly-around camera** (mouse + WASD). Needs an input-binding
    layer.
11. **In-game camera modes** (tactical, bridge, external orbit,
    cinematic). Each needs its own camera-state machine and BC-config
    interpretation.
12. **HUD and UI.** Separate sub-project entirely; not part of any item
    in the renderer breakdown.
13. **Procedural FX** (explosions, weapon fire, warp trails). Gap analysis
    confirms runtime-procedural; will need its own renderer pass and
    particle system.
14. **Hardpoint-marker / damage-node interpretation.** The rest of item 6
    in the renderer breakdown.
15. **Mod / asset-overlay support.** Depends on asset pipeline gaining
    the same (asset pipeline deferred-work item #6).
16. **Save/load coverage of render state.** Phase 1 concern; render state
    is rebuilt at load from Python ship state, but the seam needs to be
    formalized once Phase 1 save/load lands.
17. **BC input system integration.** Keyboard/mouse/joystick mapping
    matching BC's input scheme, distinct from the v1 fixed third-person
    camera.
18. **Read turn rate / max impulse from BC config.** `_PlayerControl`'s
    `TURN_RATE_RAD_PER_S` (1.5) and `IMPULSE_UNIT` (50.0) are tuned by
    feel; they should come from the ship's `ImpulseEngineSubsystem`
    properties or `GlobalPropertyTemplates.py` once Phase 1 wires those
    up. Same for `REVERSE_LEVEL`.
19. **Switch to physics integration.** When `engine/physics/simulation.py`
    gets a real PyBullet integrator, `_PlayerControl.apply` should set
    target velocity / target angular velocity on the ship's impulse
    subsystem instead of writing the transform directly.
20. **BC config-file keybindings.** Read user-customized bindings from
    `data/scripts/Custom/Bridge/Keymap.py` (or wherever BC stores them)
    so players who remap keys see those bindings honored.
21. **Mouse input.** Stock BC supports yaw/pitch via mouse-look; v1 is
    keyboard-only.
22. **Acceleration / deceleration curves.** v1 sets impulse level
    instantaneously; BC ramps. Adding ramps depends on item 19 above.
23. **Auto-damping toggle.** Some space sims auto-damp angular velocity
    when no input is held; v1 doesn't (release = stop turning, but no
    re-centering).
24. **Bloom pass over ship glow lights.** The glow stage now lights up
    window/engine/nacelle pixels via `glow.rgb * glow.a` in the opaque
    shader (`opaque.frag`), but those pixels are LDR and not blurred.
    Adding bloom would: (a) render the opaque pass into an off-screen
    FBO (or use MRT to capture the glow term separately), (b) Gaussian-
    blur a bright-extract or the glow channel via ping-pong half-res
    FBOs, (c) composite back to the backbuffer. Most of the FBO ping-
    pong scaffolding was prototyped for the sun corona before being
    reverted (commit `72d91aa`); recoverable. Depends on item 9.

25. **Strip the space pass when bridge view is active.** The space
    render path (backdrops, sun, opaque-in-Space, shield, dust, lens
    flares, torpedoes, phasers, hit VFX) currently runs every frame
    even when the bridge pass is the only thing the user sees
    (`host_bindings.cc::frame` lines ~263-271 explain why). Deferred
    until the viewscreen-as-RTT work (item 26) lands — that work needs
    the space pass running so it can target the viewscreen surface;
    stripping it now would force adding a "render space here" path
    that doesn't otherwise exist.

26. **Viewscreen-as-render-target.** Render the space scene into the
    `DbridgeViewScreen.NIF` surface so the bridge's main screen shows a
    live view of the outside world. Pulls in framebuffer / render-
    target plumbing. Unblocks item 25.

27. **Animated bridge state.** Red-alert ambient dim is wired
    (`engine/host_loop.py:_aggregate_bridge_lights` scales the ambient
    to 50% when `player.GetAlertLevel() == 2`); BC's emissive
    convention (`Material::emissive == (1,1,1)` for 22 light-fixture
    materials in DBridge) keeps the ceiling panels bright through the
    dim. Still TODO:
    - Pulsing red emergency-strip lights on the walls during red
      alert. Would need either a separate bridge pass with a
      pulsing additive tint over specific shapes, or a per-material
      `pulse_phase` uniform driven from a time uniform.
    - Yellow-alert tinting (currently no visual change).
    - Viewscreen flicker / station-screen content updates.

28. **Per-ship-class bridge variants.** DBridge is hardcoded in
    `host_loop.py:502`; other classes (FBridge, EBridge, KBridge,
    BBridge, RBridge) have their own NIFs that should swap based on
    the player ship's class.

29. **Bridge characters / skinned animation.** Crew at stations.
    Depends on item 5 (skinned-mesh rendering).

30. **Specular / glow on bridge geometry.** Not authored in stock
    content; relevant if mods add it. Would need `bridge.frag`
    extensions and a glow-stage pass over `Material::stages[Glow]`.

31. **Per-LCARS-panel alpha-test threshold tuning.** Currently 0.5
    hardcoded in `bridge.frag`. Surface as a per-material override
    (e.g. `Material::alpha_test_threshold` is already populated from
    `NiAlphaProperty`; wire it into the shader) if specific panels
    need tuning.

32. **Cleanup: drop `Material::lightmap_pass` + `lightmap.{vert,frag}`.**
    These were the original design's "tag lightmap shapes + render
    them via multiply blend" mechanism. The final design (Dark-slot
    lightmap with two-UV composite in `bridge.frag`) doesn't need
    either: the lightmap goes to `StageSlot::Dark` and the bridge
    shader samples it via `u_dark_map`. `lightmap_pass` is now 0 for
    every material in DBridge, and `Pipeline::lightmap_shader()` is
    never bound. Removing both reduces surface area; gated on
    confidence that no other content needs them.

33. **`CreateAmbientLight` 4th-arg true semantics.** The chosen Phase 1
    interpretation (clamp dimmer to [0, 1]) matches visual expectations
    for stock content; the ground truth (range vs dimmer vs something
    else) is still unconfirmed and may matter for non-stock content.
    See `engine/appc/sets.py:CreateAmbientLight` for the chosen
    behaviour and rationale.

34. **Bridge SFX one-shots.** `engine/audio/bridge_ambient.py` wires
    the looping `AmbBridge` to view-mode toggle, but BC's
    `LoadBridge.LoadSounds()` (sdk/.../LoadBridge.py:349-379)
    registers more bridge sounds that aren't yet wired:
    - `RedAlertSound` / `YellowAlertSound` / `GreenAlertSound`
      one-shots when `SetAlertLevel` changes (registered as default
      sounds; just needs a transition hook).
    - `CollisionAlertSound` (sfx/critical.wav) — looping when hull is
      critical.
    - `ConsoleExplosion1..8` — random pick when consoles take damage.
    - `InSystemWarp` (sfx/Bridge/bridge_loop_warp.wav) — looping
      while at warp.
    - `ViewOn` / `ViewOff` (sfx/hail.wav, sfx/ViewscreenOff.WAV) —
      pair with the viewscreen-RTT work (item 26).

35. **Bridge camera pose tuning.** Eye is currently anchored at
    `(0, 50, 47)` with initial yaw=π (forward = -Y) — values copied
    from MissionLib's `CameraObjectClass_Create(0, 50, 47, -1.55,
    0, 0, 1)` and tuned visually. User noted slight misalignment
    vs the BC original. The MissionLib pose is axis-angle (angle
    -1.55 rad around +Z); the Gamebryo NiCamera default forward
    convention that combines with this rotation hasn't been
    cleanrooomed yet, so the eye/forward defaults are a best-guess.
    Tracked in `engine/host_loop.py:_BridgeCamera`.

36. **DBridge mesh has mixed face winding.** Workaround: bridge pass
    disables back-face culling (`bridge_pass.cc`). Sub-percent
    fillrate overhead at most; not worth fixing unless something
    weird shows up. Documented here so a future "why is bridge cull
    state different from the rest of the pipeline" question has an
    answer.

37. **Red Alpha Glow / red-alert strip lights.** BC modding lore
    references a "Red Alpha Glow" convention for the pulsing red
    emergency-strip-lights effect during red alert
    (https://www.bc-central.net/forums/index.php?action=printpage;topic=8210.0,
    listed under future tutorial topics). The naming hints at a
    red-channel-+-alpha texture overlay rather than per-material
    emissive pulsing. Mechanism not fully documented in the excerpt
    we have; would need a NIF-data survey + visual reference from
    the original game to confirm. Part of deferred item 27.

38. **Bridge door animations.** DBridge.NIF contains 12
    NiKeyframeController + 12 NiKeyframeData blocks — almost
    certainly the door open/close animations (5 doors × 2 leaves =
    10, plus a couple more). Our asset pipeline already builds
    AnimationClips into `Model::animations` but the renderer ignores
    them. Wiring this is animation-playback general work (deferred
    item 4 from the renderer-host spec) — once that lands, bridge
    doors and ship engine flares (which use the same controller
    type) come along for free. Also a prerequisite for crew
    animations (item 29) since the crew walks need synchronised door
    state.

## Conventions worth recording

(Sourced from `BRIDGE MODDING 101` tutorial — useful invariants for
future asset-pipeline / renderer work.)

- **Bridges are authored around world origin (0, 0, 0).** Our
  bridge-local frame in `_BridgeCamera` matches this.
- **Lightmap UV is 3ds Max "Channel 2"**, which is UV set 1 (0-indexed)
  in NIF / GL. `Vertex.uv1` consumes this.
- **Lightmap textures use the `_lm` or ` lm` suffix** and ride in
  the 3ds Max Self-Illumination map slot during authoring; the BC
  exporter funnels these into NiMultiTextureProperty stage 0 with
  uv_set=1. Our `apply_multi_texture_property` routes that to
  `Material::stages[Dark]`.
- **Texture dimensions must be powers of 2.** Common sizes: 256×256,
  512×512, 1024×1024. Lightmaps for large surfaces (floors, walls,
  ceilings) typically 1024+. Smaller textures (8×8 minimum) keep
  load times down for plain-color regions.
- **Lightmap rendering convention in Max**: usually a single omni
  light at default level (1.0) with Adv Ray Traced shadows. Bake
  produces the `_lm.tga` files. This matches the visual we see —
  baked shadows from a single overhead source.

## v1 deviations from the original plan

These are things the implementation found that the plan didn't anticipate;
captured here so future contributors don't re-discover them.

- **`-force_load,$<TARGET_FILE:nif>` required on host targets.** The NIF
  block parsers self-register via static initializers. Without
  force-loading the nif archive into both the `_open_stbc_host` module
  and the `open_stbc_host` executable, the linker drops the unreferenced
  object files and the registrations never run; `model_build` then
  throws "no NiNode root in NIF file" on every load. The same pattern
  was already used by `nif_tests` and `assets_tests`. See
  `native/src/host/CMakeLists.txt`.

- **`<pybind11/stl.h>` required for STL conversions.** pybind11's
  `std::vector<float>` / `std::tuple<float,float,float>` automatic
  conversions need this header at the binding-module's translation unit.
  Missing it produces a runtime `TypeError: incompatible function
  arguments` on first call, not a compile error. See
  `native/src/host/host_bindings.cc`.

- **`Development.Embed` (granular form) required.** CMake's legacy
  `find_package(Python3 ... COMPONENTS Development Embed)` (two separate
  components) fails on macOS Python.framework. The granular
  `Development.Embed` works because it lets CMake match the framework
  bundle. See `native/CMakeLists.txt`.

- **Top-level `cmake -S . -B build`.** The README's `-S native -B build`
  example skips the project's top-level `CMakeLists.txt` (which wraps
  `native/`). The docs and the plan have been corrected. Asset tests
  reference `${CMAKE_SOURCE_DIR}/native/src/assets/src` which only
  resolves correctly when `CMAKE_SOURCE_DIR` is the project root.

- **White-fallback texture in `FrameSubmitter`.** Originally added because
  Galaxy.nif's materials returned `stages[Base].texture_index = -1` from
  the asset pipeline. That asset-pipeline gap was fixed 2026-05-09 (see
  `native/src/assets/docs/deferred_work.md` item #19) and the Galaxy now
  renders with real BC textures. The white-fallback is kept as
  defensive logic for materials that legitimately have no Base-stage
  texture (procedural surfaces, etc.) — without it, GL's zero-texture
  produces black pixels and the lighting math is wiped out.

- **`SetClass.GetNextObject` wraps around.** The Phase 1 set iterator
  returns the first object after the last (mirroring BC's iteration
  semantics). A naive `while obj is not None` loop infinite-loops on a
  populated set. `engine/host_loop.py:_iter_set_objects` detects the
  wrap-around by comparing object IDs against the first object's ID.

- **No skybox NIF in BC assets.** `tools/pick_default_skybox.py` returns
  starbase NIFs (matching "star" in the path) because BC's skybox is
  procedural, not a NIF. v1 leaves `DEFAULT_SKYBOX_NIF = None` and the
  skybox pass is a no-op. Real skybox lookup → procedural starfield is
  spec deferred-work item #1.
