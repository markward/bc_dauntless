# Layered hull damage — from spike to product

**Status:** planning, 2026-10-20. The spike lives on `spike/damage-redesign`
(worktree `.claude/worktrees/damage-redesign`, 16 commits on main
`9da1178c3`). Nothing is merged. This document records what the spike proved,
what a read-only review found wrong with it, and the work needed to ship it.

## 1. What the spike proved

Live-checked by Mark in game, one step at a time:

| Layer | What you see | Verdict |
|---|---|---|
| Plating | Torpedo hits strip whole panels; repeated hits widen the patch | "looking really impressive" |
| Skeleton | Ribs follow the hull's detected parts: saucer spokes branching outward + rings, nacelle hoops + stringers | matched the NX drydock reference |
| Damaged structure | Ribs bend, twist, sag, snap and scorch with wear | approved after brightness fix |
| Inner pressure hull | Dents, scorches and glows under the ribs; holds until ~4.5 hits on one spot | approved |
| Torn edges | Plating rips across panels, peels and shreds at the edge | "really great" |
| Part detection | Disc / cylinder / box from the solid voxel shape, never from polygon edges; works on the LC Intrepid | "pretty good" |
| Internal blasts | A destroyed subsystem blows out only where its blast reaches the hull | approved approach |
| Holes | Torn-through hull is cut (see-through); the inside wall shows through one sheet, space through two; ribs reach into the hole | "very interesting", `member_survive` 4 |
| Death cascade | BC's `AddDamage` storm opens these holes across a dying ship | **not yet checked** |

Decisions Mark made along the way:

- The old voxel carve is off; damage is built layer by layer instead.
- Ribs must follow the hull's shape and be detected from the model with no
  per-ship setup, and never by turning mesh edges into ribs.
- Panels are cells of the skeleton; they tear, peel and shred rather than lift
  out cleanly.
- A destroyed subsystem only blows a visible hole if its blast reaches the
  hull.
- A real hole is see-through.
- Deferred: whether collisions strip plating; caching parts to disk.

## 2. What the review found

A read-only review of the whole diff (2026-10-20). Items marked *verified*
were re-checked by hand; the rest are taken from the review and must be
confirmed before fixing.

### Must fix (wrong today)

1. **Holes can see straight through the ship.** Double-sided drawing turns on
   only when one record alone reaches 0.8 × breach wear, but the shader sums
   wear across records and adds tear noise. Two overlapping records can cut a
   hole with no inside wall behind it.
2. **One hole makes the whole ship double-sided.** Every back face on the hull
   shades as bulkhead, so any open or single-sided BC geometry (fins, cards)
   anywhere on the ship can show a dark back face.
3. **Targetable rocks get plating.** *Verified:* rocks that are game objects
   draw through the ship path; only scenery rocks zero their records. A
   torpedoed asteroid grows panels and ribs, and its craters (from the carve)
   are gone.
4. **Scripted subsystem kills blast at load.** Every DESTROYED transition
   queues a blast, including missions that set up pre-damaged ships, and a
   repair-then-destroy cycle blasts again.
5. **The exit search mixes poses.** The blast centre comes from the 60 Hz sim
   pose while the ray traces hit the interpolated render pose. `breach_burst`
   vents along a radial-from-centre direction, not the exit normal.
6. **More than 12 parts are dropped in label order,** so a small early lobe can
   push out a saucer or nacelle.

### Performance (unmeasured, and must be measured)

- *Verified:* the gate is "the hull has any damage record". One phaser glow or
  scuff turns on the full plating cost for every pixel of that hull:
  roughly 220–260 record-loop iterations per pixel at 24 records, against ~48
  before; a stripped pixel can reach ~650 plus ~30 noise calls.
- Damaged ships draw double-sided, so back faces rasterise too.
- No eligibility cap: every damaged ship pays, in every camera including the
  viewscreen feed. The old carve was capped to the player plus a few ships.
