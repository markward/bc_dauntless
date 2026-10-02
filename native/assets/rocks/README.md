# Rock catalogue

Generated asteroid/rock assets: 13 "major" rocks and 24 fragments across four
families (silicate, carbonaceous, icy, metallic), each with LOD glTF meshes,
albedo/normal textures, a 16-view impostor, and a voxel volume for collision.
Centred, bounding radius exactly 100 m (see `recipe.json`'s `bound_radius_m`).

## Rock collections

`collections/<variant>_<NN>/` holds 48 baked "rock collection" impostors (16
each of `sparse`, `medium`, `dense`; recipe key `collections`): one 16-view
sprite of a whole cluster of catalogue rocks, drawn by the rock-fields mid band
as one sprite per tile. Each is `impostor_base.png` + `impostor_normal.png`,
the same 4x4 atlas layout and view directions as a single rock's impostor, and
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
