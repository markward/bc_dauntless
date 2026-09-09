# Raymarched Breach Interior Implementation Plan (Plan 2b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the breach interior come from the damage field instead of from the 24-slot sphere list, so damage past the ceiling stops showing through to space.

**Architecture:** The scoop stops being one deformed sphere mesh per carve. Instead each damaged instance draws a single proxy, stencil-limited to where the hull was actually cut, and the fragment shader marches the damage field along the view ray to find the cavity wall. The field is already on the GPU as a 2D slice atlas, so no new transport.

**Tech Stack:** GLSL 410, C++20 (`native/src/renderer`), GoogleTest.

**Spec:** `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md` (§7)

## Why this slice

Plan 2a made the hull clip against the field, so damage now survives past 24 carves. The *interior* did not move — `breach_pass` still iterates `inst.carve.slots()` and `breach.vert` still deforms a unit sphere per carve. So a carve beyond the ring cuts hull with nothing drawn behind it: **see-through to space**, live-observed and currently the branch's most visible defect.

This plan moves only the interior. Deliberately **NOT** in scope:

- **Baking the rim noise into the brush.** `breach.vert` and `opaque.frag` both carry a `KEEP IN SYNC` comment and duplicate the same oblate-plus-noise maths; carving the jaggedness into the field would make hull and interior agree by construction and delete that whole drift class. It is the right next step — plan 2c — but doing it here would change the interior *and* the rim shape at once, and a bad live result would not say which.
- **Deleting the sphere list.** Three things still read it: the framework lattice (needs per-carve normal, radius and rim fraction), the noise rim, and the breach-event ring.
- **Deleting `carve_has_backing` / `carve_cavity_depth_cells`.** Their purpose shifts once the interior comes from the field, but removing them is a behaviour change needing its own live pass.

## Global Constraints

