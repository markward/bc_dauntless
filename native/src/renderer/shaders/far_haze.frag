#version 410 core
// Far tier belt haze (docs/superpowers/specs/2026-10-01-far-tier-design.md,
// §2 "Haze"). One fullscreen march per disc source. This is the GLSL twin of
// renderer::far::haze_column / haze_interval (far_field.cc) and must stay
// EXACTLY the same: the same interval (the slab |z| <= u_slab_sigmas * H at the
// OUTER radius, and the cylinder rho <= last table row + u_outer_fade, clipped
// to [0, scene depth]), the same midpoint rule, the same closed-form
// cross-section (with its q == 1 / q == 3 log branches) and the same
// n * sigma-weighted albedo mix. FarPassGLTest.HazeShaderMatchesTheCpuReference
// pins the two together.
// No pixel cut (ruling R16, 2026-10-02): every sample integrates the WHOLE
// population cross-section (mean_cross_section), so the haze does not depend
// on the camera's k (resolution, fov). u_brightness (the source's
// DiscSource::brightness) scales the accumulated COLOUR only -- the
// transmittance, and so alpha, is untouched.
// Sphere sources (u_shape == 1, tile-field haze, added 2026-10-02): the
// interval is the ray's chord through the sphere of radius u_sphere_r, clipped
// to [0, scene depth], and a(x) is 1 within u_sphere_r * (1 - u_sphere_edge),
// a linear ramp to 0 at u_sphere_r -- far_field.cc's sphere_a / the Sphere
// branch of haze_interval. The march itself is shared.
// FarPassGLTest.SphereHazeShaderMatchesTheCpuReference pins the sphere twin.
// Haze noise (every shape since rock-fields R1, 2026-10-02): the march
// density is scaled by m(x) = max(0, 1 + c * (2 fbm((x - centre) /
// u_noise_scale) - 1)), c = clamp(u_noise_contrast, 0, 1) -- 3D value noise
// from an integer (PCG) hash, no textures, fixed to the source. haze_hash /
// value_noise / fbm / noise_m are far_field.cc's haze_hash /
// haze_value_noise_h / haze_fbm / haze_noise_m: keep identical (the seed is
// hashed once per octave in fbm and handed to lattice pre-hashed).
// FarPassGLTest.NoisySphereHazeShaderMatchesTheCpuReference and
// NoisyDiscHazeShaderMatchesTheCpuReference pin them.
// Output is PREMULTIPLIED (rgb, alpha = 1 - T); blend GL_ONE,
// GL_ONE_MINUS_SRC_ALPHA.
in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_depth;
uniform mat4  u_inv_vp;
uniform vec3  u_eye;            // render space
uniform vec3  u_centre;         // render space: centre - origin_sys + eye_render
uniform vec3  u_normal;
uniform int   u_shape;          // 0 disc, 1 sphere (DiscSource::Shape)
uniform float u_sphere_r;
uniform float u_sphere_edge;
uniform float u_table_r[32];
uniform float u_table_a[32];
uniform int   u_table_n;
uniform float u_outer_fade;
uniform float u_h_frac;
uniform float u_h_min;
uniform float u_slab_sigmas;
uniform int   u_pop_n;          // <= 2
uniform float u_pop_density[2];
uniform float u_pop_a_lo[2];
uniform float u_pop_a_hi[2];
uniform float u_pop_rmin[2];
uniform float u_pop_rmax[2];
uniform float u_pop_q[2];
uniform vec3  u_pop_albedo[2];
uniform int   u_steps;          // clamped to [1, kMaxSteps] by the host
uniform float u_noise_scale;    // GU; <= 0 = no noise
uniform float u_noise_contrast; // 0 = no noise
uniform int   u_noise_octaves;  // <= 0 = no noise; capped at kMaxOctaves
uniform int   u_noise_seed;     // the source seed's bits (read as uint)
uniform float u_gain;           // haze_gain * the source's gain_scale
uniform float u_brightness;     // the source's brightness: colour only
// Light: the same inputs speck.frag reads.
uniform vec3 u_ambient_light;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[4];   // toward each light
uniform vec3 u_dir_light_color[4];

const float PI = 3.14159265;
const int kMaxSteps = 64;
const int kMaxOctaves = 8;

// renderer::far::lambert_sphere_phase (far_math.cc).
float lambert_sphere_phase(float cos_alpha) {
    float c = clamp(cos_alpha, -1.0, 1.0);
    float a = acos(c);
    return (2.0 / (3.0 * PI)) * (sin(a) + (PI - a) * c);
}

