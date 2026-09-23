# The radial system profile — space as a function of distance from the star (design)

**Date:** 2026-09-23
**Status:** design, for approval. Not implemented.
**Supersedes:** `docs/superpowers/specs/2026-09-23-system-scale-clouds-design.md`
and the `Cloud`/`Volume` implementation that shipped from it.
**Relates to:** `2026-09-22-in-system-navigation-design.md` (§4),
`2026-09-23-celestial-layer-design.md`, `2026-05-11-space-dust-particles-design.md`
**Area:** `engine/systems/map.py`, `tools/systems/layout.py`,
`native/src/renderer/dust_pass.cc`, a new asteroid seeder

## The idea

**A cloud is not an object to be placed. It is a property of the system,
indexed by distance from the star.**

Each system carries one table. Each row is a radius and three independent
intensities: how thick the gas is, how many rocks there are, and how much it
hurts. Values interpolate linearly between rows and the last row persists
outward forever.

| `distance_gu` | `nebula` | `asteroids` | `radiation` |
|---|---|---|---|
| 0 | 0.00 | 0.00 | 0.00 |
| 10,000 | 0.20 | 0.00 | 0.05 |
| 45,000 | 0.05 | 1.00 | 0.00 |
| 57,000 | 1.00 | 0.35 | 1.00 |
| 120,000 | 0.05 | 0.00 | 0.00 |

That is the whole model.

## Why placement was the wrong model

The superseded design made clouds into geometry: a `Cloud` holding `Volume`s,
each with a shape, an envelope, a profile and four parameters — a sphere centred
on the star for Vesuvi, a directional lobe for Belaruz, with BC's authored sphere
pinned inside as a "pocket". It was answering the question *where is the cloud*,
and that question has no good answer, because a cloud is not anywhere in
particular.

Everything that design struggled with dissolves here:

- **No orientation.** The lobe's axis, its `near`/`far`/`radius`, and the
  unanswerable question of whether it should envelop its own system — gone.
  A radius has no direction to get wrong.
- **No envelope-versus-pocket distinction.** That split existed to separate
  "renders but does nothing" from "does what BC says". Here the columns are
  already independent, so a region can be thick and harmless or thin and lethal
  without a category for it.
- **No second volumetric concept.** `compute_dust_influence` already reduces the
  world to one scalar — closeness to the nearest sun — and drives density, tint
  and drift from it. This is that scalar with a lookup table in front of it, not
  a new mechanism beside it.

## What BC's authored cloud becomes

BC placed exactly two `MetaNebula` objects in the campaign: `Belaruz1_S.py` and
`Vesuvi4_S.py`. Under this model **the clump is a pointer, not a body.** It
serves two purposes and stops being modelled:

1. **It calibrates the curve.** The profile is shaped so the nebula column peaks
   at the radius where BC put its clump, at the intensity BC authored.
2. **It stays as set content for the near field.** The set still builds its
   `MetaNebula`, so `GetObject`, missions and the tuned
   `nebula_volumetric_pass` all keep working when the player is actually there.

The two agree by construction rather than by machinery: the profile is derived
*from* the clump, so the system-scale field is at its thickest exactly where the
local volumetric cloud is. That is the LOD relationship the superseded design
built a schema for, achieved by calibration instead.

**Where the clumps actually sit**, measured from the committed maps:

| System | Star | Clump radius | Regions span |
|---|---|---|---|
| Vesuvi | 2,000 GU remnant | **56,903 GU** | 32,000 → 106,846 |
| Belaruz | 8,000 GU, alive | **38,845 GU** | 38,000 → 121,181 |

Both are at or inside their system's innermost *listed* region, which is BC's own
ordering — it lists the dust cloud first in both systems. Nothing needs inventing
to justify either placement.

## The three columns

Each is independent, `0.0`–`1.0`, and interpolated on its own. Independence is
not a convenience — it is what the source material actually does:

| | visibility | sensor density | `SetupDamage` |
|---|---|---|---|
| **Vesuvi 4** | 145 GU | 10.5 | 150 hull/s, 20 shield/s |
| **Belaruz 1** | 200 GU | 6.5 | **never called** |

Belaruz's cloud blinds you and cannot hurt you. Vesuvi's is thicker *and* lethal.
Thickness and harm move separately in BC's own data, so they are separate
columns here.

### `nebula` — how thick the gas is

Drives visibility, sensor interference, and the dust field's density and tint.

**`1.0` is the thickest thing BC authored** — Vesuvi 4 — not "whatever this
system's clump is". The scale is absolute across all thirty-two systems, so
Belaruz's clump is thinner than Vesuvi's in the data exactly as it is in BC.

Intensity is defined by BC's own word for it, `MetaNebula_Create`'s **sensor
density** argument:

```
intensity  = sensor_density / 10.5        Vesuvi 4 = 1.000,  Belaruz 1 = 0.619
```

Visibility must diverge as intensity approaches zero — clear space sees forever —
so it is fitted as `a + b/i` through the only two samples that exist:

```
visibility_gu(i) = 55.6 + 89.4 / i
```

| intensity | visibility |
|---|---|
| 1.00 | 145 GU *(BC: 145)* |
| 0.62 | 200 GU *(BC: 200)* |
| 0.20 | 503 GU |
| 0.05 | 1,843 GU |

The fit is exact because two points determine two unknowns. **It is also the
weakest evidence in this document** — two samples, and the curve's shape between
and beyond them is an assumption. It is the best available, and it is honest
about being a fit rather than a measurement.

### `radiation` — how much it hurts

Drives hull and shield damage per second. `1.0` is Vesuvi 4's `SetupDamage`:

