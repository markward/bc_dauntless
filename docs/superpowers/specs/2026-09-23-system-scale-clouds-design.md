# System-scale clouds — the first thing a system owns that a region does not (design)

**Date:** 2026-09-23
**Status:** design note, for approval. Not implemented.
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

The `debris_ring` / `nebula_field` distinction is not something we are inventing
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
cloud has no single position and no radius: Vesuvi's is an annulus around the
star, Belaruz's is a lobe the system is moving into. Forcing either into a
centre-and-radius loses the shape that makes it what it is, and `orbits` is
meaningless for both.

It is also not a `Region`. A region is a BC set with local coordinates and a
streaming lifecycle. A cloud is neither loaded nor unloaded; it is terrain.

So: a third list on `SystemMap`, alongside `bodies` and `regions`.

## The data shape

```python
@dataclass
class Cloud:
    name: str                  # "Vesuvi Debris Field"
    display_name: str
    kind: str                  # "debris_ring" | "nebula_field"
    color: tuple               # BC's own MetaNebula RGB, verbatim
    envelope: dict             # kind-specific EXTENT -- see below
    spheres: list              # SUBSTANCE, in SYSTEM coordinates
    params: dict               # BC's MetaNebula numbers, verbatim
    regions: list              # set names the cloud passes through
```

`params` carries BC's four authored numbers unchanged — `visibility_gu`,
`sensor_density`, `damage_hull_per_s`, `damage_shield_per_s`. Belaruz's damage
pair is `0.0, 0.0` because BC never called `SetupDamage`, not because we decided
its cloud should be gentle.

### Envelope is extent; spheres are substance

This is the load-bearing distinction, and it answers the
scenery-versus-substance question without inventing a category.

- The **envelope** is a volume that renders and does nothing else. It is what
  you see from Vesuvi 6 and what tells you the system has a ring. No damage, no
  sensor effect, no collision.
- The **spheres** are `MetaNebula` volumes in system coordinates. Being inside
  one applies `params` exactly as BC's engine does. They are the only part of a
  cloud with gameplay consequence.

Today each cloud has exactly one sphere: the one BC authored, transformed
through its region's anchor. That sphere is **pinned** — generated from the
survey, never moved, never regenerated — on the same footing as a pinned body.

This is what makes the two scales one phenomenon rather than two facts that can
drift. The region keeps `Region.nebula` in **set-local** coordinates because
that is what the set needs when it loads and creates the `MetaNebula`; the cloud
holds the same sphere in **system** coordinates because that is what the
celestial layer needs. One source (the survey), two consumers, two coordinate
spaces — and a validator that proves they still agree.

### Vesuvi — `debris_ring`

```json
"envelope": {
  "shape": "annulus",
  "inner_gu": 28655.0,
  "outer_gu": 61567.0,
  "half_thickness_gu": 3456.0,
  "normal": [0.0, 0.0, 1.0]
}
```

Centred on the star, lying in the orbital plane — `_orbit_point` places every
body at `(r·sin a, r·cos a, 0)`, so `z = 0` is the plane by construction, even
though anchors carry a little `z` of their own.

Every number is derived, none is chosen:

- **inner** = Vesuvi 1's orbit minus its region radius (32,000 − 3,345). Vesuvi 1
  is where the Core Fragment is.
- **outer** = Vesuvi 4's orbit plus its region radius (58,000 + 3,567). Vesuvi 4
  is where the Unknown Debris is.
- **half-thickness** = the mean region radius of the two member regions.
- It stops well short of Vesuvi 5 at 80,575, which is right: Geki and Haven are
  outside the ring, which is how they are still inhabited.

The ring spans exactly the regions that carry debris. That is the whole rule.

### Belaruz — `nebula_field`

Not centred on the star, because the star is not the cause.

```json
"envelope": {
  "shape": "lobe",
  "axis": [0.0, 1.0, 0.0],
  "near_gu": 20000.0,
  "far_gu": 220000.0,
  "radius_gu": 160000.0
}
```

A body of interstellar dust the system is ploughing into, thickening along one
direction. BC's authored pocket sits at `(-17, 38845, -30)` — 38,845 GU out —
and the `axis` above is simply the direction from the star to that pocket,
normalised. The envelope is then the lobe that pocket is the leading tip of.

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
| Far | System body, drawn from any region | Envelope, drawn from any region |
| Near | Same system body, up close | The cloud's own spheres |
| BC's authored object | **Deleted** — the system body replaces it | **Kept** — it *is* the sphere, in the coordinates the set needs |

A planet is one object at two distances. A cloud is one object with an outer
form and an inner substance, and you are inside the outer form long before you
reach the inner. That is not a compromise; it is what a cloud is.

Concretely: from Vesuvi 6 you see a ring around the remnant. Flying inward, the
envelope resolves into a band you are crossing, and the ring's rendering gives
way to Vesuvi 4's `MetaNebula` — at which point visibility drops to 145 GU, your
sensors degrade by 10.5, and your hull starts taking 150 a second. Nothing about
the envelope caused any of that. The sphere did.

## What this note deliberately does not decide

**Seeding the ring with asteroids and further pockets.** The envelope is a
seeding volume and that is the obvious next use for it, but every question that
raises — how many, how dense, whether seeded pockets carry `params`, how a
40,000 GU band of 150 hull/s could possibly be survivable — belongs to that work
and not to this one. What this note commits to is that the envelope renders and
does nothing, and the spheres do what BC says. A ring you can see and fly through
harmlessly, with one lethal pocket where BC put one, is honest and complete on
its own.

**Vesuvi 4's twelve asteroids and Vesuvi 1's asteroid field.** They are set
content, created by `loadspacehelper.CreateShip` at set waypoints, and the region
model already carries set content across untouched. They are evidence for what
the ring is; they are not migrated into it.

## Validation

Three new rules for `engine/systems/validate.py`, which never raises:

- **`cloud-sphere-agrees-with-region`** — every sphere with an `origin_region`
  must equal that region's `anchor_gu + Region.nebula.spheres[i]`, within
  tolerance. This is the anti-drift guard: it is the rule that makes "two
  coordinate spaces" not mean "two sources of truth".
- **`cloud-region-membership`** — every set name in `Cloud.regions` exists, and
  every region carrying a `nebula` is named by exactly one cloud.
- **`cloud-envelope-contains-spheres`** — every sphere lies inside its cloud's
  envelope. A pocket outside its own ring means the derivation is wrong.

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
   region anchors at 38,000 GU, inside Belaruz 2's orbit at 69,070 — it is the
   innermost thing in the system, not the outermost. Under the reading above this
   is not an error in the data but in the sentence, and the correction is also
   the more interesting fiction: the dust has fallen inward, and that is what the
   star is feeding on.

The second depends on approving the Belaruz envelope; the first does not.

## Open question

The lobe's numbers above (`near`, `far`, `radius`) are the one part of this note
that is asserted rather than derived — BC gives us one 900 GU sphere and a
direction, and nothing that bounds the cloud the system is crossing. They are
sized to reach past Belaruz 4 at 121,181 GU so that the outer system sits in thin
material, which is what the description claims. If the lobe should instead be a
wall the system has not yet fully entered, or a shell around the outer system
only, that is a call to make before generating.
