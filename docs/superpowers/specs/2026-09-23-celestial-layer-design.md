# The celestial layer — making a star system visible from inside it (design)

**Date:** 2026-09-23
**Status:** design, for approval. Not implemented.
**Implements:** §2, §4 and the first half of §3 of
`docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`
**Amends:** §4 of that spec — see "Amendment" at the end.
**Area:** `engine/host_loop.py`, `engine/appc/sets.py`, a new resolution module,
`native/src/renderer/sun_pass.cc`, `native/src/renderer/lens_flare_pass.cc`

## Goal

Thirty-two system maps are checked in and nothing reads them. This makes one of
them visible: standing anywhere in a system, you see that system — its real star
in a consistent direction, its other worlds at their true bearings and distances,
all of them real objects you can target and orbit, at the sizes the maps specify.

It is general. There is no per-system code; a set resolves to a system through
the checked-in maps or it does not, and anything that does not behaves exactly
as it does today.

## What you would see

Measured from Ona 1's anchor, against `engine/systems/maps/ona.json`:

| | Distance | Apparent size |
|---|---|---|
| Ona 1 — the planet you are framed on | 5,997 GU | **33.4°** |
| The star | 34,097 GU | 32.7° |
| Ona 2 | 93,538 GU | 2.2° |
| Ona 3 | 96,211 GU | 2.1° |

Ona 2 at 2.2° is about four full moons wide — a disc, not a dot. Those are the
two goals from the parent spec, in priority order: continuity between places, and
planets that fill the sky.

**None of it renders today.** The exterior camera's far plane is 5,000 GU
(`host_loop.py:9661`), so every row of that table is outside the frustum —
including Ona 1 itself, because ×20 scaling pushed its framing distance to
5,997 GU. The local body is the *first* thing to disappear, not the last.

## The far plane

**Raise it from 5,000 GU to 450,000 GU.**

The widest sightline in the game is **Itari, 420,676 GU** (73,618 km) — the
greatest distance between any two bodies or anchors across all thirty-two maps.
450,000 covers it with margin.

**Depth precision is not the objection it appears to be.** For a 24-bit
fixed-point forward-Z buffer, the resolvable gap at eye distance `z` is
`Δz ≈ (1/2²⁴) · z² · (f−n)/(f·n)`. The `(f−n)/f` term is already ~1 at
`f = 5000`, so raising `f` barely moves it:

| Eye distance | `far = 5,000` | `far = 450,000` |
|---|---|---|
| 100 GU | 0.000596 GU | 0.000596 GU |
| 4,900 GU | 1.4308 GU | 1.4311 GU |

**0.02%.** Precision in forward-Z is governed by the **near** plane: halving
`near` from 1.0 to 0.5 costs twice as much as a ninetyfold increase in `far`.
`near` stays at 1.0 and this design does not touch it.

The alternative considered and rejected was a separate celestial pass with its
own depth range, modelled on `backdrop_pass.cc`. It buys isolation from a
precision problem that does not exist, at the cost of a new pass plus seamless
handover logic for every body crossing 5,000 GU. One number is better.

### Every consumer of `camera.far`, audited

Three passes read it. A fourth is fed it explicitly.

**`nebula_volumetric_pass.cc:162` → `nebula_volumetric.frag` — no change.**
The march interval comes from `union_interval` over the nebula's own spheres,
clamped by `scene_dist` from the depth buffer. `u_near`/`u_far` are used only to
reconstruct world position from depth, which is the exact inverse of the
projection and therefore correct at any far. Step count and quality are
unaffected.

**DOF (`host_bindings.cc:1399` feeds it `g_camera.near, g_camera.far`) — accept
a slight softening.** Two effects:

- The starfield exemption is `if (z >= u_far * 0.98) return 0.0`, expressed as a
  *fraction* of far rather than a constant, and the backdrop pass writes no
  depth, so those pixels hold the clear value and stay exempt at any far.
