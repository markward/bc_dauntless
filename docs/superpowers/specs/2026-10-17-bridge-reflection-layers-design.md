# Bridge reflections: per-state base probes, animation layers, 384² — design

*Designed with Mark 2026-10-17. Builds on the living bridge spec
`2026-10-08-bridge-emitters-spike-design.md` (cited below as "§N") and
supersedes its §9.4 base-probe split, §9.7's "probes exclude it", §11.4's
two capture colours and §13.1's "offline / special borrow the yellow/red
probe".*

## 1. Intent

DBridge is a beta-level bridge with glowing panels, pulsing red-alert bars and
state-coloured lights, but its reflections show almost none of it. Today there
are two probes (green, and yellow/red captured at yellow), and the capture draws
only lit diffuse. **No glowing surface is ever in a reflection** (§9.7), and a
light that pulses is absent from reflections altogether (§11.4). This round makes
the reflections hold what the room actually shows, in every state, including
what pulses, at a higher resolution, with no frame paying for it all at once.

Success, live on DBridge (Mark's check): at red alert the red bars and the
alcove's red pulse appear in the glossy surfaces and pulse in step with the
objects themselves; each of the five states reflects its own lighting; no visible
hitch at bridge load or on an alert change.

## 2. Decisions (Mark, 2026-10-17)

| # | Decision |
|---|---|
| D1 | **Glowing surfaces appear in reflections.** Steady glow goes into the state's base probe; pulsing glow goes into its animation layer. |
| D2 | **One base probe per bridge state**: offline, green, yellow, red, special. |
| D3 | **An animation layer = one (state, wave)**: the room lit ONLY by the materials whose animation in that state has exactly that wave, drawn at the wave's peak, added in the shader × the wave's live value. |
| D4 | **The wave key is the WHOLE wave**: `shape`, `period_s`, `phase`, `min`, `duty`, `soft` -- and, when a material multiplies several animations in one state, the whole set. Two materials that differ only in `min` get separate layers (exact; see §4.3 for why sharing cannot be). |
| D5 | **Layer cap per state, by the Bridge Quality preset**: Low 2, Medium 4, High 8 (the existing `renderer::BridgeQuality`, default Medium). |
| D6 | **384² faces on every quality preset** (Mark: "for now"). |
| D7 | **Captures are time-sliced across frames**: the current state's base first, then its layers, then the other states one probe at a time. Never per frame once complete; never all in one frame. |
| D8 | DBridge's four red pulses (Map 22a, Map 22a 2, Map 27, g_imp_redbars) take the alcove's `min` 0.2, so all of DBridge's animation is **one** layer at red (committed af1300df on `feat/bridge-reflections`). |

## 3. Evidence (measured 2026-10-17, this worktree)

- **DBridge's animation after D8**: exactly one (state, wave) — red, sine,
  3 s, phase 0, min 0.2 — across 4 materials (alcove: 4 roofs + 4 spots; Map
  22a + its copy, Map 27, g_imp_redbars: glow only, no lights). No animation in
  offline, green, yellow or special. So DBridge = **5 bases + 1 layer = 6 probes**.
- **Capture cost** — headless QuickBattle on DBridge, `DAUNTLESS_PROFILE_FRAMES=600`,
  throwaway switches forcing a recapture every frame (reverted by copy, byte-
  identical). Stable plateau of each run (another session's GL gate competed for
  the GPU late in some runs; that only inflates):

  | Face | 2 probes | 7 probes | per probe |
  |---|---|---|---|
  | 256² (today) | 23.9 ms | ~72 ms | ~10–12 ms |
  | 384² | 29.6 ms | 94.6 ms | ~13.5–15 ms |

  Cross-check: the profiler's top-level `bridge` scope read 24.0 ms GPU against
  the glFinish-bracketed wall timer's 23.9 ms (no-capture baseline: 6.7 ms GPU).
  The capture is GPU-bound and dominated by per-draw work, not pixels: 384²
  costs only ~25–30% more than 256². **§11.4's "~14 ms for both" was low** —
  today's two captures cost ~24 ms. *Not measured:* how a probe's cost splits
  between its six faces and the prefilter.
- **Memory today**: each `BridgeProbe` holds its own raw RGBA16F capture cube
  (full mip chain) beside its prefiltered cube — ~8.4 MB per probe at 256², not
  the spec's 4 MB.

## 4. Design

### 4.1 What each probe holds

Every probe is drawn from `_BRIDGE_CAMERA_EYE` (the probe origin), box-projected
against the bridge AABB, prefiltered by roughness into 6 mips — all unchanged
(§9.4, §9.6). Officers and the viewscreen stay out (§9.6). Content:

- **Base probe for state s** — the room as it looks in s with every animation in
  s at zero contribution:
  - room light (`room_light(doc, s)`, else the engine default for s);
  - every light's diffuse at its **steady** colour in s; a light whose material
    animates in s contributes **0** (today's rule, §11.4, now per state);
  - **glow (new, D1)**: every glowing surface at its steady value in s — the
    material glow table's output in s, and the texture-level `_emissive`
    default with the variant for s (`bridge_emissive_texture(mat, s)`, dark at
    offline exactly as the view draws it). A surface whose material animates in
    s contributes **no glow** (it is a plain receiver in the base);
  - captured with the material overrides and the AO-free diffuse path as today.
- **Layer probe for (s, wave W)** — the room lit ONLY by the members of W in s
  (materials whose animation set in s equals W), drawn at **wave value 1**:
  - room light 0; non-member lights 0; non-member glow 0;
  - members' lights at their state-s colour with the wave at 1
    (`behaviour.output(..., for_light=True)` with the animation factor 1),
    ^2.2 × intensity as §11.4;
  - members' glow at the state-s output with the wave at 1;
  - every surface still draws (black albedo-lit where nothing reaches it), so
    the room occludes and receives as in the base.
- **Glow colour space in a probe**: the view adds glow in display space after
  the diffuse ceiling (§9.7). A probe stores linear radiance, so a capture
  writes glow as `decode(glow)` (= glow^2.2), added after the capped diffuse and
  **not** capped — glow over 1 stays HDR in the probe, so a reflected bar can
  bloom like the bar (§9.5).
- **Diffuse ceiling, per probe** *(my call)*: each probe — base or layer — caps
  its own lit diffuse exactly as today's capture does
  (`decode(diffuse_ceiling(encode(lit)))`), then adds glow uncapped. Below the
  knee (~0.345 linear) base + layer × w^2.2 is exact. Above it: where the base is
  dark (DBridge at red: room light 0) the reflection matches at the peak and dims
  slightly early between peaks; where base and layer are both bright the sum can
  exceed the ceiling. Accepted.
- **Builder's latitude:** the received-light dip (§11.2) on an animated member
  is not reproduced exactly by base + layer; the base draws members as plain
  receivers (no dip). Accept unless it shows.

### 4.2 Shading

`spec = (Σ_i base[i] × b_i + Σ_k layer[k] × weight[k]) × (F0·A + B) × SO`
— §9.6's assembly with the layer sum added inside the prefiltered term. Bases
and layers are one list of (probe, weight) entries; the shader sums them.

- **Base weights `b_i` (the state cross-fade) live in C++** *(my call: the
  renderer is the only side that knows when a base has landed)*. Python sends
  the shown state and the paused-aware bridge dt each frame. The shown state's
  base rises by up to dt/0.5 per update and the other bases give that up in
  proportion to their weights, so the weights always sum to 1 (with two bases
  this is exactly "the other falls at dt/0.5"; *amended as built, ruling R8 —
  the original "others fall at dt/0.5, then renormalise" jumped on a mid-fade
  retarget*). The shown state's base starts rising only once it is valid. A
  change mid-fade simply retargets — no pop, no chain limit (a red → green →
  yellow click mid-fade briefly weighs three bases).
  Replaces `ProbeBlend` and `set_bridge_probe_mix`.
- **Layer weights** `weight[k] = v_k(t) × b_{s(k)}`: Python sends `v_k = w(t)^2.2`
  per layer, where `w(t)` is the product of the layer's wave factors
  (`behaviour.wave_factor`) on the bridge clock; C++ multiplies by its state's
  base weight. Layers whose state weighs 0 are not sampled.
- Why ^2.2: a light's linear radiance is `(rgb × w)^2.2 × intensity` and a glow's
  linear value is `(g × w)^2.2`; both factor as content-at-1 × w^2.2, so the layer
  is exact for every member of W (§4.3) below the diffuse ceiling (§4.1).
- Entry budget (sampled per fragment): at most 3 bases + 2 × cap layers during a
  fade; settled, 1 base + the shown state's layers (DBridge red: 2 samples).

### 4.3 Why `min` is part of the key (D4)

With `w = min + (1 − min)·f`, the reflected linear contribution is
`content × w^2.2`. Two members with different `min` need different multipliers
from the same `f`, and `w^2.2` cannot be split into a steady part (for the base)
plus a part linear in one shared factor. Sharing one layer would be off by up to
~25% mid-pulse for `min` 0.2 vs 0. Hence exact keys; authors align `min` when
they want one layer (D8).

### 4.4 Grouping and the cap (pure Python)

A new pure module (suggested `engine/bridge_editor/probe_layers.py`) plans the
probe set from the doc, the resolved materials and the quality preset:

- For each state s: the distinct wave keys among the materials actually in use
  (resolved onto ≥1 matched mesh) with ≥1 animation scoped to s. A key whose
  members contribute nothing at the peak — zero glow output and no lights in s
  (e.g. an animation over emission 0 with no State) — makes no layer and uses no
  slot of the cap.
- Order: by the first material in the doc's `materials` order carrying the key
  (authored order). The first `cap(quality)` survive; each dropped key's members
  are **absent from reflections in that state** with a warning naming the
  materials (the dev log and the editor status line, as dropped lights are).
- Output: the layer list `[(state, key)]`, and per light row / glow row its base
  capture value per state (5) and its layer membership + layer value.
- A Bridge Quality change re-plans: new layers are queued for capture, dropped
  ones freed. DBridge (1 layer) is identical on every preset.

### 4.5 Data to the renderer

Extends §11.4's capture/live split; the live per-frame colours are unchanged.

- Spots and area-light rows: `capture_radiance` grows from 2 to **5** (indexed
  by state), plus an optional layer index and its at-peak radiance.
- Glow: a new static capture table per mesh — base value per state and optional
  layer index + at-peak value — pushed with the spot/area rows (not per frame).
  The per-frame `set_bridge_glow` keeps driving the view.
- `set_bridge_probe_scales` takes 5 room-light values.
- New per frame: the shown state + bridge dt (C++ runs the base fade, §4.2) and
  each layer's `v_k = w(t)^2.2`.
- Every static push compares per probe: a probe is dirty only when an input IT
  reads changed (its state's capture values, its layer's members, the
  overrides, its room light, the bridge model, the eye). An identical re-push
  dirties nothing (today's rule, kept per probe).

### 4.6 Storage

- Prefiltered probes: **384², 6 mips, `GL_R11F_G11F_B10F`** (4 B/texel — the
  probes need no alpha and are positive; half of RGBA16F), suggested as one
  **cube-map array** (GL 4.0 core) holding every base and layer, so the shader
  binds one unit and indexes by layer. If either proves unsupported or
  imprecise on this Mac's GL 4.1, fall back to RGBA16F and/or separate cubes
  within the texture-unit budget — the builder's call, recorded in the plan.
- **One shared raw capture cube** (RGBA16F, 384², full chain) as the capture
  scratch, instead of one per probe.
- Budget at 384²: ~4.7 MB per probe + ~9.4 MB scratch. DBridge (6 probes)
  ≈ **38 MB** (today: ~17 MB for 2). Worst case High (5 + 40) ≈ 222 MB, Medium
  (5 + 20) ≈ 128 MB, Low (5 + 10) ≈ 80 MB — only for a bridge that animates
  that much; probes are allocated for layers that exist, never for the cap.
  Plus one spare slot for the probe in flight (§4.7).

### 4.7 Scheduling (D7)

- A **capture queue** of dirty probes, processed one **step** per frame at the
  top of the main bridge render (where capture runs today, before the AO
  pre-pass). A step is one cube face or one prefilter mip (a probe ≈ 6 faces
  + prefilter); the step size is the builder's to tune against the profiler,
  targeting a few ms of GPU per frame. At ~14 ms per probe that is ~2 ms per step
  if the cost splits evenly — **measure, don't assume**.
- **Priority**: the shown state's base, then its layers, then the other states
  (bases before layers), one probe at a time.
- **A recapture never blanks or tears a visible probe** *(my call)*: the probe
  in flight is captured and prefiltered into a **spare slot**, and swapped in
  when its prefilter completes; until then the old content keeps showing (one
  spare slot, since one probe is in flight at a time: +4.7 MB).
- **The inputs are snapshotted when a probe's capture starts**, so all its faces
  see one consistent room. An input change mid-capture does NOT restart it: the
  capture finishes with its snapshot and the probe is requeued once (changes
  coalesce). A continuous editor drag therefore refreshes the reflection about
  every probe-length (~7 frames), never stalls, never starves.
- The raw scratch belongs to the probe in flight.
- **Alert change before the target state is ready**: its probes jump the queue.
  Glow, lights and room light change immediately as today; the reflection
  keeps the old base until the new base lands, then cross-fades; layers fade in
  as each lands.
- **Bridge load**: no reflection until the shown state's base lands (~7 frames on
  DBridge), then the rest fill in (~42 steps ≈ 0.7 s at 60 fps on DBridge).
- **Editor edits**: only the probes the edit touches are queued, shown state
  first; a slider drag never stalls a frame (the reflection trails by a few
  frames).
- Still never per frame once complete; never on a pulse; an alert change
  queues nothing that is already valid.

### 4.8 Developer tools

- Debug view 9 (probe only) shows the composed reflection (bases + layers) for
  the shown state.
- New debug view: **reflection layers only** (the layer sum, × weight).
- Profiler: a `bridge.probe_capture` scope around each capture step (CPU; GPU is
  measured by the top-level `bridge` scope on this Mac).

## 5. Goals, non-goals, anti-goals

- **Goals**: D1–D8; DBridge reflections match the room in every state; the
  frame-time cost of a capture step bounded and visible in the profiler.
- **Non-goals**: per-frame or per-pulse recapture; a viewscreen reflection
  layer; officers in probes; reflections of reflections; resolution per quality
  preset; animated flipbook frames in probes (a `src: texture` glow on a
  flipbook is captured at whatever frame shows when its step runs);
  colour-to-colour animation.
- **Anti-goals** (failure even if it technically works): any single frame
  carrying a whole capture (the ~95 ms frame this round exists to remove); a
  reflection that pulses out of step with its object; a green-state reflection
  showing at red (or any state's content leaking into another's base); a bridge
  with no lighting file or no animation rendering differently from today apart
  from the new per-state bases, glow and resolution.

## 6. Testing

- Pure Python: grouping (key equality incl. `min` and multiplied animations;
  authored order; cap per preset; dropped-layer warnings; materials with no glow
  and no lights make no layer), base capture values per state (0 when animated),
  layer values at peak, layer weights (`w^2.2 × f_s` through a cross-fade, frozen
  under pause).
- **The linearity falsifier (GL)**: on a synthetic room lit below the diffuse
  knee, a full capture at red
  with a member's wave forced to w = 0.6 equals base(red) + layer × 0.6^2.2 within
  RGB11 tolerance — for a light member AND a glow member. This is the test that
  proves the layer model; it must fail if the ^2.2 or the content-at-1 is wrong.
- GL: time-sliced capture produces the same probe as a one-shot capture; no step
  exceeds its share; an input change mid-capture finishes on the snapshot and
  requeues that probe once; the old content shows until the swap; per-probe
  dirtiness (a red-only edit does not requeue green).
- C++ base fade: settles to the shown state; waits for an invalid target base;
  a mid-fade retarget is continuous (no weight jumps) and sums to 1; frozen at
  dt 0.
- GL: glow is in the base (a glowing quad shows in the probe, decoded, uncapped
  above 1); offline base shows texture-level emissive dark.
- Shader compile: `renderer_tests --gtest_filter='PipelineTest.*'`.
- The gate, `scripts/check_tests.sh`, green with no new ledger entries.
- **Live (Mark, DBridge, `--developer`)**: each of the five states via the
  Bridge Editor's preview squares; red bars + alcove pulse visible in
  reflections and in step; no hitch at load or on an alert change; the
  profiler's `bridge` scope during the fill.

## 7. Left to the builder

The capture step size and per-frame budget (§4.7); cube-map array vs separate
cubes and the R11G11B10F fallback (§4.6); the exact shape of the native data
(§4.5) within the stated rules; where the layer planner lives; the warning text;
how the probe storage grows when a layer is added; the queue order among the
non-shown states.

## 8. As built (2026-10-17)

**Live-verified by Mark on DBridge, 2026-10-17** (the five states via the Bridge
Editor preview squares; the red pulse in the reflections).

- **Storage** (§4.6, as specified): one `GL_TEXTURE_CUBE_MAP_ARRAY`, 384², 6
  mips, `GL_R11F_G11F_B10F` (`BridgeProbeArray`), precise enough on this Mac's
  GL 4.1 — tests allow one ulp per channel (1/64 R and G, 1/32 B; the driver
  truncates). One shared RGBA16F raw capture cube is the scratch. The array
  holds every probe plus **one spare layer**; the probe in flight is
  prefiltered into the spare and its last step swaps the two, so a slot's
  layer moves — the pass indexes through a slot → layer table. Growth (a new
  layer) allocates a bigger array and **blits** every layer, face and mip
  across (GL 4.1 has no `glCopyImageSubData`); a probe in flight survives.
  Shrinking repacks.
- **The step** (§4.7, ruling R9): **17 steps per probe**, one per frame
  (`kBridgeProbeStepsPerFrame = 1`): 6 faces, 1 for the raw mip chain + mip 0,
  6 for mip 1 (one face each), 1 each for mips 2–5. The swap is the last step.
  DBridge (6 probes) fills in ~102 steps ≈ 1.7 s at 60 fps, the shown base
  first after 17 steps ≈ 0.3 s (§4.7's "~7 frames" and "~42 steps" were for an
  even split that did not hold).
- **Measured** (DBridge, QuickBattle headless, 600 frames, 6 probes at 384²,
  GPU drained around each step). *Before R9*: settled `bridge` 4.72 ms GPU,
  continuous fill at one step per frame 8.07 ms (+3.35 ms); **mip 1 (all six
  faces) 8.99 / 14.59 ms** avg / max — the one step far above "a few ms",
  hence R9. *After R9* (avg / max ms): faces 2.13/4.72, 2.22/3.11, 2.00/2.43,
  2.06/3.18, 1.84/2.21, 2.00/3.02; mip chain + mip 0 0.93/5.73; mip-1 faces
  2.00/3.58, 1.58/2.58, 1.60/2.58, 1.63/2.75, 1.70/4.54, 1.64/2.86; mip 2
  2.95/5.20; mip 3 2.59/6.22; mip 4 1.24/1.82; mip 5 0.97/1.54. `bridge`
  settled 4.72 ms, continuous fill 7.90 ms (+3.2 ms). So the worst step
  averages ~3 ms, with occasional single-step peaks to ~6 ms. A probe ≈ 29–30
  ms of stepped work against §3's one-shot ~14 ms — not investigated; the
  harness's per-step glFinish inflates it. `bridge.probe_capture` is nested
  in `bridge`, so on this Mac it reads CPU only; a step's GPU lands in
  `bridge`.
- **Fade** (§4.2): as amended above (R8). With no base weighing anything (a
  new bridge) the first valid shown base snaps to 1. A non-positive or
  non-finite dt moves nothing.
- **Bridge-model change** (ruling R7): invalidates **every** probe, not just
  the one in flight, so a new room never reflects the old one — no reflection
  until the new shown base lands, then the rest fill in.
- **Layer values**: `set_bridge_layer_values` clamps each `w^2.2` to [0, 1]
  (non-finite → 0) in the binding.
