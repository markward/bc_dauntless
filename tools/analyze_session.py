"""Analyze a BCTickLog.cfg session and report tick rate (Q1), time scale (Q3),
and frame position of Python AI calls (Q2)."""
import pathlib
import statistics
import sys

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
DEFAULT_LOG = PROJECT_ROOT / "game" / "BCTickLog.cfg"


def read_log(log_path: pathlib.Path) -> tuple[
    list[tuple[float, int, float, float | None]],
    list[tuple[float, int, float]],
]:
    """Parse the [BCTickLog] section from a SaveConfigFile-format .cfg file.

    Returns:
      ticks:  list of (wall_time, frame, game_time, frame_pos_s)
              frame_pos_s is None for old 3-field entries
      events: list of (wall_time, frame, frame_pos_s) from AddEvent wrapper
    """
    if not log_path.exists():
        print(f"Log not found: {log_path}")
        print("Run setup.py --recompile, play Quick Battle for 30s, then retry.")
        sys.exit(1)

    tick_data: dict[int, str] = {}
    ev_data: dict[int, str] = {}
    count = 0
    evcount = 0
    in_section = False

    with open(log_path) as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line == "[BCTickLog]":
                in_section = True
                continue
            if line.startswith("[") and in_section:
                break
            sep = "=" if "=" in line else "|" if "|" in line else ""
            if not in_section or not sep:
                continue
            key, _, val = line.partition(sep)
            if key == "count":
                count = int(val)
            elif key == "evcount":
                evcount = int(val)
            elif key in ("err_type", "err_value"):
                print(f"Snippet error recorded: {key}={val}")
            elif key.startswith("ev") and key[2:].isdigit():
                ev_data[int(key[2:])] = val
            elif key.startswith("t") and key[1:].isdigit():
                tick_data[int(key[1:])] = val

    ticks: list[tuple[float, int, float, float | None]] = []
    for i in range(count):
        parts = tick_data.get(i, "").split()
        if len(parts) == 4:
            ticks.append((float(parts[0]), int(parts[1]), float(parts[2]), float(parts[3])))
        elif len(parts) == 3:
            ticks.append((float(parts[0]), int(parts[1]), float(parts[2]), None))

    events: list[tuple[float, int, float]] = []
    for i in range(evcount):
        parts = ev_data.get(i, "").split()
        if len(parts) == 3:
            events.append((float(parts[0]), int(parts[1]), float(parts[2])))

    return ticks, events


