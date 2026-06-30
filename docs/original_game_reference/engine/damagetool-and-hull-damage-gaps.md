# DamageTool & Hull-Damage Gaps

**What this is:** an analysis of BC's `DamageTool` and the hull-damage system it
authors, mapped against Dauntless's voxel-carve damage system, with prioritized
gaps. Reference material beside
[`aieditor-ai-surface-and-gaps.md`](aieditor-ai-surface-and-gaps.md) and
[`bcs-save-format.md`](bcs-save-format.md).

**Sources:** the core internals here come from an **RTTI/symbol extraction of
`sdk/Tools/DamageTool/DamageTool.exe`** (MSVC RTTI; PDB path
`C:\TGSharedExternal\NDL3\...\DamageTool_s.pdb`) run on Windows, cross-checked
against the SDK Python and the generated `Damage*.py` scripts. Codebase
correspondences and gap-liveness were verified against the current tree (see the
✓/⚠ verification notes inline).

> Phase 2 is active — the gaps below are real Phase-2 omissions, **not** intentional
> Phase-1 simplifications.

---

## What DamageTool is

`sdk/Tools/DamageTool/DamageTool.exe` is a **content-authoring tool** BC's artists
used to pre-place visual damage on ships. Workflow: load a NIF (via
`ConfigFile.txt`), interactively position implicit-field **MetaVolumes (metaballs)**
over the hull, export a Python script. Every `Damage*.py` in the SDK was generated
by it — **24 generated scripts, ~22 ships across 7 campaign missions** spawn
pre-wrecked: E2M1 (Karoon), E3M2 (Berkeley), E3M4 (Galors/Marauder/Terrik), E3M5
(BOPs), E5M2 (Akira), E6M2 (Hulks), E6M4 (Keldon/Transport), plus station debris.

Generated form:
```python
def AddDamage(pThingToDamage):
    pThingToDamage.AddObjectDamageVolume(x, y, z, influRad, strength)
    ...
```
Five floats: **position** `(x,y,z)` in body/model space (GU), **influRad** (metaball
radius, GU), **strength** (field weight). Authored tiers (constant across all ships):

| Tier | influRad | strength |
|---|---|---|
| Minor surface damage | 0.4 | 300 |
| Major hull breach | 1.0 | 600 |

The ratio **strength / influRad ≈ 750 is constant** — strength scales with radius.
This is the key BC calibration anchor.

---

## The full Damage system (from DamageTool.exe RTTI)

| Class | Role |
|---|---|
| `MetaVolume(pos, influRad, strength)` | One implicit-field sphere (metaball). |
| `MetaVolumePool` | Shared MetaVolume store; spatial query `GetInfluencing`. |
| `BinaryVoxelizer` / `BinaryVoxel` | Voxel BSP of the hull — **clipper**; damage stays outside solid interior. `VoxelIsInside(x,y,z)`, `VoxelIsBoundary(x,y,z)`. |
| `MetaSurfacePolygonizer` | Walks hull triangles; classifies each base / scorch / hole; subdivides straddling tris; hides tris in hole regions. Collectors: `ms_pBaseFeatures`, `ms_pDamageFeatures`, `ms_pHoleFeatures`. |
| `MetaVolumePolygonizer` | Marching-cubes-ish on the damage-volume interior — generates the exposed-interior geometry visible **through** holes. |
| `OBBForest/Root/Node/Leaf` | OBB acceleration tree from the NIF mesh; ray/segment/sphere/box intersection. Enabled by the `USE_OBBS` NIF extra-data property. |
| `TGImageOverlay` / `TGOverlayController` | Texture-space compositing: `AddOverlay(name,path)`, `BeginOverlay()/ApplyOverlay()/EndOverlay()` — composites damage decals onto the hull texture. |
| `Damage` | Top-level: holds volumes, polygonizers, clipper. |

