# Shield system redesign — facing, absorption, cadence

*Design spec. 2026-08-16.*

## 1. Why

`stbc_reference` `spec/ShieldFacingDamage.md` (2026-08-16) documents BC's
impact→facing→damage path end to end for the first time. It establishes that our
shield model diverges from the original in four places, one of which — absorption —
we had recorded as *verified* on the strength of a probe that only ever measured
the regime where the divergence vanishes.

This spec redesigns the shield system around what that document establishes, and
cleans up the structure while we are in there.

### Evidence grade — read this before trusting any number below

**Every routine on BC's shield path is `reviewed-not-tested`: read from the
original image, never executed.** The reference says so per-routine and leads with
it. Every constant in this spec inherits that grade.

The single exception is the anchor in §11: probe q04 measured **exactly 0.0** hull
damage with all facings full. That is tested evidence, and the new model must
reproduce it.

We are implementing on read-evidence deliberately (decision 3 below), with a live
pass afterwards. If live play contradicts this spec, the spec is wrong, not the
game.

## 2. Decisions taken

| # | Decision | Consequence |
|---|---|---|
| 1 | **Faithful model, corrected defects** | Implement BC's mechanics; fix what is evidently broken. No quirk flags. |
| 2 | **Scope: shields + shared cadence** | Facing, absorption, charge cadence, beam pulsing, splash. Hull/subsystem distribution explicitly deferred. |
| 3 | **Implement now, validate live after** | Ship against the spec; correct from the live pass. |
| 4 | **Approach A — extract a shields module** | Two pure units + one stateful ticker; `apply_hit` shrinks to routing. |
| 5 | **Keep skin shielding, separate the concerns** | Gameplay geometry is the ellipsoid for every ship; skin is visual only. |

## 3. Architecture

Three new modules and one shrunken caller.

```
shield_geometry.py    pure   ellipsoid + facing-from-segment
shield_absorption.py  pure   the pass-through ramp
beam_dwell.py         state  0.5 s pulse accumulator
ShieldSubsystem       state  charge, fraction, 0.5 s charge quantum
combat.apply_hit      glue   resolve facing -> absorb -> route -> feedback
```

The two units most likely to be *wrong* — the ramp curve and the facing geometry —
are pure functions. Being wrong there is cheap to detect and cheap to correct after
the live pass. That is the point of the split, not tidiness.

`apply_hit` today is ~200 lines with eight keyword flags doing cheats, immunity,
facing, shields, hull, subsystems, feedback and event broadcast. It keeps the
routing and loses the shield maths.

## 4. Geometry — `engine/appc/shield_geometry.py`

### 4.1 The ellipsoid

Frozen value type: body-frame `centre` and `semi_axes`.

```
semi_axes = model_bound_half_extents * sqrt(3) * node_scale
centre    = model_bound_centre * node_scale
```

Per `ComputeShieldEllipsoid` (`0x005ABAC0`): the **first cloned model's** bound,
half-extents scaled by √3, recentred on the bound centre. Recomputed only when the
model changes, never per frame.

**This becomes the single source of truth for the shield shape.** Today √3 lives in
the renderer as `kShieldEllipsoidAxisScale` while the box lives in
`host_loop._cache_shield_hull_box` — two half-definitions of one surface. Both
consumers read from this module after the change.

### 4.2 Facing from a segment

```
facing_for_segment(ell, start_body, end_body) -> FacingHit | None
FacingHit = (facing: int, entry_body: Vec3, normal_body: Vec3)
```

1. Normalise both endpoints: `n = (p - centre) / semi_axes`.
2. If `|n_start|² <= 1` the shooter is already inside the bubble → return `None`.
3. Intersect the segment with the **unit sphere at the origin**; take the near hit `h`.
4. No intersection → `None`.
5. `facing = dominant_signed_axis(h)`.
6. `entry_body = h * semi_axes + centre`.
7. `normal_body = normalise(h / semi_axes)` — the true ellipsoid normal.

`None` means "no facing, route to hull", matching BC's fall-through.

### 4.3 The dominant-axis rule

Scan order `+y, +z, +x, −y, −z, −x`; strict comparison, so the **earlier entry wins
a tie**. Mapping:

| Axis | `+y` | `+z` | `+x` | `−y` | `−z` | `−x` |
|---|---|---|---|---|---|---|
| Facing | 0 | 2 | 5 | 1 | 3 | 4 |

