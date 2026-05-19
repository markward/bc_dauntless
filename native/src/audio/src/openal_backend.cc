#include <audio/openal_backend.h>
#include <AL/al.h>
#include <AL/alc.h>
#include <cstdio>
#include <unordered_map>

namespace dauntless::audio {

namespace {

ALenum pick_format(uint16_t channels, uint16_t bps) {
    if (channels == 1 && bps == 8)  return AL_FORMAT_MONO8;
    if (channels == 1 && bps == 16) return AL_FORMAT_MONO16;
    if (channels == 2 && bps == 8)  return AL_FORMAT_STEREO8;
    if (channels == 2 && bps == 16) return AL_FORMAT_STEREO16;
    return AL_NONE;
}

class OpenALBackend : public IAudioBackend {
public:
    bool init() override {
        device_ = alcOpenDevice(nullptr);
        if (!device_) {
            std::fprintf(stderr, "[audio] alcOpenDevice failed; running silent\n");
            return false;
        }
        context_ = alcCreateContext(device_, nullptr);
        if (!context_ || !alcMakeContextCurrent(context_)) {
            std::fprintf(stderr, "[audio] alcCreateContext failed\n");
            if (context_) { alcDestroyContext(context_); context_ = nullptr; }
            alcCloseDevice(device_);
            device_ = nullptr;
            return false;
        }
        return true;
    }

    void shutdown() override {
        for (auto& [_, src] : sources_) alDeleteSources(1, &src.al);
        sources_.clear();
        for (auto& [_, buf] : buffers_) alDeleteBuffers(1, &buf);
        buffers_.clear();
        if (context_) { alcMakeContextCurrent(nullptr); alcDestroyContext(context_); context_ = nullptr; }
        if (device_)  { alcCloseDevice(device_); device_ = nullptr; }
    }

    BufferHandle create_buffer(const PcmDesc& d, const uint8_t* pcm, size_t bytes) override {
        ALenum fmt = pick_format(d.channels, d.bits_per_sample);
        if (fmt == AL_NONE) return 0;
        ALuint al;
        alGenBuffers(1, &al);
        if (alGetError() != AL_NO_ERROR) return 0;
        alBufferData(al, fmt, pcm, static_cast<ALsizei>(bytes),
                     static_cast<ALsizei>(d.sample_rate));
        if (alGetError() != AL_NO_ERROR) { alDeleteBuffers(1, &al); return 0; }
        BufferHandle h = ++next_buf_;
        buffers_[h] = al;
        return h;
    }

    void destroy_buffer(BufferHandle h) override {
        auto it = buffers_.find(h);
        if (it != buffers_.end()) { alDeleteBuffers(1, &it->second); buffers_.erase(it); }
    }

    SourceHandle play(BufferHandle buf, bool looping, float gain, Category cat,
                      bool positional, float x, float y, float z) override {
        auto it = buffers_.find(buf);
        if (it == buffers_.end()) return 0;
        ALuint al;
        alGenSources(1, &al);
        if (alGetError() != AL_NO_ERROR) return 0;
        alSourcei(al, AL_BUFFER, static_cast<ALint>(it->second));
        alSourcei(al, AL_LOOPING, looping ? AL_TRUE : AL_FALSE);
        alSourcef(al, AL_GAIN, gain * category_gain_[static_cast<int>(cat)]);
        if (positional) {
            alSourcei(al, AL_SOURCE_RELATIVE, AL_FALSE);
            alSource3f(al, AL_POSITION, x, y, z);
            alSourcef(al, AL_REFERENCE_DISTANCE, 100.0f);
            alSourcef(al, AL_ROLLOFF_FACTOR, 1.0f);
        } else {
            // Non-positional source: place 1 unit in front of the listener
            // (RELATIVE -Z) rather than exactly at origin so HRTF/panning
            // has a real direction. Disable distance attenuation entirely.
            alSourcei(al, AL_SOURCE_RELATIVE, AL_TRUE);
            alSource3f(al, AL_POSITION, 0.0f, 0.0f, -1.0f);
            alSourcef(al, AL_REFERENCE_DISTANCE, 1.0f);
            alSourcef(al, AL_ROLLOFF_FACTOR, 0.0f);
        }
        alSourcePlay(al);
        SourceHandle h = ++next_src_;
        sources_[h] = {al, cat, gain};
        return h;
    }

    void stop(SourceHandle h) override {
        auto it = sources_.find(h);
        if (it == sources_.end()) return;
        alSourceStop(it->second.al);
        alDeleteSources(1, &it->second.al);
        sources_.erase(it);
    }

    void set_position(SourceHandle h, float x, float y, float z) override {
        if (auto it = sources_.find(h); it != sources_.end())
            alSource3f(it->second.al, AL_POSITION, x, y, z);
    }
    void set_gain(SourceHandle h, float g) override {
        if (auto it = sources_.find(h); it != sources_.end()) {
            it->second.user_gain = g;
            alSourcef(it->second.al, AL_GAIN,
                      g * category_gain_[static_cast<int>(it->second.cat)]);
        }
    }
    void set_looping(SourceHandle h, bool l) override {
        if (auto it = sources_.find(h); it != sources_.end())
            alSourcei(it->second.al, AL_LOOPING, l ? AL_TRUE : AL_FALSE);
    }
    void set_min_max_distance(SourceHandle h, float mn, float mx) override {
        if (auto it = sources_.find(h); it != sources_.end()) {
            alSourcef(it->second.al, AL_REFERENCE_DISTANCE, mn);
            alSourcef(it->second.al, AL_MAX_DISTANCE, mx);
        }
    }
    void set_listener(float px, float py, float pz,
                      float fx, float fy, float fz,
                      float ux, float uy, float uz) override {
        alListener3f(AL_POSITION, px, py, pz);
        float ori[6] = {fx, fy, fz, ux, uy, uz};
        alListenerfv(AL_ORIENTATION, ori);
    }
    void set_category_gain(Category c, float g) override {
        category_gain_[static_cast<int>(c)] = g;
        for (auto& [_, src] : sources_) {
            if (src.cat == c) alSourcef(src.al, AL_GAIN, src.user_gain * g);
        }
    }
    bool source_finished(SourceHandle h) override {
        auto it = sources_.find(h);
        if (it == sources_.end()) return true;
        ALint state = 0;
        alGetSourcei(it->second.al, AL_SOURCE_STATE, &state);
        return state != AL_PLAYING && state != AL_PAUSED;
    }

private:
    struct Source { ALuint al; Category cat; float user_gain; };
    ALCdevice*  device_  = nullptr;
    ALCcontext* context_ = nullptr;
    std::unordered_map<BufferHandle, ALuint> buffers_;
    std::unordered_map<SourceHandle, Source> sources_;
    BufferHandle next_buf_ = 0;
    SourceHandle next_src_ = 0;
    float category_gain_[3] = {1.f, 1.f, 1.f};
};

}  // namespace

std::unique_ptr<IAudioBackend> make_openal_backend() {
    return std::make_unique<OpenALBackend>();
}

}  // namespace dauntless::audio
