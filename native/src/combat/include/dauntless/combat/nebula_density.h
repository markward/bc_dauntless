#pragma once

#include <cstddef>

// engine/appc/nebula_density.py in C++, bit for bit: the fbm density field a
// MetaNebula conceals a ship with (sensor_detection._local_concealment).
// Operand order and NaN branches follow the Python exactly; see py_math.h.

namespace dauntless::combat {

// One nebula sphere, as MetaNebula.GetNebulaSpheres() hands it: centre + radius.
struct Sphere {
    double x, y, z, r;
};

// nebula_density.fbm: 5 octaves of value noise, lacunarity 2.02, gain 0.5.
double fbm(double x, double y, double z);

// nebula_density.density: the sphere-union falloff times the saturated fbm.
// `seed` is the nebula's (sx, sy, sz); `floor` is the Python's density_floor.
double density(double px, double py, double pz, const Sphere* spheres,
               std::size_t n, const double seed[3], double freq, double gain,
               double floor, double drift_t);

}  // namespace dauntless::combat
