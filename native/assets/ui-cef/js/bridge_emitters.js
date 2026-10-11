// Bridge Editor dev page (spec 2026-10-08-bridge-emitters §8, §13.3).
// Python pushes setBridgeEmitters(state); actions go back through
// dauntlessEvent('bridge-emitters/<action>'). The top-left bar is always
// shown while the editor is open (its presence IS editing mode); the dock
// shows only with a selection, as Object / Material tabs of collapsible
// stack entries. No <select> anywhere: CEF OSR draws no native popup.

function _beEsc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
}

// A value placed inside a single-quoted JS string in an onclick attribute:
// JS-escape first, then HTML-escape (the attribute decodes &#39; back to ').
function _beJs(s) {
    return _beEsc(String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

function _beChip(label, action, active, disabled) {
    return '<button class="be-chip' + (active ? ' active' : '') + '"'
        + ' onclick="dauntlessEvent(\'bridge-emitters/' + action + '\')"'
        + (disabled ? ' disabled' : '') + '>' + _beEsc(label) + '</button>';
}

function _beNumberRow(label, action, value, step) {
    return '<div class="be-row">'
        + '<label>' + _beEsc(label) + '</label>'
        + '<input type="number" step="' + (step || 0.01) + '" value="' + _beEsc(Number(value)) + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/' + action + ':\' + this.value)">'
        + '</div>';
}

const _BE_STATES = [['offline', '⬛'], ['green', '🟩'], ['yellow', '🟨'], ['red', '🟥'],
                    ['special', '🟦']];

function _beBar(state) {
    let html = '<span class="be-title">BRIDGE EDITOR</span><span class="be-sep">|</span>';
    _BE_STATES.forEach(function (p) {
        html += '<button class="be-state ' + p[0] + (state.state === p[0] ? ' active' : '') + '"'
            + ' onclick="dauntlessEvent(\'bridge-emitters/state:' + p[0] + '\')">' + p[1] + '</button>';
    });
    html += '<span class="be-sep">|</span>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/preview-toggle\')">'
        + (state.playing ? '⏸' : '▶') + '</button><span class="be-sep">|</span>'
        + '<button' + (state.can_undo ? '' : ' disabled')
        + ' onclick="dauntlessEvent(\'bridge-emitters/undo\')">Undo</button>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/revert\')">Revert</button>'
        + '<button' + (state.can_save ? '' : ' disabled')
        + ' onclick="dauntlessEvent(\'bridge-emitters/save\')">Save' + (state.dirty ? '*' : '')
        + '</button><span class="be-sep">|</span>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/close\')">✕</button>';
    return html;
}

// One stack entry: a header row (expand toggle, title, optional scope
// squares, optional ×) and, when expanded, its fields.
function _beEntry(id, title, expanded, scope, removeAction, fields) {
    let html = '<div class="be-entry"><div class="be-entry-head">'
        + '<button class="be-caret" onclick="dauntlessEvent(\'bridge-emitters/expand:' + id + '\')">'
        + (expanded ? '▾' : '▸') + '</button><span class="be-entry-title">' + _beEsc(title) + '</span>';
    if (scope) {
        _BE_STATES.forEach(function (p) {
            html += '<button class="be-scope ' + p[0] + (scope.list.indexOf(p[0]) >= 0 ? ' on' : '') + '"'
                + ' onclick="dauntlessEvent(\'bridge-emitters/' + scope.action + p[0] + '\')">'
                + p[1] + '</button>';
        });
    }
    if (removeAction)
        html += '<button onclick="dauntlessEvent(\'bridge-emitters/' + removeAction + '\')">×</button>';
    html += '</div>';
    if (expanded) html += '<div class="be-entry-body">' + fields + '</div>';
    return html + '</div>';
}

function _beUsers(n) {
    return 'used by ' + n + (n === 1 ? ' object' : ' objects');
}

// Each TGA is a material (Mark 2026-10-11): with no link an object uses its
// texture's material, so "unlink" is the chip naming that material.
function _beLibrary(s) {
    const unlinked = s.texture_material ? 'texture · ' + s.texture_material : 'none';
    let html = '<div class="be-list">' + _beChip(unlinked, 'material-link:', !s.linked, false);
    (s.library || []).forEach(function (m) {
        html += '<button class="be-chip' + (s.linked && m.name === s.material ? ' active' : '') + '"'
            + ' onclick="dauntlessEvent(\'bridge-emitters/material-link:' + _beJs(m.name) + '\')">'
            + _beEsc(m.name + (m.texture ? ' (texture)' : '') + ' — ' + _beUsers(m.used_by))
            + '</button>';
    });
    html += '</div><div class="be-row">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/material-new\')">New</button>';
    if (s.material || s.texture_material)
        html += '<button onclick="dauntlessEvent(\'bridge-emitters/material-duplicate\')">Duplicate</button>';
    return html + '</div>';
}

function _beObjectTab(s) {
    const open = function (id) { return (s.expanded || []).indexOf(id) >= 0; };
    const title = s.linked ? s.material
        : (s.texture_material ? s.texture_material + ' (texture)' : 'none');
    let html = _beEntry('material', 'Material: ' + title, true, null, null, _beLibrary(s));
    if (!s.material && s.has_emission_map) {
        const stem = String((s.textures || [''])[0]).replace(/\.[^.]*$/, '');
        html += '<div class="be-help">Emission map · ' + _beEsc(stem) + '_emissive · steady</div>';
    }
    (s.lights || []).forEach(function (l, i) {
        const fields = '<div class="be-row">'
            + '<button onclick="dauntlessEvent(\'bridge-emitters/light-place:' + i + '\')">Place here</button>'
            + '<button onclick="dauntlessEvent(\'bridge-emitters/light-aim:' + i + '\')">Aim where I\'m looking</button>'
            + '</div>'
            // HALF-angles from the axis; CEF OSR shows no tooltips, so say so.
            + _beNumberRow('inner half-angle°', 'light:' + i + ':inner_deg', l.inner_deg, 0.1)
            + _beNumberRow('outer half-angle°', 'light:' + i + ':outer_deg', l.outer_deg, 0.1)
            + _beNumberRow('range', 'light:' + i + ':range', l.range, 0.1)
            + _beNumberRow('intensity', 'light:' + i + ':intensity', l.intensity, 1);
        html += _beEntry('light:' + i, 'Light ' + (i + 1), open('light:' + i), null,
                         'light-remove:' + i, fields);
    });
    html += '<div class="be-row"><button onclick="dauntlessEvent(\'bridge-emitters/light-add\')">'
        + 'Add light</button></div>';
    return html;
}

function _beFinishRow(ch, f) {
    const v = Number(f.value).toFixed(2);
    const dis = f.source === 'map' ? ' disabled' : '';
    return '<div class="be-row"><label>' + ch + '</label>'
        + '<input type="range" min="0" max="1" step="0.01" value="' + v + '"' + dis
        + ' onchange="dauntlessEvent(\'bridge-emitters/finish:' + ch + ':\' + this.value)">'
        + '<input type="number" min="0" max="1" step="0.01" value="' + v + '" style="width:56px"' + dis
        + ' onchange="dauntlessEvent(\'bridge-emitters/finish:' + ch + ':\' + this.value)">'
        + '<span class="be-source">' + _beEsc(f.source) + '</span>'
        + (f.source === 'material'
            ? '<button onclick="dauntlessEvent(\'bridge-emitters/finish-clear:' + ch + '\')">×</button>'
            : '')
        + '</div>';
}

const _BE_WITHOUT_MAP = [['texture', 'own texture'], ['flat', 'flat colour']];

function _beModifier(m, i, expanded) {
    let fields = '';
    if (m.type === 'emitter') {
        const lv = Number(m.level);
        fields = '<div class="be-row"><canvas id="be-wheel-' + i + '" width="120" height="120"></canvas>'
            + '<div id="be-swatch-' + i + '" class="be-swatch"></div></div>'
            + '<div class="be-row"><label>level</label>'
            + '<input type="range" min="0" max="4" step="0.01" value="' + Math.min(lv, 4) + '"'
            + ' onchange="dauntlessEvent(\'bridge-emitters/mod:' + i + ':level:\' + this.value)">'
            + '<input type="number" min="0" step="0.01" value="' + lv.toFixed(2) + '" style="width:56px"'
            + ' onchange="dauntlessEvent(\'bridge-emitters/mod:' + i + ':level:\' + this.value)"></div>';
    } else {
        fields = '<div class="be-row"><label>shape</label>'
            + _beChip('sine', 'mod:' + i + ':shape:sine', m.shape === 'sine', false)
            + _beChip('square', 'mod:' + i + ':shape:square', m.shape === 'square', false) + '</div>'
            + _beNumberRow('period s', 'mod:' + i + ':period_s', m.period_s, 0.05)
            + _beNumberRow('min', 'mod:' + i + ':min', m.min || 0, 0.05)
            + _beNumberRow('phase', 'mod:' + i + ':phase', m.phase || 0, 0.05);
        if (m.shape === 'square') {
            fields += _beNumberRow('duty', 'mod:' + i + ':duty', m.duty === undefined ? 0.5 : m.duty, 0.05)
                + _beNumberRow('soft', 'mod:' + i + ':soft', m.soft || 0, 0.05);
        }
    }
    const title = m.type === 'emitter' ? 'Emitter' : 'Animation (' + m.shape + ')';
    return _beEntry('mod:' + i, title, expanded,
                    {list: m.scope || [], action: 'mod:' + i + ':scope:'},
                    'mod-remove:' + i, fields);
}

function _beAddModifier() {
    return '<div class="be-row"><label>add</label>'
        + _beChip('Emitter', 'mod-add:emitter', false, false)
        + _beChip('Animation', 'mod-add:animation', false, false) + '</div>';
}

function _beMaterialTab(s) {
    const m = s.material_data;
    if (!m) {
        return '<div class="be-help">No material. New makes one for this object; adding a '
            + 'modifier makes one too.</div><div class="be-row">'
            + '<button onclick="dauntlessEvent(\'bridge-emitters/material-new\')">New</button></div>'
            + _beAddModifier();
    }
    const open = function (id) { return (s.expanded || []).indexOf(id) >= 0; };
    // Commits on `change` (Enter blurs via text_capture) and on the button.
    let html = '<div class="be-row"><input type="text" id="be-rename" value="' + _beEsc(m.name) + '"'
        + ' style="width:150px" onchange="dauntlessEvent(\'bridge-emitters/material-rename:\' + this.value)">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/material-rename:\' + '
        + 'document.getElementById(\'be-rename\').value)">Rename</button>'
        + '<span class="be-source">' + _beEsc((m.kind === 'texture' ? 'texture material · ' : '')
                                            + _beUsers(m.used_by || 0)) + '</span></div>';
    // Finish and Surface are fixed sections, open by default: toggling
    // their header collapses them (modifiers and lights start collapsed).
    html += _beEntry('finish', 'Finish', !open('finish'), null, null,
                     _beFinishRow('roughness', m.finish.roughness)
                     + _beFinishRow('metalness', m.finish.metalness));
    // Emission follows the roughness/metalness rule: the object's emission
    // map whenever it has one (shown, not chosen); `without map` is what
    // glows for objects that have none (spec §13, Mark 2026-10-11).
    const stem = String((s.textures || [''])[0]).replace(/\.[^.]*$/, '');
    const fallback = m.emission.without_map === 'flat' ? 'flat colour' : 'own texture';
    let emis = '<div class="be-row"><span class="be-source">source: '
        + (s.has_emission_map ? 'emission map · ' + _beEsc(stem) + '_emissive'
                              : _beEsc(fallback) + ' (no emission map)')
        + '</span></div><div class="be-row"><label>without a map</label>';
    _BE_WITHOUT_MAP.forEach(function (p) {
        emis += _beChip(p[1], 'emission:without_map:' + p[0], m.emission.without_map === p[0], false);
    });
    emis += '</div>' + _beNumberRow('strength', 'emission:strength', m.emission.strength, 0.1)
        + _beNumberRow('state fade s', 'fade', m.fade_s, 0.05);
    html += _beEntry('emission', 'Emission', !open('emission'), null, null, emis);
    (m.modifiers || []).forEach(function (mod, i) {
        html += _beModifier(mod, i, open('mod:' + i));
    });
    return html + _beAddModifier();
}

function _beDockHtml(state) {
    const s = state.selected;
    let html = '<div class="be-row"><label>Object</label><span>'
        + _beEsc(s.display_name || s.name) + '</span></div>'
        + '<div class="be-row"><label>Block</label><span>' + _beEsc(s.block) + '</span></div>'
        + '<div class="be-row"><label>Textures</label><span>'
        + _beEsc((s.textures || []).join(', ') || '—') + '</span></div>'
        + '<div class="be-chain">' + _beEsc((s.node_chain || []).join(' › ')) + '</div>'
        + '<div class="be-tabs">'
        + _beChip('Object', 'tab:object', s.tab === 'object', false)
        + _beChip('Material', 'tab:material', s.tab === 'material', false) + '</div>';
    return html + (s.tab === 'material' ? _beMaterialTab(s) : _beObjectTab(s));
}

// One wheel per expanded emitter. A drag commits once, on release (one undo
// step); the swatch follows live. A dragging wheel blocks rebuilds.
var _beWheels = [];
function _beMountWheels(state) {
    _beWheels = [];
    const s = state.selected;
    if (!s || !s.material_data || typeof ColourWheel === 'undefined') return;
    (s.material_data.modifiers || []).forEach(function (m, i) {
        const canvas = document.getElementById('be-wheel-' + i);
        if (!canvas || !canvas.getContext || m.type !== 'emitter') return;
        const swatch = document.getElementById('be-swatch-' + i);
        const paint = function (rgb) {
            if (swatch) swatch.style.background = 'rgb(' + rgb.map(function (c) {
                return Math.round(Math.max(0, Math.min(1, c)) * 255);
            }).join(',') + ')';
        };
        paint(m.tint);
        _beWheels.push(new ColourWheel(canvas, colourRgbToHs(m.tint), function (hs, final) {
            const rgb = colourHsToRgb(hs.hue, hs.sat);
            paint(rgb);
            if (final) dauntlessEvent('bridge-emitters/mod:' + i + ':tint:'
                + rgb.map(function (c) { return c.toFixed(4); }).join(','));
        }));
    });
}

// The dock is rebuilt from the payload -- but never while the user is typing
// in a field inside it (every hover change sends a payload, and a rebuild
// destroys the focused field mid-edit), nor while a colour wheel is dragging.
function _beEditingInDock(root) {
    if (_beWheels.some(function (w) { return w.dragging; })) return true;
    const a = document.activeElement;
    if (!a || !root.contains || !root.contains(a)) return false;
    if (a.tagName === 'TEXTAREA' || a.isContentEditable) return true;
    return a.tagName === 'INPUT' && a.type !== 'range' && a.type !== 'checkbox'
        && a.type !== 'button';
}

function setBridgeEmitters(state) {
    const root = document.getElementById('bridge-emitters-root');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        _beWheels = [];          // a hidden panel holds no drag
        return;
    }
    const bar = document.getElementById('be-bar');
    if (bar) bar.innerHTML = _beBar(state);
    const hint = document.getElementById('be-hint');
    if (hint) hint.textContent = state.in_bridge === false
        ? 'Close this, press Space to go to the bridge, then reopen Bridge Editor.'
        : (state.hint || '');
    const hover = document.getElementById('be-hover');
    if (hover) hover.textContent = state.hover || '';
    const status = document.getElementById('be-status');
    if (status) status.textContent = state.status || '';
    const dock = document.getElementById('be-dock');
    if (dock) dock.style.display = state.selected ? 'flex' : 'none';
    const body = document.getElementById('bridge-emitters-body');
    if (body && state.selected && !_beEditingInDock(root)) {
        body.innerHTML = _beDockHtml(state);
        _beMountWheels(state);
    }
    root.style.display = 'block';
}
