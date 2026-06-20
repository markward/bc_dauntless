#version 330 core
// Depth-only pass. Color writes are disabled (glColorMask FALSE) and the FBO
// has no color attachment (GL_NONE draw buffer); depth is written automatically
// by the fixed-function depth test. Nothing to do here.
void main() {
}
