# Acoustic recovery of the BC .LIP code->viseme table. Writes
# engine/appc/lip_visemes.json. Consumes the audio decoder only.
add_executable(recover_lip_visemes recover_lip_visemes.cc)
target_link_libraries(recover_lip_visemes PRIVATE dauntless_audio)
