# Rock catalogue

Generated asteroid/rock assets: 13 "major" rocks and 24 fragments across four
families (silicate, carbonaceous, icy, metallic), each with LOD glTF meshes,
albedo/normal textures, a 64-view impostor, and a voxel volume for collision.
Centred, bounding radius exactly 100 m (see `recipe.json`'s `bound_radius_m`).

## Impostors

Every rock's impostor is an 8x8 atlas of 64 orthographic
views (rock-blend, 2026-10-03; was 4x4 / 16 Fibonacci views). The views are
the CORNER-sampled grid points of an octahedral map of the sphere (glTF
frame, pole axis +y): view `v = 8j + i`, in cell `(i, j)`, looks from
`oct_decode((2i-7)/7, (2j-7)/7)`; `catalogue.json`'s `impostor_view_dirs`
lists them. The border views fold onto each other in mirror pairs with
bit-identical directions and pictures (49 distinct directions) -- the price
of a lookup with no search: the renderer (`renderer::far::view_blend`)
blends the 3 views of the grid triangle around the eye, continuous
everywhere, so a tumbling billboard is a smooth, closed loop. Each cell is
half the old resolution (`impostor_view_size` 64), so the atlases keep their
old pixel size (512 px).
`rockgen::impostor_view_dirs` and `renderer::far::oct_decode` are copies of
one rule, not linked; `tests/unit/test_rock_catalogue.py` checks the
manifest against it.

## Regenerating

Regenerate with:

```
./build/native/tools/rock_catalogue/rock_catalogue --recipe native/assets/rocks/recipe.json --out native/assets/rocks
```

Never hand-edit a generated file; change `recipe.json` or the generator and
regenerate. `--only <id>` (a rock id such as `majors/silicate_01`) rewrites
just that rock and leaves the manifest alone. `tests/tools/test_rock_catalogue_drift.py` guards
this catalogue against drift from an uncommitted generator or recipe change.

The drift test is only valid on the platform that generated the catalogue —
platform libm feeds the shapes, so regenerate deliberately on a different
platform rather than expecting the committed bytes to match.
