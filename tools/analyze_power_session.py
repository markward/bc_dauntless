"""Analyze a BCTickLog.cfg power-drain session captured by the ORIGINAL game
via tools/appc_power_logger.py.

Scenario Mark runs: Galaxy at red alert, all four power groups at 125%, tractor
engaged on an asteroid, held until power depletes. This derives:
  * absolute drain rates of main / backup batteries (per phase),
  * whether backup drains BEFORE main is empty (conduit-overflow model) or only
    AFTER main depletes (the manual's "backup is a last resort" story),
  * whether the original AdjustPower throttles the sliders under tractor load.

Usage:
    uv run python tools/analyze_power_session.py [path/to/BCTickLog.cfg]
    uv run python tools/analyze_power_session.py --selftest
"""
from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
DEFAULT_LOG = PROJECT_ROOT / "game" / "BCTickLog.cfg"

# Column order emitted by appc_power_logger.py (mirrors its "pfields" key).
FIELDS = [
    "game_time", "main", "backup", "output", "mainconduit", "backupconduit",
    "available", "dispensed", "wanted", "condpct",
    "impulse", "warp", "shields", "phasers", "torps", "pulse", "sensors",
    "tractor",
]
SLIDER_FIELDS = ["impulse", "warp", "shields", "phasers", "torps", "pulse", "sensors"]

# --- Dauntless model predictions for this exact scenario --------------------
# All four groups at 125%, tractor held. Our engine/appc/subsystems.py delivers
# through BOTH the main and backup conduits every interval (each min'd against
# its own battery), so backup drains CONCURRENTLY with main rather than only
# after main empties. Rates below are the modeled steady-state figures the task
# names for the comparison block.
DAUNTLESS_PREDICTION = {
    "main_drain_per_s": -200.0,
    "backup_drain_per_s": -200.0,
    "concurrent": True,  # backup begins draining while main > 0
    "sliders_throttled": False,  # AdjustPower holds the requested 125%
}


@dataclass
class Sample:
    game_time: float
    values: dict  # field name -> float or None ("NA")


def _parse_val(tok: str):
    if tok == "NA":
        return None
    try:
        return float(tok)
    except ValueError:
        return None


def read_power_log(log_path: pathlib.Path) -> list[Sample]:
    """Parse the [BCTickLog] p* power samples from a SaveConfigFile .cfg."""
    if not log_path.exists():
        print(f"Log not found: {log_path}")
        print("Run: uv run python tools/setup.py --power --recompile")
        print("then play the scenario, quit, and retry.")
        sys.exit(1)

    raw: dict[int, str] = {}
    pcount = 0
    in_section = False
    err_type = err_value = None

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
            if key == "pcount":
                pcount = int(val)
            elif key == "err_type":
                err_type = val
            elif key == "err_value":
                err_value = val
            elif key.startswith("p") and key[1:].isdigit():
                raw[int(key[1:])] = val

    if err_type:
        print(f"Snippet error recorded in log: {err_type}: {err_value}")

    samples: list[Sample] = []
    for i in range(pcount):
        parts = raw.get(i, "").split()
        if len(parts) < len(FIELDS):
            continue
        vals = {name: _parse_val(parts[j]) for j, name in enumerate(FIELDS)}
        gt = vals.get("game_time")
        if gt is None:
            continue
        samples.append(Sample(game_time=gt, values=vals))
    return samples


def _rate(prev: Sample, cur: Sample, field: str):
    a = prev.values.get(field)
    b = cur.values.get(field)
    dt = cur.game_time - prev.game_time
    if a is None or b is None or dt <= 0:
        return None
    return (b - a) / dt


def _fmt(v, width=8, prec=1):
    if v is None:
        return "NA".rjust(width)
    return ("%.*f" % (prec, v)).rjust(width)


def _slider_active(samples: list[Sample]) -> list[Sample]:
    """Samples where a real player exists (main battery is not NA)."""
    return [s for s in samples if s.values.get("main") is not None]


def _phase_split(samples: list[Sample]):
    """Split active samples into (pre_tractor, tractor_engaged) by the tractor
    firing flag. Returns two lists; either may be empty."""
    pre, engaged = [], []
    for s in samples:
        t = s.values.get("tractor")
        if t is not None and t >= 1.0:
            engaged.append(s)
        else:
            pre.append(s)
    return pre, engaged


