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
    return '<div class="be-row">'
        + '<label>' + ch + '</label>'
        + '<input type="range" min="0" max="1" step="0.01" value="' + v + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/material:' + ch + ':\' + this.value)">'
        + '<input type="number" min="0" max="1" step="0.01" value="' + v + '" style="width:56px"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/material:' + ch + ':\' + this.value)">'
        + '<span class="be-source">' + _beEsc(m.source) + '</span>'
        + (m.source === 'override'
            ? '<button onclick="dauntlessEvent(\'bridge-emitters/material-clear:' + ch + '\')">×</button>'
            : '')
        + '</div>';
}

function setBridgeEmitters(state) {
    const root = document.getElementById('bridge-emitters-root');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const body = document.getElementById('bridge-emitters-body');
    let html = '';
    if (!state.in_bridge) {
        html += '<div class="be-help">Switch to the bridge view to edit it.</div>';
    } else {
        html += '<div class="be-help">Hold right mouse to look · WASD move · Q/E down/up · '
              + 'Shift fast · Alt slow · Click to select · Alt+click: the surface behind</div>';
        html += '<div class="be-row"><label>Hover</label><span>'
              + _beEsc(state.hover || '—') + '</span></div>';
        const s = state.selected;
        if (!s) {
            html += '<div class="be-help">Nothing selected.</div>';
        } else {
            html += '<div class="cp-section-title">Selection</div>';
            html += '<div class="be-row"><label>Shape</label><span>' + _beEsc(s.name) + '</span></div>';
            html += '<div class="be-row"><label>Block</label><span>' + s.block + '</span></div>';
            html += '<div class="be-row"><label>Textures</label><span>'
                  + _beEsc((s.textures || []).join(', ') || '—') + '</span></div>';
            html += '<div class="be-chain">' + _beEsc((s.node_chain || []).join(' › ')) + '</div>';
            html += '<div class="cp-section-title">Material</div>';
            html += _beMaterialRow('roughness', s.material.roughness);
            html += _beMaterialRow('metalness', s.material.metalness);
        }
    }
    html += '<div class="be-status">' + _beEsc(state.status || '')
          + (state.dirty ? ' (unsaved)' : '') + '</div>';
    if (body) body.innerHTML = html;
    const save = document.getElementById('be-save');
    if (save) save.disabled = !state.can_save;
    const undo = document.getElementById('be-undo');
    if (undo) undo.disabled = !state.can_undo;
    root.style.display = 'block';
}
