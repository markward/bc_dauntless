// native/src/renderer/glow_region.cc
#include "renderer/glow_region.h"

#include <algorithm>
#include <limits>
#include <utility>
#include <vector>

#include <assets/mesh.h>
#include <assets/model.h>

namespace renderer {

GlowRegion compute_capsule_region(const assets::Model& model,
                                  const glm::vec3& center,
                                  const glm::vec3& axis,
                                  float radius) {
    GlowRegion reg;
    reg.center = center;
    reg.axis   = axis;
    reg.active = true;

    // The hardpoint radius is the gameplay damage sphere — several times the
    // nacelle's visual cross-section. `widened` is used only to GATHER candidate
    // vertices and bound the axial fit; the RENDERED capsule (reg.radius) is a
    // nacelle-scale fraction of it so the shader dims the nacelle's glow band
    // without reaching across the spine into the secondary hull.
    const float widened = radius * kGlowCapsuleRadiusWiden;
    reg.radius = widened * kGlowCapsuleRenderRadiusFrac;

    const float lat2 = widened * widened;
    // (axial projection t, squared lateral distance) of every captured vertex.
    std::vector<std::pair<float, float>> samples;

    if (!model.nodes.empty()) {
        // Walk node hierarchy to chain local_transform from root down. The asset
        // pipeline orders nodes so parents precede children, so a single linear
        // pass produces correct world-per-node matrices.
        std::vector<glm::mat4> node_world(model.nodes.size(), glm::mat4(1.0f));
        node_world[model.root_node] =
            model.nodes[model.root_node].local_transform;
        for (std::size_t i = 0; i < model.nodes.size(); ++i) {
            const auto& node = model.nodes[i];
            if (node.parent_index >= 0) {
                node_world[i] =
                    node_world[node.parent_index] * node.local_transform;
            }
            for (int mesh_idx : node.meshes) {
                if (mesh_idx < 0 ||
                    mesh_idx >= static_cast<int>(model.meshes.size())) continue;
                const auto& cpu = model.meshes[mesh_idx].cpu_data();
                if (!cpu) continue;
                for (const auto& v : cpu->vertices) {
                    const glm::vec3 p =
                        glm::vec3(node_world[i] * glm::vec4(v.position, 1.0f));
                    const glm::vec3 d = p - center;
                    const float t = glm::dot(d, axis);            // axial proj
                    const glm::vec3 perp = d - t * axis;          // lateral
                    const float perp2 = glm::dot(perp, perp);
                    if (perp2 > lat2) continue;                   // outside tube
                    samples.push_back({t, perp2});
                }
            }
        }
    }

    if (static_cast<int>(samples.size()) < kGlowCapsuleMinCaptured) {
        const float half = kGlowCapsuleFallbackHalfLenFactor * widened;
        reg.aft  = -half;
        reg.fore =  half;
        return reg;
    }

    // Tight-radius selection: the gameplay radius is several times the nacelle's
    // visual cross-section, so the wide tube reaches into the laterally-offset
    // saucer. Fit fore/aft against only the vertices that hug the nacelle axis
    // (within kGlowCapsuleFitRadiusFrac * radius), which drops the saucer and
    // opens an axial gap for the gap-stop below. Fall back to the full set if
    // too few vertices hug the axis (e.g. sparse/degenerate geometry) so we
    // never regress below the old behaviour.
    const float fit_lat2 =
        (widened * kGlowCapsuleFitRadiusFrac) * (widened * kGlowCapsuleFitRadiusFrac);
    std::vector<float> ts;
    ts.reserve(samples.size());
    for (const auto& s : samples) {
        if (s.second <= fit_lat2) ts.push_back(s.first);
    }
    if (static_cast<int>(ts.size()) < kGlowCapsuleMinCaptured) {
        ts.clear();
        for (const auto& s : samples) ts.push_back(s.first);
    }

    // Gap-stop fit: the selected projections may still form several axial
    // clusters (the nacelle around the hardpoint plus a far cluster). Split the
    // sorted projections into contiguous runs separated by gaps wider than
    // `gap`, then keep the run that contains the hardpoint (t == 0), or — if
    // t == 0 falls in a gap — the run nearest to it. This drops disconnected far
    // clusters instead of stretching aft/fore to them.
    std::sort(ts.begin(), ts.end());
    const float gap = widened * kGlowCapsuleGapFrac;
    float best_aft = ts.front();
    float best_fore = ts.back();
    float best_dist = std::numeric_limits<float>::max();
    std::size_t start = 0;
    for (std::size_t i = 1; i <= ts.size(); ++i) {
        const bool boundary = (i == ts.size()) || (ts[i] - ts[i - 1] > gap);
        if (!boundary) continue;
        const float run_lo = ts[start];
        const float run_hi = ts[i - 1];
        // Distance from the hardpoint (t == 0) to this run; 0 if inside it.
        const float dist = (run_lo > 0.0f) ? run_lo
                         : (run_hi < 0.0f) ? -run_hi
                         : 0.0f;
        if (dist < best_dist) {
            best_dist = dist;
            best_aft = run_lo;
            best_fore = run_hi;
        }
        start = i;
    }
    reg.aft  = best_aft;
    reg.fore = best_fore;
    return reg;
}

GlowRegion add_sphere_region(const glm::vec3& center, float radius) {
    GlowRegion reg;
    reg.center = center;
    reg.axis   = glm::vec3(0.0f);
    reg.radius = radius;
    reg.aft    = 0.0f;
    reg.fore   = 0.0f;
    reg.active = true;
    return reg;
}

}  // namespace renderer
