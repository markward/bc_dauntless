#version 330 core

// Per-vertex (the quad). 4 vertices total.
layout(location = 0) in vec2 a_corner;     // in {-1,-1}, {+1,-1}, {-1,+1}, {+1,+1}
layout(location = 1) in vec2 a_uv;         // matching UVs in [0,1]

// Per-instance (the particle). N instances.
layout(location = 2) in vec4 a_particle;   // xyz = world pos, w = jitter

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_camera_pos;
uniform vec3  u_smear;          // -camera_velocity * smear_seconds
uniform float u_radius;
uniform float u_size_min;
uniform float u_size_max;
uniform float u_brightness_min;
uniform float u_brightness_max;

out vec2  v_uv;
out float v_brightness;
out vec3  v_local;

void main() {
    // Toroidal wrap of the particle's world position into a 2R cube
    // around the camera. mod() is GLSL's true modulo (always
    // non-negative for positive divisor).
    vec3 local = a_particle.xyz - u_camera_pos;
    local = mod(local + u_radius, 2.0 * u_radius) - u_radius;
    vec3 world_pos = u_camera_pos + local;

    // Billboard basis from the inverse rotation of the view matrix.
    // For an orthonormal view rotation, inverse == transpose, so the
    // world-space camera-right vector is the first row of the rotation
    // submatrix.
    vec3 cam_right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 cam_up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);

    // Per-particle size and brightness from the jitter channel. Multiply
    // jitter by 7.0 then take the fractional part to decorrelate size
    // from brightness while staying single-channel.
    float jitter = a_particle.w;
    float size       = mix(u_size_min,       u_size_max,       fract(jitter * 7.0));
    float brightness = mix(u_brightness_min, u_brightness_max, jitter);

    vec3 offset = a_corner.x * size * cam_right
                + a_corner.y * size * cam_up;

    // Stretch the leading edge (a_corner.y > 0) and trailing edge along
    // the smear vector. Half the smear length on each side gives a total
    // streak length equal to |u_smear|.
    offset += 0.5 * a_corner.y * u_smear;

    gl_Position = u_proj * u_view * vec4(world_pos + offset, 1.0);

    v_uv = a_uv;
    v_brightness = brightness;
    v_local = local;
}
