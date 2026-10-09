# Bridge Emitters — Spike Design (living)

> **Status:** exploration, 2026-10-08. Branch `spike/bridge-emitters`
> (worktree `.claude/worktrees/bridge-emitters`), off local `main` `08045a2d`.
> Builds on the merged baseline (`2026-10-08-bridge-lighting-baseline-design.md`).
> Updated with each accepted iteration; §10 is the iteration log.

## 1. Goal

(A) Select an object on a bridge in-game. (B) Make a selected object an
**emitter**: a light direction and cone, a surface tint per alert state
(green / yellow / red), and transition cycles between and within states
(e.g. a red-alert pulse/blink). Per-bridge data, developer-only editing.

Invariant inherited from the baseline: **lit surfaces never bloom; only
emitters do** (`diffuse_ceiling`, max 0.88 < bloom threshold 0.9).

## 2. Evidence (read before re-deriving)

### 2.1 What BC does (SDK + clean-room reference)

- **No SDK script drives bridge alert visuals.** Alert changes post
  `ET_SET_ALERT_LEVEL` to the player ship (`XOMenuHandlers.py:139-175`,
  `MissionLib.RedAlert` `:2816-2850`); the SWIG surface
  `BridgeObjectClass.GoToGreen/Yellow/RedAllert`, `FlickerLCARs`,
  `TurnLCARsOn/Off` (`App.py:4915-4920`) has **no SDK caller** for the GoTo
  methods. The link is inside the engine.
- The only script-driven bridge visual: `bridgeeffects.py:26,57,102`
  `FlickerLCARs(2.0/3.0/4.0)` on weapon hits.
- Clean-room reference `spec/BridgeObjectClass.md` §4.3 (logic-exact):

  | Method | red flag | blink controllers | `SetLightLevel` |
  |---|---|---|---|
  | Green | 0 | stop | (0.5, 1.0) |
  | Yellow | 0 | start | (0.5, 1.0) |
  | Red | 1 | start | (0.5, 0.4) |

  So **yellow blinks without dimming; red blinks and dims to 0.4**. §4.5
  `Update`: a linear ramp (time-left, duration, from→to) lands exactly on
  its target — reading `(0.5, x)` as "0.5 s ramp to x" is plausible but
  **unproven**. LCARS flicker = random grey per frame for a duration, then
  restore.
- **Unknown:** blink period / duty / waveform / colours (the blink
  controllers are a "wall" in the reference); how or whether the engine
  binds the NIF groups `Red On GlowAlpha`, `Red Off GlowAlpha`,
  `Blinking GlowAlpha`, `Dim Maps` by name. The bible has nothing.
- ⚠️ Our baseline differs from BC: red is ×1.0 (BC: 0.4 dim), green is
  ×1.5 (BC: 1.0). The baseline values were Mark's live picks, not fidelity
  claims.

### 2.2 Asset facts (memory: bridge NIF vertex-lighting facts)

- EBridge carries the four groups as NiNode subtrees; GlowAlpha textures have
  real alpha masks (redalertpanel 7% bulbs). DBridge has **no** alert nodes;
  its alert bars are "wall inset slot left/right", black, sharing a texture
  with "Material: black" ⇒ grouping must be per shape, never per texture.
- DBridge tex 7 is shared by 22 shapes ⇒ per-texture masks leak.
- DBridge `Map 3.tga` alcove cove glow is painted into a DIFFUSE.

### 2.3 Prior art

- `feat/interior-lighting` spec (status "design", never built): per-set
  `lighting.json`, `animation_profiles` {green/yellow/red: color, intensity,
  animation{type sine|square|saw, period_s, duty, phase_s}}, lights anchored
  by NIF block index, `surface_material` by block or coplanar cluster,
  emissive is a LEVEL × mask × diffuse, a glowing surface does not light the
  room unless a light is linked (`emitter_mesh`). Editor on the SPV chassis.
  Key lesson: **inferring sources from geometry puts correct lights on the
  wrong objects** — humans pick.
- `spike/ebridge-emissive-sh` (shelved, look GO): `emit = albedo × vc × mask
  × group_scale`; `receive = 1 − mask·group_on` so screens don't clip white;
  pulse `0.5+0.5·sin`, yellow 0.5 Hz amber, red 1.0 Hz (placeholders).
- 2026-06-20 spec: proposes a **bridge-wide shared clock** with per-group
  phase — unresolved against free per-profile `period_s`.

### 2.4 Engine surface today

- Picking: `manual_aim.cursor_ray` (Python) + `host_io.ray_trace_mesh` →
  C++ `ray_trace_instance_linear`; works on any instance incl. the bridge,
  but `RayHit` is only `(point, normal, t)` — **no mesh / shape identity**.
  No ID buffer or picking readback exists.
