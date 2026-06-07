#version 330 core
in vec2 v_uv; out vec4 frag_color;
uniform sampler2D u_src;
uniform float u_threshold;
void main() {
    vec3 c = texture(u_src, v_uv).rgb;
    float b = max(max(c.r, c.g), c.b);
    float k = max(b - u_threshold, 0.0) / max(b, 1e-5);
    frag_color = vec4(c * k, 1.0);
}
