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
embed_shader(SHADER_BACKDROP_VS shaders/backdrop.vert backdrop_vs)
embed_shader(SHADER_BACKDROP_FS shaders/backdrop.frag backdrop_fs)
embed_shader(SHADER_SUN_VS shaders/sun.vert sun_vs)
embed_shader(SHADER_SUN_FS shaders/sun.frag sun_fs)
embed_shader(SHADER_DUST_VS shaders/dust.vert dust_vs)
embed_shader(SHADER_DUST_FS shaders/dust.frag dust_fs)
embed_shader(SHADER_SHIELD_VS shaders/shield.vert shield_vs)
embed_shader(SHADER_SHIELD_FS shaders/shield.frag shield_fs)
embed_shader(SHADER_LENS_FLARE_VS shaders/lens_flare.vert lens_flare_vs)
embed_shader(SHADER_LENS_FLARE_FS shaders/lens_flare.frag lens_flare_fs)
embed_shader(SHADER_TORPEDO_VS shaders/torpedo.vert torpedo_vs)
embed_shader(SHADER_TORPEDO_FS shaders/torpedo.frag torpedo_fs)
embed_shader(SHADER_HIT_VFX_VS shaders/hit_vfx.vert hit_vfx_vs)
embed_shader(SHADER_HIT_VFX_FS shaders/hit_vfx.frag hit_vfx_fs)
embed_shader(SHADER_PHASER_VS shaders/phaser.vert phaser_vs)
embed_shader(SHADER_PHASER_FS shaders/phaser.frag phaser_fs)

add_library(renderer STATIC
    window.cc
    shader.cc
    pipeline.cc
    frame.cc
    sphere_mesh.cc
    backdrop_pass.cc
    sun_pass.cc
    dust_pass.cc
    aabb.cc
    shield_state.cc
    skin_shield.cc
    shield_pass.cc
    lens_flare_pass.cc
    torpedo_pass.cc
    hit_vfx_pass.cc
    phaser_pass.cc
)
target_include_directories(renderer
    PUBLIC include
    PRIVATE "${CMAKE_CURRENT_BINARY_DIR}"
)
target_compile_features(renderer PUBLIC cxx_std_20)
target_link_libraries(renderer PUBLIC assets scenegraph glad glfw glm)
