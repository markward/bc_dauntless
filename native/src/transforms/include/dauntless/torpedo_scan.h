#pragma once

#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "dauntless/transform_store.h"

namespace dauntless {

// The in-flight torpedo table behind BC's AIScriptAssist_GetIncomingTorpIDsInSet
// ("which torpedoes are coming at me?"). engine/appc/projectiles.py keeps it in
// step with its `_active` list: a row per torpedo, added and removed with the
// list, its velocity, source and set group updated whenever the torpedo's own
// change. Positions are NOT copied: each row holds the torpedo's transform
// handle and reads the store live, so motion needs no sync at all.
//
// Why native: every NPC asks this every 0.15 s and the answer walks every
// torpedo in flight. A 64-ship fight keeps ~1,500 torpedoes up (BC's 60 s
// default lifetime), and the Python walk was over half of all AI time.
//
// `incoming` must give exactly the answer of projectiles._closing_time +
// _matches_source for every row, bit for bit — the two are run against each
// other by tests/unit/test_torpedo_scan_conformance.py. The arithmetic is in
// the same order as the Python, in double, and its source file is compiled
// with floating-point contraction OFF: a fused multiply-add would round
// differently from CPython and could flip a borderline threshold compare.
//
// `group` names the set the torpedo is in (Python passes id(set); 0 = in no
// set). The caller hands `incoming` the offset of each group it can see from
// the observer's set (frames.offset_between); a row whose group is not listed
// is in another frame and is never incoming.
//
// Results come back in insertion order — the order of `_active`, which is what
// the Python walk returned. Removal tombstones a row and compacts later, so
// the order survives.
class TorpedoScan {
public:
    struct GroupOffset {
        std::int64_t group;
        double off[3];
    };

    explicit TorpedoScan(const TransformStore& store) : store_(store) {}

    // Adds a row, or updates the row in place if `id` is already present.
    void add(std::int64_t id, std::uint32_t xform_index,
             std::uint32_t xform_generation, double vx, double vy, double vz,
             bool has_source, std::int64_t source, std::int64_t group);
    // False when `id` was not in the table. The setters ignore unknown ids.
    bool remove(std::int64_t id);
    void set_velocity(std::int64_t id, double vx, double vy, double vz);
    void set_source(std::int64_t id, bool has_source, std::int64_t source);
    void set_group(std::int64_t id, std::int64_t group);
    void clear();
    std::size_t size() const { return index_.size(); }

    // Ids of the torpedoes that will reach the observer (position `obs`,
    // velocity `obs_vel`, in its own set) within `threshold` seconds. With
    // `match_source`, only torpedoes fired by `firing_id`.
    std::vector<std::int64_t> incoming(
        const double obs[3], const double obs_vel[3], double threshold,
        bool match_source, std::int64_t firing_id,
        const std::vector<GroupOffset>& offsets) const;

private:
    struct Row {
        std::int64_t id;
        std::uint32_t xi, xg;
        double vel[3];
        bool has_source;
        std::int64_t source;
        std::int64_t group;
        bool alive;
    };

    Row* find(std::int64_t id);
    void compact();

    const TransformStore& store_;
    std::vector<Row> rows_;
    std::unordered_map<std::int64_t, std::size_t> index_;
    std::size_t dead_ = 0;
};

// The process-wide table, over transform_store().
TorpedoScan& torpedo_scan();

}  // namespace dauntless
