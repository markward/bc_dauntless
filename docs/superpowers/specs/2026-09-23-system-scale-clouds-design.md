# System-scale clouds — the first thing a system owns that a region does not (design)

**Date:** 2026-09-23
**Status:** **Superseded** by `2026-09-23-radial-system-profile-design.md` (revised 2026-09-28). It was implemented (`engine/systems/clouds.py`, `SystemMap.clouds`); that code is removed by the radial profile work.
**Extends:** `docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`
**Area:** `engine/systems/map.py`, `engine/systems/validate.py`,
`tools/systems/survey.py`, `tools/systems/layout.py`, `tools/gen_system_maps.py`

## The gap

Every other feature of a system exists at two scales and we handle it the same
way each time: BC authored a small thing inside a set, and we re-author a large
thing in system coordinates that replaces it. A planet is 110 GU in
`Vesuvi5_S.py` and 2,200 GU in `vesuvi.json`; the region loads without its
planet, and the system's body stands in.

Clouds break that pattern, and the whole-system atlas made it visible. Vesuvi 4's
dust renders as five pixels because it is BC's authored 1,500 GU sphere plotted
through its region's anchor — **the region's cloud, borrowed into system
coordinates.** There is no system-scale cloud, because the data has nowhere to
put one: `nebula` is a field on `Region`, and `SystemMap` has bodies, regions and
a star and nothing else.

So this is the first thing that belongs to a **system** rather than to a region.
It needs its own shape because, unlike a body, a cloud has no single position.

## What BC actually authored

Exactly two of the 90 regions carry a cloud, and they are the same two regions
that carry no star and no planet. Both scripts are short enough to read whole;
these are their complete contents.

(Four SDK sets build a `MetaNebula`, not two. The other two are `Multi5_S.py`
and `Multi6_S.py`, which never reach a map: the multiplayer arenas are single
sets with no numbered children, so the survey finds no regions for them at all.
They still matter as the only evidence that a file may hold **several**
nebulae — Multi5 holds four — and that `SetupDamage` has a one-argument form.)

| | **Vesuvi 4** | **Belaruz 1** |
|---|---|---|
| `MetaNebula_Create` colour | `155,90,185` — purple | `100,99,146` — blue-grey |
| Visibility inside | **145 GU** | 200 GU |
| Sensor density | **10.5** | 6.5 |
| `SetupDamage` | **150 hull/s, 20 shield/s** | **absent — does nothing** |
| Spheres | one, r=1500 at `(0, 1500, 0)` | one, r=900 at `(-17.1, 844.7, -30.3)` |
| Solid content | **12 asteroids, scale 9, named `"Unknown Debris 1"`–`"12"`** | none |
| Waypoints | `Nebula Location`, 12 `AsteroidGroupN Start M` | `Kacheeti Nebula`, **`Exit Nebula`** |
| Directional light | white @ 0.5 | white @ **1.0** — the brightest in the game |
| Ambient | 0.25 | 0.10 |

The `debris` / `nebula` distinction is not something we are inventing
on top of BC. BC authored it. Vesuvi's cloud is denser on both axes, it is the
only one that hurts you, and it is full of rocks the artists named **Unknown
Debris**. Belaruz's is thinner, inert, empty, and has a waypoint called **Exit
Nebula** — you pass through it and come out the other side.

Two more details from the same tree support the reading the descriptions already
carry:

- **`Vesuvi1.py`** — the orphan set, still in the tree, never menu-listed —
  places a waypoint named **`Core Fragment Start 1`** and an
  `AsteroidFieldPlacement`. BC's own name for what is in the innermost Vesuvi
  region is a fragment of the star's core.
- **`Vesuvi5_S.py`** creates `GekiStation` and immediately does
  `DamageSystem(GetHull(), max * 0.80)`. The Federation outpost at Geki is
  authored at 20 % hull.

## Why a cloud cannot be a `Body`

`Body` is `(name, radius_gu, position_gu, orbits, appearance, owner_region)`. A
cloud is not one volume: Vesuvi's is a shell around the star with a lethal
pocket inside it, Belaruz's is a lobe the system is moving into with a pocket at
its tip. A single centre and radius can describe neither, and `orbits` is
meaningless for both.

It is also not a `Region`. A region is a BC set with local coordinates and a
streaming lifecycle. A cloud is neither loaded nor unloaded; it is terrain.

So: a third list on `SystemMap`, alongside `bodies` and `regions`.

## The data shape

