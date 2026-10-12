# Bridge Emitters — Spike Design (living)

> **Status:** exploration, 2026-10-08. Branch `spike/bridge-emitters`
> (worktree `.claude/worktrees/bridge-emitters`), off local `main` `08045a2d`.
> Builds on the merged baseline (`2026-10-08-bridge-lighting-baseline-design.md`).
> Updated with each accepted iteration; §10 is the iteration log.
> **2026-10-10:** §11 = emitter glow slice 1 (branch `feat/dbridge-round7`), amending §6.1, §7 and §9.7.
> **2026-10-11:** §12 = editor panes for glow and profiles (slice 2). §13 = modifier stacks, five states, editor chrome (slice 3; supersedes §11's state shape and §12's panes).

## 1. Goal

(A) Select an object on a bridge in-game. (B) Make a selected object an
**emitter**: a light direction and cone, a surface tint per alert state
(green / yellow / red), and transition cycles between and within states
(e.g. a red-alert pulse/blink). Per-bridge data, developer-only editing.

Invariant, narrowed from the baseline's "lit surfaces never bloom" (§9.5):
**lit diffuse never blooms** (`diffuse_ceiling`, max 0.88 < bloom threshold
0.9); **emitters and their reflections/highlights may.**

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
- **Stock bridges carry NO specular, gloss, bump or normal maps** (measured
  2026-10-09 by filename: DBridge 129 textures, EBridge 174, zero
  `*spec*`/`*gloss*`/`*bump*`/`*norm*`). Caveat: a filename search can't
  see a NIF gloss slot pointing at a differently-named texture; irrelevant
  here, because the loader fills the gloss slot from `_specular`/`_spec` names
  only and §9 doesn't read it. **The July spike's `_specular`-map multiplier
  is NOT ported**: bridge specular comes only from roughness/metalness
  (§9.2), Fresnel and what is reflected.

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

- **Entry.** Developer-only pause-menu row "Bridge Emitters…". Like every
  dev panel, it joins the host's modal blockers: the pause menu stays open
  but hidden, which is what keeps the sim **paused**; the bridge is still
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
  shape. Stock DBridge's shapes are all unnamed (145 of 145), so there the
  identity is effectively (hash, block) and the panel's display name falls
  back to the owning node's name, shown as "(node) <name>".
- **Display.** Dev-only `bridge.frag` overlay keyed by that stable identity
  (not the per-frame mesh counter): the selected shape gets a pulsing cyan
  tint, the shape under the cursor a faint tint. The panel shows the
  identity readout.
- Not here: sub-shape regions (masks → §6.1), gizmos (later, via the adapter).

## 5. Programme order *(Mark, 2026-10-09)*

1. **Foundation** — §4 (fly camera, picker, highlight, stable identity) and
   the per-shape data file (§7) with its `material` and `emitter` sections.
