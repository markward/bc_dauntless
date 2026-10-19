#include <gtest/gtest.h>
#include "skin_offsets.h"
#include <assets/mesh.h>
#include <nif/block.h>

#include "model_build.h"
#include <assets/model.h>
#include <assets/path_resolver.h>
#include <nif/file.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <filesystem>
#include <optional>
#include "support/content_root.h"

// BC's legacy NiTriShapeSkinController stores, per (bone, vertex) influence, the
// vertex's position in that bone's space. BC skins from those offsets; the
// shape's own vertex array only matters where nothing skins it. In every stock
// character the two agree to ~0.0003 units, but kessok_head.NIF's vertex array
// is stored rotated 90° and shifted (~44 units) from where its offsets put it,
// so a loader that trusts the vertex array buries the Kessok's head in its
// chest. seat_from_skin_offsets re-seats such a shape from its offsets.

using assets::detail::seat_from_skin_offsets;

namespace {

constexpr float kEps = 1e-4f;

void expect_near(const glm::vec3& a, const glm::vec3& b) {
    EXPECT_NEAR(a.x, b.x, kEps);
    EXPECT_NEAR(a.y, b.y, kEps);
    EXPECT_NEAR(a.z, b.z, kEps);
}

// Four non-coplanar true bind positions, each skinned 100% to `bone_bind`.
struct Fixture {
    glm::mat4 bone_bind = glm::translate(glm::mat4(1.0f), {0.0f, 0.0f, 68.0f});
    std::vector<glm::vec3> truth = {{0, 0, 70}, {3, 0, 72}, {0, 4, 73}, {-2, -1, 76}};
    glm::vec3 true_normal = glm::normalize(glm::vec3(0.0f, -1.0f, 0.2f));
    nif::NiTriShapeSkinController skin;
    std::vector<std::optional<glm::mat4>> bones;

    Fixture() {
        skin.num_bones = 1;
        skin.bone_weights.resize(1);
        const glm::mat4 inv = glm::inverse(bone_bind);
        for (std::size_t k = 0; k < truth.size(); ++k) {
            const glm::vec3 o = glm::vec3(inv * glm::vec4(truth[k], 1.0f));
            skin.bone_weights[0].push_back(
                {1.0f, static_cast<std::uint16_t>(k), {o.x, o.y, o.z}});
        }
        bones = {bone_bind};
    }

    assets::MeshCpu mesh_through(const glm::mat4& stored) const {
        assets::MeshCpu m;
        for (const auto& p : truth) {
            assets::MeshCpu::Vertex v;
            v.position = glm::vec3(stored * glm::vec4(p, 1.0f));
            v.normal = glm::normalize(glm::mat3(stored) * true_normal);
            m.vertices.push_back(v);
        }
        return m;
    }
};

// The shape the Kessok head ships: vertex array rotated 90° about one axis and
// shifted, relative to where its skin offsets place it.
glm::mat4 kessok_like_frame() {
    glm::mat4 r = glm::rotate(glm::mat4(1.0f), glm::radians(90.0f), {1.0f, 1.0f, 1.0f});
    return glm::translate(glm::mat4(1.0f), {-50.0f, 2.0f, 48.0f}) * r;
}

}  // namespace

TEST(SeatFromSkinOffsets, ShapeThatAgreesWithItsOffsetsIsUntouched) {
    Fixture fx;
    assets::MeshCpu mesh = fx.mesh_through(glm::mat4(1.0f));
    // Within the stock corpus's own drift (≤0.0003): still "agrees".
    mesh.vertices[1].position.x += 0.0005f;
    const assets::MeshCpu before = mesh;

    EXPECT_FALSE(seat_from_skin_offsets(mesh, fx.skin, fx.bones));
    for (std::size_t k = 0; k < mesh.vertices.size(); ++k) {
        EXPECT_EQ(mesh.vertices[k].position, before.vertices[k].position);
        EXPECT_EQ(mesh.vertices[k].normal, before.vertices[k].normal);
    }
}

