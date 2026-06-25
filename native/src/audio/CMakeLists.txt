add_library(dauntless_audio STATIC
    src/wav.cc
    src/mp3.cc
    src/null_backend.cc
    src/audio_system.cc
    src/python_binding.cc
    src/openal_backend.cc
)
target_include_directories(dauntless_audio PUBLIC include)
target_compile_features(dauntless_audio PUBLIC cxx_std_20)
# Headers only — never link the embed libpython into a static lib that gets
# pulled into the _dauntless_host module. The final consumers provide Python:
# the `dauntless` executable links Python3::Python; the pybind11 module resolves
# symbols via -undefined dynamic_lookup. Linking libpython here drags a second
# libpython copy into the module, which crashes a statically-linked interpreter
# (e.g. uv/python-build-standalone). pybind11::headers supplies <Python.h>.
target_link_libraries(dauntless_audio PRIVATE pybind11::headers Python3::Module)
target_link_libraries(dauntless_audio PRIVATE OpenAL)
target_link_libraries(dauntless_audio PRIVATE dr_mp3)
target_include_directories(dauntless_audio PRIVATE
    ${openal_soft_SOURCE_DIR}/include)
