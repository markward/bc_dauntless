#version 330 core

in vec3 v_dir;

uniform samplerCube u_skybox;

out vec4 frag_color;

void main() {
    frag_color = vec4(texture(u_skybox, normalize(v_dir)).rgb, 1.0);
}
