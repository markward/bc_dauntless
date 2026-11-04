#pragma once

#include <cstdint>
#include <span>
#include <unordered_map>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

// The published-pose buffer (native motion phase 2, Task 6): at the end of
// each motion stage every ship row's pose and velocity is copied here, tagged
// with the stage's tick number, so later phases (render, hit tests, combat)
// can read the poses motion published for the tick. Each publish REPLACES
// the contents.
//
// THE READ WINDOW (phase 4, Task 4): publish opens it; close() (Python:
// native_motion.close_published, at the top of every GameLoop.tick, at the
// end of host_loop._advance_combat and before a boundary-owning GameLoop's
// effect_queue.boundary()) and clear() close it. While it is open the combat
// kernels' pose reads (read_pose below: detail::xform, K4's position, native
// can_detect's _get_xyz) and the host's gameplay hit pose (host_bindings.cc
// hit_pose_of) answer from pose_for, keyed by the
// published row's store slot; a slot not published (a ship spawned after the
// publish, a freed and reused slot) and every read outside the window take
// the live store. Inside the window the two agree (spec 2026-11-03 §6: no
// stage writes a ship pose between the publish and combat).
//
// The tick tag is a per-publish counter (native_motion._tick: +1 per motion
// stage), NOT the GameLoop tick: phases 3-4 must not compare the two. The
// roster is the non-rock ships in set-iteration order, read at publish time
// (the end of the stage). A row whose _velocity is not a TGPoint3
// (_velocity_state 2) is skipped, like -1, a stale handle and an invalid
// transform.
//
// The buffer is an UNSYNCHRONISED global: every writer and reader is the
// main thread. The writers hold the GIL (a short copy; the mirror is not
// written); a kernel's reads may run with it released (K2/K3's trace hooks),
// still on the main thread, while nothing publishes.
namespace dauntless::combat {

struct PublishedPose {
    int64_t object;   // the mirror's Object handle
    double pos[3];
    double rot[9];    // row-major, the store's layout
    double vel[3];    // the row's _velocity
};

class PublishedPoses {
public:
    // Replace the contents with `objects`' poses, tagged `tick`. Skips -1, a
    // stale or non-Object handle, and an invalid transform.
    void publish(const Mirror& m, const dauntless::TransformStore& store,
                 const std::vector<int64_t>& objects, int64_t tick);
    int64_t tick() const { return tick_; }
    const PublishedPose* find(int64_t object) const;
    std::span<const PublishedPose> all() const { return poses_; }
    void clear();  // also closes the window

    // The published pose of store slot (index, gen), or nullptr when the
    // window is closed or the slot was not published.
    const TransformStore::Transform* pose_for(uint32_t xform_index,
                                              uint32_t xform_gen) const;
    void close() { open_ = false; }
    bool is_open() const { return open_; }

private:
    int64_t tick_ = 0;
    bool open_ = false;
    std::vector<PublishedPose> poses_;
    // pose_for's backing: the published transforms, and their index by
    // slot key (index << 32 | gen).
    std::vector<TransformStore::Transform> xforms_;
    std::unordered_map<uint64_t, size_t> by_slot_;
};

PublishedPoses& published_poses();  // process-wide

// THE pose a gameplay read takes for store slot (index, gen), which the
// caller has already checked valid: the published pose inside the read
// window, else the live slot. detail::xform, K4's position, native
// can_detect's _get_xyz and the host's hit_pose_of all read through it.
// It consults the PROCESS-WIDE published_poses() singleton whatever store or
// Mirror the caller holds: a gtest building its own Mirror must never
// publish into the singleton (it would answer that test's slot numbers for
// every later case in the binary); publish into a local PublishedPoses.
inline const TransformStore::Transform& read_pose(const TransformStore& store,
                                                  uint32_t index,
                                                  uint32_t gen) {
    if (const auto* p = published_poses().pose_for(index, gen)) return *p;
    return store.at(index);
}

// What detail::xform answers for Object handle `h` right now (the
// combat_pose_read test binding): the published pose inside the window, else
// the live slot. Throws std::invalid_argument where detail::xform falls back.
const TransformStore::Transform& combat_pose(const Mirror& m, int64_t h);

}  // namespace dauntless::combat
