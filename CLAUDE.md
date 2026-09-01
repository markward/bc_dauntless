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
| Live game | `game/` | BC installation (gitignored) — needed for instrumentation |
| Space dust pass | `native/src/renderer/dust_pass.cc`, `docs/superpowers/specs/2026-05-11-space-dust-particles-design.md` | Camera-anchored dust particles with motion smear; toggle via `_h.dust_set_enabled()` |
| BCS save format | `docs/engine/bcs-save-format.md`, `tools/bcs_inspect.py` | Real binary save format; preamble + object table + TGL + pickle-memo decoded; 93.6% object-state region remains as parking-lot RE work |
| AI surface & gaps | `docs/engine/aieditor-ai-surface-and-gaps.md` | What the original `AIEditor` tool reveals about BC's AI: it's a code-generator emitting `CreateAI(pShip)` Python that Dauntless's `engine/appc/ai.py`+`ai_driver.py` already run. Maps the 7 AI container types, 8 named preprocessors, and 34 Condition classes against Dauntless's implementation. ⚠️ **Audited 2026-08-09 — two of its "confirmed gaps" were STALE.** `RandomAI` IS dispatched (`ai_driver.py:111`, `:478`) and `GetCloakingSubsystem` IS implemented (`ships.py:992`) — the latter caused a false confirmed gap. Still real: partial collision-avoidance (the reference cannot close it — `ProximityManager_Update` `0x005a83a0` is catalogued **stub**, body unreconstructed). **The ~10 Condition Appc-query rows are CLOSED 2026-08-11**: all ten names are real published API (addresses confirmed), and 8 were artifacts of an audit grep that searched `def <Name>(` — SWIG binds most of the surface at module level via `new.instancemethod`, so that grep can never match, and it also mis-attributes the receiver class. Two real gaps fell out, **both live-hit in `docs/stub_heatmap.md`, both ✅ FIXED 2026-08-11**: `WarpSequence.GetDestinationMission`/`GetDestinationEpisode` **plus `WarpSequence_Cast`** (all missing → truthy `_Stub` → `ConditionWarpingToMission` fired for *every* warp, and via the missing Cast even for ships **not warping at all** — fails ON, ranks 62/95) and `WaypointEvent` + `ET_AI_REACHED_WAYPOINT` (both undefined → `FollowWaypoints`' arrival broadcast was dead, killing `ConditionReachedWaypoint` and E8M2's handler, ranks 76/108/109/113). ✅ **`ET_SET_WARP_SEQUENCE` is CLOSED** (constant + emitter). The constant became real in the 2026-08-31 sweep (`0x8000ee`, measured); the emitter landed with it in `WarpEngineSubsystem.SetWarpSequence` (`engine/appc/subsystems.py`), so `ConditionWarpingToSet` now re-evaluates when the sequence changes instead of only at construction. Of the twelve event types that had real ints but no poster, **eleven are now closed and one remains** — `ET_RESTORE_PERSISTENT_TARGET`, where BC's engine owns both the persistent-target storage and the restore trigger. The torpedo pair closed 2026-09-01 by promoting `Torpedo` from `TGObject` to `ObjectClass` and giving it real set membership, which also made `GetClassObjectList(CT_TORPEDO)` answer for the first time. `docs/engine/event-emitter-gaps.md` is the live register — read it rather than this sentence, which has already gone stale once. **Treat every ❌ in `aieditor-ai-surface-and-gaps.md` as a hypothesis to re-check against `engine/`, not a fact — and never use a `def <Name>(` grep to decide whether engine surface exists.** |
| DamageTool & hull-damage gaps | `docs/engine/damagetool-and-hull-damage-gaps.md` | RTTI-extracted internals of BC's `DamageTool.exe` + 4 prioritized gaps vs our voxel-carve system. BC damage = summed **metaball field** (`MetaVolume(pos, influRad, strength)`; authored tiers 0.4/300 + 1.0/600; constant `strength≈750·influRad`) clipped by a `BinaryVoxel` hull mask — our `HullCarve`+`SourceVolumeCache` is the same shape. **Gap 1 ✅ DONE:** `DamageableObject.AddObjectDamageVolume`/`AddDamage`/`DamageRefresh`/`RemoveVisibleDamage`/`SetVisibleDamage*Modifier` now route authored + runtime visible damage into `host.hull_carve_add` via `engine/appc/visible_damage.py` (deferred queue, no native change). NOTE the missing methods never crashed — `TGObject.__getattr__` `_Stub` made them silent no-ops (wrecks rendered intact). `RemoveVisibleDamage` clears pending only; clearing emitted carves needs a native `HullCarveField::clear()` (still absent). Verify via `--developer` → mission picker → **Developer → Damage Preview** (`engine/dev_missions/damage_preview.py`). **Gap 2 ✅ DONE:** BC additive metaball field — `HullCarve` gains `strength`+`influ_radius`; `HullCarveField::add` accumulates strength; visible radius = `max(floor, fraction(strength)·ship_radius)`, 0 below the iso (150) so sub-iso accumulation is invisible/silent; `hit_feedback` accumulates strength across the throttle window (don't drop ticks) and deposits `absorbed_hull×STRENGTH_PER_HULL` (1.0). `hull_carve_add(influ, strength, time, floor=0, strength_size_ref=0)`. Tuning: `STRENGTH_PER_HULL`/influ in `hull_carve.py` (no rebuild); iso/curve are C++ `kHullCarve*` consts (rebuild). **Gap 3:** carve radii drift from BC's 0.4/1.0 GU (subsumed by the fraction-of-radius curve). **Gap 4 ✅ DONE (SDK-faithful):** carve sizes are **absolute** GU (a weapon makes the same hole on any hull — impacts don't shrink on smaller targets); the only per-ship scale is BC's authored `SetVisibleDamage{Radius,Strength}Modifier` (`radius_modifier` arg → carve radius, strength mod → deposit), set only on 10 fixed structures (DamageRadMod 5–15 + reciprocal DamageStrMod). A `GetRadius()`-proportional curve was tried first and reverted (physically wrong + double-counted size on the stations). Also: `breach_pass.cc` mis-sources its cavity texture from the `Damage1-4.tga` HUD glyphs, not `Textures/Effects/Damage.tga`. |
| **Perf cadences that are also GAMEPLAY latency** | `engine/appc/subsystems.py:115` (`SHIELD_CHARGE_PERIOD_S`), `engine/ui/panel_registry.py`, `engine/appc/ai_optimized.py:138`, `engine/appc/ai_driver.py` (`AI_MAX_SLEEP_TICKS`) | Four things that used to run every tick now run on a cadence. Each was landed as a perf win and each is **also a behaviour change** — check here before reading a delayed reaction as a bug. **Shields charge every 0.5 s**, not per tick: total charge is conserved (the banked interval is applied whole) but regen is a staircase, so the HUD bar and bubble intensity step, and `_shield_watchers` crossing events (`ConditionSingleShieldBelow` et al) fire up to 0.5 s late — a 30x latency increase on shield-threshold AI reactions. The 0.5 s figure is BC's, from `stbc_reference` `spec/ShieldFacingDamage.md §6.1`, graded **reviewed-not-tested** — RE-tier, not TESTED. **The target list polls at 2 Hz**; it is marked due immediately on its own events, on a visibility flip, and (host loop) whenever the engine changes the player's target or subsystem behind its back. ⚠️ Do NOT put a game-state mutation in `render_payload` — `_reconcile_subsystem_lock` was there and the throttle silently gave the player's phasers up to 0.5 s aiming at a destroyed subsystem; it is now `reconcile_subsystem_lock()` at module scope, driven per-frame from the host loop beside `clear_undetectable_player_lock`. **An evading ship re-decides avoidance at 4 Hz** (`AVOID_EVADING_UPDATE_DELAY_S = 0.25`, BC's own commented-out `fMinimumUpdateDelay` — `AI/Preprocessors.py:1624` reads `0.0 # 0.25`) — measured NOT to degrade separation at realistic radii, but the value is pinned by a test: re-run the separation probes before changing it. ⚠️ **Until 2026-08-28 this sentence described a configuration nobody ran.** The cadence (and the `_phase_factor` herd-breaker) were applied only in `_replace_avoid_obstacles`, i.e. to the *engine* scan, which is opt-in behind `DAUNTLESS_ENGINE_AVOIDANCE=1` and off by default; the default SDK path got neither. It was invisible because avoidance was **wholly inert** — `ProximityManager.GetNextObject` was a hardcoded `return None`, so BC's `GetNearObjects`/`GetNextObject`/`EndObjectIteration` walk exited before its first iteration and `AvoidObstacles.TestCourseOverride` always reported "nothing to avoid". Both are fixed; both now apply on the default path. Re-measured: +0.27 ms of sim per tick at 16 **and** 32 ships (it was +1.4 / +3.4 ms with the cadence missing). **A ship's AI tree may sleep up to `AI_MAX_SLEEP_TICKS` (66 ms)**, so `ForceUpdate` is no longer 'next tick'. ⚠️ These last two COMPOUND: avoidance now lives inside the sleeping AI tree (`tick_collision_avoidance` was removed from `GameLoop.tick`), so worst-case re-decision is 0.25 s + sleep skew. Each was measured alone; **the combination has not been measured live.** |
| **Frame profiler — MEASURE BEFORE OPTIMISING** | `docs/engine/frame-profiler.md`, `native/src/renderer/frame_timer.{h,cc}`, `engine/core/frame_profiler.py` | Per-pass CPU+GPU timing for both halves of the frame. Toggle with `` ` `` under `--developer`; report to stderr every 120 frames. **Read the doc before drawing a conclusion from it** — four ways to read a correct number and reach a wrong one: `present` is the **vsync wait when the swap interval is 1** — the report prints the interval, READ IT rather than assuming (it prints `-1` for "could not read", which is not `0`); at interval 1 a big `present` means the frame finished EARLY; the Python and render totals **nest, they do not add** (`r.frame()` runs inside the loop body); whole-frame GPU is first-timestamp-to-last, **not** a sum of the nested scopes; and a stale extension module reports the render half `UNAVAILABLE` rather than zeros. ⛔ **The GPU column is DEAD on this Mac** — Apple's GL returns zeroed `GL_TIMESTAMP` counters (measured: 117 resolved frames of exactly 0), and because `gpu_ms` only accumulates when `t1 >= t0` every span is `>= 0` by construction, so a dead driver and a free GPU are indistinguishable. The report now prints **GPU TIMING UNAVAILABLE** and blanks the column after 30 such frames. Every GPU figure recorded before 2026-08-28 was never measured; the CPU columns are unaffected. Unattended capture: `OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_PROFILE_FRAMES=600 ./build/dauntless --developer`. ⛔ It MUST run through `dauntless.exe`, not `python -c host_loop.run()` — CEF only initialises when `main()` runs `dispatch_subprocess` before Python starts, so a python-driven capture prints `cef.pump`/`cef.composite` as `0.000`, which reads as free and means ABSENT. ⛔ **CHECK THE SCENE LINE — every early capture with this profiler measured an IDLE game** (QuickBattle boots `g_kEnemyList = []`; E3M1/E2M1/E8M1 fire nothing in 900 ticks), and combat is **20-50x** the idle sim cost (~1.4 ms idle → ~70 ms at 17 ships). Use `DAUNTLESS_MISSION=engine.dev_missions.combat_stress DAUNTLESS_COMBAT_SHIPS=16`. ⚠️ That mission's avoidance default flipped OFF→**ON** (QuickBattle wraps its attack tree in `AvoidObstacles`, so off was never faithful to the scene it imitates), so captures taken before the flip do not reproduce — `DAUNTLESS_COMBAT_AVOID=0` restores them. It also seeds its nominal 4 GU hull radius **headless-only** now; it used to win the race against `_realize_session` and pin every live ship to the same radius. Combat frame (17 ships, ~70 projectiles): `sim` ~70 (`sim.combat` ~25-33, `sim.gameloop` ~35 = `gl.ai` ~10 + `gl.subsystems` ~7.6 + `gl.motion` ~5.6), `ui_panels` ~17, `render_prep` ~12, `r.frame` ~15-24. ⚠️ Run-to-run variance is large and external load inflates EVERYTHING at once — if `gl.ai`/`ui_panels`/`gl.motion` all move together by 2-3x that is contention, not a regression. **Two landed wins:** projectile/ship broadphase (`sim` 166 → ~87 at matched load) and the impulse derating computed once per ship-tick instead of four times (motion path −27%). ⛔ **Open the box before choosing the fix** — `gl.motion` looked like a matrix problem; unrolling `MultMatrix` (3.74x on the primitive) moved it 10.45 → 9.9 ms, and cProfile then showed the multiply was 2.5% of the path while `impulse_output_fraction` was 55%. **Two scenes, two different bottlenecks — profile the one you mean to fix.** QuickBattle/bridge: `render_prep` **15.8 ms**, `r.frame` 7.7 ms (of which `anim` **4.1 ms** = bone palettes for every animated instance, ungated, and `cef.composite` **1.9 ms CPU + 1.3 ms GPU** = the full-surface overlay upload, no dirty-rect, no PBO). E3M1/exterior: `ui_panels` **10.7 ms**, `sim` 5.0 ms, `render_prep` 0.8 ms. Both scenes: `scene_push` 0.7–1.5 ms (lights/backdrops/suns/planets/nebulae/decals/warp VFX — this was reported as `starmap` until the phase was split; the star map early-returns when closed and was never the cost); real `input` is 0.034 ms. The dominant costs are Python-side and CPU-side; none of them is a thread-count problem. Off by default (a predicted branch; no GL object created), results read back 3 frames late so resolving never stalls the pipeline. |
| Developer flag | `engine/dev_mode.py`, `native/src/host/developer_mode.{h,cc}`, `docs/superpowers/specs/2026-06-02-developer-flag-design.md` | Runtime `--developer` flag gating dev-only keybindings, pause-menu sections, renderer overlays, and CEF panels. Parse once in C++ (`host_main.cc`), read via `dauntless::is_developer_mode()` / `engine.dev_mode.is_enabled()` / `window.__DAUNTLESS_DEV__`. Exposed to Python as `_dauntless_host.developer_mode`. Register dev keybindings with `dev_mode.register_dev_keybinding(...)`; register dev pause-menu rows with `dev_mode.register_dev_pause_menu_entry(label, handler)`; wrap dev-only behaviour with `@dev_mode.dev_only`. CSS-hide CEF elements with class `dev-only`. |
| Dev mission loader | `engine/dev_mission_picker.py`, `native/assets/ui-cef/{js/mission_picker.js,css/hello.css,hello.html}`, `docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md` | Developer-only "Load Mission…" pause-menu row that opens a CEF-rendered centred-modal picker listing every discoverable SDK mission (family → episode → mission). Picker is a `Panel` subclass pumped by `PanelRegistry`; one click on a mission row calls `controller.swap_mission(module)` + `pause.close()`. Lazy SDK walk on first open. ESC and Cancel route back to the pause menu; pause-menu hides while picker is open. |
| Developer Options menu | `engine/ui/developer_options_panel.py`, `engine/dev_combat_cheats.py`, `native/assets/ui-cef/js/developer_options.js`, `docs/superpowers/specs/2026-06-08-developer-options-menu-design.md` | Developer-only "Developer Options…" pause-menu modal styled like the configuration panel (reuses its `cp-*` CSS + shared backdrop). Combat tab toggles God Mode, 2× player weapon strength, and Disable NPC Shields — all hook `combat.apply_hit` via the dev-mode-gated flags in `dev_combat_cheats` (`*_active()` getters AND with `dev_mode.is_enabled()`, so production combat is byte-identical). God mode skips damage mutation but keeps hit feedback (`persist_decal=False` suppresses only the permanent scar). Off by default, not persisted across launches. |
| Ship Property Viewer | `engine/ui/ship_property_viewer.py`, `engine/ui/ship_property_viewer_panel.py`, `native/src/renderer/{hologram_pass,subsystem_pin_pass}.cc`, `native/assets/ui-cef/js/ship_property_viewer.js`, `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md` | Developer-only "Ship Property Viewer" pause-menu modal: the player ship rendered as a translucent Fresnel hologram (`opacity = 0.70 − 0.50·\|N·V\|`, facing→0.20 grazing→0.70, blue back-face glow; `hologram_pass` re-draws the real ship instance with the solid hull hidden via `set_visible(iid, False)`) with camera-facing billboard pins per subsystem (white disc + black class Damage glyph, `subsystem_pin_pass`, world-scaled `kPinWorldSize`, drawn depth-test-off so none hide behind the hull). Pins sit at `subsystem_world_position` mounts (ship world-loc + R·local, **no scale**). Orbit camera + projection + pin-picking are pure Python in `ship_property_viewer.py` (the GL passes get the same camera via `set_camera`, so picks match by construction). Click a pin → property popover. Everything is absolute world space; the camera orbits the subsystem centroid (no re-centring). Opens from the dev pause menu (sim already frozen via `frame_dt=0`); off by default; production render path byte-identical (panel never constructed without `--developer`). The two GL passes take `(camera, viewport_rect)` for a future render-to-texture windowed mode. |
| **Stub heatmap — CHECK BEFORE CLAIMING A NO-OP** | `docs/stub_heatmap.md`, `tools/stub_heatmap.py`, `engine/core/stub_telemetry.py` | **Trigger: any time you suspect — or are about to assert — that an SDK call is (or isn't) a silent no-op, READ `docs/stub_heatmap.md` FIRST. Never assert stub behaviour from reasoning alone.** It ranks unimplemented attrs by live hit count, plus **Boolean-test call sites (truthiness risk)** and **Numeric-coercion call sites (`int()==0` risk)** tables. Since 2026-07-12 it covers **both** stub paths: the *instance* path (`TGObject.__getattr__` → `_Stub`) **and** the *App-module* path (`App.<name>` → `_NamedStub`), including the silent-collapse operators — so an undefined **constant** (`App.<CLASS>.<CONST>`) now shows up instead of quietly degrading to truthy / `int()==0`. That class had already caused ≥4 real bugs (keyboard `WC_*`; `TGUIObject.ALIGN_*` collapsing every `AlignTo` to `ALIGN_UL`; `EngRepairPane.REPAIR_AREA`; `STTopLevelMenu_GetOpenMenu` making BC's cutscene menu-drop a no-op) — **if you see a name in the coercion/truthiness tables, treat it as a live bug, not noise.** Note the stubs still *behave* the same (truthy / 0); the telemetry only observes. Whole SDK **modules** can also be silently stubbed in the twin stub lists (`tools/mission_harness.py` AND `tests/conftest.py` — fix BOTH), and **never unstub a whole module to reach one function** — its body needs engine surface we lack; reimplement that one behaviour at the equivalent engine hook. |
| Measured constant surface | `engine/appc/constants_generated.py`, `engine/appc/constants_apply.py`, `tools/gen_app_constants.py`, `tests/unit/test_constant_surface.py`, `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md` | All 3,829 `App` constants read out of a running original `stbc.exe` by probe q13, applied to the shim 2026-08-31 — 581 previously-wrong values corrected and every previously-missing constant defined, leaving the shim at `ok=3825 wrong=4 missing=0`. **Never hand-edit `constants_generated.py`** — it is GENERATED; change `tools/gen_app_constants.py` or add a `DEVIATIONS` entry in `engine/appc/constants_apply.py`. `test_constant_surface.py` ratchets the surface (`REMAINING_WRONG` may only fall) and runs its terminal assertion with **0 skipped** — every remaining difference must be a declared deviation. The floor is **4, not 0**: `PI`/`HALF_PI`/`TWO_PI`/`FOURTH_PI` are kept at Python double precision against BC's float32 on purpose. Two traps this sweep uncovered, both live bug classes if re-broken: BC's `CSP_*` polarity is **lower = higher priority** (`engine/appc/crew_speech.py` is written to match — change one, change both), and `CT_*` are **int tags**, resolved to classes for `isinstance` filtering by an int↔class registry in `engine/appc/object_types.py`, not the class objects themselves. One RE finding worth keeping: our `ET_TORPEDO_AMMO_CONSUMED`, reverse-engineered from the binary with no SDK symbol, turned out to equal BC's own `ET_PLAYER_TORPEDO_COUNT_CHANGED` (both `0x800067`) — the RE recovered the real behaviour (player-only torpedo-count broadcast) correctly, only the name was invented. ⚠️ **Fixing a constant's VALUE does not add its emitter or its call site** — three event types (`ET_TORPEDO_ENTERED_SET`/`_EXITED_SET`, `ET_RESTORE_PERSISTENT_TARGET`) still have real ints but nothing in the engine posts them; their SDK handlers are still dead. Nine of the original twelve are closed as of 2026-08-31 (`ET_SET_TARGET` closed as a documented non-emission, not a pending gap). See `docs/engine/event-emitter-gaps.md`. **Live-verified 2026-08-31** (Mark, 8-test in-game plan): keyboard flight + F-keys + modifier chord; E1M1 `s` skip-intro; nebula/planet/sun render with the orbit menu correctly listing planets not suns; subsystem targeting → repair pane; tactical/engineering/bridge-menu layout and Galaxy/Sovereign icons unmoved; mission narration correctly interrupting engineer chatter (`CSP_` polarity); the five revived bridge menu items (*medium* confidence — they respond, but only three have unambiguous visible results); red alert + warp flash now non-positional (`LS_3D`). The two silent-failure paths (`CT_*` type dispatch, tests 3 and 4) both passed. One fatal crash surfaced during that run and was fixed in `3748fb96` — an **unrelated, pre-existing** hazard this sweep neither caused nor covered: `g_k*Color` globals are Appc *instances*, not scalars, so the q13 dump never held them; 40 of the 51 the SDK references remain undefined and now degrade to a default colour instead of killing the frame (`engine/ui/info_box_panel.py:_color_to_list`). Recovering their real values needs its own probe. |
| Cutscene letterbox — a RENDERER pass, not UI | `native/src/renderer/letterbox_pass.cc`, `engine/ui/letterbox.py`, `docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md` | The `StartCutscene..EndCutscene` bars are **GL, drawn below the whole UI layer** — `glScissor`+`glClear` into FBO 0 in `host_bindings.cc:frame()`, after the post chain resolves and **before `ui_cef::composite()`**. That ordering IS the feature: every CEF element (subtitles, crew menus, info boxes, pause menu) lands on top of the bars **by construction**, with no z-index to forget. **Do NOT re-add them as DOM.** They were `.sdk-letterbox` at `z-index: 5` and every HUD root here has *no* z-index (`#tactical-left-column`, `#tactical-bottom-row`, reticle text, `#ai-inspector-panel`) → CSS painted the bars *over* the UI; that shipped a real bug (E1M1's XO menu vanished under them mid-tutorial — see `tests/ui/test_sdk_panel_positions.py`). Flow: `TopWindow.letterbox_snapshot()` → `LetterboxAnimator` (smoothstep ease; replaces the old CSS `transition`; `transition_s == 0` snaps for `AbortCutscene`) → `_pump_letterbox` (host loop, **every frame, unconditional**) → `renderer.letterbox_set(covered)`. `covered` is BC's `fCoveredArea` — the **TOTAL** fraction across both bars (0.125 ⇒ 6.25% each); the native pass halves it. Fed `_player_dt`, so the bars **freeze under pause/DevTools** instead of sliding on wall-clock. Reset in the mission-swap block (the animator outlives `TopWindow`). Skipped in hologram-only mode (the SPV owns the frame). |
| Shield face + impact splash | `engine/appc/combat.py:_shield_face_from_hit_point`, `native/src/renderer/shaders/shield.frag`, `native/src/renderer/shield_state.h` | **Which shield face a hit belongs to is a HULL-BOX question, not a 45° cone.** BC hulls are 4–8:1 (Galaxy half-extents 232/322/70 NIF units; Sovereign 115/350/41), so comparing raw body-frame components labelled only **6.6%** of a Galaxy's dorsal surface TOP (Sovereign 4.2%) and billed the rest to FRONT/REAR/LEFT/RIGHT. The delta is now measured from the hull **AABB centre** (the model origin is off-centre on real hulls — Sovereign −6.98 Z, Keldon +14.30 Z / −81 Y — which inverts the dorsal/ventral call near the mid-plane) and **normalised by the half-extents**. The box is cached at spawn by `host_loop._cache_shield_hull_box` from the same `model_aabb` the shield bubble is centred on, in world units at `GetScale()==1`. Ships with no cached box fall back to the raw-axis rule. **The normalisation is OUR design**, checked against the clean-room reference 2026-08-11. **CONFIRMED:** `ShieldClass` holds **no geometry** — its object model (`sizeof 0x15C`) is six per-facing scalars (`m_curShields[6]`, `m_fraction[6]`, `m_breached[6]`) + a combined fraction + `FloatRangeWatcher[7]`, caps on the companion ShieldProperty; no extents/offsets/normals/box anywhere. So BC's facing decision is necessarily made from hull geometry held elsewhere, as here. Also confirmed: facings are front/rear/top/bottom/left/right with `GetNumShields()` a fixed 6, the 7th combined watcher slot matches our `NUM_SHIELDS + 1` array, and of the 20 scripted `ShieldClass_` entries every facing-taking one takes an **already-resolved index** — none applies damage, none maps a point/direction to a facing, so the chooser is engine-internal and was never script-visible. ✅ **SETTLED 2026-08-16** — `stbc_reference` `spec/ShieldFacingDamage.md` (graded `reviewed-not-tested` throughout; every routine on the path is unreconstructed — read, never executed). The chooser is **`ShipClass::TestHit` `0x005AE730`**, not ShieldClass, and it runs at **collision-detection time on a SEGMENT**, leaving the facing in `ShipClass+0x240` for `ApplyWeaponHit` to consume and reset. The bubble is cached on ShipClass (`+0x24C..+0x254` semi-axes, `+0x258..+0x260` centre) from the **model** bound half-extents × √3 (`ComputeShieldEllipsoid` `0x005ABAC0`). Our normalisation is **vindicated**: dividing by semi-axes vs raw half-extents differs only by uniform scalars, so it cannot change which axis wins, and our axis→index table and y→z→x tie order match the binary exactly. ⚠️ **But our INPUT is wrong** — BC takes the dominant axis of the point where the shot's segment **enters** the ellipsoid (ray/sphere intersection), not of the hull impact point; these agree on the surface and diverge on grazing/long-step shots. ⚠️ **Three further divergences, all unimplemented:** absorption is **NOT a strict cascade** (pass-through fraction `b`: 0 at `f≥0.6`, ramping to 0.6 at `f≤0.1`, plus overdraw — our probe measured only full facings, where `b=0`, and over-generalised); beams apply damage in **0.5 s pulses**, matching the shield charge tick that refreshes the `m_fraction` the ramp reads; and every overlapping subsystem takes the **full** damage (residuals summed), not a weighted share. Confirmed correct as-is: hull is dropped only for a `PhaserBank` with `+0xAC == 0` (default 1), so **torpedoes never drop the hull**; collision/scripted damage bypasses facings; and the binary's distance factor `min(1, R/d)` independently confirms our probe-measured falloff. Facing *names* ("0 = front") remain **unsourced** — see `docs/instrumented_experiments/2026-08-16-shield-facing-and-beam-falsifiers.md`. Renderer half: the splash is a disc on the **bubble** (impact direction projected to the fragment's own radius — the hull sits √3−1 ≈ 236 world-units inside the bubble on a Galaxy's long axis, so measuring from the hull point blanks bow/stern flashes), gated to the hit-facing hemisphere (`shield_splash_gate`; without it the antipode samples uv (0.5,0.5) = the texture CENTRE, painting a full-brightness mirror on the opposite face — and with depth test on, the **mirror is the one you can see**), radius keyed to the **smallest** half-extent (`shield_hit_radius`). Face labels are correct: `LEFT_SHIELDS` = port = body −X (`sdk/.../Hardpoints/galaxy.py:913` `PortWarp.SetPosition(-1.30, -2.10, -0.06)`). |
| Game-unit conversion | `engine/units.py` | BC stores **everything** spatial (positions, velocities, distances, radii) in a single internal unit, "game units" (GU). **1 GU = 175 m = 0.175 km, 1 GU/s = 630 km/h.** Derived from Galaxy `SetMaxSpeed(6.3)` → 3969 kph in BC's helm tooltip (`sdk/.../BridgeHandlers.py:1389` via `Appc.UtopiaModule_ConvertGameUnitsToKilometers`). Physics, renderer, and camera stay in GU end-to-end; **only convert at display boundaries** via `GU_TO_KM` / `GUPS_TO_KPH`. Never call any variable `*_m` / `*_mps` — speed/range inside the engine is **always** `*_gu` / `*_gups`. |
| E1M1 intro skip | `docs/engine/e1m1-skip-intro.md`, `engine/appc/input.py`, `engine/dev_tutorial_flag.py` | BC's "Press 's' to skip introduction" prompt. Needed FIVE pieces of missing surface: `TGKeyboardEvent.GetUnicode`, a real `App.ET_KEYBOARD` int, raw `ET_KEYBOARD` dispatch down the window chain (`_raw_keyboard_destination`), `TGInputManager.GetDisplayStringFromUnicode` (heatmap rank 57, 342 hits), and `TGActionManager_KillActions` — whose registry had to become name→**list** because E1M1 registers six sequences under `"CharacterIntros"`. ⚠️ The `PlayedTutorial` gate is only forced under `--developer` for now; persisting the `"global"` VarManager scope is deferred to persistent-save work. |

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

