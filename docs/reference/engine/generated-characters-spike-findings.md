# Generated characters spike — findings

**Status:** concluded 2026-10-14. Not merged. The branch was deleted after this
write-up; its tip was `2ef1340867a424726229233e8505f5c3983a6b2a`
(`spike/generated-character`), recoverable from the reflog only until git
garbage-collects it.

## Question

Can an open-source human body generator replace BC's bridge officers while
BC's own animation clips keep driving them? The test case was the XO, Saffi
(`BodyFemM.nif` + `saffi_head.nif`).

## Verdict

**Technically yes; artistically no.** A generated body runs on BC's clips,
blinks, lip-syncs and holds frame rate. It still looks jarring next to the
rest of the bridge: BC's clips are rough, and the parts that make a character
read as a person (hair, shoes, clothing, skin) do not come out of a body
generator.

Better characters need dedicated art work: character models, clothing design,
fresh animations and careful shader work, done together. That is weeks of work,
probably for a small team of skilled people, not something to grow out of
engine code.

## What was proven

- **BC's clips drive a modern body unchanged.** The generated mesh was rebound
  onto BC's own `Bip01` skeleton offline. Groups of the generator's bones mapped
  onto each BC bone, the A-pose was fitted to BC's T-pose (rotation plus a
  stretch along each bone), and the skin weights were folded onto BC's bone
  names. The clips themselves were not translated at all. Seated, standing and
  console poses all held up, in renders and live.
- **The body generator works for this.** [Anny](https://github.com/naver/anny)
  (NAVER Labs, 2025) has Apache-2.0 code and CC0 MakeHuman data. ⚠️ Its optional
  `smplx` topology is non-commercial only. It offers 11 whole-body controls,
  256 local shape controls and 52 facial blendshapes (ARKit-style). `gender=1.0`
  is female. Both rigs are Z-up, face −Y and put the character's left at +X.
- **Blinking and lip-sync carry over.** BC's face slots (`blink1`, `blink2`,
  `eyesclosed`, `a`, `e`, `u`, plus jaw openness) were baked from Anny's
  blendshapes into glTF morph targets. The existing `lip_sync_runtime.py`
  drove them with no changes. Engine side: morph offsets went into a float
  texture per mesh, added in `skinned_bridge.vert` before skinning.
- **The triangle budget is about 5–6k per officer.** The first body was 27.4k
  triangles in four primitives, and the frame rate dropped visibly. Reducing it
  to 5.5k triangles in one primitive fixed it. The reducer was meshoptimizer's
  attribute-aware simplifier, keeping a subset of the original vertices so
  UVs, weights and morphs carried over exactly. The head needs its own budget
  (here 3.5k head + 2k body): with one shared budget the head got about 1.5k
  triangles, and closed eyelids no longer covered the eyeballs.
- **Loading skinned glTF is a small change.** cgltf already parses skins and
  morph targets. Our `Skeleton` maps one-to-one onto a glTF skin, and
  name-matching joints onto the body skeleton reused the head-weld idea.

## What did not work

- **The stiff seated pose is BC's.** Rendering BC's original Saffi and ours in
  `seated_M` with the skeleton drawn over both shows identical bone poses, as
  expected from the same skeleton and the same clip. A more realistic body only
  makes the rough clip more obvious.
- **BC's skeleton fixes the proportions.** BC sets the shoulder joints wide
  (about 37 cm at her scale) and builds its mesh with the shoulders ending at
  the joint and very thin arms below. A realistically built body has shoulder
  mass beyond the joint, so it gets stretched into a broad, flat shelf.
  Narrowing the generator's shoulders changed nothing, because the fit
  stretches them back out to BC's joints. Better proportions need a different
  skeleton, which means new animations.
- **Procedural appearance has a low ceiling.** A texture painted from rules on
  the fitted surface (skin, makeup, brows, eyes, the First Contact uniform) and
  a sculpted hair shell got as far as "recognisably an officer", and no further.
  Hair reads as a helmet, the face looks painted, and shoes and clothing folds
  don't exist.

## Traps worth remembering

- **The bridge shader ignores `Material::diffuse`.** It only samples textures,
  so a flat-colour material draws white. That is why the first version had
  blank eyes.
- **Height-based rules catch the arms in a T-pose.** The arms sit at neck
  height, so any "above the collar" rule paints them too. Limit such rules to
  the head column.
- **meshoptimizer 0.2.30a0 has a broken wrapper.** Its Python
  `simplify_with_attributes` passes a bare float to ctypes; call the C function
  directly with explicit `argtypes`.
- **Generated assets embed BC data.** A fitted model carries BC skeleton
  transforms, so it is BC-derived and must never be committed.

## If this is picked up again

The engine pieces generalise to artist-made characters: skinned and morphed
glTF loading, name-matched joints, morph slots driven by lip-sync. An art
brief would start from:

- **Skeleton:** characters on a known skeleton, either BC's `Bip01` or a new one
  supplied with its own animations.
- **Face:** shapes named after BC's face slots.
- **Hair and clothing:** modelled and textured as real assets, not painted onto
  the body.
- **Budget:** about 5–6k triangles per officer, with the head budgeted
  separately.
