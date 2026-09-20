// native/src/scenegraph/src/damage_decals.cc
#include "scenegraph/damage_decals.h"

#include <algorithm>
#include <cmath>

namespace scenegraph {

glm::vec3 world_to_body(const glm::mat4& ship_world, const glm::vec3& p_world) {
    return glm::vec3(glm::inverse(ship_world) * glm::vec4(p_world, 1.0f));
}

glm::vec3 world_dir_to_body(const glm::mat4& ship_world, const glm::vec3& dir_world) {
    glm::vec3 b = glm::mat3(glm::inverse(ship_world)) * dir_world;
    float len = glm::length(b);
    return len > 0.0f ? b / len : b;
}

glm::vec3 tangent_on_surface(const glm::vec3& normal, const glm::vec3& hint) {
    const float nl = glm::length(normal);
    const glm::vec3 n = nl > 0.0f ? normal / nl : glm::vec3(0.0f, 0.0f, 1.0f);
    glm::vec3 t = hint - n * glm::dot(hint, n);
    float tl = glm::length(t);
    if (tl < 1e-6f) {
        // Pick the world axis least aligned with n so the cross is well-conditioned.
        const glm::vec3 a = std::abs(n.x) < std::abs(n.y)
            ? (std::abs(n.x) < std::abs(n.z) ? glm::vec3(1, 0, 0) : glm::vec3(0, 0, 1))
            : (std::abs(n.y) < std::abs(n.z) ? glm::vec3(0, 1, 0) : glm::vec3(0, 0, 1));
        t = glm::cross(n, a);
        tl = glm::length(t);
    }
    return t / tl;
}

void DamageDecalRing::add(const glm::vec3& point_body, const glm::vec3& normal_body,
                          float radius, float intensity, WeaponClass weapon_class,
                          float now, const glm::vec3& tangent_body) {
    const float clamped_in = std::clamp(intensity, 0.0f, 1.0f);
    const glm::vec3 tangent = (weapon_class == WeaponClass::Scuff)
        ? tangent_on_surface(normal_body, tangent_body)
        : glm::vec3(0.0f);

    // 1. Merge into a co-located same-class decal — persistent classes only
    //    (Scorch, Scuff). Scorch is persistent, so co-located torpedo/disruptor
    //    hits should deepen one deposit. Scuff is also persistent; co-located
    //    scrapes should deepen and update the slip direction. HeatGlow (phaser)
    //    is transient and must NOT merge: merging re-ignites birth_time, pinning
    //    an actively-hit area bright so it never visibly cools. Keeping each
    //    glow independent lets it age out on its own.
    if (weapon_class == WeaponClass::Scorch || weapon_class == WeaponClass::Scuff) {
        const float merge_dist = kMergeFactor * radius;
        for (auto& d : slots_) {
            if (!d.active || d.weapon_class != weapon_class) continue;
            if (glm::length(point_body - d.point_body) <= merge_dist) {
                d.intensity = std::min(1.0f, d.intensity + clamped_in);
                d.birth_time = now;          // re-ignite ember
                d.normal_body = normal_body; // freshest surface normal
                d.tangent_body = tangent;    // freshest slip direction (Scuff)
                d.seq = next_seq_++;         // refresh FIFO age (reinforced scar
                                             // survives eviction over older ones)
                return;
            }
        }
    }

    // 2. Allocate the first free slot, else 3. evict.
    DamageDecal* target = nullptr;
    for (auto& d : slots_) {
        if (!d.active) { target = &d; break; }
    }
    if (target == nullptr) {
        // Prefer evicting the oldest transient HeatGlow so a persistent Scorch
        // or Scuff is never pushed out by phaser flooding. Only if there is no
        // HeatGlow to reclaim do we evict the oldest decal overall.
        DamageDecal* oldest_glow = nullptr;
        DamageDecal* oldest_any = &slots_[0];
        for (auto& d : slots_) {
            if (d.seq < oldest_any->seq) oldest_any = &d;
            if (d.weapon_class == WeaponClass::HeatGlow
                && (oldest_glow == nullptr || d.seq < oldest_glow->seq)) {
                oldest_glow = &d;
            }
        }
        target = (oldest_glow != nullptr) ? oldest_glow : oldest_any;
    }

    *target = DamageDecal{
        point_body, normal_body, radius, clamped_in,
        now, weapon_class, /*active=*/true, next_seq_++,
    };
    target->tangent_body = tangent;
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
