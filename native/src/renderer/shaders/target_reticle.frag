#version 330 core
in vec2 v_uv;
uniform sampler2D u_tex;   // reticle art (white/grey, tinted by u_tint)
uniform vec4 u_tint;       // multiply colour (rgb) + alpha scale
out vec4 frag;
void main() {
    vec4 t = texture(u_tex, v_uv);
    if (t.a < 0.01) discard;
    frag = t * u_tint;
}
