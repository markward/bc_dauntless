# In-system warp — one warp for every ship, the dash, the hand-off (design)

**Date:** 2026-09-25
**Status:** design approved in brainstorming; spec awaiting review. Not implemented.
**Branch:** `feat/system-frames` (the branch does not merge until this lands).
**Parent spec:** `docs/superpowers/specs/2026-09-24-system-frames-design.md`. This
document is the "detailed design" its §7 deferred. §7's rules **A, A′, H, C, D, N**
bind it and are restated where they apply; where this document refines one (the
timing of A′ during a dash, below) it says so.
**Depends on:** `docs/superpowers/specs/2026-09-25-warp-button-chain-and-mission-warps-design.md`,
built first. The survey for this plan found that **nothing sends
`ET_WARP_BUTTON_PRESSED` today** — the tunnel bypasses the mission handlers too —
so rule D's "mission chain" does not exist until that spec lands (Mark: build it,
option A). Every mention of the chain below means the chain as that spec builds it.

## Goal

A star system is one place you can cross. From any region you can reach any other
region of the same system in about ten seconds without the tunnel, or strike out
along your own heading into the space between. Crossing into a region's sphere
by any means hands you into that region, and every mission that keys on an
arrival still sees one.

## Decisions (Mark, in brainstorming)

| Question | Answer |
|---|---|
| How is an in-system warp started? | **Both**: Set Course to an in-system destination, and a Helm "Warp on Heading" entry that engages on the current nose. |
| How long does a Set Course dash take? | **~10 s flash to flash**, whatever the distance; speed follows from the path length. |
| Heading dash speed | One fixed speed, **~10,000 GU/s** (a neighbour hop in ~10 s). |
| Where does a Set Course dash end? | **At the destination's arrival placement, at rest** — exactly where the tunnel would have put you. |
| A body in the straight line | **Route around it** on a smooth curve. (Refusing the course was acceptable but would need new dialogue.) |
| A heading dash aimed at a body | **Automatic drop-out** at a safe standoff, flash only, no dialogue. |
| Exit speed, heading dash | Auto drop-out: **the impulse speed you engaged at**. Manual drop-out: **at rest**. |
| Controls | **Helm command only.** No keyboard engage. Drop out with the **0** key or **All Stop**. Ctrl+W's boost is removed. |
| Visuals | The real system, rushing past; the existing space-dust pass stretches into warp streaks. |
| NPCs | **Player only for now.** NPC in-system travel (flash only, vs full NPC dash) is the **immediate follow-up**. |
| Architecture | **One in-system warp for every ship**: extend `ShipClass.InSystemWarp` rather than build a player-only dash beside it. The AI gains routing and body drop-out too. |

## What exists today (measured in the tree)

