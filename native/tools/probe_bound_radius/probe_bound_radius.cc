// native/tools/probe_bound_radius/probe_bound_radius.cc
//
// Investigation tool for the system-scale work:
// Loads a NIF and reports each NiTriShapeData's authored bound_center +
// bound_radius, alongside its parent NiTriShape's av.translation. Then
// computes the model's outer "visual radius" — the maximum of
//   |av.translation + bound_center| + bound_radius
// across all shapes. This is the divisor for our renderer's per-object
// scale: render_scale = GetRadius() / NIF_visual_radius.
//
// Usage:
//   probe_bound_radius <nif-file> [<nif-file> ...]

#include <nif/block.h>
#include <nif/file.h>

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <unordered_map>
#include <variant>

namespace fs = std::filesystem;

namespace {

float length3(const nif::Vec3& v) {
    return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

nif::Vec3 add(const nif::Vec3& a, const nif::Vec3& b) {
    return {a.x + b.x, a.y + b.y, a.z + b.z};
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <nif-file> [<nif-file> ...]\n", argv[0]);
        return 2;
    }

    for (int ai = 1; ai < argc; ++ai) {
        fs::path path = argv[ai];
        nif::File f;
        try {
            f = nif::load(path);
        } catch (const std::exception& e) {
            std::printf("ERR %s: %s\n", path.string().c_str(), e.what());
            continue;
        }

        // Map block_id -> index into f.blocks, so we can resolve NiTriShape.data_link.
        std::unordered_map<std::uint32_t, std::size_t> id_to_index;
        for (std::size_t i = 0; i < f.block_ids.size(); ++i) {
            id_to_index[f.block_ids[i]] = i;
        }

        std::printf("%s\n", path.string().c_str());
        std::printf("  blocks=%zu  eof=%d\n", f.blocks.size(), int(f.eof_reached));

        float max_visual = 0.0f;
        float max_radius_alone = 0.0f;
        std::size_t shape_count = 0;

        for (std::size_t i = 0; i < f.blocks.size(); ++i) {
            auto* shape = std::get_if<nif::NiTriShape>(&f.blocks[i]);
            if (!shape) continue;
            ++shape_count;

            const nif::Vec3& t = shape->av.translation;
            float scale = shape->av.scale;

            // Find the linked NiTriShapeData.
            const nif::NiTriShapeData* data = nullptr;
            auto it = id_to_index.find(shape->data_link);
            if (it != id_to_index.end() && it->second < f.blocks.size()) {
                data = std::get_if<nif::NiTriShapeData>(&f.blocks[it->second]);
            }

            if (!data) {
                std::printf("  shape[%zu] name=%-24s  t=(%.3f,%.3f,%.3f)  s=%.3f  data=MISSING\n",
                            i, shape->av.obj.name.c_str(), t.x, t.y, t.z, scale);
                continue;
            }

            nif::Vec3 world_center = add(t, data->bound_center);
            float world_extent = length3(world_center) + data->bound_radius * scale;
            if (world_extent > max_visual) max_visual = world_extent;
            if (data->bound_radius > max_radius_alone) max_radius_alone = data->bound_radius;

            std::printf("  shape[%zu] name=%-24s  t=(%8.3f,%8.3f,%8.3f) s=%.3f  "
                        "bound_c=(%8.3f,%8.3f,%8.3f) r=%8.3f  nv=%5u  extent=%.3f\n",
                        i, shape->av.obj.name.c_str(), t.x, t.y, t.z, scale,
                        data->bound_center.x, data->bound_center.y, data->bound_center.z,
                        data->bound_radius, data->num_vertices, world_extent);
        }

        std::printf("  AGGREGATE: shapes=%zu  max bound_radius alone=%.3f  "
                    "max model-space extent=%.3f\n\n",
                    shape_count, max_radius_alone, max_visual);
    }
    return 0;
}