- Bodies at real distances are no longer beyond `0.98 · far`, so they enter the
  background branch: `min((1 − focus/z)·FAR_STRENGTH, FAR_CEILING)`. As `z`
  grows this saturates at `FAR_CEILING = 0.2`, scaled by
  `MAX_RADIUS_FRAC = 0.006` — a blur radius of 0.0012 of screen height, about
  **1.3 px at 1080p**. Mild, and arguably correct for something 90,000 GU away.

No retune is proposed. If it reads wrong in the live pass, the fix is an
exemption for celestial bodies, not a change to the curve.

**`sun_pass.cc:119` and `lens_flare_pass.cc:93` — a real bug this change
exposes.** Both re-place their object at `virtual_distance = camera.far * 0.95`
and scale its radius to preserve apparent size. That is **unconditional**, which
is harmless today because everything real is inside 5,000 GU.

With a real far it is wrong. Standing in Ona 1, the star is 34,097 GU away and
Ona 3 is 96,211 GU away on the far side of the system. The star should visibly
occlude Ona 3. `sun_pass` would draw it at 427,500 GU — *behind* the planet it
is in front of.

**Fix: make the virtual-distance treatment conditional** — apply it only when
the object is genuinely beyond the far plane, otherwise draw at true position
with true radius. After this change BC's suns (~70,000 GU) are inside the
frustum, so the path is never taken, and suns render where BC put them. The
branch stays because the trick is still correct for anything that ever does
exceed the far plane.

## Residency

**Resolution.** A map from set name to `(system, region)`, built once from the
checked-in maps — `Ona1` → Ona, `Vesuvi4` → Vesuvi. Every set BC has that
appears in a map is covered. Anything absent (the bridge, QuickBattle arenas, the
seven single-set multiplayer systems) resolves to nothing and behaves exactly as
today. This is the only place system membership is decided.

**Entry is when the player's set resolves to a system that is not the current
one.** That covers every arrival — Set Course, a mission load, a developer
mission swap — because all of them end with the player in a set. There is no
separate "enter the system" call to forget.

**Entering a system creates all of its regions.** Not the one the player
arrived in — all of them. That is what makes the other worlds *objects* rather
than pictures, which §2 of the parent spec requires:

> A region's bodies remain objects **in that region's set** … This is what keeps
> the Orbit command, `GetObject("Haven")`, hailable planets and the target list
> working with zero changes.

**`DeleteSet` is suppressed within a system.** Today `warp.py:_WarpDepartAction`
destroys the set you leave. Within one system that must stop, or the bodies you
can see cease to exist the moment you travel. This is engine rule E of the
parent spec.

**Teardown is on leaving, and "leaving" means any set that is not this system's.**
Arriving in another system's region tears the old one down and builds the new.
Arriving somewhere that resolves to no system at all — the bridge, a QuickBattle
arena, a multiplayer set — tears the old one down too and builds nothing. A
system is never left resident behind a set that is not part of it.

**Missions are included.** A scripted mission loads its system like any other
arrival. The sky is the real system whether you arrived by Set Course or because
E1M1 put you there. The alternative — missions loading a single set as today —
was rejected: it makes the sky depend on how you arrived at the same place, and
absents the continuity this work exists to deliver from most of the game.

Two consequences, both accepted deliberately:

- Thirty-three campaign missions now load several sets where they loaded one.
- A player can fly out of a mission's staging area toward another planet
  mid-mission. There is no hand-off yet, so they cannot arrive; they can only
  leave. That is a gap this design closes in the next slice, not a defect.

## Applying the map

When a region's set is created, each body in it takes the map's **radius** and
the map's position expressed in that set's local coordinates:

```
local_position = body.position_gu − region.anchor_gu
```

Nothing is created, nothing is deleted, no model is swapped. A BC planet at
538 GU with a 110 GU radius becomes the same object at ~6,000 GU with a 2,200 GU
radius. That is §2's substitution, and it is what makes `GetObject`, hailing,
the target list and Orbit keep working untouched.

**Mission staging does not move with it.** A mission's authored waypoints are
set-local and stay where BC put them, so a body that moves away from the origin
moves away from the ships staged beside it. The parent spec's `pins` mechanism
exists for exactly this and is already declared in the overrides block; it is
unchanged here.

### The star is the case the map exists to fix

