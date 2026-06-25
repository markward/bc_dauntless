// Quick Battle Setup panel render fn. Driven by Python via
// cef_execute_javascript:
//   setQuickBattleSetup({open:true, selected_tab, tabs});
//   setQuickBattleSetup({open:false});
// Click events fire dauntlessEvent('quick-battle-setup/<verb>[:<arg>]').
// Reuses the cp-* classes from css/configuration_panel.css so the look
// matches the configuration panel. T1 = shell only (Ships tab placeholder).

function escapeHtmlQBS(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _qbsRenderTabstrip(state) {
    let html = '';
    for (let i = 0; i < state.tabs.length; ++i) {
        const t = state.tabs[i];
        const isActive = t.id === state.selected_tab;
        const cls = 'cp-tab' + (isActive ? ' cp-tab--active' : '');
        html += '<div class="' + cls + '"'
              +   ' onclick="dauntlessEvent(\'quick-battle-setup/tab:' + t.id + '\')">'
              +     escapeHtmlQBS(t.label)
              + '</div>';
    }
    return html;
}

function _qbsRenderBody(state) {
    // T1: placeholder only. The ship accordion / friend-enemy lists land in
    // a later task.
    if (state.selected_tab === 'ships') {
        return '<div class="qbs-placeholder">(ships)</div>';
    }
    return '';
}

function setQuickBattleSetup(state) {
    const root = document.getElementById('quick-battle-setup');
    if (!root) return;
    if (!state || state.open !== true) {
        root.style.display = 'none';
        return;
    }
    const tabstrip = document.getElementById('qbs-tabstrip');
    if (tabstrip) tabstrip.innerHTML = _qbsRenderTabstrip(state);
    const body = document.getElementById('qbs-body');
    if (body) body.innerHTML = _qbsRenderBody(state);
    root.style.display = 'flex';
}
