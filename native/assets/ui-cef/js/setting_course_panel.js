// Two-level Set Course menu render fn. Driven by Python:
//   setSettingCoursePanel({visible, selected_system, systems, warp_points});
//   setSettingCoursePanel({visible:false});
// System rows fire setting-course/select-system:<id>; warp rows fire
// setting-course/select-warp:<id>; OK/ESC fire setting-course/cancel.
// Reuses cp-* chrome; sc-* classes add the two-column layout.

function escapeHtmlSC(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _scRow(item, evt) {
    const cls = 'sc-row'
        + (item.active ? ' sc-row--active' : '')
        + (item.selected ? ' sc-row--selected' : '');
    return '<li class="' + cls + '" data-id="' + escapeHtmlSC(item.id) + '"'
        + ' onclick="dauntlessEvent(\'' + evt + ':\' + this.getAttribute(\'data-id\'))">'
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
        sysEl.innerHTML = (state.systems || []).map(function (s) {
            const sel = (s.id === state.selected_system);
            return _scRow({id: s.id, label: s.label, active: s.active,
                           selected: sel}, 'setting-course/select-system');
        }).join('');
    }
    const warpEl = document.getElementById('setting-course-warps');
    if (warpEl) {
        var note = state.warp_note
            ? '<li class="sc-note">' + escapeHtmlSC(state.warp_note) + '</li>'
            : '';
        warpEl.innerHTML = note + (state.warp_points || []).map(function (w) {
            return _scRow(w, 'setting-course/select-warp');
        }).join('');
    }
    var warpBtn = document.getElementById('setting-course-warp');
    if (warpBtn) {
        warpBtn.textContent = state.warp_label || 'Warp';
        warpBtn.disabled = (state.can_warp !== true);
    }
    root.style.display = 'flex';
}
