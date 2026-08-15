#version 330 core
//
// Non-finite probe: reduces a render target to a coarse grid of "did any texel
// in this cell hold a NaN or an Inf" flags. Developer diagnostic for the HDR
// black-square bug -- see renderer/nonfinite_probe.h.
//
// Runs in two passes with the same shader:
//   u_detect != 0 : source is the HDR target; flag non-finite RGB (1.0 / 0.0)
//   u_detect == 0 : source is this shader's own output; take the max
//
// texelFetch, not texture(): sampling must be EXACT. Bilinear filtering would
// smear a flag across neighbouring cells and blur the position we are trying to
// recover, and it interpolates the very NaNs we are hunting.

out vec4 frag_color;

uniform sampler2D u_src;
uniform ivec2     u_block;    // source texels covered by one output texel
uniform int       u_detect;   // 1 = test for non-finite, 0 = max-reduce .r

// Belt-and-braces non-finite test.
//
// isnan()/isinf() are the spec-correct answer, but a driver compiling under
// fast-math assumptions is entitled to fold them to constant false -- and this
// probe exists precisely because we do not trust assumptions about non-finite
// handling. The comparison forms are independent of those builtins:
//   v == v            is false ONLY for NaN
//   !(abs(v) <= MAX)  is true for +/-Inf (and NaN, harmlessly)
// Written as !(a <= b) rather than (a > b) so NaN trips it either way.
bool bad1(float v) {
    return isnan(v) || isinf(v) || !(v == v) || !(abs(v) <= 3.4028235e38);
}

bool bad3(vec3 c) { return bad1(c.r) || bad1(c.g) || bad1(c.b); }

void main() {
    ivec2 size = textureSize(u_src, 0);
    ivec2 base = ivec2(gl_FragCoord.xy) * u_block;

    float acc = 0.0;
    for (int y = 0; y < u_block.y; ++y) {
        for (int x = 0; x < u_block.x; ++x) {
            ivec2 p = base + ivec2(x, y);
            // The block grid is a ceil() of the source size, so the last row /
            // column of cells runs past the edge. texelFetch out of bounds is
            // undefined, so skip rather than clamp (clamping would double-count
            // edge texels, which is harmless for max but muddies intent).
            if (p.x >= size.x || p.y >= size.y) continue;
            vec4 s = texelFetch(u_src, p, 0);
            // In detect mode the flag carries opaque.frag's CAUSE CODE, which
            // that shader parks in alpha when u_nan_debug is on (see its
            // comment). With the shader-side debug off, alpha is its usual 1.0,
            // which reads back as code 1 = "flagged, cause not recorded" -- the
            // host only names a cause when it knows debug was enabled.
            //
            // Either way the value is converted to a finite 0..1 here, so no NaN
            // ever reaches max() -- whose NaN behaviour is exactly the undefined
            // thing that made the original bug so confusing. Alpha itself can be
            // poisoned, hence the nf test on it rather than a bare clamp
            // (clamp is undefined for NaN).
            float v = 0.0;
            if (u_detect != 0) {
                if (bad3(s.rgb)) {
                    float code = bad1(s.a) ? 1.0 : clamp(s.a, 1.0, 255.0);
                    v = code / 255.0;
                }
            } else {
                v = s.r;
            }
            acc = max(acc, v);
        }
    }
    frag_color = vec4(acc, 0.0, 0.0, 1.0);
}
