# Rock class — design (modern asteroids, sub-project 2)

**Date:** 2026-09-30
**Branch:** `feat/rock-class`, forked from `feat/rock-catalogue` (sub-project 1,
unmerged, awaiting live check). Base the work on that branch, never on `main`.
**Roadmap:** `docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md`
(standing decisions for this sub-project are there; this spec settles the rest).

## Intent

Asteroids stop being ships while still answering every call a mission makes on
them. A rock is a lean body: it takes hits, shows rock craters, and when its
hull runs out it **breaks up** — no ship death sequence, no fireball. Pieces big
enough become new targetable rocks; smaller ones tumble as rock chunks until
sub-project 3 (minors) exists.

This is a **deliberate departure from BC**, which built every asteroid as a full
`ShipClass`.

## Decisions (Mark, 2026-09-30)

| # | Decision |
|---|---|
| Q1 | `RockClass` **subclasses `ShipClass`**. Missions depend on `ShipClass_Cast` succeeding on rocks (see Evidence). |
| Q2 | A rock built from a **stock asteroid type keeps that type's hull HP and mass**; its shields, power and AI are ignored. Only a rock with no type file (broken off, seeded later, `DamageableObject_Create`) derives HP and mass. |
| Q3 | At 0 HP a rock **breaks up at once** (~0.5 s): crack, dust and grit burst, no fireball. |
| — | Rocks are **excluded from death-explosion splash in both directions**: a dying rock splashes nothing, and a dying ship's splash does not reach rocks. |
| — | Design sections 1–3 approved as presented. |

## Evidence

- **Cast mechanism.** `ShipClass_Cast` / `ShipClass_GetObject`
  (`engine/appc/ships.py:1936-1948`) are `isinstance` checks, so a subclass
  passes. (TESTED tier once the E2E tests below exist; today: code read.)
- **Missions that need the cast.** Each returns early on `None`, so a non-ship
  rock would silently skip a story beat:
  - E1M2 `ObjectDestroyed` (`E1M2.py:1257`) — clearing the debris rocks spawns
    the moving asteroids (`g_bDebrisCleared`).
  - E1M2 `PlanetCollision` (`E1M2.py:1314`) — "an asteroid hit Haven".
  - E1M2 `WeaponFired` (`E1M2.py:1388`) — Picard's shot counter (minor).
  - E2M1 `KaroonCollision` (`E2M1.py:649`) — Karoon hits an asteroid.
  - E2M1 tractor handler (`E2M1.py:1079`) — `ShipClass_GetObject(Beol4,
    "Asteroid 3")` or the Warbird never flings the Karoon.
  - E1M2 `AsteroidExploding` (`E1M2.py:3084`, the death script) uses
    `DamageableObject_Cast`, which any design passes.
- **E3M1's "Asteroid Amagon" DOES become a rock** (`E3M1.py:411`,
  `loadspacehelper.CreateShip("Amagon", ...)`): its hardpoint sets genus 3
  (`ships/Hardpoints/amagon.py:24`, `AsteroidMass.SetGenus(3)`), so
  `SetupProperties` switches it to `RockClass` like any stock asteroid.
  (Corrected in the final review; an earlier draft called it a disguised ship
  and out of scope.) Needs a live check — see below.
