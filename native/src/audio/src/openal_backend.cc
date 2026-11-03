#include <audio/openal_backend.h>
#include <audio/audio_constants.h>
#include <AL/al.h>
#include <AL/alc.h>
#include <AL/alext.h>
#include <cstdio>
#include <unordered_map>

#ifdef __APPLE__
#include <atomic>
#include <chrono>
#include <string>
#include <Block.h>
#include <CoreAudio/CoreAudio.h>
#include <dispatch/dispatch.h>
#endif

namespace dauntless::audio {

namespace {

ALenum pick_format(uint16_t channels, uint16_t bps) {
    if (channels == 1 && bps == 8)  return AL_FORMAT_MONO8;
    if (channels == 1 && bps == 16) return AL_FORMAT_MONO16;
    if (channels == 2 && bps == 8)  return AL_FORMAT_STEREO8;
    if (channels == 2 && bps == 16) return AL_FORMAT_STEREO16;
    return AL_NONE;
}

#ifdef __APPLE__
// Following the system's output device on macOS.
//
// OpenAL Soft's CoreAudio backend (1.23.1, and still today) opens "the
// default device" by looking up the default output's AudioDeviceID once and
// pinning a HAL output unit to it. It never moves: AirPods auto-switching to
// a phone, being taken out, or a Bluetooth reconnect remove that device (a
// returning device can come back under a new ID), and the game plays into
// nothing until it is restarted; a device that becomes the default later
// (AirPods connected after launch) is never used. It also never reports the
// loss (no ALC_CONNECTED change on CoreAudio).
//
// So the backend watches CoreAudio itself, as Apple documents for apps that
// follow the default device: the system object's default output device and
// device list, and the bound device's DeviceIsAlive. The listeners run on a
// private serial dispatch queue (the block API), so they do not depend on
// the main thread running a CFRunLoop, and they only raise a flag -- no AL
// or ALC call is made off the audio thread (ALC_SOFT_system_events' rule).
// The game thread then moves the device with alcReopenDeviceSOFT, which keeps
// the context, every buffer and every playing source.
class OutputDeviceWatch {
public:
    // Seconds of quiet after the last notification before acting: connecting
    // Bluetooth headphones posts a burst of changes, and the new device is not
    // usable the instant it is listed.
    static constexpr double kSettleS = 0.4;
    // Seconds between retries while a reopen keeps failing.
    static constexpr double kRetryS = 1.0;

    void start() {
        queue_ = dispatch_queue_create("dauntless.audio.device-watch", DISPATCH_QUEUE_SERIAL);
        // Copied to the heap: a block literal lives on start()'s stack, and
        // CoreAudio keeps calling this one until stop() removes it.
        block_ = Block_copy(^(UInt32, const AudioObjectPropertyAddress*) { poke(); });
        AudioObjectPropertyAddress def{kAudioHardwarePropertyDefaultOutputDevice,
                                       kAudioObjectPropertyScopeGlobal,
                                       kAudioObjectPropertyElementMain};
        AudioObjectPropertyAddress devs{kAudioHardwarePropertyDevices,
                                        kAudioObjectPropertyScopeGlobal,
                                        kAudioObjectPropertyElementMain};
        AudioObjectAddPropertyListenerBlock(kAudioObjectSystemObject, &def, queue_, block_);
        AudioObjectAddPropertyListenerBlock(kAudioObjectSystemObject, &devs, queue_, block_);
        bind(default_output());
    }

    void stop() {
        if (!queue_) return;
        AudioObjectPropertyAddress def{kAudioHardwarePropertyDefaultOutputDevice,
                                       kAudioObjectPropertyScopeGlobal,
                                       kAudioObjectPropertyElementMain};
        AudioObjectPropertyAddress devs{kAudioHardwarePropertyDevices,
                                        kAudioObjectPropertyScopeGlobal,
                                        kAudioObjectPropertyElementMain};
        AudioObjectRemovePropertyListenerBlock(kAudioObjectSystemObject, &def, queue_, block_);
        AudioObjectRemovePropertyListenerBlock(kAudioObjectSystemObject, &devs, queue_, block_);
        unbind_alive();
        dispatch_sync(queue_, ^{});   // let a listener already running finish
        dispatch_release(queue_);
        queue_ = nullptr;
        Block_release(block_);
        block_ = nullptr;
    }

