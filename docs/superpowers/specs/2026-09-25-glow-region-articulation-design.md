# Glow regions follow an articulated part

**Status:** DESIGNED 2026-09-25. Approach A approved in conversation. Not built.
**Builds on:** `docs/superpowers/specs/2026-09-23-spv-part-articulation-authoring-design.md`

---

## 1. The problem

A glow region (`SetGlowRegionShape` / `Position` / `Axis` / `Radius` /
`Extent` / `Scale` on a subsystem property) is a body-frame volume that
`opaque.frag`'s `glow_region_mult` uses to **modulate the hull's emissive
texture** by its subsystem's state: flicker while disabled, blow out then go
dark when destroyed, brighten with throttle for impulse. It is not a light in
space; it only changes the hull fragments inside it.

Regions are authored in the **NIF (rest) frame**, the same frame hardpoint
mounts use. The shader tests them against the wrong frame:

- Each mesh is drawn with its **posed** node matrix:
  `prog.set_mat4("u_model", ... world_per_node[i])` (`native/src/renderer/frame.cc:674`),
  where `world_per_node` comes from `compose_node_worlds(model, world, *node_overrides)`
  (`frame.cc:652`) for an articulated instance.
- The fragment shader rebuilds the body-frame position by dividing out only the
  hull's matrix: `p_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz`
  (`opaque.frag:1122`). That is the POSED body position.
- `glow_region_mult(p_body, n_body, ...)` (`opaque.frag:1342`) compares that
  posed position with a rest-frame region.

So on a part that has rotated, the region and the surface it was authored on
come apart. A destroyed subsystem's region stays at the rest position while the
raised wing it belongs to keeps glowing at full brightness, and whatever
surface happens to occupy the rest position gets dimmed instead.

No stock Bird of Prey wing carries a region today, so nothing visible is broken
on stock content. A modded ship with glow regions on any moving part (a
nacelle on a swing-pylon, a hinged wing with running lights) will show it.
Nothing in authoring prevents it: the SPV authors regions in the NIF pose.

`opaque.frag` is the only shader that reads `u_glow_region_*`.

## 2. Decision: correct the fragment, not the region

Approved: **approach A**.

For every mesh draw, the renderer already knows the node's posed matrix. It
also computes the node's **rest** matrix and passes the shader one per-draw
matrix that maps a posed body-frame point back to where it sits in the rest
pose. The glow test, and only the glow test, maps each fragment through it
before comparing with the regions.

Why A:

- **Exact per fragment.** Every fragment carries its own node's correction, so
  there is no step that assigns a region to a part.
- **Hinges come for free.** A region straddling a hinge splits correctly,
  because each side's surface maps back through its own node.
- **Any model.** Nothing is keyed to the Bird of Prey, to the four BoP part
  names, or to the SPV's part rules. A modded ship gets it with no data.
- **Byte-identical when nothing moves.** An instance without node overrides,
  a node without one, and a skinned draw all get the identity matrix.

Rejected:

