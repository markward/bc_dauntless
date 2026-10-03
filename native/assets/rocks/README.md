# Rock catalogue

Generated asteroid/rock assets: 13 "major" rocks and 24 fragments across four
families (silicate, carbonaceous, icy, metallic), each with LOD glTF meshes,
albedo/normal textures, a 64-view impostor, and a voxel volume for collision.
Centred, bounding radius exactly 100 m (see `recipe.json`'s `bound_radius_m`).

## Impostors

Every impostor (rocks and collections) is an 8x8 atlas of 64 orthographic
views (rock-blend, 2026-10-03; was 4x4 / 16 Fibonacci views). The views are
the CORNER-sampled grid points of an octahedral map of the sphere (glTF
frame, pole axis +y): view `v = 8j + i`, in cell `(i, j)`, looks from
`oct_decode((2i-7)/7, (2j-7)/7)`; `catalogue.json`'s `impostor_view_dirs`
lists them. The border views fold onto each other in mirror pairs with
bit-identical directions and pictures (49 distinct directions) -- the price
of a lookup with no search: the renderer (`renderer::far::view_blend`)
blends the 3 views of the grid triangle around the eye, continuous
everywhere, so a tumbling billboard is a smooth, closed loop. Each cell is
half the old resolution (`impostor_view_size` 64, collections 88), so the
atlases keep their old pixel size (512 px rocks, 704 px collections).
`rockgen::impostor_view_dirs` and `renderer::far::oct_decode` are copies of
one rule, not linked; `tests/unit/test_rock_catalogue.py` checks the
manifest against it.

## Rock collections

`collections/<variant>_<NN>/` holds 48 baked "rock collection" impostors (16
each of `sparse`, `medium`, `dense`; recipe key `collections`): one 64-view
sprite of a whole cluster of catalogue rocks, drawn by the rock-fields mid band
as one sprite per tile. Each is `impostor_base.png` + `impostor_normal.png`,
the same 8x8 atlas layout and view directions as a single rock's impostor, and
baked by the same rasteriser (`rockgen::bake_impostor_parts`;
`bake_impostor` is its one-part case).

The arrangement is deterministic from the recipe seed and the collection id:
centres uniform in the unit ball, radii a power law over `size` (fractions of
the collection radius, `exponent`), random orientation, meshes (lod1) from the
`family`'s fragments below radius 0.08 and its majors at or above it, then
rescaled so the union's bounding sphere has radius exactly 1 m. The variant's
`rocks` range sets the part count. `catalogue.json` lists them under
`collections` with `avg_albedo`, the coverage-weighted mean of the albedo
atlas. The contact sheet shows rocks only.

Collections picture GRAVEL, never a big asteroid (rock-real Part 2,
2026-10-03): a sprite is a picture with nothing real behind it, so no pictured
part may read as a big rock where it is shown. At the largest L0 sprite
(half-size 0.5 x 150 GU x 1.2) the largest part, `size` max 0.011, is 0.99 GU
-- within the smallest real large rock (1 GU); real big rocks come from the
near band's far shell instead. Thousands of parts per collection (3,000-10,000,
all fragments) keep them reading as rock clouds, baked at 176 px per view
(704 px atlases: 48 x 2 maps = 1.89x the memory of the original 128 px bake;
a 128 px bake left 1-2 px parts magnified ~7x at L0 into blocky noise). The
64-view bake (rock-blend) keeps the 704 px atlas at 88 px per view, so a
view's parts are half that resolution again -- not yet checked live (the mid
band is off by default).
`tests/tools/test_rock_catalogue_drift.py` pins both the size bound and the
2x memory budget. GPU cost of the collection atlases once all are loaded:
48 x 2 x 704^2 RGBA8 = 181.5 MiB (~190 MB), ~242 MiB (~254 MB) with the
mip chain FarPass generates (x 4/3).

## Regenerating

Regenerate with:

```
./build/native/tools/rock_catalogue/rock_catalogue --recipe native/assets/rocks/recipe.json --out native/assets/rocks
```

Never hand-edit a generated file; change `recipe.json` or the generator and
regenerate. `--only <id>` (a rock id such as `majors/silicate_01` or a
collection id such as `collections/dense_00`) rewrites just that output and
leaves the manifest alone. `tests/tools/test_rock_catalogue_drift.py` guards
this catalogue against drift from an uncommitted generator or recipe change.

The drift test is only valid on the platform that generated the catalogue —
platform libm feeds the shapes, so regenerate deliberately on a different
platform rather than expecting the committed bytes to match.
