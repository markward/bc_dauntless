# Embed shader sources as char arrays via configure_file. Each shader gets a
# generated header with a constexpr string. This keeps shader text in *.vert /
# *.frag (so editors highlight them) without runtime file I/O.

function(embed_shader OUT_VAR INPUT_PATH SYMBOL_NAME)
    file(READ "${INPUT_PATH}" SRC)
    set(GENERATED "${CMAKE_CURRENT_BINARY_DIR}/embedded_${SYMBOL_NAME}.h")
    file(WRITE "${GENERATED}.in"
"// Generated. Do not edit.\n#pragma once\nnamespace renderer::shader_src {\nconstexpr const char* ${SYMBOL_NAME} = R\"GLSL(@SRC@)GLSL\";\n}\n")
    configure_file("${GENERATED}.in" "${GENERATED}" @ONLY)
    set(${OUT_VAR} "${GENERATED}" PARENT_SCOPE)
endfunction()

embed_shader(SHADER_OPAQUE_VS shaders/opaque.vert opaque_vs)
embed_shader(SHADER_OPAQUE_FS shaders/opaque.frag opaque_fs)
embed_shader(SHADER_SKINNED_VS shaders/skinned.vert skinned_vs)
embed_shader(SHADER_BACKDROP_VS shaders/backdrop.vert backdrop_vs)
embed_shader(SHADER_BACKDROP_FS shaders/backdrop.frag backdrop_fs)
embed_shader(SHADER_SUN_VS shaders/sun.vert sun_vs)
embed_shader(SHADER_SUN_FS shaders/sun.frag sun_fs)
embed_shader(SHADER_SUN_FLARE_VS shaders/sun_flare.vert sun_flare_vs)
embed_shader(SHADER_SUN_FLARE_FS shaders/sun_flare.frag sun_flare_fs)
embed_shader(SHADER_DUST_VS shaders/dust.vert dust_vs)
embed_shader(SHADER_DUST_FS shaders/dust.frag dust_fs)
embed_shader(SHADER_NEBULA_VS shaders/nebula.vert nebula_vs)
embed_shader(SHADER_NEBULA_FS shaders/nebula.frag nebula_fs)
embed_shader(SHADER_NEBULA_SHELL_VS shaders/nebula_shell.vert nebula_shell_vs)
embed_shader(SHADER_NEBULA_SHELL_FS shaders/nebula_shell.frag nebula_shell_fs)
embed_shader(SHADER_NEBULA_VOLUMETRIC_VS shaders/nebula_volumetric.vert nebula_volumetric_vs)
embed_shader(SHADER_NEBULA_VOLUMETRIC_FS shaders/nebula_volumetric.frag nebula_volumetric_fs)
embed_shader(SHADER_NEBULA_UPSAMPLE_FS shaders/nebula_upsample.frag nebula_upsample_fs)
embed_shader(SHADER_NEBULA_GODRAY_VS shaders/nebula_godray.vert nebula_godray_vs)
embed_shader(SHADER_NEBULA_GODRAY_FS shaders/nebula_godray.frag nebula_godray_fs)
embed_shader(SHADER_SHIELD_VS shaders/shield.vert shield_vs)
embed_shader(SHADER_SHIELD_FS shaders/shield.frag shield_fs)
embed_shader(SHADER_LENS_FLARE_VS shaders/lens_flare.vert lens_flare_vs)
embed_shader(SHADER_LENS_FLARE_FS shaders/lens_flare.frag lens_flare_fs)
embed_shader(SHADER_LENS_FLARE_HDR_FS shaders/lens_flare_hdr.frag lens_flare_hdr_fs)
embed_shader(SHADER_LENS_FLARE_BLUR_FS shaders/lens_flare_blur.frag lens_flare_blur_fs)
embed_shader(SHADER_TORPEDO_VS shaders/torpedo.vert torpedo_vs)
embed_shader(SHADER_TORPEDO_FS shaders/torpedo.frag torpedo_fs)
embed_shader(SHADER_DISRUPTOR_VS shaders/disruptor.vert disruptor_vs)
embed_shader(SHADER_DISRUPTOR_FS shaders/disruptor.frag disruptor_fs)
embed_shader(SHADER_HIT_VFX_VS shaders/hit_vfx.vert hit_vfx_vs)
embed_shader(SHADER_HIT_VFX_FS shaders/hit_vfx.frag hit_vfx_fs)
embed_shader(SHADER_HULL_DISCHARGE_VS shaders/hull_discharge.vert hull_discharge_vs)
embed_shader(SHADER_HULL_DISCHARGE_FS shaders/hull_discharge.frag hull_discharge_fs)
embed_shader(SHADER_NEBULA_WAKE_VS shaders/nebula_wake.vert nebula_wake_vs)
embed_shader(SHADER_NEBULA_WAKE_FS shaders/nebula_wake.frag nebula_wake_fs)
embed_shader(SHADER_PHASER_VS shaders/phaser.vert phaser_vs)
embed_shader(SHADER_PHASER_FS shaders/phaser.frag phaser_fs)
embed_shader(SHADER_HOLOGRAM_VS shaders/hologram.vert hologram_vs)
embed_shader(SHADER_HOLOGRAM_FS shaders/hologram.frag hologram_fs)
embed_shader(SHADER_BREACH_VS shaders/breach.vert breach_vs)
embed_shader(SHADER_BREACH_FS shaders/breach.frag breach_fs)
embed_shader(SHADER_SUBSYSTEM_PIN_VS shaders/subsystem_pin.vert subsystem_pin_vs)
embed_shader(SHADER_SUBSYSTEM_PIN_FS shaders/subsystem_pin.frag subsystem_pin_fs)
embed_shader(SHADER_TARGET_RETICLE_VS shaders/target_reticle.vert target_reticle_vs)
embed_shader(SHADER_TARGET_RETICLE_FS shaders/target_reticle.frag target_reticle_fs)
embed_shader(SHADER_BRIDGE_VS shaders/bridge.vert bridge_vs)
embed_shader(SHADER_BRIDGE_FS shaders/bridge.frag bridge_fs)
embed_shader(SHADER_VS_STATIC_VS shaders/viewscreen_static.vert viewscreen_static_vs)
embed_shader(SHADER_VS_STATIC_FS shaders/viewscreen_static.frag viewscreen_static_fs)
embed_shader(SHADER_SKINNED_BRIDGE_VS shaders/skinned_bridge.vert skinned_bridge_vs)
embed_shader(SHADER_LIGHTMAP_VS shaders/lightmap.vert lightmap_vs)
embed_shader(SHADER_LIGHTMAP_FS shaders/lightmap.frag lightmap_fs)
embed_shader(SHADER_RESOLVE_VS shaders/resolve.vert resolve_vs)
embed_shader(SHADER_RESOLVE_FS shaders/resolve.frag resolve_fs)
embed_shader(SHADER_FILMIC_FS shaders/filmic.frag filmic_fs)
embed_shader(SHADER_MOTION_BLUR_FS shaders/motion_blur.frag motion_blur_fs)
embed_shader(SHADER_SMAA_LIB   shaders/smaa_lib.glsl  smaa_lib)
embed_shader(SHADER_SMAA_EDGE_VS   shaders/smaa_edge.vert   smaa_edge_vs)
embed_shader(SHADER_SMAA_EDGE_FS   shaders/smaa_edge.frag   smaa_edge_fs)
embed_shader(SHADER_SMAA_WEIGHT_VS shaders/smaa_weight.vert smaa_weight_vs)
embed_shader(SHADER_SMAA_WEIGHT_FS shaders/smaa_weight.frag smaa_weight_fs)
embed_shader(SHADER_SMAA_BLEND_VS  shaders/smaa_blend.vert  smaa_blend_vs)
embed_shader(SHADER_SMAA_BLEND_FS  shaders/smaa_blend.frag  smaa_blend_fs)
embed_shader(SHADER_SHADOW_VS shaders/shadow.vert shadow_vs)
embed_shader(SHADER_SHADOW_FS shaders/shadow.frag shadow_fs)
embed_shader(SHADER_BLOOM_PREFILTER_FS shaders/bloom_prefilter.frag bloom_prefilter_fs)
embed_shader(SHADER_BLOOM_DOWN_FS shaders/bloom_down.frag bloom_down_fs)
embed_shader(SHADER_BLOOM_UP_FS shaders/bloom_up.frag bloom_up_fs)
embed_shader(SHADER_SHOCKWAVE_VS shaders/shockwave.vert shockwave_vs)
embed_shader(SHADER_SHOCKWAVE_FS shaders/shockwave.frag shockwave_fs)
embed_shader(SHADER_SKYBOX_VS shaders/skybox.vert skybox_vs)
embed_shader(SHADER_SKYBOX_FS shaders/skybox.frag skybox_fs)
embed_shader(SHADER_CLOAK_REFRACTION_VS shaders/cloak_refraction.vert cloak_refraction_vs)
embed_shader(SHADER_CLOAK_REFRACTION_FS shaders/cloak_refraction.frag cloak_refraction_fs)

