"""Tests for tools/analyze_power_session.py against synthetic BCTickLog.cfg
fixtures (no game required)."""
import pathlib

from tools.analyze_power_session import (
    FIELDS,
    _backup_starts_before_main_empty,
    _mean_rate,
    _phase_split,
    _slider_active,
    _write_synthetic_fixture,
    analyze,
    read_power_log,
)


def _make_log(tmp_path: pathlib.Path, rows: list[str]) -> pathlib.Path:
    """Write a minimal SaveConfigFile-shaped .cfg with the given p* rows."""
    lines = ["[Options]", "Foo=1", "[BCTickLog]"]
    lines.append("pfields=" + " ".join(FIELDS))
    for i, r in enumerate(rows):
        lines.append("p%d=%s" % (i, r))
    lines.append("pcount=%d" % len(rows))
    lines.append("[Trailing]")
    lines.append("Bar=2")
    p = tmp_path / "BCTickLog.cfg"
    p.write_text("\n".join(lines) + "\n")
    return p


def _row(t, main, backup, tractor, slider=125):
    return (
        "%g %g %g 500 300 150 450 440 460 100 %g %g %g %g %g %g %g %d"
        % (t, main, backup, slider, slider, slider, slider, slider, slider,
           slider, tractor)
    )


def test_parses_pcount_and_columns(tmp_path):
    log = _make_log(tmp_path, [_row(0, 4000, 2000, 0), _row(2, 3600, 1600, 1)])
    samples = read_power_log(log)
    assert len(samples) == 2
    assert samples[0].values["main"] == 4000
    assert samples[1].values["backup"] == 1600
    assert samples[1].values["tractor"] == 1


def test_na_tokens_parse_to_none_and_drop_from_active(tmp_path):
    na_payload = " ".join(["0"] + ["NA"] * (len(FIELDS) - 1))
    log = _make_log(tmp_path, [na_payload, _row(2, 3600, 1600, 1)])
    samples = read_power_log(log)
    assert samples[0].values["main"] is None
    active = _slider_active(samples)
    assert len(active) == 1
    assert active[0].values["main"] == 3600


def test_measured_drain_rate_matches_synthetic_200(tmp_path):
    rows = [_row(0, 4000, 2000, 1), _row(2, 3600, 1600, 1), _row(4, 3200, 1200, 1)]
    log = _make_log(tmp_path, rows)
    active = _slider_active(read_power_log(log))
    assert abs(_mean_rate(active, "main") - (-200.0)) < 1e-6
    assert abs(_mean_rate(active, "backup") - (-200.0)) < 1e-6


def test_conduit_overflow_detected_when_backup_drops_with_main_positive(tmp_path):
    rows = [_row(0, 4000, 2000, 1), _row(2, 3600, 1600, 1)]
    log = _make_log(tmp_path, rows)
    active = _slider_active(read_power_log(log))
    assert _backup_starts_before_main_empty(active) is True


def test_manual_model_detected_when_backup_holds_until_main_empty(tmp_path):
    # main drains to 0 first, backup untouched, then backup drops.
    rows = [_row(0, 400, 2000, 1), _row(2, 0, 2000, 1), _row(4, 0, 1600, 1)]
    log = _make_log(tmp_path, rows)
    active = _slider_active(read_power_log(log))
    # backup drops (at t=4) only when main is already 0 -> not "before empty".
    assert _backup_starts_before_main_empty(active) is False


def test_phase_split_by_tractor_flag(tmp_path):
    rows = [_row(0, 4000, 2000, 0), _row(2, 4000, 2000, 0), _row(4, 3600, 1600, 1)]
    log = _make_log(tmp_path, rows)
    active = _slider_active(read_power_log(log))
    pre, engaged = _phase_split(active)
    assert len(pre) == 2
    assert len(engaged) == 1


def test_analyze_renders_without_error(tmp_path, capsys):
    p = tmp_path / "BCTickLog.cfg"
    _write_synthetic_fixture(p)
    analyze(p)
    out = capsys.readouterr().out
    assert "Measured drain rates" in out
    assert "Dauntless model prediction" in out
    assert "CONDUIT-OVERFLOW" in out
