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
| Gap analysis | `docs/gap_analysis.md` | 8 gaps, 21 open questions, solution paths |
| Open questions | `docs/original_game_reference/open_questions.md` | 4 instrumentation questions — Q4 closed |
| Live game | `game/` | BC installation (gitignored) — needed for instrumentation |
| Space dust pass | `native/src/renderer/dust_pass.cc`, `docs/superpowers/specs/2026-05-11-space-dust-particles-design.md` | Camera-anchored dust particles with motion smear; toggle via `_h.dust_set_enabled()` |
| BCS save format | `docs/original_game_reference/engine/bcs-save-format.md`, `tools/bcs_inspect.py` | Real binary save format; preamble + object table + TGL + pickle-memo decoded; 93.6% object-state region remains as parking-lot RE work |
| AI surface & gaps | `docs/original_game_reference/engine/aieditor-ai-surface-and-gaps.md` | What the original `AIEditor` tool reveals about BC's AI: it's a code-generator emitting `CreateAI(pShip)` Python that Dauntless's `engine/appc/ai.py`+`ai_driver.py` already run. Maps the 7 AI container types, 8 named preprocessors, and 34 Condition classes against Dauntless's implementation. Confirmed gaps: `RandomAI` never dispatched; `GetCloakingSubsystem` stubbed `None` (cloak doctrines off); partial collision-avoidance; ~10 Condition Appc-query rows to verify (silent-degradation risk). |
| DamageTool & hull-damage gaps | `docs/original_game_reference/engine/damagetool-and-hull-damage-gaps.md` | RTTI-extracted internals of BC's `DamageTool.exe` + 4 prioritized gaps vs our voxel-carve system. BC damage = summed **metaball field** (`MetaVolume(pos, influRad, strength)`; authored tiers 0.4/300 + 1.0/600; constant `strength≈750·influRad`) clipped by a `BinaryVoxel` hull mask — our `HullCarve`+`SourceVolumeCache` is the same shape. **Gap 1 ✅ DONE:** `DamageableObject.AddObjectDamageVolume`/`AddDamage`/`DamageRefresh`/`RemoveVisibleDamage`/`SetVisibleDamage*Modifier` now route authored + runtime visible damage into `host.hull_carve_add` via `engine/appc/visible_damage.py` (deferred queue, no native change). NOTE the missing methods never crashed — `TGObject.__getattr__` `_Stub` made them silent no-ops (wrecks rendered intact). `RemoveVisibleDamage` clears pending only; clearing emitted carves needs a native `HullCarveField::clear()` (still absent). Verify via `--developer` → mission picker → **Developer → Damage Preview** (`engine/dev_missions/damage_preview.py`). **Gap 2 ✅ DONE:** BC additive metaball field — `HullCarve` gains `strength`+`influ_radius`; `HullCarveField::add` accumulates strength; visible radius = `max(floor, fraction(strength)·ship_radius)`, 0 below the iso (150) so sub-iso accumulation is invisible/silent; `hit_feedback` accumulates strength across the throttle window (don't drop ticks) and deposits `absorbed_hull×STRENGTH_PER_HULL` (1.0). `hull_carve_add(influ, strength, time, floor=0, strength_size_ref=0)`. Tuning: `STRENGTH_PER_HULL`/influ in `hull_carve.py` (no rebuild); iso/curve are C++ `kHullCarve*` consts (rebuild). **Gap 3:** carve radii drift from BC's 0.4/1.0 GU (subsumed by the fraction-of-radius curve). **Gap 4 ✅ DONE (SDK-faithful):** carve sizes are **absolute** GU (a weapon makes the same hole on any hull — impacts don't shrink on smaller targets); the only per-ship scale is BC's authored `SetVisibleDamage{Radius,Strength}Modifier` (`radius_modifier` arg → carve radius, strength mod → deposit), set only on 10 fixed structures (DamageRadMod 5–15 + reciprocal DamageStrMod). A `GetRadius()`-proportional curve was tried first and reverted (physically wrong + double-counted size on the stations). Also: `breach_pass.cc` mis-sources its cavity texture from the `Damage1-4.tga` HUD glyphs, not `Textures/Effects/Damage.tga`. |
| Developer flag | `engine/dev_mode.py`, `native/src/host/developer_mode.{h,cc}`, `docs/superpowers/specs/2026-06-02-developer-flag-design.md` | Runtime `--developer` flag gating dev-only keybindings, pause-menu sections, renderer overlays, and CEF panels. Parse once in C++ (`host_main.cc`), read via `dauntless::is_developer_mode()` / `engine.dev_mode.is_enabled()` / `window.__DAUNTLESS_DEV__`. Exposed to Python as `_dauntless_host.developer_mode`. Register dev keybindings with `dev_mode.register_dev_keybinding(...)`; register dev pause-menu rows with `dev_mode.register_dev_pause_menu_entry(label, handler)`; wrap dev-only behaviour with `@dev_mode.dev_only`. CSS-hide CEF elements with class `dev-only`. |
| Dev mission loader | `engine/dev_mission_picker.py`, `native/assets/ui-cef/{js/mission_picker.js,css/hello.css,hello.html}`, `docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md` | Developer-only "Load Mission…" pause-menu row that opens a CEF-rendered centred-modal picker listing every discoverable SDK mission (family → episode → mission). Picker is a `Panel` subclass pumped by `PanelRegistry`; one click on a mission row calls `controller.swap_mission(module)` + `pause.close()`. Lazy SDK walk on first open. ESC and Cancel route back to the pause menu; pause-menu hides while picker is open. |
| Developer Options menu | `engine/ui/developer_options_panel.py`, `engine/dev_combat_cheats.py`, `native/assets/ui-cef/js/developer_options.js`, `docs/superpowers/specs/2026-06-08-developer-options-menu-design.md` | Developer-only "Developer Options…" pause-menu modal styled like the configuration panel (reuses its `cp-*` CSS + shared backdrop). Combat tab toggles God Mode, 2× player weapon strength, and Disable NPC Shields — all hook `combat.apply_hit` via the dev-mode-gated flags in `dev_combat_cheats` (`*_active()` getters AND with `dev_mode.is_enabled()`, so production combat is byte-identical). God mode skips damage mutation but keeps hit feedback (`persist_decal=False` suppresses only the permanent scar). Off by default, not persisted across launches. |
| Ship Property Viewer | `engine/ui/ship_property_viewer.py`, `engine/ui/ship_property_viewer_panel.py`, `native/src/renderer/{hologram_pass,subsystem_pin_pass}.cc`, `native/assets/ui-cef/js/ship_property_viewer.js`, `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md` | Developer-only "Ship Property Viewer" pause-menu modal: the player ship rendered as a translucent Fresnel hologram (`opacity = 0.70 − 0.50·\|N·V\|`, facing→0.20 grazing→0.70, blue back-face glow; `hologram_pass` re-draws the real ship instance with the solid hull hidden via `set_visible(iid, False)`) with camera-facing billboard pins per subsystem (white disc + black class Damage glyph, `subsystem_pin_pass`, world-scaled `kPinWorldSize`, drawn depth-test-off so none hide behind the hull). Pins sit at `subsystem_world_position` mounts (ship world-loc + R·local, **no scale**). Orbit camera + projection + pin-picking are pure Python in `ship_property_viewer.py` (the GL passes get the same camera via `set_camera`, so picks match by construction). Click a pin → property popover. Everything is absolute world space; the camera orbits the subsystem centroid (no re-centring). Opens from the dev pause menu (sim already frozen via `frame_dt=0`); off by default; production render path byte-identical (panel never constructed without `--developer`). The two GL passes take `(camera, viewport_rect)` for a future render-to-texture windowed mode. |
| **Stub heatmap — CHECK BEFORE CLAIMING A NO-OP** | `docs/stub_heatmap.md`, `tools/stub_heatmap.py`, `engine/core/stub_telemetry.py` | **Trigger: any time you suspect — or are about to assert — that an SDK call is (or isn't) a silent no-op, READ `docs/stub_heatmap.md` FIRST. Never assert stub behaviour from reasoning alone.** It ranks unimplemented attrs by live hit count, plus **Boolean-test call sites (truthiness risk)** and **Numeric-coercion call sites (`int()==0` risk)** tables. Since 2026-07-12 it covers **both** stub paths: the *instance* path (`TGObject.__getattr__` → `_Stub`) **and** the *App-module* path (`App.<name>` → `_NamedStub`), including the silent-collapse operators — so an undefined **constant** (`App.<CLASS>.<CONST>`) now shows up instead of quietly degrading to truthy / `int()==0`. That class had already caused ≥4 real bugs (keyboard `WC_*`; `TGUIObject.ALIGN_*` collapsing every `AlignTo` to `ALIGN_UL`; `EngRepairPane.REPAIR_AREA`; `STTopLevelMenu_GetOpenMenu` making BC's cutscene menu-drop a no-op) — **if you see a name in the coercion/truthiness tables, treat it as a live bug, not noise.** Note the stubs still *behave* the same (truthy / 0); the telemetry only observes. Whole SDK **modules** can also be silently stubbed in the twin stub lists (`tools/mission_harness.py` AND `tests/conftest.py` — fix BOTH), and **never unstub a whole module to reach one function** — its body needs engine surface we lack; reimplement that one behaviour at the equivalent engine hook. |
| Game-unit conversion | `engine/units.py` | BC stores **everything** spatial (positions, velocities, distances, radii) in a single internal unit, "game units" (GU). **1 GU = 175 m = 0.175 km, 1 GU/s = 630 km/h.** Derived from Galaxy `SetMaxSpeed(6.3)` → 3969 kph in BC's helm tooltip (`sdk/.../BridgeHandlers.py:1389` via `Appc.UtopiaModule_ConvertGameUnitsToKilometers`). Physics, renderer, and camera stay in GU end-to-end; **only convert at display boundaries** via `GU_TO_KM` / `GUPS_TO_KPH`. Never call any variable `*_m` / `*_mps` — speed/range inside the engine is **always** `*_gu` / `*_gups`. |

