#version 410 core
// BridgeProbe GGX prefilter (Karis, "Real Shading in Unreal Engine 4", 2013):
// fills one face of one mip of the prefiltered cube with the raw capture
// convolved by the GGX lobe at u_roughness, under Karis's N = V = R
// assumption. Mip k of the output is roughness k / (mips - 1); the bridge
// shader then samples textureLod(cube, R, rough * (mips - 1)).
//
// GGX convention (matches bridge_pbr.h): a = rough^2, D = a^2 / (pi * (
// NdotH^2 (a^2 - 1) + 1)^2). Importance sampling draws H from D * NdotH.
//
// Fireflies: each sample reads the raw cube at a level chosen from the
// sample's pdf (the "filtered importance sampling" of GPU Gems 3 ch. 20), so
// a few hundred samples stay smooth. The raw cube therefore carries a full
// glGenerateMipmap chain; u_env_size / u_env_max_lod describe it because
// GLSL 410 has no textureQueryLevels.
out vec4 FragColor;

uniform samplerCube u_env;          // raw capture, full mip chain
uniform float       u_roughness;    // 0..1 for this output mip
uniform int         u_face;         // 0..5, GL_TEXTURE_CUBE_MAP_POSITIVE_X + i
uniform float       u_face_size;    // this output mip's size in texels
uniform float       u_env_size;     // raw cube level-0 size in texels
uniform float       u_env_max_lod;  // raw cube's last mip level
uniform int         u_samples;      // importance samples (256)

const float PI = 3.14159265358979;

// The GL cube-map face selection table (GL 4.1 spec, table 3.21), inverted:
// face + (s, t) in [0,1]^2 of that face's texel -> the direction it stores.
// Texel row 0 is t = 0, which is gl_FragCoord.y = 0 when rendering the face.
vec3 face_direction(int face, vec2 st) {
    vec2 c = st * 2.0 - 1.0;   // (sc, tc)
    if (face == 0) return vec3( 1.0, -c.y, -c.x);
    if (face == 1) return vec3(-1.0, -c.y,  c.x);
    if (face == 2) return vec3( c.x,  1.0,  c.y);
    if (face == 3) return vec3( c.x, -1.0, -c.y);
    if (face == 4) return vec3( c.x, -c.y,  1.0);
    return              vec3(-c.x, -c.y, -1.0);
}

vec2 hammersley(uint i, uint n) {
    return vec2(float(i) / float(n), float(bitfieldReverse(i)) * 2.3283064365386963e-10);
}

// GGX half-vector around N for the uniform pair xi; a = rough^2.
vec3 importance_sample_ggx(vec2 xi, vec3 N, float a) {
    float phi = 2.0 * PI * xi.x;
    float cos_t = sqrt((1.0 - xi.y) / (1.0 + (a * a - 1.0) * xi.y));
    float sin_t = sqrt(max(1.0 - cos_t * cos_t, 0.0));
    vec3 h = vec3(cos(phi) * sin_t, sin(phi) * sin_t, cos_t);
    vec3 up = abs(N.z) < 0.999 ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
    vec3 tx = normalize(cross(up, N));
    vec3 ty = cross(N, tx);
    return normalize(tx * h.x + ty * h.y + N * h.z);
}

float d_ggx(float n_dot_h, float a) {
    float a2 = a * a;
    float d = n_dot_h * n_dot_h * (a2 - 1.0) + 1.0;
    return a2 / (PI * d * d);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_face_size;
    vec3 N = normalize(face_direction(u_face, st));

    // Roughness 0 is the mirror: mip 0 is a straight copy of the capture.
    if (u_roughness <= 0.0) {
        FragColor = vec4(textureLod(u_env, N, 0.0).rgb, 1.0);
        return;
    }

    vec3 V = N;   // Karis: N = V = R
    float a = u_roughness * u_roughness;
    float sa_texel = 4.0 * PI / (6.0 * u_env_size * u_env_size);
    uint n = uint(max(u_samples, 1));
    vec3 sum = vec3(0.0);
    float weight = 0.0;
    for (uint i = 0u; i < n; ++i) {
        vec3 H = importance_sample_ggx(hammersley(i, n), N, a);
        vec3 L = normalize(2.0 * dot(V, H) * H - V);
        float n_dot_l = dot(N, L);
        if (n_dot_l > 0.0) {
            float n_dot_h = max(dot(N, H), 0.0);
            float h_dot_v = max(dot(H, V), 1e-4);
            // pdf of L = D * NdotH / (4 VdotH); its solid angle vs a texel's
            // picks the raw level (0.5 * log2 of the area ratio).
            float pdf = d_ggx(n_dot_h, a) * n_dot_h / (4.0 * h_dot_v) + 1e-4;
            float sa_sample = 1.0 / (float(n) * pdf + 1e-4);
            float lod = clamp(0.5 * log2(sa_sample / sa_texel), 0.0, u_env_max_lod);
            sum += textureLod(u_env, L, lod).rgb * n_dot_l;
            weight += n_dot_l;
        }
    }
    FragColor = vec4(sum / max(weight, 1e-4), 1.0);
}
