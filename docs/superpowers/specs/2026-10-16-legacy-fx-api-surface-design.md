# Legacy FX API surface — design

**Date:** 2026-10-16
**Status:** design approved section by section in conversation; awaiting review of this written spec
**Branch:** `feat/nanofx-surface` (worktree `.claude/worktrees/nanofx-surface`)
**Immediate follow-up:** apply the sprite library to Dauntless's own stock effects (§11)

## 1. Goal

Many Bridge Commander mods were written against **NanoFX 2.0**, a 2003
effects mod. They call its Python API, or point at its texture paths. Those
mods should work in Dauntless **without NanoFX installed**.

This project supports NanoFX's **API surface**, not NanoFX itself. NanoFX's
own effects (its replacement hit, death, warp and camera sequences) are not
run. A real NanoFX install is **blocked as incompatible**.

Success means:

- A mod that imports `Custom.NanoFXv2.NanoFX_Lib` and calls it loads and
  behaves sensibly, using Dauntless's own systems.
- Dropping the real NanoFX into `mods/` breaks nothing. It is reported as
  blocked, and tactical sounds and Quick Battle still work.
- Foundation-era bundled infrastructure files are refused with a reason,
  rather than silently replacing engine-owned modules.

## 2. Non-goals

- Running NanoFX's effect modules (`ExplosionFX`, `WarpFX`, `CameraFX`,
  `BridgeFX`, `SpecialFX`), its config panel, or its warp AI.
- Foundation `OverrideDef`, `TriggerDef` and working mutators. These remain
  non-goals of `2026-09-09-foundation-compatibility-design.md`.
- Mod-added Quick Battle systems and **custom bridges**. Custom bridges are a
  separate project.
- Mods replacing engine icon groups (`DamageTextures`, `EffectTextures`,
  `WarpFlashTextures`), and a general policy for mods overriding engine-read
  assets such as `data/Textures/Effects/Damage.tga`.
- Applying the new sprites to Dauntless's own production effects. Production
  VFX stay byte-identical (§11).
- Tinting our warp glow or launch flashes from ShipDef `Override*FXColor` or
  torpedo `GetFlashColor()`. The getters work; consuming them is a follow-up.

## 3. Background — what NanoFX is (evidence)

Source examined: `bc_mod_tools/extracted/NanoFX_2.0 BETA/` (442 files, 51 MB).
It was read for interface facts only.

- **Mechanism.** `Custom/Autoload/LoadNanoFX.py` creates a Foundation
  `MutatorDef` and registers about 90 `OverrideDef`s. These cover
  `Effects.*Hit`, `Effects.ObjectExploding`, `WarpSequence.SetupSequence`,
  `CameraModes.*`, `Bridge.bridgeeffects.DoHullDamage`, `AI.PlainAI.Warp`,
  `AI.PlainAI.FollowThroughWarp`, and the `Initialize` of about 75 stock
  `Systems.*_S` scripts (sun-shell "atmospheres").
- **Bundled Foundation.** The installer ships Foundation's own
  `Foundation.py`, `FoundationMenu.py`, `FoundationTriggers.py`,
  `Fixes20030217.py`, `LoadTacticalSounds.py`, `QuickBattle/QuickBattle.py`,
  `MainMenu/mainmenu.py`, the `Custom/Autoload/000-*` add-ons, and ATP
  (`Custom/AdvancedTechnologies`).
- **Most overrides could never apply here.** The engine replaces those SDK
  functions:
  - hits: `hit_feedback.py`
  - death: `death_cascade.py`
  - cameras: `camera_modes.py`
  - warp: `warp.py` / `warp_button.py`
- **Its system overrides would be harmful.** Each atmosphere is three
  `Sun_Create` shells. Each renders as a full star, the shells do not follow
  the planet, and a shell could be picked as the system's star.
- **Today, installing NanoFX would break things:**
  - Its `LoadTacticalSounds.py` evaluates `Foundation.MutatorDef.StockSounds`
    at import. Our Foundation raises `AttributeError` there, so tactical
    sounds fail to load.
  - Its `QuickBattle.py` would replace stock under our Quick Battle hooks.
  - `g_kLODModelManager.SetGlowMapsEnabled` raises `AttributeError`.
