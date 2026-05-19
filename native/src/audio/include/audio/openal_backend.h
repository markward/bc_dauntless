#pragma once
#include <audio/audio_backend.h>
#include <memory>
namespace dauntless::audio {
// Returns nullptr if OpenAL is unavailable or stubbed (replaced in Task 5).
std::unique_ptr<IAudioBackend> make_openal_backend();
}  // namespace dauntless::audio
