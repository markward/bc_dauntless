#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <unordered_map>
#include <unordered_set>
#include <vector>

// The state the native sensor-detection kernel OWNS (spec §7.6.2-3): the
// Python module globals it replaces, held per Mirror and cleared with it.
//
//   latch          sensor_detection._broken   (observer, target) pairs whose
//                                             lock is broken
//   memo           sensor_detection._answers  (observer, target) -> answer
//                                             inside a step_memo block
//   walking_probes sensor_detection._walking_probes
//   tick_time      sensor_occlusion._tick_time (unset == Python None)
//   rock_cache     sensor_occlusion._rock_cache, per set
//   pair_cache     sensor_occlusion._pair_cache, per set
//
// Keys are mirror handles, which are generation-checked and never reused, so
// a dead object's key can never answer for a new one (the hazard Python's
// weak keying guards against). An unregistered Object row drops its latch
// pairs and memo entries; an unregistered Set row drops its two caches (the
// WeakKeyDictionary semantics). See sensor_detect.h for who reads what.

namespace dauntless::combat {

struct HandlePair {
    int64_t a, b;
    bool operator==(const HandlePair& o) const { return a == o.a && b == o.b; }
};

struct HandlePairHash {
    std::size_t operator()(const HandlePair& p) const noexcept {
        return std::hash<int64_t>()(p.a) ^
               (std::hash<int64_t>()(p.b) * 0x9E3779B97F4A7C15ull);
    }
};

// One major rock, frozen when its set's rock list was built:
// sensor_occlusion._major_rocks' (rock, x, y, z, r).
struct FrozenRock {
    int64_t rock;
    double x, y, z, r;
};

// sig = (now, _tick_time, len(ships_in(pset)), min_r) -> rocks
struct RockCacheEntry {
    double now;
    bool tick_set;
    double tick;
    std::size_t n_ships;
    double min_r;
    std::vector<FrozenRock> rocks;
};

// sig = (now, _tick_time, len(rocks)) -> {(observer, target): blocked}
struct PairCacheEntry {
    double now;
    bool tick_set;
    double tick;
    std::size_t n_rocks;
    std::unordered_map<HandlePair, bool, HandlePairHash> pairs;
};

// weapon_geometry.h's mount-position memo: subsystems._mounts, keyed
// (sub, ship_arg) -> (x, y, z). ship_arg is -1 for Python's None.
using MountMemo = std::unordered_map<HandlePair, std::array<double, 3>,
                                     HandlePairHash>;

struct SensorState {
    std::unordered_set<HandlePair, HandlePairHash> latch;
    std::unordered_map<HandlePair, bool, HandlePairHash> memo;
    bool walking_probes = false;
    bool tick_time_set = false;
    double tick_time = 0.0;
    std::unordered_map<int64_t, RockCacheEntry> rock_cache;
    std::unordered_map<int64_t, PairCacheEntry> pair_cache;
    MountMemo mounts;

    // Mirror::clear: every piece back to its Python import-time value.
    void clear();
    // Mirror::unregister_row of an Object row.
    void drop_object(int64_t h);
    // Mirror::unregister_row of a Set row.
    void drop_set(int64_t h);
    // Mirror::unregister_row of a Subsystem row.
    void drop_mounts_of(int64_t h);
};

}  // namespace dauntless::combat
