# Per-Channel Animation Binder — BC-Faithful Officer Animation Rebuild

- **Date:** 2026-07-15
- **Status:** Approved design, pre-implementation
- **Branch:** `worktree-anim-channel-binder` (experimental fork in a worktree; merges back
  as a local branch for live testing in the main tree)
- **Prior work:** commits `071356a8` (single clip-path resolve site), `3c3b25cc`
  (dead-clip gate) — both shipped, both subsumed or preserved by this design.
- **Decomp evidence:** `../STBC-Reverse-Engineering-1/docs/gameplay/bridge-character-system.md`
  §5.3, §5.6, §6.2, §6.2a (all claims cited below are high-confidence entries there).

## 1. Problem

Officer gestures play but glitch: pops at gesture start/end, a full-body jerk before
LookDown/LookLeft (their leading 0.1 s facial clip `eyes_open_mouth_close` evicts the
breathe loop for the whole body), and "cut-off"-looking chains. All of it is one
structural divergence: our `renderer::update_animations` samples **one active clip per
instance** (`Instance::AnimationState`) over a static rest base, while BC's
`TGAnimBlender` binds clips **per node** — exact case-sensitive strcmp of node names;
hit = rebind that node's controllers to the clip's keys; unmatched nodes keep running
whatever drove them before (e.g. breathing); per-node last-bind-wins.

The shipped dead-clip gate (`clip_drives_skeleton` in `play_instance_gesture`) is a
special case patching over that shape. This rebuild makes it emergent and deletes it.

## 2. Decomp facts the design is built on

| Fact | Source |
|---|---|
| Channel binding is a join of two name-sorted tables by exact, case-sensitive, full-string strcmp (`FUN_006CC730`). Hit → rebind node's controllers; miss → channel dead, silent. | §5.6 |
| Every bridge animation is **non-exclusive**: character gestures pass `TGAnimAction_Create(…, 0, 0, 1)`, every door/chair/walk-on passes `(…, 0, 0)` — `bExclusive=0` throughout. Exclusive whole-skeleton mode is unused on the bridge. | §6.2 |
| `bBlend` defaults to **1** and no bridge script clears it: every bridge animation blends in. Blend time = `0.34 s`, or `0.75 × duration` for clips shorter than 0.34 s (`TGAnimAction::Play`, `0x00704140`). | §6.2, §6.2a |
| The blend interpolates from a **static seed transform** toward the new clip — the old clip cannot keep evaluating because its controllers are stolen at rebind. No dual-clip crossfade exists. | §5.3, §5.6 |
| No reverse playback anywhere (`CYCLE_CLAMP` hard-coded, `m_fFrequency = 1.0`); looping is blender re-phasing (`startTime += duration`), not an NI cycle type. | §5.5 |
| The clip loader special-cases the literal root node name `"Bip01"` (`0x0095AC30`) to set a root-motion flag. | §5.6 |
| Positioning paths (`TGAnimNode::UseAnimation`) bypass blending entirely — they snap. | §5.3 |

The exact `NiAnimBlender` interpolation curve is **not** decoded. See §8 (risks) and
§6 (dials).

## 3. Design overview

Replace the modal per-instance `AnimationState` with a per-bone channel table.
Skeleton bones are individually bound to (clip, track, start time, loop/hold flags,
blend-in). Play calls bind only the clip's name-matched tracks; other bones are
untouched. Per-frame evaluation samples each bone's own binding — or the cached
placement pose when unbound — then builds the palette exactly as today.

The Python layer above (`BridgeCharacterAnimController`: timing, priorities, chains,
`on_complete`; `bridge_idle_gestures`; `bridge_hit_reactions`) is **out of scope** — it
sits above the same boundary BC's blender does. Bridge-node clips (doors/chairs,
`node_overrides`, `g_bridge_node_anims`) are a separate system — untouched. The
lip-sync face-texture system is untouched.

### 3.1 Data model (`scenegraph/instance.h`)

`AnimationState`, `animation`, `rest_pose`, `has_rest_pose` are **removed**, replaced by:

