#pragma once
#include <cstdint>
#include <vector>

namespace dauntless::audio {

struct WavData {
    uint16_t channels = 0;
    uint16_t bits_per_sample = 0;
    uint32_t sample_rate = 0;
    std::vector<uint8_t> pcm;  // interleaved little-endian PCM bytes
};

// Returns true on success. Supports PCM (format code 1), 8 or 16 bit,
// 1 or 2 channels. Other formats return false (caller treats as missing).
bool decode_wav(const uint8_t* bytes, size_t len, WavData& out);

}  // namespace dauntless::audio
