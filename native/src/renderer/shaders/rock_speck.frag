#version 410 core
// Rock-field speck band (SPIKE): speck.frag's flux-conserving coverage, plus
// a lit-sphere mode for big specks. Below 1.5 px radius the light is the
// disc-mean Lambert sphere phase (exactly speck.frag); from 3 px up it is
// per pixel on a sphere (view-space normal from the disc), so a near speck
// shows a terminator instead of a flat dot. The two agree on average.
// PREMULTIPLIED, blended GL_ONE, GL_ONE_MINUS_SRC_ALPHA.
in vec3 v_pos;
flat in vec2 v_centre_px;
flat in float v_p;
flat in vec3 v_albedo;
flat in float v_alpha;
flat in vec4 v_seed;
uniform vec3 u_camera_pos_ws;
uniform mat4 u_view;
uniform vec3 u_ambient_light;
uniform int u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[4];           // toward each light
uniform vec3 u_dir_light_color[4];
uniform float u_speck_gain;
out vec4 frag_color;

const float PI = 3.14159265;

float lambert_sphere_phase(float cos_alpha) {
    float c = clamp(cos_alpha, -1.0, 1.0);
    float a = acos(c);
    return (2.0 / (3.0 * PI)) * (sin(a) + (PI - a) * c);
}

void main() {
    float p = v_p;
    vec2 b = floor(v_centre_px + 0.5);
    vec2 f = floor(gl_FragCoord.xy);
    bool in_block = all(greaterThanEqual(f, b - 1.0)) && all(lessThan(f, b + 1.0));
    float square = in_block ? PI * p * p / 4.0 : 0.0;
    vec2 off = gl_FragCoord.xy - v_centre_px;
    // Lumpy silhouette from 3 px up (per-rock phases): the radius wobbles
    // with angle, so a big speck reads as a rock, not a ball.
    float shape_w = clamp((p - 3.0) / 3.0, 0.0, 1.0);
    float th = atan(off.y, off.x);
    float wob = 0.10 * sin(2.0 * th + v_seed.x) + 0.07 * sin(3.0 * th + v_seed.y)
              + 0.05 * sin(5.0 * th + v_seed.z);
    float p_edge = p * (1.0 + shape_w * (wob - 0.05));
    float disc = clamp(p_edge + 0.5 - length(off), 0.0, 1.0) * (p * p / (p * p + 1.0 / 12.0));
    float cov = mix(square, disc, clamp(p - 1.0, 0.0, 1.0));
    float a = cov * v_alpha;
    if (a <= 0.0) discard;

    vec3 to_eye = normalize(u_camera_pos_ws - v_pos);
    // Sphere normal in view space from the pixel's offset (window y is up,
    // as view space's), clamped onto the limb.
    vec2 o = off / max(p, 1e-3);
    float rr = min(dot(o, o), 1.0);
    vec3 n_view = vec3(o * inversesqrt(max(dot(o, o), 1e-6)) * sqrt(rr), sqrt(1.0 - rr));
    // Bumps: a few per-rock sinusoids bend the normal (lit facets, not a ball).
    vec3 bump = vec3(sin(3.0 * o.x + 2.0 * o.y + v_seed.x) + 0.5 * sin(5.0 * o.y - 3.0 * o.x + v_seed.z),
                     sin(3.0 * o.y - 4.0 * o.x + v_seed.y) + 0.5 * sin(5.0 * o.x + 4.0 * o.y + v_seed.w * 6.28),
                     0.0);
    n_view = normalize(n_view + shape_w * 0.15 * bump);
    float sphere_w = clamp((p - 1.5) / 1.5, 0.0, 1.0);
    mat3 v3 = mat3(u_view);
    vec3 light = u_ambient_light;
    for (int i = 0; i < u_dir_light_count; ++i) {
        vec3 L = normalize(u_dir_light_dir_ws[i]);
        float phase = lambert_sphere_phase(dot(L, to_eye));
        float lit = max(dot(n_view, normalize(v3 * L)), 0.0);
        light += u_dir_light_color[i] * mix(phase, lit, sphere_w);
    }
    vec3 c = v_albedo * light * u_speck_gain;
    frag_color = vec4(c * a, a);
}