2. **Bridge PBR** — implemented FIRST, in this session (§9). Starting point: the GGX BRDF preserved on
   `origin/feat/pbr-ship-spike` (56575bb4). The July ship spike lost mainly
   because nothing gave metals anything to reflect, so the bridge step
   brings its own reflection probe and a few static picker-placed spot
   lights (an early slice of §6's cast light).
3. **Emitters** — §6, built on PBR shading.

Steps 1 and 2 are planned as **two plans** (foundation, then PBR), each
ending with a live check before the next starts.

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
- **`mask`** sets which texels glow *(dropped from the schema for slice 1 -- §11.2)*:
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
  *(Narrowed 2026-10-09, task 17: texture-level `_emissive` sibling maps
  now exist as a DEFAULT under the emitter — see §9.7.)*
- **A glowing texel takes less room light:** received light (diffuse and
  specular) × `(1 − mask × level_norm)`, where `level_norm` is the
  current level clamped to [0,1]. This is the shelved spike's fix that
  stopped screens clipping to white; at level 0 the shape is an ordinary
  receiver again.
- **Bloom:** glow is always eligible. The baseline rule "lit surfaces never
  bloom" is narrowed to **"lit DIFFUSE never blooms"**; specular is uncapped
  (§9.5).

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
  never blooms; specular is uncapped (§9.5).
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

## 7. Persistence *(accepted 2026-10-09)*

- **Location:** `native/assets/bridge_lighting/<fnv1a64>.json`, a PROJECT
  asset beside `mesh_fixes/` (§6a of the baseline spike), resolved via the
  project asset root. It holds only references and parameters, never BC
  geometry.
- **Lookup order:** the replacements overlay and mod directories first, at
  `<dir>/dauntless/bridge_lighting/<hash>.json` (a mod can ship a file for
  its own bridge NIF, keyed by that NIF's hash), then the project. A modded NIF with no file gets the baseline: default
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
  sections. `material` = `{"roughness": 0..1, "metalness": 0..1}`, each
  optional — source B of §9.2; a channel absent here falls through to the
  default.
  Positions are bridge-local (sets draw with an identity transform). The
  numbers above are illustrative, not tuned.
- **Validation at load:** unknown fields are REJECTED (the atmosphere
  catalogue's rule). A block/name mismatch skips that entry with one
  warning naming it. A profile reference that resolves to nothing is an
  error naming the shape.
- **Writer:** the editor regenerates the file wholesale, deterministically
  (sorted keys, fixed float format) and atomically (`.tmp` then replace).
  Unknown keys never survive to the writer — the loader rejects them. Save
  writes where the file was found, else the project directory (the
  `decals_writer` target rule). A round-trip test pins it: load → save is
  byte-identical.

## 8. Editor *(accepted 2026-10-09)*

- **A CEF panel in the `cp-*` modal family**, developer-only, tagged
  `data-panel` so text fields capture the keyboard automatically. It is
  docked to one side, so the 3D view stays clickable (§4).
- **Panes:**
  - *Selection*: the identity readout (§4), plus the shape's parent group
    (`Red On GlowAlpha` and so on), shown as information only.
  - *Material*: roughness and metalness sliders (0–1, source B of §9.2),
    each showing which source currently wins (map / override / default).
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

## 9. Bridge PBR *(accepted 2026-10-09)*

Cook-Torrance GGX on the bridge pass, ported from `origin/feat/pbr-ship-spike`
(56575bb4) minus its spike shortcuts and its `_specular`-map multiplier
(§2.2). §9.1–9.6 record each decision.

### 9.1 Linear lighting — a deliberate tone shift

`bridge.frag` today lights the raw (gamma-space) texture values. GGX needs
linear albedo (`pow(base, 2.2)`, as the July spike did), so PBR shifts the
whole bridge's tone before any roughness or metal comes in. The downlight's
`down_top` / `down_bottom` and the ×1.5 green ambient are re-calibrated live
in a dedicated iteration.

### 9.2 Material sources — layered, per channel *(Mark, 2026-10-09)*

Roughness and metalness are each resolved independently, first hit wins:

| Order | Source | Detail |
|---|---|---|
| A | Maps found by the albedo's filename | `<albedo stem>_rough.tga` / `<albedo stem>_metal.tga`. Where they are looked up depends on where the ALBEDO resolved (below). |
| B | Per-shape override, a 0–1 float each | Picker-set; the shape's `material` section of the bridge file (§7). |
| C | Default | metalness 0, roughness 1 |

The NIF's own gloss/specular values are NOT a source.

**Where maps are looked up (Mark, 2026-10-09):**
- **Stock albedo** (resolved under `paths.game_root()`): maps come from
  our replacements overlay — project-authored additions for stock content.
- **Mod albedo** (resolved from a mod) — *future*: maps only beside that
  albedo in the mod, never from our overlay, even when the mod's texture
  shares a stock filename (`Map 3.tga`). Our maps never land on a mod's
  different texture. Same guard as the rock catalogue's redirect.

**Known trade-off:** a map always beats an override, so once a shared
texture (DBridge texture 7, 22 shapes) gets a `_rough` map, no single shape
using it can opt out. Accepted; flipping A and B for one shape is a one-line
change if it ever bites.

### 9.3 Normal maps *(Mark, 2026-10-09: "yes absolutely")*

`<albedo stem>_normal.tga`, the same name lookup and stock/mod rule as
§9.2. Only source A applies — no per-shape override, no default: no map
means a flat surface (the generated normal). Tangent frame from
screen-space derivatives (the July spike's `pbr_perturb_normal`), so meshes
need no tangent data.

### 9.4 Reflections — per-alert base probes + animation layers *(Mark, 2026-10-09)*

Reflected light is the sum of each source's contribution, so the
environment is split into layers and summed in the shader:

- **Base probes: two — `green` and `yellow/red`** (Mark: yellow and red
  will be extremely similar or the same). The `yellow/red` probe is
  captured at yellow; **anything whose look differs between yellow and red
  goes into a layer instead** (e.g. a fixture steadily lit only at red), so
  yellow↔red never cross-fades probes — only layers change. Each is a
  cubemap from the captain's chair **excluding animated emitters** (an emitter is animated in a state if its wave there is not
  `steady`). Steady emitters are baked in. Pre-filtered mips by roughness
  (split-sum IBL + a BRDF lookup table); **box-projected** against the
  bridge AABB so reflections sit where the reflected thing really is. An
  alert change cross-fades between two base probes over the profile
  `fade_s`.
- **Animation layers (emitter step, later).** One probe per animation group,
  capturing the room lit by ONLY that group's glow + cast light (everything
  else black), added in the shader × the group's live wave value — so a red
  alert bar's floor reflection blinks with the bar. Group = emitters that
  vary in lockstep: **same profile and same phase** (§6.3).
- **Cost:** a 256² RGBA16F cube with mips ≈ 4 MB; captures happen at load or
  on a data change only, never per frame.
- **In the PBR step** (no emitters yet): build the capture machinery and
  the two base probes (they differ only in ambient at first); the emitter
  step adds exclusions and layers.

### 9.5 Bloom — specular uncapped *(Mark, 2026-10-09)*

Diffuse keeps the 0.88 ceiling; **specular is uncapped**. In practice only
emitter reflections (the probe holds a lit room capped at 0.88, so only
emitters in it exceed the threshold) and spot-light highlights can bloom.
§1's invariant now reads: **lit diffuse never blooms; emitters and their
reflections/highlights may.**

### 9.6 Shading assembly *(accepted 2026-10-09)*

**Why bridges suit PBR (Mark):** stock bridges author no specular, gloss or
normal maps (§2.2) and their lightmaps are already gone, so PBR loses
nothing BC had. Every added map is pure gain.

- **Diffuse** = `albedo × (1 − metal) × (1 − F) × downlight irradiance × AO`,
  then the 0.88 diffuse ceiling. `F` here is the **roughness-aware** Schlick
  (`F_schlick_rough`, Lagarde): plain Schlick at NdotV darkened the default
  rough dielectric by up to ~1/3 at grazing views (final review, 2026-10-09);
  at rough 1 a dielectric now loses F0 at every angle. The hemisphere downlight becomes the
  diffuse ambient term; its shape stays, its constants are re-calibrated for
  linear lighting (§9.1).
- **Specular** = `probe(R, roughness) × (F0·A + B) × specular occlusion`,
  uncapped (§9.5). The probe is box-projected, with the mip chosen by
  roughness; A and B come from the BRDF lookup table; specular occlusion is
  derived from AO (Lagarde) so creases don't shine.
- **Spot lights** (§6.2) add GGX specular + Lambert diffuse; no AO.
- **Probe capture content:** the bridge drawn with the **diffuse-only**
  path in linear HDR (no reflections of reflections). **Excluded:**
  officers (they move; they'd be baked in where they stood) and the
  viewscreen (live feed; captured black). *Candidate for later:* a
  viewscreen reflection layer (low-res probe updated a few times a second).
  **When:** at bridge load and when the editor changes material or emitter
  data — never per frame. Capture point: the captain's-chair eye. Box: the
  bridge model's AABB.
- **Officers** go through the same path with the defaults (metal 0,
  rough 1): matte, with a slight Fresnel edge. Their textures can gain maps
  by the same naming rule.
- **Static spot lights in the PBR step:** picker-placed §6.2 lights. An
  emitter with no `profile` uses a built-in steady white profile (level 1 in
  every state), so the schema doesn't change between the PBR step and the
  emitter step.
- **Developer tools (Developer Options → Lighting):** a PBR on/off A/B
  switch, **for the spike only** — removed once PBR is accepted (the
  baseline deleted the old look rather than keeping an option); new debug
  views: roughness, metalness, specular only, probe only (mirror sphere),
  normal-map normals.
- **Testing:** CPU twins pin the GGX terms, box projection and spot falloff;
  unit tests for map resolution (stock → overlay, mod → beside the mod
  albedo, per channel, A→B→C); a GL frame test proving diffuse stays
  ≤ 0.88 while a specular highlight can exceed it; schema round-trip; the
  gate (`scripts/check_tests.sh`) green with no new ledger entries.

### 9.7 As built: emissive sibling maps *(Mark approved 2026-10-09, task 17)*

A texture-level emission default, loaded by filename like the §9.2 maps.
It is NOT the §6 emitter and does not replace it.

- **Convention:** beside the albedo, `<stem>_emissive.<ext>` (default,
  green), `<stem>_emissive_y.<ext>` (yellow alert), `<stem>_emissive_r.<ext>`
  (red alert); `<stem>` built by `sibling_map_filename` (trailing `_glow`
  stripped, extension kept). RGB = emitted colour, alpha ignored, sampled
  with the base UV. Stage slots `Emissive` / `EmissiveYellow` /
  `EmissiveRed`. Same look-up policy as §9.2 (stock albedo → overlay only;
  mod albedo → beside itself), and **interior loads only** — ship loads never
  probe them. An `_emissive*` file is a derived map: never probed for
  siblings itself, and refused as a mesh-fix / shape-diff albedo
  (`check_albedo_name`, `_RESERVED_SUFFIXES`).
- **Alert selection** *(red's fallback amended by §11.1: `_r`, else `_y`, else default)* (`renderer::bridge_emissive_texture`): yellow →
  `_emissive_y` else `_emissive`; red → `_emissive_r` else `_emissive`;
  green and any unknown level → `_emissive`. A hard switch, no fade.
  `host_loop` pushes `set_bridge_alert_level(GetAlertLevel())` every frame
  beside the ambient scale (no player → green). Main bridge view only: a
  comm set always shows the default.
- **Colour space:** the emissive texel is added UNCONVERTED, in display
  (gamma) space — the space both bridge shading paths output and the HDR
  target holds (RGBA8 textures, no sRGB decode on upload, no encode in
  resolve). Do not add an sRGB→linear decode on the sample: the result is
  never re-encoded, so a 0.5 texel would display as 0.218. Consequence:
  over a lit, mid-bright albedo the glow reads brighter than a
  linear-correct add; over dark albedo (the usual authoring) it is exact.
- **Shading:** `emissive = texture(u_emissive_map, uv).rgb × kEmissiveScale`
  (1.0, `bridge_lighting_tuning.h`, rebuild to tune), added AFTER the
  diffuse ceiling on both the PBR and the legacy path, so it can exceed
  bloom's 0.9 and glow. Purely additive: unlike §6.1 it does NOT reduce the
  texel's received light. Texture unit 10.
- **Probes exclude it.** The capture branch returns before the emissive
  term. Simplest correct choice: emission is per alert while the
  yellow/red probe is shared by two alerts, and a green-emission probe would
  reflect green panels at red alert; excluding it also means an alert change
  never needs a recapture. Cost: reflections show no glowing panels.
- **Debug views show none** (all of 1–10, including "light only", which is
  received light). No new view.
- **Flipbooks:** a flipbook base's emissive comes from its frame-0 stem and
  is static — no per-frame emissive.
- **Coexistence with the §6 emitter `map` mask:** the sibling is the
  texture-level default (every shape drawing that texture glows — so put
  emission on a texture only one surface uses, e.g. a mesh-fix-spliced
  albedo like `Map 22a.tga`); the emitter `map` is per-shape and comes
  later, with profiles, level and the received-light dip.
- **DBridge as shipped:** `Map 22a` has all three; `g_imp_redbars` and
  `g_imp_connops` the default only (files renamed to the convention).

## 10. Iteration log

| # | Date | Change | Verdict | Sections |
|---|------|--------|---------|----------|
| — | 2026-10-08 | Spec created; evidence recorded | — | 1, 2 |
| — | 2026-10-09 | Approach A + WASDQE fly camera chosen; camera & selection design | accepted | 3, 4 |
| — | 2026-10-09 | Programme order (PBR first); emitter model documented assuming PBR; persistence + editor drafted | §5–6 documented; §7–8 draft | 5, 6, 7, 8, 9 |
| — | 2026-10-09 | Persistence + editor accepted | accepted | 7, 8 |
| — | 2026-10-09 | PBR: linear-lighting tone shift noted; material sources layered (maps by albedo name → per-shape 0-1 override → metal 0 / rough 1) | accepted | 9 |
| — | 2026-10-09 | PBR: overlay maps only for stock albedo; mod maps beside the mod albedo (future) | accepted | 9.2 |
| — | 2026-10-09 | PBR: normal maps by albedo name; per-alert base probes excluding animated emitters + later per-animation-group probe layers | accepted | 9.3, 9.4 |
| — | 2026-10-09 | PBR: base probes reduced to green + yellow/red; yellow-vs-red differences become layers | accepted | 9.4 |
| — | 2026-10-09 | PBR: specular uncapped, diffuse keeps ceiling | accepted | 9.5 |
| — | 2026-10-09 | Measured: stock bridges have no spec/gloss/normal maps; spike spec-mask not ported | recorded | 2.2 |
| — | 2026-10-09 | PBR shading assembly accepted; §9 complete | accepted | 9.6 |
| — | 2026-10-09 | Self-review: stale cross-refs fixed; `material` schema defined; foundation + PBR planned as two plans | — | 1, 4, 5, 6, 7, 8, 9 |
| P1 | 2026-10-09 | Bridge PBR built (plan 2026-10-09-bridge-pbr): linear GGX, layered material channels, normal/rough/metal maps, two box-projected probes, spot lights, live editor push | live-verified (Mark, 2026-10-09: "looks pretty good! I can't see any issues"); DBridge + EBridge material overrides authored live | 9 |
| — | 2026-10-09 | Plan-time corrections: dev panels keep the pause menu open-but-hidden; loader rejects unknown keys (writer no longer "keeps" them); mod lookup path named | — | 4, 7 |
| F1 | 2026-10-09 | Foundation built: fly camera, pick + identity, selection tint, lighting doc + writer, panel (plan 2026-10-09-bridge-editor-foundation) | live-verified (Mark, 2026-10-09: "works!") | 4, 7, 8 |
| E1 | 2026-10-09 | Emissive sibling maps `_emissive{,_y,_r}` (task 17): interior loads, per-alert variant, after the diffuse ceiling, probes exclude | built; live-verified by Mark 2026-10-10 (green/yellow/red on DBridge) | 6.1, 9.7 |
| G0 | 2026-10-10 | Emitter glow slice 1 designed: maps = where, profiles = how; `src` emissive/texture/flat; red falls back to yellow; light colour = evaluated^2.2; probe capture colours split from live colours | agreed with Mark | 9.7, 11 |
| G1 | 2026-10-10 | Glow slice 1 built (plan 2026-10-10-bridge-emitter-glow-slice-1): per-mesh glow + dip, profiles/waves/fades, spot capture vs live colours, DBridge alcove + roof data | built; live-verified by Mark 2026-10-11 ("works as described") | 11 |
| G2 | 2026-10-11 | Editor panes designed (§12): glow + profile panes, state tabs double as the alert preview, preview clock, shared colour wheel | agreed with Mark | 12 |
| G3 | 2026-10-11 | Editor panes built (plan 2026-10-11-bridge-editor-glow-panes) | built; awaiting Mark's live check | 12 |
| G4 | 2026-10-11 | Slice 3 designed (§13): Object/Material tabs over a shared material library of scoped Emitter/Animation modifiers (phase in Animation), five states (offline/special), editor bar chrome, Shift-fly | approved by Mark 2026-10-11 (incl. Shift-fly and offline-dark) | 13 |
| G5 | 2026-10-11 | Slice 3 built (plan 2026-10-11-bridge-materials-slice-3) | built; awaiting Mark's live check | 13 |
| G6 | 2026-10-12 | Emission is a Finish row; Emitter -> State override; strength and fade_s removed; Transition modifier (0.5 s default); `format: 3` | designed with Mark 2026-10-12; built | 14 |
| G7 | 2026-10-12 | Room light: a bridge with its own lights is lit by them (room light 0 unless set per state); Bridge Settings cog; reflections captured under it | designed with Mark 2026-10-12; built | 15 |

## 11. Emitter glow — slice 1 *(agreed with Mark 2026-10-10)*

The first build step of §6. It amends §6/§7/§9.7 where it says so; everything
else in §6 stands.

### 11.1 The rule: maps say WHERE, profiles say HOW

- **Maps** decide which texels glow and their colour detail (an `_emissive`
  map, or the albedo itself). Pixels never change over time.
- **Profiles** decide the colour, brightness and motion per alert state:
  `tint`, `level`, `wave`, and the `fade_s` between states (§6.3). One profile
  drives the glow AND the shape's cast light, so they match by construction.
- **`_emissive_y` / `_emissive_r` stay**, but only for alerts where the
  PATTERN changes (measured: Map 22a's green map lights only the middle block;
  its yellow map lights the whole strip; its red map is the yellow one × about
  (1.05, 0.08, 0.19) -- a tint). The profile multiplies whichever map is chosen.
- **Fallback amended (§9.7):** red → `_emissive_r`, else `_emissive_y`, else
  `_emissive` (it skipped yellow before). Matches the green vs yellow/red probe
  pairing (§9.4). No shipped data changes: nothing has `_y` without `_r`.
- Why not maps alone: a light has no pixels, so its alert colours live in JSON
  anyway; pulses as maps are flipbooks; reflections are linear in the source,
  so pattern × scalar lets one capture serve every alert and every pulse
  (§9.4 layers); an 8-bit map stops at 1.0, just over bloom's 0.9, so
  brightness needs a per-shape level regardless.

### 11.2 Glow, per shape

`glow = src(uv) × tint(t) × level(t) × scale`, added after the diffuse ceiling
in display space exactly like §9.7's term (so it can bloom). `emitter.glow`:

| field | values | meaning |
|---|---|---|
| `src` | `emissive` | the albedo's `_emissive` sibling for the CURRENT alert (fallback above). Refused at load, naming the shape, if the albedo has no `_emissive` sibling |
| | `texture` | the albedo's current texel -- the current flipbook frame, so an animated LCARS glows its frame (lifts §9.7's "emissive on a flipbook is static" for this source) |
| | `flat` | 1 (DBridge alert bars are textured black) |
| `scale` | ≥ 0, default 1 | per-shape multiplier on top of the profile |

- **Per shape, never per texture.** The alcove roofs (b0401/423/441/455) draw
  `Map 19.tga`, a 32×32 swatch shared by 22 shapes; `src: texture` on just
  those four lights only them.
- **A shape with a glow replaces its texture-level default.** Shapes without
  `emitter.glow` keep §9.7 unchanged (sibling map × `kEmissiveScale`).
- **Received-light dip (§6.1):** received light (diffuse and specular) ×
  `(1 − m × clamp(level·wave, 0, 1))`, where `m` = 1 for `texture`/`flat` and
  the emissive texel's max channel for `emissive` (so a map's black ribs stay
  ordinary receivers). At level 0 the shape is an ordinary surface.
- **Amends §6.1/§7:** `mask` and its `luma_*` / `map` fields are dropped from
  the schema for now -- `src: emissive` replaces the per-shape `map` mask, and
  `base_alpha` / `luma` come back when a shape needs them. Unknown keys are
  still rejected.
- **No profile** = the built-in steady white profile (level 1 in every state),
  as §9.6 already says for lights.

### 11.3 Profiles, clock, fades

As §6.3, built now: states `{tint, level, wave}`, a missing state = off;
waves `steady | sine | square` with `period_s`, `min`, `duty`, `soft`; `phase`
per emitter; **one bridge clock** = game time accumulated from the player dt
(frozen under pause; the editor's preview clock is a later slice). An alert
change cross-fades from the live output of the old state to the new over the
profile's `fade_s` (default 0.5 s). Evaluated in Python each frame as pure
functions (unit-tested without GL) and pushed as one small per-shape array:
`(mesh, src, rgb)` where `rgb = tint × level × wave × scale` after the fade.

### 11.4 Cast light follows the profile

- A shape's `emitter.light` takes its colour from the same evaluated value.
- **Colour space:** glow is added in display space, spots light in linear
  (§9.1). Spot colour = `(evaluated rgb)^2.2` per channel × `light_scale`; a
  tint converts exactly (multiplying commutes with the curve), brightness goes
  through it. `intensity` is unchanged. Spots with no profile stay white.
- **Probes never recapture per frame (~14 ms for both).** The spot list splits:
  `set_bridge_spots` carries geometry plus each spot's CAPTURE colour for the
  green probe and for the yellow/red probe (its steady state colour; 0 when
  its wave there is not `steady`) and still dirties the probes on change. A
  new per-frame `set_bridge_spot_colours` carries the live colours and never
  dirties them. So a pulsing or fading spot lights the room live, and its
  reflection is absent until §9.4's animation layers.
- Glow stays out of the probes (§9.7, unchanged).

### 11.5 Slice 1 scope

In: §11.1 fallback; §11.2 glow (`emissive` / `texture` / `flat`, `scale`,
dip); §11.3 profiles, waves, phase, clock, fades; §11.4 light colour + probe
split; schema + loader + writer round-trip. Authored **by hand** in the
DBridge file; the editor's Revert reloads it.

Out (next slices): editor panes (glow, profile, alert preview switch, preview
clock); `base_alpha` / `luma` masks; probe animation layers; light occlusion.

**Test cases (DBridge):**
- *Alcoves* -- roofs b0401/423/441/455, `src: texture`, profile `alcove`:
  green white, yellow off, red a dim red sine pulse; one downward spot per
  alcove on the same profile, so the floor goes white → dark → pulsing red
  with the roof.
- *Roof* -- b0076/81/84/87/90 on Mark's `Map 5` / `Map 13` emissive maps,
  `src: emissive`, profile `roof`: glowing in every state, dimmer at yellow
  and red; Mark's existing spot on b0081 joins the profile.

Numbers are Mark's to tune live.

## 12. Editor panes for glow and profiles — slice 2 *(agreed with Mark 2026-10-11)*

Fills in §8's Emitter / Profile / Preview panes for the §11 model. Slice 1
(§11) is live-verified; until this lands, profiles are hand-edited JSON.

### 12.1 Layout (the dock, under Light; selected shape only)

- **Glow** -- on/off; source `emissive` / `texture` / `flat` (`emissive`
  disabled, with the reason shown, when the shape's material has no
  `_emissive` sibling -- `model_identity` `maps.emissive`); `scale`.
- **Profile** -- dropdown of the bridge's profiles plus "none (steady
  white)"; **New** (a copy of the current profile, or steady white from
  none, named `profile N`); **Rename** (a text field; every shape using the
  profile follows); "used by N shapes", because a shared profile changes
  every shape on it. No delete in this slice: an unused profile stays in the
  file, shown "used by 0".
- **Green | Yellow | Red tabs**, one state at a time (the dock is 360 px):
  - on/off (a missing state is off, §6.3);
  - **colour**: a hue/saturation wheel with V = 1, so `tint` always has a
    max channel of 1 and brightness lives only in `level`. Editing a tint
    authored with a lower max channel replaces it;
  - **level**: slider 0–4 plus a number field (any value ≥ 0);
  - **pulse**: `steady` / `sine` / `square`; `period_s` (≥ 0.05), `min`
    (0–1) for sine and square; `duty`, `soft` (0–1) for square only.
- Profile `fade_s` and the shape's `phase` (0–1) under the tabs.

### 12.2 Preview

- **The selected tab IS the preview alert.** Choosing Yellow shows the
  bridge at yellow: emissive map variant, probe mix, alert ambient, glows
  and lights -- everything that reads the alert level takes the editor's
  value while the editor is open. The ship's real alert is never changed
  (§4). Switching tabs fades over the profile's `fade_s`, so the fade is
  previewed too. Closing the editor returns to the player's alert (with a
  fade).
