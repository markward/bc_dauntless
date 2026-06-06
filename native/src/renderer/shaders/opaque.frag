#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;
in vec3 v_position_ws;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;

uniform sampler2D u_glow_map;
uniform vec3 u_emissive_color;

uniform sampler2D u_specular_map;
uniform vec3 u_specular_color;
uniform float u_specular_power;
uniform int u_specular_enabled;

// Fresnel rim light. u_rim_strength == 0.0 disables the term (set per
// draw by frame.cc: the global dauntless_rim toggle AND per-instance
// rim_eligible AND material specular). Tinted by the accumulated
// directional light so the rim only shows where a star hits.
uniform float u_rim_strength;
const float RIM_POWER = 3.0;

uniform vec3 u_ambient_light;
uniform vec3 u_camera_pos_ws;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 V = normalize(u_camera_pos_ws - v_position_ws);

    vec3 lit_dir  = vec3(0.0);
    vec3 spec_acc = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        vec3 L  = normalize(u_dir_light_dir_ws[i]);
        float nl = max(dot(n, L), 0.0);
        lit_dir += nl * u_dir_light_color[i];

        if (u_specular_enabled != 0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);
            spec_acc += s * u_dir_light_color[i];
        }
    }

    vec4 base = texture(u_base_color, v_uv);
    vec3 lit  = (u_ambient_light + lit_dir) * u_diffuse_color * base.rgb;
    vec4 glow = texture(u_glow_map, v_uv);
    vec3 spec = (u_specular_enabled != 0)
        ? spec_acc * u_specular_color * texture(u_specular_map, v_uv).rgb
        : vec3(0.0);

    vec3 rim = vec3(0.0);
    if (u_rim_strength > 0.0) {
        float f = pow(1.0 - max(dot(n, V), 0.0), RIM_POWER);
        rim = f * lit_dir * u_rim_strength;
    }

    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a + spec + rim, 1.0);
}
