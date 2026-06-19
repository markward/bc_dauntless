#version 330 core
in vec2 v_uv;
uniform sampler2D u_noise;
uniform float u_intensity;   // 0..1
out vec4 FragColor;
void main() {
    vec3 n = texture(u_noise, v_uv).rgb;
    FragColor = vec4(n, u_intensity);
}
