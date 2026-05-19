add_library(dauntless_audio STATIC
    src/wav.cc
    src/null_backend.cc
    src/audio_system.cc
    src/python_binding.cc
    src/openal_backend.cc
)
target_include_directories(dauntless_audio PUBLIC include)
target_compile_features(dauntless_audio PUBLIC cxx_std_20)
target_link_libraries(dauntless_audio PRIVATE pybind11::headers Python3::Python)
target_link_libraries(dauntless_audio PRIVATE OpenAL)
target_include_directories(dauntless_audio PRIVATE
    ${openal_soft_SOURCE_DIR}/include)