```
hull_per_s(r)   = 150.0 * r
shield_per_s(r) =  20.0 * r
```

Only one non-zero sample exists, so linearity is an assumption, stated. Belaruz
is `0.0` throughout — BC never called `SetupDamage` there, which is an authored
zero, not a missing value.

**Survivability is a constraint on the data, not on the model.** A profile that
holds `radiation` above roughly `0.05` across a whole system makes that system
unplayable — 7.5 hull/s with no route around it. The generator must not author
that, and a validator should refuse it.

### `asteroids` — how many rocks

Drives seeding density. BC gives two very different references:

- **Vesuvi 4** — 12 `Asteroidh1` at scale 9.0, named `"Unknown Debris 1"`–`"12"`,
  scattered across roughly 1,000 GU inside a 1,500 GU cloud. A loose field.
- **Vesuvi 1** — one `AsteroidFieldPlacement`: field radius 100 GU, 3 tiles per
  axis, 2 asteroids per tile, size factor 10. A tight clump.

**`1.0` is the loose field** — 12 bodies within a 1,500 GU sphere — because that
is what a belt should feel like to fly through. The tight clump is a different
authored thing and is left as set content.

Asteroids are real objects with `GENUS_ASTEROID`, not particles, so a belt is
**seeded around the player, not instantiated across its whole radius**: maintain
the profile's density within a working volume that travels with the player, and
retire bodies that fall far behind. The six stock asteroid models are the
starting vocabulary; more variety later is a content problem, not a design one.

## Where the data lives

A new field on `SystemMap`:

```python
@dataclass
class ProfileRow:
    distance_gu: float
    nebula: float = 0.0
    asteroids: float = 0.0
    radiation: float = 0.0

# SystemMap.profile: list[ProfileRow], sorted by distance_gu
```

**Evaluation rules**, which the implementation must hold exactly:

- Rows are sorted by `distance_gu` and the first row is at `0.0`.
- Between rows, each column interpolates linearly and independently.
- **Beyond the last row, the last row's values persist outward forever.** A
  system with a final `nebula` of `0.05` is inside thin gas at any distance.
- An empty profile means clear space everywhere — which is correct for the thirty
  systems BC gave no cloud.

## How the thirty-two profiles get authored

Derived by the generator, corrected by hand — the pattern `overrides.star`
already uses. Nobody hand-writes thirty-two tables.

The generator proposes from each system's own facts:

- **A corona row** near the star, scaled to its radius. The dust pass already
  brightens, warms and blows dust outward near a sun; this is that effect given a
  number instead of a hard-coded ramp.
- **A nebula peak** at the clump's radius, at the clump's calibrated intensity,
  for the two systems that have one, tapering outward to a thin floor.
- **A radiation peak** co-located with it, where BC called `SetupDamage`.
- **Asteroid rows** where BC authored asteroids.
- **Nothing at all** for the thirty systems with neither, unless a hand override
  says otherwise.

`overrides.profile` replaces the derived table wholesale where a human disagrees.

## What the runtime does with it

**Dust** — `compute_dust_influence` gains the profile as a third source beside
suns and planets. Its output already has the right shape: a density multiplier, a
tint factor and a drift direction. The nebula column feeds density and tint
(tinted toward the *cloud's* authored colour rather than the sun's orange, where
one applies); the star continues to drive drift.

**Visibility and sensors** — `visibility_gu(i)` and `sensor_density(i)` evaluated
at the player's radius, applied the way BC's `MetaNebula` applies them today.

**Damage** — `radiation` at the player's radius, through the same environmental
damage path BC's nebula uses, so `ET_ENVIRONMENT_DAMAGE` handlers and the
existing per-object exemptions keep working unchanged.

**Asteroids** — seeded around the player per the section above.

## What comes out of the tree

The clouds implementation is superseded, not amended:

- `Cloud` and `Volume` from `engine/systems/map.py`, and `SystemMap.clouds`.
- `engine/systems/clouds.py` — the three profiles. Its *numbers* move into this
  document's calibration; the module goes.
- Four validation rules: `cloud-volume-agrees-with-region`,
  `cloud-region-membership`, `cloud-pocket-inside-cloud`,
  `cloud-profile-matches-params`.
- `_build_clouds` and `_build_cloud_large_volume` in `tools/systems/layout.py`,
  `cloud_from` in `tools/gen_system_maps.py`, and the `overrides.cloud` blocks
  in `belaruz.json` and `vesuvi.json`.

**What survives:** the survey work. `tools/systems/survey.py` reading BC's four
`MetaNebula` numbers — with spheres scoped to their own nebula — is what makes
the calibration above possible, and it stays exactly as it is.

## Unknowns to measure, not guess

- **The visibility curve's shape.** Fitted through two points. Anything said
  about intensity 0.3 is interpolation, not evidence.
- **Whether a profile-driven dust field reads as a nebula.** The dust pass is 512
  camera-anchored particles tuned for empty space. At `nebula = 1.0` it may look
  like thick dust rather than cloud, and need the volumetric pass at system scale
  after all. That is a live-pass question.
- **What a travelling asteroid belt costs**, and whether bodies retiring behind
  the player is visible.
- **Whether the profile and BC's local `MetaNebula` visibly disagree** where they
  overlap, given one is particles and the other is a raymarched volume.

## Consequence for the shipped descriptions

Belaruz's player-facing text currently says the cloud's dense part has fallen
inward and thin material stretches out ahead of it. Under a radial model there is
no "ahead" — the system sits inside a spherical body of gas that is thickest at
38,845 GU. That sentence needs its third correction, and this time the geometry
it describes will be the geometry that exists.
