#pragma once
#include <cstddef>
#include <cstdint>
#include <audio/wav.h>  // WavData

namespace dauntless::audio {

// Decodes a whole MP3 (in memory) to interleaved int16 PCM, filling `out`.
// Returns true on success; false on init/decode failure or empty output
// (caller treats false as "unloadable", same as a non-WAV decode_wav miss).
bool decode_mp3(const uint8_t* bytes, size_t len, WavData& out);

}  // namespace dauntless::audio
