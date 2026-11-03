// engine/appc/nebula_density.py in C++, bit for bit -- see nebula_density.h.
// Each function mirrors its Python namesake line for line; keep them in step.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/nebula_density.h"

#include <cmath>
#include <stdexcept>

#include "dauntless/combat/py_math.h"

namespace dauntless::combat {

namespace {

// Python `math.floor(x)` used as a number: it returns an int, and an int has
// no -0.0, so floor(-0.0) must come back +0.0 (`+ 0.0` does exactly that and
// nothing else). Every later int<->float mix is exact: a floor of a double is
// a double-representable integer, and `ix + 1` rounds the same in both.
//
// Python's floor RAISES on a non-finite value (ValueError on NaN,
// OverflowError on inf). A NaN or infinite POSITION never gets here (its
// falloff is 0, so density returns first), but a non-finite drift_t, freq or
// seed at a point inside a sphere does, and so does a finite coordinate that
// the octave doubling overflows. Python raises there; so does this
// (std::invalid_argument, Python ValueError -- ruling R5), and the caller
// falls back to the Python, which raises as it always did. Never a silent NaN.
inline double py_floor(double x) {
    if (!std::isfinite(x))
        throw std::invalid_argument(
            "combat nebula_density: math.floor of a non-finite value");
    return std::floor(x) + 0.0;
}

inline double fract(double x) { return x - py_floor(x); }

double hash13(double x, double y, double z) {
    // p3 = fract(p3 * 0.1031)
    double px = fract(x * 0.1031), py = fract(y * 0.1031), pz = fract(z * 0.1031);
    // p3 += dot(p3, p3.zyx + 31.32)
    const double d = px * (pz + 31.32) + py * (py + 31.32) + pz * (px + 31.32);
    px = px + d;
    py = py + d;
    pz = pz + d;
    // fract((p3.x + p3.y) * p3.z)
    return fract((px + py) * pz);
}

double vnoise(double x, double y, double z) {
    const double ix = py_floor(x), iy = py_floor(y), iz = py_floor(z);
    double fx = x - ix, fy = y - iy, fz = z - iz;
    fx = fx * fx * (3.0 - 2.0 * fx);
    fy = fy * fy * (3.0 - 2.0 * fy);
    fz = fz * fz * (3.0 - 2.0 * fz);

    auto h = [&](double dx, double dy, double dz) {
        return hash13(ix + dx, iy + dy, iz + dz);
    };

    const double n00 = h(0, 0, 0) + (h(1, 0, 0) - h(0, 0, 0)) * fx;
    const double n10 = h(0, 1, 0) + (h(1, 1, 0) - h(0, 1, 0)) * fx;
    const double n01 = h(0, 0, 1) + (h(1, 0, 1) - h(0, 0, 1)) * fx;
    const double n11 = h(0, 1, 1) + (h(1, 1, 1) - h(0, 1, 1)) * fx;
    const double n0 = n00 + (n10 - n00) * fy;
    const double n1 = n01 + (n11 - n01) * fy;
    return n0 + (n1 - n0) * fz;
}

double sphere_union_falloff(double px, double py, double pz,
                            const Sphere* spheres, std::size_t n) {
    // Smooth 0->1 inward from each sphere boundary; union = max.
    double best = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        const double cx = spheres[i].x, cy = spheres[i].y, cz = spheres[i].z;
        const double r = spheres[i].r;
        if (r <= 0.0) {
            continue;
        }
        const double dx = px - cx, dy = py - cy, dz = pz - cz;
        const double d = std::sqrt(dx * dx + dy * dy + dz * dz);
        // 1 at centre, 0 at the rim; smoothstep over the outer 30% shell.
        const double t = saturate((r - d) / (0.3 * r));
        const double f = t * t * (3.0 - 2.0 * t);
        if (f > best) {
            best = f;
        }
    }
    return best;
}

}  // namespace

double fbm(double x, double y, double z) {
    double a = 0.5, s = 0.0;
    for (int i = 0; i < 5; ++i) {
        s += a * vnoise(x, y, z);
        x = x * 2.02;
        y = y * 2.02;
        z = z * 2.02;
        a *= 0.5;
    }
    return s;
}

void seed_for(double cx, double cy, double cz, double out[3]) {
    out[0] = cx * 0.013 + 11.7;
    out[1] = cy * 0.013 + 23.1;
    out[2] = cz * 0.013 + 47.3;
}

double density(double px, double py, double pz, const Sphere* spheres,
               std::size_t n, const double seed[3], double freq, double gain,
               double floor, double drift_t) {
    const double bound = sphere_union_falloff(px, py, pz, spheres, n);
    if (bound <= 0.0) {
        return 0.0;
    }
    const double sx = seed[0], sy = seed[1], sz = seed[2];
    const double nz = fbm(px * freq + sx + drift_t, py * freq + sy, pz * freq + sz);
    return bound * saturate(nz * gain - floor);
}

}  // namespace dauntless::combat
