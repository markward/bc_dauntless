#include "renderer/plating_damage.h"

#include <algorithm>
#include <cmath>

namespace renderer::plating {

DamageList build_damage_list(const scenegraph::HullDamageStore& store,
                             const float* params) {
    using scenegraph::HullDamageKind;
    DamageList out;
    float total = 0.0f;
    for (const auto& r : store.records()) {
        // Inactive slots keep stale data; a record with no wear adds nothing.
        if (!r.active || r.wear <= 0.0f || out.count >= kMaxDamage) continue;
        const int i = out.count;
        if (r.kind == HullDamageKind::Surface) {
            out.a[i] = glm::vec4(r.centre_body, r.reach * params[7]);
            out.b[i] = glm::vec4(r.normal_body, r.wear);
            out.c[i] = glm::vec4(1.0f, 0.0f, 0.0f, 0.0f);
        } else if (r.kind == HullDamageKind::Internal) {
            out.a[i] = glm::vec4(r.centre_body, r.reach);
            out.b[i] = glm::vec4(0.0f, 0.0f, 0.0f, r.wear);
            out.c[i] = glm::vec4(3.0f, 0.0f, 0.0f, 0.0f);
        } else {
            continue;
        }
        out.node[i] = r.node;
        total += r.wear;
        ++out.count;
    }
    out.torn_possible = out.count > 0 && total >= params[16] * (1.0f - 0.4f * params[22]) - params[23] -
                                            0.75f * params[19];
    return out;
}

bool record_in_frame(const DamageList& list, int k, const std::vector<glm::mat4>& node_fix,
                     const glm::mat4& frame) {
    const int n = list.node[k];
    if (n < 0 || static_cast<std::size_t>(n) >= node_fix.size())
        return frame == glm::mat4(1.0f);
    return node_fix[static_cast<std::size_t>(n)] == frame;
}

DamageList records_in_frame(const DamageList& list, const std::vector<glm::mat4>& node_fix,
                            const glm::mat4& frame) {
    DamageList out;
    out.torn_possible = list.torn_possible;
    for (int k = 0; k < list.count; ++k) {
        if (!record_in_frame(list, k, node_fix, frame)) continue;
        out.a[out.count] = list.a[k];
        out.b[out.count] = list.b[k];
        out.c[out.count] = list.c[k];
        out.node[out.count] = list.node[k];
        ++out.count;
    }
    return out;
}

bool wants_plating(const DamageList& list, const float* params) {
    return params[0] > 0.5f && list.count > 0;
}

float plating_margin(const float* params) {
    return params[5] + params[6] + params[15] + params[2];
}

// Derivation (opaque.frag, PLATING; every place a pixel at body point p reads
// a damage record):
//   - main / apply_plating / plating_hole read wear, internal wear and the
//     wear gradient AT p.
//   - apply_plating reads the cell wear at p's panel centre ctr(p)
//     (plating_cell_wear), and in its plate-edge march, at qw = p + ray * t
//     for t = (j + 0.5) / 4 * Dp, j < 4, both the wear at qw (plating_tear)
//     and the cell wear at ctr(qw). ray = -Vb / max(dot(Vb, n), 0.25), so
//     |ray| <= 4 and |qw - p| <= 4 * 0.875 * Dp = 3.5 * Dp.
//   - Nothing else reads a record. The member-top, member-side and inner-hull
//     samples (and plating_hole's member test) are warped by member bend, but
//     they read only member distances, noise and the breach threshold, never
//     wear: the bend dial moves no wear sample.
// So every wear sample lies within 3.5 * Dp + C of p, where C bounds the
// panel-centre offset |ctr(q) - q| of the chart the pixel's part uses
// (plating_sample; F = params[2], S = params[3]; the ku / kv panel
// subdivisions only shrink it, so they are bounded by one):
//   - box (also the no-parts fallback): centre moves along A0 by at most F / 2
//     and along the in-surface axis V by at most S / 2, orthogonal:
//     C = sqrt((F/2)^2 + (S/2)^2).
//   - disc: radial |rc - r| <= S / 2; angular |dth| <= pi / N with
//     N = 25 * 2^band (round(2 pi * 4F / F) = 25 spokes, doubling per band)
//     and r < 8F * 2^band, so r * |dth| < 8 pi F / 25 < 1.006 F (the outer
//     edge of a band, where a cell is ~2F wide). |ctr - q|^2 =
//     (rc - r)^2 + 4 rc r sin^2(dth / 2) <= (S/2)^2 + (r dth)^2 + (S/2) dth r dth
//     <= (S/2)^2 + (1.006 F + 0.032 S)^2.
//   - cylinder: axial offset <= F / 2; the centre keeps the point's own
//     radius rho and moves round by |dth| <= pi / N,
//     N = max(6, floor(2 pi R / S + 0.5)), R = max(0.8 max(h1, h2), 1): a chord
//     of 2 rho sin(pi / (2N)). rho is unbounded by the dials alone (a point
//     far outside the fitted tube that still belongs to it), so it is taken
//     at its largest over `body_box` grown by 3.5 * Dp (distance to a line is
//     convex: the largest is at a corner).
// A record left out of a mesh's subset is then further than its reach from
// every wear sample of every pixel of the mesh, so it adds nothing. The cull
// margin also never falls below the shader's own near-test margin
// (plating_margin), so a left-out record never decides plating_near either.
// The constants carry a little rounding slack; a wider margin only keeps
// more records, which is always safe.
float plating_cull_margin(const float* params,
                          const std::vector<voxel::StructurePart>* parts,
                          const Aabb& body_box) {
    const float F = std::max(params[2], 0.0f);
    const float S = std::max(params[3], 0.0f);
    const float march = 3.5f * std::max(params[5], 0.0f);
    float c = std::sqrt(0.25f * F * F + 0.25f * S * S);   // box chart, always possible
    if (parts != nullptr) {
        const glm::vec3 grown = body_box.half_extents + glm::vec3(march);
        for (const auto& part : *parts) {
            if (part.kind == voxel::PartKind::Disc) {
                const float ang = 1.01f * F + 0.035f * S;
                c = std::max(c, std::sqrt(0.25f * S * S + ang * ang));
            } else if (part.kind == voxel::PartKind::Cylinder) {
                const float R = std::max(0.8f * std::max(part.half_extent.y, part.half_extent.z),
                                         1.0f);
                const float N = S > 0.0f
                    ? std::max(6.0f, std::floor(6.2831853f * R / S + 0.5f)) : 6.0f;
                const glm::vec3 axis = glm::normalize(part.axis[0]);
                float rho = 0.0f;
                for (int k = 0; k < 8; ++k) {
                    const glm::vec3 corner =
                        body_box.center +
                        glm::vec3((k & 1) ? grown.x : -grown.x, (k & 2) ? grown.y : -grown.y,
                                  (k & 4) ? grown.z : -grown.z);
                    const glm::vec3 off = corner - part.centre;
                    rho = std::max(rho, glm::length(off - axis * glm::dot(off, axis)));
                }
                const float chord = 2.0f * rho * std::sin(3.14159265f / (2.0f * N));
                c = std::max(c, std::sqrt(0.25f * F * F + chord * chord));
            }
        }
    }
    return std::max(plating_margin(params), (march + c) * 1.001f + 0.01f);
}

int records_near(const DamageList& list, const Aabb& body_box, float margin,
                 std::array<std::uint8_t, kMaxDamage>& out) {
    const glm::vec3 lo = body_box.center - body_box.half_extents;
    const glm::vec3 hi = body_box.center + body_box.half_extents;
    int n = 0;
    for (int i = 0; i < list.count; ++i) {
        const glm::vec3 c(list.a[i]);
        const glm::vec3 d = c - glm::clamp(c, lo, hi);
        const float reach = list.a[i].w + margin;
        // Slack: 1% of the reach plus a quarter model unit (see the header).
        const float grown = reach * 1.01f + 0.25f;
        if (glm::dot(d, d) <= grown * grown) out[static_cast<std::size_t>(n++)] =
            static_cast<std::uint8_t>(i);
    }
    return n;
}

std::vector<MeshRecordSubset> mesh_record_subsets(
        const DamageList& list, const std::vector<Aabb>& boxes, const float* params,
        const std::vector<voxel::StructurePart>* parts) {
    std::vector<MeshRecordSubset> out(boxes.size());
    for (std::size_t k = 0; k < boxes.size(); ++k)
        out[k].count = records_near(list, boxes[k],
                                    plating_cull_margin(params, parts, boxes[k]), out[k].idx);
    return out;
}

DeckBreakSet deck_break_subset(const DamageList& list, const float* params) {
    const float threshold = params[24] - 1.25f * std::fabs(params[19]);
    // Rounding slack: keeping an extra record is always safe.
    const float keep_at = threshold - 1e-4f * std::max(1.0f, std::fabs(threshold));
    DeckBreakSet out;
    for (int i = 0; i < list.count; ++i) {
        const glm::vec3 ci(list.a[i]);
        float sum = 0.0f;
        for (int j = 0; j < list.count; ++j) {
            const float reach = list.a[i].w + list.a[j].w;
            const float grown = reach * 1.001f + 1e-3f;
            const glm::vec3 d = glm::vec3(list.a[j]) - ci;
            if (glm::dot(d, d) <= grown * grown) sum += list.b[j].w;
        }
        if (sum >= keep_at) out.idx[static_cast<std::size_t>(out.count++)] = i;
    }
    return out;
}

DeckBreakSet full_deck_break_set(const DamageList& list) {
    DeckBreakSet out;
    for (int i = 0; i < list.count; ++i) out.idx[static_cast<std::size_t>(i)] = i;
    out.count = list.count;
    return out;
}

}  // namespace renderer::plating
