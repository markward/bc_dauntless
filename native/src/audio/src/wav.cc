#include "audio/wav.h"
#include <cstring>

namespace dauntless::audio {

static bool read_u32(const uint8_t* p, size_t off, size_t len, uint32_t& v) {
    if (off + 4 > len) return false;
    v = static_cast<uint32_t>(p[off]) | (static_cast<uint32_t>(p[off+1]) << 8) |
        (static_cast<uint32_t>(p[off+2]) << 16) | (static_cast<uint32_t>(p[off+3]) << 24);
    return true;
}

static bool read_u16(const uint8_t* p, size_t off, size_t len, uint16_t& v) {
    if (off + 2 > len) return false;
    v = static_cast<uint16_t>(p[off]) | static_cast<uint16_t>(p[off+1] << 8);
    return true;
}

bool decode_wav(const uint8_t* p, size_t len, WavData& out) {
    if (len < 44) return false;
    if (std::memcmp(p, "RIFF", 4) != 0) return false;
    if (std::memcmp(p + 8, "WAVE", 4) != 0) return false;

    size_t off = 12;
    bool got_fmt = false;
    while (off + 8 <= len) {
        char id[4]; std::memcpy(id, p + off, 4);
        uint32_t sz;
        if (!read_u32(p, off + 4, len, sz)) return false;
        size_t chunk_data = off + 8;
        if (chunk_data + sz > len) return false;

        if (std::memcmp(id, "fmt ", 4) == 0) {
            uint16_t fmt_code, channels, bps;
            uint32_t sample_rate;
            if (!read_u16(p, chunk_data + 0, len, fmt_code)) return false;
            if (fmt_code != 1) return false;  // PCM only
            if (!read_u16(p, chunk_data + 2, len, channels)) return false;
            if (!read_u32(p, chunk_data + 4, len, sample_rate)) return false;
            if (!read_u16(p, chunk_data + 14, len, bps)) return false;
            if (channels != 1 && channels != 2) return false;
            if (bps != 8 && bps != 16) return false;
            out.channels = channels;
            out.bits_per_sample = bps;
            out.sample_rate = sample_rate;
            got_fmt = true;
        } else if (std::memcmp(id, "data", 4) == 0) {
            if (!got_fmt) return false;
            out.pcm.assign(p + chunk_data, p + chunk_data + sz);
            return true;
        }

        off = chunk_data + sz;
        if (sz % 2) off += 1;  // RIFF chunks pad to even length
    }
    return false;
}

}  // namespace dauntless::audio
