# The radial system profile — space as a function of distance from the star (design)

**Date:** 2026-09-23, **revised 2026-09-28** against main at `10129269`
(system frames and in-system warp merged; orbital spacing doubled twice).
**Status:** design approved section by section (2026-09-28); awaiting review
of this written spec. Not implemented.
**Supersedes:** `docs/superpowers/specs/2026-09-23-system-scale-clouds-design.md`
and the `Cloud`/`Volume` implementation that shipped from it.
**Relates to:** `2026-09-24-system-frames-design.md`,
`2026-09-23-celestial-layer-design.md`, `2026-05-11-space-dust-particles-design.md`,
`docs/superpowers/deferred/2026-09-28-nebula-sensor-scale-unmeasured.md`
**Area:** `engine/systems/{map,validate,profile}.py`, `tools/systems/layout.py`,
`tools/gen_system_maps.py`, `engine/appc/{nebula_runtime,sensor_detection}.py`,
`engine/host_loop.py`, `native/src/renderer/dust_pass.cc`, a nebula render pass

## The idea

**A cloud is not an object to be placed. It is a property of the system,
indexed by distance from the star.**

Each system carries one table. Each row is a radius and five independent
values in `0.0`–`1.0`. Values interpolate linearly between rows and the last
row persists outward forever.

| column | drives | `1.0` means |
|---|---|---|
| `nebula` | the visible nebula at system scale (a render pass) | Vesuvi 4's thickness |
| `dust` | space-dust particle **density** — nothing else | the dust pass's existing 10× ceiling |
| `sensors` | target concealment | Vesuvi 4's core concealment |
| `radiation` | shield/hull drain + random subsystem outages | Vesuvi 4's `SetupDamage(150, 20)` |
| `asteroids` | **nothing yet** — data for a separate asteroid design | Vesuvi 4's loose debris field |

That is the whole model. A low `nebula` value is simply thin nebula — there is
one concept, not a "gas" separate from "cloud".

## Why placement was the wrong model

The superseded design made clouds into geometry: a `Cloud` holding `Volume`s,
each with a shape, an envelope, a profile and four parameters — a sphere for
Vesuvi, a directional lobe for Belaruz, with BC's authored sphere pinned inside
as a "pocket". It answered *where is the cloud*, which has no good answer.

- **No orientation.** A radius has no direction to get wrong; the lobe's axis
  and extent stop existing.
- **No envelope-versus-pocket distinction.** The columns are independent, so a
  region can be thick and harmless (Belaruz) or thick and lethal (Vesuvi)
  without a category for it.
- **Nothing reads it.** Audited 2026-09-28: no runtime, renderer or native code
  reads `SystemMap.clouds`. Only the generator, validator and tests do, so
  removal is safe.

## What BC's authored cloud becomes

BC placed exactly two `MetaNebula` objects in the **campaign**: `Belaruz1_S.py`
and `Vesuvi4_S.py`. **The clump is a pointer, not a body.** It:

1. **Calibrates the curve** — each column peaks at the clump's distance from
   the star, at the clump's calibrated value.
2. **Stays as set content for the near field.** The set still builds its
   `MetaNebula`, so `GetObject`, missions, the BC-measured creation hit, the
   16 Hz `ET_ENVIRONMENT_DAMAGE` events, fbm concealment and the tuned
   `nebula_volumetric_pass` all keep working unchanged when the player is there.

**Multiplayer systems are ignored.** Multi5 (×4) and Multi6 also author
MetaNebulae (sensor density 0.5; Multi6 visibility 75 GU). They calibrate
nothing, get no derived profile, and their local clouds keep behaving as BC
authored them. A hand `overrides.profile` could give one a profile later;
nothing is built for that.

**Clump positions are never written into this spec.** They are derived from the
maps at generation time. (The first draft hard-coded 56,903 / 38,845 GU; two
orbital-spacing doublings made both wrong within two days. At `10129269` they
are ≈123,500 GU for Vesuvi and ≈128,845 GU for Belaruz.) The clump's radius is
`|region anchor + sphere centre − star|`, and the star is at the origin in
every map.

## The columns

### `nebula` — how thick it looks

Calibrated from BC's visibility distance, fitted `visibility = a + b/i` through
the only two campaign samples (exact: `a = 55.625`, `b = 89.375`):