Per-ship `Damage` setters (all per-ship tunables): `SetSurfaceGeometry`,
`SetSurfaceDamageTexture`, `SetSurfaceHoleTexture`, `SetSurfaceGenerateHoleGeometry`,
`SetSurfaceDamageRes`, `SetSurfaceDamageLevel`, `SetSurfaceScorchLevel`,
`SetInsideTexture`, `SetVolumeIsoLevel`, `SetVolumeClipper`, `SetSurfaceOBBs`,
`SetMaxRefreshTime`, `ResetRefreshTime`, `AddVolume`, `Refresh`.

### DamageableObject Python API (`sdk/Build/scripts/App.py:5346-5369`)

Visual-damage methods that need shims:

| Method | Frame | Caller | Status |
|---|---|---|---|
| `AddObjectDamageVolume(x,y,z, influRad, strength)` | body-space | story `Damage*.py` | ❌ MISSING |
| `AddDamage(pEmitPos, fRadius, fDamage)` | world-space | runtime, `Effects.py:698` (`DeathExplosionDamage`) | ❌ MISSING |
| `DamageRefresh()` | — | trigger re-polygonization | ❌ MISSING |
| `RemoveVisibleDamage()` | — | clear all damage | ❌ MISSING |
| `SetVisibleDamageRadiusModifier(float)` | — | per-ship scale | ❌ MISSING |
| `SetVisibleDamageStrengthModifier(float)` | — | per-ship scale | ❌ MISSING |

Peripheral / lower priority: `SetSpecularKs`, `DisableGlowAlphaMaps`,
`GetClonedModelRadius`, `HasClonedModel`, `GetClonedModelCount`.

---

## How BC maps onto Dauntless

Our Path C ([hull-breach-2b spec](../../superpowers/specs/2026-06-17-hull-breach-2b-dual-contouring-interior-design.md))
converged on BC's semantics independently: same primitive (a sphere defines hole +
scoop), same masking idea (BC `BinaryVoxel` ≡ our `SourceVolumeCache` fill).

**Already-correct correspondences (verified):**

| BC | Ours |
|---|---|
| `BinaryVoxel` material mask | `SourceVolumeCache` fill volume; `fill(p_body) ≥ iso` in `native/src/renderer/breach_pass.cc:179` |
| `MetaVolume(pos, influRad)` | `HullCarve` slot `(center_body, radius)` in `native/src/scenegraph/include/scenegraph/hull_carve.h:12` |
| body-frame coords on moving ships | `host_bindings.cc:2477` converts world→body at emission (`world_to_body`, `radius/s`) — correct by construction |
| `Damage.tga` cavity texture | triplanar damage texture on the scoop (`breach_pass.cc`) — **but see Damage.tga note below** |
| `MetaVolumePolygonizer` | `native/src/voxel/dual_contour` (built + tested, then bypassed for Path C) |

---

## Actionable gaps (priority order)

### Gap 1 — `DamageableObject` visible-damage API ✅ IMPLEMENTED
**Premise correction:** the missing methods did **not** crash. Our base
`TGObject.__getattr__` (`engine/core/ids.py:87`) returns a callable, truthy `_Stub`
for any unknown attribute, so `pShip.AddObjectDamageVolume(...)` **silently no-ops** —
authored wrecks rendered intact (silent fidelity loss, not an `AttributeError`).

Now implemented in `engine/appc/objects.py` (`DamageableObject`) +
`engine/appc/visible_damage.py` (a deferred queue mirroring `core_breach_carve.py`):
authored calls are queued during `Initialize` and drained per-tick from
`host_loop._advance_*` once the ship's render instance is realized, then emitted via
the existing `host.hull_carve_add` (**no native change**).
- `AddObjectDamageVolume(x,y,z,influRad,strength)`: body→world is `loc + R·(x,y,z)`
  with no scale (same convention as `subsystems.subsystem_world_position`);
  `radius = max(MIN_CARVE_RADIUS_GU, influRad)`; outward radial normal. `strength`
  dropped (Gap 2).