```python
@dataclass
class Volume:
    shape: str                 # "sphere" | "lobe"
    geometry: dict             # shape-specific, in SYSTEM coordinates
    profile: str               # "debris" | "nebula" | "mist"
    params: dict               # visibility_gu, sensor_density,
                               # damage_hull_per_s, damage_shield_per_s
    origin_region: str | None  # set when derived from a BC MetaNebula

@dataclass
class Cloud:
    name: str                  # "Vesuvi Debris Field"
    display_name: str
    kind: str                  # "debris_shell" | "nebula_field"
    color: tuple               # BC's own MetaNebula RGB, verbatim
    volumes: list              # one or more Volumes
    regions: list              # set names the cloud passes through
```

### Every volume carries numbers

A cloud is not one shape. It is a set of volumes, each with its own extent and
its own four numbers, and the numbers are the only thing that decides what a
volume does to a ship inside it.

That is the whole model, and it deliberately has no scenery-versus-substance
category in it. A volume that renders but does nothing is simply one whose
numbers are zero. This matters because the third profile below is extensive
*and* has effect, so any line drawn between "big decorative shape" and "small
real one" would be in the wrong place the moment it is built.

**Three profiles. Two are BC's and are never tuned; one is ours.**

| Profile | Extent | Visibility | Sensor | Damage | Source |
|---|---|---|---|---|---|
| `debris` | small, dense pocket | 145 GU | 10.5 | 150 / 20 | **Vesuvi 4, verbatim** |
| `nebula` | small, dense pocket | 200 GU | 6.5 | 0 / 0 | **Belaruz 1, verbatim** |
| `mist` | system-scale | weaker than either | weaker | see below | ours, **deferred** |

BC's two are authored data and are copied unchanged, including Belaruz's zero
damage — which is zero because BC never called `SetupDamage`, not because we
decided its cloud should be gentle.

**`mist` is named here and not built here.** It is the thin material that
extends out into a system: what makes Vesuvi's shell a thing you fly through for
a long time rather than a boundary you cross, and what puts Belaruz's outer
worlds inside the cloud their description already claims they are in. Its
numbers are deferred, under one binding constraint: **mist must be survivable at
sustained exposure**, because it covers most of a system and there is no route
that avoids it. Concretely that means weaker than `nebula` on every axis, and it
is why the lethal pocket stays a pocket. BC put one lethal place in Vesuvi; the
mist does not spread it across 30,000 GU.

### The BC-derived volume is pinned

Today each cloud has exactly one volume with real numbers: the sphere BC
authored, transformed through its region's anchor into system coordinates. It is
**pinned** — generated from the survey, never moved, never regenerated — on the
same footing as a pinned body, and it carries `origin_region`.

This is what makes the two scales one phenomenon rather than two facts that can
drift. The region keeps `Region.nebula` in **set-local** coordinates because
that is what the set needs when it loads and creates the `MetaNebula`; the cloud
holds the same sphere in **system** coordinates because that is what the
celestial layer needs. One source (the survey), two consumers, two coordinate
spaces — and a validator that proves they still agree.

The large volume in each cloud below ships with all four numbers at zero. When
`mist` is built it is a change to those numbers, not to this schema.

### Vesuvi — `debris_shell`

A sphere centred on the remnant, not a ring in the orbital plane.

```json
{
  "shape": "sphere",
  "geometry": { "center_gu": [0.0, 0.0, 0.0], "radius_gu": 61567.0 },
  "profile": "mist",
  "params": { "visibility_gu": 0.0, "sensor_density": 0.0,
              "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0 }
}
```

The radius is derived: **Vesuvi 4's orbit plus its region radius**
(58,000 + 3,567). That is the outermost region carrying debris, so the shell
reaches exactly as far as the wreckage does. It comfortably contains Vesuvi 1 at
32,000 — where the `Core Fragment` is — and stops well short of Vesuvi 5 at
80,575, which is right: Geki and Haven are outside the shell, which is how they
are still inhabited.

The shell spans exactly the regions that carry debris. That is the whole rule.

**Why a shell and not a ring.** A disc is the more obvious shape for stellar
debris, and it was the first draft here. It is the wrong one for two reasons.
The presentational one: every region anchor in Vesuvi sits within 5° of the
orbital plane — Vesuvi 6 within half a degree — because `_orbit_point` places
bodies at `(r·sin a, r·cos a, 0)` and the anchors follow. A disc would therefore
be seen edge-on from wherever the regions are, reading as a thin band rather
than as a ring, and would only resolve into a ring if the player climbed well
out of the plane. A sphere has no preferred viewing angle and no such
dependency. The structural one: a star that was destabilised from within threw
its material out in every direction, not into a plane. A disc is what accretion
builds over time; a shell is what a detonation leaves.