```cpp
struct BoneChannel {              // one per skeleton bone
    int    clip_index  = -1;      // -1 = unbound → bone shows rest local
    int    track_index = -1;      // into clip.tracks (bone-matched at bind)
    double start_wall_time = 0.0;
    float  blend_in_s = 0.0f;     // BC formula at bind; 0 = snap
    bool   loop = false;          // idle loops; gestures/walks clamp+hold
    bool   root_motion = false;   // root bone: apply track translation (walks)
    bool   use_clip_base = false; // omitted-channel base: clip rest_locals (walks)
    bool   hold_at_start = false; // legacy sample_at_start (generic binding)
    bool   settled = false;       // non-loop reached end AND blend done
    glm::vec3 seed_t{0}; glm::quat seed_r{1,0,0,0}; float seed_s = 1.0f;
                                  // blend seed: bone local at bind, decomposed once
};
struct SkeletalAnim {
    std::vector<BoneChannel> channels;   // sized to skeleton bones at first bind
    std::vector<glm::mat4>  rest_locals; // placement pose, sampled ONCE at set_rest_pose
    std::vector<glm::mat4>  last_locals; // last evaluated pose (blend-seed source)
    bool has_rest = false;
    bool dirty    = true;                // false = all settled, skip palette rebuild
};
```

`SkeletalAnim` lives on `scenegraph::Instance` as a plain value member (`anim`).
`World::set_animation` / `set_rest_pose` / `restore_rest_pose` are removed; the host
layer mutates `Instance::anim` through the binder functions below.

### 3.2 The binder (`renderer::bind_clip`, new — lives beside `pose_sampler` so ctest
reaches it without the host)

```
int bind_clip(scenegraph::Instance&, const assets::Model&, int clip_index,
              const BindOptions&, double now_wall_time);
// BindOptions: bool loop, root_motion, use_clip_base, hold_at_start, blend
```

