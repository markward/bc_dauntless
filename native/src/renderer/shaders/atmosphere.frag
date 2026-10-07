#version 410 core
// Planet atmosphere single-scattering march. Mirrors renderer::planet_atmo
// (atmosphere_math.cc) function for function -- AtmospherePassTest.
// ShaderMatchesCpuTwin pins the two together. Change one, change both.
in vec3 v_world;
out vec4 frag_color;
uniform vec3  u_camera_pos;
uniform vec3  u_center;
uniform float u_r_planet;
uniform float u_r_top;
uniform vec3  u_color;       // linear
uniform float u_density;
uniform vec3  u_sun_dir;     // unit, toward the sun
uniform vec3  u_sun_color;   // directional 0 colour (carries intensity)
uniform sampler2D u_scene_depth;
uniform vec2  u_viewport;
uniform mat4  u_view;
uniform float u_near;
uniform float u_far;
const int   VIEW_SAMPLES = 8;
const int   SUN_SAMPLES  = 6;
const float OPAQUE_TAU   = 1.0e4;
const float PI = 3.14159265;

// Ray-sphere: returns (t_near, t_far); t_near > t_far means miss.
vec2 sphere(vec3 o, vec3 d, float r) {
    vec3 oc = o - u_center;
    float b = dot(oc, d);
    float c = dot(oc, oc) - r * r;
    float disc = b * b - c;
    if (disc <= 0.0) return vec2(1.0, -1.0);
    float s = sqrt(disc);
    return vec2(-b - s, -b + s);
}
float H()     { return 0.25 * (u_r_top - u_r_planet); }
float sigma() { return u_density / max(u_r_top - u_r_planet, 1e-6); }
float rho(vec3 p) { return exp(-max(length(p - u_center) - u_r_planet, 0.0) / max(H(), 1e-6)); }
float sun_tau(vec3 x) {
    vec2 hp = sphere(x, u_sun_dir, u_r_planet);
    if (hp.x <= hp.y && hp.x > 1e-4) return OPAQUE_TAU;
    vec2 ht = sphere(x, u_sun_dir, u_r_top);
    if (ht.x > ht.y) return 0.0;
    float len = max(ht.y, 0.0);
    float acc = 0.0;
    for (int i = 0; i < SUN_SAMPLES; ++i)
        acc += rho(x + u_sun_dir * ((float(i) + 0.5) * len / float(SUN_SAMPLES)));
    return acc * (len / float(SUN_SAMPLES)) * sigma();
}
float hg(float g, float c) { float g2 = g * g; return (1.0 - g2) / (4.0 * PI * pow(max(1e-6, 1.0 + g2 - 2.0 * g * c), 1.5)); }
float phase(float c) { return 3.0 / (16.0 * PI) * (1.0 + c * c) + 0.25 * hg(0.6, c); }

// Distance from the eye to the opaque surface in the depth buffer along this
// fragment's (unit) ray `dir`; 1e30 when there is none (depth == 1).
// Linearised analytically rather than through inverse(proj * view): the
// projection is glm's zero-to-one under GL's [-1,1] clip volume, so
// ndc = 2d - 1 and z_eye = f*n / (n + 2(1-d)(f-n)) -- every term positive,
// 1-d exact for d in [0.5,1]. The matrix route cancels catastrophically near
// d = 1 and lands hundreds of GU off at planet range.
float scene_t(vec3 dir) {
    vec2 uv = gl_FragCoord.xy / u_viewport;
    float d = texture(u_scene_depth, uv).r;
    if (d >= 1.0) return 1e30;
    float z = u_far * u_near / (u_near + 2.0 * (1.0 - d) * (u_far - u_near));
    float fwd = -(mat3(u_view) * dir).z;   // cos of the ray to the view axis
    return z / max(fwd, 1e-6);
}

// The 24-bit depth quantum at eye distance t (half the depth range is used:
// zero-to-one ndc under a [-1,1] clip volume), x2 for the analytic-vs-mesh
// surface, plus a relative floor for the float reconstruction.
float depth_tolerance(float t) {
    return 4.0 * t * t / (u_near * 16777216.0) + 1.0e-3 * t;
}

void main() {
    if (u_r_top <= u_r_planet) { frag_color = vec4(0.0); return; }
    vec3 o = u_camera_pos;
    vec3 dir = normalize(v_world - o);
    vec2 top = sphere(o, dir, u_r_top);
    if (top.x > top.y) { frag_color = vec4(0.0); return; }
    float t0 = max(top.x, 0.0);
    float t1 = top.y;
    vec2 pl = sphere(o, dir, u_r_planet);
    float st = scene_t(dir);
    if (pl.x <= pl.y && pl.x > 0.0) {
        // The ray hits the analytic planet. The depth buffer holds the
        // planet's own quantised surface here, which can read tens of GU
        // nearer than pl.x at range and would truncate the dense bottom of
        // the march; trust it only when it is nearer by more than a quantum
        // (something genuinely in front of the surface).
        t1 = min(t1, (st < pl.x - depth_tolerance(pl.x)) ? st : pl.x);
    } else {
        t1 = min(t1, st);
    }
    if (!(t1 > t0)) { frag_color = vec4(0.0); return; }
    float ds = (t1 - t0) / float(VIEW_SAMPLES);
    float tau_view = 0.0;
    float acc = 0.0;
    for (int i = 0; i < VIEW_SAMPLES; ++i) {
        vec3 x = o + dir * (t0 + (float(i) + 0.5) * ds);
        float r = rho(x);
        float dt = sigma() * r * ds;
        float t_mid = tau_view + 0.5 * dt;
        acc += r * exp(-(t_mid + sun_tau(x))) * sigma() * ds;
        tau_view += dt;
    }
    vec3 c = acc * phase(dot(dir, u_sun_dir)) * u_color * u_sun_color;
    // max/min rather than clamp: a NaN must never reach bloom.
    c = min(max(c, vec3(0.0)), vec3(65000.0));
    if (any(isnan(c))) c = vec3(0.0);
    frag_color = vec4(c, 0.0);
}