`scripts/run_tests.sh` is **pytest-only** and cannot see C++ regressions. Before
merging, run the GATE instead:

```bash
scripts/check_tests.sh        # builds C++, runs pytest + ctest, diffs failures
```

It compares every failure against `tests/known_failures.txt` and **exits
non-zero, naming any failure not in that list** — that failure is a regression
this tree introduced, not "pre-existing". When a baselined test starts passing
the gate tells you to delete its line. **Never call a failure "pre-existing" by
eyeball; run the gate.**

**Read the ledger, never a remembered count.** This paragraph used to name "the
7 headless-GL scorch/heat-glow `FrameTest`s" long after they were fixed
(`5739e1b5` — they were never a headless-GL artifact; the shader's decal-normal
gate had been un-negated and the tests kept seeding inward normals). As of
2026-08-06 the ledger holds **zero ctest entries** and **exactly one pytest
entry**: the order-dependent
`test_engineer_emitters.py::test_shield_level_change_announces`. Prose about the
baseline drifts, which is the whole reason the machine-checked ledger exists —
`cat tests/known_failures.txt` instead of trusting any sentence here.

A new required arg / changed output shape means you update that
thing's tests in the same change. Order-flaky? Run it in isolation to separate
cross-test pollution (reset leaked globals in `tests/conftest.py`'s autouse
`_reset_leakable_engine_globals`) from a real break.

## Executing plans

When asked to execute a plan in `docs/plans/`, dispatch one `tdd-engineer`
subagent per task in order, run the full suite and commit between tasks, and
stop on any BLOCKED.
