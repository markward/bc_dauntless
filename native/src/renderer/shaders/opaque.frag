#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;

uniform vec3 u_ambient_light;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 lit_dir = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        float ndotl = max(dot(n, normalize(u_dir_light_dir_ws[i])), 0.0);
        lit_dir += ndotl * u_dir_light_color[i];
    }
    vec4 tex = texture(u_base_color, v_uv);
    vec3 lit = (u_ambient_light + lit_dir) * u_diffuse_color * tex.rgb;
    frag_color = vec4(lit, 1.0);
}
