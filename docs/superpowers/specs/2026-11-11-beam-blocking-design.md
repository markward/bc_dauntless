# Beams stop on the first thing in their path — design

Status: built on feat/beam-blocking (2026-11-11), not live-verified.

## 1. Intent

In original Bridge Commander a phaser beam hits **whatever gets in its way**.
If a ship, station or asteroid crosses between the shooter and its target, the
beam stops on that object, the object takes a normal hit, and the intended
target takes nothing until the line clears. Mark confirmed this from play
(2026-11-11), including that it raised Saffi's friendly-fire warning when an
ally crossed his own beam.

Dauntless has never done this. Every release (0.1.0, 0.2.0, 0.2.1, current
main) traces a beam against its **target's hull only**:

- damage: `engine/host_loop.py:_phaser_step_bank` →
  `combat._resolve_hit_point(..., ship=target, ...)`, and its native twin in
  `native/src/combat/src/k2_beams.cc` (`St::TRACE`) →
  `beam_trace.cc:resolve_hit_point`;
- the drawn beam: `native/src/combat/src/beam_feed.cc:beam_endpoint`
  (native only; it was `host_loop._beam_endpoint` in 0.2.x).

So this is a missing feature, not a regression from the C++ port. The port
copied the target-only trace faithfully.

Torpedoes and other projectiles already hit any ship in their path
(`projectiles._broadphase` / `k3_projectiles.cc`, every ship but the source).
Beams are the odd one out.

## 2. Goals

1. A firing phaser bank's beam stops at the **first blocking object** along
   the line from its emit point to where it would have landed on the target.
2. That object takes the hit **exactly as if it had been the target**:
   shields first (bubble entry when a facing is up), then subsystems or hull,
   with the same per-frame contact feedback (glow, sparks), the same damage
   pulses, and the same `WeaponHitEvent` (firing object = the shooter,
   destination = the blocker). The intended target takes nothing that tick.
3. The **drawn beam** ends on the blocker, at the same point the damage
   lands, so what you see and what gets hit always agree.
