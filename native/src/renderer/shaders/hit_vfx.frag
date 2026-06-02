#version 330 core
in  vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform float     u_alpha;
uniform vec4      u_tint;

void main() {
    vec4 t = texture(u_texture, v_uv);
    frag_color = t * u_tint * vec4(1.0, 1.0, 1.0, u_alpha);
}
