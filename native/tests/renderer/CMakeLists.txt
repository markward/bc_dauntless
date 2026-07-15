add_executable(renderer_tests
    window_test.cc
    gl_caps_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
    skinned_program_test.cc
    skinned_render_test.cc
    hit_vfx_pass_test.cc
    lighting_test.cc
    backdrop_pass_test.cc
    sun_pass_test.cc
    dust_pass_test.cc
    letterbox_pass_test.cc
    aabb_test.cc
    bone_palette_test.cc
    pose_sampler_test.cc
    node_anim_test.cc
    bridge_node_anim_store_test.cc
    animation_update_test.cc
    glow_region_test.cc
    ray_trace_test.cc
    shield_state_test.cc
    skin_shield_test.cc
    lens_flare_pass_test.cc
    bridge_pass_test.cc
    skinned_bridge_test.cc
    head_weld_seam_test.cc
    hdr_target_test.cc
    cubemap_target_test.cc
    resolve_pass_test.cc
    filmic_pass_test.cc
    motion_blur_pass_test.cc
    bloom_pass_test.cc
    smaa_pass_test.cc
    particle_math_test.cc
    particle_pass_test.cc
    asset_path_test.cc
    hull_clip_test.cc
    breach_pass_test.cc
    breach_venting_test.cc
    breach_debris_test.cc
    comm_pass_test.cc
    viewscreen_brightness_test.cc
    viewscreen_static_pass_test.cc
    light_matrix_test.cc
    shadow_map_target_test.cc
    torpedo_anim_test.cc
)

target_link_libraries(renderer_tests
    PRIVATE
        renderer
        GTest::gtest_main
)

# Force-load the nif static library so block parsers self-register via
# static initializers (matches the pattern used by nif_tests / assets_tests).
if(APPLE)
    target_link_options(renderer_tests PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(renderer_tests PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()

target_include_directories(renderer_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/tests/assets/gpu  # reuse gl_fixture for offscreen contexts
)

gtest_discover_tests(renderer_tests
    PROPERTIES
        ENVIRONMENT "GALLIUM_DRIVER=llvmpipe"
)