- **What dependent mods use.**
  - In the local corpus (DJ Galaxy Pack, LC Intrepid, DCMPv2, CGSovereign,
    LateTNG, VoyagerCubeHP), the only dependency is the texture path
    `scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga` on
    `BlinkingLightProperty`.
  - NanoFX's public functions (§6), its texture paths, and the ShipDef colour
    hooks are what a dependent mod can reach.
- **Licence.** NanoFX has no licence file. The bundled `Foundation.py` reads
  *"all rights reserved"*, and the system scripts are Totally Games
  *"Confidential and Proprietary"*. Nothing from NanoFX is copied into this
  tree, whether code or assets. Its legacy texture *paths* appear only as
  alias keys (data).

## 4. Decisions

| # | Decision |
|---|---|
| D1 | Support the surface, not NanoFX. A real install is blocked as incompatible, and ours always wins. |
| D2 | NanoFX block granularity: a standalone NanoFX mod is blocked whole. NanoFX bundled inside a bigger pack has only its own files skipped. |
| D3 | Foundation infrastructure files are refused in any mod (§5). |
| D4 | `MutatorDef` is inert and always on; `OverrideDef` / `TriggerDef` stay out. |
| D5 | `DisableGlowAlphaMaps` is real. The global glow toggle is real. Specular flags are stored only. |
| D6 | `Custom.NanoFXv2` is provided by Dauntless through a claimed-namespace finder rule, with neutral code location `engine/compat/fx_api/`. |
| D7 | Effect textures go through a **sprite library**. A legacy path is a *name for a kind of effect*, resolved to Dauntless-owned art or a stock BC fallback. |
| D8 | Sprite art is **PNG** for output. Sources are AI-generated (Gemini) sheets, produced from briefs written against each effect's *meaning*. |
| D9 | Black-background sources are supported. The prep tool derives alpha (four background modes, §7.3). |
| D10 | `shock_ring` is a `native` entry routed to Dauntless's procedural shockwave, which gains a tint. `shock_sphere` / `nova_flare` stay sprites. |
| D11 | Debris playback is a looping tumble: rows are variants, columns cycle at `fps` from a random start. Ship the 4 good rows of the current pair. |
| D12 | Sprite sources and outputs are committed under `native/assets/sprites/`, with a drift test. Nothing we name contains "nanofx". |
| D13 | Live testing uses a developer-only fixture mod in the gitignored `mods/`. It is not committed. |

## 5. Mod policy — blocking NanoFX, refusing Foundation infrastructure

**Module.** `engine/mod_policy.py` holds pure functions with no I/O.
`engine/mods.build_index` consults it **per mod, before that mod's files
enter the index**.

Why at that point:

- A refused file never reaches the index, so every consumer skips it with no
  second filter:
  - the asset overlay
  - both `_SDKFinder`s (`tools/mission_harness.py`, `tests/conftest.py`)
  - the C++ override map
- Filtering after the build would be wrong. The index is "later mod wins", so
  removing a refused winner would also lose the earlier mod's file it had
  displaced.
- `detect_frameworks` runs on the filtered index. A refused
  `FoundationTriggers.py` therefore does not count as the mod "providing"
  that framework.

`build_index` already lists a mod's files before inserting them
(`_walk_files`). The policy classifies that list once per mod:

```python
decide(mod_files: list[ModFileInfo]) -> PolicyDecision
# PolicyDecision.blocked: Optional[str]          whole-mod reason, or None
# PolicyDecision.refused: dict[folded_rel, str]  per-file reason
```

`ModFileInfo` carries the folded relative path, plus the top-level import
names of `.py` files. That is the existing `_imported_names` parse, reused
rather than re-read.

### 5.1 Rule A — NanoFX

**Marker files** (case-folded):

- `custom/nanofxv2/nanofx_lib.py`
- `custom/autoload/loadnanofx.py`

**NanoFX's own files:**

- `custom/nanofxv2/**`
- `custom/autoload/loadnanofx.py`

**NanoFX's distribution set** is NanoFX's own files plus:

- Foundation's bundled files (§5.2 list)
- `custom/autoload/000-*.py`
- `custom/advancedtechnologies/**`
- `data/movies/**`
- `data/textures/effects/damage.tga`

**Decision:**

- A mod has a marker, **and** every file is in the distribution set → the mod
  is blocked whole:
  `"incompatible: NanoFX (Dauntless provides its API)"`.
