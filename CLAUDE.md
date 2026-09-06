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
| BC content paths | `engine/paths.py`, `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md` | Where `game/` and `sdk/` live. Four sources, highest **set** one wins even when invalid. Resolved at USE, never at import — a module-level constant is stale the moment the first-run picker changes a root. Guarded by `tests/unit/test_path_indirection.py`. |
| Space dust pass | `native/src/renderer/dust_pass.cc`, `docs/superpowers/specs/2026-05-11-space-dust-particles-design.md` | Camera-anchored dust particles with motion smear; toggle via `_h.dust_set_enabled()` |
| BCS save format | `docs/engine/bcs-save-format.md`, `tools/bcs_inspect.py` | Real binary save format; preamble + object table + TGL + pickle-memo decoded; 93.6% object-state region remains as parking-lot RE work |
| AI surface & gaps | `docs/engine/aieditor-ai-surface-and-gaps.md`, `docs/engine/event-emitter-gaps.md` | What BC's `AIEditor` reveals about its AI: it is a code *generator* emitting `CreateAI(pShip)` Python that `engine/appc/ai.py` + `ai_driver.py` already run. Maps the 7 AI container types, 8 preprocessors and 34 Condition classes against ours. ⚠️ **Treat every ❌ in that doc as a hypothesis to re-check against `engine/`, not a fact** — an audit found several of its "confirmed gaps" already implemented. **Never use a `def <Name>(` grep to decide whether Appc surface exists**: SWIG binds most of the surface at module level via `new.instancemethod`, so that grep can never match, and it mis-attributes the receiver class. All 12 event-emitter gaps are now closed — `event-emitter-gaps.md` is the live register. Still genuinely open: partial collision avoidance (`ProximityManager_Update` is catalogued **stub**, body unreconstructed). |
| DamageTool & hull-damage gaps | `docs/engine/damagetool-and-hull-damage-gaps.md` | RTTI-extracted internals of BC's `DamageTool.exe` plus 4 prioritized gaps against our voxel carve. BC damage is a summed **metaball field** clipped by a `BinaryVoxel` hull mask — our `HullCarve` + `SourceVolumeCache` is the same shape. Gaps 1, 2 and 4 are ✅ DONE; gap 3 is subsumed by the fraction-of-radius curve. Carve sizes are **absolute** GU — a weapon makes the same hole on any hull; the only per-ship scale is BC's authored `SetVisibleDamage{Radius,Strength}Modifier`. Tuning: `STRENGTH_PER_HULL` / influ in `hull_carve.py` (no rebuild); iso and curve are C++ `kHullCarve*` consts (rebuild). Verify via `--developer` → mission picker → **Developer → Damage Preview**. The doc re-verifies its own gap claims against the tree — read it before citing a gap. |
| **Perf cadences that are also GAMEPLAY latency** | `docs/engine/perf-cadences-and-latency.md` | Four things that used to run every tick now run on a cadence, and each is **also a behaviour change** — check here before reading a delayed in-game reaction as a bug. Shields charge every 0.5 s; the target list polls at 2 Hz; an evading ship re-decides avoidance at 4 Hz; a ship's AI tree may sleep up to 4 ticks (~66 ms), so `ForceUpdate` is no longer 'next tick'. ⚠️ The last two **COMPOUND** — avoidance now lives inside the sleeping AI tree — and **the combination has never been measured live.** ⚠️ Do NOT put a game-state mutation in `render_payload`: one there silently gave the player's phasers up to 0.5 s aiming at a destroyed subsystem. Both AI cadences are env-overridable, which is how you test whether a suspected latency bug is one of them. |
| **Frame profiler — MEASURE BEFORE OPTIMISING** | `docs/engine/frame-profiler.md`, `native/src/renderer/frame_timer.{h,cc}`, `engine/core/frame_profiler.py` | Per-pass CPU+GPU timing for both halves of the frame. Toggle with `` ` `` under `--developer`; report to stderr every 120 frames. **Read the doc before drawing a conclusion from it** — there are four ways to read a correct number and reach a wrong one (`present` is the vsync wait, so a big value means the frame finished EARLY; the Python and render totals **nest, they do not add**; whole-frame GPU is first-to-last, not a sum; a stale extension module reports UNAVAILABLE rather than zeros). ⛔ **The GPU column is DEAD on this Mac** — every GPU figure recorded before 2026-08-28 was never measured. ⛔ It must run through `./build/dauntless`, not python. ⛔ **CHECK THE SCENE LINE** — combat is 20-50× the idle sim cost, so use `DAUNTLESS_MISSION=engine.dev_missions.combat_stress`. Off by default. |
| Developer flag | `engine/dev_mode.py`, `native/src/host/developer_mode.{h,cc}`, `docs/superpowers/specs/2026-06-02-developer-flag-design.md` | Runtime `--developer` flag gating dev-only keybindings, pause-menu sections, renderer overlays, and CEF panels. Parse once in C++ (`host_main.cc`), read via `dauntless::is_developer_mode()` / `engine.dev_mode.is_enabled()` / `window.__DAUNTLESS_DEV__`. Exposed to Python as `_dauntless_host.developer_mode`. Register dev keybindings with `dev_mode.register_dev_keybinding(...)`; register dev pause-menu rows with `dev_mode.register_dev_pause_menu_entry(label, handler)`; wrap dev-only behaviour with `@dev_mode.dev_only`. CSS-hide CEF elements with class `dev-only`. |
| Dev mission loader | `engine/dev_mission_picker.py`, `native/assets/ui-cef/{js/mission_picker.js,css/hello.css,hello.html}`, `docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md` | Developer-only "Load Mission…" pause-menu row that opens a CEF-rendered centred-modal picker listing every discoverable SDK mission (family → episode → mission). Picker is a `Panel` subclass pumped by `PanelRegistry`; one click on a mission row calls `controller.swap_mission(module)` + `pause.close()`. Lazy SDK walk on first open. ESC and Cancel route back to the pause menu; pause-menu hides while picker is open. |
| Developer Options menu | `engine/ui/developer_options_panel.py`, `engine/dev_combat_cheats.py`, `native/assets/ui-cef/js/developer_options.js`, `docs/superpowers/specs/2026-06-08-developer-options-menu-design.md` | Developer-only "Developer Options…" pause-menu modal styled like the configuration panel (reuses its `cp-*` CSS + shared backdrop). Combat tab toggles God Mode, 2× player weapon strength, and Disable NPC Shields — all hook `combat.apply_hit` via the dev-mode-gated flags in `dev_combat_cheats` (`*_active()` getters AND with `dev_mode.is_enabled()`, so production combat is byte-identical). God mode skips damage mutation but keeps hit feedback (`persist_decal=False` suppresses only the permanent scar). Off by default, not persisted across launches. |
| Ship Property Viewer | `engine/ui/ship_property_viewer.py`, `engine/ui/ship_property_viewer_panel.py`, `native/src/renderer/{hologram_pass,subsystem_pin_pass}.cc`, `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md` | Developer-only pause-menu modal: the player ship drawn as a translucent Fresnel hologram (`hologram_pass` re-draws the real instance with the solid hull hidden via `set_visible(iid, False)`) with camera-facing billboard pins per subsystem (`subsystem_pin_pass`, depth-test off so none hide behind the hull). Pins sit at `subsystem_world_position` mounts (ship world-loc + R·local, **no scale**). Orbit camera, projection and pin-picking are pure Python; the GL passes get the same camera via `set_camera`, so picks match by construction. Everything is absolute world space. Off by default, and the production render path is byte-identical — the panel is never constructed without `--developer`. |
| **Stub heatmap — CHECK BEFORE CLAIMING A NO-OP** | `docs/stub_heatmap.md`, `tools/stub_heatmap.py`, `engine/core/stub_telemetry.py` | **Trigger: any time you suspect — or are about to assert — that an SDK call is (or isn't) a silent no-op, READ `docs/stub_heatmap.md` FIRST. Never assert stub behaviour from reasoning alone.** It ranks unimplemented attrs by live hit count, plus **Boolean-test (truthiness risk)** and **Numeric-coercion (`int()==0` risk)** call-site tables. It covers both stub paths — the instance path (`TGObject.__getattr__`) and the App-module path (`App.<name>`) — so an undefined **constant** now shows up instead of quietly degrading to truthy / 0. That class has caused ≥4 real bugs, so **if you see a name in those tables, treat it as a live bug, not noise.** Whole SDK **modules** can also be silently stubbed in the twin lists (`tools/mission_harness.py` AND `tests/conftest.py` — fix BOTH), and **never unstub a whole module to reach one function.** |
| Measured constant surface | `engine/appc/constants_generated.py`, `engine/appc/constants_apply.py`, `tools/gen_app_constants.py`, `tests/unit/test_constant_surface.py`, `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md` | All 3,829 `App` constants read out of a running original `stbc.exe` and applied to the shim 2026-08-31 — 581 wrong values corrected, leaving `ok=3825 wrong=4 missing=0`. The floor is **4, not 0**, on purpose: `PI` and friends stay at double precision against BC's float32. **Never hand-edit `constants_generated.py`** — it is GENERATED; change `tools/gen_app_constants.py` or add a `DEVIATIONS` entry in `constants_apply.py`. Two traps, both live bug classes if re-broken: BC's `CSP_*` polarity is **lower = higher priority** (`crew_speech.py` matches it — change one, change both), and `CT_*` are **int tags** resolved via an int↔class registry, not the class objects. ⚠️ Fixing a constant's VALUE does not add its emitter — see `docs/engine/event-emitter-gaps.md`. |
| Cutscene letterbox — a RENDERER pass, not UI | `native/src/renderer/letterbox_pass.cc`, `engine/ui/letterbox.py`, `docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md` | The `StartCutscene..EndCutscene` bars are **GL, drawn below the whole UI layer** — into FBO 0 after the post chain resolves and **before `ui_cef::composite()`**. That ordering IS the feature: every CEF element lands on top of the bars by construction, with no z-index to forget. **Do NOT re-add them as DOM** — they were, at `z-index: 5`, and because every HUD root here has *no* z-index the bars painted *over* the UI and hid E1M1's XO menu mid-tutorial. `covered` is BC's `fCoveredArea`: the **TOTAL** fraction across both bars (0.125 ⇒ 6.25% each), which the native pass halves. Fed `_player_dt`, so the bars freeze under pause instead of sliding on wall-clock. Reset on mission swap; skipped in hologram-only mode. |
| Shield face + impact splash | `engine/appc/combat.py:_shield_face_from_hit_point` (**its docstring is the authority**), `native/src/renderer/include/renderer/shield_state.h`, `docs/instrumented_experiments/2026-08-16-shield-facing-and-beam-falsifiers.md` | **Which shield face a hit belongs to is a HULL-BOX question, not a 45° cone.** BC hulls are 4–8:1, so a raw body-frame compare labels only ~6% of a Galaxy's dorsal surface TOP. The delta is measured from the hull **AABB centre** and normalised by the **half-extents**; ships with no cached box fall back to the raw-axis rule. Verified against the clean-room reference: the chooser is `ShipClass::TestHit` (not ShieldClass, which holds no geometry at all), and our axis→index table and tie order match the binary. Still open: absorption is a strict cascade where BC uses a **pass-through ramp**, and beams should apply damage in **0.5 s pulses**. The renderer splash is procedural 3D on the **bubble**, not the hull — `shield_state.h` documents every constant and the live bug behind it. |
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