- **Preview clock.** While the editor is open the bridge clock runs on the
  real frame time (the sim is paused, so the player dt is 0), with a
  play/pause toggle in the panel. Closing returns to the paused-aware dt.

### 12.3 Editing rules

- Every control is one undoable action (§8 snapshot stack), pushed live;
  Save / Revert / Undo cover the new fields. Values are clamped to the
  schema's ranges before they enter the document, so Save can never be
  refused by validation for a value the panel produced.
- The colour wheel commits on pointer release (one undo step per drag),
  showing its swatch live while dragging.
- Turning Glow off removes `emitter.glow`; an emitter left with nothing is
  removed (as Light's Remove already does).

### 12.4 The colour wheel is shared

The SPV's hue/saturation wheel (`ship_property_viewer.js`: HSV→RGB at V = 1,
its inverse, the cached disc, pointer handling) moves to a shared
`js/colour_wheel.js` that both panels use. The SPV's behaviour is unchanged.
CEF OSR shows no native colour-picker popup, so a canvas wheel is the
working control.

### 12.5 Out of scope

Pipette (copy an emitter between shapes), gizmos, colour-to-colour pulses,
deleting profiles, a preview-clock speed control.

## 13. Material library, Object / Material tabs, five bridge states, editor chrome — slice 3 *(designed with Mark 2026-10-11; supersedes §11's per-shape profile model and §12's panes)*