## Open questions status

### Instrumentation questions (require running game)

| Q | Topic | Status |
|---|---|---|
| Q1 | Tick rate — fixed or variable? what Hz? | ✅ **60 Hz fixed** (16.67 ms/tick) |
| Q2 | Subsystem update ordering within a tick | ✅ **AI/Python first** (~2% into tick), then physics, then render |
| Q3 | Time scale interaction with physics/AI/timers | ✅ **Game time scales** (0.204 measured); real time does not |
| Q4 | TimeSliceProcess priority semantics | ✅ Closed — static analysis sufficient |

### Gap analysis OQs (21 total)

- Closed by static analysis: OQ-1.1, 1.2, 1.3, 2.1, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 6.2, 7.4, 8.1, 8.2 (15)
- Closed by instrumentation: OQ-7.1, OQ-7.2, OQ-7.3 (3)
- Partially answered: OQ-2.2 (teleport confirmed; warp-exit velocity Phase 2), OQ-2.3 (arc/modes known; force law tuned by feel)
- Still open: OQ-3.1–3.3, OQ-6.1, OQ-8.3, OQ-8.4 — all Phase 2, all file-inspection or grep work
- **No remaining OQs require running the live game**

**Phase 1 blockers: all resolved. Ready to begin Phase 1 implementation.**

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

It compares every failure against `tests/known_failures.txt` (the only entries
are the 7 headless-GL scorch/heat-glow `FrameTest`s) and **exits non-zero,
naming any failure not in that list** — that failure is a regression this tree
introduced, not "pre-existing". When a baselined test starts passing the gate
tells you to delete its line. **Never call a failure "pre-existing" by eyeball;
run the gate.** A new required arg / changed output shape means you update that
thing's tests in the same change. Order-flaky? Run it in isolation to separate
cross-test pollution (reset leaked globals in `tests/conftest.py`'s autouse
`_reset_leakable_engine_globals`) from a real break.

## Executing plans

When asked to execute a plan in `docs/plans/`, dispatch one `tdd-engineer`
subagent per task in order, run the full suite and commit between tasks, and
stop on any BLOCKED.
