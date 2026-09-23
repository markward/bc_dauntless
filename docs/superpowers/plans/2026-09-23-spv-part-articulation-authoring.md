# SPV Part Articulation Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Ship Property Viewer author ship part articulation — mark mesh
nodes detachable, place their hinges, and give them a pose per alert state — and
guarantee hardpoints are only ever edited in the pose they are stored in.

**Architecture:** Articulation stops being hardcoded Python dicts and becomes
BC-style property templates (`ArticulatedPartProperty`), written by the existing
SPV save path into `hardpoint_overrides.py` for stock ships and, later, straight
into a mod's own hardpoint file. The NIF pose anchors everything; bounding boxes
are derived from mesh geometry rather than authored; part candidates are the
children of `Scene Root`, so no NIF reader change is needed.

**Tech Stack:** Python 3 (`engine/appc/`, `engine/ui/`), C++20 + glm
(`native/src/host/`, `native/src/renderer/`), CEF/JS
(`native/assets/ui-cef/`), pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-09-23-spv-part-articulation-authoring-design.md`

## Global Constraints

- **Shared checkout — destructive git is BANNED.** Read the "Shared checkout"
  section of `CLAUDE.md` and obey it exactly: never restore the working tree
  from the index or HEAD, never stash, never clean, never hard-reset, and never
  stage with a wildcard. Stage with explicit pathspecs only. To mutate a file
  temporarily, `cp` to the scratchpad, mutate, restore by `cp`, and `diff` to
  prove the restore is byte-identical.
- **NEVER launch the game** (`./build/dauntless`). Mark does live verification.
- **ONE build tree** at `<project-root>/build/`: `cmake -B build -S . && cmake --build build -j`.
  Never run `cmake` inside `native/`.
- **The gate is `scripts/check_tests.sh`**, never `scripts/run_tests.sh` (which
  cannot see C++ regressions). Clean is `OK — no new failures. 1 known failure(s)
  still baselined.` Read `tests/known_failures.txt`; never trust a remembered count.
- **Units.** `MODEL_TO_SHIP = 0.01` = `host_loop.BC_MODEL_SCALE`. Hardpoints,
  `PART_BOXES`, `part_for_point`, pivots and derived bounds are SHIP units;
  `world_to_body` results and raw NIF data are MODEL units. `host_io.set_instance_node_rotation`
  takes MODEL units. This confusion has shipped dead features twice.
- **Rotation is column-vector, right-handed:** `v_world = R · v_body`;
  world-forward is `GetCol(1)`, never `GetRow(1)`.
- **Never spell `game` or `sdk` as a literal path segment.** Use `engine/paths.py`.
- **A real BC hull is THREE levels** — part → `__NDL_MultiMtl_Node` → mesh. Every
  test fixture mirrors three. A two-level fixture let a picking bug reach live play.
- **Python 1.5 safety.** Anything emitted into a file the original `stbc.exe` may
  load must parse under Python 1.5: no `True`/`False` literals (use `1`/`0`), no
  f-strings, no `import X as Y`. `hardpoint_overrides.py` is exempt — stbc.exe
  never loads it.
- **The four state names are exactly** `"cruise"`, `"yellow"`, `"red"`, `"warp"`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `engine/host_loop.py` | render sync | `_sync_ship_articulation` honours a forced display pose while the SPV is open |
| `native/src/renderer/model_parts.{h,cc}` | **new** — part-candidate detection + per-node derived bounds, pure geometry | created |
| `native/src/host/host_bindings.cc` | bindings | new `model_nodes(iid)` |
| `engine/appc/articulated_part.py` | **new** — the `ArticulatedPartProperty` template type and its registry lookup | created |
| `engine/appc/hardpoint_override_writer.py` | override emitter | new find-or-**create** verb |
| `engine/appc/articulation.py` | rig maths + state machine | loses `_RIGS`/`PART_BOXES`/`DETACHABLE`; gains four states and per-part angles |
| `engine/appc/hardpoint_overrides.py` | machine-owned data | gains the migrated BoP part templates |
| `engine/ui/ship_property_viewer.py` | SPV model | part list state, selection, derived-box display |
| `engine/ui/ship_property_viewer_panel.py` | CEF panel | Model Parts pane payload, actions, save edits, safety lock |
| `native/assets/ui-cef/{index.html,js/ship_property_viewer.js,css/hello.css}` | SPV UI | the Model Parts pane and its controls |

---

### Task 1: The SPV forces the anchor pose

**This task stands alone and ships first.** It depends on nothing else in this
plan and fixes a live hazard: a Bird of Prey opened in the SPV at green alert is
drawn wings-UP, its subsystem pins follow that pose, and any mount position
authored through it is written back as a rest-pose number — a ~0.9 ship-unit
(~150 m) error at the wingtip, with nothing on screen to say so.

**Files:**
- Modify: `engine/host_loop.py:7022-7062` (`_sync_ship_articulation`), and its
  one call site in `_sync_instance_transforms` (~`:7137`)
- Test: `tests/unit/test_spv_anchor_pose.py` (create)

**Interfaces:**
- Consumes: `engine.ui.ship_property_viewer.is_open() -> bool`,
  `articulation.parts_for_ship(ship)`, `articulation.rotation_for(part, deflection)`,
  `part_severance.is_detached(ship, node)`, `host_io.set_instance_node_rotation`
- Produces: `_sync_ship_articulation(session, ship, iid, *, force_rest=False)` —
  the new keyword argument. Later tasks keep this signature.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_spv_anchor_pose.py`:

```python
"""The SPV draws the hull in its NIF pose, so mounts are edited in the frame
they are stored in.

The hologram re-draws the LIVE player instance and honours node_overrides by
design (hologram_pass.cc:51-56 -- it must, or pins on an articulated part land
wrong). Opening the SPV freezes the sim but does not reset the pose:
_sync_ship_articulation runs in the RENDER pass, not the sim tick, so it keeps
re-pushing the frozen deflection. A Bird of Prey opened at green alert is drawn
wings-up and every mount authored through it is ~0.9 ship units out.
"""
import pytest

from engine.appc import articulation


class _Session:
    def __init__(self):
        self.ship_articulation = {}


class _Ship:
    def __init__(self, deflection=1.0):
        self._articulation_leaf = "birdofprey"
        self._articulation_deflection = deflection

    def GetArticulationDeflection(self):
        return self._articulation_deflection


@pytest.fixture
def pushes(monkeypatch):
    """Record every set_instance_node_rotation the sync makes."""
    from engine import host_io
    seen = []
    monkeypatch.setattr(
        host_io, "set_instance_node_rotation",
        lambda iid, node, pivot, axis, theta: seen.append((node, theta)))
    return seen


def test_the_fixture_ship_actually_articulates(pushes):
    """Guard. If the BoP rig ever stops resolving, every test below would pass
    vacuously by pushing nothing at all."""
    from engine import host_loop
    host_loop._sync_ship_articulation(_Session(), _Ship(deflection=1.0), 7)
    assert pushes, "the fixture must push a real pose, or the tests prove nothing"
    assert any(theta != 0.0 for _node, theta in pushes)


def test_force_rest_pushes_ZERO_rotation_on_every_part(pushes):
    """THE POINT. Not 'pushes nothing' -- pushing nothing would leave the
    previous articulated pose standing in node_overrides."""
    from engine import host_loop
    host_loop._sync_ship_articulation(_Session(), _Ship(deflection=1.0), 7,
                                      force_rest=True)
    assert pushes, "the rest pose must be pushed, not merely not-overwritten"
    assert all(theta == 0.0 for _node, theta in pushes), pushes


def test_force_rest_does_not_mutate_the_ship(pushes):
    """_sync_ship_articulation is READ-ONLY on game state -- a mutation in the
    render path is what once gave the player's phasers half a second aiming at
    a destroyed subsystem."""
    from engine import host_loop
    ship = _Ship(deflection=1.0)
    host_loop._sync_ship_articulation(_Session(), ship, 7, force_rest=True)
    assert ship.GetArticulationDeflection() == 1.0


def test_the_change_guard_still_fires_on_the_open_and_close_edges(pushes):
    """The sync is guarded on CHANGE so a settled ship costs one float compare.
    Forcing rest must not defeat that, and must not be defeated BY it: opening
    the SPV has to push once, and closing has to push the live pose back."""
    from engine import host_loop
    session, ship = _Session(), _Ship(deflection=1.0)

    host_loop._sync_ship_articulation(session, ship, 7)            # live
    live = list(pushes); pushes.clear()
    assert live

    host_loop._sync_ship_articulation(session, ship, 7, force_rest=True)
    assert pushes, "the open edge must re-push"
    assert all(theta == 0.0 for _n, theta in pushes)
    pushes.clear()

    host_loop._sync_ship_articulation(session, ship, 7, force_rest=True)
    assert pushes == [], "a settled forced pose must not re-push every frame"

    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes, "the close edge must restore the live pose"
    assert any(theta != 0.0 for _n, theta in pushes)


def test_a_severed_part_stays_severed_while_forced(pushes, monkeypatch):
    """A severed part is HIDDEN through the same node_overrides slot this
    rotation writes. Pushing a rest rotation onto it would snap the wing back
    onto the hull and then erase the hide for good."""
    from engine import host_loop
    from engine.appc import part_severance
    monkeypatch.setattr(part_severance, "is_detached",
                        lambda s, node: node == "left wing")
    host_loop._sync_ship_articulation(_Session(), _Ship(deflection=1.0), 7,
                                      force_rest=True)
    assert pushes, "the other wing must still be posed"
    assert all(node != "left wing" for node, _t in pushes)


def test_an_unrigged_ship_is_untouched(pushes):
    from engine import host_loop
    ship = _Ship()
    ship._articulation_leaf = ""
    host_loop._sync_ship_articulation(_Session(), ship, 7, force_rest=True)
    assert pushes == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_spv_anchor_pose.py -v`