Slice 2 (§12) proved the per-alert idea but crowded the dock. This slice
reorganises the editor the Blender way -- **objects link to materials from a
shared library** -- and widens the bridge states to five. The renderer
contract (§11.2 per-mesh glow, §11.4 spot capture vs live colour) is
unchanged apart from the new states. "Shape" becomes **object** in the editor.

### 13.1 Five bridge states

| State | Square | In game | Room ambient | Emissive sibling |
|---|---|---|---|---|
| `offline` | ⬛ | the player ship's `PowerSubsystem` disabled or destroyed; overrides every other state while it lasts | dimmed (a new value in `bridge_lighting`, below yellow/red) | none: **texture-level `_emissive` maps go dark** on objects whose material does not light them |
| `green` | 🟩 | alert 0 | as today | `_emissive` |
| `yellow` | 🟨 | alert 1 | as today | `_emissive_y` → `_emissive` |
| `red` | 🟥 | alert 2 | as today | `_emissive_r` → `_emissive_y` → `_emissive` |
| `special` | 🟦 | a generic hook (`set_special_alert(on)`), no in-game caller yet -- e.g. a future multi-vector assault "blue alert". Overrides green/yellow/red, not offline | as red | `_emissive_s` → `_emissive` |

Reflection probes for `offline` / `special` are a later phase; until then
they use the yellow/red probe.