TEST(SeatFromSkinOffsets, MisplacedShapeIsReseatedFromItsOffsets) {
    Fixture fx;
    assets::MeshCpu mesh = fx.mesh_through(kessok_like_frame());

    EXPECT_TRUE(seat_from_skin_offsets(mesh, fx.skin, fx.bones));
    for (std::size_t k = 0; k < mesh.vertices.size(); ++k)
        expect_near(mesh.vertices[k].position, fx.truth[k]);
}

TEST(SeatFromSkinOffsets, NormalsTurnWithTheShape) {
    Fixture fx;
    assets::MeshCpu mesh = fx.mesh_through(kessok_like_frame());

    seat_from_skin_offsets(mesh, fx.skin, fx.bones);
    for (const auto& v : mesh.vertices) expect_near(v.normal, fx.true_normal);
}

TEST(SeatFromSkinOffsets, UnskinnedVertexMovesWithTheRestOfTheShape) {
    Fixture fx;
    fx.truth.push_back({1, 1, 71});  // no influence record for this one
    assets::MeshCpu mesh = fx.mesh_through(kessok_like_frame());

    seat_from_skin_offsets(mesh, fx.skin, fx.bones);
    expect_near(mesh.vertices.back().position, fx.truth.back());
}

TEST(SeatFromSkinOffsets, UnresolvedBoneLeavesTheShapeAlone) {
    Fixture fx;
    fx.bones = {std::nullopt};  // the skin names a bone the skeleton lacks
    assets::MeshCpu mesh = fx.mesh_through(kessok_like_frame());
    const assets::MeshCpu before = mesh;

    EXPECT_FALSE(seat_from_skin_offsets(mesh, fx.skin, fx.bones));
    EXPECT_EQ(mesh.vertices[0].position, before.vertices[0].position);
}

// ---- the real asset -------------------------------------------------------

namespace {
assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(0, 0, 0, static_cast<std::uint32_t>(cpu.indices.size()),
                        cpu.material_index, cpu.node_index);
}

assets::Model build(const std::filesystem::path& nif) {
    static assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {nif.parent_path()};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.keep_cpu_data = true;
    return assets::detail::build_model(nif::load(nif), ctx);
}

glm::vec3 bone_bind_origin(const assets::Model& m, const std::string& name) {
    for (std::size_t i = 0; i < m.nodes.size(); ++i) {
        if (m.nodes[i].name != name) continue;
        glm::mat4 w = m.nodes[i].local_transform;
        for (int p = m.nodes[i].parent_index; p >= 0; p = m.nodes[p].parent_index)
            w = m.nodes[p].local_transform * w;
        return glm::vec3(w[3]);
    }
    ADD_FAILURE() << "no node " << name;
    return {};
}
}  // namespace

TEST(SeatFromSkinOffsets, KessokHeadSitsOnItsHeadBone) {
    const std::filesystem::path game = test_support::game_root();
    const auto nif = game / "data" / "Models" / "Characters" / "Heads"
                     / "HeadKessok" / "kessok_head.NIF";
    if (!std::filesystem::exists(nif)) GTEST_SKIP() << "asset missing: " << nif;
    const assets::Model model = build(nif);
    const assets::Model* m = &model;

    const glm::vec3 head = bone_bind_origin(*m, "Bip01 Head");
    glm::vec3 lo(1e9f), hi(-1e9f), sum(0.0f);
    std::size_t n = 0;
    for (const auto& mesh : m->meshes) {
        const auto& cpu = mesh.cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices) {
            lo = glm::min(lo, v.position);
            hi = glm::max(hi, v.position);
            sum += v.position;
            ++n;
        }
    }
    ASSERT_GT(n, 0u);
    const glm::vec3 mean = sum / static_cast<float>(n);
    // Before the fix: z 40-61 (in the chest) and ~25 units forward of the bone.
    EXPECT_LT(lo.z, head.z);
    EXPECT_GT(hi.z, head.z + 5.0f);
    EXPECT_NEAR(mean.x, head.x, 1.0f);
    EXPECT_NEAR(mean.y, head.y, 6.0f);
}