Expected: the four `force_rest` tests FAIL with
`TypeError: _sync_ship_articulation() got an unexpected keyword argument 'force_rest'`.
`test_the_fixture_ship_actually_articulates` and `test_an_unrigged_ship_is_untouched`
PASS — they are guards, not drivers. **If the first guard fails, STOP and report:**
the fixture is not exercising a real rig and nothing below would prove anything.

- [ ] **Step 3: Add the forced pose**

In `engine/host_loop.py`, change the signature and the deflection read:

```python
def _sync_ship_articulation(session, ship, iid, *, force_rest=False) -> None:
```

Extend the docstring with:

```
    `force_rest` draws the hull in its NIF pose (every part at rotation 0)
    without touching game state. The Ship Property Viewer sets it, because a
    hardpoint mount is STORED in the NIF frame: editing one through an
    articulated pose writes back a number that is ~0.9 ship units out at a
    Bird of Prey's wingtip, silently. See spec section 5.1.

    It pushes an explicit ZERO rotation rather than skipping the push --
    skipping would leave whatever pose is already in node_overrides standing.
```

Replace the deflection read and the `rotation_for` call:

```python
    try:
        deflection = float(ship.GetArticulationDeflection())
    except Exception:  # noqa: BLE001 - a prop / test double is not articulated
        return
    if force_rest:
        deflection = 0.0
    last = session.ship_articulation.get(iid)
    if last is not None and last == deflection:
        return
```

The rest of the loop is unchanged: `rotation_for(part, 0.0)` yields
`theta == 0.0`, which is exactly the rest pose, and the existing
`is_detached` guard already keeps severed parts hidden.

⚠️ Do NOT reuse `session.ship_articulation[iid]` for a separate "forced" flag.
Storing the effective deflection is what makes both edges re-push exactly once.

- [ ] **Step 4: Set it from the SPV**

Find the call site in `_sync_instance_transforms` (`grep -n "_sync_ship_articulation" engine/host_loop.py`).
Pass the flag, resolving the SPV state the same way the render block already
does at `engine/host_loop.py:9615-9617`:

```python
        _spv_rest = (dev_mode.is_enabled()
                     and ship_property_viewer.is_open())
        _sync_ship_articulation(session, ship, iid, force_rest=_spv_rest)
```

Use whatever import of `ship_property_viewer` / `dev_mode` is already in scope in
that function; do not add a duplicate module-level import. If neither is in
scope, import inside the function — `_sync_instance_transforms` runs per frame,
so a module-level import of a UI module here would be a new import cycle risk.

⚠️ `dev_mode.is_enabled()` must be part of the condition. The SPV panel is never
constructed outside `--developer`, and production rendering must stay
byte-identical.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_spv_anchor_pose.py -v`
Expected: 6 passed.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_spv_anchor_pose.py
git commit -m "fix(spv): draw the hull in its NIF pose while the viewer is open

A hardpoint mount is stored in the NIF frame, but the SPV re-draws the
live instance and the hologram honours node_overrides -- so a Bird of
Prey opened at green alert was drawn wings-up and any mount authored
through it was written back ~0.9 ship units out, silently.

Pushes an explicit zero rotation rather than skipping the push, so the
previously articulated pose cannot stand.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `model_nodes` — enumerate parts and derive their bounds

Nothing can list a model's nodes from Python, which is why `articulation.py`
hardcodes `"left wing"` as a string read off the NIF by hand and hand-authors
`PART_BOXES`. One binding closes both gaps.

**Files:**
- Create: `native/src/renderer/include/renderer/model_parts.h`,
  `native/src/renderer/model_parts.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (source list, beside `part_frame.cc`),
  `native/tests/renderer/CMakeLists.txt` (test list, beside `part_frame_test.cc`),
  `native/src/host/host_bindings.cc` (new binding)
- Test: `native/tests/renderer/model_parts_test.cc` (create)

**Interfaces:**
- Consumes: `assets::Model` (`nodes`, `root_node`, `meshes`, `Node::parent_index`,
  `Node::children`, `Node::meshes`, `Node::name`, `Node::local_transform`,
  `assets::Mesh::cpu_data()` — which returns `const std::optional<MeshCpu>&`,
  NOT a pointer), `resolve_model(inst->model_handle)`
- Produces:
  ```cpp
  namespace renderer {
  struct ModelPart {
      std::string name;
      std::string parent;      // empty for the root
      bool        candidate = false;
      glm::vec3   bounds_min{0.0f};
      glm::vec3   bounds_max{0.0f};
      bool        has_bounds = false;
  };
  std::vector<ModelPart> model_parts(const assets::Model& model);
  }
  ```
  and the Python binding `model_nodes(instance_id) -> list[dict]` with keys
  `name`, `parent`, `candidate`, `bounds_min`, `bounds_max` (bounds in **SHIP**
  units; a node with no geometry in its subtree is omitted from the list).

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/model_parts_test.cc`:

```cpp
// Part candidates are the children of 'Scene Root'. Measured on the real
// BirdOfPrey.nif with native/tools/dump_nif_tree:
//
//   [5] NiNode 'Scene Root'  (children=4)
//         [6]  'head'        [20] 'left wing'
//         [32] 'left wing01' [42] 'birdofprey'
//
// 'Scene Root' itself sits under two UNNAMED wrapper nodes, and every part's
// geometry hangs off an interposed '__NDL_MultiMtl_Node' -- a 3ds Max exporter
// artifact. A real hull is THREE levels, and a two-level fixture is what let a
// picking bug reach live play in the preceding work.

#include <gtest/gtest.h>

#include <string>
#include <vector>

#include <glm/gtc/matrix_transform.hpp>

#include <assets/model.h>
#include <renderer/model_parts.h>