- A mod has a marker plus other content → only NanoFX's own files are refused:
  `"bundled NanoFX skipped (Dauntless provides its API)"`. Everything else
  loads, including ATP, which other mods use in its own right.

### 5.2 Rule B — Foundation infrastructure (any mod)

**Always refused:**

- `foundation.py` (already shadowed by the root shim; now also reported)
- `foundationmenu.py`
- `foundationtriggers.py`
- `fixes2003*.py`
- `custom/autoload/000-fixes*.py`
- `custom/autoload/000-utilities-*.py`

**Refused only when the file imports `Foundation` or `FoundationMenu`:**

- `loadtacticalsounds.py`
- `quickbattle/quickbattle.py`
- `mainmenu/mainmenu.py`

A pre-Foundation mod that edits `LoadTacticalSounds.py` directly to add its
sounds keeps working.

Reason strings name the rule, for example
`"Foundation infrastructure (Dauntless provides Foundation)"`.

### 5.3 Reporting

- `ModStatus` gains `blocked: Optional[str]` and `refused: list[(rel, reason)]`.
- `describe()` prints the whole-mod block in place of the file count. It
  prints the refused files grouped by reason.
- The Mods screen (`engine/ui/mods_screen.py`, home mode) lists blocked mods
  with their reason, instead of omitting them.

## 6. Missing names (Foundation and Appc)

### 6.1 `Foundation.MutatorDef` (inert, always on)

- `MutatorDef(name)` with attribute `name`.
- `IsEnabled()` always returns `1`.
- `Enable`, `Disable`, `Activate` and `Deactivate` are no-ops and log once.
- Class attributes, the four standard instances Foundation defines: `Stock`,
  `StockSounds`, `StockShips`, `QuickBattle`.
- Mods may attach attributes (`Foundation.MutatorDef.NanoFX = mode`,
  `mode.bBase = 1`).
- `{'modes': [...]}` arguments continue to be accepted and ignored by every
  `*Def`.
- `docs/engine/foundation-api-surface.md` gains these rows.
- **No Foundation code is copied.** The names come from call sites and from
  the interface facts of Foundation's own file.

### 6.2 `DamageableObject.DisableGlowAlphaMaps()` — real

