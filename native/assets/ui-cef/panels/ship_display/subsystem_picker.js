// native/assets/ui-cef/panels/ship_display/subsystem_picker.js
//
// The target panel's subsystem picker: one square button per family, a name
// bar, the open family's members as blocks, and the lock marker on the ship
// icon. State is the `setShipDisplay("target", ...)` payload (families,
// icons, open_family, locked). Loaded after ship_display.js; ship_display.js calls
// renderSubsystemPicker(root, state) for the target role.
//
// Pure functions first (pickerFamilyColumns, pickerMemberColumns,
// pickerCaption, pickerClick), DOM last. Events go out through
// dauntlessEvent: ship-target/open|show/<family> and ship-target/close to
// the panel, and target/<ship>[/<subsystem>] to the target list.

(function () {
    "use strict";

    var PICKER_DOUBLE_CLICK_MS = 350;
    // Hardpoint Position2D is pixel space against a 128 x 128 frame; same
    // constant as ship_display.js (single named value, spec 9 q7 is open).
    var PICKER_FRAME_PX = 128;

    var _HTML_ESCAPES = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
    function escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return _HTML_ESCAPES[c];
        });
    }

    // 7 or 8 families -> 8 columns, anything else -> 6.
    function pickerFamilyColumns(n) { return (n === 7 || n === 8) ? 8 : 6; }

    function pickerMemberColumns(n) { return Math.min(Math.max(n, 1), 3); }

    function pickerCaption(state, hoverName) {
        return hoverName || state.open_family || state.locked || "";
    }

    function _family(state, name) {
        var fams = state.families || [];
        for (var i = 0; i < fams.length; i++) {
            if (fams[i].name === name) { return fams[i]; }
        }
        return null;
    }

    // Click rules, spec 4.3 / 4.5. Returns {events, last}; a double click
    // consumes `last` so a third quick click is a single click again.
    function pickerClick(state, kind, name, nowMs, last) {
        var ship = state.ship != null ? state.ship : state.ship_name;
        var base = "target/" + ship;
        var locked = state.locked || null;
        if (kind === "member") {
            return {events: [locked === name ? base : base + "/" + name],
                    last: last};
        }
        var fam = _family(state, name);
        var members = fam ? (fam.members || []) : [];
        var isDouble = !!(last && last.name === name && last.name != null &&
                          nowMs - last.t < PICKER_DOUBLE_CLICK_MS);
        var next = isDouble ? {name: null, t: 0} : {name: name, t: nowMs};
        if (isDouble) {
            if (members.length) {
                return {events: ["ship-target/show/" + name,
                                 base + "/" + members[0].name], last: next};
            }
            return {events: ["ship-target/close", base + "/" + name],
                    last: next};
        }
        if (fam && fam.lockable && members.length) {
            return {events: locked === name
                ? [base] : ["ship-target/show/" + name, base + "/" + name],
                last: next};
        }
        if (members.length === 1) {
            var m = members[0].name;
            return {events: locked === m
                ? [base] : ["ship-target/show/" + name, base + "/" + m],
                last: next};
        }
        if (members.length >= 2) {
            return {events: ["ship-target/open/" + name], last: next};
        }
        // A single subsystem: lock or unlock it, and close the open family,
        // whose member blocks the lock has just left (mockup v54).
        return {events: ["ship-target/close",
                         locked === name ? base : base + "/" + name],
                last: next};
    }

    function _holdsLock(fam, locked) {
        if (!locked) { return false; }
        if (fam.name === locked) { return true; }
        var ms = fam.members || [];
        for (var i = 0; i < ms.length; i++) {
            if (ms[i].name === locked) { return true; }
        }
        return false;
    }

    function _findLocked(state) {
        var locked = state.locked;
        if (!locked) { return null; }
        var fams = state.families || [];
        for (var i = 0; i < fams.length; i++) {
            if (fams[i].name === locked) { return fams[i]; }
            var ms = fams[i].members || [];
            for (var j = 0; j < ms.length; j++) {
                if (ms[j].name === locked) { return ms[j]; }
            }
        }
        return null;
    }

    function _pct(px) { return (px / PICKER_FRAME_PX * 100).toFixed(2) + "%"; }

    // Glyph for an icon key from the payload's `icons` table; a missing key
    // or table is an empty glyph.
    function _glyph(state, key) {
        var icons = state.icons || {};
        return icons[key] || "";
    }

    function _lockMarkerHtml(state) {
        var sub = _findLocked(state);
        if (!sub || (!sub.x_px && !sub.y_px)) { return ""; }
        return '<div class="lock-marker" data-state="' + escapeHtml(sub.state || "healthy") + '"'
            + ' style="left:' + _pct(sub.x_px) + ';top:' + _pct(sub.y_px) + '">'
            + '<span class="lock-marker__frame"></span>'
            + '<span class="lock-marker__icon">' + _glyph(state, sub.icon_key) + '</span></div>';
    }

    function _subsystemsHtml(state) {
        var fams = state.families || [];
        if (!fams.length) { return ""; }
        var html = '<div class="subsys-grid" style="--cols:' + pickerFamilyColumns(fams.length) + '">';
        var openFam = null;
        for (var i = 0; i < fams.length; i++) {
            var f = fams[i];
            var isOpen = !!(state.open_family && f.name === state.open_family
                            && (f.members || []).length);
            if (isOpen) { openFam = f; }
            html += '<button class="subsys-btn' + (isOpen ? ' subsys-btn--open' : '')
                + (_holdsLock(f, state.locked) ? ' subsys-btn--locked' : '') + '"'
                + ' data-btn="' + escapeHtml(f.name) + '"'
                + ' data-state="' + escapeHtml(f.state || "healthy") + '">'
                + '<span class="subsys-btn__icon">' + _glyph(state, f.icon_key) + '</span></button>';
        }
        html += '</div>';
        // The bar is always present (no layout shift), empty when idle.
        html += '<div class="subsys-caption">' + escapeHtml(pickerCaption(state, null)) + '</div>';
        if (openFam) {
            var ms = openFam.members;
            html += '<div class="subsys-blocks" style="--member-cols:' + pickerMemberColumns(ms.length) + '">';
            for (var j = 0; j < ms.length; j++) {
                html += '<div class="subsys-block'
                    + (state.locked === ms[j].name ? ' subsys-block--locked' : '') + '"'
                    + ' data-member="' + escapeHtml(ms[j].name) + '"'
                    + ' data-state="' + escapeHtml(ms[j].state || "healthy") + '">'
                    + '<span class="subsys-block__name">' + escapeHtml(ms[j].name) + '</span></div>';
            }
            html += '</div>';
        }
        return html;
    }

    function renderSubsystemPicker(root, state) {
        var host = root.querySelector('[data-bind="subsystems"]');
        var layer = root.querySelector('[data-bind="lock-layer"]');
        if (!host) { return; }
        var st = {};
        for (var k in state) { st[k] = state[k]; }
        st.ship = state.ship != null ? state.ship : state.ship_name;
        host._pickerState = st;
        // The panel is re-pushed nearly every frame (speed, range). Rebuild
        // only when a picker field changed, so hover and in-flight clicks
        // survive.
        var sig = JSON.stringify([st.ship, st.families, st.open_family, st.locked, st.icons]);
        if (sig !== host._pickerSig) {
            if (host._pickerShip !== st.ship) { host._pickerLast = {name: null, t: 0}; }
            host._pickerShip = st.ship;
            host._pickerSig = sig;
            host._pickerHover = null;
            host.innerHTML = _subsystemsHtml(st);
            if (layer) { layer.innerHTML = _lockMarkerHtml(st); }
        }

        if (host._pickerWired) { return; }
        host._pickerWired = true;
        host._pickerLast = {name: null, t: 0};
        host.addEventListener("click", function (e) {
            var cur = host._pickerState;
            if (!cur || !e.target || !e.target.closest) { return; }
            var el = e.target.closest("[data-btn]");
            var kind = "family", name;
            if (el) { name = el.getAttribute("data-btn"); }
            else {
                el = e.target.closest("[data-member]");
                if (!el) { return; }
                kind = "member";
                name = el.getAttribute("data-member");
            }
            var r = pickerClick(cur, kind, name, Date.now(), host._pickerLast);
            host._pickerLast = r.last;
            for (var i = 0; i < r.events.length; i++) { dauntlessEvent(r.events[i]); }
        });
        // The bar follows hover over family buttons only; updated in place.
        host.addEventListener("mouseover", function (e) {
            var cur = host._pickerState;
            if (!cur || !e.target || !e.target.closest) { return; }
            var b = e.target.closest("[data-btn]");
            var n = b ? b.getAttribute("data-btn") : null;
            if (n === host._pickerHover) { return; }
            host._pickerHover = n;
            var cap = host.querySelector(".subsys-caption");
            if (cap) { cap.textContent = pickerCaption(cur, n); }
        });
        host.addEventListener("mouseleave", function () {
            var cur = host._pickerState;
            host._pickerHover = null;
            var cap = host.querySelector(".subsys-caption");
            if (cap && cur) { cap.textContent = pickerCaption(cur, null); }
        });
    }

    window.pickerFamilyColumns = pickerFamilyColumns;
    window.pickerMemberColumns = pickerMemberColumns;
    window.pickerCaption = pickerCaption;
    window.pickerClick = pickerClick;
    window.renderSubsystemPicker = renderSubsystemPicker;
    window.PICKER_DOUBLE_CLICK_MS = PICKER_DOUBLE_CLICK_MS;
})();
