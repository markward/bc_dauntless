// native/assets/ui-cef/panels/ship_display/ship_display.js
//
// ShipDisplay panel — DOM update entry point.
// Called from Python via render_payload: setShipDisplay("player", {...}).
//
// State shape:
//   {
//     visible:      bool,
//     ship_name:    str,
//     affiliation:  "FRIENDLY" | "ENEMY" | "NEUTRAL" | "NONE",
//     species:      str | null,       // e.g. "galaxy", "warbird"
//     hull_pct:     float,            // 0.0 – 1.0
//     shields_pct:  [float x 6],      // FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT
//     damage_icons: [{icon_num, icon_svg, x_px, y_px, state}],
//     minimized:    bool,
//     range_km:     float | null,     // target role only — already km
//     speed_kph:    float | null,     // target role only
//   }
//
// Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md

(function () {
    "use strict";

    // Shield face binding order must match the Python shields_pct tuple:
    // index 0 = FRONT, 1 = REAR, 2 = TOP, 3 = BOTTOM, 4 = LEFT, 5 = RIGHT.
    // ShieldSubsystem emits faces in this order; JS reads them at the same
    // positions. A face-order swap here silently shows wrong quadrant states.
    var SHIELD_FACE_BIND_ORDER = [
        "shield-front",
        "shield-rear",
        "shield-top",
        "shield-bottom",
        "shield-left",
        "shield-right"
    ];

    // Hull bucket thresholds — 70% / 25% matches the spec and test fixtures.
    function bucketForHull(pct) {
        if (pct >= 0.70) { return "healthy"; }
        if (pct >= 0.25) { return "damaged"; }
        return "critical";
    }

    // Shield face bucket — four tiers driving the arc colour:
    //   down     ≤ 1%   → hidden (≤1% epsilon so the per-tick regen
    //                     trickle doesn't flicker the arc back on for
    //                     a fraction of a second after shields drop)
    //   critical 1-33%  → red
    //   damaged  34-66% → amber
    //   healthy  ≥ 67%  → green
    function bucketForShield(pct) {
        if (pct <= 0.01) { return "down"; }
        if (pct < 0.34)  { return "critical"; }
        if (pct < 0.67)  { return "damaged"; }
        return "healthy";
    }

    // SDK reference panel size at 640x480: 128 wide x 120 tall.
    // Hardpoint Position2D coords are pixel-space against this frame;
    // the overlay covers the silhouette stack at 100% / 100%, so we
    // map x_px → percent by dividing by these constants.
    var SDK_PANE_WIDTH_PX  = 128;
    var SDK_PANE_HEIGHT_PX = 120;

    function rebuildDamageOverlay(overlay, rows) {
        overlay.innerHTML = "";
        var entries = rows || [];
        for (var i = 0; i < entries.length; i++) {
            var row = entries[i];
            if (!row || !row.icon_svg) { continue; }
            var el = document.createElement("div");
            el.className = "damage-icon";
            el.dataset.state = row.state || "healthy";
            el.dataset.iconNum = String(row.icon_num);
            el.style.left = (row.x_px / SDK_PANE_WIDTH_PX  * 100).toFixed(2) + "%";
            el.style.top  = (row.y_px / SDK_PANE_HEIGHT_PX * 100).toFixed(2) + "%";
            el.innerHTML = row.icon_svg;  // potrace-traced, deterministic; safe
            overlay.appendChild(el);
        }
    }

    function setSilhouette(el, url) {
        if (!url) {
            el.removeAttribute("src");
            el.hidden = true;
            return;
        }
        el.src = url;
        el.hidden = false;
    }

    window.setShipDisplay = function (role, state) {
        var root = document.getElementById("ship-display-" + role);
        if (!root) { return; }

        root.hidden = !state.visible;
        if (!state.visible) { return; }

        root.dataset.affiliation = state.affiliation || "NONE";
        root.dataset.hull = bucketForHull(typeof state.hull_pct === "number" ? state.hull_pct : 1.0);
        root.dataset.minimized = state.minimized ? "true" : "false";

        var title = root.querySelector('[data-bind="title"]');
        if (title) {
            title.textContent = state.ship_name || (role === "target" ? "NO TARGET" : "PLAYER");
        }

        var hullPct = typeof state.hull_pct === "number" ? state.hull_pct : 1.0;
        var fill = root.querySelector('[data-bind="hull-fill"]');
        if (fill) { fill.style.width = (hullPct * 100).toFixed(1) + "%"; }
        var pct = root.querySelector('[data-bind="hull-pct"]');
        if (pct) { pct.textContent = Math.round(hullPct * 100) + "%"; }

        var shields = state.shields_pct || [];
        for (var i = 0; i < SHIELD_FACE_BIND_ORDER.length; i++) {
            var el = root.querySelector('[data-bind="' + SHIELD_FACE_BIND_ORDER[i] + '"]');
            if (el) {
                el.dataset.integrity = bucketForShield(typeof shields[i] === "number" ? shields[i] : 0);
            }
        }

        var overlay = root.querySelector('[data-bind="damage-overlay"]');
        if (overlay) { rebuildDamageOverlay(overlay, state.damage_icons); }

        var sil = root.querySelector('[data-bind="silhouette"]');
        if (sil) { setSilhouette(sil, state.silhouette_url || null); }

        if (role === "target") {
            var rng = root.querySelector('[data-bind="range"]');
            var spd = root.querySelector('[data-bind="speed"]');
            if (rng) {
                rng.textContent = (state.range_km == null)
                    ? "— km"
                    : state.range_km.toFixed(2) + " km";
            }
            if (spd) {
                spd.textContent = (state.speed_kph == null)
                    ? "— kph"
                    : Math.round(state.speed_kph) + " kph";
            }
        }
    };
})();