def analyze(log_path: pathlib.Path) -> None:
    entries, events = read_log(log_path)

    if len(entries) < 10:
        print(f"Only {len(entries)} entries — need at least 10.")
        print("Make sure gameplay was active (Quick Battle, not just the main menu).")
        sys.exit(1)

    wall = [e[0] for e in entries]
    frames = [e[1] for e in entries]
    game_t = [e[2] for e in entries]
    frame_pos = [e[3] for e in entries if e[3] is not None]

    total_wall = wall[-1] - wall[0]
    total_frames = frames[-1] - frames[0]
    mean_hz = total_frames / total_wall
    period_ms = (total_wall / total_frames) * 1000

    frame_steps = [frames[i + 1] - frames[i] for i in range(len(frames) - 1)]
    skipped = sum(1 for s in frame_steps if s > 1)

    game_duration = game_t[-1] - game_t[0]
    time_scale = game_duration / total_wall

    print(f"Samples:    {len(entries)} frame boundaries")
    print(f"Duration:   {total_wall:.1f}s wall / {game_duration:.1f}s game time")
    print(f"Frames:     {total_frames} ticks")
    print(f"Tick rate:  {mean_hz:.2f} Hz  ({period_ms:.2f} ms/tick)")

    if len(frame_steps) > 1:
        wall_deltas = [wall[i + 1] - wall[i] for i in range(len(wall) - 1)]
        sample_sigma = statistics.stdev(wall_deltas) * 1000
        print(f"Sample σ:   {sample_sigma:.2f} ms (includes AI scheduling jitter)")

    print(f"Time scale: {time_scale:.4f}  (1.000 = normal speed)")

    if skipped:
        pct = 100.0 * skipped / len(frame_steps)
        print(f"Note:       {skipped}/{len(frame_steps)} samples ({pct:.0f}%) skipped frames")
        print("            Python not called every tick - tick rate above is still accurate.")

    # Q2: frame position — where in the tick does Python AI get called?
    if frame_pos:
        tick_s = total_wall / total_frames  # measured tick duration in seconds
        fp_ms = [v * 1000.0 for v in frame_pos]
        # Outliers: values larger than 2x the tick period are measurement
        # artefacts (startup, pause/resume). Filter for the verdict but report both.
        clean = [v for v in frame_pos if v <= 2.0 * tick_s]
        outliers = len(frame_pos) - len(clean)
        print()
        print(f"Q2 frame position (where in the {period_ms:.2f} ms tick Python AI is called):")
        print(f"  median: {statistics.median(fp_ms):.3f} ms")
        print(f"  mean:   {statistics.mean(fp_ms):.3f} ms")
        print(f"  min:    {min(fp_ms):.3f} ms")
        print(f"  max:    {max(fp_ms):.3f} ms")
        if len(fp_ms) > 1:
            print(f"  stdev:  {statistics.stdev(fp_ms):.3f} ms")
        if outliers:
            print(f"  ({outliers} outlier(s) > 2x tick period excluded from verdict)")
        if clean:
            median_frac = statistics.median(clean) / tick_s
            median_ms = statistics.median(clean) * 1000.0
            if median_frac < 0.25:
                verdict = "early in tick — before most C++ subsystems"
            elif median_frac > 0.75:
                verdict = "late in tick — after most C++ subsystems"
            else:
                verdict = "mid-tick"
            print(f"  -> Python AI called {verdict} ({median_ms:.2f} ms = {median_frac*100:.0f}% into {period_ms:.2f} ms tick)")
    else:
        print()
        print("Q2: no frame_pos data (old log format — rerun with current snippet)")

    # OQ-4.2: event dispatch timing — when in the tick does AddEvent fire?
    if events:
        tick_s = total_wall / total_frames
        ev_pos = [e[2] for e in events]
        ev_ms = [v * 1000.0 for v in ev_pos]
        # AI window: frame_pos values consistent with Q2 result (~0.28ms, <1ms)
        ai_window_s = 0.001
        in_ai = sum(1 for v in ev_pos if v <= ai_window_s)
        outside_ai = len(ev_pos) - in_ai
        print()
        print(f"OQ-4.2 event dispatch (first {len(events)} AddEvent calls):")
        print(f"  median frame_pos: {statistics.median(ev_ms):.3f} ms")
        print(f"  mean frame_pos:   {statistics.mean(ev_ms):.3f} ms")
        print(f"  min:              {min(ev_ms):.3f} ms")
        print(f"  max:              {max(ev_ms):.3f} ms")
        print(f"  within AI window (<1ms):  {in_ai}/{len(ev_pos)} ({100*in_ai//len(ev_pos)}%)")
        print(f"  outside AI window (>1ms): {outside_ai}/{len(ev_pos)} ({100*outside_ai//len(ev_pos)}%)")
        if in_ai > outside_ai:
            print("  -> Events dispatched primarily from Python AI window")
            print("     (consistent with synchronous / Python-driven dispatch)")
        else:
            print("  -> Events dispatched throughout the tick (C++ drives most events)")
            print("     Need handler-side instrumentation to determine reentrancy model")
    else:
        print()
        print("OQ-4.2: no event data (rerun with current snippet)")

    print()
    for candidate_hz in (20, 25, 30, 60):
        if abs(period_ms - 1000.0 / candidate_hz) < 2.0:
            print(f"Q1 answer:  {candidate_hz} Hz fixed tick rate")
            return

    if mean_hz < 5:
        print(f"Q1 answer:  {mean_hz:.1f} Hz - unexpectedly low, check gameplay was active")
    else:
        wall_deltas = [wall[i + 1] - wall[i] for i in range(len(wall) - 1)]
        verdict = "fixed" if statistics.stdev(wall_deltas) * 1000 < 3.0 else "variable"
        print(f"Q1 answer:  {mean_hz:.1f} Hz ({verdict})")


if __name__ == "__main__":
    log = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG
    analyze(log)
