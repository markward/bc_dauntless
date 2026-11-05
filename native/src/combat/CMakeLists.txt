# The native combat step (spec docs/superpowers/specs/2026-10-30-native-combat-step-design.md).
# Every answer must be bit-identical to the Python it replaces, so:
#   * no source may contract a multiply-add (-ffp-contract=off here, plus the
#     clang pragma at the top of each source; MSVC: /fp:precise);
#   * every source is optimised in every configuration, Debug included (Mark
#     runs Debug, and the combat step is the frame's largest cost) -- the
#     per-source pattern of native/src/lottie/CMakeLists.txt.
# set_source_files_properties(... COMPILE_OPTIONS ...) REPLACES the property,
# so each source gets ONE combined list.
set(DAUNTLESS_COMBAT_SOURCES
    src/py_math.cc
    src/nebula_density.cc
    src/profile_eval.cc
    src/mirror.cc
    src/torpedo_table.cc
    src/step_scan.cc
    src/k4_eligibility.cc
    src/sensor_detect.cc
    src/part_pose.cc
    src/weapon_geometry.cc
    src/beam_geometry.cc
    src/projectile_geometry.cc
    src/beam_trace.cc
    src/fire_gates.cc
    src/k1_fire_control.cc
    src/k0_charging.cc
    src/k2_beams.cc
    src/k3_projectiles.cc
    src/damage.cc
    src/tractor_force.cc
    src/impulse.cc
    src/motion_step.cc
    src/published_poses.cc
    src/subsystem_step.cc
)

add_library(dauntless_combat STATIC ${DAUNTLESS_COMBAT_SOURCES})
target_include_directories(dauntless_combat PUBLIC include)
target_compile_features(dauntless_combat PUBLIC cxx_std_20)
# Positions are read live from transform_store() (the detection kernel).
target_link_libraries(dauntless_combat PUBLIC dauntless_transforms)

if(MSVC)
    # MSVC rejects /O2 beside /RTC1 and warns when it overrides /Od or /Ob0,
    # so this directory's Debug flags lose all three; every source here is
    # optimised, so none gets them back.
    string(REGEX REPLACE "/RTC[1csu]+|/Od|/Ob0" "" CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG}")
    set_source_files_properties(${DAUNTLESS_COMBAT_SOURCES} PROPERTIES
        COMPILE_OPTIONS "/fp:precise;$<$<CONFIG:Debug>:/O2>")
else()
    set_source_files_properties(${DAUNTLESS_COMBAT_SOURCES} PROPERTIES
        COMPILE_OPTIONS "-ffp-contract=off;$<$<CONFIG:Debug>:-O2>")
endif()
