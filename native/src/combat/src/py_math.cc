// Python-exact math for the native combat step -- see py_math.h.
//
// dist3 below is a port of math_dist_impl and vector_norm from CPython
// v3.11.15, Modules/mathmodule.c, used under the PSF License Agreement for
// Python (https://docs.python.org/3/license.html), whose notice is retained:
// "Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
// 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023
// Python Software Foundation; All Rights Reserved". It is ported line for line
// so it rounds exactly as the interpreter does: change neither the operand
// order nor the branch order. If the project's interpreter moves off 3.11,
// re-port from that version's mathmodule.c (3.12 changed vector_norm).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/py_math.h"

#include <cmath>
#include <cstddef>

namespace dauntless::combat {

namespace {

// CPython 3.11.15 Modules/mathmodule.c `vector_norm`, verbatim but for the
// asserts and Py_IS_INFINITY/Py_IS_NAN/Py_NAN spelled with <cmath>.
// Given *vec* of n values, sqrt(sum(x ** 2 for x in vec)); *max* is the
// largest fabs(x) (INF if an infinity is present), *found_nan* whether some
// member is a NaN. Lossless power-of-two scaling, Veltkamp-Dekker squaring,
// Neumaier-variant compensated summation and a differential correction of the
// square root -- see the long comment above vector_norm in mathmodule.c.
double vector_norm(std::ptrdiff_t n, double* vec, double max, int found_nan) {
    const double T27 = 134217729.0;     /* ldexp(1.0, 27) + 1.0) */
    double x, scale, oldcsum, csum = 1.0, frac1 = 0.0, frac2 = 0.0, frac3 = 0.0;
    double t, hi, lo, h;
    int max_e;
    std::ptrdiff_t i;

    if (std::isinf(max)) {
        return max;
    }
    if (found_nan) {
        return std::nan("");
    }
    if (max == 0.0 || n <= 1) {
        return max;
    }
    std::frexp(max, &max_e);
    if (max_e >= -1023) {
        scale = std::ldexp(1.0, -max_e);
        for (i=0 ; i < n ; i++) {
            x = vec[i];

            x *= scale;

            t = x * T27;
            hi = t - (t - x);
            lo = x - hi;

            x = hi * hi;
            oldcsum = csum;
            csum += x;
            frac1 += (oldcsum - csum) + x;

            x = 2.0 * hi * lo;
            oldcsum = csum;
            csum += x;
            frac2 += (oldcsum - csum) + x;

            frac3 += lo * lo;
        }
        h = std::sqrt(csum - 1.0 + (frac1 + frac2 + frac3));

        x = h;
        t = x * T27;
        hi = t - (t - x);
        lo = x - hi;

        x = -hi * hi;
        oldcsum = csum;
        csum += x;
        frac1 += (oldcsum - csum) + x;

        x = -2.0 * hi * lo;
        oldcsum = csum;
        csum += x;
        frac2 += (oldcsum - csum) + x;

        x = -lo * lo;
        oldcsum = csum;
        csum += x;
        frac3 += (oldcsum - csum) + x;

        x = csum - 1.0 + (frac1 + frac2 + frac3);
        return (h + x / (2.0 * h)) / scale;
    }
    /* When max_e < -1023, ldexp(1.0, -max_e) overflows.
       So instead of multiplying by a scale, we just divide by *max*.
    */
    for (i=0 ; i < n ; i++) {
        x = vec[i];
        x /= max;
        x = x*x;
        oldcsum = csum;
        csum += x;
        frac1 += (oldcsum - csum) + x;
    }
    return max * std::sqrt(csum - 1.0 + frac1);
}

}  // namespace

double py_pow(double x, double y) {
    volatile double exponent = y;  // opaque to the optimiser (py_math.h)
    return std::pow(x, exponent);
}

// Each in its own out-of-line, never-inlined function: the call sites cannot
// be paired into a __sincos_stret, not even under LTO (py_math.h).
DAUNTLESS_PY_MATH_NOINLINE double py_sin(double x) { return std::sin(x); }
DAUNTLESS_PY_MATH_NOINLINE double py_cos(double x) { return std::cos(x); }

// CPython 3.11.15 Modules/mathmodule.c `math_dist_impl`, the loop and the
// vector_norm call, for two 3-tuples of floats.
double dist3(const double a[3], const double b[3]) {
    double max = 0.0;
    double x, px, qx, result;
    std::ptrdiff_t i;
    const std::ptrdiff_t n = 3;
    int found_nan = 0;
    double diffs[3];

    for (i=0 ; i<n ; i++) {
        px = a[i];
        qx = b[i];
        x = std::fabs(px - qx);
        diffs[i] = x;
        found_nan |= std::isnan(x);
        if (x > max) {
            max = x;
        }
    }
    result = vector_norm(n, diffs, max, found_nan);
    return result;
}

// sensor_occlusion._segment_hits, verbatim.
bool segment_hits(double ax, double ay, double az, double bx, double by,
                  double bz, double cx, double cy, double cz, double r) {
    const double dx = bx - ax, dy = by - ay, dz = bz - az;
    const double seg2 = dx * dx + dy * dy + dz * dz;
    const double px = cx - ax, py = cy - ay, pz = cz - az;
    double t = (seg2 <= 1e-12) ? 0.0 : (px * dx + py * dy + pz * dz) / seg2;
    t = (t < 0.0) ? 0.0 : ((t > 1.0) ? 1.0 : t);
    const double qx = px - t * dx, qy = py - t * dy, qz = pz - t * dz;
    return qx * qx + qy * qy + qz * qz < r * r;
}

// sensor_occlusion._contains, verbatim.
bool contains(double x, double y, double z, double cx, double cy, double cz,
              double r) {
    const double dx = x - cx, dy = y - cy, dz = z - cz;
    return dx * dx + dy * dy + dz * dz < r * r;
}

}  // namespace dauntless::combat
