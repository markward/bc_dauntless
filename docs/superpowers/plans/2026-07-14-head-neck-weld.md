# Head/Neck Shared-Skeleton Weld Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rigid single-bone head graft with BC's bone-rebinding weld: grafted head vertices keep their authored multi-bone skin weights, remapped by bone NAME onto the body skeleton (spec: `docs/superpowers/specs/2026-07-14-head-neck-weld-design.md`).

**Architecture:** One new pure function `weld_head_bones` (maps head-skeleton bones onto the body skeleton by name, appending *alias bones* for bind-pose mismatches and *real bones* for head-only bones), wired into `graft_head_cpu`, which stops overwriting vertex weights and stops shifting vertex positions. Zero renderer/shader/palette changes — alias bones ride the existing `build_bone_palette` parent-chain walk.

**Tech Stack:** C++20 (`native/src/assets/`), GoogleTest (`native/tests/`), glm. Build: `cmake --build build -j`. Gate: `scripts/check_tests.sh`.

## Global Constraints

- **Branch:** all commits go on `feat/head-neck-weld` (already holds the spec, tip `3871ba7c`). **Precondition: only `git checkout feat/head-neck-weld` once Mark confirms the other active session has wrapped** — the checkout is shared. If the working tree contains an untracked `docs/superpowers/specs/2026-07-14-head-neck-weld-design.md` identical to the branch's copy, delete the untracked copy first (`diff` it against `git show feat/head-neck-weld:docs/...` to confirm byte-identity before deleting).
- **NEVER run destructive git** (shared checkout, concurrent sessions): banned outright — `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs only. Tell every subagent (reviewers included) the same. To probe-mutate a file, back up/restore by `cp`, never by git.
- **Never modify anything under `sdk/`.**
- Real-NIF tests must `GTEST_SKIP()` when `game/` assets are absent (follow the existing pattern in `model_compose_gpu_test.cc:30-32`).
- The test gate is `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs failures against `tests/known_failures.txt`). The only baselined failures are 7 headless-GL scorch/heat-glow `FrameTest`s. Never call any other failure "pre-existing".
- Character model units are **not** GU — bodies are ~78 units tall (human height). Do not name test variables `*_gu`.
- Update every test that asserts the old rigid-bind behaviour **in the same task** that changes the behaviour; never leave a task with a red suite.

## Reference: measured corpus facts the tests lean on

- `game/data/Models/Characters/Heads/HeadMiguel/miguel_head.NIF` shape `grmale med head 01:0`: skinned to 6 bones (`Bip01 Head`, `Bip01 Neck`, `Bip01 R Clavicle`, `Bip01 Ponytail1`, `Bip01 L Clavicle`, `Bip01 Spine2`), 143/143 verts weighted, 51 multi-bone.
- Bind poses: `BodyMaleS`+`miguel_head` bit-identical; `BodyMaleM`+`miguel_head` mismatched (per-bone pure-translation deltas up to ~5.9 units).
- Body skeletons have **no** `Bip01 Ponytail1` bone.
- `Model::head_mesh_begin` (default -1) is set by `compose_officer_model` to the first grafted mesh index; head set is `[head_mesh_begin, meshes.size())`.

---

### Task 1: `weld_head_bones` — the name-keyed bone map

**Files:**
- Modify: `native/src/assets/include/assets/model_compose.h` (declare after line 56)
- Modify: `native/src/assets/src/model_compose.cc` (implement; include `<functional>`, `<unordered_map>`, `<cmath>`)
- Create: `native/tests/assets/cpu/head_weld_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt` (add `cpu/head_weld_test.cc` to `add_executable(assets_tests ...)` after `cpu/model_compose_test.cc`)

**Interfaces:**
- Consumes: `assets::Skeleton` / `assets::Bone` (`native/src/assets/include/assets/skeleton.h` — fields `name`, `parent_index`, `local_transform`, `inverse_bind_pose`).
- Produces (Task 2 relies on these exact names):
  - `std::vector<int> assets::weld_head_bones(Skeleton& body, const Skeleton& head);` — returns head-bone-index → body-palette-index, mutating `body` by appending alias/head-only bones.
  - `inline constexpr std::string_view assets::kHeadBindAliasSuffix = "@head-bind";`

- [ ] **Step 1: Write the failing tests**

Create `native/tests/assets/cpu/head_weld_test.cc`:

