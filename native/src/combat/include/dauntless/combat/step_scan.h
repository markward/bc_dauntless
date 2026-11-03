#pragma once

#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"

// The per-step ship scan and frame table that K4 (eligibility) and K3
// (projectiles) share (spec docs/superpowers/specs/2026-11-01-native-combat-
// k3-k4-design.md §4.1).
//
// At the top of `cb.eligibility` the driver scans the step's `ships_list`
// once (native_combat.step_scan -> the binding combat_step_scan): the
// Python-level checks (an Object row, a class K2 has seen, no instance
// attribute shadowing a stood-in method) run in the binding over the
// instance dicts and fill `ships` in list order; check_rows() then checks the
// rows themselves and collects the distinct Set handles in play. Python
// resolves frames.frame_of(set) for each of those sets, EVERY step (never
// cached across steps), and sends the frame table (combat_step_frames).

namespace dauntless::combat {

// Why a scan is not representable for K3/K4 (the first failure found).
enum class ScanWhy : int32_t {
    ok,
    no_row,          // an entry with no Object row (binding)
    unseen,          // its class is one K2 has never seen (binding)
    instance_patch,  // an instance attribute shadows a stood-in method
    stale,           // its handle names no live Object row
    is_dead,         // no real IsDead (has_real_is_dead 0)
    not_ship,        // not a ShipClass (an engine ObjectClass subclass may
                     // answer GetRadius from elsewhere: ProximityCheck)
    duplicate,       // the same row listed twice
    set,             // its _containing_set is unrepresentable or stale
    kCount
};

const char* scan_why_name(ScanWhy w);

// One frame-table entry: frames.frame_of(set) as Python resolved it this
// step. `key` is the frame key interned per step (two sets in one star
// system share it); -1 when frame_of returned None. `anchor` is anchor_gu.
struct FrameEntry {
    int64_t set = -1;
    int64_t key = -1;
    Vec3 anchor{0.0, 0.0, 0.0};
};

struct StepScan {
    // Bumped by every begin(): a kernel can tell a scan from the last one.
    uint64_t serial = 0;
    bool representable = false;
    ScanWhy why = ScanWhy::no_row;
    // Object handle per ships_list entry, in list order (filled only while
    // every entry so far was representable).
    std::vector<int64_t> ships;
    // Distinct live Set handles named by the ship rows' _containing_set,
    // then by the torpedo rows' cset, in first-seen order.
    std::vector<int64_t> sets;
    // This step's frame table (empty until combat_step_frames).
    std::vector<FrameEntry> frames;

    // A new step: empties everything, bumps the serial.
    void begin();
    // The frame entry for `set`, or nullptr.
    const FrameEntry* frame(int64_t set) const;
};

// Process-wide: one step at a time (GIL held, ruling J).
StepScan& step_scan();

// The row-level checks over s.ships (after the binding filled it): every
// handle a live ShipClass Object row with a real IsDead, no handle twice,
// every _containing_set none or a live Set. Fills s.sets (ships' sets, then the
// torpedo table's), sets s.representable / s.why, and returns s.why.
ScanWhy check_rows(const Mirror& m, StepScan& s);

// frames.offset_between(set_a, set_b) over this step's frame table.
enum class OffsetStatus : int32_t {
    ok,               // `out` holds the offset (exact zeros for one set)
    none,             // Python returns None: other frame, or no set
    missing,          // a set with no frame-table entry: ask Python
    unrepresentable,  // a -2 or stale set handle: Python decides
};

// `a`, `b`: Set handles as an Object row's _containing_set holds them (-1
// None, -2 unrepresentable). Same handle: exact zeros for a live Set (a
// SetClass; frame never resolved), None for -1. Different: both frames
// looked up; either frame None or keys differ -> none; else b.anchor -
// a.anchor per component.
OffsetStatus offset_between(const Mirror& m, const StepScan& s, int64_t a,
                            int64_t b, Vec3& out);

}  // namespace dauntless::combat