- The shared opaque shader carries all of this code, which can lower GPU
  occupancy for every hull draw, damaged or not.
- CPU per draw: uncached uniform-name lookups, a mutex and a string
  allocation for the parts cache, `glIsEnabled`.
- Part detection starts one unbounded thread per new hull type.

### Data model

The spike stores everything in the 24-slot decal ring, which was built for
transient scars:

- Internal holes never refresh, so they are the first evicted: a hole heals
  after ~24 later impacts. A phaser burst can evict a persistent record.
- An evicted torpedo record takes its wear with it, so stripped panels replate.
- One DamageTool script (22 volumes) or a long death cascade fills the ring.
- Wear counts throttled emits, not damage; phasers never build wear.

### Frames and units

- Plating runs in the posed body frame, but parts come from the rest-pose
  model: on articulated hulls (LC Intrepid nacelles) the skeleton slides, and
  a hole can float where a part used to be.
- Plating sizes are model units and scale with `SetScale`; hole radii are
  absolute GU. The project rule is absolute GU.

### What carving did that is now gone

- **Gameplay:** `hull_breakup` severing chunks and killing the subsystems
  inside them. Part severance still works; it never used the carve.
- Breach venting and debris on ordinary hits (only internal blasts emit them).
- Collision carves, death-cascade capsule cracks, the warp-core breach carve.
- Rock craters.
- DamageTool volumes in Damage Preview.

### Rules and hygiene

- Production is not byte-identical: plating is on by default, soot is scaled,
  carving is off, and there is no toggle.
- Defaults are duplicated in `plating_dials.py` and `frame.cc`.
- A bare `except: pass` in `plating_dials.push`; unconditional
  `[internal-blast]` prints.
- CLAUDE.md rows for DamageTool, Rock class and Damage Preview describe the
  carve.
- Test gaps: no render tests for discard, double-sided drawing, glow kill or
  "undamaged hull unchanged"; no parts-cache tests; no real-hull detection
  regression; several carve tests now pass against a no-op.

## 3. The product

### 3.1 A damage store of its own

Move wear and holes out of the decal ring into a per-instance **hull damage
store**:

- Persistent records never evict. When full, the two nearest records of the
  same kind merge (summed wear, centroid, enclosing radius), so damage
  coarsens instead of healing.
- Sized for a full death cascade plus authored damage: 64 records to start.
- Records carry damage dealt, not emit counts; phaser fire builds a small
  wear so sustained beams still do structural damage.
- Decals stay as they are for scorch, heat glow and scuffs.
- Upload as a uniform block. Any sampled store (texture buffer) must first be
  checked against the known `opaque.frag` sampler miscompile on this Mac.
- **Later, if 64 is not enough:** the per-hull damage map (a unique UV
  unwrap of each hull) from the original proposal.

### 3.2 Pay only near damage

- The CPU builds, per draw, the short list of records whose reach can touch
  the hull, plus a bounding sphere per damaged region.
- The shader does one cheap loop to find whether this pixel is near any
  damage; if not, nothing else runs.
- Plating moves into its own shader variant (`#ifdef PLATING`, like
  `PLANET_SURFACE`), used only for damaged hulls, so undamaged hulls keep
  today's program.
- **Double-sided drawing:**
  - Decide it from the same summed wear the shader uses (fixes item 1).
  - Back faces far from any damage are discarded, so open geometry
    elsewhere on the hull looks exactly as before (fixes item 2).
- An eligibility cap like the old carve's: player, target, nearest few.
- Cache uniform locations; one lock-free lookup per draw.

### 3.3 Structure parts, generated once

- Detect at model load on one bounded worker, and for the warp destination
  during the tunnel preload, so parts exist before the first hit.
- Cache to disk beside the `.dhv` hull volumes, keyed by the hull file's
  content hash plus a detection version. Write through the per-user data
  dirs, reporting failures with `report_write_failure`.
