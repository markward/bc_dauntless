#version 410 core
layout(location = 0) in vec2 a_corner;   // [-1,1] quad corner

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;     // light world pos
uniform float u_half_size;  // billboard half-size (GU)

out vec2 v_uv;
void main() {
    // View space, where the billboard axes are simply x and y. Pull the centre
    // toward the eye by the sprite's half size (never past 90% of the way), so
    // a light authored ON the hull skin is a whole disc instead of half-clipped
    // or z-fighting with its own surface. The bias is tiny (~0.03 GU) against
    // any hull's thickness, so far-side lights stay occluded (spec §4.4).
    vec3 c = (u_view * vec4(u_center, 1.0)).xyz;
    float d = length(c);
    if (d > 0.0) c *= 1.0 - min(u_half_size / d, 0.9);
    vec3 vp = c + vec3(a_corner * u_half_size, 0.0);
    v_uv = a_corner;
    gl_Position = u_proj * vec4(vp, 1.0);
}
