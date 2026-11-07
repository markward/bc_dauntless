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
    std::optional<IndexKey> add(IndexKey set, std::string_view ident, IndexKey obj,
                                int64_t obj_id, bool is_ship, int64_t target_id);
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
    int64_t popularity(IndexKey set, IndexKey rater, int64_t target_id) const;
    std::vector<IndexKey> targeting(IndexKey set, int64_t target_id) const;

    std::vector<IndexKey> sets_holding(IndexKey obj) const;
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
