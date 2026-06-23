#version 330 core
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

void main(){
    float d_full = texture(u_depth, v_uv).r;

    // Four half-res tap centres around this full-res pixel + the bilinear
    // fraction within the cell.
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
    for(int i = 0; i < 4; i++){
        vec2  uv    = base + offs[i];
        float d_tap = texture(u_depth, uv).r;
        // Depth weight: 1 when the tap is on the same surface, → 0 as depths
        // diverge (a hull edge). exp() keeps it smooth; the +1e-5 floor means
        // if all four are rejected (thin feature) it degrades to a plain blend.
        float dw = exp(-abs(d_tap - d_full) * u_depth_sharpness);
        float w  = bw[i] * dw + 1e-5;
        sum  += texture(u_cloud, uv) * w;
        wsum += w;
    }

    // Premultiplied OVER: composited by GL_ONE, GL_ONE_MINUS_SRC_ALPHA.
    frag = sum / wsum;
}
