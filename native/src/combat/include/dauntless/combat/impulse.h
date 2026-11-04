#pragma once

#include <cstdint>

#include "dauntless/combat/mirror.h"

// subsystems.impulse_fractions (engine/appc/subsystems.py): the impulse
// engine's (online, output) fractions from ONE walk over its pods, answered
// from the Mirror. A line-for-line port of the FUSED walk, including its
// "ship known good" shortcut: past the master's own _is_offline test the
// pods' parent-ship clause is skipped (when the IES carries GetParentShip),
// so a pod's own _radiation_out is NOT read there (open-questions-by-reading
// Q1; a deliberate, pinned difference from impulse_online_fraction).
//
// `ies` is a Subsystem row handle, or -1 for no impulse engine ((1, 1)).
// Throws std::invalid_argument (Python ValueError, "answer in Python") where
// the mirror cannot answer: a -2 ref the walk reaches, a gone row, a parent
// that is not a ShipClass row.
namespace dauntless::combat {

struct ImpulseFractions {
    double online;
    double output;
};

ImpulseFractions impulse_fractions(const Mirror& m, int64_t ies);

}  // namespace dauntless::combat
