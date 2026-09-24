> **SUPERSEDED** by `docs/superpowers/specs/2026-09-24-system-frames-design.md`.
> Kept as the record of how the design got here. Several decisions below are
> reversed there — see its "Decisions this reverses". Do not implement from
> this document.

# In-system navigation — one solar system per star, streamed regions (design)

**Date:** 2026-09-22
**Status:** design approved; not implemented. Ona to be generated and reviewed
before the remaining 24 systems.
**Area:** sets (`engine/appc/sets.py`), warp (`engine/appc/warp.py`,
`engine/appc/ships.py`), render scoping (`engine/host_loop.py`), a new system-map
data format and generator.

## Goal

Today each place in a BC star system — Ona 1, Ona 2, Ona 3 — is a **separate,
unrelated set**. Travelling between them is a scene cut: you warp into a tunnel
and appear somewhere else. The places share nothing, not even a consistent sun
direction.

Replace that with **one solar system per star**: the sun at the centre, the
planets and moons on orbits around it, and the original BC sets placed *in* that
system as regions you fly between. Two outcomes are wanted, in priority order:

1. **Continuity between places.** From Ona 1 you can see Ona 2 where it actually
   is, lit by the same sun, and flying toward it genuinely closes the distance.
2. **Planets that fill the sky.** Bodies re-authored considerably larger than
   BC's 90–360 GU.

Warp inside a system becomes an exploratory act rather than a menu choice: a
heading you engage on, at a speed that scales with the distance, with a flash to
sell it. Reaching another planet by impulse alone must be possible, if slow.

## Vocabulary

| Term | Meaning |
|---|---|
| **system** | A star system — `Ona`. Has one coordinate space. |
| **region** | An original BC set (`Ona1`), now anchored at a position in its system. Keeps its own local coordinates. |
| **anchor** | A region's position in system coordinates. Translation only, never a rotation. |
| **space set** | One extra set per system, holding the sun and any body owned by no region. What you occupy between regions. |
| **hand-off** | Moving a ship between two sets at a region boundary, keeping pose and velocity. Silent. |
| **dash** | In-system warp. No tunnel. |
| **tunnel** | BC's existing `"warp"` set and its full warp sequence. Retained for system-to-system only. |

## What exists today (measured in the tree, not assumed)

### The SDK's system structure

- **89 menu-listed places** across 25 campaign systems, built by
  `Systems.Utils.CreateSystemMenu` into the Helm → Set Course tree
  (`sdk/Build/scripts/Systems/Utils.py:30`). Each is its own set created by
  `Systems/<Sys>/<Sys>N.py`, with static objects in a sibling `<Sys>N_S.py`.
