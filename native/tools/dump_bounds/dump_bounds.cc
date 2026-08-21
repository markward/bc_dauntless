// Report the hull pieces a NIF decomposes into, and how tightly they bound it.
//
// Written to answer, in order:
//   1. do BC's models carry authored NiTriShapeData bounds at all? (yes, all of
//      them) -- everything downstream silently degrades to the model-wide
//      sphere if they are zero, and that looks identical to "not wired up";
//   2. is the authored sphere TIGHT? (no: -v shows 5-22x slack against the
//      shape's own AABB in the thin direction, because BC hulls are flat
//      plates and the sphere is fitted about the AABB centre);
//   3. is one bound per shape one bound per PIECE? (no: three of
//      FedStarbase's five shapes each span the entire station);
// which is why compute_model_bounds derives pieces from the TRIANGLES instead.
// -p runs that same shipping splitter -- renderer::compute_bounds_from_triangles
// -- so what this prints is what the engine gets.
//
// CAVEAT on -p: this reads the NIF directly and does NOT compose NiNode
// transforms, where the engine does. Harmless on the files it was built to
// measure (FedStarbase.nif and Galaxy.nif have identity shape transforms --
// check with probe_shape_transforms), wrong on any model that offsets its
// shapes.
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <exception>
#include <variant>
#include <vector>

#include <glm/glm.hpp>

#include <nif/block.h>
#include <nif/file.h>
#include <renderer/aabb.h>

