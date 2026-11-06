#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"

// K2's ship scan (phase 6 follow-up 3b): which ships the K2 driver must hand
// to native_combat._k2_python_ship before begin, answered from the mirror.
//
// The binding (combat_k2_scan_rows) reads one `_nslot` per ship and checks
// the ship's live class against native_combat._k2_seen_set; this walks the
// rows. Ships it calls unclean go to _k2_python_ship, the authority,
// which decides each one as before; a clean ship is walked by K2.
//
// For each handle >= 0 the ship is UNCLEAN when:
//   - its Object row is gone (stale or freed);
//   - its _phaser_system is kRefUnrepresentable, or names a row that is
//     gone, or one that is not a stock phaser system (k2_stock 0, or a
//     weapon_kind other than the phaser system's);
//   - its system's _children holds kRefUnrepresentable, a row that is gone,
//     or one that is not a stock phaser bank (k2_stock 0, or a weapon_kind
//     other than the bank's), or a bank whose _target is
//     kRefUnrepresentable.
// A _phaser_system of -1 (none) is clean. A handle of -1 (no row) is never
// checked and never listed.
//
// What it cannot see (accepted, plan 2026-11-06-phase6-k2-scan-from-mirror
// Global Constraints): a change Python makes behind the mirror's back -- a
// bank's `_nslot` deleted or replaced with no native_combat._drop, or a
// system's, bank's or target's `__class__` swapped with no
// native_combat.reclassify (its class flags, k2_stock included, stay its
// old class's). The ship's own class is the binding's live check.

namespace dauntless::combat {

// The indexes into `handles` of the unclean ships, in order.
std::vector<size_t> k2_unclean_ships(const Mirror& m,
                                     const std::vector<int64_t>& handles);

}  // namespace dauntless::combat
