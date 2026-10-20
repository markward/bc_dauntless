"""Tests for the developer-only performance monitor: the flag module, the
frame-rate meter, and the top-right overlay panel that shows resolution and
FPS. Spec: docs/superpowers/specs/2026-10-20-dev-perf-monitor-design.md"""
import json

import pytest


@pytest.fixture
def dev_on():
    import _dauntless_host
    import engine.dev_perf_monitor as perf
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    perf.reset()
    try:
        yield perf
    finally:
        perf.reset()
        _dauntless_host.developer_mode = original_dev


def _body(payload):
    assert payload.startswith("setPerfMonitor(") and payload.endswith(");")
    return json.loads(payload[len("setPerfMonitor("):-2])


# ---- flag module ------------------------------------------------------------

def test_off_by_default(dev_on):
    assert dev_on.enabled() is False


def test_set_enabled_round_trips(dev_on):
    dev_on.set_enabled(True)
    assert dev_on.enabled() is True
    dev_on.set_enabled(False)
    assert dev_on.enabled() is False


def test_never_enabled_without_developer_mode(dev_on):
    import _dauntless_host
    dev_on.set_enabled(True)
    _dauntless_host.developer_mode = False
    assert dev_on.enabled() is False


# ---- frame-rate meter -------------------------------------------------------

def test_meter_reports_nothing_before_its_first_window():
    from engine.dev_perf_monitor import FrameRateMeter
    m = FrameRateMeter(window_s=0.5)
    m.record(1 / 60)
    assert m.fps is None and m.frame_ms is None


def test_meter_averages_over_the_window():
    from engine.dev_perf_monitor import FrameRateMeter
    m = FrameRateMeter(window_s=0.5)
    for _ in range(30):
        m.record(1 / 60)
    assert m.fps == pytest.approx(60.0)
    assert m.frame_ms == pytest.approx(1000 / 60)


def test_meter_publishes_per_window_not_cumulatively():
    """A slow stretch must show up within one window, not be diluted by the
    whole session's history."""
    from engine.dev_perf_monitor import FrameRateMeter
    m = FrameRateMeter(window_s=0.5)
    for _ in range(30):
        m.record(1 / 60)
    for _ in range(15):
        m.record(1 / 30)
    assert m.fps == pytest.approx(30.0)


def test_meter_ignores_non_positive_deltas():
    from engine.dev_perf_monitor import FrameRateMeter
    m = FrameRateMeter(window_s=0.5)
    m.record(0.0)
    m.record(-1.0)
    for _ in range(30):
        m.record(1 / 60)
    assert m.fps == pytest.approx(60.0)


# ---- overlay panel ----------------------------------------------------------

def _panel(size=(3840, 2160)):
    from engine.ui.perf_monitor_panel import PerfMonitorPanel
    return PerfMonitorPanel(size_fn=lambda: size)


def test_panel_name_and_throttle():
    p = _panel()
    assert p.name == "perf-monitor"
    assert p.poll_interval_s > 0.0


def test_panel_hidden_until_enabled(dev_on):
    p = _panel()
    p.tick(1 / 60)
    assert p.visible is False
    assert _body(p.render_payload()) == {"visible": False}


def test_panel_shows_resolution_and_fps_when_enabled(dev_on):
    dev_on.set_enabled(True)
    p = _panel(size=(2560, 1440))
    for _ in range(30):
        p.tick(1 / 60)
    assert p.visible is True
    body = _body(p.render_payload())
    assert body["visible"] is True
    assert body["width"] == 2560 and body["height"] == 1440
    assert body["fps"] == 60
    assert body["frame_ms"] == pytest.approx(16.7)


def test_panel_shows_placeholders_before_first_window(dev_on):
    dev_on.set_enabled(True)
    p = _panel()
    p.tick(1 / 60)
    body = _body(p.render_payload())
    assert body["fps"] is None and body["frame_ms"] is None


def test_panel_dedups_unchanged_payload(dev_on):
    dev_on.set_enabled(True)
    p = _panel()
    for _ in range(30):
        p.tick(1 / 60)
    assert p.render_payload() is not None
    assert p.render_payload() is None


def test_panel_re_emits_when_resolution_changes(dev_on):
    dev_on.set_enabled(True)
    size = [1920, 1080]
    from engine.ui.perf_monitor_panel import PerfMonitorPanel
    p = PerfMonitorPanel(size_fn=lambda: tuple(size))
    for _ in range(30):
        p.tick(1 / 60)
    p.render_payload()
    size[:] = [1280, 720]
    body = _body(p.render_payload())
    assert (body["width"], body["height"]) == (1280, 720)


def test_panel_hides_when_disabled_again(dev_on):
    dev_on.set_enabled(True)
    p = _panel()
    p.tick(1 / 60)
    p.render_payload()
    dev_on.set_enabled(False)
    p.tick(1 / 60)
    assert p.visible is False
    assert _body(p.render_payload()) == {"visible": False}


def test_panel_invalidate_re_emits(dev_on):
    dev_on.set_enabled(True)
    p = _panel()
    p.tick(1 / 60)
    p.render_payload()
    p.invalidate()
    assert p.render_payload() is not None


def test_panel_survives_a_failing_size_source(dev_on):
    def boom():
        raise RuntimeError("no renderer")
    from engine.ui.perf_monitor_panel import PerfMonitorPanel
    dev_on.set_enabled(True)
    p = PerfMonitorPanel(size_fn=boom)
    p.tick(1 / 60)
    body = _body(p.render_payload())
    assert body["width"] == 0 and body["height"] == 0


def test_panel_handles_no_events():
    assert _panel().dispatch_event("anything") is False


# ---- Developer Options row --------------------------------------------------

def test_developer_options_toggle_drives_the_flag(dev_on):
    from engine.ui.developer_options_panel import DeveloperOptionsPanel
    panel = DeveloperOptionsPanel()
    panel.open()
    assert panel.dispatch_event("toggle:perf_monitor") is True
    assert dev_on.enabled() is True
    assert panel.dispatch_event("toggle:perf_monitor") is True
    assert dev_on.enabled() is False


def test_developer_options_row_is_on_the_diagnostics_tab(dev_on):
    from engine.ui.developer_options_panel import DeveloperOptionsPanel
    panel = DeveloperOptionsPanel()
    panel.open()
    panel.dispatch_event("tab:diagnostics")
    assert ("ctrl", "perf_monitor") in panel._focusables()


def test_developer_options_reopen_reads_the_live_flag(dev_on):
    from engine.ui.developer_options_panel import DeveloperOptionsPanel
    panel = DeveloperOptionsPanel()
    dev_on.set_enabled(True)
    panel.open()
    assert panel._perf_monitor is True


def test_js_focus_list_matches_python():
    """developer_options.js duplicates the focus order; keyboard focus lands on
    the wrong row if the two drift."""
    from engine import paths
    js = (paths.PROJECT_ROOT / "native" / "assets" / "ui-cef" / "js"
          / "developer_options.js").read_text()
    assert "target: 'perf_monitor'" in js
    assert "'perf_monitor', s.perf_monitor" in js


def test_index_html_hosts_the_overlay():
    from engine import paths
    root = paths.PROJECT_ROOT / "native" / "assets" / "ui-cef"
    html = (root / "index.html").read_text()
    assert 'id="perf-monitor"' in html
    assert 'src="js/perf_monitor.js"' in html
    assert 'href="css/perf_monitor.css"' in html
    assert "function setPerfMonitor(" in (root / "js" / "perf_monitor.js").read_text()
