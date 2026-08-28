"""Frame-time measurement for the host loop's Python half.

The renderer's C++ passes are timed by renderer::FrameTimer (CPU + GPU, via
GL_TIMESTAMP queries) and read back through _dauntless_host.profiler_*. This
module is the other half: the per-frame Python work in engine.host_loop, which
is the larger body of code and was equally unmeasured.

MODEL — a flat timeline of mark() phases, with a nested scope() tree hanging
off it.

The loop BODY is one long linear sequence (input -> sim advance -> render prep
-> overlays -> r.frame()), so each top-level phase is delimited by a single
mark() call at the seam: a one-line insert per boundary instead of re-indenting
a 1,300-line loop body into `with` blocks, and it cannot mis-nest, because
mark() closes whatever was open and opens the next.

Inside those phases the breakdown IS a tree, and pretending otherwise is how
the report came to print `gl.ai` above `sim` with nothing marking the relation:

    sim                  (mark)
      sim.gameloop       (scope, once per catch-up tick)
        gl.ai gl.motion gl.subsystems ...
      sim.combat         (scope, once per frame)
        cb.projectiles cb.phasers ...
    ui_panels            (mark)
      ui.render_all
        ui.<panel>

So scope() records the scope (or mark phase) it opened inside, and the report
indents each row under its parent. Children are INCLUDED in their parent's
total; summing the column counts the frame about three times over.

Timings are EMA-smoothed with the same weight the C++ timer uses, so the two
halves of a merged report are comparable rather than differently-lagged.

Disabled by default. When off, mark() is a module-global lookup and a branch.
scope() is NOT free even when off: @contextmanager builds a generator and a
_GeneratorContextManager per use, ~0.36 us measured, so it belongs at phase
seams and around whole subsystems, never inside a per-ship or per-projectile
loop. (The C++ half's push/pop really are just a branch when disabled.)
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

# name -> the phase it ran INSIDE (None for a top-level mark() phase), and the
# order names were first seen. The parent is re-recorded on every entry, so the
# tree describes the most recent frame's nesting rather than freezing whatever
# the first frame happened to look like -- a helper scope called from two
# phases really does change parent, exactly as the C++ passes do.
_parents: dict[str, Optional[str]] = {}
_order: list[str] = []
_scope_stack: list[str] = []

# Entries per name in the CURRENT frame, and the snapshot of that from the last
# completed frame. Printed because it is the generic answer to "is this row a
# sum?": sim.gameloop and everything under it runs once per catch-up tick, its
# siblings run once per frame, and the two used to print indistinguishably.
_frame_calls: dict[str, int] = {}
_calls: dict[str, int] = {}

_open_name: Optional[str] = None
_open_t0: float = 0.0
_frame_t0: float = 0.0
_frame_ms: float = 0.0
_frame_seeded = False
_frames = 0
_frame_open = False

# Fixed-timestep catch-up ticks in the last frame. Reported because the frame
# cost is dominated by it whenever the sim cannot keep up, and reading a phase
# total without it invites dividing by the wrong number: "sim = 500 ms" is ten
# ticks of 50, not one tick of 500.
#
# Smoothed as well as raw: every cost beside it is an EMA, so printing only the
# instantaneous count invites dividing an average by a single frame's tick
# count. Both are printed, each labelled.
_sim_ticks = 0
_sim_ticks_avg = 0.0
_sim_ticks_seeded = False

# Rows that are summed over the frame's catch-up ticks rather than measured
# once per frame. Only the ROOT is named: everything nested inside it inherits
# the property, which the parent chain already knows. This is host_loop's
#
#     for _ in range(_sim_ticks_this_frame):
#         with frame_profiler.scope("sim.gameloop"):
#             loop.tick()
#
# and its siblings sim.weapons / sim.combat / sim.collisions deliberately sit
# OUTSIDE that loop. If the scope is ever renamed, rename it here too -- the
# per-frame `calls` column is the backstop that still tells the truth.
PER_TICK_ROOTS = frozenset({"sim.gameloop"})


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
    global _frame_open, _sim_ticks, _since_report
    global _sim_ticks_avg, _sim_ticks_seeded
    _phases.clear()
    _seeded.clear()
    _frame_acc.clear()
    _parents.clear()
    _order.clear()
    _scope_stack.clear()
    _frame_calls.clear()
    _calls.clear()
    _open_name = None
    _open_t0 = 0.0
    _frame_t0 = 0.0
    _frame_ms = 0.0
    _frame_seeded = False
    _frames = 0
    _frame_open = False
    # Both of these used to survive a reset. The stale tick count was printed
    # beside freshly-seeded costs, and the stale interval made the first frame
    # after re-enabling report immediately -- which is what turned a wrong
    # average into a visibly absurd headline number.
    _sim_ticks = 0
    _sim_ticks_avg = 0.0
    _sim_ticks_seeded = False
    _since_report = 0


def begin_frame() -> None:
    """Start a frame. Any phase left open by the previous frame is dropped."""
    global _open_name, _open_t0, _frame_t0, _frame_open
    if not _enabled:
        return
    _open_name = None
    _frame_acc.clear()
    _frame_calls.clear()
    # A scope() that was open when the profiler was switched on mid-frame never
    # ran its `finally`, so the stack can be stale. Left standing it would make
    # this frame's top-level scopes children of a phase that ended long ago.
    _scope_stack.clear()
    _frame_t0 = _perf()
    _open_t0 = _frame_t0
    _frame_open = True


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
    # A mark phase is always a root of the report tree: marks delimit the loop
    # body itself, so nothing in the loop contains them.
    _note(name, None)
    _open_name = name
    _open_t0 = now


def end_frame() -> None:
    """Close the open phase and fold the frame total into its average."""
    global _open_name, _frame_ms, _frame_seeded, _frames, _frame_open
    if not _enabled:
        return
    # The profiler is toggled on mid-frame -- that is the documented workflow --
    # so this frame's begin_frame() may have run while disabled and no-opped,
    # leaving _frame_t0 at 0.0. Measuring against that yields perf_counter()'s
    # raw epoch (hundreds of thousands of seconds), and since reset() also
    # clears _frame_seeded it is ASSIGNED rather than blended: the headline
    # total starts at ~8.5e8 ms and decays, reading as "the frame got faster".
    # A frame this module did not open is not a frame it can time.
    if not _frame_open:
        return
    _frame_open = False
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
    # Raw, not smoothed, and for the frame just closed only -- the same rule
    # the C++ timer's `calls` follows, so the two tables mean the same thing.
    _calls.clear()
    _calls.update(_frame_calls)

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

    The block is recorded as a CHILD of whatever scope (or mark phase) is open
    around it, which is what lets the report print `gl.ai` underneath
    `sim.gameloop` underneath `sim` rather than as three unrelated rows.

    Costs a generator plus a _GeneratorContextManager per use -- ~0.36 us even
    when the profiler is DISABLED, because the decorator work happens before
    the `if not _enabled` ever runs. Fine at a phase seam or around a whole
    subsystem; never inside a per-ship or per-projectile loop.
    """
    if not _enabled:
        yield
        return
    # Nested inside another scope -> that scope is the parent. Otherwise the
    # mark() phase currently open is, since marks delimit the loop body.
    _note(name, _scope_stack[-1] if _scope_stack else _open_name)
    _scope_stack.append(name)
    t0 = _perf()
    try:
        yield
    finally:
        # Pop before accumulating: a raising block must not leave this scope on
        # the stack, or every later scope in the frame becomes its child.
        if _scope_stack:
            _scope_stack.pop()
        _accumulate(name, (_perf() - t0) * 1000.0)