def _mean_rate(seq: list[Sample], field: str):
    rates = []
    for i in range(1, len(seq)):
        r = _rate(seq[i - 1], seq[i], field)
        if r is not None:
            rates.append(r)
    if not rates:
        return None
    return sum(rates) / len(rates)


def _backup_starts_before_main_empty(samples: list[Sample]) -> bool | None:
    """True if backup drops below its first observed value while main is still
    > 0 (conduit-overflow model). None if undeterminable."""
    active = _slider_active(samples)
    if len(active) < 2:
        return None
    backup0 = active[0].values.get("backup")
    if backup0 is None:
        return None
    for s in active[1:]:
        main = s.values.get("main")
        backup = s.values.get("backup")
        if main is None or backup is None:
            continue
        if backup < backup0 - 1e-6 and main > 1e-6:
            return True
    return False


def analyze(log_path: pathlib.Path) -> None:
    samples = read_power_log(log_path)
    active = _slider_active(samples)

    print(f"Log:      {log_path}")
    print(f"Samples:  {len(samples)} total, {len(active)} with a live player")
    if not active:
        print("No samples with a live player — was the scenario actually running?")
        sys.exit(1)

    # --- Table -------------------------------------------------------------
    hdr = (f"{'t':>7} {'main':>8} {'backup':>8} {'dMain/s':>8} {'dBack/s':>8} "
           f"{'output':>7} {'disp':>7} {'avail':>7} {'sliders(i/w/s/ph/t/pu/se)':>28} {'trac':>4}")
    print()
    print(hdr)
    print("-" * len(hdr))
    prev = None
    for s in active:
        dmain = _rate(prev, s, "main") if prev else None
        dback = _rate(prev, s, "backup") if prev else None
        sliders = "/".join(
            "NA" if s.values.get(f) is None else "%g" % s.values[f]
            for f in SLIDER_FIELDS
        )
        trac = s.values.get("tractor")
        trac_s = "NA" if trac is None else ("%d" % int(trac))
        print(f"{s.game_time:7.1f} {_fmt(s.values.get('main'))} "
              f"{_fmt(s.values.get('backup'))} {_fmt(dmain)} {_fmt(dback)} "
              f"{_fmt(s.values.get('output'), 7)} {_fmt(s.values.get('dispensed'), 7)} "
              f"{_fmt(s.values.get('available'), 7)} {sliders:>28} {trac_s:>4}")
        prev = s

    # --- Phase drain rates -------------------------------------------------
    pre, engaged = _phase_split(active)
    print()
    print("=== Measured drain rates ===")
    for label, seq in (("pre-tractor", pre), ("tractor-engaged", engaged)):
        m = _mean_rate(seq, "main")
        b = _mean_rate(seq, "backup")
        n = max(len(seq) - 1, 0)
        print(f"  {label:16} ({len(seq)} samples, {n} intervals):")
        print(f"      main   Δ/s: {('NA' if m is None else '%.2f' % m)}")
        print(f"      backup Δ/s: {('NA' if b is None else '%.2f' % b)}")

    # --- Reservoir order / overlap ----------------------------------------
    concurrent = _backup_starts_before_main_empty(active)
    print()
    print("=== Reservoir drain order ===")
    if concurrent is None:
        print("  Undeterminable (need >=2 samples with main+backup readings).")
    elif concurrent:
        print("  Backup starts draining while main > 0  -> CONDUIT-OVERFLOW model")
        print("  (both reservoirs deliver concurrently; matches Dauntless).")
    else:
        print("  Backup only drops after main depletes  -> MANUAL's 'last resort' model")
        print("  (main is fully drained before backup is touched).")

    # --- Slider throttling -------------------------------------------------
    print()
    print("=== AdjustPower slider behaviour under tractor load ===")
    moved = {}
    for f in SLIDER_FIELDS:
        vals = [s.values.get(f) for s in active if s.values.get(f) is not None]
        if len(vals) >= 2:
            moved[f] = (min(vals), max(vals))
    any_moved = False
    for f, (lo, hi) in moved.items():
        if abs(hi - lo) > 0.5:
            any_moved = True
            print(f"  {f:8}: moved {lo:g} -> {hi:g}  (AdjustPower throttled it)")
    if not any_moved:
        if moved:
            held = ", ".join("%s=%g" % (f, v[0]) for f, v in moved.items())
            print(f"  All sliders held constant: {held}")
            print("  -> AdjustPower did NOT throttle the requested percentages.")
        else:
            print("  No slider readings captured.")

    # --- Comparison with Dauntless model ----------------------------------
    p = DAUNTLESS_PREDICTION
    print()
    print("=== Dauntless model prediction (all groups 125%, tractor held) ===")
    print(f"  main   drain Δ/s: {p['main_drain_per_s']:.1f}")
    print(f"  backup drain Δ/s: {p['backup_drain_per_s']:.1f}")
    print(f"  reservoir order:  {'concurrent (conduit-overflow)' if p['concurrent'] else 'main-then-backup'}")
    print(f"  sliders:          {'throttled' if p['sliders_throttled'] else 'held at request'}")
    print()
    print("  Diff vs measured:")
    m_eng = _mean_rate(engaged, "main")
    b_eng = _mean_rate(engaged, "backup")
    if m_eng is not None:
        print(f"    main   Δ/s: model {p['main_drain_per_s']:.1f} vs measured {m_eng:.2f} "
              f"(Δ {m_eng - p['main_drain_per_s']:+.2f})")
    if b_eng is not None:
        print(f"    backup Δ/s: model {p['backup_drain_per_s']:.1f} vs measured {b_eng:.2f} "
              f"(Δ {b_eng - p['backup_drain_per_s']:+.2f})")
    if concurrent is not None:
        match = (concurrent == p["concurrent"])
        print(f"    reservoir order: {'MATCH' if match else 'MISMATCH'} "
              f"(model concurrent={p['concurrent']}, measured concurrent={concurrent})")


