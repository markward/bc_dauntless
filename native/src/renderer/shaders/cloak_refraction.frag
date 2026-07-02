#version 330 core
// Cloak: translucent glow-keyed hull + screen-space refraction + chromatic
// dispersion + animated shimmer.
//
// The cloaked hull keeps rendering its own textures, but the glow map acts as
// an opacity filter: dark (non-glowing) surfaces sit at u_opacity_floor (~10%),
// glowing surfaces rise toward u_opacity_ceiling (~50%). Behind the hull we
// sample a scratch copy of the scene at a screen-space offset driven by the
// surface normal (grazing surfaces bend the background most) and split per RGB
// channel so white light disperses like a prism. An animated wobble keeps the
// whole field shimmering. During the cloak-in transition (u_frac ramping 0->1)
// the hull starts near-opaque and fades to the glow-keyed floor/ceiling.
in vec3 v_world_pos;
in vec3 v_world_normal;
in vec2 v_uv;

uniform sampler2D u_scene;       // scratch copy of the HDR scene colour
uniform sampler2D u_base_color;  // hull diffuse texture
uniform sampler2D u_glow_map;    // hull glow map (rgb colour, a = emissive mask)
uniform vec3  u_diffuse_color;   // material diffuse tint (matches opaque pass)
uniform vec3  u_camera_pos;

// Directional + ambient lighting — same values the opaque pass uses so the
// cloaked hull shades identically (no lit/unlit brightness pop at hand-over).
const int MAX_DIR_LIGHTS = 4;
uniform vec3  u_ambient_light;
uniform int   u_dir_light_count;
uniform vec3  u_dir_light_dir_ws[MAX_DIR_LIGHTS];  // direction TOWARD the light
uniform vec3  u_dir_light_color[MAX_DIR_LIGHTS];   // colour × dimmer
uniform vec2  u_viewport;        // framebuffer size in pixels
uniform float u_time;
uniform float u_frac;            // 0..1 cloak progress (0 = visible, 1 = cloaked)
uniform float u_strength;        // max screen-space refraction offset (UV units)
uniform float u_dispersion;      // chromatic split fraction (prism strength)
uniform vec3  u_tint;            // faint cloak tint glowing along the rim
uniform float u_opacity_floor;   // dark-hull alpha at full cloak
uniform float u_opacity_ceiling; // glowing-surface alpha ceiling
uniform float u_shimmer_amp;     // animated screen-space wobble (UV units)
uniform float u_shimmer_speed;   // shimmer angular frequency (rad/s)
uniform float u_normal_bias;     // 0 = flat refraction, 1 = grazing-weighted

out vec4 frag;

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(u_camera_pos - v_world_pos);
    float facing = clamp(abs(dot(N, V)), 0.0, 1.0);
    // Fresnel rim: the cloak-field glow concentrates at grazing angles.
    float fres = pow(1.0 - facing, 3.0);

    vec2 uv = gl_FragCoord.xy / u_viewport;

    // ── Screen-space refraction: bend the background behind the hull. ────────
    // Direction = hull normal projected into screen space. Guard head-on facets
    // where N.xy vanishes so normalize never yields NaN.
    vec2 ndir = N.xy;
    float nlen = length(ndir);
    ndir = (nlen > 1e-4) ? ndir / nlen : vec2(0.0);

    // Strength scales with the surface normal: grazing surfaces (facing -> 0)
    // misalign the background most. u_normal_bias blends flat<->normal-driven.
    float normal_factor = mix(1.0, 1.0 - facing, u_normal_bias);
    float amt = u_strength * u_frac * normal_factor;
    // Animated shimmer rides on top of the static offset.
    float wob = u_shimmer_amp * u_frac
              * sin(u_time * u_shimmer_speed + dot(v_world_pos, vec3(0.2)));
    amt += wob;

    // Per-channel offsets split white light into spectral fringes.
    vec2 oR = ndir * amt * (1.0 + u_dispersion);
    vec2 oG = ndir * amt;
    vec2 oB = ndir * amt * (1.0 - u_dispersion);
    float r = texture(u_scene, clamp(uv + oR, vec2(0.0), vec2(1.0))).r;
    float g = texture(u_scene, clamp(uv + oG, vec2(0.0), vec2(1.0))).g;
    float b = texture(u_scene, clamp(uv + oB, vec2(0.0), vec2(1.0))).b;
    vec3 refracted_bg = vec3(r, g, b);

    // ── Hull surface: textures kept, glow map keys the opacity. ──────────────
    vec3 base = texture(u_base_color, v_uv).rgb;
    vec4 glow = texture(u_glow_map,   v_uv);

    // Shade the diffuse exactly as the opaque pass does — (ambient + Σ n·L) ×
    // material diffuse × base texture — so the hull that hands over from the
    // opaque pass is the same brightness (no "pops to fully lit" flash).
    vec3 lit_dir = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i)
        lit_dir += max(dot(N, normalize(u_dir_light_dir_ws[i])), 0.0)
                 * u_dir_light_color[i];
    vec3 lit = (u_ambient_light + lit_dir) * u_diffuse_color * base;

    float glow_intensity =
        clamp(dot(glow.rgb, vec3(0.299, 0.587, 0.114)) * glow.a, 0.0, 1.0);
    // When fully cloaked: dark hull -> floor (~10%), glowing surfaces -> up to
    // ceiling (~50%). Ease the hull from fully solid (frac 0) into that
    // glow-keyed shell across the transition so opacity blends smoothly rather
    // than popping straight from opaque to translucent.
    float t = smoothstep(0.0, 1.0, clamp(u_frac, 0.0, 1.0));
    float cloaked_alpha = mix(u_opacity_floor, u_opacity_ceiling, glow_intensity);
    float hull_alpha    = mix(1.0, cloaked_alpha, t);

    // Full (un-weighted) surface colour: lit diffuse + self-lit glow + rim tint.
    // The mix() below weights it against the bent background by hull_alpha.
    vec3 surface = lit + glow.rgb * glow.a + u_tint * (fres * u_frac);

    // Composite the surface over the refracted background within this fragment,
    // then over-blend onto the framebuffer. hull_alpha selects how much of the
    // pixel is textured hull vs bent background — at frac 0 it is fully the
    // (solid) hull; approaching full cloak the bent background shows through.
    vec3 col = mix(refracted_bg, surface, hull_alpha);

    // Presence stays high so the refracted / misaligned background reads through
    // the cloak; a slight drop at full cloak softens the silhouette edge.
    float a = mix(1.0, 0.90, t);
    frag = vec4(col, a);
}
