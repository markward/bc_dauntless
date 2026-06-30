// Developer Options panel render fn. Driven by Python via
// cef_execute_javascript:
//   setDeveloperOptions({visible:true, tabs, selected_tab, focused, settings});
//   setDeveloperOptions({visible:false});
// Click events fire dauntlessEvent('developer-options/<verb>:<arg>').
// Reuses the cp-* classes from css/configuration_panel.css so the look
// matches the configuration panel.
// Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md.

function escapeHtmlDO(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _doFocusableList(state) {
    const out = state.tabs.map(t => ({kind: 'tab', target: t.id}));
    if (state.selected_tab === 'combat') {
        out.push({kind: 'ctrl', target: 'god_mode'});
        out.push({kind: 'ctrl', target: 'double_weapons'});
        out.push({kind: 'ctrl', target: 'no_npc_shields'});
        out.push({kind: 'ctrl', target: 'disable_collisions'});
    } else if (state.selected_tab === 'rendering') {
        out.push({kind: 'ctrl', target: 'pbr'});
        out.push({kind: 'ctrl', target: 'pbr_metalness'});
        out.push({kind: 'ctrl', target: 'pbr_roughness_bias'});
        out.push({kind: 'ctrl', target: 'pbr_reflection'});
        out.push({kind: 'ctrl', target: 'pbr_normal_strength'});
    }
    return out;
}

function _doRenderTabstrip(state, focusables) {
    let html = '';
    for (let i = 0; i < state.tabs.length; ++i) {
        const t = state.tabs[i];
        const isActive = t.id === state.selected_tab;
        const f = focusables[state.focused];
        const isFocused = f && f.kind === 'tab' && f.target === t.id;
        const cls = 'cp-tab'
                  + (isActive ? ' cp-tab--active' : '')
                  + (isFocused ? ' cp-focused' : '');
        html += '<div class="' + cls + '"'
              +   ' onclick="dauntlessEvent(\'developer-options/tab:' + t.id + '\')">'
              +     escapeHtmlDO(t.label)
              + '</div>';
    }
    return html;
}

function _doToggleRow(label, key, on, focused) {
    return '<div class="cp-row' + (focused ? ' cp-focused' : '') + '">'
         +   '<div class="cp-row__label">' + escapeHtmlDO(label) + '</div>'
         +   '<div class="cp-row__control">'
         +     '<button class="cp-toggle' + (on ? ' cp-toggle--on' : '') + '"'
         +        ' onclick="dauntlessEvent(\'developer-options/toggle:' + key + '\')">'
         +       (on ? 'On' : 'Off')
         +     '</button>'
         +   '</div>'
         + '</div>';
}

function _doRenderCombatBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    let html = '';
    html += _doToggleRow('God Mode', 'god_mode', s.god_mode, isFoc('god_mode'));
    html += _doToggleRow('2× Player Weapon Strength', 'double_weapons',
                         s.double_weapons, isFoc('double_weapons'));
    html += _doToggleRow('Disable NPC Shields', 'no_npc_shields',
                         s.no_npc_shields, isFoc('no_npc_shields'));
    html += _doToggleRow('Disable Collisions', 'disable_collisions',
                         s.disable_collisions, isFoc('disable_collisions'));
    return html;
}

// Slider row matching the configuration panel's FOV control. `onchange`
// (released), not `oninput`, so dragging doesn't flood the event channel.
function _doSliderRow(label, key, value, min, max, step, fmt, focused) {
    return '<div class="cp-row' + (focused ? ' cp-focused' : '') + '">'
         +   '<div class="cp-row__label">' + escapeHtmlDO(label) + '</div>'
         +   '<div class="cp-row__control">'
         +     '<input class="cp-slider" type="range"'
         +        ' min="' + min + '" max="' + max + '" step="' + step + '"'
         +        ' value="' + value + '"'
         +        ' onchange="dauntlessEvent(\'developer-options/' + key + ':\' + this.value)">'
         +     '<span class="cp-slider-value">' + fmt(value) + '</span>'
         +   '</div>'
         + '</div>';
}

function _doRenderRenderingBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    const pct = (v) => Math.round(v * 100) + '%';
    const num = (v) => Number(v).toFixed(2);
    let html = '';
    html += _doToggleRow('PBR Shading (Cook-Torrance)', 'pbr',
                         s.pbr_enabled, isFoc('pbr'));
    html += _doSliderRow('Metalness', 'pbr_metalness', s.pbr_metalness,
                         0, 1, 0.05, pct, isFoc('pbr_metalness'));
    html += _doSliderRow('Roughness Bias', 'pbr_roughness_bias', s.pbr_roughness_bias,
                         -0.5, 1, 0.05, num, isFoc('pbr_roughness_bias'));
    html += _doSliderRow('Reflection Intensity', 'pbr_reflection', s.pbr_reflection,
                         0, 4, 0.1, num, isFoc('pbr_reflection'));
    html += _doSliderRow('Normal Strength', 'pbr_normal_strength', s.pbr_normal_strength,
                         0, 4, 0.1, num, isFoc('pbr_normal_strength'));
    return html;
}

function setDeveloperOptions(state) {
    const root = document.getElementById('developer-options-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const focusables = _doFocusableList(state);
    const tabstrip = document.getElementById('do-tabstrip');
    if (tabstrip) tabstrip.innerHTML = _doRenderTabstrip(state, focusables);
    const body = document.getElementById('do-body');
    if (body) {
        body.innerHTML = (state.selected_tab === 'combat')
            ? _doRenderCombatBody(state, focusables)
            : (state.selected_tab === 'rendering')
            ? _doRenderRenderingBody(state, focusables)
            : '';
    }
    root.style.display = 'flex';
}
