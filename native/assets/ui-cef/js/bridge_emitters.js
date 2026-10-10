// Bridge Editor dev panel (spec 2026-10-08-bridge-emitters §8).
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

function _beNumberRow(label, action, value, step) {
    return '<div class="be-row">'
        + '<label>' + _beEsc(label) + '</label>'
        + '<input type="number" step="' + (step || 0.01) + '" value="' + _beEsc(Number(value)) + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/' + action + ':\' + this.value)">'
        + '</div>';
}

// Glow (spec §12.1): on/off, source, scale. "emissive map" is disabled when
// the shape's material has no _emissive sibling (title= is a no-op in CEF
// OSR, so the reason is a visible line).
function _beGlowSection(s) {
    const g = s.glow;
    let html = '<div class="cp-section-title">Glow</div>'
        + '<div class="be-row"><label>glow</label><input type="checkbox"' + (g ? ' checked' : '')
        + ' onchange="dauntlessEvent(\'bridge-emitters/glow-\' + (this.checked ? \'on\' : \'off\'))"></div>';
    if (!g) return html;
    const opt = function (v, label, dis) {
        return '<option value="' + v + '"' + (g.src === v ? ' selected' : '')
            + (dis ? ' disabled' : '') + '>' + label + '</option>';
    };
    html += '<div class="be-row"><label>source</label>'
        + '<select onchange="dauntlessEvent(\'bridge-emitters/glow:src:\' + this.value)">'
        + opt('emissive', 'emissive map', !s.has_emissive_map)
        + opt('texture', 'own texture', false) + opt('flat', 'flat', false) + '</select></div>';
    if (!s.has_emissive_map)
        html += '<div class="be-help">No _emissive map beside this texture.</div>';
    html += _beNumberRow('scale', 'glow:scale', g.scale === undefined ? 1 : g.scale, 0.1);
    return html;
}

const _BE_STATES = ['green', 'yellow', 'red'];

function _beStateFields(tab, st) {
    const w = st.wave || {shape: 'steady'};
    const lv = Number(st.level);
    let html = '<div class="be-row"><canvas id="be-wheel" width="120" height="120"></canvas>'
        + '<div id="be-swatch" class="be-swatch"></div></div>'
        + '<div class="be-row"><label>level</label>'
        + '<input type="range" min="0" max="4" step="0.01" value="' + Math.min(lv, 4) + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/state:' + tab + ':level:\' + this.value)">'
        + '<input type="number" min="0" step="0.01" value="' + lv.toFixed(2) + '" style="width:56px"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/state:' + tab + ':level:\' + this.value)"></div>';
    const shp = function (v) {
        return '<option value="' + v + '"' + (w.shape === v ? ' selected' : '') + '>' + v + '</option>';
    };
    html += '<div class="be-row"><label>pulse</label>'
        + '<select onchange="dauntlessEvent(\'bridge-emitters/state:' + tab + ':wave:shape:\' + this.value)">'
        + shp('steady') + shp('sine') + shp('square') + '</select></div>';
    if (w.shape !== 'steady') {
        html += _beNumberRow('period s', 'state:' + tab + ':wave:period_s', w.period_s, 0.05);
        html += _beNumberRow('min', 'state:' + tab + ':wave:min', w.min || 0, 0.05);
    }
    if (w.shape === 'square') {
        html += _beNumberRow('duty', 'state:' + tab + ':wave:duty', w.duty === undefined ? 0.5 : w.duty, 0.05);
        html += _beNumberRow('soft', 'state:' + tab + ':wave:soft', w.soft || 0, 0.05);
    }
    return html;
}

