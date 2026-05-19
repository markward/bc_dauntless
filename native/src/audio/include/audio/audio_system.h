#pragma once
#include <audio/audio_backend.h>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>

namespace dauntless::audio {

using SoundId = uint32_t;    // logical buffer id, returned to Python
using PlayingId = uint32_t;  // logical source id, returned to Python
using NodeId = uint32_t;     // scenegraph node id, 0 == none

// Pulls a node's world position. Set by host_loop; tests provide a stub.
using NodePositionFn = std::function<bool(NodeId, float& x, float& y, float& z)>;

class AudioSystem {
public:
    explicit AudioSystem(std::unique_ptr<IAudioBackend> backend);
    ~AudioSystem();

    bool init();
    void shutdown();

    void set_node_position_fn(NodePositionFn fn) { node_pos_fn_ = std::move(fn); }

    bool load_sound(const std::string& path, const std::string& name,
                    const uint8_t* wav_bytes, size_t wav_len, bool positional);

    SoundId get_sound(const std::string& name) const;
    bool is_loaded(SoundId) const;
    bool is_positional(SoundId) const;

    PlayingId play_sound(const std::string& name, bool looping, float gain,
                         Category, NodeId attach_node,
                         bool position_provided, float x, float y, float z);

    PlayingId play(SoundId, bool looping, float gain, Category, NodeId attach_node,
                   bool position_provided, float x, float y, float z);

    void stop(PlayingId);
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
    };
    struct Source {
        SourceHandle backend;
        NodeId node;
        bool looping;
    };

    std::unique_ptr<IAudioBackend> backend_;
    std::unordered_map<std::string, SoundId> name_to_id_;
    std::unordered_map<SoundId, Sound> sounds_;
    std::unordered_map<PlayingId, Source> sources_;
    SoundId next_sound_id_ = 1;
    PlayingId next_playing_id_ = 1;
    NodePositionFn node_pos_fn_;
};

}  // namespace dauntless::audio
