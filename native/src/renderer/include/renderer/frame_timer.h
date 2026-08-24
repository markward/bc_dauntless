#pragma once
// native/src/renderer/include/renderer/frame_timer.h
//
// Per-pass CPU + GPU frame timing.
//
// The renderer had no timing instrumentation of any kind, so the frame budget
// was unmeasured: every statement about where the 16.67 ms goes was a guess.
// This is the measurement.
//
// CPU time comes from steady_clock around each scope. GPU time comes from
// GL_TIMESTAMP queries (core since GL 3.3), NOT GL_TIME_ELAPSED: only one
// TIME_ELAPSED query may be active at a time, which would forbid the nested
// scopes the pass structure naturally has (frame > render_space > nebula).
// Timestamp queries have no such restriction.
//
// Results are read back kRingDepth frames late so resolving never blocks on
// the GPU. A profiler that stalls the pipeline measures the stall.
//
// Disabled by default: push()/pop() are a predicted branch and nothing else,
// and no GL object is ever created, so the production render path is
// unaffected until a developer turns it on.

#include <cstdint>
#include <string>
#include <vector>

namespace renderer {

class FrameTimer {
public:
    struct ScopeResult {
        std::string name;
        double cpu_ms = 0.0;      // EMA-smoothed
        double gpu_ms = 0.0;      // EMA-smoothed; 0 when the scope issues no GL
        int    calls  = 0;        // entries in the last resolved frame
        int    depth  = 0;        // nesting depth IN THAT FRAME (see below)
    };

    /// Frames of latency before a frame's queries are read back. 3 is enough
    /// that GL_QUERY_RESULT_AVAILABLE is effectively always true, so we never
    /// stall; a record that is somehow still unavailable is retried, not waited on.
    static constexpr int kRingDepth = 3;

    /// Exponential-moving-average weight for the newest sample. Low enough to
    /// read stably by eye, high enough that a hitch is still visible.
    static constexpr double kEmaAlpha = 0.15;

    FrameTimer() = default;
    ~FrameTimer();

    FrameTimer(const FrameTimer&) = delete;
    FrameTimer& operator=(const FrameTimer&) = delete;

    bool enabled() const { return enabled_; }

    /// Turning the timer on clears accumulated averages so the first report
    /// is not a blend of old and new state. Turning it off leaves GL objects
    /// allocated (deleting them needs a current context, which the caller may
    /// not have) but stops all recording.
    void set_enabled(bool v);

    /// Frame boundary. begin_frame resolves the oldest pending record and
    /// starts a new one; end_frame closes it. Both are no-ops when disabled.
    void begin_frame();
    void end_frame();

    /// Open/close a timing scope. `name` must outlive the call (a string
    /// literal); it is copied into the slot table on first sight only.
    /// Unbalanced pop() is ignored rather than fatal — a profiler must never
    /// be the thing that crashes the game.
    void push(const char* name);
    void pop();

    /// The scopes entered in the last resolved frame, in entry order, each
    /// with the depth it had IN THAT FRAME.
    ///
    /// Deliberately not "every scope ever seen, at the depth it first had".
    /// Passes change parent at runtime -- render_space runs under `space` in
    /// the exterior view and under `viewscreen.rtt` on the bridge -- so a
    /// first-sight tree prints this frame's children beneath last mission's
    /// parent. The table would be individually correct and collectively a lie.
    /// A scope that stops running simply leaves the table; its average keeps
    /// decaying internally in case it comes back.
    const std::vector<ScopeResult>& results() const { return results_; }

    /// Whole-frame totals, EMA-smoothed, in ms.
    double frame_cpu_ms() const { return frame_cpu_ms_; }
    double frame_gpu_ms() const { return frame_gpu_ms_; }

    /// Frames resolved since the last reset. Report consumers use this to
    /// avoid printing an average built from one sample.
    std::uint64_t frames_resolved() const { return frames_resolved_; }

    /// Drop all averages and slots. Safe without a GL context.
    void reset();

private:
    struct Slot {
        std::string name;
        double cpu_ms = 0.0;      // EMA
        double gpu_ms = 0.0;      // EMA
        // First sample assigns rather than blends, so a scope's average never
        // has to climb out of a zero it was never measuring. Tracked per
        // channel: a scope can issue real CPU work and no GL at all.
        bool   cpu_seeded = false;
        bool   gpu_seeded = false;
    };

    struct Sample {
        int slot = 0;
        unsigned int q_begin = 0;
        unsigned int q_end = 0;
    };

    struct Record {
        std::vector<Sample> samples;
        std::vector<unsigned int> queries;   // owned pool, grows to high water
        std::size_t used = 0;                // queries handed out this frame
        std::vector<double> cpu_ns;          // per slot
        std::vector<int>    calls;           // per slot
        // Slot indices in the order they were first entered THIS frame, and
        // the depth each had when entered. Rebuilt every frame so the report's
        // tree always describes the frame it is reporting.
        std::vector<int>    order;
        std::vector<int>    depth;           // per slot
        double frame_cpu_ns = 0.0;
        bool   pending = false;
    };

    int slot_for(const char* name);
    unsigned int take_query(Record& rec);
    void resolve(Record& rec);

    bool enabled_ = false;
    std::uint64_t frame_index_ = 0;
    std::uint64_t frames_resolved_ = 0;

    Record ring_[kRingDepth];
    Record* current_ = nullptr;

    std::vector<Slot> slots_;
    std::vector<int>  open_;            // stack of slot indices
    std::vector<std::int64_t> open_t0_; // parallel: CPU start, ns since epoch
    std::vector<std::size_t>  open_sample_;  // parallel: index into rec.samples

    std::int64_t frame_t0_ = 0;
    double frame_cpu_ms_ = 0.0;
    double frame_gpu_ms_ = 0.0;
    bool   cpu_total_seeded_ = false;
    bool   gpu_total_seeded_ = false;

    std::vector<ScopeResult> results_;
};

/// RAII scope. Zero cost when the timer is disabled.
class ScopedFrameTimer {
public:
    ScopedFrameTimer(FrameTimer& t, const char* name) : t_(t) { t_.push(name); }
    ~ScopedFrameTimer() { t_.pop(); }
    ScopedFrameTimer(const ScopedFrameTimer&) = delete;
    ScopedFrameTimer& operator=(const ScopedFrameTimer&) = delete;
private:
    FrameTimer& t_;
};

/// The one instance the render passes and the host bindings share.
FrameTimer& frame_timer();

}  // namespace renderer

// Two-level concat so __LINE__ expands before pasting — the single-level form
// yields the literal identifier `dauntless_scope___LINE__` for every use, which
// collides the moment one block opens two scopes.
#define DAUNTLESS_FT_CAT2(a, b) a##b
#define DAUNTLESS_FT_CAT(a, b) DAUNTLESS_FT_CAT2(a, b)

/// Time the enclosing block as `name`. Compiles to a branch when disabled.
#define DAUNTLESS_FRAME_SCOPE(name)                \
    ::renderer::ScopedFrameTimer DAUNTLESS_FT_CAT( \
        dauntless_frame_scope_, __LINE__)(::renderer::frame_timer(), name)
