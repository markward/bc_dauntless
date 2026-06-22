// Two-level Set Course menu render fn. Driven by Python:
//   setSettingCoursePanel({visible, selected_system, systems, warp_points, warp_note});
//   setSettingCoursePanel({visible:false});
// System rows fire setting-course/select-system:<id>. Clicking a warp-point
// row SETS THE COURSE via setting-course/set-course:<id> and closes the popup;
// the player then engages the warp from the SDK Helm "Warp" button. Cancel/ESC
// fire setting-course/cancel. Rows with available:false are shown greyed and
// are not clickable. Reuses cp-* chrome; sc-* classes add the two-column layout.

function escapeHtmlSC(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _scRow(item, evt) {
    const available = (item.available !== false);
    const cls = 'sc-row'
        + (item.active ? ' sc-row--active' : '')
        + (available ? '' : ' sc-row--disabled');
    const click = available
        ? ' onclick="dauntlessEvent(\'' + evt + ':\' + this.getAttribute(\'data-id\'))"'
        : '';
    return '<li class="' + cls + '" data-id="' + escapeHtmlSC(item.id) + '"' + click + '>'
        + escapeHtmlSC(item.label) + '</li>';
}

function setSettingCoursePanel(state) {
    const root = document.getElementById('setting-course-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const sysEl = document.getElementById('setting-course-systems');
    if (sysEl) {
        // System rows are always selectable (they reveal warp points).
        sysEl.innerHTML = (state.systems || []).map(function (s) {
            return _scRow({id: s.id, label: s.label, active: s.active,
                           available: true}, 'setting-course/select-system');
        }).join('');
    }
    const warpEl = document.getElementById('setting-course-warps');
    if (warpEl) {
        var note = state.warp_note
            ? '<li class="sc-note">' + escapeHtmlSC(state.warp_note) + '</li>'
            : '';
        warpEl.innerHTML = note + (state.warp_points || []).map(function (w) {
            return _scRow(w, 'setting-course/set-course');
        }).join('');
    }
    root.style.display = 'flex';
}
