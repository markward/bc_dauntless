#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/step_scan.h"

#include <algorithm>

namespace dauntless::combat {

namespace {

constexpr const char* kWhyNames[] = {
    "ok", "no_row", "unseen", "instance_patch", "stale", "is_dead",
    "not_ship", "duplicate", "set",
};
static_assert(sizeof(kWhyNames) / sizeof(kWhyNames[0]) ==
              static_cast<size_t>(ScanWhy::kCount));

void add_set(std::vector<int64_t>& sets, int64_t h) {
    if (std::find(sets.begin(), sets.end(), h) == sets.end())
        sets.push_back(h);
}

ScanWhy fail(StepScan& s, ScanWhy why) {
    s.representable = false;
    s.why = why;
    s.sets.clear();
    return why;
}

}  // namespace

const char* scan_why_name(ScanWhy w) {
    return kWhyNames[static_cast<size_t>(w)];
}

void StepScan::begin() {
    ++serial;
    representable = false;
    why = ScanWhy::no_row;
    ships.clear();
    sets.clear();
    frames.clear();
}

const FrameEntry* StepScan::frame(int64_t set) const {
    for (const FrameEntry& f : frames)
        if (f.set == set) return &f;
    return nullptr;
}

StepScan& step_scan() {
    static StepScan s;
    return s;
}

ScanWhy check_rows(const Mirror& m, StepScan& s) {
    s.sets.clear();
    for (int64_t h : s.ships) {
        const ObjectRow* r = m.object(h);
        if (r == nullptr) return fail(s, ScanWhy::stale);
        if (r->has_real_is_dead == 0) return fail(s, ScanWhy::is_dead);
        if (r->is_ship_class == 0) return fail(s, ScanWhy::not_ship);
        const int64_t cs = r->_containing_set;
        if (cs == -1) continue;
        if (cs < 0 || m.set(cs) == nullptr) return fail(s, ScanWhy::set);
        add_set(s.sets, cs);
    }
    // A row is one object: a handle twice is the same ship listed twice
    // (map B8 risk 4).
    std::vector<int64_t> sorted = s.ships;
    std::sort(sorted.begin(), sorted.end());
    if (std::adjacent_find(sorted.begin(), sorted.end()) != sorted.end())
        return fail(s, ScanWhy::duplicate);
    for (const TorpedoRow& t : m.torpedoes().rows()) {
        if (!t.alive || t.cset < 0 || m.set(t.cset) == nullptr) continue;
        add_set(s.sets, t.cset);
    }
    s.representable = true;
    s.why = ScanWhy::ok;
    return s.why;
}

OffsetStatus offset_between(const Mirror& m, const StepScan& s, int64_t a,
                            int64_t b, Vec3& out) {
    if (a == b) {
        // frames.py: `a is b` -> _ZERO if a SetClass else None, the frame
        // never resolved. Every Set row is a SetClass (sets.py registers
        // in SetClass.__init__).
        if (a == -1) return OffsetStatus::none;
        if (a < 0 || m.set(a) == nullptr) return OffsetStatus::unrepresentable;
        out = {0.0, 0.0, 0.0};
        return OffsetStatus::ok;
    }
    if (a == kRefUnrepresentable || b == kRefUnrepresentable)
        return OffsetStatus::unrepresentable;
    // frame_of(None) is None.
    if (a == -1 || b == -1) return OffsetStatus::none;
    if (m.set(a) == nullptr || m.set(b) == nullptr)
        return OffsetStatus::unrepresentable;
    const FrameEntry* fa = s.frame(a);
    const FrameEntry* fb = s.frame(b);
    if (fa == nullptr || fb == nullptr) return OffsetStatus::missing;
    if (fa->key < 0 || fb->key < 0 || fa->key != fb->key)
        return OffsetStatus::none;
    // tuple(b - a for a, b in zip(fa.anchor_gu, fb.anchor_gu))
    out = {fb->anchor[0] - fa->anchor[0], fb->anchor[1] - fa->anchor[1],
           fb->anchor[2] - fa->anchor[2]};
    return OffsetStatus::ok;
}

}  // namespace dauntless::combat
