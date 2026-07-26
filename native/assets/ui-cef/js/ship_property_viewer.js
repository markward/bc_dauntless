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
        (typeof data.selected_index === 'number') ? data.selected_index : null,
        (typeof data.selected_light_index === 'number') ? data.selected_light_index : null);

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

// A light-volume node's working seed lives on the row (row.light_region), keyed
// by its parent subsystem index (row.light_of). Track the right-clicked node so
// the context menu knows which items to show.
var spvCtxKind = 'subsystem';       // 'subsystem' | 'light'
var spvCtxLightOf = null;           // parent subsystem index for a light node

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

// Light node row click: select this light (or deselect if already selected).
window.shipPropertyViewerLightRow = function (lightOf, chosen) {
    dauntlessEvent('ship-property-viewer/' +
                   (chosen ? 'deselect' : ('select_light:' + lightOf)));
};

// Right-click a subsystem row: Set Radius always; Add Light Volume only when the
// subsystem has no light yet.
window.shipPropertyViewerRowMenu = function (event, index, hasLight) {
    event.preventDefault(); event.stopPropagation();
    spvCtxKind = 'subsystem'; spvCtxIndex = index; spvCtxLightOf = null;
    spvCtxRadius = (spvRowRadii[index] !== undefined) ? spvRowRadii[index] : 0;
    spvShowMenuItems({radius: true, addlight: !hasLight, light: false, removelight: false});
    spvOpenMenuAt(event);
    return false;
};

// Right-click a light node: Edit + Remove.
window.shipPropertyViewerLightMenu = function (event, lightOf) {
    event.preventDefault(); event.stopPropagation();
    spvCtxKind = 'light'; spvCtxLightOf = lightOf; spvCtxIndex = lightOf;
    spvShowMenuItems({radius: false, addlight: false, light: true, removelight: true});
    spvOpenMenuAt(event);
    return false;
};

function spvShowMenuItems(show) {
    var map = {radius: 'spv-ctx-radius', addlight: 'spv-ctx-addlight',
               light: 'spv-ctx-light', removelight: 'spv-ctx-removelight'};
    Object.keys(map).forEach(function (k) {
        var el = document.getElementById(map[k]);
        if (el) el.style.display = show[k] ? 'block' : 'none';
    });
}
function spvOpenMenuAt(event) {
    var menu = document.getElementById('spv-ctxmenu');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';
    dauntlessEvent('ship-property-viewer/overlay:1');
}

// Add Light Volume (subsystem context) → stage a default, then Python selects it.
window.shipPropertyViewerCtxAddLight = function () {
    dauntlessEvent('ship-property-viewer/add_light:' + spvCtxIndex);
    spvHideOverlays();
};
// Remove Light Volume (light-node context).
window.shipPropertyViewerCtxRemoveLight = function () {
    dauntlessEvent('ship-property-viewer/remove_light:' + spvCtxLightOf);
    spvHideOverlays();
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

function spvSeedRow(row) {
    if (row.kind === 'light') {
        if (row.light_region) spvRowLight[row.light_of] = row.light_region;
        return;
    }
    if (row.radius != null) spvRowRadii[row.index] = row.radius;
    // subsystem row no longer carries light_region; Add uses light_of default
    // captured from its own light child if present (seeded above).
}

// Recursive render: a row, then (if expanded) its children at any depth.
function spvRenderRows(rows, out, selectedIndex, selectedLight, depth) {
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i] || {};
        spvSeedRow(row);
        out.push(spvRowHtml(row, selectedIndex, selectedLight, depth));
        if (row.expanded && (row.children || []).length) {
            spvRenderRows(row.children, out, selectedIndex, selectedLight, depth + 1);
        }
    }
}

// Render the left-column subsystem list: category rows with their child
// pods/banks/tubes/light-volume nodes nested under them (collapsible, like
// the target list), recursing to any depth.
function renderSPVSubsystemList(rows, selectedIndex, selectedLight) {
    var body = document.getElementById('spv-syslist-body');
    if (!body) return;
    var out = [];
    spvRenderRows(rows, out, selectedIndex, selectedLight, 0);
    body.innerHTML = out.join('');
}

function spvRowHtml(row, selectedIndex, selectedLight, depth) {
    var isLight = (row.kind === 'light');
    var chosen = isLight ? (selectedLight === row.light_of)
                         : (selectedIndex === row.index);
    var hasChildren = (row.children || []).length > 0;
    var lead;
    if (hasChildren) {
        // Glyph swap (▾/▸), not CSS rotation — see target_list.js on CEF
        // layer promotion hurting text crispness.
        lead = '<span class="spv-sys-caret" onclick="event.stopPropagation();'
             + 'shipPropertyViewerGroupToggle(' + row.index + ')">'
             + (row.expanded ? '&#9662;' : '&#9656;') + '</span>';
    } else {
        lead = '<span class="spv-sys-caret spv-sys-caret--none"></span>';
    }
    var clickJs = isLight
        ? ('shipPropertyViewerLightRow(' + row.light_of + ', ' + chosen + ')')
        : ('shipPropertyViewerRow(' + row.index + ', ' + chosen + ')');
    var menuJs = isLight
        ? ('return shipPropertyViewerLightMenu(event, ' + row.light_of + ')')
        : ('return shipPropertyViewerRowMenu(event, ' + row.index + ', '
           + (row.has_light === true) + ')');
    var extra = isLight ? ' spv-sys-row--light' : '';
    var indent = ' style="padding-left:' + (10 + depth * 14) + 'px"';
    var body = '<span class="spv-sys-row__name">' + escapeHtmlSPV(row.name || '') + '</span>';
    if (!isLight) {
        var eye = row.targetable ? SPV_EYE_OPEN : SPV_EYE_SHUT;
        var eyeCls = row.targetable ? '' : ' spv-sys-row__eye--shut';
        var bar = (typeof row.condition_pct === 'number')
            ? '<span class="spv-sys-row__bar" style="--bar-pct:'
              + Math.max(0, Math.min(100, row.condition_pct)) + '%"></span>' : '';
        body += bar + '<span class="spv-sys-row__eye' + eyeCls + '">' + eye + '</span>';
    }
    return '<div class="spv-sys-row' + (depth > 0 ? ' spv-sys-row--child' : '')
         + (chosen ? ' spv-sys-row--chosen' : '')
         + (row.dirty === true ? ' spv-sys-row--dirty' : '') + extra + '"' + indent
         + ' onclick="' + clickJs + '"'
         + ' oncontextmenu="' + menuJs + '">'
         + lead + body + '</div>';
}
