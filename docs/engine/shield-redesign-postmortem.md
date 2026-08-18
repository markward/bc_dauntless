# Shield system redesign — post-mortem (ABANDONED 2026-08-18)

## Outcome

Implemented in full on `feat/shield-system-redesign`: 26 commits, spec + 12-task
plan, `scripts/check_tests.sh` green at every step. **Failed live testing.**
Mark's verdict after several in-game passes: behaviour ended up *further* from
stock BC than what it replaced.

Never merged. `main` is unaffected — the only shield-redesign artifacts on main
are the spec and plan, both now banner-marked ABANDONED.

The branch is retained, not deleted. It is the only record of the work and of
the reference findings below.

## What it tried to change

Replace the strict-cascade shield model with what `stbc_reference`
`spec/ShieldFacingDamage.md` describes:

- facing selected from where a shot's segment **enters** the shield ellipsoid
  (`ShipClass::TestHit` `0x005AE730`), not from the impact point
- absorption as a **pass-through ramp** rather than a strict cascade
- power-linked 0.5 s charge tick
- beam damage in 0.5 s dwell pulses

## Why it failed

The honest headline: **every stage was green, and the result was worse.** The
test suite could not see the thing that mattered.

1. **The gate is blind to this whole class of change.** Facing selection,
   splash placement, detonation distance, and flash cadence are all only
   observable in a running game. 26 commits passed the gate; the first live
   pass found the model visibly wrong. Green tests were never evidence here.

2. **Reference grading was ignored in practice.** `ShieldFacingDamage.md` is
   graded `reviewed-not-tested` **throughout** — every routine on the
   impact→facing→damage path was read from the binary, never executed. That was
   recorded in the spec and then treated as settled fact while building on top
   of it. A `reviewed-not-tested` chain is a hypothesis stack, not a
   foundation.

3. **Unsourced rulings entered the model as if they were findings.** The
   zeroing of `m_curShields` on power-off was mine, justified in a test
   docstring as "the honest approximation". The reference contradicts it
   outright (`SaveToStream` `0x56AB60` persists the array). At least one such
   ruling shipped per stage.

4. **Debugging chased symptoms across layers.** Five rounds, each ending in
   "this should fix it": classify/cascade mismatch → world-space hit storage →
   flash-vs-damage cadence → torpedo detonation surface. Each was a real
   defect; none restored the feel. That pattern — fixes that are individually
   correct and cumulatively wrong — is the signature of a wrong model, not a
   buggy one. It should have triggered a stop far earlier than it did.

5. **A quantitative claim was asserted from a misread log.** Impact log lines
   were read as per-frame when they were per-0.5 s-pulse, producing a "92% of
   each flash lives outside its bubble" figure that was wrong by ~30×. Caught
   and corrected, but only after it had justified a change.

## Findings worth keeping

These are independent of the redesign and survive it:

- **`ShieldClass` holds no geometry.** Object model (`sizeof 0x15C`) is six
  per-facing scalars + a combined fraction + `FloatRangeWatcher[7]`. The facing
  decision is necessarily made from hull geometry held elsewhere.
- **Shields are not zeroed when powered off.** `SaveToStream` (`0x56AB60`)
  persists `m_curShields[i]` per facing. The off-state is expressed by
  short-circuiting the *queries*: `IsShieldBreached` (`0x56A620`) returns true,
  `GetShieldPercentage` (`0x56A540`) returns 1.0.
- **Shield impacts must be stored in the ship's model frame.** Stored in world
  space they drift off the hull as the ship moves. (Fix is small and
  self-contained; salvageable independently — see `e8f6cc9d`.)
- **Our torpedo detonation surface is a bounding sphere; BC's is the shield
  ellipsoid.** `TestHit` *is* the collision test. On flat hulls the gap is
  large: a Marauder's sphere is ~2.6 GU against a 0.55 GU vertical bubble, so
  torpedoes detonate ~2 GU short of the shield and reach bare hull. **This gap
  exists on `main` today** and is independent of the redesign.
- **Facing index → name ("0 = front") remains unsourced.** No string table, no
  enum. Probe `tools/probes/q19_shield_facing_and_beam.py` is written and still
  unrun; it would settle it in minutes on the original game.

## If this is ever revisited

Do not restart from the plan. Start by establishing a **live baseline** of
current behaviour — recorded, not remembered — so "closer to BC" is measurable
rather than argued. Run the q19 probe first: it is cheap and it grounds the one
mapping everything else is built on.

Any single change should be live-verified before the next is written. The
failure mode here was a long green chain with no live checkpoint until the end.
