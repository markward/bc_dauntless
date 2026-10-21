# Layered hull damage, phase 4: finish and retire the carve — design

**Status:** design, 2026-10-22. It follows phases 1–3 of
`2026-10-21-layered-hull-damage-production-design.md`, the parent design, whose
goals and rules still bind. Mark asked on 2026-10-21 to "spec and plan phase 4
and implement it subagent driven". The calls marked *(my call)* are mine and
are listed for him at the end.

## 1. Intent

Phases 1–3 rebuilt everything the player sees on the layered system. Phase 4
finishes the work:

- damage stays on articulated parts as they move;
- parts are ready before the first hit;
- the remaining loose ends of breaking apart are closed;
- the old voxel carve is deleted outright;
- the tuning is put somewhere usable;
- everything is documented and given a final measurement.

After phase 4 the branch can be merged into main. Mark: not before the carve
is gone.

## 2. Goals

### 2.1 Damage moves with articulated parts

- **Hits are recorded on the part they struck.** Damage records are stored
  in each part's REST frame, with the part they hit: the node index, or −1
  for the hull body.
  - A hit is attributed by the existing rig lookup,
    `part_severance.part_for_live_point`, and passed to the wear bindings as
    a node name.
  - The binding converts the hit point and normal into that node's rest frame
    with `rest_corrections`.
- **The plating, the interior and the severance check all work in the rest
  frame.** This mirrors the hull-name decals:
  - The plating draw and the mark use `u_node_rest_fix` per mesh.
  - The interior pass transforms its ray per mesh.
  - Structure parts, the fill volume and records are all rest-frame data, so
    they agree by construction.
- **The articulated fallbacks go.** These are the "whole list for articulated
  hulls" fallback in the per-mesh subsets, and the "articulated → whole list"
  branches.
- **Structure severance stays off for rigged ships** (`after_wear`'s rig
  gate). Rigged ships keep `part_severance` by named part.
- **Proof:** an LC Intrepid-style rig. Pose a nacelle, hit it, then move it:
  the damage stays on the nacelle.

### 2.2 Structure parts ready at load, cached on disk

- **Detection starts when a ship's model is realised or warp-preloaded,** not
  at its first damaged draw. A `prefetch_structure_parts(handle)` binding is
  called beside `prefetch_hull_fill`.
- **The cache file.** The segmentation (volume dims/origin/cell, labels,
  parts) goes to `<cache_dir>/structure_parts/<fnv1a64 of the source file
  bytes>-v<kDetectVersion>.sps`. The format is versioned binary, read on the
  worker thread, little-endian. *(my call: binary, not JSON; the label grid
  is ~370k cells)*
- **Where it goes.** The root is pushed from Python at boot, as
  `hull_volume_set_cache_root` does. It is written through the per-user data
  dirs.
- **Failures.** Write failures are reported once per path. A corrupt or
  stale file is ignored and rebuilt.
- **Tests never write under `PROJECT_ROOT`** (the install-write guard).

### 2.3 Breaking apart, finished

- **The parent stops shadowing a lost part.** The shadow depth pass gets a
  part-mask variant, used only for instances with severed parts or chunks.
  It does a fragment discard by the same `plating_part` rule. A chunk then
  casts its own piece's shadow, not none.
- **Cloak: chunks are skipped, as they are in shadows today.** A cloaking
  parent still shows its lost part while cloaked. *(my call: rare, accepted)*
- **Lights and emitters on a lost structure part go out:**
  - running lights;
  - attached emitter lights;
  - particle emitters on subsystems in the part.

  Python reads the instance's severed mask (binding `instance_severed_parts`)
  and tests each light or emitter's rest position with `structure_part_at`,
  as it already does for rig parts (`_PART_SEVERED`).
- **A severed chunk is dead.** Its `emissive_scale` is 0 at spawn, with no
  window glow.
- **Molten rims on fresh tears return.** The four freshest breach events
  (age < `kRimLife`) are uploaded to the PLATING program and the interior.
  The torn rim glows `blackbody` hot, fading over `kRimLife` and with
  distance from each event, as the old breach pass's rim did.

### 2.4 The old carve, deleted

Remove every runtime piece the phase-3 final review inventoried (ledger
2026-10-21-layered-damage-p3):

- **Python:**
  - `hull_carve.py` and `core_breach_carve.py`;
  - the carve branches of `hit_feedback`, `visible_damage` and
    `hull_breakup`;
  - `host_io`'s carve wrappers and `hull_carving_enabled`;
  - the instance-field hull-volume pipeline.
