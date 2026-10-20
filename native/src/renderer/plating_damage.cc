#include "renderer/plating_damage.h"

namespace renderer::plating {

// A full ring always fits the list, so build_damage_list(ring) never drops a
// record (the count guard below only matters for a raw slot span).
static_assert(kMaxDamage >= static_cast<int>(scenegraph::DamageDecalRing::kMaxDecals),
              "the plating damage list must hold every ring slot");

DamageList build_damage_list(const scenegraph::DamageDecal* slots, std::size_t n,
                             const float* params) {
    using scenegraph::WeaponClass;
    DamageList out;
    float total = 0.0f;
    for (std::size_t s = 0; s < n; ++s) {
        const auto& d = slots[s];
        // Inactive slots keep stale data (DamageDecalRing::tick only clears
        // `active`); a record with no wear adds nothing to the layer.
        if (!d.active || d.wear <= 0.0f || out.count >= kMaxDamage) continue;
        const int i = out.count;
        if (d.weapon_class == WeaponClass::Scorch) {
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

DamageList build_damage_list(const scenegraph::DamageDecalRing& ring,
                             const float* params) {
    return build_damage_list(ring.slots().data(), ring.slots().size(), params);
}

bool wants_plating(const DamageList& list, const float* params) {
    return params[0] > 0.5f && list.count > 0;
}

}  // namespace renderer::plating