4. SDK scripts react with no special casing. Because the hit is a normal
   `WeaponHitEvent`, `MissionLib.FriendlyFireHandler` (player shooter,
   destination in the mission's friendly group) counts it. That gives
   Saffi's warning (`ET_FRIENDLY_FIRE_REPORT`) and, past the tolerance,
   `ET_FRIENDLY_FIRE_GAME_OVER`, just as in BC. Any other script listening
   to `ET_WEAPON_HIT` sees the blocker get hit.
5. It works the same with `DAUNTLESS_NATIVE_COMBAT=0` (the Python K2 copy) as
   on the native path, proven by `tests/unit/test_native_k2_blocker.py`
   (seeded blocker scenes, native vs Python compared with `==`) and
   `tests/host/test_native_k2_differential.py` (real meshes; about 2,000
   blocked contacts in its Python arm). `test_native_combat_step_differential.py`
   is NOT that proof: it is unchanged, and headless `combat_stress` has no
   blocker. (The runtime audit, `DAUNTLESS_NATIVE_AUDIT=1`,
   runs `cb.phasers` wholly in Python and compares mirror rows, not kernel
   outputs, so it has nothing to say about the blocker choice; no new audit
   machinery is in scope.)

## 3. Non-goals

- **Tractor beams are unchanged** (target-only, as today). We don't know what
  BC's tractor does when something crosses it, and grabbing a different ship
  would change tractor-dependent missions. Open question §8.
- Changing *which* target the shooter picks, or making the AI aim around
  blockers. The shooter keeps its target and keeps firing. Any
  "don't shoot through friendlies" behaviour comes from the SDK AI scripts,
  as it would in BC.
- Torpedoes and pulse weapons: they already collide with ships in their path.
  Whether they should also stop on planets is a separate question (§8).
- Making unsimulated scenery block (see §4.2).

## 4. Behaviour

### 4.1 What the beam is tested against

The beam segment runs from the bank's emit point (`_strip_emit_position`)
along `aim_unit` toward the target, out to where the beam meets the target
today (the target's bubble entry, else hull trace, else fallback point). A
candidate blocks only if the beam reaches it **strictly nearer** than that.
If nothing nearer is found, behaviour is byte-identical to today.

**Blockers, from Mark:** ships, stations, asteroids, planets.

| Object | Blocks? | What happens |
|---|---|---|
| Ship / station (`ShipClass`, not a rock) | yes | normal hit: shields → subsystem/hull, event, feedback |
| Asteroid (`RockClass`, incl. breakup remnant and pieces, and promoted "Field Rock XXXX") | yes | normal hit through `apply_hit` (rocks have no shields), so it can break up as if targeted |
| Planet / Sun (`engine/appc/planet.py` `Planet`, `Sun`) | yes | **beam stops, nothing else**: no damage, no event, no impact feedback (Mark: "hitting a planet doesn't do anything") |
| The firing ship itself | never | a strip emitter lies along the shooter's own hull |
| Objects in another set / frame | never | the existing same-set guard stands |
| Dead objects (`IsDead()`) | no | same as the torpedo `ship_cache` rule |
| Hidden objects (`SetHidden(1)` / `IsHidden()`) | no | see below |

**My calls (Claude), open to correction:**

- **Cloaked ships block** when they are physically in the line, the same as
  torpedoes, which already hit them (`projectiles` has no cloak exclusion in
  its narrow test). Open question §8.
- **Planet contact makes no event and no feedback.** A planet has no shields
  or hull, so a `WeaponHitEvent` would have nothing behind it. If an SDK
  script turns out to listen for weapon hits on a planet, revisit.
- **Suns count as planets** (`Sun` subclasses `Planet`).
- **Hidden objects never block.** Campaign missions hide ships mid-play
  (E8M2 hides Matan's Keldon, `E8M2.py:4821`; E6M5 hides the player,
  `E6M5.py:2792`). An invisible ship absorbing beams, dying, or firing
  mission handlers is a worse failure than a beam passing through something
  nobody can see. The mesh trace ignores visibility, so this must be an
  explicit candidate filter. Open question §8.

### 4.2 What does not block (my call)

Unsimulated scenery never blocks:

- minor rocks (`engine/rocks/minors.py`, `MinorField`), whether halo or free;
- streamed rock-field rocks that have not been promoted to `RockClass`
  (`rock_near`, specks, puffs).

These number in the thousands, carry no simulation state and cannot take
damage. Testing them per bank per tick would cost more than everything else
in this design. The promoted field rocks (the nearest large ones, which are
real `RockClass` objects) do block.

### 4.3 Geometry of the contact

For each candidate the beam is tested the way the target is tested today, so
the blocker contact point is the same kind of point the target would get:

1. **Shielded ship:** if `shields_block(candidate)`, the contact is
   `shield_bubble_entry(candidate, emitter, aim_unit, max_dist)`.
2. **Otherwise:** `_resolve_hit_point` against the candidate's instance
   (mesh trace, then the bounding-sphere entry). The sphere-entry tier does
   **not** count as a block for a non-target candidate. A beam that merely
   grazes a non-target's inflated bounding sphere but misses its mesh must
   pass by. Without this rule, a ship near the line with no renderer instance
   (headless, or not yet realised) would block on its ~2x-inflated sphere.
   In practice a candidate with no instance **never** blocks: tier 1 also
   needs `_shield_hull_box`, which is written at realize together with the
   instance (`combat._hull_box_for`), and headless `host_io.ray_trace_mesh`
   returns None. Tests must fake both (see §7).
   **Bubble hit, mesh miss:** a shielded blocker whose bubble the beam
   crosses while the mesh trace misses (e.g. an empty facing with the
   generator on — `shields_block` ignores per-facing charge) still blocks
   at the bubble. Its hull point follows the torpedo pattern
   (`projectiles.py` ~1015-1055: trace back from the bubble, then the sphere
   entry, then the bubble point). (My call; check against BC's `TestHit`
   once the clean-room reference is reachable.)
3. **Planet / Sun:** a ray–sphere entry with radius `collisions.world_radius`
   (`GetRadius()`, the drawn radius), NOT the collision `contact_radius`
   (0.8 × R for planets) and NOT `SetAtmosphereRadius` (gameplay-only).
   The centre is the sphere's **true** centre, not `GetWorldLocation()`:
   every stock planet NIF is one sphere of r 90.0099 whose centre sits at
   (−0.736648, 0.368324, 0) through the `planet` node (the Planet geosphere
   row in CLAUDE.md). The planet is drawn at `radius / 90.0099` scale
   (`host_loop.py` ~6965), so that offset scales with the planet and is
   ~0.9% of R: several GU on a large planet, enough to stop the drawn beam
   short of or inside the visible surface. Apply the offset through the
   planet's rotation and scale. A modded non-sphere planet (fails the
   geosphere gate) uses its origin and `GetRadius()`.

Use the **sim pose** for all of this (`hit_pose_of`, per the Native ship
motion row). It is a gameplay query.

The nearest contact wins. Ties (equal distance) go to the intended target, so
a target touching its own escort never flickers.

### 4.4 Damage, pulses and feedback on a blocker

- **Distance falloff** uses the distance from the emit point to the blocker
  contact. Today `dist` is emitter → aim point on the target. For a blocker,
  the beam is that much shorter. (My call: it is the length the beam actually
  travelled.)
- **Pulses:** the bank's dwell keeps accumulating as today (`accumulate_dwell`
  / `take_dwell` are the bank's, not the target's). When a pulse fires, it
  lands on **whatever the beam touches on that tick**: the blocker if
  blocked, else the target. Nothing is split or carried per object.
