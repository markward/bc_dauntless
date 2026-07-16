#pragma once
#include <cstddef>
#include <cstdint>

namespace dauntless::audio {

using BufferHandle = uint32_t;  // 0 == invalid
using SourceHandle = uint32_t;  // 0 == invalid

enum class Category : uint8_t {
    SFX = 0,
    Voice = 1,
    Interface = 2,
};

struct PcmDesc {
    uint16_t channels;
    uint16_t bits_per_sample;
    uint32_t sample_rate;
};

class IAudioBackend {
public:
    virtual ~IAudioBackend() = default;
    virtual bool init() = 0;
    virtual void shutdown() = 0;

    virtual BufferHandle create_buffer(const PcmDesc& desc,
                                       const uint8_t* pcm, size_t bytes) = 0;
    virtual void destroy_buffer(BufferHandle) = 0;

    virtual SourceHandle play(BufferHandle, bool looping, float gain,
                              Category, bool positional,
                              float x, float y, float z) = 0;
    virtual void stop(SourceHandle) = 0;
    virtual void set_position(SourceHandle, float x, float y, float z) = 0;
    virtual void set_velocity(SourceHandle, float x, float y, float z) = 0;
    virtual void set_gain(SourceHandle, float) = 0;
    virtual void set_looping(SourceHandle, bool) = 0;
    virtual void set_min_max_distance(SourceHandle, float min, float max) = 0;

    virtual void set_listener(float px, float py, float pz,
                              float fx, float fy, float fz,
                              float ux, float uy, float uz,
                              float vx, float vy, float vz) = 0;
    virtual void set_category_gain(Category, float) = 0;

    // True if the source has stopped on its own (one-shot completed).
    virtual bool source_finished(SourceHandle) = 0;
};

}  // namespace dauntless::audio