- `AddDamage(pEmitPos, fRadius, fDamage)`: world-space point passed straight through;
  normal = `unitize(point − loc)`. Covers `Effects.DeathExplosionDamage`.
- `DamageRefresh()`: no-op (renderer is per-frame).
- `RemoveVisibleDamage()`: clears **pending** volumes only. Clearing already-emitted
  carves still needs a native `HullCarveField::clear()` + `hull_carve_clear` binding
  (does **not** exist — Gap-1 follow-up; only caller is `Actions/ShipScriptActions.py`).
- `SetVisibleDamage{Radius,Strength}Modifier(float)`: stored on the ship; the radius
  modifier scales the emitted carve radius now, strength modifier waits on Gap 2.

**Known limitation:** `HullCarveField` is 24 slots, so a >24-volume script
(`Hulk1Damaged` = 103) overflows (proximity-merge softens it). `DamageAkira` (22) and
`DamagedKaroon` (6) fit. **Verify in-GUI:** `./build/dauntless --developer` → mission
picker → **Developer → Damage Preview** (`engine/dev_missions/damage_preview.py`) spawns
a stock-pre-damaged Akira ~6 GU dead-ahead.

### Gap 2 — strength accumulation: phaser dribble builds into a breach ✅ IMPLEMENTED
**The hull-damage-relevant phaser finding.** BC's metaball field *sums*: many weak hits
at one spot eventually cross the iso → spontaneous breach. Previously we hard-gated on a
per-hit `MIN_CARVE_HULL = 60`, so sustained light fire never breached. Now implemented as
BC's additive field:
- `HullCarve` (`native/.../hull_carve.h`) gains `strength` (accumulated) + `influ_radius`
  (merge proximity); `HullCarveField::add` accumulates strength on merge and returns the
  slot. Visible `radius` is derived from the running total via
  `hull_carve_strength_to_fraction` — **0 below the iso** (150), then a *fraction of the
  ship's bounding radius* (emerges small, grows to ≈25% of radius), so carves scale with
  hull size (see Gap 4). The host scales by `ship_radius` and the instance scale.
- `hull_carve_add` binding takes `(influ_radius, strength, time, floor_radius=0)`; the
  visible radius = `max(floor, strength→radius)`, never shrinking. The breach VFX event
  fires only when a carve newly appears or grows, so sub-iso accumulation is silent.
  Renderer skips `radius<=0` slots (`frame.cc`, `breach_pass.cc`).
- `hit_feedback` drops the per-hit gate and deposits `strength = absorbed_hull ×
  STRENGTH_PER_HULL` (5.0; so a ~60-hull hit reaches the iso in one shot, preserving the
  old strong-hit feel) with `influ = carve_influ_gu(splash)`; floor 0 (invisible until
  accumulated). `core_breach` + authored `visible_damage` pass a `floor` (guaranteed size)
  and carry their own strength (authored 300/600), so they integrate with combat
  accumulation. Tuning knobs (`STRENGTH_PER_HULL`, influ floor) live in
  `engine/appc/hull_carve.py`; the iso/curve are C++ constants (`kHullCarve*`).

