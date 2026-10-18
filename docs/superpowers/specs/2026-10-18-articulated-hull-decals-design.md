# Hull name decals on articulated parts — design

Date: 2026-10-18. Branch `fix/articulated-hull-decals`, from integration branch
`int/2026-10-18-01`. Status: **implemented and live-verified** (option 1 below; merged
into `int/2026-10-18-01` as `4aefe4cd`, to main as `5fc58ec8`; Mark checked §8 on the LC
Intrepid's nacelles, 2026-10-18).

## 1. Why

The LC Intrepid (the first Dauntless-native mod) needs name decals soon, and its
warp nacelles articulate: parts `wing left` / `wing right` swing about 40° into
a `warp` pose (`_dauntless_spv` block of
`mods/LC Intrepid Pack/scripts/ships/Hardpoints/LCintrepidHP.py`). Today a decal
painted on a nacelle stays where the nacelle *was* while the nacelle moves
away. The hull-name-decals spec (`2026-09-28-hull-name-decals-design.md`, §7)
and the SPV decal-editing spec (§ non-goals) both deferred this.

Success: a decal authored on a nacelle at the NIF pose stays glued to the
nacelle's surface through the whole transition into and out of the warp pose,
and leaves with the nacelle when it is shot off. Every ship that is not
articulated renders exactly as before.

## 2. How the pieces fit today (verified against the tree)

- **Projector.** `opaque.frag:apply_hull_decal` projects `p_body =
  inverse(ship world) · v_position_ws` through `u_decal_proj[i]`, tests facing
  with `n_body`, and samples the mask with gradients `mat3(u_decal_proj[i]) ·
  dFdx/dFdy(p_body)` taken outside all branches. `p_body` is the POSED body
  position; the projector is fixed in the REST (NIF) frame — hence the slide.
- **`u_node_rest_fix`.** Per node, `C_i = R_i · P_i⁻¹` (`node_anim.cc:
  rest_corrections`): the node's rest world over its posed world, both composed
  with an identity instance world. It maps a posed body point back to where it
  was authored. `frame.cc` sets it on EVERY mesh draw (identity for an
  unarticulated instance, for a skinned draw, for a node whose chain has no
  override, and for a severed node, whose posed matrix is singular). Its only
  reader today is the glow-region test (`opaque.frag` ~line 1938), which solved
  the same problem for glow (`2026-09-25-glow-region-articulation-design.md`).
- **Which part a decal paints.** A placement's optional `shape` restricts it to
  that shape's meshes (per-mesh enable bit, `model_build.cc:apply_decals`). An
  empty `shape` paints every mesh it projects onto.
- **Severance.** `part_detach_render` draws a shot-off part as a SECOND
  INSTANCE OF THE SAME MODEL with every other part hidden; the ship hides the
  part with a zero-matrix override (collapsed to a point). Production decals
  are baked into the model at `load_model`, so the chunk carries them; the
  chunk's part has no override on its chain, so its `C` is identity.
- **SPV authoring.** A Decals-pane click traces the POSED mesh
  (`ray_trace_mesh` composes the instance's node overrides) and stores the hit
  as-is via `host_io.world_to_body`. Placements are new with `shape = ""`. The
  SPV opens at the NIF pose and poses the ship only while a `{State}
  Transformation` node is selected (`_sync_part_pose`).

## 3. Goals

1. A decal on an articulated part follows the part in every pose, including
   mid-transition.
2. A decal on a shot-off part leaves with the part (the chunk shows it; the
   ship no longer does).
3. A decal placed in the SPV on an articulated part is stored in the rest frame
   and restricted to the clicked shape, so it cannot ghost onto the hull.
4. Unarticulated ships, and articulated ships in their rest pose, render
   byte-identically to today.

## 4. Non-goals

- Authoring the Intrepid's real lettering or masks (artwork; Mark).
- Previewing decal motion inside the SPV while a state pose is shown. Motion
  is proven by the render tests and by Mark's in-game check.
- The SPV's live per-instance decal override reaching a severed chunk (dev
  preview only; production decals are baked into the model).
- **Shared decal file across rigged and unrigged ships (accepted).**
  `decals.json` is found by the model folder, and `LCintrepidModel/` holds
  `LCintrepid.nif`, `LCbellerophon.nif` and `LCvoyager.NIF` with the same shape
  names. Intrepid and Bellerophon share the wing rig; Voyager has none. A
  nacelle decal authored on the Voyager gets no `shape` (rule 2), and in the
  shared file it could paint the Intrepid's pylons where the nacelle sat at
  rest while the nacelle is in the warp pose. Workaround: author nacelle
  decals on the Intrepid or Bellerophon. Not fixed here.
- **Known, separate:** a chunk spawns at the part's REST pose, not its current
  pose, so a nacelle shot off in the warp pose snaps to its folded position as
  it flies off. Unrelated to decals; recorded here as a follow-up only.

## 5. Anti-goals

- Any visible change on a ship that does not articulate (the Ambassador's
  names in particular).
- A new data field or `decals.json` format change. `shape` already names the
  part.
- A second correction matrix or a second definition of "rest". The decal
  correction is the glow correction, `u_node_rest_fix`, unchanged.

## 6. Design

### 6.1 Renderer (the fix — option 1, Mark's pick)

In the hull-decal loop, feed `apply_hull_decal` the REST-frame position, normal
and gradients:

- `p_rest = (u_node_rest_fix · vec4(p_body, 1)).xyz`
- `n_rest = mat3(u_node_rest_fix) · n_body`
- gradients: `mat3(u_node_rest_fix) · dpdx_d` and `· dpdy_d`. `C` is constant
  over the draw, so this is exactly the screen derivative of `p_rest`; keep
  taking the derivatives OUTSIDE every branch, as today.

Only the hull-decal call changes. `p_body` / `n_body` / `dpdx_d` / `dpdy_d` keep
their current values for every other consumer (scuffs, carve, damage decals,
hull field) — those have their own frames and are out of scope.

No `normalize` on `n_rest`, for the reason the glow path documents: `C` is
rigid, and `mat3(identity) · n == n` exactly, which is what keeps the
unarticulated path byte-identical. Likewise `identity · vec4(p, 1)` is exact in
float.

No C++ change is expected: `frame.cc` already sets `u_node_rest_fix` on every
mesh draw before the shader runs. The builder confirms that every path that
draws hull decals goes through that per-mesh set (or sets identity); a path
that draws decals without it would read a stale matrix from the previous ship.

### 6.2 SPV authoring

1. **Rest pose while placing.** Decal placement and the decal gizmo operate at
   the NIF pose. If the Decals pane can be active while a `{State}
   Transformation` preview poses the ship, entering the pane (or a click in it)
   must put the ship at the NIF pose first, the same way `_sync_part_pose` does
   for any non-state selection. If the existing selection model already makes
   this impossible, the builder pins that with a test instead of adding code.
   *(Claude's call: authoring at rest beats converting posed clicks back to
   rest, because the pane's gizmo and outlines are drawn in the rest frame too —
   a posed click converted to rest would still show its gizmo off the nacelle.)*
2. **Shape auto-fill on articulated parts.** When the mesh under a placement
   lies under a part that THIS SHIP's rig articulates (a part name the ship's
   articulation knows, matched against the mesh's node chain), set the
   placement's `shape` to that mesh's shape name. Use
   `host_io.ray_trace_mesh_pick` (it returns the mesh index) and
   `host_io.model_identity` (mesh → name, node chain). A mesh not under an
   articulated part leaves `shape` empty, as today, so hull placements keep
   painting across meshes. The builder verifies that `model_identity`'s mesh
   `name` is the same string `apply_decals` matches against
   (`Mesh::shape_name()`; the Ambassador entry is `amb saucer:0`).
   - **Single shape, not the whole part** (Mark 2026-10-18: "doesn't matter,
     what's the easiest" → this, because it needs no C++ change). Each LC
     nacelle is two material-split shapes (`wing left:0` large, `wing left:1`
     small); lettering that crosses onto the small one gets a gap there.
     Accepted.
   - *(Claude's call: "articulated on this ship", not "any part candidate":
     `model_parts` candidates are the children of Scene Root, which include
     the main hull, so that rule would restrict every hull click.)*
3. **Re-derive after every move** *(Claude's call)*. Any edit that changes a
   placement's centre re-derives `shape` by rule 2. Add and Reposition take
   the mesh the click itself hit (`ray_trace_mesh_pick`), so a surface proud
   of the clicked one (`wing left:1` over `wing left:0`) cannot win. A gizmo
   Move (each drag step), Paste, a typed coordinate and Mirror re-trace at the
   placement's new centre along its −normal. So Mirror of a `wing left:0`
   decal lands as `wing right:0`; a move onto the plain hull clears `shape` to
   `""`; a click or trace that misses keeps the old `shape`. Rotate and Scale
   do not move the centre and leave `shape` alone. Only a shape on an
   articulated part is cleared; a hand-authored shape off the parts (the
   Ambassador's `amb saucer:0`) is kept.

### 6.3 Docs

- `2026-09-28-hull-name-decals-design.md` §7 line on articulated shapes and
  `2026-09-28-spv-decal-editing-design.md` non-goal: point at this spec.
- `2026-10-17-subsystem-physical-parents-design.md` ~line 339 (the decal-slide
  note): mark as resolved by this spec.
- CLAUDE.md "Hull name decals" row: replace "⚠️ No `u_node_rest_fix`: an
  ARTICULATED-shape decal slides with the part" with the new rule (decals use
  `u_node_rest_fix`; SPV places at rest and auto-fills `shape` on parts). Keep
  the row within its current length budget.

## 7. Testing

C++ render tests in `native/tests/renderer/decal_render_test.cc`, through the
real submit path on the real Ambassador (the file's existing pattern), modelled
on `frame_test.cc`'s `GlowRegionFollowsARotatedNode` family:

1. **Follows a rotated node.** A decal restricted to a shape; override that
   shape's node (or the root) with a rotation; the painted pixels move with the
   surface, and the old screen location no longer shows the mask.
2. **Rest-pose override is byte-identical.** An override equal to the node's
   own rest local renders with zero differing texels against no override.
3. **No leak across draws.** An articulated ship drawn first does not shift a
   plain ship's decal (the uniform-persistence trap).
4. **Severed chunk.** An instance with every node but the decal's hidden (the
   chunk shape) still shows the decal at the part; the ship instance with only
   that node hidden shows none of it.

Python tests for §6.2 in the SPV decal-pane test file(s) the builder finds
(`tests/ui/` — focused files only): rest pose forced on placement; `shape`
filled on an articulated-part hit, left empty on a hull hit; re-derived on
Reposition, gizmo Move, Paste and Mirror (left → right, part → hull
clears, a miss keeps the old value); untouched by Rotate and Scale.

Shader edits surface at runtime: after the edit, `cmake -B build -S .` (the
embedded header regenerates only at configure), rebuild, grep the embedded
header for the new code, and run the bounded headless boot
(`OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_PROFILE_FRAMES=60 ./build/dauntless
--developer`, grep for `Traceback|Shader compile|error`).

⛔ Focused test files only — never `scripts/check_tests.sh`, never a whole
pytest suite (`tests`, `tests/unit`, `tests/ui`). The machine is in use for
performance testing. ⛔ No destructive git (CLAUDE.md list).

## 8. Live check (Mark)

Needs content Mark supplies: a mask PNG under
`mods/LC Intrepid Pack/data/Models/Ships/LCintrepidModel/Masks/<registry>/` and
a registry (`default_registry` in that folder's `decals.json`, written by the
SPV's Save). Then: `--developer` → SPV → Decals → place a test decal on a
nacelle → Save → fly, go to warp, watch the nacelles swing; optionally shoot a
nacelle off. Ambassador names unchanged is the regression check.

## 9. Left to the builder

- Exact test geometry (which node to rotate, sample blocks).
- Where in the SPV code the rest-pose guarantee lives, and whether it needs
  code or only a pinning test.
- How to tell "this mesh lies under an articulated part" (node chain vs the
  SPV's part list), provided it uses the same part names the rig uses.
