// native/src/renderer/frame_timer.cc
#include "renderer/frame_timer.h"

#include <chrono>
#include <utility>

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

void FrameTimer::set_gpu_requested(bool v) {
    if (v == gpu_requested_) return;
    gpu_requested_ = v;
    // reset() also re-probes, so the next frame picks its timer from the new
    // request. Called between frames (from Python), never with a query open.
    if (enabled_) reset();
}

void FrameTimer::set_gpu_focus(std::vector<std::string> names) {
    if (names == gpu_focus_) return;
    gpu_focus_ = std::move(names);
    // One report must never mix focused and unfocused frames: the top-level
    // rows read the same either way, but the focus rows would start mid-EMA.
    if (enabled_) reset();
}

bool FrameTimer::is_gpu_focus(const std::string& name) const {
    for (const auto& f : gpu_focus_)
        if (f == name) return true;
    return false;
}

void FrameTimer::begin_segment(int owner, int top) {
    Segment seg;
    seg.query = take_query(*current_);
    seg.owner = owner;
    seg.top = top;
    glBeginQuery(GL_TIME_ELAPSED, seg.query);
    current_->segments.push_back(seg);
    elapsed_query_ = seg.query;
    elapsed_open_ = true;
}

void FrameTimer::end_segment() {
    glEndQuery(GL_TIME_ELAPSED);
    current_->last_query = elapsed_query_;
    elapsed_open_ = false;
    elapsed_query_ = 0;
}

