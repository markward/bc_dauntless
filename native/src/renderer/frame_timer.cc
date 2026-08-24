// native/src/renderer/frame_timer.cc
#include "renderer/frame_timer.h"

#include <chrono>

#include <glad/glad.h>

namespace renderer {

namespace {

std::int64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

// Blend a new sample into an EMA, or seed it on the first sample so the
// average does not have to climb out of a zero it was never measuring.
void ema(double& acc, bool& seeded, double sample) {
    if (!seeded) {
        acc = sample;
        seeded = true;
        return;
    }
    acc += FrameTimer::kEmaAlpha * (sample - acc);
}

}  // namespace

FrameTimer::~FrameTimer() {
    // Queries are GL objects and deleting them requires a current context,
    // which a static destructor at process teardown does not have. Leaking
    // them at exit is correct: the context is being destroyed anyway.
}

void FrameTimer::set_enabled(bool v) {
    if (v == enabled_) return;
    enabled_ = v;
    // Drop everything either way. Enabling must not report an average blended
    // with samples from the last time it was on (which may be a different
    // mission, camera, or ship count); disabling must not leave a stale table
    // that a later reader mistakes for live data.
    reset();
}

void FrameTimer::reset() {
    for (auto& rec : ring_) {
        rec.samples.clear();
        rec.used = 0;
        rec.cpu_ns.clear();
        rec.calls.clear();
        rec.order.clear();
        rec.depth.clear();
        rec.frame_cpu_ns = 0.0;
        rec.pending = false;
    }
    current_ = nullptr;
    slots_.clear();
    open_.clear();
    open_t0_.clear();
    open_sample_.clear();
    results_.clear();
    frame_cpu_ms_ = 0.0;
    frame_gpu_ms_ = 0.0;
    cpu_total_seeded_ = false;
    gpu_total_seeded_ = false;
    frames_resolved_ = 0;
    frame_index_ = 0;
}

int FrameTimer::slot_for(const char* name) {
    for (std::size_t i = 0; i < slots_.size(); ++i) {
        if (slots_[i].name == name) return static_cast<int>(i);
    }
    Slot s;
    s.name = name;
    slots_.push_back(std::move(s));
    return static_cast<int>(slots_.size()) - 1;
}

unsigned int FrameTimer::take_query(Record& rec) {
    if (rec.used >= rec.queries.size()) {
        // Grow the record's own pool. Each record keeps its high-water mark,
        // so after a few frames no allocation happens at all.
        GLuint q = 0;
        glGenQueries(1, &q);
        rec.queries.push_back(q);
    }
    return rec.queries[rec.used++];
}

void FrameTimer::begin_frame() {
    if (!enabled_) return;

    // Resolve the record from kRingDepth frames ago. It is the one we are
    // about to overwrite, so it must be drained first.
    Record& next = ring_[frame_index_ % kRingDepth];
    if (next.pending) resolve(next);

    current_ = &next;
    current_->samples.clear();
    current_->used = 0;
    current_->cpu_ns.assign(slots_.size(), 0.0);
    current_->calls.assign(slots_.size(), 0);
    current_->depth.assign(slots_.size(), 0);
    current_->order.clear();
    current_->frame_cpu_ns = 0.0;
    current_->pending = false;

    open_.clear();
    open_t0_.clear();
    open_sample_.clear();
    frame_t0_ = now_ns();
}

void FrameTimer::end_frame() {
    if (!enabled_ || current_ == nullptr) return;
    // Close anything a `return` inside a pass left open, so an early-out never
    // corrupts the next frame's stack.
    while (!open_.empty()) pop();
    current_->frame_cpu_ns = static_cast<double>(now_ns() - frame_t0_);
    current_->pending = true;
    current_ = nullptr;
    ++frame_index_;
}

void FrameTimer::push(const char* name) {
    if (!enabled_ || current_ == nullptr) return;

    const int slot = slot_for(name);
    // slot_for can append; keep the per-frame arrays wide enough for it.
    if (current_->cpu_ns.size() < slots_.size()) {
        current_->cpu_ns.resize(slots_.size(), 0.0);
        current_->calls.resize(slots_.size(), 0);
        current_->depth.resize(slots_.size(), 0);
    }
    // First entry this frame fixes this scope's position and depth in the
    // report. Re-entries (a pass drawn for both the exterior view and the
    // viewscreen RTT) accumulate into the same row rather than moving it.
    if (current_->calls[slot] == 0) {
        current_->order.push_back(slot);
        current_->depth[slot] = static_cast<int>(open_.size());
    }

    Sample s;
    s.slot = slot;
    s.q_begin = take_query(*current_);
    s.q_end = take_query(*current_);
    glQueryCounter(s.q_begin, GL_TIMESTAMP);

    open_sample_.push_back(current_->samples.size());
    current_->samples.push_back(s);
    open_.push_back(slot);
    open_t0_.push_back(now_ns());
}

void FrameTimer::pop() {
    if (!enabled_ || current_ == nullptr || open_.empty()) return;

    const int slot = open_.back();
    const std::int64_t t0 = open_t0_.back();
    const std::size_t sample_idx = open_sample_.back();
    open_.pop_back();
    open_t0_.pop_back();
    open_sample_.pop_back();

    glQueryCounter(current_->samples[sample_idx].q_end, GL_TIMESTAMP);
    current_->cpu_ns[slot] += static_cast<double>(now_ns() - t0);
    current_->calls[slot] += 1;
}

void FrameTimer::resolve(Record& rec) {
    rec.pending = false;
    if (rec.samples.empty()) return;

    // Availability is checked on the LAST query issued: GL guarantees results
    // become available in issue order, so if the last one is ready they all are.
    // If it is not ready we drop this record rather than block — a profiler
    // that calls glGetQueryObjectui64v on an unready query stalls the CPU on
    // the GPU, which is exactly the cost we are here to measure.
    GLuint last = rec.samples.back().q_end;
    GLint available = 0;
    glGetQueryObjectiv(last, GL_QUERY_RESULT_AVAILABLE, &available);
    if (!available) return;

    std::vector<double> gpu_ns(slots_.size(), 0.0);
    for (const Sample& s : rec.samples) {
        GLuint64 t0 = 0, t1 = 0;
        glGetQueryObjectui64v(s.q_begin, GL_QUERY_RESULT, &t0);
        glGetQueryObjectui64v(s.q_end, GL_QUERY_RESULT, &t1);
        if (s.slot < static_cast<int>(gpu_ns.size()) && t1 >= t0)
            gpu_ns[s.slot] += static_cast<double>(t1 - t0);
    }

    for (std::size_t i = 0; i < slots_.size(); ++i) {
        const double cpu = (i < rec.cpu_ns.size() ? rec.cpu_ns[i] : 0.0) / 1e6;
        const double gpu = gpu_ns[i] / 1e6;
        ema(slots_[i].cpu_ms, slots_[i].cpu_seeded, cpu);
        ema(slots_[i].gpu_ms, slots_[i].gpu_seeded, gpu);
    }

    // Whole-frame GPU time is the span from the first timestamp to the last,
    // not the sum of the scopes: scopes nest, so summing double-counts.
    GLuint64 first_ts = 0, last_ts = 0;
    glGetQueryObjectui64v(rec.samples.front().q_begin, GL_QUERY_RESULT, &first_ts);
    glGetQueryObjectui64v(last, GL_QUERY_RESULT, &last_ts);
    ema(frame_cpu_ms_, cpu_total_seeded_, rec.frame_cpu_ns / 1e6);
    ema(frame_gpu_ms_, gpu_total_seeded_,
        last_ts >= first_ts ? static_cast<double>(last_ts - first_ts) / 1e6 : 0.0);

    // Report exactly the scopes this frame entered, in this frame's order and
    // at this frame's depth. See results() for why a first-sight tree is wrong.
    results_.clear();
    results_.reserve(rec.order.size());
    for (int slot : rec.order) {
        const auto i = static_cast<std::size_t>(slot);
        if (i >= slots_.size()) continue;
        ScopeResult r;
        r.name = slots_[i].name;
        r.cpu_ms = slots_[i].cpu_ms;
        r.gpu_ms = slots_[i].gpu_ms;
        r.calls = (i < rec.calls.size() ? rec.calls[i] : 0);
        r.depth = (i < rec.depth.size() ? rec.depth[i] : 0);
        results_.push_back(std::move(r));
    }
    ++frames_resolved_;
}

FrameTimer& frame_timer() {
    static FrameTimer instance;
    return instance;
}

}  // namespace renderer
