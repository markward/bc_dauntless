#version 330 core
in vec2 v_uv; out vec4 frag_color;
uniform sampler2D u_src;
uniform float u_threshold;

// Upper bound on bloom input. Legitimate scene values sit in the 0..~100 range
// (emissive ~1-10, region_gain pushes higher); anything past this is a firefly
// or a saturated 16F store, and either way it clamps to white in resolve.frag
// once multiplied by u_bloom_strength. Bounding here is visually inert for any
// sane scene and keeps the mip chain finite.
const float BLOOM_CLAMP = 4096.0;

// Sanitise the HDR sample before it can enter the mip chain.
//
// Why this exists: a single non-finite texel used to poison the entire bloom
// chain and paint a hard-edged black rectangle tens of pixels across.
//   1. +Inf here made `k` below Inf/Inf == NaN.
//   2. NaN survives every weighted sum in bloom_down/bloom_up, and bilinear
//      filtering spreads it across whole texels instead of fading it out, so it
//      climbs the mip chain growing ~2 texels per level.
//   3. resolve.frag adds the bloom, then clamp()s -- and max(NaN, 0.0) yields
//      0.0 on IEEE-maxNum hardware. The block comes out pure black.
// At the coarsest mip one texel covers 64x64 screen pixels, which is how one
// bad pixel became a quarter-screen flash for a single frame.
vec3 sanitize(vec3 c) {
    // NaN -> 0, component-wise select.
    // NOT mix(): it is defined as x*(1-a) + y*a, and NaN*0 == NaN, so the NaN
    // survives. NOT clamp() alone: min/max are undefined for NaN by spec.
    c = vec3(isnan(c.r) ? 0.0 : c.r,
             isnan(c.g) ? 0.0 : c.g,
             isnan(c.b) ? 0.0 : c.b);
    // With NaN gone, clamp is well-defined and bounds +/-Inf and negatives.
    return clamp(c, vec3(0.0), vec3(BLOOM_CLAMP));
}

void main() {
    vec3 c = sanitize(texture(u_src, v_uv).rgb);
    float b = max(max(c.r, c.g), c.b);
    float k = max(b - u_threshold, 0.0) / max(b, 1e-5);
    frag_color = vec4(c * k, 1.0);
}
