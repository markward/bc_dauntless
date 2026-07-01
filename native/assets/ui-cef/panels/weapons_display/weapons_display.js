// native/assets/ui-cef/panels/weapons_display/weapons_display.js
//
// WeaponsDisplay panel — DOM update entry point.
// Called from Python via render_payload: setWeaponsDisplay({...}).
//
// State shape:
//   {
//     visible:        bool,
//     ship_name:      str,
//     speed_label:    str,          // BC helm tooltip format,
//                                   // "Speed {imp} : {vel} kph"
//     silhouette_url: str | null,   // data:image/png;base64,...
//     weapon_icons:   [{
//       icon_num:      int,
//       icon_svg:      str,            // inline SVG text — fill="currentColor"
//                                      // so CSS color cascades into the path.
//       x_px:          float,          // top-left pixel offset in the
//       y_px:          float,          // SDK's WEAPONS_PANE (~130x110)
//       above:         bool,           // dorsal = above silhouette
//       firing:        bool,
//       destroyed:     bool,
//       online:        bool,           // bank's parent system is powered
//       charge_ratio:  float,          // 0..1, mixed into the icon colour
//       in_firing_arc: bool            // target is in arc + in range; adds
//                                      // .is-in-arc to draw a fine stroke
//     }, ...],
//     config: {                        // weapon-settings block (weapon_config.py)
//       show_settings, has_any_config,
//       has_torpedoes, torp_type, torp_count, torp_types_cyclable,
//       spread, spread_options,
//       has_phasers, phaser_intensity,
//       tractor_present, tractor_on, cloak_present, cloak_on
//     }
//   }
//
// The hamburger (weapons/toggle-view) flips between the status view and the
// settings view; each settings control fires weapons/<action>
// (cycle-type | cycle-spread | cycle-intensity | toggle-tractor | toggle-cloak).