- **Subsystem lock / manual-aim offset:** these only shape the aim *ray*
  (`_phaser_aim_point`). A blocker gets no locked subsystem (`target_sub`
  is None). The hit routes to subsystems by impact point, as any untargeted
  hit does.
- **LIGHT power (PP_LOW)** "disable, don't destroy" still applies on the
  blocker. It is a property of the shot, not the target.
- **Dev cheats** (god mode, NPC shields off, 2× player weapons) apply by
  who the blocker is, as they would for any hit (they already hook
  `apply_hit` / `shields_block`).
- **Per-frame contact feedback** (`hit_feedback.beam_contact`) goes to the
  blocker with the blocker's contact point and bubble entry.

### 4.5 What does not change

- Fire control (K1): when to start and stop firing, arc checks, range gates,
  the `can_detect` gate. All of these are still judged against the **intended
  target**. A blocker in the way does not stop the bank.
- The bank's `_target`, the shooter's AI, the target list and the HUD.
- Torpedoes, pulses, tractors.

## 5. Where it lives (how it gets made)

ONE "first contact along a beam" resolver per language, used by **both** the
damage step and the drawn beam, the same way `resolve_hit_point` is shared
today:

- **C++:** a new function beside `beam_trace.cc:resolve_hit_point`, taking
  the shooter, the target, emitter, `aim_unit`, the target's own contact
  distance and the candidate set. It returns the contact object (target,
  blocker or planet), point, normal and bubble entry. Called by
  `k2_beams.cc`'s TRACE step and by `beam_feed.cc:beam_endpoint`.
- **Python:** the twin, called from `host_loop._phaser_step_bank` (the
  `DAUNTLESS_NATIVE_COMBAT=0` copy). It must agree with the C++ path exactly
  (the K2 A/B and audit compare them).

**Candidates:**