```cpp
// §3.5 bone rebinding (the BC "weld"): weld_head_bones maps every head-skeleton
// bone onto the body skeleton by NAME. Equal binds map directly; a bind-pose
// mismatch appends an ALIAS bone (rides the body bone's pose, skins with the
// HEAD's inverse bind — BC composes body node worlds with the head controller's
// own bind offsets); a head-only bone (Bip01 Ponytail1) is appended for real.
#include <gtest/gtest.h>

#include <assets/model_compose.h>
#include <assets/skeleton.h>

#include <glm/gtc/matrix_transform.hpp>

#include <string>
#include <vector>

namespace {

// Two-bone skeleton: "Bip01" root (identity bind) + "Bip01 Head" child with a
// bind-world at Z = head_bind_z.
assets::Skeleton two_bone(float head_bind_z) {
    assets::Skeleton sk;
    assets::Bone root;
    root.name = "Bip01";
    root.parent_index = -1;
    assets::Bone head;
    head.name = "Bip01 Head";
    head.parent_index = 0;
    head.local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, head_bind_z));
    head.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -head_bind_z));
    sk.bones = {root, head};
    sk.root_bone_index = 0;
    return sk;
}

}  // namespace

TEST(WeldHeadBones, EqualBindsMapDirectlyNoAppends) {
    assets::Skeleton body = two_bone(10.0f);
    // Head lists its bones in a DIFFERENT order to prove the mapping is by
    // NAME, not by index.
    assets::Skeleton head;
    assets::Bone hhead;
    hhead.name = "Bip01 Head";
    hhead.parent_index = 1;
    hhead.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -10.0f));
    assets::Bone hroot;
    hroot.name = "Bip01";
    hroot.parent_index = -1;
    head.bones = {hhead, hroot};
    head.root_bone_index = 1;

    const std::size_t before = body.bones.size();
    const std::vector<int> map = assets::weld_head_bones(body, head);

    ASSERT_EQ(map.size(), 2u);
    EXPECT_EQ(map[0], 1);  // head's "Bip01 Head" -> body index 1
    EXPECT_EQ(map[1], 0);  // head's "Bip01"      -> body index 0
    EXPECT_EQ(body.bones.size(), before);  // nothing appended
}

TEST(WeldHeadBones, BindMismatchAppendsAliasWithHeadBind) {
    assets::Skeleton body = two_bone(10.0f);
    assets::Skeleton head = two_bone(4.0f);  // same names, different binds

    const std::vector<int> map = assets::weld_head_bones(body, head);

    EXPECT_EQ(map[0], 0);       // root binds equal (identity) -> direct
    ASSERT_EQ(map[1], 2);       // head bone -> appended alias
    ASSERT_EQ(body.bones.size(), 3u);
    const assets::Bone& alias = body.bones[2];
    EXPECT_EQ(alias.name,
              std::string("Bip01 Head") +
                  std::string(assets::kHeadBindAliasSuffix));
    EXPECT_EQ(alias.parent_index, 1);  // rides the body's real "Bip01 Head"
    EXPECT_EQ(alias.local_transform, glm::mat4(1.0f));
    EXPECT_EQ(alias.inverse_bind_pose,
              glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -4.0f)));
}

TEST(WeldHeadBones, AliasReusedNotDuplicated) {
    assets::Skeleton body = two_bone(10.0f);
    assets::Skeleton head = two_bone(4.0f);

    const std::vector<int> m1 = assets::weld_head_bones(body, head);
    const std::vector<int> m2 = assets::weld_head_bones(body, head);

    EXPECT_EQ(m1[1], m2[1]);
    EXPECT_EQ(body.bones.size(), 3u);  // still exactly one alias
}

TEST(WeldHeadBones, HeadOnlyBoneAppendedUnderMappedParent) {
    assets::Skeleton body = two_bone(10.0f);
    assets::Skeleton head = two_bone(10.0f);  // binds match
    assets::Bone pony;
    pony.name = "Bip01 Ponytail1";  // body skeletons lack this bone (corpus)
    pony.parent_index = 1;          // under the head's "Bip01 Head"
    pony.local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, -2.0f, 1.0f));
    pony.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 2.0f, -11.0f));
    head.bones.push_back(pony);

    const std::vector<int> map = assets::weld_head_bones(body, head);

    ASSERT_EQ(map.size(), 3u);
    ASSERT_EQ(map[2], 2);
    const assets::Bone& b = body.bones[2];
    EXPECT_EQ(b.name, "Bip01 Ponytail1");  // name KEPT: clips may drive it
    EXPECT_EQ(b.parent_index, 1);          // under the body's "Bip01 Head"
    EXPECT_EQ(b.local_transform, pony.local_transform);
    EXPECT_EQ(b.inverse_bind_pose, pony.inverse_bind_pose);
}
```

Add `cpu/head_weld_test.cc` to `native/tests/assets/CMakeLists.txt` (in the `add_executable(assets_tests` source list, after `cpu/model_compose_test.cc`).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cmake --build build -j --target assets_tests 2>&1 | tail -5
```
Expected: compile FAILURE — `weld_head_bones` is not declared.

- [ ] **Step 3: Declare + implement**

In `native/src/assets/include/assets/model_compose.h`, after the
`graft_head_cpu` declaration (line 56), add:

```cpp
/// Suffix for alias bones appended by weld_head_bones. The suffix guarantees
/// no clip track or rest_locals entry ever matches the alias by name, so its
/// posed local stays identity and build_bone_palette yields
/// posed_body_bone_world * head_inverse_bind — BC's exact §3.5 semantics.
inline constexpr std::string_view kHeadBindAliasSuffix = "@head-bind";

/// §3.5 bone rebinding (the BC "weld"). Maps every head-skeleton bone onto the
/// body skeleton by NAME, returning head-bone-index -> body-palette-index:
///   * name found, inverse binds equal (1e-4 component epsilon): the body
///     bone's own index — 18 of the 22 SDK body/head pairs are bit-identical;
///   * name found, binds differ (4 SDK pairs, per-bone translation deltas up
///     to ~5.9 units): appends an ALIAS bone (parent = the matched body bone,
///     local = identity, inverse_bind_pose = the HEAD's, name suffixed with
///     kHeadBindAliasSuffix) and maps to it. Reused if already appended.
///   * name missing from the body (e.g. "Bip01 Ponytail1"): appends a REAL
///     bone (name/local/inverse_bind from the head, parent = the mapped index
///     of its head-skeleton parent, resolved recursively).
/// Mutates `body` only by appending bones; existing indices stay valid.
std::vector<int> weld_head_bones(Skeleton& body, const Skeleton& head);
```

In `native/src/assets/src/model_compose.cc` (add `#include <functional>` and
`#include <unordered_map>` to the includes; implement above `graft_head_cpu`,
with `binds_equal` in the anonymous namespace):

```cpp
// (anonymous namespace)
bool binds_equal(const glm::mat4& a, const glm::mat4& b) {
    for (int c = 0; c < 4; ++c)
        for (int r = 0; r < 3; ++r)  // row 3 is constant (0,0,0,1) — skip
            if (std::fabs(a[c][r] - b[c][r]) > 1e-4f) return false;
    return true;
}
```

