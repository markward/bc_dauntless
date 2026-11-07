// SetIndex: the native mirror of SetClass._objects for class lists and
// (set, target) counts. Semantics: one entry per identifier, dict slot order
// (an overwrite keeps the slot's sequence number, a pop-and-re-add goes to the
// end), multiplicity (an object under two identifiers is two entries), and a
// LEAVING flag that hides an entry from the contact view only.
//
// Native-reader contract. Keys are BORROWED `PyObject*` addresses: the set's
// `_objects` dict keeps each member alive and a weakref callback forgets a
// set as it dies (native/src/host/host_bindings.cc, namespace si). So a key
// is valid only for as long as no Python can run:
//  - read the index only under the GIL, on the main thread;
//  - never hold a key (or a vector of keys) across a call that can run
//    Python or allocate a Python object: any allocation can run a cyclic
//    collection whose weakref callbacks forget and free sets, and any
//    isinstance can run arbitrary Python. Turn keys into owned references
//    (or finish with them) first.
// The index never dereferences a key itself.
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
constexpr int64_t kNoId = -1;  // an object with no GetObjID()

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
    // Per-object records (class flag, target, own id) exist only while some
    // set holds the object: the last remove / forget_set erases it, and
    // set_target / set_is_ship on an object held by no set do nothing.
    //
    // `obj_id` is the object's own GetObjID() (kNoId for none): the id other
    // ships' targets are counted under, so a native reader holding only the
    // candidate's key can ask popularity_by_key.
    std::optional<IndexKey> add(IndexKey set, std::string_view ident, IndexKey obj,
                                bool is_ship = false, int64_t target_id = kNoTarget,
                                int64_t obj_id = kNoId);
    void mark_leaving(IndexKey set, std::string_view ident);
    std::optional<IndexKey> remove(IndexKey set, std::string_view ident);
    // Marks every current entry of `set` LEAVING (the contact view empties;
    // class lists and counts are untouched). A later add shows its member, an
    // overwrite of a hidden entry clears the mark, removing one changes no
    // contact view. No-op for an unknown set.
    void hide_contacts(IndexKey set);
    // True if `obj` has an entry in `set` that is not LEAVING.
    bool visible(IndexKey set, IndexKey obj) const;

    void set_target(IndexKey ship, int64_t target_id);
    void set_is_ship(IndexKey obj, bool is_ship);

    bool has_set(IndexKey set) const { return sets_.count(set) != 0; }
    bool has_bucket(IndexKey set, IndexKey cls) const;
    // Creates the set if unknown (check has_set first to count its reference).
    void create_bucket(IndexKey set, IndexKey cls, const std::function<bool(IndexKey)>& member_of);
    // Forgets one bucket (a class test that raised left it half-built); the
    // next read creates it again. False if there was none.
    bool drop_bucket(IndexKey set, IndexKey cls);
    std::vector<IndexKey> bucket_classes(IndexKey set) const;
    void set_bucket_membership(IndexKey set, IndexKey cls, IndexKey obj, bool member);
    std::vector<IndexKey> bucket(IndexKey set, IndexKey cls) const;
    // Calls visit(ctx, obj) for each entry bucket() would list, in its
    // order, until visit returns false; false if it stopped early (true for
    // an unknown set or bucket). Allocates nothing, so a native reader can
    // walk the borrowed keys while no Python runs; visit must not change the
    // index.
    bool visit_bucket(IndexKey set, IndexKey cls, bool (*visit)(void* ctx, IndexKey obj),
                      void* ctx) const;
    std::vector<IndexKey> distinct_live(IndexKey set, IndexKey cls) const;

    int64_t targeted_by(IndexKey set, int64_t target_id) const;
    int64_t multiplicity(IndexKey set, IndexKey obj) const;
    // 0 for kNoTarget (never negative).
    int64_t popularity(IndexKey set, IndexKey rater, int64_t target_id) const;
    // The object's own id as `add` recorded it; kNoId for an object no set
    // holds.
    int64_t obj_id(IndexKey obj) const;
    // popularity(set, rater, obj_id(candidate)).
    int64_t popularity_by_key(IndexKey set, IndexKey rater, IndexKey candidate) const;
    std::vector<IndexKey> targeting(IndexKey set, int64_t target_id) const;

    // Sets holding `obj` under a non-LEAVING entry (the contact view).
    std::vector<IndexKey> sets_holding(IndexKey obj) const;
    // Every set holding `obj`, LEAVING entries included (reclassification).
    std::vector<IndexKey> held_sets(IndexKey obj) const;
    std::size_t object_records() const { return objs_.size(); }
    std::size_t entry_count() const;  // entries across every set
    std::size_t entry_count(IndexKey set) const;  // 0 for an unknown set
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
        int64_t id = kNoId;
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
