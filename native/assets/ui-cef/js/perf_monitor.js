// native/assets/ui-cef/js/perf_monitor.js
//
// Developer-only performance monitor in the top-right corner. Driven by
// engine/ui/perf_monitor_panel.py via cef_execute_javascript:
//   setPerfMonitor({visible, width, height, fps, frame_ms});
// fps / frame_ms are null until the first half-second window closes.
// Non-interactive (pointer-events: none), so it needs no click bbox.
// Spec: docs/superpowers/specs/2026-10-20-dev-perf-monitor-design.md
function setPerfMonitor(state) {
    var root = document.getElementById('perf-monitor');
    if (!root) return;
    if (!state || !state.visible) {
        root.style.display = 'none';
        return;
    }
    root.style.display = 'block';
    var res = document.getElementById('perf-monitor-res');
    var fps = document.getElementById('perf-monitor-fps');
    var ms = document.getElementById('perf-monitor-ms');
    res.textContent = state.width + ' × ' + state.height;
    if (state.fps == null) {
        fps.textContent = '--';
        ms.textContent = '-- ms';
        fps.className = 'perf-monitor__fps';
        return;
    }
    fps.textContent = String(state.fps);
    ms.textContent = state.frame_ms.toFixed(1) + ' ms';
    var band = state.fps >= 55 ? 'good' : (state.fps >= 30 ? 'fair' : 'poor');
    fps.className = 'perf-monitor__fps perf-monitor__fps--' + band;
}