### 13.2 Objects and the material library

- An **object** is one NIF shape (identity unchanged, §4).
- The bridge file holds a **material library**: named materials. An object
  links to at most one. Editing a material changes every object using it
  ("used by N objects"); **Duplicate** gives the object its own copy to
  diverge.
- **Each TGA is a material** (Mark, 2026-10-11): `textures` maps a texture
  (case-folded file name) to a material, named after it (`Map 13`). An
  object with **no link uses its texture's material**, so editing one wall
  panel's roughness changes every panel with that TGA. A link **replaces**
  the texture's material (no layering) -- that is how 4 of the 22
  `Map 19.tga` shapes are the alcove: select one, Duplicate (`Map 19 copy`),
  rename it, link the other three. **Unlink** returns an object to its
  texture's material (the chip names it, "texture · Map 19"). The texture's
  material is made empty on its first edit; an object with no texture gets
  a new linked material instead. One resolver (`lighting_doc.resolve`:
  link, else texture) feeds the overrides, glow and lights.
  *(Replaces per-object finish materials: identical TGAs showed up as
  unrelated `material N` entries. The committed DBridge/EBridge files were
  folded once (`fold_into_textures`, with the real built textures): per
  texture the most common finish -- equal to 0.05 counts as one -- became
  the texture's material, a tie going to the finish nearest the default so
  the unlinked meshes that adopt it change least; each object that differs
  kept a `<texture> 2`... link.)*