def _note(name: str, parent: Optional[str]) -> None:
    """Record where `name` ran, and its first-sight position in the report."""
    if name not in _parents:
        _order.append(name)
    _parents[name] = parent


def _accumulate(name: str, ms: float) -> None:
    """Add raw milliseconds -- and one entry -- to this frame's total for `name`."""
    _frame_acc[name] = _frame_acc.get(name, 0.0) + ms
    _frame_calls[name] = _frame_calls.get(name, 0) + 1


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


def calls() -> dict[str, int]:
    """{phase name: entries in the last completed frame}.

    Raw, not smoothed -- a row entered three times is a sum of three, and an
    averaged count would match neither reading.
    """
    return dict(_calls)


def parents() -> dict[str, Optional[str]]:
    """{phase name: the phase it ran inside}, None for a top-level mark."""
    return dict(_parents)


def note_sim_ticks(n: int) -> None:
    """Record how many fixed-timestep ticks the current frame ran."""
    global _sim_ticks, _sim_ticks_avg, _sim_ticks_seeded
    if not _enabled:
        return
    _sim_ticks = int(n)
    # Seeded on the first sample for the same reason every other average here
    # is: a count that had to climb out of zero would understate the divisor
    # exactly when the sim is struggling and the divisor matters most.
    if _sim_ticks_seeded:
        _sim_ticks_avg += EMA_ALPHA * (_sim_ticks - _sim_ticks_avg)
    else:
        _sim_ticks_avg = float(_sim_ticks)
        _sim_ticks_seeded = True


