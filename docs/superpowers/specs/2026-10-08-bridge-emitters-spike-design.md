# Bridge Emitters — Spike Design (living)

> **Status:** exploration, 2026-10-08. Branch `spike/bridge-emitters`
> (worktree `.claude/worktrees/bridge-emitters`), off local `main` `08045a2d`.
> Builds on the merged baseline (`2026-10-08-bridge-lighting-baseline-design.md`).
> Updated with each accepted iteration; §8 is the iteration log.

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

## 8. Iteration log

| # | Date | Change | Verdict | Sections |
|---|------|--------|---------|----------|
| — | 2026-10-08 | Spec created; evidence recorded | — | 1, 2 |
| — | 2026-10-09 | Approach A + WASDQE fly camera chosen; camera & selection design | accepted | 3, 4 |
