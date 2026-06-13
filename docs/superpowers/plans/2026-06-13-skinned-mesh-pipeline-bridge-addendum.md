# SP1 Addendum — Skinned Rendering in the Bridge Pass

> Scope addition to SP1 (`2026-06-13-skinned-mesh-pipeline.md`), approved mid-branch.
> Makes the bridge pass capable of rendering skinned characters, lit by the bridge
> lighting, so the F7 dev preview works on the bridge. Authentic officer placement
> (placement-animation NIFs) remains SP3; this only adds the *capability* + a working
> preview. Must support an arbitrary number of skinned bridge instances, not one.

## Root cause this fixes
F7 spawned a `Pass::Space` character at a space coordinate. On the bridge: (1) the
bridge pass is static-only (no skinning), and (2) it `glClear`s and redraws only
`Pass::Bridge` instances, wiping the space pass's output. So the skinned preview was
inherently exterior-only. Plus placement was a fixed 6 GU from the player ship,
mis-framing the ~tens-of-GU character model.

## Design
- **Lighting:** bridge characters use the **bridge ambient** (`Lighting::ambient`), same
  as bridge geometry, via the existing `bridge.frag` (`light = max(u_ambient, u_emissive)`;
  with a white dark-map → `base × ambient`). No new fragment shader.
- **Shader pairing:** new `skinned_bridge.vert` = `skinned.vert`'s palette blend but
  outputting the varyings `bridge.frag` expects (`v_uv`, `v_uv1`). Characters have no
  UV1, so `v_uv1 = vec2(0)` and a white dark-map is bound (lm = 1).
- **Multi-instance:** the bridge skinned sub-pass loops every `Pass::Bridge` instance
  with a non-empty skeleton. No single-character assumptions in the renderer.

---

### Task A: skinned-bridge shader + pipeline + BridgePass skinned sub-pass

**Files:**
- Create: `native/src/renderer/shaders/skinned_bridge.vert`
- Modify: `native/src/renderer/CMakeLists.txt` (embed), `pipeline.{h,cc}` (`skinned_bridge_shader()`)
- Modify: `native/src/renderer/bridge_pass.cc` (+ its header if the skinned sub-pass needs pipeline access)
- Test: `native/tests/renderer/skinned_bridge_test.cc` (create; register in `tests/renderer/CMakeLists.txt`)

**A1. `skinned_bridge.vert`** — mirror `skinned.vert`'s palette blend, but match `bridge.vert`'s
attribute set (it also reads `layout(location = 6) in vec2 a_uv1;`) and `bridge.frag`'s inputs:

```glsl
#version 330 core
// Skinned vertex stage for bridge characters. Palette-blends like skinned.vert
// but outputs the varyings bridge.frag consumes (v_uv, v_uv1), so a skinned
// character is lit by the same base x ambient path as the bridge geometry.
layout(location = 0) in vec3 a_position;
layout(location = 2) in vec2 a_uv;
layout(location = 4) in ivec4 a_bone_indices;
layout(location = 5) in vec4  a_bone_weights;
layout(location = 6) in vec2 a_uv1;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_bones[128];   // size must equal renderer::kMaxBones (bone_palette.h)

out vec2 v_uv;
out vec2 v_uv1;

void main() {
    mat4 skin = a_bone_weights.x * u_bones[a_bone_indices.x]
              + a_bone_weights.y * u_bones[a_bone_indices.y]
              + a_bone_weights.z * u_bones[a_bone_indices.z]
              + a_bone_weights.w * u_bones[a_bone_indices.w];
    v_uv  = a_uv;
    v_uv1 = a_uv1;   // characters carry no UV1; a_uv1 is zero, dark-map is white
    gl_Position = u_proj * u_view * u_model * skin * vec4(a_position, 1.0);
}
```

**A2. Embed + pipeline.** Add `embed_shader(SHADER_SKINNED_BRIDGE_VS shaders/skinned_bridge.vert skinned_bridge_vs)`
to `CMakeLists.txt`. In `pipeline.cc`: `#include "embedded_skinned_bridge_vs.h"` and
`skinned_bridge_ = std::make_unique<Shader>(shader_src::skinned_bridge_vs, shader_src::bridge_fs);`.
In `pipeline.h`: accessor `Shader& skinned_bridge_shader() noexcept { return *skinned_bridge_; }` + member.
(Reconfigure with `cmake -B build -S .` so the new shader embeds.)

**A3. Exclude skinned models from the static walk.** In `bridge_pass.cc:walk_bridge_meshes`, after
`const assets::Model* m = lookup(inst.model_handle); if (!m) return;`, add:
`if (!m->skeleton.bones.empty()) return;` — skinned models are drawn by the skinned sub-pass only,
never the static base shader (which would draw them undeformed and double-draw).

**A4. Skinned sub-pass in `BridgePass::render`.** After the two static `walk_bridge_meshes` calls
(and `glEnable(GL_CULL_FACE)` — keep culling disabled or enabled consistently with the static pass;
characters can keep culling on), add a sub-pass that iterates skinned Bridge instances and draws each:

```cpp
    // ── Sub-pass C: skinned bridge characters ──────────────────────────────
    // Any Pass::Bridge instance carrying a skeleton is drawn here, lit by the
    // same bridge ambient as the geometry (bridge.frag, white dark-map). Bone
    // palette is bind-pose for now (SP1); SP2 supplies an animated pose.
    auto& skin_shader = pipeline.skinned_bridge_shader();
    skin_shader.use();
    skin_shader.set_mat4("u_view", camera.view_matrix());
    skin_shader.set_mat4("u_proj", camera.proj_matrix());
    skin_shader.set_vec3("u_ambient", lighting.ambient);
    skin_shader.set_int("u_base_color", 0);
    skin_shader.set_int("u_dark_map", 1);
    skin_shader.set_float("u_alpha_test_threshold", 0.5f);

    world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance& inst) {
            const assets::Model* m = lookup(inst.model_handle);
            if (!m || m->skeleton.bones.empty()) return;
            std::vector<glm::mat4> palette = build_bone_palette(m->skeleton, nullptr);
            skin_shader.set_mat4_array("u_bones", palette.data(),
                                       static_cast<int>(palette.size()));
            // World transform per node, same node-walk as walk_bridge_meshes.
            std::vector<glm::mat4> world_per_node(m->nodes.size(), glm::mat4(1.0f));
            if (!m->nodes.empty())
                world_per_node[m->root_node] =
                    inst.world * m->nodes[m->root_node].local_transform;
            for (std::size_t i = 0; i < m->nodes.size(); ++i) {
                const auto& node = m->nodes[i];
                if (node.parent_index >= 0)
                    world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
                for (int mesh_idx : node.meshes) {
                    const auto& mesh = m->meshes[mesh_idx];
                    const auto& mat = (mesh.material_index() >= 0
                        ? m->materials[mesh.material_index()] : assets::Material{});
                    draw_mesh(*m, mesh, mat, skin_shader, world_per_node[i], white, t);
                }
            }
        });
```

`draw_mesh` already sets `u_model`, binds base+dark textures, alpha-test, and draws the VAO
(the VAO carries the bone attributes at loc 4/5 that `skinned_bridge.vert` reads). Add
`#include "renderer/bone_palette.h"` to `bridge_pass.cc`. Note: `draw_mesh` sets
`u_alpha_test_threshold` per material (overriding the default set above) and `u_emissive` —
both are bridge.frag uniforms, so they apply correctly to the skinned program too.

**A5. GL test** (`native/tests/renderer/skinned_bridge_test.cc`): hidden Window + Pipeline +
AssetCache (mirror `skinned_render_test.cc`). Load `BodyMaleL.NIF`, `create_instance`, set its
pass to `Pass::Bridge` (via `World::set_pass`), position it in front of a bridge camera, set a
non-black `Lighting::ambient`, call `BridgePass::render`, glReadPixels, assert non-background
pixels exist (the character rendered, lit). SKIP if asset/GL absent. Also assert that with
`ambient = (0,0,0)` and zero emissive the character is black/background (lit by bridge ambient,
not space lighting) — i.e. confirm it's the BRIDGE lighting driving it.

**A6.** `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "SkinnedBridge|Bridge|Skinned" --output-on-failure`. All pass; existing bridge tests unaffected. Commit.

---

### Task B: bounds-aware, active-pass F7 placement

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`spawn_test_character`)
- Modify: `engine/renderer.py`, `engine/dev_keybindings.py`, `tests/unit/test_renderer_test_character.py`

**B1.** Rework `spawn_test_character` so the host (which owns the cameras + pass state) places the
character in front of the **active** camera at a bounds-aware distance and tags the **active** pass:

```cpp
    m.def("spawn_test_character",
          [](const std::string& nif_path) {
              std::filesystem::path tex_dir = std::filesystem::path(nif_path).parent_path();
              auto handle = load_model_impl(nif_path, py::cast(tex_dir.string()));
              auto id = g_world.create_instance(handle);

              const bool bridge = g_bridge_pass_enabled && g_bridge_pass;
              const scenegraph::Camera& cam = bridge ? g_bridge_camera : g_camera;

              // Distance ~1.8x the model's bounding radius so it frames in view.
              float radius = g_world.instance_bounding_radius(id);  // or model AABB; see note
              if (!(radius > 0.0f)) radius = 3.0f;
              glm::vec3 fwd = cam.target - cam.eye;
              float len = glm::length(fwd);
              fwd = (len > 1e-4f) ? fwd / len : glm::vec3(0.0f, 0.0f, -1.0f);
              glm::vec3 pos = cam.eye + fwd * (radius * 1.8f);

              glm::mat4 world(1.0f);
              world[3][0] = pos.x; world[3][1] = pos.y; world[3][2] = pos.z;
              g_world.set_world_transform(id, world);
              g_world.set_pass(id, bridge ? scenegraph::Pass::Bridge : scenegraph::Pass::Space);
              return id;
          },
          py::arg("nif_path"),
          "Developer-only: spawn a skinned NIF framed in front of the active camera, "
          "tagged for the active pass (bridge or space). Returns its InstanceId.");
```

Note: confirm the real way to get a model/instance bounding radius — there are existing bindings
`model_aabb` (~host_bindings.cc:998) and `get_instance_bounds` (~:898). Use whichever the C++
`g_world`/model API exposes directly (e.g. compute from the model AABB of `handle`); do NOT round-trip
through Python. If only an AABB is available, radius = half the max extent (or 0.5*length of the
diagonal). Drop the `world_pos` parameter entirely.

**B2.** `engine/renderer.py`: drop the `world_pos` arg from the `spawn_test_character` wrapper
(now `spawn_test_character(nif_path)`), keeping the host-absent guard pattern.

**B3.** `engine/dev_keybindings.py`: remove the player-forward placement math and the
`_DEFAULT_SPAWN_POS` constant; the handler just calls `renderer.spawn_test_character(_TEST_CHARACTER_NIF)`
inside the existing try/except. Toggle/despawn logic unchanged.

**B4.** Update `tests/unit/test_renderer_test_character.py` to the new single-arg signature
(host-absent → None; forwarding the nif path). Run ONLY this file:
`uv run pytest tests/unit/test_renderer_test_character.py -q`.

**B5.** Build (`cmake -B build -S . && cmake --build build -j`) so the `.so` regenerates; commit.
Live verification (press F7 on DBridge, character appears framed and bridge-lit) is the user's.