- Bridge camera `_BridgeCamera` (`host_loop.py:3765`): first-person
  mouse-look, cursor locked; officer picking already aims at **screen
  centre**.
- Per draw, identity available: `Node::name`/parent chain,
  `Mesh::shape_name()`, material index; NIF block index via `nif_shapes`.
  Debug mesh-id is a per-frame counter, not stable.
- SPV: generic `EditTarget` adapters, undo snapshots, pipette — but the
  panel/host path is ship-coupled and forces hologram-only mode (no bridge).
- Hash: `fnv1a64_hex` (`mesh_fix.cc:14`), C++ only; Python twin in
  `tools/gen_mesh_fixes.py:71`. Mesh fixes keyed
  `native/assets/mesh_fixes/<hash>.json`, shapes as `{block, name}`.
- No per-mesh tint/emissive binding; `bridge.frag` has no emissive term.

## 3. Approach — chosen: A, look-and-pick vertical slice (Mark, 2026-10-09)

Considered: **A** look-and-pick slice; **B** SPV-chassis bridge editor
(orbit camera, gizmos — large up-front host path); **C** group-first,
BC-structured (per-group profiles only; no per-object direction/cone, DBridge
starts empty). Chosen **A**, borrowing from C a shared named-profile layer
and from B an `EditTarget`-shaped adapter so gizmos can be added later
without a rewrite. Mark's addition: **a WASDQE fly camera**.

## 4. Camera & selection *(accepted 2026-10-09)*

- **Entry.** Developer-only pause-menu row "Bridge Emitters…". Opening it
  closes the pause menu and leaves the sim **paused**; the bridge is still
  drawn and lit normally. The editor previews alert states with its own
  green/yellow/red switch; it never changes the ship's real alert level.
- **Fly camera.** Hold **RMB** to look; while held, **W/S** forward/back,
  **A/D** strafe, **Q/E** down/up; **Shift** fast, **Alt** slow. Starts at
  the current captain's-chair eye, bridge-local units, base ~60 units/s (a
  DBridge is ~400 across). No collision. Closing restores the bridge camera
  exactly as it was. Bridge view doesn't drive the ship (Mark), so
  WASDQE are free there — verify our engine agrees when building.
- **Picking.** RMB released ⇒ free cursor. **LMB in the 3D view** picks
  under the cursor: `manual_aim.cursor_ray` → the C++ ray trace on the
  bridge instance, **extended to return the hit mesh + triangle**. Python
  then resolves: NIF block index, shape name, parent-node chain (shows
  `Red On GlowAlpha` and the other groups), material and texture names.
  **Alt+LMB** picks the next surface behind the first (EBridge wall tops
  hold two coincident emitters).
- **Unit of selection** = one NIF shape. Stable identity across launches =
  **(NIF content hash, block index, shape name)**; the name is a sanity
  check, so a mismatch is reported, never silently applied to the wrong
  shape.
- **Display.** Dev-only `bridge.frag` overlay keyed by that stable identity
  (not the per-frame mesh counter): the selected shape gets a pulsing cyan
  tint, the shape under the cursor a faint tint. The panel shows the
  identity readout.
- Not here: sub-shape regions (masks → §5), gizmos (later, via the adapter).

## 5. Programme order *(Mark, 2026-10-09)*

1. **Foundation** — §4 (fly camera, picker, highlight, stable identity) and
   the per-shape data file (§7) with its `material` and `emitter` sections.
2. **Bridge PBR** — implemented FIRST, in this session, with its own
   section (§9, to be designed). Starting point: the GGX BRDF preserved on
   `origin/feat/pbr-ship-spike` (56575bb4). The July ship spike lost mainly
   because nothing gave metals anything to reflect, so the bridge step
   brings its own reflection probe and a few static picker-placed spot
   lights (an early slice of §6's cast light).
3. **Emitters** — §6, built on PBR shading.

§6 is written **assuming PBR has landed**. Where it depends on a PBR-step
decision it says so; nothing in §6 depends on how those decisions go.

## 6. Emitter model *(documented 2026-10-09, assumes PBR first)*

An emitter is attached to one picked shape and has two independent parts:
a **glowing surface** and an optional **cast light**. One alert **profile**
drives both, so the colour on the fixture always matches the colour it
throws into the room.

### 6.1 Surface glow — emissive radiance

- **Defined independently of the lighting model:** linear HDR radiance
  added after lighting, before tonemap/bloom. The same term works under
  the baseline downlight and under PBR; the PBR step does not touch it.
- `glow = tint(t) × level(t) × mask × src × glow_scale`, where `src` is:
  - `texture`: the shape's own base colour (albedo);
  - `flat`: 1. Needed because DBridge's alert bars are textured **black**,
    so texture × tint gives nothing.
- **`mask`** sets which texels glow:
  - `whole`: every texel of the shape;
  - `base_alpha`: the base texture's alpha (BC's GlowAlpha textures already
    store a bulb mask there — redalertpanel is 7% bulbs);
  - `luma`: base-colour luminance above `luma_threshold`, with a
    `luma_soft` edge — for the cove glow painted into DBridge's `Map 3.tga`
    diffuse;
  - `map`: an authored greyscale emissive map from the replacements overlay
    (a PBR-era addition).