namespace {

int add_node(assets::Model& m, const char* name, int parent,
             const glm::mat4& xf = glm::mat4(1.0f)) {
    const int idx = static_cast<int>(m.nodes.size());
    m.nodes.push_back(assets::Node{
        .name = name, .parent_index = parent, .local_transform = xf,
    });
    if (parent >= 0) m.nodes[parent].children.push_back(idx);
    return idx;
}

int add_unit_cube_mesh(assets::Model& m) {
    assets::MeshCpu cpu;
    cpu.vertices.push_back({.position = glm::vec3(-1, -1, -1)});
    cpu.vertices.push_back({.position = glm::vec3(1, -1, 1)});
    cpu.vertices.push_back({.position = glm::vec3(1, 1, 1)});
    cpu.indices = {0u, 1u, 2u};
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
    return static_cast<int>(m.meshes.size()) - 1;
}

// Two unnamed wrappers -> 'Scene Root' -> two parts -> __NDL -> mesh.
assets::Model bop_shaped_model() {
    assets::Model m;
    m.root_node = 0;
    const int w0 = add_node(m, "", -1);
    const int w1 = add_node(m, "", w0);
    const int root = add_node(m, "Scene Root", w1);
    const int mesh = add_unit_cube_mesh(m);

    const int wing = add_node(m, "left wing", root,
                              glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0)));
    const int wing_mtl = add_node(m, "__NDL_MultiMtl_Node", wing);
    m.nodes[wing_mtl].meshes.push_back(mesh);

    const int body = add_node(m, "birdofprey", root);
    const int body_mtl = add_node(m, "__NDL_MultiMtl_Node", body);
    m.nodes[body_mtl].meshes.push_back(mesh);
    return m;
}

const renderer::ModelPart* find(const std::vector<renderer::ModelPart>& v,
                                const std::string& name) {
    for (const auto& p : v) if (p.name == name) return &p;
    return nullptr;
}

}  // namespace

TEST(ModelParts, SceneRootsChildrenAreTheCandidates) {
    const auto parts = renderer::model_parts(bop_shaped_model());
    const auto* wing = find(parts, "left wing");
    const auto* body = find(parts, "birdofprey");
    ASSERT_NE(wing, nullptr);
    ASSERT_NE(body, nullptr);
    EXPECT_TRUE(wing->candidate);
    EXPECT_TRUE(body->candidate);
}

TEST(ModelParts, PlumbingAndWrappersAreNotCandidates) {
    // The thing that makes the list usable. __NDL_MultiMtl_Node is exporter
    // plumbing and 'Scene Root' is not itself a part.
    const auto parts = renderer::model_parts(bop_shaped_model());
    for (const auto& p : parts) {
        if (p.name == "__NDL_MultiMtl_Node" || p.name == "Scene Root" || p.name.empty()) {
            EXPECT_FALSE(p.candidate) << p.name << " must not be a candidate";
        }
    }
}

TEST(ModelParts, BoundsIncludeDESCENDANTGeometry) {
    // THE TRAP. A part node carries no meshes of its own -- they hang off its
    // __NDL child. Bounds built from a node's OWN meshes would be empty for
    // every part on every real hull.
    const auto parts = renderer::model_parts(bop_shaped_model());
    const auto* wing = find(parts, "left wing");
    ASSERT_NE(wing, nullptr);
    ASSERT_TRUE(wing->has_bounds) << "a part's bounds come from its descendants";
    EXPECT_NEAR(wing->bounds_min.x, 9.0f, 1e-4f);
    EXPECT_NEAR(wing->bounds_max.x, 11.0f, 1e-4f);
}

TEST(ModelParts, BoundsAreRestPoseAndIncludeTheNodeChain) {
    // The wing is translated +10 by its own local_transform; the body is not.
    const auto parts = renderer::model_parts(bop_shaped_model());
    const auto* body = find(parts, "birdofprey");
    ASSERT_NE(body, nullptr);
    ASSERT_TRUE(body->has_bounds);
    EXPECT_NEAR(body->bounds_min.x, -1.0f, 1e-4f);
    EXPECT_NEAR(body->bounds_max.x, 1.0f, 1e-4f);
}

TEST(ModelParts, ANodeWithNoGeometryAnywhereHasNoBounds) {
    assets::Model m;
    m.root_node = 0;
    const int root = add_node(m, "Scene Root", -1);
    add_node(m, "empty", root);
    const auto parts = renderer::model_parts(m);
    const auto* empty = find(parts, "empty");
    ASSERT_NE(empty, nullptr);
    EXPECT_FALSE(empty->has_bounds);
}

TEST(ModelParts, FallsBackToTheFirstBranchingNodeWithoutASceneRoot) {
    // Not every hull names its root 'Scene Root'. The rule degrades to "the
    // first node with more than one child" rather than returning nothing.
    assets::Model m;
    m.root_node = 0;
    const int w0 = add_node(m, "", -1);
    const int mesh = add_unit_cube_mesh(m);
    const int a = add_node(m, "alpha", w0);
    const int b = add_node(m, "beta", w0);
    m.nodes[a].meshes.push_back(mesh);
    m.nodes[b].meshes.push_back(mesh);

    const auto parts = renderer::model_parts(m);
    const auto* alpha = find(parts, "alpha");
    ASSERT_NE(alpha, nullptr);
    EXPECT_TRUE(alpha->candidate);
}
```

- [ ] **Step 2: Register the test and watch it fail**

Add `model_parts_test.cc` to `native/tests/renderer/CMakeLists.txt` beside
`part_frame_test.cc`.

Run: `cmake -B build -S . && cmake --build build -j`
Expected: FAIL — `renderer/model_parts.h: No such file or directory`.

- [ ] **Step 3: Write the header**

Create `native/src/renderer/include/renderer/model_parts.h`:

```cpp
// native/src/renderer/include/renderer/model_parts.h
#pragma once

#include <string>
#include <vector>

#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// One node of a model, with its rest-pose bounds, for the SPV's part list.
struct ModelPart {
    std::string name;
    std::string parent;          ///< empty for the root
    bool        candidate = false;
    glm::vec3   bounds_min{0.0f};
    glm::vec3   bounds_max{0.0f};
    bool        has_bounds = false;
};

/// Every named node of `model`, rest pose, MODEL units.
///
/// `candidate` marks the nodes a human would call a "part". Those are the
/// children of the node named "Scene Root" -- measured on the real
/// BirdOfPrey.nif with native/tools/dump_nif_tree, whose Scene Root has
/// exactly four children: head, left wing, left wing01, birdofprey. Scene Root
/// itself sits below two UNNAMED wrapper nodes, so this cannot simply use
/// model.root_node. Hulls with no "Scene Root" fall back to the first node
/// with more than one child.
///
/// The NIF's own "Top Level Object" label is NOT usable for this: it is a
/// stream-framing marker that precedes a block's real type name
/// (native/src/nif/src/file.cc:81-91), it is discarded during parse, and
/// assets::Node has no field for it.
///
/// `bounds_*` cover the node's WHOLE SUBTREE, because a part node carries no
/// meshes of its own -- they hang off an interposed __NDL_MultiMtl_Node child
/// (a 3ds Max exporter artifact). Bounds taken from a node's own meshes would
/// be empty for every part on every real hull.
std::vector<ModelPart> model_parts(const assets::Model& model);

}  // namespace renderer
```

- [ ] **Step 4: Write the implementation**

Create `native/src/renderer/model_parts.cc`:

```cpp
// native/src/renderer/model_parts.cc
#include <renderer/model_parts.h>

#include <limits>

#include <assets/model.h>

namespace renderer {
namespace {

/// The node whose children are parts: "Scene Root" if present, else the first
/// node with more than one child, else -1.
int part_parent_index(const assets::Model& model) {
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].name == "Scene Root") return static_cast<int>(i);
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].children.size() > 1) return static_cast<int>(i);
    }
    return -1;
}

}  // namespace

