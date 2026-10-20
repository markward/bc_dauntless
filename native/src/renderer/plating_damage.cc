#include "renderer/plating_damage.h"

namespace renderer::plating {

DamageList build_damage_list(const scenegraph::DamageDecalRing& ring,
                             const float* params) {
    using scenegraph::WeaponClass;
    DamageList out;
    float total = 0.0f;
    for (const auto& d : ring.slots()) {
        if (!d.active || out.count >= kMaxDamage) continue;
        const int i = out.count;
        if (d.weapon_class == WeaponClass::Scorch && d.wear > 0.0f) {
            out.a[i] = glm::vec4(d.point_body, d.radius * params[7]);
            out.b[i] = glm::vec4(d.normal_body, d.wear);
            out.c[i] = glm::vec4(1.0f, 0.0f, 0.0f, 0.0f);
        } else if (d.weapon_class == WeaponClass::Internal) {
            out.a[i] = glm::vec4(d.point_body, d.radius);
            out.b[i] = glm::vec4(0.0f, 0.0f, 0.0f, d.wear);
            out.c[i] = glm::vec4(3.0f, 0.0f, 0.0f, 0.0f);
        } else {
            continue;
        }
        total += d.wear;
        ++out.count;
    }
    out.torn_possible = out.count > 0 && total >= params[16] - 0.75f * params[19];
    return out;
}

bool wants_plating(const DamageList& list, const float* params) {
    return params[0] > 0.5f && list.count > 0;
}

}  // namespace renderer::plating