If it plays better as a disc, `shape` is one field and the radius derivation is
unchanged.

### Belaruz — `nebula_field`

Not centred on the star, because the star is not the cause.

```json
{
  "shape": "lobe",
  "geometry": { "axis": [0.0, 1.0, 0.0], "near_gu": 20000.0,
                "far_gu": 220000.0, "radius_gu": 160000.0 },
  "profile": "mist",
  "params": { "visibility_gu": 0.0, "sensor_density": 0.0,
              "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0 }
}
```

A body of interstellar dust the system is ploughing into, thickening along one
direction. BC's authored pocket sits at `(-17, 38845, -30)` — 38,845 GU out —
and the `axis` above is simply the direction from the star to that pocket,
normalised. The lobe is the body of cloud that pocket is the leading tip of.

Belaruz keeps a directional shape where Vesuvi gets a shell, and the reason is
the same in both cases: the shape follows the cause. Vesuvi's material came from
the star and went outward in every direction. Belaruz's came from outside and is
being ploughed into from one side.

**Why the dense pocket is the innermost thing in the system, not the outermost.**
BC put the cloud at Belaruz **1**, inside the orbit of every planet. That reads
backwards for a system entering a nebula from outside — until you notice it is
also the explanation for everything else in that system. The outer reaches sit
in the thin body of the cloud; the material that has fallen furthest in has been
drawn there by gravity, and that infall is what is feeding the star. Belaruz 1
carries the brightest directional light in the game — pure white at full
strength, against an ambient of 0.1 — which is what standing near a feeding star
looks like. The dense pocket is innermost *because* the star is alive.

That also makes sense of `Exit Nebula`: you fly in and out of the thick part,
rather than crossing a boundary at the system's edge.

## The two scales, and the hand-off

The LOD relationship is the one the region model already uses everywhere else,
with one difference worth stating plainly.

| | Planet | Cloud |
|---|---|---|
| Far | System body, drawn from any distance | The large volume, drawn from any distance |
| Near | Same system body, up close | The pocket's own volume |
| BC's authored object | **Deleted** — the system body replaces it | **Kept** — it *is* the pocket volume, in the coordinates the set needs |

A planet is one object at two distances. A cloud is several volumes at once, and
you are inside the large one long before you reach the small one. That is not a
compromise; it is what a cloud is.

Concretely, flying inward through Vesuvi: the shell is around you from about
61,000 GU in, doing nothing yet because its numbers are zero — and doing
something once `mist` is built. Around 57,000 you reach the pocket BC authored,
and Vesuvi 4's own `MetaNebula` takes over: visibility drops to 145 GU, sensors
degrade by 10.5, the hull starts taking 150 a second. Nothing about the shell
caused any of that. The pocket did, with BC's numbers.

Note what this paragraph no longer says. It does not say "from Vesuvi 6" — in
this design there is no standing in a set and looking out of it. There is a
position in a system, with a region's content streaming in when you are near it,
and the cloud is there the whole way.

## What this note deliberately does not decide

**`mist`'s numbers.** Named above, deferred deliberately. The binding constraint
is recorded — survivable at sustained exposure — and the shapes it will fill are
already in the data with zeroed params. Choosing the values is a tuning exercise
that wants something to fly around in first.

**Seeding the shell with asteroids and further pockets.** The large volume is a
seeding volume and that is the obvious next use for it, but how many, how dense,
and whether seeded pockets get `debris` numbers or `mist` numbers all belong to
that work. What this note commits to is the shapes, the pinned BC pockets, and
the rule that numbers decide behaviour.

**Vesuvi 4's twelve asteroids and Vesuvi 1's asteroid field.** They are set
content, created by `loadspacehelper.CreateShip` at set waypoints, and the region
model already carries set content across untouched. They are evidence for what
the shell is; they are not migrated into it.

## Validation

Four new rules for `engine/systems/validate.py`, which never raises:

- **`cloud-volume-agrees-with-region`** — every volume with an `origin_region`
  must equal that region's `anchor_gu + Region.nebula.spheres[i]`, within
  tolerance. This is the anti-drift guard: it is the rule that makes "two
  coordinate spaces" not mean "two sources of truth".
- **`cloud-region-membership`** — every set name in `Cloud.regions` exists, and
  every region carrying a `nebula` is named by exactly one cloud.
- **`cloud-pocket-inside-cloud`** — every volume with an `origin_region` lies
  inside its cloud's largest volume. A pocket outside its own shell means the
  derivation is wrong.