add_library(renderer STATIC
    window.cc
    gl_caps.cc
    shader.cc
    bone_palette.cc
    pose_sampler.cc
    node_anim.cc
    bridge_node_anim_store.cc
    animation_update.cc
    pipeline.cc
    frame.cc
    hdr_target.cc
    cubemap_target.cc
    ldr_target.cc
    bloom_pass.cc
    resolve_pass.cc
    filmic_pass.cc
    motion_blur_pass.cc
    smaa_pass.cc
    sphere_mesh.cc
    backdrop_pass.cc
    sun_pass.cc
    dust_pass.cc
    nebula_pass.cc
    nebula_volumetric_pass.cc
    nebula_godray_pass.cc
    shockwave_pass.cc
    aabb.cc
    glow_region.cc
    dynamic_lights.cc
    ray_trace.cc
    shield_state.cc
    skin_shield.cc
    shield_pass.cc
    lens_flare_pass.cc
    lens_flare_hdr_pass.cc
    torpedo_pass.cc
    hit_vfx_pass.cc
    hull_discharge_pass.cc
    nebula_wake_pass.cc
    particle_pass.cc
    phaser_pass.cc
    hologram_pass.cc
    cloak_pass.cc
    breach_venting.cc
    breach_debris.cc
    breach_pass.cc
    carve_field_cache.cc
    subsystem_pin_pass.cc
    debug_volume_pass.cc
    target_reticle_pass.cc
    letterbox_pass.cc
    bridge_pass.cc
    viewscreen_static_pass.cc
    light_matrix.cc
    shadow_map_target.cc
)
target_include_directories(renderer
    PUBLIC include
    PRIVATE "${CMAKE_CURRENT_BINARY_DIR}"
)
target_compile_features(renderer PUBLIC cxx_std_20)
target_link_libraries(renderer PUBLIC assets scenegraph voxel glad glfw glm)