namespace {

void dump_shape(int index, const nif::NiTriShapeData& d) {
    if (d.vertices.empty()) {
        std::printf("  [%2d] r=%9.1f  (no vertices)\n", index, d.bound_radius);
        return;
    }
    nif::Vec3 lo = d.vertices.front(), hi = d.vertices.front();
    for (const auto& v : d.vertices) {
        lo.x = std::min(lo.x, v.x); hi.x = std::max(hi.x, v.x);
        lo.y = std::min(lo.y, v.y); hi.y = std::max(hi.y, v.y);
        lo.z = std::min(lo.z, v.z); hi.z = std::max(hi.z, v.z);
    }
    const float hx = (hi.x - lo.x) * 0.5f;
    const float hy = (hi.y - lo.y) * 0.5f;
    const float hz = (hi.z - lo.z) * 0.5f;
    const float thinnest = std::min({hx, hy, hz});
    std::printf("  [%2d] r=%9.1f  box_c=(%9.1f %9.1f %9.1f)  half=(%9.1f %9.1f %9.1f)"
                "  slack=%5.1fx  verts=%u\n",
                index, d.bound_radius, (lo.x + hi.x) * 0.5f, (lo.y + hi.y) * 0.5f,
                (lo.z + hi.z) * 0.5f, hx, hy, hz,
                thinnest > 0.0f ? d.bound_radius / thinnest : 0.0f,
                unsigned(d.vertices.size()));
}

std::vector<std::array<glm::vec3, 3>> gather_triangles(const nif::File& doc) {
    std::vector<std::array<glm::vec3, 3>> tris;
    for (const auto& b : doc.blocks) {
        const auto* d = std::get_if<nif::NiTriShapeData>(&b);
        if (!d) continue;
        for (const auto& t : d->triangles) {
            if (t[0] >= d->vertices.size() || t[1] >= d->vertices.size() ||
                t[2] >= d->vertices.size()) continue;
            std::array<glm::vec3, 3> out;
            for (int c = 0; c < 3; ++c) {
                const auto& v = d->vertices[t[c]];
                out[c] = glm::vec3(v.x, v.y, v.z);
            }
            tris.push_back(out);
        }
    }
    return tris;
}

/// Print the pieces, and the headline number: how much of the model's own
/// bounding sphere they DON'T claim. That fraction is the space a ship can fly
/// through -- a starbase's docking bay, the volume under its mushroom cap --
/// which one model-wide sphere claims entirely.
void dump_pieces(const nif::File& doc, float unit_scale) {
    const auto tris = gather_triangles(doc);
    if (tris.empty()) {
        std::printf("  (no triangles)\n");
        return;
    }
    const auto pieces = renderer::compute_bounds_from_triangles(tris);
    glm::vec3 lo(tris[0][0]), hi(tris[0][0]);
    for (const auto& t : tris) {
        for (const auto& p : t) { lo = glm::min(lo, p); hi = glm::max(hi, p); }
    }
    const glm::vec3 center = 0.5f * (lo + hi);
    float model_r = 0.0f;
    for (const auto& t : tris) {
        for (const auto& p : t) model_r = std::max(model_r, glm::length(p - center));
    }
    float biggest = 0.0f, sum_vol = 0.0f;
    for (const auto& p : pieces) {
        biggest = std::max(biggest, p.radius);
        sum_vol += p.radius * p.radius * p.radius;   // upper bound: ignores overlap
    }
    const float model_vol = model_r * model_r * model_r;
    std::printf("  pieces=%zu  tris=%zu  model_r=%.1f  biggest_piece=%.1f (%.0f%%)"
                "  claimed<=%.0f%% of the model sphere\n",
                pieces.size(), tris.size(), model_r * unit_scale,
                biggest * unit_scale, 100.0f * biggest / model_r,
                model_vol > 0.0f ? 100.0f * sum_vol / model_vol : 0.0f);
    for (std::size_t i = 0; i < pieces.size(); ++i) {
        std::printf("    <%2zu> c=(%8.1f %8.1f %8.1f)  r=%8.1f\n", i,
                    pieces[i].center.x * unit_scale,
                    pieces[i].center.y * unit_scale,
                    pieces[i].center.z * unit_scale,
                    pieces[i].radius * unit_scale);
    }
}

/// For each probe point: is it inside a piece, and how far is the nearest real
/// VERTEX? The gap between those two answers is the slack -- the empty space
/// the pieces wrongly claim, which is exactly what stops a ship flying in
/// under a starbase's cap. Nearest vertex rather than nearest point-on-triangle:
/// it slightly overstates the distance on big triangles, and overstating the
/// distance understates the slack, so the number never flatters the splitter.
void query_points(const nif::File& doc, float unit_scale,
                  const std::vector<glm::vec3>& probes_world) {
    const auto tris = gather_triangles(doc);
    if (tris.empty()) return;
    const auto pieces = renderer::compute_bounds_from_triangles(tris);
    std::printf("  %-28s %-8s %-14s %-14s\n", "probe (given units)", "inside",
                "piece surface", "nearest vertex");
    for (const auto& pw : probes_world) {
        const glm::vec3 p = pw / unit_scale;   // back into raw NIF units
        bool inside = false;
        float to_piece = std::numeric_limits<float>::max();
        for (const auto& s : pieces) {
            const float d = glm::length(p - s.center) - s.radius;
            if (d <= 0.0f) inside = true;
            to_piece = std::min(to_piece, d);
        }
        float to_vert = std::numeric_limits<float>::max();
        for (const auto& t : tris) {
            for (const auto& v : t) to_vert = std::min(to_vert, glm::length(p - v));
        }
        char buf[64];
        std::snprintf(buf, sizeof buf, "(%.1f %.1f %.1f)", pw.x, pw.y, pw.z);
        std::printf("  %-28s %-8s %-14.1f %-14.1f\n", buf, inside ? "yes" : "no",
                    to_piece * unit_scale, to_vert * unit_scale);
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr,
                     "usage: %s [-v] [-p] [-gu] [-q x,y,z] <file.nif> ...\n"
                     "  -v      per-shape authored sphere vs vertex AABB\n"
                     "  -p      hull pieces, via the shipping splitter\n"
                     "  -gu     report in game units rather than raw NIF units\n"
                     "  -q      probe a point: inside a piece? how far is real\n"
                     "          geometry? (repeatable; same units as the output)\n",
                     argv[0]);
        return 2;
    }
    bool verbose = false, pieces = false;
    float unit_scale = 1.0f;
    std::vector<glm::vec3> probes;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "-v") == 0) { verbose = true; continue; }
        if (std::strcmp(argv[i], "-p") == 0) { pieces = true; continue; }
        if (std::strcmp(argv[i], "-gu") == 0) { unit_scale = 0.01f; continue; }
        if (std::strcmp(argv[i], "-q") == 0 && i + 1 < argc) {
            glm::vec3 p{};
            if (std::sscanf(argv[++i], "%f,%f,%f", &p.x, &p.y, &p.z) == 3) {
                probes.push_back(p);
            }
            continue;
        }
        try {
            nif::File doc = nif::load(argv[i]);
            int shapes = 0, nonzero = 0;
            float max_r = 0.0f;
            for (const auto& b : doc.blocks) {
                if (const auto* d = std::get_if<nif::NiTriShapeData>(&b)) {
                    if (d->bound_radius > 0.0f) ++nonzero;
                    if (d->bound_radius > max_r) max_r = d->bound_radius;
                    if (verbose) dump_shape(shapes, *d);
                    ++shapes;
                }
            }
            std::printf("%-58s shapes=%-4d bounded=%-4d max_r=%.1f\n",
                        argv[i], shapes, nonzero, max_r * unit_scale);
            if (pieces) dump_pieces(doc, unit_scale);
            if (!probes.empty()) query_points(doc, unit_scale, probes);
        } catch (const std::exception& e) {
            std::printf("%-58s ERROR %s\n", argv[i], e.what());
        }
    }
    return 0;
}