    // Game thread, once a frame: true when the device should be reopened now.
    bool due(double now_s) {
        if (dirty_.load(std::memory_order_acquire)) {
            dirty_.store(false, std::memory_order_release);
            pending_ = true;
            changed_at_s_ = now_s;
        }
        if (!pending_) return false;
        if (now_s - changed_at_s_ < kSettleS) return false;
        if (now_s < retry_at_s_) return false;
        AudioDeviceID want = default_output();
        if (want == bound_ && want != kAudioObjectUnknown && alive(bound_)) {
            pending_ = false;     // a burst that changed nothing (another device came or went)
            return false;
        }
        return true;
    }

    // After a reopen attempt: bind the device now in use, or schedule a retry.
    void reopened(bool ok, double now_s) {
        if (ok) {
            pending_ = false;
            bind(default_output());
        } else {
            retry_at_s_ = now_s + kRetryS;
        }
    }

    static std::string name_of(AudioDeviceID id) {
        if (id == kAudioObjectUnknown) return "no device";
        CFStringRef cf = nullptr;
        UInt32 size = sizeof(cf);
        AudioObjectPropertyAddress a{kAudioObjectPropertyName,
                                     kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
        if (AudioObjectGetPropertyData(id, &a, 0, nullptr, &size, &cf) != noErr || !cf)
            return "unknown device";
        char buf[256] = {0};
        CFStringGetCString(cf, buf, sizeof(buf), kCFStringEncodingUTF8);
        CFRelease(cf);
        return buf;
    }

    AudioDeviceID bound() const { return bound_; }

    static AudioDeviceID default_output() {
        AudioDeviceID id = kAudioObjectUnknown;
        UInt32 size = sizeof(id);
        AudioObjectPropertyAddress a{kAudioHardwarePropertyDefaultOutputDevice,
                                     kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
        if (AudioObjectGetPropertyData(kAudioObjectSystemObject, &a, 0, nullptr, &size, &id) != noErr)
            return kAudioObjectUnknown;
        return id;
    }

private:
    static bool alive(AudioDeviceID id) {
        if (id == kAudioObjectUnknown) return false;
        UInt32 v = 0, size = sizeof(v);
        AudioObjectPropertyAddress a{kAudioDevicePropertyDeviceIsAlive,
                                     kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
        return AudioObjectGetPropertyData(id, &a, 0, nullptr, &size, &v) == noErr && v != 0;
    }

    void poke() { dirty_.store(true, std::memory_order_release); }

    void bind(AudioDeviceID id) {
        unbind_alive();
        bound_ = id;
        if (id == kAudioObjectUnknown) return;
        AudioObjectPropertyAddress a{kAudioDevicePropertyDeviceIsAlive,
                                     kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
        if (AudioObjectAddPropertyListenerBlock(id, &a, queue_, block_) == noErr)
            alive_bound_ = id;
    }

    void unbind_alive() {
        if (alive_bound_ == kAudioObjectUnknown) return;
        AudioObjectPropertyAddress a{kAudioDevicePropertyDeviceIsAlive,
                                     kAudioObjectPropertyScopeGlobal,
                                     kAudioObjectPropertyElementMain};
        AudioObjectRemovePropertyListenerBlock(alive_bound_, &a, queue_, block_);
        alive_bound_ = kAudioObjectUnknown;
    }

    dispatch_queue_t queue_ = nullptr;
    AudioObjectPropertyListenerBlock block_ = nullptr;
    std::atomic<bool> dirty_{false};
    AudioDeviceID bound_ = kAudioObjectUnknown;
    AudioDeviceID alive_bound_ = kAudioObjectUnknown;
    bool pending_ = false;
    double changed_at_s_ = 0.0;
    double retry_at_s_ = 0.0;
};

double steady_seconds() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}
#endif

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
        // Guide §2/§14.1: THE faithful model — the same law DS3D uses. This is
        // already OpenAL's default, but pin it explicitly: AL_LINEAR_DISTANCE
        // cuts off at max where BC/DS3D clamps, and that is the one change
        // that makes BC's audio sound wrong.
        alDistanceModel(AL_INVERSE_DISTANCE_CLAMPED);
        // Guide §3/§6: BC overrides no DS3D global — doppler and rolloff both
        // stay at 1.0 (the AIL_set_3D_*_factor symbols don't exist in the
        // image). unitsPerMeter defaults to 1.0 and applies to velocity only,
        // so BC treats one game unit as one metre for doppler regardless of
        // visual scale. Feed raw game units; do NOT convert GU->m and do NOT
        // port BC's velocity /1000 (a Miles m/ms API convention).
        alDopplerFactor(1.0f);
        alSpeedOfSound(kSpeedOfSoundGU);
#ifdef __APPLE__
        if (alcIsExtensionPresent(device_, "ALC_SOFT_reopen_device")) {
            reopen_ = reinterpret_cast<LPALCREOPENDEVICESOFT>(
                alcGetProcAddress(device_, "alcReopenDeviceSOFT"));
        }
        if (reopen_) {
            watch_.start();
            std::fprintf(stderr, "[audio] output: %s (follows the system output device)\n",
                         OutputDeviceWatch::name_of(watch_.bound()).c_str());
        } else {
            std::fprintf(stderr, "[audio] ALC_SOFT_reopen_device missing; output stays on the launch device\n");
        }
#endif
        return true;
    }

    // Guide §9: the analog of DS3D's deferred commit -- a frame's listener
    // and emitter moves apply atomically instead of tearing mid-frame.
    void begin_frame() override {
#ifdef __APPLE__
        follow_output_device();
#endif
        if (context_) alcSuspendContext(context_);
    }
    void end_frame()   override { if (context_) alcProcessContext(context_); }

    void shutdown() override {
#ifdef __APPLE__
        if (reopen_) watch_.stop();
#endif
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
                      bool positional, float x, float y, float z,
                      float priority) override {
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
            // BC TGSound::SetupFromFile defaults (guide §5, audio_constants.h).
            // TGSound.Play overwrites these via set_min_max_distance; they are
            // the floor for any caller that does not.
            alSourcef(al, AL_REFERENCE_DISTANCE, kBcDefaultMinDistance);
            alSourcef(al, AL_MAX_DISTANCE,       kBcDefaultMaxDistance);
            alSourcef(al, AL_ROLLOFF_FACTOR,     1.0f);
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
        // Guide §8: priority is never mapped to AL_GAIN or any other AL
        // param. Stored here only for symmetry with AudioSystem::Source --
        // nothing reads it back from this backend today; AudioSystem picks
        // its eviction victim from its own sources_ map, not this one.
        sources_[h] = {al, cat, gain, priority};
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
    void set_velocity(SourceHandle h, float x, float y, float z) override {
        if (auto it = sources_.find(h); it != sources_.end())
            alSource3f(it->second.al, AL_VELOCITY, x, y, z);
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
                      float ux, float uy, float uz,
                      float vx, float vy, float vz) override {
        alListener3f(AL_POSITION, px, py, pz);
        alListener3f(AL_VELOCITY, vx, vy, vz);
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
#ifdef __APPLE__
    // Game thread: move to the system output device once a change has
    // settled (OutputDeviceWatch). A null name reopens "the default device",
    // which OpenAL Soft resolves to the current default output.
    void follow_output_device() {
        if (!reopen_ || !device_) return;
        const double now = steady_seconds();
        if (!watch_.due(now)) return;
        const AudioDeviceID want = OutputDeviceWatch::default_output();
        if (want == kAudioObjectUnknown) {
            watch_.reopened(false, now);      // nothing to play to yet; retry
            return;
        }
        const bool ok = reopen_(device_, nullptr, nullptr) == ALC_TRUE;
        watch_.reopened(ok, now);
        if (ok) {
            std::fprintf(stderr, "[audio] output moved to %s\n",
                         OutputDeviceWatch::name_of(watch_.bound()).c_str());
        } else {
            std::fprintf(stderr, "[audio] could not move output to %s; retrying\n",
                         OutputDeviceWatch::name_of(want).c_str());
        }
    }

    OutputDeviceWatch watch_;
    LPALCREOPENDEVICESOFT reopen_ = nullptr;
#endif
    struct Source { ALuint al; Category cat; float user_gain; float priority; };
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
