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
                for(float k=1.0;k<=u_light_steps;k+=1.0)
                    occ+=density(p+ld*(k*u_step))*u_density_scale*u_step;
                scat+=u_dir_light_color[l]*exp(-occ);
            }
            vec3 col=(scat*u_scatter + u_rgb*u_self_glow)*dens;
            lit+=transm*col*ext;
            transm*=exp(-ext);
        }
        t+=u_step;
    }
    float alpha=1.0-transm;
    frag=vec4(lit, alpha);   // premultiplied; blended GL_ONE, GL_ONE_MINUS_SRC_ALPHA
}
