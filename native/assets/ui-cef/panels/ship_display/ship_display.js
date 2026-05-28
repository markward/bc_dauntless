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
//     damage:       [{name, state}],  // state: "damaged" | "disabled" | "destroyed"
//     minimized:    bool,
//     range_m:      float | null,     // target role only
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

    // Shield face bucket — 75% / 0% thresholds per spec §5.
    function bucketForShield(pct) {
        if (pct >= 0.75) { return "full"; }
        if (pct > 0.0)   { return "damaged"; }
        return "down";
    }

    function rebuildDamageList(ul, damage) {
        ul.innerHTML = "";
        var rows = damage || [];
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var li = document.createElement("li");
            li.className = "damage-row";
            li.dataset.state = row.state || "";
            // e.g. "Engines — DISABLED"
            li.textContent = row.name + " — " + (row.state || "").toUpperCase();
            ul.appendChild(li);
        }
    }

    function setSilhouette(el, speciesKey) {
        // Phase 1: species stamped as a class hook; Task 9 will replace
        // this with an <img> driven by silhouette_url.
        if (!speciesKey) {
            el.className = "ship-display__silhouette";
            return;
        }
        el.className = "ship-display__silhouette silhouette--" + speciesKey.toLowerCase();
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

        var ul = root.querySelector('[data-bind="damage-list"]');
        if (ul) { rebuildDamageList(ul, state.damage); }

        var sil = root.querySelector('[data-bind="silhouette"]');
        if (sil) { setSilhouette(sil, state.species || null); }

        if (role === "target") {
            var rng = root.querySelector('[data-bind="range"]');
            var spd = root.querySelector('[data-bind="speed"]');
            if (rng) {
                rng.textContent = (state.range_m == null)
                    ? "— km"
                    : (state.range_m / 1000).toFixed(2) + " km";
            }
            if (spd) {
                spd.textContent = (state.speed_kph == null)
                    ? "— kph"
                    : Math.round(state.speed_kph) + " kph";
            }
        }
    };
})();
