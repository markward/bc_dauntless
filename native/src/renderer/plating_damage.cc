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
        total += r.wear;
        ++out.count;
    }
    out.torn_possible = out.count > 0 && total >= params[16] * (1.0f - 0.4f * params[22]) - params[23] -
                                            0.75f * params[19];
    return out;
}

bool wants_plating(const DamageList& list, const float* params) {
    return params[0] > 0.5f && list.count > 0;
}

float plating_margin(const float* params) {
    return params[5] + params[6] + params[15] + params[2];
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
