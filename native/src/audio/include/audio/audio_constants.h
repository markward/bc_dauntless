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

// Guide §8: BC's shipped default voice priority. Single source of truth for
// audio_system.h's two `priority = ...` parameter defaults and
// python_binding.cc's `py::arg("priority") = ...`, which cannot drift from
// each other since they both read this constant directly. The Python side
// (TGSound.BC_DEFAULT_PRIORITY, engine/audio/tg_sound.py) derives from this
// value too, via the `bc_default_priority()` binding (same precedent as
// kSpeedOfSoundGU / speed_of_sound() below) -- so it cannot independently
// drift either, not merely "shouldn't".
constexpr float kBcDefaultPriority = 0.5f;

// Guide §5: BC's TGSound::SetupFromFile shipped min/max distance defaults
// (TGSound.BC_DEFAULT_MIN_DISTANCE / BC_DEFAULT_MAX_DISTANCE on the Python
// side, engine/audio/tg_sound.py). openal_backend.cc's `play()` sets these
// as the AL_REFERENCE_DISTANCE / AL_MAX_DISTANCE floor for any positional
// source; TGSound.Play() overwrites them via set_min_max_distance() for
// every real call site, so drift here is theoretical, not live -- but they
// belong beside the other shared audio constants rather than as bare
// literals at the call site.
constexpr float kBcDefaultMinDistance = 50.0f;
constexpr float kBcDefaultMaxDistance = 700.0f;

}  // namespace dauntless::audio