(function () {
    "use strict";

    function setSilhouette(el, url) {
        if (!url) {
            el.removeAttribute("src");
            el.hidden = true;
            return;
        }
        el.src = url;
        el.hidden = false;
    }

    // Rebuild the per-mount icon overlay. Descriptor list is short
    // (Galaxy: ~14 mounts) and snapshot equality upstream gates calls,
    // so the cost is bounded.
    function renderWeaponIcons(root, icons) {
        var above = root.querySelector('[data-bind="weapons-above"]');
        var below = root.querySelector('[data-bind="weapons-below"]');
        if (!above || !below) { return; }
        above.innerHTML = "";
        below.innerHTML = "";
        var rows = icons || [];
        for (var i = 0; i < rows.length; i++) {
            var d = rows[i];
            var container = d.above ? above : below;
            // Indicator drawn first so it sits behind the weapon icon
            // (mirrors SDK layering at WeaponsDisplay.py:83-87 —
            // pUPhaserInd added before pUPhaser).
            // Inline SVG injection — currentColor in the path then
            // resolves against the parent span's CSS color so the
            // .weapon-icon rule themes the fill directly.
            // <img src="data:image/svg+xml,..."> would ignore outer
            // CSS and render with the SVG's own colour context
            // (defaults to black on the dark panel).
            var w = document.createElement("span");
            w.className = "weapon-icon"
                        + (d.destroyed ? " is-destroyed" : "")
                        + (d.online ? " is-online" : "")
                        + (d.in_firing_arc ? " is-in-arc" : "");
            w.style.left = d.x_px + "px";
            w.style.top  = d.y_px + "px";
            // When online, look up the 10 %-bucketed CSS variable for
            // this bank's charge. BC's WeaponsDisplay uses ~10 discrete
            // bands (black → red → yellow → green) rather than a
            // continuous lerp, and the bucket matches the snapshot
            // equality quantisation so the JS and the snapshot agree on
            // which colour applies. When offline, leaving the inline
            // style empty lets the CSS rule's --weapons-icon-offline
            // take over.
            if (d.online) {
                var bucket = Math.max(0, Math.min(10,
                    Math.round(d.charge_ratio * 10)));
                w.style.color = "var(--weapons-icon-charge-"
                              + (bucket * 10) + ")";
            }
            w.innerHTML = d.icon_svg;
            container.appendChild(w);
        }
    }

    function escHtml(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function spreadWord(n) {
        return n === 4 ? "Quad" : (n === 2 ? "Dual" : "Single");
    }

    // Build the weapon-settings view markup from the config block. Sections
    // gate on subsystem presence (mirrors read_weapon_config): no torpedo
    // launchers -> no Torpedoes section; no phasers -> no Phasers section; a
    // lone Tractor/Cloak button flexes to fill the row.
    function buildSettingsHtml(cfg) {
        var html = "";
        if (cfg.has_torpedoes) {
            var typeCls = "torp-btn torp-btn--type"
                        + (cfg.torp_types_cyclable ? "" : " torp-btn--static");
            var typeAct = cfg.torp_types_cyclable ? ' data-act="cycle-type"' : "";
            html += '<div class="section-head"><span>Torpedoes</span></div>'
                  + '<div class="section-rule"></div>'
                  + '<div class="torp-row">'
                  +   '<div class="' + typeCls + '"' + typeAct + '>'
                  +     '<span class="name">' + escHtml(cfg.torp_type) + '</span>'
                  +     '<span class="qty">(' + (cfg.torp_count | 0) + ')</span>'
                  +   '</div>'
                  +   '<div class="torp-btn torp-btn--spread" data-act="cycle-spread">'
                  +     '<span class="spread">' + spreadWord(cfg.spread) + '</span>'
                  +   '</div>'
                  + '</div>';
        }
        if (cfg.has_phasers) {
            html += '<div class="section-head"><span>Phasers</span></div>'
                  + '<div class="section-rule"></div>'
                  + '<div class="cfg-row" data-act="cycle-intensity">'
                  +   '<span class="label">Intensity</span>'
                  +   '<span class="value">' + escHtml(cfg.phaser_intensity) + '</span>'
                  +   '<span class="caret">‹ ›</span>'
                  + '</div>';
        }
        var sys = "";
        if (cfg.tractor_present) {
            sys += '<div class="sys-btn' + (cfg.tractor_on ? " sys-btn--on" : "") + '" data-act="toggle-tractor">'
                 +   '<span class="label">Tractor</span><span class="value">' + (cfg.tractor_on ? "On" : "Off") + '</span>'
                 + '</div>';
        }
        if (cfg.cloak_present) {
            sys += '<div class="sys-btn' + (cfg.cloak_on ? " sys-btn--on" : "") + '" data-act="toggle-cloak">'
                 +   '<span class="label">Cloak</span><span class="value">' + (cfg.cloak_on ? "On" : "Off") + '</span>'
                 + '</div>';
        }
        if (sys) {
            html += '<div style="height:6px;"></div><div class="sys-row">' + sys + '</div>';
        }
        return html;
    }

    // Wire every [data-act] control to fire the matching weapons/<action>
    // event back to Python (which mutates the shared weapon_config state).
    function wireSettingsActions(container) {
        var els = container.querySelectorAll("[data-act]");
        for (var i = 0; i < els.length; i++) {
            (function (el) {
                el.onclick = function () {
                    dauntlessEvent("weapons/" + el.getAttribute("data-act"));
                };
            })(els[i]);
        }
    }

    window.setWeaponsDisplay = function (state) {
        var root = document.getElementById("weapons-display");
        if (!root) { return; }

        root.hidden = !state.visible;
        if (!state.visible) { return; }

        // Header label: BC's "Speed {imp} : {vel} kph" helm-tooltip
        // format. Replaces the standalone SpeedDisplay's KPH readout.
        var label = root.querySelector('[data-bind="speed-label"]');
        if (label) {
            label.textContent = state.speed_label || "Speed 0 : 0 kph";
        }

        var sil = root.querySelector('[data-bind="silhouette"]');
        if (sil) { setSilhouette(sil, state.silhouette_url || null); }

        renderWeaponIcons(root, state.weapon_icons);

        // ── Weapon-settings view ────────────────────────────────────────
        var cfg = state.config || {};
        var btn = root.querySelector('[data-bind="mode-btn"]');
        var viewStatus = root.querySelector('[data-bind="view-status"]');
        var viewSettings = root.querySelector('[data-bind="view-settings"]');
        var open = !!cfg.show_settings && !!cfg.has_any_config;

        // Hamburger only appears when there's something to configure.
        if (btn) { btn.hidden = !cfg.has_any_config; }
        var tip = root.querySelector('[data-bind="mode-tip"]');
        if (tip) { tip.textContent = open ? "Hide settings" : "Weapon settings"; }

        if (viewSettings) {
            if (open) {
                viewSettings.innerHTML = buildSettingsHtml(cfg);
                wireSettingsActions(viewSettings);
                viewSettings.hidden = false;
            } else {
                viewSettings.hidden = true;
                viewSettings.innerHTML = "";
            }
        }
        if (viewStatus) { viewStatus.hidden = open; }
    };
})();