This is stock surface (`App.py:5353`). The stock campaign calls it: E4M5 on
four Kessok ships (`stub_heatmap.md` open row #137, 4 hits).

- **What it does.** Sets a per-object flag.
- **Hull glow.** The host loop drives the existing per-instance
  `emissive_scale` to `0.0` for a flagged ship (`host_loop.py:9445` path; field
  `instance.h:90`). That is the same path that darkens a destroyed hulk.
- **Running lights go out too.** `running_lights.level_for` multiplies by
  0 for a flagged ship, next to its power-plant factor.
- **No `EnableGlowAlphaMaps`.** Stock BC has no such method, and none is added.

### 6.3 `g_kLODModelManager` glow and specular flags — real

`SetGlowMapsEnabled`, `AreGlowMapsEnabled`, `SetSpecularMapsEnabled` and
`AreSpecularMapsEnabled`. They are added to `LODModelManager`
(`engine/appc/lod_models.py:93`), which today raises.

- **Glow.** A global flag, default on. While off, every ship's emissive is 0
  and every running-light level is 0.
- **Re-enabling clears every per-object `DisableGlowAlphaMaps` flag.**
  - ⚠️ **ASSUMPTION, not recovered behaviour.** NanoFX's `TurnOnLights`
    toggles glow off and on in one call to restore a ship's lights. That only
    works if re-enabling resets per-object disables.
  - Verify against the clean-room reference when it is reachable
    (`DamageableObject_DisableGlowAlphaMaps` and
    `LODModelManager_SetGlowMapsEnabled`).
- **Specular.** Stored, with truthful getters, default on. The renderer is
  unaffected, since ships carry no specular maps.

## 7. Sprite library

### 7.1 Concept

A legacy texture path given to `CreateTarget` is treated as a **name for a
kind of effect**. For example,
`scripts/Custom/NanoFXv2/ExplosionFX/Gfx/Explosions/Exp_Nano3.tga` means
`fireball`. A library entry resolves that name to one of:

- Dauntless-owned art,
- a stock BC sprite,
- a native effect, or
- nothing.

The library is not NanoFX-specific. Dauntless effects and Dauntless mods can
later request ids directly; the NanoFX aliases are its first client.

### 7.2 Library contents

| id | kind | Meaning | Aliased NanoFX paths | Source art | Stock fallback |
|---|---|---|---|---|---|
| `fireball` | sprite | Round fireball bloom → fade | `ExplosionFX/Gfx/Explosions/Exp_Nano1..12`, `Exp_Fire` | `src/fireball/black.jpeg` (8×4) | `data/Textures/Effects/ExplosionA.tga` (8×8) |
| `fireball_hot` | sprite | White-hot core burst | `Exp_ExpDeb` | — | `data/Textures/Effects/ExplosionB.tga` |
| `fire_jet` | sprite | One-sided venting flame | `Exp_Flare`, `Exp_Starflare` | `src/fire_jet/black.jpeg` (8×4) | `ExplosionA.tga` |
| `glint_burst` | sprite | Animated star flash | `ExpFlash/ExpFlash1`, `SpecialFX/Gfx/Weapon/WeaponFlash`, `WarpFX/Gfx/NacelleFlash/NacelleFlash_Core`, `NacelleFlash_Outter` | `src/glint_burst/black.jpeg` (4×4) | `data/explodeSharp.tga` |
| `glint` | sprite | Static star light | `SpecialFX/Gfx/Blinker/Blinker` | — | `data/round.tga` |
| `spark` | sprite | Small bright point | `ExplosionFX/Gfx/Particles/Sparks` | — | `data/smooth.tga` |
| `plasma_puff` | sprite | Vent puff (caller-tinted) | `SpecialFX/Gfx/Plasma/Plasma` | — | `data/Textures/Effects/SunFlaresWhite.tga` (8×8) |
| `debris_chunk` | sprite | Tumbling hull fragment | `ExplosionFX/Gfx/Debris/*` | `src/debris_chunk/{black,green}.jpeg` (6×6; rows 1, 2, 4, 6 kept) | `data/rough.tga` |
| `shock_ring` | **native** → shockwave | Expanding ring | `ExplosionFX/Gfx/NovaRing/*` | — | — |
| `shock_sphere` | sprite | Burst → expanding shell | `ExplosionFX/Gfx/NovaSphere/*` | `src/shock_sphere/black.jpeg` (8×4) | `data/explodeSharp.tga` |
| `nova_flare` | **none** | (covered by the shockwave's core flash) | `ExplosionFX/Gfx/NovaFlash/*` | — | — |
| `star_streak` | sprite | Warp streak | `WarpFX/Gfx/StarStreaks_Nano` | — | `data/Textures/starstreak.tga` |
| `space_dust` | sprite | Dust mote | `WarpFX/Gfx/SpaceDust_Nano` | — | `data/Textures/spacedust.tga` |
| `warp_flash` | sprite | Warp flash | `WarpFX/Gfx/WarpFlash/*` | — | `data/Textures/warpflash3.tga` |
| `none` | none | Deliberately invisible | `SpecialFX/Gfx/Blinker/Blank` | — | — |

All alias paths above sit under `scripts/Custom/NanoFXv2/` and end in `.tga`.

Notes on the table:

- `nova_flare → none` is to be **confirmed by eye** against the shockwave's own
  core flash.
- Not aliased:
  - the NanoFX atmosphere textures (`CreateAtmosphereFX` maps to the
    atmosphere catalogue, §8.3);
  - `Damage_Nano*` (icon-group override only, out of scope);
  - the BridgeFX sheets (used only by NanoFX's own bridge module).

**Source art.** The source art was delivered as `~/Downloads/sprites/*.jpeg`.
The implementation copies it into `native/assets/sprites/src/<id>/`.

### 7.3 Assets and prep tool

**Layout** (`native/assets/sprites/`, all committed):

```
native/assets/sprites/
  manifest.json          # one entry per id (prep + runtime fields)
  legacy_aliases.json    # folded legacy path or folder prefix -> id
  src/<id>/black.jpeg    # raw generated sheet(s)
  src/<id>/green.jpeg    #   (green_matte only)
  <id>.png               # processed output the engine loads
```

**Manifest entry fields.**

`prep`, read only by the tool:

- `grid` (source cols × rows; fractional cell sizes allowed)
- `keep_rows` / `keep_frames`
- `background`: `black` | `black_solid` | `green_matte` | `alpha`
- `black_cut`
- `edge_fade` (px), **or** `origin_ramp` (edge + width) for directional sprites
- `cell` (output cell size, a power of two)

Runtime fields:

- `kind`: `sprite` | `native` | `none`
- `grid`: output cols × rows
- `playback`: §7.4
- `fps`
- `scale`: size multiplier calibrating the art's fill against the original
  (e.g. `glint_burst` ≈ 0.6)
- `pivot`: anchor within the cell, default centre
- `orient`: `camera` | `emit_dir`, with the art's authored axis (`fire_jet`
  points `+x`)
- `brightness`
- `fallback`: stock path + grid
- `native`: effect name + parameter mapping, when `kind` is `native`

Stock sheets `ExplosionA` / `ExplosionB` also get entries. Their grid and
brightness move here from the hard-coded `_KNOWN_SHEET_TEXTURES` /
`_TEXTURE_BRIGHTNESS` in `engine/appc/particles.py`.

**Background modes:**

| mode | input | alpha | RGB | use |
|---|---|---|---|---|
| `black` | black sheet | `max(r,g,b)` after `black_cut` | brightness restored: `rgb / a` | light-only effects (fire, flashes, shells) |
| `black_solid` | black sheet | soft threshold on brightness, morphological close, 1 px blur | as painted | solid objects when no green version exists |
| `green_matte` | black + green sheets of the same composition | `1 − clamp((g − max(r,b) − lo)/(hi − lo))`, shrunk 1 px, light blur | taken from the **black** sheet | solid objects; no spill, true colours |
| `alpha` | real transparency | as given | as given | anything that arrives transparent |

**`green_matte` silhouette check.** The green-keyed object must lie inside the
black sheet's object (brightness > 16), dilated by 2 px. It must do so for
≥ 99% of its pixels **per cell**. Otherwise the tool refuses the pair and names
the failing cells. Reference measurement for the delivered debris pair:

- IoU 0.890;
- the green object lies wholly within the black object at 1 px;
- the black-only remainder is the glow halos.

**`tools/sprites/prep.py`:**

- **Pipeline:** slice → per-cell crop and resample to `cell` → background mode
  → black cut → edge fade / origin ramp → row and frame selection → pack PNG.
- **Without `--write`** it previews only (writes to a temp dir and reports).
- **Determinism:** fixed algorithms and Pillow (already a project dependency).

**Drift test** (`tests/tools/test_sprite_drift.py`):

- Regenerates every sprite.
- Compares **decoded pixels** with the committed PNG, within a small
  tolerance, so a Pillow upgrade does not fail it.
- Never hand-edit an output PNG.

**Per-sprite prep notes, from measurement of the delivered sheets:**

| id | Issues the prep must fix |
|---|---|
| `fireball` | Smoke and sparks cross cell edges in frames 11–25 → `edge_fade`. Non-square 344×384 cells → resample. |
| `glint_burst` | Rays touch edges at ≤ 18/255 → `edge_fade`. `scale` ≈ 0.6. |
| `shock_sphere` | Rim reaches edges in frames 12–17 → `edge_fade`. Frame 1 warm haze (edge median 8) → `black_cut` ≥ 10 for that sheet. |
| `fire_jet` | Origin on the left cell edge plus a pale blue root band → `origin_ramp` (left, ~10% width). `pivot` left-centre. `orient: emit_dir`, axis `+x`. |
| `debris_chunk` | `green_matte`. `keep_rows` 1, 2, 4, 6 (row 3 has an odd frame; row 5 is static). The 1 px shrink removes the generator's stippled outline. |

### 7.4 Playback modes (particle pass)

| mode | rows | columns | use |
|---|---|---|---|
| `life_columns` | random variant per particle | stepped over the particle's life | **today's behaviour**, stock `ExplosionA`/`B` (`particle_pass.cc:276`) |
| `life_sequence` | — | the whole sheet plays row-major over life | `fireball`, `fire_jet`, `glint_burst`, `shock_sphere` |
| `loop` | random variant per particle | cycle at `fps` from a random start column | `debris_chunk` |

The particle pass already provides per-particle roll and tumble. Debris keeps
them; `orient: emit_dir` ignores roll (streak branch).

### 7.5 Runtime integration

**`engine/sprites.py`:**

- Loads the manifest and aliases **lazily, at first use**, never at import
  (paths rule).
- `resolve(path)` folds the path, then looks for an exact alias, then the
  longest folder prefix. It returns one of:
  - a `SpriteRef` (absolute PNG path, or the stock fallback when the PNG is
    absent, plus runtime fields);
  - `NATIVE(name, mapping)`;
  - `NONE`;
  - pass-through for unaliased paths.

**`particles.AnimTSParticleController.CreateTarget`** calls `resolve` and
applies, as the case requires:

- file, grid, brightness and playback;
- `scale` (multiplying size keys at descriptor time, as brightness already
  does);
- `pivot` and `orient`.

`resolve_asset_path` passes absolute paths through unchanged
(`asset_path.cc:105`).

**`App.g_kTextureAnimManager`** becomes real:

- `AddContainer(path).AddTextureTrack(n).SetFrame(i, l, t, r, b)` records a
  texture's frames.
- When the rects form a regular grid, the grid is stored for that path, and
  `CreateTarget` uses it if the library has no entry.
- An irregular track is logged once and ignored.

**`kind: native` (shockwave).**

- At `EffectAction` **play** time, instead of registering an emitter, the
  action calls `shockwaves.spawn(center_world, max_radius_gu, lifetime, pSet)`
  (`engine/appc/shockwaves.py:27`), plus a tint.
- Mapping:
  - `center_world`: emit position resolved through the emit-from object;
  - `max_radius_gu`: size keys × a manifest factor;
  - `lifetime`: the emit life (`iTiming/15` for NanoFX callers);
  - tint: the mid colour key.
- `ShockwaveDescriptor` (`frame.h:179`) gains `glm::vec3 tint`, defaulting to
  today's colour so `warp_core_breach` is unchanged. It is plumbed through
  `shockwaves.render_data` → `host_io.set_shockwaves` → `ShockwavePass`.

**`kind: none`.** The controller is marked inert and never emits.

**C++ particle pass:**

- `texture_for` switches `decode_tga` → `decode_image` (PNG or TGA,
  `texture.h:72`).
- Descriptor fields: `playback`, `fps`, `pivot` (vec2) and `orient`.
- `orient: emit_dir` reuses the streak branch (`hit_vfx.vert:18`). Its axis is
  the world emit direction, and its length is the particle size × the art's
  aspect.

## 8. `Custom.NanoFXv2` package

### 8.1 Location and resolution

- **Code** lives in `engine/compat/fx_api/`. Module files carry their import
  names (`NanoFX_Lib.py`, `NanoFX_ScriptActions.py`, `NanoFX_Config.py`,
  `__init__.py`, plus effect sub-packages). Mods import exactly these names.
- **Claimed-namespace rule.** A small shared module
  (`engine/compat/claimed.py`) maps the case-folded dotted prefix
  `custom.nanofxv2` → that directory.
  - Both `_SDKFinder`s consult it **before** the mod overlay and after the
    project-root shims. Ours therefore always wins.
  - `Custom` itself, `Custom.Ships`, `Custom.Autoload` and the rest still
    resolve from mods and the SDK.
  - A root-level `Custom/__init__.py` must **not** be used; it would shadow
    every mod's `Custom.*`.
- **Loading.** These are modern Python modules, loaded with a normal source
  loader (not the SDK loader's Python 1.5 transforms). They reach the engine
  through `App`.
- **No copying.** Each function is rebuilt from NanoFX's documented behaviour
  and signature.

### 8.2 `NanoFX_Lib`

| function | behaviour |
|---|---|
| `CreateFlickerSeq(pShip, fTotalTime, fFlickerSpeed=0.2, sStatus="On")` | `TGSequence` toggling the ship's glow flag (§6.2) every `fFlickerSpeed` s with ±0.1 s jitter, ending on or off per `sStatus`. At most 2 concurrent (`CONST_MAXFLICKERS`); beyond that, an empty sequence. |
| `CreateRotationSeq(pShip, fRotation=None, fSpeed=None)` | Sequence adding a random angular velocity and an optional speed (`SetAngularVelocity` / `SetVelocity`). |
| `CreateSpecialFXSeq(pShip, pEvent, sFXType, bPlay=0)` | Returns `None` for every type (NanoFX's own plasma vent returns `None` on most calls). With `bPlay=1`, plays nothing. |
| `CreateAtmosphereFX(pPlanet, sNifPath=..., sTexturePath="Class-M")` | Registers a mod-requested atmosphere (§8.3). Creates no objects. |
| `GetSpeciesName(pShip)` | ShipDef race long name via `engine.ship_catalog`, else `"Default"`. |
| `GetOverrideColor(pShip, sEffectType)` | `ShipDef.Override<Type>Color(None)` if the ShipDef carries it (unknown attributes are kept, `shipdef.py:119`), else `None`. |
| `GetRaceTextureColor(sRace)` | Race RGB table (data), with a default. |
| globals | `g_LightsOff`, `g_FlickerControl`, `CONST_MAXFLICKERS`, `ControlFlickers(pAction, n)` |

### 8.3 Mod-requested atmospheres

- `engine/planets/atmosphere.py` gains a runtime layer for mod-requested
  entries, keyed `"<set>/<planet name>"`.
- `resolve_key` order:
  1. catalogue `"<set>/<name>"` override;
  2. catalogue NIF stem;
  3. mod-requested entry.

  The catalogue always wins, including an explicit `atmosphere: false`. In
  practice mod requests fill only custom planet NIFs.
- The entry comes from a planet-class preset in
  `native/assets/planets/atmosphere_classes.json` (`Class-M`, `-H`, `-K`, `-O`,
  plus a default). It uses the catalogue's own field schema and validation.
- Mod-requested entries are kept for the whole session and cleared at session
  teardown (next to `clear_live()`). A set can be re-realised without
  re-running its `Initialize`, so clearing per set would lose them.

### 8.4 `NanoFX_ScriptActions` and `NanoFX_Config`

**`NanoFX_ScriptActions`:**

- `TurnOffLights(pAction, pObject)` → `DisableGlowAlphaMaps()`.
- `TurnOnLights(pAction)` → global glow off then on (§6.3).
- `NanoDamageShip(...)` → `AddDamage`.
- `SetNanoRotation`, `SetGameSpeed` and `DestroyTGSequence` behave as named.
- `CreateControllerFX(sFile, pEmitFrom, pAttachTo, fSize=1.0, vEmitPos, vEmitDir, bInheritVel=0, bDetach=0, fFrequency=0.2, fLifeTime=0.1, fEmitVel=None, fVariance=None, fDamping=None, vGravity=None, iTiming=32, sType="Normal", fRed/fGreen/fBlue=255.0, fBrightness=0.6)`
  builds the controller through `SetupController(sType, ...)` with NanoFX's
  per-type key shapes. The texture goes through the sprite library (§7). It
  returns `App.EffectAction_Create(controller)`.
  - `fBrightness` is the **time** of the tint colour key, not a brightness.
- **Stock App behaviour is NOT changed for this.** Production effects run
  through the same controller surface:
  - `hull_hit_smoke` → `Effects.CreateSmokeHigh` uses
    `TGModelUtils_CastNodeToAVObject` (`Effects.py:281`) and
    `ExplosionPlumeController_Create`;
  - the death cascade's `CreateDebrisSparks` calls `SetDetachEmitObject`
    (`Effects.py:487`).

  So those calls, `SetTargetAlphaBlendModes` (any call → additive) and the
  `SetGravity` / `SetDetachEmitObject` no-ops all keep today's behaviour. The
  shim adapts on its side:
  - **`pEmitFrom`.** When a caller passes a `pEmitFrom` that is not a real
    object (e.g. the `_NamedStub` from `TGModelUtils_CastNodeToAVObject`),
    the shim emits from `pAttachTo`.
  - **`sType="Debris"`** uses a new `App.DebrisParticleController_Create`.
    No stock script calls it, so adding it is safe. It is an AnimTS-style
    controller carrying NanoFX's debris keys.
  - **`sType="Plume"`** builds an AnimTS controller with NanoFX's plume keys
    rather than touching `ExplosionPlumeController`.
  - **`vGravity`** is accepted and ignored. Only NanoFX's own BridgeFX passes
    it, and the only stock caller of `SetGravity` is
    `Bridge/bridgeeffects.py`, which the engine never runs.

**`NanoFX_Config`.** NanoFX's default settings as read-only module values.

### 8.5 Effect modules

- The sub-packages `ExplosionFX`, `WarpFX` (with `WarpFX_GUI`, `AI`),
  `CameraFX`, `BridgeFX` and `SpecialFX` exist.
- Any function looked up on them is a callable that logs once per name
  (`"NanoFX effect API not supported: <module>.<name>"`) and returns `None`.
- Never a truthy stub object.

### 8.6 In passing

`ShipDef.race` becomes a `str` subclass with `.name` (`"Fed"` → `"Federation"`;
other races identity). Foundation-style `shipList[k].race.name` then works
everywhere.

## 9. Testing and live verification

**Automated, run by `scripts/check_tests.sh`:**

- **`mod_policy`:**
  - synthetic lists, plus a checked-in **path-only** list of the real NanoFX
    2.0 layout;
  - standalone blocked whole; bundled skipped with the rest loaded;
  - Foundation files refused, with the conditional three only when they import
    Foundation;
  - "later mod wins" preserved when a refused file would have won;
  - report lines.
- **Finders (both):**
  - ours beats a mod's `Custom/NanoFXv2`;
  - `Custom.Ships` / `Custom.Autoload` still resolve from mods;
  - case-folded match.
- **Names:**
  - `MutatorDef` and its instances;
  - `DisableGlowAlphaMaps` → emissive 0 and running-light level 0;
  - global glow off → all dark; on → clears per-object flags;
  - `race.name`.
- **API package:** one test per function **against the real App surface**, not
  doubles. `CreateAtmosphereFX` precedence; flicker concurrency cap; effect
  modules return `None` and log.
- **Sprite library:**
  - alias exact and prefix, case-folded;
  - fallback when a PNG is missing;
  - `sprite` / `native` / `none`;
  - `TextureAnimManager` grid capture;
  - shockwave spawn and tint;
  - drift test;
  - `green_matte` refusal on a misaligned pair.
- **C++ (ctest):** PNG decode in the particle pass; frame selection for the
  three playback modes; pivot offset; `emit_dir` orientation; shockwave tint
  default unchanged.
- **Heatmap:** E4M5's `DisableGlowAlphaMaps` row clears.
- **Production byte-identical guard.** A test drives the stock `Effects`
  helpers the engine calls:
  - `CreateSmokeHigh`
  - `CreateDebrisExplosion`
  - `CreateDebrisSparks`

  It asserts their particle descriptors are unchanged by this project:
  texture path, grid, brightness, blend and keys. In particular, moving
  `ExplosionA` / `ExplosionB` into the manifest must reproduce today's values
  exactly.

**Live checks (Mark):**

1. Fixture mod in `mods/` (uncommitted), a developer mission or Autoload. It
   calls every §8 function on visible ships and a custom-NIF planet, and every
   sprite id through `CreateControllerFX`, including `shock_ring` and `none`.
2. E4M5: the Kessok ships go dark.
3. Real NanoFX in `mods/`: reported as blocked; tactical sounds and Quick
   Battle work.
4. By eye: `nova_flare → none`, each sprite's `scale` / `pivot`, debris `fps`,
   and `fire_jet` venting along the hull normal.

## 10. Assumptions and risks

- **§6.3 re-enable semantics** are inferred from NanoFX's usage, not recovered
  from the binary. Verify when the reference server is reachable.
- **Glow scope.** `emissive_scale` is assumed to cover the glow map and any
  glow regions on the instance. Confirm during implementation that region
  gain does not re-light a ship at emissive 0.
- **Generator determinism.** `green_matte` depends on two generations keeping
  their composition. The silhouette check is the guard.
- **Shared controller surface.** `particles.py` serves both NanoFX callers and
  production effects. Every change there is gated on the library resolving an
  *aliased* path (or a new `sType`). The guard test in §9 holds the stock
  path to today's output.
- **Black-background art adds light only.** Smoke frames read as lit gas. This
  is accepted for `fireball` / `fire_jet` tails.
- **Corpus gap.** Locally, no mod calls the NanoFX API; only `Blank.tga` is
  used. §8 follows NanoFX's public functions. Real call sites may surface
  needs not covered here.

## 11. Follow-up (immediate, agreed)

Apply the library to Dauntless's own stock effects:

- alias stock `ExplosionA` / `ExplosionB` → `fireball` (affects every SDK
  `Effects` explosion, including the death cascade);
- `glint_burst` for hit flashes;
- `debris_chunk` alongside `breach_debris`;
- `shock_sphere` added to the warp-core breach.

Each is its own visual decision, with an in-game A/B.

Also later:

- tumble sheets with more frames;
- a native expanding shell for breaches;
- consuming ShipDef colour hooks;
- custom bridges (a separate project).
