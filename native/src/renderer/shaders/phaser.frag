#version 330 core
in  vec2 v_uv;
in  float v_t;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform vec4      u_color;

void main() {
    vec4 t = texture(u_texture, v_uv);
    float endpoint_fade = 1.0 - smoothstep(0.95, 1.0, v_t);
    frag_color = t * u_color;
    frag_color.a *= endpoint_fade;
}