- **Set Course → Warp** (`engine/host_loop.py` `record_course_selection` ~8228,
  `engage_warp` ~8163): `warp_gates.warp_gate` (`engine/appc/warp_gates.py:126`,
  the port of `HelmMenuHandlers.WarpPressed`'s checks), Helm-menu disable, then
  `warp.execute_warp` (`engine/appc/warp.py:901`) → `WarpSequence_Create(...).Play()`.
  Between two regions of one system this runs the full tunnel today: 8 s transit
  (`warp.py:45, 98-107`), then `_PlacePlayerAction` (`warp.py:430`) places the
  player at the arrival placement **at rest** (`warp.py:457-474`).
- **`ShipClass.InSystemWarp(target, distance)`** (`engine/appc/ships.py:710-838`),
  called by SDK `AI/PlainAI/Intercept.py:214`. Engages when facing within
  `IN_SYSTEM_WARP_FACING_COS` and beyond `distance`; one warp per
  `StopInSystemWarp` cycle (`_warp_consumed`); posts `ET_IN_SYSTEM_WARP` at start
  and end. Motion in `engine/appc/ship_motion.py:_step_in_system_warp`
  (~274-338): straight line at 100 × authored impulse max, rotation frozen,
  follows a moving target, exits at the pre-warp `_current_speed`. **Raw set-local
  positions** — never leaves its set's frame correctly.
- **Ctrl+W "in-system warp boost"** (`host_loop.py` `_PlayerControl`,
  `WARP_BOOST_FACTOR = 100`, toggle ~2788-2808): live in normal play, bypasses
  every warp check. Removed by this design.
- **BC expects the in-system warp to avoid obstacles.** `AI/Preprocessors.py:1690`
  skips AvoidObstacles while `IsDoingInSystemWarp()` "because the in-system warp
  check already does that". Routing is BC's contract for this call, not an
  invention.
- **BC's own region banner.** `Bridge/HelmMenuHandlers.py:383-408`
  (`ObjectEnteredSet`) shows "Entering <set>" when the player enters a set.
- **Nothing emits `ET_EXITED_WARP` / `ET_ENTERED_WARP`** today (only the
  generated constants exist). Nine missions hook `ET_EXITED_WARP`; 24 hook
  `ET_ENTERED_SET`, all name-keyed (audit in the superseded navigation spec,
  `worktree-system-navigation:docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`).
- **The space-dust pass** (`native/src/renderer/dust_pass.cc`) already smears
  along the camera's real velocity, capped at `kMaxSmearLength`; separately it
  has the tunnel's `u_warp_streak` drift/prism mode.

## Design

### 1. One in-system warp for every ship

`ShipClass.InSystemWarp` stays the SDK entry point and keeps its contract with
Intercept: engage once facing and beyond the drop distance; report active while
in progress (`IsDoingInSystemWarp`); one warp per `StopInSystemWarp` cycle;
`ET_IN_SYSTEM_WARP` on start and end. Underneath, `_step_in_system_warp` becomes
a small **warp flight** with four parts.

**Target.** A **destination** — a ship (Intercept; tracked live, the path
re-planned each tick toward its current position) or a fixed point (Set
Course: the placement; planned with no arrival direction since 2026-09-27 — the
arrival turn in §2 faces it afterwards) — or a **heading** (open-ended;
the heading dash).

**Path.** Planned in **system coordinates** (`frames.system_position` /
`frames.local_in`), so a warp that carries a ship out of its region's sphere
still aims correctly. A pure planner takes start, end (and, for a placement, the
arrival direction) and the obstacle bodies, and returns either a straight line or
**one smooth curve for the whole trip** that clears every obstacle by the
**comfort margin**. The obstacles are the system map's bodies in a mapped frame,
and the set's own `Planet`/`Sun` objects in an unmapped one. The destination's
own body is an obstacle too — the path reaches the placement, it does not pass
through the planet the placement looks at.

*Revised 2026-09-28 (Mark, live).* The first build routed the shortest
tangents-and-arcs path at the clearance margin; live it was "very tight around
the body and plays out like the planetary body has repelled us magnetically".
Mark: "set out on a heading which avoids the planet and then turn over the course
of the entire warp in order to make it look like a path we have plotted around
the object or objects". So:

- **Straight when unobstructed:** the line is kept exactly when it clears every
  body's comfort keep-out.
- **Otherwise one curve, bend spread over the whole trip.** A cubic Bézier from
  start to end whose inner control points sit at ⅓ and ⅔ of the chord, pushed
  off it along one perpendicular: both the same side is a bow (skewed toward the
  start or the end when the offsets differ), opposite sides an S-bend for bodies
  either side of the line. The ship sets off angled away from the obstacle(s) and
  bends gently and continuously to the end — no straight-then-tight-arc.
- **Least bend wins.** For each shape and perpendicular direction the least
  offset that clears **every** body is solved in closed form (progress along the
  chord is linear in the curve parameter, so each sampled point's "inside a
  body" offsets form one interval). Candidates are ranked by maximum curvature,
  then length, then a fixed table order (deterministic), and accepted only after
  a conservative 3D check against every body (polyline distance less the most
  the curve can sag from it, ≤ 0.25 GU). The horizontal perpendicular is tried
  alone first — the maps are flat, so a detour goes sideways in the map; tilted
  directions (30°…150°) only when it has no clear candidate. Offsets are capped
  at the chord length.
- **Multiple bodies are the norm:** every candidate is validated against all of
  them; tested with two on one side, two either side (S-bend), three, the real
  Ona 1 → Ona 3 (sun), the real Vesuvi Haven/Moon 1 overlapping pair, and a
  seeded 3D fuzz.
- **Comfort margin:** gap to the surface `max(radius, 4,000 GU)`
  (`COMFORT_MARGIN_MIN_GU`, `comfort_gu`). The R5 exemption carries over: a body
  whose margin sphere holds the start or the end is kept out of only halfway to
  that endpoint (and never less than the hard keep-out).
- **Fallback:** no smooth curve at the comfort margin → the same search at the
  hard **clearance margin** (`clearance_gu`, `comfort_kept` False) → the original
  routed planner (`smooth` False). The dash never enters a body.
- **Walked by arc length:** `point_at(s)` / `tangent_at(s)` go through an
  arc-length table (Hermite-inverted), so the speed policy and the drop edge
  are unchanged and the tangent is continuous.
- **AI flights (review of b80085ba).** The straight line to the target's
  **live drop point** is judged every tick with the planner's own keep-out test
  (`warp_path.line_clear`), with hysteresis: a curve hands over to the straight
  line once it keeps the comfort margin; the straight line holds while it keeps
  the hard clearance — so the two never alternate. Straight, the nose leads a
  moving target (intercept point) and the flight ends on the drop edge of the
  target **where it is** (Intercept relies on `SetInSystemWarpDistance`); a
  spent plan is re-planned, never "arrived at". Every re-plan pins the new
  curve's first tangent to the heading flown (`start_dir`) and **holds**: it
  keeps the hard clearance, or — already inside it — never comes more than
  0.5 GU closer than now (the R5 halfway exemption is for a trip's own start;
  re-applied per re-plan it halved the gap each time). A plan the pin cannot
  hold (target swung behind) is pivoted onto on the spot. Off a curve the nose
  turns at most `AI_WARP_TURN_RATE_RAD_S` (π rad/s, 3° a tick at 60 Hz). A
  target faster than the AI's warp that has already passed is not caught (as
  before).
- `end_dir` (arrive along a direction) still works through the routed planner;
  no caller passes it since the arrival turn (2026-09-27).

**Speed policy,** chosen by the caller:

| Caller | Speed |
|---|---|
| Player, Set Course | path length ÷ `DASH_TRIP_S` (10 s), clamped to [`DASH_MIN_GUPS`, `DASH_MAX_GUPS`] |
| Player, heading | `HEADING_DASH_GUPS` (10,000 GU/s) |
| AI Intercept | 100 × authored impulse max — **unchanged** (superseded 2026-09-28: BC's fixed 75 GU/s for every ship, measured in stbc-oracle `warp_*`; Mark: "helps us differentiate intercept from warping") |

"Flash to flash" is engage to drop-out; the Set Course align turn happens before
the engage flash and is not part of the 10 s.

**Exit,** by reason:

| Why the warp ended | Player | AI |
|---|---|---|
| Reached the destination | at rest, at the placement, facing its forward | pre-warp speed along the line (as today) |
| Body ahead (auto drop-out) | the impulse speed engaged at, on its heading | pre-warp speed |
| 0 key / All Stop | at rest | — |
| Death / control taken / `StopInSystemWarp` | as today's aborts | as today's aborts |

**Body drop-out** applies to every warp. The flight looks `DROP_LOOKAHEAD_S` (2 s)
of travel ahead; when a body that is not the destination lies on the line within
that distance, the warp ends at the **standoff**:

- a body that owns a region: the distance from the body's centre to **that
  region's arrival point** (its Player Start in system coordinates), measured on
  the line of approach — so you arrive at BC's own framing range, and the
  hand-off (§3) makes you part of that region **from any direction**: the
  arrival range is always inside the body's reach (§3). The arrival range is
  one function, `handoff.arrival_range`, read by both the drop-out and the
  hand-off so they cannot drift. (Starting inside a body's arrival range — R9
  — the standoff is radius + `clearance_gu` instead.) *Ruling R14 — cutting
  the standoff short so the drop point landed inside the region's sphere — is
  retired (Mark, 2026-09-28): the sphere sits on its Player Start side of the
  body, so R14 only half-worked (dead astern it had no solution and the
  player stopped beside the planet with no hand-off);*
- a body that owns no region (the star; an unmapped set's bodies): one body
  radius above the surface.

A Set Course path never triggers it: its route already clears every obstacle.

**Warp state.** The warp engine sits at `WES_WARPING` for the whole flight, so the
existing warp collision suppression and every SDK "is warping" check behave as
they do for the tunnel. The player's steering and throttle are locked; the AI's
rotation is already frozen.

*NPC warp state + parts hold (Mark, option A, 2026-09-28).* Until then the
"ai" flight set **no** `WES_*` state at all, so an NPC's articulated parts
(e.g. the LC Intrepid's wings, `SetTransitionSeconds(4.75)`) stayed in cruise
pose for the whole warp and it stayed collidable. Now an NPC signals warp and
waits for its parts before leaving, like the player's dash:

- At acceptance (`InSystemWarp` past its facing gate — `ET_IN_SYSTEM_WARP`
  True is posted there, unchanged), `warp_flight.begin_ai_warp` measures
  `t_parts = articulation.time_to_reach(ship, "warp") + TICK_DELTA`. Parts to
  move: `WES_WARP_INITIATED` and a **hold**; none: `WES_WARPING` at once, no
  hold.
- During the hold `warp_flight.step` returns False and `ship_motion` flies the
  ship's **own impulse orders** instead: the SDK's Intercept keeps calling
  `TurnTowardLocation` every update (so the nose stays on a moving target at
  the ship's normal turn rate) and skips its `SetSpeed` while `InSystemWarp`
  returns 1, so the ship **coasts on at the impulse speed it last ordered**
  along its nose — the heading dash's "cruise on at impulse" hold, not a stop.
  It never translates at warp speed. `InSystemWarp` keeps returning 1 and
  `IsDoingInSystemWarp()` is 1, so Intercept does not fight it and the SDK sees
  a warp in progress. A target lost or gone to another frame aborts the hold.
- The tick the hold completes: `WES_WARPING` and the flight exactly as before.
- Every end — arrival and each abort (`StopInSystemWarp`, `SetAI`/`ClearAI`/
  `CompleteStop`, death, target lost/left frame, the player taking the conn)
  — goes through `_end_in_system_warp`, which (`warp_flight.end_ai_warp`)
  returns an "ai" flight to `WES_NOT_WARPING`. No dewarp transition: the
  flight ends where the ship drops out, with no exit glide to cover (the dash
  does the same; the tunnel's `WES_DEWARP_ENDING` covers its exit-decel
  glide). The parts return to cruise by the articulation rule.
- Only the "ai" policy is managed there; the dashes (`set_course`, `heading`)
  keep managing their own state in `dash.py`. A **player on autopilot
  Intercept** flies an "ai" flight and so gets the NPC behaviour.
- Consequences for every NPC, rigged or not: it is **non-collidable** for the
  whole warp, hold included (`collisions` keys off `is_ship_warping`) — as the
  tunnel already makes a warping NPC from its align start
  (`WES_WARP_INITIATED`); SDK `GetWarpState` readers see it warping
  (`WarpSequence.py:638` skips it when clearing an arrival placement, since it
  has no warp sequence; `ConditionInRange` computes an unused radius;
  `HelmMenuHandlers`/E6M3 read the player only); `AvoidObstacles` and the
  science/helm menus key off `IsDoingInSystemWarp`, unchanged.

**Removed:** Ctrl+W's boost (`WARP_BOOST_FACTOR`, the toggle, and `GetTargetSpeed`'s
boost term) and the `ships.py` comment tying AI warp speed to it.

### 2. The player's two dashes

**Set Course → Warp.** Through the warp button chain unchanged — destination
picked, Warp pressed, the mission handlers, then the engine's final step
(`warp_gate`, the Helm-menu disable). At the point that step builds the warp,
one test:

- the destination region belongs to the **same mapped system** as the player's
  current region **and the warp names no mission or episode change** → **dash**
  (a mission change needs the transit, so it always takes the tunnel);
- anything else → the **tunnel**, unchanged (**rule C**: E6M1–E6M5 create ships
  during it).

The dash: **align** (the tunnel's existing cinematic turn, onto the path's first
direction) → **engage flash** → **~10 s** along the path → **drop-out flash** at
the arrival placement ("Player Start", or the placement Set Course chose), at
rest, **facing its travel direction**. The path is planned **without** an end
direction (straight, or routed around bodies only where their clearance needs
it), and the drop-out places the ship exactly on the placement's position but
does **not** snap its rotation. Then an **arrival turn**: the ship, still at
rest, turns onto the placement's rotation (forward `GetCol(1)`, up `GetCol(2)`)
at its impulse turn rate — the cap `_PlayerControl` flies manual turns at — and
the turn ends when aligned. Any steering or throttle input takes the conn back
at once and cancels it; so do an AI order, a new dash, a warp, death, a player
swap or a mission change. The tunnel's own arrival (`PlaceObjectByName`, which
snaps the rotation — BC behaviour) and Warp on Heading are unchanged. Every
mission's arrival *position* holds; its arrival *facing* is reached a moment
later unless the player overrides it. (Mark, live 2026-09-27: "I would prefer
the ship to exit warp and then turn to that spot at impulse so it doesnt look
wierd. the player can chose to shake out of it if they wish by overriding the
turn." This replaced the original design, which curved the path's end onto the
placement's forward so the ship arrived facing it without a snap.)

**Warp on Heading.** A new Helm entry beside Warp, with a project-authored label
(BC has no string for it). It sends the same `ET_WARP_BUTTON_PRESSED` through
the same chain and final `warp_gate` (**rule D**), with the button's destination,
mission and episode **cleared for the dispatch** and the plotted course restored
after it — so no handler acts on a stale course (E6M5's Beol 4 → Episode 7, E7M6's
Starbase 12 → Episode 8). Anything a handler sets on the button during that
dispatch is ignored by the heading dash. Actions handlers queue play at the
dash's matching points: before-warp at engage, the during queues in flight,
after-warp at drop-out. The survey's audit of all 26 handlers with no
destination: none crashes; E1M2 refuses silently, E6M1 answers "follow orders",
E8M2 counts it as leaving Omega Draconis (game over after three) — each the
mission's own rule, now enforced.
No align: engage flash, then the heading dash until drop-out. Greyed out
whenever a mission has disabled Helm > Set Course (ruling R15: missions hold
the player that way — E1M1, E1M2, E3M1). Offered in mapped and unmapped sets
alike — *amended 2026-09-27, Mark's call after a live pass (greyed in
QuickBattle's placeholder set): features are consistent everywhere.* An
unmapped set dashes on its own `Planet`/`Sun` objects, has no regions and so
no hand-off, and drops out at 2 × radius from a body ahead.

**The parts hold (either kind; 2026-09-28).** A ship with articulated parts
(e.g. a mod's warp-folding wings, `SetTransitionSeconds`) must have them settled
in their warp pose *before* the engage, which is the visible jump. So when
`articulation.time_to_reach(player, "warp")` is non-zero the dash enters
`WES_WARP_INITIATED` at the press (as the tunnel does at its align start),
which starts the parts folding. A Set Course dash turns at its normal rate —
the turn is never slowed to absorb the wait — then holds aligned and at rest
until `time_to_reach + TICK_DELTA` has elapsed from the press (the parts start
on the tick after the state flips), then engages (`WES_WARPING`, flight,
flash); parts that settle before the turn ends add no hold. A heading dash has
no align: it cruises on at its engaged impulse speed, controls locked, for the
same wait, then engages. Unlike the tunnel there is no `_T_ENTER_BOOST` term:
the dash is at full speed from its first flight tick. 0 / All Stop / death /
player swap during the hold cancel it like an align-phase cancel — queues back
on the button, `WES_NOT_WARPING`, Helm restored (a cruising heading hold stops
at rest) — and the parts return to cruise by the ordinary articulation rule.
The ~10 s flash-to-flash is unchanged: the hold is all before the engage. A
ship with no parts (`time_to_reach == 0`) is exactly as before: it stays
`WES_NOT_WARPING` through the align and engages at its end (or, heading, at
the press).

**While dashing (either kind):**

- **0** or **All Stop** drops out at rest, with the flash. All Stop is the one
  Helm entry left enabled.
- Warp, Warp on Heading, Set Course, Orbit, Intercept and Dock are disabled, and
  re-enabled on drop-out — the dash's counterpart of BC disabling the Helm menu
  in warp.
- Impulse keys 1–9 and steering are inert.
- The helm acknowledgement is whatever the Warp button plays today; Warp on
  Heading reuses it. No new dialogue.

### 3. The hand-off

**What it does (rule A).** The player moves from region A's set into region B's:
rotation and velocity unchanged (all regions share the system's axes); set-local
position rebased by the anchor difference,
`local_B = local_A + offset_between(B, A)`, so **`system_position` is identical
before and after**. The move is the ordinary `RemoveObjectFromSet` /
`AddObjectToSet`, so `ET_EXITED_SET` / `ET_ENTERED_SET` fire as they already do
and BC's own handler puts up "Entering Ona 2". The player's target is cleared,
as tunnel arrival does today (`_ArrivalClearTargetsAction`) — weapons still fire
within one set only, so a target left in the old set could not be engaged. The
widening plan lifts this.

**Only the player** is ever handed off (**rule N**).

**When:**

- **Containment (Mark, 2026-09-28: arriving near a planet from ANY direction
  counts as entering its region).** A region contains the player's system
  position when it is inside the region's sphere (`anchor_gu`, `radius_gu`)
  **or** within `reach(body) = arrival_range(body) + HANDOFF_MARGIN_GU` of the
  centre of any body the region owns (map `Body.owner_region`), where
  `arrival_range` is the distance from the body's centre to the region's
  Player Start in system coordinates (`handoff.arrival_range`, shared with §1's
  body drop-out) — or `2 × radius + HANDOFF_MARGIN_GU` when that region's set
  is not loaded. The sphere alone sits on its Player Start side of the body,
  so an approach from the far side used to stop beside the planet but outside
  its region: no banner, no arrival beats. Where two regions both contain a
  point, the one whose nearest shape centre (sphere anchor or owned body) is
  closest wins, ties to the lower set name.
- **At impulse:** the moment the player's system position is contained by
  another region. **Rule H:** the player stays in the current set until beyond
  its radius + `HANDOFF_MARGIN_GU` of its sphere **and** beyond
  reach + `HANDOFF_MARGIN_GU` of every body it owns, **and** inside another
  region (by the containment above). There is still no "space set" — in the
  open you stay in the region you left.
- **During a dash: deferred to drop-out.** Passing through a sphere mid-dash does
  nothing; at drop-out the player is handed off to whichever region contains
  them. Arrival means where you stop, not what you fly through — otherwise an
  Ona 1 → Ona 3 crossing that grazed Ona 2's sphere would flash "Entering Ona 2"
  and could fire Ona 2's arrival beats (24 missions key `ET_ENTERED_SET` on the
  set name).

**`ET_EXITED_WARP` (rule A′), refined.** The player gets `ET_EXITED_WARP`:

- after every impulse hand-off (A′ as written), and
- at every dash drop-out, **after** any hand-off that drop-out causes — including
  a drop-out in open space or inside the region you started in, mirroring tunnel
  arrival.

Order at a drop-out into a new region: `ET_EXITED_SET`, `ET_ENTERED_SET`,
`ET_EXITED_WARP`. The nine hooks read `player.GetContainingSet().GetName()`, so
the set must already be the new one when `ET_EXITED_WARP` fires.
`ET_ENTERED_WARP` stays unemitted (no mission hooks it; recorded, not built).

### 4. What you see and hear

- **The real system, drawn as normal.** Nothing hidden, no sky re-projection: a
  crossing is nothing at galaxy scale, so the starfield stays put. The render
  origin keeps everything steady at dash speed.
- **Streaks from the existing dust.** During a dash the host pushes a 0–1 dash
  intensity that raises the dust pass's smear cap (`kMaxSmearLength`), so the
  dust stretches along the real travel direction. The tunnel's `u_warp_streak`
  drift/prism mode is **not** used. The raised cap is a live-tuned constant; the
  origin-aware motion-blur pass gets the same treatment if the live pass wants it.
  The per-frame dust draw count is also scaled down to 20% of the location's
  normal count while dashing (`dash_density_factor`, `kDashDustDensity` in
  `dust_pass.h`), applied after the sun/planet proximity multiplier — fewer,
  longer streaks rather than a dense smear.
- **Flash:** the tunnel's existing screen flash on engage and drop-out. The
  tunnel's "jump burst" is not used.
- **Nacelle glow:** the existing warp glow spools during align/engage and holds.
- **Sound:** "Enter Warp" and "Exit Warp" are played **attached to the ship**
  (`warp._play_attached` → `TGSound.Play(attach_node=ship.GetNode())`), as BC
  attaches both (`WarpSequence.py:79-89, 285-297`:
  `pWarpSoundAction.SetNode(pShip.GetNode())`). Both are loaded `LS_3D`
  (`LoadTacticalSounds.py:79-80`), so an unattached play is pinned where it
  started, and the dash is thousands of GU away by the crack — Mark, live: the
  wind-down was heard, the crack was not. "Enter Warp" has a **1.5 s pre-roll**
  (`warp._SFX_ENTER_FLASH_AT`, where its crack sits in the clip): it starts that
  long before the engage, as BC starts it at `fEntryDelayTime - 1.5`, so the
  crack lands on the engage flash. The engage is therefore never sooner than
  1.5 s after the press — engage = max(align, parts hold, 1.5 s). A Set Course
  dash holds aligned for any remainder; a heading dash cruises at its impulse
  speed through it (the parts-hold mechanism), then engages. A stop, death or
  player swap before the engage cancels as during the align, and stops "Enter
  Warp" if it has started. "Exit Warp" at drop-out. The tunnel's
  `_WarpSoundAction` attaches both sounds to the warping ship too, player or
  NPC. Weapon loops silenced while dashing, as the tunnel does.
- **Camera:** the chase camera stays on the ship, with the tunnel's align turn-in.
  No cinematic cut.

## Tunables (starting values; each named in one place)

| Name | Start | Meaning |
|---|---|---|
| `DASH_TRIP_S` | 10.0 | Set Course engage → drop-out |
| `DASH_MIN_GUPS` / `DASH_MAX_GUPS` | 2,000 / 100,000 | Set Course speed clamp |
| `HEADING_DASH_GUPS` | 10,000 | heading dash speed |
| `DROP_LOOKAHEAD_S` | 2.0 | how far ahead body drop-out looks, in travel time |
| comfort margin (`COMFORT_MARGIN_MIN_GU`) | body radius, min 4,000 GU | the smooth curve's gap to a body's surface |
| clearance margin | 0.25 × body radius, min 2,000 GU | the hard minimum gap (fallbacks) |
| `HANDOFF_MARGIN_GU` | 1,500 | rule H exit margin (matches `LayoutTuning.region_margin_gu`) |
| dust dash smear cap | live-tuned | streak length at full dash |

## Testing

**In the gate (`scripts/check_tests.sh`):**

- **Planner (pure):** straight line when clear; a curve clears every body by the
  margin; the planner can still end a path along an arrival direction
  (`end_dir`), though Set Course no longer asks it to (§2's arrival turn);
  Set Course speed gives ~10 s within the clamps; on the real Ona map,
  Ona 1 → Ona 3 routes around the sun (the straight line passes ~4,350 GU from
  the sun's centre, inside its 10,000 GU radius).
- **One warp:** Intercept's contract holds — facing gate, one warp per cycle,
  `ET_IN_SYSTEM_WARP` start/end, pre-warp exit speed. Existing tests pinning
  today's straight line are updated **by name in the plan**, never silently.
  Frame-aware positions leave an AI warp inside one unmapped set behaving
  exactly as today.
- **Body drop-out:** a heading dash at Ona 2 stops at Ona 2's arrival range on
  its line, is handed off to Ona 2 and keeps the engaged impulse speed; a heading
  dash at the star stops one radius above it; an AI warp is routed around a
  planet in its path and never drops out (ruling R2).
- **Hand-off:** `system_position` identical before and after; event order
  `ET_EXITED_SET`, `ET_ENTERED_SET`, `ET_EXITED_WARP`; no flicker circling a
  sphere's or a reach's edge; an approach from a planet's far side (outside its
  region's sphere, within its reach) hands off; overlapping containments pick
  the nearest; deferred during a dash (through Ona 2 to Ona 3: no event, no
  banner); an NPC is never handed off; target cleared.
- **Rule C:** a Set Course to another system still runs the tunnel; E6M1's
  in-tunnel ships exist on arrival.
- **Rule D:** the gate refuses both dashes with engines disabled / off /
  unpowered or in a nebula; a mission swallowing `ET_WARP_BUTTON_PRESSED` aborts
  both; **all 26 handlers are audited** against an event with no destination.
- **Controls:** 0 and All Stop drop out at rest; 1–9 and steering inert; Helm
  entries disabled and restored; Warp on Heading greyed while Set Course is
  disabled (enabled in an unmapped set — amended 2026-09-27);
  Ctrl+W is gone.
- **End to end, headless:** Ona 1 → dash → Ona 2 → dash → Ona 1. At each stop the
  draw list is the system's bodies, the player is in the right set, at the
  arrival placement, at rest.

**Live (Mark):** a flight guide with timings — both dashes, Ona 1 → Ona 3 past
the sun, a heading dash at a planet, an impulse crossing from a spot placed near
a boundary, and the dust streak strength tuned by eye.

## Risks

- **Warp on Heading reaching mission handlers with no destination** — the audit
  is the mitigation.
- **Arrival event order** — the nine `ET_EXITED_WARP` missions read the
  containing set; the order test pins it.
- **Frame-aware AI warps in unmapped sets** must be byte-identical to today.

## Follow-ups

1. **Immediately after:** NPC in-system travel — **B** (NPC warp flashes,
   including `CreateShip(..., iWarpFlash=1)` arrivals) vs **C** (NPCs dash
   between regions through real space, reopening rule N). **Still open**
   after option A (2026-09-28), which settled only the warp state and parts
   hold of the in-region AI warp, not how NPCs travel between regions.
2. The widening plan (system-frames Plan 4): frame-aware target list, weapons,
   perception, cameras — which also lifts the target-clear on hand-off.

## Deliberately out of scope

- Dash speed scaled by warp-engine condition.
- NPC hand-off (rule N).
- New dialogue.
- Persistence of in-system position (save/load does not exist yet).
- `ET_ENTERED_WARP` emission.
