"""Axis conventions and 4x4 helpers. Matrices are column-major lists of 16
floats, as `_dauntless_host.nif_shapes` returns `world`."""


def bc_to_obj(p):
    """BC model (Z-up) -> OBJ file axes that Blender's default import shows Z-up."""
    return (p[0], p[2], -p[1])


def obj_to_bc(p):
    """Inverse of bc_to_obj: OBJ (x, y, z) is BC (x, -z, y)."""
    return (p[0], -p[2], p[1])


def apply(m, p):
    x, y, z = p
    return (m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def affine_inverse(m):
    """Inverse of an affine column-major 4x4 (general 3x3 part)."""
    a, b, c = m[0], m[4], m[8]
    d, e, f = m[1], m[5], m[9]
    g, h, i = m[2], m[6], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise ValueError("singular transform")
    inv = [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
           (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
           (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]
    # inv is row-major 3x3: inv[r*3 + c]
    t = (m[12], m[13], m[14])
    tt = [-(inv[r * 3] * t[0] + inv[r * 3 + 1] * t[1] + inv[r * 3 + 2] * t[2]) for r in range(3)]
    return [inv[0], inv[3], inv[6], 0.0,
            inv[1], inv[4], inv[7], 0.0,
            inv[2], inv[5], inv[8], 0.0,
            tt[0], tt[1], tt[2], 1.0]
