#version 410 core
// System-scale nebula: the star system as a star-centred atmosphere
// (docs/superpowers/specs/2026-09-29-system-nebula-render-design.md).
// Haze only: a near-field march through the radial profile, then the far
// field from a precomputed (radius, mu) table. Output is premultiplied
// (lit, alpha) into the low-res target; the host upsamples it OVER the HDR
// target exactly as nebula_volumetric.frag's output is.
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_depth;
uniform sampler2D u_radial;     // RG: density(r), tau_star(r); u = sqrt(r/far)
uniform sampler2D u_table_tau;  // far-field OPTICAL DEPTH [u(r), (mu+1)/2]
uniform sampler2D u_table_S;    // far-field inscatter
uniform mat4  u_inv_view_proj;
uniform vec3  u_eye;
uniform vec3  u_star;           // render-space star centre
uniform float u_far_gu;
uniform float u_k_sys;
uniform vec3  u_cloud_rgb;
uniform vec3  u_star_rgb;
uniform float u_g;
uniform float u_floor;
uniform float u_scatter;
uniform float u_near_range;
uniform int   u_steps;
uniform float u_lane_size;
uniform float u_lane_contrast;
uniform vec3  u_noise_origin;
uniform int   u_has_profile;
// Local MetaNebula clumps: density bumps inside the profile haze (or, with no
// profile at all, the ONLY density in this system). One sphere per clump
// (the volume's first sphere), at most 8.
uniform int   u_clump_count;
uniform vec4  u_clump_sphere[8];   // xyz centre, w radius (GU, render space)
uniform vec3  u_clump_rgb[8];
uniform vec3  u_clump_fbm[8];      // freq, gain, floor
uniform vec3  u_clump_seed[8];
uniform float u_clump_ext[8];      // 1/visibility per GU per unit clump density
// temporal (same contract as nebula_volumetric.frag)
uniform sampler2D u_prev;
uniform mat4  u_prev_view_proj;
uniform float u_temporal_weight;
uniform vec2  u_half_texel;
uniform float u_dither_amount;
uniform vec2  u_jitter;

// Texture sizes: must match renderer::atmosphere::kRadialTexels / kTableR /
// kTableMu (nebula_atmosphere.h).
const float kRadialTexels = 4096.0;
const float kTableR = 256.0;
const float kTableMu = 128.0;

// --- fbm copy of backdrop.frag / nebula_density.py (keep in sync) ---
float hash13(vec3 p3){ p3=fract(p3*0.1031); p3+=dot(p3,p3.zyx+31.32); return fract((p3.x+p3.y)*p3.z); }
float vnoise(vec3 p){
    vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    float n000=hash13(i),               n100=hash13(i+vec3(1,0,0));
    float n010=hash13(i+vec3(0,1,0)),   n110=hash13(i+vec3(1,1,0));
    float n001=hash13(i+vec3(0,0,1)),   n101=hash13(i+vec3(1,0,1));
    float n011=hash13(i+vec3(0,1,1)),   n111=hash13(i+vec3(1,1,1));
    return mix(mix(mix(n000,n100,f.x),mix(n010,n110,f.x),f.y),
               mix(mix(n001,n101,f.x),mix(n011,n111,f.x),f.y), f.z);
}
float fbm(vec3 p){ float a=0.5,s=0.0; for(int k=0;k<5;k++){ s+=a*vnoise(p); p*=2.02; a*=0.5; } return s; }

const float PI = 3.14159265;
float hg(float g, float c){ float g2=g*g; return (1.0-g2)/(4.0*PI*pow(max(1e-6,1.0+g2-2.0*g*c),1.5)); }

// The CPU samples texel i at u = i/(N-1); map u onto that texel's CENTRE so
// the GPU reads the exact CPU samples, not a half-texel-shifted blend.
float texel_centre(float u, float n){ return (u*(n-1.0)+0.5)/n; }
float u_of_r(float r){ return sqrt(clamp(r/u_far_gu,0.0,1.0)); }

vec2 radial(float r){ return texture(u_radial, vec2(texel_centre(u_of_r(r), kRadialTexels), 0.5)).rg; }

// Clump i's density bump at world point p: a smoothstep spherical falloff
// (the volume's first sphere) times an fbm bump, same shape as
// nebula_volumetric.frag's density() but keyed by that clump's own dials.
float clump_density(int i, vec3 p){
    vec4 s = u_clump_sphere[i]; if (s.w <= 0.0) return 0.0;
    float d = length(p - s.xyz);
    float tb = clamp((s.w - d)/(0.3*s.w), 0.0, 1.0); float b = tb*tb*(3.0-2.0*tb);
    if (b <= 0.0) return 0.0;
    vec3 w = p + u_noise_origin; vec3 f = u_clump_fbm[i]; vec3 sd = u_clump_seed[i];
    float n = fbm(vec3(w.x*f.x+sd.x, w.y*f.x+sd.y, w.z*f.x+sd.z));
    return b * clamp(n*f.y - f.z, 0.0, 1.0);
}
float lanes(vec3 p){
    float n = fbm((p+u_noise_origin)/u_lane_size);          // ~0.5 mean
    return max(0.0, mix(1.0, 2.0*n, u_lane_contrast));
}
float sky_lanes(vec3 dir){ return max(0.0, mix(1.0, 2.0*fbm(dir*6.0+13.0), u_lane_contrast)); }
vec3 world_from_depth(vec2 uv, float d){ vec4 c=vec4(uv*2.0-1.0, d*2.0-1.0, 1.0); vec4 w=u_inv_view_proj*c; return w.xyz/w.w; }
float dither(vec2 fc){ return fract(sin(dot(fc, vec2(12.9898, 78.233))) * 43758.5453); }

