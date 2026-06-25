#version 330 core

in vec3 v_pos_local;
in vec2 v_uv;

uniform sampler2D u_texture;
uniform mat3  u_world_rotation;  // column 1 = patch-centre direction (kForward)
uniform vec2  u_tile;
uniform vec2  u_span;
uniform int   u_use_alpha;   // 0 = opaque (Star), 1 = blended (Backdrop)
uniform int   u_procedural;   // 0 = stock texture path, 1 = procedural
uniform int   u_proc_kind;    // 0 = stars, 1 = starcloud (galaxy), 2 = nebula
uniform int   u_envelop;      // 1 = camera inside this feature: fill the whole sky
uniform vec3  u_color;        // recorded dominant colour, 0..1
uniform float u_coverage;     // density 0..1
uniform float u_seed;
uniform float u_time;

out vec4 frag_color;

float hash13(vec3 p3){ p3 = fract(p3*0.1031); p3 += dot(p3, p3.zyx+31.32); return fract((p3.x+p3.y)*p3.z); }
vec3  hash33(vec3 p3){ p3 = fract(p3*vec3(0.1031,0.1030,0.0973)); p3 += dot(p3, p3.yxz+33.33); return fract((p3.xxy+p3.yxx)*p3.zyx); }
float vnoise(vec3 p){
    vec3 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
    float n000=hash13(i), n100=hash13(i+vec3(1,0,0));
    float n010=hash13(i+vec3(0,1,0)), n110=hash13(i+vec3(1,1,0));
    float n001=hash13(i+vec3(0,0,1)), n101=hash13(i+vec3(1,0,1));
    float n011=hash13(i+vec3(0,1,1)), n111=hash13(i+vec3(1,1,1));
    return mix(mix(mix(n000,n100,f.x),mix(n010,n110,f.x),f.y),
               mix(mix(n001,n101,f.x),mix(n011,n111,f.x),f.y), f.z);
}
float fbm(vec3 p){ float a=0.5,s=0.0; for(int k=0;k<5;k++){ s+=a*vnoise(p); p*=2.02; a*=0.5; } return s; }
// Ridged turbulence — sharper filaments than fbm, for nebula wisps + dust lanes.
float turb(vec3 p){ float a=0.5,s=0.0; for(int k=0;k<5;k++){ s+=a*abs(2.0*vnoise(p)-1.0); p*=2.03; a*=0.5; } return s; }

vec3 proc_stars(vec3 dir, float density){
    vec3 g = dir*220.0; vec3 cell = floor(g);
    vec3 rnd = hash33(cell + u_seed);
    float present = step(1.0 - density, rnd.x);
    vec3 starPos = cell + 0.2 + 0.6*hash33(cell+7.1);
    float d = length(g - starPos);
    float core = present * smoothstep(0.6, 0.0, d);
    float tw = 0.75 + 0.25*sin(u_time*(1.0+2.0*rnd.z) + rnd.y*6.2831);
    vec3 tint = mix(vec3(0.7,0.8,1.0), vec3(1.0,0.9,0.75), rnd.z);
    return core * (0.4 + 0.6*rnd.y) * tw * tint;
}

