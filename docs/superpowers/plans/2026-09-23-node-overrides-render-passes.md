# Node Overrides in the Render Passes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every pass that DRAWS a hull honour `Instance::node_overrides`, so an articulated or severed part looks the same in the cloak, shadow, hologram and breach passes as it does in the opaque pass.

**Architecture:** `draw_model` already composes node worlds through `renderer::compose_node_worlds(model, world, overrides)`, which reduces to the plain static walk when the override map is empty. Four other paths hand-roll that same walk and never see overrides. Each one is replaced with a `compose_node_worlds` call. Two of them (`cloak_pass`, `hologram_pass`) already hold the `Instance*` and need no signature change; the other two need the map threaded to them.

**Tech Stack:** C++20, GLM, GoogleTest via ctest. Python only for the gate.

**Spec:** `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md` §4.3 (the render-pass rows) and OQ-12.

**This is plan 1 of 3** for §4.3. It covers only the paths that DRAW. Picking (`ray_trace`) and the sim-side geometry (collision pieces, hull volume, glow regions, carve entries) are separate plans, because they consume per-MODEL shared structures and transform the QUERY rather than threading overrides — a different technique with different risks.

## Global Constraints

- **`compose_node_worlds(model, world, overrides)` with an EMPTY map must stay byte-identical to the hand-rolled walk.** That equivalence is what makes every task here safe; it is already relied on by `draw_model`. Never "improve" the walk while moving it.
- **Rotation is column-vector, right-handed** (`CLAUDE.md`): `world_per_node[i] = world_per_node[parent] * node.local_transform`. Never transpose, never reorder that product.
- **Parents precede children** in `Model::nodes` — guaranteed by the asset pipeline. That is why one linear pass suffices; do not add a recursive walk.
- **A hidden (severed) part is the ZERO matrix**, not a flag. `set_instance_node_hidden` writes `glm::mat4(0.0f)` as the node's local, collapsing its subtree to a point. Any pass honouring overrides therefore hides severed parts for free — do not add a separate visibility test.
- **Never use `git add -A` or `git add .`** — this checkout is shared. Stage explicit paths.
- Build: `cmake --build build -j` from the worktree root. Never run `cmake` inside `native/`.
- Gate: `scripts/check_tests.sh`. Expected tail: `OK — no new failures. 1 known failure(s) still baselined.` The baselined entry is `tests/unit/test_engineer_emitters.py::test_shield_level_change_announces`.
- C++ tests live in `native/tests/renderer/` and are registered in that directory's `CMakeLists.txt`. `native/tests/renderer/node_anim_test.cc` is the existing example of testing override composition — read it before writing a new one.

---

### Task 1: Shadow depth pre-pass and `draw_model_positions_only`

The smallest change and the most visible: a severed or raised wing currently casts its REST-pose shadow.

**Files:**
- Modify: `native/src/renderer/include/renderer/model_draw_helpers.h`
- Modify: `native/src/renderer/model_draw_helpers.cc`
- Modify: `native/src/renderer/frame.cc` (the shadow pre-pass call, ~line 1159)
- Test: `native/tests/renderer/model_draw_helpers_test.cc` (create)

**Interfaces:**
- Consumes: `renderer::compose_node_worlds(const assets::Model&, const glm::mat4&, const std::unordered_map<int, glm::mat4>&) -> std::vector<glm::mat4>` (existing, `renderer/node_anim.h`).
- Produces: `draw_model_positions_only(model, world, prog, const std::unordered_map<int, glm::mat4>* node_overrides = nullptr)`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/model_draw_helpers_test.cc`. This tests the COMPOSITION, not the GL draw — there is no context in a unit test, so assert on what `compose_node_worlds` produces for the same inputs the helper would use:

```cpp
#include <gtest/gtest.h>

#include <renderer/node_anim.h>
#include <assets/model.h>

#include <glm/gtc/matrix_transform.hpp>

#include <unordered_map>

namespace {

// Root -> child. The child carries a translation so a moved child is
// distinguishable from an unmoved one by inspection.
assets::Model two_node_model() {
    assets::Model m;
    m.nodes.resize(2);
    m.root_node = 0;
    m.nodes[0].parent_index = -1;
    m.nodes[0].local_transform = glm::mat4(1.0f);
    m.nodes[1].parent_index = 0;
    m.nodes[1].local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(1.0f, 0.0f, 0.0f));
    return m;
}

}  // namespace

