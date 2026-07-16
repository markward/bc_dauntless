#pragma once

namespace dauntless::audio {

// Guide §3/§6: BC overrides no DS3D global — doppler and rolloff both stay at
// 1.0, and speed of sound stays at DirectSound3D's real-world default. This is
// the ONE source of truth for c: openal_backend.cc's alSpeedOfSound() call,
// AudioSystem::update()'s discontinuity guard, and the Python binding
// (`_dauntless_host.audio.speed_of_sound()`, which feeds
// `engine/audio/attached_sources.py:SPEED_OF_SOUND_GU`) all read this constant
// rather than re-declaring the literal.
//
// Nothing in this game legitimately moves at or above this speed in game
// units (a Galaxy's max speed is 6.3 GU/s; torpedoes ~25 GU/s), and OpenAL
// clamps velocity at c anyway — so a derived velocity at or above c is
// definitionally a discontinuity (view-mode toggle, cutscene cut, teleport),
// not real motion.
constexpr float kSpeedOfSoundGU = 343.3f;

// Guide §8: BC's shipped default voice priority (TGSound.BC_DEFAULT_PRIORITY
// on the Python side, engine/audio/tg_sound.py). Single source of truth so
// audio_system.h's two `priority = ...` parameter defaults and
// python_binding.cc's `py::arg("priority") = ...` cannot drift from each
// other or from the Python constant.
constexpr float kBcDefaultPriority = 0.5f;

}  // namespace dauntless::audio