// Far-field lookup at a point, to infinity along dir: optical depth and
// inscatter. Transmittance is exp(-tau); a finite segment is a DIFFERENCE of
// optical depths -- never a ratio of stored transmittances, which underflow
// at system scale.
void far_at(vec3 p, vec3 dir, out vec3 tau, out vec3 S){
    vec3 rel = p - u_star; float r = length(rel);
    float mu = r > 1e-3 ? dot(dir, rel/r) : 0.0;
    vec2 uv = vec2(texel_centre(u_of_r(r), kTableR),
                   texel_centre(clamp(mu*0.5+0.5, 0.0, 1.0), kTableMu));
    tau = texture(u_table_tau, uv).rgb; S = texture(u_table_S, uv).rgb;
}

void main(){
    float dsc = texture(u_depth, v_uv).r;
    vec3 wp = world_from_depth(v_uv, dsc);
    float scene_dist = (dsc >= 1.0) ? 1e20 : length(wp - u_eye);
    vec3 dir = normalize(world_from_depth(v_uv, 0.5) - u_eye);

    vec3 transm = vec3(1.0); vec3 lit = vec3(0.0);
    float near_end = min(scene_dist, u_near_range);
    if (u_has_profile == 1 || u_clump_count > 0) {
        // geometric steps: t_i = near_end * ((1+q)^i - 1)/((1+q)^N - 1)
        float q = 0.06; float denom = pow(1.0+q, float(u_steps)) - 1.0;
        float jit = u_dither_amount * dither(gl_FragCoord.xy + u_jitter);
        float t_prev = 0.0;
        for (int i = 1; i <= u_steps; ++i) {
            float t = near_end * (pow(1.0+q, float(i) - 1.0 + jit) - 1.0) / denom;
            // the last step always closes on near_end, where the far field
            // takes over: no unmarched gap whatever the dither offset
            t = (i == u_steps) ? near_end : min(t, near_end);
            float dt = t - t_prev; t_prev = t;
            if (dt <= 0.0) continue;
            vec3 p = u_eye + dir * (t - 0.5*dt);
            vec3 rel = p - u_star; float r = length(rel);
            // The star-centred haze (only when a profile is bound).
            float sig_h = 0.0; float tau_star = 0.0;
            if (u_has_profile == 1) {
                vec2 rd = radial(r);
                sig_h = u_k_sys * rd.x * lanes(p);
                tau_star = rd.y;
            }
            // Local MetaNebula clumps: density bumps that add on top (or, with
            // no profile, are the entire density in this system).
            float sig_c = 0.0; vec3 col_c = vec3(0.0);
            for (int ci = 0; ci < u_clump_count; ++ci) {
                float dc = clump_density(ci, p) * u_clump_ext[ci];
                sig_c += dc;
                col_c += dc * u_clump_rgb[ci];
            }
            float sigma = sig_h + sig_c;
            if (sigma <= 0.0) continue;
            float cos_t = r > 1e-3 ? -dot(dir, rel/r) : 0.0;
            // Density-weighted colour: haze contributes u_cloud_rgb, each
            // clump contributes its own rgb, both weighted by their share of
            // this step's total extinction.
            vec3 weighted_col = (sig_h * u_cloud_rgb + col_c) / sigma;
            vec3 light = u_scatter * hg(u_g, cos_t) * u_star_rgb * weighted_col * exp(-tau_star);
            vec3 emit  = u_floor * weighted_col;
            float ext = sigma * dt;
            lit += transm * (light + emit) * ext;
            transm *= exp(-ext);
        }
        // The far field is the star-centred table: nothing to look up without
        // a bound profile, so a clump-only run skips it entirely.
        if (u_has_profile == 1) {
            vec3 p_end = u_eye + dir * near_end;
            vec3 tau_a, Sa; far_at(p_end, dir, tau_a, Sa);
            if (scene_dist <= u_near_range) {
                // a hull inside the near field: nothing behind it
            } else if (scene_dist < 1e19) {
                vec3 tau_b, Sb; far_at(u_eye + dir*scene_dist, dir, tau_b, Sb);
                vec3 T = exp(-max(tau_a - tau_b, vec3(0.0)));   // <= 1
                vec3 S = max(Sa - T*Sb, vec3(0.0));
                lit += transm * S * sky_lanes(dir); transm *= T;
            } else {
                lit += transm * Sa * sky_lanes(dir); transm *= exp(-tau_a);
            }
        }
    }
    float alpha = 1.0 - dot(transm, vec3(1.0/3.0));
    vec4 cur = vec4(lit, alpha);   // premultiplied

    // ── Conservative temporal reprojection (nebula_volumetric.frag) ────────
    // Anchored at the midpoint of the near-field span: a real forward point
    // that reprojects correctly wherever the camera is.
    if(u_temporal_weight > 0.0){
        vec3 cloud_p = u_eye + dir * (0.5 * near_end);
        vec4 pc = u_prev_view_proj * vec4(cloud_p, 1.0);
        if(pc.w > 0.0){
            vec2 prev_uv = (pc.xy / pc.w) * 0.5 + 0.5;
            // On-screen guard with a one-texel border (bilinear safety).
            if(all(greaterThanEqual(prev_uv, u_half_texel)) &&
               all(lessThanEqual(prev_uv, vec2(1.0) - u_half_texel))){
                vec4 hist = texture(u_prev, prev_uv);
                cur = mix(cur, hist, u_temporal_weight);
            }
        }
    }

    frag = cur;   // premultiplied (lit, alpha)
}
