// Bridge Emitters dev panel (spec 2026-10-08-bridge-emitters §8).
// Python pushes setBridgeEmitters(state); actions go back through
// dauntlessEvent('bridge-emitters/<action>'). Sliders commit on `change`.

function _beEsc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
}

function _beMaterialRow(ch, m) {
    const v = Number(m.value).toFixed(2);
    // A map (baked texture) always wins over any stored per-shape override
    // (spec 2026-10-09-bridge-pbr global constraints: map -> override ->
    // default), so the slider/number field are shown but disabled -- the
    // value they display is the DEFAULT, never a stale override.
    const dis = m.source === 'map' ? ' disabled' : '';
    return '<div class="be-row">'
        + '<label>' + ch + '</label>'
        + '<input type="range" min="0" max="1" step="0.01" value="' + v + '"' + dis
        + ' onchange="dauntlessEvent(\'bridge-emitters/material:' + ch + ':\' + this.value)">'
        + '<input type="number" min="0" max="1" step="0.01" value="' + v + '" style="width:56px"' + dis
        + ' onchange="dauntlessEvent(\'bridge-emitters/material:' + ch + ':\' + this.value)">'
        + '<span class="be-source">' + _beEsc(m.source) + '</span>'
        + (m.source === 'override'
            ? '<button onclick="dauntlessEvent(\'bridge-emitters/material-clear:' + ch + '\')">×</button>'
            : '')
        + '</div>';
}

function _beLightNumberRow(label, field, value) {
    return '<div class="be-row">'
        + '<label>' + _beEsc(label) + '</label>'
        + '<input type="number" step="0.1" value="' + _beEsc(Number(value)) + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/light:' + field + ':\' + this.value)">'
        + '</div>';
}

// The Light section: no emitter.light yet -> a single "Add light" button
// (placed at the last pick's hit point, aimed along its normal); once one
// exists -> Place/Aim/Remove plus the four number fields. Sliders aren't
// used here (no natural 0-1 range), unlike the material rows.
function _beLightSection(light) {
    let html = '<div class="cp-section-title">Light</div>';
    if (!light) {
        html += '<div class="be-row">'
              + '<button onclick="dauntlessEvent(\'bridge-emitters/light-add\')">Add light</button>'
              + '</div>';
        return html;
    }
    html += '<div class="be-row">'
          + '<button onclick="dauntlessEvent(\'bridge-emitters/light-place\')">Place here</button>'
          + '<button onclick="dauntlessEvent(\'bridge-emitters/light-aim\')">Aim where I\'m looking</button>'
          + '<button onclick="dauntlessEvent(\'bridge-emitters/light-remove\')">Remove</button>'
          + '</div>';
    // "half-angle": inner_deg/outer_deg are HALF-angles (cone axis to edge,
    // 0-90), not full cone-apex angles -- CEF OSR shows no native tooltips
    // (title= is a no-op), so the label spells it out instead.
    html += _beLightNumberRow('inner half-angle°', 'inner_deg', light.inner_deg);
    html += _beLightNumberRow('outer half-angle°', 'outer_deg', light.outer_deg);
    html += _beLightNumberRow('range', 'range', light.range);
    html += _beLightNumberRow('intensity', 'intensity', light.intensity);
    return html;
}

// The body is rebuilt from the payload -- but never while the user is typing
// in a field inside the dock: every hover change sends a payload, and a
// rebuild destroys the focused field mid-edit. Range sliders and buttons
// don't count (nothing half-typed to lose).
function _beEditingInDock(root) {
    const a = document.activeElement;
    if (!a || !root.contains || !root.contains(a)) return false;
    if (a.tagName === 'TEXTAREA' || a.isContentEditable) return true;
    return a.tagName === 'INPUT' && a.type !== 'range' && a.type !== 'checkbox'
        && a.type !== 'button';
}

function _beBodyHtml(state) {
    let html = '';
    if (!state.in_bridge) {
        html += '<div class="be-help">Close this, press Space to go to the bridge, '
              + 'then reopen Bridge Emitters.</div>';
    } else {
        html += '<div class="be-help">Hold right mouse to look · WASD move · Q/E down/up · '
              + 'Shift fast · Alt slow · Click to select · Alt+click: the surface behind</div>';
        // Hover text is filled by textContent (see setBridgeEmitters).
        html += '<div class="be-row"><label>Hover</label><span id="be-hover"></span></div>';
        const s = state.selected;
        if (!s) {
            html += '<div class="be-help">Nothing selected.</div>';
        } else {
            html += '<div class="cp-section-title">Selection</div>';
            html += '<div class="be-row"><label>Shape</label><span>'
                  + _beEsc(s.display_name || s.name) + '</span></div>';
            html += '<div class="be-row"><label>Block</label><span>' + _beEsc(s.block) + '</span></div>';
            html += '<div class="be-row"><label>Textures</label><span>'
                  + _beEsc((s.textures || []).join(', ') || '—') + '</span></div>';
            html += '<div class="be-chain">' + _beEsc((s.node_chain || []).join(' › ')) + '</div>';
            html += '<div class="cp-section-title">Material</div>';
            html += _beMaterialRow('roughness', s.material.roughness);
            html += _beMaterialRow('metalness', s.material.metalness);
            html += _beLightSection(s.light);
        }
    }
    html += '<div class="be-status" id="be-status"></div>';
    return html;
}

function setBridgeEmitters(state) {
    const root = document.getElementById('bridge-emitters-root');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const body = document.getElementById('bridge-emitters-body');
    if (body && !_beEditingInDock(root)) body.innerHTML = _beBodyHtml(state);
    const hover = document.getElementById('be-hover');
    if (hover) hover.textContent = state.hover || '—';
    const status = document.getElementById('be-status');
    if (status) status.textContent = (state.status || '') + (state.dirty ? ' (unsaved)' : '');
    const save = document.getElementById('be-save');
    if (save) save.disabled = !state.can_save;
    const undo = document.getElementById('be-undo');
    if (undo) undo.disabled = !state.can_undo;
    root.style.display = 'block';
}
