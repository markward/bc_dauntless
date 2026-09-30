# Modern asteroids: programme roadmap and standing decisions

**Date:** 2026-09-30
**Status:** living roadmap. Each sub-project gets its own brainstorm, spec and plan.
This file records the decisions already taken, so they are not re-litigated.

## Intent

In BC, and in our engine today, every asteroid is a full ship. In Mark's words:
"they're basically ships — damage works like a ship and they just explode and
evaporate."

Moving away from that is a **deliberate departure from BC**. Rocks should:

- load, behave and die like rocks
- chip and break into smaller pieces rather than explode
- never sit bare: a rock is a celestial body and always has company (small
  rocks, dust, haze)
- fill the space the radial system profile's `asteroids` column says has rocks

Every mission that scripts asteroids must keep working. That covers:

- **E1M2:** debris and moving asteroids, death scripts, collision events
- **E2M1:** tractoring "Asteroid 3"
- **E3M1:** Amagon's `ET_WEAPON_HIT` count and its fail condition
- **E3M2:** scanning, targeting and renaming the Vesuvi 4 "Unknown Debris"
- **E4M6:** the Nepenthe field's nav points

## Size spectrum: the core model

Size decides how real a rock is.

| Tier | What | Simulated | Targetable |
|---|---|---|---|
| **Major** | big rocks, placed by a mission or seeded | yes: a light rock body that collides, chips and breaks up | yes |
| **Minor** | gravel and small rocks around and between majors | no: instanced scenery that drifts and parts around the ship | no |
| **Dust / haze** | the existing dust pass plus local haze | no | no |
| **Far tier** | a belt, field or ring seen from a distance | no: a continuous band or impostor representation that hands off to rocks as you approach | no |

## Sub-projects

| # | Sub-project | Status |
|---|---|---|
| 1 | **Rock catalogue**: glTF loader, offline generation tool, committed catalogue, BC scripts redirected to it | spec `2026-09-30-rock-catalogue-design.md` |
| 2 | **Rock class**: one class for mission and seeded rocks; rock damage; breakup | not started |
| 3 | **Minors**: instancing, halos, tile fields, fly-through | not started |
| 3b | **Far tier** | not started |
| 4 | **Profile seeding** | not started |
| later | **Sensor occlusion by rocks** | play-test experiment |

## Standing decisions for sub-projects 2–4

### Sub-project 2: rock class

- **One class** for mission-placed and seeded majors. Only the spawner differs.
  - Both are targetable and scannable.
  - There are **no hardpoint files**. Hull and mass derive from the rock's size.
  - `CreateShip("Asteroid…")` still yields this class. Mission calls keep
    working: `GetHull().SetMaxCondition`, `SetDeathScript`, `SetVelocity`,
    `SetAngularVelocity`, `SetScale`, `SetTargetable`/`SetScannable`/
    `SetHailable`, `SetName`/`SetDisplayName`.
  - The class must pass the SDK's `ShipClass_Cast`/`ShipClass_GetObject` as
    missions use them. E1M2 casts `ET_OBJECT_EXPLODING` destinations, and E2M1
    uses `ShipClass_GetObject`. *How* it passes (for example a `ShipClass`
    subclass) is for the sub-project 2 design, once our cast mechanism has been
    checked.
  - It keeps rocks off the ship-cost paths: no AI, no subsystem ticks, no ship
    death cascade.
- **Rock damage visuals** are salvaged from `feat/procedural-asteroids`:
  - the per-instance rock surface class
  - craters that expose rock
  - no venting, arcing or smoke
  - rock-tinted debris

  They are re-keyed from species 712 to "is a rock", and ported carefully,
  because `breach_pass` and `carve_field_cache` have moved since August.
- **Breakup is decided by size.** Fragments big enough to be majors become new
  targetable majors named after the parent ("Asteroid 5b-1"). Smaller ones become
  minors and dust. Mission rocks follow the same rule, so small story rocks just
  crumble.
  - The parent still fires `ET_OBJECT_EXPLODING`/`ET_OBJECT_DESTROYED` and runs
    its death script, so mission bookkeeping is unchanged.
- **Blocking.** Majors are solid to torpedoes and pulses, as ships are today. They
  also appear in the AI's line-of-sight check (`GetLineIntersectObjects`), so NPCs
  won't fire through them.
  - Phaser beams match whatever beams do against ships (to check at design time).
  - BC's torpedo cone deliberately allows firing *through* an asteroid
    (`weapon_subsystems.py:2795`, audited). That is launch gating, not flight
    blocking.
