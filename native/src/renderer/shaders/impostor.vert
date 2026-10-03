#version 410 core
// Rock impostors (far-tier spec §3; rock-blend 2026-10-03): a unit quad per
// instance, FACING THE CAMERA, linked with the EXISTING opaque.frag compiled
// with IMPOSTOR_VIEWS defined. The quad is only a canvas: opaque.frag finds
// the picture by projecting each fragment's view ray into the three blended
// baked views (far::view_blend), so the quad's pose may change continuously
// with the camera and never snaps with the rock's view.
layout(location = 0) in vec2 a_corner;          // (+-1, +-1)
layout(location = 7) in vec4 a_centre_half;     // xyz render, w half-size GU
layout(location = 8) in vec4 a_axis_x_grid;     // xyz rock glTF +x (render), w atlas grid
layout(location = 9) in vec4 a_axis_y_dither;   // xyz rock glTF +y (render), w signed dither
layout(location = 10) in vec4 a_views;          // xyz view indices
layout(location = 11) in vec4 a_weights;        // xyz view weights
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_camera_pos_ws;
out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;
flat out float v_dither;
flat out vec4 v_imp_centre_half;
flat out vec4 v_imp_axis_x_grid;
flat out vec3 v_imp_axis_y;
flat out vec3 v_imp_views;
flat out vec3 v_imp_weights;
void main() {
    vec3 c = a_centre_half.xyz;
    float h = a_centre_half.w;
    vec3 to_eye = u_camera_pos_ws - c;
    float dist = length(to_eye);
    vec3 e = dist > 0.0 ? to_eye / dist : vec3(0.0, 0.0, 1.0);
    // The bake's basis rule (far::make_view_basis) about the camera's up:
    // up x right == e, so the strip is front-facing (CCW).
    vec3 cam_up = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 right = cross(cam_up, -e);
    if (dot(right, right) < 1e-8) right = cross(vec3(u_view[0][0], u_view[1][0], u_view[2][0]), -e);
    right = normalize(right);
    vec3 up = cross(-e, right);
    // Perspective: the bounding sphere's silhouette at the centre plane is
    // h * dist / sqrt(dist^2 - h^2) -- grow the quad to cover it.
    float grow = dist > 1.001 * h ? dist / sqrt(dist * dist - h * h) : 4.0;
    float s = h * min(grow, 4.0);
    vec3 ws = c + (a_corner.x * right + a_corner.y * up) * s;
    v_uv = a_corner * 0.5 + 0.5;   // unused by the IMPOSTOR_VIEWS fragment path
    v_normal_ws = e;
    v_position_ws = ws;
    v_dither = a_axis_y_dither.w;
    v_imp_centre_half = a_centre_half;
    v_imp_axis_x_grid = a_axis_x_grid;
    v_imp_axis_y = a_axis_y_dither.xyz;
    v_imp_views = a_views.xyz;
    v_imp_weights = a_weights.xyz;
    gl_Position = u_proj * u_view * vec4(ws, 1.0);
}
