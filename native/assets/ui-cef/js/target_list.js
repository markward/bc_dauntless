// native/assets/ui-cef/js/target_list.js
//
// Target-list render fn. Driven by Python via cef_execute_javascript:
//   setTargetList({visible: true, selected: "USS X", rows: [{name, affiliation}, ...]});
//
// Click on a row emits `dauntlessEvent('target/<ship name>')`; the
// PanelRegistry routes it to TargetListView.dispatch_event(ship name).
// Spec: docs/ui_designs/02-tactical-cluster.md

function setTargetList(state) {
    const panel = document.getElementById('target-list-panel');
    if (!panel) return;
    if (!state || !state.visible) {
        panel.classList.add('target-list--hidden');
        return;
    }
    panel.classList.remove('target-list--hidden');

    const body = document.getElementById('target-list-body');
    if (!body) return;

    const rows = state.rows || [];
    const selected = state.selected || null;

    let html = '';
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const name = String(row.name || '');
        const aff = String(row.affiliation || 'UNKNOWN');
        const chosen = (selected === name) ? ' target-list__row--chosen' : '';
        const safe = name.replace(/'/g, "\\'");
        html += '<div class="target-list__row target-list__row--' + aff + chosen + '"'
              +   ' onclick="dauntlessEvent(\'target/' + safe + '\')">'
              +   '<span class="target-list__caret">&#9656;</span>'
              +   '<span class="target-list__name">' + name + '</span>'
              + '</div>';
    }
    body.innerHTML = html;
}
