// Configuration panel render fn. Driven by Python via
// cef_execute_javascript:
//   setConfigurationPanel({visible:true, tabs, selected_tab, focused, settings});
//   setConfigurationPanel({visible:false});
// Click events fire dauntlessEvent('configuration/<verb>:<arg>').
// Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md.

function escapeHtmlCP(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Master toggles: one row over several renderer effects. Mirrors
// MASTER_TOGGLES in configuration_panel.py; the two orderings are pinned
// together by test_js_graphics_focusables_match_python.
const CP_MASTERS = [
    ['improved_space',     'Improved Space Visuals'],
    ['camera_realism',     'Camera Realism'],
    ['realistic_lighting', 'Realistic Lighting'],
];

// Graphics-tab controls in rendered order: the standalone rows, then the
// masters. Single source for both the focusable list and the rendered rows.
const CP_GRAPHICS_STANDALONE = ['smaa', 'fov'];
const CP_GRAPHICS_CTRLS =
    CP_GRAPHICS_STANDALONE.concat(CP_MASTERS.map(m => m[0]));

// One On/Off settings row. `key` names both the setting (`<key>_on`) and the
// action (`toggle:<key>`), so a row cannot read one control and toggle another.
function _cpToggleRow(label, key, on, isFoc) {
    return '<div class="cp-row' + (isFoc(key) ? ' cp-focused' : '') + '">'
         +   '<div class="cp-row__label">' + escapeHtmlCP(label) + '</div>'
         +   '<div class="cp-row__control">'
         +     '<button class="cp-toggle' + (on ? ' cp-toggle--on' : '') + '"'
         +        ' onclick="dauntlessEvent(\'configuration/toggle:' + key + '\')">'
         +       (on ? 'On' : 'Off')
         +     '</button>'
         +   '</div>'
         + '</div>';
}

function _cpFocusableList(state) {
    // Mirror ConfigurationPanel._focusables on the Python side: tabs
    // first, then per-tab controls. Only Graphics ships in this pass.
    const out = state.tabs.map(t => ({kind: 'tab', target: t.id}));
    if (state.selected_tab === 'graphics') {
        CP_GRAPHICS_CTRLS.forEach(t => out.push({kind: 'ctrl', target: t}));
    } else if (state.selected_tab === 'gameplay') {
        out.push({kind: 'ctrl', target: 'subtitles'});
        out.push({kind: 'ctrl', target: 'disable_annoying_dialogue'});
        out.push({kind: 'ctrl', target: 'ai_difficulty'});
    } else if (state.selected_tab === 'controls') {
        (state.controls || []).forEach(c => out.push({kind: 'rebind', target: c.id}));
        out.push({kind: 'ctrl', target: 'controls_reset'});
    }
    return out;
}

function _cpRenderTabstrip(state, focusables) {
    let html = '';
    for (let i = 0; i < state.tabs.length; ++i) {
        const t = state.tabs[i];
        const isActive = t.id === state.selected_tab;
        const isFocused = focusables[state.focused]
            && focusables[state.focused].kind === 'tab'
            && focusables[state.focused].target === t.id;
        const cls = 'cp-tab'
                  + (isActive ? ' cp-tab--active' : '')
                  + (isFocused ? ' cp-focused' : '');
        html += '<div class="' + cls + '"'
              +   ' onclick="dauntlessEvent(\'configuration/tab:' + t.id + '\')">'
              +     escapeHtmlCP(t.label)
              + '</div>';
    }
    return html;
}

function _cpRenderGraphicsBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    let html = '';

    html += _cpToggleRow('Anti-Aliasing (SMAA)', 'smaa', s.smaa_on, isFoc);

    // FOV slider — listen on 'change' (released), not 'input' (every
    // pixel), so dragging doesn't flood the CEF event channel.
    html += '<div class="cp-row' + (isFoc('fov') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Exterior Camera FOV</div>'
          +   '<div class="cp-row__control">'
          +     '<input class="cp-slider" type="range" min="25" max="55" step="5"'
          +        ' value="' + s.fov_deg + '"'
          +        ' onchange="dauntlessEvent(\'configuration/fov:\' + this.value)">'
          +     '<span class="cp-slider-value">' + s.fov_deg + '°</span>'
          +   '</div>'
          + '</div>';

    // ── Modern VFX group ─────────────────────────────────────────────
    html += '<hr class="cp-divider">';
    html += '<div class="cp-group-header">Modern VFX</div>';

    // Master toggles, in CP_MASTERS order. Each drives several renderer
    // effects; see MASTER_TOGGLES in configuration_panel.py for the members.
    CP_MASTERS.forEach(function (m) {
        html += _cpToggleRow(m[1], m[0], s[m[0] + '_on'], isFoc);
    });

    return html;
}

function _cpRenderGameplayBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    let html = '';

    // Subtitles toggle
    html += '<div class="cp-row' + (isFoc('subtitles') ? ' cp-focused' : '') + '">'
          +     '<span class="cp-label">Subtitles</span>'
          +     '<button class="cp-toggle' + (s.subtitles_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:subtitles\')">'
          +       (s.subtitles_on ? 'On' : 'Off')
          +     '</button>'
          + '</div>';

    // Disable Annoying Dialogue toggle
    html += '<div class="cp-row' + (isFoc('disable_annoying_dialogue') ? ' cp-focused' : '') + '">'
          +     '<span class="cp-label">Disable Annoying Dialogue</span>'
          +     '<button class="cp-toggle' + (s.disable_annoying_dialogue_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:disable_annoying_dialogue\')">'
          +       (s.disable_annoying_dialogue_on ? 'On' : 'Off')
          +     '</button>'
          + '</div>';

    // AI Difficulty — three-way segmented control (Easy / Medium / Hard).
    // Clicking a segment sends configuration/ai_difficulty:<index>.
    const aiLabels = ['Easy', 'Medium', 'Hard'];
    const ai = (typeof s.ai_difficulty === 'number') ? s.ai_difficulty : 1;
    html += '<div class="cp-row' + (isFoc('ai_difficulty') ? ' cp-focused' : '') + '">'
          +     '<span class="cp-label">AI Difficulty</span>'
          +     '<div class="cp-segmented">';
    for (let i = 0; i < aiLabels.length; ++i) {
        html += '<button class="cp-toggle' + (ai === i ? ' cp-toggle--on' : '') + '"'
              +    ' onclick="dauntlessEvent(\'configuration/ai_difficulty:' + i + '\')">'
              +    aiLabels[i]
              + '</button>';
    }
    html += '</div></div>';
    return html;
}

// Controls tab — one rebind row per action, grouped by category, plus a
// Reset to Defaults row. The key button fires configuration/rebind:<action>,
// which puts Python into capture; the host loop then scans for the pressed key
// and sends configuration/bind:<action>:<KEY>.
function _cpRenderControlsBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isRebindFoc = (id) => focused.kind === 'rebind' && focused.target === id;
    const rows = state.controls || [];
    let html = '';
    let lastCat = null;
    for (let i = 0; i < rows.length; ++i) {
        const c = rows[i];
        if (c.category !== lastCat) {
            if (lastCat !== null) html += '<hr class="cp-divider">';
            html += '<div class="cp-group-header">' + escapeHtmlCP(c.category) + '</div>';
            lastCat = c.category;
        }
        const capturing = state.capturing_action === c.id;
        const keyTxt = capturing ? '…' : (c.key || '—');
        html += '<div class="cp-row' + (isRebindFoc(c.id) ? ' cp-focused' : '') + '">'
              +     '<span class="cp-label">' + escapeHtmlCP(c.label) + '</span>'
              +     '<button class="cp-toggle cp-row__key' + (capturing ? ' cp-toggle--on' : '') + '"'
              +        ' onclick="dauntlessEvent(\'configuration/rebind:' + c.id + '\')">'
              +       escapeHtmlCP(keyTxt)
              +     '</button>'
              + '</div>';
    }
    const isResetFoc = focused.kind === 'ctrl' && focused.target === 'controls_reset';
    html += '<hr class="cp-divider">';
    html += '<div class="cp-row' + (isResetFoc ? ' cp-focused' : '') + '">'
          +     '<span class="cp-label">Reset to Defaults</span>'
          +     '<button class="cp-toggle"'
          +        ' onclick="dauntlessEvent(\'configuration/controls_reset\')">Reset</button>'
          + '</div>';
    return html;
}

// "Press a key…" capture overlay, created/removed on demand so we don't have to
// reserve a slot in hello.html. Shown whenever Python is mid-capture.
function _cpUpdateCaptureOverlay(state) {
    const root = document.getElementById('configuration-panel');
    if (!root) return;
    let ov = document.getElementById('cp-capture-overlay');
    if (!state || !state.capturing_action) {
        if (ov) ov.remove();
        return;
    }
    if (!ov) {
        ov = document.createElement('div');
        ov.id = 'cp-capture-overlay';
        ov.className = 'cp-capture-modal';
        root.appendChild(ov);
    }
    ov.innerHTML =
        '<div class="cp-capture-box">'
      +   '<div class="cp-capture-title">Press a key for '
      +       escapeHtmlCP(state.capturing_label || '') + '</div>'
      +   '<div class="cp-capture-hint">Esc to cancel</div>'
      +   (state.controls_message
            ? '<div class="cp-capture-msg">' + escapeHtmlCP(state.controls_message) + '</div>'
            : '')
      + '</div>';
}

function setConfigurationPanel(state) {
    const root = document.getElementById('configuration-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        _cpUpdateCaptureOverlay(null);
        root.style.display = 'none';
        return;
    }
    const focusables = _cpFocusableList(state);
    const tabstrip = document.getElementById('cp-tabstrip');
    if (tabstrip) tabstrip.innerHTML = _cpRenderTabstrip(state, focusables);
    const body = document.getElementById('cp-body');
    if (body) {
        if (state.selected_tab === 'graphics') {
            body.innerHTML = _cpRenderGraphicsBody(state, focusables);
        } else if (state.selected_tab === 'gameplay') {
            body.innerHTML = _cpRenderGameplayBody(state, focusables);
        } else if (state.selected_tab === 'controls') {
            body.innerHTML = _cpRenderControlsBody(state, focusables);
        } else {
            body.innerHTML = '';
        }
    }
    _cpUpdateCaptureOverlay(state);
    root.style.display = 'flex';
}
