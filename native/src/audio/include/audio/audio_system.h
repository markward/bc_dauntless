#pragma once
#include <audio/audio_backend.h>
#include <memory>
#include <string>
#include <unordered_map>

namespace dauntless::audio {

using SoundId = uint32_t;    // logical buffer id, returned to Python
using PlayingId = uint32_t;  // logical source id, returned to Python

class AudioSystem {
public:
    explicit AudioSystem(std::unique_ptr<IAudioBackend> backend);
    ~AudioSystem();

    bool init();
    void shutdown();

    bool load_sound(const std::string& path, const std::string& name,
                    const uint8_t* wav_bytes, size_t wav_len, bool positional);

    SoundId get_sound(const std::string& name) const;
    bool is_loaded(SoundId) const;
    bool is_positional(SoundId) const;
    double get_duration(const std::string& name) const;

    PlayingId play_sound(const std::string& name, bool looping, float gain,
                         Category, bool position_provided, float x, float y, float z,
                         bool force_non_positional = false);

    PlayingId play(SoundId, bool looping, float gain, Category,
                   bool position_provided, float x, float y, float z,
                   bool force_non_positional = false);

    void stop(PlayingId);

    // True when `pid` is unknown (already reaped by update()'s finished-source
    // sweep) or the backend reports the underlying source has stopped on its
    // own. Lets a per-frame Python pump (attached_sources.pump) drop a
    // finished one-shot's tracking entry instead of issuing a dead-pid
    // set_position forever.
    bool is_finished(PlayingId) const;

    // Test-only: the concrete backend SourceHandle for `pid`, or 0 if
    // unknown. Lets Python tests reach into a specific backend (e.g.
    // NullBackend::mark_finished) to simulate a source finishing, without
    // AudioSystem itself depending on any concrete backend's type.
    SourceHandle debug_backend_handle(PlayingId) const;
    void set_gain(PlayingId, float);
    void set_looping(PlayingId, bool);
    void set_min_max_distance(PlayingId, float, float);
    void set_position(PlayingId, float, float, float);

    void set_category_gain(Category, float);

    void update(float lx, float ly, float lz,
                float fx, float fy, float fz,
                float ux, float uy, float uz,
                float dt);

    // Test/inspection.
    IAudioBackend* backend() { return backend_.get(); }

private:
    struct Sound {
        BufferHandle buf;
        bool positional;
        double duration_sec = 0.0;
    };
    struct Source {
        SourceHandle backend;
        bool looping;
    };

    std::unique_ptr<IAudioBackend> backend_;
    std::unordered_map<std::string, SoundId> name_to_id_;
    std::unordered_map<SoundId, Sound> sounds_;
    std::unordered_map<PlayingId, Source> sources_;
    SoundId next_sound_id_ = 1;
    PlayingId next_playing_id_ = 1;
};

}  // namespace dauntless::audio