- **B. Move the regions on the CPU.** It needs each region assigned to one
  part, which fails exactly where it matters: at hinges and where part boxes
  overlap (the BoP's warp mounts attribute to no part today). It also
  re-uploads regions every frame.
- **C. A rest-position vertex attribute.** Changes the mesh format and forces a
  re-upload of every model, to deliver what one uniform per draw already can.

## 3. The maths

Let `W` be the instance world, `P_i` node *i*'s posed model-space matrix and
`R_i` its rest one, both composed with an **identity** instance world. Then a
vertex `v` of node *i* is drawn at `W·P_i·v`, the shader recovers
`p_body = W⁻¹·W·P_i·v = P_i·v`, and its rest position is `R_i·v`. So

```
C_i = R_i · P_i⁻¹        p_rest = C_i · p_body
```

`W` cancels, so `C_i` does not depend on where the ship is and needs no
per-frame instance data beyond the node overrides.

Units: `p_body` is in MODEL units (the instance world carries
`BC_MODEL_SCALE`), and so are the region uniforms (`u_glow_region_a` is
"center.xyz, radius (model units)", `opaque.frag:306`). `P_i` and `R_i` are
model-space. Nothing converts.

Normals: `n_rest = normalize(mat3(C_i) · n_body)`. `C_i` is rigid, since
articulation only rotates, so `mat3` is its own inverse-transpose.

Severed parts: a hidden node carries the **zero** matrix
(`ray_trace.cc:462-465` treats it the same way), and its geometry collapses
to a point that draws no fragments. `P_i` is then not invertible; `C_i` is
the identity for any node with `|det P_i| < 1e-12`.

## 4. Components

### 4.1 `renderer::rest_corrections` (new, pure)

In `node_anim.{h,cc}`, beside `compose_node_worlds`:

```cpp
/// Per-node matrix mapping a POSED body-frame point back to its REST
/// position: C_i = R_i · P_i⁻¹, both composed with an identity instance
/// world. Identity for every node when `overrides` is empty, for a node
/// whose chain carries no override, and for a severed (zero-matrix) node.
std::vector<glm::mat4> rest_corrections(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides);
```

Pure: no GL, no instance state. It is the unit that gets the maths tests.

### 4.2 `draw_model` (`frame.cc:362`)

- When the instance has node overrides, compute `rest_corrections` once per
  call, alongside the existing `compose_node_worlds`.
- In the per-node mesh loop (`frame.cc:670-680`), set `u_node_rest_fix` for
  **every** mesh draw: `C_i` when articulated, the identity otherwise, and the
  identity on the skinned path. A uniform keeps its value between draws, so
  setting it only when non-identity would leak one ship's correction onto the
  next model drawn with the same program.

The positions-only path (`model_draw_helpers.cc`, shadow/depth) does not run
the glow test and is untouched.

### 4.3 `opaque.frag`

- New `uniform mat4 u_node_rest_fix;`
- At the glow call site (`opaque.frag:1342`), pass
  `(u_node_rest_fix * vec4(p_body, 1.0)).xyz` and
  `normalize(mat3(u_node_rest_fix) * n_body)` instead of `p_body` / `n_body`.
- **Only there.** Decals, scuffs and the hull carve keep reading the posed
  `p_body`. `4be56165` reverted the carve to posed sampling on purpose; this
  change must not undo that.

Shader edits need a CMake reconfigure to reach the build, and shader errors
surface at runtime, not at compile time (project memory). The render test in
§5 is what catches a broken shader.

## 5. Testing

1. **`rest_corrections` (gtest, pure).** On a **three-level** fixture
   (part → `__NDL_MultiMtl_Node` → mesh node, per the part-authoring spec's
   rule), rotate the part node through an override:
   - for a vertex of the mesh node, `C_i · (P_i · v) == R_i · v`;
   - a node outside the rotated subtree gets the identity;
   - an empty override map gives the identity everywhere;
   - a zero-matrix override gives the identity, not NaNs.
2. **Shader (`FrameTest`, headless).** A model with an articulated node and an
   active glow region authored on it at rest, in the DESTROYED state (dark):
   - rotated, the node's surface is still darkened: sampled pixels match the
     unrotated render of the same surface within tolerance;
   - without the fix (identity correction), the same pixels are NOT darkened,
     which is the check that the test can see the bug at all;
   - a model with no node overrides renders byte-identical to before.
3. **Gate.** `scripts/check_tests.sh`, with no new failures.

## 6. Live verification (Mark)

The gate cannot judge how it looks.

1. In the SPV, author a glow region on a Bird of Prey wing (on a subsystem
   mounted there, e.g. Port Cannon), save.
2. Damage that subsystem until disabled, so its region flickers.
3. Cycle alert states. The flicker must stay on the wing as it swings, and
   nothing must flicker at the wing's old position.
4. Revert the authored region afterwards (the file is authored data).

## 7. Out of scope, recorded

- **Debris chunks carry no glow regions.** `part_detach_render._copy_render_state`
  copies world, visibility and rim state but not regions, so a severed part's
  emissive draws unmodulated: a wing whose subsystems were destroyed by the
  severance still glows at full brightness as it tumbles away. Pre-existing
  and independent of this change: with A, copied regions would be correct on
  the chunk, since the chunk is drawn at rest pose.
- **Regions attributed by their parent subsystem's state.** A region's
  flicker or darkness follows its subsystem, wherever the region sits, the same
  shape as the cast-light gap fixed in `e410ca16`. With A the region still
  sits on the right surface; whether its state should come from its own part
  is a separate question.
