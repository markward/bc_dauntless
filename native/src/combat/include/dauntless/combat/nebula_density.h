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
// Throws std::invalid_argument where Python's math.floor raises: a non-finite
// value reaching the noise lattice.
double fbm(double x, double y, double z);

// nebula_density.seed_for: a nebula's seed from its first sphere's centre
// (MetaNebula.GetSeed derives it lazily).
void seed_for(double cx, double cy, double cz, double out[3]);

// nebula_density.density: the sphere-union falloff times the saturated fbm.
// `seed` is the nebula's (sx, sy, sz); `floor` is the Python's density_floor.
// Throws std::invalid_argument (see fbm) when the point is inside a sphere
// and a non-finite drift_t, freq or seed reaches the noise.
double density(double px, double py, double pz, const Sphere* spheres,
               std::size_t n, const double seed[3], double freq, double gain,
               double floor, double drift_t);

}  // namespace dauntless::combat