- Sizes `channels`/`last_locals` to the skeleton on first use.
- For each clip track whose `target_node_name` exactly equals a bone name
  (case-sensitive, full-string — BC's join): overwrite that bone's channel. Seed
  `seed_t/r/s` from `last_locals[bone]` (falling back to `rest_locals[bone]`, then the
  bind local) decomposed once.
- Tracks matching no bone are dropped silently (dead ballast — BC's behaviour).
- Bones the clip does not track are **untouched** (non-exclusive; last-bind-wins).
- Blend-in: `dur < 0.34 ? 0.75 * dur : 0.34`, from the runtime-tunable dials (§6);
  `BindOptions.blend = false` forces 0 (positioning paths).
- Returns the number of bones bound. **Zero means the clip changed nothing** — the
  dead-clip gate becomes emergent; `clip_drives_skeleton` and its gate in
  `play_instance_gesture` are deleted.

### 3.3 Entry points (six bindings — names and signatures unchanged, Python untouched)

| Binding | Semantics on the channel table |
|---|---|
| `set_instance_rest_pose(iid, clip, at_start)` | Sample the placement clip once (t=0 or t=dur) into `rest_locals`; clear all channels. Snap — no blend (BC positioning path). |
| `restore_rest_pose(iid)` | Clear all channels; bones fall back to `rest_locals`. Snap, as today. |
| `play_instance_idle(iid, clip)` | `bind_clip` loop=true, root translation anchored to rest, blend-in. |
| `play_instance_gesture(iid, clip)` | `bind_clip` clamp+hold, root anchored, blend-in. **Gate deleted.** |
| `play_instance_walk(iid, clip)` | `bind_clip` clamp+hold, `root_motion=true` (the literal-`"Bip01"` special case preserved), `use_clip_base=true` (omitted-channel base = clip's own `rest_locals`, matching today's non-layered `sample_pose`), blend-in. |
| `set_instance_animation(iid, clip, loop, sample_at_start)` | Generic full bind: loop as given, `root_motion=true`, `use_clip_base=true`, `hold_at_start` maps `sample_at_start`. SP2 compatibility. |

### 3.4 Per-frame evaluation (`renderer::update_animations`, rewritten)

Per instance with a `SkeletalAnim`; skip when `!dirty`. Per bone:

1. **Base local** = `rest_locals[i]` when `has_rest`, else the skeleton bind local.
   (Rest is no longer resampled every frame — cached at `set_instance_rest_pose`.)
2. **Unbound** (`clip_index < 0`) → base local.
3. **Bound** → `t` = `fmod(elapsed, dur)` for loops, `clamp` + settle otherwise
   (`hold_at_start` forces t=0 + settle). Sample the track with omitted channels
   falling back to the base TRS (clip `rest_locals` base when `use_clip_base`).
   Root bone: translation from base unless `root_motion`.
4. **Blend window**: if `elapsed < blend_in_s`, interpolate seed → sampled value
   (lerp translation/scale, slerp rotation) by the dial curve (§6; default linear).
5. Write `last_locals`, then `build_bone_palette(skeleton, &locals)` exactly as today.
   When every channel is settled (end reached, blend done) the instance goes
   `dirty=false` until the next bind — today's `settled` optimization, generalized.

`sample_pose` stays (rest capture + tests). `sample_pose_over_base` is deleted once the
eval loop subsumes it; its per-bone `pose_bone` fallback logic is reused.

## 4. What this fixes by construction

- **Full-body jerk on LookDown/LookLeft:** the 0.1 s facial lead-in binds only the
  bones it names; the breathe loop keeps every other bone. (Its facial content is
  morph-channel data BC animated and we never rendered — unchanged gap, see §8.)
- **Breathe eviction during gestures:** breathing continues on all unbound bones
  through the entire gesture chain — the numeric acceptance oracle.
- **Pops at gesture start/end:** blend-in from each bone's current local (BC's 0.34 s
  formula) at every bind, including the resume-idle bind after a gesture.
- **Dead clips:** bind zero bones, change nothing — special-case gate deleted.
- **Gesture-end hold:** a settled channel holds its last frame until the next bind —
  identical to BC's clamped controllers staying bound.
- **Walks become non-exclusive (deliberate behaviour change):** today
  `play_instance_walk` replaces the whole pose, snapping bones the walk clip does not
  track to the clip's rest locals. The binder leaves untracked bones on their previous
  binding — which is what BC does (every walk-on is `TGAnimAction_Create(…, 0, 0)`,
  non-exclusive). Walk clips track essentially the full biped, so the visible delta is
  expected to be nil; the walk oracle pins the tracked-bone trajectory either way.

## 5. Landing strategy — two commits (de-risk)

1. **Structural swap at blend = 0.** Channel table, binder, eval rewrite, gate
   deletion — with blend-in forced to 0. Output must be bit-identical to today's
   system except for exactly three behaviour changes, all verified by the palette
   oracles: (a) layered clips no longer evict the breathe loop from unbound bones
   (fixes the full-body jerk and the eviction), (b) walks go non-exclusive on
   untracked bones (§4), (c) dead clips bind nothing — visually identical to today's
   gate, which is then deleted. The walk oracle is recorded against the CURRENT
   system before the rewrite starts.
2. **Blend-on.** Enable the BC formula + the dev tuning binding.

## 6. Feel dials + dev tuning binding

Runtime-tunable, dev-mode-gated (`--developer`), same pattern as `dust_set_enabled`:

```
anim_blend_set(cap_s=0.34, short_factor=0.75, curve=0)   # curve: 0 linear, 1 smoothstep
```

Dials, in descending expected impact: blend cap (0.34 s, decomp-proven), short-clip
factor (0.75, decomp-proven), curve shape (unknown in BC — default linear; first thing
to flip if onsets feel un-BC), and per-entry-point blend on/off (positioning snaps by
default). Tuned live during Mark's visual pass without rebuilds; winning values baked
as C++ defaults afterward. A blend-off toggle gives live A/B against the structural
swap. Dials cannot mask structural errors — handover continuity is covered by numeric
oracles, not by feel.

## 7. Verification oracles

- **Headless (ctest, real assets via the worktree's cloned `sdk/`+`game/`):**
  - Scratch-probe on the real `BodyFemM` + `kiska_head` welded skeleton:
    `tilt_head_left.NIF` (Bip01 Head track) moves the head-bound palette row while
    body rows continue the breathe oscillation across the bind, with no discontinuity
    exceeding the per-frame breathe delta.
  - `Console_Look_Down.NIF` (Kiska-rigged) leaves every palette row bit-identical.
  - **Walk oracle written against the CURRENT system before the rebuild starts:**
    record the palette trajectory of the walk clip's TRACKED bones (root translation
    advancing, final pose) for a real walk clip; the rebuilt system must reproduce it.
    (Untracked bones deliberately change per §4 — the oracle scopes to tracked bones.)
    Gesture binds must keep root translation anchored.
  - Last-bind-wins: two overlapping binds on the same bone — second owns it; bones
    only in the first keep playing the first.
  - Rewrite `native/tests/renderer/animation_update_test.cc` around the table; keep
    `pose_sampler_test.cc`; update `head_weld_seam_test.cc` / `skinned_bridge_test.cc`
    where they touch `AnimationState`.
- **Live numeric (main tree, after branch lands there):** recover
  `debug_instance_anim` + `debug_bone_palette_row` readbacks from git history around
  `3c3b25cc`; run `./build/dauntless --developer` in a background shell grepping
  stdout. Acceptance: during a LookDown chain, body palette rows continue the
  breathing oscillation uninterrupted while Bip01 Head plays the look.
- **Gate:** `scripts/check_tests.sh` (never `run_tests.sh` alone) — worktree baseline
  captured before any change.
- **Final:** Mark's visual pass — smooth idles, no pops, chains read as chains, and
  the **E1M1 walk-on spine explicitly re-verified** (walk controller and bridge
  placement depend on root translation).

## 8. Risks — where this is not a copy of STBC, and why that's handled

1. **Blend seed semantics — retired by evidence.** BC blends from a static seed (the
   node's transform at rebind), not a dual-clip crossfade — controllers are stolen at
   rebind, so the old clip cannot keep evaluating. Our snapshot-and-ramp is the same
   machine.
2. **Blend curve shape — genuinely unknown.** Default linear; a one-dial swap (§6) and
   a fileable decomp follow-up if the visual pass disagrees.
3. **Morph channels — pre-existing gap, not a regression.** BC rebinds transform AND
   morph controllers per node; we render no morphs (facial = lip-sync textures). Clips
   whose only content is morph data do nothing here, before and after this rebuild.
4. **Unbound-bone fallback.** BC has no engine rest pose — untouched nodes keep the
   last transform written. We evaluate unbound bones to cached `rest_locals`. These
   agree everywhere the shipped system already behaves correctly; settled-channel
   hold-until-next-bind reproduces BC's clamped-controller persistence exactly.
5. **Walk root motion — the real regression risk.** BC's runtime use of `TGAnimNode`'s
   cached root/parent translations is not fully decoded; our walk path is our own
   live-verified construction. Mitigation is sequencing: the walk oracle is recorded
   against the current system before the eval loop changes, and E1M1 is re-verified
   live at the end.
6. **Loop seam.** BC re-phases at its completion check; we `fmod`. Sub-frame phase
   difference at the seam only; Python owns gameplay timing.

## 9. Files

| File | Change |
|---|---|
| `native/src/scenegraph/include/scenegraph/instance.h` | `AnimationState` → `BoneChannel`/`SkeletalAnim` |
| `native/src/scenegraph/{include/scenegraph/world.h,src/world.cc}` | remove the three `AnimationState` setters |
| `native/src/renderer/include/renderer/pose_sampler.h`, `pose_sampler.cc` | keep `sample_pose`; delete `sample_pose_over_base` + `clip_drives_skeleton` after subsumption |
| `native/src/renderer/{include/renderer/,}channel_binder.{h,cc}` (new) | `bind_clip`, `BindOptions`, blend dials |
| `native/src/renderer/animation_update.cc` | per-bone eval rewrite |
| `native/src/host/host_bindings.cc` | six bindings rebuilt on the binder; gate deleted; `anim_blend_set` dev binding; debug readbacks (temporary) |
| `native/tests/renderer/animation_update_test.cc` | rewritten around the table |
| `native/tests/renderer/{head_weld_seam_test,skinned_bridge_test}.cc` | updated where they touch `AnimationState` |
| `native/tests/renderer/channel_binder_test.cc` (new) | binder + oracles above |

Python: no files change (`engine/renderer.py` docstrings may be refreshed).