// ∫ r^e dr from a to b (e may be -1): far_math.cc int_pow.
float int_pow(float a, float b, float e) {
    if (abs(e + 1.0) < 1e-6) return log(b / a);
    return (pow(b, e + 1.0) - pow(a, e + 1.0)) / (e + 1.0);
}

// renderer::far::mean_cross_section (= cross_section_below at r_max).
float mean_cross_section(int i) {
    float rmin = u_pop_rmin[i], rmax = u_pop_rmax[i];
    if (rmax <= rmin) return 0.0;
    float e = -u_pop_q[i];
    return PI * int_pow(rmin, rmax, e + 2.0) / int_pow(rmin, rmax, e);
}

// renderer::far::table_a.
float table_a(float rho) {
    if (u_table_n <= 0) return 0.0;
    if (rho <= u_table_r[0]) return u_table_a[0];
    for (int i = 1; i < 32; ++i) {
        if (i >= u_table_n) break;
        if (rho <= u_table_r[i]) {
            float span = u_table_r[i] - u_table_r[i - 1];
            float u = span > 0.0 ? (rho - u_table_r[i - 1]) / span : 1.0;
            return u_table_a[i - 1] + (u_table_a[i] - u_table_a[i - 1]) * u;
        }
    }
    if (!(u_outer_fade > 0.0)) return 0.0;
    float last_r = u_table_r[u_table_n - 1];
    float u = (rho - last_r) / u_outer_fade;
    return u >= 1.0 ? 0.0 : u_table_a[u_table_n - 1] * (1.0 - u);
}

float scale_height(float rho) { return max(u_h_frac * rho, u_h_min); }

// renderer::far::sphere_a (far_field.cc).
float sphere_a(vec3 p) {
    float R = u_sphere_r;
    float d = length(p - u_centre);
    if (!(R > 0.0) || d >= R) return 0.0;
    float inner = R * (1.0 - clamp(u_sphere_edge, 0.0, 1.0));
    if (d <= inner) return 1.0;
    return (R - d) / (R - inner);
}

