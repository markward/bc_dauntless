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

    renderSPVSubsystemList(data.subsystems || [],
                           (typeof data.selected_index === 'number')
                               ? data.selected_index : null);

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
    } else {
        pop.style.display = 'none';
        pop.innerHTML = '';
    }
};

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
         +   (chosen ? ' spv-sys-row--chosen' : '') + '"'
         +   ' onclick="shipPropertyViewerRow(' + row.index + ', ' + chosen + ')">'
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
        html += spvRowHtml(row, selectedIndex, false);
        if (row.expanded) {
            var kids = row.children || [];
            for (var j = 0; j < kids.length; j++) {
                html += spvRowHtml(kids[j] || {}, selectedIndex, true);
            }
        }
    }
    body.innerHTML = html;
}
