# dauntless — Claude Context

## What this project is

Open reimplementation of the Star Trek: Bridge Commander (BC) engine, targeting modern operating systems. The long-term deliverable is a new C++ engine that runs BC's original Python game scripts without the original Windows-only `Appc.dll`.

The original engine is a compiled C++ binary exposed to Python via a SWIG-generated interface (`App.py`). Everything the game does crosses that boundary. The plan is to reverse-engineer and replace `Appc` with a modern, cross-platform C++ engine that embeds CPython.

## Current stage

**Phase 2 in progress.** Phase 1 (headless Python `App` shim, event system, timers, PyBullet physics, harness running SDK missions) is complete. Active work is the C++ engine + renderer: `native/` builds `build/dauntless`, with NIF asset loading, the renderer (sun, dust, glow via AddLOD), and the Python host loop driving SDK scripts. The instrumentation tooling in `tools/` remains available for the open Phase 2 questions.

## Implementation phases

**Phase 1 — Headless logic engine** ✅ complete
- Python shim for `Appc`
- Physics via PyBullet
- Event system, timers, sets, missions
- No renderer
- Runs SDK missions through the gameloop harness

**Phase 2 — Full C++ engine** (active)
- NIF renderer in `native/` (BC-specific block types; NifSkope has BC support)
- OpenAL audio
- Character animation
- CPython embedding via the host loop in `engine/host_loop.py` + `native/src/host/`

## Key reference material

