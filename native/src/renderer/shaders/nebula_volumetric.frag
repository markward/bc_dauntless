#version 330 core
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_depth;       // HDR depth (sampleable). No u_scene: the pass
                                 // blends premultiplied (lit, alpha) OVER the HDR
                                 // target via fixed-function blend (no feedback loop).
uniform mat4  u_inv_view_proj;
uniform vec3  u_eye;
uniform float u_near, u_far;

uniform int   u_sphere_count;
uniform vec4  u_spheres[8];      // xyz centre, w radius (GU)
uniform vec3  u_rgb;             // nebula tint / self-glow colour
uniform vec3  u_fbm;             // freq, gain, floor
uniform vec3  u_seed;
uniform float u_time;

uniform int   u_dir_light_count;
uniform vec3  u_dir_light_dir_ws[4];   // direction TOWARD the light
uniform vec3  u_dir_light_color[4];

// Tunable dials.
uniform float u_step;            // march step (GU), default 6.0
uniform int   u_max_steps;       // default 96
uniform float u_density_scale;   // default 0.06 (extinction per GU per density)
uniform float u_scatter;         // default 1.2
uniform float u_self_glow;       // default 0.25
uniform float u_light_steps;     // occlusion taps toward light, default 3.0
uniform float u_color_var;       // 0..1 per-clump warm/cool tint variation

// Half-res perf path (Task 6).
uniform vec2  u_jitter;          // sub-pixel jitter (unused dir; kept for time hash)
uniform float u_dither_amount;   // 0..1 scale on the per-pixel step offset

// Temporal reprojection (conservative). When u_temporal_weight <= 0 OR the
// reprojected UV falls off-screen, history is ignored (full current frame).
uniform sampler2D u_prev;        // previous half-res cloud (premultiplied)
uniform mat4  u_prev_view_proj;  // previous frame's proj*view
uniform float u_temporal_weight; // 0 (no history) .. ~0.85 (max blend)
uniform vec2  u_half_texel;      // 1/half_res, for off-screen guard

// Cheap per-pixel hash in [0,1) for the dither step offset. Decorrelated from
// the fbm hash so the two noises don't beat against each other.
float dither(vec2 fc){
    return fract(sin(dot(fc, vec2(12.9898, 78.233))) * 43758.5453);
}

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

float bound_falloff(vec3 p){
    float best=0.0;
    for(int i=0;i<u_sphere_count;i++){
        float r=u_spheres[i].w; if(r<=0.0) continue;
        float d=length(p-u_spheres[i].xyz);
        float t=clamp((r-d)/(0.3*r),0.0,1.0);
        best=max(best, t*t*(3.0-2.0*t));
    }
    return best;
}
float density(vec3 p){
    float b=bound_falloff(p); if(b<=0.0) return 0.0;
    float n=fbm(vec3(p.x*u_fbm.x+u_seed.x+u_time*0.01,
                     p.y*u_fbm.x+u_seed.y,
                     p.z*u_fbm.x+u_seed.z));
    return b*clamp(n*u_fbm.y - u_fbm.z, 0.0, 1.0);
}

vec3 world_from_depth(vec2 uv, float d){
    vec4 c=vec4(uv*2.0-1.0, d*2.0-1.0, 1.0);
    vec4 w=u_inv_view_proj*c; return w.xyz/w.w;
}

// Sphere-union entry/exit along ray (o,dir): widest [t0,t1] over spheres.
void union_interval(vec3 o, vec3 dir, out float t0, out float t1){
    t0=1e20; t1=-1e20;
    for(int i=0;i<u_sphere_count;i++){
        vec3 c=u_spheres[i].xyz; float r=u_spheres[i].w; if(r<=0.0) continue;
        vec3 L=c-o; float tca=dot(L,dir); float d2=dot(L,L)-tca*tca; float r2=r*r;
        if(d2>r2) continue;
        float thc=sqrt(r2-d2);
        t0=min(t0,tca-thc); t1=max(t1,tca+thc);
    }
}