std::vector<ModelPart> model_parts(const assets::Model& model) {
    std::vector<ModelPart> out;
    const std::size_t n = model.nodes.size();
    if (n == 0) return out;

    // Rest world-per-node. The asset pipeline orders nodes so parents precede
    // children, so one linear pass suffices (same as aabb.cc / part_frame.cc).
    std::vector<glm::mat4> rest(n, glm::mat4(1.0f));
    if (model.root_node >= 0 && static_cast<std::size_t>(model.root_node) < n) {
        rest[model.root_node] = model.nodes[model.root_node].local_transform;
    }
    for (std::size_t i = 0; i < n; ++i) {
        const int parent = model.nodes[i].parent_index;
        if (parent >= 0 && static_cast<std::size_t>(parent) < n) {
            rest[i] = rest[parent] * model.nodes[i].local_transform;
        }
    }

    const int part_parent = part_parent_index(model);

    for (std::size_t i = 0; i < n; ++i) {
        const auto& node = model.nodes[i];
        if (node.name.empty()) continue;            // unnamed wrappers

        ModelPart p;
        p.name = node.name;
        const int parent = node.parent_index;
        if (parent >= 0 && static_cast<std::size_t>(parent) < n) {
            p.parent = model.nodes[parent].name;
        }
        p.candidate = (part_parent >= 0 && parent == part_parent);

        // Subtree bounds: a part's meshes hang off its __NDL child, so the
        // node's OWN meshes are not enough.
        glm::vec3 lo(std::numeric_limits<float>::max());
        glm::vec3 hi(std::numeric_limits<float>::lowest());
        for (std::size_t j = 0; j < n; ++j) {
            bool in_subtree = (j == i);
            for (int q = model.nodes[j].parent_index;
                 !in_subtree && q >= 0 && static_cast<std::size_t>(q) < n;
                 q = model.nodes[q].parent_index) {
                if (static_cast<std::size_t>(q) == i) in_subtree = true;
            }
            if (!in_subtree) continue;
            for (int mesh_idx : model.nodes[j].meshes) {
                if (mesh_idx < 0 ||
                    static_cast<std::size_t>(mesh_idx) >= model.meshes.size()) {
                    continue;
                }
                const auto& cpu = model.meshes[mesh_idx].cpu_data();
                if (!cpu.has_value()) continue;
                for (const auto& v : cpu->vertices) {
                    const glm::vec3 w(rest[j] * glm::vec4(v.position, 1.0f));
                    lo = glm::min(lo, w);
                    hi = glm::max(hi, w);
                    p.has_bounds = true;
                }
            }
        }
        if (p.has_bounds) { p.bounds_min = lo; p.bounds_max = hi; }
        out.push_back(std::move(p));
    }
    return out;
}

}  // namespace renderer
```

Add `model_parts.cc` to `native/src/renderer/CMakeLists.txt` beside `part_frame.cc`.

- [ ] **Step 5: Build and run the gtests**

Run: `cmake --build build -j && ctest --test-dir build -R ModelParts --output-on-failure`
Expected: 6 tests PASS.

- [ ] **Step 6: Add the Python binding**

In `native/src/host/host_bindings.cc`, add `#include <renderer/model_parts.h>`
and a binding modelled on the neighbouring `model_bounds` / `instance_node_world`
definitions (find them with `grep -n '"model_bounds"\|"instance_node_world"' native/src/host/host_bindings.cc`):

```cpp
    m.def("model_nodes",
          [](scenegraph::InstanceId id) {
              // SHIP units out: the SPV, PART_BOXES and hardpoint mounts all
              // work in ship units, and this is the only place the model-unit
              // geometry meets them. MODEL_TO_SHIP == BC_MODEL_SCALE == 0.01.
              constexpr float kModelToShip = 0.01f;
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr) return out;          // stale id -> empty
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return out;
              for (const auto& p : renderer::model_parts(*model)) {
                  if (!p.has_bounds) continue;          // no geometry, no part
                  py::dict d;
                  d["name"] = p.name;
                  d["parent"] = p.parent;
                  d["candidate"] = p.candidate;
                  d["bounds_min"] = py::make_tuple(p.bounds_min.x * kModelToShip,
                                                   p.bounds_min.y * kModelToShip,
                                                   p.bounds_min.z * kModelToShip);
                  d["bounds_max"] = py::make_tuple(p.bounds_max.x * kModelToShip,
                                                   p.bounds_max.y * kModelToShip,
                                                   p.bounds_max.z * kModelToShip);
                  out.append(std::move(d));
              }
              return out;
          },
          py::arg("instance_id"));
```

Match the surrounding bindings' exact idioms for `py::` usage, `g_world.get`
and `resolve_model` — copy their form rather than inventing one.

- [ ] **Step 7: Expose it through the facade and its test double**

`engine/host_io.py` keeps an explicit name table (see its `"world_to_body",
"damage_decal_add", "hull_carve_add"` list around line 49) — add `"model_nodes"`
to it and add a passthrough alongside the other wrappers. Then find the test
double that mirrors the host surface (`grep -rn "hull_carve_add" tests/ | grep -i "stub\|double\|fake"`)
and add `model_nodes` there returning `[]`.

⚠️ A binding present natively but absent from the facade's name table is how a
feature has shipped inert here before. Add both.

- [ ] **Step 8: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 9: Commit**

```bash
git add native/src/renderer/include/renderer/model_parts.h native/src/renderer/model_parts.cc native/src/renderer/CMakeLists.txt native/tests/renderer/model_parts_test.cc native/tests/renderer/CMakeLists.txt native/src/host/host_bindings.cc engine/host_io.py
git commit -m "feat(spv): model_nodes -- enumerate parts and derive their bounds

Part candidates are the children of Scene Root, measured on the real
BirdOfPrey.nif. Bounds cover a node's whole subtree, because a part
carries no meshes of its own -- they hang off an interposed
__NDL_MultiMtl_Node. No NIF reader change: the 'Top Level Object' label
is stream framing, parsed and discarded.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The `ArticulatedPartProperty` template and a create-capable writer

**Files:**
- Create: `engine/appc/articulated_part.py`
- Modify: `engine/appc/hardpoint_override_writer.py` (find-or-create verb)
- Test: `tests/unit/test_articulated_part.py` (create)

**Interfaces:**
- Produces:
  - `ArticulatedPartProperty` with `SetPivot(x,y,z)`, `SetAxis(x,y,z)`,
    `SetStateAngle(state, deg)`, `SetDetachFraction(f)`, `GetName()`, and
    readers `pivot`, `axis`, `angle_for(state)`, `detach_fraction`.
  - `ArticulatedPartProperty_Create(name)` — registered onto `App`.
  - `parts_for_leaf(leaf) -> tuple[ArticulatedPartProperty, ...]`.
  - Writer verb: an edit tuple `(name, "__part__", calls)` where `calls` is a
    list of `(setter, args)`, emitted as a find-or-create block.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_articulated_part.py`:

```python
"""An articulated part is a BC property template like any other.

That shape is not incidental: a hardpoint file is nothing but
`X = App.Something_Create(name); X.SetFoo(...); RegisterLocalTemplate(X)`,
and it is exactly what hardpoint_overrides.py already replays. Choosing it
means a modded ship can eventually carry its own rig in its own hardpoint
file, with no second format. See spec section 2.2.
"""
import pytest

from engine.appc import articulated_part as ap

STATES = ("cruise", "yellow", "red", "warp")


def test_the_name_IS_the_node_name():
    """One string, not two. It is the template name AND the NIF node name,
    and the same key find() already uses."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.GetName() == "left wing"


def test_an_unset_state_angle_is_zero():
    """Zero is the NIF pose, so an unauthored state means 'as modelled'
    rather than an error."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    for s in STATES:
        assert p.angle_for(s) == 0.0


def test_state_angles_round_trip():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetStateAngle("cruise", 45.0)
    p.SetStateAngle("red", 0.0)
    assert p.angle_for("cruise") == 45.0
    assert p.angle_for("red") == 0.0
    assert p.angle_for("warp") == 0.0


def test_an_unknown_state_is_rejected():
    """A typo must not silently become a part that never moves."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    with pytest.raises(ValueError):
        p.SetStateAngle("REd", 45.0)


def test_detach_fraction_defaults_to_NOT_detachable():
    """Absent means 'does not come off', never 'comes off at 0.0'."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.detach_fraction is None
    p.SetDetachFraction(0.20)
    assert p.detach_fraction == 0.20


def test_a_static_detachable_part_needs_no_extra_concept():
    """All angles zero plus a detach fraction is a breakable panel -- the
    BoP's 'head'. It must be expressible without a separate flag."""
    p = ap.ArticulatedPartProperty_Create("head")
    p.SetDetachFraction(0.20)
    assert all(p.angle_for(s) == 0.0 for s in STATES)
    assert p.detach_fraction == 0.20


def test_pivot_and_axis_round_trip():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetPivot(-0.16, 0.0, 0.05)
    p.SetAxis(0.0, 1.0, 0.0)
    assert p.pivot == (-0.16, 0.0, 0.05)
    assert p.axis == (0.0, 1.0, 0.0)
```

Create `tests/unit/test_override_writer_create.py`:

```python
"""The writer can register a template BC never had.

Until now it could only MODIFY templates the stock hardpoint file already
registered: `find("left wing")` returns None for a template that does not
exist, and the override block is skipped. An articulated part is new, so
without this the whole feature writes files that do nothing.
"""
from engine.appc import hardpoint_override_writer as w


def test_a_part_edit_emits_a_find_or_CREATE_block():
    models = w.read_models(None) if False else {}
    w.set_part(models, "birdofprey", "left wing", [
        ("SetPivot", (-0.16, 0.0, 0.05)),
        ("SetStateAngle", ("cruise", 45.0)),
        ("SetDetachFraction", (0.20,)),
    ])
    text = w.emit(models)
    assert "left wing" in text
    assert "SetStateAngle" in text
    assert "ArticulatedPartProperty_Create" in text, (
        "the block must be able to CREATE the template, not only find it")


def test_the_emitted_file_is_valid_python():
    """emit() already ast.parses its output; a part block must not break that."""
    import ast
    models = {}
    w.set_part(models, "birdofprey", "left wing",
               [("SetStateAngle", ("cruise", 45.0))])
    ast.parse(w.emit(models))


def test_a_part_edit_round_trips_through_read_models():
    """read_models recovers a ship's model by EXECUTING its function against a
    recorder. A create-verb block has no `find` to record, so the recorder
    needs its own hook -- without this, saving twice would drop every part."""
    models = {}
    w.set_part(models, "birdofprey", "left wing",
               [("SetStateAngle", ("cruise", 45.0))])
    text = w.emit(models)
    again = w.read_models_from_source(text)
    assert "left wing" in again.get("birdofprey", {}).get("__parts__", {})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_articulated_part.py tests/unit/test_override_writer_create.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.appc.articulated_part'`
and `AttributeError: module ... has no attribute 'set_part'`.

- [ ] **Step 3: Write `engine/appc/articulated_part.py`**

```python
"""The ArticulatedPartProperty template — a ship part that moves or comes off.

A BC property template like any other, because a hardpoint file is nothing but
`X = App.Something_Create(name); X.SetFoo(...); RegisterLocalTemplate(X)`.
Choosing that shape means a modded ship can carry its own rig in its own
hardpoint file with no second format, and that `hardpoint_overrides.py` can
carry it for stock ships with no new file. See spec section 2.2.

The template NAME is the NIF node name. One string, and the same key `find()`
already uses. A node named identically to a subsystem would collide in
FindByName; no stock ship does this. Accepted, not designed around.
"""

STATES = ("cruise", "yellow", "red", "warp")


class ArticulatedPartProperty:
    def __init__(self, name):
        self._name = str(name)
        self._pivot = (0.0, 0.0, 0.0)
        self._axis = (0.0, 1.0, 0.0)     # ship-forward
        self._angles = {}
        self._detach = None

    # ---- BC-style setters (what a hardpoint file calls) ----------------
    def SetPivot(self, x, y, z):
        self._pivot = (float(x), float(y), float(z))

    def SetAxis(self, x, y, z):
        self._axis = (float(x), float(y), float(z))

    def SetStateAngle(self, state, degrees):
        if state not in STATES:
            raise ValueError(
                "unknown articulation state %r; expected one of %r"
                % (state, STATES))
        self._angles[state] = float(degrees)

    def SetDetachFraction(self, fraction):
        self._detach = float(fraction)

    def GetName(self):
        return self._name

    # ---- readers -------------------------------------------------------
    @property
    def pivot(self):
        return self._pivot

    @property
    def axis(self):
        return self._axis

    @property
    def detach_fraction(self):
        """Fraction of MAX hull that shears this part, or None for a part that
        does not come off. None, never 0.0 -- absent must not read as
        'detaches instantly'."""
        return self._detach

    def angle_for(self, state):
        """Degrees about the hinge in `state`. Unset is 0.0: the NIF pose,
        i.e. 'as modelled', which is the right default for a part whose
        author has not considered that state."""
        return self._angles.get(state, 0.0)


def ArticulatedPartProperty_Create(name):
    """Factory, matching BC's `App.<Type>_Create` convention."""
    return ArticulatedPartProperty(name)
```

Register the factory and the class onto the `App` shim wherever the other
`*_Create` factories are registered — find the pattern with
`grep -rn "_Create" App.py engine/appc/__init__.py | head`. Follow that
pattern exactly; do not invent a second registration mechanism.

- [ ] **Step 4: Add `set_part` and the recorder hook to the writer**

Read `engine/appc/hardpoint_override_writer.py` first — it recovers a ship's
model by EXECUTING its function against a recording `find` (`_Recorder`,
~line 32-60), and emits with `_emit_function` (~line 128-140).

Add a `"__parts__"` section to a ship's model dict, a `set_part(models, leaf,
name, calls)` mutator mirroring `set_region`, and emission of a guarded
create block:

```python
def _emit_part(lines, name, calls):
    """Emit a find-or-CREATE block for one articulated part.

    The App-level hasattr guard (not the usual per-instance one) is required
    because stock BC has never heard of this property type: the guard must sit
    on App, since there is no instance to guard on until Create succeeds. The
    guard is Python-1.5-safe -- hasattr is a two-argument builtin -- and so is
    everything inside it. See spec section 2.3.

    hardpoint_overrides.py does not strictly need the guard (stbc.exe never
    loads it), but emitting the identical block in both homes means the SPV has
    exactly one part emitter to maintain, and the text can be lifted straight
    into a mod's hardpoint file.
    """
    var = _ident_for(name)
    lines.append('    if hasattr(App, "ArticulatedPartProperty_Create"):')
    lines.append('        %s = App.ArticulatedPartProperty_Create(%r)' % (var, name))
    for setter, args in calls:
        lines.append('        %s.%s(%s)' % (var, setter, _fmt_args(args)))
    lines.append('        App.g_kModelPropertyManager.RegisterLocalTemplate(%s)' % var)
```

Reuse the module's existing argument-formatting and identifier-sanitising
helpers rather than writing new ones; if none exist, add `_fmt_args` and
`_ident_for` beside the other private helpers. `emit()` must keep its closing
`ast.parse(text)` validation.

For `read_models` to recover parts, the recorder needs to see the create call.
Add a `read_models_from_source(text)` entry point used by the tests, and make
the execution environment supply an `App` object whose
`ArticulatedPartProperty_Create` records into `models[leaf]["__parts__"]`.

⚠️ `read_models` executing a file that now imports/uses `App` must not require
the real `App` module — supply a recording stand-in, exactly as the existing
`_Recorder` stands in for a live property.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_articulated_part.py tests/unit/test_override_writer_create.py -v`
Expected: 10 passed.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add engine/appc/articulated_part.py engine/appc/hardpoint_override_writer.py tests/unit/test_articulated_part.py tests/unit/test_override_writer_create.py
git commit -m "feat(articulation): ArticulatedPartProperty, and a writer that can create

A part is a BC property template like any other, so the same text works in
hardpoint_overrides.py today and in a mod's own hardpoint file later. The
writer gains a find-or-CREATE verb, since stock BC never registered this
template and find() alone would silently skip every part.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Four states, per-part angles, warp wins

**Files:**
- Modify: `engine/appc/articulation.py` (state machine, per-part angles),
  `engine/dev_keybindings.py:284-308` (`K` becomes a state cycle)
- Test: `tests/unit/test_articulation_states.py` (create)

**Interfaces:**
- Consumes: `articulated_part.STATES`, `parts_for_leaf(leaf)`
- Produces:
  - `articulation.state_for(ship) -> str` — one of `STATES`
  - `articulation.angle_for_part(ship, part) -> float` (degrees, current)
  - `articulation.tick_ship(ship, dt)` — eases every part toward its target
  - `articulation.rotation_for(part, angle_deg)` — **signature changes** from
    `(part, deflection)` to `(part, angle_deg)`
  - `articulation.set_dev_override(state | None)` — now a state name

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_articulation_states.py`:

```python
"""Four alert states, and warp outranks all of them.

Warp wins because wing position is a FLIGHT configuration -- warp entry should
visibly re-configure the ship. NPCs never show 'yellow': BC never takes an NPC
off Red Alert (measured; stbc-oracle bible s13 N2), which is why NPC
articulation keys off 'has a target' rather than off alert level.
"""
import pytest

