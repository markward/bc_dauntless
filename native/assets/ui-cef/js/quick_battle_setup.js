// Quick Battle Setup panel render fn. Driven by Python via
// cef_execute_javascript:
//   setQuickBattleSetup({open:true, categories, friendly, enemy, player_ship});
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

// Ship-category accordion — mirrors the crew-menu row/caret/depth pattern.
// `action` is the per-ship dauntlessEvent verb ('click-ship' for the enemy
// catalog, 'select-player-ship' for the player ship); `highlightKey` is the
// per-ship flag that draws the row as highlighted ('selected' / 'current').
function _qbsRenderCategories(categories, action, highlightKey) {
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
                + (ship[highlightKey] ? ' qbs-row--selected' : '');
            const onclick = disabled ? ''
                : ' onclick="dauntlessEvent(\'quick-battle-setup/' + action + ':' + ship.id + '\')"';
            html += '<div class="' + cls + '" data-depth="2"' + onclick + '>'
                  +   '<span class="qbs-label">' + escapeHtmlQBS(ship.label) + '</span>'
                  + '</div>';
        }
    }
    return html;
}

// Friendly / Enemy roster list — stacked "shopping-basket" rows. Each group is
// {label, count}; controls drive roster-inc/dec/remove with side + label.
// kind is 'friendly' | 'enemy' (the SDK side and the affiliation tint class).
// At count 1 the [−] slot is rendered as [×] (decrement removes the stack).
function _qbsRenderRoster(items, kind) {
    const list = items || [];
    if (!list.length) return '<div class="qbs-empty">(none)</div>';
    let html = '';
    for (const it of list) {
        // encodeURIComponent leaves "'" literal, which would terminate the
        // single-quoted JS string inside the onclick attribute (breaking every
        // button for apostrophe names like "Vor'cha"); encode it as %27 too,
        // which Python's unquote decodes back.
        const arg = kind + ':' + encodeURIComponent(it.label).replace(/'/g, '%27');
        const decGlyph = it.count <= 1 ? '×' : '−';   // × at 1, − otherwise
        html += '<div class="qbs-roster-row qbs-roster-row--' + kind + '">'
              +   '<span class="qbs-roster-label">' + escapeHtmlQBS(it.label) + '</span>'
              +   '<span class="qbs-qty">'
              +     '<button class="qbs-qty-btn"'
              +       ' onclick="dauntlessEvent(\'quick-battle-setup/roster-dec:' + arg + '\')">'
              +       decGlyph + '</button>'
              +     '<span class="qbs-qty-count">' + it.count + '</span>'
              +     '<button class="qbs-qty-btn"'
              +       ' onclick="dauntlessEvent(\'quick-battle-setup/roster-inc:' + arg + '\')">'
              +       '+</button>'
              +     '<button class="qbs-qty-btn qbs-qty-remove"'
              +       ' onclick="dauntlessEvent(\'quick-battle-setup/roster-remove:' + arg + '\')">'
              +       '×</button>'
              +   '</span>'
              + '</div>';
    }
    return html;
}

function _qbsRenderBody(state) {
    const player = state.player_ship
        ? escapeHtmlQBS(state.player_ship) : '(none)';
    return '<div class="qbs-lists">'
         +   '<div class="qbs-col qbs-catalog">'
         +     '<div class="qbs-scroll">'
         +       _qbsRenderCategories(state.categories, 'click-ship', 'selected')
         +     '</div>'
         +     '<div class="qbs-actions">'
         +       '<button class="cp-done-button"'
         +         ' onclick="dauntlessEvent(\'quick-battle-setup/add-friend\')">Add As Friendly</button>'
         +       '<button class="cp-done-button"'
         +         ' onclick="dauntlessEvent(\'quick-battle-setup/add-enemy\')">Add As Enemy</button>'
         +       '<button class="cp-done-button"'
         +         ' onclick="dauntlessEvent(\'quick-battle-setup/set-player\')">Set As Player Ship</button>'
         +     '</div>'
         +   '</div>'
         +   '<div class="qbs-col qbs-rosters">'
         +     '<div class="qbs-scroll">'
         +       '<div class="qbs-roster-title">Player Ship</div>'
         +       '<div class="qbs-player-ship">' + player + '</div>'
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
    const body = document.getElementById('qbs-body');
    if (body) body.innerHTML = _qbsRenderBody(state);
    // Start is disabled until at least one ship sits on a roster.
    const startBtn = document.getElementById('qbs-start-button');
    if (startBtn) startBtn.disabled = state.can_start !== true;
    root.style.display = 'flex';
}
