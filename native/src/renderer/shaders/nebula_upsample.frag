#version 410 core
in vec2 v_uv;
out vec4 frag;

// Joint-bilateral upsample of the half-res volumetric cloud into the full-res
// HDR target.
//
// The cloud is premultiplied (lit, alpha). A plain bilinear upsample is smooth
// but bleeds cloud across hull silhouettes (the half-res march clamped to the
// hull at low res; a full-res hull edge cuts between half-res taps). The
// previous version avoided that by PICKING the single nearest-depth tap — but a
// hard pick gives every full-res pixel in a low-res cell the same value, which
// shows as a blocky 4x4 grid wherever the cloud is bright (e.g. lit by a
// lightning flash). Instead we BILINEARLY BLEND the four surrounding half-res
// taps, weighting each DOWN by depth mismatch: in open space all four match so
// it is a smooth bilinear blend (the grid dissolves); at a hull edge the wrong-
// surface taps are suppressed so the silhouette stays crisp.

uniform sampler2D u_cloud;        // half-res premultiplied cloud
uniform sampler2D u_depth;        // full-res HDR depth
uniform vec2 u_half_texel;        // 1 / half_res
uniform vec2 u_full_texel;        // 1 / full_res
uniform float u_depth_sharpness;  // higher = harder depth-edge snapping
// 1: compare RELATIVE linear eye depth, |z_tap - z_full| / min(z_tap, z_full),
// instead of the raw depth buffer value. With a far plane far beyond the near
// one, raw depth crowds toward 1 at distance (an occluder 3,000 GU ahead and
// open space differ by ~0.003), so the raw weight barely rejects a wrong-
// surface tap. The far haze sets it (rock-fields Task 12 fix round 1) and
// puts it back to 0; at 0 (the default) this shader is unchanged.
uniform int   u_linear_depth;
uniform float u_near;
uniform float u_far;

float linear_z(float d) {
    float ndc = d * 2.0 - 1.0;
    return 2.0 * u_near * u_far / (u_far + u_near - ndc * (u_far - u_near));
}

float depth_delta(float a, float b) {
    if (u_linear_depth == 0) return abs(a - b);
    float za = linear_z(a), zb = linear_z(b);
    return abs(za - zb) / max(min(za, zb), 1e-6);
}

uniform int u_edge_aa;   // 1: antialias the cloud's own depth edges (far haze; spike/rock-specks)

// The joint-bilateral blend of the four low-res taps around v_uv, matched to
// depth d_ref. With u_edge_aa, a pixel whose four taps all sit on another
// surface widens to the 4x4 low-res neighbourhood before giving up, so a thin
// strip of space beside a hull still finds its haze.
vec4 bilateral(float d_ref) {
    vec2 hp   = v_uv / u_half_texel - 0.5;
    vec2 fr   = fract(hp);
    vec2 base = (floor(hp) + 0.5) * u_half_texel;

    vec2 offs[4] = vec2[4](
        vec2(0.0,            0.0),
        vec2(u_half_texel.x, 0.0),
        vec2(0.0,            u_half_texel.y),
        vec2(u_half_texel.x, u_half_texel.y));
    float bw[4] = float[4](
        (1.0 - fr.x) * (1.0 - fr.y),
        fr.x         * (1.0 - fr.y),
        (1.0 - fr.x) * fr.y,
        fr.x         * fr.y);

    vec4  sum  = vec4(0.0);
    float wsum = 0.0;
    float dsum = 0.0;
    for(int i = 0; i < 4; i++){
        vec2  uv    = base + offs[i];
        float d_tap = texture(u_depth, uv).r;
        // Depth weight: 1 when the tap is on the same surface, → 0 as depths
        // diverge (a hull edge). exp() keeps it smooth; the +1e-5 floor means
        // if all four are rejected (thin feature) it degrades to a plain blend.
        float dw = exp(-depth_delta(d_tap, d_ref) * u_depth_sharpness);
        float w  = bw[i] * dw + 1e-5;
        sum  += texture(u_cloud, uv) * w;
        wsum += w;
        dsum += bw[i] * dw;
    }
    if (u_edge_aa != 0 && dsum < 0.05) {
        vec4  s2 = vec4(0.0);
        float w2 = 0.0;
        for (int y = -1; y <= 2; ++y)
            for (int x = -1; x <= 2; ++x) {
                vec2 uv = base + vec2(float(x), float(y)) * u_half_texel;
                float dw = exp(-depth_delta(texture(u_depth, uv).r, d_ref) * u_depth_sharpness);
                s2 += texture(u_cloud, uv) * dw;
                w2 += dw;
            }
        if (w2 > 0.05) return s2 / w2;
    }
    return sum / wsum;
}

void main(){
    float d_full = texture(u_depth, v_uv).r;
    if (u_edge_aa == 0) { frag = bilateral(d_full); return; }

    // Edge AA: the hull's own edge pixels were resolved from MSAA (part hull,
    // part space) but the depth says one or the other, so the haze would cut
    // on the pixel grid. Where the 3x3 neighbourhood holds two surfaces,
    // blend the haze matched to each by a tent-weighted coverage of the far
    // one (centre 1/4, edges 1/8, corners 1/16) -- a ~1 px soft haze edge.
    float d_far = d_full, d_near = d_full;
    float dn[9];
    int k = 0;
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x) {
            float d = texture(u_depth, v_uv + vec2(float(x), float(y)) * u_full_texel).r;
            dn[k++] = d;
            d_far = max(d_far, d);
            d_near = min(d_near, d);
        }
    if (depth_delta(d_far, d_near) * u_depth_sharpness < 1.0) { frag = bilateral(d_full); return; }
    float cov = 0.0;
    k = 0;
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x) {
            float w = (x == 0 ? 2.0 : 1.0) * (y == 0 ? 2.0 : 1.0) / 16.0;
            bool far_side = depth_delta(dn[k], d_far) < depth_delta(dn[k], d_near);
            cov += far_side ? w : 0.0;
            ++k;
        }
    frag = mix(bilateral(d_near), bilateral(d_far), cov);
}
