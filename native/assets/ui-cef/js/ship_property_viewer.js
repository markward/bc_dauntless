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
var spvRowLight = {};   // index -> light_region spec (or true) for light rows
var spvLight = null;    // working spec while the modal is open

// Hide the overlay chrome without telling the host — used when the panel
// itself already knows the overlay closed (ESC via close_overlays, or the
// whole panel closing per Fix 2) so we don't double-fire overlay:0.
function spvHideOverlaysNoEvent() {
    ['spv-ctxmenu', 'spv-radius', 'spv-light', 'spv-confirm'].forEach(function (id) {
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
    var lightItem = document.getElementById('spv-ctx-light');
    if (lightItem) lightItem.style.display = spvRowLight[index] ? 'block' : 'none';
    var menu = document.getElementById('spv-ctxmenu');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';
    dauntlessEvent('ship-property-viewer/overlay:1');
    return false;
};
// Radius is edited with a mouse-only stepper: the engine has no keyboard->CEF
// forwarding, so a typed <input> can't receive characters. spvRadiusValue holds
// the working value (2 decimal places, clamped > 0); the buttons nudge it.
var spvRadiusValue = 0;

function spvRenderRadiusValue() {
    var el = document.getElementById('spv-radius-value');
    if (el) el.textContent = spvRadiusValue.toFixed(2);
}
window.shipPropertyViewerCtxRadius = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    var start = (spvCtxRadius > 0) ? spvCtxRadius : 0.25;   // fallback if unseeded
    spvRadiusValue = Math.round(start * 100) / 100;
    spvRenderRadiusValue();
    document.getElementById('spv-radius').style.display = 'flex';
};
window.shipPropertyViewerRadiusStep = function (delta) {
    spvRadiusValue = Math.max(0.01, Math.round((spvRadiusValue + delta) * 100) / 100);
    spvRenderRadiusValue();
};
window.shipPropertyViewerRadiusApply = function () {
    if (spvRadiusValue > 0) {
        dauntlessEvent('ship-property-viewer/set_radius:'
                       + JSON.stringify({i: spvCtxIndex, value: spvRadiusValue}));
    }
    spvHideOverlays();
};
window.shipPropertyViewerRadiusCancel = function () { spvHideOverlays(); };

// Light is edited with a mouse-only shape picker + steppers: same reasoning as
// the radius stepper above (no keyboard->CEF forwarding). light_region is
// baked-shaped (radius=[r], extent=[aft,fore], scale=[sx,sy,sz]); spvLight
// holds the flattened working copy while the modal is open.

// Default sizes when a field isn't pre-seeded from light_region.
function spvLightDefaults() {
    return {shape: 'Sphere', radius: 0.25, aft: 0.0, fore: 2.0,
            sx: 0.25, sy: 0.25, sz: 0.25};
}

window.shipPropertyViewerCtxLight = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    spvLight = spvLightDefaults();
    var seed = spvRowLight[spvCtxIndex];
    if (seed && typeof seed === 'object') {
        // light_region is baked-shaped: radius=[r], extent=[aft,fore], scale=[sx,sy,sz]
        spvLight.shape = seed.shape || 'Sphere';
        if (seed.radius && seed.radius.length) spvLight.radius = seed.radius[0];
        if (seed.extent && seed.extent.length === 2) {
            spvLight.aft = seed.extent[0]; spvLight.fore = seed.extent[1];
        }
        if (seed.scale && seed.scale.length === 3) {
            spvLight.sx = seed.scale[0]; spvLight.sy = seed.scale[1]; spvLight.sz = seed.scale[2];
        }
    }
    shipPropertyViewerLightShape(spvLight.shape);
    document.getElementById('spv-light').style.display = 'flex';
};

function spvStepperHtml(label, field, step) {
    return '<div class="spv-stepper">'
         +   '<span class="spv-stepper__label">' + label + '</span>'
         +   '<button class="spv-step-btn" onclick="shipPropertyViewerLightStep(\'' + field + '\',' + (-step) + ')">&minus;</button>'
         +   '<span class="spv-stepper__val" id="spv-lv-' + field + '">' + spvLight[field].toFixed(2) + '</span>'
         +   '<button class="spv-step-btn" onclick="shipPropertyViewerLightStep(\'' + field + '\',' + step + ')">+</button>'
         + '</div>';
}

window.shipPropertyViewerLightShape = function (shape) {
    spvLight.shape = shape;
    ['Sphere', 'Cylinder', 'Box'].forEach(function (s) {
        var b = document.getElementById('spv-shape-' + s);
        if (b) b.classList.toggle('active', s === shape);
    });
    var html = '';
    if (shape === 'Sphere') {
        html = spvStepperHtml('Radius', 'radius', 0.05);
    } else if (shape === 'Cylinder') {
        html = spvStepperHtml('Radius', 'radius', 0.05)
             + spvStepperHtml('Aft', 'aft', 0.25)
             + spvStepperHtml('Fore', 'fore', 0.25);
    } else {   // Box
        html = spvStepperHtml('Size X', 'sx', 0.05)
             + spvStepperHtml('Size Y', 'sy', 0.05)
             + spvStepperHtml('Size Z', 'sz', 0.05);
    }
    document.getElementById('spv-light-fields').innerHTML = html;
};

window.shipPropertyViewerLightStep = function (field, delta) {
    var floor = (field === 'aft') ? -100.0 : 0.01;   // aft may be <=0; others > 0
    spvLight[field] = Math.round((spvLight[field] + delta) * 100) / 100;
    if (spvLight[field] < floor) spvLight[field] = floor;
    var el = document.getElementById('spv-lv-' + field);
    if (el) el.textContent = spvLight[field].toFixed(2);
};

window.shipPropertyViewerLightApply = function () {
    var msg = {i: spvCtxIndex, shape: spvLight.shape};
    if (spvLight.shape === 'Sphere') {
        msg.radius = spvLight.radius;
    } else if (spvLight.shape === 'Cylinder') {
        msg.radius = spvLight.radius; msg.aft = spvLight.aft; msg.fore = spvLight.fore;
    } else {
        msg.sx = spvLight.sx; msg.sy = spvLight.sy; msg.sz = spvLight.sz;
    }
    dauntlessEvent('ship-property-viewer/set_light:' + JSON.stringify(msg));
    spvHideOverlays();
};

window.shipPropertyViewerLightCancel = function () { spvHideOverlays(); };

window.shipPropertyViewerSave = function () {
    // List the modified subsystems in the confirm modal, each with a tally of
    // its staged changes in brackets, e.g. "Center Impulse (1)".
    var body = document.getElementById('spv-confirm-body');
    if (body) {
        body.innerHTML = (spvPendingEdits || []).map(function (e) {
            return '<div class="spv-row">'
                 +   '<span class="spv-k">' + escapeHtmlSPV(e.name || '') + '</span>'
                 +   '<span class="spv-v">(' + (e.count || 0) + ')</span>'
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
    if (row.light === true) spvRowLight[row.index] = row.light_region || true;
    else delete spvRowLight[row.index];
}
