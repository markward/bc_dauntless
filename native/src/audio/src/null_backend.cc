#include <audio/null_backend.h>

namespace open_stbc::audio {

bool NullBackend::init() { log_.push_back({"init"}); return true; }
void NullBackend::shutdown() { log_.push_back({"shutdown"}); }

BufferHandle NullBackend::create_buffer(const PcmDesc& d, const uint8_t*, size_t n) {
    LoggedCall c{"create_buffer"};
    c.u[0] = d.channels; c.u[1] = d.bits_per_sample;
    c.u[2] = d.sample_rate; c.u[3] = (uint32_t)n;
    log_.push_back(c);
    return next_buf_++;
}

void NullBackend::destroy_buffer(BufferHandle h) {
    LoggedCall c{"destroy_buffer"}; c.u[0] = h; log_.push_back(c);
}

SourceHandle NullBackend::play(BufferHandle buf, bool looping, float gain,
                               Category cat, bool positional,
                               float x, float y, float z) {
    LoggedCall c{"play"};
    c.u[0] = buf; c.u[1] = (uint32_t)cat;
    c.b[0] = looping; c.b[1] = positional;
    c.f[0] = gain; c.f[1] = x; c.f[2] = y; c.f[3] = z;
    log_.push_back(c);
    return next_src_++;
}

void NullBackend::stop(SourceHandle h) {
    LoggedCall c{"stop"}; c.u[0] = h; log_.push_back(c);
}

void NullBackend::set_position(SourceHandle h, float x, float y, float z) {
    LoggedCall c{"set_position"}; c.u[0] = h;
    c.f[0] = x; c.f[1] = y; c.f[2] = z;
    log_.push_back(c);
}

void NullBackend::set_gain(SourceHandle h, float g) {
    LoggedCall c{"set_gain"}; c.u[0] = h; c.f[0] = g; log_.push_back(c);
}

void NullBackend::set_looping(SourceHandle h, bool l) {
    LoggedCall c{"set_looping"}; c.u[0] = h; c.b[0] = l; log_.push_back(c);
}

void NullBackend::set_min_max_distance(SourceHandle h, float mn, float mx) {
    LoggedCall c{"set_min_max_distance"}; c.u[0] = h;
    c.f[0] = mn; c.f[1] = mx; log_.push_back(c);
}

void NullBackend::set_listener(float px, float py, float pz,
                               float fx, float fy, float fz,
                               float ux, float uy, float uz) {
    LoggedCall c{"set_listener"};
    c.f[0]=px; c.f[1]=py; c.f[2]=pz;
    c.f[3]=fx; c.f[4]=fy; c.f[5]=fz;
    c.f[6]=ux; c.f[7]=uy; c.f[8]=uz;
    log_.push_back(c);
}

void NullBackend::set_category_gain(Category cat, float g) {
    LoggedCall c{"set_category_gain"};
    c.u[0] = (uint32_t)cat; c.f[0] = g; log_.push_back(c);
}

bool NullBackend::source_finished(SourceHandle) { return false; }

}  // namespace open_stbc::audio
