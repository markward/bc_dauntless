#include <gtest/gtest.h>

#include <assets/asset.h>
#include <assets/animation.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

TEST(AssetsHeaders, AllPublicHeadersInclude) {
    assets::Image img;
    assets::MeshCpu mesh;
    assets::Material mat;
    assets::Skeleton skel;
    assets::AnimationClip clip;
    assets::Model model;

    EXPECT_EQ(img.width, 0u);
    EXPECT_EQ(mesh.material_index, -1);
    EXPECT_EQ(mat.alpha, 1.0f);
    EXPECT_EQ(skel.root_bone_index, -1);
    EXPECT_EQ(clip.duration_seconds, 0.0f);
    EXPECT_EQ(model.root_node, 0);
}

TEST(AssetsHeaders, MaterialStageSlotCount) {
    EXPECT_EQ(static_cast<int>(assets::Material::StageSlot::Count), 9);
    assets::Material m;
    EXPECT_EQ(m.stages.size(), 9u);
    EXPECT_EQ(m.stages[0].texture_index, -1);  // unused by default
}

TEST(AssetsHeaders, MeshCpuVertexLayoutDefaults) {
    assets::MeshCpu::Vertex v;
    EXPECT_EQ(v.color, glm::u8vec4(255, 255, 255, 255));
    EXPECT_EQ(v.bone_indices, glm::u8vec4(0, 0, 0, 0));
    EXPECT_EQ(v.bone_weights, glm::u8vec4(0, 0, 0, 0));
}
