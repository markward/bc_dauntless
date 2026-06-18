# Render Handedness Un-Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. NOTE: several tasks can ONLY be verified by a human looking at the running renderer — those are marked **[USER VISUAL GATE]** and must not be auto-checked.

**Goal:** Eliminate the left-handed reflection currently baked into ship rendering so every ship draws in its true geometry (hull registry text reads correctly, port/starboard are physically correct), and make combat/camera/radar geometry consistent with that single right-handed convention.

**Architecture:** Today the pipeline forces every ship's model matrix to negative determinant (a reflection): NPCs because `AlignToVectors` builds `right = up × forward` (det = −1), the player because `_world_matrix_from` negates the X column to force det < 0. A det < 0 model matrix mirrors the geometry — invisible on symmetric hulls but proven mirrored by the backwards `NCC-71879` registry text. We convert the whole pipeline to right-handed (det > 0, no reflection): `AlignToVectors` builds `right = forward × up`, the renderer stops negating X, `glFrontFace` flips `GL_CW → GL_CCW`, and the inside-of-sphere cull passes flip to match. Combat then uses the raw rotation as the true visual frame.

**Tech Stack:** Python engine (`engine/`), C++ OpenGL renderer (`native/src/renderer/`), pytest. Build: `cmake -B build -S . && cmake --build build -j`. Run: `./build/dauntless`.

## Global Constraints

- One build tree only: `build/dauntless` + `build/python/_open_stbc_host.cpython-*.so`. Never spawn binaries elsewhere; never run cmake from inside `native/`.
- Shader (`.vert`/`.frag`) changes need a `cmake -B build -S .` reconfigure before `cmake --build` — not relevant unless a task edits a shader, but noted.
- Edits to `native/src/host/host_bindings.cc` require a full `dauntless` rebuild. Renderer `.cc` edits: `cmake --build build -j`.
- Rotation matrices are column-vector: `R.GetCol(0)=right, GetCol(1)=forward, GetCol(2)=up`; body→world is `R · v_body` (`MultMatrixLeft`). After this change the convention becomes right-handed (det > 0) and `GetCol(0)` is finally the TRUE starboard.
- Game units throughout; convert only at display. Not central here.
- `sdk/` and `game/` are gitignored and live only in the main checkout — work on a feature branch in the main checkout, NOT a worktree.

---

## Branch & Baseline

This work supersedes the combat-only band-aid currently uncommitted on `fix/phaser-arc-yaw-handedness` (the `rotate_body_to_render_world` "match the render" helper). That helper becomes wrong once the reflection is gone, so it is reverted in Task 1. The genuinely-correct pitch fix (commit `69bf9c78`, on `main`) stays; the committed yaw fix (`3f2ff2bc`, the `world_up × world_dir` derivation) is re-derived in Task 7.

Create branch `fix/render-handedness-unmirror` off `main` (NOT off the band-aid branch, so the working tree starts clean of the Option-A helper).

---

## Task 1: Branch + park the combat band-aid

**Files:**
- Branch from `main`.
- Revert (in this branch's working tree) the uncommitted Option-A changes to: `engine/appc/weapon_subsystems.py`, `engine/appc/subsystems.py`, `tests/unit/test_phaser_arc_handedness.py`, `tests/unit/test_strip_emit_position_arc.py`.

**Interfaces:**
- Produces: a clean `main`-based branch with only the committed pitch fix (`69bf9c78`) and committed yaw fix (`3f2ff2bc`) present, no `rotate_body_to_render_world` helper.

- [ ] **Step 1: Stash/discard the uncommitted band-aid and branch from main**

```bash
git stash push -u -m "option-A combat band-aid (parked)"
git checkout -b fix/render-handedness-unmirror main
```

(The committed yaw fix `3f2ff2bc` lives on `fix/phaser-arc-yaw-handedness`, not `main`. Cherry-pick it so the baseline includes it, then we re-derive it in Task 7.)

```bash
git cherry-pick 3f2ff2bc
```

- [ ] **Step 2: Confirm baseline tests pass**

Run: `uv run pytest tests/unit/test_phaser_arc_handedness.py tests/unit/test_strip_emit_position_arc.py -q`
Expected: PASS (these are the committed-fix versions, pre-Option-A).

- [ ] **Step 3: Commit the cherry-pick as the branch base** (already committed by cherry-pick; no action). Verify:

Run: `git log --oneline -3`
Expected: shows `3f2ff2bc` content on top of `main`.

---

## Task 2: Flip `AlignToVectors` to right-handed (det > 0)

**Files:**
- Modify: `engine/appc/objects.py:126-155` (`AlignToVectors`)
- Test: `tests/unit/test_physics_object.py` (existing AlignToVectors coverage), new assertions in `tests/unit/test_align_to_vectors_handedness.py`

**Interfaces:**
- Produces: `AlignToVectors(forward, up)` yields a rotation with `det = +1` and `GetCol(0) == forward × up` (true starboard). `GetCol(1)` (forward) and `GetCol(2)` (up) are unchanged from before.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_align_to_vectors_handedness.py
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass


def _det(R):
    m = R._m
    return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
          - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
          + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))