- **87 of the 89 contain at least one planet; 2 do not** — `Vesuvi4` ("Vesuvi
  Dust Cloud") and `Belaruz1`, both `MetaNebula_Create` only.
- **118 planet objects** in total: 64 places hold exactly one, 23 hold a primary
  plus 1–3 companions (Beol 1 holds four).
- **No planet sits at its set's origin.** The origin belongs to `Player Start`;
  the planet is placed by `PlaceObjectByName` at an authored waypoint. Primary
  planets sit 263–5041 GU out, clustered 400–1000 and 1500–2000.
- **Placement names are not consistent.** `Planet Location` ×52, `Planet` ×20,
  `Planet1` ×13, plus `Planet Placement`, `Colony`, and two named after the set
  itself (`Nepenthe1`, `Belaruz4`). Moons use six spellings. A set's planet
  **cannot be found by waypoint name** — use the object, whose display name is
  the one `AddObjectToSet` was given and the one the target list shows.
- **Per-set suns are inconsistent within a system.** `Alioth1`'s sun is at
  `(+70000, 0, 0)`; `Alioth3`'s at `(-70000, 0, 0)`. Belaruz and Vesuvi have no
  sun object at all. There is no system-level geometry to be faithful to.
- **Region numbering reads as orbital order** — Ona 1/2/3, Alioth 1–8; Vesuvi
  starts at 4 with an orphan `Vesuvi1.py` still in the tree, which fits.

### How much space a region actually needs

Body positions are irrelevant (the bodies are being re-placed). What bounds a
region is the **non-body** content the system script and its missions place in
set-local coordinates. Measured across every `Systems/*/*.py` and every mission
`*_P.py`:

| Extent | Regions |
|---|---|
| ≤ 1000 GU | the large majority |
| 1000–3000 GU | ~10 (Vesuvi 4/6 asteroids, Beol 4 asteroid field, Alioth 6, Biranu 2, Serris 2, Starbase 12, E7M6) |
| 5000–6400 GU | **Prendel 3** (E5M2/E6M4 stage a base and three Galors just past Moon 2 at `(400,5000,0)`), **Xi Entrades 5** (E7M3 stages a fight around a *phantom* `Moon1` waypoint at `(400,5000,0)` that no moon is ever placed at) |
| 17,322 GU | **Savoy 1** — E3M1 parks two Birds of Prey at `(-10000,-10000,10000)` as an off-screen holding spot |

Two consequences: region radii are individual and mostly small; and where a
mission stages content beside a body, that body must keep its set-local position
(a **pin**) or the mission needs a placement override. Savoy 1 needs neither —
content beyond the radius simply stays in the set, far away, which already works.

### The mission arrival surface (full audit)

Arriving by impulse from an arbitrary bearing is a state no mission was written
for. Every hook that fires on a set transition, classified:

- **`ET_EXITED_WARP` — 9 missions** (E1M2, E2M6, E4M4, E5M4, E6M4, E7M3, E7M6,
  E8M1, E8M2). All the same shape: `player.GetContainingSet().GetName() == "X"`
  → run the arrival beat. None reads position or placement.
- **`ET_ENTERED_SET` — 24 missions**, all `AddBroadcastPythonFuncHandler` on the
  mission, all name-keyed. Fire naturally on any set change.
- **The `"warp"` tunnel set — referenced by 12 missions.** Seven of them (E1M1,
  E2M2, E3M1, E5M2, E5M4, E7M3, E7M6) use it only for timers, comm-flag
  bookkeeping and "don't do this while in transit" guards. The other five are the
  problem: **E6M1–E6M5 `PlayerEntersWarpSet` reads the warp button's destination
  and pre-creates ships during the tunnel** —
  E6M1 creates the Artrus ships there and `GiveArtrusShipsAI()` then dereferences
  them on arrival **with no None check**. Skipping the tunnel on those trips
  would crash. Every ship-creating case is a cross-system trip from Starbase 12;
  the in-system exposures (Savoy 3→1, Geble 3↔4, Serris 1↔3, Tezle 1↔2) are all
  `StopProdTimer`, which the arrival handler also does.
- **`ET_WARP_BUTTON_PRESSED` — 26 missions hook it; most block warp** behind story state
  ("supplies not transferred", "stay and guard Biranu 2"); E6M1 ends the game on
  the fifth refused attempt.
- **`LinkMenuToPlacement` — 9 sites**, arrival geometry only.

**Conclusion: no mission needs editing**, provided five engine rules hold (below).
The residual is arrival *geometry*, a live-check list.

### Our engine

- **Planets already draw at exactly `GetRadius()` GU.** `host_loop.py:5743`
  divides by the model's bound-sphere radius so the NIF scales to the number.
  **Making a planet bigger is one number, no model work.**
- **Rendering is already scoped to the player's set** — `active_set()`
  (`engine/appc/ship_iter.py:32`) → `_live_sets()` (`host_loop.py:4160`) gates
  planets, suns and ship realization. Simulation is *not* scoped: AI, motion and
  combat iterate every set.
- **The dash exists** — `ShipClass.InSystemWarp` (`engine/appc/ships.py:715`),
  integrated by `ship_motion._step_in_system_warp`, cruising at
  `IN_SYSTEM_WARP_SPEED_FACTOR = 100.0` × impulse `MaxSpeed` (≈630 GU/s for a
  Galaxy) and stopping at a standoff. It is AI-driven today; the player has no
  control bound to it.
- **The tunnel exists and is load-bearing** — `engine/appc/warp.py` clears
  targets, silences weapons, stands down player AI, plays VFX, routes through the
  `"warp"` set, and arrives at **exactly zero velocity** (settled 2026-08-10). Critically, it
  also **deletes the source set** (`_WarpDepartAction`: render teardown hook,
  then `g_kSetManager.DeleteSet`), so a set you leave today is destroyed and
  re-created from its module on return. The two calls are already separate,
  which is what makes §3 possible.
- **Followers already handle a vanished player** —
  `AI/PlainAI/FollowThroughWarp.py` warps to whatever set the followed object is
  in, arriving 40 GU behind it, re-checked on a ~10 s cadence. 34 call sites across
  17 missions.
- **`WarpFlash` is a silent stub.** BC's `Actions/EffectScriptActions.py:27` is
  called by the tunnel sequence *and* by `loadspacehelper.CreateShip(...,
  iWarpFlash=1)`. We implement neither (`docs/stub_heatmap.md:151`,
  `WarpFlash_CreateWithoutShip`, 12 hits). AI dashes and scripted arrivals are
  currently flashless.
- **Nacelle glow exists but is deliberately narrow** — `_warp_glow_envelope`
  (`host_loop.py:1344`) is **player-only, cross-system-sequence only**, an
  explicit scoping decision at the time. 32 ships carry authored `GlowRegion`
  volumes in `engine/appc/hardpoint_overrides.py`, so the data for widening it
  exists.
- **BC's own warp gate is complete** (`Bridge/HelmMenuHandlers.py:740–800`):
  refuses on warp engines disabled (`CantWarp1`), off (`CantWarp5`), unpowered
  (`EngineeringNeedPowerToEngines`), or inside a nebula (`CantWarp2`) — each with
  an authored helm line and subtitle fallback.
- **The Orbit command is already surface-relative** —
  `AI/Player/OrbitPlanet.py` circles between `GetRadius()+150` and
  `GetRadius()+190`, gated by `ConditionInRange(200 + GetRadius())`, intercepting
  with `SetAddObjectRadius(1)`. **It scales with planet size for free.** The
  target-list range readout is likewise surface-based.
- **Save/load is not implemented** (34 SDK `MissionLib.SaveGame` call sites, no
  engine implementation), so it constrains nothing here — but when it is built,
  where the player is within a system becomes part of a save.

## Design

### 1. The system map — data and generator

One file per system, checked in, resolved through the **project** asset root
(never `paths.game_asset`) — the precedent is the scuff normal map.

Contents:

- **Bodies.** Name, display name, radius, position in system coordinates, what
  it orbits, and an **appearance** block held separately from identity. Today
  appearance is `{kind: "nif", model: "..."}`; a future procedural body is a
  different appearance on the same identity. This split exists from the start so
  that swapping in generated planets later touches the renderer and one field.
- **Regions.** One per BC set: anchor, radius, and which bodies it owns.
- **Pins.** Bodies that must keep their original set-local offset because a
  mission stages content beside them (Prendel 3, Xi Entrades 5).
- **Overrides.** A hand-edited block the generator never rewrites.

**The generator** (`tools/gen_system_maps.py`) reads the SDK and emits the
generated block: discovers regions, reads each one's bodies, measures its radius
from the non-body content (system script *and* mission `_P` modules), detects
pins, orders regions by their trailing number, and lays bodies out — sun at the
centre, planets on orbits, moons around planets.

**Anchor rule — reproduce the artist's intent.** The original set records, for
each body, *the direction you looked to see it* and *how far away it was*,
measured from `Player Start`. Anchors are derived from that: place the bodies on
their orbits first, then set the anchor at the **centroid of the region's bodies,
displaced back along the original viewing direction** by a standoff chosen from
how large the primary body should appear. One planet → near it, on the side the
artist put you. Planet plus moon → between the two. Beol 1's five bodies → their
centre. Distance is set by desired apparent size, not by the original distance.

**What the rule cannot preserve: lighting direction.** With one real sun at the
centre, light comes from wherever the region sits, so some regions will be lit
from a different side than in the original. This is a deliberate, visible change
and the price of a coherent system. Backdrops stay per-region and are unchanged.

**Two things the generator must guess and will sometimes get wrong**, both
resolved in the overrides block:

1. **Unnumbered regions** (Haven Colony, Geki Colony, Kessok Colony) have no
   orbital index and need placing by hand.
2. **Moon or planet?** `"… Moon N"` is unambiguous. Vesuvi 5 holds Geki, Inyo and
   Mori; Beol 3 holds Kerry and Legare — these read as separate worlds sharing
   one map. The generator assumes "largest is the planet, the rest are its moons"
   and **flags** the ambiguous ones.

**A validator runs in the gate** over all maps: every BC set has a region; no
region's radius contains a neighbour's anchor; pinned bodies still sit where
their mission stages content; no body engulfs its own anchor.

**Ona is generated and reviewed first** (three numbered regions, one planet each,
no moons, no pins) before the other 24 are touched.

### 2. Bodies stay in their own sets

A region's bodies remain objects **in that region's set**. The map sets their
position and radius; nothing is removed, no object is created, no model is
swapped. This is what keeps the Orbit command, `GetObject("Haven")`, hailable
planets and the target list working with zero changes.

The space set holds only the sun(s) and bodies owned by no region.

Removal happens only where the map relocates a body — the ambiguous Vesuvi 5 /
Beol 3 cases — and each is a deliberate entry in the overrides block.

### 3. Region streaming

**The space set** is a normal `SetClass` named for the system (`"Ona"`), created
with the system map. It has a region module so it is a valid NPC warp
destination.

**Set lifetime changes, and this is the one real change to existing behaviour.**
Today, warping away from a set **destroys it**: `warp.py:_WarpDepartAction`
calls the render teardown hook and then `g_kSetManager.DeleteSet(name)`. A
region you leave is gone, and arriving re-creates it from its module — so
mission ships staged there do *not* persist.

Within one system that must stop. Regions are created once when the system is
entered and **are not deleted until the player leaves the system entirely**.
Crossing to another *system* tears the old one down exactly as today. This is
what makes "the ambush is still sitting where the mission put it, however you
arrive" true rather than aspirational.

**Set lifetime and render realization are separate concerns**, and the warp path
already treats them as two calls. Only the second changes:

| | Today | Within a system |
|---|---|---|
| Render teardown (`teardown_set_objects`) | on departure | driven by the streamer, per region, by distance |
| `DeleteSet` | on departure | only on leaving the system |

So distant regions keep simulating (their ships exist, their AI runs, their
mission state advances) but hold no renderer instances. Bodies are the exception
— they are realized **system-wide** regardless, because the celestial layer draws
them from everywhere. That bounds the render cost to roughly the system's body
count (~15 for the largest systems), not to every region's ships.

**The hand-off** — one new operation on the set layer: *move this ship from set A
to set B, place it here, keep its heading and velocity*. No tunnel, no stop, no
target clear, no VFX. It emits `ET_EXITED_SET` / `ET_ENTERED_SET`, and — when the
object is the player — **also `ET_EXITED_WARP`**, which is what makes all 33
mission arrival hooks fire untouched (rule A).

**The streamer** — one new owner in the host loop. Per tick it tests the player
against the active system's region boundaries and calls the hand-off. It also
supplies the celestial layer's draw list and runs the dash.

- **Hysteresis.** Enter at the radius, leave at radius + margin. Sitting on the
  line must not flip-flop.
- **Missions can refuse an exit.** Leaving a region runs the same gate the warp
  button runs; a refusal plays the mission's own line and holds the player at the
  boundary (rule D).
- **NPCs.** Followers use `FollowThroughWarp` unchanged and follow the player
  into and out of the space set (rule B2 — the space set must be a valid warp
  destination). Ships without a follow order stay in their region.

**Deliberately not built: sleeping distant regions' simulation.** Render
realization is scoped by distance (above), but AI, motion and combat keep
iterating every set exactly as today — that is what lets a mission's off-screen
duel run, and it is load-bearing for E2M6-style scripting. If the extra resident
regions prove too costly once 8-region systems are live, sleeping *simulation* is
a later optimisation **with a measurement behind it**, not a guess.

### 4. The celestial layer

When the player is in region R, the bodies of every *other* set in the system are
drawn shifted by the difference between their anchor and R's. They appear at
their true bearing and distance, lit by the same sun, with correct parallax —
they are genuinely where they appear to be, not a painted backdrop. Flying at one
closes the distance; reaching its boundary hands you off.

Bodies beyond normal draw range use the **virtual-distance** treatment the
renderer already applies to suns and lens flares (`sun_pass.cc:119`,
`lens_flare_pass.cc:93`): drawn at a scaled distance preserving apparent size, so
the far plane need not stretch to 100,000 GU and depth precision is unaffected.

This requires bodies to be render-realized system-wide, which is the exception
carved out in §3. Ships stay scoped to nearby regions.

**Cost is a new unknown.** An 8-region system draws up to ~15 bodies where today
it draws one or two, and holds several regions' sets resident where today it
holds one. They are simple objects at distance and this is expected to be cheap,
but that is an expectation, not a measurement — the frame profiler, against a
combat scene, is the check.

### 5. The dash — in-system warp

**Two kinds of trip.**

| Trip | Mechanism |
|---|---|
| System to system | **Tunnel, unchanged.** The audit makes this load-bearing: E6M1 creates ships during it. |
| Anywhere within one system | **Dash.** No tunnel. |

**Two ways to start a dash:** Set Course to an in-system destination, or a new
Helm control that engages on the current heading. Both run the same machinery.

**Speed from distance.** Target trip time ≈25–30 s; speed = distance ÷ trip time,
clamped at both ends. A neighbouring-region hop lands near today's dash speed; a
long crossing runs several times faster. Trips feel a consistent length and the
difference reads as speed.

**Slow on arrival.** Inside the destination region, drop to today's dash speed
for the final leg and stop at a standoff from the body — matching BC's existing
dash, so the approach stays BC-paced however fast the crossing was.

**Two distinct moments, not to be conflated:**

- Crossing a region boundary is a **silent hand-off**. Nothing visible happens.
- Leaving the dash is a **drop-out with a flash**, at the standoff, typically
  seconds later.

**Steering is locked while dashing.** Engage fixes the heading; disengage to turn.
The strictest rule, and the one that reads as warp rather than fast impulse.
Loosening it to slow steering is a small later change if the live pass wants it.

**The flash** fires on engage and drop-out for **any** ship. This implements BC's
`WarpFlash`, so escorts flash out following the player, enemies flash in to
intercept, and BC's own `CreateShip(..., iWarpFlash=1)` arrivals start working.

**The jump burst is not reused.** The tunnel's bright jump flare belongs to a
single jump moment a dash does not have; the dash gets spool-and-hold, with the
flash effect doing that job. Adding the burst later is trivial.

**Nacelle glow widens to every warp type and every ship** with authored glow
volumes (32 of them). This reverses the earlier player-only, tunnel-only scoping.

**The warp gate is BC's, not a new one.** Engaging a dash runs
`HelmMenuHandlers`' existing checks — engines disabled / off / unpowered / in a
nebula — with their authored lines, plus the mission `ET_WARP_BUTTON_PRESSED`
chain. A mission that swallows the event aborts the dash.

**Deliberately not built:** dash speed scaled by warp-engine condition. BC has
the subsystem and it is an obvious later addition; it is not needed here and
every extra dependency is another thing to get wrong first.

### 6. Orbit and planet substitution

Nothing about the Orbit command changes. `AI/Player/OrbitPlanet.py` is entirely
surface-relative, so a twenty-times-larger planet is orbited twenty times further
out at the same 150 GU altitude, automatically. The range readout is likewise
surface-based.

**A consequence of large bodies: orbits get long.** A lap around Ona 1 today is
~4 minutes at impulse; around a body twenty times larger it approaches ~50. This
is physically right and probably acceptable — one orbits to *be* somewhere — but
"I ordered orbit and nothing happens" is a plausible live-pass finding.

**Three things to verify rather than assume at 20× scale:** collision against a
planet that large; the environmental-damage band (authored separately, does not
scale itself); and whether a body that size looks right lit by a real sun at real
distance rather than the 70,000-GU stand-in it was authored against.

## The five engine rules the audit depends on

These are the load-bearing invariants. Each gets a guard test.

| # | Rule |
|---|---|
| **A** | A region hand-off emits the same arrival events as a warp — including `ET_EXITED_WARP` for the player. |
| **B2** | The space set is a valid NPC warp destination (has a region module), so `FollowThroughWarp` works unchanged. |
| **C** | System-to-system Set Course keeps BC's tunnel sequence. Without it, E6M1 crashes. |
| **D** | Dash engage and region exit both run the warp-button gate, so mission refusals hold. |
| **E** | Within a system, leaving a region never calls `DeleteSet`. Only leaving the *system* does. Render teardown is driven by distance instead. |

## Testing

**In the gate (headless):**

- Map validity across all 25 maps — coverage, radius vs neighbouring anchors,
  pins, body-engulfs-anchor.
- Hand-off — heading and velocity survive; events fire, in order; set membership
  correct on both sides.
- Boundary — hysteresis prevents flip-flop; a mission refusal blocks the crossing.
- **Arrival hooks** — run a staging mission headless, cross a boundary, assert its
  arrival function ran. The audit, as a test rather than a claim.
- **Rule C guard** — system-to-system Set Course still routes through the tunnel
  set. Exactly the kind of invariant a later refactor deletes by accident.
- Warp gate — disabled / off / unpowered / nebula each refuse with their own line.
- Speed profile — distance → speed with clamps; drop-out at the standoff, not the
  boundary.

**Live-pass checklist (written down, not remembered):** arrival view against the
artist's intent; changed lighting direction; whether planets read as big; orbit
duration; flash timing; collision at 20× radius; celestial-layer frame cost via
the frame profiler against `combat_stress`, not an idle scene.

**A dev mission** — `engine/dev_missions/system_nav.py`, alongside
`damage_preview` and `collision_sim` — drops the player into Ona with the map
live, making each of the above one launch rather than a campaign playthrough.

**Housekeeping:** system maps resolve through the project asset root, never a
hardcoded path (`tests/unit/test_path_indirection.py` enforces). The
known-failures ledger stays at its current single entry; nothing here is
baselined.

## Open questions

1. **Does losing a warp nacelle disable warp in BC?** Ships carry a
   non-targetable `WarpEngineProperty` ("Warp Engines") *and* two targetable
   `EngineProperty` nacelles of type `EP_WARP` ("Port Warp" / "Star Warp" —
   `sdk/Build/scripts/ships/Hardpoints/Galaxy.py:907,921,935`). BC's script gate
   checks only the former. Whether the C++ links them is unresolved — the
   clean-room reference timed out twice on 2026-09-22.
   **Default if unresolved:** gate warp on the nacelles as well, labelled
   explicitly as **our** behaviour change, not a fidelity fix.
2. **Vesuvi 5 and Beol 3 companion bodies** — moons, or separate worlds needing
   their own orbits? An authoring decision, taken per system in the overrides.
3. **Celestial-layer frame cost** — unmeasured until Ona runs.
4. **Orbit duration at large radii** — may need a `CircleObject` speed override;
   deferred until the live pass says so.

## Deliberately out of scope

- Sleeping or unloading distant regions (optimisation, needs a measurement first).
- Procedurally generated planet appearance (the identity/appearance split exists
  so this lands later without reworking the map format).
- Dash speed scaled by warp-engine condition.
- The tunnel's jump burst on dashes.
- Save/load of in-system position (save/load does not exist yet).
- Rewriting any campaign mission.
