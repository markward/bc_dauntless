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
// whichever timer query the DRIVER DECLARES (choose_gpu_timer), read once per
// enable from GL_QUERY_COUNTER_BITS:
//
//   * GL_TIMESTAMP when its counter has bits. Every scope is timed, nested or
//     not, because timestamps have no one-active-at-a-time rule.
//   * GL_TIME_ELAPSED when the timestamp counter has 0 bits -- Apple's
//     GL-over-Metal (measured 2026-10-08: GL_TIMESTAMP 0 bits, GL_TIME_ELAPSED
//     32). Only one TIME_ELAPSED query may be active, so only the direct
//     children of the outermost `frame` scope are timed: they run strictly in
//     sequence. Nested scopes keep their CPU time and report gpu_measured =
//     false, which the report prints as "-". The `frame` row's GPU time is the
//     sum of its timed children.
//   * Nothing, when neither counter has bits.
//
// A 0-bit GL_TIMESTAMP counter is never queried at all: Apple's driver answers
// with zeros yet charges 2-6 ms/frame for the queries (measured 2026-10-03).
//
// Results are read back kRingDepth frames late, and only once
// GL_QUERY_RESULT_AVAILABLE says so, so resolving never blocks on the GPU. A
// profiler that stalls the pipeline measures the stall.
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
        // False when no GPU query covered this scope (a nested scope under
        // GL_TIME_ELAPSED, or no GPU timer at all). gpu_ms is then 0.0 and
        // means NOT MEASURED, never "free".
        bool   gpu_measured = false;
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

    enum class GpuTimer { None, Timestamp, Elapsed };

    /// The GPU timer a driver supports, from the GL_QUERY_COUNTER_BITS it
    /// declares for each target. A counter with no bits is never queried.
    static constexpr GpuTimer choose_gpu_timer(int timestamp_bits,
                                               int elapsed_bits) {
        return timestamp_bits > 0 ? GpuTimer::Timestamp
             : elapsed_bits > 0   ? GpuTimer::Elapsed
                                  : GpuTimer::None;
    }

    /// Under GL_TIME_ELAPSED, the one scope depth that gets a query: the
    /// children of the outermost scope. They are sequential, so at most one
    /// TIME_ELAPSED query is ever active.
    static constexpr int kElapsedDepth = 1;
    static constexpr bool elapsed_times_depth(int depth) {
        return depth == kElapsedDepth;
    }

    FrameTimer() = default;
    ~FrameTimer();

    FrameTimer(const FrameTimer&) = delete;
    FrameTimer& operator=(const FrameTimer&) = delete;

    bool enabled() const { return enabled_; }

    /// Turning the timer on clears accumulated averages so the first report
    /// is not a blend of old and new state. Turning it off stops all
    /// recording. Either way the query pool is dropped (see reset()), so the
    /// next enable generates fresh queries in whatever context is current.
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

    /// The frame end_frame() just closed, CPU only and RAW: not smoothed and
    /// not lagged by the ring (CPU time is known at pop). gpu_ms is 0 and
    /// gpu_measured false on every row. For the spike log, which needs one
    /// long frame's own numbers -- the EMA in results() hides a single hitch.
    const std::vector<ScopeResult>& last_frame_raw() const { return last_raw_; }
    double last_frame_raw_cpu_ms() const { return last_raw_cpu_ms_; }

    /// Whole-frame totals, EMA-smoothed, in ms.
    double frame_cpu_ms() const { return frame_cpu_ms_; }
    double frame_gpu_ms() const { return frame_gpu_ms_; }

    /// Frames resolved since the last reset. Report consumers use this to
    /// avoid printing an average built from one sample.
    std::uint64_t frames_resolved() const { return frames_resolved_; }

    /// The GPU timer in use. None until the first frame after an enable has
    /// read the driver's counter bits (that needs a current context).
    GpuTimer gpu_timer() const { return enabled_ ? gpu_timer_ : GpuTimer::None; }

    /// True while scopes issue GPU queries of any kind.
    bool gpu_queries_active() const { return gpu_timer() != GpuTimer::None; }

    /// The counter bits the driver declared, -1 until probed.
    int timestamp_bits() const { return timestamp_bits_; }
    int elapsed_bits() const { return elapsed_bits_; }

    /// glQueryCounter(GL_TIMESTAMP) calls since the last reset. Exists so a
    /// test can prove a 0-bit driver is never sent one.
    std::uint64_t timestamp_queries_issued() const { return timestamp_queries_; }

    /// Drop all averages, slots, and the per-record query pool. Safe without a
    /// GL context: the query NAMES are abandoned rather than deleted, because
    /// this is reachable after the context that owned them is gone (a
    /// shutdown()/init() cycle) and deleting a name in a different context
    /// would destroy an unrelated object there. Keeping them was the bug: the
    /// next enable issued glQueryCounter against dead names and every readback
    /// reported unavailable, so nothing ever resolved again.
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
        unsigned int q_begin = 0;   // timestamp begin, or the TIME_ELAPSED query
        unsigned int q_end = 0;     // timestamp end; 0 under TIME_ELAPSED
        // TIME_ELAPSED only: the sample index of the enclosing outermost
        // scope, whose GPU time is the sum of its timed children. -1 if none.
        int parent = -1;
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
        // The query whose glQueryCounter was issued LAST this frame, which is
        // the outermost scope's q_end (end_frame force-closes it after every
        // child has closed). NOT samples.back().q_end -- that is the last
        // scope PUSHED, i.e. `present`, whose end query is issued BEFORE the
        // enclosing `frame` scope's. resolve() needs the truly-last one for
        // both its availability check and the whole-frame span; see there.
        unsigned int last_query = 0;
        double frame_cpu_ns = 0.0;
        bool   pending = false;
        // The timer this frame's queries were issued with, fixed at
        // begin_frame so resolve() reads them back the same way.
        GpuTimer timer = GpuTimer::None;
    };

    int slot_for(const char* name);
    unsigned int take_query(Record& rec);
    void resolve(Record& rec);

    bool enabled_ = false;
    bool gpu_probed_ = false;                    // counter bits read this enable
    GpuTimer gpu_timer_ = GpuTimer::None;
    int timestamp_bits_ = -1;
    int elapsed_bits_ = -1;
    bool elapsed_open_ = false;                  // a TIME_ELAPSED query is active
    std::uint64_t timestamp_queries_ = 0;
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
    std::vector<ScopeResult> last_raw_;
    double last_raw_cpu_ms_ = 0.0;
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