void proc_main(vec3 dir, vec2 offset){
    if (u_proc_kind == 0) {
        // STAR SPHERE: modulate density by a low-frequency field so the whole
        // sky has dense drifts and sparse voids — cluster variety everywhere,
        // not only where a galaxy backdrop happens to exist.
        float field = fbm(dir*1.3 + 3.0*u_seed);
        float dens  = mix(0.00225, 0.015, smoothstep(0.30, 0.85, field));  // density 1.5x baseline (was 0.0015..0.01)
        // stars brightened +50% over original (haze on the next line left unchanged)
        vec3 c = 1.5*(proc_stars(dir, dens) + 0.55*proc_stars(dir*1.7 + 11.0, dens*0.6));
        // faint unresolved-star haze pooling in the densest drifts
        c += vec3(0.55, 0.6, 0.8) * 0.05 * smoothstep(0.62, 0.95, field);
        frag_color = vec4(c, 1.0); return;
    }
    // Star-clouds use the projected span directly. The earlier 4x multiplier
    // (added when spans were tiny) blew each cloud up to near-full-sphere; with
    // map-driven spans (~1.5) that produced 5 overlapping sky-wide dense fields.
    // Angular falloff from the patch centre, computed in 3D — NOT from v_uv.
    // The UV-based cutoff broke at the sphere's longitude seam (u:1->0) and
    // poles, where v_uv is discontinuous; on large patches that printed hard
    // straight lines across the sky. The angle between the fragment direction
    // and the feature's forward axis (world_rotation column 1) has no seam or
    // pole, so the patch is a clean circular cap.
    // Angular falloff from the patch centre — but ONLY when the feature is a
    // bounded patch in the distance. When the camera is INSIDE the feature's
    // sphere (u_envelop), there is no "centre direction": the feature wraps the
    // whole sky, so the cap is dropped and edge stays 1.0 everywhere. Without
    // this, the far hemisphere (ang > R) discarded and the nebula vanished from
    // the inside — the exact opposite of being engulfed.
    float edge = 1.0;
    if (u_envelop == 0) {
        vec3  fwd = normalize(vec3(u_world_rotation[1]));
        float ang = acos(clamp(dot(dir, fwd), -1.0, 1.0));   // radians from centre
        float R   = max(u_span.x, 1e-3) * 0.30;              // angular radius (rad)
        edge = 1.0 - smoothstep(0.55*R, R, ang);
        if (edge <= 0.0) discard;
    }
    vec3 np = dir*3.0 + u_seed; float drift = u_time*0.01;
    if (u_proc_kind == 2) {
        // NEBULA: filamentary structure, slight colour variety rooted in the
        // recorded hue, and bright stellar-nursery cores.
        float n     = fbm(np + vec3(drift));
        float fil   = turb(np*1.7 + vec3(drift*0.6));      // wispy filaments
        float field = mix(n, fil, 0.55);
        float cov   = min(1.0, u_coverage * 1.5);          // 1.5x (was 2x: -25% density)
        float dens  = smoothstep(1.0 - cov*0.9, 1.0, field + 0.15);
        // cool dim wisps -> warm bright cores, both anchored to u_color so the
        // recorded hue stays dominant (slight variety, not a different colour).
        vec3 cool = u_color * vec3(0.85, 0.95, 1.15);
        vec3 warm = u_color * vec3(1.20, 1.02, 0.85);
        vec3 base = mix(cool, warm, smoothstep(0.30, 0.85, field)) * (0.45 + 0.95*field);
        // stellar nursery: hot emission knots + embedded young stars in the
        // densest cores, brightening from u_color toward white-hot.
        float core = smoothstep(0.80, 1.0, field);
        vec3 emission = mix(u_color*1.6, vec3(1.0, 0.96, 0.9), 0.55*core) * core;
        vec3 young = proc_stars(dir, 0.22*core) * (1.0 + 2.5*core);
        // Scaled for additive blending — full-strength nebulae blew out to white.
        vec3 col = (base + emission + young) * 0.40;
        frag_color = vec4(col, clamp(max(dens, core)*edge, 0.0, 1.0));
    } else {
        // STARCLOUD (galaxy): a denser-than-base star region + diffuse dust glow
        // + dark dust lanes. Density well below the old 0.24 so several clouds
        // don't saturate the sky into a uniform white field.
        vec3 stars = proc_stars(dir, 0.06) * edge;
        float glowN = fbm(np*0.6 + vec3(drift));
        float lanes = smoothstep(0.50, 0.72, turb(np*1.8));
        float dust = (0.32 + 0.55*glowN) * (1.0 - 0.88*lanes);
        vec3 col = (stars*(1.0 - 0.88*lanes) + u_color*dust) * 0.45;
        frag_color = vec4(col, max(dust*edge, length(stars)));
    }
}

void main() {
    if (u_procedural == 1) {
        proc_main(normalize(v_pos_local), v_uv - vec2(0.25, 0.5));
        return;
    }
    // The textured patch is centred on the sphere mesh vertex
    // (cos_t*cos_p, cos_t*sin_p, sin_t) at UV = (0.25, 0.5), which lives
    // at local position (0, 1, 0). u_world_rotation columns are
    // (right, forward, up) from AlignToVectors, so a_pos.y = 1 carries
    // that point onto kForward — the texture centre ends up where the
    // script asked the backdrop to point. Anchoring at (0, 0) instead
    // (the old behaviour) put the patch at v = south pole, where every
    // mesh vertex collapses to a single point and the texture got
    // smeared into a triangular fan-out — visible on E1M1 as wedge
    // artefacts in the treknebula.
    // BC's H/VSpan semantics aren't pinned to instrumented data yet — see
    // project_backdrop_span_semantics memory. Treating span as a *radius*
    // in UV space (rather than the full diameter) gives an ~54° patch on
    // E1M1 instead of ~109°, which matches "compact nebula in the sky"
    // expectation. Half-extent in each axis = u_span.{x,y} * 0.5, so the
    // discard threshold is `abs(offset) > span * 0.25` and the UV remap
    // doubles the offset.
    vec2 offset = v_uv - vec2(0.25, 0.5);
    if (abs(offset.x) > u_span.x * 0.25 || abs(offset.y) > u_span.y * 0.25) {
        if (u_use_alpha == 1) discard;
    }
    vec2 uv;
    if (u_use_alpha == 1) {
        // Centred partial-coverage patch (nebulae). Flip U: from inside the
        // sphere looking at kForward, increasing mesh longitude rotates
        // toward -kRight, so we invert it to get the texture's +U pointing
        // to the viewer's right.
        uv = vec2(0.5 - 2.0 * offset.x / u_span.x,
                  0.5 + 2.0 * offset.y / u_span.y) * u_tile;
    } else {
        // StarSphere: tile across the whole sphere. The centred-patch
        // remap above doubles the tile frequency, which shrinks each star
        // to sub-pixel size and lets mipmap minification average them
        // toward black — visibly dim starfield.
        uv = v_uv * u_tile;
    }
    vec4 tex = texture(u_texture, uv);
    if (u_use_alpha == 1) {
        frag_color = vec4(tex.rgb, tex.a);
    } else {
        frag_color = vec4(tex.rgb * 2.0, 1.0);
    }
}
