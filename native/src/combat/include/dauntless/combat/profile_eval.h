#pragma once

#include <cstddef>

// engine/systems/profile.py `evaluate`, the `sensors` column only, bit for
// bit: the radial system profile's sensor concealment at distance r from the
// star (sensor_detection.concealment_at).

namespace dauntless::combat {

// One profile row: its distance from the star and its `sensors` value.
struct ProfileRow {
    double distance_gu;
    double sensors;
};

// The `sensors` column at radius r. Rows are sorted by distance_gu (as the
// Python's are). No rows is clear space (0.0). At or inside the first row:
// the first row's value. An exact breakpoint returns that row's stored value
// (never a t = 1.0 lerp). Between rows: a + (b - a) * t. Past the last row,
// and for a NaN r (every compare False): the last row's value.
double evaluate_sensors(const ProfileRow* rows, std::size_t n, double r);

}  // namespace dauntless::combat
