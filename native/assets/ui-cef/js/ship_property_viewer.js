// Ship Property Viewer overlay. Global entry called from Python render_payload
// via cef_execute_javascript:
//   setShipPropertyViewer({visible: true, pin_count: N, selected: {...}|null});
//   setShipPropertyViewer({visible: false});
// Close button fires dauntlessEvent('ship-property-viewer/cancel') which
// routes through PanelRegistry to ShipPropertyViewerPanel.dispatch_event.
// Reuses the cp-* classes from css/configuration_panel.css and the
// ship_property_viewer.css overlay styles.
// Spec: docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md

function escapeHtmlSPV(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

window.setShipPropertyViewer = function (data) {
    var root = document.getElementById('spv-root');
    if (!root) return;
    if (!data || data.visible !== true) {
        root.style.display = 'none';
        // The panel can close (Cancel / mission swap / Task 5 Fix 2) while a
        // context menu / modal is still up; leaving that chrome's inline
        // display untouched means it reappears, already open, next time the
        // viewer opens. Force every overlay closed alongside the root.
        spvHideOverlaysNoEvent();
        var bar0 = document.getElementById('spv-savebar');
        if (bar0) bar0.style.display = 'none';
        return;
    }
    root.style.display = 'block';

    var count = document.getElementById('spv-pincount');
    if (count) {
        count.textContent = (data.pin_count || 0) + ' subsystems';
    }

    var glowBtn = document.getElementById('spv-toggle-glow');
    if (glowBtn) {
        glowBtn.classList.toggle('active', data.show_glow === true);
    }
    var arcsBtn = document.getElementById('spv-toggle-arcs');
    if (arcsBtn) {
        arcsBtn.classList.toggle('active', data.show_arcs === true);
    }
    // Hull-texture toggle: active = real hull textures, inactive = hologram
    // (the default).
    var hullBtn = document.getElementById('spv-toggle-hull');
    if (hullBtn) {
        hullBtn.classList.toggle('active', data.show_hull === true);
    }

    renderSPVSubsystemList(data.subsystems || [],
                           (typeof data.selected_index === 'number')
                               ? data.selected_index : null);

    // Save bar: surfaces the staged-edit count (data.pending_count); hidden
    // while nothing is pending.
    var bar = document.getElementById('spv-savebar');
    var n = data.pending_count || 0;
    var saveCount = document.getElementById('spv-savecount');
    if (saveCount) saveCount.textContent = n;
    if (bar) bar.style.display = n > 0 ? 'block' : 'none';

    // Keep the confirm modal's pending-edits list in sync with the panel
    // (populated into #spv-confirm-body when the Save bar opens it).
    spvPendingEdits = data.pending || [];

    // Server-driven ESC: the raw-GLFW modal-ESC router calls the panel's
    // handle_key_esc() independent of CEF focus, so the panel (not this JS)
    // owns "did ESC close an overlay or the whole panel" to avoid a race.
    // One-shot data.close_overlays === true means ESC just closed an
    // overlay — hide the overlay chrome WITHOUT re-firing overlay:0 (the
    // panel already cleared _overlay_open itself).
    if (data.close_overlays === true) {
        spvHideOverlaysNoEvent();
    }

    var pop = document.getElementById('spv-popover');
    if (!pop) return;
    if (data.selected) {
        var sel = data.selected;
        var p = sel.properties || {};
        var rows = Object.keys(p).map(function (k) {
            return '<div class="spv-row">'
                 +   '<span class="spv-k">' + escapeHtmlSPV(k) + '</span>'
                 +   '<span class="spv-v">' + escapeHtmlSPV(String(p[k])) + '</span>'
                 + '</div>';
        }).join('');
        pop.innerHTML = '<div class="spv-pop-title">' + escapeHtmlSPV(sel.name || '') + '</div>'
                      + rows;
        pop.style.display = 'block';
        // Capture the selected subsystem's radius so the context-menu modal
        // can pre-fill from it (the row payload itself carries no radius).
        if (p.radius !== undefined && typeof data.selected_index === 'number') {
            spvRowRadii[data.selected_index] = parseFloat(p.radius);
        }
    } else {
        pop.style.display = 'none';
        pop.innerHTML = '';
    }
};

// ── Context menu / radius modal / Save bar wiring (Task 5) ─────────────────
// Right-click a subsystem row -> context menu -> "Set Radius..." -> numeric
// modal -> Apply stages the edit via 'set_radius:<json>'. The Save bar opens
// an amend-confirm modal; confirming fires 'save'. All overlays notify the
// host via 'overlay:1'/'overlay:0' so 3D orbit-drag is suppressed while an
// overlay has mouse focus.
//
// ESC is deliberately NOT handled here. It's read raw (GLFW), independent of
// CEF focus, by host_loop's modal-ESC router, which calls the panel's
// handle_key_esc() — the single owner of "does ESC close the overlay or the
// panel" (a JS keydown listener racing that would double-handle the same
// key-press). The panel signals "ESC just closed an overlay" back to this
// JS one-shot via payload.close_overlays (see setShipPropertyViewer above).
var spvCtxIndex = null, spvCtxRadius = 0, spvRowRadii = {}, spvPendingEdits = [];

// Hide the overlay chrome without telling the host — used when the panel
// itself already knows the overlay closed (ESC via close_overlays, or the
// whole panel closing per Fix 2) so we don't double-fire overlay:0.
function spvHideOverlaysNoEvent() {
    ['spv-ctxmenu', 'spv-radius', 'spv-confirm'].forEach(function (id) {
        var el = document.getElementById(id); if (el) el.style.display = 'none';
    });
}
function spvHideOverlays() {
    spvHideOverlaysNoEvent();
    dauntlessEvent('ship-property-viewer/overlay:0');
}
document.addEventListener('click', function (e) {
    var menu = document.getElementById('spv-ctxmenu');
    if (menu && menu.style.display !== 'none' && !menu.contains(e.target)) {
        menu.style.display = 'none';
        if (document.getElementById('spv-radius').style.display === 'none'
            && document.getElementById('spv-confirm').style.display === 'none') {
            dauntlessEvent('ship-property-viewer/overlay:0');
        }
    }
});

window.shipPropertyViewerRowMenu = function (event, index) {
    event.preventDefault(); event.stopPropagation();
    spvCtxIndex = index;
    spvCtxRadius = (spvRowRadii[index] !== undefined) ? spvRowRadii[index] : 0;
    var menu = document.getElementById('spv-ctxmenu');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';
    dauntlessEvent('ship-property-viewer/overlay:1');
    return false;
};
window.shipPropertyViewerCtxRadius = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    var inp = document.getElementById('spv-radius-input');
    inp.value = spvCtxRadius;
    document.getElementById('spv-radius').style.display = 'flex';
    inp.focus(); inp.select();
};
window.shipPropertyViewerRadiusApply = function () {
    var v = parseFloat(document.getElementById('spv-radius-input').value);
    if (!isNaN(v) && v > 0) {
        dauntlessEvent('ship-property-viewer/set_radius:'
                       + JSON.stringify({i: spvCtxIndex, value: v}));
    }
    spvHideOverlays();
};
window.shipPropertyViewerRadiusCancel = function () { spvHideOverlays(); };
window.shipPropertyViewerSave = function () {
    // List the pending edits in the confirm modal (spec: "a confirmation
    // listing the pending edits"), e.g. "Center Impulse: -> 0.5".
    var body = document.getElementById('spv-confirm-body');
    if (body) {
        body.innerHTML = (spvPendingEdits || []).map(function (e) {
            return '<div class="spv-row">'
                 +   '<span class="spv-k">' + escapeHtmlSPV(e.name || '') + '</span>'
                 +   '<span class="spv-v">&#8594; ' + escapeHtmlSPV(String(e.value)) + '</span>'
                 + '</div>';
        }).join('');
    }
    document.getElementById('spv-confirm').style.display = 'flex';
    dauntlessEvent('ship-property-viewer/overlay:1');
};
window.shipPropertyViewerConfirmSave = function () {
    dauntlessEvent('ship-property-viewer/save'); spvHideOverlays();
};
window.shipPropertyViewerConfirmCancel = function () { spvHideOverlays(); };