TEST(ModelDrawHelpers, AnEmptyOverrideMapReproducesTheStaticWalk) {
    const assets::Model m = two_node_model();
    const glm::mat4 world = glm::translate(glm::mat4(1.0f),
                                           glm::vec3(0.0f, 5.0f, 0.0f));
    const std::unordered_map<int, glm::mat4> none;

    const auto composed = renderer::compose_node_worlds(m, world, none);

    // The hand-rolled walk this replaces.
    std::vector<glm::mat4> expected(m.nodes.size(), glm::mat4(1.0f));
    expected[m.root_node] = world * m.nodes[m.root_node].local_transform;
    for (std::size_t i = 0; i < m.nodes.size(); ++i)
        if (m.nodes[i].parent_index >= 0)
            expected[i] = expected[m.nodes[i].parent_index] *
                          m.nodes[i].local_transform;

    ASSERT_EQ(composed.size(), expected.size());
    for (std::size_t i = 0; i < composed.size(); ++i)
        EXPECT_EQ(composed[i], expected[i]) << "node " << i;
}

TEST(ModelDrawHelpers, AnOverriddenChildMovesAndTheRootDoesNot) {
    const assets::Model m = two_node_model();
    const glm::mat4 world(1.0f);
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, 9.0f));

    const auto composed = renderer::compose_node_worlds(m, world, ov);

    EXPECT_EQ(composed[0], glm::mat4(1.0f));
    EXPECT_EQ(composed[1][3].z, 9.0f) << "the override must replace the local";
    EXPECT_EQ(composed[1][3].x, 0.0f) << "and REPLACE it, not compose with it";
}

TEST(ModelDrawHelpers, AZeroMatrixCollapsesTheSubtreeSoASeveredPartVanishes) {
    // set_instance_node_hidden writes mat4(0) as a node's local. That is how a
    // severed wing disappears -- every vertex in its subtree lands on the
    // origin, so its triangles have zero area. A pass honouring overrides
    // therefore needs NO separate visibility test.
    const assets::Model m = two_node_model();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::mat4(0.0f);

    const auto composed = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);

    EXPECT_EQ(composed[1], glm::mat4(0.0f));
}
```

Register it in `native/tests/renderer/CMakeLists.txt` alongside the existing entries — read the file and follow whatever pattern the neighbouring `*_test.cc` files use.

- [ ] **Step 2: Build and run it to verify it passes**

Run: `cmake --build build -j && ctest --test-dir build -R ModelDrawHelpers --output-on-failure`
Expected: **PASS**. These three characterise `compose_node_worlds`, which already exists — they are the safety net for Step 3, not a RED phase.

- [ ] **Step 3: Thread the parameter**

In `native/src/renderer/include/renderer/model_draw_helpers.h`, add `#include <unordered_map>` if absent, and change the declaration to:

```cpp
/// Draw every mesh in `model` with position attributes only, composing the node
/// hierarchy into `u_model` per mesh. Used by the shadow depth pre-pass and the
/// breach hull proxy.
///
/// `node_overrides` (nullptr or empty = none) replaces individual nodes' local
/// transforms, so an articulated or severed part casts the shadow it actually
/// has rather than its rest-pose one. Empty takes a walk byte-identical to the
/// static one.
void draw_model_positions_only(const assets::Model& model,
                               const glm::mat4& world,
                               Shader& prog,
                               const std::unordered_map<int, glm::mat4>*
                                   node_overrides = nullptr);
```

