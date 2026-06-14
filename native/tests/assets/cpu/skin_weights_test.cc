#include <gtest/gtest.h>
#include "skin_weights.h"
#include <assets/mesh.h>
#include <nif/block.h>

#include "model_build.h"
#include <assets/model.h>
#include <assets/path_resolver.h>
#include <nif/file.h>

#include <filesystem>
#include <set>

using assets::detail::fill_skin_weights;

namespace {
assets::MeshCpu make_mesh(int n) {
    assets::MeshCpu m;
    m.vertices.resize(n);
    return m;
}
}  // namespace

TEST(FillSkinWeights, SingleBoneFullWeightMapsToSkeletonIndex) {
    nif::NiTriShapeSkinController skin;
    skin.num_bones = 1;
    skin.bone_weights = {{ {1.0f, /*vertex_index=*/0, {}} }};
    // controller-bone 0 -> skeleton-bone 7
    std::vector<int> skin_bone_to_skeleton = {7};

    auto mesh = make_mesh(1);
    fill_skin_weights(mesh, skin, skin_bone_to_skeleton);

    EXPECT_EQ(mesh.vertices[0].bone_indices.x, 7);
    EXPECT_EQ(mesh.vertices[0].bone_weights.x, 255);  // 1.0 -> 255 (u8 normalized)
}

TEST(FillSkinWeights, KeepsTopFourAndRenormalizes) {
    nif::NiTriShapeSkinController skin;
    skin.num_bones = 5;
    // Vertex 0 influenced by 5 bones with weights 0.1..0.5; smallest (0.1) dropped.
    skin.bone_weights = {
        {{0.10f, 0, {}}}, {{0.20f, 0, {}}}, {{0.30f, 0, {}}},
        {{0.40f, 0, {}}}, {{0.50f, 0, {}}},
    };
    std::vector<int> map = {0, 1, 2, 3, 4};

    auto mesh = make_mesh(1);
    fill_skin_weights(mesh, skin, map);

    // 4 largest are bones 4,3,2,1 (0.5,0.4,0.3,0.2) summing 1.4; renormalized to 1.0.
    int sum = mesh.vertices[0].bone_weights.x + mesh.vertices[0].bone_weights.y
            + mesh.vertices[0].bone_weights.z + mesh.vertices[0].bone_weights.w;
    EXPECT_NEAR(sum, 255, 2);                  // weights renormalize to ~1.0
    // bone 0 (weight 0.1) must NOT appear among the four indices.
    for (int k = 0; k < 4; ++k) {
        int idx = mesh.vertices[0].bone_indices[k];
        EXPECT_NE(idx, 0);
    }
}

TEST(FillSkinWeights, UnweightedVertexDefaultsToBoneZeroFullWeight) {
    nif::NiTriShapeSkinController skin;
    skin.num_bones = 1;
    skin.bone_weights = {{ {1.0f, 0, {}} }};   // only vertex 0 weighted
    std::vector<int> map = {3};

    auto mesh = make_mesh(2);                   // vertex 1 has no influence
    fill_skin_weights(mesh, skin, map);

    EXPECT_EQ(mesh.vertices[1].bone_indices.x, 0);
    EXPECT_EQ(mesh.vertices[1].bone_weights.x, 255);
    EXPECT_EQ(mesh.vertices[1].bone_weights.y, 0);
}

namespace {
assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(
        /*vao=*/0, /*vbo=*/0, /*ebo=*/0,
        static_cast<std::uint32_t>(cpu.indices.size()),
        cpu.material_index, cpu.node_index);
}
}  // namespace

TEST(FillSkinWeightsAsset, BodyMaleLHasNonTrivialWeights) {
    namespace fs = std::filesystem;
    const fs::path root = OPEN_STBC_PROJECT_ROOT;
    const fs::path nif = root / "game" / "data" / "Models" / "Characters"
        / "Bodies" / "BodyMaleL" / "BodyMaleL.NIF";
    if (!fs::exists(nif)) GTEST_SKIP() << "BodyMaleL.NIF not present at " << nif;

    nif::File f = nif::load(nif);

    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {nif.parent_path()};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.keep_cpu_data = true;

    assets::Model model = assets::detail::build_model(f, ctx);
    ASSERT_FALSE(model.skeleton.bones.empty())
        << "BodyMaleL should produce a non-empty skeleton";

    bool found = false;
    for (const auto& mesh : model.meshes) {
        const auto& cpu = mesh.cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices) {
            if (v.bone_weights.x > 0 &&
                v.bone_indices.x < model.skeleton.bones.size()) {
                found = true;
                break;
            }
        }
        if (found) break;
    }
    EXPECT_TRUE(found)
        << "expected at least one retained vertex with bone_weights.x > 0 "
           "and a valid bone index";
}

// SP3: skin-controller-less (rigid) shapes of a skinned model must bind to
// their PARENT bone, not always bone 0. BodyMaleL is mostly rigid shapes
// parented to Bip01 bone nodes, so after the rebind the set of bones used by
// rigid-bound vertices (weight == (255,0,0,0)) must include a real non-root
// bone index. SP1 bound them all to bone 0, which this test rejects.
TEST(RigidRebindAsset, RigidShapesBindToParentBoneNotAlwaysZero) {
    namespace fs = std::filesystem;
    const fs::path root = OPEN_STBC_PROJECT_ROOT;
    const fs::path nif = root / "game" / "data" / "Models" / "Characters"
        / "Bodies" / "BodyMaleL" / "BodyMaleL.NIF";
    if (!fs::exists(nif)) GTEST_SKIP() << "BodyMaleL.NIF not present at " << nif;

    nif::File f = nif::load(nif);

    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {nif.parent_path()};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.keep_cpu_data = true;

    assets::Model model = assets::detail::build_model(f, ctx);
    ASSERT_FALSE(model.skeleton.bones.empty())
        << "BodyMaleL should produce a non-empty skeleton";

    // Collect bone indices of rigid-bound vertices: weight exactly (255,0,0,0).
    std::set<int> rigid_bones;
    for (const auto& mesh : model.meshes) {
        const auto& cpu = mesh.cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices) {
            if (v.bone_weights.x == 255 && v.bone_weights.y == 0 &&
                v.bone_weights.z == 0 && v.bone_weights.w == 0) {
                rigid_bones.insert(static_cast<int>(v.bone_indices.x));
            }
        }
    }
    ASSERT_FALSE(rigid_bones.empty())
        << "expected at least one rigid-bound (255,0,0,0) vertex in BodyMaleL";

    const int nbones = static_cast<int>(model.skeleton.bones.size());
    bool has_real_nonroot = false;
    for (int b : rigid_bones) {
        if (b > 0 && b < nbones) { has_real_nonroot = true; break; }
    }
    EXPECT_TRUE(has_real_nonroot)
        << "rigid shapes should bind to a real non-root parent bone "
           "(index > 0, < bone count), not all to bone 0";
}