```cpp
std::vector<int> weld_head_bones(Skeleton& body, const Skeleton& head) {
    std::unordered_map<std::string, int> body_by_name;
    for (std::size_t i = 0; i < body.bones.size(); ++i)
        body_by_name.emplace(body.bones[i].name, static_cast<int>(i));

    std::vector<int> map(head.bones.size(), -1);

    // Recursive resolve: a head-only bone's PARENT must map first, and the
    // head skeleton's array order doesn't guarantee parents precede children.
    std::function<int(int)> resolve = [&](int hi) -> int {
        if (hi < 0 || hi >= static_cast<int>(head.bones.size())) return -1;
        if (map[hi] != -1) return map[hi];
        const Bone& hb = head.bones[hi];
        auto it = body_by_name.find(hb.name);
        if (it != body_by_name.end()) {
            if (binds_equal(body.bones[it->second].inverse_bind_pose,
                            hb.inverse_bind_pose))
                return map[hi] = it->second;
            // Bind mismatch: alias rides the body bone's pose but skins with
            // the HEAD's bind (BC: body node world x head bind offset).
            const std::string alias_name =
                hb.name + std::string(kHeadBindAliasSuffix);
            for (std::size_t i = 0; i < body.bones.size(); ++i)
                if (body.bones[i].name == alias_name)
                    return map[hi] = static_cast<int>(i);
            Bone alias;
            alias.name = alias_name;
            alias.parent_index = it->second;
            alias.local_transform = glm::mat4(1.0f);
            alias.inverse_bind_pose = hb.inverse_bind_pose;
            body.bones.push_back(std::move(alias));
            return map[hi] = static_cast<int>(body.bones.size()) - 1;
        }
        // Head-only bone: append for real, under its name-matched parent,
        // keeping name/local so animation clips may drive it.
        const int parent = resolve(hb.parent_index);
        Bone extra;
        extra.name = hb.name;
        extra.parent_index = parent;
        extra.local_transform = hb.local_transform;
        extra.inverse_bind_pose = hb.inverse_bind_pose;
        body.bones.push_back(std::move(extra));
        return map[hi] = static_cast<int>(body.bones.size()) - 1;
    };
    for (std::size_t i = 0; i < head.bones.size(); ++i)
        resolve(static_cast<int>(i));
    return map;
}
```

(Note the deliberate ordering in the head-only branch: `resolve(parent)` runs
**before** constructing `extra`, because the recursive call may append to
`body.bones` and the new bone must land after its parent.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cmake --build build -j --target assets_tests && \
  ./build/native/tests/assets_tests --gtest_filter='WeldHeadBones.*'
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/include/assets/model_compose.h \
        native/src/assets/src/model_compose.cc \
        native/tests/assets/cpu/head_weld_test.cc \
        native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): weld_head_bones — §3.5 name-keyed bone map with alias/head-only appends"
