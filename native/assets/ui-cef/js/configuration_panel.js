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

function _cpFocusableList(state) {
    // Mirror ConfigurationPanel._focusables on the Python side: tabs
    // first, then per-tab controls. Only Graphics ships in this pass.
    const out = state.tabs.map(t => ({kind: 'tab', target: t.id}));
    if (state.selected_tab === 'graphics') {
        out.push({kind: 'ctrl', target: 'dust'});
        out.push({kind: 'ctrl', target: 'specular'});
        out.push({kind: 'ctrl', target: 'fov'});
        out.push({kind: 'ctrl', target: 'hdr'});
        out.push({kind: 'ctrl', target: 'rim'});
        out.push({kind: 'ctrl', target: 'decals'});
        out.push({kind: 'ctrl', target: 'hull_damage'});
        out.push({kind: 'ctrl', target: 'fxaa'});
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

    // Space Dust toggle
    html += '<div class="cp-row' + (isFoc('dust') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Space Dust</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.dust_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:dust\')">'
          +       (s.dust_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Specular Highlights toggle
    html += '<div class="cp-row' + (isFoc('specular') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Specular Highlights</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.specular_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:specular\')">'
          +       (s.specular_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // FOV slider — listen on 'change' (released), not 'input' (every
    // pixel), so dragging doesn't flood the CEF event channel.
    html += '<div class="cp-row' + (isFoc('fov') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Exterior Camera FOV</div>'
          +   '<div class="cp-row__control">'
          +     '<input class="cp-slider" type="range" min="40" max="80" step="5"'
          +        ' value="' + s.fov_deg + '"'
          +        ' onchange="dauntlessEvent(\'configuration/fov:\' + this.value)">'
          +     '<span class="cp-slider-value">' + s.fov_deg + '°</span>'
          +   '</div>'
          + '</div>';

    // ── Modern VFX group ─────────────────────────────────────────────
    html += '<hr class="cp-divider">';
    html += '<div class="cp-group-header">Modern VFX</div>';

    // HDR toggle
    html += '<div class="cp-row' + (isFoc('hdr') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">HDR</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.hdr_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:hdr\')">'
          +       (s.hdr_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Fresnel Rim Light toggle
    html += '<div class="cp-row' + (isFoc('rim') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Fresnel Rim Light</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.rim_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:rim\')">'
          +       (s.rim_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Damage Decals toggle (persistent hull scorch + heat-glow)
    html += '<div class="cp-row' + (isFoc('decals') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Damage Decals</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.decals_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:decals\')">'
          +       (s.decals_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Hull breaches toggle (carve emission + shader clip)
    html += '<div class="cp-row' + (isFoc('hull_damage') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Hull breaches</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.hull_damage_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:hull_damage\')">'
          +       (s.hull_damage_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // FXAA toggle (post-process anti-aliasing)
    html += '<div class="cp-row' + (isFoc('fxaa') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">FXAA</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.fxaa_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:fxaa\')">'
          +       (s.fxaa_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    return html;
}

function setConfigurationPanel(state) {
    const root = document.getElementById('configuration-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
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
        } else {
            body.innerHTML = '';  // future tabs slot in here
        }
    }
    root.style.display = 'flex';
}
