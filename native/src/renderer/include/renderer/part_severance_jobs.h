// native/src/renderer/include/renderer/part_severance_jobs.h
//
// The structure-severance check (find_severed_parts) on a worker thread
// (layered damage phase 4, final review Ruling 10). On the main thread a
// check that found a broken voxel cost a single-frame stall of >= 8-11 ms
// (Debug; perf-register SIG-113) every 0.5 s through a death.
//
// poll() is the whole protocol, called from the main thread only:
//   - no job for the instance: the same gates and unchanged-hull stamp as
//     split_severed_parts; then queue ONE job, owning every input BY VALUE
//     (a shared reference to the immutable segmentation, the DamageList, the
//     deck break, the parts already lost), and answer `pending`;
//   - a job still running: `pending`;
//   - a finished job: apply it (apply_severed_pieces: chunk instances, the
//     parent's severed mask, the stamp) only if the instance still exists and
//     its damage-store revision, severed mask, deck break and segmentation
//     are all what the job was queued with. Otherwise the result is DROPPED
//     and a fresh job is queued at once (`pending` again).
// The worker never touches an Instance, the World, GL or Python. A job whose
// instance is forgotten (destroyed, world reset) keeps running to completion
// on its own inputs and its result is discarded.
#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <unordered_map>
#include <vector>

#include "renderer/part_severance_check.h"
#include "renderer/plating_damage.h"
#include "scenegraph/instance.h"
#include "scenegraph/world.h"
#include "voxel/structure_parts.h"

namespace renderer {

struct SplitPoll {
    bool pending = false;              // a job is (now) running: poll again
    std::vector<SeveredSplit> split;   // what was applied (empty if pending)
};

class SeveranceJobs {
public:
    // The parent's damage list, built on the main thread when a job is queued.
    using DamageFn = std::function<plating::DamageList(const scenegraph::Instance&)>;

    SeveranceJobs() = default;
    // Waits for running jobs: they own their inputs, so this is only a wait.
    ~SeveranceJobs() = default;
    SeveranceJobs(const SeveranceJobs&) = delete;
    SeveranceJobs& operator=(const SeveranceJobs&) = delete;

    // See the file comment. `seg` null = parts not detected yet: nothing to
    // do (not pending). Rocks, chunks, articulated/rigged hulls, skinned
    // models and stale ids never sever (and drop any job they had).
    SplitPoll poll(scenegraph::World& world, scenegraph::InstanceId parent,
                   std::shared_ptr<const voxel::StructureSegmentation> seg,
                   const DamageFn& damage, float deck_break, bool skinned = false,
                   SeveranceStats* stats = nullptr);

    // Discard `id`'s job, if any, without waiting for it.
    void forget(scenegraph::InstanceId id);
    // Discard every job (the world was reset), without waiting.
    void clear();

    // Whether `id` has a job queued (finished or not).
    bool has_job(scenegraph::InstanceId id) const;
    // Jobs queued plus discarded ones still running.
    std::size_t outstanding() const;

    // Test: block until `id`'s job (if any) has finished. Never in production.
    void wait_for_test(scenegraph::InstanceId id);
    // Test: run on the worker at the start of every job queued from now on.
    void set_before_run_for_test(std::function<void()> hook);

private:
    struct Result {
        std::vector<SeveredPiece> pieces;
        int total_voxels = 0;
    };
    struct Job {
        std::future<Result> result;
        std::shared_ptr<const voxel::StructureSegmentation> seg;
        std::uint32_t revision = 0;
        std::uint32_t severed = 0;
        float deck_break = 0.0f;
    };
    static std::uint64_t key(scenegraph::InstanceId id) {
        return (static_cast<std::uint64_t>(id.index) << 32) | id.generation;
    }
    static bool finished(const std::future<Result>& f);
    void reap();   // drop discarded jobs that have finished

    std::unordered_map<std::uint64_t, Job> jobs_;
    std::vector<std::future<Result>> discarded_;   // finish, then freed
    std::function<void()> before_run_;
};

}  // namespace renderer
