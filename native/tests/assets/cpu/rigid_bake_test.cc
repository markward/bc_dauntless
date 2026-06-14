#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include "model_build.h"
#include <assets/model.h>
#include <assets/path_resolver.h>
#include <nif/file.h>

#include <cmath>
#include <filesystem>

// A rigid BC body part's vertices must be baked into BIND-MODEL space so the
// GPU palette (world_pose * inverse_bind) poses them. Proof: for a rigid shape
// on bone B, at BIND pose palette[B] == identity, so the drawn world position
// is world * v_bindmodel. v_bindmodel must equal world_bind(B) * v_nodelocal.
// We verify build_model now stores a body whose rigid mesh verts, in model
// space, span the arms: an arm/hand mesh's verts sit far from the spine in X
// (arm span ~±32), which is ONLY true if verts are in bind-model space, not
// node-local (where a hand shape's verts cluster near its own node origin,
// |x| < ~5).
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

TEST(RigidBake, RigidVertsAreInBindModelSpace) {
    namespace fs = std::filesystem;
    const fs::path root = OPEN_STBC_PROJECT_ROOT;
    const fs::path nif = root / "game" / "data" / "Models" / "Characters"
        / "Bodies" / "BodyMaleL" / "BodyMaleL.NIF";
    if (!fs::exists(nif)) GTEST_SKIP() << "asset missing: " << nif;

    nif::File f = nif::load(nif);

    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {nif.parent_path()};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.keep_cpu_data = true;

    assets::Model m = assets::detail::build_model(f, ctx);
    ASSERT_FALSE(m.skeleton.bones.empty());

    float max_abs_x = 0.0f;
    for (const auto& mesh : m.meshes) {
        const auto& cpu = mesh.cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices)
            max_abs_x = std::max(max_abs_x, std::abs(v.position.x));
    }
    EXPECT_GT(max_abs_x, 20.0f)
        << "rigid verts look node-local (clustered), not bind-model space";
}
