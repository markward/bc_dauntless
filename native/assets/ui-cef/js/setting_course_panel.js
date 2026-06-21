// Setting Course panel render fn. Driven by Python via cef_execute_javascript:
//   setSettingCoursePanel({visible:true, title, message, destinations});
//   setSettingCoursePanel({visible:false});
// The OK button and ESC fire dauntlessEvent('setting-course/cancel').
// Reuses the cp-* classes from css/configuration_panel.css.
// Spec: docs/superpowers/specs/2026-06-21-set-course-button-popup-design.md.

function escapeHtmlSC(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function setSettingCoursePanel(state) {
    const root = document.getElementById('setting-course-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const header = document.getElementById('setting-course-header');
    if (header) header.textContent = state.title || 'Set Course';
    const body = document.getElementById('setting-course-body');
    if (body) {
        const dests = state.destinations || [];
        if (dests.length === 0) {
            // Placeholder: just the message.
            body.innerHTML = '<div class="cp-row__label">'
                + escapeHtmlSC(state.message || '') + '</div>';
        } else {
            // Future: render a clickable destination list. Each row fires
            // dauntlessEvent('setting-course/select:<id>'). The id is carried
            // in a data attribute and read back (decoded) at click time, so a
            // quote in the id can never break the onclick string.
            let html = '';
            for (let i = 0; i < dests.length; ++i) {
                const d = dests[i];
                html += '<div class="cp-row" data-dest-id="'
                      + escapeHtmlSC(d.id) + '"'
                      + ' onclick="dauntlessEvent(\'setting-course/select:\''
                      + ' + this.getAttribute(\'data-dest-id\'))">'
                      + '<div class="cp-row__label">'
                      + escapeHtmlSC(d.label) + '</div></div>';
            }
            body.innerHTML = html;
        }
    }
    root.style.display = 'flex';
}