// renderer::far::haze_hash: 32-bit PCG output hash. Keep identical.
uint haze_hash(uint v) {
    uint state = v * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

// far_field.cc lattice(): the 24-bit hashed value at a lattice point. `hs`
// is the PRE-HASHED seed (haze_hash(seed)).
float lattice(ivec3 c, uint hs) {
    uint h = haze_hash(uint(c.x) ^ haze_hash(uint(c.y) ^ haze_hash(uint(c.z) ^ hs)));
    return float(h >> 8u) / 16777215.0;
}

float lerp1(float a, float b, float t) { return a + (b - a) * t; }

// renderer::far::haze_value_noise_h (seed pre-hashed). Keep identical.
float value_noise(vec3 p, uint hs) {
    vec3 fl = floor(p);
    vec3 f = p - fl;
    vec3 u = f * f * (3.0 - 2.0 * f);
    ivec3 c = ivec3(fl);
    float x00 = lerp1(lattice(c, hs), lattice(c + ivec3(1, 0, 0), hs), u.x);
    float x10 = lerp1(lattice(c + ivec3(0, 1, 0), hs), lattice(c + ivec3(1, 1, 0), hs), u.x);
    float x01 = lerp1(lattice(c + ivec3(0, 0, 1), hs), lattice(c + ivec3(1, 0, 1), hs), u.x);
    float x11 = lerp1(lattice(c + ivec3(0, 1, 1), hs), lattice(c + ivec3(1, 1, 1), hs), u.x);
    return lerp1(lerp1(x00, x10, u.y), lerp1(x01, x11, u.y), u.z);
}

// renderer::far::haze_fbm (lacunarity 2, gain 0.5, normalised). Keep identical.
float fbm(vec3 p, int octaves, uint seed) {
    int n = min(octaves, kMaxOctaves);
    if (n <= 0) return 0.5;
    float sum = 0.0, norm = 0.0, amp = 1.0;
    vec3 q = p;
    for (int o = 0; o < kMaxOctaves; ++o) {
        if (o >= n) break;
        sum += amp * value_noise(q, haze_hash(seed + uint(o) * 0x9E3779B9u));
        norm += amp;
        amp *= 0.5;
        q *= 2.0;
    }
    return sum / norm;
}

// renderer::far::haze_noise_m: both shapes; 1 with the noise off.
float noise_m(vec3 p) {
    if (!(u_noise_scale > 0.0) || u_noise_contrast == 0.0 || u_noise_octaves <= 0)
        return 1.0;
    float c = clamp(u_noise_contrast, 0.0, 1.0);
    float f = fbm((p - u_centre) / u_noise_scale, u_noise_octaves, uint(u_noise_seed));
    return max(0.0, 1.0 + c * (2.0 * f - 1.0));
}

// renderer::far::density_a.
float density_a(vec3 p) {
    if (u_shape == 1) return sphere_a(p);
    vec3 d = p - u_centre;
    float z = dot(d, u_normal);
    float rho = length(d - u_normal * z);
    float H = scale_height(rho);
    return table_a(rho) * exp(-0.5 * z * z / (H * H));
}

// renderer::far::pop_density.
float pop_density(int i, float a) {
    float span = u_pop_a_hi[i] - u_pop_a_lo[i];
    float w = span > 0.0 ? clamp((a - u_pop_a_lo[i]) / span, 0.0, 1.0)
                         : (a > u_pop_a_lo[i] ? 1.0 : 0.0);
    return u_pop_density[i] * w;
}

vec3 world_from_depth(vec2 uv, float d) {
    vec4 w = u_inv_vp * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return w.xyz / w.w;
}

// renderer::far::haze_interval. Keep identical (see the header comment).
bool haze_interval(vec3 dir, float t_max, out float t0, out float t1) {
    t0 = 0.0;
    t1 = 0.0;
    if (u_shape == 1) {
        float R = u_sphere_r;
        if (!(R > 0.0)) return false;
        vec3 d = u_eye - u_centre;
        float qa = dot(dir, dir), qb = 2.0 * dot(d, dir), qc = dot(d, d) - R * R;
        if (qa < 1e-12) return false;
        float disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) return false;
        float sq = sqrt(disc);
        t0 = max(0.0, (-qb - sq) / (2.0 * qa));
        t1 = min(t_max, (-qb + sq) / (2.0 * qa));
        return t1 > t0;
    }
    if (u_table_n <= 0) return false;
    float R = u_table_r[u_table_n - 1] + max(0.0, u_outer_fade);
    float Z = u_slab_sigmas * scale_height(R);
    vec3 d = u_eye - u_centre;
    t0 = 0.0;
    t1 = t_max;
    float z0 = dot(d, u_normal), dz = dot(dir, u_normal);
    if (abs(dz) < 1e-12) {
        if (abs(z0) > Z) return false;
    } else {
        float a = (-Z - z0) / dz, b = (Z - z0) / dz;
        t0 = max(t0, min(a, b));
        t1 = min(t1, max(a, b));
    }
    vec3 p = d - u_normal * z0, v = dir - u_normal * dz;
    float qa = dot(v, v), qb = 2.0 * dot(p, v), qc = dot(p, p) - R * R;
    if (qa < 1e-12) {
        if (qc > 0.0) return false;
    } else {
        float disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) return false;
        float sq = sqrt(disc);
        t0 = max(t0, (-qb - sq) / (2.0 * qa));
        t1 = min(t1, (-qb + sq) / (2.0 * qa));
    }
    return t1 > t0;
}

void main() {
    float dsc = texture(u_depth, v_uv).r;
    float t_max = 1e30;
    if (dsc < 1.0) t_max = length(world_from_depth(v_uv, dsc) - u_eye);
    vec3 dir = normalize(world_from_depth(v_uv, 0.5) - u_eye);

    float t0, t1;
    if (!haze_interval(dir, t_max, t0, t1)) { frag_color = vec4(0.0); return; }

    vec3 light = u_ambient_light;
    for (int i = 0; i < u_dir_light_count; ++i)
        light += u_dir_light_color[i]
               * lambert_sphere_phase(dot(normalize(u_dir_light_dir_ws[i]), -dir));

    float dt = (t1 - t0) / float(u_steps);
    float T = 1.0;
    vec3 rgb = vec3(0.0);
    for (int s = 0; s < kMaxSteps; ++s) {
        if (s >= u_steps) break;
        float t = t0 + (float(s) + 0.5) * dt;
        vec3 x = u_eye + dir * t;
        float a = density_a(x);
        float sum = 0.0;
        vec3 sum_albedo = vec3(0.0);
        for (int i = 0; i < 2; ++i) {
            if (i >= u_pop_n) break;
            float ns = pop_density(i, a) * mean_cross_section(i);
            sum += ns;
            sum_albedo += ns * u_pop_albedo[i];
        }
        if (!(sum > 0.0)) continue;
        // Noise scales the rock density, not a (haze_column's m).
        float dtau = u_gain * sum * noise_m(x) * dt;
        float ext = exp(-dtau);
        rgb += T * (1.0 - ext) * (sum_albedo / sum) * light * u_brightness;
        T *= ext;
    }
    frag_color = vec4(rgb, 1.0 - T);
}