In `native/src/renderer/model_draw_helpers.cc`, add `#include <renderer/node_anim.h>` and replace the hand-rolled walk (the `world_per_node` construction and the `for` loop's parent-chain line) with:

```cpp
    static const std::unordered_map<int, glm::mat4> kEmpty;
    const std::vector<glm::mat4> world_per_node = renderer::compose_node_worlds(
        model, world, node_overrides ? *node_overrides : kEmpty);
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        for (int mesh_idx : node.meshes) {
```

Keep the rest of the loop body exactly as it is.

- [ ] **Step 4: Pass the overrides from the shadow pre-pass**

In `native/src/renderer/frame.cc` at the shadow pre-pass call (~line 1159), change:

```cpp
            draw_model_positions_only(*m, inst.world, prog);
```

to:

```cpp
            draw_model_positions_only(*m, inst.world, prog, &inst.node_overrides);
```

- [ ] **Step 5: Build and run the full C++ suite**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -20`
Expected: 0 failures.

- [ ] **Step 6: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

Stage exactly `native/src/renderer/include/renderer/model_draw_helpers.h`, `native/src/renderer/model_draw_helpers.cc`, `native/src/renderer/frame.cc`, `native/tests/renderer/model_draw_helpers_test.cc`, `native/tests/renderer/CMakeLists.txt`. Message:

```
feat(shadows): a moved or severed part casts the shadow it actually has

draw_model_positions_only hand-rolled the node walk and never saw
Instance::node_overrides, so a raised BoP wing cast its rest-pose shadow and
a severed one kept casting entirely. Routed through compose_node_worlds,
which reduces to the identical walk when the map is empty.

A hidden part is the ZERO matrix, so severed parts stop casting for free --
no separate visibility test.
```

---

### Task 2: Cloak pass

The highest-value one: the Bird of Prey is BC's only cloaking ship, so this is where the rest-pose snap is most visible. `cloak_pass` already holds the `Instance*`, so no signature changes.

**Files:**
- Modify: `native/src/renderer/cloak_pass.cc` (~lines 151-161)
- Test: `native/tests/renderer/model_draw_helpers_test.cc` (extend — the composition is the same helper)

**Interfaces:**
- Consumes: `renderer::compose_node_worlds` (as Task 1); `scenegraph::Instance::node_overrides`.
- Produces: nothing new.

- [ ] **Step 1: Replace the walk**

In `native/src/renderer/cloak_pass.cc`, add `#include <renderer/node_anim.h>` if absent. Replace the `world_per_node` construction and its parent-chain loop with:

```cpp
        // Honour the instance's node overrides, so a cloaking ship fades with
        // the wings it actually has. The BoP is BC's one cloaking ship, so
        // this is exactly the hull where a rest-pose snap shows.
        const std::vector<glm::mat4> world_per_node =
            renderer::compose_node_worlds(*model, world_xf,
                                          inst->node_overrides);
```

Leave the mesh loop that follows — including `shader.set_mat4("u_model", world_per_node[i])` — untouched.

- [ ] **Step 2: Build and run the C++ suite**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -20`
Expected: 0 failures. Cloak has existing coverage; if a cloak test fails, STOP and report — it means the walk was not equivalent.

- [ ] **Step 3: Commit**

Stage exactly `native/src/renderer/cloak_pass.cc`. Message:

```
feat(cloak): a cloaking ship fades with the wings it actually has

cloak_pass hand-rolled the node walk, so a BoP cloaking with its wings up
snapped them to the rest (down) pose for the whole fade, and a severed wing
grew back for it. The BoP is BC's one cloaking ship, so this hull is exactly
where it showed.
```

---

### Task 3: Hologram pass

Same shape as Task 2. Lower stakes (the Ship Property Viewer only), but it is the pass the SPV pins are drawn against, so a mismatch there makes the pin overlay disagree with the hologram.

**Files:**
- Modify: `native/src/renderer/hologram_pass.cc` (~lines 57-67)

**Interfaces:**
- Consumes: `renderer::compose_node_worlds`; `scenegraph::Instance::node_overrides`.
- Produces: nothing new.

- [ ] **Step 1: Replace the walk**

In `native/src/renderer/hologram_pass.cc`, add `#include <renderer/node_anim.h>` if absent, and replace the `world_per_node` construction and parent-chain loop with:

```cpp
    // Honour node overrides so the hologram matches the hull: the SPV draws
    // its subsystem pins against THIS pose, so a mismatch here puts every pin
    // on an articulated part in the wrong place.
    const std::vector<glm::mat4> world_per_node =
        renderer::compose_node_worlds(*model, world_xf, inst->node_overrides);
```

Leave the mesh loop untouched.

- [ ] **Step 2: Build and run the C++ suite**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -20`
Expected: 0 failures.

- [ ] **Step 3: Commit**

Stage exactly `native/src/renderer/hologram_pass.cc`. Message:

```
feat(hologram): the SPV hologram matches the hull's live pose

The SPV draws its subsystem pins against the hologram, and the pins already
follow articulated parts (subsystem_world_position does). Without this the
hologram itself stayed at rest pose, so every pin on a moved part sat off
the mesh it labels.
```

---

### Task 4: Breach pass

The longest thread: `draw_hull_proxy` takes a model and a world matrix, not an `Instance`, so the overrides pass down through `draw_instance` → `draw_hull_proxy` → `draw_model_positions_only`.

**Files:**
- Modify: `native/src/renderer/include/renderer/breach_pass.h`
- Modify: `native/src/renderer/breach_pass.cc` (`draw_instance`, `draw_hull_proxy`, `draw_interior_shell`)
- Modify: whatever calls `BreachPass::draw_instance` (find it: `grep -rn "draw_instance" native/src/renderer/frame.cc`)

**Interfaces:**
- Consumes: `draw_model_positions_only(..., node_overrides)` from Task 1.
- Produces: `BreachPass::draw_instance` and `draw_hull_proxy` each gain a trailing `const std::unordered_map<int, glm::mat4>* node_overrides = nullptr`.

- [ ] **Step 1: Find the call chain**

Run: `grep -rn "draw_instance\|draw_hull_proxy\|draw_interior_shell" native/src/renderer/breach_pass.cc native/src/renderer/frame.cc native/src/renderer/include/renderer/breach_pass.h`

Write down every signature and call site before editing. There are three functions in the chain and at least one external caller; changing one without the others will not compile, which is the point — let the compiler enumerate them.

- [ ] **Step 2: Thread a defaulted parameter through the chain**

Add `const std::unordered_map<int, glm::mat4>* node_overrides = nullptr` as the LAST parameter of `draw_instance`, `draw_hull_proxy` and `draw_interior_shell` (header and definition), pass it down at each internal call, and pass it into `draw_model_positions_only` at `breach_pass.cc:377`.

Document it once, on `draw_instance` in the header:

```cpp
    /// `node_overrides` (nullptr = none) is the instance's articulation /
    /// severance map, threaded down to draw_model_positions_only so the hull
    /// proxy is drawn at the pose the opaque pass drew. Without it a breach on
    /// a raised wing is rendered against where that wing sits at REST.
```

- [ ] **Step 3: Pass the real map at the external call site**

At the `BreachPass::draw_instance` call in `frame.cc`, pass the instance's overrides. If the instance is not in scope there, STOP and report — do not reach for a global.

- [ ] **Step 4: Build and run the C++ suite**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -20`
Expected: 0 failures. `breach_pass_test.cc` and `breach_raymarch_test.cc` are substantial; a failure there means the threading changed behaviour for an unarticulated hull, which it must not.

- [ ] **Step 5: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 6: Commit**

Stage the breach header, `breach_pass.cc`, and `frame.cc`. Message:

```
feat(breach): a hull breach is drawn against the wing's live pose

BreachPass::draw_hull_proxy takes a model and a matrix rather than an
Instance, so the overrides thread down through draw_instance ->
draw_hull_proxy -> draw_model_positions_only. Without it a breach on a
raised or severed wing was drawn against the rest pose.
```

---

## Spec coverage

| spec section | covered by |
|---|---|
| §4.3 "render passes" row — `cloak_pass` | Task 2 |
| §4.3 "render passes" row — `hologram_pass` | Task 3 |
| §4.3 "render passes" row — `model_draw_helpers` (shadow) | Task 1 |
| §4.3 "render passes" row — `model_draw_helpers` (breach) | Task 4 |
| §4.3 picking / collision / hull volume / glow / carve | **out of scope — plans 2 and 3** |
| OQ-12's four named paths | all four, one per task |

## Verification

Live, from this worktree, after Task 4:

```bash
./build/dauntless --developer
```

QuickBattle, player Bird of Prey:

1. **Cloak with the wings up.** `Shift+1` for green (wings rise), then cloak. The wings must STAY up through the fade. The bug looks like them snapping down the instant the cloak starts.
2. **Shoot a wing off, then cloak.** The missing wing must stay missing through the fade.
3. **Shadows.** With a sun behind you, a raised wing's shadow must move with it.

## Out of scope

- **Picking** (`ray_trace`) — plan 2. Until then a raised wing is drawn correctly but still traced against its rest pose, so it is not reliably hittable.
- **Sim geometry** (collision pieces, hull volume, glow regions, carve entries) — plan 3. That plan REVERSES Ruling 1 and must invert the two rest-mount characterisation tests; see spec §4.3.1.
