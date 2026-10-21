// native/tests/renderer/model_textures_test.cc
//
// renderer::find_base_texture_id (renderer/model_textures.h): the texture a
// rock's crater interior is painted with. Moved here from breach_pass_test.cc
// when the old breach pass was removed (layered damage phase 4, Task 2); the
// hull interior pass is its consumer now.
#include <gtest/gtest.h>

#include <glad/glad.h>

#include <renderer/model_textures.h>
#include <renderer/window.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <memory>
#include <stdexcept>

TEST(FindBaseTextureId, EmptyModelHasNone) {
    assets::Model m;   // no meshes, no materials: nothing to find
    EXPECT_EQ(renderer::find_base_texture_id(m), 0u);
}

TEST(FindBaseTextureId, ReadsTheFirstMeshWithABaseStageTexture) {
    std::unique_ptr<renderer::Window> w;
    try {
        w = std::make_unique<renderer::Window>(16, 16, "model-textures-test", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }
    assets::Model m;
    // A mesh with no material at all comes first: skipped.
    assets::MeshCpu bare;
    bare.material_index = -1;
    for (int i = 0; i < 3; ++i) bare.vertices.push_back({});
    bare.indices = {0, 1, 2};
    m.meshes.push_back(assets::upload_mesh(bare));
    EXPECT_EQ(renderer::find_base_texture_id(m), 0u);

    // A second mesh whose material's Base stage names a real texture.
    GLuint id = 0;
    glGenTextures(1, &id);
    m.textures.emplace_back(id, 1u, 1u, false);   // Texture owns + frees it
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)].texture_index = 0;
    m.materials.push_back(mat);
    assets::MeshCpu cpu;
    cpu.material_index = 0;
    for (int i = 0; i < 3; ++i) cpu.vertices.push_back({});
    cpu.indices = {0, 1, 2};
    m.meshes.push_back(assets::upload_mesh(cpu));
    EXPECT_EQ(renderer::find_base_texture_id(m), static_cast<unsigned int>(id));

    // An out-of-range texture index is guarded, not dereferenced.
    m.materials[0].stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)].texture_index = 7;
    EXPECT_EQ(renderer::find_base_texture_id(m), 0u);
}
