#include "dauntless/combat/set_index.h"

#include <algorithm>

namespace dauntless::combat {

namespace {
void erase_value(std::vector<uint64_t>& v, uint64_t x) {
    v.erase(std::remove(v.begin(), v.end(), x), v.end());
}
}  // namespace

void SetIndex::bump(SetData& sd, int64_t target, int64_t delta) {
    if (target == kNoTarget) return;
    auto it = sd.counts.find(target);
    if (it == sd.counts.end()) {
        if (delta > 0) sd.counts[target] = delta;
        return;
    }
    it->second += delta;
    if (it->second <= 0) sd.counts.erase(it);
}

void SetIndex::hold(IndexKey obj, IndexKey set, int64_t delta) {
    auto& held = objs_[obj].held;
    for (auto it = held.begin(); it != held.end(); ++it) {
        if (it->first != set) continue;
        it->second += delta;
        if (it->second <= 0) held.erase(it);
        return;
    }
    if (delta > 0) held.emplace_back(set, delta);
}

void SetIndex::add_entry_contrib(SetData& sd, IndexKey set, IndexKey obj) {
    hold(obj, set, 1);
    const ObjInfo& oi = objs_[obj];
    if (oi.is_ship) bump(sd, oi.target, 1);
}

void SetIndex::drop_entry_contrib(SetData& sd, IndexKey set, IndexKey obj) {
    const ObjInfo& oi = objs_[obj];
    if (oi.is_ship) bump(sd, oi.target, -1);
    hold(obj, set, -1);
}

std::optional<IndexKey> SetIndex::add(IndexKey set, std::string_view ident, IndexKey obj,
                                      int64_t /*obj_id*/, bool is_ship, int64_t target_id) {
    if (!sets_.count(set)) set_order_.push_back(set);
    SetData& sd = sets_[set];
    std::optional<IndexKey> replaced;
    std::string key(ident);
    auto bi = sd.by_ident.find(key);
    uint64_t seq;
    if (bi != sd.by_ident.end()) {
        seq = bi->second;
        Entry& e = sd.entries[seq];
        replaced = e.obj;
        drop_entry_contrib(sd, set, e.obj);
        erase_value(sd.by_obj[e.obj], seq);
        if (sd.by_obj[e.obj].empty()) sd.by_obj.erase(e.obj);
        for (auto& [cls, seqs] : sd.buckets) seqs.erase(seq);
        e.obj = obj;
        e.leaving = false;
    } else {
        seq = sd.next_seq++;
        sd.entries[seq] = Entry{key, obj, false};
        sd.by_ident[key] = seq;
    }
    sd.by_obj[obj].push_back(seq);
    ObjInfo& oi = objs_[obj];
    oi.is_ship = is_ship;
    if (is_ship) oi.target = target_id;
    add_entry_contrib(sd, set, obj);
    return replaced;
}

void SetIndex::mark_leaving(IndexKey set, std::string_view ident) {
    auto si = sets_.find(set);
    if (si == sets_.end()) return;
    auto bi = si->second.by_ident.find(std::string(ident));
    if (bi == si->second.by_ident.end()) return;
    si->second.entries[bi->second].leaving = true;
}

std::optional<IndexKey> SetIndex::remove(IndexKey set, std::string_view ident) {
    auto si = sets_.find(set);
    if (si == sets_.end()) return std::nullopt;
    SetData& sd = si->second;
    auto bi = sd.by_ident.find(std::string(ident));
    if (bi == sd.by_ident.end()) return std::nullopt;
    uint64_t seq = bi->second;
    IndexKey obj = sd.entries[seq].obj;
    drop_entry_contrib(sd, set, obj);
    erase_value(sd.by_obj[obj], seq);
    if (sd.by_obj[obj].empty()) sd.by_obj.erase(obj);
    for (auto& [cls, seqs] : sd.buckets) seqs.erase(seq);
    sd.entries.erase(seq);
    sd.by_ident.erase(bi);
    return obj;
}

void SetIndex::set_target(IndexKey ship, int64_t target_id) {
    ObjInfo& oi = objs_[ship];
    if (oi.target == target_id) return;
    if (oi.is_ship) {
        for (auto& [set, mult] : oi.held) {
            SetData& sd = sets_[set];
            bump(sd, oi.target, -mult);
            bump(sd, target_id, mult);
        }
    }
    oi.target = target_id;
}

void SetIndex::set_is_ship(IndexKey obj, bool is_ship) {
    ObjInfo& oi = objs_[obj];
    if (oi.is_ship == is_ship) return;
    for (auto& [set, mult] : oi.held)
        bump(sets_[set], oi.target, is_ship ? mult : -mult);
    oi.is_ship = is_ship;
}

bool SetIndex::has_bucket(IndexKey set, IndexKey cls) const {
    auto si = sets_.find(set);
    return si != sets_.end() && si->second.buckets.count(cls) != 0;
}

void SetIndex::create_bucket(IndexKey set, IndexKey cls,
                             const std::function<bool(IndexKey)>& member_of) {
    if (!sets_.count(set)) set_order_.push_back(set);
    SetData& sd = sets_[set];
    auto& seqs = sd.buckets[cls];
    seqs.clear();
    for (auto& [seq, e] : sd.entries)
        if (member_of(e.obj)) seqs.insert(seq);
}

std::vector<IndexKey> SetIndex::bucket_classes(IndexKey set) const {
    std::vector<IndexKey> out;
    auto si = sets_.find(set);
    if (si == sets_.end()) return out;
    for (auto& [cls, seqs] : si->second.buckets) out.push_back(cls);
    return out;
}

void SetIndex::set_bucket_membership(IndexKey set, IndexKey cls, IndexKey obj, bool member) {
    auto si = sets_.find(set);
    if (si == sets_.end()) return;
    SetData& sd = si->second;
    auto bi = sd.buckets.find(cls);
    if (bi == sd.buckets.end()) return;
    auto oi = sd.by_obj.find(obj);
    if (oi == sd.by_obj.end()) return;
    for (uint64_t seq : oi->second) {
        if (member) bi->second.insert(seq);
        else bi->second.erase(seq);
    }
}

std::vector<IndexKey> SetIndex::bucket(IndexKey set, IndexKey cls) const {
    std::vector<IndexKey> out;
    auto si = sets_.find(set);
    if (si == sets_.end()) return out;
    auto bi = si->second.buckets.find(cls);
    if (bi == si->second.buckets.end()) return out;
    for (uint64_t seq : bi->second) out.push_back(si->second.entries.at(seq).obj);
    return out;
}

std::vector<IndexKey> SetIndex::distinct_live(IndexKey set, IndexKey cls) const {
    std::vector<IndexKey> out;
    auto si = sets_.find(set);
    if (si == sets_.end()) return out;
    auto bi = si->second.buckets.find(cls);
    if (bi == si->second.buckets.end()) return out;
    std::set<IndexKey> seen;
    for (uint64_t seq : bi->second) {
        const Entry& e = si->second.entries.at(seq);
        if (e.leaving) continue;
        if (seen.insert(e.obj).second) out.push_back(e.obj);
    }
    return out;
}

int64_t SetIndex::targeted_by(IndexKey set, int64_t target_id) const {
    auto si = sets_.find(set);
    if (si == sets_.end()) return 0;
    auto it = si->second.counts.find(target_id);
    return it == si->second.counts.end() ? 0 : it->second;
}

int64_t SetIndex::multiplicity(IndexKey set, IndexKey obj) const {
    auto si = sets_.find(set);
    if (si == sets_.end()) return 0;
    auto it = si->second.by_obj.find(obj);
    return it == si->second.by_obj.end() ? 0 : static_cast<int64_t>(it->second.size());
}

int64_t SetIndex::popularity(IndexKey set, IndexKey rater, int64_t target_id) const {
    int64_t n = targeted_by(set, target_id);
    auto oi = objs_.find(rater);
    if (oi != objs_.end() && oi->second.is_ship && oi->second.target == target_id)
        n -= multiplicity(set, rater);
    return n;
}

std::vector<IndexKey> SetIndex::targeting(IndexKey set, int64_t target_id) const {
    std::vector<IndexKey> out;
    auto si = sets_.find(set);
    if (si == sets_.end() || target_id == kNoTarget) return out;
    for (auto& [seq, e] : si->second.entries) {
        auto oi = objs_.find(e.obj);
        if (oi != objs_.end() && oi->second.is_ship && oi->second.target == target_id)
            out.push_back(e.obj);
    }
    return out;
}

std::vector<IndexKey> SetIndex::sets_holding(IndexKey obj) const {
    std::vector<IndexKey> out;
    auto oi = objs_.find(obj);
    if (oi == objs_.end()) return out;
    for (auto& [set, mult] : oi->second.held) {
        const SetData& sd = sets_.at(set);
        auto bo = sd.by_obj.find(obj);
        if (bo == sd.by_obj.end()) continue;
        for (uint64_t seq : bo->second)
            if (!sd.entries.at(seq).leaving) { out.push_back(set); break; }
    }
    return out;
}

std::vector<IndexKey> SetIndex::forget_set(IndexKey set) {
    std::vector<IndexKey> out;
    auto si = sets_.find(set);
    if (si == sets_.end()) return out;
    SetData& sd = si->second;
    for (auto& [seq, e] : sd.entries) {
        out.push_back(e.obj);
        hold(e.obj, set, -1);
    }
    out.push_back(set);
    sets_.erase(si);
    set_order_.erase(std::remove(set_order_.begin(), set_order_.end(), set), set_order_.end());
    return out;
}

std::vector<IndexKey> SetIndex::reset() {
    std::vector<IndexKey> out;
    for (auto& [set, sd] : sets_) {
        for (auto& [seq, e] : sd.entries) out.push_back(e.obj);
        out.push_back(set);
    }
    sets_.clear();
    set_order_.clear();
    objs_.clear();
    return out;
}

std::vector<IndexKey> SetIndex::sets() const { return set_order_; }

}  // namespace dauntless::combat
