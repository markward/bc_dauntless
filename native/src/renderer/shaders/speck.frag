#version 410 core
// Far tier specks (far-tier spec §3): a lit, area-weighted point whose total
// flux is pi p^2 * albedo * light, matching the lit mesh and the impostor of
// the same rock (FarPassGLTest.FluxContinuityAtTwoPixels). Output is
// PREMULTIPLIED, blended GL_ONE, GL_ONE_MINUS_SRC_ALPHA: a speck occludes.
in vec3 v_pos;
flat in vec2 v_centre_px;
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

const float PI = 3.14159265;

// GLSL twin of renderer::far::lambert_sphere_phase (far_math.cc): disk-mean of
// max(N.L, 0) over a Lambert sphere's visible disk at phase angle acos(c).
float lambert_sphere_phase(float cos_alpha) {
    float c = clamp(cos_alpha, -1.0, 1.0);
    float a = acos(c);
    return (2.0 / (3.0 * PI)) * (sin(a) + (PI - a) * c);
}

void main() {
    float p = v_p;
    // Two coverage kernels, each of total flux EXACTLY pi p^2:
    //  * square: the 2x2 pixel block whose centres lie within 1 px of the
    //    speck centre, each texel pi p^2 / 4. Chosen by floor(), so it is
    //    always exactly 4 pixels: no sub-pixel shimmer at all.
    //  * disc: an AA disc clamp(p + 0.5 - r, 0, 1). Its plane integral is
    //    pi(p - 1/2)^2 + [pi(p - 1/2) + pi/3] = pi p^2 + pi/12 (p >= 1/2), so
    //    it is scaled by p^2 / (p^2 + 1/12) (ruling R12).
    // Sampled at pixel centres the disc alone shimmers 1.11x across sub-pixel
    // offsets at p = 1, so the speck cross-fades square -> disc over
    // 1 <= p <= 2 (worst shimmer 1.05 over a 16x16 offset grid, any p).
    vec2 b = floor(v_centre_px + 0.5);
    vec2 f = floor(gl_FragCoord.xy);
    bool in_block = all(greaterThanEqual(f, b - 1.0)) && all(lessThan(f, b + 1.0));
    float square = in_block ? PI * p * p / 4.0 : 0.0;
    float disc = clamp(p + 0.5 - length(gl_FragCoord.xy - v_centre_px), 0.0, 1.0)
               * (p * p / (p * p + 1.0 / 12.0));
    float cov = mix(square, disc, clamp(p - 1.0, 0.0, 1.0));
    float a = cov * v_alpha;
    vec3 to_eye = normalize(u_camera_pos_ws - v_pos);
    vec3 light = u_ambient_light;
    for (int i = 0; i < u_dir_light_count; ++i)
        light += u_dir_light_color[i]
               * lambert_sphere_phase(dot(normalize(u_dir_light_dir_ws[i]), to_eye));
    vec3 c = v_albedo * light * u_speck_gain;
    frag_color = vec4(c * a, a);
}
