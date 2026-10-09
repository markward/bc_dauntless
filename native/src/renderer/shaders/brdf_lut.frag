#version 410 core
// BridgeProbe split-sum BRDF LUT (Karis, "Real Shading in Unreal Engine 4",
// 2013): for x = NdotV and y = roughness, integrates the GGX specular BRDF
// over the hemisphere and outputs the scale A and bias B applied to F0:
//     integral(f_spec * NdotL) = F0 * A + B.
//
// GGX conventions:
//   a = rough^2 (matches bridge_pbr.h) for the importance-sampled D.
//   Smith-Schlick G with the IBL remap k = a / 2 = rough^2 / 2 -- Karis's
//   "k = alpha / 2" with alpha = rough^2, which is LearnOpenGL's
//   "k_IBL = a^2 / 2" with ITS a = rough. (The DIRECT-light term in
//   bridge.frag uses Karis's other remap, k = (rough + 1)^2 / 8.)
out vec2 FragColor;

uniform float u_size;      // LUT width = height in texels
uniform int   u_samples;   // importance samples (512)

const float PI = 3.14159265358979;

vec2 hammersley(uint i, uint n) {
    return vec2(float(i) / float(n), float(bitfieldReverse(i)) * 2.3283064365386963e-10);
}

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

float g_schlick(float n_dot_x, float k) {
    return n_dot_x / (n_dot_x * (1.0 - k) + k);
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_size;   // texel centres
    float n_dot_v = max(uv.x, 1e-3);
    float rough = uv.y;
    float a = rough * rough;
    float k = a / 2.0;                     // IBL remap, see header

    vec3 V = vec3(sqrt(1.0 - n_dot_v * n_dot_v), 0.0, n_dot_v);
    vec3 N = vec3(0.0, 0.0, 1.0);
    uint n = uint(max(u_samples, 1));
    float A = 0.0, B = 0.0;
    for (uint i = 0u; i < n; ++i) {
        vec3 H = importance_sample_ggx(hammersley(i, n), N, a);
        vec3 L = normalize(2.0 * dot(V, H) * H - V);
        float n_dot_l = max(L.z, 0.0);
        float n_dot_h = max(H.z, 0.0);
        float v_dot_h = max(dot(V, H), 0.0);
        if (n_dot_l > 0.0) {
            float G = g_schlick(n_dot_v, k) * g_schlick(n_dot_l, k);
            float g_vis = G * v_dot_h / max(n_dot_h * n_dot_v, 1e-6);
            float fc = pow(1.0 - v_dot_h, 5.0);
            A += (1.0 - fc) * g_vis;
            B += fc * g_vis;
        }
    }
    FragColor = vec2(A, B) / float(n);
}