- **`cloud-profile-matches-params`** — a volume's `profile` must name a known
  profile, and its `params` must agree with whichever **independent** source
  that volume has.
  - A **pocket** (`origin_region` set) is compared against **its own region's
    `Region.nebula`** — BC's four authored numbers, read straight out of the
    set's static-placement script. It is deliberately *not* compared against
    `clouds.PROFILES`: `tools/systems/layout.py` writes a pocket's `params`
    *from* that table, so comparing them back against it is a tautology that
    can never fail for a generated map. Concretely, `Multi6_S.py` authors
    `MetaNebula_Create(..., 75.0, 0.5, ...)` + `SetupDamage(1.0)`; if such a
    set ever became a region, layout would classify it `debris` (hull > 0) and
    stamp Vesuvi's `145 / 10.5 / 150 / 20` onto it — a 150× hull-damage error
    that a table comparison validates clean.
  - `damage_shield_per_s` is **skipped when the survey has `None`** there: BC
    called `SetupDamage` with a single argument and authored no shield rate at
    all. `None` is not zero (see `survey._nebula`), so there is nothing to
    compare.
  - The **large volume** (`origin_region` is null) has no region and no BC
    original, so the profile table is the only thing it can be held to — and
    holding it there is what stops `mist`'s zeros being quietly tuned. It
    starts enforcing real `mist` numbers the moment `mist` has them.

`region-reaches-star` and the existing geometry rules are untouched; a cloud is
not a body and cannot clip anything.

## Two contradictions this turned up in shipped data

Both are in `engine/systems/descriptions.json`, committed in `21ed51cc`.

1. **"The Federation survey station at Vesuvi IV sits inside that cloud."** There
   is no station in Vesuvi 4 — its set contains a nebula and twelve asteroids and
   nothing else. The Vesuvi outposts are `GekiStation` in Vesuvi 5 (authored at
   20 % hull) and `Facility` in Vesuvi 6. The line is wrong on its face and
   should be corrected to the damaged station at Geki.

2. **Belaruz: "The cloud … can be entered out past the first planet."** The cloud
   region anchors at 38,000 GU (BC's own pocket inside it at 38,845), inside
   Belaruz 2's orbit at **64,000** — it is the innermost thing in the system, not
   the outermost. Under the reading above this is not an error in the data but in
   the sentence, and the correction is also the more interesting fiction: the
   dust has fallen inward, and that is what the star is feeding on.

   *(Corrected: this bullet read "Belaruz 2's orbit at 69,070", and the Open
   question below read "Belaruz 4 at 121,181". Both were region-ANCHOR distances
   quoted as orbital radii. A region's anchor is offset from the body it frames,
   so the two are never the same number. The orbits in the committed map are
   64,000 / 90,000 / 116,000 GU.)*

The second depends on approving the Belaruz lobe; the first does not.

## Open question

The lobe's numbers above (`near`, `far`, `radius`) are the one part of this note
that is asserted rather than derived — BC gives us one 900 GU sphere and a
direction, and nothing that bounds the cloud the system is crossing.

**What the generated lobe actually does.** Measured against the committed
`engine/systems/maps/belaruz.json`: its axis is the unit star→pocket direction,
so BC's pocket projects onto the axis at 38,845 GU with zero perpendicular
offset, and the lobe runs on to `far_gu` = 220,000 — roughly 180,000 GU beyond
the pocket's far edge. So the thin body does stretch out well ahead of the dense
part, and that is what the description claims and what
`test_belaruzs_description_matches_where_its_cloud_actually_is` pins.

**What it does not do is envelop the system.** The planets are spread around the
star at BC's own orbital angles, while the lobe is one-sided. Projected onto its
axis, Belaruz 2 lands at *t* = −47,211 (behind the star entirely) and Belaruz 3
at *t* = 7,908 (short of `near_gu` = 20,000); only Belaruz 4 at *t* = 70,538 is
inside. Two of the three worlds are outside the lobe.

**The question, still open.** Whether that is right is the decision this section
exists to flag, and it is not made here. If the cloud should envelop the whole
system, widening `radius_gu` will not do it — Belaruz 2's axial projection is
*negative*, so it needs a negative `near_gu`, a different axis, or a different
shape altogether. If the lobe should instead stay one-sided — a wall the system
has not yet fully entered, or a shell around the outer system only — the current
numbers are already close to that reading. The description was rewritten
(`c73ad644`) to claim only what the geometry supports, so nothing is blocked on
answering this; the text and the data agree either way.