- Ships and rocks: the same roster combat already walks (`ships_list` in the
  combat step / the mirror's object rows). Broadphase with a segment-vs-sphere
  reject using the bubble bound radius, the way K3's `_broadphase` /
  `sweep_candidates` does for torpedoes. Reuse it if it fits; per bank, the
  segment is the beam.
- Planets and suns: not in the combat roster or the mirror today. They need
  feeding in as (set, world position, radius) rows. They are few per set and
  static or slow, so a per-step list is enough. How (a mirror table, a
  per-step push) is the builder's choice.

The native K2 kernel's existing rules still hold. Anything it cannot
represent hands that ship's step to Python (`k2_unclean_ships` /
RUN_PYTHON), and a field the kernel reads must be a `Native*` descriptor.
Native-reader rules for `SetIndex` keys apply if the set index is used for
candidates.

## 6. Cost

This runs per firing bank per sim tick, and the drawn-beam feed per bank per
frame. The broadphase must keep the common case (nothing near the line)
close to free. Mesh traces run only for candidates whose sphere the segment
crosses nearer than the current best contact.

Measure before and after with the frame profiler on
`DAUNTLESS_MISSION=engine.dev_missions.combat_stress` (Release vs Release,
the `cb.phasers` and beam-feed rows), and record it as a signal in
`docs/reference/engine/perf-register.md`. No target number is set; a visible
regression in `cb.phasers` at 64+ ships is a stop-and-ask.

## 7. How we'll know it works

Headless tests (focused files only; see CLAUDE.md "Test gate"). Headless,
no ship blocks on its own (§4.3.2), so the blocker tests must either seed a
hull box and install a fake mesh-trace hook (the way existing K2 / beam-feed
tests drive `install_trace_hooks`), or be asset-backed with real instances.
Prefer the fake for 1-2, 4-5, 7-10, and keep 3 and 11 asset-backed so at
least one test exercises a real mesh.

1. **Ship blocks:** shooter, blocker and target in a line, with the blocker
   shields down. The blocker's hull/subsystems take the pulse, the target
   takes nothing, and one `WeaponHitEvent` has destination = blocker,
   firing object = shooter.
2. **Shielded blocker:** the blocker's facing absorbs; contact at its bubble
   entry.
3. **Graze:** a ship whose bounding sphere the beam crosses but whose mesh it
   misses does not block. This needs an instance; mark it asset-backed if
   necessary.
4. **Behind the target:** a ship past the target on the same line is never
   hit.
5. **Self:** a strip emitter whose segment crosses the shooter's own hull
   never blocks on the shooter.
6. **Planet blocks silently:** the beam stops at the planet sphere, with no
   damage to anyone, no event and no feedback.
7. **Asteroid blocks:** a `RockClass` in the line takes the hit.
8. **Friendly fire:** with `MissionLib.SetupFriendlyFire()`, the player's
   beam blocked by a friendly-group ship raises the current friendly-fire
   total and posts `ET_FRIENDLY_FIRE_REPORT`. This is an end-to-end test
   through the real SDK handler.
9. **Line clears:** once the blocker leaves the line, the next pulse lands
   on the target.
10. **Native = Python:** native on and off are byte-identical on seeded
    blocker scenes (`tests/unit/test_native_k2_blocker.py`: ship, planet,
    hidden planet, two banks, the ASK paths, an unshielded pair) and on real
    meshes (`tests/host/test_native_k2_differential.py`, about 2,000 blocked
    contacts in its Python arm).
12. **Hidden ship:** a hidden ship in the line does not block.
11. **Drawn beam:** the beam feed's endpoint equals the damage contact point
    for a blocked bank.

Live check (Mark): Quick Battle, fly through a beam between two AI ships,
and fire past an ally (friendly-fire warning). Until then the CLAUDE.md row
says "not live-verified".

## 8. Open questions

- **Tractor beams:** in BC, does something crossing a tractor beam get
  grabbed, block it, or get ignored? Unchanged until answered.