from engine.appc import articulation


class _Part:
    def __init__(self, angles):
        self._angles = angles
        self.pivot = (0.0, 0.0, 0.0)
        self.axis = (0.0, 1.0, 0.0)

    def GetName(self):
        return "left wing"

    def angle_for(self, state):
        return self._angles.get(state, 0.0)


class _Ship:
    def __init__(self, *, player=False, alert=0, warping=False, target=None):
        self._player = player
        self._alert = alert
        self._warping = warping
        self._target = target

    def GetAlertLevel(self):
        return self._alert

    def GetTarget(self):
        return self._target


def test_warp_beats_red_alert(monkeypatch):
    """THE precedence rule. A ship running under fire is still in its travel
    shape."""
    import App
    ship = _Ship(player=True, alert=App.ShipClass.RED_ALERT, warping=True)
    monkeypatch.setattr(articulation, "_is_player", lambda s: True)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: s._warping)
    assert articulation.state_for(ship) == "warp"


def test_player_states_follow_alert_level(monkeypatch):
    import App
    monkeypatch.setattr(articulation, "_is_player", lambda s: True)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: False)
    assert articulation.state_for(
        _Ship(alert=App.ShipClass.RED_ALERT)) == "red"
    assert articulation.state_for(
        _Ship(alert=App.ShipClass.YELLOW_ALERT)) == "yellow"
    assert articulation.state_for(_Ship(alert=0)) == "cruise"


def test_an_npc_uses_red_when_it_has_a_target(monkeypatch):
    """NPCs never leave Red Alert in BC, so alert level carries no signal for
    them. 'Has a target' is the measured proxy."""
    monkeypatch.setattr(articulation, "_is_player", lambda s: False)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: False)
    assert articulation.state_for(_Ship(target=object())) == "red"
    assert articulation.state_for(_Ship(target=None)) == "cruise"


def test_an_npc_NEVER_shows_yellow(monkeypatch):
    """Pinned deliberately. Inventing NPC alert levels was rejected."""
    import App
    monkeypatch.setattr(articulation, "_is_player", lambda s: False)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: False)
    for target in (object(), None):
        assert articulation.state_for(
            _Ship(alert=App.ShipClass.YELLOW_ALERT, target=target)) != "yellow"


def test_a_part_eases_toward_its_target_angle():
    part = _Part({"cruise": 45.0, "red": 0.0})
    a = articulation.ease_angle(0.0, 45.0, part_range=45.0, dt=1.0)
    assert 0.0 < a < 45.0
    assert articulation.ease_angle(a, 45.0, part_range=45.0, dt=10.0) == 45.0


def test_a_full_swing_takes_TRAVEL_SECONDS():
    """Each part eases at its own range / TRAVEL_SECONDS, so parts moving
    between the same two states stay in sync."""
    a = articulation.ease_angle(0.0, 45.0, part_range=45.0,
                                dt=articulation.TRAVEL_SECONDS)
    assert a == pytest.approx(45.0)


def test_an_interrupted_transition_just_changes_target():
    """No captured start pose, no from/to pair -- the part keeps easing from
    wherever it is. This is the case that makes per-part angles simpler than a
    normalised t."""
    a = articulation.ease_angle(0.0, 45.0, part_range=45.0, dt=1.0)
    back = articulation.ease_angle(a, 0.0, part_range=45.0, dt=1.0)
    assert back < a


def test_rotation_for_takes_DEGREES_not_a_deflection():
    """Signature change. rotation_for(part, 45.0) must mean 45 degrees, not
    45x the authored angle -- the old signature took a 0..1 scalar."""
    import math
    part = _Part({"cruise": 45.0})
    _pivot, _axis, theta = articulation.rotation_for(part, 45.0)
    assert theta == pytest.approx(math.radians(45.0))
```

- [ ] **Step 2: Run and watch fail**

Run: `uv run pytest tests/unit/test_articulation_states.py -v`
Expected: `AttributeError: module 'engine.appc.articulation' has no attribute 'state_for'`.

- [ ] **Step 3: Implement the state machine**

In `engine/appc/articulation.py`:

```python
def _is_warping(ship) -> bool:
    """Whether `ship` is at warp. Best-effort: a prop or test double that
    cannot answer is not warping."""
    from engine.appc import warp
    try:
        return bool(warp.is_at_warp(ship))
    except Exception:  # noqa: BLE001
        return False


def state_for(ship) -> str:
    """Which articulation state `ship` is in.

    Warp outranks alert level: wing position is a FLIGHT configuration, so
    warp entry visibly re-configures the ship. See spec section 2.4.

    NPCs key off "has a target" rather than alert level, and therefore never
    show "yellow" -- BC never takes an NPC off Red Alert, so its alert level
    carries no signal. Measured, not assumed (stbc-oracle bible s13 N2).
    """
    if _is_warping(ship):
        return "warp"
    if _is_player(ship):
        import App
        level = ship.GetAlertLevel()
        if level == App.ShipClass.RED_ALERT:
            return "red"
        if level == App.ShipClass.YELLOW_ALERT:
            return "yellow"
        return "cruise"
    getter = getattr(ship, "GetTarget", None)
    if getter is None:
        return "cruise"
    try:
        return "red" if getter() else "cruise"
    except Exception:  # noqa: BLE001
        return "cruise"


def ease_angle(current: float, target: float, *, part_range: float,
               dt: float) -> float:
    """Move `current` toward `target` at `part_range / TRAVEL_SECONDS` per
    second, clamped so it never overshoots.

    Rate is proportional to the part's OWN range, so a part swinging its whole
    travel always takes TRAVEL_SECONDS and parts moving between the same two
    states arrive together. Interrupting a transition needs no special case:
    the target changes and the part keeps easing from wherever it is.
    """
    if part_range <= 0.0 or TRAVEL_SECONDS <= 0.0:
        return target
    step = abs(part_range) * (float(dt) / TRAVEL_SECONDS)
    delta = target - current
    if abs(delta) <= step:
        return target
    return current + (step if delta > 0 else -step)
```

Change `rotation_for` to take degrees:

```python
def rotation_for(part, angle_deg: float):
    """Return (pivot, unit_axis, theta_radians) for `part` at `angle_deg`.

    Takes DEGREES, not a 0..1 deflection. Four independent per-state angles
    cannot be expressed as one scalar times an authored maximum.
    """
    ax, ay, az = part.axis
    n = math.sqrt(ax * ax + ay * ay + az * az)
    unit = (0.0, 1.0, 0.0) if n <= 0.0 else (ax / n, ay / n, az / n)
    return part.pivot, unit, math.radians(float(angle_deg))
```

Store current angles per ship (`ship._articulation_angles`, a dict keyed by part
name) and rewrite `tick_ship` to ease each part toward `part.angle_for(state_for(ship))`.
Keep `part_transform_point` working by reading the current angle for the part it
resolves rather than a deflection.

- [ ] **Step 4: Update the `K` dev keybinding**

In `engine/dev_keybindings.py`, replace the 0/0.5/1 cycle with a state cycle:

```python
    def _cycle_wing_state() -> None:
        from engine.appc import articulation
        from engine.appc.articulated_part import STATES
        order = (None,) + STATES
        cur = articulation.dev_override()
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else None
        articulation.set_dev_override(nxt)
        print("[articulation] wing state override: %s"
              % ("follow" if nxt is None else nxt))
```

Update the comment block above it: the 0.5 stop is gone because the authored
states are now the interesting poses, and mid-travel is still reachable by
switching states and watching the ease.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_articulation_states.py tests/unit/test_articulation.py -v`
Expected: PASS. Existing articulation tests that assert the OLD `rotation_for(part, deflection)`
signature must be updated to degrees in this task — that is the signature change's
own responsibility, not a later task's.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add engine/appc/articulation.py engine/dev_keybindings.py tests/unit/test_articulation_states.py tests/unit/test_articulation.py
git commit -m "feat(articulation): four states, per-part angles, warp wins

Replaces the single 0..1 deflection with a current angle per part, eased
toward the target state's angle. Warp outranks alert level because wing
position is a flight configuration. NPCs never show yellow -- BC never
takes them off Red Alert, so alert level carries no signal for them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Migrate the Bird of Prey and retire the hardcoded dicts

