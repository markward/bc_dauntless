#version 330 core
in vec2 v_uv;
out vec4 frag;

// Depth-aware (nearest-depth bilateral) upsample of the half-res volumetric
// cloud into the full-res HDR target.
//
// The cloud is premultiplied (lit, alpha). A naive bilinear upsample bleeds
// cloud across hull silhouettes (the half-res cloud was clamped to the hull at
// half resolution, but a full-res hull edge cuts between half-res taps). To
// keep silhouettes crisp we sample the FULL-RES depth at this pixel and at the
// four surrounding half-res tap centres, then pick the half-res cloud tap whose
// depth best matches this pixel's depth. Where all four match (open space) this
// degrades gracefully to a bilinear-ish nearest pick; at a hull edge it snaps
// to the tap on the same surface, so the cloud never haloes past the hull.

uniform sampler2D u_cloud;    // half-res premultiplied cloud
uniform sampler2D u_depth;    // full-res HDR depth
uniform vec2 u_half_texel;    // 1 / half_res
uniform vec2 u_full_texel;    // 1 / full_res

void main(){
    float d_full = texture(u_depth, v_uv).r;

    // Four half-res tap centres around this full-res pixel. Snap v_uv to the
    // half-res grid, then offset by ±half a half-texel to land on tap centres.
    vec2 hp = v_uv / u_half_texel - 0.5;     // half-res tap coordinate
    vec2 base = (floor(hp) + 0.5) * u_half_texel;

    vec2 offs[4] = vec2[4](
        vec2(0.0,            0.0),
        vec2(u_half_texel.x, 0.0),
        vec2(0.0,            u_half_texel.y),
        vec2(u_half_texel.x, u_half_texel.y));

    vec4  best_cloud = vec4(0.0);
    float best_err   = 1e20;
    for(int i = 0; i < 4; i++){
        vec2 uv = base + offs[i];
        // Depth at the half-res tap centre, read from the FULL-RES depth (the
        // half-res march clamped to exactly this depth, so it is the right
        // surface to compare against).
        float d_tap = texture(u_depth, uv).r;
        float err = abs(d_tap - d_full);
        if(err < best_err){ best_err = err; best_cloud = texture(u_cloud, uv); }
    }

    // Premultiplied OVER: composited by GL_ONE, GL_ONE_MINUS_SRC_ALPHA.
    frag = best_cloud;
}