```

---

### Task 2: wire the weld into `graft_head_cpu`; delete the rebase

**Files:**
- Modify: `native/src/assets/src/model_compose.cc:146-243` (`graft_head_cpu`)
- Modify: `native/src/assets/include/assets/model_compose.h:1-56` (doc comments)
- Modify: `native/tests/assets/cpu/model_compose_test.cc` (update/replace the rigid-bind and rebase tests)
- Test: `./build/native/tests/assets_tests`

**Interfaces:**
- Consumes: `assets::weld_head_bones` + `assets::kHeadBindAliasSuffix` (Task 1).
- Produces: `graft_head_cpu` (signature unchanged) with new semantics — grafted verts keep authored weights, indices remapped through the weld table; vertex positions never modified; empty head skeleton falls back to the old rigid attach-bone bind. Tasks 3–4 rely on these semantics.

- [ ] **Step 1: Update/write the failing tests**

In `native/tests/assets/cpu/model_compose_test.cc`:

**(a)** Re-comment + rename `GraftHeadCpu.BindsGraftedVerticesToAttachBoneRigid`
→ `GraftHeadCpu.RigidFallbackWhenHeadModelHasNoSkeleton`. Same body and
assertions (the `make_head()` fixture has no skeleton, so the graft must keep
the old rigid attach-bone bind for degenerate/synthetic heads). Replace the
header comment above it with:

```cpp
// Degenerate heads (no skeleton — synthetic fixtures; real BC head NIFs are
// full character templates and always carry one) keep the old rigid bind to
// the attach bone. Also covers the material/texture append plumbing.
```

**(b)** Leave `GraftsHeadMeshNotParentedUnderAttachNode` and
`MissingBoneLeavesBodyUnchanged` untouched (their fixtures have no head
skeleton → fallback path, same assertions).

**(c)** DELETE `GraftHeadCpu.RebasesHeadToBodyAttachBoneBindHeight`
(`model_compose_test.cc:254-302`) and replace it with (same fixture models,
note the vertex now carries an authored weight):

```cpp
// §3.5: a bind-height mismatch between body and head templates is absorbed by
// an ALIAS BONE carrying the head's inverse bind — vertex data is never
// touched (BC never moves verts; the translation-only rebase this replaces
// moved them and was only exact for single-bone bindings). Replaces
// RebasesHeadToBodyAttachBoneBindHeight.
TEST(GraftHeadCpu, BindMismatchUsesAliasBoneAndLeavesVertsUntouched) {
    const auto base_slot =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);

    // Body: "Bip01 Head" bind-world at Z = 10.
    assets::Model body;
    assets::Bone broot; broot.name = "Bip01"; broot.parent_index = -1;
    assets::Bone bhead; bhead.name = "Bip01 Head"; bhead.parent_index = 0;
    bhead.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -10.0f));
    body.skeleton.bones = {broot, bhead};
    body.skeleton.root_bone_index = 0;
    assets::Node bnode; bnode.name = "Bip01 Head"; bnode.parent_index = -1;
    body.nodes = {bnode}; body.root_node = 0;
    body.textures.emplace_back(0, 1, 1, false);
    body.materials.emplace_back();

    // Head: "Bip01 Head" bind-world at Z = 4; one vertex at (1,2,3) authored
    // fully onto the head skeleton's "Bip01 Head" (index 1).
    assets::Model head;
    assets::Bone hroot; hroot.name = "Bip01"; hroot.parent_index = -1;
    assets::Bone hhead; hhead.name = "Bip01 Head"; hhead.parent_index = 0;
    hhead.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -4.0f));
    head.skeleton.bones = {hroot, hhead};
    head.skeleton.root_bone_index = 0;
    head.textures.emplace_back(0, 1, 1, false);
    assets::Material mat; mat.stages[base_slot].texture_index = 0;
    head.materials.push_back(mat);
    assets::MeshCpu hc; hc.vertices.resize(1);
    hc.vertices[0].position = glm::vec3(1.0f, 2.0f, 3.0f);
    hc.vertices[0].bone_indices = {1, 0, 0, 0};
    hc.vertices[0].bone_weights = {255, 0, 0, 0};
    hc.indices = {0, 0, 0}; hc.material_index = 0;
    assets::Mesh hm(0, 0, 0, 3, 0, -1); hm.set_cpu_data(hc);
    head.meshes.push_back(std::move(hm));
    assets::Node hn; hn.name = "head"; hn.parent_index = -1;
    head.nodes = {hn}; head.root_node = 0; head.nodes[0].meshes.push_back(0);

    std::vector<assets::MeshCpu> grafted =
        assets::graft_head_cpu(body, head, "Bip01 Head");
    ASSERT_EQ(grafted.size(), 1u);

    // Vertex position UNTOUCHED (no rebase).
    EXPECT_FLOAT_EQ(grafted[0].vertices[0].position.x, 1.0f);
    EXPECT_FLOAT_EQ(grafted[0].vertices[0].position.y, 2.0f);
    EXPECT_FLOAT_EQ(grafted[0].vertices[0].position.z, 3.0f);

    // Body skeleton gained the alias; the vertex points at it, weight kept.
    ASSERT_EQ(body.skeleton.bones.size(), 3u);
    EXPECT_EQ(body.skeleton.bones[2].name,
              std::string("Bip01 Head") +
                  std::string(assets::kHeadBindAliasSuffix));
    EXPECT_EQ(grafted[0].vertices[0].bone_indices.x, 2);
    EXPECT_EQ(grafted[0].vertices[0].bone_weights.x, 255);
}
```

**(d)** Add the multi-bone remap test:

```cpp
// The weld preserves authored multi-bone weights byte-for-byte, remapping only
// the INDICES by bone name (head skeleton bone order deliberately differs from
// the body's). Zero-weight slots are normalized to index 0.
TEST(GraftHeadCpu, RemapsMultiBoneWeightsByName) {
    const auto base_slot =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);

    // Body skeleton: [Bip01, Bip01 Neck, Bip01 Head], identity binds.
    assets::Model body;
    assets::Bone b0; b0.name = "Bip01";      b0.parent_index = -1;
    assets::Bone b1; b1.name = "Bip01 Neck"; b1.parent_index = 0;
    assets::Bone b2; b2.name = "Bip01 Head"; b2.parent_index = 1;
    body.skeleton.bones = {b0, b1, b2};
    body.skeleton.root_bone_index = 0;
    assets::Node bnode; bnode.name = "Bip01 Head"; bnode.parent_index = -1;
    body.nodes = {bnode}; body.root_node = 0;
    body.textures.emplace_back(0, 1, 1, false);
    body.materials.emplace_back();

    // Head skeleton REVERSED: [Bip01 Head, Bip01 Neck, Bip01], identity binds.
    assets::Model head;
    assets::Bone h0; h0.name = "Bip01 Head"; h0.parent_index = 1;
    assets::Bone h1; h1.name = "Bip01 Neck"; h1.parent_index = 2;
    assets::Bone h2; h2.name = "Bip01";      h2.parent_index = -1;
    head.skeleton.bones = {h0, h1, h2};
    head.skeleton.root_bone_index = 2;
    head.textures.emplace_back(0, 1, 1, false);
    assets::Material mat; mat.stages[base_slot].texture_index = 0;
    head.materials.push_back(mat);
    assets::MeshCpu hc; hc.vertices.resize(1);
    // Authored: 2/3 head-skeleton "Bip01 Head" (idx 0), 1/3 "Bip01 Neck" (1).
    hc.vertices[0].bone_indices = {0, 1, 0, 0};
    hc.vertices[0].bone_weights = {170, 85, 0, 0};
    hc.indices = {0, 0, 0}; hc.material_index = 0;
    assets::Mesh hm(0, 0, 0, 3, 0, -1); hm.set_cpu_data(hc);
    head.meshes.push_back(std::move(hm));
    assets::Node hn; hn.name = "head"; hn.parent_index = -1;
    head.nodes = {hn}; head.root_node = 0; head.nodes[0].meshes.push_back(0);

    std::vector<assets::MeshCpu> grafted =
        assets::graft_head_cpu(body, head, "Bip01 Head");
    ASSERT_EQ(grafted.size(), 1u);
    ASSERT_EQ(body.skeleton.bones.size(), 3u);  // binds equal: no appends

    const auto& v = grafted[0].vertices[0];
    EXPECT_EQ(v.bone_indices.x, 2);   // head "Bip01 Head"(0) -> body 2
    EXPECT_EQ(v.bone_indices.y, 1);   // head "Bip01 Neck"(1) -> body 1
    EXPECT_EQ(v.bone_weights.x, 170); // weights byte-preserved
    EXPECT_EQ(v.bone_weights.y, 85);
    EXPECT_EQ(v.bone_weights.z, 0);
    EXPECT_EQ(v.bone_weights.w, 0);
}
```

- [ ] **Step 2: Run tests to verify the new ones fail**

```bash
cmake --build build -j --target assets_tests && \
  ./build/native/tests/assets_tests --gtest_filter='GraftHeadCpu.*'
```
Expected: `BindMismatchUsesAliasBoneAndLeavesVertsUntouched` FAILS (vertex Z is
9.0 — the rebase moved it — and no alias bone exists);
`RemapsMultiBoneWeightsByName` FAILS (weights overwritten to (255,0,0,0)).
The two fallback tests still PASS.

- [ ] **Step 3: Rewire `graft_head_cpu`**

In `native/src/assets/src/model_compose.cc`:

**(a)** Delete the rebase block (lines 197-218, the comment + `glm::vec3
rebase(0.0f); { ... }` computation).

**(b)** Replace the vertex-binding loop (lines 220-242) with:

```cpp
    // §3.5 bone rebinding — the BC "weld". Map every head-skeleton bone onto
    // the body skeleton by name; grafted verts keep their AUTHORED weights and
    // only their indices are rewritten. Degenerate heads with no skeleton
    // (synthetic fixtures) keep the old rigid attach-bone bind.
    std::vector<int> bone_map;
    if (!head.skeleton.bones.empty())
        bone_map = weld_head_bones(body.skeleton, head.skeleton);

    std::vector<MeshCpu> out;
    out.reserve(graftable.size());
    for (const MeshCpu* src : graftable) {
        MeshCpu cpu = *src;  // deep copy of vertices/indices/extra_uvs
        for (auto& v : cpu.vertices) {
            if (bone_map.empty()) {
                v.bone_indices = glm::u8vec4(
                    static_cast<std::uint8_t>(attach_idx), 0, 0, 0);
                v.bone_weights = glm::u8vec4(255, 0, 0, 0);
                continue;
            }
            for (int k = 0; k < 4; ++k) {
                if (v.bone_weights[k] == 0) { v.bone_indices[k] = 0; continue; }
                const int old = v.bone_indices[k];
                const int mapped =
                    (old >= 0 && old < static_cast<int>(bone_map.size()))
                        ? bone_map[old] : -1;
                v.bone_indices[k] = static_cast<std::uint8_t>(
                    std::clamp(mapped < 0 ? attach_idx : mapped, 0, 255));
            }
        }
        const int src_mat = src->material_index;
        cpu.material_index =
            (src_mat >= 0) ? mat_offset + src_mat : -1;
        cpu.node_index = node_index;
        out.push_back(std::move(cpu));
    }
    return out;