```
i = 89.375 / (visibility_gu − 55.625)       Vesuvi 4 = 1.00, Belaruz 1 = 0.62
```

A fit through two points, scoped to the campaign (Multi6's 75 GU would land far
above 1). It is the weakest evidence here and says nothing reliable about
shape between and beyond the samples.

**Runtime: the visible nebula at system scale.** The render pass receives, per
frame: the `nebula` value at the camera, the system's cloud colour (the clump's
authored RGB, e.g. Vesuvi 155/90/185, Belaruz 100/99/146), the outward radial
unit vector in render space, and `d nebula / dr` at the camera, so the effect
can thicken toward the side of the view the cloud lies on. How it looks and
what it costs are **unknown and settled by a live spike** (see *Unknowns*).
Visibility has no gameplay effect: nothing but the faithful nebula pass reads it.

### `dust` — how dense the space dust is

Drives **density only** — no tint, no drift; the sun keeps both.

```
density_mult = max(existing sun/planet boost, 1 + 9 · dust)
```

`9` lifts `1.0` to `kMaxDensityMult` = 10. `dust = 0` renders exactly as today.
By default the generator copies the `nebula` shape into `dust` (Vesuvi 1.0,
Belaruz 0.62); `overrides.profile` can separate them.

### `sensors` — how well it hides things

```
concealment_at(ship) = max(local MetaNebula fbm concealment, sensors(r) · C_V)
```

`C_V` is the concealment Vesuvi 4's own fbm field produces at its core, measured
by the generator with the runtime's own `nebula_density` and stored with the
profile — not guessed. Belaruz's peak is its measured core concealment as a
fraction of `C_V`. Everything downstream (`LOCK_BREAK_T` = 0.28, the
`1 − 0.9·conceal` range factor) is unchanged. It acts on the **target's**
position, as concealment does today.

