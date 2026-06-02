// SpeedDisplay render fn. Driven by Python via cef_execute_javascript:
//   setSpeedDisplay({visible, current_kph, max_kph, warp});
//
// Read-only — no clicks, no interactivity.
// Spec: docs/ui_designs/04-weapons-and-speed.md

(function () {
    "use strict";

    window.setSpeedDisplay = function (state) {
        var root = document.getElementById("speed-display");
        if (!root) { return; }
        root.hidden = !state.visible;
        if (!state.visible) { return; }

        root.dataset.warp = state.warp ? "true" : "false";

        var cur = root.querySelector('[data-bind="current"]');
        if (cur) { cur.textContent = String(state.current_kph); }
        var mx = root.querySelector('[data-bind="max"]');
        if (mx) { mx.textContent = String(state.max_kph); }
    };
})();