**Files:**
- Modify: `engine/appc/articulation.py` (drop `_RIGS`, `PART_BOXES`, `DETACHABLE`),
  `engine/appc/hardpoint_overrides.py` (add the migrated part templates),
  `engine/appc/part_severance.py` (read bounds from `model_nodes`)
- Test: `tests/unit/test_articulation_migration.py` (create)

**Interfaces:**
- Consumes: `articulated_part.parts_for_leaf(leaf)`, `host_io.model_nodes(iid)`
- Produces: `articulation.part_boxes_for(leaf, iid)` now derives from the model;
  `articulation.detachable_for(leaf)` reads `detach_fraction` off the templates.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_articulation_migration.py`:

```python
"""The Bird of Prey's authored numbers survive the move to templates.

Migration, not rewrite: identical pivots, axes and detach fraction, so day-one
behaviour is verifiable rather than merely plausible. The ONE deliberate change
is that bounding boxes now come from the mesh (spec section 2.5).
"""
from engine.appc import articulation
from engine.appc.articulated_part import STATES


def test_the_bop_rig_survives_the_move():
    parts = {p.GetName(): p for p in articulation.parts_for_leaf("birdofprey")}
    assert set(parts) >= {"left wing", "left wing01"}

    port, star = parts["left wing"], parts["left wing01"]
    assert port.pivot == (-0.16, 0.0, 0.05)
    assert star.pivot == (0.16, 0.0, 0.05)
    assert port.axis == (0.0, 1.0, 0.0)
    assert star.axis == (0.0, 1.0, 0.0)


def test_the_wing_angle_SIGNS_are_preserved():
    """REGRESSION GUARD. The signs were swapped once during the spike: +45 on
    the starboard wing SANK the tip instead of raising it, and only a test
    against the real tip coordinate caught it."""
    parts = {p.GetName(): p for p in articulation.parts_for_leaf("birdofprey")}
    assert parts["left wing"].angle_for("cruise") == 45.0
    assert parts["left wing01"].angle_for("cruise") == -45.0


def test_red_alert_is_the_NIF_pose():
    """Zero rotation, because the BoP's NIF is modelled wings-down. This is
    what makes Red the anchor for this ship -- no declaration needed."""
    for p in articulation.parts_for_leaf("birdofprey"):
        assert p.angle_for("red") == 0.0


def test_both_wings_shear_at_twenty_percent():
    parts = {p.GetName(): p for p in articulation.parts_for_leaf("birdofprey")}
    assert parts["left wing"].detach_fraction == 0.20
    assert parts["left wing01"].detach_fraction == 0.20


def test_the_hardcoded_dicts_are_GONE():
    """The whole point of the migration. Leaving them would give two sources
    of truth that silently disagree."""
    assert not hasattr(articulation, "_RIGS")
    assert not hasattr(articulation, "PART_BOXES")
    assert not hasattr(articulation, "DETACHABLE")
```

- [ ] **Step 2: Run and watch fail**

Run: `uv run pytest tests/unit/test_articulation_migration.py -v`
Expected: failures on `parts_for_leaf` and on the three `hasattr` assertions.

- [ ] **Step 3: Write the BoP templates into `hardpoint_overrides.py`**

Add a `_birdofprey` part block emitting exactly the migrated values. Generate it
through the Task 3 writer (`w.set_part(...)` then `w.emit(...)`) rather than
hand-editing the file — it is machine-owned, and hand-editing is what its header
forbids. `warp` is deliberately left unauthored (angle 0); it is the first thing
the new SPV surface will author.

- [ ] **Step 4: Retire the dicts**

Delete `_RIGS`, `PART_BOXES` and `DETACHABLE` from `engine/appc/articulation.py`.
Replace their readers:

- `rig_for(leaf)` / `parts_for_ship(ship)` → `articulated_part.parts_for_leaf(leaf)`
- `detachable_for(leaf)` → `{p.GetName(): p.detach_fraction
  for p in parts_for_leaf(leaf) if p.detach_fraction is not None}`
- `part_boxes_for(leaf)` → derive from `host_io.model_nodes(iid)`, cached per
  instance at first use. It needs an instance id; thread one through from the
  caller in `part_severance`, and fall back to an empty dict when there is none
  (headless tests, an unrealised ship) so attribution degrades to "unattributed"
  rather than raising.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_articulation_migration.py tests/unit/test_part_severance.py tests/unit/test_hull_bounds_parts.py -v`
Expected: PASS. Tests that referenced the retired dicts are updated here.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add engine/appc/articulation.py engine/appc/hardpoint_overrides.py engine/appc/part_severance.py tests/unit/test_articulation_migration.py
git commit -m "refactor(articulation): retire the hardcoded rig dicts

_RIGS, PART_BOXES and DETACHABLE become lookups against registered
templates; bounds derive from mesh geometry. The BoP's numbers migrate
verbatim, so day-one behaviour is verifiable. Bounds are the one
deliberate change: tighter than the hand-drawn boxes, so attribution
sharpens and severance may need re-tuning live.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The Model Parts pane

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (part list state + selection),
  `engine/ui/ship_property_viewer_panel.py` (payload + actions),
  `native/assets/ui-cef/index.html`, `native/assets/ui-cef/js/ship_property_viewer.js`,
  `native/assets/ui-cef/css/hello.css`
- Test: `tests/unit/test_spv_model_parts_pane.py` (create)

**Interfaces:**
- Consumes: `host_io.model_nodes(iid)`
- Produces: payload key `"model_parts"` — `{"expanded": bool, "selected": str|None,
  "rows": [{"name", "candidate", "detachable", "fraction", "angles": {state: deg}}]}`;
  actions `model_parts/toggle`, `model_parts/select:<name>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_spv_model_parts_pane.py`:

```python
"""The Model Parts pane: collapsed by default, 25% when open.

It lists part CANDIDATES -- the children of Scene Root -- because a real hull's
node list is mostly __NDL_MultiMtl_Node exporter plumbing. A 'show all' toggle
is the escape hatch for a hull whose hierarchy does not fit the rule.
"""
from engine.ui import ship_property_viewer as spv


def _nodes():
    return [
        {"name": "head", "parent": "Scene Root", "candidate": True,
         "bounds_min": (-0.1, 0.13, -0.08), "bounds_max": (0.1, 0.9, 0.07)},
        {"name": "left wing", "parent": "Scene Root", "candidate": True,
         "bounds_min": (-1.02, -0.67, -0.71), "bounds_max": (-0.12, 0.53, 0.18)},
        {"name": "__NDL_MultiMtl_Node", "parent": "left wing", "candidate": False,
         "bounds_min": (-1.02, -0.67, -0.71), "bounds_max": (-0.12, 0.53, 0.18)},
    ]


def test_the_pane_starts_collapsed():
    """Mark's requirement: the header is visible, the list is not."""
    assert spv.model_parts_expanded() is False


def test_only_candidates_are_listed_by_default():
    rows = spv.model_part_rows(_nodes(), show_all=False)
    names = [r["name"] for r in rows]
    assert names == ["head", "left wing"]
    assert "__NDL_MultiMtl_Node" not in names, (
        "exporter plumbing must not reach the author")


def test_show_all_is_the_escape_hatch():
    rows = spv.model_part_rows(_nodes(), show_all=True)
    assert "__NDL_MultiMtl_Node" in [r["name"] for r in rows]


def test_selecting_a_part_exposes_its_derived_box():
    """The box is what severance will actually test against; the author must
    see it before committing to a detach fraction."""
    spv.select_model_part("left wing", _nodes())
    box = spv.selected_part_box()
    assert box == ((-1.02, -0.67, -0.71), (-0.12, 0.53, 0.18))


def test_selection_survives_a_list_refresh():
    spv.select_model_part("left wing", _nodes())
    spv.model_part_rows(_nodes(), show_all=False)
    assert spv.selected_model_part() == "left wing"


def test_selecting_a_vanished_part_clears_rather_than_raises():
    """A mission swap can replace the model under the panel."""
    spv.select_model_part("left wing", _nodes())
    spv.model_part_rows([], show_all=False)
    assert spv.selected_model_part() is None
```

