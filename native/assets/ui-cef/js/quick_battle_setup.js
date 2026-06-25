// Quick Battle Setup panel render fn. Driven by Python via
// cef_execute_javascript:
//   setQuickBattleSetup({open:true, selected_tab, tabs, categories,
//                        friendly, enemy});
//   setQuickBattleSetup({open:false});
// Click events fire dauntlessEvent('quick-battle-setup/<verb>[:<arg>]').
// Reuses the cp-* chrome (css/configuration_panel.css) and the crew-menu
// accordion + target-list roster tints so the look matches the rest of the UI.

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

// Ship-category accordion — mirrors the crew-menu row/caret/depth pattern.
function _qbsRenderCategories(categories) {
    const cats = categories || [];
    if (!cats.length) return '<div class="qbs-placeholder">(no ships)</div>';
    let html = '';
    for (const cat of cats) {
        const open = cat.expanded === true;
        html += '<div class="qbs-row" data-depth="1"'
              +   ' onclick="dauntlessEvent(\'quick-battle-setup/expand:' + cat.id + '\')">'
              +   '<span class="qbs-caret">' + (open ? '▾' : '▸') + '</span>'
              +   '<span class="qbs-label">' + escapeHtmlQBS(cat.label) + '</span>'
              + '</div>';
        if (!open) continue;
        for (const ship of (cat.ships || [])) {
            const disabled = ship.enabled === false;
            const cls = 'qbs-row qbs-row--leaf'
                + (disabled ? ' disabled' : '')
                + (ship.selected ? ' qbs-row--selected' : '');
            const onclick = disabled ? ''
                : ' onclick="dauntlessEvent(\'quick-battle-setup/click-ship:' + ship.id + '\')"';
            html += '<div class="' + cls + '" data-depth="2"' + onclick + '>'
                  +   '<span class="qbs-label">' + escapeHtmlQBS(ship.label) + '</span>'
                  + '</div>';
        }
    }
    return html;
}

// Friendly / Enemy roster list — target-list affiliation tint via the kind class.
function _qbsRenderRoster(items, kind) {
    const list = items || [];
    if (!list.length) return '<div class="qbs-empty">(none)</div>';
    let html = '';
    for (const it of list) {
        html += '<div class="qbs-roster-row qbs-roster-row--' + kind + '">'
              +   escapeHtmlQBS(it.label)
              + '</div>';
    }
    return html;
}

function _qbsRenderBody(state) {
    if (state.selected_tab !== 'ships') return '';
    return '<div class="qbs-lists">'
         +   '<div class="qbs-col qbs-catalog">'
         +     '<div class="qbs-scroll">' + _qbsRenderCategories(state.categories) + '</div>'
         +     '<div class="qbs-actions">'
         +       '<button class="cp-done-button"'
         +         ' onclick="dauntlessEvent(\'quick-battle-setup/add-friend\')">Add As Friendly</button>'
         +       '<button class="cp-done-button"'
         +         ' onclick="dauntlessEvent(\'quick-battle-setup/add-enemy\')">Add As Enemy</button>'
         +     '</div>'
         +   '</div>'
         +   '<div class="qbs-col qbs-rosters">'
         +     '<div class="qbs-scroll">'
         +       '<div class="qbs-roster-title">Friendly Ships</div>'
         +       '<div class="qbs-roster">' + _qbsRenderRoster(state.friendly, 'friendly') + '</div>'
         +       '<div class="qbs-roster-title">Enemy Ships</div>'
         +       '<div class="qbs-roster">' + _qbsRenderRoster(state.enemy, 'enemy') + '</div>'
         +     '</div>'
         +   '</div>'
         + '</div>';
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
