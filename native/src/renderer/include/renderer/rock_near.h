// native/src/renderer/include/renderer/rock_near.h
// Rock fields, near band (docs/superpowers/specs/2026-10-02-rock-fields-design.md):
// real rocks streamed in deterministic cells around a centre, sampled from
// the one density field every band shares (far::field_density).
#pragma once
#include <cstdint>
#include <functional>
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>
#include <renderer/far_field.h>

namespace renderer::rockfield {

enum class NearClass : std::uint8_t { Small = 0, Large = 1 };

struct NearClassDials {
    float density = 0.008f;     // rocks / GU^3 where field_density == 1
    float r_min = 0.05f, r_max = 0.5f, exponent = 2.5f;
    float cell_gu = 10.0f;
    float mesh_gu = 20.0f;      // mesh out to here (camera distance)
    float billboard_gu = 30.0f; // billboard out to here; streamed radius
    int max_instances = 4000;   // per camera build
};

struct NearDials {   // defaults MUST equal far_dials.py DEFAULTS near_* keys
    NearClassDials small{};
    NearClassDials large{1.0f / 8000.0f, 1.0f, 5.0f, 2.5f, 20.0f, 50.0f, 60.0f, 1000};
    float fade_gu = 4.0f;                 // dither band width at each tier edge
    float stream_margin_gu = 10.0f;       // keep cells this far past range (hysteresis)
    float collide_cooldown_s = 0.5f;      // per large rock
    float collide_margin_gu = 0.0f;
};

struct NearRock {
    glm::dvec3 pos_sys{0.0};
    float radius = 0.0f;
    int rock = 0;                    // catalogue index (fragment for Small, major for Large)
    glm::vec3 tumble_axis{0, 0, 1};
    float tumble_rate = 0.0f, phase = 0.0f;
};

struct NearCatalogue {               // pushed with far_set_catalogue
    std::vector<int> small_rocks;    // catalogue indices of silicate-family fragments
    std::vector<int> large_rocks;    // catalogue indices of silicate-family majors
};

// Pure: the rocks of one cell. Poisson(n_bound * L^3) candidates, each
// accepted with probability density * field_density(x) / n_bound, where
// n_bound = density * a_bound(cell) * noise_m_bound(s). Fixed draw order per
// candidate: position (3), accept, size, rock, tumble axis (2), rate, phase.
std::vector<NearRock> generate_near_cell(const far::DiscSource& s, NearClass cls,
                                         const glm::i64vec3& ijk, const NearDials& d,
                                         const NearCatalogue& cat);

struct NearStats { int cells = 0; int small = 0; int large = 0; int ghosted = 0; };

class NearField {
public:
    void set_dials(const NearDials&);      // a generator change clears every cell
    const NearDials& dials() const { return dials_; }
    void set_catalogue(NearCatalogue);     // clears every cell
    // The far tier's active sources (FarField::active_sources(), system coords).
    void set_sources(const std::vector<far::DiscSource>& active);  // clears on change
    // Generate cells newly in range of `centre_sys`, drop cells out of range +
    // stream_margin_gu. Range per class = billboard_gu.
    void stream(const glm::dvec3& centre_sys);
    void clear();                          // cells, contacts, sweep state, cooldowns, ghosts
    NearStats stats() const;
    // Every rock currently streamed, per class (tests, build, contacts).
    void for_each(NearClass cls, const std::function<void(std::uint64_t key, const NearRock&)>& fn) const;
private:
    struct Cell {
        NearClass cls;
        std::vector<NearRock> rocks;
        glm::dvec3 lo{0.0};              // system-space AABB min corner
        double size = 0.0;               // edge (the class's cell_gu when generated)
    };
    // key: mix(source id, class, i, j, k); rock key = mix(cell key, index + 1)
    std::unordered_map<std::uint64_t, Cell> cells_;
    NearDials dials_;
    NearCatalogue cat_;
    std::vector<far::DiscSource> sources_;
};

}  // namespace renderer::rockfield
