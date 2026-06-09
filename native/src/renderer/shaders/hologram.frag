#version 330 core
in vec3 v_world_pos;
in vec3 v_world_normal;
uniform vec3 u_camera_pos;
uniform vec3 u_color;            // holographic blue
uniform float u_opacity_facing;  // 0.05
uniform float u_opacity_grazing; // 0.50
out vec4 frag;
void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(u_camera_pos - v_world_pos);
    float d = abs(dot(N, V));
    float opacity = u_opacity_grazing - (u_opacity_grazing - u_opacity_facing) * d;
    frag = vec4(u_color * opacity, opacity);
}
