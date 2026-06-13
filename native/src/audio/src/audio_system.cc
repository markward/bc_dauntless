#include <audio/audio_system.h>
#include <audio/wav.h>
#include <audio/mp3.h>
#include <cstring>

namespace dauntless::audio {

AudioSystem::AudioSystem(std::unique_ptr<IAudioBackend> b)
    : backend_(std::move(b)) {}

AudioSystem::~AudioSystem() = default;

bool AudioSystem::init() { return backend_ && backend_->init(); }
void AudioSystem::shutdown() { if (backend_) backend_->shutdown(); }

bool AudioSystem::load_sound(const std::string&, const std::string& name,
                             const uint8_t* wav_bytes, size_t wav_len,
                             bool positional) {
    WavData wav;
    const bool is_wav = wav_len >= 12
        && std::memcmp(wav_bytes, "RIFF", 4) == 0
        && std::memcmp(wav_bytes + 8, "WAVE", 4) == 0;
    const bool decoded = is_wav ? decode_wav(wav_bytes, wav_len, wav)
                                : decode_mp3(wav_bytes, wav_len, wav);
    if (!decoded) return false;
    PcmDesc d{wav.channels, wav.bits_per_sample, wav.sample_rate};
    BufferHandle h = backend_->create_buffer(d, wav.pcm.data(), wav.pcm.size());
    if (h == 0) return false;
    SoundId id = next_sound_id_++;
    sounds_[id] = {h, positional};
    name_to_id_[name] = id;
    return true;
}

SoundId AudioSystem::get_sound(const std::string& name) const {
    auto it = name_to_id_.find(name);
    return it == name_to_id_.end() ? 0 : it->second;
}

bool AudioSystem::is_loaded(SoundId id) const { return sounds_.count(id) > 0; }
bool AudioSystem::is_positional(SoundId id) const {
    auto it = sounds_.find(id);
    return it != sounds_.end() && it->second.positional;
}

PlayingId AudioSystem::play(SoundId id, bool looping, float gain, Category cat,
                            NodeId attach_node, bool pos_provided,
                            float x, float y, float z) {
    auto it = sounds_.find(id);
    if (it == sounds_.end()) return 0;
    bool positional = it->second.positional || pos_provided || attach_node != 0;
    SourceHandle bh = backend_->play(it->second.buf, looping, gain, cat,
                                     positional, x, y, z);
    if (bh == 0) return 0;
    PlayingId pid = next_playing_id_++;
    sources_[pid] = {bh, attach_node, looping};
    return pid;
}

PlayingId AudioSystem::play_sound(const std::string& name, bool looping, float gain,
                                  Category cat, NodeId attach_node,
                                  bool pos_provided, float x, float y, float z) {
    SoundId id = get_sound(name);
    return id == 0 ? 0 : play(id, looping, gain, cat, attach_node,
                              pos_provided, x, y, z);
}

void AudioSystem::stop(PlayingId pid) {
    auto it = sources_.find(pid);
    if (it == sources_.end()) return;
    backend_->stop(it->second.backend);
    sources_.erase(it);
}

void AudioSystem::set_gain(PlayingId pid, float g) {
    auto it = sources_.find(pid);
    if (it != sources_.end()) backend_->set_gain(it->second.backend, g);
}

void AudioSystem::set_looping(PlayingId pid, bool l) {
    auto it = sources_.find(pid);
    if (it == sources_.end()) return;
    it->second.looping = l;
    backend_->set_looping(it->second.backend, l);
}

void AudioSystem::set_min_max_distance(PlayingId pid, float mn, float mx) {
    auto it = sources_.find(pid);
    if (it != sources_.end()) backend_->set_min_max_distance(it->second.backend, mn, mx);
}

void AudioSystem::set_position(PlayingId pid, float x, float y, float z) {
    auto it = sources_.find(pid);
    if (it != sources_.end()) backend_->set_position(it->second.backend, x, y, z);
}

void AudioSystem::set_category_gain(Category c, float g) {
    backend_->set_category_gain(c, g);
}

void AudioSystem::update(float lx, float ly, float lz,
                         float fx, float fy, float fz,
                         float ux, float uy, float uz, float /*dt*/) {
    backend_->set_listener(lx,ly,lz, fx,fy,fz, ux,uy,uz);

    // Update attached source positions.
    for (auto& [pid, src] : sources_) {
        if (src.node == 0 || !node_pos_fn_) continue;
        float x, y, z;
        if (node_pos_fn_(src.node, x, y, z)) {
            backend_->set_position(src.backend, x, y, z);
        }
    }

    // Reap finished one-shots. Must call backend_->stop() so the underlying
    // ALuint is released — otherwise finished sources accumulate until OpenAL
    // Soft trips its 256-source-per-context limit.
    for (auto it = sources_.begin(); it != sources_.end(); ) {
        if (!it->second.looping && backend_->source_finished(it->second.backend)) {
            backend_->stop(it->second.backend);
            it = sources_.erase(it);
        } else {
            ++it;
        }
    }
}

}  // namespace dauntless::audio