| Resource | Location | Purpose |
|---|---|---|
| Appc interface spec | `sdk/Build/scripts/App.py` | Complete surface of every engine call — SWIG-generated, fully readable |
| SDK Python source | `sdk/Build/scripts/` | 1228 files; ground truth for all game logic |
| Physics parameters | `sdk/Build/scripts/GlobalPropertyTemplates.py` | Mass, rotational inertia per ship class |
| Ship hardpoints | `sdk/Build/scripts/ships/Hardpoints/` | Per-ship physics, weapons, arc geometry |
| Ship construction | `sdk/Build/scripts/loadspacehelper.py:54–135` | Integration point between Appc and physics |
| Mission lib | `sdk/Build/scripts/MissionLib.py` | Timer lifecycle, two-tier timer architecture |
| Gap analysis | `docs/gap_analysis.md` | 8 gaps, 26 open questions, solution paths |
| Open questions | `docs/open_questions.md` | 4 instrumentation questions — Q4 closed |
| Live game | configurable — see `engine/paths.py` | BC installation; location set via `--game-dir`/`DAUNTLESS_GAME_DIR`/`settings.json`, falling back to the in-project `game/` — needed for instrumentation |
| BC content paths | `engine/paths.py`, `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md`, `docs/superpowers/specs/2026-09-06-first-run-folder-picker-design.md` | Where `game/` and `sdk/` live. Five sources, **in precedence order**: a root picked in the first-run screen, `--game-dir`/`--sdk-dir`, `DAUNTLESS_GAME_DIR`/`DAUNTLESS_SDK_DIR`, `settings.json`, legacy in-project. The highest **set** one wins even when invalid. A pick outranks the CLI flag on purpose — it is the most recent explicit human act, and an invalid flag stays "set", so anything lower would lose to the very flag the screen exists to correct. Resolved at USE, never at import — a module-level constant is stale the moment the first-run picker changes a root. When no source resolves, boot hands off to the CEF-rendered "Select Bridge Commander Install" screen (`engine/ui/first_run_panel.py`, driven from `engine/host_loop.py`'s own pump loop before the game loop exists) rather than a bare dialog. Guarded by `tests/unit/test_path_indirection.py`. |
| Space dust pass | `native/src/renderer/dust_pass.cc`, `docs/superpowers/specs/2026-05-11-space-dust-particles-design.md` | Camera-anchored dust particles with motion smear; toggle via `_h.dust_set_enabled()` |
| BCS save format | `docs/engine/bcs-save-format.md`, `tools/bcs_inspect.py` | Real binary save format; preamble + object table + TGL + pickle-memo decoded; 93.6% object-state region remains as parking-lot RE work |
| AI surface & gaps | `docs/engine/aieditor-ai-surface-and-gaps.md`, `docs/engine/event-emitter-gaps.md` | What BC's `AIEditor` reveals about its AI: it is a code *generator* emitting `CreateAI(pShip)` Python that `engine/appc/ai.py` + `ai_driver.py` already run. Maps the 7 AI container types, 8 preprocessors and 34 Condition classes against ours. ⚠️ **Treat every ❌ in that doc as a hypothesis to re-check against `engine/`, not a fact** — an audit found several of its "confirmed gaps" already implemented. **Never use a `def <Name>(` grep to decide whether Appc surface exists**: SWIG binds most of the surface at module level via `new.instancemethod`, so that grep can never match, and it mis-attributes the receiver class. All 12 event-emitter gaps are now closed — `event-emitter-gaps.md` is the live register. Still genuinely open: partial collision avoidance (`ProximityManager_Update` is catalogued **stub**, body unreconstructed). |
| DamageTool & hull-damage gaps | `docs/engine/damagetool-and-hull-damage-gaps.md` | ⚠️ **Superseded** — its gaps were written against the voxel carve, which is **deleted**; current hull damage is the **Layered hull damage** row. Still the reference for BC's `DamageTool.exe` internals (RTTI-extracted): BC damage is a summed **metaball field** clipped by a `BinaryVoxel` hull mask. Authored volumes (`AddObjectDamageVolume`, the `Damage*.py` wreck scripts) and `AddDamage` now become ONE Internal record each in the layered store (`engine/appc/visible_damage.py`), sized by the volume radius × BC's `SetVisibleDamageRadiusModifier`; `SetVisibleDamageStrengthModifier` is stored only (it fed the carve). Verify via `--developer` → mission picker → **Developer → Damage Preview**. |
| Layered hull damage | `engine/appc/{hull_wear,hit_feedback,internal_blast,hull_breakup,plating_dials}.py`, `scenegraph/hull_damage.h`, `renderer/{plating_damage,hull_interior_pass,structure_parts_cache}.cc`, `shaders/{opaque,hull_interior,shadow_parts}.frag`, specs `2026-10-21-layered-hull-damage-production-design.md` §10 + `2026-10-22-layered-damage-p4-finish-design.md` | Replaces the deleted voxel carve. Hull damage dealt → wear records (64/instance, merged not evicted): plating strips, ribs snap, hull tears; rooms within 20 GU; past deck break, structure parts sever. ⚠️ Records in each part's REST frame (node −1 = body); per-mesh uploads filter by POSED OWNER. ⚠️ Rigged ships: flagged at realize (`set_instance_rigged`), never structure-sever. ⚠️ `.sps` parts cache keyed by NIF bytes + `kStructurePartsVersion`: bump on detection changes. ⚠️ Twins: `plating_part` (drift test), `plating_rim_heat`/`rim_heat` (by hand). ⚠️ `opaque.frag`: no new sampler, no early return. Dials: Developer Options → Hull damage; `/ L O` "plating". Perf: damaged ≤ 2× undamaged per pass, dying ≤ legacy death; DP `DAUNTLESS_DAMAGE_PREVIEW_FIRST_S`/`_SEED`; verdict P-12. ⛔ No merge to main without Mark. |
| **Perf cadences that are also GAMEPLAY latency** | `docs/engine/perf-cadences-and-latency.md` | Four things that used to run every tick now run on a cadence, and each is **also a behaviour change** — check here before reading a delayed in-game reaction as a bug. Shields charge every 0.5 s; the target list polls at 2 Hz; an evading ship re-decides avoidance at 4 Hz; a ship's AI tree may sleep up to 4 ticks (~66 ms), so `ForceUpdate` is no longer 'next tick'. ⚠️ The last two **COMPOUND** — avoidance now lives inside the sleeping AI tree — and **the combination has never been measured live.** ⚠️ Do NOT put a game-state mutation in `render_payload`: one there silently gave the player's phasers up to 0.5 s aiming at a destroyed subsystem. Both AI cadences are env-overridable, which is how you test whether a suspected latency bug is one of them. |
| **Frame profiler — MEASURE BEFORE OPTIMISING** | `docs/engine/frame-profiler.md`, `native/src/renderer/frame_timer.{h,cc}`, `engine/core/frame_profiler.py` | Per-pass CPU+GPU timing, both halves of the frame. Toggle: Developer Options → Diagnostics; stderr report every 120 frames. **Read the doc before drawing a conclusion from it** — a correct number is easy to misread (`present` may be the vsync wait; Python and render totals **nest, not add**; a stale module reports UNAVAILABLE). ⚠️ **GPU timer is chosen from the driver's counter bits.** This Mac's GL has a 0-bit `GL_TIMESTAMP`, so it uses non-nesting `GL_TIME_ELAPSED`: only **top-level passes** get GPU, nested rows print `-` (not measured), `frame` = their sum. ⚠️ **GPU timing is opt-in** (`DAUNTLESS_PROFILE_GPU=1`): it makes the CPU wait for the GPU (+~GPU frame time): no frame times from it (`perf-register.md` M-6). Nested GPU: `DAUNTLESS_PROFILE_GPU_FOCUS`. ⛔ Run via `./build/dauntless`, not python. ⛔ **CHECK THE SCENE LINE** — combat is 20-50× the idle sim cost, so use `DAUNTLESS_MISSION=engine.dev_missions.combat_stress`. Hitches: `DAUNTLESS_PROFILE_SPIKES=<path>` logs frames ≥ `DAUNTLESS_PROFILE_SPIKE_MS` (100) raw. |
| **Perf register — signals, then issues** | `docs/engine/perf-register.md`, logs in `~/Documents/dauntless-perf/` | Every open perf problem and the captured **signals** behind it, kept apart: a signal is what a capture showed (numbers + capture ID + evidence tier measured/derived/inferred), an issue is our reading of signals. Record counter-signals (what is cheap). Never edit an old signal to fit a new capture; add one. Baselines B1 (E1M2 Haven death), B2 (Felix: Destroy, 5 BoP vs a Sovereign) and B2d (B2, scripted kill) and B3 (Vesuvi Dust Cloud, parked: nebula + dust, few rocks) have exact commands there. ⚠️ Captures so far are a **Debug** build — compare like with like. ⚠️ A GPU-timed run is NOT a frame-time measurement (M-6); A-1 was that artifact and is closed. |
| Developer flag | `engine/dev_mode.py`, `native/src/host/developer_mode.{h,cc}`, `docs/superpowers/specs/2026-06-02-developer-flag-design.md` | Runtime `--developer` flag gating dev-only keybindings, pause-menu sections, renderer overlays, and CEF panels. Parse once in C++ (`host_main.cc`), read via `dauntless::is_developer_mode()` / `engine.dev_mode.is_enabled()` / `window.__DAUNTLESS_DEV__`. Exposed to Python as `_dauntless_host.developer_mode`. Register dev keybindings with `dev_mode.register_dev_keybinding(...)`; register dev pause-menu rows with `dev_mode.register_dev_pause_menu_entry(label, handler)`; wrap dev-only behaviour with `@dev_mode.dev_only`. CSS-hide CEF elements with class `dev-only`. |
| **Keyboard capture for CEF text fields** | `native/src/renderer/key_gate.{h,cc}`, `engine/ui/text_capture.py`, `native/assets/ui-cef/js/text_capture.js`, `docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md` | While an editable element in the in-game page has focus, the game reads **no keys at all**: `Window::key_state` filters every read through `KeyGate`, so the 60+ direct `h.key_*` call sites need no changes. ⚠️ **Never call `glfwGetKey` outside `Window::key_state` / `set_key_capture`** — `tests/tools/test_raw_key_reads.py` fails the gate. A key held when capture ends stays masked until released (the Esc/Enter that ended an edit is never a game press). Release triggers: page blur, native reset on load/crash, owner panel closed, mission swap, unrouted click. **Panel contract:** tag the root `data-panel="<registry name>"`, commit on `change`; capture is automatic. Cmd/Ctrl+A/C/V/X/Z/Y run `CefFrame` edit commands (macOS OSR never acts on Cmd as keys). First consumer: SPV Move/Rotate/Scale click-to-edit rows. |
| Dev mission loader | `engine/dev_mission_picker.py`, `native/assets/ui-cef/{js/mission_picker.js,css/hello.css,hello.html}`, `docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md` | Developer-only "Load Mission…" pause-menu row that opens a CEF-rendered centred-modal picker listing every discoverable SDK mission (family → episode → mission). Picker is a `Panel` subclass pumped by `PanelRegistry`; one click on a mission row calls `controller.swap_mission(module)` + `pause.close()`. Lazy SDK walk on first open. ESC and Cancel route back to the pause menu; pause-menu hides while picker is open. |
| Developer Options menu | `engine/ui/developer_options_panel.py`, `engine/dev_combat_cheats.py`, `native/assets/ui-cef/js/developer_options.js`, `docs/superpowers/specs/2026-06-08-developer-options-menu-design.md` | Developer-only "Developer Options…" pause-menu modal styled like the configuration panel (reuses its `cp-*` CSS + shared backdrop). Combat tab toggles God Mode, 2× player weapon strength, and Disable NPC Shields — all hook `combat.apply_hit` via the dev-mode-gated flags in `dev_combat_cheats` (`*_active()` getters AND with `dev_mode.is_enabled()`, so production combat is byte-identical). God mode skips damage mutation but keeps hit feedback (`persist_decal=False` suppresses only the permanent scar). Off by default, not persisted across launches. |
| Ship Property Viewer | `engine/ui/ship_property_viewer.py`, `engine/ui/ship_property_viewer_panel.py`, `native/src/renderer/{hologram_pass,subsystem_pin_pass}.cc`, `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md` | Developer-only pause-menu modal: the player ship drawn as a translucent Fresnel hologram (`hologram_pass` re-draws the real instance with the solid hull hidden via `set_visible(iid, False)`) with camera-facing billboard pins per subsystem (`subsystem_pin_pass`, depth-test off so none hide behind the hull). Pins sit at `subsystem_world_position` mounts (ship world-loc + R·local, **no scale**). Orbit camera, projection and pin-picking are pure Python; the GL passes get the same camera via `set_camera`, so picks match by construction. Everything is absolute world space. Every tool (Move/Rotate/Scale, Copy/Paste, Mirror, Pipette, gizmo drags) is written once against a per-kind `EditTarget` adapter in `engine/ui/spv_edit_targets.py`; a new editable kind implements an adapter, never a new branch in the panel. Off by default, and the production render path is byte-identical — the panel is never constructed without `--developer`. |
| **Stub heatmap — CHECK BEFORE CLAIMING A NO-OP** | `docs/stub_heatmap.md`, `tools/stub_heatmap.py`, `engine/core/stub_telemetry.py` | **Trigger: any time you suspect — or are about to assert — that an SDK call is (or isn't) a silent no-op, READ `docs/stub_heatmap.md` FIRST. Never assert stub behaviour from reasoning alone.** It ranks unimplemented attrs by live hit count, plus **Boolean-test (truthiness risk)** and **Numeric-coercion (`int()==0` risk)** call-site tables. It covers both stub paths — the instance path (`TGObject.__getattr__`) and the App-module path (`App.<name>`) — so an undefined **constant** now shows up instead of quietly degrading to truthy / 0. That class has caused ≥4 real bugs, so **if you see a name in those tables, treat it as a live bug, not noise.** Whole SDK **modules** can also be silently stubbed in the twin lists (`tools/mission_harness.py` AND `tests/conftest.py` — fix BOTH), and **never unstub a whole module to reach one function.** |
| Measured constant surface | `engine/appc/constants_generated.py`, `engine/appc/constants_apply.py`, `tools/gen_app_constants.py`, `tests/unit/test_constant_surface.py`, `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md` | All 3,829 `App` constants read out of a running original `stbc.exe` and applied to the shim 2026-08-31 — 581 wrong values corrected, leaving `ok=3825 wrong=4 missing=0`. The floor is **4, not 0**, on purpose: `PI` and friends stay at double precision against BC's float32. **Never hand-edit `constants_generated.py`** — it is GENERATED; change `tools/gen_app_constants.py` or add a `DEVIATIONS` entry in `constants_apply.py`. Two traps, both live bug classes if re-broken: BC's `CSP_*` polarity is **lower = higher priority** (`crew_speech.py` matches it — change one, change both), and `CT_*` are **int tags** resolved via an int↔class registry, not the class objects. ⚠️ Fixing a constant's VALUE does not add its emitter — see `docs/engine/event-emitter-gaps.md`. |
| Cutscene letterbox — a RENDERER pass, not UI | `native/src/renderer/letterbox_pass.cc`, `engine/ui/letterbox.py`, `docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md` | The `StartCutscene..EndCutscene` bars are **GL, drawn below the whole UI layer** — into FBO 0 after the post chain resolves and **before `ui_cef::composite()`**. That ordering IS the feature: every CEF element lands on top of the bars by construction, with no z-index to forget. **Do NOT re-add them as DOM** — they were, at `z-index: 5`, and because every HUD root here has *no* z-index the bars painted *over* the UI and hid E1M1's XO menu mid-tutorial. `covered` is BC's `fCoveredArea`: the **TOTAL** fraction across both bars (0.125 ⇒ 6.25% each), which the native pass halves. Fed `_player_dt`, so the bars freeze under pause instead of sliding on wall-clock. Reset on mission swap; skipped in hologram-only mode. |
| Shield face + impact splash | `engine/appc/combat.py:_shield_face_from_hit_point` (**its docstring is the authority**), `native/src/renderer/include/renderer/shield_state.h`, `docs/instrumented_experiments/2026-08-16-shield-facing-and-beam-falsifiers.md` | **Which shield face a hit belongs to is a HULL-BOX question, not a 45° cone.** BC hulls are 4–8:1, so a raw body-frame compare labels only ~6% of a Galaxy's dorsal surface TOP. The delta is measured from the hull **AABB centre** and normalised by the **half-extents**; ships with no cached box fall back to the raw-axis rule. Verified against the clean-room reference: the chooser is `ShipClass::TestHit` (not ShieldClass, which holds no geometry at all), and our axis→index table and tie order match the binary. Still open: absorption is a strict cascade where BC uses a **pass-through ramp**, and beams should apply damage in **0.5 s pulses**. The renderer splash is procedural 3D on the **bubble**, not the hull — `shield_state.h` documents every constant and the live bug behind it. |
| Collision scuff decals | `engine/appc/collisions.py:scuff_radius_gu`, `native/src/renderer/shaders/opaque.frag:apply_scuffs`, `native/src/renderer/scuff_texture.cc`, `docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md` | Collisions route `weapon_type="collision"` → `WeaponClass::Scuff` (2): a **splatted normal map** (`native/assets/textures/scuff_normal.tga`, a PROJECT asset resolved via `set_project_asset_root`, never `game/`) sampled per scuff in its slip frame at a hashed offset, plus bare metal on the creases and a grime fill, in a **pre-lighting** pass on `n_shade`/`base`; `textureGrad` with gradients taken **outside** the loop. ⚠️ Procedural relief was tried eight ways live (scratches, buckle, dished facets, mesh-oriented panels) and always read as a stencil or a grid — don't restart it. ⚠️ The scuff size travels as `decal_radius` — never `splash_radius`, which sets the subsystem-damage catchment. ⚠️ The post-lighting scorch loop must `continue` on class 2 or the ember comes back. Big crumpling hits also wear plating (`COLLISION_MIN_HULL_DAMAGE`). `kScuff*` consts: rebuild to tune. Live tuning: `--developer` → Damage Preview / Collision Sim. |
| Hull name-cut fix — ID patches merged at load | `native/src/assets/src/mesh_fix.cc`, `tools/gen_mesh_fixes.py`, `native/assets/mesh_fixes/`, `docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md` | BC cuts each Fed hull's registry into a separate "ID" patch shape with its own texture. We merge that patch back into its saucer shape at load (High LOD only; the engine never loads Medium/Low), with UVs into the ORIGINAL saucer texture, driven by per-mesh fix files keyed by the NIF's **FNV-1a 64 content hash** (a mod-edited mesh never matches). Applied in `AssetCache::load` before `build_model`; a bad fix warns once and loads unpatched. ⚠️ Consequence: `ReplaceTexture("ID")` now matches nothing on stock Fed hulls. **All five patched hulls (Ambassador, Galaxy, Nebula, Akira, Sovereign) have their names back as projected decals** (next row). ⚠️ Never hand-edit a fix file: regenerate with `tools/gen_mesh_fixes.py --write`; review overlays with a dry run first (no `--write`); `tests/tools/test_mesh_fixes_drift.py` fails on any drift. |
| Bridge shape diff — Blender edits of set NIFs stored as a diff | `tools/bridge_shape_diff.py`, `tools/shape_diff/`, `native/src/assets/src/mesh_fix.cc` (`shape_edits`, `textures`), `native/assets/mesh_fixes/dbcdbd4a43dc5a56.json`, `docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md` **§11 = runbook** | Mark edits DBridge in Blender; `diff <fixed base.obj> <edit.obj> --partial [--write]` regenerates the WHOLE fix cumulatively (never merges) and only writes after an apply-and-compare check through the real C++ loader. The payload (BSD2, base64 in the fix JSON) holds ONLY indices, references and deltas plus authored UVs — never an absolute BC coordinate; OBJs live outside the repo (`~/Documents/dauntless-blender/`). Supports moves, UV edits, face add/remove (n-gons ear-clipped), vertex deletion, new vertices, per-shape albedo swap + numbered-frame flipbook. ⚠️ Don't join/split/rename objects in Blender (rename `.001` back). ⚠️ Commit a regenerated fix only after Mark's in-game check. ⚠️ Not the hull-name-cut generator: the drift test skips files whose `generator` is `tools/bridge_shape_diff.py`. |
| Hull name decals — registry masks projected in the ship-body frame | `engine/appc/hull_decals.py`, `engine/ui/spv_decals_pane.py`, `native/src/renderer/shaders/opaque.frag`, `native/assets/replacements/data/Models/Ships/<Class>/Masks/`, `docs/superpowers/specs/2026-09-28-hull-name-decals-design.md` | Names on patched Fed hulls. `ReplaceTexture(".../Zhukov.tga","ID")` (or `default_registry`) → `Masks/<registry>/<mask>.png` per placement (optional `mask`, else name) in `Masks/decals.json` (beside `FilenameHigh`); authored by `tools/gen_mesh_fixes.py --decals` or the dev-only SPV Decals pane (saves where it is read). ≤16 placements, ≤4 masks on units 8–11 (`Model::decals`, `u_decal_mask0..3`). Premultiplied mask (needs alpha) overrides albedo+glow RGB, alpha kept; paint specular `kDecalPaintSpecular` 0.8. Masks: all five patched Fed hulls. ⚠️ **No mesh-fix gate**: any class declaring decals gets them (a refit on a stock Fed model can double-name; accepted). Live preview: `host_io.set_instance_decals`. Articulated parts: decals test `u_node_rest_fix·p_body` (rest frame); the SPV places at rest and fills `shape` on rig parts. Live-verified 2026-10-18 (LC Intrepid nacelle). |
| Rock catalogue — generated rocks + glTF loader | `engine/rocks/catalogue.py`, `native/assets/rocks/`, `native/tools/rock_catalogue/`, `native/src/assets/src/gltf_load.cc`, `docs/superpowers/specs/2026-09-30-rock-catalogue-design.md` | BC's stock asteroid NIFs (asteroid, asteroid1-3, and asteroidh1-3 — byte-identical copies at their OWN paths, so keyed separately; Amagon loads asteroid3) realise as a deterministic catalogue pick (crc32 of the ship NAME) scaled to the stock mesh's bounding radius (`STOCK_RADIUS_MU`). GENERATED and committed: change `recipe.json` or `native/src/rockgen` and re-run; never hand-edit; `tests/tools/test_rock_catalogue_drift.py` guards it. ⚠️ glTF convention: 1 unit = 1 m, BC model unit = 1.75 m, axes (x,y,z)→(−x,z,y). ⚠️ `Model::source` is `"<path>#s=<scale>"` for a scaled load — damage-volume caches key on it via `assets::split_hull_source`; never `fs::exists()` a raw source. A mod overriding a stock asteroid NIF in place keeps its own model (redirect only when the resolved path is under `paths.game_root()`). Dev toggle: Developer Options → Environments → Catalogue Rocks. Programme: `docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md`. |
| Planet geosphere — icosphere LODs for planet NIFs | `native/src/assets/{include/assets,src}/geosphere.*`, `native/src/renderer/frame.cc:geosphere_level_for`, `native/src/renderer/shaders/opaque.frag` (`u_sphere_map`), `engine/planet_geosphere.py`, `docs/superpowers/specs/2026-10-06-planet-geosphere-design.md` | All 31 stock planet NIFs are ONE 673-vert UV sphere (r 90.0099, centre (−0.736648, 0.368324, 0) via the `planet` node) with an exact equirectangular map, u = fract(atan2(y,x)/2π+0.75), v = 0.5−asin(z)/π. `load_model(..., geosphere=True)` keeps BC's mesh in `meshes[]` (AABB/trace/other passes unchanged) and adds `Model::sphere_map` = 4 icosphere LODs (levels 3–6); the opaque submitter picks one PER CAMERA by 0.5 px silhouette sagitta and `opaque.frag` derives normal + UV from the sphere direction (Tarini dual-seam gradients). Gate: one mesh, all verts within 0.5% of the mean radius — modded non-sphere planets load unchanged. Toggle: Developer Options → Environments → Geosphere Planets (default on). Live-verified 2026-10-07. |
| Planet atmospheres — catalogue + shell scattering + surface limb | `engine/planets/atmosphere.py`, `native/assets/planets/atmospheres.json`, `native/src/renderer/{atmosphere_math,atmosphere_pass}.{h,cc}`, `shaders/atmosphere.{vert,frag}`, `opaque.frag` (`u_atmo_*`), `docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md` | BC identifies a planet ONLY by (set name, AddObjectToSet name). Catalogue keys: `"<set>/<name>"` else case-folded NIF stem; NO bare-name key ("Moon 1" is in 3 sets). Fields color/thickness/density/limb/sunset_color/intensity/mie; `atmosphere:false` = airless; unknown fields REJECTED. BC's `SetAtmosphereRadius` is gameplay-only, NOT used. Shell pass: PHASE 2, march ends at scene depth; **chromatic Rayleigh** (`color` = relative per-channel scattering strength, NOT a final tint) + grey Mie (HG 0.76), so long paths redden; CPU twin pins the shader. Needs the geosphere `sphere_map` variant. Dev: Developer Options → Environments → Planet Atmospheres / Reload; dial group "atmosphere" tunes the nearest planet's ENTRY. Player Helm Orbit altitude = max(150, 0.15·R) via `engine/orbit_altitude.py` (hooks SDK `OrbitPlanet.CreateAI`). Live-verified 2026-10-07. |
| Planet surface detail — procedural detail over BC maps via a budgeted clipmap | `engine/planets/surface.py`, `engine/planet_surface.py`, `engine/planets/surface_dials.py`, `native/src/renderer/{planet_detail_noise,planet_clipmap_schedule,planet_clipmap_atlas,planet_detail_pass,planet_detail_uniforms}.{h,cc}`, `shaders/planet_bake.frag`, `opaque.frag` `#ifdef PLANET_SURFACE`, `docs/superpowers/specs/2026-10-08-planet-surface-detail-design.md` | ONE target planet (nearest, detail visible) gets a 5×1024² toroidal clipmap baked under a per-frame cost budget (`planet_detail` profiler scope); its sphere-LOD draw uses the `planet_` program (`PLANET_SURFACE`); every other draw byte-identical, full-screen cost ≈ 0.3 ms bake + 0.58 ms sampling (M3 Pro, 3840×1200). `surface` key in `atmospheres.json` resolves independently of the air; `atmosphere:false` keeps surface. Per-type defaults: `planet_detail_noise`'s table; dial group "surface" on `/ L O`. Toggles: Dev Options → Environments → "Planet Surface Detail" / "Surface Detail Debug" / "Reload Planet Surfaces". `planet_bake.frag` is the GLSL twin of `planet_detail_noise.cc` — change both. ⚠️ Not live-verified until Mark calibrates. |
| Rock class — asteroids as rocks, not ships | `engine/rocks/{rock,motion,death,breakup,vfx,minors}.py`, `docs/superpowers/specs/2026-09-30-rock-class-design.md` | Genus-3 ships become `RockClass(ShipClass)` in `SetupProperties` (`ShipClass_Cast` still passes). AI/motion/subsystem loops skip rocks (`ship_iter.iter_non_rock_ships`); `rocks.motion` integrates scripted velocity/spin. Hull death → `rocks.death`: death script, `ET_OBJECT_EXPLODING`, size-decided breakup from `rocks.rock.effective_radius` (base × `GetScale()`; a 30% remnant named `"<name> - Remnant"` (sole target if ≥2.0 GU) + ≤12 untargetable `"<name>-N"` 0.5–1.5 GU pieces (<1.0 GU → debris minors in a free cloud), rest dust; pieces of pieces only crumble), `ET_OBJECT_DESTROYED` after 0.5 s or the death script's life. ⚠️ Deliberate BC departures: no death splash to/from rocks, no fireball. Renderer: `Instance::surface_is_rock` (craters, no panels/rooms; no venting/smoke, grey debris, rock-dust sparks). `DamageableObject_Create("Asteroid")` returns a rock (Multi1/Multi6). Dials: `engine/rocks/breakup.py`. `ET_PLANET_COLLISION` is posted before impact damage so E1M2's Haven hit counts (`event-emitter-gaps.md` #13). |
| Minor rocks — instanced scenery around rocks | `engine/rocks/{minors,minor_dials,minor_contact}.py`, `native/src/renderer/{minor_field,minor_pass}.cc`, `shaders/minor.vert`, `engine/dev_dial_groups.py`, `docs/superpowers/specs/2026-10-01-minor-rocks-design.md` | Non-simulated catalogue fragments in **clouds**: `halo:<set>:<rock>` per `RockClass` (anchored), `free:<set>:<rock>` (detached halo + breakup debris; capped at 256). ⚠️ No `tile:<set>:<field>` cloud any more (an `AsteroidField` is now a rock-fields density source). Scale `s = r / bound_radius_mu`; fragments load at 1. C++ `MinorField` owns instances/cull/LOD/shove; `build_bins` re-bins per **drawn camera** (main view AND the viewscreen RTT). Contact is an **exact convex sweep** (golden-section, no tunnelling below `teleport_gu`), guarded by a per-minor `contact_cooldown_s`. Only `halo_*` dials rebuild clouds (would wipe shove wake); others read at use. Shove floor: `shove_min_gups`. `clear()` drops contacts + fragments; registry re-pushes. Bench: **~0.24 ms/step at 20k** (CPU). ⚠️ No damage/events, never in `render_payload`. ⚠️ `/ L O` SHARED with nebula + rock fields. Rock chunks retired. |
| Rock fields — one density field per source drives near streamed rocks, a speck band and puffs | `engine/rocks/{density,far_dials,far_tier,scenery_contact}.py`, `native/src/renderer/{rock_near,rock_speck,rock_puffs,far_field}.{h,cc}`, `docs/superpowers/specs/2026-10-02-rock-fields-design.md` | Density is `far::field_density` = `a·m` per source. Near band streamed around the player: small mesh 0–15/billboard to 90 GU, large mesh 0–60/billboard to 405 GU, hard mesh↔billboard swap, per-class pixel floors, billboards collapse to the mesh range when dashing; large rocks **collide and damage** (`scenery_contact.py`). Speck band: large rocks past 405 GU as GPU-faded specks. Puffs: soft lit billboards placed by the density carry the far look. Dials: "rock fields" on `/ L O`. Toggles: Dev Options → Environments → "Rock Fields" (master, also scenery collisions), "Rock Specks", "Rock Puffs". Large rocks: 0 at a≤0.5 → full at 1 (large_ramp_*); the nearest 8 ≥4 GU within 300 GU are promoted to targetable RockClass "Field Rock XXXX" (engine/rocks/promotion.py, rockfield_set_promoted/query_large); NPCs avoid field rocks (field_obstacles). |
| Ship-attached dynamic lights — resolved in C++ | `native/src/renderer/dynamic_lights.cc:resolve_attached_dynamic_lights`, `host_loop.py:_build_emitter_light_render_data`, `docs/superpowers/specs/2026-09-16-instance-attached-emitter-lights-design.md` | Subsystem emitter lights leave Python **body-frame** with an `instance_id` and are resolved through the hull's own `inst->world` in `frame()` right after the transform-store sweep, so light and hull share one pose per frame (the particle-emitter pattern). ⚠️ Do NOT rebuild world positions in Python from `GetWorldLocation/Rotation` — that is the live 60 Hz pose, and the hull renders interpolated; the mismatch is a visible jitter at 144 Hz. ⚠️ Do NOT resolve at `set_dynamic_lights` time — that reads last frame's matrices (`tests/host/test_attached_lights_resolve_ordering.py` guards both). Emitter offsets are unscaled GU: world = `t + R·p`, scale divided out. Torpedo/explosion lights stay world-space. |
| Ship running lights — `BlinkingLightProperty` | `engine/appc/running_lights.py`, `engine/appc/running_light_dials.py`, `native/src/renderer/running_light_{math,store,pass}.{h,cc}`, `docs/superpowers/specs/2026-10-14-ship-running-lights-design.md` | Mod hardpoints' nav lights (LC Intrepid 19, DCMPv2 10/ship; stock none). Additive depth-tested soft discs placed by C++ through the hull's `inst->world`, looked up by id. ⚠️ **Deliberately NOT BC** (BC: ~9 Hz flicker, Duration-0 statics invisible; spec §2-3): on for Duration every Period, statics always on. Level = alive × power-plant glow state × (1 − cloak), 0 for every hull the host loop hides. ⚠️ The pass ignores `inst->visible`, so **any NEW `set_visible(iid, False)` hull hide must be mirrored in `_push_running_lights`**. Native caches positions: lights on an articulated part are re-sent from Python when it moves (attributed by `physical_parents.part_for_property` — see the Physical parents row) and dropped with a severed part. Dials "running lights" on `/ L O`; toggle Developer Options → Lighting → Running Lights. |
| Physical parents — explicit "which mesh part is this on" | `engine/appc/physical_parents.py` (`part_for_property`), `SetPhysicalParent("<part>")` / `GetPhysicalParent()` (`None` = Auto), `docs/superpowers/specs/2026-10-17-subsystem-physical-parents-design.md` | Replaces the nearest-mesh guess (`part_for_mount`, articulation OQ-13) for subsystems and running lights; unset falls back to it. Authored in the SPV's Functional/Physical tabs, saved into hardpoints (Python 1.5-safe text). Unrigged ships never resolve. ⚠️ **Emitter lights NEVER read it** — they keep their own-position placement. ⚠️ The SPV `physical/` actions are exempt from the pose lock. Live-verified 2026-10-18 (Bird of Prey impulse/sensors/warp on `birdofprey`). |
| Bridge lighting baseline — downlight + SSAO, no lightmaps | `native/src/renderer/{bridge_pass,bridge_ao_pass}.cc`, `renderer/bridge_lighting_tuning.h`, `renderer/bridge_quality.h`, `native/src/assets/src/normal_gen.{h,cc}`, `engine/bridge_lighting.py`, `docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md` | BC's bridge lightmaps are NOT rendered. Interior sets load with `interior=True`: shapes authored without normals get generated ones (T-junction repair, 40° crease, area weighting) — ships never do. `bridge.frag`: `ambient × mix(0.25, 1.0, up-facing) × AO`, then a soft ceiling under bloom's 0.9 threshold (**lit surfaces never bloom; only emitters and `_emissive` maps do**). AO is main-view only (never the comm-set feed), presets Low/Medium/High = 24/32/64 samples, High at full res and meant for gaming GPUs. Alert ambient green ×1.5, yellow/red ×1.0. All tuning values are ONE header (rebuild to tune). Debug views: Developer Options → Lighting → Bridge Debug View. ⚠️ `Map 3.tga` (DBridge alcove) has a cove glow painted into its DIFFUSE — not a lightmap; deliberately left for the emitters phase. |
| Bridge editor — pick shapes, per-bridge lighting data | `engine/bridge_editor/`, `engine/ui/bridge_emitters_panel.py`, `native/assets/bridge_lighting/`, `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` (§13-15) | `--developer` → pause → **Bridge Editor…**: click to select a NIF shape (Alt+click: behind). Identity = (NIF content hash — INTERIOR loads only, block, name); a mismatch skips with a warning. Per-bridge data `native/assets/bridge_lighting/<fnv1a64>.json` (format 4; 1-3 upgrade on load): a material library (finish = roughness, metalness, emission over `_emissive` or own texture/flat; scoped State (replaces it), Animation (multiplies), Transition (0.5 s default) modifiers) + `textures` (a material belongs to one TGA; unlinked objects use its texture's) + objects (same-texture link, lights; a strip snaps to the edge nearest the selecting click (§16.8)); unknown keys REJECTED; writer deterministic + atomic. Five states: offline (power down), green/yellow/red, special (hook). Room light per state: the bridge's own, else 0 if it has lights, else the default. Editor: top-left bar, Object/Material tabs on selection, Bridge Settings cog; hold Shift to fly. |
| Bridge PBR — linear GGX, layered materials, reflection probes, spot lights | `native/src/renderer/{bridge_pass,bridge_probe_array}.cc`, `renderer/bridge_pbr.h`, `shaders/bridge.frag`, `engine/bridge_editor/{materials,lights,runtime,probe_layers}.py`, specs `2026-10-08-bridge-emitters-spike-design.md` §9 + `2026-10-17-bridge-reflection-layers-design.md` | Decodes albedo + downlight (2.2), linear GGX, re-encodes for the gamma post chain (default = old look). Output = `ceiling(enc(D)) + max(enc(D+S) − enc(D), 0)`: lit diffuse never blooms, specular may. Channels: `<stem>_rough/_metal/_normal` maps (interior: stock → our overlay, mod → beside it) → per-shape override → default. Probes: 5 per-state bases + (state, whole-wave) layers capped 2/4/8 by quality, 384² R11G11B10F cube-map array, time-sliced (17 steps/probe, 1/frame, shown state first) at `_BRIDGE_CAMERA_EYE`, per-probe dirtiness, glow in; base fade 0.5 s in C++ (`set_bridge_probe_state`), layers × `w^2.2` (`set_bridge_layer_values`). ≤32 spot/area lights (§16; CPU twins: bridge_pbr.h). Comm sets shade legacy. `BridgeRuntime` applies saved data in PRODUCTION. Dev: Lighting → Bridge PBR (A/B), debug views 6–11 (11 = layers). |
| **Per-user data dirs — packaged builds never write in their own folder** | `engine/paths.py` (`config_dir`, `saves_dir`, `mods_default_dir`, `cache_dir`, `log_dir`, `log_file_path`, `report_write_failure`), `docs/superpowers/specs/2026-10-16-per-user-data-dirs-design.md` | Where the game WRITES. Modes, **in precedence order**: `--data-dir`, `DAUNTLESS_DATA_DIR`, packaged marker `dauntless-packaged.json` (OS per-user folders), checkout (`PROJECT_ROOT`, today's layout). ⛔ **Never write under `PROJECT_ROOT` outside the static guard's allowlist.** Failed writes go through `report_write_failure`, never a bare swallow. Guards: `tests/unit/test_install_write_guard.py`; `tests/integration/test_no_install_writes.py` + `tests/helpers/write_audit.py`; e2e `tests/integration/test_packaged_readonly_e2e.py`. The suite runs under a temp `DAUNTLESS_DATA_DIR`. Log tee: packaged only, file-backed (a pipe deadlocked), console mirror on stderr. ⚠️ **Windows not yet verified** (checklist in the spec's Outcomes). |
| Legacy FX API surface — NanoFX's API without NanoFX | `engine/mod_policy.py`, `engine/compat/{claimed.py,fx_api/}`, `engine/sprites.py`, `native/assets/sprites/`, `tools/sprites/prep.py`, `docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md` | Mods calling `Custom.NanoFXv2.*` get Dauntless's implementation, served by a claimed-namespace rule in BOTH `_SDKFinder`s (ours always wins). A real NanoFX install is **blocked** (standalone) or its files **skipped** (bundled); Foundation's bundled infrastructure files are refused (`LoadTacticalSounds`/`QuickBattle`/`mainmenu` only when they import Foundation). NanoFX texture paths are NAMES resolved by the sprite library (`legacy_aliases.json` → `manifest.json`: `sprite`/`native`/`none`, playback `life_columns`/`life_sequence`/`loop`, `pivot`, `orient: emit_dir`). ⚠️ Production VFX stay byte-identical (`tests/unit/test_stock_particle_output_unchanged.py`). ⚠️ Output PNGs are GENERATED by `tools/sprites/prep.py` from `native/assets/sprites/src/` — never hand-edit (drift test). ⚠️ §6.3 "re-enabling global glow clears per-ship disables" is an ASSUMPTION. Sprites are mod-only: stock-VFX use was A/B'd and rejected (2026-10-16). |
| Game-unit conversion | `engine/units.py` | BC stores **everything** spatial (positions, velocities, distances, radii) in a single internal unit, "game units" (GU). **1 GU = 175 m = 0.175 km, 1 GU/s = 630 km/h.** Derived from Galaxy `SetMaxSpeed(6.3)` → 3969 kph in BC's helm tooltip (`sdk/.../BridgeHandlers.py:1389` via `Appc.UtopiaModule_ConvertGameUnitsToKilometers`). Physics, renderer, and camera stay in GU end-to-end; **only convert at display boundaries** via `GU_TO_KM` / `GUPS_TO_KPH`. Never call any variable `*_m` / `*_mps` — speed/range inside the engine is **always** `*_gu` / `*_gups`. |
| Radial system profile | `engine/systems/profile.py`, `tools/systems/profile_builder.py`, `engine/appc/radiation.py`, `docs/superpowers/specs/2026-09-23-radial-system-profile-design.md` | Space as a per-system table keyed by distance from the star: `nebula`, `dust`, `sensors`, `radiation`, `asteroids` (0-1, linear between rows, last row persists outward). ⚠️ **Radiation departs from BC** (BC nebula hits once, at creation): 16 Hz `ET_ENVIRONMENT_DAMAGE` lands 1/16 s of drain only if the destination handler chain runs to the end — a handler that stops it (`MissionLib.IgnoreEvent`, E3M2 `CoreDamage`) cancels the damage. Outage: flag (`sub._radiation_out`) read by `subsystems._is_offline` alongside `IsDisabled`/`IsDestroyed` — never `TurnOff`. A ship inside an armed local `MetaNebula` gets one event stream. `dust` sets space-dust density. Vesuvi's table is a hand `overrides.profile` in absolute GU — `profile-override-tracks-clump` fails generation if the layout moves. `asteroids` feeds render-only far-tier belts. Render: `native/src/renderer/system_nebula_pass.{h,cc}`, on in production (Volumetric Nebulae / Improved Space); dials on developer keys (`engine/dev_nebula_dials.py`). |
| Dauntless crew dialogue — our own TGL + voice lines | `tools/dialogue/dauntless_crew.json`, `tools/gen_dauntless_tgl.py`, `engine/appc/crew_hazard_prompts.py`, `native/assets/dialogue/patches.json`, `docs/engine/dauntless-crew-dialogue.md` | New crew lines (no BC original): author key/text/sound in the JSON, put the voice under `native/assets/replacements/`, regenerate the TGL with `--write` — never hand-edit it (drift test). The TGL is in BC's own layout and both files resolve through the replacements overlay, so `g_kLocalizationManager.Load` + `SpeakLine` work like any SDK line. Keys are BC-style (`BrexRadiationShields1`). First consumer: "raise shields" prompts in asteroids/radiation with shields down. Dialogue patches insert lines after a scripted line or replace a line's text/sound at runtime, without SDK edits (first use: E1M2's cut replicator lines). ⚠️ No language selection exists. Live-verified: asteroid + radiation prompts, E1M2 reinserted lines, Felix replacement + subtitles. |
| Sensor tiers — detected vs identified | `engine/appc/sensor_contacts.py`, `engine/appc/unknown_labels.py`, `engine/appc/science_scan_labels.py`, `engine/appc/sensor_dials.py`, `docs/superpowers/specs/2026-10-03-sensor-model-roadmap.md` | BC's two tiers, RE'd: contacts list as grey **"Unknown N"** (no subsystems, Hail, target) until **4.0 s** in the **near band (half range)**, or scanned. Player-only 1 s sweep posts `FAR/NEAR_PROXIMITY` (source = the ship). `_identify_one` is the single commit point. ⚠️ `STSubsystemMenu.GetLabel()` stays the REAL name (tutorial arrows resolve rows by it); placeholder `GetCaption()`. SP2: a major rock on the line of sight hides a contact in `can_detect` (player + AI); a field/moderate nebula reads Unknown; hidden <5 s keeps identity, longer loses the track (not cloak/medium). SP3/SP4: `can_detect` memory, over-boost, probe branch (`AddProbe`). Dials: "sensors" group on / L O. SP5: `ForceObjectIdentified` is player-only; sensor-less observers (CommArray/CommLight) see the `sensorless_range_gu` dial (2000 GU), and the cloak bubble is capped by `cloak_bubble_cap_gu` — spec `2026-10-08-sensor-debts-design.md`. |
| E1M1 intro skip | `docs/engine/e1m1-skip-intro.md`, `engine/appc/input.py`, `engine/dev_tutorial_flag.py` | BC's "Press 's' to skip introduction" prompt. Needed FIVE pieces of missing surface: `TGKeyboardEvent.GetUnicode`, a real `App.ET_KEYBOARD` int, raw `ET_KEYBOARD` dispatch down the window chain (`_raw_keyboard_destination`), `TGInputManager.GetDisplayStringFromUnicode` (heatmap rank 57, 342 hits), and `TGActionManager_KillActions` — whose registry had to become name→**list** because E1M1 registers six sequences under `"CharacterIntros"`. ⚠️ The `PlayedTutorial` gate is only forced under `--developer` for now; persisting the `"global"` VarManager scope is deferred to persistent-save work. |
| Manual Aim (H, "mouse pick fire") | `engine/manual_aim.py`, `docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md` | BC's point-to-aim: `H` → `ET_INPUT_TOGGLE_PICK_FIRE` → SDK `TacticalControlHandlers.TogglePickFire` (registered by `manual_aim.register_toggle_handler`, NOT by `TacticalControlHandlers.Initialize` — that would double-dispatch the fire keys). Per tick, sim side: cursor → `cursor_ray` (exact inverse of the SPV `project`) → `ray_trace_mesh` on the **targeted** hull only → `ShipClass.set_manual_target_offset` (target-local, **unscaled**). Off the hull ⇒ `UseTargetOffsetTG(0)` immediately. Phaser tick + drawn beam share `_phaser_aim_point`; torpedoes/pulse read the offset live via `WeaponSystem._live_held_offset`. Dropped whenever the bridge becomes visible (`manual_aim.drop_mode`, twin of the stubbed `BridgeHandlers.DropOutOfManualFireMode`). ⚠️ The C++ pick semantics are five **stated assumptions** in the spec, not RE'd behaviour. |
| **Target zoom fit (Z + viewscreen)** | `engine/cameras/zoom_fit.py`, `engine/cameras/tracking.py:_compute_zoom_target`, `engine/host_loop.py:_viewscreen_scene_feed`, `docs/superpowers/specs/2026-10-20-target-zoom-fit-design.md` | The exterior Z zoom and the bridge viewscreen share one solver: fit the target's **scaled** hull box (rocks: base × `GetScale()`) at the rendered FOV + aspect (`VS_ASPECT` 640/360 for the feed), centred on it, **never further back than the player**, and a surface the camera would sit inside beats the own-hull rule; the viewscreen distance is smoothed (tau 0.25 s, snaps on retarget, held under pause). Headless proof: `tests/integration/test_e1m2_target_zoom_fit.py` (E1M2's six `SetScale(3)` rocks). ⚠️ **Deliberate BC departure** (BC stands off by a radius-derived distance and can crop or bury the target). Live-verified by Mark 2026-10-20. |
| Viewscreen target bars | `engine/ui/viewscreen_bars.py`, `native/src/renderer/viewscreen_bars_pass.cc`, `tools/fonts/gen_bitmap_font.py`, `docs/superpowers/specs/2026-10-21-viewscreen-target-bars-design.md` | A top-corner readout drawn INTO the viewscreen RTT on the scene (target) feed only (never a hail or the forward view): an affiliation-coloured dot + the target name at the TOP-LEFT, and a smaller `DST: <km> km  SPD: <kph> kph` line at the TOP-RIGHT (right-aligned, cap tops level with the name's; the name is ellipsised short of it). White text over a soft black shadow, **no background** (the first design's footer band was hidden behind the bridge consoles — spec §2a). The numbers are the reticle's (`reticle_text.readout_values`), so the two can't disagree. Dot and text capped at 0.85 so nothing blooms. Layout = `kVsReadout*` consts at 640 px wide, scaled by width (rebuild to tune). Text comes from the GENERATED Antonio bitmap atlas: regenerate with `tools/fonts/gen_bitmap_font.py`, never hand-edit; `PIXEL_SIZE` is the size knob. Live-verified by Mark 2026-10-21 (rev 3 layout). |
| Warp button chain + mission change | `engine/appc/warp_button.py`, `engine/core/mission_change.py`, `engine/appc/warp.py`, `docs/superpowers/specs/2026-09-25-warp-button-chain-and-mission-warps-design.md` | Helm "Warp" sends `ET_WARP_BUTTON_PRESSED` to the button; its handlers run newest-first (missions' `WarpHandler`s), and the engine step at the bottom replaces SDK `WarpPressed`: `warp_gate`, then a warp built from destination, placement, mission, episode and the button's five queues. Transit parks the ship in BC's persistent `"warp"` set — on the hard cut too — and holds on `WarpSequence.WaitForQueued`; `_MissionChangePoint` runs `mission_change.change()`, which keeps only the bridge set(s) and `"warp"` (so the in-transit player carries over; a DIRECT `LoadEpisode` builds a new ship). Direct `Game.LoadEpisode`/`Episode.LoadMission` route through it while a mission runs. Headless E2E: `tests/integration/test_campaign_warp_transitions.py` + the 26-mission sweep. ⚠️ **Not live-verified.** |
| Warp tunnel preload — the tunnel is the loading screen | `engine/warp_preload.py`, `engine/appc/warp.py` (`_HoldUntilAction`), `engine/system_haze.py`, `native/src/renderer/system_nebula_cache.{h,cc}`, `docs/superpowers/specs/2026-10-16-warp-tunnel-preload-design.md` | The player's tunnel holds until its floor (today's length) AND the destination preload is ready, capped 30 s of **sim ticks** past the floor (`[warp-preload] late: <items>` on stderr at the cap). One GL load per tunnel frame; the haze table is cached per session with a `std::async` prebuild (Vesuvi 7 s Debug). ⚠️ The profile dict must come from `system_haze.profile_dict` on both sides or the cache misses. ⚠️ Never run SDK `Initialize` early from the preload. Measured live 2026-10-17: Vesuvi 9.4 s → 0.32 s first visit (accepted), 7.4 s → 0.11 s return. Deferred: `warp.place_player` 0.8 s (QuickBattle Starbase12), `warp.depart` 0.4 s (leaving Vesuvi). ⚠️ OPEN: tunnel frames of 100-180 ms while the preload loads catalogue rocks/planets (follow-up: worker prepare + budgeted GL finish). |
| In-system warp (dash + hand-off) | `engine/systems/warp_path.py`, `engine/appc/warp_flight.py`, `engine/appc/dash.py`, `engine/systems/handoff.py`, `docs/superpowers/specs/2026-09-25-in-system-warp-design.md` | Within one mapped system, Set Course **dashes** through real space (~10 s flash to flash, arriving at rest at the placement) instead of BC's tunnel, on a path `plan_path` routes around every body's clearance; **Warp on Heading** (Helm, beside Warp) dashes along the nose until a body ahead drops it out at its region's arrival range, keeping the engaged impulse speed; `0` / All Stop drop out at rest. A dash never enters the `"warp"` set; a system-to-system course still tunnels (rule C). The player is handed off between region sets only at the drop-out (`handoff.hand_off`), `system_position` unchanged. The host calls `dash.tick` each frame; `GameLoop` does not (headless: `headless_mission._sim_tick`). A region also contains points within `handoff.region_reach` of its bodies, so arriving from any side hands off. Headless E2E: `tests/integration/test_in_system_warp_e2e.py`. ⚠️ **Not live-verified.** |
| Ship → bridge matrix (auto player bridge) | `engine/bridge_selection.py`, `bridges.json` (beside `settings.json`), `docs/superpowers/specs/2026-09-16-ship-bridge-matrix-design.md` | The DEFAULT bridge-for-ship mechanism for any mode that doesn't dictate one. `BridgePins.resolve(ship)` → bridge config script; absent file ⇒ Galaxy/Sovereign/Akira defaults, present ⇒ authoritative. QuickBattle consumes it via a once-per-load wrap of `RecreatePlayer` (`install_quickbattle_hook`) so all four SDK callers resolve at use. Campaign/tutorial `LoadBridge.Load("<literal>")` override by construction — do NOT hook `LoadBridge.Load`. A runtime bridge swap is re-realised per tick by `_reconcile_bridge_config` (host_loop) on a `BridgeSet.GetConfig()` change. Labels are BC's (*Galaxy*/*Sovereign*, `Ships.tgl`), never DBridge/EBridge. `_scan_mod_bridges` is a STUB with an `xfail(strict)` contract test. Ships as a dedicated ⚠️ `bridges.json` (NOT `settings.json`) so it can be backed up/restored on its own. |
| Ship metadata catalog | `engine/ship_catalog/`, `engine/foundation/shipdef_overrides.py`, `docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md` | Dauntless-owned per-ship metadata (era span, role, playable, title, species, named variants) for Quick Battle, as a `dauntless` dict on the Foundation `ShipDef`: stock in `shipdef_overrides.py` (unlisted), mod ships in `Custom/Ships`, gate answers as `zz_Dauntless_<shipFile>.py`. **Read metadata ONLY through `engine.ship_catalog`** (`entries()`, `entry()`, `species()`, `insignia_path()`): merges stock then mods, validated. ⚠️ Keep stock dict literals Python 1.5-safe (1/0, never True/False). ⚠️ A variant's `script` spawns a separate ship script; the class default (`variants[0]`) is name-only, not scripted. Sub-project 3: named classes (`variant_of`, one starred `class_default`) via the pre-boot **Mods screen** (`engine/ui/mods_screen.py` + its state machine `mods_screen_panel.py`): gate mode for incomplete mod ships, else a READ-ONLY home mode via `--mods`/pause's **Quit and Manage Mods** (RELAUNCHES, `platform/relaunch`). CEF keyboard input is pre-boot AND in-game. Spec `2026-10-01-mod-ships-screen-design.md`. |
| Quick Battle setup + group spawning | `engine/quickbattle/`, `engine/ui/quick_battle_setup_panel.py`, `docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md` | Only `GenerateShips` is wrapped (`spawn.install_generate_ships_hook`); it reads the panel's plan via `spawn.set_provider` at call time (no provider ⇒ BC's original). It also writes `g_kEnemyList`: `StartSimulation2` arms the win from its length. Neutrals: no `g_kShips` entry. Placement is deterministic (`placement.py`). ⚠️ Ships report `GetRadius() == 0` before realisation, so `spawn.set_radius_fn` seeds radii through the shared runtime load first. The player's name: `spawn.apply_player_identity` in host_loop's QuickBattle reconcile block — ⚠️ no `has_replacements` guard, because `CreatePlayerShip` pre-queues the class default. ⚠️ The setup is per-run; only presets are on disk (`quickbattle_presets.json`). ⚠️ No dedicated revert hook — outside a battle, `RecreatePlayer` itself always resolves the home ship (Galaxy USS Dauntless, ruled 2026-10-02) via `bridge_selection.set_player_type_resolver`/`spawn.player_type_for_recreate`, reading `bInSimulation` live. ⚠️ **Not live-verified.** |
| **`.pyc`-only mod scripts — Python 1.5 bytecode lifted in the SDK loader** | `engine/py15/`, `_module_tree` + `_mod_override_spec` in `tools/mission_harness.py` AND `tests/conftest.py`, `docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md` | A mod module shipped only as 1.5 `.pyc` (the LC Intrepid's `ZZ_VoyPhoton`/`ZZ_Tricobalt`) is lifted in memory to the Python 3 AST its source would parse to, then takes the SAME transform pipeline. **Mod files only**: stock always loads from SDK `.py`. Per layer `.py` → `/__init__.py` → `.pyc` → `/__init__.pyc`. Straight-line subset only (no jumps, classes, nested/variadic defs); anything else raises `Py15Unsupported`, prints ONE `[sdk-loader]` line per file, and projectiles fall back to the photon. ⚠️ The subset grows only with a stock-corpus case in `tests/unit/test_py15_stock_oracle.py` (floor 514 of 1201, 0 mismatches). ⚠️ Never write lifted or decompiled mod text anywhere, and never commit a mod-derived value in a test. ⚠️ uncompyle6 is NOT a fallback: it silently mis-decompiles 1.5 (`import a.b` → `import a`). |

## Open questions status

### Instrumentation questions (require running game)

| Q | Topic | Status |
|---|---|---|
| Q1 | Tick rate — fixed or variable? what Hz? | ✅ **60 Hz fixed** (16.67 ms/tick) |
| Q2 | Subsystem update ordering within a tick | ✅ **AI/Python first** (~2% into tick), then physics, then render |
| Q3 | Time scale interaction with physics/AI/timers | ✅ **Game time scales** (0.204 measured); real time does not |
| Q4 | TimeSliceProcess priority semantics | ✅ Closed — static analysis sufficient |

### Gap analysis OQs (26 total)

**Audited against code 2026-08-09** — most "open" OQs were stale Phase-1 planning
artifacts, already answered by shipped Phase-2 work. Counts are now machine-checked
by `tests/docs/test_doc_consistency.py`; if you change a status, that test enforces
the summary line agrees.

- Closed by static analysis: OQ-1.1, 1.2, 1.3, 2.1, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 6.2, 7.4, 8.1, 8.2 (15)
- Closed by instrumentation: OQ-7.1, OQ-7.2, OQ-7.3 (3)
- Closed by code audit 2026-08-09 (5): OQ-3.1 *superseded* (BC ships NIF v3.1, which OpenMW cannot parse — we wrote our own loader), OQ-3.2 (damage geometry is a paired `*_vox.nif`, not node tags), OQ-3.3 (head graft, `model_compose.cc:206`), OQ-8.3 *dead surface* (`MorphBody`: zero SDK call sites), OQ-8.4 *superseded* (a static manifest would list a typo'd file BC deliberately re-registers)
- Partially answered: OQ-2.2 — **do not conflate the halves.** In-system warp is implemented and preserves pre-warp speed; **set-to-set warp exit velocity is genuinely open** and our current behaviour is accidental. OQ-2.3 — the spring-damper is built and tested, but it is a *designed approximation*, not a reconstruction; the clean-room reference has no tractor force section, so it cannot be promoted
- Built 2026-08-09 (Phase 3): **OQ-6.1** DynamicMusic (`engine/appc/music_manager.py`, `engine/audio/music.py`, `_pump_music` in `host_loop.py`) and **OQ-2.2** set-to-set warp exit velocity (`engine/appc/warp.py`)
- ⚠️ **Both need a live run before being called done.** Music cannot be checked headlessly, and the warp velocity is a *chosen* default, not recovered BC behaviour. The old "no remaining OQs require running the live game" line was wrong and has been removed
- ✅ Settled 2026-08-10: BC **crossfades** — two ramp records, same instant, same duration, both streams audible. `MusicPlayer` rewritten around BC's volume-ramp record. Falsifier: with no current track the incoming record is startVolume 1 / duration 0, so the fade-in exists only when fading out of something. Warp arrival velocity is likewise **exactly zero**, not the chosen default we briefly shipped

**Phase 1 blockers: all resolved.** Phase 3 build candidates are in
`docs/superpowers/plans/2026-08-09-triage-report.md`.

## Instrumentation approach

`tools/appc_logger.py` is the active instrumentation snippet. It is appended to `sdk/Build/scripts/App.py` by `tools/setup.py` and installed into `game/scripts/App.py`. The combined file runs inside the App module namespace, so all module-level names (`UtopiaModule`, `g_kSystemWrapper`, `g_kConfigMapping`, etc.) are available without qualification.

### How to instrument

```powershell
uv run python tools/setup.py            # normal: uses cached .pyc (no recompile)
uv run python tools/setup.py --recompile  # force Python 1.5 to recompile App.py
uv run python tools/setup.py --capture    # after a successful recompile, cache the new .pyc
uv run python tools/uninstall.py          # restore game to working state
```

### Critical constraints discovered during instrumentation

**Python version:** stbc.exe embeds Python 1.5 (magic `0x4E99`), statically compiled into the binary alongside Appc. No separate `python15.dll`.

**Python 1.5 syntax:** `import X as Y` is Python 1.6+ and causes a fatal `SyntaxError` crash at startup. All snippet code must use plain `import X` and save aliases manually (`_time_func = time.time`). No f-strings, no `True`/`False` literals.

**Static build — limited stdlib:** `os` is not compiled into the binary and is not importable. `sys` is always available. Treat every `import` in snippet code as potentially absent and guard with `try/except ImportError`. Do not put any `import` that could fail at the outer module level — put them inside the GetGameTime wrapper where failures are caught.

**Timestamp trick:** `setup.py` writes `App.py` with its mtime set to match the value stored in `App.pyc` (bytes 4–7, little-endian Unix seconds), then copies `App.pyc.bak` as `App.pyc`. Python sees matching timestamps and loads from `.pyc` without recompiling. `--recompile` deliberately skips this trick for one launch to compile new snippet changes; `--capture` then caches the result.

**Python-level file I/O is blocked:** `open()` fails silently for all paths from within the game process (absolute, relative, `%TEMP%`). `os.system()` (cmd.exe subprocess) is also blocked. `sys.stdout.write()` crashes the game (stbc.exe is a GUI subsystem binary with no console handle). Do not use any of these in the snippet.

### Output mechanism: SaveConfigFile

The only confirmed working write path is the C++ engine's own file I/O, accessed via:

```python
g_kConfigMapping.SetStringValue("BCTickLog", "key", "value")
g_kConfigMapping.SetIntValue("BCTickLog", "count", n)
g_kConfigMapping.SaveConfigFile("BCTickLog.cfg")
```

`SaveConfigFile` writes to the game's working directory (`game/`), so the output lands at `game/BCTickLog.cfg`. The file is a full dump of all config state (all sections from `Options.cfg` plus the custom `[BCTickLog]` section appended). `tools/analyze_session.py` parses only the `[BCTickLog]` section.

The ConfigMapping API (argument order confirmed from SDK scripts):
- `SetStringValue(section, key, value)` / `GetStringValue(section, key)`
- `SetIntValue(section, key, value)` / `GetIntValue(section, key)`
- `SetFloatValue(section, key, value)` / `GetFloatValue(section, key)`
- `SaveConfigFile(filename)` / `LoadConfigFile(filename)`

### Current snippet behaviour

`appc_logger.py` wraps `UtopiaModule.GetGameTime` (the per-tick heartbeat called by AI scripts). Each unique `GetUpdateNumber()` frame is recorded as `"%f %d %f" % (wall_time, frame, game_time)` and buffered in a Python list. Every 30 seconds of wall time the buffer is flushed to `BCTickLog.cfg` via `SaveConfigFile`. On any exception, the error type and value are written to `[BCTickLog]` and the file is saved, so failures are visible without needing a debugger.

## Key architectural facts

- Object hierarchy: `ObjectClass → PhysicsObjectClass → DamageableObject → ShipClass`
- Python owns Appc objects it creates; must explicitly clean up in `__del__` via engine calls
- Save/load: 39 classes use `__getstate__`/`__setstate__`; saves Python-side state only, re-looks up Appc handles on restore
- `PythonMethodProcess` cannot be pickled — must be recreated in `__setstate__`
- Two independent time streams: `g_kTimerManager` (game time) and `g_kRealtimeTimerManager` (wall clock)
- Loop is single-threaded from Python's perspective (`sys.setcheckinterval(200)` in `Autoexec.py`)
- Python priority levels actually used: `NORMAL` (most things) and `LOW` (2 scripts only); `CRITICAL`/`UNSTOPPABLE` are C++ internal

## Project-root SDK shims

Some Python files at the project root exist specifically to **shadow SDK modules of the same name**. SDK scripts use bare imports (`import App`, `import LoadBridge`), and `tests/conftest.py` configures `_SDKFinder` to check `PROJECT_ROOT` before falling back to `sdk/Build/scripts/`. This is how Phase 1 swaps real SDK behaviour for headless stubs without forking the SDK tree.

Current shims:
- `App.py` — Phase 1 replacement for `Appc.dll` / `sdk/Build/scripts/App.py`
- `LoadBridge.py` — empty `SetClass` registration so `g_kSetManager.GetSet("bridge")` works headless
- `LoadDamageHitSounds.py` — project-authored SDK *companion* (no BC original): damage-impact sound names for `hit_feedback`. Lives here, not in `sdk/`, because BC content is no longer inside the project tree

Add new SDK-name shadows at the root only when needed; keep application code in `engine/`. If a third shim shows up, consider grouping them into a `shims/` directory and updating `_SDKFinder` accordingly.

## Rotation matrix convention — column-vector, right-handed

`TGMatrix3` stores **basis vectors as columns**. For a ship's world rotation `R`:

- `R.GetCol(0)` = ship-right (starboard) axis in world space
- `R.GetCol(1)` = ship-forward axis in world space (model-Y mapped through R)
- `R.GetCol(2)` = ship-up axis in world space (model-Z mapped through R)

**Handedness (right-handed, det = +1).** `AlignToVectors` builds
`right = forward × up`, so the basis is right-handed and `GetCol(0)` is the
TRUE starboard axis. The renderer draws `R` **directly with no reflection**
(`glFrontFace(GL_CCW)`). This replaced the historical left-handed convention
(`right = up × forward`, det = -1, which the renderer reflected with an
X-column flip — drawing every hull mirror-imaged) on **2026-06-18**; see
`docs/superpowers/plans/2026-06-18-render-handedness-unmirror.md`. Consequences:
cross products of rotated vectors **no longer flip sign** (det = +1), so the old
left-handed gotchas are retired; and `_PlayerControl` negates yaw/roll rates so
controls match the un-reflected view (pitch is unchanged).

Transforming a body-frame vector to world: `v_world = R · v_body`. The
SDK's `NiPoint3.MultMatrixLeft(R)` mutates `self` in place to that result;
our `engine/appc/math.py:TGPoint3.MultMatrixLeft` matches. `MakeXRotation`,
`MakeYRotation`, `MakeZRotation`, and `MakeRotation` all produce
standard column-vector rotation matrices.

Why column: the original Appc.dll wraps Gamebryo `NiMatrix3`, which is
column-vector internally, and the SDK only ever touches matrices through
`MultMatrixLeft` and `AlignToVectors` (it never reads rows or columns
directly — grep the 1228 SDK files). The SDK's *only* enforced constraint
is `MultMatrixLeft(R) ⇒ v_world = R · v_body`, which is column-vec. The
column choice is the one historically-faithful option, not an arbitrary
coin flip.

### Hard rules when reading rotations

- World-forward of any object: **`obj.GetWorldRotation().GetCol(1)`**.
  Never `GetRow(1)`. There is a helper `ObjectClass.GetWorldForwardTG()`
  that already does the right thing — prefer it.
- World-up: **`GetCol(2)`**. World-right: **`GetCol(0)`**.
- Body-frame angular velocity integration: `R_new = R · Δ_body`
  (**post**-multiply the body-frame delta). See
  `engine/host_loop.py:_PlayerControl` and
  `engine/appc/ship_motion.py:_step_ship_motion`.
- Body→world direction transform: `v.MultMatrixLeft(R)` — already does
  `R · v` correctly.
- Renderer hands `R` to the GL shader **directly** (no transpose, no
  reflection); the shader's `u_model` is column-vector and `R`'s columns are
  body axes. `_world_matrix_from` applies position + uniform scale only — there
  is **no** X-column flip (removed with the 2026-06-18 right-handed un-mirror;
  the NIF winding is handled by `glFrontFace(GL_CCW)` in `pipeline.cc`).

### When this convention was unified

Pre-refactor the codebase had a row/column split: `AlignToVectors`, the
renderer transpose, `_PlayerControl`, the camera spring, the Euler
extractor, and `radar_projection.py` used **rows**; `ships.py`,
`ship_motion.py`, `subsystems.py`, `emission.py`, the SDK callers (via
`MultMatrixLeft`), and the AI smoke tests used **columns**. Both
pipelines were internally consistent and the split survived only because
tests rarely exercised pitched orientations. The radar branch
(`9e79b7d`) and `68f6220` were skirmishes in opposite directions.
Branch `worktree-matrix-convention-unify` consolidated everything onto
column. If you see `GetRow(1)` in code that's reading a ship's world
forward, it is a regression — fix it.

## BC content paths — one authority, resolved at use

`game/` and `sdk/` do not have to live inside the project. `engine/paths.py`
resolves both roots from four sources in precedence order — `--game-dir` /
`--sdk-dir`, `DAUNTLESS_GAME_DIR` / `DAUNTLESS_SDK_DIR`, `settings.json`
`[paths]`, then the legacy in-project layout. The highest source that is
**set** wins even if it is invalid; falling through would silently run a
different install than the one that was asked for. A CLI flag persists; an
env var never does.

The data-dir accessors (`config_dir`, `saves_dir`, ...) follow the same
resolve-at-use rule: never capture one at import.

### Hard rules

- **Never spell `game` or `sdk` as a path segment.** Not in `engine/`, not in
  `tools/`, not in `tests/conftest.py`, not in `native/src`. Ask
  `paths.game_asset(rel)`, `paths.game_root()`, `paths.sdk_scripts()`,
  `paths.sdk_data()`.
- **Never capture a path at import.** No module-level constant may hold one.
  `paths.configure()` is callable again after boot — that is what the
  first-run picker needs — so anything captured at import is stale the moment
  the player picks a folder. `engine/missions/name_resolver.py`'s `TGL_ROOTS`
  was the densest instance of this trap.
- C++ joins relative asset paths onto `renderer::game_root()`, default the
  literal `"game"`. A literal `"game/"` reaching `resolve_asset_path` is a
  missed migration: it is stripped so the asset still loads, and logged once.

`tests/unit/test_path_indirection.py` enforces all three. The two Python
guards **parse rather than grep**: a grep flags every docstring citing
`sdk/Build/scripts/...` and still misses `dev_keybindings.py`'s nine-line
constant, where no single line holds both the root and the segment. A string
that describes the layout rather than building a path is exempted in place
with `# paths-guard: <reason>` — a prefix, not a fixed string, so two
different reasons (a Ghidra export label, a test fixture building a fake
install tree) can both live in the tree without colliding. `tools/probes/`
holds Python 1.5 sources injected into the original `stbc.exe`; modern `ast`
cannot parse them, so the guard skips them and a second test asserts the
skip never strays outside that one directory.

Spec: `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md`

## Shared checkout — NEVER run destructive git

This working tree is shared by **concurrent Claude sessions**, and feature
branches live in it directly (not in worktrees). Work is often deliberately
**uncommitted** for long stretches. In that situation, any git command that
restores the working tree from the index or from HEAD is a **destructive
command** — it silently deletes another session's (or your own) in-flight work,
and git offers no undo for uncommitted content.

**Banned outright — do not run these, and tell every subagent you dispatch not
to either (reviewers included):**

```
git checkout -- <path>     git checkout .      git restore <path>
git stash                  git clean           git reset --hard
git add -A / git add .     (sweeps other sessions' files into your commit)
```

`git checkout -b <new>` and `git checkout <branch>` are fine. Read-only git is
fine. Always stage with an **explicit pathspec**.

**To mutate a file temporarily** — which reviewers legitimately need to do, to
prove a test actually catches the bug it claims to — back it up and restore by
copy, never by git:

```bash
cp path/to/file /tmp/bak            # 1. back up
# ...mutate with Edit, run the test, watch it FAIL...
cp /tmp/bak path/to/file            # 2. restore
diff path/to/file /tmp/bak          # 3. PROVE the restore is byte-identical
```

**Why this rule exists:** during the letterbox work a *reviewer* subagent used
`git checkout --` to revert its own probe mutation and wiped the task's real,
uncommitted edit along with it. It only recovered because it happened to
re-check. A PreToolUse hook now denies these commands, but the hook is a net,
not the rule — do not go looking for a way around it.

## Build layout — single source of truth

There is **one** build tree at `<project-root>/build/`. The renderer host binary is at **`build/dauntless`** and the Python extension module is at **`build/python/_dauntless_host.cpython-*.so`**. Do not introduce alternate output locations.

- Build: `cmake -B build -S . && cmake --build build -j`
- Run:   `./build/dauntless`

Hard rules:

- **Never** spawn a new binary at a different path (e.g. `build/bin/open_stbc_host`, `native/build/...`, anywhere else). If you find such a binary, treat it as stale and delete it — do not run it.
- **Never** run `cmake` from inside `native/` (that produces a parallel `native/build/` tree that diverges from the canonical one).
- If the runtime fails with `AttributeError: module '_dauntless_host' has no attribute X`, the cause is a stale binary or stale `.so` — rebuild from `build/`, do not change the Python side.

## Setup

```bash
# Drop BC installation into game/, BC SDK v1.1 into sdk/
uv sync
uv run pytest
```

## Test gate — both suites, machine-checked baseline

⛔ **The gate runs ONLY when merging into `main`, and only when Mark says so.**
Never per feature, never per task, never on an integration branch. Features
merge into an integration branch (`int/<date>-NN`) with **no gate**: that
branch is a bubble, and the one full gate runs when it merges into main. Never
run whole pytest suites either (`tests`, `tests/unit`, `tests/ui`: ~15 min of
CPU). During development run **only the focused test files** for your change,
and tell every subagent you dispatch the same. **Why:** this machine is shared
and used for performance testing; every surprise gate or whole-suite run wrecks
a perf baseline. This overrides any plan, skill or brief step that says "run the
full suite" or "run the gate".

`scripts/run_tests.sh` is **pytest-only** and cannot see C++ regressions. When
merging into main, run the GATE instead:

```bash
scripts/check_tests.sh        # builds C++, runs pytest + ctest, diffs failures
```

It compares every failure against `tests/known_failures.txt` and **exits
non-zero, naming any failure not in that list** — that failure is a regression
this tree introduced, not "pre-existing". When a baselined test starts passing
the gate tells you to delete its line. **Skips are gated too:** a gtest SKIP exits 0,
so with a BC content root configured, any ctest skip not baselined as
`skip:ctest:<name>` fails the gate (asset-backed tests find content through
`native/tests/support/content_root.h`, never a hard-coded `<project>/game`). **And an in-process pass:** after ctest the gate runs each gtest
binary once, whole, from the project root (failures report as `inproc:<name>`),
because ctest's one-process-per-case from the build dir hid a real renderer bug
and a GL-state leak between fixtures. **Never call a failure "pre-existing" by
eyeball** — the ledger and the main-merge gate decide that.

**Read the ledger, never a remembered count.** This paragraph used to name "the
7 headless-GL scorch/heat-glow `FrameTest`s" long after they were fixed
(`5739e1b5` — they were never a headless-GL artifact; the shader's decal-normal
gate had been un-negated and the tests kept seeding inward normals). As of
2026-10-05 the ledger holds **no failure entries at all**, and the rule is to
keep it that way: fix a failing test, don't baseline it. Prose about the
baseline drifts, which is the whole reason the machine-checked ledger exists —
`cat tests/known_failures.txt` instead of trusting any sentence here.

A new required arg / changed output shape means you update that
thing's tests in the same change. Order-flaky? Run it in isolation to separate
cross-test pollution (reset leaked globals in `tests/conftest.py`'s autouse
`_reset_leakable_engine_globals`) from a real break.

## Executing plans

When asked to execute a plan in `docs/plans/`, dispatch one `tdd-engineer`
subagent per task in order, run that task's focused test files (never the full
suite or the gate — see "Test gate") and commit between tasks, and stop on any
BLOCKED.