void FrameTimer::reset() {
    for (auto& rec : ring_) {
        rec.samples.clear();
        rec.segments.clear();
        rec.used = 0;
        // Drop the query pool too. These names belong to whatever context was
        // current when they were generated, and reset() is reachable across a
        // shutdown()/init() cycle (the host tests do exactly that); reusing
        // them afterwards issues glQueryCounter against a destroyed context's
        // objects, and every readback then reports unavailable forever.
        //
        // Dropped, NOT deleted: glDeleteQueries here would either need a
        // current context (reset() promises it works without one) or, worse,
        // delete those numeric names in whatever context IS current -- which
        // may be a live, unrelated object. Leaking a few dozen query names per
        // toggle is the cheap side of that trade.
        rec.queries.clear();
        rec.last_query = 0;
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
    last_raw_.clear();
    last_raw_cpu_ms_ = 0.0;
    frame_cpu_ms_ = 0.0;
    frame_gpu_ms_ = 0.0;
    cpu_total_seeded_ = false;
    gpu_total_seeded_ = false;
    frames_resolved_ = 0;
    frame_index_ = 0;
    // Re-probe the driver on every enable: the verdict belongs to the context
    // it was read in, and reset() is reachable across a shutdown()/init().
    gpu_probed_ = false;
    gpu_timer_ = GpuTimer::None;
    timestamp_bits_ = -1;
    elapsed_bits_ = -1;
    elapsed_open_ = false;
    elapsed_query_ = 0;
    focus_open_ = false;
    focus_sample_ = 0;
    timestamp_queries_ = 0;
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

    if (!gpu_probed_) {
        // Here rather than in set_enabled(): this is the first point that is
        // guaranteed a current context. -1 survives a query the driver rejects,
        // and choose_gpu_timer reads it as "no counter".
        gpu_probed_ = true;
        GLint ts = -1, te = -1;
        glGetQueryiv(GL_TIMESTAMP, GL_QUERY_COUNTER_BITS, &ts);
        glGetQueryiv(GL_TIME_ELAPSED, GL_QUERY_COUNTER_BITS, &te);
        timestamp_bits_ = ts;
        elapsed_bits_ = te;
        gpu_timer_ = select_gpu_timer(gpu_requested_, ts, te);
    }

    current_ = &next;
    current_->samples.clear();
    current_->segments.clear();
    current_->used = 0;
    current_->cpu_ns.assign(slots_.size(), 0.0);
    current_->calls.assign(slots_.size(), 0);
    current_->depth.assign(slots_.size(), 0);
    current_->order.clear();
    current_->frame_cpu_ns = 0.0;
    current_->last_query = 0;
    current_->pending = false;
    current_->timer = gpu_timer_;

    open_.clear();
    open_t0_.clear();
    open_sample_.clear();
    elapsed_open_ = false;
    elapsed_query_ = 0;
    focus_open_ = false;
    frame_t0_ = now_ns();
}

void FrameTimer::end_frame() {
    if (!enabled_ || current_ == nullptr) return;
    // Close anything a `return` inside a pass left open, so an early-out never
    // corrupts the next frame's stack.
    while (!open_.empty()) pop();
    current_->frame_cpu_ns = static_cast<double>(now_ns() - frame_t0_);

    last_raw_.clear();
    last_raw_.reserve(current_->order.size());
    for (int slot : current_->order) {
        const auto i = static_cast<std::size_t>(slot);
        if (i >= slots_.size()) continue;
        ScopeResult r;
        r.name = slots_[i].name;
        r.cpu_ms = (i < current_->cpu_ns.size() ? current_->cpu_ns[i] : 0.0) / 1e6;
        r.calls = (i < current_->calls.size() ? current_->calls[i] : 0);
        r.depth = (i < current_->depth.size() ? current_->depth[i] : 0);
        last_raw_.push_back(std::move(r));
    }
    last_raw_cpu_ms_ = current_->frame_cpu_ns / 1e6;

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
    const int depth = static_cast<int>(open_.size());
    const int idx = static_cast<int>(current_->samples.size());
    if (current_->timer == GpuTimer::Timestamp) {
        s.q_begin = take_query(*current_);
        s.q_end = take_query(*current_);
        glQueryCounter(s.q_begin, GL_TIMESTAMP);
        ++timestamp_queries_;
    } else if (current_->timer == GpuTimer::Elapsed &&
               elapsed_times_depth(depth) && !elapsed_open_) {
        // Depth-1 scopes are strictly sequential, so elapsed_open_ is always
        // false here; the guard turns a broken invariant into an untimed row
        // instead of a GL_INVALID_OPERATION from a nested glBeginQuery.
        s.parent = static_cast<int>(open_sample_.front());
        begin_segment(idx, idx);
        s.q_begin = elapsed_query_;
    } else if (current_->timer == GpuTimer::Elapsed && elapsed_open_ &&
               focus_splits(depth, is_gpu_focus(slots_[slot].name),
                            focus_open_)) {
        // Suspend the depth-1 ancestor's span; pop() resumes it.
        const int top = static_cast<int>(open_sample_[kElapsedDepth]);
        end_segment();
        begin_segment(idx, top);
        s.q_begin = elapsed_query_;
        focus_open_ = true;
        focus_sample_ = static_cast<std::size_t>(idx);
    }

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

    const Sample& s = current_->samples[sample_idx];
    // Every pop issues its end query after every query issued so far, so the
    // last timed pop of the frame leaves the last-issued query in last_query.
    // resolve() reads it rather than guessing from the sample order.
    if (s.q_end != 0) {
        glQueryCounter(s.q_end, GL_TIMESTAMP);
        ++timestamp_queries_;
        current_->last_query = s.q_end;
    } else if (focus_open_ && sample_idx == focus_sample_) {
        // A focus scope closes: end its span and resume its depth-1
        // ancestor's, which is still open (it encloses this scope).
        if (elapsed_open_) end_segment();
        focus_open_ = false;
        if (open_sample_.size() > static_cast<std::size_t>(kElapsedDepth)) {
            const int top = static_cast<int>(open_sample_[kElapsedDepth]);
            begin_segment(top, top);
        }
    } else if (s.q_begin != 0 && elapsed_open_) {
        // A depth-1 pass closes; its current segment is the open query. A
        // focus scope left open inside it (an early return) was force-closed
        // by its own pop() first, since pops run innermost-first.
        end_segment();
    }
    current_->cpu_ns[slot] += static_cast<double>(now_ns() - t0);
    current_->calls[slot] += 1;
}

void FrameTimer::resolve(Record& rec) {
    rec.pending = false;
    if (rec.samples.empty()) return;

    // Availability is checked on the LAST query ISSUED: GL guarantees results
    // become available in issue order, so if the last one is ready they all are.
    // If it is not ready we drop this record rather than block — a profiler
    // that calls glGetQueryObjectui64v on an unready query stalls the CPU on
    // the GPU, which is exactly the cost we are here to measure.
    //
    // rec.last_query, NOT samples.back().q_end: samples are ordered by PUSH,
    // and the outermost scope is pushed first but closed LAST (end_frame
    // force-closes it after `present` has already closed). Checking
    // samples.back() therefore left samples[0].q_end — the whole-frame scope —
    // outside the guard, so the loop below could read an unready query and
    // stall on exactly the thing the 3-frame ring exists to avoid.
    //
    // A frame that issued no query (no GPU timer, or no timed scope) has
    // nothing to wait for and resolves CPU-only.
    const GLuint last = rec.last_query;
    if (last != 0) {
        GLint available = 0;
        glGetQueryObjectiv(last, GL_QUERY_RESULT_AVAILABLE, &available);
        if (!available) return;
    }

    std::vector<double> gpu_ns(slots_.size(), 0.0);
    std::vector<char> measured(slots_.size(), 0);
    double frame_gpu_ns = 0.0;
    auto in_range = [&](int slot) {
        return slot >= 0 && slot < static_cast<int>(gpu_ns.size());
    };

    if (last != 0 && rec.timer == GpuTimer::Timestamp) {
        for (const Sample& s : rec.samples) {
            if (s.q_begin == 0 || !in_range(s.slot)) continue;
            GLuint64 t0 = 0, t1 = 0;
            glGetQueryObjectui64v(s.q_begin, GL_QUERY_RESULT, &t0);
            glGetQueryObjectui64v(s.q_end, GL_QUERY_RESULT, &t1);
            if (t1 >= t0) gpu_ns[s.slot] += static_cast<double>(t1 - t0);
            measured[s.slot] = 1;
        }
        // Whole-frame GPU time is the span from the first timestamp to the
        // last, not the sum of the scopes: scopes nest, so summing
        // double-counts. `last` being the last-ISSUED query is what makes this
        // the outermost scope's end. Taking `present`'s end instead reported
        // present.end - frame.begin, a total that disagreed with the `frame`
        // row's own gpu_ms printed directly above it.
        GLuint64 first_ts = 0, last_ts = 0;
        glGetQueryObjectui64v(rec.samples.front().q_begin, GL_QUERY_RESULT, &first_ts);
        glGetQueryObjectui64v(last, GL_QUERY_RESULT, &last_ts);
        if (last_ts >= first_ts)
            frame_gpu_ns = static_cast<double>(last_ts - first_ts);
    } else if (last != 0 && rec.timer == GpuTimer::Elapsed) {
        // The segments are sequential spans inside the outermost scope, so
        // their sum IS the whole frame and also that outermost row's time. GPU
        // work outside every top-level pass is not covered; there is
        // essentially none, since `frame` only opens, runs its children, and
        // closes. Each segment also counts toward its depth-1 pass, and a
        // focus scope's segment toward the focus scope itself.
        const int n = static_cast<int>(rec.samples.size());
        auto credit = [&](int sample, double d) {
            if (sample < 0 || sample >= n) return;
            const int slot = rec.samples[static_cast<std::size_t>(sample)].slot;
            if (!in_range(slot)) return;
            gpu_ns[slot] += d;
            measured[slot] = 1;
        };
        for (const Segment& seg : rec.segments) {
            GLuint64 ns = 0;
            glGetQueryObjectui64v(seg.query, GL_QUERY_RESULT, &ns);
            const double d = static_cast<double>(ns);
            frame_gpu_ns += d;
            if (seg.owner != seg.top) credit(seg.owner, d);
            credit(seg.top, d);
            if (seg.top >= 0 && seg.top < n)
                credit(rec.samples[static_cast<std::size_t>(seg.top)].parent, d);
        }
    }

    for (std::size_t i = 0; i < slots_.size(); ++i) {
        const double cpu = (i < rec.cpu_ns.size() ? rec.cpu_ns[i] : 0.0) / 1e6;
        ema(slots_[i].cpu_ms, slots_[i].cpu_seeded, cpu);
        // An unmeasured scope's GPU average is left alone rather than blended
        // toward a 0 it never measured.
        if (measured[i])
            ema(slots_[i].gpu_ms, slots_[i].gpu_seeded, gpu_ns[i] / 1e6);
    }

    ema(frame_cpu_ms_, cpu_total_seeded_, rec.frame_cpu_ns / 1e6);
    if (rec.timer != GpuTimer::None)
        ema(frame_gpu_ms_, gpu_total_seeded_, frame_gpu_ns / 1e6);

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
        r.gpu_measured = measured[i] != 0;
        r.gpu_ms = r.gpu_measured ? slots_[i].gpu_ms : 0.0;
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
