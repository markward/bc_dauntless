// native/src/renderer/part_severance_jobs.cc -- see part_severance_jobs.h.
#include "renderer/part_severance_jobs.h"

#include <chrono>
#include <cstdio>
#include <exception>
#include <utility>

namespace renderer {

bool SeveranceJobs::finished(const std::future<Result>& f) {
    return f.valid() && f.wait_for(std::chrono::seconds(0)) == std::future_status::ready;
}

void SeveranceJobs::reap() {
    for (std::size_t i = 0; i < discarded_.size();) {
        if (finished(discarded_[i])) {
            discarded_[i] = std::move(discarded_.back());
            discarded_.pop_back();
        } else {
            ++i;
        }
    }
}

SplitPoll SeveranceJobs::poll(scenegraph::World& world, scenegraph::InstanceId parent,
                              std::shared_ptr<const voxel::StructureSegmentation> seg,
                              const DamageFn& damage, float deck_break, bool skinned,
                              SeveranceStats* stats) {
    reap();
    SplitPoll out;
    scenegraph::Instance* p = world.get(parent);
    // The same gates as split_severed_parts: a chunk never severs further, a
    // skinned model cannot hide parts, rocks and articulated/rigged hulls
    // leave other ways. A stale id's job (if any) is discarded.
    if (p == nullptr || seg == nullptr || skinned || p->surface_is_rock ||
        p->shown_parts != 0 || !can_structure_sever(*p)) {
        forget(parent);
        return out;
    }

    const auto it = jobs_.find(key(parent));
    if (it != jobs_.end()) {
        Job& job = it->second;
        if (job.result.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
            out.pending = true;
            return out;
        }
        Result r;
        bool ok = true;
        try {
            r = job.result.get();
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[severance] check failed: %s\n", e.what());
            ok = false;
        } catch (...) {
            std::fprintf(stderr, "[severance] check failed\n");
            ok = false;
        }
        const bool current = ok && p->hull_damage.revision() == job.revision &&
                             p->severed_parts == job.severed &&
                             job.deck_break == deck_break && job.seg == seg;
        jobs_.erase(it);
        if (current) {
            out.split = apply_severed_pieces(world, parent, r.pieces, r.total_voxels,
                                             deck_break);
            return out;
        }
        if (!ok) return out;   // the next check re-queues
        // Stale (the damage, the lost parts or the dial moved meanwhile):
        // drop it and check again on the current inputs, below.
    }

    // Nothing changed since the last full check (same damage, same lost
    // parts, same deck break): it would find nothing new.
    const scenegraph::Instance::PartCheckStamp& last = p->part_check;
    if (last.valid && last.revision == p->hull_damage.revision() &&
        last.severed_parts == p->severed_parts && last.deck_break == deck_break)
        return out;

    if (stats != nullptr) ++stats->checks;
    Job job;
    job.seg = seg;
    job.revision = p->hull_damage.revision();
    job.severed = p->severed_parts;
    job.deck_break = deck_break;
    // Everything the worker reads is captured BY VALUE here.
    const std::uint32_t gone = p->severed_parts;
    const std::uint32_t unhideable = ~((1u << kMaxHideableParts) - 1u);
    job.result = std::async(
        std::launch::async,
        [seg, dl = damage(*p), deck_break, gone, unhideable, hook = before_run_]() {
            if (hook) hook();
            Result r;
            r.pieces = find_severed_parts(*seg, dl, deck_break, unhideable, gone);
            if (!r.pieces.empty()) r.total_voxels = solid_voxels(*seg);
            return r;
        });
    jobs_[key(parent)] = std::move(job);
    out.pending = true;
    return out;
}

void SeveranceJobs::forget(scenegraph::InstanceId id) {
    const auto it = jobs_.find(key(id));
    if (it == jobs_.end()) return;
    if (!finished(it->second.result)) discarded_.push_back(std::move(it->second.result));
    jobs_.erase(it);
}

void SeveranceJobs::clear() {
    for (auto& kv : jobs_)
        if (!finished(kv.second.result)) discarded_.push_back(std::move(kv.second.result));
    jobs_.clear();
    reap();
}

bool SeveranceJobs::has_job(scenegraph::InstanceId id) const {
    return jobs_.count(key(id)) != 0;
}

std::size_t SeveranceJobs::outstanding() const { return jobs_.size() + discarded_.size(); }

void SeveranceJobs::wait_for_test(scenegraph::InstanceId id) {
    const auto it = jobs_.find(key(id));
    if (it != jobs_.end()) it->second.result.wait();
}

void SeveranceJobs::set_before_run_for_test(std::function<void()> hook) {
    before_run_ = std::move(hook);
}

}  // namespace renderer
