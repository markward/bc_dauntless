#include "renderer/plating_damage.h"

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

}  // namespace renderer::plating