void main(){
    float dsc=texture(u_depth,v_uv).r;
    vec3 wp=world_from_depth(v_uv,dsc);
    float scene_dist=(dsc>=1.0)?1e20:length(wp-u_eye);

    vec3 dir=normalize(world_from_depth(v_uv,0.5)-u_eye); // ray dir via a mid-depth point
    float t0,t1; union_interval(u_eye,dir,t0,t1);
    if(t1<=t0){ frag=vec4(0.0); return; }        // no cloud here -> no contribution
    float t=max(t0,0.0);
    float tend=min(t1, scene_dist);              // stop at hulls
    if(tend<=t){ frag=vec4(0.0); return; }

    // Dither step-offset: jitter the first sample by up to one step so the
    // (now half-res, low step count) march doesn't band. Cheap hash on the
    // fragment coord; u_dither_amount lets the host dial it (0 disables).
    t += u_step * u_dither_amount * dither(gl_FragCoord.xy + u_jitter);
    if(t>=tend){ frag=vec4(0.0); return; }

    float transm=1.0; vec3 lit=vec3(0.0);
    for(int s=0;s<u_max_steps;s++){
        if(t>=tend || transm<0.02) break;
        vec3 p=u_eye+dir*t;
        float dens=density(p);
        if(dens>0.001){
            float ext=dens*u_density_scale*u_step;
            // single-scatter from up to 4 directional lights w/ cheap occlusion
            vec3 scat=vec3(0.0);
            for(int l=0;l<u_dir_light_count;l++){
                vec3 ld=normalize(u_dir_light_dir_ws[l]);
                float occ=0.0;
                // Self-shadow ONLY the primary (slot 0) light. The occlusion
                // taps are the dominant march cost (lights x taps density() evals
                // per step); shadowing just the sun keeps the cloud's form while
                // cutting that cost ~4x. Fill lights (and future thunder pulses)
                // add unshadowed — visually fine for secondary light.
                if(l==0){
                    for(float k=1.0;k<=u_light_steps;k+=1.0)
                        occ+=density(p+ld*(k*u_step))*u_density_scale*u_step;
                }
                scat+=u_dir_light_color[l]*exp(-occ);
            }
            // Per-clump colour variety: one cheap low-frequency noise octave
            // (≈0.4x the density freq, so it varies clump-to-clump not within)
            // shifts the nebula tint warm↔cool. Visual only — no gameplay/parity
            // coupling. u_color_var dials 0 (uniform) → 1 (full variety).
            float cvar = vnoise(p*(u_fbm.x*0.4) + u_seed.yzx + 13.0);
            vec3 tintmul = mix(vec3(0.70,0.92,1.30), vec3(1.30,1.02,0.70),
                               clamp(cvar,0.0,1.0));
            vec3 base = u_rgb * mix(vec3(1.0), tintmul, u_color_var);
            vec3 col=(scat*u_scatter + u_self_glow)*base*dens;
            lit+=transm*col*ext;
            transm*=exp(-ext);
        }
        t+=u_step;
    }
    float alpha=1.0-transm;
    vec4 cur=vec4(lit, alpha);   // premultiplied

    // ── Conservative temporal reprojection ────────────────────────────────
    // Blend with the previous half-res frame, reprojected by the previous
    // proj*view of a representative cloud point (the march start, t0). The
    // host RESETS history (u_temporal_weight=0) on large camera deltas / warp
    // and on the first frame, so this only fires when the camera barely moved.
    if(u_temporal_weight > 0.0){
        // Anchor at the MIDPOINT of the marched span, not the entry point. When
        // the camera is inside the sphere t0 < 0, so max(t0,0)=0 would anchor at
        // the eye itself — which reprojects every pixel to the same screen point,
        // breaking per-pixel history lookup and leaving the dither noise
        // unresolved (the "noisy while inside" bug). The midpoint is a real
        // forward point in the cloud that reprojects correctly in or out.
        vec3 cloud_p = u_eye + dir * (0.5 * (max(t0, 0.0) + tend));
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