def test_align_to_vectors_is_right_handed():
    o = ObjectClass()
    o.AlignToVectors(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    R = o.GetWorldRotation()
    assert abs(_det(R) - 1.0) < 1e-9            # right-handed now
    col0 = R.GetCol(0)
    assert (round(col0.x, 6), round(col0.y, 6), round(col0.z, 6)) == (1.0, 0.0, 0.0)  # +X starboard
    col1 = R.GetCol(1)
    assert (round(col1.x, 6), round(col1.y, 6), round(col1.z, 6)) == (0.0, 1.0, 0.0)  # +Y forward
    col2 = R.GetCol(2)
    assert (round(col2.x, 6), round(col2.y, 6), round(col2.z, 6)) == (0.0, 0.0, 1.0)  # +Z up
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_align_to_vectors_handedness.py -q`
Expected: FAIL — current det is −1 and col0 is (−1,0,0).

- [ ] **Step 3: Change the cross-product order**

In `engine/appc/objects.py`, in `AlignToVectors`, change:

```python
        right = u.Cross(fwd)
```
to:
```python
        right = fwd.Cross(u)   # right = forward × up — right-handed (det = +1)
```

Update the docstring: replace the "`right = up × forward` produces a left-handed basis (det = −1) ... renderer compensates with an X-axis flip" paragraph with: "`right = forward × up` is a right-handed basis (det = +1); the renderer draws this directly with no reflection (see host_loop._world_matrix_from, glFrontFace(GL_CCW))."

- [ ] **Step 4: Run the new test + existing AlignToVectors tests**

Run: `uv run pytest tests/unit/test_align_to_vectors_handedness.py tests/unit/test_physics_object.py tests/unit/test_appc_backdrops.py tests/unit/test_aggregate_backdrops.py tests/unit/test_placement.py -q`
Expected: the new test PASSES. The others may FAIL where they hard-coded the old det=−1 col0 — fix each by updating the expected col0/row to the right-handed value (forward × up). Show each change in the commit. (These tests assert AlignToVectors output rows/cols; e.g. `test_aggregate_backdrops.py:76` comment references the forward row which is unchanged — only col0/right-dependent assertions move.)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/objects.py tests/unit/test_align_to_vectors_handedness.py tests/unit/test_physics_object.py tests/unit/test_appc_backdrops.py tests/unit/test_aggregate_backdrops.py tests/unit/test_placement.py
git commit -m "fix(math): AlignToVectors builds right-handed (det=+1) basis"
```

---

## Task 3: Stop negating X in the world-matrix builder

**Files:**
- Modify: `engine/host_loop.py:1846-1861` (`_world_matrix_from`), and the docstrings of `_ship_world_matrix` (1864-1900) / `_astro_world_matrix` (1903-1917)
- Test: `tests/unit/` new `test_world_matrix_no_reflection.py`

**Interfaces:**
- Consumes: `_rot_determinant(rot)` (unchanged, host_loop:1838).
- Produces: `_world_matrix_from(loc, rot, s)` returns a row-major mat4 whose upper-left 3×3 is exactly `rot · diag(s)` with NO X negation. Determinant of the 3×3 has the same sign as `det(rot)` (now always +1 for properly-built ships).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_world_matrix_no_reflection.py
from engine.appc.math import TGPoint3, TGMatrix3
from engine.host_loop import _world_matrix_from


def test_world_matrix_does_not_negate_x_for_det_pos():
    R = TGMatrix3()  # identity, det +1
    loc = TGPoint3(0.0, 0.0, 0.0)
    m = _world_matrix_from(loc, R, 2.0)
    # Column 0 (m[0][0], m[1][0], m[2][0]) must be +2x, NOT negated.
    assert m[0] == 2.0   # m[0][0]
    assert m[4] == 0.0
    # Row-major flat list: index 0,1,2,3 = first row. m[0][0] is index 0.
    # First column entries are indices 0, 4, 8.
    assert m[0] == 2.0 and m[4] == 0.0 and m[8] == 0.0
```

NOTE: `_world_matrix_from` returns a flat 16-element row-major list (`[m00,m01,m02,tx, m10,...]`). Column 0 scale lives at index 0. Adjust the assertion indices to the actual return shape when writing.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_world_matrix_no_reflection.py -q`
Expected: FAIL — current code negates X for det>0 (index 0 would be −2.0).

- [ ] **Step 3: Remove the flip**

In `_world_matrix_from`, replace:

```python
    flip = -1.0 if _rot_determinant(rot) > 0.0 else 1.0
    sx = s * flip
    return [
        rot._m[0][0]*sx, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*sx, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*sx, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,             0.0,            0.0,            1.0,
    ]
```
with:
```python
    # Right-handed convention (det > 0): the rotation goes to the GPU
    # untouched. The previous determinant-normalization X-flip (which forced
    # det < 0 to satisfy glFrontFace(GL_CW)) reflected every ship — the cause
    # of the mirrored hull registry text. It is removed in concert with
    # AlignToVectors (now right-handed) and pipeline.cc (now glFrontFace CCW).
    return [
        rot._m[0][0]*s, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*s, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*s, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,            0.0,            0.0,            1.0,
    ]
```

Update the `_ship_world_matrix` docstring: delete the "Determinant normalization (workaround)" paragraph and replace with a one-line note that the renderer is now right-handed (no reflection; see this plan). `_rot_determinant` may become unused — if so, leave it (harmless, used by tests) or remove and update imports; prefer leaving it.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_world_matrix_no_reflection.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_world_matrix_no_reflection.py
git commit -m "fix(render): world matrix no longer negates X (drop reflection)"
```

---

## Task 4: Flip global front-face to GL_CCW

**Files:**
- Modify: `native/src/renderer/pipeline.cc:66-72`

**Interfaces:**
- Produces: front-facing triangles are now CCW in screen space. Ship hull (right-handed model matrix, CW-wound NIF) renders correctly and un-mirrored. Sphere passes are addressed in Task 5.

- [ ] **Step 1: Change the front-face**

In `pipeline.cc`, replace `glFrontFace(GL_CW);` and its comment with:

```cpp
    // Right-handed convention: ship model matrices are now det > 0 (no
    // reflection — see host_loop._world_matrix_from, AlignToVectors). The
    // CW-wound D3D NIFs therefore present CCW front faces in screen space, so
    // front-facing is GL_CCW. (Was GL_CW back when every model matrix was
    // reflected to det < 0.)
    glFrontFace(GL_CCW);
```

- [ ] **Step 2: Build**

Run: `cmake --build build -j`
Expected: builds clean.

- [ ] **Step 3: [USER VISUAL GATE] Verify ship hull**

Launch `./build/dauntless` into a mission with the player Galaxy (and the registry-text texture hack if available).
ACCEPTANCE: (a) the hull is solid, not inside-out / not see-through-to-backfaces; (b) the `NCC-71879` / `U.S.S. DAUNTLESS` registry text reads **forwards**, not mirrored; (c) NPC Galaxy ships are likewise solid and un-mirrored. Note any pass that now renders inside-out (expected: backdrop and/or sun may be wrong until Task 5).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/pipeline.cc
git commit -m "fix(render): glFrontFace GL_CCW for right-handed ship matrices"
```

---

## Task 5: Fix inside-of-sphere cull passes (backdrop, sun) and breach

**Files:**
- Modify: `native/src/renderer/backdrop_pass.cc:87,118`
- Modify: `native/src/renderer/sun_pass.cc:105,109,275,284`
- Modify: `native/src/renderer/sphere_mesh.cc:46-60` (comment only — winding interpretation)
- Modify: `native/src/renderer/breach_pass.cc:227,238,274,313` (cull FRONT/BACK pairs)

**Interfaces:**
- Produces: backdrop sphere, sun sphere/corona, and hull-breach carving render correctly under `glFrontFace(GL_CCW)`.

Rationale: these passes draw a sphere from the inside and cull front faces (`glCullFace(GL_FRONT)`) to show the inside, relying on the *global* front-face. Flipping the global front-face to CCW inverts which face is "front" for the unchanged CW-from-outside sphere winding, so each `GL_FRONT` likely becomes `GL_BACK` (and vice-versa). Breach uses front/back cull to carve cavities and is winding-sensitive for the same reason.

- [ ] **Step 1: [USER VISUAL GATE] Determine which passes broke after Task 4**

From the Task 4 visual check, list which of {backdrop starfield sphere, sun body, sun corona, hull breach holes} render wrong (missing, inside-out, or inverted).

- [ ] **Step 2: Flip the cull face on each broken sphere pass**

For each broken pass, swap its inside-render cull: `glCullFace(GL_FRONT)` ↔ `glCullFace(GL_BACK)`. Specifically:
- `backdrop_pass.cc:87`: `GL_FRONT` → `GL_BACK` (and the restore at 118 `GL_BACK` is the global default; leave or set explicitly to match pipeline default).
- `sun_pass.cc:105,275`: `GL_FRONT` → `GL_BACK`; the restores at 109,284 (`GL_BACK`) match the global default — leave.
- Update each pass's comment to reference `glFrontFace(GL_CCW)` instead of `GL_CW`.
- `sphere_mesh.cc:46-60`: update the comment block ("Combined with glFrontFace(GL_CCW) + glCullFace(GL_BACK), the inside of the sphere is drawn"). No index change.

- [ ] **Step 3: Evaluate breach pass**

`breach_pass.cc` toggles `GL_FRONT`/`GL_BACK` to carve and back-fill cavities. If breach holes render wrong after Task 4, swap each `GL_FRONT`↔`GL_BACK` in the 227/238 and 274/313 pairs and update comments. If breach was fine (it may be, depending on its own mesh winding), leave it and note that in the commit.

- [ ] **Step 4: Build**

Run: `cmake --build build -j`
Expected: builds clean.

- [ ] **Step 5: [USER VISUAL GATE] Verify spheres + breach**

ACCEPTANCE: backdrop starfield visible and surrounding the scene; sun body + corona render as a solid glowing sphere (not inside-out, not missing); firing on a hull until it breaches shows correct see-through holes (no inverted carving). Iterate Step 2/3 until all correct.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/backdrop_pass.cc native/src/renderer/sun_pass.cc native/src/renderer/sphere_mesh.cc native/src/renderer/breach_pass.cc
git commit -m "fix(render): flip inside-sphere + breach cull for GL_CCW"
```

---

## Task 6: Audit cull-disabled passes (shield, hologram, bridge) — comments + lighting

**Files:**
- Modify: `native/src/renderer/shield_pass.cc:125-133` (comment), `native/src/renderer/hologram_pass.cc:48-60` (comment), `native/src/renderer/bridge_pass.cc:215-235` (comment + verify)

**Interfaces:**
- Produces: stale "negate X / left-handed" comments corrected; confirmation these passes still render correctly (they disable culling, so winding-insensitive, but lighting/normals may shift).

- [ ] **Step 1: Update stale comments**

- `shield_pass.cc:130-133`: the "Ship world matrices negate the X column to satisfy glFrontFace(GL_CW)" comment is now false. Replace with: "Ship matrices are right-handed (no reflection); culling is disabled for the additive bubble regardless." Behavior unchanged (cull already disabled).
- `hologram_pass.cc:53`: "The X-axis flip / world handedness is already baked into inst->world" → "inst->world is the right-handed ship transform; reused verbatim so the hologram overlays the opaque hull." Behavior unchanged.
- `bridge_pass.cc:217-222`: the double-reflection reasoning changes — the instance world is no longer det<0. Re-derive: officer instance world is now det>0; the skin bind basis det sign is unchanged, so the composed winding flips relative to before. Culling is already DISABLED, so officers still render double-sided; update the comment to state the new det composition and that culling stays disabled.

- [ ] **Step 2: Build**

Run: `cmake --build build -j`
Expected: builds clean.

- [ ] **Step 3: [USER VISUAL GATE] Verify shields, hologram (Ship Property Viewer), bridge officers**

ACCEPTANCE: raising shields shows the additive bubble; SPV hologram overlays the hull; bridge officers render solid (not shredded/inside-out) and lit reasonably. If officer lighting is visibly wrong (normals flipped), note it as a follow-up — cosmetic, not blocking.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shield_pass.cc native/src/renderer/hologram_pass.cc native/src/renderer/bridge_pass.cc
git commit -m "docs(render): correct stale left-handed comments after un-mirror"
```

---

## Task 7: Re-derive combat arc geometry for the right-handed convention

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`_emitter_in_arc` — the committed yaw fix's `world_up × world_dir` becomes `world_forward × world_up`)
- Modify: `engine/appc/subsystems.py` (`_strip_emit_position` — `world_up × world_forward` becomes `world_forward × world_up`)
- Test: `tests/unit/test_phaser_arc_handedness.py`, `tests/unit/test_strip_emit_position_arc.py`

**Interfaces:**
- Consumes: `ship.GetWorldRotation()` is now the TRUE visual orientation (det > 0, no reflection).
- Produces: `_emitter_in_arc(emitter, ship, aim_world)` gates banks against the visible hull. `world_right = world_forward × world_up` (standard right-handed). No determinant flip / no `rotate_body_to_render_world` helper anywhere.

Rationale: with the reflection gone, raw `R` is the visible frame. Visual starboard `= R·(forward × up) = world_forward × world_up`. The committed yaw fix used `world_up × world_dir` (correct only under the OLD det<0 reflected frame); under the new convention the cross order swaps.

- [ ] **Step 1: Write the failing test (asymmetric + side banks, det > 0)**

Replace the body of `tests/unit/test_phaser_arc_handedness.py` rotations to use right-handed (det>0) ships built via `AlignToVectors`, and assert: a physically-starboard (`+X`) target engages the starboard-favouring forward bank (VentralPhaser3, yaw −20..+80) and the `+X`-firing side bank (VentralPhaser4), and NOT their port mirrors (VP2/VP1). Use the actual galaxy arc values. Concretely (add as a new test):

```python
def test_starboard_target_engages_starboard_banks_right_handed():
    from engine.appc.math import TGPoint3
    from engine.appc.objects import ObjectClass
    # Right-handed identity ship: forward +Y, up +Z, right +X (true starboard).
    ship = _Ship(ObjectClass().GetWorldRotation())  # identity, det +1
    vp3 = _asym_bank("VP3", -0.349066, 1.396263, ship)   # starboard-favouring fwd
    vp2 = _asym_bank("VP2", -1.396263, 0.349066, ship)   # port-favouring fwd
    vp4 = _side_bank("VP4", (1.0, 0.0, 0.0), ship)       # +X = starboard
    vp1 = _side_bank("VP1", (-1.0, 0.0, 0.0), ship)      # -X = port
    tgt = _Target(900.0, 600.0, -120.0)                  # +X (starboard) + fwd, low
    assert _emitter_in_arc(vp3, ship, _resolve_bank_aim_world(vp3, tgt)) is True
    assert _emitter_in_arc(vp4, ship, _resolve_bank_aim_world(vp4, tgt)) is True
    assert _emitter_in_arc(vp2, ship, _resolve_bank_aim_world(vp2, tgt)) is False
    assert _emitter_in_arc(vp1, ship, _resolve_bank_aim_world(vp1, tgt)) is False
```

(Keep `_asym_bank`/`_side_bank` helpers from the parked Option-A test; re-add them. Delete the Option-A `_render_world`/`rotate_body_to_render_world`-based assertions.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_phaser_arc_handedness.py::test_starboard_target_engages_starboard_banks_right_handed -q`
Expected: FAIL — the committed `world_up × world_dir` derivation mis-signs yaw under the new convention.

- [ ] **Step 3: Swap the cross order in the gate**

In `engine/appc/weapon_subsystems.py` `_emitter_in_arc`: ensure `world_dir = R · local_dir` (plain rotate, NO `rotate_body_to_render_world` — that helper should not exist on this branch after Task 1), `world_up = R · up_local`, and:

```python
    # Right-handed convention (post un-mirror): raw R is the true visual frame.
    # world_right = world_forward × world_up = R·(forward×up) = R·GetCol(0)
    # = true starboard. (Was world_up × world_dir under the old reflected det<0
    # frame.) Matches _strip_emit_position so gate and beam agree.
    world_right = TGPoint3(
        world_dir.y * world_up.z - world_dir.z * world_up.y,
        world_dir.z * world_up.x - world_dir.x * world_up.z,
        world_dir.x * world_up.y - world_dir.y * world_up.x,
    )
```

- [ ] **Step 4: Swap the cross order in the strip emit**

In `engine/appc/subsystems.py` `_strip_emit_position`, change `world_right` from `world_up × world_forward` to `world_forward × world_up`:

```python
        world_right = TGPoint3(
            world_forward.y * world_up.z - world_forward.z * world_up.y,
            world_forward.z * world_up.x - world_forward.x * world_up.z,
            world_forward.x * world_up.y - world_forward.y * world_up.x,
        )
```

Both `world_forward` and `world_up` here are `R · body` (plain rotate; remove any `rotate_body_to_render_world` use).

- [ ] **Step 5: Update test_strip_emit_position_arc.py expectations**

These use an identity (now det+1, un-reflected) ship with DorsalPhaser1 (forward −X). With no reflection, a body −X bank fires toward world −X. Restore the ORIGINAL pre-Option-A expectations (emit toward (−1,0,0) for a −X target; clamp yaw with `Right = forward × up`). Verify the clamp test's expected `(expected_x, expected_y)`: for forward=(−1,0,0), up=(0,0,1), `right = forward × up = (0,1,0)`... compute and set the expected emit direction for a +Y target accordingly. Run the test and adjust the expected constants to match the right-handed geometry.

- [ ] **Step 6: Run combat tests**

Run: `uv run pytest tests/ -q -k "phaser or arc or weapon or combat or fire or emit or strip or weapons_display or solution"`
Expected: PASS.

- [ ] **Step 7: [USER VISUAL GATE] Verify firing in-game**

Target an NPC fore-starboard and fire. ACCEPTANCE: only banks on the target's side light in the weapons panel; beams emerge from the hull toward the target with NO through-hull raking. Repeat with the target fore-port, above, and below.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/weapon_subsystems.py engine/appc/subsystems.py tests/unit/test_phaser_arc_handedness.py tests/unit/test_strip_emit_position_arc.py
git commit -m "fix(combat): re-derive arc gate + beam emit for right-handed frame"
```

---

## Task 8: Audit camera / control / radar right-axis readers

**Files:**
- Modify (as needed): `engine/host_loop.py:705` (`rgt = R.GetCol(0)`), `engine/host_loop.py:911-925` (`_apply_body_rotation` pitch/yaw/roll), `engine/ui/radar_projection.py:54` (`right = player_rot.GetCol(0)`)
- Test: `tests/unit/test_radar_projection*.py` (existing), plus a control-direction reasoning check.

**Interfaces:**
- Produces: HUD/camera/radar right-axis and player pitch/roll directions consistent with the un-reflected hull.

Rationale: `GetCol(0)` previously returned `up × forward` (= −X, secretly port) but the rendering reflection made it *appear* on starboard. After the fix, `GetCol(0)` is `forward × up` (= +X, true starboard). Code that read `GetCol(0)` and then displayed/used it relative to the VISIBLE ship may have been implicitly relying on the reflection.

- [ ] **Step 1: Inspect `host_loop.py:700-710`**

Read the function around `rgt = R.GetCol(0)` (the pitch/heading HUD calc near line 705). Determine whether its consumer compares `rgt` against world positions (physics — now correct automatically) or against screen/visual space (may need sign review). Add/adjust a unit test if it has one; otherwise reason in the commit message.

- [ ] **Step 2: Radar projection**

`radar_projection.py:54` reads `right = player_rot.GetCol(0)` and projects contacts onto the player's right/forward plane. Run existing radar tests:

Run: `uv run pytest tests/ -q -k radar`
Expected: PASS. If a test encoded the old (reflected) right sign, it will fail — update it to the right-handed expectation (contact to physical starboard appears on the right of the radar). 

- [ ] **Step 3: [USER VISUAL GATE] Control + radar feel**

In-game: ACCEPTANCE — (a) pitch up tilts the nose up on screen, yaw left turns left, roll left rolls left (NOT inverted); (b) a contact off the starboard bow appears on the right side of the radar; (c) the target reticle points to the correct side. If pitch or roll is inverted, flip the corresponding fixed-axis sign in `_apply_body_rotation` (e.g. negate `pitch_rate` or `roll_rate` axis) — these were tuned against the reflected view and may invert. Make the minimal sign change and re-verify.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py engine/ui/radar_projection.py tests/
git commit -m "fix(hud): right-axis readers + control directions for un-mirror"
```

---

## Task 9: Full suite + documentation

**Files:**
- Modify: `CLAUDE.md` (the "Rotation matrix convention" section), the memory note `project_lefthanded_rotation_cross_product.md` (now obsolete — update or delete)

**Interfaces:**
- Produces: docs describe the right-handed (det > 0, no reflection) convention.

- [ ] **Step 1: Run the full test suite**

Run: `scripts/run_tests.sh` (watchdog-capped) or `uv run pytest -q`
Expected: PASS. Fix any remaining handedness-dependent test fallout.

- [ ] **Step 2: Rewrite the CLAUDE.md rotation section**

Replace the "Rotation matrix convention — column-vector, always" guidance about `AlignToVectors` producing det=−1 and the renderer X-flip. New content: column-vector, right-handed (`right = forward × up`, det = +1); `GetCol(0)` is true starboard; the renderer draws `R` directly under `glFrontFace(GL_CCW)` with NO reflection; remove the "X-axis flip stays" hard rule. Note that cross products of rotated vectors no longer flip sign (det = +1), so the left-handed gotchas are retired.

- [ ] **Step 3: Update/retire the left-handed memory note**

`~/.claude/.../memory/project_lefthanded_rotation_cross_product.md` is now wrong. Update it to record that the convention was converted to right-handed on 2026-06-18 (this plan), or delete it and drop the MEMORY.md pointer.

- [ ] **Step 4: [USER VISUAL GATE] Final regression sweep**

ACCEPTANCE: registry text correct; ships solid & un-mirrored; sun/backdrop/shields/breach/bridge correct; firing hits the right banks with no through-hull; controls + radar correct.

- [ ] **Step 5: Commit + finish branch**

```bash
git add CLAUDE.md
git commit -m "docs: rotation convention is now right-handed (det>0, no reflection)"
```

Then use superpowers:finishing-a-development-branch to decide merge/PR.

---

## Self-Review Notes

- **Spec coverage:** mirror cause (Task 2+3+4), every winding-sensitive pass (Task 5), cull-disabled passes (Task 6), combat (Task 7), camera/control/radar (Task 8), docs (Task 9). Covered.
- **Risk hotspots:** Task 5 (which cull flips — empirical, USER-gated), Task 8 control inversion (USER-gated, minimal sign flips). Both are explicitly iterative with visual acceptance.
- **Reversibility:** each task is its own commit; the renderer change is a contiguous set (Tasks 3-6) — if a visual stage can't be made correct, the branch can be parked without touching `main`.
- **Open question:** whether any OTHER ship-placement path still yields det<0 after Task 2 (e.g. waypoints whose matrices were stored pre-change). If a mission stores a raw matrix, it keeps its old det. Task 9 Step 4 sweep should catch a stray mirrored ship; if found, trace its placement and route it through the new AlignToVectors.