This does **not** touch the local MetaNebula's `sensor_density` scaling, which
is an accidental no-op (BC's 10.5 / 6.5 clamp to 1.0) with BC's real behaviour
unmeasured — logged in
`docs/superpowers/deferred/2026-09-28-nebula-sensor-scale-unmeasured.md`.

### `radiation` — how much it hurts

**A deliberate departure from BC.** BC's `SetupDamage` nebula does not drain:
measured on `stbc.exe` (bible §15 E1), it deals one hit to ships present at its
creation and nothing to a ship that flies in. The profile adds real harm, with
BC's own number as the scale.

Two effects, per ship in the active set, each evaluated at that ship's radius,
on the fixed sim tick (so pause freezes it). `m` is the difficulty multiplier:
**easy 0, medium 0.5, hard 1.0** (BC gave easy nothing; so do we).

1. **Drain.** Shields up: every face loses `20 · r · m` per second. Shields down:
   the hull loses `150 · r · m` per second. The same branch as BC's one-off hit.
   A Sovereign (12,000 hull) with shields down at Vesuvi's peak on hard lasts
   ~80 s.
2. **Outages — shields up or down.** Per ship, outages start at rate
   `r · m / 30 s` (≈ one per 30 s at Vesuvi's peak on hard, ≈ 60 s on medium).
   Each picks a random subsystem **other than the hull and the power plant** and
   holds it forced-off for a uniform 5–20 s; turning it on is refused until the
   timer expires. A shield-generator outage drops shields and so exposes the hull
   to the drain. An outage ends cleanly if the ship dies or leaves the set.

Both are skipped: at easy; while the ship is dashing (`WES_WARPING` — player
dashes run 2,000–100,000 GU/s, so sampling the profile mid-dash is meaningless);
and for ships whose `ET_ENVIRONMENT_DAMAGE` handlers include
`MissionLib.IgnoreEvent` (Vesuvi 4's asteroids, E3M2's probe).

While `radiation > 0` the ship receives `ET_ENVIRONMENT_DAMAGE` at 16 Hz, so the
SDK's CoreDamage reactions ("raise shields") fire. At most one per ship per
tick, shared with the local MetaNebula's own events.

### `asteroids`

Authored in the schema; **the generator writes 0 everywhere** and nothing reads
it. Every asteroid in BC is a full `ShipClass` (`loadspacehelper.CreateShip
("Asteroidh1", …)`, genus set but never read), simulated globally and in
all-pairs O(n²) collisions, so seeding a belt of them would be expensive and would
die like ships. Calibrating this column and consuming it belong to a separate
**modern asteroids** design (lightweight non-ship bodies, broadphase, breakup,
seeding around the player). SDK references for that design: Vesuvi 4 (12
loose `Asteroidh1`, ~1,226 GU spread), Vesuvi 1 / Nepenthe 1 / Beol 4
`AsteroidFieldPlacement` (Beol 4: radius 1000, 3³ tiles × 15), and single rocks
in Belaruz 4, Cebalrai 1 and E1M2.

## Where the data lives

```python
@dataclass
class ProfileRow:
    distance_gu: float
    nebula: float = 0.0
    dust: float = 0.0
    sensors: float = 0.0
    radiation: float = 0.0
    asteroids: float = 0.0

@dataclass
class Profile:
    rows: list[ProfileRow]          # sorted by distance_gu, first at 0.0
    color: tuple[float, float, float]   # the clump's authored RGB, 0–1
    full_concealment: float         # C_V, generator-measured

# SystemMap.profile: Profile | None  — None is clear space
```

**Evaluation rules**, held exactly:

- Rows are sorted by `distance_gu` and the first row is at `0.0`.
- Between rows each column interpolates linearly and independently.
- **Beyond the last row, the last row's values persist outward forever.**
- `profile = None` means clear space everywhere — correct for the thirty
  systems with no campaign cloud.

`engine/systems/profile.py` holds the dataclasses' evaluation
(`evaluate(profile, r) -> Sample`) and `star_distance(obj)`, which uses
`frames.system_position` and the map's star (the pattern of
`star_light.for_player`). The dust pass works in render space since
`d2f95f9d`, so the distance is always computed in Python, in system
coordinates, and only evaluated values cross into C++.

## How the profiles get authored

Derived by `tools/gen_system_maps.py`, corrected by hand — the pattern
`overrides.star` uses. A `profile_from()` reader loads `overrides.profile`,
which replaces the derived profile wholesale; `_merge_overrides` carries it
forward.

The generator derives a profile for each **campaign** system with a region
whose `nebula` survey entry is set (today Vesuvi, Belaruz):

| | peak value | shape around the peak radius `R` |
|---|---|---|
| `nebula` | from the visibility fit | wide: 0 at `0.5·R`, peak at `R`, 0.05 floor at `2·R`, floor persists |
| `dust` | = `nebula` | same wide shape |
| `sensors` | `core concealment / C_V` | narrow: 0 at `R ± 2·region radius` |
| `radiation` | `1.0` if `SetupDamage` authored, else `0` (Belaruz: an authored zero) | narrow, back to 0 |
| `asteroids` | 0 | — |

The three shape constants (rise start `0.5`, floor radius `2.0`, floor
`0.05`, band `2 × region radius`) are named constants in the generator.
At `10129269` the band is ≈ ±7,100 GU at Vesuvi and ≈ ±4,500 GU at Belaruz.

**Validator rules** (`_profile_problems` in `validate.py`):

- `profile-rows-ordered` — sorted, first at 0, every value finite and in 0–1.
- `profile-radiation-bounded` — `radiation` is 0 at radius 0 **and** in the last
  row (the last row persists forever, so non-zero there makes the outer system
  lethal).
- `profile-radiation-band` — no stretch of `radiation > 0.05` wider than
  20,000 GU, so no system is authored without a way round.

## What the runtime does with it

| effect | where | when |
|---|---|---|
| radiation drain, outages, events | new driver beside `NebulaTracker` (`host_loop.py` ≈ 10436) | fixed sim tick |
| concealment | `sensor_detection.concealment_at` | on demand |
| dust density | `r.set_dust_profile(dust)` from `_push_environment_feeds`, `max` in `compute_dust_influence` | render frame |
| nebula look | a render pass fed from `_push_environment_feeds` | render frame — **last phase, behind a live spike** |

The plan must first check whether any SDK `ET_ENVIRONMENT_DAMAGE` handler reads
the event's source, since profile events have no nebula object to be the source.

## What comes out of the tree

Superseded, not amended:

- `engine/systems/map.py`: `Volume`, `Cloud`, `SystemMap.clouds`, the
  `SystemMap.cloud()` lookup, `_volume_from_json`, `_cloud_from_json`, and the
  `clouds` parse/argument in `from_json`.
- `engine/systems/clouds.py` (its three profiles; the SDK numbers stay pinned by
  the survey test, rewritten against this calibration).
- `engine/systems/validate.py`: the four `cloud-*` rules, the `clouds` import,
  the eight cloud-only helpers (`_looks_like_volume`, `_volume_geometry_ok`,
  `_volume_extent`, `_PARAM_KEYS`, `_pocket_param_details`, `_sphere_entries`,
  `_match_pockets_to_region`, `_pocket_inside_large`), the `clouds` field
  check, `star_origin`, and the cloud problems filed under `malformed-geometry`.
- `tools/systems/layout.py`: `_build_clouds`, `_build_cloud_large_volume`, the
  clouds imports, and the `cloud=` parameter through `_first_orbit_push`,
  `ambiguities` (with its cloud-kind check), `_place` and `layout`.
- `tools/gen_system_maps.py`: `cloud_from` and its uses in `generate()`.
- `overrides.cloud` in `belaruz.json` and `vesuvi.json`; the `"clouds"` key in
  **all 32** map files (regenerated, gaining `"profile"`).
- Doc cross-references: celestial-layer spec (≈ line 358) and plan (≈ 623),
  system-frames spec item 10 (≈ 551), `engine/systems/resolve.py:26` docstring.
  The superseded clouds spec's status becomes **Superseded by** this document.
- Tests: `tests/unit/test_cloud_profiles.py` (deleted) and the cloud tests in
  `test_system_map.py`, `test_system_map_validate.py` (~30),
  `test_system_maps_valid.py`, `tests/tools/test_system_layout.py` and
  `tests/tools/test_system_survey.py`.

**What survives:** `tools/systems/survey.py` and `Region.nebula` — the source of
every calibration number above.

## Consequences for shipped behaviour and text

- **E3M2.** Today the player warps into Vesuvi 4 and takes nothing (BC-faithful).
  Now Vesuvi 4 drains shields (hull when they are down) and knocks random
  systems offline for 5–20 s, from medium difficulty up.
- **Belaruz description** (`engine/systems/descriptions.json`) gets its third
  correction: there is no "ahead"; the system sits in a spherical body of dust
  and gas, thickest just beyond Belaruz 1, which blinds but does not burn. New
  wording is approved by Mark before it lands;
  `test_belaruzs_description_matches_where_its_cloud_actually_is` is rewritten
  with it. The stale "Belaruz 4 at 121,181 GU" `why` string goes with
  `overrides.cloud`.
- **Vesuvi description**'s "route around it or accept the damage" becomes true.

## Testing

- `profile.evaluate`: interpolation per column, persistence past the last row,
  `None` = clear, exact row hits.
- Generator: each peak sits at the clump's *current* derived radius (asserted
  from the map, never a literal); Belaruz radiation is 0; Multi systems and
  the other thirty get `None`; `overrides.profile` replaces wholesale.