- **Masks stay per shape, never per texture.** New per-texture PBR maps are
  right for *materials* (one texture ≈ one surface type) but wrong for
  emission: DBridge texture 7 is shared by 22 shapes, from cove roofs to
  lift roofs, and a glow map on it would light all 22. A `map` mask is
  therefore named by the emitter, not discovered beside the texture.
- **A glowing texel takes less room light:** received light (diffuse and
  specular) × `(1 − mask × level_norm)`, where `level_norm` is the
  current level clamped to [0,1]. This is the shelved spike's fix that
  stopped screens clipping to white; at level 0 the shape is an ordinary
  receiver again.
- **Bloom:** glow is the only term guaranteed to be eligible. The baseline
  rule "lit surfaces never bloom" is narrowed to **"lit DIFFUSE never
  blooms"**; whether a specular highlight may bloom is decided in the PBR
  step (§9).

### 6.2 Cast light — a punctual spot

- Fields: `position` (bridge-local; default = the pick's hit point),
  `direction` (default = the surface normal at the hit; the editor's "aim
  where I'm looking" re-points it), `inner_deg`, `outer_deg`, `range`,
  `intensity`.
- **Physically sensible units, so PBR doesn't force a rework:**
  - distance falloff = inverse-square with a smooth window to zero at
    `range`: `(clamp(1 − (d/range)⁴, 0, 1))² / (d² + 1)`;
  - cone = `smoothstep(cos outer, cos inner, dot(−L, direction))`, squared;
  - radiance in = `colour × intensity × falloff × cone`, through the same
    BRDF as every other light (GGX once PBR lands).
- **Colour** = the profile's evaluated tint × level at time t, so the light
  pulses and fades exactly with its glow. Optional `light_scale` decouples
  the cast brightness from the glow brightness.
- Adds to received light: diffuse goes through the diffuse ceiling and
  never blooms; specular is subject to the §9 decision.
- **Not occluded:** no shadows, and AO multiplies only ambient / indirect
  light, never direct spots. A spot can light through a thin wall; `range`
  keeps it local. Shadows are a later decision.
- **Cap: 32 lights**, looped per pixel. Lights beyond the cap are reported
  by name at load, never dropped silently.

### 6.3 Profiles, waves, transitions

- Named and shared: `profiles.<name>` = `{fade_s, green, yellow, red}`.
  DBridge's left and right alert bars both use one `red_bar`.
- Each state = `{tint: [r,g,b], level, wave}`. A missing state means off
  (level 0) in that state.
- **`wave`**: `shape` ∈ `steady | sine | square`; `period_s`; `duty`
  (fraction of the period that is on, `square` only); `soft` (edge easing
  for `square`, as a fraction of the period: 0 is a hard blink, higher
  values a pulse); `min` (floor level at the trough, as a fraction of
  `level`).
- **Phase is per emitter** (`phase`, fraction of a period), so a row of
  lights can chase along a wall.
- **One shared bridge clock** — a bridge-wide time base, frozen under pause
  like the letterbox (`_player_dt`). Emitters with the same period and
  phase stay in sync, and periods stay free per profile. This settles the
  2026-06-20 spec's "shared clock vs per-profile period" conflict: we get
  both. The editor drives its own preview clock so waves animate while you
  edit a paused game.
- **Alert-state change cross-fades** from the old state's *live* output to
  the new state over the profile's `fade_s`. Default 0.5 s, because BC's
  `SetLightLevel(0.5, …)` ramp suggests it (unproven, §2.1).
- **Alert ambient untouched:** the baseline's ×1.5 / ×1.0 / ×1.0 room
  ambient stays as it is. BC's red-alert room dim to 0.4 (§2.1) is a
  separate question, left open.

### 6.4 Where it runs

- Python evaluates profiles each frame — pure functions beside
  `engine/bridge_lighting.py`, unit-testable without GL — and pushes two
  small arrays to the bridge pass: per-shape glow (colour, mask mode and
  params) and per-light spot data.
- Render-only data; never a game-state mutation (the `render_payload`
  warning in `perf-cadences-and-latency.md`).
- Emitters apply only to the player's bridge instance. Comm-set rooms have
  other NIFs, so their hashes never match.

## 7. Persistence *(draft — pending Mark's review)*

- **Location:** `native/assets/bridge_lighting/<fnv1a64>.json`, a PROJECT
  asset beside `mesh_fixes/` (§6a of the baseline spike), resolved via the
  project asset root. It holds only references and parameters, never BC
  geometry.
- **Lookup order:** the replacements overlay and mod directories first (a
  mod can ship a file for its own bridge NIF, keyed by that NIF's hash), then
  the project. A modded NIF with no file gets the baseline: default
  materials, no emitters. **No name-match fallback**: a near-miss bridge
  silently receiving another bridge's emitters is the wrong-object failure
  §2.3 warns about.
- **Hash in Python:** a new binding returns the content hash the asset cache
  already computes for mesh fixes, so Python never re-hashes a NIF.
- **Schema** (`format: 1`):

  ```json
  {
    "format": 1,
    "source": "data/Models/Sets/DBridge/DBridge.nif",
    "profiles": {
      "red_bar": {
        "fade_s": 0.5,
        "green":  {"tint": [1, 0.2, 0.1], "level": 0},
        "yellow": {"tint": [1, 0.6, 0.1], "level": 2, "wave": {"shape": "sine", "period_s": 2.0, "min": 0.3}},
        "red":    {"tint": [1, 0.1, 0.05], "level": 4, "wave": {"shape": "square", "period_s": 1.0, "duty": 0.5, "soft": 0.1}}
      }
    },
    "shapes": {
      "137:wall inset slot left": {
        "block": 137,
        "name": "wall inset slot left",
        "material": {},
        "emitter": {
          "profile": "red_bar",
          "phase": 0.0,
          "glow": {"src": "flat", "mask": "whole", "scale": 1.0},
          "light": {"position": [191, 0, 40], "direction": [-1, 0, 0],
                    "inner_deg": 30, "outer_deg": 60, "range": 120,
                    "intensity": 1.0, "light_scale": 1.0}
        }
      }
    }
  }
  ```

  Shapes are keyed `"<block>:<name>"`, keeping one entry per shape with both
  sections. `material` is reserved here and defined by the PBR step (§9).
  Positions are bridge-local (sets draw with an identity transform). The
  numbers above are illustrative, not tuned.
- **Validation at load:** unknown fields are REJECTED (the atmosphere
  catalogue's rule). A block/name mismatch skips that entry with one
  warning naming it. A profile reference that resolves to nothing is an
  error naming the shape.
- **Writer:** the editor regenerates the file wholesale, deterministically
  (sorted keys, fixed float format) and atomically (`.tmp` then replace),
  keeping unknown top-level keys (the `decals_writer` pattern). A
  round-trip test pins it: load → save is byte-identical.

## 8. Editor *(draft — pending Mark's review)*

- **A CEF panel in the `cp-*` modal family**, developer-only, tagged
  `data-panel` so text fields capture the keyboard automatically. It is
  docked to one side, so the 3D view stays clickable (§4).
- **Panes:**
  - *Selection*: the identity readout (§4), plus the shape's parent group
    (`Red On GlowAlpha` and so on), shown as information only.
  - *Material*: defined by the PBR step (§9).
  - *Emitter*: an enable checkbox; a profile dropdown with New/Rename;
    glow src, mask and its parameters; a light toggle plus its fields;
    **"Place light at hit"**; **"Aim where I'm looking"**.
  - *Profile*: per state, a tint colour picker, a level, and the wave
    fields; the profile's `fade_s`.
  - *Preview*: green/yellow/red switch (§4); preview clock play/pause and
    speed.
- **Edits are live** (pushed to the renderer each change). **Save** writes
  the file (§7); **Revert** reloads it.
- **Undo** = SPV-style snapshot stack: deep-copy the pending document
  before each action, push it if anything changed.
- **Pipette** copies one shape's emitter onto the selected shape. Phase is
  kept on the target, so a copied light doesn't land in lockstep.
- **`BridgeEmitterTarget`** implements the `EditTarget` methods that make
  sense for a light (`position` / `set_position`, `get_rotation` /
  `set_rotation` on the direction, `pipette_fields_from`), so the SPV's
  Move/Rotate gizmos can be added later without a new branch in the panel.

## 9. Bridge PBR *(to be designed next)*

Placeholder. It must decide: the BRDF port; the `material` section of §7;
map sources (replacements overlay, per texture); the reflection probe (one
capture at the captain's chair, possibly one per steady alert state so
emitters appear in reflections); whether specular may bloom (§6.1); how the
downlight becomes diffuse irradiance; and how AO applies.

## 10. Iteration log

| # | Date | Change | Verdict | Sections |
|---|------|--------|---------|----------|
| — | 2026-10-08 | Spec created; evidence recorded | — | 1, 2 |
| — | 2026-10-09 | Approach A + WASDQE fly camera chosen; camera & selection design | accepted | 3, 4 |
| — | 2026-10-09 | Programme order (PBR first); emitter model documented assuming PBR; persistence + editor drafted | §5–6 documented; §7–8 draft | 5, 6, 7, 8, 9 |
