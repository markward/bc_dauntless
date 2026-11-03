#pragma once

// Python-exact math for the native combat step.
//
// The combat step's answers must be IDENTICAL to the Python they replace
// (spec docs/superpowers/specs/2026-10-30-native-combat-step-design.md §3.2),
// so every primitive here computes what CPython 3.11.15 computes, bit for bit:
// double everywhere a Python float is used, the same operand order
// (left-associative), and no fused multiply-add (every combat source is built
// with -ffp-contract=off plus the clang pragma; see CMakeLists.txt).
//
// NaN: Python's comparisons decide which branch a NaN takes, so each one is
// written the same way round here. std::min/std::max/fmin/fmax do NOT match
// Python's min/max and must never be used for a value Python computes.
//
// Pinned against the Python by tests/unit/test_native_combat_math.py and
// native/tests/combat/py_math_test.cc.

namespace dauntless::combat {

// Python `min(a, b)`: returns b only if b < a, else a. So min(NaN, 1.0) is NaN
// and min(1.0, NaN) is 1.0 -- the first argument wins unless the second
// strictly beats it.
inline double py_min(double a, double b) { return (b < a) ? b : a; }

// Python `max(a, b)`: returns b only if b > a, else a.
inline double py_max(double a, double b) { return (b > a) ? b : a; }

// engine/appc/nebula_density.py `_saturate`: clamp to [0, 1]; NaN passes
// through (both compares are False).
inline double saturate(double v) {
    return (v < 0.0) ? 0.0 : ((v > 1.0) ? 1.0 : v);
}

// Python `x ** y` for finite y: libm pow. ALWAYS use this, never std::pow with
// a literal exponent: clang folds pow(x, 0.5) into sqrt(x), and libm's pow
// (what CPython calls) is not correctly rounded, so it differs from sqrt by
// an ulp on some inputs (0x1.73a804986b1acp+0 is one). The exponent goes
// through a volatile inside py_math.cc so no caller can be folded.
double py_pow(double x, double y);

// `math.sin(x)` / `math.cos(x)`: libm, each called ALONE. They live in their
// own translation unit because clang pairs an adjacent sin(x) and cos(x) into
// one __sincos_stret call, which can round differently from the two libm
// calls CPython makes (the strip emit point's yaw hit this). NOINLINE too:
// with LTO a separate translation unit is no barrier, and an inlined pair
// could be re-paired.
#if defined(_MSC_VER)
#define DAUNTLESS_PY_MATH_NOINLINE __declspec(noinline)
#else
#define DAUNTLESS_PY_MATH_NOINLINE __attribute__((noinline))
#endif
DAUNTLESS_PY_MATH_NOINLINE double py_sin(double x);
DAUNTLESS_PY_MATH_NOINLINE double py_cos(double x);

// `math.dist(a, b)` for 3-D points: CPython 3.11.15's math_dist_impl +
// vector_norm (Modules/mathmodule.c), ported line for line. NOT
// sqrt(dx*dx + dy*dy + dz*dz): vector_norm scales by a power of two, squares
// losslessly, sums with compensation and corrects the square root, and its
// answer differs from the naive one on ~1 pair in 5.
double dist3(const double a[3], const double b[3]);

// engine/appc/sensor_occlusion.py `_segment_hits`: does the segment a->b pass
// strictly inside the sphere (c, r)? A segment with seg2 <= 1e-12 is a point.
bool segment_hits(double ax, double ay, double az, double bx, double by,
                  double bz, double cx, double cy, double cz, double r);

// engine/appc/sensor_occlusion.py `_contains`: is (x, y, z) strictly inside
// the sphere (c, r)?
bool contains(double x, double y, double z, double cx, double cy, double cz,
              double r);

}  // namespace dauntless::combat