This matches our current implementation exactly, including the tie priority. It is
kept verbatim because it is free fidelity.

⚠️ The mapping from index to the *words* front/rear/top/bottom/left/right is **not
established anywhere in the binary** — no string table, no enum. Our
`ShieldSubsystem` constants encode an unsourced convention. Probe q19
(`docs/instrumented_experiments/2026-08-16-shield-facing-and-beam-falsifiers.md`)
tests it. Nothing in this spec depends on the names being right; if q19 refutes
them, only the constants move.

### 4.4 What changes versus today

We currently take the dominant axis of the **impact point**. BC takes it of the
point where the segment **enters** the ellipsoid. They agree for a hit recorded on
the bubble surface and diverge on grazing shots and long per-frame steps.

## 5. Absorption — `engine/appc/shield_absorption.py`

```
passthrough_fraction(f):
    f >= 0.6           -> 0.0
    f <= 0.1           -> 0.6
    otherwise          -> (1 - 2 * (f - 0.1)) * 0.6

absorb(fraction, charge, damage) -> (absorbed, passthrough, new_charge)
    b        = passthrough_fraction(fraction)
    new      = charge - (1 - b) * damage
    if new >= 0:  passthrough = b * damage
    else:         passthrough = b * damage + (-new); new = 0
    absorbed = damage - passthrough
```

The curve is continuous: `0.6` at `f = 0.1`, `0.0` at `f = 0.6`. Constants read at
`0x0088BF28` (0.1) and `0x0088CB60` (0.6).

Separately, as a predicate, because in BC this gate lives in the geometry pass and
not in absorption:

```
facing_stops_shot(fraction) = fraction > 0.1
```

Below that the facing does not stop the shot at all — the hit routes to hull.

**Consequence of decision 1, stated so nobody deletes it as dead code:** once the
fraction is live rather than stale (§7.3), the gate always fires before absorption,
so the `b = 0.6` branch is unreachable in practice. In BC the 0.5 s staleness is
what made it reachable. The function stays total and documented; the branch would
become live again if the gate ever moved.

## 6. Cadence

Two 0.5 s quanta.

### 6.1 Charge tick — `ShieldSubsystem`

Accumulate `dt`; at each 0.5 s boundary apply the regen quantum and recompute the
per-facing fraction. Threshold read at `0x008E529C`.

**Scoped out, deliberately:** BC derives its quantum from accumulated *power*
(× 1/6, × 0.85) and distributes it by a per-facing property weight. We keep our
existing rate-based regen and adopt only the 0.5 s quantisation. Coupling shield
regen to the power system is a larger change with its own blast radius and belongs
in its own pass. Recorded here as a known remaining divergence.

### 6.2 Beam dwell — `engine/appc/beam_dwell.py`

A small accumulator keyed by (weapon, target), ~40 lines, driven from the phaser
path in `host_loop`:

- accumulate `dt` while firing at a target;
- at 0.5 s, flush one `apply_hit` with `damage = rate × dwell`, then reset;
- on target change, flush the partial pulse and reset.

Damage scales linearly with dwell, so a held beam delivers equal pulses and a swept
beam delivers a final partial one. The existing plateau + `R/d` falloff is unchanged
— the binary's `min(1, R/d)` distance factor independently confirms the curve we
already shipped from probe q09.

## 7. Corrected defects

Decision 1 says faithful model, corrected defects. These are the corrections, each
with the reason it is judged a defect rather than design.

| # | BC behaviour | Our behaviour | Why |
|---|---|---|---|
| 1 | A beam flush with no fresh hit-test reads facing `-1` and dumps full damage on the **hull at full shields** (§12.5a) | Carry `(target, facing)` with the accumulator; flush against the carried facing; **drop** the pulse if there is none | An unshielded-damage window on every beam sweep, arising from a stale field rather than any rule |
| 2 | The hit normal written is the **sphere's** normal, not the ellipsoid's (§2.3) | True ellipsoid normal, `normalise(h / semi_axes)` | Geometrically wrong on any non-spherical hull, i.e. all of them |
| 3 | The absorption ramp reads a fraction refreshed **only** on the 0.5 s charge tick (§9.2) | Recompute the fraction on every charge change | A burst inside one window all sees a stale value; consequence in §5 |
| 4 | `GetOppositeShield` returns `index − 1`, wrong for even indices (§9.1) | Not implemented | No callers, and BC's own answer is never read by its engine |

## 8. Skin shielding — an explicit boundary

