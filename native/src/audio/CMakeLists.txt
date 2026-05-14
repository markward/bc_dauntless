add_library(open_stbc_audio STATIC
    src/wav.cc
    src/null_backend.cc
    src/audio_system.cc
    src/python_binding.cc
    src/openal_backend.cc
)
target_include_directories(open_stbc_audio PUBLIC include)
target_compile_features(open_stbc_audio PUBLIC cxx_std_20)
target_link_libraries(open_stbc_audio PRIVATE pybind11::headers Python3::Python)