- **Native:**
  - `HullCarveField`, `InstanceFieldCache`, the field atlas and brush;
  - `hull_split_detached`, `hull_carve_add`, `hull_carve_capsule`;
  - the carve stencil and `BreachPass`;
  - `breach.frag`, the Damage1-4 frames;
  - `opaque.frag`'s `hull_cut_at`, `u_carve_*` and `u_hull_field*`.
- **Also:** dead tests, dials, docs and CLAUDE.md text for all of the above.
- **Re-homed, not deleted:**
  - **The fill cache.** `CarveFieldCache` is renamed `HullFillCache` and kept.
  - **`find_base_texture_id`,** for rock craters.
  - **`breach.vert`,** renamed `hull_interior.vert`.
  - **Venting and debris,** re-gated on breach events only, with no
    `enabled()`.
  - **`allow_hull_carve`,** renamed for light phaser fire (no structural wear).
  - **The warp-core breach visual.** It becomes three Internal records
    growing at the core over 1.5 s, sized as before: 0.25 × radius, capped
    at 1.2 GU, wear 10.
  - **The death capsule** is dropped. Severance and the death blasts cover it
    now.
  - **DamageTool volumes in Damage Preview** become Internal records.
- **Shared pipelines are kept.** Anything the inventory lists that turns out
  to have a non-carve consumer, such as the hull volumes or `SourceVolumeCache`
  used elsewhere, is kept and noted. The removal task checks every consumer
  before deleting.
- **The stock program changes** when the carve clip and its sampler go. Pin
  an undamaged-hull pixel test against the pre-removal output, and re-baseline
  `HullClipTest` / `ScuffTest`. Delete the tests that only tested the carve.

### 2.5 Tuning in Developer Options

- **One source of defaults: C++ `g_params`.** A binding
  `plating_param_defaults()` returns them. Python's `plating_dials.DEFAULTS`
  stays as the headless fallback, pinned equal by a drift test.
- **Developer Options gets a "Hull damage" section.** It has value-cycling
  rows (the existing `_doValueRow` pattern) for:
  - strip, breach and deck-break wear;
  - toughness spread and lumps;
  - soot;
  - phaser rate and collision threshold;
  - the death blast size tiers;
  - interior on/off;
  - rooms near distance (20 GU);
  - "Reset hull damage dials".

  The `/ L O` dial group stays for fine stepping. *(my call: value rows, no
  slider widget)*

### 2.6 Docs and the final measurement

- **CLAUDE.md:**
  - add a "Layered hull damage" row;
  - correct the DamageTool, Rock class and Collision scuff rows;
  - remove the carve's tuning instructions.
- **`damagetool-and-hull-damage-gaps.md`** is marked superseded, with a
  pointer.
- **Final perf, Debug, DP with FIRST_S/SEED, CPU-only plus GPU-focus:**
  - alive must be ≤ 2× undamaged;
  - dying must be ≤ the legacy death (SIG-098 / SIG-090);
  - add one severed-ship capture;
  - read `hb.split_parts`.
- **Record the P-12 verdict.**
- **Hand Mark a live-check list.**

## 3. Non-goals

- New interior content.
- Saving damage in save games.
- Hull or subsystem health changes.
- Capping or filling the break line. It stays an open, smooth part-shape
  boundary unless Mark asks.
- Severance on rigged ships through structure parts.

## 4. Constraints

- **All of the parent design's rules hold:**
  - the opaque.frag driver rules (no samplers added, no early return, one
    plating discard);
  - focused tests only;
  - no destructive git;
  - never touch main;
  - perf only on an idle machine.
- **The stock program may change only by losing the carve clip.** An
  undamaged hull renders identically before and after: pinned.
- **Removal lands after its replacements exist,** so the game never loses a
  feature mid-branch: venting, rocks and severance are already rebuilt.

## 5. Calls made for Mark

1. Structure-part cache files are versioned binary, keyed by source-file
   content hash.
2. A cloaking parent still shows its lost part while cloaked; chunks are
   skipped by the cloak pass.
3. Severed chunks go dark (emissive 0) at spawn.
4. Molten rims on fresh tears come back on the new system.
5. The warp-core breach is three growing Internal records. The death capsule
   is dropped.
6. Developer Options uses value-cycling rows, not sliders.
