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
        out.push({kind: 'ctrl', target: 'procedural_sky'});
        out.push({kind: 'ctrl', target: 'hdr'});
        out.push({kind: 'ctrl', target: 'rim'});
        out.push({kind: 'ctrl', target: 'shadows'});
        out.push({kind: 'ctrl', target: 'decals'});
        out.push({kind: 'ctrl', target: 'smaa'});
        out.push({kind: 'ctrl', target: 'filmic'});
        out.push({kind: 'ctrl', target: 'motion_blur'});
        out.push({kind: 'ctrl', target: 'warp_flythrough'});
        out.push({kind: 'ctrl', target: 'volumetric_nebulae'});
        out.push({kind: 'ctrl', target: 'nebula_lightning'});
        out.push({kind: 'ctrl', target: 'hdr_lens_flare'});
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
          +     '<input class="cp-slider" type="range" min="25" max="55" step="5"'
          +        ' value="' + s.fov_deg + '"'
          +        ' onchange="dauntlessEvent(\'configuration/fov:\' + this.value)">'
          +     '<span class="cp-slider-value">' + s.fov_deg + '°</span>'
          +   '</div>'
          + '</div>';

    // ── Modern VFX group ─────────────────────────────────────────────
    html += '<hr class="cp-divider">';
    html += '<div class="cp-group-header">Modern VFX</div>';

    // Procedural Sky toggle — On = map-driven galaxy sky; Off = original
    // STBC authored starbox (stock BC).
    html += '<div class="cp-row' + (isFoc('procedural_sky') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Procedural Sky</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.procedural_sky_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:procedural_sky\')">'
          +       (s.procedural_sky_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

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

    // Dynamic Shadows toggle
    html += '<div class="cp-row' + (isFoc('shadows') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Dynamic Shadows</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.shadows_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:shadows\')">'
          +       (s.shadows_on ? 'On' : 'Off')
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

    // SMAA toggle (post-process anti-aliasing)
    html += '<div class="cp-row' + (isFoc('smaa') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Anti-Aliasing (SMAA)</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.smaa_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:smaa\')">'
          +       (s.smaa_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Filmic Filter toggle — grain + vignette + chromatic aberration on the
    // exterior view (Modern VFX).
    html += '<div class="cp-row' + (isFoc('filmic') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Filmic Filter</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.filmic_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:filmic\')">'
          +       (s.filmic_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Motion Blur toggle — camera motion blur on the exterior view (Modern VFX).
    html += '<div class="cp-row' + (isFoc('motion_blur') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Motion Blur</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.motion_blur_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:motion_blur\')">'
          +       (s.motion_blur_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Warp Flythrough toggle — procedural warp flythrough VFX (Modern VFX).
    html += '<div class="cp-row' + (isFoc('warp_flythrough') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Warp Flythrough</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.warp_flythrough_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:warp_flythrough\')">'
          +       (s.warp_flythrough_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Volumetric Nebulae toggle — volumetric nebula render pass (Modern VFX).
    html += '<div class="cp-row' + (isFoc('volumetric_nebulae') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Volumetric Nebulae</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.volumetric_nebulae_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:volumetric_nebulae\')">'
          +       (s.volumetric_nebulae_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Nebula Lightning toggle — lightning render pass (Modern VFX).
    html += '<div class="cp-row' + (isFoc('nebula_lightning') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Nebula Lightning</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.nebula_lightning_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:nebula_lightning\')">'
          +       (s.nebula_lightning_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Modern Lens Flares toggle — image-based screen-space lens flare (Modern
    // VFX). When on, the classic per-sun billboard flares are suppressed.
    html += '<div class="cp-row' + (isFoc('hdr_lens_flare') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Modern Lens Flares</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.hdr_lens_flare_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:hdr_lens_flare\')">'
          +       (s.hdr_lens_flare_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

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
