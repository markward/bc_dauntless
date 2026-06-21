#version 330 core
in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_src;
uniform mat4 u_inv_proj;       // inverse(camera proj)
uniform mat3 u_cam_rot;        // camera view->world rotation
uniform vec3 u_cam_pos;        // camera world position
uniform mat4 u_prev_viewproj;  // previous frame proj * view

// Camera-motion-blur tuning — eye-tunable by rebuilding (like the filmic
// grade). Depthless: the scene is reprojected as if at DISTANCE_GU.
const float STRENGTH    = 1.0;    // motion-vector multiplier
const int   SAMPLES     = 8;      // taps along the vector
const float MAX_UV      = 0.05;   // cap on motion-vector length (screen frac)
const float DISTANCE_GU = 100.0;  // assumed scene distance (game units)

void main() {
    vec2 ndc = v_uv * 2.0 - 1.0;

    // View-space ray through this pixel (far-plane point; direction only).
    vec4 vr = u_inv_proj * vec4(ndc, 1.0, 1.0);
    vec3 ray_view = normalize(vr.xyz / vr.w);

    // Pseudo world point at a fixed distance along the ray.
    vec3 world = u_cam_pos + DISTANCE_GU * (u_cam_rot * ray_view);

    // Where that point sat on screen last frame.
    vec4 clip_prev = u_prev_viewproj * vec4(world, 1.0);
    vec2 uv_prev = (clip_prev.xy / clip_prev.w) * 0.5 + 0.5;

    // Screen-space motion vector, capped.
    vec2 mv = (v_uv - uv_prev) * STRENGTH;
    float len = length(mv);
    if (len > MAX_UV) mv *= MAX_UV / len;

    // Average taps trailing toward the previous position.
    vec3 acc = vec3(0.0);
    for (int i = 0; i < SAMPLES; ++i) {
        float t = float(i) / float(SAMPLES - 1);   // 0..1
        acc += texture(u_src, v_uv - mv * t).rgb;
    }
    frag_color = vec4(acc / float(SAMPLES), 1.0);
}
