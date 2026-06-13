#include <audio/mp3.h>
#include <vector>

#define DR_MP3_IMPLEMENTATION
#include "dr_mp3.h"

namespace dauntless::audio {

bool decode_mp3(const uint8_t* bytes, size_t len, WavData& out) {
    if (bytes == nullptr || len == 0) return false;

    drmp3 mp3;
    if (!drmp3_init_memory(&mp3, bytes, len, nullptr)) return false;

    const drmp3_uint64 total_frames = drmp3_get_pcm_frame_count(&mp3);
    if (total_frames == 0) { drmp3_uninit(&mp3); return false; }

    const drmp3_uint32 channels = mp3.channels;
    std::vector<int16_t> samples(static_cast<size_t>(total_frames) * channels);
    const drmp3_uint64 read =
        drmp3_read_pcm_frames_s16(&mp3, total_frames, samples.data());
    const drmp3_uint32 sample_rate = mp3.sampleRate;
    drmp3_uninit(&mp3);

    if (read == 0) return false;

    out.channels = static_cast<uint16_t>(channels);
    out.bits_per_sample = 16;
    out.sample_rate = sample_rate;
    const size_t byte_count =
        static_cast<size_t>(read) * channels * sizeof(int16_t);
    out.pcm.assign(reinterpret_cast<const uint8_t*>(samples.data()),
                   reinterpret_cast<const uint8_t*>(samples.data()) + byte_count);
    return true;
}

}  // namespace dauntless::audio
