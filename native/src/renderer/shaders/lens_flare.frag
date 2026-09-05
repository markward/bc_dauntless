#version 410 core
in  vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform float     u_brightness;   // global fade in [0, 1]

void main() {
    vec4 t = texture(u_texture, v_uv);
    frag_color = vec4(t.rgb, t.a) * u_brightness;
}