- **Nothing attaches an AI to a rock.** The hardpoints' `SetAIString
  ("NonFedAttack")` is copied (`ships.py:1210`) and never read by the engine or
  the SDK. E2M1's "FlyToAsteroid" AI belongs to the Warbird.
- **Scripted velocity is never integrated today.** `SetVelocity` /
  `SetAngularVelocity` only store (`engine/appc/objects.py:601-620`);
  `ship_motion._step_ship_motion` returns when no setpoint was written
  (`ship_motion.py:185-188`), and no other code advances a position from
  `_velocity` (only the decaying collision overlay, `collisions.py:698`). So
  E1M2's five moving asteroids very likely **never move** in Dauntless today.
  Code-read only; Task-level tests must pin it before and after.
- **`DamageableObject_Create` is unimplemented** — `App.DamageableObject_Create`
  resolves to the module `__getattr__` `_NamedStub` (`App.py:2059-2072`), so
  Multi1's and Multi6's 54 rocks each (`Multi1.py:86-149`, `Multi6_S.py:47-110`)
  are inert and invisible. Multi1 also calls `SetNetType`, `RandomOrientation`,
  `UpdateNodeOnly` and `pSet.IsLocationEmptyTG` on them; check
  `docs/stub_heatmap.md` for each before assuming it exists.
- **Torpedoes already strike any ship they cross**
  (`engine/appc/projectiles.py:update_all`), so a `ShipClass` rock blocks them
  for free. Phasers resolve against the locked target only — no change.
- **The stbc-reference MCP was unreachable** throughout (EHOSTDOWN). BC's own
  asteroid classes are not checked against the clean-room RE.

## Design

### 1. The class, creation, and per-tick cost

**`RockClass(ShipClass)`** lives in `engine/rocks/rock.py`. `GetGenus()` keeps
answering `GENUS_ASTEROID` (3) — SDK `ScienceCharacterHandlers.py` relies on it.

**Becoming a rock.** `ShipClass_Create` only receives a name, so a rock is
recognised when its properties land: in `ShipClass.SetupProperties`, after the
`ShipProperty` copy, if the genus is `GENUS_ASTEROID` the object's
`__class__` is reassigned to `RockClass` and `RockClass._become_rock()` runs.
Genus, not name, is the marker, so a mod's genus-3 rock is a rock too.
`RockClass` adds no `__slots__` and no incompatible layout, so the reassignment
is legal.

**Other constructors.**
- `RockClass_Create(radius_gu, family, seed, name)` — for broken-off pieces now
  and seeded rocks in sub-project 4. Model: a catalogue rock (a fragment for
  broken-off pieces) chosen deterministically from `seed` within `family`.
- `App.DamageableObject_Create(model_name)` → a `RockClass` when `model_name`
  resolves to a stock asteroid LOD model; otherwise a plain `DamageableObject`
  (that path is out of scope beyond not crashing). Radius comes from the
  model's bound radius times `GetScale()`.

**Hull and mass (Q2).**
- From a stock type: the hardpoint's hull `MaxCondition` and `ShipProperty`
  mass, unchanged. Mission `GetHull().SetMaxCondition(...)` overrides still
  apply (E1M2 does this per moving rock).
- A broken-off piece: `parent_max_hp × (v_piece / v_parent)^(2/3)`; mass
  `parent_mass × v_piece / v_parent`.
- No parent and no type file: `hull = 2500 × (r / 0.8)²`, `mass = 400 × (r /
  0.8)³`, `r` in GU — calibrated on stock `Asteroid` (radius 0.8, 2500 HP,
  mass 400). An explicit `SetMass` (Multi1: 400) wins.
- The hull stays **critical**, so reaching 0 still routes to death — to rock
  death (§2), not `ship_death`.

**Subsystems.** The default subsystem objects `ShipClass_Create` allocates stay
(SDK UI code pokes at whatever is targeted and does not null-guard). Shield
maxima are zeroed so `shields_block` is false; power, shield, repair and cloak
never tick.

**Loops that skip rocks** (a rock is filtered out of each):
- AI: `ai_driver.tick_all_ai` (`ai_driver.py:1660`).
- Ship motion: `ship_motion.tick_all_ship_motion` (`ship_motion.py:135`).
- Subsystem updates and articulation: `GameLoop._update_ship_subsystems`
  (`engine/core/loop.py:90-118`).
- `SetAI` on a rock logs once (developer log) and stores nothing.

The cleanest cut is a second iterator, `ship_iter.iter_non_rock_ships()`, used
by exactly those three call sites; `iter_ships()` keeps returning rocks for
every other consumer.

**Rock motion step** — `rocks.motion.tick_all(dt)`, called beside
`tick_all_ship_motion`: `p += v·dt` from `GetVelocity()`; rotation integrated
from `GetAngularVelocity()` honouring the space it was set in
(`DIRECTION_MODEL_SPACE` is used by E1M2, `E1M2.py:3032`, so the stored space
must be kept); `SetStatic` / immobile rocks never move. The collision overlay
keeps working as it does for ships. A tractor on a rock works through whatever
the tractor writes today (verify at plan time against `engine/appc/tractor.py`).

**Loops that keep rocks:** collisions, torpedo hits, the target list, sensors,
AI line of sight (`ProximityManager.GetLineIntersectObjects`), direct-hit
damage. **Not** death splash (next section).

### 2. Damage, death and breakup

**Hits.** `combat.apply_hit` is unchanged; with no live shields the damage goes
to the hull and carves craters as it does on ships. Breakable-component
severing (`hull_breakup.after_carve`) is left as it is: a carve that cuts a
piece off a big rock (radius above `BREAKABLE_MIN_RADIUS_GU`) sheds a chunk,
which reads as chipping.

**Rock surface flag.** Each rock's renderer instance carries
`surface_is_rock`, set at both realise sites (`host_loop.py` beside the
`set_rim_eligible` calls, ~6051 and ~7159). With it:
- `breach_pass` fills crater interiors from the rock's own base texture
  (triplanar, darkened) instead of the hull-interior `Damage.tga`
- `breach_venting` emits nothing
- `hull_hit_smoke.maybe_emit` skips rocks
- no hull arcing
- `breach_debris` tints chunks and sparks grey-brown

Rebuilt against today's files, using `feat/procedural-asteroids` (commits
`5ff22ff2`, `4b67f4ae`, `30f11f80`, `a28ed044`) as **reference only** — every
file it touched has been rewritten since, so nothing is cherry-picked.

**Rock death** (`engine/rocks/death.py`), replacing `ship_death.begin` for rocks
when the critical hull reaches 0:
1. Mark dying; run the death script (`RunDeathScript`, raise-safe).
2. Fire `ET_OBJECT_EXPLODING` at once, with the killer, exactly as
   `ship_death._broadcast_exploding` does.
3. Visual: crack flash plus dust and grit burst. No fireball, no explosion
   storm, no `death_cascade`.
4. **No splash damage.** `splash_damage.apply` returns early for a rock source
   and skips rock targets.
5. Break up (below), then remove the parent and fire `ET_OBJECT_DESTROYED`
   after 0.5 s, or after the lifetime the death script set if it set one
   (E1M2 sets 0.5 s).

**Breakup.**
- A size-mix split (`engine/rocks/breakup.py` dials), drawn by a generator
  seeded by the rock's name, so the same rock always breaks the same way.
  Fractions are of the parent's volume, each uniform in its range: **one large**
  piece (0.20–0.30), **3–5 medium** (0.07–0.12 each), **5–8 small** (0.03–0.06
  each); the rest is dust. If the total exceeds `kVolumeTotalMax` (1.0) the
  small pieces shrink first, then the medium; the large piece is never scaled,
  so it stays the largest. Piece radius = parent radius × v^(1/3).
  (`kVolumeBudget` and `kPieceCountMin/Max` are retired.)
- Pieces fly apart with the parent's velocity plus an outward push of
  `kSeparationSpeedGU` (**0.8 GU/s**, was 0.4) along parent-centre →
  piece-centre, and a random tumble. The large and medium pieces take
  **spread** directions (best of `kSpreadCandidates` seeded unit vectors,
  farthest from those already placed); small pieces stay random.
- Large and medium pieces of radius ≥ **1.0 GU** (`kMajorMinRadiusGU`) become
  a new `RockClass` via `RockClass_Create`: a catalogue *fragment* of the
  parent's family, named `"<parent>-1"`, `"<parent>-2"`, … in plan order (the
  large piece is always `-1`), scannable / hailable copied from the parent, HP
  and mass per §1. Below that floor they become chunks.
- **Targeting:** only the large piece may be targetable, and only when its
  BUILT (quantised) radius is ≥ **2.0 GU** (`kTargetableMinRadiusGU`); it then
  copies the parent's flag. Every other piece is untargetable whatever the
  parent's flag, and stays a solid rock you can shoot by aiming.
- One major generation (`kMaxMajorGeneration = 1`): a rock that is itself a
  piece (`_rock_generation ≥ 1`) breaks into chunks and dust only — its
  would-be majors become chunks — so there is no `"<parent>-1-1"`, and
  destroying a remnant never spawns a new target.
- Small pieces become tumbling rock chunks whatever their radius
  (`debris_chunk` style, catalogue fragment mesh, never targeted, no hull;
  capped and oldest-first evicted). At most `kMaxChunksPerDeath` (**8**) per
  death, the largest; the rest become dust. Sub-project 3 replaces these with
  minors.
- Below `kChunkMinRadiusGU`, dust only.
- Every pair in the breakup group — pieces, chunks, the parent, and **the
  killer** — ignores collisions until that pair's contact spheres
  (`collisions.contact_radius`) are `kGhostSeparationMarginGU` (0.25 GU) clear,
  with a `kGhostMaxTime` (10 s) safety cap; a pair whose member is gone is
  dropped. The killer is the body whose hit caused the
  death (a collision's other body reaches `death.begin` as DamageSystem's
  `source`). When the killer is immovable (a `Planet`, or `IsImmobile()`),
  each piece's and chunk's velocity component toward the killer's centre is
  removed: pieces born inside Haven used to keep flying inward, and the
  breakup cascaded (final review, 2026-09-30).
- Pieces do not inherit the parent's death script, and are not in any mission
  name list, so mission bookkeeping sees exactly one death per scripted rock.

**Tuned after live test 2026-10-01.** Mark's first E1M2 run: destroying a large
rock set off a lagging cascade of small explosions, with too many chunks and
large remnants crowding the target list. A headless probe found pieces born
overlapping that stay overlapped for 1.15–8.05 s against the old fixed 1 s
ghost (`kPieceGhostTime`, now retired), after which every overlapping pair
ground each collision frame: 3,520 float-noise hit-VFX spawns in 10 s for one
rock. Hence ghost-until-separated, 2–3 pieces, one major generation, ≤3
chunks per death and the 2.5 GU targetable threshold above. (The piece count, chunk cap and threshold were
superseded by the size-mix split below.)

**Size-mix split after live test 2026-10-01.** Mark's second E1M2 run: the
largest asteroid broke into pieces all about the same size. He asked for a
classic fragment mix (his feel: 1 × 0.25, 4 × 0.1, 7 × 0.05 of the volume),
hence the large / medium / small split, small pieces as chunks (cap 3 → 8),
and the large-only targeting rule at 2.0 GU. With up to six 3–5 GU majors on
random directions, nearly every name left one near-parallel sibling pair
overlapping past the 10 s ghost cap, which then ground (scenario A); hence
spread major directions and separation speed 0.4 → 0.8 GU/s.
`test_no_sibling_major_pair_overlaps_at_the_ghost_cap` pins that no major pair
is still overlapping at `kGhostMaxTime`. Note radius is the cube root of
volume, so a 0.25 vs 0.05 split is only about 1.7× in radius.

**Family.** A rock's family comes from its catalogue pick (sub-project 1's
`engine/rocks/catalogue.py`). With catalogue rocks toggled off (stock BC
meshes), pieces still use the silicate family.

### 3. Collisions broadphase

`collisions.resolve_collisions` is all-pairs today (`collisions.py:738-760`).
Breakup and Multi1's 54 rocks raise the body count, so add a **uniform spatial
hash**: cell size = 2 × the largest collidable radius in the set, clamped
to a floor; each body tests its own and the 26 neighbouring cells. Frames
(`frames.offset_between`) are handled as now — bodies in different frames are
never paired. **The pair set must equal the all-pairs set**: a test runs both
over randomised scenes and asserts identical pairs and identical resolved
state.

**Radius follows GetScale (final review, 2026-09-30).** Every object draws at
`GetRadius() × GetScale()`, but collisions used the raw `GetRadius()`, so the
player flew partway into E1M2's 3–8.5× rocks (Mark, live). The collision body
radius (`collisions.world_radius`) is now `GetRadius() × GetScale()` for every
object — the broadphase, `_respond_pair` and the hull-piece culls all read it;
`GetRadius()` itself stays unscaled SDK surface, so
`rocks.rock.effective_radius` (base × `GetScale()`) is unchanged. A rock is
exempt from `COLLISION_RADIUS_SCALE` (its sphere is its surface), and at
realise a radius-less rock seeds `GetRadius()` from its bounding sphere
(`_model_sphere_radius_from_aabb`, as planets do), not the AABB corner. The
projectile hull-sphere test, its broadphase bound, the sphere hit-point
fallback and the death-splash reach use the scaled radius too.

## Out of scope

Minors and halos, fly-through and shield flicker (sub-project 3); the far tier
(3b); profile seeding, the generic density interface and Vesuvi's 0.4 edit (4);
planetary rings; sensor occlusion; the Karoon's own scripted `SetVelocity` in
E2M1 (a ship, not a rock — noted as a related gap, not fixed here);
multiplayer net semantics of `DamageableObject_Create` (`SetNetType` may stay
inert).

## Testing

- **Unit:** genus-3 `SetupProperties` switches class; non-rocks unchanged;
  `ShipClass_Cast`, `ShipClass_GetObject`, `DamageableObject_Cast` pass on a
  rock; rocks absent from the AI, motion and subsystem loops and present in
  collisions / torpedo candidates; `SetAI` inert; hull and mass rules (stock,
  piece, formula, explicit `SetMass`); drift and model-space spin; static rocks
  never move; death splash skipped both ways; breakup determinism (same name →
  same pieces), volume budget, major/chunk/dust split at the thresholds,
  naming, flag inheritance, no death-script inheritance; event order
  EXPLODING → DESTROYED with the lifetime honoured.
- **Broadphase equivalence** against all-pairs.
- **E2E through the mission harness** (entry at the mission, not a helper):
  E1M2 — debris clearing spawns the moving asteroids; a moving asteroid
  reaches Haven and fires `AsteroidHitPlanet`; E2M1 — `KaroonCollision` fires
  on an asteroid and `"Asteroid 3"` resolves; Multi1 — 54 rocks exist, are
  `RockClass`, and have distinct positions.
- **Renderer:** `surface_is_rock` binding round-trips; venting descriptors
  empty for a rock instance; breach pass samples the base texture for a rock
  (headless GL test in the existing breach-pass style).
- **Gate:** `scripts/check_tests.sh` exits 0.

## Live check (Mark)

`./build/dauntless --developer`, then: E1M2 — shoot the debris, watch the
moving asteroids actually move and break; E3M2 — Vesuvi 4's Unknown Debris
still scan and do not die; QuickBattle in Multi1 — 54 rocks visible; shoot a
big rock until it breaks into targetable pieces.

Also:
- **E1M2 — a fully destroyed large asteroid** yields one large piece (the only
  target, if built ≥ 2.0 GU), 3–5 untargetable medium rocks and ≤ 8 small
  chunks; each piece breaks into ≤ 8 chunks and dust, with no generation 2.
  Check the size mix reads as one big / some medium / many small, and that
  the pieces separate cleanly at 0.8 GU/s (tune `kSeparationSpeedGU` by feel). Was ~58 across generations before the 2026-10-01 tuning:
  check the target list and frame rate hold up, and that no lagging cascade
  of small explosions follows the kill.
- **E3M1 — "Asteroid Amagon"** is a genus-3 rock: it should drift/spin as
  scripted, not run ship AI, and break up rather than explode like a ship.
  Confirm E3M1's own handling of it still plays out.