def sim_ticks() -> int:
    """The LAST frame's tick count. Instantaneous; see sim_ticks_avg()."""
    return _sim_ticks


def sim_ticks_avg() -> float:
    """Smoothed tick count, comparable with the smoothed costs beside it."""
    return _sim_ticks_avg


# ── Reporting ────────────────────────────────────────────────────────────────
# The report is printed to the console rather than drawn as a CEF overlay, and
# that is deliberate: the CEF surface is uploaded to the GPU in full every frame
# (no dirty-rect, no PBO), so a DOM overlay mutating every frame would add paint
# work to the very frame being measured. The console costs nothing until it
# prints, and it prints once every REPORT_EVERY frames.

REPORT_EVERY = 120          # ~2 s at 60 fps
_since_report = 0

# Label column width, and the marker that says a name did not fit. A silently
# clipped name reads as a different, shorter phase -- `ui.tactical_left_column`
# and `ui.tactical_left_co` are not obviously the same row to a reader who did
# not write the code.
LABEL_W = 30
CLIP_MARK = "+"

# Appended to rows that are summed over the frame's catch-up ticks. Everything
# else in the table is a once-per-frame cost, and the tick count printed above
# the table invites dividing all of them by it.
PER_TICK_MARK = "*"

# Resolved frames of an exactly-zero whole-frame GPU span before the report
# calls the GPU column broken rather than fast. Apple's GL returns zeroed
# GL_TIMESTAMP counters, and `gpu_ms` only ever accumulates when t1 >= t0, so a
# dead driver produces a full column of 0.000 that is indistinguishable from a
# free GPU -- the same misreading the "render passes: UNAVAILABLE" line exists
# to prevent. One frame proves nothing (an idle frame can round to zero); a few
# hundred cannot all be zero on a GPU that is drawing anything.
GPU_ZERO_FRAMES = 30


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


def _fit(label: str) -> str:
    """Clip `label` to the column, MARKING that it was clipped."""
    if len(label) <= LABEL_W:
        return label
    return label[:LABEL_W - len(CLIP_MARK)] + CLIP_MARK


def _is_per_tick(name: str) -> bool:
    """True when `name` is summed over the frame's catch-up ticks.

    Walks up the parent chain rather than matching a name prefix: the property
    belongs to everything INSIDE the per-tick scope, and `gl.` is a naming
    convention that a new scope can forget. Bounded by a visited set because a
    scope entered under two different parents in different frames could
    otherwise leave a cycle in the recorded tree.
    """
    seen = set()
    cur: Optional[str] = name
    while cur is not None and cur not in seen:
        if cur in PER_TICK_ROOTS:
            return True
        seen.add(cur)
        cur = _parents.get(cur)
    return False


