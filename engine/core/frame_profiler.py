"""Frame-time measurement for the host loop's Python half.

The renderer's C++ passes are timed by renderer::FrameTimer (CPU + GPU, via
GL_TIMESTAMP queries) and read back through _dauntless_host.profiler_*. This
module is the other half: the per-frame Python work in engine.host_loop, which
is the larger body of code and was equally unmeasured.

MODEL — a flat phase timeline, not nested scopes.

The host loop body is one long linear sequence (input -> sim advance -> render
prep -> overlays -> r.frame()), so each phase is delimited by a single mark()
call at the seam. That is a one-line insert per boundary instead of re-indenting
a 1,300-line loop body into `with` blocks, and it cannot mis-nest: mark() closes
whatever was open and opens the next. The C++ side keeps real nesting because
its passes genuinely nest.

Timings are EMA-smoothed with the same weight the C++ timer uses, so the two
halves of a merged report are comparable rather than differently-lagged.

Disabled by default. When off, mark() is a module-global lookup and a branch.
"""
import time
from contextlib import contextmanager
from typing import Optional

# Matches renderer::FrameTimer::kEmaAlpha. If you change one, change both --
# a report that blends a fast-moving average against a slow one invites
# reading the difference as a real cost difference.
EMA_ALPHA = 0.15

_enabled = False
_perf = time.perf_counter

# phase name -> smoothed milliseconds, in first-seen order (which is loop order,
# so the report reads top-to-bottom as the frame executes).
_phases: dict[str, float] = {}
_seeded: set[str] = set()

# Raw milliseconds accumulated during the CURRENT frame, before smoothing.
# Two-stage on purpose: a name entered more than once in one frame (scope()
# around a helper called from several places) must SUM within the frame and
# only then fold into the average. Folding per entry instead would make two
# 2 ms uses report 2 ms rather than 4 -- each call blending against a value
# equal to itself, so the average never moves and the second use is invisible.
_frame_acc: dict[str, float] = {}

_open_name: Optional[str] = None
_open_t0: float = 0.0
_frame_t0: float = 0.0
_frame_ms: float = 0.0
_frame_seeded = False
_frames = 0


def is_enabled() -> bool:
    return _enabled


def set_enabled(value: bool, *, native: bool = True) -> None:
    """Turn measurement on or off, clearing whatever was accumulated.

    `native=True` also drives the C++ renderer timer through host_io, so one
    switch controls both halves and a report can never pair live Python
    numbers with stale (or absent) render numbers. Callers that want only the
    Python half -- tests, mainly -- pass native=False.
    """
    global _enabled
    if value == _enabled:
        return
    _enabled = value
    reset()
    if native:
        try:
            from engine import host_io
            host_io.profiler_set_enabled(value)
        except Exception:
            # A headless run or a stale extension module without the binding.
            # The Python half still measures; the report says the render half
            # is absent rather than inventing zeros for it.
            pass


def reset() -> None:
    global _open_name, _open_t0, _frame_t0, _frame_ms, _frame_seeded, _frames
    _phases.clear()
    _seeded.clear()
    _frame_acc.clear()
    _open_name = None
    _open_t0 = 0.0
    _frame_t0 = 0.0
    _frame_ms = 0.0
    _frame_seeded = False
    _frames = 0


def begin_frame() -> None:
    """Start a frame. Any phase left open by the previous frame is dropped."""
    global _open_name, _open_t0, _frame_t0
    if not _enabled:
        return
    _open_name = None
    _frame_acc.clear()
    _frame_t0 = _perf()
    _open_t0 = _frame_t0


def mark(name: str) -> None:
    """Close the open phase and open `name`.

    The FIRST mark of a frame just names the phase that began at begin_frame;
    it does not close anything. So a loop body marked

        begin_frame(); mark("input"); ...; mark("sim"); ...; end_frame()

    attributes begin_frame..mark("sim") to "input", which is what reading the
    call sites suggests it should.
    """
    global _open_name, _open_t0
    if not _enabled:
        return
    now = _perf()
    if _open_name is not None:
        _accumulate(_open_name, (now - _open_t0) * 1000.0)
    _open_name = name
    _open_t0 = now


def end_frame() -> None:
    """Close the open phase and fold the frame total into its average."""
    global _open_name, _frame_ms, _frame_seeded, _frames
    if not _enabled:
        return
    now = _perf()
    if _open_name is not None:
        _accumulate(_open_name, (now - _open_t0) * 1000.0)
        _open_name = None
    # Fold this frame's raw totals into the averages. Every KNOWN phase is
    # folded, not just the ones that ran: a pass that stops running must decay
    # toward zero rather than freeze at its last reading and keep being read as
    # a live cost. (renderer::FrameTimer does the same, for the same reason.)
    for name in list(_phases) + [n for n in _frame_acc if n not in _phases]:
        _fold(name, _frame_acc.get(name, 0.0))
    _frame_acc.clear()

    total = (now - _frame_t0) * 1000.0
    if _frame_seeded:
        _frame_ms += EMA_ALPHA * (total - _frame_ms)
    else:
        _frame_ms = total
        _frame_seeded = True
    _frames += 1


@contextmanager
def scope(name: str):
    """Time a nested block, accumulating into `name` for this frame.

    For the odd measurement that does not fit the flat timeline (a helper
    called from several phases). Costs a generator per use, so do not put one
    in a per-ship loop.
    """
    if not _enabled:
        yield
        return
    t0 = _perf()
    try:
        yield
    finally:
        _accumulate(name, (_perf() - t0) * 1000.0)