- **Cloaked ships:** do they block a beam in BC? We assume yes (§4.1).
- **Hidden ships:** do they block in BC? We assume no (§4.1).
- **Why BC's AI fires through allies:** the SDK FireScript's line-of-sight
  check is switched off (`AI/Preprocessors.py:344`, "For now, skip this
  check"), so AI ships do shoot into friendlies in the way. That matches
  what Mark saw; this design keeps it.
- **Torpedoes and planets:** torpedoes currently test only the ship roster,
  so a torpedo apparently passes through a planet. This is out of scope
  here; worth checking separately.
- The clean-room reference (stbc-reference MCP) was down while this was
  written. BC's phaser tick should be checked there for how it picks the
  first object (ray vs sphere vs mesh) when it is back.

## 9. Left to the builder

- Exact function names, signatures, and where the planet rows live.
- Whether the broadphase reuses `sweep_candidates` or a sibling.
- Test file layout, and the CLAUDE.md row (add one; this is a fidelity
  behaviour a future reader will look for).

## 10. Decisions made while planning and building

- **Planet surface** is a mesh trace on the planet's renderer instance, so the
  beam ends on the drawn surface. With no instance (headless) it is a
  ray-sphere entry about `GetWorldLocation()` with `world_radius`, which can
  sit a few GU off the drawn surface; never seen in a rendered game. Planet
  broadphase bound is `world_radius * 1.02` (`PLANET_BOUND_SLACK`).
- **A planet-blocked pulse is lost**: the dwell was consumed by the bank and
  nothing receives it. Planets stop silently (no hit event).
- **A shielded blocker's hull point** is the mesh tier along the same ray if it
  hits, else the bubble point itself (normal None). The torpedo pattern's
  inflated-sphere tier is skipped. The tier is reported as "mesh", "sphere" or
  "bubble".
- **Candidate order** is deterministic (`ships_list` order, then planets in
  `planet_instances` order); a candidate wins only when strictly nearer, so the
  target wins ties.
- **Cross-set pairs are never blocked**: candidates are same-set only.
  Hidden and dead objects never block (`IsDead`/`_dead` read live per
  candidate). Tractors are unchanged: only phaser banks block.
- **Row-less ship**: a session ship with no mirror row sends the bank to Python
  (`stale_row`). Class overrides of `IsDead`/`IsHidden` are decided in Python,
  not natively.
- **NeedPython**: in damage it becomes the `blocker` ASK; in the drawn feed the
  pair is drawn with today's unblocked endpoint and counted as BeamSkip
  "blocker". Known cost: one row-less or class-flagged ship anywhere in the
  ship list makes every phaser pair draw unblocked that frame, while damage
  asks Python, so the two can disagree for that frame. Whether production ever
  has such ships is unchecked.
- **Tests**: the spec's asset-backed tests 3 and 11 became fake-trace tests
  (`install_trace_hooks` in gtest, a monkeypatched `host_io.ray_trace_mesh` in
  Python); real meshes are covered by the live check.
- **The native = Python proof** is `tests/unit/test_native_k2_blocker.py`
  plus `tests/host/test_native_k2_differential.py` (real meshes; 2,017
  blocked contacts through the Python `first_blocker` in one run), not
  `test_native_combat_step_differential.py` (unchanged; headless
  `combat_stress` cannot block). An earlier "native 20 hits vs Python 9"
  reading in `test_native_k2_blocker.py` was the harness, not the kernel:
  its two arms shared `App.g_kSystemWrapper`'s RNG, the module `random` and
  the `ship_death` / `object_lifetime` registries. It reproduces at the base
  commit and matches once each arm is seeded and the registries cleared
  (`_fresh_arm`; the unshielded-pair case guards it).
- **Hidden planets** never block either: `first_blocker` skips
  `planet.IsHidden()` after the shooter/target check, and the native side
  reads the same answer from the planet row (`_k2_planet_rows`' `hidden`).
- **Golden**: Mark re-recorded the `beam_scene` render golden on 2026-11-11;
  drawn beams now end on blockers from frame 19.
- **Owed**: live check (fly through a beam between two AI ships, fire past an
  ally, fire at a ship behind a planet) and a before/after profiler capture on
  `combat_stress` (`cb.phasers`, beam feed, `cb.render_data`).
