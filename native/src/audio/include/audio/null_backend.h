#pragma once
#include <audio/audio_backend.h>
#include <string>
#include <vector>
#include <variant>

namespace open_stbc::audio {

struct LoggedCall {
    std::string op;
    // Tagged-union args. We keep this loose because tests only inspect a handful.
    float f[9] = {0,0,0,0,0,0,0,0,0};
    uint32_t u[4] = {0,0,0,0};
    bool b[2] = {false,false};
};

class NullBackend : public IAudioBackend {
public:
    bool init() override;
    void shutdown() override;

    BufferHandle create_buffer(const PcmDesc&, const uint8_t*, size_t) override;
    void destroy_buffer(BufferHandle) override;
    SourceHandle play(BufferHandle, bool looping, float gain, Category,
                      bool positional, float, float, float) override;
    void stop(SourceHandle) override;
    void set_position(SourceHandle, float, float, float) override;
    void set_gain(SourceHandle, float) override;
    void set_looping(SourceHandle, bool) override;
    void set_min_max_distance(SourceHandle, float, float) override;
    void set_listener(float,float,float, float,float,float, float,float,float) override;
    void set_category_gain(Category, float) override;
    bool source_finished(SourceHandle) override;

    const std::vector<LoggedCall>& command_log() const { return log_; }
    void clear_command_log() { log_.clear(); }

private:
    uint32_t next_buf_ = 1;
    uint32_t next_src_ = 1;
    std::vector<LoggedCall> log_;
};

}  // namespace open_stbc::audio