// Close button → send 'cancel' to Python via the same console-log bridge
// that every other panel uses (defined in pause_menu.js):
//   dauntlessEvent('ship-property-viewer/cancel')
// C++ OnConsoleMessage strips the 'dauntless-event:' prefix and dispatches
// to PanelRegistry, which routes to ShipPropertyViewerPanel.dispatch_event.
window.shipPropertyViewerClose = function () {
    dauntlessEvent('ship-property-viewer/cancel');
};

// Tool-grid overlay toggles (Glow Regions / Weapon Arcs) → Python flips the
// flag and re-pushes the payload, which round-trips back here as
// data.show_glow / data.show_arcs so the .active button state always mirrors
// the panel's real state.
window.shipPropertyViewerToggle = function (action) {
    dauntlessEvent('ship-property-viewer/' + action);
};

// Subsystem-list row click: select that pin; clicking the already-selected
// row deselects (mirrors clicking empty space in the 3D view).
window.shipPropertyViewerRow = function (index, chosen) {
    dauntlessEvent('ship-property-viewer/' +
                   (chosen ? 'deselect' : ('select_pin:' + index)));
};

// Eye glyphs: open = targetable, shut = untargetable. Inline SVG so the
// colour follows the row's currentColor.
var SPV_EYE_OPEN =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none"'
  + ' stroke="currentColor" stroke-width="2" stroke-linejoin="round">'
  + '<path d="M2 12 C 5.5 6.5, 18.5 6.5, 22 12 C 18.5 17.5, 5.5 17.5, 2 12 Z"/>'
  + '<circle cx="12" cy="12" r="3"/></svg>';