def _accumulate(name: str, ms: float) -> None:
    """Add raw milliseconds to the current frame's total for `name`."""
    _frame_acc[name] = _frame_acc.get(name, 0.0) + ms


def _fold(name: str, ms: float) -> None:
    """Blend one frame's total for `name` into its average.

    The first sample is ASSIGNED, not blended: seeding from zero would make a
    phase report ~15% of its true cost on the frame it first appears and climb
    from there, which is long enough to mislead anyone reading an early report.
    """
    if name in _seeded:
        _phases[name] += EMA_ALPHA * (ms - _phases[name])
    else:
        _phases[name] = ms
        _seeded.add(name)


def phases() -> dict[str, float]:
    """{phase name: smoothed ms}, in loop order."""
    return dict(_phases)


def frame_ms() -> float:
    """Smoothed wall-clock ms for the whole Python loop body."""
    return _frame_ms


def frames() -> int:
    return _frames


# ── Reporting ────────────────────────────────────────────────────────────────
# The report is printed to the console rather than drawn as a CEF overlay, and
# that is deliberate: the CEF surface is uploaded to the GPU in full every frame
# (no dirty-rect, no PBO), so a DOM overlay mutating every frame would add paint
# work to the very frame being measured. The console costs nothing until it
# prints, and it prints once every REPORT_EVERY frames.

REPORT_EVERY = 120          # ~2 s at 60 fps
_since_report = 0


def should_report() -> bool:
    """True once every REPORT_EVERY frames while enabled. Advances the counter."""
    global _since_report
    if not _enabled:
        return False
    _since_report += 1
    if _since_report < REPORT_EVERY:
        return False
    _since_report = 0
    return True


def report_lines() -> list[str]:
    """The merged report: Python loop phases, then render passes, then totals.

    Two things this states explicitly rather than leaving to the reader:

    * Whether vsync is capping the frame -- READ from the context, never
      assumed. Under swap interval 1 the `present` scope IS the wait for the
      next refresh, so a large `present` alongside small siblings means the
      frame finished EARLY and blocked, the opposite of what "present is
      expensive" would suggest; any headroom conclusion from such a capture is
      worthless. But a HIDDEN window already defaults to interval 0, so a
      report that hard-coded the vsync note told every headless capture the
      opposite of the truth. It now states the real value both in the header
      and next to `present`.
    * Whether the render half is present at all. A stale extension module
      yields an empty scope list, and a report that silently omitted the render
      passes would read as "the render costs nothing".
    """
    from engine import host_io

    lines: list[str] = []
    native = host_io.profiler_frame()
    scopes = host_io.profiler_scopes()

    # ASCII only, deliberately. Windows consoles default to cp1252, and a
    # box-drawing character in a printed line raises UnicodeEncodeError from
    # inside the frame loop -- the profiler would take down the game it is
    # measuring. Comments and docstrings are free to use whatever; anything
    # that reaches a stream must not.
    interval = native.get("swap_interval", -1)
    if interval == 1:
        cap = "swap interval 1 (VSYNC ON - frame is capped to the refresh rate)"
    elif interval == 0:
        cap = "swap interval 0 (uncapped)"
    else:
        cap = "swap interval unknown"
    lines.append("-- frame profile -- (EMA over %d frames, alpha %.2f, %s)"
                 % (_frames, EMA_ALPHA, cap))

    if _phases:
        lines.append("  python loop phases            cpu ms")
        for name, ms in _phases.items():
            lines.append("    %-26s %7.3f" % (name, ms))
    else:
        lines.append("  python loop phases: none recorded")

    if scopes:
        lines.append("  render passes                 cpu ms   gpu ms  calls")
        for s in scopes:
            indent = "  " * int(s.get("depth", 0))
            label = indent + str(s.get("name", "?"))
            note = ""
            if s.get("name") == "present":
                # Only a vsync wait when the interval actually is 1. At 0 this
                # is the swap itself plus whatever GPU work was still queued,
                # which is a real cost, not a block.
                note = ("   <- vsync wait (frame finished early)"
                        if interval == 1
                        else "   <- swap + queued GPU drain (not a vsync wait)")
            lines.append("    %-26s %7.3f  %7.3f  %5d%s"
                         % (label[:26], s.get("cpu_ms", 0.0),
                            s.get("gpu_ms", 0.0), s.get("calls", 0), note))
    elif native.get("enabled"):
        lines.append("  render passes: enabled, nothing resolved yet")
    else:
        lines.append("  render passes: UNAVAILABLE "
                     "(binding absent - rebuild the native module)")

    # The Python total already CONTAINS the render call: r.frame() is invoked
    # from inside the loop body, so these are nested, not additive. Saying so
    # here stops the two totals being summed into a number that is roughly
    # double the truth.
    lines.append("  totals: python loop %.3f ms (includes r.frame); "
                 "render cpu %.3f ms, gpu %.3f ms over %d frames"
                 % (_frame_ms, native.get("cpu_ms", 0.0),
                    native.get("gpu_ms", 0.0), native.get("frames", 0)))
    return lines


def print_report() -> None:
    """Write the merged report to stderr (stdout is the game's own console).

    Never raises. This runs inside the frame loop, and a profiler that can
    kill a frame is worse than no profiler -- so an encoding-hostile console
    or a closed stream degrades to a dropped report, not an exception.
    """
    import sys
    try:
        for line in report_lines():
            sys.stderr.write(line + "\n")
    except Exception:
        pass
