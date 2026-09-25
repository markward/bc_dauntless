# In-system warp — one warp for every ship, the dash, the hand-off (design)

**Date:** 2026-09-25
**Status:** design approved in brainstorming; spec awaiting review. Not implemented.
**Branch:** `feat/system-frames` (the branch does not merge until this lands).
**Parent spec:** `docs/superpowers/specs/2026-09-24-system-frames-design.md`. This
document is the "detailed design" its §7 deferred. §7's rules **A, A′, H, C, D, N**
bind it and are restated where they apply; where this document refines one (the
timing of A′ during a dash, below) it says so.

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
re-planned each tick toward its current position) or a fixed point with an
arrival direction (Set Course: the placement) — or a **heading** (open-ended;
the heading dash).

**Path.** Planned in **system coordinates** (`frames.system_position` /
`frames.local_in`), so a warp that carries a ship out of its region's sphere
still aims correctly. A pure planner takes start, end (and, for a placement, the
arrival direction) and the obstacle bodies, and returns either a straight line or
a smooth curve that clears every obstacle by the **clearance margin**. The
obstacles are the system map's bodies in a mapped frame, and the set's own
`Planet`/`Sun` objects in an unmapped one. The destination's own body is an
obstacle too — the path reaches the placement, it does not pass through the
planet the placement looks at.

**Speed policy,** chosen by the caller:

| Caller | Speed |
|---|---|
| Player, Set Course | path length ÷ `DASH_TRIP_S` (10 s), clamped to [`DASH_MIN_GUPS`, `DASH_MAX_GUPS`] |
| Player, heading | `HEADING_DASH_GUPS` (10,000 GU/s) |
| AI Intercept | 100 × authored impulse max — **unchanged** |

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
  the line of approach — so you arrive inside the region's sphere at BC's own
  framing range, and the hand-off (§3) makes you part of it;
- a body that owns no region (the star; an unmapped set's bodies): one body
  radius above the surface.

A Set Course path never triggers it: its route already clears every obstacle.

**Warp state.** The warp engine sits at `WES_WARPING` for the whole flight, so the
existing warp collision suppression and every SDK "is warping" check behave as
they do for the tunnel. The player's steering and throttle are locked; the AI's
rotation is already frozen.

**Removed:** Ctrl+W's boost (`WARP_BOOST_FACTOR`, the toggle, and `GetTargetSpeed`'s
boost term) and the `ships.py` comment tying AI warp speed to it.

### 2. The player's two dashes

**Set Course → Warp.** Unchanged up to the moment it would build the tunnel:
destination picked, Warp pressed, `warp_gate`, the mission
`ET_WARP_BUTTON_PRESSED` chain, the Helm-menu disable. Then one test:

- the destination region belongs to the **same mapped system** as the player's
  current region → **dash**;
- anything else → the **tunnel**, unchanged (**rule C**: E6M1–E6M5 create ships
  during it).

The dash: **align** (the tunnel's existing cinematic turn, onto the path's first
direction) → **engage flash** → **~10 s** along the path → **drop-out flash** at
the arrival placement ("Player Start", or the placement Set Course chose), at
rest. The path is planned to **arrive along the placement's forward direction**,
so the ship ends where and facing where the tunnel would have put it, without a
snap. Every mission's arrival geometry holds.

**Warp on Heading.** A new Helm entry beside Warp, with a project-authored label
(BC has no string for it). It runs the same `warp_gate` and the same mission
`ET_WARP_BUTTON_PRESSED` chain (**rule D**); the event carries no destination.
No align: engage flash, then the heading dash until drop-out. Greyed out in an
unmapped set.

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

- **At impulse:** the moment the player's system position enters another
  region's sphere. **Rule H:** the player stays in the current set until beyond
  its radius + `HANDOFF_MARGIN_GU` **and** inside another region's sphere. There
  is still no "space set" — in the open you stay in the region you left.
- **During a dash: deferred to drop-out.** Passing through a sphere mid-dash does
  nothing; at drop-out the player is handed off to whichever region's sphere they
  are in. Arrival means where you stop, not what you fly through — otherwise an
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
- **Flash:** the tunnel's existing screen flash on engage and drop-out. The
  tunnel's "jump burst" is not used.
- **Nacelle glow:** the existing warp glow spools during align/engage and holds.
- **Sound:** "Enter Warp" timed to the engage flash, "Exit Warp" at drop-out;
  weapon loops silenced while dashing, as the tunnel does.
- **Camera:** the chase camera stays on the ship, with the tunnel's align turn-in.
  No cinematic cut.

## Tunables (starting values; each named in one place)

| Name | Start | Meaning |
|---|---|---|
| `DASH_TRIP_S` | 10.0 | Set Course engage → drop-out |
| `DASH_MIN_GUPS` / `DASH_MAX_GUPS` | 2,000 / 100,000 | Set Course speed clamp |
| `HEADING_DASH_GUPS` | 10,000 | heading dash speed |
| `DROP_LOOKAHEAD_S` | 2.0 | how far ahead body drop-out looks, in travel time |
| clearance margin | 0.25 × body radius, min 2,000 GU | a routed path's gap to a body's surface |
| `HANDOFF_MARGIN_GU` | 1,500 | rule H exit margin (matches `LayoutTuning.region_margin_gu`) |
| dust dash smear cap | live-tuned | streak length at full dash |

## Testing

**In the gate (`scripts/check_tests.sh`):**

- **Planner (pure):** straight line when clear; a curve clears every body by the
  margin; a placement path ends at the placement arriving along its forward;
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
  dash at the star stops one radius above it; an AI warp stops short of a planet
  in its path.
- **Hand-off:** `system_position` identical before and after; event order
  `ET_EXITED_SET`, `ET_ENTERED_SET`, `ET_EXITED_WARP`; no flicker circling a
  sphere's edge; deferred during a dash (through Ona 2 to Ona 3: no event, no
  banner); an NPC is never handed off; target cleared.
- **Rule C:** a Set Course to another system still runs the tunnel; E6M1's
  in-tunnel ships exist on arrival.
- **Rule D:** the gate refuses both dashes with engines disabled / off /
  unpowered or in a nebula; a mission swallowing `ET_WARP_BUTTON_PRESSED` aborts
  both; **all 26 handlers are audited** against an event with no destination.
- **Controls:** 0 and All Stop drop out at rest; 1–9 and steering inert; Helm
  entries disabled and restored; Warp on Heading greyed in an unmapped set;
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
   between regions through real space, reopening rule N).
2. The widening plan (system-frames Plan 4): frame-aware target list, weapons,
   perception, cameras — which also lifts the target-clear on hand-off.

## Deliberately out of scope

- Dash speed scaled by warp-engine condition.
- NPC hand-off (rule N).
- New dialogue.
- Persistence of in-system position (save/load does not exist yet).
- `ET_ENTERED_WARP` emission.