- **A material belongs to one texture** (Mark, 2026-10-11: "the TGA is
  part of the material"): it records `texture` (the case-folded file name),
  the library offers only the selected object's texture's materials, and a
  link counts only on an object of that texture (`lighting_doc.fits`; a
  hand-edited mismatch is ignored with a warning). The albedo still comes
  from the NIF and the mesh fixes, and `_rough` / `_metal` / `_normal` /
  `_emissive` maps are still found by texture name (§9.2, §9.7). Two
  textures pulsing together use two materials with the same settings --
  one bridge clock keeps them in step. *(The first build let one material
  span textures; DBridge's `roof` (Map 5 rear ribs + Map 13 front rib) was
  split by `bind_textures`: the texture with most users kept the name, the
  other got `roof (Map 13)`.)*

**A material holds** (Material tab):
- **Finish**: `roughness`, `metalness` (0-1 each, optional). A texture map
  still beats the material's value per channel (§9.2).
- **Emission** -- what glows, following the roughness/metalness rule (Mark,
  2026-10-11): the object's `_emissive` map whenever its texture has one
  (the variant for the current state, §13.1; shown in the editor, not
  chosen); `without_map` -- `texture` (its own texture, default) or `flat`
  -- for objects that have none; plus `strength` (≥ 0, default 1; 0 = no
  glow while the lights still follow the emitters). Since a material has
  one texture, the editor shows the map as the source when there is one and
  offers the own texture / flat choice only when there is not.
  *(Replaces the first build's "Surface" with auto / emission map / own
  texture / flat / none: confusing beside Finish, and the map choice was
  inconsistent with roughness/metalness.)*
- **fade_s**: the cross-fade on a state change (default 0.5).
- **Modifiers**, each with a **scope** -- any of the five states; none
  ticked = parked:
  - **Emitter** (any number): colour (wheel, V = 1) and level. Emitters
    active in a state ADD.
  - **Animation** (any number): `sine` / `square`, `period_s`, `min`,
    `duty`, `soft`, and **`phase`** (0-1). Animations active in a state
    MULTIPLY the emitters' sum.

Output in state *s* = (Σ emitters scoped to *s*) × (Π animations scoped to
*s*), cross-faded over `fade_s` on a state change; glow = emission
source × output × strength. Examples: alcove = Emitter white [green] + Emitter red 0.5
[red] + Animation sine 2 s [red]; red bars = Emitter red [red] + Animation
sine 2 s [red]; reserve power = Emitter red [offline].

**An object holds** (Object tab):
- its **material** link;
- **Lights** (any number): position, aim, cone, range, intensity -- placed
  per object; their colour follows the material's output, ^2.2 (§11.4).

No per-object phase: objects on one material pulse in lockstep. A staggered
"chase" needs a duplicated material with a different phase (accepted, Mark
2026-10-11; a per-object offset can be added if it ever bites).

**No material**: roughness 1 / metalness 0, the texture's emission map
steady (dark at `offline`), no lights unless the object adds them (white,
steady).

### 13.3 Editor chrome

- **The bar** (top left; its presence IS bridge editing mode):
  `BRIDGE EDITOR | ⬛ 🟩 🟨 🟥 🟦 | ▶/⏸ | Undo · Revert · Save | ✕`. The squares
  set the preview state (everything state-dependent shows it; the game is
  never changed, §12.2). ▶/⏸ is the preview clock. ✕ leaves the editor. One
  hint line under it: `Hold Shift: fly · WASD · Q/E · scroll: speed · click:
  select · Alt+click: surface behind · materials layer over the object's
  texture`.
- **Fly controls**: hold
  **Shift** (not RMB) to fly with mouse-look; the scroll wheel sets the fly
  speed; Alt-slow goes; RMB is freed.
- **The side panel shows only while an object is selected** (clicking empty
  space deselects and hides it), with two tabs:
  - **Object** -- the selection readout; the material picker (library list
    with "used by N", New, Duplicate, Unlink); the Light stack with
    **Add light**. With no material and a texture-level emission map, a
    read-only row: "Emission map · <name> · steady".
  - **Material** -- name (Rename), Finish, Emission (source, strength, state fade), then the modifier
    stack with **Add modifier** (Emitter, Animation). Every stack entry is a
    header row (name, scope squares, ×) that expands on click.
- Every choice is a chip row or an in-page menu, never a `<select>` (§12).

### 13.4 Data (`format: 2`)

```json
{"format": 2, "source": "...",
 "materials": {"alcove": {"texture": "map 19.tga", "roughness": 0,
   "emission": {"without_map": "texture", "strength": 1},
   "fade_s": 0.5,
   "modifiers": [{"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
                 {"type": "emitter", "scope": ["red"], "tint": [1, 0.12, 0.08], "level": 0.5},
                 {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2,
                  "min": 0.2, "phase": 0}]},
   "Map 13": {"texture": "map 13.tga", "roughness": 0.3}},
 "textures": {"map 13.tga": "Map 13"},
 "objects": {"401:": {"block": 401, "name": "", "material": "alcove",
   "lights": [{"position": [157, -135, 105], "direction": [0, 0, -1], "inner_deg": 45,
               "outer_deg": 85, "range": 150, "intensity": 8000}]}}}
```

Unknown keys REJECTED (as §7). **Reading `format: 1`** converts: each
shape's material overrides + glow source/scale + profile (+ its phase) form a
signature; profiled shapes with identical signatures share one material,
named after the profile (`<profile> 2` on a clash). Every other shape gets
its own `material N`, never merged: equal finish values are a coincidence,
not a choice to share, and merging them put 32 unrelated DBridge objects in
one material (Mark, 2026-10-11). Profile states become scoped
modifiers (a state's wave becomes an Animation scoped to that state); the
light becomes `lights[0]`. The writer saves `format: 2`; the DBridge file is
converted and committed.

### 13.5 Out of scope

Reflection probes for the new states; per-object phase offsets;
multi-select; colour-to-colour animation; per-emitter "throws light"
switches.

## 14. Emission as a Finish row; State, Animation, Transition *(designed with Mark 2026-10-12; supersedes §13.2's Emission section and Emitter modifier)*

Why: Mark set Emission strength 3 on the Map 8 com lights and nothing
glowed -- a material only glowed with an Emitter modifier, and Emission's
strength and fade only acted on Emitters. Glow was split across two places
and neither worked alone. Mark: "emission level COULD form part of Finish,
which is a mandatory / non-removable modifier ... roughness and metalness
already handle default vs map vs material really well."

- **Finish = roughness, metalness, emission.** Emission is a level: steady
  white x the source, in every state but Power offline (dark, as an
  `_emissive` map is). Sources, as the other rows: **default** 0 without a
  map; **map** 1 (the map as painted) when the texture has `_emissive`;
  **material** once set. Unlike roughness/metalness the level stays
  editable over a map -- the map says what glows, the level how much.
  Slider 0-4, the box to 16.
- **What glows** without a map: `emission_source` own texture (default) or
  flat, as chips under the row, shown only when there is no map. *(Mark:
  "not 100% sure ... happy to see it and tweak.")*
- **State** modifier (was Emitter): in its ticked states it REPLACES the
  emission (colour wheel + level; several add). Not "Emitter": it emits no
  light -- lights are object-level (§13.2) and follow the result.
- **Animation**: multiplies, unchanged.
- **Transition** modifier: the blend time INTO its ticked states (0 = an
  instant cut). With none, a state change blends over **0.5 s** -- Mark
  kept the flat default, not "absent = instant".
- **Strength is gone** (redundant with the State levels) and so is
  `fade_s`.
- A material sets a glow (is in the glow table) when it has an emission
  level, a State or an Animation (`behaviour.drives_glow`); otherwise the
  texture default stands. A light on a material that sets no glow stays
  steady white.

**Data `format: 3`.** Material keys: `texture`, `roughness`, `metalness`,
`emission` (number >= 0), `emission_source`, `modifiers` (`state`,
`animation`, `transition {scope, seconds}`). Formats 1 and 2 upgrade on load
with every state looking the same: emitters become States with the old
strength folded into their levels and base emission 0 (a state no emitter
covered was dark); `without_map` becomes `emission_source`; a fade other
than 0.5 s becomes a Transition on every state; strength or fade on a
material with no emitters did nothing and is dropped. Lossy only for a v1
profiled light with no glow (strength 0): its light follows levels of 0.
Committed files stay `format: 2` until next saved from the editor.



## 15. Room light and Bridge Settings *(designed with Mark 2026-10-12)*

Why: the alcoves' normal maps showed no relief under their red pulsing
lights. Measured (shader formulas, a wall 60 units from the cove light): the
room light (the bridge ambient, white, x1.0 at red) put ~0.09 linear on the
wall against the red spot's ~0.03 at its pulse peak (level 0.5 -> 22% after
^2.2), so relief from the normal map was ~3/255. With the room light zeroed
(a launch-time experiment) the relief showed at once -- Mark: "the normal
rendering was being overpowered by the base illumination".

- **Room light** = the bridge ambient's multiplier, per state.
  `lighting_doc.room_light(doc, state)`: the bridge's own `room_light`
  level when set; else **0 when the bridge defines lights of its own**
  (any object with `lights`); else the engine default
  (`bridge_lighting._ALERT_AMBIENT_SCALE`: green 1.5, yellow/red 1.0,
  offline 0.4) -- unchanged for every bridge with no lighting file or no
  lights. `bridge_lighting.bridge_ambient_scale(player, preview, room)` picks
  it for the editor's preview state, else the player's (green with no
  player, so a mission swap never flashes a lit bridge to the default).
- **Reflections follow it**: the green probe is captured under the green
  room light, the yellow/red probe under yellow's (as the spot capture
  colours are), through the existing `set_bridge_probe_scales`; the runtime
  recaptures only when they change. The comm viewscreen feed keeps its own
  constant lighting.
