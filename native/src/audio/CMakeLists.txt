add_library(open_stbc_audio STATIC src/wav.cc src/null_backend.cc src/audio_system.cc)
target_include_directories(open_stbc_audio PUBLIC include)
target_compile_features(open_stbc_audio PUBLIC cxx_std_20)