- [ ] **Step 2: Run and watch fail**

Run: `uv run pytest tests/unit/test_spv_model_parts_pane.py -v`
Expected: `AttributeError: module 'engine.ui.ship_property_viewer' has no attribute 'model_parts_expanded'`.

- [ ] **Step 3: Implement the Python side**

Add the state and helpers to `engine/ui/ship_property_viewer.py`, following the
module's existing module-level-state style (the same shape as the existing
selection and toggle state). Add the payload key and the two actions to
`ship_property_viewer_panel.py`, following the five-step wiring pattern the
panel already uses: payload key → DOM repaint → `dauntlessEvent` → a
`_dispatch_event_inner` branch → `self._last_pushed = None`.

- [ ] **Step 4: Implement the CEF side**

In `native/assets/ui-cef/index.html`, add the pane beneath `#spv-syslist`:

```html
<div id="spv-parts">
  <div id="spv-parts-header" onclick="dauntlessEvent('ship-property-viewer/model_parts/toggle')">
    Model Parts
  </div>
  <div id="spv-parts-body"></div>
</div>
```

In `css/hello.css`, `#spv-parts-body` is `display:none` when collapsed and
`height: 25%` when the root carries an `expanded` class. In
`js/ship_property_viewer.js`, read `data.model_parts` inside the existing
`window.setShipPropertyViewer` and repaint `#spv-parts-body`, mirroring
`renderSPVSubsystemList`'s row rendering.

- [ ] **Step 5: Run the tests and the gate**

Run: `uv run pytest tests/unit/test_spv_model_parts_pane.py -v && scripts/check_tests.sh`
Expected: tests pass; gate `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/ui/ship_property_viewer_panel.py native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/css/hello.css tests/unit/test_spv_model_parts_pane.py
git commit -m "feat(spv): Model Parts pane

Collapsed header beneath the subsystem tree, 25% of the vertical when
expanded. Lists part candidates -- Scene Root's children -- with a show-all
escape hatch, and draws the selected part's derived bounds.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Per-part controls and the safety lock

**Files:**
- Modify: `engine/ui/ship_property_viewer.py`, `engine/ui/ship_property_viewer_panel.py`,
  `native/assets/ui-cef/index.html`, `native/assets/ui-cef/js/ship_property_viewer.js`
- Test: `tests/unit/test_spv_part_controls.py` (create)

**Interfaces:**
- Consumes: the Task 6 selection state, `articulated_part.STATES`, the existing
  gizmo suite (`_active_transform_target`, `_target_pos_of`)
- Produces: `("part", name)` as a fourth transform target kind; actions
  `part/set_detach:<json>`, `part/set_angle:<json>`, `part/preview:<state>`;
  payload key `"part_preview"` (`None` or a state name); part edits in the Save
  list as `(name, "__part__", calls)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_spv_part_controls.py`:

```python
"""Authoring a part, and the lock that stops you authoring a mount through
the wrong pose.

The lock is the feature. Its failure mode without one is silent and invisible:
a wingtip cannon authored ~0.9 ship units out, discovered only in combat. A
banner relies on the author reading it.
"""
import pytest

from engine.ui import ship_property_viewer as spv


def test_previewing_the_anchor_state_leaves_editing_ENABLED():
    """Red is the BoP's NIF pose, so previewing it changes nothing and must
    not lock anything."""
    spv.preview_part_state("red", angles={"red": 0.0, "cruise": 45.0})
    assert spv.mount_editing_enabled() is True


def test_previewing_an_ARTICULATED_state_DISABLES_mount_editing():
    """THE POINT."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    assert spv.mount_editing_enabled() is False


def test_the_lock_names_its_reason():
    """A disabled control with no explanation reads as a bug."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    assert spv.mount_editing_reason()


def test_clearing_the_preview_restores_editing():
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    spv.preview_part_state(None, angles={})
    assert spv.mount_editing_enabled() is True


def test_angle_editing_stays_available_while_locked():
    """You must be able to tune the very angle you are looking at."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    assert spv.angle_editing_enabled() is True


def test_a_state_whose_angles_are_all_zero_is_not_a_lock():
    """'Articulated' means a non-zero angle, not 'a state was selected'. A
    ship whose cruise pose equals its NIF pose must stay editable."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 0.0})
    assert spv.mount_editing_enabled() is True


def test_part_edits_reach_the_save_list():
    edits = spv.part_save_edits({
        "left wing": {"pivot": (-0.16, 0.0, 0.05), "axis": (0.0, 1.0, 0.0),
                      "angles": {"cruise": 45.0}, "fraction": 0.20},
    })
    assert edits
    name, verb, calls = edits[0]
    assert name == "left wing"
    assert verb == "__part__"
    setters = [c[0] for c in calls]
    assert "SetPivot" in setters and "SetStateAngle" in setters
    assert "SetDetachFraction" in setters


def test_a_non_detachable_part_emits_NO_detach_call():
    """Absent must stay absent -- emitting SetDetachFraction(0.0) would make
    every part shear instantly."""
    edits = spv.part_save_edits({
        "head": {"pivot": (0.0, 0.0, 0.0), "axis": (0.0, 1.0, 0.0),
                 "angles": {}, "fraction": None},
    })
    calls = edits[0][2]
    assert all(c[0] != "SetDetachFraction" for c in calls)
```

- [ ] **Step 2: Run and watch fail**

Run: `uv run pytest tests/unit/test_spv_part_controls.py -v`
Expected: `AttributeError: ... has no attribute 'preview_part_state'`.

- [ ] **Step 3: Implement the controls and the lock**

Add the preview state, the lock predicates and `part_save_edits` to
`ship_property_viewer.py`. Wire the panel: a `("part", name)` transform target
in `_active_transform_target` / `_target_pos_of` so the existing Transform gizmo
places the pivot and the Rotate tool sets the axis; the four angle rows; the
detachable checkbox and fraction field; and the Preview buttons.

While `mount_editing_enabled()` is False, the panel must refuse subsystem, light
and emitter edits — gate them in `_dispatch_event_inner` so a stale click cannot
slip through, not only by greying the DOM.

Add the part edits to the Save list beside the existing four kinds
(`ship_property_viewer_panel.py:2421-2428`).

- [ ] **Step 4: CEF controls**

Add the per-part control block to `#spv-parts-body` in
`js/ship_property_viewer.js` — four angle rows with Preview buttons, the
detachable checkbox and fraction field — following the established
`dauntlessEvent('ship-property-viewer/<action>:<json>')` pattern. Render the
lock reason in the panel when `data.part_preview` names a non-anchor state.

- [ ] **Step 5: Run the tests and the gate**

Run: `uv run pytest tests/unit/test_spv_part_controls.py -v && scripts/check_tests.sh`
Expected: tests pass; gate `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/ui/ship_property_viewer_panel.py native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js tests/unit/test_spv_part_controls.py
git commit -m "feat(spv): author a part's hinge, angles and detachability

Pivot and axis reuse the Transform and Rotate gizmos. Previewing a state
whose angles are not all zero disables mount editing with a stated
reason -- a mount authored through an articulated pose is silently wrong
by ~0.9 ship units at a BoP wingtip.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (Mark, after Task 7)

The gate cannot see any of this. Run `./build/dauntless --developer`,
QuickBattle as a Bird of Prey, open the Ship Property Viewer.

1. **The anchor pose (Task 1, verifiable on its own).** Open the SPV at green
   alert. The wings must be DOWN. Before this, they stayed wherever the live
   pose had them.
2. **Model Parts lists four.** `head`, `left wing`, `left wing01`, `birdofprey` —
   no `__NDL_MultiMtl_Node`. Selecting one draws its box on the hull.
3. **The lock.** Preview Cruising: the wings rise and mount editing greys out
   with a reason. Preview Red: editing returns.
4. **Author a warp pose**, save, then warp. The wings must take the pose you
   authored, and it must outrank Red Alert if you warp under fire.
5. **Severance re-check — the known risk.** Derived bounds are tighter than the
   old hand-drawn ones, so wings accumulate damage faster. Shoot a wing off and
   judge whether 20% still feels right.
6. **Regression.** Fly a Galaxy: no Model Parts entries, everything else
   unchanged.