- **Data**: optional top-level `room_light: {state: level >= 0}` (editor
  0-4); unknown states rejected.
- **Editor**: a cog at the bottom right of the free view (left of the dock
  while it shows) opens **Bridge Settings** above it -- a slider + pencil
  row per state, `default`/`bridge` source and a × back to the default.
  Python owns open/closed for the click region (`COG_CSS_PX`,
  `SETTINGS_CSS_W/H` = the CSS). Bridge-level edits need no selection.

## 16. Lights with size: strips and panels *(designed with Mark 2026-10-12)*

Why: two asks with one cause. Mark wanted a **strip light** along an
object's top / bottom / left / right edge, with a start and end along it,
facing perpendicular to the edge and on average toward the object's centre.
Separately, lights on the ceiling dome read as downlights, not a wide wash.
The cone is not the limit (`outer_deg` is a half-angle, clamped to 90 = the
whole hemisphere already): a POINT source puts 1/d² and a high N·L straight
below it and grazes the walls. Both need a light with **size**. Mark: "which
is exactly why it seems related!" Strips and panels are one feature: a
rectangular area light, cut from the object's front rectangle.

Mark, on the whole section: "I have areas I'm not sure how well they will
work but I think we are best to proceed and find out." The judgement is live.

### 16.1 Data (`format: 4`)

A light gains `shape`; absent = `spot`. The reader rejects unknown keys, so
the new keys need a format bump; `format: 3` upgrades on load unchanged (it
holds only spots).

| `shape` | keys |
|---|---|
| `spot` | as §13.4: `position`, `direction`, `inner_deg`, `outer_deg`, `range`, `intensity` |
| `strip` | `edge` (`top` / `bottom` / `left` / `right`), `start`, `end` (0-1 along the edge, defaults 0 and 1, `start` <= `end`), `offset`, `range`, `intensity` |
| `panel` | `x`, `y` (each `[from, to]`, 0-1 across the front rectangle, default `[0, 1]`, from <= to), `offset`, `range`, `intensity` |

```json
"lights": [{"shape": "strip", "edge": "top", "start": 0.1, "end": 0.9,
            "offset": 1, "range": 150, "intensity": 4},
           {"shape": "panel", "x": [0, 1], "y": [0, 1], "offset": 0,
            "range": 400, "intensity": 1}]
```

- **No coordinates are stored** for a strip or panel: the rectangle is
  recomputed from the mesh at load (§16.2), so it follows mesh fixes and
  shape diffs. A later `follow: "rim"` (a strip along the real outline -- Mark
  expects a top edge of at most ~7 vertices) is an added key, not a break.
- **`intensity` is surface brightness** (radiance per unit area, before the
  colour): shortening a strip removes light, as covering part of an LED strip
  would, rather than concentrating it.
- **Colour follows the material** exactly as a spot's (§13.2, §11.4): the
  object's resolved material, `^2.2`, steady white when it sets no glow; the
  same static capture colours and per-frame live colours.

### 16.2 Geometry: the front rectangle

`engine/bridge_editor/light_shapes.py`, pure Python, no GL. Input from a new
host query `bridge_mesh_geometry(iid, mesh)`: the shape's world-space vertices
and its area-weighted normal sum (C++ owns the triangles).

- **Frame**: *facing* = the normalised normal sum -- each triangle's normal
  first turned toward the bridge eye (`light_shapes.oriented_normal_sum`;
  DBridge's walls carry a back-facing copy of every face, so raw winding
  cancels: final review 2026-10-12, 3 of 145 shapes fell to "no facing");
  *up* = room up (+Z) with
  its facing component removed, normalised; *right* = up x facing. The
  object's box in (right, up, facing) gives the **front rectangle**: the box
  face at max facing (toward the room). An alcove's front rectangle is its
  lip; a flat panel's is the panel.
- **Fallbacks**:
  - no facing (normal sum < 5% of the total area -- a closed shape such as a
    pillar): facing = the horizontal direction from the box centre to the
    bridge camera eye (`_BRIDGE_CAMERA_EYE`, passed in), so the front is the
    side the captain sees;
  - facing within 25° of vertical (a ceiling or floor piece): up = the
    horizontal direction from the eye to the box centre, so **top is the edge
    farther from the captain's chair**. A panel does not care.
- **Strip**: that edge of the front rectangle, cut to `[start, end]`, a thin
  rectangle (`STRIP_WIDTH` = 0.5 bridge units, an engine constant) moved out along facing by
  `offset`. Its normal = (box centre - strip centre) with the component along
  the edge removed, normalised: perpendicular to the edge, toward the centre
  on average. `offset` is what lets a strip on a FLAT panel light the panel
  itself -- at 0 its normal lies in the panel's plane and the panel receives
  only grazing light.
- **Panel**: the `x` x `y` sub-rectangle of the front rectangle, moved out
  along facing by `offset`, normal = facing.
- **Known approximation**: a panel on the dome is its rectangular footprint,
  so its corners emit where there is no dome. A disc shape is a small addition
  if that shows.

### 16.3 Renderer

- `BridgeAreaLight`: 4 corners, normal, range, live radiance, green and
  yellow/red capture colours; uploaded as `u_area_*` arrays beside the spots.
  **Spots and area lights share the 32-light budget**: `lights.py` caps the
  combined list in mesh order and warns per dropped light, as today.