1. **Never add a `sampler3D` to `opaque.frag`** — measured to corrupt shading across `TangentBasisTest`, `ConeLightFrameTest`, `ExplosionLightFrameTest` and `CloakAmbientParityTest` even on an unreachable branch. `breach.frag` already has one and is fine; the hazard is specific to `opaque.frag`.
2. **After ANY shader change, run the FULL `renderer_tests` binary, never a filter.** The corruption appears in suites you would not think to filter for.
3. **Shaders are embedded at CONFIGURE time.** Always `cmake -B build -S .` before `cmake --build build -j` when a `.frag`/`.vert` changed, or you will test a stale shader and believe it worked.
4. **The atlas carries DAMAGE, not hull geometry.** Every cell starts at `-127` ("no damage"); only the brushes raise a cell. Untouched hull must never be discarded or shaded as interior.
5. **The encoding is `d + 128`**, so **`128/255` is the boundary, not `0.5`**. Comments asserting `0.5` have been wrong here twice.
6. **MAIN CHECKOUT, shared with concurrent sessions.** Explicit pathspecs only. `.claude/`, `mods/` and a modified `.gitignore` belong to another session. Never `git add -A`, `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`.
7. Never spell `game` or `sdk` as a path segment. 1 model unit = 0.01 GU.
8. Gate: `./scripts/check_tests.sh` exit 0 — **read its OUTPUT, not a pipeline's exit code**; it prints a `NEW FAILURES (not in baseline)` banner on failure. Only `test_shield_level_change_announces` is baselined.
9. Commit messages end with:
   `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## What already exists and must be reused, not rebuilt

- **The stencil.** `FrameSubmitter::submit_carve_stencil` stamps stencil = 1 where the hull was actually cut, and that marking pass **already includes the field's cut** (`opaque.frag`'s `u_carve_invert` path sets `marked` from the field block). `breach_pass.cc:172` already tests `GL_EQUAL, 1`. This is exactly the mask the new proxy needs — do not invent another.
- **The atlas and its uniforms.** `InstanceFieldCache::Entry` carries `tex2d`, `layout`, `origin`, `cell`, `dims`, `scale`. `frame.cc:542-567` already binds them for the opaque pass; the same values feed the breach pass.
- **`sample_hull_field` / `hull_field_slice`** in `opaque.frag` — the tile-atlas sampling, already verified correct against `field_atlas.cc`'s layout by hand.

## File Structure

| File | Change |
|---|---|
| `native/src/renderer/shaders/breach.frag` | field sampling (copy of `opaque.frag`'s), then the raymarch |
| `native/src/renderer/shaders/breach.vert` | proxy becomes a per-instance box, not a per-carve deformed sphere |
| `native/src/renderer/breach_pass.cc` | one draw per damaged instance instead of one per carve |
| `native/src/renderer/include/renderer/breach_pass.h` | pass the field entry through |
| `native/src/renderer/frame.cc` | hand the breach pass the instance's field entry |
| `native/tests/renderer/breach_field_sampling_test.cc` | **new** — the drift guard |
| `native/tests/renderer/breach_raymarch_test.cc` | **new** — cavity-surface correctness |
| `native/tests/renderer/breach_pass_test.cc` | updated for the per-instance draw |

---

## Task 1: Field sampling in `breach.frag`, with a drift guard

**Interfaces produced:** `float sample_hull_field(vec3 p_body)` and `float hull_field_slice(...)` in `breach.frag`, byte-identical to `opaque.frag`'s, plus the same `u_hull_field*` uniform block.

The two shaders will hold identical copies of this sampling code. `embed_shader` reads one file at a time, so sharing it needs a build change whose own `CONFIGURE_DEPENDS` would have to be right or it hits the documented stale-shader trap. Not worth that risk inside this plan.

**Instead, guard the duplication mechanically.** Write a test that extracts the sampling block from both shader sources and asserts they are **byte-identical**. Delimit the block with explicit marker comments in both files so the extraction is unambiguous. That test is the whole point of this task — a copy that can silently drift is exactly the failure this plan exists to reduce, and this project has already paid for two `KEEP IN SYNC` comments that were not enforced.

**Steps:** write the guard test first against a `breach.frag` that has no such block (RED: extraction finds nothing) → add the markers to `opaque.frag` → copy the block and the uniform block into `breach.frag` → GREEN. Then reconfigure, build, and run the FULL renderer binary.

Commit: `feat(renderer): field sampling in breach.frag, guarded against drift`.

---

## Task 2: Raymarch the cavity surface

**Interfaces produced:** in `breach.frag`, a function returning the body-frame point and normal of the cavity wall along a view ray, or a miss.

**The march.** A fragment reaching this pass is, by the stencil, one where the hull was cut. Start at the fragment's body-frame position, step along the view ray *into* the hull, and find where the damage field falls back below the iso margin — that is the far wall of the cavity. Shade that point as the interior.

**Details that must be right:**

- **Step size** relative to `u_hull_field_cell`. Too coarse and thin cavity walls are missed (the ray tunnels through and the interior vanishes); too fine and the cost is wasted. Derive it from the cell size and state the derivation in a comment.
- **A bounded number of steps**, with an explicit miss result. An unbounded loop in a fragment shader is a hang, not a slow frame.
- **The normal** comes from the field's gradient (central differences on the atlas). That is what lets the interior light correctly instead of reading flat.
- **A miss must not paint anything.** If the march finds no wall — a carve that cuts clean through a thin plate — the correct result is to draw nothing and let the background show, which is the project's existing "a hole is a hole" precedent.

**Tests** (`breach_raymarch_test.cc`), each asserting a stated behaviour, and each verified to fail if that behaviour breaks:

- A ray entering a known carved cavity finds its wall within one cell of the analytic answer.
- A ray through undamaged field (all `-127`) finds nothing and paints nothing.
- A ray through a cavity that cuts clean through paints nothing rather than a wall at the far side of the ship.
- The gradient normal points out of the cavity wall, not into it — check the sign explicitly; an inverted normal lights the interior inside-out and is easy to miss headlessly.
- Step count is bounded: a pathological ray terminates.

**Do the arithmetic for each test's sample point before writing it.** Nine tests on this branch have shipped passing without exercising what they named; the recurring cause is a sample point that does not reach the code under test.

Commit: `feat(renderer): raymarch the damage field for the breach interior`.

---

## Task 3: One proxy draw per damaged instance

**Currently:** `breach_pass.cc:322-360` iterates `inst.carve.slots()` and issues a draw per carve, with `breach.vert` deforming a unit sphere by `u_carve_center` / `u_carve_radius` / `u_carve_normal`.

**Becomes:** one draw per damaged instance. The proxy is a box covering the field's extent — `Entry::origin` and `Entry::dims * Entry::cell` give it directly — transformed by the instance's world matrix. `breach.vert` no longer deforms anything; it just puts the box in clip space and hands the fragment shader what it needs to start a ray.

The existing stencil test (`GL_EQUAL, 1`) stays and is what limits the proxy to where hull was actually cut. **Do not remove or weaken it** — without it the proxy paints over the whole ship.

**Tests:**
- A damaged instance issues exactly one breach draw, not one per carve.
- An undamaged instance issues none.
- **An instance with more than 24 carves still draws its interior** — this is the artifact the plan exists to remove, so the test must observe the interior being drawn for a carve beyond the ring, not merely that a draw happened.
- The stencil state is restored exactly as `breach_pass.cc:157-181` documents; that comment names a real trap where `glStencilMask` left closed silently breaks the next clear.

Commit: `feat(renderer): one breach proxy per instance, not one per carve`.

---

## Task 4: Retire the dead per-carve path

Remove `breach.vert`'s sphere deformation and the `u_carve_center` / `u_carve_radius` / `u_carve_normal` uniforms now that nothing sets them, along with any now-unreachable code in `breach_pass.cc`.

**Do NOT remove** the `KEEP IN SYNC` oblate maths from `opaque.frag` — the hull clip still uses it, and the sphere list stays until plan 2c.

Then the full gate, and the whole `renderer_tests` binary.

Commit: `refactor(renderer): retire the per-carve scoop path`.

---

## Done criteria

- `./scripts/check_tests.sh` exits 0, banner absent.
- Full `renderer_tests` green, including the four driver-hazard suites.
- A hull with more than 24 carves has interior behind every one of them.
- An undamaged ship renders byte-identically to before.

## Deferred to an end-of-implementation cleanup pass

Recorded at Mark's request rather than left in conversation.

**Share the field-sampling GLSL between `opaque.frag` and `breach.frag` for real,
instead of duplicating it behind a drift guard.** Task 1 duplicates the block and
enforces byte-identity with a test, because `embed_shader` reads one file at a time and
a shared prelude needs its own `CMAKE_CONFIGURE_DEPENDS` — without that, editing the
prelude silently ships the old shader, which is the exact trap
`native/src/renderer/CMakeLists.txt:5-11` already documents and which cost a round
during plan 2a.

The guard test makes the duplication safe, not good. The cleanup pass should extract the
block to a shared `.glsl` snippet, have `embed_shader` concatenate it, and add the
snippet to `CONFIGURE_DEPENDS` so a prelude edit regenerates both headers. Verify by
editing the snippet and confirming BOTH embedded headers change — a build that stays
green after a prelude edit is the failure, not the success.

Do this when the shader work has settled, not while it is still moving: the guard test
is doing its job in the meantime, and a build-system change is the wrong thing to be
debugging in the middle of a live-test cycle.

## What a live test should judge

1. **Is the see-through gone?** Take a ship past ~24 hits and look for holes showing space. That is the whole point of this plan.
2. **Does the interior look lit, or flat?** The gradient normal is what makes a cavity read as depth rather than as a painted patch. Flat shading means the normal is wrong or the gradient step is mis-scaled.
3. **Does the interior track merged carves?** Overlapping hits should give one continuous cavity, not two overlapping bowls.
4. **Frame time during a death cascade**, worst on a Warbird or KessokHeavy. The march is per-fragment over the breach area; if it costs, that is where it shows.
5. **Anything that looks like tunnelling** — an interior that vanishes at a glancing angle — points at the step size being too coarse for a thin cavity wall.
