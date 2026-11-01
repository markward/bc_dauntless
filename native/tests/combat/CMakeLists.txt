add_executable(combat_tests
    py_math_test.cc
    mirror_test.cc
    sensor_detect_test.cc
    weapon_geometry_test.cc
    beam_geometry_test.cc
    projectile_geometry_test.cc
    beam_trace_test.cc
    fire_gates_test.cc
    k1_fire_control_test.cc
    k2_beams_test.cc
    k3_projectiles_test.cc
    k4_eligibility_test.cc
)
target_link_libraries(combat_tests
    PRIVATE
        dauntless_combat
        GTest::gtest_main
)
# Prefixed so `ctest -R combat_` runs exactly the combat library's cases.
gtest_discover_tests(combat_tests TEST_PREFIX "combat_")