- `bridge.frag accumulate_area_lights`:
  - **diffuse**: the horizon-clipped Lambert edge integral (Heitz), ported
    from the 2026-09-04 quad-area-light spike (`spike/ebridge-emissive-sh`:
    `clip_quad_to_horizon`, the quad form factor, and its C++ twin's test
    against numerical quadrature); exact for a rectangle;
  - **one-sided**: a receiver behind the rectangle's plane gets nothing;
  - **range**: the spot window (`spot_falloff`'s `w`), on the distance to
    the nearest point of the rectangle;
  - **specular**: GGX at a representative point (the reflection ray meets the
    rectangle's plane, clamped into it), energy-normalised for the light's
    size. The part most likely to need tuning; the upgrade is an LTC table.
- C++ twins in `bridge_pbr.h`, as the spot formulas.
- **Probes**: the capture pass adds the area lights' diffuse half exactly as
  the spots'; a geometry or parameter change recaptures, a pulse or state
  change does not (§11.4).
- `runtime.py` builds the area list from `light_shapes` at load and after
  every edit and pushes it through `host_io.set_bridge_area_lights` /
  `set_bridge_area_colours`. A bridge with no strips or panels uploads a count
  of 0: its frame is unchanged.

### 16.4 Editor

- **Add light** becomes a menu -- Spot, Strip, Panel -- like Add Modifier.
- **Strip** row: edge chips (Top, Bottom, Left, Right), start and end
  sliders, offset, range, intensity. **Panel** row: x from / to, y from / to,
  offset, range, intensity.
- One undo step per edit; an edit recomputes that object's rectangles.
- No outline is drawn: a strip is placed by the light it casts. Drawing the
  rectangle while its row is expanded is the add-on if that proves hard.

### 16.5 Tests

- `light_shapes` on synthetic meshes: a flat panel, a sloped console, an
  alcove shell, a closed box (no-facing fallback), a ceiling piece
  (near-vertical fallback): frame, front rectangle, each edge, spans, offset,
  normals.
- Format: 3 -> 4 upgrade; round trip; rejection of unknown keys, a bad edge,
  a span outside 0-1, from > to.
- The shared budget: spots + area lights cap at 32 together.
- C++: the form factor against quadrature (the spike's test, ported); with no
  area lights the frame is byte-identical.
- Live (Mark, DBridge): a strip on an alcove lip; a panel on the dome.

### 16.6 Out of scope

Disc or curved panels; an LTC specular table; shadows from area lights;
drawing the light rectangle in the editor. (Strips that follow the rim:
§16.8.)

### 16.7 As built

Built on `feat/bridge-area-lights` (plan
`docs/superpowers/plans/2026-10-12-bridge-area-lights.md`). **Not live-verified**
-- Mark's DBridge check (a strip on an alcove lip, a panel on the dome) is owed,
and the defaults (`STRIP_INTENSITY` 40, `PANEL_INTENSITY` 2, `STRIP_OFFSET` 1 in
`engine/bridge_editor/editing.py`) are first guesses to tune there.

### 16.8 Edge snap: strips on the edge you click *(designed with Mark 2026-10-12)*

Why: the first live check put a strip on DBridge's Map 3 above the alcove,
not in it. Map 3 is one mesh per side wall (blocks 652 / 663: 578 triangles,
y -185 to 94, z 0 to 107) holding three alcoves, the cabinets and the door
frame, so its front rectangle is the whole wall and no box edge, start / end
or offset reaches the alcove lip. Compound meshes like it are the rule on the
bridge sets. A spike (`spike/strip-edge-snap`) snapped a strip to the mesh's
own edge nearest a click; Mark: "looks much better" -- once a highlight
doubling at the joints was fixed (below).

- **Data** (still `format: 4`, unshipped): a strip may carry `anchor`
  (`[x, y, z]`, the clicked point, bridge space like a spot's `position`).
  With it the strip sits on the sharp edge nearest the anchor, recomputed
  from the mesh at load; `edge` stays required and is the fallback when no
  edge is in reach (status line says so). `start`, `end`, `offset` apply to
  both.
- **Snap** (`engine/bridge_editor/edge_snap.py`, pure Python), constants in
  one block:
  - weld vertices at 0.01 units; drop degenerate and duplicate triangles
    (the back-facing copies); orient each normal toward the eye;
  - sharp edges: open edges, and edges whose faces meet at more than
    `CREASE_DEG` 30;
  - candidates: sharp edges within `SNAP_TIE` 2 units of the nearest one,
    all within `SNAP_REACH` 20; each is walked both ways while the run turns
    less than `STRAIGHT_DEG` 20; the **longest run wins** (a click by a lip
    must not take the short fillet at its corner);
  - the run is simplified (Douglas-Peucker, `SIMPLIFY_TOL` 0.5 units, the
    tolerance doubled until at most `MAX_SEGMENTS` 6) -- Map 3's lips are
    7-10-vertex runs on a curved wall, and a single chord floats ~3 units off
    it;
  - ordered left to right as seen from the clicked surface (`frame()`'s
    rule: an upright edge bottom to top, a ceiling's "top" its far edge);
    cut to `[start, end]` by arc length;
  - one rectangle per segment, `STRIP_WIDTH` wide, moved out along the
    clicked surface's normal by `offset`, aimed at the clicked surface
    `WASH_DEPTH` 10 units in from the edge: it washes the surface you
    clicked (under a lip: down the wall; on a ceiling: along it).
- **Joints** (renderer): each segment is its own area light, and each gave a
  full representative-point highlight, so both neighbours lit every joint
  (Map 3: 0.75 + 0.75 against 0.65 mid-segment -- bloom blobs). A segment
  carries join bits (bit 0: joined at its -u end, bit 1: at +u); at a joined
  end the highlight fades to half over the lobe footprint `d x a_eff`, so
  neighbours sum to one (`pbr::area_join_weight`, GLSL twin). Diffuse is
  exact and untouched; lone rectangles and free ends are unchanged.
- **Budget**: segments, not lights. Spots, strip segments and panels share
  the 32; rows are built once, in mesh order, by one builder that both the
  static rows and the live colours use. A light that does not fit **whole**
  is dropped with a warning -- a snapped strip is never cut short.
- **Editor**: **Add Light -> Strip** snaps at once to the edge nearest the
  click that selected the object; with no click on record, or nothing in
  reach, it is an unsnapped strip with the edge chips. On a strip row:
  **Snap to edge here** (re-snap to the latest click) and **Unsnap**; the
  edge chips show only while unsnapped.
- **Tests**: synthetic double-sided alcove (lip, left-to-right, wash
  direction, offset, start / end, curved run kept as a polyline, nothing in
  reach -> fallback + warning, join bits); the C++ joint test (unjoined
  segments > 1.5x a single rectangle at the joint, joined within 20%) and a
  frame test pinning the shader to it; the budget counting segments and
  dropping a whole strip; a DBridge test (asset-backed): a click under the
  Map 3 alcove lip snaps to the curved lip run, > 100 units, <= 6 segments.
- **Out of scope**: drawing the snapped edge; panels from a clicked face.
