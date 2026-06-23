"""Deterministic fbm density field for nebulae — the CPU mirror of the GLSL
copy in shaders/nebula_volumetric.frag. Same formula + per-nebula seed, so the
raymarch (GPU) and concealment (CPU) agree. Pure functions, no deps.

The fbm mirrors backdrop.frag's hash13/vnoise/fbm verbatim (5 octaves, lacunarity
2.02, gain 0.5). GLSL<->Python exactness is review-enforced + tolerance-bounded;
these functions are pinned by tests/unit/test_nebula_density.py.
"""
import math


def _fract(x):
    return x - math.floor(x)


def _hash13(x, y, z):
    # p3 = fract(p3 * 0.1031)
    px, py, pz = _fract(x * 0.1031), _fract(y * 0.1031), _fract(z * 0.1031)
    # p3 += dot(p3, p3.zyx + 31.32)
    d = px * (pz + 31.32) + py * (py + 31.32) + pz * (px + 31.32)
    px, py, pz = px + d, py + d, pz + d
    # fract((p3.x + p3.y) * p3.z)
    return _fract((px + py) * pz)


def _vnoise(x, y, z):
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    fz = fz * fz * (3.0 - 2.0 * fz)

    def h(dx, dy, dz):
        return _hash13(ix + dx, iy + dy, iz + dz)

    n00 = h(0, 0, 0) + (h(1, 0, 0) - h(0, 0, 0)) * fx
    n10 = h(0, 1, 0) + (h(1, 1, 0) - h(0, 1, 0)) * fx
    n01 = h(0, 0, 1) + (h(1, 0, 1) - h(0, 0, 1)) * fx
    n11 = h(0, 1, 1) + (h(1, 1, 1) - h(0, 1, 1)) * fx
    n0 = n00 + (n10 - n00) * fy
    n1 = n01 + (n11 - n01) * fy
    return n0 + (n1 - n0) * fz


def fbm(x, y, z):
    a, s = 0.5, 0.0
    for _ in range(5):
        s += a * _vnoise(x, y, z)
        x, y, z = x * 2.02, y * 2.02, z * 2.02
        a *= 0.5
    return s


def seed_for(cx, cy, cz):
    # Deterministic per-nebula offset; large multipliers so distinct nebulae
    # land in unrelated regions of the noise field.
    return (cx * 0.013 + 11.7, cy * 0.013 + 23.1, cz * 0.013 + 47.3)


def _saturate(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _sphere_union_falloff(px, py, pz, spheres):
    # Smooth 0->1 inward from each sphere boundary; union = max.
    best = 0.0
    for (cx, cy, cz, r) in spheres:
        if r <= 0.0:
            continue
        dx, dy, dz = px - cx, py - cy, pz - cz
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        # 1 at centre, 0 at the rim; smoothstep over the outer 30% shell.
        t = _saturate((r - d) / (0.3 * r))
        f = t * t * (3.0 - 2.0 * t)
        if f > best:
            best = f
    return best


def density(px, py, pz, spheres, seed, freq, gain, density_floor, drift_t):
    bound = _sphere_union_falloff(px, py, pz, spheres)
    if bound <= 0.0:
        return 0.0
    sx, sy, sz = seed
    n = fbm(px * freq + sx + drift_t, py * freq + sy, pz * freq + sz)
    return bound * _saturate(n * gain - density_floor)
