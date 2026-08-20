# RE request — `DamageRadiusFactor` and subsystem damage attribution

**Requested output:** a new document in the `stbc_reference` corpus, suggested
path `spec/WeaponDamageRadius.md`, answering the questions in §3 with the usual
per-claim evidence grades (`tested` / `reviewed-not-tested` / `stub` /
`unreconstructed`). Explicit "unknown" is a useful answer; a plausible
reconstruction presented without a grade is not.

---

## 1. The decision this blocks

Dauntless shows noticeably less subsystem damage in play than stock BC does.
We want to know whether our reading of `DamageRadiusFactor` is the cause before
we change any numbers, because every alternative we can think of is a guess.

## 2. What Dauntless currently does, so you can see where we may have gone wrong

`engine/appc/combat.py`:

```python
def weapon_splash_radius(hardpoint_weapon, payload_template) -> float:
    # hardpoint DamageRadiusFactor, else payload DamageRadiusFactor,
    # else 0.15 (our phaser default). Returned AS A WORLD-SPACE RADIUS
    # in game units, used unscaled.
```

That value (`r_hit`) is then used as a sphere radius. A subsystem is damaged
when

```
d < r_sub + r_hit
```

where `d` is the distance from the impact point to the subsystem's world
position and `r_sub` is the subsystem's own `GetRadius()` from the hardpoint
file. Until today we also scaled the damage by a linear falloff across that
band; we have just changed it to give every overlapping subsystem the full
damage (see Q4).

Concrete values we are using: photon `DamageRadiusFactor` 0.13, phaser 0.15,
in game units where 1 GU = 175 m. Galaxy subsystem radii from
`sdk/Build/scripts/ships/Hardpoints/galaxy.py` run 0.20 to 1.20, mean 0.34.

**Measured consequence.** Sampling 200,000 impact points uniformly over a
Galaxy's hull AABB (half-extents 2.32 x 3.22 x 0.70 GU), against the 34
subsystems in that hardpoint file that carry both a position and a radius:

| | phaser (`r_hit` 0.15) | photon (`r_hit` 0.13) |
|---|---|---|
| hits overlapping **no** subsystem | 58.2% | 59.5% |
| mean subsystems overlapped | 0.64 | 0.60 |

So under our reading, most weapon hits on a Galaxy damage no subsystem at all.
That is the number we suspect is wrong.

## 3. Questions

**Q1 — Where does `DamageRadiusFactor` live, and what reads it?**
Field offset on `WeaponProperty` (and on the projectile/payload template if
they differ), its accessor, and the list of routines that read it. We reach it
through the SWIG surface as `GetDamageRadiusFactor()` and have never seen the
engine side.

**Q2 — Is it a RADIUS or a FACTOR?**
This is the question we care most about. We treat the returned value as an
absolute world-space radius in game units and use it unscaled. The field name
says *Factor*, which would suggest it multiplies something else — the target's
radius, the weapon's damage, a per-weapon base radius, a global constant. If it
is a multiplier, what is the multiplicand, and where does the base value come
from? A dimensionless 0.13 multiplying something would explain our 58%
no-overlap rate directly.

**Q3 — What is the subsystem damage-attribution routine, and what geometry does
it use?**
Name and address, and the actual test. Specifically: is it a sphere/sphere
overlap using the subsystem's own radius (as we assume), a sphere/point test
that ignores the subsystem radius, a test against subsystem *bounding
geometry*, or something else entirely? If the subsystem radius is not part of
the test, what is it for — targeting pick, HUD, something else?

**Q4 — Within the radius, does damage fall off with distance?**
We just switched from a linear distance weight to "every overlapping subsystem
takes the full damage and residuals sum", on the strength of a line in
`spec/ShieldFacingDamage.md` graded `reviewed-not-tested`. Our own probe q05 is
recorded as non-discriminating between the two models. A graded answer either
way would settle it, and we will revert if we have it backwards.

**Q5 — Is the same radius used for functional damage and for visible damage?**
`DamageTool` authors visible damage as metaball volumes
(`MetaVolume(pos, influRad, strength)`, tiers 0.4/300 and 1.0/600). Those radii
are in the same numeric range as `DamageRadiusFactor` but are clearly a
different system. Does the subsystem-damage path read `DamageRadiusFactor`, the
metaball `influRad`, or a third field?

**Q6 — Units.**
Are `DamageRadiusFactor` and the hardpoint `SetRadius` values in the same space
as hardpoint `SetPosition` coordinates? We assume all three are game units and
directly comparable, which is what makes the §2 arithmetic meaningful. If
positions and radii are in different spaces, that alone could be the bug.

## 4. Anchors already in the corpus

Possibly adjacent, to save re-deriving:

- `ShipClass::TestHit` `0x005AE730` — the shield-facing chooser; runs at
  collision-detection time and leaves the facing in `ShipClass+0x240` for
  `ApplyWeaponHit` to consume. `ApplyWeaponHit` is presumably on or near the
  path we are asking about.
- `ComputeShieldEllipsoid` `0x005ABAC0` — bubble semi-axes = model bound
  half-extents x sqrt(3).
- `spec/ShieldFacingDamage.md` — graded `reviewed-not-tested` throughout;
  source of the Q4 claim.
- The `DamageTool` metaball notes behind Q5.

## 5. What we will do with each answer

- **Q2 says "factor"** → we rewrite `weapon_splash_radius` around the real
  multiplicand. This is the outcome we consider most likely and it would
  plausibly close the whole gap on its own.
- **Q2 says "absolute radius" and Q3 confirms sphere/sphere with `r_sub`** →
  our geometry is right, the scarcity is authored, and we stop looking here.
- **Q3 says the subsystem radius is not part of the test** → our overlap set is
  wrong in a way no tuning would fix.
- **Q4 contradicts us** → we revert today's change (commit `28145a2a`).
