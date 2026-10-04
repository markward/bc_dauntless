#version 410 core
// Rock-field puffs (rock_puffs.h): a camera-facing quad of the puff's
// world radius; alpha = opacity * weight * distance fade-in * near fade-out.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_pos_r;         // xyz relative to the field origin, w radius (GU)
layout(location = 8) in vec4 a_albedo_w;      // rgb albedo, a density weight
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_offset;                        // render-space position of the field origin
uniform vec3 u_eye;                           // render-space camera position
uniform float u_opacity, u_start_gu, u_ramp_gu, u_near_fade;
out vec2 v_corner;
flat out vec3 v_centre;
flat out vec3 v_albedo;
flat out float v_alpha;
flat out vec3 v_seed;
void main() {
    vec3 c = a_pos_r.xyz + u_offset;
    float r = a_pos_r.w;
    float d = length(c - u_eye);
    float a_far = u_ramp_gu > 0.0 ? clamp((d - u_start_gu) / u_ramp_gu, 0.0, 1.0)
                                  : (d >= u_start_gu ? 1.0 : 0.0);
    float a_near = clamp((d - r) / max(u_near_fade * r - r, 1e-3), 0.0, 1.0);
    float alpha = u_opacity * a_albedo_w.a * a_far * a_near;
    // Camera-facing in view space.
    vec4 vc = u_view * vec4(c, 1.0);
    if (alpha <= 0.0 || vc.z > -1.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_corner = vec2(0.0); v_centre = c; v_albedo = vec3(0.0); v_alpha = 0.0; v_seed = vec3(0.0);
        return;
    }
    vc.xy += a_corner * r;
    gl_Position = u_proj * vc;
    v_corner = a_corner;
    v_centre = c;
    v_albedo = a_albedo_w.rgb;
    v_alpha = alpha;
    v_seed = fract(sin(a_pos_r.xyz * vec3(12.9898, 78.233, 37.719)) * 43758.5453) * 64.0;
}
