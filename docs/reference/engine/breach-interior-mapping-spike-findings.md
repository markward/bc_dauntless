# Breach interior mapping spike — findings

**Status:** concluded 2026-10-20. **Decent results; not merged.** Mark approved
the look in game after three tuning rounds, then chose to document it rather
than merge, because the damage system is heading for a wider redesign. The code
lives on `spike/breach-interior-mapping` (tip `2eee872e0`, four commits on top
of main `2a80c14c3`), in the worktree `.claude/worktrees/breach-interior-mapping`.

## Question

Can a cheap shader effect make a hull breach read as "looking into a ship",
where today's cavity texture cannot? Today the breach scoop marches to the
cavity's far wall and paints `Damage1-4.tga` on it with a triplanar projection,
cycled at 8 fps. That has four problems:

- Four frames don't animate convincingly.
- There are no normal maps, so the surface has no depth.
- The projection ignores orientation, so decks can't run along the hull.
- The hull reads as a solid lump with a dent in it, not a hollow ship.

Note the asset is not BC's choice either: `Damage1-4.tga` are BC's tactical HUD
subsystem-damage icons, which our breach pass borrowed
(`damagetool-and-hull-damage-gaps.md`, Observations).

## Approach: interior mapping

This is the technique games use to show rooms behind windows (Spider-Man's
skyscrapers, Unreal's interior cubemaps). No room geometry exists. The shader
treats the hull as a regular lattice of rooms and finds analytically which
plane the view ray hits.

It is applied only in the breach scoop (`breach.frag`, `ih_shade`), and only
for hulls, not rocks:

1. **Lattice in the body frame.** Decks are planes along body Z. Longitudinal
   walls are planes along X, and transverse bulkheads along Y. So decks always
   run along the hull, whatever the camera does.
2. **Plane-to-plane walk.** The ray steps from one plane crossing to the next
   with a 3-D DDA, starting at the struck hull surface, for at most 24
   crossings. At each crossing:
   - If the point is outside the original hull fill, the ray has left the
     ship. Discard, exactly as before ("a hole is a hole"), so the interior
     shell behind shows instead.
   - If the per-instance damage field reads as carved there, that plate was
     blown away, and the ray keeps walking. This is what turns a carve into
     torn decks with intact rooms behind them.
   - Otherwise this plate is what the eye sees. Shade it as the floor, ceiling
     or wall of the room the ray is in.
3. **Walls come and go.** Each wall segment exists or not from a hash
   (longitudinal 55%, transverse 45%). Decks always exist. Missing walls merge
   cells into longer rooms and corridors, so the lattice does not read as a
   grid.
4. **Rooms have their own state.** Each room cell hashes to one of these:
   - lit, with a ceiling light strip along the keel; a quarter of these flicker
   - dark, with a faint spill so the room's shape still shows
   - emergency red, pulsing
   - burning, lit from the floor
5. **Surface detail is procedural.** Floors get plating seams. Walls get
   panels, a dark waist band, and doorways on bulkheads.
6. **Torn edges and depth.** Plates close to the carve threshold are charred,
   and they glow molten while the hit is fresh. This reuses the existing
   age- and distance-gated heat. Everything fades to black with depth.
7. **No new inputs.** The pass only needs a game-clock uniform and an on/off
   toggle. The fill volume, the damage field and the scene lighting were
   already bound.

## Live-tuned values (Mark, 2026-10-20)

| Knob | First cut | Final | Why |
|---|---|---|---|
| Room size, mu (beam × keel × deck) | 9 × 13 × 4 | 6 × 8.67 × 2.67 | Decks read "~50% too big" |
| Max plane crossings | 16 | 24 | Keeps the reach with smaller rooms |
| Lit-room light | 0.55 | 1.8 | "Too dark to see any detail" |
| Emergency / fire light | 0.45 / 1.4 | 1.3 / 2.4 | Same |
| Surface colour (floor / ceiling / wall) | 0.20 / 0.24 / 0.30 | 0.36 / 0.40 / 0.50 | Same |
| Depth fog distance, mu | 45 | 120 | Same |
| Room mix (lit / dark / red / fire) | 42 / 28 / 20 / 10 | 35 / 35 / 20 / 10 | Mark asked for about a third dark |

1 mu = 0.01 GU = 1.75 m, so the final decks are about 4.7 m apart.

## What worked

- **Decks run along the ship from every angle.** This was the main thing the
  texture could not do.
- **The parallax is real.** As the camera moves you see down into rooms and
  past walls, with no normal maps needed.
- **Per-room state does the animating.** Each room flickers, pulses or burns
  on its own phase, so nothing reads as a short loop.
- **The damage field gives torn decks for free.** The ragged edge comes from
  the carve threshold plus noise.
- **Rooms carry their own light.** This sidesteps the old "darkening has no
  headroom" problem noted in `breach.frag`: the interior is mostly dark, but
  there is always light inside it.

## Known limits and owed work

These were not done, because the spike was not merged:

- **Thin hull still shows the old frames.** Where the ray leaves the hull
  fill, the interior shell, the far plating's inside face, still shows the
  Damage frames.
- **No tests cover the new path.** `BreachPassGLTest` pins the legacy look.
- **Frame cost is unmeasured.** The worst case is 24 crossings with three
  texture reads each, per breach pixel.
- **Deck pitch is one global constant.** Small craft get the same 4.7 m decks.

## If it is picked up again

- **Rebase onto the redesign.** Rebase the branch, or port `ih_shade` and
  `ih_room_light`, into whatever the redesigned damage renderer is.
- **Toggle:** the developer key ` (backtick) switches between the new look
  and the legacy frames.
- **Tuning constants:** all are at the top of the interior-mapping block in
  `breach.frag`. They need `cmake -B build -S .` before the build.