# --- Self-test fixture ------------------------------------------------------
def _write_synthetic_fixture(path: pathlib.Path) -> None:
    """Emit a BCTickLog.cfg matching the SaveConfigFile shape with a plausible
    conduit-overflow discharge: main and backup both drain -200/s concurrently,
    tractor firing throughout, sliders held at 125."""
    lines = ["[Options]", "SomeUnrelated=1", "[BCTickLog]"]
    lines.append("pfields=" + " ".join(FIELDS))
    samples = []
    main = 6000.0
    backup = 4000.0
    for i in range(8):
        t = i * 2.0
        trac = 1 if i >= 1 else 0  # first sample pre-tractor
        row = [
            "%g" % t,
            "%g" % main,
            "%g" % backup,
            "500",         # output
            "300",         # mainconduit
            "150",         # backupconduit
            "450",         # available
            "440",         # dispensed
            "460",         # wanted
            "100",         # condpct
            "125", "125", "125", "125", "125", "125", "125",  # sliders held
            "%d" % trac,
        ]
        samples.append(" ".join(row))
        if trac:
            main = max(main - 400.0, 0.0)    # 2s interval * 200/s
            backup = max(backup - 400.0, 0.0)
    for i, s in enumerate(samples):
        lines.append("p%d=%s" % (i, s))
    lines.append("pcount=%d" % len(samples))
    lines.append("[NextSection]")
    lines.append("Ignored=1")
    path.write_text("\n".join(lines) + "\n")


def _selftest() -> None:
    import tempfile

    tmp = pathlib.Path(tempfile.mkdtemp()) / "BCTickLog.cfg"
    _write_synthetic_fixture(tmp)
    samples = read_power_log(tmp)
    assert len(samples) == 8, len(samples)
    active = _slider_active(samples)
    assert len(active) == 8, len(active)

    _, engaged = _phase_split(active)
    assert len(engaged) == 7, len(engaged)
    m = _mean_rate(engaged, "main")
    b = _mean_rate(engaged, "backup")
    assert abs(m - (-200.0)) < 1e-6, m
    assert abs(b - (-200.0)) < 1e-6, b

    assert _backup_starts_before_main_empty(active) is True

    # NA parsing: a row with all-NA payload should be dropped from active.
    print("Self-test: parse + phase split + drain rate + overflow detection OK")
    print(f"  main drain: {m:.1f}/s   backup drain: {b:.1f}/s   concurrent: True")
    # Full report render smoke test (must not raise).
    analyze(tmp)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        log = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG
        analyze(log)
