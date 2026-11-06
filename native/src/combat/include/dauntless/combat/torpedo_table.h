#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

// The K3 torpedo table (spec docs/superpowers/specs/2026-11-01-native-combat-
// k3-k4-design.md §4.3): one row per in-flight torpedo, in the order of
// engine/appc/projectiles.py's `_active`, holding every Torpedo field the K3
// kernel reads. Torpedoes have no Object row (they hide mirrored fields
// behind properties, native_combat._hidden_fields), so they are a separate
// table, synced exactly like TorpedoScan: a row is added at `_active.append`,
// dropped at remove, and any other list mutation empties the table and marks
// it dirty, to be rebuilt from Python in list order before K3 reads it.
//
// Handles are int64 counted up from 1 and never reused, so a handle a Python
// torpedo still holds after a clear or drop fails at once. Removal tombstones
// a row (alive = false) and compacts later, so rows() stays in insertion
// order; the kernel skips the dead rows.
//
// Ref fields hold combat-mirror handles (Object, Set, Subsystem; -1 None,
// kRefUnrepresentable -2). The table stores them as given; Mirror's
// set_torpedo_ref / set_torpedo_mount check the kind, and Mirror::torpedo_ref
// re-checks liveness at read time (a dead handle reads -2, never None).

namespace dauntless::combat {

// Keyed by the Python attribute each mirrors (the descriptor's name).
enum class TorpField : int32_t {
    // double
    _age, _ttl, _guidance_lifetime, _guidance_initial, _max_angular_accel,
    // 3 doubles + set flag (_velocity is always set)
    _velocity, _target_offset, _last_seen_target_pos, _last_target_vel,
    // refs: Object, Object, Set
    _target_ship, _source_ship, _containing_set,
    // (target, x, y, z, subsystem) or None: mount_sub, mount_attributed,
    // mount_offset
    _mount_key,
    // double: the hit K3 applies (native damage Task 4): the torpedo's
    // damage and its DamageRadiusFactor (weapon_splash_radius's R_hit)
    _damage, _damage_radius_factor,
    kCount
};

const char* torp_field_name(TorpField f);

// A torpedo's static visuals, read once at CreateTorpedoModel /
// CreateDisruptorModel (engine/appc/native_combat.py torpedo_visual_changed)
// and held for the native per-frame descriptor feed. Types are exactly what
// set_torpedoes takes: sizes are Python
// floats (double here; the feed casts to float32), colours are UNDIMMED
// `_color_tuple` results (the feed dims core/glow/flares by TORPEDO_BRIGHTNESS
// per frame), textures are `_resolve_game_texture` strings resolved at
// creation. `num_flares` and `id` are Python ints. `light_base` is Python's
// `max(glow_size_a, glow_size_b)` (argument order, so a NaN or tie reads as
// Python reads it); the raw glow sizes stay in the record.
struct TorpedoVisual {
    using Color = std::array<double, 4>;
    std::string core_texture, glow_texture, flares_texture;
    Color core_color{1, 1, 1, 1}, glow_color{1, 1, 1, 1},
          flares_color{1, 1, 1, 1}, shell_color{1, 1, 1, 1},
          bolt_core_color{1, 1, 1, 1};
    double core_size_a = 0.0, core_size_b = 0.0;
    double glow_size_a = 0.0, glow_size_b = 0.0, glow_size_c = 0.0;
    double flares_size_a = 0.0, flares_size_b = 0.0;
    int64_t num_flares = 0;
    int64_t id = 0;
    bool is_disruptor = false;
    double bolt_length = 0.0, bolt_width = 0.0;
    double light_base = 0.0;
};

struct TorpedoRow {
    using Vec3 = std::array<double, 3>;
    int64_t handle = 0;
    bool alive = true;
    // The torpedo's TransformStore handle (`_xform`), fixed at add.
    int64_t xform_index = -1, xform_gen = -1;
    double age = 0.0, ttl = 0.0, guidance_lifetime = 0.0,
           guidance_initial = 0.0, max_angular_accel = 0.0;
    double damage = 0.0, damage_radius_factor = 0.0;
    Vec3 vel{0, 0, 0};
    int64_t target = -1;
    Vec3 target_offset{0, 0, 0};
    bool target_offset_set = false;
    int64_t source = -1, cset = -1;
    Vec3 last_seen{0, 0, 0};
    bool last_seen_set = false;
    Vec3 last_tvel{0, 0, 0};
    bool last_tvel_set = false;
    // `_mount_key`: attributed = the key is not None AND its target IS the
    // torpedo's `_target_ship` (Python's `key[0] is target`, computed by
    // Python on a write of either); mount_offset = key[1:4]; mount_sub =
    // key[4] (-1 None).
    int64_t mount_sub = -1;
    bool mount_attributed = false;
    Vec3 mount_offset{0, 0, 0};
    // Bit (1 << TorpField) per field whose last Python value the row cannot
    // hold (a non-number lifetime, a last-seen point that is neither None
    // nor a TGPoint3, ...). The kernel must hand such a torpedo to Python.
    // A later good push of the field clears its bit.
    uint32_t unrepresentable = 0;
    // False until the visual record is pushed (a torpedo whose model was
    // never created): the native feed treats that as unrepresentable.
    bool visual_set = false;
    TorpedoVisual visual;
};

class TorpedoTable {
public:
    using Vec3 = TorpedoRow::Vec3;

    int64_t add(int64_t xform_index, int64_t xform_gen);
    // False when `h` is not a live row.
    bool drop(int64_t h);
    void clear();
    std::size_t size() const { return index_.size(); }

    TorpedoRow* find(int64_t h);
    const TorpedoRow* find(int64_t h) const;
    // Throws std::invalid_argument (Python ValueError) unless `h` is live.
    TorpedoRow& checked(int64_t h);

    // Insertion order, tombstones included (alive = false).
    const std::vector<TorpedoRow>& rows() const { return rows_; }
    // Live handles, in insertion order.
    std::vector<int64_t> handles() const;

    // Each throws std::invalid_argument for a stale handle or a field of
    // another type. A successful set clears the field's unrepresentable bit.
    void set_f(int64_t h, TorpField f, double v);
    void set_v(int64_t h, TorpField f, bool is_set, const Vec3& v);
    void set_ref(int64_t h, TorpField f, int64_t ref);
    void set_mount(int64_t h, bool attributed, int64_t sub, const Vec3& off);
    void set_unrepresentable(int64_t h, TorpField f);
    // Throws std::invalid_argument for a stale handle.
    void set_visual(int64_t h, const TorpedoVisual& v);
    // The row holds no visual record (a record the binding could not take
    // replaces the one before it with none). Throws as set_visual.
    void clear_visual(int64_t h);

private:
    void compact();

    std::vector<TorpedoRow> rows_;
    std::unordered_map<int64_t, std::size_t> index_;
    std::size_t dead_ = 0;
    int64_t next_ = 1;
};

}  // namespace dauntless::combat