def _phase_tree() -> list[tuple[int, str]]:
    """(depth, name) for every known phase, parents before their children.

    Depth is what makes the containment readable: `gl.ai` is 10 ms OF the
    35 ms `sim.gameloop` is OF the 70 ms `sim`, and printing all three flush
    left made the column look like 115 ms of a 70 ms frame.
    """
    names = list(_order) + [n for n in _phases if n not in _parents]
    known = set(names)
    children: dict[Optional[str], list[str]] = {}
    for name in names:
        parent = _parents.get(name)
        if parent not in known or parent == name:
            parent = None      # orphan (or self-parented): print it as a root
        children.setdefault(parent, []).append(name)

    rows: list[tuple[int, str]] = []
    emitted: set[str] = set()

    def walk(parent: Optional[str], depth: int) -> None:
        for name in children.get(parent, ()):
            if name in emitted:
                continue       # a cycle in the recorded tree; print it once
            emitted.add(name)
            rows.append((depth, name))
            walk(name, depth + 1)

    walk(None, 0)
    # Anything the walk could not reach (only possible via a cycle) still gets
    # printed: a phase missing from the report is worse than a mis-indented one.
    for name in names:
        if name not in emitted:
            rows.append((0, name))
    return rows


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
    lines.append(scene_summary())
    # Both numbers, each labelled: the costs beside them are EMA-smoothed, so
    # dividing one of those by a single frame's raw tick count mixes an
    # instantaneous value into an average.
    lines.append("  sim ticks: %.1f avg, %d last frame  (catch-up; the frame "
                 "runs one gameloop tick per 16.67 ms of accumulated game "
                 "time, capped at 15)" % (_sim_ticks_avg, _sim_ticks))

    try:
        from engine.appc.ai_driver import ai_breakdown_report
        _ai = ai_breakdown_report()
        if _ai:
            lines.append(_ai)
    except Exception:
        pass

    if _phases:
        lines.append("  %-32s %7s %5s" % ("python loop phases", "cpu ms",
                                          "calls"))
        any_per_tick = False
        for depth, name in _phase_tree():
            per_tick = _is_per_tick(name)
            any_per_tick = any_per_tick or per_tick
            lines.append("    %-30s %7.3f %5d %s"
                         % (_fit("  " * depth + name), _phases.get(name, 0.0),
                            _calls.get(name, 0),
                            PER_TICK_MARK if per_tick else " "))
        # The two things an indented column of numbers still does not say.
        lines.append("    (an indented row is included in its parent's total "
                     "-- do not sum the column)")
        if any_per_tick:
            lines.append("    (%s = per tick: summed over this frame's "
                         "catch-up ticks, so divide by the tick count above. "
                         "Unmarked rows run once per frame.)" % PER_TICK_MARK)
    else:
        lines.append("  python loop phases: none recorded")

    # A driver with dead GL_TIMESTAMP counters reports every span as zero, and
    # zero reads as "free". Say so instead, for the same reason a missing
    # binding says UNAVAILABLE rather than printing zeros.
    gpu_dead = (native.get("gpu_ms", 0.0) == 0.0
                and native.get("frames", 0) >= GPU_ZERO_FRAMES)
    if gpu_dead:
        lines.append("  GPU TIMING UNAVAILABLE: whole-frame GPU span was "
                     "exactly 0 over %d resolved frames, so the driver is "
                     "returning zeroed GL_TIMESTAMP counters (Apple's GL "
                     "does). The gpu column below is NOT MEASURED - read it "
                     "as absent, not as a free GPU."
                     % native.get("frames", 0))

    if scopes:
        lines.append("  %-32s %7s %7s %5s" % ("render passes", "cpu ms",
                                              "gpu ms", "calls"))
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
            gpu = ("      -" if gpu_dead
                   else "%7.3f" % s.get("gpu_ms", 0.0))
            lines.append("    %-30s %7.3f %s %5d%s"
                         % (_fit(label), s.get("cpu_ms", 0.0), gpu,
                            s.get("calls", 0), note))
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
                 "render cpu %.3f ms, gpu %s over %d frames"
                 % (_frame_ms, native.get("cpu_ms", 0.0),
                    "UNAVAILABLE" if gpu_dead
                    else "%.3f ms" % native.get("gpu_ms", 0.0),
                    native.get("frames", 0)))
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


# ── Scene load ───────────────────────────────────────────────────────────────
# A capture that does not say what it measured is not reproducible, and worse,
# it invites a confident conclusion about the wrong scene. The first captures
# taken with this profiler were all of an IDLE game -- QuickBattle boots with
# an empty enemy list, and E3M1/E2M1/E8M1 run 900 ticks with zero projectiles
# fired and zero hull damage -- and nothing in the output said so. Every report
# now carries its own load line.
#
# Computed lazily, only when a report is actually built (every REPORT_EVERY
# frames), so it costs nothing per frame. Best-effort throughout: a profiler
# must never be the thing that raises.

def scene_summary() -> str:
    """One line describing the load: ships, projectiles, damage taken.

    Returns a short marker rather than raising if the world is not available
    (headless import contexts, teardown, a mission mid-swap).
    """
    ships = projectiles = damaged = -1
    try:
        from engine.appc.ship_iter import iter_ships
        live = list(iter_ships())
        ships = len(live)
        damaged = 0
        for s in live:
            try:
                hull = s.GetHull()
                if hull is not None and hull.GetCondition() < hull.GetMaxCondition():
                    damaged += 1
            except Exception:
                continue
    except Exception:
        pass
    try:
        from engine.appc import projectiles as _p
        projectiles = len(_p._active)
    except Exception:
        pass

    def _n(v):
        return "?" if v < 0 else str(v)

    line = ("  scene: %s ships, %s projectiles in flight, %s hull-damaged"
            % (_n(ships), _n(projectiles), _n(damaged)))
    # The whole point of the line: say plainly when nothing is happening, so a
    # reader cannot mistake an idle capture for a representative one.
    if projectiles == 0 and damaged == 0:
        line += "   <- IDLE: no combat in this capture"
    return line