// Profile (spec §12.1): dropdown + New/Rename, then Green|Yellow|Red tabs --
// the selected tab is also the alert the bridge previews (§12.2).
function _beProfileSection(state) {
    const s = state.selected;
    let html = '<div class="cp-section-title">Profile</div>'
        + '<div class="be-row"><label>profile</label>'
        + '<select onchange="dauntlessEvent(\'bridge-emitters/profile-select:\' + this.value)">'
        + '<option value=""' + (s.profile ? '' : ' selected') + '>none (steady white)</option>';
    (state.profiles || []).forEach(function (p) {
        html += '<option value="' + _beEsc(p.name) + '"' + (p.name === s.profile ? ' selected' : '')
            + '>' + _beEsc(p.name) + ' (' + p.used_by + ')</option>';
    });
    html += '</select></div><div class="be-row">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/profile-new\')">New</button>';
    if (s.profile) {
        html += '<input type="text" id="be-rename" value="' + _beEsc(s.profile) + '" style="width:120px">'
            + '<button onclick="dauntlessEvent(\'bridge-emitters/profile-rename:\' + '
            + 'document.getElementById(\'be-rename\').value)">Rename</button>';
    }
    html += '</div><div class="be-tabs">';
    _BE_STATES.forEach(function (t) {
        html += '<button class="be-tab' + (state.tab === t ? ' active' : '') + '"'
            + ' onclick="dauntlessEvent(\'bridge-emitters/tab:' + t + '\')">' + t + '</button>';
    });
    html += '<button onclick="dauntlessEvent(\'bridge-emitters/preview-toggle\')">'
        + (state.preview_playing ? 'Pause' : 'Play') + '</button></div>';
    const prof = s.profile_data;
    if (!prof) {
        html += '<div class="be-help">Previewing ' + _beEsc(state.tab)
            + '. Pick or create a profile to edit its states.</div>';
        return html;
    }
    const st = prof[state.tab];
    html += '<div class="be-row"><label>' + _beEsc(state.tab) + '</label><input type="checkbox"'
        + (st ? ' checked' : '')
        + ' onchange="dauntlessEvent(\'bridge-emitters/state-\' + (this.checked ? \'on\' : \'off\') + \':'
        + state.tab + '\')"><span>' + (st ? 'on' : 'off in this state') + '</span></div>';
    if (st) html += _beStateFields(state.tab, st);
    html += _beNumberRow('fade s', 'fade', prof.fade_s === undefined ? 0.5 : prof.fade_s, 0.05);
    html += _beNumberRow('phase', 'phase', s.phase || 0, 0.05);
    return html;
}

// The wheel is a canvas inside the rebuilt body: mount it after every
// rebuild. A drag commits once, on release (one undo step); the swatch
// follows live. `_beWheel.dragging` also blocks rebuilds (_beEditingInDock).
var _beWheel = null;
function _beMountWheel(state) {
    _beWheel = null;
    const canvas = document.getElementById('be-wheel');
    const s = state.selected;
    if (!canvas || !canvas.getContext || typeof ColourWheel === 'undefined' || !s
        || !s.profile_data || !s.profile_data[state.tab]) return;
    const tab = state.tab;
    const tint = s.profile_data[tab].tint;
    const swatch = document.getElementById('be-swatch');
    const paint = function (rgb) {
        if (swatch) swatch.style.background = 'rgb(' + rgb.map(function (c) {
            return Math.round(Math.max(0, Math.min(1, c)) * 255);
        }).join(',') + ')';
    };
    paint(tint);
    _beWheel = new ColourWheel(canvas, colourRgbToHs(tint), function (hs, final) {
        const rgb = colourHsToRgb(hs.hue, hs.sat);
        paint(rgb);
        if (final) dauntlessEvent('bridge-emitters/state:' + tab + ':tint:'
            + rgb.map(function (c) { return c.toFixed(4); }).join(','));
    });
}

// The body is rebuilt from the payload -- but never while the user is typing
// in a field inside the dock: every hover change sends a payload, and a
// rebuild destroys the focused field mid-edit. Range sliders and buttons
// don't count (nothing half-typed to lose).
function _beEditingInDock(root) {
    if (_beWheel && _beWheel.dragging) return true;
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
              + 'then reopen Bridge Editor.</div>';
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
            html += _beGlowSection(s);
            html += _beProfileSection(state);
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
    if (body && !_beEditingInDock(root)) {
        body.innerHTML = _beBodyHtml(state);
        _beMountWheel(state);
    }
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
