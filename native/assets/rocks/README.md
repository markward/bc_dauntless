# Rock catalogue

Generated asteroid/rock assets: 13 "major" rocks and 24 fragments across four
families (silicate, carbonaceous, icy, metallic), each with LOD glTF meshes,
albedo/normal textures, a 16-view impostor, and a voxel volume for collision.
Centred, bounding radius exactly 100 m (see `recipe.json`'s `bound_radius_m`).

Regenerate with:

```
./build/native/tools/rock_catalogue/rock_catalogue --recipe native/assets/rocks/recipe.json --out native/assets/rocks
```

Never hand-edit a generated file; change `recipe.json` or the generator and
regenerate. `tests/tools/test_rock_catalogue_drift.py` guards this catalogue
against drift from an uncommitted generator or recipe change.

The drift test is only valid on the platform that generated the catalogue —
platform libm feeds the shapes, so regenerate deliberately on a different
platform rather than expecting the committed bytes to match.