var SPV_EYE_SHUT =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none"'
  + ' stroke="currentColor" stroke-width="2" stroke-linecap="round">'
  + '<path d="M2 12 C 5.5 17.5, 18.5 17.5, 22 12"/>'
  + '<path d="M6 15.5l-1.8 2.4M12 17v3M18 15.5l1.8 2.4"/></svg>';

// Accordion caret: expand/collapse a category row's children without
// selecting the category (the caret's onclick stops propagation).
window.shipPropertyViewerGroupToggle = function (index) {
    dauntlessEvent('ship-property-viewer/toggle_group:' + index);
};

// One list row (category or child). row.index is the pin-descriptor index.
function spvRowHtml(row, selectedIndex, isChild) {
    var chosen = (selectedIndex === row.index);
    var eye = row.targetable ? SPV_EYE_OPEN : SPV_EYE_SHUT;
    var eyeCls = row.targetable ? '' : ' spv-sys-row__eye--shut';
    var bar = (typeof row.condition_pct === 'number')
        ? '<span class="spv-sys-row__bar" style="--bar-pct:'
          + Math.max(0, Math.min(100, row.condition_pct)) + '%"></span>'
        : '';
    var hasChildren = (row.children || []).length > 0;
    var lead;
    if (hasChildren) {
        // Glyph swap (▾/▸), not CSS rotation — see target_list.js on CEF
        // layer promotion hurting text crispness.
        lead = '<span class="spv-sys-caret"'
             +   ' onclick="event.stopPropagation();'
             +   'shipPropertyViewerGroupToggle(' + row.index + ')">'
             +   (row.expanded ? '&#9662;' : '&#9656;') + '</span>';
    } else {
        lead = '<span class="spv-sys-caret spv-sys-caret--none"></span>';
    }
    return '<div class="spv-sys-row' + (isChild ? ' spv-sys-row--child' : '')
         +   (chosen ? ' spv-sys-row--chosen' : '')
         +   (row.dirty === true ? ' spv-sys-row--dirty' : '') + '"'
         +   ' onclick="shipPropertyViewerRow(' + row.index + ', ' + chosen + ')"'
         +   ' oncontextmenu="return shipPropertyViewerRowMenu(event, ' + row.index + ')">'
         +   lead
         +   '<span class="spv-sys-row__name">' + escapeHtmlSPV(row.name || '') + '</span>'
         +   bar
         +   '<span class="spv-sys-row__eye' + eyeCls + '"'
         +   ' title="' + (row.targetable ? 'Targetable' : 'Not targetable') + '">'
         +   eye + '</span>'
         + '</div>';
}

// Render the left-column subsystem list: category rows with their child
// pods/banks/tubes nested under them (collapsible, like the target list).
function renderSPVSubsystemList(rows, selectedIndex) {
    var body = document.getElementById('spv-syslist-body');
    if (!body) return;
    var html = '';
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i] || {};
        spvSeedRowRadius(row);
        html += spvRowHtml(row, selectedIndex, false);
        if (row.expanded) {
            var kids = row.children || [];
            for (var j = 0; j < kids.length; j++) {
                var kid = kids[j] || {};
                spvSeedRowRadius(kid);
                html += spvRowHtml(kid, selectedIndex, true);
            }
        }
    }
    body.innerHTML = html;
}

// Seed spvRowRadii from every row as it renders (not just the selected pin's
// popover), so a right-click context menu on a never-selected row pre-fills
// its real current radius instead of falling back to 0.
function spvSeedRowRadius(row) {
    if (row.radius != null) {
        spvRowRadii[row.index] = row.radius;
    }
}
