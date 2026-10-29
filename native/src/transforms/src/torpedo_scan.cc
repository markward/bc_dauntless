#include "dauntless/torpedo_scan.h"

#include <cmath>

// Belt and braces with the -ffp-contract=off this file is built with (see
// native/src/transforms/CMakeLists.txt): no fused multiply-add, so every
// product and sum rounds exactly as CPython's do.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

namespace dauntless {

void TorpedoScan::add(std::int64_t id, std::uint32_t xform_index,
                      std::uint32_t xform_generation, double vx, double vy,
                      double vz, bool has_source, std::int64_t source,
                      std::int64_t group) {
    Row row{id, xform_index, xform_generation, {vx, vy, vz},
            has_source, source, group, true};
    if (Row* r = find(id)) {
        *r = row;
        return;
    }
    index_.emplace(id, rows_.size());
    rows_.push_back(row);
}

bool TorpedoScan::remove(std::int64_t id) {
    auto it = index_.find(id);
    if (it == index_.end()) return false;
    rows_[it->second].alive = false;
    index_.erase(it);
    ++dead_;
    // Compact once tombstones are both numerous and the majority, so a
    // steady fire-and-expire churn costs amortised O(1) per removal.
    if (dead_ > 64 && dead_ * 2 > rows_.size()) compact();
    return true;
}

void TorpedoScan::set_velocity(std::int64_t id, double vx, double vy,
                               double vz) {
    if (Row* r = find(id)) {
        r->vel[0] = vx;
        r->vel[1] = vy;
        r->vel[2] = vz;
    }
}

void TorpedoScan::set_source(std::int64_t id, bool has_source,
                             std::int64_t source) {
    if (Row* r = find(id)) {
        r->has_source = has_source;
        r->source = source;
    }
}

void TorpedoScan::set_group(std::int64_t id, std::int64_t group) {
    if (Row* r = find(id)) r->group = group;
}

void TorpedoScan::clear() {
    rows_.clear();
    index_.clear();
    dead_ = 0;
}

TorpedoScan::Row* TorpedoScan::find(std::int64_t id) {
    auto it = index_.find(id);
    return it == index_.end() ? nullptr : &rows_[it->second];
}

void TorpedoScan::compact() {
    std::size_t out = 0;
    for (std::size_t i = 0; i < rows_.size(); ++i) {
        if (!rows_[i].alive) continue;
        if (out != i) rows_[out] = rows_[i];
        index_[rows_[out].id] = out;
        ++out;
    }
    rows_.resize(out);
    dead_ = 0;
}

std::vector<std::int64_t> TorpedoScan::incoming(
        const double obs[3], const double obs_vel[3], double threshold,
        bool match_source, std::int64_t firing_id,
        const std::vector<GroupOffset>& offsets) const {
    std::vector<std::int64_t> out;
    if (offsets.empty()) return out;
    for (const Row& r : rows_) {
        if (!r.alive) continue;
        // projectiles._matches_source.
        if (match_source && (!r.has_source || r.source != firing_id)) continue;
        const double* off = nullptr;
        for (const GroupOffset& g : offsets) {
            if (g.group == r.group) {
                off = g.off;
                break;
            }
        }
        if (off == nullptr) continue;          // another frame / no set
        if (!store_.valid(r.xi, r.xg)) continue;
        const double* p = store_.at(r.xi).pos;

        // projectiles._closing_time, operation for operation.
        const double dx = (p[0] + off[0]) - obs[0];
        const double dy = (p[1] + off[1]) - obs[1];
        const double dz = (p[2] + off[2]) - obs[2];
        const double dist = std::sqrt(dx * dx + dy * dy + dz * dz);
        double t;
        if (dist < 1e-6) {
            t = 0.0;                           // already on top of us
        } else {
            const double rx = r.vel[0] - obs_vel[0];
            const double ry = r.vel[1] - obs_vel[1];
            const double rz = r.vel[2] - obs_vel[2];
            const double inv = 1.0 / dist;
            const double tx = dx * inv;
            const double ty = dy * inv;
            const double tz = dz * inv;
            const double closing = -(rx * tx + ry * ty + rz * tz);
            if (closing <= 1e-6) continue;     // not approaching
            t = dist / closing;
        }
        if (t <= threshold) out.push_back(r.id);
    }
    return out;
}

TorpedoScan& torpedo_scan() {
    static TorpedoScan scan(transform_store());
    return scan;
}

}  // namespace dauntless
