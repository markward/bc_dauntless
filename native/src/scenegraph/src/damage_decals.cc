// native/src/scenegraph/src/damage_decals.cc
#include "scenegraph/damage_decals.h"

#include <algorithm>

namespace scenegraph {

glm::vec3 world_to_body(const glm::mat4& ship_world, const glm::vec3& p_world) {
    return glm::vec3(glm::inverse(ship_world) * glm::vec4(p_world, 1.0f));
}

glm::vec3 world_dir_to_body(const glm::mat4& ship_world, const glm::vec3& dir_world) {
    glm::vec3 b = glm::mat3(glm::inverse(ship_world)) * dir_world;
    float len = glm::length(b);
    return len > 0.0f ? b / len : b;
}

void DamageDecalRing::add(const glm::vec3& point_body, const glm::vec3& normal_body,
                          float radius, float intensity, WeaponClass weapon_class,
                          float now) {
    const float clamped_in = std::clamp(intensity, 0.0f, 1.0f);

    // 1. Merge into a co-located same-class decal.
    const float merge_dist = kMergeFactor * radius;
    for (auto& d : slots_) {
        if (!d.active || d.weapon_class != weapon_class) continue;
        if (glm::length(point_body - d.point_body) <= merge_dist) {
            d.intensity = std::min(1.0f, d.intensity + clamped_in);
            d.birth_time = now;          // re-ignite ember
            d.normal_body = normal_body; // freshest surface normal
            return;
        }
    }

    // 2. Allocate the first free slot, else 3. evict the oldest.
    DamageDecal* target = nullptr;
    for (auto& d : slots_) {
        if (!d.active) { target = &d; break; }
    }
    if (target == nullptr) {
        target = &slots_[0];
        for (auto& d : slots_) {
            if (d.seq < target->seq) target = &d;
        }
    }

    *target = DamageDecal{
        point_body, normal_body, radius, clamped_in,
        now, weapon_class, /*active=*/true, next_seq_++,
    };
}

void DamageDecalRing::tick(float now) {
    for (auto& d : slots_) {
        if (d.active && d.weapon_class == WeaponClass::HeatGlow
            && (now - d.birth_time) > kHeatGlowLifetime) {
            // Deactivate only; the slot's stale point/normal/seq remain until
            // add() fully overwrites it. Readers of slots() (e.g. the Phase 2
            // shader upload) must filter on `active`, not on zeroed fields.
            d.active = false;
        }
    }
}

std::size_t DamageDecalRing::count() const {
    std::size_t n = 0;
    for (const auto& d : slots_) if (d.active) ++n;
    return n;
}

}  // namespace scenegraph