- Validator: each of the three rules fires and stays quiet on the committed maps.
- Radiation: drain per shield branch; `m` = 0 / 0.5 / 1.0; skipped while dashing
  and with `IgnoreEvent`; outages with a seeded RNG — rate, 5–20 s bounds,
  hull/power never chosen, turn-on refused until expiry, clean end on death /
  set exit; one event per ship per tick with a local nebula present.
- Concealment: `max` of local and profile.
- Dust: `compute_dust_influence` density formula as a ctest.
- **The existing `tests/oracle/test_nebula.py` passes unchanged** — the local
  MetaNebula's BC-measured behaviour must not move.

## Unknowns to measure, not guess

- **The visibility fit's shape** — two points; anything between is interpolation.
- **How the system-scale nebula should look and what it costs.** Settled by a
  live spike Mark checks, as the plan's last phase. GPU timing is dead on this
  Mac, so cost is judged by the CPU profiler and by eye. If the spike shows the
  look needs real design work, the plan stops there.
- **Whether the profile and a local `MetaNebula` visibly disagree** where they
  overlap (the dust and the nebula pass against a raymarched volume).
- **Whether the radiation numbers play well** — `m`, the 30 s outage rate and the
  5–20 s range are chosen, not recovered. Live-tuned in E3M2.
- **BC's "sensor scale"** — unmeasured; deferred (see above).
