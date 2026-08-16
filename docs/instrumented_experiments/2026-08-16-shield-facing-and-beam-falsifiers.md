# Shield facing names + the beam-sweep hull hit — two falsifiers

## Status

**Probe written, NOT YET RUN.** Awaiting an operator run on the original game.
Findings section is empty by design — do not fill it from reasoning.

## Goal

Convert two claims from *read* evidence to *tested* evidence. Both come from
`stbc_reference` `spec/ShieldFacingDamage.md`, which is graded
`reviewed-not-tested` throughout: every routine on the impact→facing→damage path
is **unreconstructed** — read from the original image, never executed. The
document says so itself and offers both falsifiers below.

These are the two cheapest open questions on that path, and both are answerable
in the original game in minutes.

## Background

`ShieldFacingDamage.md` establishes that the facing chooser is
`ShipClass::TestHit` (`0x005AE730`), that it takes the signed dominant axis of
the point where the shot's segment **enters** the shield ellipsoid, and that the
axis → index mapping is:

| Scan entry | Body axis | Facing index |
|---|---|---|
| 0 | `+y` | 0 |
| 1 | `+z` | 2 |
| 2 | `+x` | 5 |
| 3 | `−y` | 1 |
| 4 | `−z` | 3 |
| 5 | `−x` | 4 |

That table is measured. **What is NOT established is the mapping from index to
the words front/rear/top/bottom/left/right** — no string table, no enum, no
constant names them. `ShieldClass.md` §1 asserts an order as prose without a
source, and §0.2 item 1 of `ShieldFacingDamage.md` explicitly flags it as "an
unsourced convention, not a finding".

Our engine hard-codes that convention in `ShieldSubsystem`'s class constants and
in `engine/appc/combat.py:_shield_face_from_hit_point`. If it is wrong, every
shield readout and every hit flash is mirrored or rotated, and nothing in our
test suite would notice — the tests assert the same convention they encode.

## Specific questions

**Q1 — Which facing index takes a hit from a known aspect?**
Fire on a known aspect of a target (nose first) and observe which of the six
indices loses charge. Repeat for a second aspect (dorsal) to pin a second axis.
Two aspects are enough: the axis table above then determines the rest, because
the mapping is a fixed permutation, not six independent facts.

**Q2 — Does a beam swept off target mid-pulse land on the HULL at full shields?**
`ShieldFacingDamage.md` §12.5(a): `ApplyWeaponHit` consumes the facing index and
resets `ShipClass+0x240` to `-1`. The damage flush also runs on the target-lost
and target-changed paths, where no `TestHit` has run against that target that
frame. A flush with no intervening test therefore reads `-1` and takes the **hull
branch** — full damage to hull and subsystems, `IsHullHit` set — *regardless of
shield charge*.

If true, a beam swept off a fully-shielded target deals hull damage on its
trailing partial pulse. That is a real, exploitable combat behaviour, and we
would have to decide deliberately whether to reproduce it.

## The probe — `tools/probes/q19_shield_facing_and_beam.py`

Approach 2 (dev-console), per `console-probe-workflow.md`.

The probe is a **snapshot**, run twice with an operator action between. It
records, for the current target:

- all six facings' `GetCurShields` and `GetSingleShieldPercentage`, plus
  `GetMaxShields` to normalise;
- both `IsShieldBreached` and `IsShieldDamaged` per facing — the spec says these
  two can legitimately disagree (one is computed from charge, the other reads a
  raw byte), so recording only one would hide that;
- the target's world position, world-rotation columns, and radius, and the
  player's world position.

That last group matters. **The facing index is meaningless without the approach
aspect in the target's body frame**, and an operator's "I was in front of it" is
not good enough to distinguish `+y` from `+z` on a hull that is 4–8× longer than
it is tall. Recording the rotation columns lets the aspect be computed offline
from the data rather than trusted.

All six indices are recorded every time, never just the expected one — the whole
question is which index moves.

## How to run

1. Launch `stbc.exe -TestMode`. Start a Quick Battle in a ship with phasers.
2. Acquire a target with **Tab**. Let its shields sit at **full**.
3. **Q1, nose aspect.** Manoeuvre to the target's bow, holding fire.
   - `execfile('q19_shield_facing_and_beam.py')` → run A.
   - Fire **one short phaser burst**. Keep it short: facings regenerate at
     roughly 6.7 pts/s, so a long burst muddies which index moved.
   - `execfile('q19_shield_facing_and_beam.py')` → run B.
   - Collect both `.cfg` files before continuing (the probe scrubs its keys).
4. **Q1, dorsal aspect.** Repeat step 3 from directly above the target.
5. **Q2, the sweep.** With the target back at full shields, hold a phaser beam
   on it and **sweep off target mid-burst** (turn away, or break lock) so the
   final pulse flushes after the beam has left. Run the probe immediately after.

`collect.py` for each run; commit the results to `tools/probes/results/`.

## Expected output

`[BCProbe_q19]` with `n` lines, `r0..r{n-1}`.

**Q1.** Exactly one index's `cur[]` should fall between run A and run B. Under
our current convention a bow-on hit gives index **0** and a dorsal hit index
**2**. Either confirms the convention; anything else refutes it and tells us
which permutation is real.

**Q2.** After the sweep, `cur[]` on the struck facing should be *unchanged from
its pre-sweep value* for the trailing pulse while the **hull** condition drops.
Hull damage with all six facings still holding confirms §12.5(a).

## Analysis

- **Q1 confirms** → record it as tested and stop treating the name order as
  unsourced. **Q1 refutes** → our shield constants, the HUD facing map, and the
  hit-flash gating are all mirrored, and that is a real live bug found cheaply.
- **Q2 confirms** → an unshielded-damage window exists on every beam sweep.
  Decide deliberately whether to reproduce it; it is faithful, but it is also
  the kind of behaviour a player would call a bug.
- **Q2 does not reproduce** → the flush may not be reachable that way in
  practice. Record as "not observed", **not** as "the spec is wrong" — a
  behaviour we failed to trigger is not a behaviour that does not exist.

## Cleanup

The probe scrubs its own `[BCProbe_q19]` keys after each save, so `Options.cfg`
stays clean. No game files are modified; no `tools/setup.py` install is needed
(Approach 2 needs no `App.py` snippet).

## Findings

*(empty — probe not yet run)*
