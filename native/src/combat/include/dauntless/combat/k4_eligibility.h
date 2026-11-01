#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/step_scan.h"

// K4: engine/appc/damage_eligibility.py `select_eligible(player, ships)` over
// the step scan (spec docs/superpowers/specs/2026-11-01-native-combat-k3-k4-
// design.md §4.2, map docs/reference/engine/native-combat/k3-k4-map.md Part
// B). Returns the indices into ships_list of the ships `select_eligible`
// adds after the player; the driver builds the id set (the player's id
// first). Exactness:
//   E1  max_r = max(radii, default=0.0) or 1.0: a left py_max fold from the
//       first radius, then Python truthiness (0.0 and -0.0 -> 1.0);
//   E2  size = r / max_r; with a player score = prox_w * prox + size_w *
//       size, prox = 1.0 / (1.0 + d), else size_w * size;
//   E3  d = frames.system_distance(s, player): dist3 (CPython's math.dist)
//       of the ship's position and the player's position + offset_between(
//       ship's set, player's set), inf when that offset is None;
//   E4  sorted by (-score, py_id), the first max_count - (player ? 1 : 0).
// It hands the whole call back to Python (ok = false) when the scan is not
// representable, the player handle names no live Object row, a radius,
// position or score is non-finite (a NaN key makes timsort's order depend
// on its merge pattern), or a set it must compare has no frame entry or is
// unrepresentable.

namespace dauntless::combat {

enum class K4Why : int32_t {
    scan,       // the step scan is not representable
    player,     // the player handle is stale or not an Object row
    nonfinite,  // a non-finite radius, position or score
    frame,      // a set with no frame-table entry
    set,        // an unrepresentable or stale set handle
    kCount
};

const char* k4_why_name(K4Why w);

struct K4Result {
    bool ok = false;
    K4Why why = K4Why::scan;
    std::vector<int64_t> indices;  // into ships_list, in E4 order
};

// `player`: an Object handle, or -1 for None.
K4Result k4_eligible(const Mirror& m, const StepScan& s, int64_t player,
                     int64_t max_count, double prox_w, double size_w);

struct K4Counts {
    uint64_t runs = 0;
    std::array<uint64_t, static_cast<size_t>(K4Why::kCount)> why{};
};

// Process-wide counters (combat_k4_counts).
K4Counts& k4_counts();

}  // namespace dauntless::combat
