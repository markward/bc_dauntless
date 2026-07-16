#include <audio/audio_system.h>
#include <audio/audio_constants.h>
#include <audio/wav.h>
#include <audio/mp3.h>
#include <cstring>

namespace dauntless::audio {

// Guide §8: lowest-priority playing source loses. BC's consumer of this field
// was never identified, so this is the natural reading, not a verified one --
// and OpenAL Soft mixes 256 sources in software, so it rarely fires.
static constexpr size_t kMaxSoundsAtOnce = 128;

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
    double duration_sec = 0.0;
    const uint32_t bytes_per_sample = wav.bits_per_sample / 8;
    const uint64_t denom =
        static_cast<uint64_t>(wav.sample_rate) * wav.channels * bytes_per_sample;
    if (denom > 0)
        duration_sec = static_cast<double>(wav.pcm.size()) / static_cast<double>(denom);
    PcmDesc d{wav.channels, wav.bits_per_sample, wav.sample_rate};
    BufferHandle h = backend_->create_buffer(d, wav.pcm.data(), wav.pcm.size());
    if (h == 0) return false;
    SoundId id = next_sound_id_++;
    sounds_[id] = {h, positional, duration_sec};
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

double AudioSystem::get_duration(const std::string& name) const {
    auto it = name_to_id_.find(name);
    if (it == name_to_id_.end()) return 0.0;
    auto sit = sounds_.find(it->second);
    return sit == sounds_.end() ? 0.0 : sit->second.duration_sec;
}

PlayingId AudioSystem::play(SoundId id, bool looping, float gain, Category cat,
                            bool pos_provided, float x, float y, float z,
                            bool force_non_positional, float priority) {
    auto it = sounds_.find(id);
    if (it == sounds_.end()) return 0;

    // Guide §8: pool is full -- evict the lowest-priority playing source if
    // this new one outranks it, else drop the new one. See kMaxSoundsAtOnce.
    if (sources_.size() >= kMaxSoundsAtOnce) {
        auto victim = sources_.end();
        for (auto sit = sources_.begin(); sit != sources_.end(); ++sit)
            if (victim == sources_.end() || sit->second.priority < victim->second.priority)
                victim = sit;
        if (victim != sources_.end() && victim->second.priority < priority) {
            backend_->stop(victim->second.backend);
            sources_.erase(victim);
        } else {
            return 0;   // nothing lower-ranked to steal; drop this one
        }
    }

    bool positional = it->second.positional || pos_provided;
    // Overrides the sound's load-time LS_3D flag: a caller that tried to
    // anchor to a node but failed to resolve a real position must not fall
    // through to a positional source at the backend's (0,0,0) default.
    if (force_non_positional) positional = false;
    SourceHandle bh = backend_->play(it->second.buf, looping, gain, cat,
                                     positional, x, y, z, priority);
    if (bh == 0) return 0;
    PlayingId pid = next_playing_id_++;
    sources_[pid] = {bh, looping, priority};
    return pid;
}

PlayingId AudioSystem::play_sound(const std::string& name, bool looping, float gain,
                                  Category cat, bool pos_provided,
                                  float x, float y, float z,
                                  bool force_non_positional, float priority) {
    SoundId id = get_sound(name);
    return id == 0 ? 0 : play(id, looping, gain, cat,
                              pos_provided, x, y, z, force_non_positional, priority);
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

void AudioSystem::set_velocity(PlayingId pid, float x, float y, float z) {
    auto it = sources_.find(pid);
    if (it != sources_.end()) backend_->set_velocity(it->second.backend, x, y, z);
}

void AudioSystem::set_category_gain(Category c, float g) {
    backend_->set_category_gain(c, g);
}

bool AudioSystem::is_finished(PlayingId pid) const {
    auto it = sources_.find(pid);
    if (it == sources_.end()) return true;  // already reaped by update()
    return backend_->source_finished(it->second.backend);
}

SourceHandle AudioSystem::debug_backend_handle(PlayingId pid) const {
    auto it = sources_.find(pid);
    return it == sources_.end() ? 0 : it->second.backend;
}

void AudioSystem::update(float lx, float ly, float lz,
                         float fx, float fy, float fz,
                         float ux, float uy, float uz, float dt) {
    // Guide §4/§6: listener velocity for doppler, derived from the camera's
    // position delta. Raw game units per second — see the units note in
    // openal_backend.cc's init().
    float vx = 0.f, vy = 0.f, vz = 0.f;
    if (have_prev_listener_ && dt > 0.f) {
        vx = (lx - prev_listener_[0]) / dt;
        vy = (ly - prev_listener_[1]) / dt;
        vz = (lz - prev_listener_[2]) / dt;
        // Discontinuity guard (review #1): a bridge<->tactical toggle,
        // cutscene camera cut, or mission swap moves the listener a large
        // distance in a single tick, which differentiates as an enormous
        // velocity -- OpenAL then clamps it at c and the doppler numerator
        // collapses toward zero, producing an audible one-frame pitch blip.
        // Nothing in this game legitimately moves at or above
        // kSpeedOfSoundGU, so treat a derived speed >= c as a cut and report
        // zero velocity instead of a clamped spike.
        const float speed_sq = vx * vx + vy * vy + vz * vz;
        if (speed_sq >= kSpeedOfSoundGU * kSpeedOfSoundGU) {
            vx = vy = vz = 0.f;
        }
    }
    prev_listener_[0] = lx; prev_listener_[1] = ly; prev_listener_[2] = lz;
    have_prev_listener_ = true;

    backend_->set_listener(lx,ly,lz, fx,fy,fz, ux,uy,uz, vx,vy,vz);

    // Reap finished one-shots. Must call backend_->stop() so the underlying
    // ALuint is released — otherwise finished sources accumulate until OpenAL
    // Soft trips its 256-source-per-context limit.
    //
    // Source POSITIONS are pumped from Python (engine/audio/attached_sources.py):
    // the deferred renderer has no scene graph, so Python owns object transforms.
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
