#version 330 core
out vec4 frag_color;

uniform vec4 u_color;   // flat unlit color; alpha carried through (bolt taper fade)

void main() {
    frag_color = u_color;
}
