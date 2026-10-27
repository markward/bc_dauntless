#include <assets/smoothing_probe.h>

#include "model_build.h"
#include "normal_gen.h"

namespace assets {

namespace {

// No GL context here: zero ids make the destructors short-circuit.
Texture stub_texture(const Image&, bool) { return Texture(/*id=*/0, 1, 1, false); }
Mesh stub_mesh(MeshCpu cpu) {
    return Mesh(/*vao=*/0, /*vbo=*/0, /*ebo=*/0,
                static_cast<std::uint32_t>(cpu.indices.size()),
                cpu.material_index, cpu.node_index);
}

}  // namespace

std::vector<SmoothingRow> probe_smoothing(const nif::File& file) {
    PathResolver resolver;
    detail::SmoothingReport report;
    detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.skip_texture_decode = true;  // geometry only: no texture lookups or warnings
    ctx.generate_missing_normals = true;
    ctx.smoothing_report = &report;
    detail::build_model(file, ctx);

    std::vector<SmoothingRow> rows;
    rows.reserve(report.edges.size());
    for (const auto& e : report.edges)
        rows.push_back({static_cast<int>(e.shape), e.a, e.b, e.found, e.joined_a, e.joined_b});
    return rows;
}

}  // namespace assets