- Keep the largest parts, not the first ones.
- **Articulated hulls:**
  - Detect parts per articulated node.
  - Store damage records in the rest frame through `u_node_rest_fix`, the way
    hull-name decals already do, so damage moves with its part.
  - First, reproduce Mark's main-branch report of one part's interior
    following another part's rotation, and design around its real cause.
- Real-hull regression tests (Galaxy, Akira, Sovereign, Bird of Prey, LC
  Intrepid) through the content-root test helper.

### 3.4 Holes and what fills them

- Keep: torn hull is cut; the inside wall shows through one sheet, space
  through two; members span the hole.
- Fill: port the decks-and-rooms interior from the breach-interior spike onto
  the inside wall, so a hole looks into rooms rather than at a flat wall.

### 3.5 Internal blasts and AddDamage

- Blast only on destruction by damage, not on scripted setup or the first
  seconds of a mission; one blast per subsystem per life.
- Resolve the blast against the render pose in C++, and vent along the exit
  normal.
- Rocks excluded (see 3.7).
- Dev-only logging.
- **Death cascade:** keep BC's timing and AddDamage branch; holes as now,
  pending Mark's check.

### 3.6 Gameplay coupling

The carve's chunk severance and its subsystem kills are gone. Options:

- (a) retire them for good;
- (b) rebuild severance on the new store, so a part is lost when torn wear
  runs across its whole cross-section;
- (c) keep part severance only (it never needed the carve).

Recommendation: (c) now, (b) later if it is missed.

### 3.7 Rocks

Rocks keep the carve-era look: craters, no plating. Either keep the old carve
path for rocks only, or give them a crater-only variant of the new store.
Recommendation: crater-only variant, so the old carve can be retired whole.

### 3.8 Production switch

- A graphics setting, "Hull damage: Classic / Layered".
- **Classic is byte-identical to main today:** carve on, no plating.
- Layered is the new system.
- The plating dials move to Developer Options with one source of defaults
  (C++, exposed through a binding).
- Retire the old carve code only after Layered has shipped and been
  live-verified.

### 3.9 Proof

- **Render tests** for:
  - undamaged hull unchanged;
  - stripped panel shows structure;
  - torn spot is discarded;
  - back faces only near damage;
  - the cull state restored.
- **Store tests:** merge-not-evict, wear from damage.
- **Blast tests:** units, poses, the scripted-setup exclusion.
- **Performance:** a B2 / B2d capture before and after, recorded in
  `perf-register.md`, in a Debug build like the existing baselines.
- **Docs:** a spec, plus CLAUDE.md rows for the new system and corrected
  rows for DamageTool, Rock class and Damage Preview.

## 4. Decisions for Mark

1. Rocks: crater-only variant, or keep the old carve for rocks?
2. Gameplay: part severance only for now, or rebuild chunk severance?
3. Should phasers build structural wear, and how fast relative to torpedoes?
4. Collisions: deferred earlier; still deferred?
5. Interior fill: port the decks-and-rooms look into holes now, or later?
6. A Classic / Layered setting, or Layered only once it ships?

## 5. Proposed order

| Step | What | Done when |
|---|---|---|
| 1 | Measure the spike as it stands (B2, B2d) | numbers in the perf register |
| 2 | Hull damage store + CPU near-damage list + plating shader variant + fixes 1, 2, 6 | render tests green, perf at or below the spike |
| 3 | Parts at load, disk cache, size order, articulation frames | Intrepid nacelles keep their damage when they move |
| 4 | Internal blast fixes (3.5), rocks (3.7) | blast tests green; rock craters back |
| 5 | Production switch, dials to Developer Options, docs | Classic byte-identical; Mark's live check of Layered |
| 6 | Interior fill, gameplay coupling, phasers, collisions | per Mark's decisions |
| 7 | Main-merge gate, then retire the old carve in its own change | gate green |