```

**(c)** Update the stale comment block at lines 197-207 area is gone with (a);
also update the big comment at lines 152-165 — keep the "graft ALL visible
meshes" paragraph, drop nothing else.

**(d)** Update `model_compose.h` docs:
- Header preamble lines 8-11: replace
  "`graft_head` appends the head's meshes into the body Model, rigid-binding
  every grafted vertex to the body skeleton's attach bone (e.g. "Bip01 Head"),
  and appends the head's materials/textures with the index remapping that an
  append implies." with:
  "`graft_head` appends the head's meshes into the body Model, welding them to
  the body skeleton BC-style (§3.5): each vertex keeps its authored skin
  weights and its bone indices are remapped by bone NAME via weld_head_bones
  (alias bones absorb bind-pose mismatches; head-only bones are appended).
  Materials/textures are appended with the index remapping an append implies."
- `graft_head_cpu` doc (lines 42-49): replace the "re-based by the attach-bone
  bind-world delta … rigid-bound to the attach bone …" bullet with:
  "returns one ready-to-upload MeshCpu per head mesh that had cpu_data, with
  vertex positions UNTOUCHED and bone indices remapped onto the body skeleton
  by name (weld_head_bones; authored weights preserved). Heads with no
  skeleton fall back to a rigid bind on the attach bone. material_index points
  at the appended material; node_index is the node the GL mesh must be
  registered on."

- [ ] **Step 4: Run the CPU suite**

```bash
cmake --build build -j --target assets_tests && \
  ./build/native/tests/assets_tests --gtest_filter='GraftHeadCpu.*:WeldHeadBones.*:SetBaseTextureCpu.*:FaceTextureCandidates.*'
```
Expected: all PASS. (The GPU real-NIF tests are now RED — that is Task 3;
do not run the full binary expecting green yet.)

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/src/model_compose.cc \
        native/src/assets/include/assets/model_compose.h \
        native/tests/assets/cpu/model_compose_test.cc
git commit -m "feat(assets): graft_head_cpu welds head skins onto the body skeleton (§3.5); drop vertex rebase"
```

---

### Task 3: update the real-NIF GPU tests to the weld semantics

**Files:**
- Modify: `native/tests/assets/gpu/model_compose_gpu_test.cc:22-110` (`GraftRealHeadOntoBodyMaleL`), `:119-215` (`OverridesBodyAndHeadBaseTextures`)
- Test: `./build/native/tests/assets_tests`

**Interfaces:**
- Consumes: `compose_officer_model` (unchanged signature); `Model::head_mesh_begin` (first grafted mesh index, -1 if none; head set is `[head_mesh_begin, meshes.size())`).

- [ ] **Step 1: Confirm the two tests fail on HEAD of the branch**

```bash
./build/native/tests/assets_tests --gtest_filter='ModelComposeGpuTest.GraftRealHeadOntoBodyMaleL:ModelComposeGpuTest.OverridesBodyAndHeadBaseTextures'
```
Expected: both FAIL (their `is_grafted`/rigid-bind heuristics assert the old
weights). If they SKIP, `game/` assets are missing — stop and report BLOCKED.

- [ ] **Step 2: Rewrite the grafted-mesh identification**

In `GraftRealHeadOntoBodyMaleL`, replace the rigid-bind counting block (lines
48-90, from the `int grafted_meshes = 0;` comment through the attach-node
per-vertex `bone_indices.x == head_bone` loop) with:

```cpp
    // Grafted head meshes are [head_mesh_begin, meshes.size()) — set by
    // compose_officer_model. The §3.5 weld preserves the head's authored
    // multi-bone skin, so rigid-bind counting can no longer identify them.
    ASSERT_GE(composed.head_mesh_begin, 0) << "no head meshes grafted";
    const int grafted_meshes =
        static_cast<int>(composed.meshes.size()) - composed.head_mesh_begin;
    EXPECT_GT(grafted_meshes, 0);

    // Every grafted vertex's weighted slots must reference a valid bone, and
    // the authored multi-bone weighting must survive: real BC head skins weight
    // collar verts to Neck/Clavicle/Spine2 (miguel: 51/143 multi-bone), so at
    // least one grafted vertex must carry >= 2 non-zero weights.
    int multi_bone_verts = 0;
    for (auto mi = static_cast<std::size_t>(composed.head_mesh_begin);
         mi < composed.meshes.size(); ++mi) {
        const auto& cpu = composed.meshes[mi].cpu_data();
        ASSERT_TRUE(cpu);
        for (const auto& v : cpu->vertices) {
            int weighted = 0;
            for (int k = 0; k < 4; ++k) {
                if (v.bone_weights[k] == 0) continue;
                ++weighted;
                ASSERT_LT(v.bone_indices[k], composed.skeleton.bones.size())
                    << "grafted vertex references an out-of-range bone";
            }
            ASSERT_GT(weighted, 0) << "grafted vertex has no bone weights";
            if (weighted >= 2) ++multi_bone_verts;
        }
    }
    EXPECT_GT(multi_bone_verts, 0)
        << "head skin collapsed to single-bone — the §3.5 weld regressed to "
           "the rigid attach-bone bind";

    // The grafted meshes must be node-attached (the renderer walks nodes) on
    // the attach node, which replaced the body's default head subtree.
    int attach_node = -1;
    for (std::size_t i = 0; i < composed.nodes.size(); ++i)
        if (composed.nodes[i].name == "Bip01 Head")
            attach_node = static_cast<int>(i);
    ASSERT_GE(attach_node, 0) << "composed body has no 'Bip01 Head' node";
    EXPECT_EQ(composed.nodes[attach_node].meshes.size(),
              static_cast<std::size_t>(grafted_meshes))
        << "attach node does not carry exactly the grafted head meshes";
```

