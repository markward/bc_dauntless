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