### Gap 3 — two-tier carve radii drift from BC's authored values ✓ verified live
BC authoring (constant across ships): small **0.4 GU**, large **1.0 GU**. Ours:
`MIN_CARVE_RADIUS_GU = 0.25` (`hull_carve.py:21`, *below* BC's small tier);
`_RADIUS_SCALE[SCORCH] = 2.25` (`damage_decals.py:29`, *far above* BC's small tier).
Fix: a calibration pass against BC's 0.4 / 1.0 GU baseline. Eye-tuned values may
still be right for our HDR/modern look — but worth knowing how far we drifted from
authored intent.

### Gap 4 — per-ship damage modifiers ✅ IMPLEMENTED (SDK-faithful, absolute sizes)
Carve sizes are **absolute** (game units) — a weapon makes the same physical hole on any
hull, so a hole is a bigger *fraction* of a small ship (correct). The C++ strength curve
returns an absolute radius (`hull_carve_strength_to_radius_gu`, clamp `kHullCarveRadiusMaxGu`).
The **only** per-ship scaling is BC's authored `SetVisibleDamageRadiusModifier` /
`SetVisibleDamageStrengthModifier` (from `loadspacehelper` hardpoint stats): the radius mod
is passed to `hull_carve_add` as `radius_modifier` (multiplies the carve radius), the
strength mod scales the deposited strength. **Only 10 fixed structures set them** — all
with `DamageRadMod` 5–15 (bigger holes) and reciprocal `DamageStrMod` ≈ 1/RadMod (tankier:
strength accumulates slower); every combat ship defaults to 1.0.

(History: a `GetRadius()`-proportional scaling was tried first — `fraction-of-radius` curve
— but it's physically wrong (impacts don't shrink on smaller targets) and double-counted
size for the 10 stations that already set `DamageRadMod`; reverted to absolute + the SDK
modifier on 2026-06-30.)

(Note: the older `ShipProperty.SetDamageResolution` per-ship value — Galaxy 10,
Akira 8, kessokmine 2 … — is still stored-but-unused in `engine/appc/ships.py:460`; it is
BC's `SetSurfaceDamageRes`, the carve **granularity** knob, complementary to these
modifiers.)

---

## Observations (lower / no action)

- **Damage1-4.tga are HUD icons, not scorch variants.** They are the tactical-display
  subsystem-damage glyphs, loaded via `LoadIconTexture` into the `"DamageTextures"`
  IconManager group (`sdk/.../Tactical/EffectTextures.py:299-312`). BC has **no
  variant system for hull scorch**. ⚠ **Live issue:** our `breach_pass.cc:43-46`
  loads `Damage1-4.tga` and animates them at 8fps as the **breach interior cavity
  texture** (the code comment already self-doubts: "*Possibly a misremembering of
  Textures/Effects/Damage.tga*"). So the cavity-interior look is sourced from the
  **wrong asset** — a concrete renderer follow-up: point it at the real
  `Textures/Effects/Damage.tga` (single image), not the HUD glyph set.
- **OBB tree vs live mesh raycast:** BC pre-baked OBB trees per NIF (`USE_OBBS` extra
  data); we raycast the live mesh in `hit_feedback`. Modern hardware makes this a
  non-issue, and it explains some otherwise-mysterious NIF extra-data bytes.
- **`SetMaxRefreshTime` per-frame budget:** BC spread remesh cost across frames. We
  obsoleted this by going shader-only (no remesh) in the breach renderer. Only
  relevant if the dual-contour interior-mesh path is ever resurrected.
- **`voxel/dual_contour` ≡ BC's `MetaVolumePolygonizer`** — built + tested, then
  bypassed for Path C. Available as a "Classic colored-voxel" rendering option if
  Path C's smooth scoop ever reads too clean.

---

## Reference paths

- DamageTool symbols: `sdk/Tools/DamageTool/DamageTool.exe` (RTTI; PDB
  `DamageTool_s.pdb`).
- Generated scripts: `sdk/Build/scripts/Maelstrom/*/Damage*.py`.
- Runtime entrypoint: `sdk/Build/scripts/Effects.py:698`.
- Our carve pipeline: `engine/appc/hull_carve.py`, `engine/appc/hit_feedback.py:256-279`,
  `native/src/host/host_bindings.cc:2464`,
  `native/src/scenegraph/include/scenegraph/hull_carve.h`,
  `native/src/renderer/breach_pass.cc`.
- Design specs: `docs/superpowers/specs/2026-06-16-voxel-hull-damage-foundation-design.md`,
  `docs/superpowers/specs/2026-06-17-hull-breach-2b-dual-contouring-interior-design.md`.