Keep the `head_bone` lookup (lines 42-46) — the draw-list block below still
compiles without it, so delete the lookup **only if** nothing else references
`head_bone` after this rewrite. Keep the draw-list and GL-handle blocks (lines
92-109) unchanged.

- [ ] **Step 3: Rewrite `is_grafted` in `OverridesBodyAndHeadBaseTextures`**

Replace the `head_bone` lookup (lines 152-156) and the `is_grafted` lambda
(lines 158-167) with:

```cpp
    ASSERT_GE(composed.head_mesh_begin, 0) << "no head meshes grafted";
    auto is_grafted = [&](std::size_t mesh_index) {
        return static_cast<int>(mesh_index) >= composed.head_mesh_begin;
    };
```

and change the call site (line 188) from `is_grafted(composed.meshes[i])` to
`is_grafted(i)`.

- [ ] **Step 4: Run the full assets suite**

```bash
cmake --build build -j --target assets_tests && ./build/native/tests/assets_tests
```
Expected: all PASS (real-NIF tests SKIP only if `game/` is absent — it isn't
on this machine).

- [ ] **Step 5: Commit**

```bash
git add native/tests/assets/gpu/model_compose_gpu_test.cc
git commit -m "test(assets): real-NIF compose tests assert the §3.5 weld (head_mesh_begin partition, multi-bone survival)"
```

---

### Task 4: seam-invariant tests (real NIFs, palette-level)

**Files:**
- Create: `native/tests/renderer/head_weld_seam_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add `head_weld_seam_test.cc` to `add_executable(renderer_tests ...)` after `skinned_bridge_test.cc`)
- Test: `./build/native/tests/renderer_tests`

**Interfaces:**
- Consumes: `assets::compose_officer_model` (Task 2 semantics), `renderer::build_bone_palette(const assets::Skeleton&, const std::vector<glm::mat4>*)` (`native/src/renderer/include/renderer/bone_palette.h`), `Model::head_mesh_begin`.
- Produces: nothing downstream — this is the spec's §3 seam guarantee as a regression net.

- [ ] **Step 1: Write the failing-or-passing test file**

(These tests are written AFTER the implementation tasks, so they should pass
immediately; they exist as the permanent regression net for §3.5. If either
fails, the weld is wrong — fix the weld, not the test.)

Create `native/tests/renderer/head_weld_seam_test.cc`:

```cpp
// §3.5's seam guarantee as a regression net: both meshes are skinned to ONE
// shared skeleton, so coincident, identically-weighted seam vertices stay
// together under any pose — with zero runtime reconciliation. Two real-NIF
// checks:
//   * matched pair (BodyMaleS + miguel_head, bit-identical binds): seam pairs
//     with byte-equal weights stay coincident under a bent neck;
//   * mismatched pair (BodyMaleM + miguel_head, ~5.9-unit bind deltas): the
//     alias-bone palette lifts the head onto the body's neck at bind (the old
//     vertex-rebase regression), and seam pairs still hold under a bent neck.
// Character model units (~78/body height), not GU. Skips without game/ assets
// or a GL context (compose_officer_model uploads GL meshes).
#include <gtest/gtest.h>

#include <assets/model.h>
#include <assets/model_compose.h>
#include <renderer/bone_palette.h>
#include <renderer/window.h>

#include <glm/gtc/matrix_transform.hpp>

#include <cmath>
#include <filesystem>
#include <memory>
#include <vector>

namespace {

namespace fs = std::filesystem;

const fs::path kRoot = fs::path(__FILE__)
    .parent_path().parent_path().parent_path().parent_path();
const fs::path kChars = kRoot / "game" / "data" / "Models" / "Characters";

struct SkinnedVert {
    glm::vec3 pos;          // skinned position
    glm::u8vec4 idx, wt;    // binding bytes (for the equal-weights pair rule)
};

// CPU-skin every vertex of the meshes in [begin, end) through `palette` —
// exactly the shader's blend (skinned_bridge.vert): sum of w * (pal[b] * v).
std::vector<SkinnedVert> skin_range(const assets::Model& m,
                                    std::size_t begin, std::size_t end,
                                    const std::vector<glm::mat4>& palette) {
    std::vector<SkinnedVert> out;
    for (std::size_t mi = begin; mi < end && mi < m.meshes.size(); ++mi) {
        const auto& cpu = m.meshes[mi].cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices) {
            glm::vec4 sp(0.0f);
            for (int k = 0; k < 4; ++k) {
                const float w = v.bone_weights[k] / 255.0f;
                if (w <= 0.0f) continue;
                const int b = v.bone_indices[k];
                if (b < static_cast<int>(palette.size()))
                    sp += w * (palette[b] * glm::vec4(v.position, 1.0f));
            }
            out.push_back({glm::vec3(sp), v.bone_indices, v.bone_weights});
        }
    }
    return out;
}

// Bind-pose palette: locals = the skeleton's own bind locals (nullptr pose).
// Identity for real bones; the bind-delta for alias bones.
std::vector<glm::mat4> bind_palette(const assets::Skeleton& sk) {
    return renderer::build_bone_palette(sk, nullptr);
}

// Posed palette: bind locals with "Bip01 Neck" bent 25 degrees about X.
std::vector<glm::mat4> bent_neck_palette(const assets::Skeleton& sk) {
    std::vector<glm::mat4> locals(sk.bones.size());
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        locals[i] = sk.bones[i].local_transform;
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        if (sk.bones[i].name == "Bip01 Neck")
            locals[i] = locals[i] * glm::rotate(glm::mat4(1.0f),
                                                glm::radians(25.0f),
                                                glm::vec3(1.0f, 0.0f, 0.0f));
    return renderer::build_bone_palette(sk, &locals);
}

