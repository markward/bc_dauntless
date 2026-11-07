// SetIndex: the native mirror of SetClass._objects for class lists and
// (set, target) counts. Semantics: one entry per identifier, dict slot order
// (an overwrite keeps the slot's sequence number, a pop-and-re-add goes to the
// end), multiplicity (an object under two identifiers is two entries), and a
// LEAVING flag that hides an entry from the contact view only.
#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace dauntless::combat {

using IndexKey = std::uintptr_t;  // object identity; 0 = none
constexpr int64_t kNoTarget = -1;

class SetIndex {
public:
    // Returns the object an overwrite replaced (the caller drops that
    // reference). An overwrite clears LEAVING and removes the slot from every
    // bucket (the caller re-asserts membership of the new object).
    //
    // `is_ship` / `target_id` must equal what was last pushed through
    // set_is_ship / set_target for an object some set already holds. The
    // facade (engine/appc/set_index.py) guarantees it: a target changes only
    // through ShipClass.SetTarget, which calls set_target, and a class only
    // through native_combat.reclassify, which calls set_is_ship. Should they
    // ever differ, add applies them through set_target / set_is_ship first,
    // so every other set holding the object is re-counted, never drifted.
    //
    // Per-object records (class flag, target) exist only while some set holds
    // the object: the last remove / forget_set erases it, and set_target /
    // set_is_ship on an object held by no set do nothing.
    std::optional<IndexKey> add(IndexKey set, std::string_view ident, IndexKey obj,
                                bool is_ship = false, int64_t target_id = kNoTarget);
    void mark_leaving(IndexKey set, std::string_view ident);
    std::optional<IndexKey> remove(IndexKey set, std::string_view ident);

    void set_target(IndexKey ship, int64_t target_id);
    void set_is_ship(IndexKey obj, bool is_ship);

    bool has_set(IndexKey set) const { return sets_.count(set) != 0; }
    bool has_bucket(IndexKey set, IndexKey cls) const;
    // Creates the set if unknown (check has_set first to count its reference).
    void create_bucket(IndexKey set, IndexKey cls, const std::function<bool(IndexKey)>& member_of);
    std::vector<IndexKey> bucket_classes(IndexKey set) const;
    void set_bucket_membership(IndexKey set, IndexKey cls, IndexKey obj, bool member);
    std::vector<IndexKey> bucket(IndexKey set, IndexKey cls) const;
    std::vector<IndexKey> distinct_live(IndexKey set, IndexKey cls) const;

    int64_t targeted_by(IndexKey set, int64_t target_id) const;
    int64_t multiplicity(IndexKey set, IndexKey obj) const;
    // 0 for kNoTarget (never negative).
    int64_t popularity(IndexKey set, IndexKey rater, int64_t target_id) const;
    std::vector<IndexKey> targeting(IndexKey set, int64_t target_id) const;

    // Sets holding `obj` under a non-LEAVING entry (the contact view).
    std::vector<IndexKey> sets_holding(IndexKey obj) const;
    // Every set holding `obj`, LEAVING entries included (reclassification).
    std::vector<IndexKey> held_sets(IndexKey obj) const;
    std::size_t object_records() const { return objs_.size(); }
    // Every key whose reference is dropped, with multiplicity (one per entry's
    // object, plus the set key once per set).
    std::vector<IndexKey> forget_set(IndexKey set);
    std::vector<IndexKey> reset();
    std::vector<IndexKey> sets() const;

private:
    struct Entry {
        std::string ident;
        IndexKey obj = 0;
        bool leaving = false;
    };
    struct SetData {
        uint64_t next_seq = 0;
        std::map<uint64_t, Entry> entries;                    // sequence order
        std::unordered_map<std::string, uint64_t> by_ident;
        std::unordered_map<IndexKey, std::vector<uint64_t>> by_obj;
        std::unordered_map<IndexKey, std::set<uint64_t>> buckets;
        std::unordered_map<int64_t, int64_t> counts;
    };
    struct ObjInfo {
        bool is_ship = false;
        int64_t target = kNoTarget;
        std::vector<std::pair<IndexKey, int64_t>> held;  // (set, multiplicity), first-entry order
    };

    void bump(SetData& sd, int64_t target, int64_t delta);
    void hold(IndexKey obj, IndexKey set, int64_t delta);
    void drop_entry_contrib(SetData& sd, IndexKey set, IndexKey obj);
    void add_entry_contrib(SetData& sd, IndexKey set, IndexKey obj);

    std::unordered_map<IndexKey, SetData> sets_;
    std::vector<IndexKey> set_order_;
    std::unordered_map<IndexKey, ObjInfo> objs_;
};

}  // namespace dauntless::combat
