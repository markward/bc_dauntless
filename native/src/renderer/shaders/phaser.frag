#version 330 core
in  vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform vec4      u_color;

void main() {
    // Sample the beam texture along U (length) × V (width).
    vec4 t = texture(u_texture, v_uv);
    // Fade alpha near endpoints (avoid hard caps).
    float endpoint_fade = smoothstep(0.0, 0.05, v_uv.x) *
                          (1.0 - smoothstep(0.95, 1.0, v_uv.x));
    frag_color = t * u_color;
    frag_color.a *= endpoint_fade;
}
