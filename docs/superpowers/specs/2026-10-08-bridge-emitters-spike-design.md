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
- **Alert selection** (`renderer::bridge_emissive_texture`): yellow →
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