`SkinShielding` is a **Dauntless-only visual**. It appears zero times in the SDK
(all 1,228 files) and zero times in either `App.py`; it exists only in our
`ShieldProperty`, `engine/shields.py`, the native `shield_pass`/`skin_shield`, and
two of our own hardpoint overrides (Akira, Sovereign).

**Gameplay geometry is the ellipsoid for every ship, unconditionally.** BC's
`ComputeShieldEllipsoid` reads the model bound with no property branch, and
`TestHit` intersects the unit sphere unconditionally — there is one shield collision
shape in BC and it is always an ellipsoid.

The ellipsoid is ~73% larger than the hull AABB, so on a skin-shielded ship the
damage boundary sits well outside the visible hull-hugging shield. That mismatch
exists today and is not created here, but making the entry point load-bearing makes
it more visible. Flash placement stays a **renderer** concern: in skin mode the pass
projects onto the inflated mesh it already builds, rather than onto the bubble.

This split is deliberate. Do not "fix" it by making facing selection mesh-based —
that would need a per-triangle raycast on the damage path, diverge from BC, and give
two ships different shield behaviour from every other hull.

## 9. Splash damage

`splash_damage.py` gains BC's separate, simpler rule (`0x00593C10`): walk **all six**
facings and let each absorb up to **one sixth** of the falloff-scaled damage, capped
at what that facing holds. Whatever survives all six routes on to hull/subsystems.
No geometry, no facing choice, no ramp.

## 10. Integration

`apply_hit` gains `segment=None`. Of six call sites, only **two** need it:

| Call site | Segment |
|---|---|
| torpedo (`host_loop:847`) | previous → current projectile position |
| phaser (`host_loop:955`, via beam flush) | muzzle → muzzle + dir × length |
| collisions ×2 | none — bypasses shields |
| `AddDamage` (`objects.py:863`) | none — bypasses shields |
| splash (`splash_damage.py:54`) | none — never selects a facing |

When `segment is None` and shields are online, facing selection falls back to
today's point-based rule. This is a documented approximation, not a hidden one: it
keeps existing callers and tests working, and it is exactly correct for a hit
recorded on the bubble surface.

## 11. Testing

**The ramp** — table test across all three regimes, both breakpoints, continuity at
`f = 0.1` and `f = 0.6`, and the overdraw case where the facing is driven negative.

**The geometry** — tested against **real** hulls, readable headlessly via
`model_aabb`: Galaxy half-extents 232/322/70; Sovereign 115/350/41 with its model
origin −6.98 off the bound centre in Z; Keldon offset +14.30 Z / −81 Y. The
anisotropy and the off-centre origins are both load-bearing — the origin offset is
what inverts the dorsal/ventral call near the mid-plane. Pure ±axis offsets from the
origin are the isotropic
case where every defect in this area vanishes; the last two shield bugs both shipped
green against exactly that fixture. Includes a **grazing shot where the entry point
and the impact point select different facings** — the direct regression test for
§4.4.

**Cadence** — dwell accumulates, flushes at 0.5 s, emits a partial pulse on target
change, and **never** dumps a facing-less pulse on the hull (defect 1).

**Splash** — each of six facings caps at one sixth; remainder routes on.

**The tested anchor** — with all facings full, `f = 1.0 → b = 0`, so bleed-through
must be **exactly 0.0**. This reproduces probe q04's measurement and is the one
assertion here backed by tested evidence rather than read evidence.

**Tests that must be rewritten, not deleted.** Anything asserting strict cascade
encodes the model being replaced. They are updated in the same change.

## 12. Out of scope

Named so they are not mistaken for oversights:

- **Hull/subsystem distribution** — BC offers every overlapping subsystem the *full*
  damage and sums residuals; we apply weighted shares. A real divergence, deferred
  by decision 2. Our q05 data is non-discriminating between the two models.
- **Power-derived charge quantum** — §6.1.
- **The mode multiplier table** (`0.25 / 0.5 / 0.5` at `0x00893170`) — values now
  known, but the index → power-level mapping is not established.
- **Facing names** — pending q19.

## 13. Risks

1. **The whole model is read-not-executed.** The live pass is the real test.
2. **Time-to-kill changes materially.** A weakened facing now leaks up to 60%.
3. **We over-generalised from a narrow probe once already** (q04 → "strict cascade"),
   and the regime we are about to rewrite is precisely the one that probe never
   entered. Probe q20 would close this; decision 3 chose to implement first.