- **Collisions** need a broadphase. Today `collisions.resolve_collisions` is
  all-pairs O(n²) over every set.

### Sub-project 3: minors

- **Every major carries its own minor cloud**, scaled to its size and moving with
  it, whatever the profile says. E1M2's swarm then falls toward Haven as one
  group.
- **Minors are instanced** from the catalogue fragments, with runtime LOD. The
  dust pass (`dust_pass.cc`) is the only instanced draw today and is the
  template.
- **BC tile fields stay set content.** Each `AsteroidFieldPlacement` (Vesuvi 1,
  Nepenthe 1, Beol 4, Multi7) becomes a local minor cloud at its own position and
  radius:
  - count = tiles³ × per-tile
  - sizes from its size factor
  - no majors
  - warp gating (`warp_gates.py`) and E4M6's "Center of Asteroid Field" nav
    points are kept
- **Fly-through.** Minors are shoved aside with a small puff and a grit sound, and
  do no damage. This is a cheap check for the player only, in the style of the
  dust proximity response. If shields are up, the shield flickers
  **cosmetically**.

### Sub-project 3b: far tier

- **In scope for this programme.** It matters for any formation (belts, tile
  fields, seeded clusters), not only rings.
- It is a continuous representation seen from a distance that hands off to
  majors and minors as you approach.
- It uses the catalogue's baked impostors and per-rock average albedo (from
  sub-project 1), so the distant band matches the rocks it stands in for.

### Sub-project 4: profile seeding

- **A generic density-field interface.** Every source of rocks implements it:
  - the radial profile (density by distance from the star)
  - a BC tile field (a sphere)
  - a future **planetary ring** (an annulus around a planet with inner and outer
    radius, thickness and its own radial bands)

  Rings then become a new source, not a new system.
- **Majors appear only where `asteroids` ≥ 0.5.** Their density rises from zero
  at 0.5 to the maximum at 1.0.
- **Anchors are a starting point and tuned by feel:**
  - **Majors at 1.0** = Vesuvi 4's loose field: 12 rocks in a 1,500 GU sphere,
    about one per 1.2 × 10⁹ GU³.
  - **Minors** ramp from 0.0, with **1.0** = Beol 4's field: 405 rocks (3³ tiles
    × 15) within a 1,000 GU radius.
  - All density and size numbers live in one data table plus `--developer` dials,
    following the `dev_nebula_dials` pattern.
- **No mission-rock safeguard.** The threshold alone keeps seeded majors out of
  story scenes. Mark declined a "no seeded majors in regions with mission rocks"
  rule.
- **Vesuvi's hand profile:** the Geki → Haven band drops from **0.5 to 0.4**,
  so Vesuvi (and E1M2 at Haven) gets minors and dust but no seeded majors.
  - This edits `engine/systems/maps/vesuvi.json`: both `overrides.profile` and
    the engine-read top-level `profile`.
  - It must keep the generator's `profile-override-tracks-clump` check green.
- **Mechanics.** Seeded majors are real set objects:
  - created in a working volume that travels with the player
  - retired behind the player
  - deterministic, so a belt looks the same when you come back, with stable
    derived names
  - sensible at dash speeds (2,000–100,000 GU/s)
  - sensible across region hand-offs (`handoff.hand_off`)

### Later: sensor occlusion

Rocks hiding ships behind them from sensors was **declined for now**. Explore it
once the belts can be play-tested. A belt's general sensor penalty is authored in
the profile's existing `sensors` column.

## Performance

- GPU timing is dead on this Mac. Measure CPU only, with the frame profiler
  (`docs/engine/frame-profiler.md`), using combat-stress-style runs.
- For reference, a headless sim tick costs about 0.35 ms per ship. Every rock
  that is a `ShipClass` pays that cost today.

## Evidence notes

- The stbc-reference MCP (clean-room RE) was **unavailable** during the brainstorm
  (connection failure). BC's own asteroid classes (`AsteroidField`,
  `CT_ASTEROID_TILE`) have not been checked against the RE.
- `DamageableObject_Create` is an **unimplemented stub** today, so Multi1's and
  Multi6's 54 rocks each are inert and invisible. Sub-project 2 or 3 should give
  them a real home.
- No engine code reads `GENUS_ASTEROID`. Its only reader is SDK
  `ScienceCharacterHandlers.py`, which keeps the science officer quiet about rocks. Whatever sub-project 2
  builds must keep `GetShipProperty().GetGenus()` answering 3 for rocks.
