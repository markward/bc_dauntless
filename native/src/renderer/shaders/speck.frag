#version 410 core
// Far tier specks (far-tier spec §3): a lit, area-weighted point. The total
// flux is pi p^2 * albedo * light, matching the lit mesh and the impostor of
// the same rock (FarPassGLTest.FluxContinuityAtTwoPixels). Output is
// PREMULTIPLIED, blended GL_ONE, GL_ONE_MINUS_SRC_ALPHA: a speck occludes.
in vec2 v_px;
in vec3 v_pos;
flat in float v_p;
flat in vec3 v_albedo;
flat in float v_alpha;
uniform vec3 u_camera_pos_ws;
uniform vec3 u_ambient_light;                 // the same ambient opaque.frag reads
uniform int u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[4];           // toward each light
uniform vec3 u_dir_light_color[4];
uniform float u_speck_gain;
out vec4 frag_color;

// GLSL twin of renderer::far::lambert_sphere_phase (far_math.cc): disk-mean of
// max(N.L, 0) over a Lambert sphere's visible disk at phase angle acos(c).
float lambert_sphere_phase(float cos_alpha) {
    const float PI = 3.14159265;
    float c = clamp(cos_alpha, -1.0, 1.0);
    float a = acos(c);
    return (2.0 / (3.0 * PI)) * (sin(a) + (PI - a) * c);
}

void main() {
    float p = v_p;
    // coverage: an AA disc of radius p for p >= 1, else a uniform 2x2-px square of
    // total area pi p^2 (continuous at p == 1; total flux == pi p^2 either way).
    float cov = p >= 1.0 ? clamp(p + 0.5 - length(v_px), 0.0, 1.0)
                         : 3.14159265 * p * p / 4.0;
    float a = cov * v_alpha;
    vec3 to_eye = normalize(u_camera_pos_ws - v_pos);
    vec3 light = u_ambient_light;
    for (int i = 0; i < u_dir_light_count; ++i)
        light += u_dir_light_color[i]
               * lambert_sphere_phase(dot(normalize(u_dir_light_dir_ws[i]), to_eye));
    vec3 c = v_albedo * light * u_speck_gain;
    frag_color = vec4(c * a, a);
}
