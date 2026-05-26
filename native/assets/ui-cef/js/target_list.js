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
    const selectedSub = state.selected_subsystem || null;

    let html = '';
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const name = String(row.name || '');
        const aff = String(row.affiliation || 'UNKNOWN');
        const chosen = (selected === name) ? ' target-list__row--chosen' : '';
        const hull = (typeof row.hull === 'number') ? row.hull : 100;
        const shields = (typeof row.shields === 'number') ? row.shields : 0;
        const safe = name.replace(/'/g, "\\'");

        // Ship row — caret, name, hull bar, shield bar.
        html += '<div class="target-list__row target-list__row--' + aff + chosen + '"'
              +   ' onclick="dauntlessEvent(\'target/' + safe + '\')">'
              +   '<span class="target-list__caret">&#9656;</span>'
              +   '<span class="target-list__name">' + name + '</span>'
              +   '<span class="target-list__bars">'
              +     '<span class="target-list__bar target-list__bar--hull"'
              +     ' style="--bar-pct:' + hull + '%"></span>'
              +     '<span class="target-list__bar target-list__bar--shields"'
              +     ' style="--bar-pct:' + shields + '%"></span>'
              +   '</span>'
              + '</div>';

        // Subsystem child rows — nested under the ship row.
        const subs = row.subsystems || [];
        for (let j = 0; j < subs.length; j++) {
            const sub = subs[j];
            const subName = String(sub.name || '');
            const subSafe = subName.replace(/'/g, "\\'");
            const subChosen = (selected === name && selectedSub === subName)
                ? ' target-list__sub--chosen' : '';
            html += '<div class="target-list__sub target-list__sub--' + aff + subChosen + '"'
                  +   ' onclick="dauntlessEvent(\'target/' + safe + '/' + subSafe + '\')">'
                  +   '<span class="target-list__sub-bullet">&#8226;</span>'
                  +   '<span class="target-list__sub-name">' + subName + '</span>'
                  + '</div>';
        }
    }
    body.innerHTML = html;
}