BC's suns are **per-set lighting props, not a system object**, and they
contradict each other inside a single system: `Alioth1`'s sun sits at
`(+70000, 0, 0)` and `Alioth3`'s at `(−70000, 0, 0)`. Two of the campaign
systems — Belaruz and Vesuvi — author no `Sun_Create` at all while still
carrying a bright directional light. A consistent light direction is the first
thing the parent spec promises, so the star cannot be left to the sets.

The map's star is a `Body` at the system origin with `orbits: None`. Apply it
the same way as any other body, with two differences:

- **A region that has a Sun object keeps it, repositioned.** Its position
  becomes `(0,0,0) − region.anchor_gu` and its radius the map's. Every region's
  sun then occupies the same point in system space, which is the correction.
- **A region that has none gets one created** from the map. This is the single
  exception to §2's "no object is created", and it is deliberate: Belaruz and
  Vesuvi render bright directional light from a source BC never placed. The
  parent spec's ruling was to *honour the light but correct the lack of source*,
  and their `overrides.star` blocks already declare what that source is.

**Only the player's own region contributes its sun to the scene.** After the
repositioning above, every region's sun occupies the same system-space point, so
drawing one is correct and drawing eight is waste. This is the one place the
celestial gathering below scopes to a single region rather than the system.

## Gathering the celestial bodies

`host_loop.py:4159`'s `_live_sets()` returns just the active set, so
`_iter_planets` and `_iter_suns` see one region's sky. Its docstring says why —
it stops one system's bodies bleeding into another's scene — and that reason
survives: the scope becomes **the current system** rather than **all sets**.

Planets gather from every region of the current system, each shifted into the
player's frame:

```
render_position = body_local_position + (body_region.anchor_gu − player_region.anchor_gu)
```

Translation only, never rotation — the anchor rule from the parent spec.

**Suns are the exception**, per "The star is the case the map exists to fix"
above: every region's sun has been repositioned to the same system-space point,
so `_iter_suns` stays scoped to the player's own region. Widening it would draw
up to eight coincident stars.

**Ships stay scoped to the active set.** That is what bounds the cost: a
system's body count (~15 for the largest) rather than every resident region's
traffic. Distant regions keep simulating — their AI runs and their mission state
advances — they simply contribute no ships to the scene.

## Deliberately out of scope

- **The hand-off.** Crossing a region boundary does nothing. §3's second half.
- **The dash.** In-system warp. §5.
- **Distance-based render streaming.** Every resident region's bodies are
  realized; nothing is dropped by distance yet.
- **Clouds.** `SystemMap.clouds` is checked in and stays unread.

## Unknowns to measure, not guess

- **What a 2,200 GU planet lit by a real star at real distance looks like.**
  BC's planet art was authored against a 70,000 GU stand-in sun. This is the
  first time it is lit by a star at a true, varying distance and direction.
- **What eight resident sets cost.** The largest systems have eight regions
  where today one is resident. Bodies are simple objects at distance and this is
  expected to be cheap, but that is an expectation. The frame profiler against a
  combat scene is the check, per the parent spec.
- **Whether ×20 bodies collide correctly**, and whether the environmental-damage
  band — authored separately and not scaled — still sits where it should.

## Amendment to the parent spec

§4 of `2026-09-22-in-system-navigation-design.md` currently reads:

> Bodies beyond normal draw range use the **virtual-distance** treatment the
> renderer already applies to suns and lens flares (`sun_pass.cc:119`,
> `lens_flare_pass.cc:93`): drawn at a scaled distance preserving apparent size,
> so the far plane need not stretch to 100,000 GU and depth precision is
> unaffected.

That mechanism is rejected on measurement. Stretching the far plane costs 0.02%
of depth precision — the concern the sentence was written to avoid does not
exist — while the virtual-distance treatment would crowd up to fifteen bodies
into one thin slab against the far plane and require them to be re-ordered
against each other and handed over as they cross 5,000 GU.

§4's *intent* is unchanged and this design delivers it: bodies appear at their
true bearing and distance, lit by the same star, with correct parallax, and are
genuinely where they appear to be rather than a painted backdrop. Only the
mechanism changes, and it changes to something simpler.