// Seam pairs: (body vert, head vert) coincident at bind (dist < pair_eps)
// with byte-equal weight vectors — §3.5's authoring invariant. Weight-vector
// equality compares the WEIGHT bytes sorted descending (they arrive sorted
// from fill_skin_weights), not the indices (body and head verts legitimately
// reference different palette entries on a mismatched pair).
struct SeamPair { std::size_t body, head; };
std::vector<SeamPair> find_seam_pairs(const std::vector<SkinnedVert>& body,
                                      const std::vector<SkinnedVert>& head,
                                      float pair_eps) {
    std::vector<SeamPair> pairs;
    for (std::size_t h = 0; h < head.size(); ++h)
        for (std::size_t b = 0; b < body.size(); ++b)
            if (glm::distance(body[b].pos, head[h].pos) < pair_eps &&
                body[b].wt == head[h].wt)
                pairs.push_back({b, h});
    return pairs;
}

class HeadWeldSeamTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;

    void SetUp() override {
        if (!fs::is_regular_file(
                kChars / "Heads/HeadMiguel/miguel_head.NIF"))
            GTEST_SKIP() << "character NIFs not installed";
        try {
            w = std::make_unique<renderer::Window>(64, 64, "seam-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }

    assets::Model compose(const char* body_dir, const char* body_nif) {
        return assets::compose_officer_model(
            kChars / "Bodies" / body_dir / body_nif, /*body_tex=*/{},
            kChars / "Heads/HeadMiguel/miguel_head.NIF", /*head_tex=*/{},
            "Bip01 Head");
    }
};

}  // namespace

TEST_F(HeadWeldSeamTest, MatchedPairSeamHoldsUnderBentNeck) {
    assets::Model m = compose("BodyMaleS", "BodyMaleS.nif");
    ASSERT_GE(m.head_mesh_begin, 0);

    const auto bind = bind_palette(m.skeleton);
    const auto body0 = skin_range(m, 0, m.head_mesh_begin, bind);
    const auto head0 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bind);

    // Matched binds: seam-ring verts coincide essentially exactly at bind.
    const auto pairs = find_seam_pairs(body0, head0, /*pair_eps=*/1e-3f);
    ASSERT_GT(pairs.size(), 0u)
        << "no coincident equal-weight seam pairs at bind — either the weld "
           "moved verts (it must not) or the pair search is broken";

    const auto bent = bent_neck_palette(m.skeleton);
    const auto body1 = skin_range(m, 0, m.head_mesh_begin, bent);
    const auto head1 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bent);
    for (const auto& p : pairs)
        EXPECT_LT(glm::distance(body1[p.body].pos, head1[p.head].pos), 1e-3f)
            << "seam split under a bent neck (body vert " << p.body
            << " vs head vert " << p.head << ")";
}

TEST_F(HeadWeldSeamTest, MismatchedPairAliasLiftsHeadOntoNeck) {
    assets::Model m = compose("BodyMaleM", "BodyMaleM.NIF");
    ASSERT_GE(m.head_mesh_begin, 0);

    // Raw (unskinned) head verts sit in the HEAD template's bind space,
    // several units below the body's head; the alias palette must lift them.
    glm::vec3 raw_lo(1e9f), raw_hi(-1e9f);
    for (std::size_t mi = m.head_mesh_begin; mi < m.meshes.size(); ++mi) {
        const auto& cpu = m.meshes[mi].cpu_data();
        ASSERT_TRUE(cpu);
        for (const auto& v : cpu->vertices) {
            raw_lo = glm::min(raw_lo, v.position);
            raw_hi = glm::max(raw_hi, v.position);
        }
    }

    const auto bind = bind_palette(m.skeleton);
    const auto head0 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bind);
    glm::vec3 sk_lo(1e9f), sk_hi(-1e9f);
    for (const auto& sv : head0) {
        sk_lo = glm::min(sk_lo, sv.pos);
        sk_hi = glm::max(sk_hi, sv.pos);
    }

    // BodyMaleM's skeleton is ~5-6 units taller than the S/M head template
    // (measured sweep: per-bone deltas 4.85-5.9). The lift must be a clear
    // upward shift, and the skinned head must sit at the BODY's head-bone
    // height (regression for the deleted translation-rebase).
    const float lift = ((sk_lo.z + sk_hi.z) - (raw_lo.z + raw_hi.z)) * 0.5f;
    EXPECT_GT(lift, 3.0f)
        << "alias palette did not lift the mismatched head onto the neck "
           "(head-in-chest regression)";

    int body_head_bone = -1;
    for (std::size_t i = 0; i < m.skeleton.bones.size(); ++i)
        if (m.skeleton.bones[i].name == "Bip01 Head")
            body_head_bone = static_cast<int>(i);
    ASSERT_GE(body_head_bone, 0);
    const glm::vec3 head_bind_world(
        glm::inverse(m.skeleton.bones[body_head_bone].inverse_bind_pose)[3]);
    EXPECT_LT(std::fabs((sk_lo.z + sk_hi.z) * 0.5f - head_bind_world.z), 8.0f)
        << "skinned head centre is far from the body's Bip01 Head bind";

    // And the seam still holds under a bent neck — pair_eps is looser here:
    // body verts skin through W*O_body, head verts through W*O_head; equal in
    // the reals on the authored seam ring, distinct float paths.
    const auto body0 = skin_range(m, 0, m.head_mesh_begin, bind);
    const auto pairs = find_seam_pairs(body0, head0, /*pair_eps=*/5e-2f);
    ASSERT_GT(pairs.size(), 0u) << "no seam pairs found on the mismatched pair";

    const auto bent = bent_neck_palette(m.skeleton);
    const auto body1 = skin_range(m, 0, m.head_mesh_begin, bent);
    const auto head1 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bent);
    for (const auto& p : pairs)
        EXPECT_LT(glm::distance(body1[p.body].pos, head1[p.head].pos), 1e-1f)
            << "mismatched-pair seam split under a bent neck (body vert "
            << p.body << " vs head vert " << p.head << ")";
}
```

Add `head_weld_seam_test.cc` to `native/tests/renderer/CMakeLists.txt`'s
`add_executable(renderer_tests` list, after `skinned_bridge_test.cc`.

- [ ] **Step 2: Build and run**

```bash
cmake --build build -j --target renderer_tests && \
  ./build/native/tests/renderer_tests --gtest_filter='HeadWeldSeamTest.*'
```
Expected: both PASS. Diagnosis guide if not:
- `no coincident equal-weight seam pairs` on the MATCHED pair → the weld moved
  vertex positions or destroyed weights; inspect `graft_head_cpu` (Task 2).
- `alias palette did not lift` → `weld_head_bones` mapped mismatched-bind
  bones directly (epsilon too loose) or alias `inverse_bind_pose` is the
  body's, not the head's.
- `seam split under a bent neck` → alias bone's name collides with a clip
  track / rest_locals entry (check `kHeadBindAliasSuffix` is applied), or its
  local_transform is not identity.
- If the MISMATCHED pair finds no seam pairs at eps 5e-2 but the matched pair
  passes, loosen `pair_eps` stepwise to 1e-1 and report the measured minimum
  body-head vertex distance in the commit message — that number is evidence
  about BC's authoring tolerance, not a test bug.

- [ ] **Step 3: Prove the net catches the old bug**

Temporarily revert the weld semantics WITHOUT git (shared checkout — copy,
never `git checkout --`):

```bash
cp native/src/assets/src/model_compose.cc /tmp/weld_bak.cc
# Edit graft_head_cpu: replace the remap loop body with the old rigid bind
#   v.bone_indices = glm::u8vec4(static_cast<std::uint8_t>(attach_idx),0,0,0);
#   v.bone_weights = glm::u8vec4(255, 0, 0, 0);
# (unconditionally, ignoring bone_map), rebuild, rerun:
cmake --build build -j --target renderer_tests && \
  ./build/native/tests/renderer_tests --gtest_filter='HeadWeldSeamTest.*'
```
Expected: `MatchedPairSeamHoldsUnderBentNeck` FAILS — either at the seam-pair
assert (the rigid overwrite destroys the byte-equal weights the pairing
requires) or at the bent-neck assert (rigid head verts rotate about the head
bone while body collar verts blend). Either failure proves the net catches
the old behaviour. Restore and verify byte-identical, then rebuild:

```bash
cp /tmp/weld_bak.cc native/src/assets/src/model_compose.cc
diff native/src/assets/src/model_compose.cc /tmp/weld_bak.cc && echo RESTORED
cmake --build build -j --target renderer_tests && \
  ./build/native/tests/renderer_tests --gtest_filter='HeadWeldSeamTest.*'
```
Expected: `RESTORED`, then both PASS again.

- [ ] **Step 4: Commit**

```bash
git add native/tests/renderer/head_weld_seam_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "test(renderer): §3.5 seam-invariant net — matched + mismatched real-NIF pairs hold under a bent neck"
```

---

### Task 5: full gate, review, live-verify handoff

**Files:**
- No source changes expected. Fix-forward anything the gate names.

- [ ] **Step 1: Run the gate**

```bash
scripts/check_tests.sh
```
Expected: exit 0; the only failures are the 7 baselined headless-GL
scorch/heat-glow `FrameTest`s in `tests/known_failures.txt`. Any OTHER failure
is a regression from this branch — fix it in the task that introduced it
(update that task's tests in the same commit) and rerun. Never eyeball a
failure as "pre-existing"; the gate's ledger is the only authority.

- [ ] **Step 2: Request code review**

Use the superpowers:requesting-code-review flow on the branch diff
(`git diff main...feat/head-neck-weld`). Tell the reviewer subagent explicitly:
**no destructive git** (no `git checkout -- <path>` / `git restore` / stash /
clean; probe-mutations restore by `cp` from a backup).

- [ ] **Step 3: Live GUI verification handoff (Mark runs; do not drive his desktop)**

Build, then hand off with this checklist:

```bash
cmake --build build -j
```

Ask Mark to run `./build/dauntless --developer` and check:
1. Bridge officers' heads are **textured** (no grey/white heads). If any head
   is untextured, capture which character — then (and only then) open the
   texturing diagnosis from spec §2, and update the
   `project_bc_character_rigid_skinning` memory either way (the "heads render
   untextured" line is believed stale).
2. The neck seam stays closed during hit reactions / nod gestures — check one
   matched-pair officer AND one mismatched-pair character (any character using
   `miguel_head`/`ferengi_head` on `BodyMaleM`, or `fem3_head`/
   `femromulan_head` on `BodyFemM` — e.g. via the dev mission picker's E1M1 or
   QuickBattle crew).
3. A comm hail: comm character's head textured, lip-sync still blinking/
   speaking (`set_officer_face` path untouched).

- [ ] **Step 4: After Mark confirms — merge flow**

Use superpowers:finishing-a-development-branch. Update project memory:
`project_bc_character_rigid_skinning` (weld shipped; untextured-heads line
resolved one way or the other) and add the weld outcome to `MEMORY.md`.

---

## Self-review notes (already applied)

- Spec §1 (remap + alias + head-only bones) → Tasks 1-2. Spec §2 (texturing:
  no code, live check) → Task 5 step 3. Spec §3 (tests incl. matched
  bit-level/epsilon split) → Tasks 1-4 (the "bit-identical" ambition is
  realized as 1e-3 model-unit coincidence on the matched pair: byte-equal
  weights + same palette entries make the arithmetic identical, but the
  pair-finding itself needs a distance predicate, so the assertion uses the
  same epsilon it pairs with). Spec §4 (live verify) → Task 5. Spec §5
  (branch discipline) → Global Constraints. Spec §6 (non-goals) → nothing to
  implement; the `model_aabb` note needs no task (officers are never
  shield-registered).
- The DISABLED PNG-dump diagnostic in `skinned_bridge_test.cc` uses a
  hardcoded `mat < 36` head heuristic; it is DISABLED and diagnostic-only —
  deliberately not updated by this plan.
- `weld_head_bones` is called once per `graft_head_cpu`; the alias-dedupe
  linear scan is O(bones) and runs at model-compose time only — no per-frame
  cost anywhere.
